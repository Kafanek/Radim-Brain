"""
🚌 AGENT MESSAGE BUS — Sprint AG.4
==============================================================
Single source of truth for "what agents currently know about user X".

Three layers (chat coordinator, agent_loop, specialists) emit AND read
messages so they stop duplicating detection and start sharing context.

  Producers              Bus                    Consumers
  ─────────────          ─────                  ─────────
  radim_orchestrator ──→ emit ──┐         ┌──→ chat coordinator
  agent_loop         ──→ emit ──┼─→ DB ──┼──→ agent_loop dedupe
  anticipation       ──→ emit ──┤         ├──→ caregiver inbox (mirror)
  specialists        ──→ emit ──┘         └──→ admin debug

API
───
  emit(user_id, sender, kind, severity, topic, payload, ttl_minutes,
       correlates_with) → int (msg_id)
  recent(user_id, since=None, kinds=None, severity_min='info',
         topics=None, limit=50) → list[dict]
  context(user_id, lookback_minutes=30, max_items=20) → list[dict]
  dedupe(user_id, sender, topic, within_minutes=15) → bool
  prune() → int

Kinds
─────
  user_input    short — what the senior just said (15 min TTL)
  context       medium — anticipation hints, baseline drift (30 min)
  observation   long — same data agent_observations has (24 h)
  intent        short — resolved local intent (15 min)
  decision      medium — coordinator picked an action (60 min)
  ack           short — caregiver/user dismissed an alert (15 min)

Backwards compat
────────────────
  agent_observations table is preserved. emit(kind='observation') ALSO
  inserts into agent_observations so the existing caregiver inbox API,
  admin endpoints, and acknowledged_at flow keep working unchanged.
"""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

try:
    from database import db_context, db_insert, is_postgres
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    logger.warning("agent_bus: database module unavailable — operations are no-ops")


# Default TTL per kind (minutes)
_TTL_DEFAULTS = {
    'user_input': 15,
    'intent': 15,
    'ack': 15,
    'context': 30,
    'decision': 60,
    'observation': 1440,   # 24 hours — matches agent_observations 24h window
}

_VALID_KINDS = set(_TTL_DEFAULTS.keys())
_VALID_SEVERITIES = {'info', 'warning', 'alert', 'crisis'}

# Severity ordering for "severity_min" filtering
_SEV_ORDER = {'info': 0, 'warning': 1, 'alert': 2, 'crisis': 3}


def _norm_severity(sev):
    s = (sev or 'info').lower()
    return s if s in _VALID_SEVERITIES else 'info'


def _now_iso():
    return datetime.utcnow().isoformat()


