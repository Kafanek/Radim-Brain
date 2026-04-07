"""
📊 SURVEY ENGINE v1.0
======================
Intelligent survey system for Radim senior assistant.

Architecture:
    1. Adaptive Survey Selection — picks questions based on yesterday's answers
    2. Per-Senior Baseline — 7-day rolling average per dimension
    3. Multi-Signal Risk Score — not just mood, but sleep + pain + activity + text
    4. Trend Detection — 3d/7d/30d with direction + confidence
    5. Gentle Memory Hints — empathetic, never diagnostic
    6. Caregiver Alerts — severity + confidence + reasons

Design principles:
    - Senior is NOT a patient. Radim is a companion, not a monitor.
    - Hints are warm and inviting, never clinical.
    - Follow-up only when meaningful.
    - Risk ≠ diagnosis. Risk = "pay more attention".
"""

import json
import logging
import math
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

PHI = 1.618034

# ═══════════════════════════════════════════════════════════════════
# DIMENSIONS — what we track
# ═══════════════════════════════════════════════════════════════════

DIMENSIONS = {
    'mood':     {'weight': PHI ** 2, 'label': 'Nálada',   'icon': '😊', 'range': [1, 5]},
    'sleep':    {'weight': PHI,      'label': 'Spánek',   'icon': '😴', 'range': [1, 5]},
    'pain':     {'weight': PHI,      'label': 'Bolest',   'icon': '💊', 'range': [0, 1]},  # 0=no, 1=yes
    'activity': {'weight': 1.0,      'label': 'Aktivita', 'icon': '🚶', 'range': [0, 1]},
    'social':   {'weight': 1.0,      'label': 'Kontakt',  'icon': '👥', 'range': [0, 1]},
    'safety':   {'weight': PHI,      'label': 'Bezpečí',  'icon': '🛡️', 'range': [1, 5]},
}

# ═══════════════════════════════════════════════════════════════════
# ADAPTIVE SURVEY SELECTION
# ═══════════════════════════════════════════════════════════════════

# Core questions — always asked (3 daily)
CORE_QUESTIONS = [
    {
        'id': 'mood_today',
        'dimension': 'mood',
        'text': 'Jak se dnes cítíte?',
        'type': 'emoji_scale',
        'options': [
            {'value': 5, 'label': '😄 Skvěle'},
            {'value': 4, 'label': '🙂 Dobře'},
            {'value': 3, 'label': '😐 Normálně'},
            {'value': 2, 'label': '😟 Nic moc'},
            {'value': 1, 'label': '😢 Špatně'},
        ]
    },
    {
        'id': 'sleep_quality',
        'dimension': 'sleep',
        'text': 'Jak jste spal/a?',
        'type': 'emoji_scale',
        'options': [
            {'value': 5, 'label': '😴 Výborně'},
            {'value': 4, 'label': '🛏️ Dobře'},
            {'value': 3, 'label': '😐 Ujde to'},
            {'value': 2, 'label': '😩 Špatně'},
            {'value': 1, 'label': '😵 Vůbec ne'},
        ]
    },
    {
        'id': 'pain_check',
        'dimension': 'pain',
        'text': 'Bolí vás dnes něco?',
        'type': 'yes_no',
        'followup': {
            'id': 'pain_detail',
            'text': 'Co vás bolí? Můžete popsat?',
            'type': 'open_text'
        }
    },
]

