# -*- coding: utf-8 -*-
"""
🪶 LEGACY ENGINE — Sprint AV — Radimův odkaz

Když senior používá Radim, vznikají rozhovory plné jeho moudrosti, vzpomínek,
zásad a vtipů. Většina z toho se ztratí, když člověk odejde.

Tento engine **destiluje** z `memory_history` a `learning` 5 kategorií, které
Radim nabídne seniorovi k schválení a pak — až přijde čas — předá rodině.

Filozofie:
  1. Senior **vlastní svůj odkaz** — žádná destilace bez consent + review
  2. Citlivý kontext (smrt, strach) jen na výslovnou žádost
  3. Předání není automatické — má pravidla (na narozeniny / po inactivity)
  4. Odkaz je **pro rodinu**, ne pro Radim — Radim je jen kurátor

5 kategorií:
  🌟 životní_zásady — opakované výroky o životě/lásce/smrti
  📖 vzpomínky — z odpovědí na otázky o minulosti
  👨‍👩‍👧 postoje_k_blízkým — jak mluví o rodině
  🍲 praktická_moudrost — recepty, rady, zvyky
  💔 strach_a_naděje — citlivý — jen po opt-in
"""

import os
import json
import logging
import re
from datetime import datetime
from flask import Blueprint, request, jsonify, g

from auth_middleware import require_auth
from memory_helpers import (
    db_load_profile, db_save_profile, db_load_learning, db_load_history, audit_log
)
from ai_config import GEMINI_MODEL

logger = logging.getLogger(__name__)

legacy_bp = Blueprint('legacy', __name__, url_prefix='/api/legacy')


# ============================================================================
# CATEGORY DEFINITIONS
# ============================================================================

LEGACY_CATEGORIES = {
    'life_principles': {
        'icon': '🌟',
        'name': 'Životní zásady',
        'description': 'Co považujete za důležité v životě',
        'sensitive': False,
    },
    'memories': {
        'icon': '📖',
        'name': 'Vzpomínky',
        'description': 'Příběhy z mládí a dospělosti',
        'sensitive': False,
    },
    'family_attitudes': {
        'icon': '👨‍👩‍👧',
        'name': 'Postoje k blízkým',
        'description': 'Co cítíte k těm, koho máte rádi',
        'sensitive': False,
    },
    'practical_wisdom': {
        'icon': '🍲',
        'name': 'Praktická moudrost',
        'description': 'Recepty, návyky, rady',
        'sensitive': False,
    },
    'fears_and_hopes': {
        'icon': '💔',
        'name': 'Strach a naděje',
        'description': 'To nejhlubší — jen pokud chcete',
        'sensitive': True,  # opt-in only
    },
}


# ============================================================================
# DESTILATION via Gemini
# ============================================================================

DISTILL_PROMPT_TEMPLATE = """Jsi pomocník Radim, který kurátoruje odkaz seniora pro jeho rodinu.

Z následující historie rozhovorů vyber a destiluj **{category_name}**.
Co hledáme: {category_desc}

PRAVIDLA:
1. Cituj seniora jeho vlastními slovy, kde můžeš (uvedeno jako citace).
2. Nepřipisuj seniorovi věci, které neřekl. Když nevíš, raději vynech.
3. Jeden záznam = jedna ucelená myšlenka/vzpomínka/zásada.
4. Maximálně 7 záznamů. Vyber to nejhodnotnější.
5. Žádné technické komentáře, žádné "Senior říká...". Jen čistá obsahová sdělení.
6. Píš v jedinečném stylu seniora, jak ho znáš z konverzací.

VRAŤ JSON pole objektů, každý: {{"summary": "...", "quote": "...optional přesná citace...", "context_date": "YYYY-MM"}}.
Vrať POUZE JSON pole, žádný úvod, žádný komentář.

═══ HISTORIE KONVERZACÍ (posledních N zpráv) ═══
{history_text}
═══════════════════════════════════════════════
"""