def emit(user_id, sender, kind, severity='info', topic='',
         payload=None, ttl_minutes=None, correlates_with=None):
    """Publish a message to the bus.

    Args:
        user_id: senior identifier this message is about (NOT sender's id)
        sender: short string identifying which agent emitted this
                ('safety_agent', 'agent_loop.recent_chat_crisis',
                 'anticipation', 'sleep_agent', 'chat_user_input', ...)
        kind: see _VALID_KINDS — controls default TTL + mirroring policy
        severity: 'info' | 'warning' | 'alert' | 'crisis'
        topic: short tag for dedupe + filtering ('fall', 'isolation', …)
        payload: dict, JSON-serializable structured data
        ttl_minutes: override default TTL for this kind
        correlates_with: int, parent message id (for ack/thread chains)

    Returns:
        int msg_id, or None on failure (never raises — bus is non-critical)
    """
    if not _DB_AVAILABLE:
        return None
    if not user_id or not sender or not kind or not topic:
        logger.debug(f"agent_bus.emit: missing required field "
                     f"(user_id={user_id} sender={sender} kind={kind} topic={topic})")
        return None
    if kind not in _VALID_KINDS:
        logger.debug(f"agent_bus.emit: unknown kind {kind!r}, defaulting to context")
        kind = 'context'

    severity = _norm_severity(severity)
    if ttl_minutes is None:
        ttl_minutes = _TTL_DEFAULTS.get(kind, 30)
    # SQLite default CURRENT_TIMESTAMP format is 'YYYY-MM-DD HH:MM:SS'
    # (space, no 'T'). To keep our expires_at comparable with both
    # CURRENT_TIMESTAMP and DB-native NOW()/datetime('now'), format the
    # same way (strftime instead of isoformat). PG TIMESTAMP accepts
    # both formats so this is safe across backends.
    expires_at_iso = (datetime.utcnow() + timedelta(minutes=int(ttl_minutes))
                      ).strftime('%Y-%m-%d %H:%M:%S')

    payload_json = json.dumps(payload or {}, ensure_ascii=False)

    msg_id = None
    try:
        with db_context(commit=True) as db:
            msg_id = db_insert(
                db, 'agent_messages',
                ['user_id', 'sender', 'kind', 'severity', 'topic',
                 'payload', 'expires_at', 'correlates_with'],
                [str(user_id), str(sender)[:80], kind, severity, topic[:120],
                 payload_json, expires_at_iso, correlates_with],
            )
    except Exception as e:
        # Bus failure must never block the producing flow.
        logger.warning(f"agent_bus.emit DB error: {e}")
        return None

    # Mirror observations into agent_observations so caregiver inbox +
    # existing admin endpoints keep working unchanged.
    if kind == 'observation' and msg_id is not None:
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO agent_observations "
                    "(user_id, observation_type, severity, message, details, action_taken) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(user_id), topic[:120], severity.upper(),
                     (payload or {}).get('message', '')[:1000] or topic,
                     payload_json, severity)
                )
        except Exception as e:
            logger.debug(f"agent_bus mirror to agent_observations failed: {e}")

    return msg_id


def recent(user_id, since=None, kinds=None, severity_min='info',
           topics=None, limit=50):
    """Return messages for user_id, newest first.

    Args:
        since: datetime | iso-string | minutes-int.
               Default: "now - 30 minutes" — uses DB-native NOW()/datetime().
        kinds: iterable of kind names to filter by (default: all).
        severity_min: 'info' | 'warning' | 'alert' | 'crisis'.
        topics: iterable of topic strings to filter by.
        limit: max rows returned.

    Returns:
        list of dicts: {id, sender, kind, severity, topic, payload,
                        created_at, expires_at, correlates_with}
        — payload is parsed back to dict.
    """
    if not _DB_AVAILABLE or not user_id:
        return []

    sev_threshold = _SEV_ORDER.get(_norm_severity(severity_min), 0)

    # Time predicates are DB-native to avoid SQLite TEXT vs Python ISO
    # format mismatches (CURRENT_TIMESTAMP uses 'YYYY-MM-DD HH:MM:SS',
    # Python datetime.isoformat() uses 'YYYY-MM-DDTHH:MM:SS' — they
    # don't compare lexicographically the same way).
    minutes_back = 30
    explicit_since = None
    if since is not None:
        if isinstance(since, (int, float)):
            minutes_back = int(since)
        elif isinstance(since, str):
            explicit_since = since
        elif hasattr(since, 'isoformat'):
            explicit_since = since.isoformat()

    if is_postgres():
        if explicit_since:
            time_pred = "created_at >= ? AND expires_at > NOW()"
            params = [str(user_id), explicit_since]
        else:
            time_pred = (f"created_at >= NOW() - INTERVAL '{minutes_back} minutes' "
                         "AND expires_at > NOW()")
            params = [str(user_id)]
    else:
        if explicit_since:
            time_pred = "created_at >= ? AND expires_at > datetime('now')"
            params = [str(user_id), explicit_since]
        else:
            time_pred = (f"created_at >= datetime('now', '-{minutes_back} minutes') "
                         "AND expires_at > datetime('now')")
            params = [str(user_id)]

    sql = ("SELECT id, sender, kind, severity, topic, payload, "
           "expires_at, correlates_with, created_at "
           "FROM agent_messages "
           "WHERE user_id = ? AND " + time_pred)

    if kinds:
        kind_list = [k for k in kinds if k in _VALID_KINDS]
        if kind_list:
            sql += " AND kind IN (" + ','.join(['?'] * len(kind_list)) + ")"
            params.extend(kind_list)

    if topics:
        top_list = list(topics)
        if top_list:
            sql += " AND topic IN (" + ','.join(['?'] * len(top_list)) + ")"
            params.extend(top_list)

    # SQLite CURRENT_TIMESTAMP is second-precision so ties are common.
    # Tiebreak by id DESC — most recent insert always wins.
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(int(limit))

    out = []
    try:
        with db_context() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        for r in rows or []:
            try:
                rec = _row_to_dict(r)
                if _SEV_ORDER.get(rec['severity'], 0) < sev_threshold:
                    continue
                out.append(rec)
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"agent_bus.recent error: {e}")
    return out