# Follow-up questions — triggered by yesterday's answers or risk
FOLLOWUP_POOL = [
    {
        'id': 'activity_check',
        'dimension': 'activity',
        'text': 'Byl/a jste dnes venku nebo jste se prošel/a?',
        'type': 'yes_no',
        'trigger': lambda history: _recent_activity_low(history),
    },
    {
        'id': 'social_check',
        'dimension': 'social',
        'text': 'Mluvil/a jste dnes s někým blízkým?',
        'type': 'yes_no',
        'trigger': lambda history: _recent_social_low(history),
    },
    {
        'id': 'safety_feeling',
        'dimension': 'safety',
        'text': 'Cítíte se doma bezpečně?',
        'type': 'emoji_scale',
        'options': [
            {'value': 5, 'label': '🛡️ Úplně'},
            {'value': 4, 'label': '👍 Většinou'},
            {'value': 3, 'label': '😐 Někdy ne'},
            {'value': 2, 'label': '😰 Mám obavy'},
            {'value': 1, 'label': '😱 Ne'},
        ],
        'trigger': lambda history: _safety_concern(history),
    },
    {
        'id': 'mood_detail',
        'dimension': 'mood',
        'text': 'Chcete říct, co vás trápí?',
        'type': 'open_text',
        'trigger': lambda history: _mood_declining(history),
    },
    {
        'id': 'meds_taken',
        'dimension': 'pain',
        'text': 'Vzal/a jste si dnes léky?',
        'type': 'yes_no',
        'trigger': lambda history: True,  # Always relevant if user has meds
    },
]


def _recent_activity_low(history):
    """Trigger if activity was low in last 2 days."""
    recent = [h for h in history if h.get('dimension') == 'activity'][-2:]
    return len(recent) < 2 or any(h.get('value', 1) == 0 for h in recent)


def _recent_social_low(history):
    recent = [h for h in history if h.get('dimension') == 'social'][-2:]
    return len(recent) < 2 or all(h.get('value', 1) == 0 for h in recent)


def _safety_concern(history):
    recent = [h for h in history if h.get('dimension') == 'safety'][-3:]
    return any(h.get('value', 5) < 3 for h in recent)


def _mood_declining(history):
    recent = [h for h in history if h.get('dimension') == 'mood'][-3:]
    if len(recent) < 2:
        return False
    return sum(h.get('value', 3) for h in recent) / len(recent) < 3.0


def select_todays_questions(user_id):
    """Select adaptive questions for today.

    Always: 3 core questions
    Plus: 0-2 follow-up based on recent history
    Max: 5 questions total
    """
    # Get recent answer history
    history = _get_recent_answers(user_id, days=7)

    questions = list(CORE_QUESTIONS)  # copy

    # Add triggered follow-ups (max 2)
    added = 0
    for fq in FOLLOWUP_POOL:
        if added >= 2:
            break
        try:
            if fq['trigger'](history):
                # Don't add if same dimension already in core
                if not any(q['dimension'] == fq['dimension'] and q['id'] == fq['id'] for q in questions):
                    q_copy = {k: v for k, v in fq.items() if k != 'trigger'}
                    questions.append(q_copy)
                    added += 1
        except Exception:
            pass

    return {
        'id': 'adaptive_daily',
        'title': '📊 Jak se dnes máte?',
        'type': 'daily',
        'questions': questions,
        'reward_points': 10 + added * 5,  # Bonus for follow-ups
        'adaptive': True,
        'question_count': len(questions)
    }


def _get_recent_answers(user_id, days=7):
    """Get flat list of recent answer items."""
    if not _AVAILABLE:
        return []
    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT answers FROM survey_responses WHERE user_id = ? "
                    "AND created_at > NOW() - INTERVAL '%s days' ORDER BY created_at DESC LIMIT 30" % days,
                    (user_id,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT answers FROM survey_responses WHERE user_id = ? "
                    "AND created_at > datetime('now', '-%d days') ORDER BY created_at DESC LIMIT 30" % days,
                    (user_id,)
                ).fetchall()

            items = []
            for r in rows:
                try:
                    data = json.loads(r[0] if isinstance(r, (list, tuple)) else r.get('answers', '{}'))
                    for a in data.get('answers', []):
                        # Enrich with dimension from question definitions
                        dim = _get_dimension_for_question(a.get('id', ''))
                        items.append({**a, 'dimension': dim or a.get('dimension', '')})
                except Exception:
                    pass
            return items
    except Exception:
        return []


def _get_dimension_for_question(question_id):
    all_qs = CORE_QUESTIONS + [q for q in FOLLOWUP_POOL]
    for q in all_qs:
        if q['id'] == question_id:
            return q.get('dimension', '')
    return ''


# ═══════════════════════════════════════════════════════════════════
# PER-SENIOR BASELINE — rolling averages
# ═══════════════════════════════════════════════════════════════════