def _format_history_for_distillation(history, limit=200):
    """Format DB history rows as flat text for LLM."""
    out = []
    for h in (history or [])[-limit:]:
        role = h.get('role') if hasattr(h, 'get') else 'unknown'
        content = h.get('content') if hasattr(h, 'get') else str(h)
        ts = h.get('timestamp') or h.get('created_at') or ''
        if role == 'user':
            out.append(f"[Senior, {str(ts)[:10]}]: {content}")
        elif role == 'assistant':
            # Skip assistant — we want senior's voice
            continue
    return '\n'.join(out)


def _call_gemini(prompt, api_key):
    """Minimal Gemini call. Returns text or None on failure."""
    if not api_key:
        return None
    try:
        import urllib.request
        from ai_config import gemini_url
        url = gemini_url(api_key)
        body = json.dumps({
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {
                'temperature': 0.4,
                'maxOutputTokens': 2000,
            }
        }).encode()
        req = urllib.request.Request(url, data=body, method='POST',
                                      headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        candidates = data.get('candidates') or []
        if not candidates:
            return None
        parts = (candidates[0].get('content') or {}).get('parts') or []
        if not parts:
            return None
        return parts[0].get('text', '').strip()
    except Exception as e:
        logger.warning(f"legacy distill Gemini call failed: {e}")
        return None


def _parse_distill_json(text):
    """Robust JSON extraction. Gemini may add fences or prose."""
    if not text:
        return []
    # Strip markdown code fences
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    # Find first JSON array
    m = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and d.get('summary')]
    except Exception as e:
        logger.warning(f"legacy distill JSON parse failed: {e}")
    return []


def distill_legacy(user_id, categories=None, history_limit=200):
    """Run distillation for one or more categories. Returns dict by category."""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        logger.warning("GEMINI_API_KEY missing — legacy distillation skipped")
        return {}

    history = db_load_history(user_id, limit=history_limit) or []
    if not history:
        return {}
    history_text = _format_history_for_distillation(history, limit=history_limit)
    if len(history_text) < 200:
        return {}

    cats = categories or list(LEGACY_CATEGORIES.keys())
    results = {}

    for cat_id in cats:
        cat = LEGACY_CATEGORIES.get(cat_id)
        if not cat:
            continue
        # Sensitive categories only on explicit opt-in (caller passes them)
        prompt = DISTILL_PROMPT_TEMPLATE.format(
            category_name=cat['name'],
            category_desc=cat['description'],
            history_text=history_text[:50000],  # cap at 50K chars to stay in context
        )
        raw = _call_gemini(prompt, api_key)
        entries = _parse_distill_json(raw)
        results[cat_id] = entries

    return results


# ============================================================================
# ROUTES
# ============================================================================

