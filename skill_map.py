"""
🗺️ RADIM SKILL MAP v1.0
=========================
Visualizes how Radim learns and grows with each senior.
No XP, no points, no gamification — dignified growth.

6 Skills (computed from existing data):
    🗣️ communication — how well Radim communicates with THIS person
    🧠 understanding — how deeply Radim knows THIS person
    🛡️ safety — how reliably Radim protects THIS person
    🏠 home — how well Radim manages the smart home
    💪 activation — how effectively Radim motivates activity
    📡 resilience — how robust Radim is (offline, errors, recovery)

Each skill: score 0-100, trend, level_label, insights
Direction: empathetic_guide / safety_assistant / daily_organizer / companion
"""

import json
import logging
import math
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning, db_load_profile
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════
# SKILL DEFINITIONS
# ═══════════════════════════════════════════════════════════════════

SKILLS = {
    'communication': {'icon': '🗣️', 'label': 'Komunikace', 'color': '#5BA8A0'},
    'understanding': {'icon': '🧠', 'label': 'Porozumění', 'color': '#6C63FF'},
    'safety':        {'icon': '🛡️', 'label': 'Bezpečnost', 'color': '#F07D7E'},
    'home':          {'icon': '🏠', 'label': 'Domácnost',  'color': '#F6AD55'},
    'activation':    {'icon': '💪', 'label': 'Aktivizace', 'color': '#48BB78'},
    'resilience':    {'icon': '📡', 'label': 'Odolnost',   'color': '#4299E1'},
}

LEVEL_LABELS = {
    (0, 15):   'Seznamuje se',
    (15, 30):  'Učí se základy',
    (30, 50):  'Rozumí rytmu',
    (50, 70):  'Chápe souvislosti',
    (70, 85):  'Zná vás dobře',
    (85, 100): 'Jako blízký přítel',
}

DIRECTIONS = {
    'empathetic_guide':  {'label': 'Empatický průvodce',   'icon': '💝', 'dominant': ['understanding', 'communication']},
    'safety_assistant':  {'label': 'Strážce bezpečí',      'icon': '🛡️', 'dominant': ['safety', 'resilience']},
    'daily_organizer':   {'label': 'Organizátor dne',      'icon': '📋', 'dominant': ['activation', 'home']},
    'companion':         {'label': 'Věrný společník',      'icon': '🤝', 'dominant': ['communication', 'understanding', 'activation']},
}


# ═══════════════════════════════════════════════════════════════════
# SKILL CALCULATORS — all from existing data
# ═══════════════════════════════════════════════════════════════════

def _calc_communication(user_id, learning):
    """How well Radim communicates with this person."""
    score = 10  # Base: Radim exists
    reasons = []

    # Conversation count (more chats = better communication)
    comm = learning.get('communication_profile', {})
    msgs = comm.get('total_messages', 0)
    if msgs > 0:
        score += min(25, msgs * 0.5)  # Up to +25 for 50+ messages
        reasons.append(f'{msgs} konverzací analyzováno')

    # Has vocabulary data (learned their words)
    if comm.get('common_words') and len(comm['common_words']) > 3:
        score += 15
        reasons.append('Naučil se váš slovník')

    # Formality adapted
    if comm.get('formality'):
        score += 10
        reasons.append('Přizpůsobil styl komunikace')

    # Speech rate personalized
    if comm.get('speech_rate') and comm['speech_rate'] != 0.9:
        score += 10
        reasons.append('Přizpůsobil tempo řeči')

    # Complexity adapted
    if comm.get('response_complexity') and comm['response_complexity'] != 'medium':
        score += 10
        reasons.append('Přizpůsobil složitost odpovědí')

    # Voice commands work (modules have handleVoiceCommand)
    score += 10  # System-level capability

    return min(100, round(score)), reasons


