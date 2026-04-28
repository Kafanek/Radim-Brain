"""
📊 SURVEY TELEMETRY & QUALITY v1.0
====================================
Analytics, alert review, quality metrics, empathetic responses.

Tracks:
    - survey_started / survey_completed / question_skipped
    - tts_replayed / followup_triggered
    - submission_duration_sec
    - risk_score_generated / alert_generated / memory_hint_injected

Alert review:
    - new → reviewed / dismissed / escalated
    - caregiver notes + feedback (valid/uncertain/false_positive)

Quality dashboard:
    - completion rate, avg time, follow-up %, alerts/week
    - false positive rate from caregiver feedback

Empathetic responses:
    - Context-aware post-submit messages
    - Trend-aware ("dnes klidněji než minule")
"""

import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

try:
    from database import db_context, db_insert, is_postgres
    from memory_helpers import db_load_learning
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

def _parse_json_or_dict(val):
    """Parse JSON string or return dict as-is (PG JSONB auto-parses)."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {'raw': val}
    return {}


telemetry_bp = Blueprint('survey_telemetry', __name__)


# ═══════════════════════════════════════════════════════════════════
# TELEMETRY — event tracking
# ═══════════════════════════════════════════════════════════════════

@telemetry_bp.route('/api/surveys/telemetry', methods=['POST'])
def log_telemetry():
    """Log survey analytics event.

    Body: {
        "user_id": "...",
        "event": "survey_started" | "survey_completed" | "question_skipped" |
                 "tts_replayed" | "followup_triggered" | "voice_answer",
        "data": { ... optional metadata }
    }
    """
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id', '')
    event = data.get('event', '')
    meta = data.get('data', {})

    if not event:
        return jsonify({'success': False, 'error': 'event required'}), 400

    try:
        with db_context(commit=True) as db:
            # Use survey_responses table with special survey_id for telemetry
            db.execute(
                "INSERT INTO survey_responses (user_id, answers, points_earned, source) VALUES (?, ?, 0, ?)",
                (user_id or 'anonymous',
                 json.dumps({'survey_id': '_telemetry', 'event': event, **meta}),
                 'telemetry')
            )
    except Exception as e:
        logger.debug(f"Telemetry save error: {e}")

    return jsonify({'success': True, 'event': event})


# ═══════════════════════════════════════════════════════════════════
# ALERT REVIEW — caregiver feedback on alerts
# ═══════════════════════════════════════════════════════════════════

@telemetry_bp.route('/api/surveys/alert-review', methods=['POST'])
def review_alert():
    """Caregiver reviews a survey alert.

    Body: {
        "user_id": "senior-id",
        "alert_timestamp": "ISO timestamp",
        "status": "reviewed" | "dismissed" | "escalated",
        "feedback": "valid" | "uncertain" | "false_positive",
        "note": "optional caregiver note"
    }
    """
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id', '')
    status = data.get('status', 'reviewed')
    feedback = data.get('feedback', '')
    note = data.get('note', '')

    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    try:
        # Save review to learning memory
        learning = db_load_learning(user_id)
        reviews = learning.get('alert_reviews', [])
        reviews.append({
            'status': status,
            'feedback': feedback,
            'note': note,
            'alert_timestamp': data.get('alert_timestamp', ''),
            'reviewed_at': datetime.utcnow().isoformat(),
            'reviewer': data.get('reviewer', 'caregiver')
        })
        learning['alert_reviews'] = reviews[-50:]  # Keep 50

        # Update learning agent with feedback
        if feedback == 'false_positive':
            learning['false_positives'] = learning.get('false_positives', 0) + 1
        elif feedback == 'valid':
            learning['true_positives'] = learning.get('true_positives', 0) + 1

        from memory_helpers import db_save_learning
        db_save_learning(user_id, learning)

        return jsonify({'success': True, 'message': 'Review zaznamenáno', 'status': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@telemetry_bp.route('/api/surveys/alert-reviews/<user_id>', methods=['GET'])
def get_alert_reviews(user_id):
    """Get alert review history for a senior."""
    try:
        learning = db_load_learning(user_id)
        reviews = learning.get('alert_reviews', [])
        fp = learning.get('false_positives', 0)
        tp = learning.get('true_positives', 0)
        total = fp + tp
        fp_rate = round(fp / total * 100, 1) if total > 0 else 0

        return jsonify({
            'success': True,
            'reviews': reviews[-20:],
            'stats': {
                'total_reviews': total,
                'true_positives': tp,
                'false_positives': fp,
                'false_positive_rate': fp_rate,
                'sensitivity': learning.get('agent_sensitivity', 1.0)
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
# QUALITY DASHBOARD — aggregated metrics
# ═══════════════════════════════════════════════════════════════════

def _answers_like(pattern):
    """LIKE query on answers column — handles PG JSONB vs SQLite TEXT."""
    if is_postgres():
        return f"answers::text LIKE '%{pattern}%'"
    return f"answers LIKE '%{pattern}%'"


@telemetry_bp.route('/api/surveys/quality', methods=['GET'])
def quality_dashboard():
    """Survey quality metrics for admin/caregiver dashboard.

    Returns: completion rate, avg time, follow-up %, alerts/week, FP rate.
    """
    days = int(request.args.get('days', 7))
    user_id = request.args.get('user_id', '')  # Optional: filter by user

    try:
        with db_context() as db:
            # Total surveys submitted
            if is_postgres():
                date_filter = f"created_at > NOW() - INTERVAL '{days} days'"
            else:
                date_filter = f"created_at > datetime('now', '-{days} days')"

            user_filter = f" AND user_id = '{user_id}'" if user_id else ""

            # JSONB text cast for LIKE queries
            ans_col = "answers::text" if is_postgres() else "answers"

            # 1. Total responses
            row = db.execute(
                f"SELECT COUNT(*) FROM survey_responses WHERE source != 'telemetry' AND {date_filter}{user_filter}"
            ).fetchone()
            total_responses = row[0] if row else 0

            # 2. Telemetry events
            started = db.execute(
                f"SELECT COUNT(*) FROM survey_responses WHERE source = 'telemetry' "
                f"AND {ans_col} LIKE '%survey_started%' AND {date_filter}{user_filter}"
            ).fetchone()
            started_count = started[0] if started else 0

            completed = db.execute(
                f"SELECT COUNT(*) FROM survey_responses WHERE source = 'telemetry' "
                f"AND {ans_col} LIKE '%survey_completed%' AND {date_filter}{user_filter}"
            ).fetchone()
            completed_count = completed[0] if completed else 0

            followups = db.execute(
                f"SELECT COUNT(*) FROM survey_responses WHERE source = 'telemetry' "
                f"AND {ans_col} LIKE '%followup_triggered%' AND {date_filter}{user_filter}"
            ).fetchone()
            followup_count = followups[0] if followups else 0

            tts_replays = db.execute(
                f"SELECT COUNT(*) FROM survey_responses WHERE source = 'telemetry' "
                f"AND {ans_col} LIKE '%tts_replayed%' AND {date_filter}{user_filter}"
            ).fetchone()
            tts_replay_count = tts_replays[0] if tts_replays else 0

            # 3. Unique active seniors
            users = db.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM survey_responses WHERE source != 'telemetry' AND {date_filter}"
            ).fetchone()
            active_seniors = users[0] if users else 0

            # 4. Alerts from agent_observations
            alerts = db.execute(
                f"SELECT COUNT(*) FROM agent_observations WHERE observation_type = 'survey_risk' AND {date_filter}"
            ).fetchone()
            alert_count = alerts[0] if alerts else 0

        # Compute rates
        completion_rate = round(completed_count / max(started_count, 1) * 100, 1)
        followup_rate = round(followup_count / max(total_responses, 1) * 100, 1)

        # Get FP rate from learning (aggregated)
        fp_total = 0
        tp_total = 0
        if not user_id:
            # Aggregate across all users (simplified — read from a few active users)
            try:
                from agent_loop import _get_active_users
                for uid in _get_active_users()[:20]:
                    learn = db_load_learning(uid)
                    fp_total += learn.get('false_positives', 0)
                    tp_total += learn.get('true_positives', 0)
            except Exception:
                pass
        else:
            learn = db_load_learning(user_id)
            fp_total = learn.get('false_positives', 0)
            tp_total = learn.get('true_positives', 0)

        review_total = fp_total + tp_total
        fp_rate = round(fp_total / max(review_total, 1) * 100, 1)

        return jsonify({
            'success': True,
            'period_days': days,
            'metrics': {
                'total_responses': total_responses,
                'active_seniors': active_seniors,
                'surveys_started': started_count,
                'surveys_completed': completed_count,
                'completion_rate': completion_rate,
                'followup_triggered': followup_count,
                'followup_rate': followup_rate,
                'tts_replayed': tts_replay_count,
                'alerts_generated': alert_count,
                'alerts_per_week': round(alert_count / max(days / 7, 1), 1),
                'false_positive_rate': fp_rate,
                'reviews_total': review_total,
            },
            'targets': {
                'completion_rate': '>75%',
                'false_positive_rate': '<25%',
                'avg_completion_time': '<2.5 min',
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
# DATA EXPORT — for analysis
# ═══════════════════════════════════════════════════════════════════

@telemetry_bp.route('/api/surveys/export', methods=['GET'])
def export_survey_data():
    """Export survey data for analysis (last N days)."""
    days = int(request.args.get('days', 30))
    user_id = request.args.get('user_id', '')

    try:
        with db_context() as db:
            if is_postgres():
                date_filter = f"created_at > NOW() - INTERVAL '{days} days'"
            else:
                date_filter = f"created_at > datetime('now', '-{days} days')"

            user_filter = f" AND user_id = '{user_id}'" if user_id else ""

            rows = db.execute(
                f"SELECT user_id, answers, points_earned, source, created_at "
                f"FROM survey_responses WHERE source != 'telemetry' AND {date_filter}{user_filter} "
                f"ORDER BY created_at DESC LIMIT 500"
            ).fetchall()

            data = []
            for r in rows:
                data.append({
                    'user_id': r[0] if isinstance(r, (list, tuple)) else r.get('user_id'),
                    'answers': _parse_json_or_dict(r[1] if isinstance(r, (list, tuple)) else r.get('answers', '{}')),
                    'points': r[2] if isinstance(r, (list, tuple)) else r.get('points_earned'),
                    'source': r[3] if isinstance(r, (list, tuple)) else r.get('source'),
                    'created_at': str(r[4] if isinstance(r, (list, tuple)) else r.get('created_at')),
                })

        return jsonify({'success': True, 'data': data, 'count': len(data), 'period_days': days})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
# EMPATHETIC POST-SUBMIT RESPONSES
# ═══════════════════════════════════════════════════════════════════

def generate_empathetic_response(user_id, answers, survey_risk=None):
    """Generate context-aware empathetic response after survey submission.

    Not generic "Děkuji!" — but trend-aware, warm, personal.
    """
    # Analyze what was submitted
    mood_val = None
    sleep_val = None
    pain_val = None

    for a in answers:
        aid = a.get('id', '')
        val = a.get('value')
        if 'mood' in aid and isinstance(val, (int, float)):
            mood_val = val
        if 'sleep' in aid and isinstance(val, (int, float)):
            sleep_val = val
        if 'pain' in aid:
            pain_val = val

    # Get yesterday's data for comparison
    yesterday_mood = _get_yesterday_value(user_id, 'mood')

    # Build response
    parts = []

    # Appreciation (always)
    parts.append("Děkuji, že jste si udělal/a chvíli pro sebe.")

    # Mood-specific
    if mood_val is not None:
        if mood_val >= 4:
            parts.append("Jsem rád, že se dnes cítíte dobře! 😊")
        elif mood_val == 3:
            if yesterday_mood and yesterday_mood < 3:
                parts.append("Dnes to vypadá trochu lépe než včera. To je dobrá zpráva.")
            else:
                parts.append("Normální den. Někdy to stačí.")
        elif mood_val <= 2:
            if yesterday_mood and yesterday_mood <= 2:
                parts.append("Zdá se, že poslední dny nejsou lehké. Jsem tu pro vás, kdykoli budete chtít.")
            else:
                parts.append("Dnes to není snadné. Chcete si popovídat nebo pustit něco příjemného?")

    # Sleep
    if sleep_val is not None and sleep_val <= 2:
        parts.append("Špatný spánek umí ztížit celý den. Zkusíme večer relaxaci?")

    # Pain
    if pain_val == 1:
        parts.append("Bolest není nic příjemného. Kdykoli potřebujete, jsem tu.")

    return ' '.join(parts)


def _get_yesterday_value(user_id, dimension):
    """Get yesterday's answer value for a dimension."""
    if not _AVAILABLE:
        return None
    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT answers FROM survey_responses WHERE user_id = ? "
                    "AND created_at > NOW() - INTERVAL '2 days' AND created_at < NOW() - INTERVAL '1 day' "
                    "AND source != 'telemetry' ORDER BY created_at DESC LIMIT 3",
                    (user_id,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT answers FROM survey_responses WHERE user_id = ? "
                    "AND created_at > datetime('now', '-2 days') AND created_at < datetime('now', '-1 day') "
                    "AND source != 'telemetry' ORDER BY created_at DESC LIMIT 3",
                    (user_id,)
                ).fetchall()

            for r in rows:
                try:
                    data = json.loads(r[0] if isinstance(r, (list, tuple)) else r.get('answers', '{}'))
                    for a in data.get('answers', []):
                        if dimension in a.get('id', '') and isinstance(a.get('value'), (int, float)):
                            return a['value']
                except Exception:
                    pass
    except Exception:
        pass
    return None


logger.info("📊 Survey Telemetry v1.0 loaded — events, reviews, quality dashboard, empathetic responses")