@legacy_bp.route('/preview/<user_id>', methods=['GET', 'OPTIONS'])
def legacy_preview(user_id):
    """View senior's legacy as it currently stands.

    Returns approved entries (visible in UI as "Můj odkaz").
    Sensitive category included only if `include_sensitive=true` query param.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        profile = db_load_profile(_uid) or {}
        legacy = profile.get('legacy') or {}
        approved = legacy.get('approved_entries') or {}
        recipients = legacy.get('recipients') or []

        include_sensitive = (request.args.get('include_sensitive', '') == 'true')

        # Compose by category (filter sensitive unless requested)
        by_cat = {}
        for cid, cdef in LEGACY_CATEGORIES.items():
            if cdef['sensitive'] and not include_sensitive:
                continue
            by_cat[cid] = {
                'icon': cdef['icon'],
                'name': cdef['name'],
                'description': cdef['description'],
                'sensitive': cdef['sensitive'],
                'entries': approved.get(cid) or [],
                'count': len(approved.get(cid) or []),
            }

        total = sum(c['count'] for c in by_cat.values())

        return jsonify({
            'success': True,
            'categories': by_cat,
            'total_entries': total,
            'recipients': recipients,
            'last_curated_at': legacy.get('last_curated_at'),
        })

    return _inner(user_id)


@legacy_bp.route('/curate/<user_id>', methods=['POST', 'OPTIONS'])
def legacy_curate(user_id):
    """Run distillation NOW. Senior reviews drafts in next GET /preview.

    Body: {"categories": ["life_principles", "memories", ...] (optional),
           "include_sensitive": false (default)}

    Stores results in profile.legacy.draft_entries — senior approves them
    via POST /entry/approve before they show in /preview.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        body = request.get_json(silent=True) or {}
        cats = body.get('categories')
        include_sensitive = bool(body.get('include_sensitive', False))

        if cats is None:
            # Default: non-sensitive categories
            cats = [c for c, d in LEGACY_CATEGORIES.items() if not d['sensitive']]
        else:
            # Validate
            cats = [c for c in cats if c in LEGACY_CATEGORIES]
            if not include_sensitive:
                cats = [c for c in cats if not LEGACY_CATEGORIES[c]['sensitive']]

        results = distill_legacy(_uid, categories=cats)

        # Store as drafts
        profile = db_load_profile(_uid) or {}
        legacy = profile.get('legacy') or {}
        drafts = legacy.get('draft_entries') or {}
        for cid, entries in results.items():
            drafts[cid] = entries
        legacy['draft_entries'] = drafts
        legacy['last_curated_at'] = datetime.utcnow().isoformat()
        legacy['model'] = GEMINI_MODEL
        profile['legacy'] = legacy
        profile['updated_at'] = datetime.utcnow().isoformat()
        db_save_profile(_uid, profile)

        try:
            audit_log(_uid, 'legacy_curate', ','.join(cats),
                      f"entries={sum(len(e) for e in results.values())}",
                      request.remote_addr)
        except Exception:
            pass

        logger.info(f"🪶 legacy curated for user={_uid}: "
                    f"{sum(len(e) for e in results.values())} draft entries")

        return jsonify({
            'success': True,
            'drafts': results,
            'total': sum(len(e) for e in results.values()),
            'model': GEMINI_MODEL,
            'message': f"Připraveno k vašemu schválení: " +
                       f"{sum(len(e) for e in results.values())} záznamů",
        })

    return _inner(user_id)


