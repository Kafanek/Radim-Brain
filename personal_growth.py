"""
🌱 PERSONAL GROWTH ENGINE v1.0
=================================
Radim learns and grows with each senior individually.

5 subsystems:
    1. Communication Profile — adapts language complexity, tempo, vocabulary
    2. Conversation Memory — remembers past topics, follows up across sessions
    3. Emotional Patterns — predicts mood by day/hour from history
    4. Relationship Growth — trust builds over time, unlocks capabilities
    5. Learning Progress — tracks quiz/education performance, adapts difficulty

Design principle:
    Radim is not a tool that reacts.
    Radim is a companion that grows WITH the senior.
"""

import json
import logging
import math
import re
from datetime import datetime, timedelta
from collections import Counter

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning, db_load_profile
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

PHI = 1.618034


# ═══════════════════════════════════════════════════════════════════
# 1. COMMUNICATION PROFILE — how Radim talks to THIS person
# ═══════════════════════════════════════════════════════════════════

def analyze_communication_style(user_id):
    """Learn how THIS senior communicates and adapt Radim's style.

    Analyzes:
        - Average message length (short → simple responses)
        - Vocabulary complexity (simple words → simple responses)
        - Response speed preference (fast chatter vs slow thinker)
        - Preferred topics
        - Words senior uses repeatedly (mirror them)
        - Formality level

    Returns communication profile for system prompt injection.
    """
    if not _AVAILABLE:
        return _default_comm_profile()

    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT content, created_at FROM memory_history "
                    "WHERE user_id = ? AND role = 'user' "
                    "AND created_at > NOW() - INTERVAL '30 days' "
                    "ORDER BY created_at DESC LIMIT 100",
                    (user_id,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT content, created_at FROM memory_history "
                    "WHERE user_id = ? AND role = 'user' "
                    "AND created_at > datetime('now', '-30 days') "
                    "ORDER BY created_at DESC LIMIT 100",
                    (user_id,)
                ).fetchall()

            if not rows or len(rows) < 5:
                return _default_comm_profile()

            messages = []
            timestamps = []
            for r in rows:
                text = r[0] if isinstance(r, (list, tuple)) else r.get('content', '')
                ts = r[1] if isinstance(r, (list, tuple)) else r.get('created_at')
                if text:
                    messages.append(str(text))
                    timestamps.append(ts)

            if len(messages) < 5:
                return _default_comm_profile()

            # Average message length
            avg_length = sum(len(m) for m in messages) / len(messages)

            # Word frequency — find senior's vocabulary
            all_words = []
            for m in messages:
                words = re.findall(r'[a-záčďéěíňóřšťúůýž]+', m.lower())
                all_words.extend(words)

            word_freq = Counter(all_words)
            common_words = word_freq.most_common(20)
            vocabulary_size = len(set(all_words))

            # Complexity: avg word length
            avg_word_len = sum(len(w) for w in all_words) / max(len(all_words), 1)

            # Preferred greeting detection
            greetings = [m for m in messages if any(g in m.lower() for g in ['ahoj', 'dobrý den', 'čau', 'nazdar', 'zdravím'])]
            preferred_greeting = 'ahoj' if any('ahoj' in g.lower() for g in greetings) else 'dobrý den'

            # Formality: ty vs vy
            ty_count = sum(1 for m in messages if any(w in m.lower() for w in [' ty ', 'tys ', 'tvůj', 'tvoje', 'tvoji']))
            vy_count = sum(1 for m in messages if any(w in m.lower() for w in [' vy ', 'váš', 'vaše', 'vaši', 'vám']))
            formality = 'formal' if vy_count > ty_count else 'informal'

            # Chattiness: messages per day
            if timestamps and len(timestamps) >= 2:
                try:
                    first = timestamps[-1]
                    last = timestamps[0]
                    if isinstance(first, str):
                        first = datetime.fromisoformat(first.replace('Z', ''))
                    if isinstance(last, str):
                        last = datetime.fromisoformat(last.replace('Z', ''))
                    days = max(1, (last - first).days)
                    msgs_per_day = len(messages) / days
                except Exception:
                    msgs_per_day = 2
            else:
                msgs_per_day = 2

            # Build profile
            profile = {
                'avg_message_length': round(avg_length),
                'vocabulary_size': vocabulary_size,
                'avg_word_length': round(avg_word_len, 1),
                'preferred_greeting': preferred_greeting,
                'formality': formality,
                'msgs_per_day': round(msgs_per_day, 1),
                'common_words': [w[0] for w in common_words[:10]],
                'total_messages': len(messages),
                'updated_at': datetime.utcnow().isoformat(),

                # Derived: how Radim should talk
                'response_complexity': _calc_complexity(avg_length, avg_word_len, vocabulary_size),
                'response_length': _calc_response_length(avg_length),
                'speech_rate': _calc_speech_rate(avg_length, msgs_per_day),
                'pause_multiplier': _calc_pause_mult(avg_length, msgs_per_day),
            }

            # Save
            learning = db_load_learning(user_id)
            learning['communication_profile'] = profile
            db_save_learning(user_id, learning)

            return profile

    except Exception as e:
        logger.debug(f"Communication analysis error: {e}")
        return _default_comm_profile()


