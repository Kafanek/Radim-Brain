"""
📰 Morning News Briefing — daily push at 08:05
=============================================================================
Fetches the 3 top general-news articles (from real Czech RSS feeds via
news_routes._fetch_via_rss), then webpushes a summary to every device with
a push_subscriptions row. Tap on the notification opens /?news=1 → the
news module auto-opens.

Triggered by APScheduler cron (Europe/Prague) at 08:05. Also callable
manually via `/api/admin/news-briefing-test` with ADMIN_SECRET.
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)


def _load_subscriptions():
    """Return list of {user_id, endpoint, keys} from push_subscriptions."""
    try:
        from database import db_context
        with db_context(commit=False) as db:
            rows = db.execute(
                "SELECT user_id, endpoint, keys FROM push_subscriptions"
            ).fetchall()
        out = []
        for row in rows or []:
            keys = row[2]
            if isinstance(keys, str):
                try: keys = json.loads(keys)
                except Exception: keys = {}
            out.append({'user_id': row[0], 'endpoint': row[1], 'keys': keys or {}})
        return out
    except Exception as e:
        logger.warning(f"briefing: subscription load failed: {e}")
        return []


def _drop_subscription(endpoint):
    """Remove a push subscription row — used when webpush returns 404/410 (gone)."""
    try:
        from database import db_context
        with db_context(commit=True) as db:
            db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    except Exception as e:
        logger.debug(f"briefing: drop-sub failed: {e}")


def _build_payload(articles):
    """Compose the push payload from the top 3 fetched articles."""
    if not articles:
        return None
    first_title = (articles[0].get('title') or '').strip()
    # Body shows up in the OS notification; keep short (~140 chars max)
    if len(articles) >= 2:
        body = f"{first_title} · {articles[1].get('title', '')}"
    else:
        body = first_title
    return {
        'title':    '📰 Ranní zprávy',
        'body':     body[:180],
        'severity': 'info',
        'type':     'morning_news',
        'url':      '/?news=1',
    }


def _send(subscription, payload_json, vapid_priv, vapid_sub):
    """Send one WebPush. Returns (ok, status_code_if_gone)."""
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return False, None
    try:
        webpush(
            subscription_info={
                'endpoint': subscription['endpoint'],
                'keys':     subscription['keys'],
            },
            data=payload_json,
            vapid_private_key=vapid_priv,
            vapid_claims={'sub': vapid_sub},
        )
        return True, None
    except WebPushException as e:
        # Check for 404/410 — subscription is dead
        status = getattr(getattr(e, 'response', None), 'status_code', None)
        if status in (404, 410):
            return False, status
        logger.debug(f"briefing: webpush error {status}: {e}")
        return False, None
    except Exception as e:
        logger.debug(f"briefing: webpush exc: {e}")
        return False, None


def run_morning_news_briefing(app=None):
    """Entry point called by APScheduler at 08:05. Safe to call manually."""
    vapid_priv = os.environ.get('VAPID_PRIVATE_KEY')
    vapid_sub = os.environ.get('VAPID_CLAIMS_EMAIL', 'mailto:info@radimcare.cz')
    if not vapid_priv:
        logger.warning("briefing: VAPID_PRIVATE_KEY missing — skipping")
        return {'sent': 0, 'skipped': True, 'reason': 'no_vapid'}

    # Fetch top 3 general news (uses real RSS + Gemini summary pipeline)
    try:
        from news_routes import _fetch_via_rss
        articles = _fetch_via_rss('general', 3) or []
    except Exception as e:
        logger.warning(f"briefing: RSS fetch failed: {e}")
        articles = []

    if not articles:
        logger.info("briefing: no articles available — skipping push")
        return {'sent': 0, 'skipped': True, 'reason': 'no_articles'}

    payload = _build_payload(articles)
    payload_json = json.dumps(payload, ensure_ascii=False)

    subs = _load_subscriptions()
    if not subs:
        logger.info("briefing: 0 push subscriptions — nothing to send")
        return {'sent': 0, 'skipped': True, 'reason': 'no_subscribers', 'articles': len(articles)}

    sent, dropped, failed = 0, 0, 0
    for sub in subs:
        ok, gone_status = _send(sub, payload_json, vapid_priv, vapid_sub)
        if ok:
            sent += 1
        elif gone_status in (404, 410):
            _drop_subscription(sub['endpoint'])
            dropped += 1
        else:
            failed += 1

    logger.info(
        f"📰 Morning briefing: sent={sent} dropped={dropped} failed={failed} "
        f"top='{articles[0].get('title','')[:60]}'"
    )
    return {
        'sent': sent,
        'dropped': dropped,
        'failed': failed,
        'articles': len(articles),
        'top_title': articles[0].get('title', '')[:120],
        'at': int(time.time()),
    }