@legacy_bp.route('/entry/<user_id>', methods=['POST', 'OPTIONS'])
def legacy_entry(user_id):
    """Senior adds/approves/rejects a single entry.

    Body forms:
      Approve draft: {"action": "approve", "category": "memories", "draft_index": 0}
      Reject draft:  {"action": "reject", "category": "memories", "draft_index": 0}
      Add custom:    {"action": "add", "category": "memories",
                       "summary": "...", "quote": "...optional"}
      Delete approved: {"action": "delete", "category": "memories", "approved_index": 2}
      Edit approved: {"action": "edit", "category": "memories", "approved_index": 2,
                       "summary": "..."}
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        body = request.get_json(silent=True) or {}
        action = body.get('action')
        category = body.get('category')
        if category not in LEGACY_CATEGORIES:
            return jsonify({'success': False, 'error': 'Neznámá kategorie'}), 400

        profile = db_load_profile(_uid) or {}
        legacy = profile.get('legacy') or {}
        drafts = legacy.get('draft_entries') or {}
        approved = legacy.get('approved_entries') or {}
        approved.setdefault(category, [])
        drafts.setdefault(category, [])

        if action == 'approve':
            idx = int(body.get('draft_index', -1))
            if 0 <= idx < len(drafts[category]):
                entry = drafts[category].pop(idx)
                entry['approved_at'] = datetime.utcnow().isoformat()
                approved[category].append(entry)
            else:
                return jsonify({'success': False, 'error': 'Index mimo rozsah'}), 400

        elif action == 'reject':
            idx = int(body.get('draft_index', -1))
            if 0 <= idx < len(drafts[category]):
                drafts[category].pop(idx)
            else:
                return jsonify({'success': False, 'error': 'Index mimo rozsah'}), 400

        elif action == 'add':
            summary = (body.get('summary') or '').strip()
            if not summary:
                return jsonify({'success': False, 'error': 'summary required'}), 400
            entry = {
                'summary': summary[:1000],
                'quote': (body.get('quote') or '').strip()[:500] or None,
                'approved_at': datetime.utcnow().isoformat(),
                'source': 'manual',
            }
            approved[category].append(entry)

        elif action == 'delete':
            idx = int(body.get('approved_index', -1))
            if 0 <= idx < len(approved[category]):
                approved[category].pop(idx)
            else:
                return jsonify({'success': False, 'error': 'Index mimo rozsah'}), 400

        elif action == 'edit':
            idx = int(body.get('approved_index', -1))
            if 0 <= idx < len(approved[category]):
                approved[category][idx]['summary'] = (body.get('summary') or '')[:1000]
                approved[category][idx]['edited_at'] = datetime.utcnow().isoformat()
            else:
                return jsonify({'success': False, 'error': 'Index mimo rozsah'}), 400

        else:
            return jsonify({'success': False, 'error': 'Unknown action'}), 400

        legacy['draft_entries'] = drafts
        legacy['approved_entries'] = approved
        profile['legacy'] = legacy
        profile['updated_at'] = datetime.utcnow().isoformat()
        db_save_profile(_uid, profile)

        try:
            audit_log(_uid, f'legacy_entry_{action}', category, '', request.remote_addr)
        except Exception:
            pass

        return jsonify({
            'success': True,
            'category': category,
            'approved_count': len(approved[category]),
            'draft_count': len(drafts[category]),
        })

    return _inner(user_id)


@legacy_bp.route('/recipient/<user_id>', methods=['POST', 'OPTIONS'])
def legacy_recipient(user_id):
    """Set or update legacy recipient(s).

    Body: {"recipients": [
      {"family_link_id": 12, "deliver_when": "inactivity_30d" | "manual" | "birthday"}
    ]}
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        body = request.get_json(silent=True) or {}
        recipients = body.get('recipients') or []

        # Sanitize
        clean = []
        for r in recipients:
            if not isinstance(r, dict): continue
            link_id = r.get('family_link_id')
            when = r.get('deliver_when', 'inactivity_30d')
            if when not in ('inactivity_30d', 'inactivity_60d', 'inactivity_90d',
                            'manual', 'birthday'):
                when = 'inactivity_30d'
            clean.append({
                'family_link_id': link_id,
                'deliver_when': when,
                'set_at': datetime.utcnow().isoformat(),
                'delivered_at': None,
            })

        profile = db_load_profile(_uid) or {}
        legacy = profile.get('legacy') or {}
        legacy['recipients'] = clean
        profile['legacy'] = legacy
        profile['updated_at'] = datetime.utcnow().isoformat()
        db_save_profile(_uid, profile)

        return jsonify({
            'success': True,
            'recipients': clean,
        })

    return _inner(user_id)


@legacy_bp.route('/deliver/<user_id>', methods=['POST', 'OPTIONS'])
def legacy_deliver(user_id):
    """Manual trigger: send legacy NOW to all configured recipients.

    Used for testing or for senior who wants to share legacy while alive
    (e.g. on birthday, anniversary).
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        profile = db_load_profile(_uid) or {}
        legacy = profile.get('legacy') or {}
        recipients = legacy.get('recipients') or []
        if not recipients:
            return jsonify({'success': False, 'error': 'Žádní příjemci'}), 400

        from legacy_delivery import deliver_legacy_to_recipients
        result = deliver_legacy_to_recipients(_uid, profile, recipients,
                                              trigger='manual')

        # Mark delivered
        for r in recipients:
            r['delivered_at'] = datetime.utcnow().isoformat()
            r['delivery_method'] = result.get('method', 'unknown')
        legacy['recipients'] = recipients
        profile['legacy'] = legacy
        db_save_profile(_uid, profile)

        return jsonify({
            'success': True,
            'delivered_to': len(recipients),
            'result': result,
        })

    return _inner(user_id)