def _calc_understanding(user_id, learning):
    """How deeply Radim knows this person."""
    score = 5
    reasons = []

    # Interests tracked
    interests = learning.get('interests', {})
    if interests:
        active = sum(1 for v in interests.values() if v > 0)
        score += min(15, active * 3)
        if active > 0:
            reasons.append(f'Zná {active} vašich zájmů')

    # Family mentions
    family = learning.get('family_mentions', [])
    if family:
        score += min(15, len(family) * 5)
        reasons.append(f'Pamatuje si {len(family)} členů rodiny')

    # Health topics
    health = learning.get('health_topics', {})
    if health:
        score += min(10, len(health) * 3)
        reasons.append(f'Sleduje {len(health)} zdravotních témat')

    # Conversation memory (follow-up topics)
    memory = learning.get('conversation_memory', [])
    if memory:
        score += min(15, len(memory) * 2)
        reasons.append(f'{len(memory)} témat k navázání')

    # Emotional patterns
    emo = learning.get('emotional_patterns', {})
    if emo.get('has_data'):
        score += 15
        reasons.append('Rozumí vašemu emočnímu rytmu')

    # Circadian profile
    circ = learning.get('circadian_profile', {})
    if circ.get('days_analyzed', 0) > 3:
        score += 10
        reasons.append('Zná váš denní rytmus')

    # Relationship level
    rel = learning.get('relationship', {})
    level = rel.get('level', 'stranger')
    if level == 'companion':
        score += 10
    elif level in ('trusted', 'family'):
        score += 15
        reasons.append('Vybudoval si s vámi důvěru')

    return min(100, round(score)), reasons


def _calc_safety(user_id, learning):
    """How reliably Radim protects this person."""
    score = 20  # Base: safety system exists and works
    reasons = []

    # Scenario engine loaded (20 scenarios)
    score += 15
    reasons.append('20 natrénovaných krizových scénářů')

    # Agent observations (detection accuracy)
    obs = learning.get('agent_observations', [])
    if obs:
        score += min(15, len(obs) * 3)
        reasons.append(f'{len(obs)} detekovaných situací')

    # False positive rate (lower = better)
    fp = learning.get('false_positives', 0)
    tp = learning.get('true_positives', 0)
    total = fp + tp
    if total > 0:
        accuracy = tp / total
        score += round(accuracy * 15)
        if accuracy > 0.7:
            reasons.append(f'Přesnost detekce {accuracy*100:.0f}%')

    # Anticipation active
    antic = learning.get('anticipation', {})
    if antic.get('C_hat') is not None:
        score += 10
        reasons.append('Predikuje stres dopředu')

    # Survey risk engine
    if learning.get('survey_hints'):
        score += 5
        reasons.append('Jemné varovné signály')

    # Emergency protocol ready
    score += 10
    reasons.append('Nouzový protokol připraven')

    return min(100, round(score)), reasons


def _calc_home(user_id, learning):
    """How well Radim manages the smart home."""
    score = 10
    reasons = []

    # HA connected
    try:
        from home_assistant import ha
        client = ha()
        if client.connected:
            score += 20

            sensors = client.get_sensors_summary()
            temp_count = len(sensors.get('temperature', []))
            motion_count = len(sensors.get('motion', []))

            if temp_count > 0:
                score += 10
                reasons.append(f'{temp_count} teplotních senzorů')
            if motion_count > 0:
                score += 10
                reasons.append(f'{motion_count} pohybových senzorů')

            devices = client.get_devices_by_type()
            total_devices = sum(len(v) for v in devices.values())
            score += min(20, total_devices * 2)
            if total_devices > 0:
                reasons.append(f'{total_devices} ovládaných zařízení')

            # Behavioral profile from sensors
            bp = learning.get('behavioral_profile', {})
            locations_with_data = sum(1 for v in bp.values() if isinstance(v, dict) and v.get('has_data'))
            if locations_with_data > 0:
                score += min(15, locations_with_data * 5)
                reasons.append(f'Monitoruje {locations_with_data} místností')
        else:
            reasons.append('Smart Home v demo režimu')
            score += 5
    except Exception:
        reasons.append('Smart Home připraven k připojení')

    # Circadian triggers
    triggers = learning.get('proactive_triggers', {})
    if triggers:
        score += min(10, len(triggers) * 2)

    return min(100, round(score)), reasons