def context(user_id, lookback_minutes=30, max_items=20):
    """High-signal subset for chat-time consumers.

    Returns recent messages where severity >= warning OR
    kind in {'observation', 'decision'}. Use this when building a system
    prompt or feeding the coordinator agent — it's the "what does anyone
    know about this user right now" slice.
    """
    if not _DB_AVAILABLE or not user_id:
        return []

    minutes_back = int(lookback_minutes)
    if is_postgres():
        time_pred = (f"created_at >= NOW() - INTERVAL '{minutes_back} minutes' "
                     "AND expires_at > NOW()")
    else:
        time_pred = (f"created_at >= datetime('now', '-{minutes_back} minutes') "
                     "AND expires_at > datetime('now')")

    sql = ("SELECT id, sender, kind, severity, topic, payload, "
           "expires_at, correlates_with, created_at "
           "FROM agent_messages "
           "WHERE user_id = ? AND " + time_pred + " "
           "AND ("
           "  severity IN ('warning','alert','crisis') "
           "  OR kind IN ('observation','decision')"
           ") "
           "ORDER BY created_at DESC, id DESC LIMIT ?")
    out = []
    try:
        with db_context() as db:
            rows = db.execute(
                sql,
                (str(user_id), int(max_items))
            ).fetchall()
        for r in rows or []:
            try:
                out.append(_row_to_dict(r))
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"agent_bus.context error: {e}")
    return out


def dedupe(user_id, sender=None, topic=None, within_minutes=15,
           any_sender=False, severity_min='warning'):
    """Check if a similar message already exists in the recent window.

    Caller pattern:
        if not bus.dedupe(uid, "agent_loop.recent_crisis", "fall"):
            bus.emit(uid, "agent_loop.recent_crisis", "observation", "crisis", "fall", ...)

    Args:
        sender: match this sender, OR if any_sender=True, match any sender.
        topic: required — dedupe is per-topic.
        within_minutes: lookback window.
        severity_min: only consider messages at or above this severity.

    Returns:
        True if a matching message was found in the window (caller should skip).
    """
    if not _DB_AVAILABLE or not user_id or not topic:
        return False

    minutes_back = int(within_minutes)
    sev_threshold = _SEV_ORDER.get(_norm_severity(severity_min), 1)

    if is_postgres():
        time_pred = (f"created_at >= NOW() - INTERVAL '{minutes_back} minutes' "
                     "AND expires_at > NOW()")
    else:
        time_pred = (f"created_at >= datetime('now', '-{minutes_back} minutes') "
                     "AND expires_at > datetime('now')")

    sql = ("SELECT 1 FROM agent_messages "
           "WHERE user_id = ? AND topic = ? AND " + time_pred)
    params = [str(user_id), topic[:120]]
    if not any_sender and sender:
        sql += " AND sender = ?"
        params.append(str(sender)[:80])
    # Severity filter: emulate ENUM ordering with literal IN list.
    sev_in = [s for s, ord_ in _SEV_ORDER.items() if ord_ >= sev_threshold]
    if sev_in:
        sql += " AND severity IN (" + ','.join(['?'] * len(sev_in)) + ")"
        params.extend(sev_in)
    sql += " LIMIT 1"

    try:
        with db_context() as db:
            row = db.execute(sql, tuple(params)).fetchone()
        return row is not None
    except Exception as e:
        logger.debug(f"agent_bus.dedupe error: {e}")
        return False