def _calc_complexity(avg_len, avg_word, vocab):
    """Simple/medium/rich based on message patterns."""
    if avg_len < 20 and avg_word < 4.5:
        return 'simple'     # Short messages, simple words → answer simply
    elif avg_len > 60 and vocab > 200:
        return 'rich'       # Long messages, rich vocab → can give detailed answers
    return 'medium'


def _calc_response_length(avg_len):
    """Target response length based on user's style."""
    if avg_len < 15:
        return 'short'      # 1-2 sentences
    elif avg_len > 50:
        return 'detailed'   # 3-5 sentences
    return 'medium'          # 2-3 sentences


def _calc_speech_rate(avg_len, msgs_per_day):
    """TTS speech rate modifier."""
    if avg_len < 15 and msgs_per_day > 5:
        return 1.0           # Fast chatter → normal speed
    elif avg_len < 15:
        return 0.85          # Short but slow → slow down
    return 0.9               # Default


def _calc_pause_mult(avg_len, msgs_per_day):
    """Pause multiplier for TTS."""
    if msgs_per_day < 2:
        return 1.3           # Infrequent user → longer pauses (needs time)
    elif msgs_per_day > 8:
        return 0.9           # Very active → shorter pauses
    return 1.0


def _default_comm_profile():
    return {
        'response_complexity': 'medium',
        'response_length': 'medium',
        'speech_rate': 0.9,
        'pause_multiplier': 1.0,
        'preferred_greeting': 'dobrý den',
        'formality': 'formal',
        'common_words': [],
        'total_messages': 0,
    }


def generate_communication_prompt(user_id):
    """Generate system prompt fragment for personalized communication."""
    learning = db_load_learning(user_id) if _AVAILABLE else {}
    profile = learning.get('communication_profile', _default_comm_profile())

    parts = []

    # Complexity
    if profile.get('response_complexity') == 'simple':
        parts.append("Mluv jednoduše. Krátké věty. Jasná slova. Žádné odborné výrazy.")
    elif profile.get('response_complexity') == 'rich':
        parts.append("Uživatel rád komunikuje detailněji. Můžeš používat bohatší slovník a delší odpovědi.")

    # Length
    if profile.get('response_length') == 'short':
        parts.append("Odpovídej stručně — 1-2 věty stačí. Senior preferuje krátké odpovědi.")
    elif profile.get('response_length') == 'detailed':
        parts.append("Senior oceňuje podrobnější odpovědi s vysvětlením.")

    # Formality
    if profile.get('formality') == 'informal':
        parts.append("Senior ti tyká — můžeš mu taky tykat.")

    # Mirror vocabulary
    common = profile.get('common_words', [])
    if common and len(common) >= 5:
        words_str = ', '.join(common[:7])
        parts.append(f"Senior často používá slova: {words_str}. Zkus je přirozeně používat taky.")

    # Greeting
    greeting = profile.get('preferred_greeting', 'dobrý den')
    if greeting == 'ahoj':
        parts.append("Senior říká 'ahoj' — používej neformální pozdravy.")

    return ' '.join(parts) if parts else ''


# ═══════════════════════════════════════════════════════════════════
# 2. CONVERSATION MEMORY — follow up across sessions
# ═══════════════════════════════════════════════════════════════════

