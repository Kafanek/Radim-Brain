"""
📊 SURVEY ROUTES v1.0 — Dotazníky za odměnu
=============================================
Seniors answer daily questions → earn points → badges → rewards.

Endpoints:
    GET  /api/surveys/today       — Get today's survey for user
    POST /api/surveys/respond     — Submit survey response + earn points
    GET  /api/surveys/rewards     — Get user's points + badges
    GET  /api/surveys/history     — Response history
    POST /api/surveys/create      — Create survey (admin)
"""

import logging
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g

from auth_middleware import optional_auth, require_auth
from database import db_context, db_insert

logger = logging.getLogger(__name__)

survey_bp = Blueprint('surveys', __name__)

# ============================================================================
# DEFAULT DAILY SURVEYS — built-in, no DB needed
# ============================================================================

DAILY_SURVEYS = [
    {
        'id': 'mood',
        'title': '😊 Jak se dnes cítíte?',
        'type': 'daily',
        'reward_points': 10,
        'questions': [
            {
                'id': 'mood_score',
                'text': 'Jak se dnes cítíte?',
                'type': 'emoji_scale',
                'options': [
                    {'value': 1, 'label': '😢 Špatně'},
                    {'value': 2, 'label': '😕 Nic moc'},
                    {'value': 3, 'label': '😐 Normálně'},
                    {'value': 4, 'label': '🙂 Dobře'},
                    {'value': 5, 'label': '😄 Výborně'},
                ]
            }
        ]
    },
    {
        'id': 'health',
        'title': '💊 Zdravotní kontrola',
        'type': 'daily',
        'reward_points': 15,
        'questions': [
            {
                'id': 'pain',
                'text': 'Bolí vás dnes něco?',
                'type': 'yes_no',
                'followup': 'Co vás bolí?'
            },
            {
                'id': 'sleep',
                'text': 'Jak jste spal/a?',
                'type': 'emoji_scale',
                'options': [
                    {'value': 1, 'label': '😫 Špatně'},
                    {'value': 2, 'label': '😴 Ujde to'},
                    {'value': 3, 'label': '😌 Dobře'},
                    {'value': 4, 'label': '😊 Výborně'},
                ]
            },
            {
                'id': 'meds',
                'text': 'Vzal/a jste dnes léky?',
                'type': 'yes_no'
            }
        ]
    },
    {
        'id': 'activity',
        'title': '🚶 Denní aktivita',
        'type': 'daily',
        'reward_points': 10,
        'questions': [
            {
                'id': 'went_outside',
                'text': 'Byl/a jste dnes venku?',
                'type': 'yes_no'
            },
            {
                'id': 'social',
                'text': 'Mluvil/a jste dnes s někým?',
                'type': 'yes_no'
            },
            {
                'id': 'meal',
                'text': 'Co jste měl/a k obědu?',
                'type': 'open_text'
            }
        ]
    },
    {
        'id': 'safety',
        'title': '🏠 Pocit bezpečí',
        'type': 'weekly',
        'reward_points': 20,
        'questions': [
            {
                'id': 'safety_score',
                'text': 'Cítíte se doma bezpečně?',
                'type': 'emoji_scale',
                'options': [
                    {'value': 1, 'label': '😰 Vůbec ne'},
                    {'value': 2, 'label': '😟 Spíše ne'},
                    {'value': 3, 'label': '😐 Tak napůl'},
                    {'value': 4, 'label': '🙂 Spíše ano'},
                    {'value': 5, 'label': '😊 Naprosto'},
                ]
            },
            {
                'id': 'improvement',
                'text': 'Co by vám pomohlo cítit se lépe?',
                'type': 'open_text'
            }
        ]
    },
]

# Badge definitions
BADGES = [
    {'id': 'first_survey', 'name': '🌟 První odpověď', 'points_needed': 10, 'icon': '🌟'},
    {'id': 'bronze', 'name': '🏅 Bronzový pomocník', 'points_needed': 50, 'icon': '🏅'},
    {'id': 'silver', 'name': '🥈 Stříbrný pomocník', 'points_needed': 200, 'icon': '🥈'},
    {'id': 'gold', 'name': '🥇 Zlatý pomocník', 'points_needed': 500, 'icon': '🥇'},
    {'id': 'streak_7', 'name': '🔥 7 dní v řadě', 'points_needed': 0, 'icon': '🔥'},
    {'id': 'streak_30', 'name': '💎 30 dní v řadě', 'points_needed': 0, 'icon': '💎'},
]


