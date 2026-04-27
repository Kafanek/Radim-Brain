# -*- coding: utf-8 -*-
"""
🧠 RADIM MEMORY ROUTES v2.2.0
API endpoints for memory system.
Business logic in memory_logic.py, DB helpers in memory_helpers.py, GDPR in gdpr_routes.py.
"""

import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth, optional_auth

from memory_helpers import (
    db_available, db_load_profile, db_save_profile, db_delete_profile,
    db_load_history, db_add_history, db_clear_history,
    db_load_learning, db_save_learning, default_learning,
    get_gdpr_consent, save_gdpr_consent, audit_log,
    get_communication_instructions, detect_topic, detect_mood
)

# Business logic (re-export for backward compat)
from memory_logic import (
    get_user_context, build_personalized_prompt,
    get_personalized_system_prompt, get_conversation_messages,
    record_interaction, _update_learning_stats, _crisis_escalate
)

logger = logging.getLogger(__name__)

# Flask Blueprint
memory_bp = Blueprint('memory', __name__, url_prefix='/api/memory')

# DB availability check
try:
    from database import is_postgres, db_context
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


# ============================================================================
# ROUTES
# ============================================================================

@memory_bp.route('/health', methods=['GET'])
def health_check():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "service": "RADIM Memory & Learning",
        "version": "2.2.0",
        "persistence": "postgresql" if (_DB_AVAILABLE and is_postgres()) else "sqlite" if _DB_AVAILABLE else "none",
        "db_available": _DB_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat()
    })