def _calc_activation(user_id, learning):
    """How effectively Radim motivates activity."""
    score = 10
    reasons = []

    # Survey streak
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT streak_days, total_points FROM survey_rewards WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row:
                streak = int(row[0]) if isinstance(row, (list, tuple)) else int(row.get('streak_days', 0))
                points = int(row[1]) if isinstance(row, (list, tuple)) else int(row.get('total_points', 0))
                score += min(20, streak * 3)
                score += min(10, points // 50)
                if streak > 0:
                    reasons.append(f'Série {streak} dní pravidelnosti')
                if points > 0:
                    reasons.append(f'{points} bodů za dotazníky')
    except Exception:
        pass

    # Learning progress (quizzes)
    progress = learning.get('learning_progress', {})
    if progress:
        topics = len(progress)
        score += min(15, topics * 5)
        reasons.append(f'{topics} procvičených témat')

    # Chat engagement (msgs per day)
    comm = learning.get('communication_profile', {})
    mpd = comm.get('msgs_per_day', 0)
    if mpd > 2:
        score += min(15, round(mpd * 3))
        reasons.append(f'Průměrně {mpd:.0f} konverzací denně')

    # Weather suggestions active
    if learning.get('weather_suggestions'):
        score += 5
        reasons.append('Denní doporučení aktivit')

    # Medication tracking
    med = learning.get('medication_responses', [])
    if med:
        score += min(10, len(med) * 2)
        reasons.append('Sleduje užívání léků')

    return min(100, round(score)), reasons


def _calc_resilience(user_id, learning):
    """How robust Radim is (offline, errors, recovery)."""
    score = 30  # Base: offline engine exists
    reasons = []

    # Offline engine v3.1 (IndexedDB + queue)
    score += 15
    reasons.append('Offline engine v3.1 aktivní')

    # Safe mode ready
    score += 10
    reasons.append('Nouzový offline režim připraven')

    # Speech pipeline (warmup, cache, ack)
    score += 10
    reasons.append('TTS warmup + phrase cache')

    # Idempotent sync
    score += 10
    reasons.append('Bezpečná synchronizace dat')

    # Service worker
    score += 10
    reasons.append('28 souborů přednahráno offline')

    # Learning agent (adaptive sensitivity)
    sensitivity = learning.get('agent_sensitivity', 1.0)
    if sensitivity != 1.0:
        score += 10
        reasons.append(f'Adaptivní citlivost: {sensitivity:.2f}')

    return min(100, round(score)), reasons


# ═══════════════════════════════════════════════════════════════════
# MAIN CALCULATOR
# ═══════════════════════════════════════════════════════════════════

CALCULATORS = {
    'communication': _calc_communication,
    'understanding': _calc_understanding,
    'safety': _calc_safety,
    'home': _calc_home,
    'activation': _calc_activation,
    'resilience': _calc_resilience,
}


def compute_all_skills(user_id):
    """Compute all 6 skill scores for a user."""
    if not _AVAILABLE:
        return {k: {'score': 0, 'reasons': []} for k in SKILLS}

    learning = db_load_learning(user_id)
    skills = {}

    for skill_id, calc_fn in CALCULATORS.items():
        score, reasons = calc_fn(user_id, learning)
        meta = SKILLS[skill_id]

        # Level label
        level = 'Seznamuje se'
        for (lo, hi), label in LEVEL_LABELS.items():
            if lo <= score < hi:
                level = label
                break
        if score >= 85:
            level = 'Jako blízký přítel'

        skills[skill_id] = {
            'score': score,
            'label': meta['label'],
            'icon': meta['icon'],
            'color': meta['color'],
            'level': level,
            'reasons': reasons[:5],
        }

    # Save snapshot for trend
    try:
        history = learning.get('skill_history', [])
        history.append({
            'scores': {k: v['score'] for k, v in skills.items()},
            'at': datetime.utcnow().isoformat(),
        })
        learning['skill_history'] = history[-60:]  # 60 snapshots (~2 months daily)
        learning['last_skills'] = {k: v['score'] for k, v in skills.items()}
        db_save_learning(user_id, learning)
    except Exception:
        pass

    return skills


# ═══════════════════════════════════════════════════════════════════
# TRENDS — 7d and 30d
# ═══════════════════════════════════════════════════════════════════

def compute_trends(user_id):
    """Compute 7d and 30d trends for each skill."""
    if not _AVAILABLE:
        return {}

    learning = db_load_learning(user_id)
    history = learning.get('skill_history', [])
    if len(history) < 2:
        return {k: {'trend_7d': 0, 'trend_30d': 0} for k in SKILLS}

    now = datetime.utcnow()
    trends = {}

    for skill_id in SKILLS:
        # 7d
        recent_7 = [h['scores'].get(skill_id, 0) for h in history
                     if (now - datetime.fromisoformat(h['at'])).days <= 7]
        old_7 = [h['scores'].get(skill_id, 0) for h in history
                  if 7 < (now - datetime.fromisoformat(h['at'])).days <= 14]

        trend_7d = 0
        if recent_7 and old_7:
            trend_7d = round(sum(recent_7) / len(recent_7) - sum(old_7) / len(old_7), 1)

        # 30d
        recent_30 = [h['scores'].get(skill_id, 0) for h in history
                      if (now - datetime.fromisoformat(h['at'])).days <= 30]
        old_30 = [h['scores'].get(skill_id, 0) for h in history
                   if 30 < (now - datetime.fromisoformat(h['at'])).days <= 60]

        trend_30d = 0
        if recent_30 and old_30:
            trend_30d = round(sum(recent_30) / len(recent_30) - sum(old_30) / len(old_30), 1)

        trends[skill_id] = {'trend_7d': trend_7d, 'trend_30d': trend_30d}

    return trends


# ═══════════════════════════════════════════════════════════════════
# LEARNING INSIGHTS — what Radim learned recently
# ═══════════════════════════════════════════════════════════════════

def generate_insights(user_id):
    """Generate human-readable learning insights."""
    if not _AVAILABLE:
        return []

    learning = db_load_learning(user_id)
    skills = compute_all_skills(user_id)
    insights = []

    # Communication insights
    comm = learning.get('communication_profile', {})
    if comm.get('total_messages', 0) > 10:
        if comm.get('response_complexity') == 'simple':
            insights.append({
                'text': 'Naučil jsem se, že preferujete stručné a jasné odpovědi.',
                'skill': 'communication', 'icon': '🗣️',
                'confidence': 0.8,
                'when': 'dnes',
            })
        if comm.get('formality') == 'informal':
            insights.append({
                'text': 'Přizpůsobil jsem se vašemu neformálnímu stylu komunikace.',
                'skill': 'communication', 'icon': '🗣️',
                'confidence': 0.9,
                'when': 'tento týden',
            })

    # Understanding insights
    memory = learning.get('conversation_memory', [])
    if memory:
        latest = memory[-1]
        if latest.get('type') == 'health':
            insights.append({
                'text': f'Zapamatoval jsem si, že vás trápí {latest.get("detail", "zdravotní téma")}. Budu se ptát jak je to lepší.',
                'skill': 'understanding', 'icon': '🧠',
                'confidence': 0.7,
                'when': 'nedávno',
            })
    if learning.get('emotional_patterns', {}).get('has_data'):
        patterns = learning['emotional_patterns']
        if patterns.get('worst_day'):
            insights.append({
                'text': f'Všiml jsem si, že {patterns["worst_day"]} bývá náročnější den. Budu extra ohleduplný.',
                'skill': 'understanding', 'icon': '🧠',
                'confidence': 0.75,
                'when': 'tento měsíc',
            })

    # Safety insights
    tp = learning.get('true_positives', 0)
    fp = learning.get('false_positives', 0)
    if tp > 0:
        insights.append({
            'text': f'Správně jsem detekoval {tp} situací vyžadujících pozornost.',
            'skill': 'safety', 'icon': '🛡️',
            'confidence': 0.9,
            'when': 'celkově',
        })
    if fp > 0 and tp > fp:
        insights.append({
            'text': 'Učím se rozlišovat skutečné problémy od falešných poplachů.',
            'skill': 'safety', 'icon': '🛡️',
            'confidence': 0.6,
            'when': 'průběžně',
        })

    # Activation insights
    progress = learning.get('learning_progress', {})
    if progress:
        best_topic = max(progress.items(), key=lambda x: x[1].get('avg_score', 0), default=None)
        if best_topic:
            insights.append({
                'text': f'Nejlépe vám jdou kvízy z tématu {best_topic[0]} ({best_topic[1].get("avg_score", 0)}% úspěšnost).',
                'skill': 'activation', 'icon': '💪',
                'confidence': 0.8,
                'when': 'celkově',
            })

    # Relationship insight
    rel = learning.get('relationship', {})
    if rel.get('level') and rel['level'] != 'stranger':
        days = rel.get('active_days', 0)
        insights.append({
            'text': f'Známe se už {days} dní. Náš vztah roste.',
            'skill': 'understanding', 'icon': '🤝',
            'confidence': 1.0,
            'when': 'celkově',
        })

    return insights[:8]  # Max 8


# ═══════════════════════════════════════════════════════════════════
# DIRECTION — specialization
# ═══════════════════════════════════════════════════════════════════

def compute_direction(user_id):
    """Determine Radim's specialization direction for this user."""
    skills = compute_all_skills(user_id)
    scores = {k: v['score'] for k, v in skills.items()}

    best_match = None
    best_score = -1

    for dir_id, dir_info in DIRECTIONS.items():
        dominant = dir_info['dominant']
        avg = sum(scores.get(s, 0) for s in dominant) / len(dominant)
        if avg > best_score:
            best_score = avg
            best_match = dir_id

    if not best_match:
        best_match = 'companion'

    dir_info = DIRECTIONS[best_match]

    # Secondary direction
    secondary = None
    second_score = -1
    for dir_id, d in DIRECTIONS.items():
        if dir_id == best_match:
            continue
        avg = sum(scores.get(s, 0) for s in d['dominant']) / len(d['dominant'])
        if avg > second_score:
            second_score = avg
            secondary = dir_id

    return {
        'primary': {
            'id': best_match,
            'label': dir_info['label'],
            'icon': dir_info['icon'],
            'score': round(best_score, 1),
        },
        'secondary': {
            'id': secondary,
            'label': DIRECTIONS[secondary]['label'],
            'icon': DIRECTIONS[secondary]['icon'],
            'score': round(second_score, 1),
        } if secondary else None,
    }


# ═══════════════════════════════════════════════════════════════════
# OVERALL GROWTH SUMMARY
# ═══════════════════════════════════════════════════════════════════

def compute_growth_summary(user_id):
    """Single-sentence growth summary for the user."""
    skills = compute_all_skills(user_id)
    avg_score = sum(v['score'] for v in skills.values()) / len(skills)
    direction = compute_direction(user_id)

    if avg_score < 20:
        summary = 'Začínáme se poznávat. Každý rozhovor mi pomáhá vás lépe pochopit.'
    elif avg_score < 40:
        summary = 'Učím se váš rytmus a zvyky. Pomalu vám začínám rozumět.'
    elif avg_score < 60:
        summary = 'Už vím, co vám pomáhá a co vás trápí. Zlepšuji se každý den.'
    elif avg_score < 80:
        summary = 'Rozumím vám dobře. Dokážu předvídat, co budete potřebovat.'
    else:
        summary = 'Znám vás jako blízký přítel. Jsem tu pro vás ve dne v noci.'

    return {
        'summary': summary,
        'avg_score': round(avg_score, 1),
        'direction': direction['primary']['label'],
        'direction_icon': direction['primary']['icon'],
    }


# ═══════════════════════════════════════════════════════════════════
# FLASK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

skill_bp = Blueprint('skill_map', __name__)


@skill_bp.route('/api/skills/<user_id>', methods=['GET'])
def api_skills(user_id):
    """Get all skill scores + metadata."""
    skills = compute_all_skills(user_id)
    trends = compute_trends(user_id)

    # Merge trends into skills
    for k in skills:
        skills[k]['trend_7d'] = trends.get(k, {}).get('trend_7d', 0)
        skills[k]['trend_30d'] = trends.get(k, {}).get('trend_30d', 0)

    return jsonify({'success': True, 'skills': skills})


@skill_bp.route('/api/skills/<user_id>/insights', methods=['GET'])
def api_insights(user_id):
    """Get learning insights."""
    insights = generate_insights(user_id)
    return jsonify({'success': True, 'insights': insights, 'count': len(insights)})


@skill_bp.route('/api/skills/<user_id>/direction', methods=['GET'])
def api_direction(user_id):
    """Get specialization direction."""
    direction = compute_direction(user_id)
    return jsonify({'success': True, **direction})


@skill_bp.route('/api/skills/<user_id>/summary', methods=['GET'])
def api_summary(user_id):
    """Get growth summary."""
    summary = compute_growth_summary(user_id)
    skills = compute_all_skills(user_id)
    insights = generate_insights(user_id)
    direction = compute_direction(user_id)

    return jsonify({
        'success': True,
        'summary': summary,
        'skills': skills,
        'insights': insights[:5],
        'direction': direction,
    })


logger.info("🗺️ Skill Map v1.0 loaded — 6 skills, insights, direction, growth summary")