def extract_memorable_topics(user_id, message, response):
    """Extract topics worth remembering for future follow-up.

    Detects:
        - Health complaints ("bolí mě záda")
        - Plans ("zítra jdu k doktorovi")
        - Emotions ("je mi smutno")
        - Family events ("dcera přijede v pátek")
        - Interests ("dívám se na fotbal")
    """
    if not _AVAILABLE or not message:
        return

    lower = message.lower()
    topics = []

    # Health
    health_patterns = [
        (r'bolí\s+m[eě]\s+(\w+)', 'pain'),
        (r'špatně\s+sp[ií]m', 'sleep_bad'),
        (r'boli\s+m[eě]\s+(\w+)', 'pain'),
        (r'nemohu|nemůžu\s+(\w+)', 'limitation'),
        (r'léky|prášky|tablety', 'medication'),
        (r'doktor|lékař|nemocnice|vyšetření', 'medical_visit'),
    ]
    for pattern, topic_type in health_patterns:
        match = re.search(pattern, lower)
        if match:
            topics.append({
                'type': 'health',
                'subtype': topic_type,
                'detail': match.group(0)[:50],
                'at': datetime.utcnow().isoformat(),
                'follow_up_after': '1d',
            })

    # Plans (tomorrow, next week, etc.)
    plan_patterns = [
        (r'zítra\s+(.{5,30})', 'tomorrow'),
        (r'příští\s+týden\s+(.{5,30})', 'next_week'),
        (r'v\s+pátek|v\s+sobotu|v\s+neděli\s+(.{5,30})', 'this_week'),
        (r'jdu\s+k\s+(.{5,20})', 'appointment'),
        (r'přijede\s+(.{5,20})', 'visitor'),
    ]
    for pattern, plan_type in plan_patterns:
        match = re.search(pattern, lower)
        if match:
            topics.append({
                'type': 'plan',
                'subtype': plan_type,
                'detail': match.group(0)[:50],
                'at': datetime.utcnow().isoformat(),
                'follow_up_after': '1d',
            })

    # Emotions
    if any(w in lower for w in ['smutno', 'smutný', 'smutná', 'osamělý', 'osamělá', 'stýská', 'chybí mi']):
        topics.append({
            'type': 'emotion',
            'subtype': 'sadness',
            'detail': message[:50],
            'at': datetime.utcnow().isoformat(),
            'follow_up_after': '1d',
        })

    if any(w in lower for w in ['radost', 'šťastný', 'šťastná', 'povedlo', 'krásný den']):
        topics.append({
            'type': 'emotion',
            'subtype': 'joy',
            'detail': message[:50],
            'at': datetime.utcnow().isoformat(),
            'follow_up_after': '3d',
        })

    # Save
    if topics:
        try:
            learning = db_load_learning(user_id)
            memory = learning.get('conversation_memory', [])
            memory.extend(topics)
            learning['conversation_memory'] = memory[-30:]  # Keep 30
            db_save_learning(user_id, learning)
        except Exception:
            pass


def get_followup_hints(user_id):
    """Get topics Radim should follow up on in today's conversation.

    Returns list of natural follow-up prompts.
    """
    if not _AVAILABLE:
        return []

    try:
        learning = db_load_learning(user_id)
        memory = learning.get('conversation_memory', [])
        now = datetime.utcnow()
        hints = []

        for topic in memory:
            created = datetime.fromisoformat(topic['at'])
            age_hours = (now - created).total_seconds() / 3600
            follow_after = topic.get('follow_up_after', '1d')

            # Check if it's time to follow up
            min_hours = 24 if follow_after == '1d' else 72 if follow_after == '3d' else 168
            max_hours = min_hours + 48  # Window: min → min+48h

            if min_hours <= age_hours <= max_hours:
                hint = _generate_followup(topic)
                if hint:
                    hints.append(hint)

        return hints[:3]  # Max 3 follow-ups per session

    except Exception:
        return []