# ─────────────────────────────────────────────────────────────────────────────
# USER PROFILE
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/profile/<user_id>', methods=['GET'])
@require_auth
def get_profile(user_id):
    """Získat profil uživatele"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    profile = db_load_profile(user_id)
    learning = db_load_learning(user_id)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "profile": profile,
        "learning": {
            "interaction_count": learning.get("interaction_count", 0),
            "top_topics": dict(sorted(learning.get("topics", {}).items(), key=lambda x: x[1], reverse=True)[:5]),
            "preferred_length": learning.get("preferred_length", "medium"),
            "communication_style": learning.get("communication_style", "warm"),
            "last_mood": learning.get("last_mood", "neutral")
        },
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/profile/<user_id>', methods=['POST', 'PUT'])
@require_auth
def save_profile(user_id):
    """Uložit/aktualizovat profil uživatele"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    data = request.get_json() or {}

    allowed_fields = ["name", "age_group", "hearing", "vision", "memory_support",
                      "communication_style", "preferred_length", "character", "tone",
                      "communication_needs", "mobility",
                      "medications", "medications_list", "medication_times",
                      "emergency_contacts", "daily_routine_notes", "baseline_C",
                      "onboarding_completed", "phone",
                      # Sprint AQ: settings module preferences
                      "quiet_hours",       # {"start": "22:00", "end": "07:00"}
                      "voice_pref",        # {"rate_modifier": -0.2..+0.2}
                      "appearance",        # {"theme", "fontSize", "colorScheme"}
                      "privacy",           # {"saveHistory", "analytics", "shareData"}
                      "simplified_ui",     # bool
                      ]

    profile = db_load_profile(user_id)

    for field in allowed_fields:
        if field in data:
            profile[field] = data[field]

    profile["updated_at"] = datetime.utcnow().isoformat()
    db_save_profile(user_id, profile)

    if "communication_style" in data or "preferred_length" in data:
        learning = db_load_learning(user_id)
        if "communication_style" in data:
            learning["communication_style"] = data["communication_style"]
        if "preferred_length" in data:
            learning["preferred_length"] = data["preferred_length"]
        db_save_learning(user_id, learning)

    logger.info(f"Profile saved for user: {user_id}")

    return jsonify({
        "success": True,
        "user_id": user_id,
        "profile": profile,
        "message": "Profil uložen",
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/profile/<user_id>', methods=['DELETE'])
@require_auth
def delete_profile(user_id):
    """Smazat profil uživatele (GDPR)"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    db_delete_profile(user_id)
    audit_log(user_id, "data_delete", "all_user_data", "GDPR profile deletion", request.remote_addr)

    logger.info(f"Profile deleted for user: {user_id}")

    return jsonify({
        "success": True,
        "message": "Všechna data smazána",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# SPRINT AP: TRANSPARENCY — "Co Radim ví" + selective forget + senior whispers
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/profile/<user_id>/summary', methods=['GET', 'OPTIONS'])
def profile_summary(user_id):
    """Friendly 'what Radim knows about me' view for the senior.

    Combines profile + learning + family + meds into a single readable
    structure for the Settings → 'Co Radim ví' transparency section.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({"success": False, "error": "Přístup odepřen"}), 403

        profile = db_load_profile(_uid) or {}
        learning = db_load_learning(_uid) or {}

        # Pull family from senior_family_links if present.
        # Schema: family_name (not name), confirmed_at (not status — confirmed
        # if confirmed_at IS NOT NULL AND revoked_at IS NULL).
        family = []
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT family_name, relation FROM senior_family_links "
                    "WHERE senior_id = ? AND confirmed_at IS NOT NULL "
                    "AND revoked_at IS NULL",
                    (_uid,)
                ).fetchall()
                for r in (rows or []):
                    if hasattr(r, 'get'):
                        family.append({
                            'name': r.get('family_name'),
                            'relation': r.get('relation'),
                        })
                    else:
                        family.append({'name': r[0], 'relation': r[1]})
        except Exception as e:
            logger.debug(f"family fetch (non-fatal): {e}")

        # Top topics + sensitive context
        sensitive = []
        for k in ('grief_context', 'recent_loss', 'recent_crisis'):
            if learning.get(k):
                sensitive.append({'key': k, 'value': learning[k]})

        whisper_count = len(learning.get('caregiver_whispers') or [])

        return jsonify({
            'success': True,
            'user_id': _uid,
            'identity': {
                'name': profile.get('name'),
                'phone': profile.get('phone'),
                'preferred_length': profile.get('preferred_length') or learning.get('preferred_length'),
                'communication_style': profile.get('communication_style') or learning.get('communication_style'),
                'tone': profile.get('tone'),
            },
            'health': {
                'medications': profile.get('medications_list') or profile.get('medications') or [],
                'medication_times': profile.get('medication_times') or {},
                'mobility': profile.get('mobility'),
                'hearing': profile.get('hearing'),
                'vision': profile.get('vision'),
                'memory_support': profile.get('memory_support'),
            },
            'family': family,
            'emergency_contacts': profile.get('emergency_contacts') or [],
            'interests': {
                'top_topics': dict(sorted(
                    (learning.get('topics') or {}).items(),
                    key=lambda x: x[1], reverse=True
                )[:10]),
                'last_mood': learning.get('last_mood'),
                'interaction_count': learning.get('interaction_count', 0),
            },
            'sensitive': sensitive,  # things tagged grief/loss/crisis
            'whisper_count': whisper_count,
            'updated_at': profile.get('updated_at'),
        })

    return _inner(user_id)


@memory_bp.route('/profile/<user_id>/forget', methods=['POST', 'OPTIONS'])
def profile_forget(user_id):
    """Selective memory wipe — senior asks Radim to forget specific things.

    Body: {"keys": ["grief_context", "topics", "medications_list"]}

    Different from DELETE /profile (full GDPR wipe). Allows e.g. a widow
    to say "forget the grief context, I'm moving on" without losing her
    medication list and family contacts.

    Allowed keys (whitelist):
      profile:    medications_list, medication_times, emergency_contacts,
                  daily_routine_notes, baseline_C, mobility, hearing, vision
      learning:   grief_context, recent_loss, recent_crisis, topics,
                  last_mood, caregiver_whispers, C_history
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({"success": False, "error": "Přístup odepřen"}), 403

        body = request.get_json(silent=True) or {}
        keys = body.get('keys') or []
        if not isinstance(keys, list) or not keys:
            return jsonify({'success': False, 'error': 'keys array required'}), 400

        PROFILE_FORGETTABLE = {
            'medications_list', 'medications', 'medication_times',
            'emergency_contacts', 'daily_routine_notes', 'baseline_C',
            'mobility', 'hearing', 'vision', 'memory_support',
            'phone', 'character', 'tone',
        }
        LEARNING_FORGETTABLE = {
            'grief_context', 'recent_loss', 'recent_crisis', 'topics',
            'last_mood', 'caregiver_whispers', 'C_history',
            'preferred_length', 'communication_style',
        }

        profile = db_load_profile(_uid) or {}
        learning = db_load_learning(_uid) or {}
        forgot = []
        rejected = []

        for k in keys:
            if k in PROFILE_FORGETTABLE and k in profile:
                profile.pop(k, None)
                forgot.append(k)
            elif k in LEARNING_FORGETTABLE and k in learning:
                learning.pop(k, None)
                forgot.append(k)
            else:
                rejected.append(k)

        if forgot:
            profile['updated_at'] = datetime.utcnow().isoformat()
            db_save_profile(_uid, profile)
            db_save_learning(_uid, learning)
            audit_log(_uid, 'memory_forget', 'selective',
                      f"forgot {forgot} via senior request",
                      request.remote_addr)

        # Bus emit so chat-time prompt builder doesn't reuse stale context
        try:
            from agent_bus import emit as _bus_emit
            _bus_emit(
                user_id=_uid,
                sender='memory_routes.profile_forget',
                kind='context',
                severity='info',
                topic='memory_forgotten',
                payload={'keys': forgot},
                ttl_minutes=60,
            )
        except Exception:
            pass

        return jsonify({
            'success': True,
            'forgot': forgot,
            'rejected': rejected,
            'message': f"Zapomenuto: {', '.join(forgot)}" if forgot else "Nic k zapomenutí.",
        })

    return _inner(user_id)


@memory_bp.route('/profile/<user_id>/recent-trace', methods=['GET', 'OPTIONS'])
def profile_recent_trace(user_id):
    """Sprint AQ: 'Co Radim viděl, když mi odpovídal' — kontextová stopa.

    Returns last N chat exchanges WITH the prompt fragments that fed
    Radim's response: bus events, neuron summary, whispers, brain mode.
    Helps caregivers + senior understand WHY Radim said what he said.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({"success": False, "error": "Přístup odepřen"}), 403

        n = int(request.args.get('n', 5))
        n = max(1, min(20, n))

        # Recent chat history
        history = []
        try:
            history = db_load_history(_uid, limit=n) or []
        except Exception:
            pass

        # Recent bus events (context Radim saw)
        bus_events = []
        try:
            from agent_bus import recent as _bus_recent
            bus_events = _bus_recent(user_id=_uid, limit=15) or []
        except Exception:
            pass

        # Last brain state
        brain = None
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT mode, c, alpha, coherence, created_at FROM brain_states "
                    "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                    (_uid,)
                ).fetchone()
                if row:
                    if hasattr(row, 'get'):
                        brain = {
                            'mode': row.get('mode'),
                            'C': float(row.get('c') or 0),
                            'alpha': float(row.get('alpha') or 0),
                            'coherence': float(row.get('coherence') or 0),
                            'at': str(row.get('created_at') or ''),
                        }
                    else:
                        brain = {'mode': row[0], 'C': float(row[1] or 0),
                                 'alpha': float(row[2] or 0),
                                 'coherence': float(row[3] or 0),
                                 'at': str(row[4] or '')}
        except Exception as e:
            logger.debug(f"brain trace fetch (non-fatal): {e}")

        # Whispers Radim could weave
        whispers_active = []
        try:
            learning = db_load_learning(_uid) or {}
            whispers = learning.get('caregiver_whispers', []) or []
            now_iso = datetime.utcnow().isoformat()
            whispers_active = [{
                'text': w.get('text'),
                'priority': w.get('priority'),
                'consumed': bool(w.get('consumed_at')),
            } for w in whispers
                if w.get('expires_at', '') > now_iso][-5:]
        except Exception:
            pass

        # Format trace
        trace = []
        for h in history[-n:]:
            trace.append({
                'role': h.get('role') if hasattr(h, 'get') else 'unknown',
                'content': (h.get('content') if hasattr(h, 'get') else str(h))[:400],
                'created_at': h.get('created_at') if hasattr(h, 'get') else None,
                'brain_C': h.get('brain_C') if hasattr(h, 'get') else None,
                'brain_mode': h.get('brain_mode') if hasattr(h, 'get') else None,
            })

        return jsonify({
            'success': True,
            'trace': trace,
            'brain_now': brain,
            'bus_recent': bus_events[:10],
            'whispers_active': whispers_active,
            'count': len(trace),
        })

    return _inner(user_id)


