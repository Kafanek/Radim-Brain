# ============================================
# 🧠 COGNITIVE ASSESSMENT ENGINE
# ============================================
# Tracks cognitive changes over time by analyzing:
# 1. Quiz performance (accuracy, response time)
# 2. Chat complexity (sentence length, vocabulary)
# 3. Task completion patterns
# 4. Memory recall (repeated questions)
# ============================================

import logging
from datetime import datetime, timedelta
from database import db_context

logger = logging.getLogger(__name__)


def compute_cognitive_score(user_id):
    """Compute cognitive assessment score (0-100) from multiple signals.

    Returns:
        dict with score, trend, signals, recommendations
    """
    signals = {}

    # Signal 1: Quiz performance (last 30 days)
    try:
        with db_context(commit=False) as db:
            rows = db.execute("""
                SELECT AVG(CASE WHEN correct THEN 1.0 ELSE 0.0 END) as accuracy,
                       COUNT(*) as total
                FROM quiz_answers
                WHERE user_id = ? AND created_at > ?
            """, (user_id, (datetime.utcnow() - timedelta(days=30)).isoformat())).fetchone()
            if rows and rows[1] and rows[1] > 5:
                signals['quiz_accuracy'] = {'value': round((rows[0] or 0) * 100, 1), 'count': rows[1]}
    except Exception:
        pass

    # Signal 2: Brain coherence trend (last 30 days vs previous 30)
    try:
        with db_context(commit=False) as db:
            recent = db.execute("""
                SELECT AVG(coherence) FROM brain_states
                WHERE user_id = ? AND created_at > ?
            """, (user_id, (datetime.utcnow() - timedelta(days=30)).isoformat())).fetchone()

            older = db.execute("""
                SELECT AVG(coherence) FROM brain_states
                WHERE user_id = ? AND created_at BETWEEN ? AND ?
            """, (user_id,
                  (datetime.utcnow() - timedelta(days=60)).isoformat(),
                  (datetime.utcnow() - timedelta(days=30)).isoformat())).fetchone()

            if recent and recent[0] is not None:
                signals['coherence_current'] = round(recent[0], 2)
            if older and older[0] is not None:
                signals['coherence_previous'] = round(older[0], 2)
            if recent and recent[0] and older and older[0]:
                delta = recent[0] - older[0]
                signals['coherence_trend'] = round(delta, 2)
    except Exception:
        pass

    # Signal 3: Interaction frequency (engagement = cognitive activity)
    try:
        with db_context(commit=False) as db:
            rows = db.execute("""
                SELECT COUNT(*) FROM brain_states
                WHERE user_id = ? AND created_at > ?
            """, (user_id, (datetime.utcnow() - timedelta(days=7)).isoformat())).fetchone()
            if rows:
                signals['weekly_interactions'] = rows[0] or 0
    except Exception:
        pass

    # Signal 4: Agent observations about cognitive issues
    try:
        with db_context(commit=False) as db:
            obs = db.execute("""
                SELECT COUNT(*) FROM agent_observations
                WHERE user_id = ? AND created_at > ?
                AND observation_type LIKE '%confusion%' OR summary LIKE '%paměť%' OR summary LIKE '%zapomín%'
            """, (user_id, (datetime.utcnow() - timedelta(days=30)).isoformat())).fetchone()
            if obs:
                signals['confusion_events'] = obs[0] or 0
    except Exception:
        pass

    # Compute composite score
    score = 70  # baseline
    components = []

    if 'quiz_accuracy' in signals:
        quiz_score = signals['quiz_accuracy']['value']
        score += (quiz_score - 60) * 0.3  # +/- based on accuracy
        components.append(f"Kvízy: {quiz_score:.0f}% správně")

    if 'coherence_current' in signals:
        c = signals['coherence_current']
        score += (c - 4.0) * 5  # C=4.0 is baseline
        components.append(f"Koherence: {c:.1f}/10")

    if 'coherence_trend' in signals:
        trend = signals['coherence_trend']
        if trend < -0.5:
            score -= 10
            components.append(f"Trend: klesající ({trend:+.1f})")
        elif trend > 0.5:
            score += 5
            components.append(f"Trend: rostoucí ({trend:+.1f})")
        else:
            components.append(f"Trend: stabilní ({trend:+.1f})")

    if 'weekly_interactions' in signals:
        interactions = signals['weekly_interactions']
        if interactions > 20:
            score += 5
        elif interactions < 5:
            score -= 10
        components.append(f"Aktivita: {interactions} za týden")

    if signals.get('confusion_events', 0) > 3:
        score -= 15
        components.append(f"Zmatenost: {signals['confusion_events']}× za měsíc")

    score = max(0, min(100, round(score)))

    # Determine trend label
    trend = 'stable'
    if 'coherence_trend' in signals:
        if signals['coherence_trend'] < -0.5:
            trend = 'declining'
        elif signals['coherence_trend'] > 0.5:
            trend = 'improving'

    # Recommendations
    recommendations = []
    if score < 50:
        recommendations.append('Doporučujeme konzultaci s lékařem ohledně kognitivních funkcí.')
        recommendations.append('Denní trénink paměti (kvízy, cvičení) může pomoci.')
    elif score < 70:
        recommendations.append('Pravidelné kvízy a mentální aktivita pomáhají udržet paměť.')
        recommendations.append('Sociální kontakt je důležitý — volejte rodině.')
    else:
        recommendations.append('Kognitivní funkce jsou v normě. Pokračujte v aktivitách.')

    return {
        'score': score,
        'trend': trend,
        'trend_label': {'stable': 'Stabilní', 'improving': 'Zlepšující se', 'declining': 'Klesající'}.get(trend, trend),
        'components': components,
        'signals': signals,
        'recommendations': recommendations,
        'assessed_at': datetime.utcnow().isoformat()
    }


def get_cognitive_history(user_id, days=90):
    """Get cognitive score history for trend visualization."""
    # We compute weekly snapshots from brain_states
    history = []
    try:
        with db_context(commit=False) as db:
            # Weekly averages of coherence
            rows = db.execute("""
                SELECT
                    DATE(created_at) as day,
                    AVG(coherence) as avg_c,
                    COUNT(*) as interactions
                FROM brain_states
                WHERE user_id = ? AND created_at > ?
                GROUP BY DATE(created_at)
                ORDER BY day
            """, (user_id, (datetime.utcnow() - timedelta(days=days)).isoformat())).fetchall()

            for row in (rows or []):
                c = row[1] or 4.0
                score = max(0, min(100, round(70 + (c - 4.0) * 5)))
                history.append({
                    'date': str(row[0]),
                    'score': score,
                    'coherence': round(c, 2),
                    'interactions': row[2]
                })
    except Exception as e:
        logger.debug(f"Cognitive history error: {e}")

    return history