def compute_survey_baseline(user_id):
    """Compute per-dimension baselines from 7-day history."""
    history = _get_recent_answers(user_id, days=7)

    baselines = {}
    for dim_id, dim_info in DIMENSIONS.items():
        values = [h['value'] for h in history
                  if h.get('dimension') == dim_id and isinstance(h.get('value'), (int, float))]
        if values:
            avg = sum(values) / len(values)
            std = math.sqrt(sum((v - avg) ** 2 for v in values) / max(len(values), 1))
            baselines[dim_id] = {
                'avg': round(avg, 2),
                'std': round(max(std, 0.3), 2),
                'count': len(values),
                'min': min(values),
                'max': max(values),
            }
        else:
            baselines[dim_id] = {'avg': None, 'std': None, 'count': 0}

    return baselines


# ═══════════════════════════════════════════════════════════════════
# TREND DETECTION — 3d / 7d / 30d
# ═══════════════════════════════════════════════════════════════════

def compute_trends(user_id):
    """Compute trends for each dimension over multiple windows."""
    trends = {}
    for window in [3, 7, 30]:
        history = _get_recent_answers(user_id, days=window)
        window_trends = {}
        for dim_id in DIMENSIONS:
            values = [h['value'] for h in history
                      if h.get('dimension') == dim_id and isinstance(h.get('value'), (int, float))]
            if len(values) >= 2:
                # Simple linear slope
                n = len(values)
                x_mean = (n - 1) / 2.0
                y_mean = sum(values) / n
                slope = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
                slope /= max(sum((i - x_mean) ** 2 for i in range(n)), 0.01)

                direction = 'improving' if slope > 0.1 else 'declining' if slope < -0.1 else 'stable'
                # For pain, inverse (rising pain = bad)
                if dim_id == 'pain':
                    direction = 'declining' if slope > 0.05 else 'improving' if slope < -0.05 else 'stable'

                confidence = min(1.0, len(values) / (window * 0.7))

                window_trends[dim_id] = {
                    'direction': direction,
                    'slope': round(slope, 3),
                    'avg': round(y_mean, 2),
                    'count': len(values),
                    'confidence': round(confidence, 2),
                }
            else:
                window_trends[dim_id] = {'direction': 'insufficient_data', 'count': len(values)}

        trends[f'{window}d'] = window_trends

    return trends


# ═══════════════════════════════════════════════════════════════════
# MULTI-SIGNAL RISK SCORE
# ═══════════════════════════════════════════════════════════════════

SEVERITY = {
    'OK': 0,
    'WATCH': 1,
    'WARNING': 2,
    'URGENT': 3,
}