def _generate_followup(topic):
    """Generate natural follow-up question for a remembered topic."""
    t = topic.get('type', '')
    s = topic.get('subtype', '')
    d = topic.get('detail', '')

    if t == 'health' and s == 'pain':
        return f"Minule jste říkal/a, že vás {d}. Je to lepší?"
    elif t == 'health' and s == 'sleep_bad':
        return "Jak se vám v poslední době spí? Minule to nebylo ideální."
    elif t == 'health' and s == 'medical_visit':
        return "Byl/a jste u toho doktora? Jak to dopadlo?"
    elif t == 'plan' and s == 'visitor':
        return f"Přijel/a už ten návštěvník, o kterém jste mluvil/a?"
    elif t == 'plan' and s == 'appointment':
        return f"Jak dopadla ta schůzka, o které jste mluvil/a?"
    elif t == 'plan' and s == 'tomorrow':
        return "Povedlo se to, co jste měl/a včera v plánu?"
    elif t == 'emotion' and s == 'sadness':
        return "Jak se dnes cítíte? Minule to nebylo úplně lehké."
    elif t == 'emotion' and s == 'joy':
        return "Minule jste měl/a radost — přeji vám, aby to pokračovalo!"
    return None


# ═══════════════════════════════════════════════════════════════════
# 3. EMOTIONAL PATTERNS — predict mood by day/hour
# ═══════════════════════════════════════════════════════════════════

def compute_emotional_patterns(user_id):
    """Build emotional profile: when is senior typically happy/sad/anxious.

    Uses brain_states C values grouped by day-of-week and hour.
    """
    if not _AVAILABLE:
        return {}

    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT C, EXTRACT(DOW FROM created_at) as dow, "
                    "EXTRACT(HOUR FROM created_at) as hr "
                    "FROM brain_states WHERE user_id = ? "
                    "AND created_at > NOW() - INTERVAL '30 days'",
                    (user_id,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT C, CAST(strftime('%w', created_at) AS INTEGER) as dow, "
                    "CAST(strftime('%H', created_at) AS INTEGER) as hr "
                    "FROM brain_states WHERE user_id = ? "
                    "AND created_at > datetime('now', '-30 days')",
                    (user_id,)
                ).fetchall()

            if not rows or len(rows) < 10:
                return {'has_data': False}

            # Group by day of week
            by_dow = {}  # 0=Sun, 1=Mon...6=Sat
            by_hour = {}
            day_names = ['Neděle', 'Pondělí', 'Úterý', 'Středa', 'Čtvrtek', 'Pátek', 'Sobota']

            for r in rows:
                c = float(r[0])
                dow = int(r[1])
                hr = int(r[2])
                by_dow.setdefault(dow, []).append(c)
                by_hour.setdefault(hr, []).append(c)

            # Averages
            dow_avg = {dow: round(sum(vals) / len(vals), 1) for dow, vals in by_dow.items()}
            hour_avg = {hr: round(sum(vals) / len(vals), 1) for hr, vals in by_hour.items()}

            # Find best/worst times
            if dow_avg:
                best_day = min(dow_avg, key=dow_avg.get)
                worst_day = max(dow_avg, key=dow_avg.get)
            else:
                best_day = worst_day = 0

            if hour_avg:
                best_hour = min(hour_avg, key=hour_avg.get)
                worst_hour = max(hour_avg, key=hour_avg.get)
            else:
                best_hour = worst_hour = 12

            profile = {
                'has_data': True,
                'by_day': {day_names[d]: v for d, v in dow_avg.items()},
                'by_hour': hour_avg,
                'best_day': day_names[best_day],
                'worst_day': day_names[worst_day],
                'best_hour': best_hour,
                'worst_hour': worst_hour,
                'data_points': len(rows),
                'updated_at': datetime.utcnow().isoformat(),
            }

            # Save
            learning = db_load_learning(user_id)
            learning['emotional_patterns'] = profile
            db_save_learning(user_id, learning)

            return profile

    except Exception as e:
        logger.debug(f"Emotional patterns error: {e}")
        return {'has_data': False}


def get_emotional_context(user_id):
    """Get current emotional context for system prompt.

    Example: "Dnes je pondělí ráno — pro tohoto seniora bývá náročnější.
    Buď extra empatický a nabídni lehké aktivity."
    """
    if not _AVAILABLE:
        return ''

    try:
        learning = db_load_learning(user_id)
        patterns = learning.get('emotional_patterns', {})
        if not patterns.get('has_data'):
            return ''

        now = datetime.utcnow()
        day_names = ['Pondělí', 'Úterý', 'Středa', 'Čtvrtek', 'Pátek', 'Sobota', 'Neděle']
        today = day_names[now.weekday()]
        hour = now.hour

        parts = []

        # Day pattern
        if patterns.get('worst_day') == today:
            parts.append(f"{today} bývá pro tohoto seniora náročnější den. Buď extra klidný a empatický.")
        elif patterns.get('best_day') == today:
            parts.append(f"{today} bývá dobrý den. Senior bývá pozitivnější — můžeš navrhnout aktivity.")

        # Hour pattern
        worst_hr = patterns.get('worst_hour')
        best_hr = patterns.get('best_hour')
        if worst_hr and abs(hour - worst_hr) <= 1:
            parts.append("Tato hodina bývá stresovější. Mluv pomalu a nabídni uklidnění.")
        elif best_hr and abs(hour - best_hr) <= 1:
            parts.append("Tato hodina bývá klidná. Senior je otevřenější konverzaci.")

        return ' '.join(parts)

    except Exception:
        return ''