def _extract_user_id():
    auth_user = getattr(g, 'auth_user', None)
    if auth_user and auth_user.get('id'):
        return str(auth_user['id'])
    return request.args.get('user_id', request.json.get('user_id', '') if request.json else '')


# ============================================================================
# ENDPOINTS
# ============================================================================

@survey_bp.route('/api/surveys/today', methods=['GET'])
@optional_auth
def get_today_survey():
    """Get next unanswered survey for today."""
    user_id = _extract_user_id()

    # Check which surveys user already answered today
    answered_today = set()
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).isoformat()
        with db_context() as db:
            rows = db.execute(
                "SELECT answers->>'survey_id' as sid FROM survey_responses "
                "WHERE user_id = ? AND created_at >= ?",
                (user_id, today_start)
            ).fetchall()
            for r in rows:
                sid = r[0] if isinstance(r, (list, tuple)) else r.get('sid', '')
                if sid:
                    answered_today.add(sid)
    except Exception:
        pass

    # Find first unanswered daily survey
    for survey in DAILY_SURVEYS:
        if survey['type'] == 'daily' and survey['id'] not in answered_today:
            return jsonify({'success': True, 'survey': survey, 'answered_today': len(answered_today)})

    # All done for today
    return jsonify({
        'success': True,
        'survey': None,
        'answered_today': len(answered_today),
        'message': 'Všechny dotazníky na dnes jsou splněné! 🎉'
    })