def compute_survey_risk(user_id):
    """Compute multi-signal risk score.

    Signals:
        1. Mood decline (vs personal baseline)
        2. Sleep decline
        3. Pain increase
        4. Activity drop
        5. Social isolation
        6. Non-response (stopped answering)
        7. Negative text signals
        8. Streak break (lost regularity)

    Returns:
        {
            score: 0-100,
            severity: OK/WATCH/WARNING/URGENT,
            confidence: 0-1,
            reasons: [{signal, value, contribution, explanation}],
            summary: "human-readable summary"
        }
    """
    baselines = compute_survey_baseline(user_id)
    trends = compute_trends(user_id)
    history = _get_recent_answers(user_id, days=7)

    signals = {}
    reasons = []

    # 1. Mood decline
    mood_bl = baselines.get('mood', {})
    mood_3d = trends.get('3d', {}).get('mood', {})
    if mood_bl.get('avg') and mood_3d.get('direction') == 'declining':
        deviation = max(0, (mood_bl['avg'] - mood_3d.get('avg', 3)) / max(mood_bl.get('std', 1), 0.5))
        sig = min(1.0, deviation / 2.0)
        signals['mood'] = sig
        if sig > 0.3:
            reasons.append({
                'signal': 'mood', 'value': sig,
                'explanation': f"Nálada klesá (průměr {mood_3d.get('avg', '?')}/5 vs obvyklých {mood_bl['avg']}/5)"
            })

    # 2. Sleep decline
    sleep_bl = baselines.get('sleep', {})
    sleep_3d = trends.get('3d', {}).get('sleep', {})
    if sleep_bl.get('avg') and sleep_3d.get('avg'):
        deviation = max(0, (sleep_bl['avg'] - sleep_3d['avg']) / max(sleep_bl.get('std', 1), 0.5))
        sig = min(1.0, deviation / 2.0)
        signals['sleep'] = sig
        if sig > 0.3:
            reasons.append({
                'signal': 'sleep', 'value': sig,
                'explanation': f"Spánek se zhoršuje ({sleep_3d['avg']}/5 vs obvyklých {sleep_bl['avg']}/5)"
            })

    # 3. Pain increase
    pain_recent = [h['value'] for h in history if h.get('dimension') == 'pain' and isinstance(h.get('value'), (int, float))]
    if pain_recent:
        pain_rate = sum(1 for v in pain_recent if v == 1) / len(pain_recent)
        signals['pain'] = pain_rate
        if pain_rate > 0.5:
            reasons.append({
                'signal': 'pain', 'value': pain_rate,
                'explanation': f"Bolest hlášena v {pain_rate*100:.0f}% posledních dotazníků"
            })

    # 4. Activity drop
    activity_recent = [h['value'] for h in history if h.get('dimension') == 'activity']
    if activity_recent:
        active_rate = sum(1 for v in activity_recent if v == 1) / len(activity_recent)
        sig = max(0, 1.0 - active_rate)
        signals['activity'] = sig
        if sig > 0.5:
            reasons.append({
                'signal': 'activity', 'value': sig,
                'explanation': 'Nízká fyzická aktivita za posledních 7 dní'
            })

    # 5. Social isolation
    social_recent = [h['value'] for h in history if h.get('dimension') == 'social']
    if social_recent:
        social_rate = sum(1 for v in social_recent if v == 1) / len(social_recent)
        sig = max(0, 1.0 - social_rate)
        signals['social'] = sig
        if sig > 0.5:
            reasons.append({
                'signal': 'social', 'value': sig,
                'explanation': 'Málo sociálních kontaktů za posledních 7 dní'
            })

    # 6. Non-response (no survey in 2+ days)
    try:
        with db_context() as db:
            if is_postgres():
                row = db.execute(
                    "SELECT MAX(created_at) FROM survey_responses WHERE user_id = ?", (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT MAX(created_at) FROM survey_responses WHERE user_id = ?", (user_id,)
                ).fetchone()
            if row and row[0]:
                last = row[0]
                if isinstance(last, str):
                    last = datetime.fromisoformat(last.replace('Z', ''))
                days_silent = (datetime.utcnow() - last).total_seconds() / 86400
                if days_silent > 1:
                    sig = min(1.0, days_silent / 5.0)
                    signals['non_response'] = sig
                    if sig > 0.3:
                        reasons.append({
                            'signal': 'non_response', 'value': sig,
                            'explanation': f'Žádný dotazník za {days_silent:.0f} dní'
                        })
    except Exception:
        pass

    # 7. Negative text signals
    text_answers = [h.get('value', '') for h in history if isinstance(h.get('value'), str) and len(h.get('value', '')) > 5]
    if text_answers:
        negative_words = ['bolest', 'bolí', 'strach', 'úzkost', 'smutný', 'smutná', 'osamělý', 'osamělá',
                          'nemoc', 'zhoršení', 'nespím', 'slabost', 'závrat', 'pád', 'spadl']
        neg_count = sum(1 for t in text_answers for w in negative_words if w in t.lower())
        if neg_count > 0:
            sig = min(1.0, neg_count / 3.0)
            signals['text_negative'] = sig
            if sig > 0.3:
                reasons.append({
                    'signal': 'text_negative', 'value': sig,
                    'explanation': f'{neg_count} negativních signálů v textových odpovědích'
                })

    # Weighted score
    total_weight = 0
    weighted_sum = 0
    for sig_name, sig_value in signals.items():
        dim = DIMENSIONS.get(sig_name, {'weight': 1.0})
        w = dim['weight']
        weighted_sum += sig_value * w
        total_weight += w

    score = round((weighted_sum / max(total_weight, 1)) * 100) if total_weight > 0 else 0
    score = min(100, score)

    # Severity
    if score < 15:
        severity = 'OK'
    elif score < 35:
        severity = 'WATCH'
    elif score < 60:
        severity = 'WARNING'
    else:
        severity = 'URGENT'

    # Confidence
    total_answers = len(history)
    confidence = min(1.0, total_answers / 14.0)  # 14 = 2 weeks of daily

    return {
        'score': score,
        'severity': severity,
        'confidence': round(confidence, 2),
        'reasons': sorted(reasons, key=lambda r: r.get('value', 0), reverse=True),
        'signals': {k: round(v, 3) for k, v in signals.items()},
        'summary': _generate_summary(severity, reasons),
        'timestamp': datetime.utcnow().isoformat(),
    }


def _generate_summary(severity, reasons):
    if severity == 'OK':
        return 'Vše v pořádku.'
    if not reasons:
        return 'Zatím málo dat pro přesné vyhodnocení.'
    top = reasons[0]
    return top['explanation']


# ═══════════════════════════════════════════════════════════════════
# GENTLE MEMORY HINTS — empathetic, never diagnostic
# ═══════════════════════════════════════════════════════════════════

GENTLE_HINTS = {
    'mood_declining': [
        "Poslední dny se zdá, že to není úplně lehké. Chcete si popovídat?",
        "Všiml jsem si, že máte náročnější dny. Jsem tu pro vás.",
        "Nálada bývá proměnlivá — chcete zkusit něco příjemného? Pustím vám hudbu.",
    ],
    'sleep_bad': [
        "Zdá se, že se vám v noci nespí nejlépe. Zkusíme relaxační cvičení před spaním?",
        "Špatný spánek umí pěkně potrápit. Chcete si popovídat o tom, co by pomohlo?",
    ],
    'pain_frequent': [
        "Všiml jsem si, že vás něco trápí častěji. Chcete, abych to zmínil u doktora?",
        "Bolest není nic příjemného. Potřebujete něco?",
    ],
    'low_activity': [
        "Už jste si dnes udělal/a malou procházku? I pár kroků pomůže.",
        "Krásný den — co takhle se projít nebo protáhnout u okna?",
    ],
    'social_isolated': [
        "Neměl/a byste chuť zavolat někomu blízkému? Stačí říct.",
        "Lidský kontakt je důležitý. Chcete, abych někomu zavolal?",
    ],
    'non_response': [
        "Nebyli jste tu nějakou dobu. Jak se máte?",
        "Chyběl/a jste mi! Jak se daří?",
    ],
    'general_watch': [
        "Jsem tu, kdykoli budete potřebovat. Stačí říct.",
        "Chcete si zkusit kvíz nebo si pustit muziku? Rád vám pomohu.",
    ],
}

import random


def create_memory_hint(user_id, risk_result):
    """Create a gentle memory hint based on risk assessment.

    The hint is injected into memory_learning so Radim mentions it
    in the next conversation — warmly and supportively.

    Returns the hint text or None.
    """
    severity = risk_result.get('severity', 'OK')
    reasons = risk_result.get('reasons', [])

    if severity == 'OK':
        return None

    # Pick hint based on top reason
    hint = None
    if reasons:
        top_signal = reasons[0].get('signal', '')
        hint_pool = GENTLE_HINTS.get(top_signal, GENTLE_HINTS['general_watch'])
        hint = random.choice(hint_pool)
    else:
        hint = random.choice(GENTLE_HINTS['general_watch'])

    # Save to learning memory
    if hint and _AVAILABLE:
        try:
            learning = db_load_learning(user_id)
            survey_hints = learning.get('survey_hints', [])
            survey_hints.append({
                'hint': hint,
                'severity': severity,
                'reason': reasons[0]['signal'] if reasons else 'general',
                'at': datetime.utcnow().isoformat()
            })
            learning['survey_hints'] = survey_hints[-5:]  # Keep last 5

            # Also set the DULEZITE marker for next chat
            agent_obs = learning.get('agent_observations', [])
            agent_obs.append({
                'type': 'survey_hint',
                'severity': severity,
                'message': f"DULEZITE: {hint}",
                'at': datetime.utcnow().isoformat()
            })
            learning['agent_observations'] = agent_obs[-5:]

            db_save_learning(user_id, learning)
        except Exception as e:
            logger.debug(f"Memory hint save error: {e}")

    return hint


# ═══════════════════════════════════════════════════════════════════
# DIGNIFIED REWARDS — not infantile
# ═══════════════════════════════════════════════════════════════════

MILESTONES = [
    {'days': 3,  'text': '3 dny péče o sebe',      'icon': '🌱'},
    {'days': 7,  'text': '7 dní věnujete chvíli sobě', 'icon': '🌿'},
    {'days': 14, 'text': '2 týdny pravidelnosti',   'icon': '🌳'},
    {'days': 30, 'text': 'Měsíc pozornosti k sobě', 'icon': '🌟'},
    {'days': 60, 'text': '2 měsíce stability',      'icon': '💎'},
    {'days': 100,'text': '100 dní — inspirace pro okolí', 'icon': '👑'},
]


def get_milestone(streak_days):
    """Get the current milestone for streak."""
    reached = None
    next_milestone = None
    for m in MILESTONES:
        if streak_days >= m['days']:
            reached = m
        elif not next_milestone:
            next_milestone = m
    return reached, next_milestone


# ═══════════════════════════════════════════════════════════════════
# FLASK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

from flask import Blueprint, request, jsonify

survey_engine_bp = Blueprint('survey_engine', __name__)


@survey_engine_bp.route('/api/surveys/adaptive', methods=['GET'])
def api_adaptive_survey():
    """Get today's adaptive survey questions."""
    user_id = request.args.get('user_id', '')
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    survey = select_todays_questions(user_id)
    return jsonify({'success': True, 'survey': survey})


@survey_engine_bp.route('/api/surveys/trends/<user_id>', methods=['GET'])
def api_survey_trends(user_id):
    """Get survey trends for all dimensions."""
    trends = compute_trends(user_id)
    baselines = compute_survey_baseline(user_id)
    return jsonify({
        'success': True,
        'trends': trends,
        'baselines': baselines,
        'dimensions': {k: {'label': v['label'], 'icon': v['icon']} for k, v in DIMENSIONS.items()}
    })


@survey_engine_bp.route('/api/surveys/risk/<user_id>', methods=['GET'])
def api_survey_risk(user_id):
    """Get survey-based risk score."""
    risk = compute_survey_risk(user_id)
    return jsonify({'success': True, **risk})


@survey_engine_bp.route('/api/surveys/alerts/<user_id>', methods=['GET'])
def api_survey_alerts(user_id):
    """Get caregiver-ready alerts."""
    risk = compute_survey_risk(user_id)

    alert = {
        'user_id': user_id,
        'severity': risk['severity'],
        'confidence': risk['confidence'],
        'score': risk['score'],
        'reasons': risk['reasons'],
        'summary': risk['summary'],
        'needs_attention': risk['severity'] in ('WARNING', 'URGENT'),
        'timestamp': risk['timestamp'],
    }

    return jsonify({'success': True, 'alert': alert})


@survey_engine_bp.route('/api/surveys/milestone/<user_id>', methods=['GET'])
def api_survey_milestone(user_id):
    """Get current milestone and next goal."""
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT streak_days FROM survey_rewards WHERE user_id = ?", (user_id,)
            ).fetchone()
            streak = (row[0] if isinstance(row, (list, tuple)) else row.get('streak_days', 0)) if row else 0
    except Exception:
        streak = 0

    reached, next_goal = get_milestone(streak)
    return jsonify({
        'success': True,
        'streak_days': streak,
        'current_milestone': reached,
        'next_milestone': next_goal,
        'days_to_next': (next_goal['days'] - streak) if next_goal else 0
    })


logger.info("📊 Survey Engine v1.0 loaded — adaptive questions, risk scoring, gentle hints, trends")