# ═══════════════════════════════════════════════════════════════════
# 4. RELATIONSHIP GROWTH — trust builds over time
# ═══════════════════════════════════════════════════════════════════

def compute_relationship_level(user_id):
    """Compute relationship maturity: how well Radim knows this senior.

    Levels:
        stranger  (day 0-3)  — formal, careful, asks permission
        acquaintance (4-14)  — warming up, remembers basics
        companion (15-30)    — informal, proactive, remembers details
        trusted (30-90)      — deep trust, auto-actions, emotional support
        family (90+)         — like family member, anticipates needs
    """
    if not _AVAILABLE:
        return {'level': 'stranger', 'days': 0, 'trust': 0.1}

    try:
        learning = db_load_learning(user_id)

        # Count days with interactions
        with db_context() as db:
            if is_postgres():
                row = db.execute(
                    "SELECT COUNT(DISTINCT DATE(created_at)) as days, MIN(created_at) as first "
                    "FROM memory_history WHERE user_id = ? AND role = 'user'",
                    (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT COUNT(DISTINCT DATE(created_at)) as days, MIN(created_at) as first "
                    "FROM memory_history WHERE user_id = ? AND role = 'user'",
                    (user_id,)
                ).fetchone()

            active_days = int(row[0]) if row else 0

            # First interaction
            first_date = row[1] if row and row[1] else None
            if first_date and isinstance(first_date, str):
                first_date = datetime.fromisoformat(first_date.replace('Z', ''))
            total_days = (datetime.utcnow() - first_date).days if first_date else 0

        # Trust score (0-1)
        trust = min(1.0, active_days / 60)  # 60 active days = full trust

        # Level
        if active_days < 3:
            level = 'stranger'
        elif active_days < 14:
            level = 'acquaintance'
        elif active_days < 30:
            level = 'companion'
        elif active_days < 90:
            level = 'trusted'
        else:
            level = 'family'

        result = {
            'level': level,
            'active_days': active_days,
            'total_days': total_days,
            'trust': round(trust, 2),
            'updated_at': datetime.utcnow().isoformat(),
        }

        learning['relationship'] = result
        db_save_learning(user_id, learning)

        return result

    except Exception as e:
        logger.debug(f"Relationship level error: {e}")
        return {'level': 'stranger', 'days': 0, 'trust': 0.1}


def get_relationship_prompt(user_id):
    """System prompt fragment based on relationship level."""
    if not _AVAILABLE:
        return ''

    learning = db_load_learning(user_id)
    rel = learning.get('relationship', {})
    level = rel.get('level', 'stranger')

    if level == 'stranger':
        return "Tohoto seniora znáš teprve krátce. Buď zdvořilý, formální, ptej se na povolení. Nabízej pomoc opatrně."
    elif level == 'acquaintance':
        return "Seniora začínáš poznávat. Můžeš být teplejší, ale stále respektuj hranice. Pamatuj si co ti řekl."
    elif level == 'companion':
        return "Se seniorem máš dobrý vztah. Můžeš být neformální, navazovat na minulé rozhovory, navrhovat aktivity."
    elif level == 'trusted':
        return "Senior ti důvěřuje. Můžeš proaktivně jednat, připomínat léky, navrhovat hovory s rodinou. Mluv jako blízký přítel."
    elif level == 'family':
        return "Jsi pro seniora jako člen rodiny. Znáš ho/ji dokonale. Předvídej potřeby, mluv laskavě a přirozeně."
    return ''


# ═══════════════════════════════════════════════════════════════════
# 5. LEARNING PROGRESS — adaptive education
# ═══════════════════════════════════════════════════════════════════

def track_quiz_performance(user_id, topic, correct, total, difficulty):
    """Track quiz performance for adaptive difficulty."""
    if not _AVAILABLE:
        return

    try:
        learning = db_load_learning(user_id)
        progress = learning.get('learning_progress', {})

        topic_data = progress.get(topic, {'attempts': 0, 'correct': 0, 'total': 0, 'avg_score': 0, 'level': 'easy'})
        topic_data['attempts'] += 1
        topic_data['correct'] += correct
        topic_data['total'] += total
        topic_data['avg_score'] = round(topic_data['correct'] / max(topic_data['total'], 1) * 100)
        topic_data['last_difficulty'] = difficulty
        topic_data['last_at'] = datetime.utcnow().isoformat()

        # Adaptive level
        if topic_data['avg_score'] > 80 and topic_data['attempts'] >= 3:
            topic_data['level'] = 'hard' if difficulty == 'medium' else 'medium'
        elif topic_data['avg_score'] < 40 and topic_data['attempts'] >= 3:
            topic_data['level'] = 'easy'

        progress[topic] = topic_data
        learning['learning_progress'] = progress
        db_save_learning(user_id, learning)

    except Exception:
        pass


def get_recommended_difficulty(user_id, topic):
    """Get recommended quiz difficulty for this user + topic."""
    if not _AVAILABLE:
        return 'easy'

    try:
        learning = db_load_learning(user_id)
        progress = learning.get('learning_progress', {})
        topic_data = progress.get(topic, {})
        return topic_data.get('level', 'easy')
    except Exception:
        return 'easy'


# ═══════════════════════════════════════════════════════════════════
# UNIFIED: Build full personal context for system prompt
# ═══════════════════════════════════════════════════════════════════

def build_personal_context(user_id):
    """Build complete personal context for AI system prompt.

    Combines all growth subsystems into one coherent prompt fragment.
    """
    parts = []

    # Communication style
    comm = generate_communication_prompt(user_id)
    if comm:
        parts.append(f"[Komunikační styl] {comm}")

    # Relationship
    rel = get_relationship_prompt(user_id)
    if rel:
        parts.append(f"[Vztah] {rel}")

    # Emotional context (time-based)
    emo = get_emotional_context(user_id)
    if emo:
        parts.append(f"[Emoční kontext] {emo}")

    # Follow-up hints
    followups = get_followup_hints(user_id)
    if followups:
        hints_str = '; '.join(followups[:2])
        parts.append(f"[Navázání na minulé rozhovory] {hints_str}")

    return '\n'.join(parts) if parts else ''


# ═══════════════════════════════════════════════════════════════════
# FLASK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

from flask import Blueprint, request, jsonify

growth_bp = Blueprint('personal_growth', __name__)


@growth_bp.route('/api/growth/profile/<user_id>', methods=['GET'])
def api_growth_profile(user_id):
    """Get complete personal growth profile."""
    comm = analyze_communication_style(user_id)
    emo = compute_emotional_patterns(user_id)
    rel = compute_relationship_level(user_id)
    followups = get_followup_hints(user_id)
    context = build_personal_context(user_id)

    return jsonify({
        'success': True,
        'communication': comm,
        'emotional_patterns': emo,
        'relationship': rel,
        'followup_hints': followups,
        'system_prompt_fragment': context,
    })


@growth_bp.route('/api/growth/communication/<user_id>', methods=['GET'])
def api_communication(user_id):
    profile = analyze_communication_style(user_id)
    return jsonify({'success': True, **profile})


@growth_bp.route('/api/growth/emotional/<user_id>', methods=['GET'])
def api_emotional(user_id):
    patterns = compute_emotional_patterns(user_id)
    return jsonify({'success': True, **patterns})


@growth_bp.route('/api/growth/relationship/<user_id>', methods=['GET'])
def api_relationship(user_id):
    rel = compute_relationship_level(user_id)
    return jsonify({'success': True, **rel})


@growth_bp.route('/api/growth/learning/<user_id>', methods=['GET'])
def api_learning_progress(user_id):
    try:
        learning = db_load_learning(user_id)
        return jsonify({'success': True, 'progress': learning.get('learning_progress', {})})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


logger.info("🌱 Personal Growth Engine v1.0 loaded — communication, memory, emotions, relationship, learning")