@memory_bp.route('/whispers/mine', methods=['GET', 'OPTIONS'])
def my_whispers():
    """Senior-side whisper inbox.

    Returns the list of whispers caregivers left for Radim about THIS
    senior — both pending (not yet woven) and recently woven. Gives the
    senior transparency: 'what is my family asking Radim to nudge me about?'

    The senior sees but cannot reply through Radim — that's the design.
    They can answer the caregiver via a separate chat channel if needed.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner():
        auth_user_id = str(g.auth_user.get('id', ''))
        if not auth_user_id:
            return jsonify({'success': False, 'error': 'Auth required'}), 401

        try:
            learning = db_load_learning(auth_user_id) or {}
            whispers = learning.get('caregiver_whispers', [])
            now_iso = datetime.utcnow().isoformat()

            # Resolve caregiver names for friendly display.
            # IDs come from `from` field which is set in caregiver_whisper as
            # str(caller.user_id) — auth_users.id (int) for direct registrations
            # or wp_<id> for WordPress JWT users. Try both tables.
            cg_ids = list({w.get('from') for w in whispers if w.get('from')})
            cg_names = {}
            if cg_ids:
                try:
                    with db_context() as db:
                        # auth_users — direct register path (most pilot users)
                        for cid in cg_ids:
                            try:
                                cid_int = int(cid)
                                row = db.execute(
                                    "SELECT name FROM auth_users WHERE id = ?",
                                    (cid_int,)
                                ).fetchone()
                                if row:
                                    nm = row.get('name') if hasattr(row, 'get') else row[0]
                                    if nm:
                                        cg_names[str(cid)] = nm
                            except (ValueError, TypeError):
                                pass
                        # chat_users — WordPress JWT path (legacy)
                        missing = [c for c in cg_ids if str(c) not in cg_names]
                        if missing:
                            placeholders = ','.join(['?'] * len(missing))
                            rows = db.execute(
                                f"SELECT id, name FROM chat_users WHERE id IN ({placeholders})",
                                tuple(missing)
                            ).fetchall()
                            for r in (rows or []):
                                rid = r.get('id') if hasattr(r, 'get') else r[0]
                                rnm = r.get('name') if hasattr(r, 'get') else r[1]
                                if rnm:
                                    cg_names[str(rid)] = rnm
                except Exception as _ce:
                    logger.debug(f"caregiver name resolve (non-fatal): {_ce}")

            def _enrich(w):
                from_id = str(w.get('from', ''))
                return {
                    'id': w.get('id'),
                    'text': w.get('text'),
                    'priority': w.get('priority', 'normal'),
                    'from_name': cg_names.get(from_id, 'Někdo z rodiny'),
                    'created_at': w.get('created_at'),
                    'consumed_at': w.get('consumed_at'),
                    'expires_at': w.get('expires_at'),
                    'status': ('delivered' if w.get('consumed_at')
                               else ('expired' if w.get('expires_at', '') < now_iso
                                     else 'pending')),
                }

            pending = [_enrich(w) for w in whispers
                       if not w.get('consumed_at')
                       and w.get('expires_at', '') > now_iso]
            delivered = [_enrich(w) for w in whispers if w.get('consumed_at')][-10:]

            return jsonify({
                'success': True,
                'pending': pending,
                'delivered': delivered,
                'total': len(whispers),
            })
        except Exception as e:
            logger.warning(f"my_whispers error: {e}")
            return jsonify({'success': False, 'error': str(e)[:120]}), 500

    return _inner()


@memory_bp.route('/profile/<user_id>/system-status', methods=['GET', 'OPTIONS'])
def profile_system_status(user_id):
    """Sprint AQ: 'Stav systému' — friendly health snapshot pro seniora.

    Mini-verze admin-health, ale auth-self-only a v lidštině:
    ✅ Hlas, ✅ Připojení, ✅ Rodina, ⚠️ Push.
    Nedělá detailní DB diagnostiku, jen co senior chce vědět.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({"success": False, "error": "Přístup odepřen"}), 403

        checks = []

        # 1. TTS health (Azure quota / circuit)
        try:
            from tts_proxy_routes import _AZURE_TTS_QUOTA
            quota = _AZURE_TTS_QUOTA or {}
            checks.append({
                'id': 'voice',
                'label': 'Hlas Radima',
                'ok': True,  # we'd flag false if circuit open
                'detail': f"Připraveno (Antonín cs-CZ)",
            })
        except Exception:
            checks.append({'id': 'voice', 'label': 'Hlas Radima', 'ok': True,
                          'detail': 'Připraveno'})

        # 2. Backend connection (DB) — we're already serving, so OK
        checks.append({
            'id': 'backend', 'label': 'Připojení k Radimovi', 'ok': True,
            'detail': 'Online'
        })

        # 3. Family connection
        family_count = 0
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT COUNT(*) AS n FROM senior_family_links "
                    "WHERE senior_id = ? AND confirmed_at IS NOT NULL "
                    "AND revoked_at IS NULL",
                    (_uid,)
                ).fetchone()
                family_count = int((rows.get('n') if hasattr(rows, 'get') else rows[0]) or 0)
        except Exception:
            pass
        checks.append({
            'id': 'family',
            'label': 'Rodina propojená',
            'ok': family_count > 0,
            'detail': (f"{family_count} {'člen' if family_count == 1 else 'členů'}"
                       if family_count else 'Žádný kontakt — pozvěte rodinu v sekci 👨‍👩‍👧'),
            'action': None if family_count else {'section': 'family', 'label': 'Pozvat'},
        })

        # 4. Push subscription
        push_ok = False
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id = ?",
                    (_uid,)
                ).fetchone()
                push_ok = int((row.get('n') if hasattr(row, 'get') else row[0]) or 0) > 0
        except Exception:
            pass
        checks.append({
            'id': 'push',
            'label': 'Push oznámení',
            'ok': push_ok,
            'detail': ('Zapnuto — rodina vás dostane'
                       if push_ok else 'Vypnuto — rodina vás nezavolá přes oznámení'),
            'action': None if push_ok else {'section': 'notifications', 'label': 'Zapnout'},
        })

        # 5. Brain pipeline (was there a recent state?)
        brain_recent = False
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT created_at FROM brain_states WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (_uid,)
                ).fetchone()
                brain_recent = bool(row)
        except Exception:
            pass
        checks.append({
            'id': 'brain',
            'label': 'Mozek Radima (Ψ)',
            'ok': brain_recent,
            'detail': ('Sleduje váš rytmus' if brain_recent else
                       'Zatím vás nezná — popovídejte si v chatu'),
        })

        all_ok = all(c['ok'] for c in checks)
        return jsonify({
            'success': True,
            'all_ok': all_ok,
            'checks': checks,
            'message': ('Vše v pořádku 💚' if all_ok else
                       'Pár věcí potřebuje vaši pozornost'),
        })

    return _inner(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION HISTORY
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/history/<user_id>', methods=['GET'])
@require_auth
def get_history(user_id):
    """Získat historii konverzací"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    limit = request.args.get('limit', 20, type=int)
    history = db_load_history(user_id, limit=limit)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "messages": history,
        "total_count": len(history),
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/history/<user_id>', methods=['POST'])
@require_auth
def add_to_history(user_id):
    """Přidat zprávu do historie"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    data = request.get_json() or {}

    role = data.get("role", "user")
    content = data.get("content", "")

    if not content:
        return jsonify({"success": False, "error": "Empty message"}), 400

    db_add_history(user_id, role, content)

    if role == "user":
        learning = db_load_learning(user_id)
        topic = detect_topic(content)
        mood = detect_mood(content)

        topics = learning.get("topics", {})
        topics[topic] = topics.get(topic, 0) + 1
        learning["topics"] = topics
        learning["last_mood"] = mood
        learning["interaction_count"] = learning.get("interaction_count", 0) + 1
        learning["last_interaction"] = datetime.utcnow().isoformat()
        db_save_learning(user_id, learning)

    return jsonify({
        "success": True,
        "message_added": {"role": role, "content": content, "timestamp": datetime.utcnow().isoformat()},
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/history/<user_id>', methods=['DELETE'])
@require_auth
def clear_history(user_id):
    """Vymazat historii konverzací"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    db_clear_history(user_id)

    return jsonify({
        "success": True,
        "message": "Historie vymazána",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT FOR CLAUDE
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/context/<user_id>', methods=['GET'])
@require_auth
def get_context(user_id):
    """Získat kontext pro Claude API volání"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    context = get_user_context(user_id)
    personalized_prompt = build_personalized_prompt(user_id)

    history = db_load_history(user_id, limit=10)
    claude_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    return jsonify({
        "success": True,
        "user_id": user_id,
        "context": context,
        "personalized_prompt_addition": personalized_prompt,
        "conversation_messages": claude_messages,
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# FEEDBACK & LEARNING
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/feedback/<user_id>', methods=['POST'])
@optional_auth
def submit_feedback(user_id):
    """Feedback with brain RL integration"""
    data = request.get_json() or {}

    feedback_type = data.get("type", "neutral")
    comment = data.get("comment", "")

    learning = db_load_learning(user_id)

    if feedback_type == "positive":
        learning["successful_interactions"] = learning.get("successful_interactions", 0) + 1
    elif feedback_type == "negative":
        learning["negative_feedback_count"] = learning.get("negative_feedback_count", 0) + 1
        if "příliš dlouhé" in comment.lower():
            learning["preferred_length"] = "short"
        elif "příliš krátké" in comment.lower():
            learning["preferred_length"] = "long"

    db_save_learning(user_id, learning)

    # Brain RL integration
    rl_result = None
    try:
        from radim_brain_routes import reinforcement_update as _rl_update
        if feedback_type in ("positive", "negative"):
            rl_result = _rl_update(
                success=(feedback_type == "positive"),
                user_id=user_id,
                signal_type="chat_feedback"
            )
    except Exception as rl_err:
        logger.debug(f"v284 RL feedback non-fatal: {rl_err}")

    logger.info(f"Feedback from {user_id}: {feedback_type} (RL: {rl_result is not None})")

    return jsonify({
        "success": True,
        "message": "Děkuji za zpětnou vazbu!",
        "rl_update": rl_result,
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# CAREGIVER & CRISIS
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/caregiver/<user_id>', methods=['POST'])
@optional_auth
def set_caregiver(user_id):
    """Set caregiver for crisis notifications"""
    data = request.get_json() or {}
    caregiver_id = data.get("caregiver_id")

    if not caregiver_id:
        return jsonify({"success": False, "error": "caregiver_id is required"}), 400

    profile = db_load_profile(user_id)
    profile["caregiver_id"] = caregiver_id
    db_save_profile(user_id, profile)

    logger.info(f"🛡️ [v284] Caregiver set: {user_id} → {caregiver_id}")

    return jsonify({
        "success": True,
        "message": f"Pečovatel {caregiver_id} nastaven pro {user_id}",
        "timestamp": datetime.utcnow().isoformat()
    })


@memory_bp.route('/crisis-history/<user_id>', methods=['GET'])
@optional_auth
def get_crisis_history(user_id):
    """Crisis event history"""
    if not _DB_AVAILABLE:
        return jsonify({"success": True, "events": []})

    events = []
    try:
        with db_context() as db:
            cursor = db.execute(
                "SELECT * FROM crisis_events WHERE user_id = ? ORDER BY created_at DESC LIMIT 20", (user_id,)
            )
            for row in (cursor.fetchall() if cursor else []):
                events.append({
                    "user_id": row[1] if isinstance(row, (list, tuple)) else row.get("user_id", user_id),
                    "brain_c": row[3] if isinstance(row, (list, tuple)) else row.get("brain_c"),
                    "message_excerpt": row[4] if isinstance(row, (list, tuple)) else row.get("message_excerpt", ""),
                    "created_at": row[5] if isinstance(row, (list, tuple)) else row.get("created_at", "")
                })
    except Exception as e:
        logger.debug(f"Crisis history fetch non-fatal: {e}")

    return jsonify({"success": True, "events": events})


# ─────────────────────────────────────────────────────────────────────────────
# BACKWARD COMPATIBILITY — re-export helpers with old names
# ─────────────────────────────────────────────────────────────────────────────
_db_load_profile = db_load_profile
_db_save_profile = db_save_profile
_db_delete_profile = db_delete_profile
_db_load_history = db_load_history
_db_add_history = db_add_history
_db_clear_history = db_clear_history
_db_load_learning = db_load_learning
_db_save_learning = db_save_learning
_default_learning = default_learning
_get_communication_instructions = get_communication_instructions

# Export
__all__ = [
    'memory_bp',
    'get_personalized_system_prompt',
    'get_conversation_messages',
    'record_interaction',
    'get_user_context',
    'build_personalized_prompt',
    '_db_load_profile', '_db_save_profile', '_db_delete_profile',
    '_db_load_history', '_db_add_history', '_db_clear_history',
    '_db_load_learning', '_db_save_learning', '_default_learning',
    'get_gdpr_consent', 'audit_log', 'detect_mood', 'detect_topic',
]