@survey_bp.route('/api/surveys/respond', methods=['POST'])
@optional_auth
def submit_response():
    """Submit survey response + award points."""
    user_id = _extract_user_id()
    data = request.json or {}
    survey_id = data.get('survey_id', '')
    answers = data.get('answers', [])
    source = data.get('source', 'ui')  # 'ui' or 'voice'

    if not survey_id or not answers:
        return jsonify({'success': False, 'error': 'survey_id a answers jsou povinné'}), 400

    # Find survey definition
    survey = next((s for s in DAILY_SURVEYS if s['id'] == survey_id), None)
    points = survey['reward_points'] if survey else 10

    try:
        with db_context(commit=True) as db:
            # Save response
            db_insert(db, 'survey_responses',
                ['survey_id', 'user_id', 'answers', 'points_earned', 'source'],
                (0, user_id, json.dumps({'survey_id': survey_id, 'answers': answers}), points, source)
            )

            # Update rewards
            row = db.execute(
                "SELECT total_points, streak_days, last_survey_at, badges FROM survey_rewards WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            if row:
                total = (row[0] if isinstance(row, (list, tuple)) else row.get('total_points', 0)) + points
                streak = row[1] if isinstance(row, (list, tuple)) else row.get('streak_days', 0)
                last_at = row[2] if isinstance(row, (list, tuple)) else row.get('last_survey_at')
                existing_badges = json.loads(row[3] if isinstance(row, (list, tuple)) else row.get('badges', '[]') or '[]')

                # Streak check
                if last_at:
                    try:
                        last_date = last_at.date() if hasattr(last_at, 'date') else datetime.fromisoformat(str(last_at).replace('Z', '')).date()
                        today = datetime.utcnow().date()
                        if (today - last_date).days == 1:
                            streak += 1
                        elif (today - last_date).days > 1:
                            streak = 1
                    except Exception:
                        streak = 1
                else:
                    streak = 1

                # Check new badges
                new_badges = []
                for badge in BADGES:
                    if badge['id'] not in existing_badges:
                        if badge['points_needed'] > 0 and total >= badge['points_needed']:
                            existing_badges.append(badge['id'])
                            new_badges.append(badge)
                        elif badge['id'] == 'streak_7' and streak >= 7:
                            existing_badges.append(badge['id'])
                            new_badges.append(badge)
                        elif badge['id'] == 'streak_30' and streak >= 30:
                            existing_badges.append(badge['id'])
                            new_badges.append(badge)

                # Determine level
                level = 'starter'
                if total >= 500:
                    level = 'gold'
                elif total >= 200:
                    level = 'silver'
                elif total >= 50:
                    level = 'bronze'

                db.execute(
                    "UPDATE survey_rewards SET total_points = ?, streak_days = ?, level = ?, "
                    "badges = ?, last_survey_at = NOW(), updated_at = NOW() WHERE user_id = ?",
                    (total, streak, level, json.dumps(existing_badges), user_id)
                )
            else:
                total = points
                streak = 1
                new_badges = [BADGES[0]] if points >= 10 else []  # first_survey badge
                existing_badges = [b['id'] for b in new_badges]
                level = 'starter'
                db.execute(
                    "INSERT INTO survey_rewards (user_id, total_points, level, badges, streak_days, last_survey_at) "
                    "VALUES (?, ?, ?, ?, ?, NOW())",
                    (user_id, total, level, json.dumps(existing_badges), streak)
                )

        result = {
            'success': True,
            'points_earned': points,
            'total_points': total,
            'streak_days': streak,
            'level': level,
            'new_badges': [{'name': b['name'], 'icon': b['icon']} for b in new_badges] if new_badges else [],
            'message': f'Děkuji! +{points} bodů 🌟'
        }

        if new_badges:
            result['message'] += f' Nový badge: {new_badges[0]["name"]}!'

        return jsonify(result)

    except Exception as e:
        logger.error(f"Survey response error: {e}")
        return jsonify({'success': False, 'error': 'Chyba při ukládání'}), 500


@survey_bp.route('/api/surveys/rewards', methods=['GET'])
@optional_auth
def get_rewards():
    """Get user's points, badges, streak."""
    user_id = _extract_user_id()

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT total_points, level, badges, streak_days, last_survey_at FROM survey_rewards WHERE user_id = ?",
                (user_id,)
            ).fetchone()

        if row:
            badges_ids = json.loads(row[3] if isinstance(row, (list, tuple)) else row.get('badges', '[]') or '[]')
            badges_full = [b for b in BADGES if b['id'] in badges_ids]
            next_badge = next((b for b in BADGES if b['id'] not in badges_ids and b['points_needed'] > 0), None)

            return jsonify({
                'success': True,
                'total_points': row[0] if isinstance(row, (list, tuple)) else row.get('total_points', 0),
                'level': row[1] if isinstance(row, (list, tuple)) else row.get('level', 'starter'),
                'badges': [{'name': b['name'], 'icon': b['icon']} for b in badges_full],
                'streak_days': row[2] if isinstance(row, (list, tuple)) else row.get('streak_days', 0),
                'next_badge': {'name': next_badge['name'], 'points_needed': next_badge['points_needed']} if next_badge else None,
            })
        else:
            return jsonify({
                'success': True,
                'total_points': 0,
                'level': 'starter',
                'badges': [],
                'streak_days': 0,
                'next_badge': {'name': BADGES[0]['name'], 'points_needed': BADGES[0]['points_needed']},
            })

    except Exception as e:
        logger.error(f"Rewards error: {e}")
        return jsonify({'success': True, 'total_points': 0, 'level': 'starter', 'badges': [], 'streak_days': 0})


@survey_bp.route('/api/surveys/history', methods=['GET'])
@optional_auth
def get_history():
    """Get user's survey response history."""
    user_id = _extract_user_id()
    days = request.args.get('days', 30, type=int)

    try:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with db_context() as db:
            rows = db.execute(
                "SELECT id, answers, points_earned, source, created_at FROM survey_responses "
                "WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 100",
                (user_id, since)
            ).fetchall()

        history = []
        for r in rows:
            history.append({
                'id': r[0] if isinstance(r, (list, tuple)) else r.get('id'),
                'answers': json.loads(r[1] if isinstance(r, (list, tuple)) else r.get('answers', '{}')),
                'points': r[2] if isinstance(r, (list, tuple)) else r.get('points_earned', 0),
                'source': r[3] if isinstance(r, (list, tuple)) else r.get('source', 'ui'),
                'date': str(r[4] if isinstance(r, (list, tuple)) else r.get('created_at', '')),
            })

        return jsonify({'success': True, 'history': history, 'count': len(history)})

    except Exception as e:
        logger.error(f"Survey history error: {e}")
        return jsonify({'success': True, 'history': [], 'count': 0})


logger.info("📊 Survey routes v1.0 loaded — dotazníky za odměnu")