def prune():
    """Delete expired messages. Called from daily 3am cleanup.

    Returns the number of rows removed (0 on failure or 0 actually pruned).
    Note: some drivers return -1 from rowcount, so callers should not
    trust the return value for assertions — query agent_messages directly
    if exact verification is needed.
    """
    if not _DB_AVAILABLE:
        return 0
    deleted = 0
    # DB-native NOW()/datetime('now') so we don't fight SQLite's TEXT
    # vs Python ISO format mismatch (CURRENT_TIMESTAMP uses 'YYYY-MM-DD
    # HH:MM:SS', not 'YYYY-MM-DDTHH:MM:SS').
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                cur = db.execute("DELETE FROM agent_messages WHERE expires_at < NOW()")
            else:
                cur = db.execute("DELETE FROM agent_messages WHERE expires_at < datetime('now')")
            try:
                deleted = int(getattr(cur, 'rowcount', 0) or 0)
            except Exception:
                deleted = 0
    except Exception as e:
        logger.warning(f"agent_bus.prune error: {e}")
    return deleted


def _row_to_dict(row):
    """Normalise PG DictRow / SQLite Row / tuple → plain dict.

    Returns dict with id, sender, kind, severity, topic, payload (parsed),
    expires_at, correlates_with, created_at.
    """
    def get(idx_or_name, default=None):
        try:
            if hasattr(row, 'get'):
                v = row.get(idx_or_name)
                if v is None and isinstance(idx_or_name, str):
                    # try positional
                    pos_map = {
                        'id': 0, 'sender': 1, 'kind': 2, 'severity': 3,
                        'topic': 4, 'payload': 5, 'expires_at': 6,
                        'correlates_with': 7, 'created_at': 8,
                    }
                    if idx_or_name in pos_map:
                        try:
                            return row[pos_map[idx_or_name]]
                        except Exception:
                            pass
                return v if v is not None else default
            return row[idx_or_name] if isinstance(idx_or_name, int) else default
        except Exception:
            return default

    payload_raw = get('payload', '{}')
    if isinstance(payload_raw, str):
        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {'raw': payload_raw[:200]}
    else:
        payload = payload_raw or {}

    def _iso(v):
        if v is None:
            return None
        if hasattr(v, 'isoformat'):
            return v.isoformat()
        return str(v)

    return {
        'id': get('id'),
        'sender': get('sender'),
        'kind': get('kind'),
        'severity': (get('severity') or 'info').lower(),
        'topic': get('topic'),
        'payload': payload,
        'expires_at': _iso(get('expires_at')),
        'correlates_with': get('correlates_with'),
        'created_at': _iso(get('created_at')),
    }


# ─── Pretty-print helper for chat system prompt injection ───
def format_for_prompt(messages, max_lines=8):
    """Render messages as a human-readable block for AI context.

    Used by radim_orchestrator to insert "what agents currently know"
    into the system prompt so the chat AI is aware of recent
    observations / anticipation warnings / unack'd crisis events.
    """
    if not messages:
        return ''
    lines = []
    for m in messages[:max_lines]:
        sev = (m.get('severity') or 'info').upper()
        kind = m.get('kind', '?')
        topic = m.get('topic', '')
        sender = m.get('sender', '')
        when = m.get('created_at', '')
        # Trim ISO to "MM-DD HH:MM"
        try:
            short = when[5:16].replace('T', ' ') if isinstance(when, str) else ''
        except Exception:
            short = ''
        msg_text = (m.get('payload') or {}).get('message', '') or topic
        lines.append(f"  [{sev} {kind} {short}] {sender} → {topic}: {msg_text[:120]}")
    return '\n'.join(lines)


logger.info("🚌 Agent message bus loaded (kinds: %s)", ", ".join(_VALID_KINDS))
