"""
🏠 PER-USER HOME ASSISTANT CONFIG (v395)
=============================================================================
Storage + factory for per-user / per-home Home Assistant clients.

Design:
- Each user can register multiple homes (home_id PK, user_id FK).
- Tokens are encrypted at rest with Fernet using HA_TOKEN_ENCRYPTION_KEY.
- Webhook secret is per-home — HA hits POST /api/ha/webhook/<home_id> with
  X-HA-Secret matching the row's ha_webhook_secret.
- ha_for_user(user_id) returns a HomeAssistantClient configured with that
  user's default home; ha_for_user(user_id, home_id) targets a specific home.
- Per-user clients are cached in a thread-safe dict so we don't rebuild
  the WebSocket connection on every request.

Encryption key:
- HA_TOKEN_ENCRYPTION_KEY env var (Fernet base64 key — generate with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
- If unset, dev mode falls back to a derived key from HA_WEBHOOK_SECRET so
  local dev still works. Production MUST set it explicitly.
"""

import os
import uuid
import base64
import hashlib
import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# ENCRYPTION
# ═══════════════════════════════════════════════════════════════════

_FERNET = None


def _get_fernet():
    """Lazy Fernet instance. Falls back to dev key if env unset."""
    global _FERNET
    if _FERNET is not None:
        return _FERNET
    from cryptography.fernet import Fernet
    key = os.environ.get('HA_TOKEN_ENCRYPTION_KEY', '').strip()
    if not key:
        # Dev fallback: derive from webhook secret or app secret. Production
        # MUST set HA_TOKEN_ENCRYPTION_KEY explicitly — see HA_SETUP.md.
        seed = (os.environ.get('HA_WEBHOOK_SECRET', '')
                or os.environ.get('FLASK_SECRET_KEY', '')
                or 'radim-dev-fallback-NOT-FOR-PRODUCTION')
        digest = hashlib.sha256(seed.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
        logger.warning("HA_TOKEN_ENCRYPTION_KEY not set — using derived dev key. "
                       "Set it explicitly in production.")
    if isinstance(key, str):
        key = key.encode()
    _FERNET = Fernet(key)
    return _FERNET


def encrypt_token(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


# ═══════════════════════════════════════════════════════════════════
# DB OPERATIONS
# ═══════════════════════════════════════════════════════════════════

def _row_to_dict(row, with_token: bool = False) -> dict:
    """Normalize PG/SQLite row into a dict. Decrypts token only when asked."""
    if hasattr(row, 'keys'):  # sqlite3.Row or RealDictRow
        d = dict(row)
    else:  # tuple
        d = {
            'home_id': row[0], 'user_id': row[1], 'label': row[2],
            'ha_url': row[3], 'ha_token_encrypted': row[4],
            'ha_webhook_secret': row[5], 'is_default': bool(row[6]),
            'last_connected_at': row[7], 'last_error': row[8],
            'created_at': row[9], 'updated_at': row[10],
        }
    if with_token:
        try:
            d['ha_token'] = decrypt_token(d['ha_token_encrypted'])
        except Exception as e:
            logger.error(f"decrypt_token failed for home {d.get('home_id')}: {e}")
            d['ha_token'] = None
    # Never leak the encrypted blob to API consumers
    d.pop('ha_token_encrypted', None)
    d['is_default'] = bool(d.get('is_default'))
    return d


def list_homes(user_id: str) -> list[dict]:
    """Return all homes registered by a user (no tokens)."""
    from database import db_context
    with db_context() as db:
        rows = db.execute(
            "SELECT home_id, user_id, label, ha_url, ha_token_encrypted, "
            "ha_webhook_secret, is_default, last_connected_at, last_error, "
            "created_at, updated_at "
            "FROM user_ha_homes WHERE user_id = ? ORDER BY is_default DESC, created_at",
            (user_id,)
        ).fetchall() or []
    return [_row_to_dict(r) for r in rows]


def get_home(user_id: str, home_id: Optional[str] = None,
             with_token: bool = False) -> Optional[dict]:
    """Get one home. If home_id is None, returns the user's default home
    (or first home if no default flagged)."""
    from database import db_context
    with db_context() as db:
        if home_id:
            row = db.execute(
                "SELECT home_id, user_id, label, ha_url, ha_token_encrypted, "
                "ha_webhook_secret, is_default, last_connected_at, last_error, "
                "created_at, updated_at "
                "FROM user_ha_homes WHERE user_id = ? AND home_id = ?",
                (user_id, home_id)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT home_id, user_id, label, ha_url, ha_token_encrypted, "
                "ha_webhook_secret, is_default, last_connected_at, last_error, "
                "created_at, updated_at "
                "FROM user_ha_homes WHERE user_id = ? "
                "ORDER BY is_default DESC, created_at LIMIT 1",
                (user_id,)
            ).fetchone()
    if not row:
        return None
    return _row_to_dict(row, with_token=with_token)


def get_home_by_id(home_id: str, with_token: bool = False) -> Optional[dict]:
    """Lookup a home by home_id alone (used by webhook)."""
    from database import db_context
    with db_context() as db:
        row = db.execute(
            "SELECT home_id, user_id, label, ha_url, ha_token_encrypted, "
            "ha_webhook_secret, is_default, last_connected_at, last_error, "
            "created_at, updated_at "
            "FROM user_ha_homes WHERE home_id = ?",
            (home_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row, with_token=with_token)


def save_home(user_id: str, label: str, ha_url: str, ha_token: str,
              home_id: Optional[str] = None, is_default: bool = False,
              ha_webhook_secret: Optional[str] = None) -> dict:
    """Insert or update a home. Returns the saved row (no token)."""
    from database import db_context, is_postgres
    home_id = home_id or str(uuid.uuid4())
    enc = encrypt_token(ha_token)
    secret = ha_webhook_secret or _new_webhook_secret()
    now = datetime.utcnow()

    with db_context(commit=True) as db:
        # Check if this is the user's first home — auto-set default
        existing = db.execute(
            "SELECT COUNT(*) AS cnt FROM user_ha_homes WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        # Handle sqlite3.Row (key + index access), tuple, RealDictRow
        if existing is None:
            count = 0
        else:
            try:
                count = existing['cnt']
            except (TypeError, KeyError, IndexError):
                try:
                    count = existing[0]
                except Exception:
                    count = 0
        first_home = int(count or 0) == 0
        if first_home:
            is_default = True

        # If marking this as default, clear other defaults for this user
        if is_default:
            db.execute(
                "UPDATE user_ha_homes SET is_default = ? WHERE user_id = ?",
                (False if is_postgres() else 0, user_id)
            )

        # Upsert
        existing_row = db.execute(
            "SELECT home_id FROM user_ha_homes WHERE home_id = ?",
            (home_id,)
        ).fetchone()
        if existing_row:
            db.execute(
                "UPDATE user_ha_homes SET label = ?, ha_url = ?, "
                "ha_token_encrypted = ?, ha_webhook_secret = ?, "
                "is_default = ?, updated_at = ? "
                "WHERE home_id = ? AND user_id = ?",
                (label, ha_url, enc, secret,
                 is_default if is_postgres() else (1 if is_default else 0),
                 now, home_id, user_id)
            )
        else:
            db.execute(
                "INSERT INTO user_ha_homes "
                "(home_id, user_id, label, ha_url, ha_token_encrypted, "
                " ha_webhook_secret, is_default, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (home_id, user_id, label, ha_url, enc, secret,
                 is_default if is_postgres() else (1 if is_default else 0),
                 now, now)
            )

    # Bust cache so next ha_for_user() rebuilds with new config
    _invalidate_client_cache(user_id, home_id)
    return get_home(user_id, home_id) or {}


def delete_home(user_id: str, home_id: str) -> bool:
    from database import db_context
    with db_context(commit=True) as db:
        cur = db.execute(
            "DELETE FROM user_ha_homes WHERE user_id = ? AND home_id = ?",
            (user_id, home_id)
        )
    _invalidate_client_cache(user_id, home_id)
    # PgCursorWrapper / sqlite3 both expose rowcount
    return getattr(cur, 'rowcount', 0) > 0


def set_default_home(user_id: str, home_id: str) -> bool:
    from database import db_context, is_postgres
    with db_context(commit=True) as db:
        # Verify ownership first
        owns = db.execute(
            "SELECT 1 FROM user_ha_homes WHERE user_id = ? AND home_id = ?",
            (user_id, home_id)
        ).fetchone()
        if not owns:
            return False
        db.execute(
            "UPDATE user_ha_homes SET is_default = ? WHERE user_id = ?",
            (False if is_postgres() else 0, user_id)
        )
        db.execute(
            "UPDATE user_ha_homes SET is_default = ?, updated_at = ? "
            "WHERE home_id = ? AND user_id = ?",
            (True if is_postgres() else 1, datetime.utcnow(), home_id, user_id)
        )
    _invalidate_client_cache(user_id)
    return True


def record_connection_status(home_id: str, ok: bool, error: Optional[str] = None):
    """Update last_connected_at / last_error for diagnostics."""
    from database import db_context
    try:
        with db_context(commit=True) as db:
            if ok:
                db.execute(
                    "UPDATE user_ha_homes SET last_connected_at = ?, last_error = NULL "
                    "WHERE home_id = ?",
                    (datetime.utcnow(), home_id)
                )
            else:
                db.execute(
                    "UPDATE user_ha_homes SET last_error = ? WHERE home_id = ?",
                    ((error or 'unknown')[:500], home_id)
                )
    except Exception as e:
        logger.debug(f"record_connection_status: {e}")


def _new_webhook_secret() -> str:
    return base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip('=')


# ═══════════════════════════════════════════════════════════════════
# CLIENT FACTORY (per-user / per-home singleton)
# ═══════════════════════════════════════════════════════════════════

# Cache key: (user_id, home_id)
_clients: dict = {}
_clients_lock = threading.Lock()


def ha_for_user(user_id: str, home_id: Optional[str] = None):
    """Return a HomeAssistantClient configured for this user (and optionally
    a specific home). Returns None if the user has no HA configured.

    Cached per (user_id, home_id) so the WebSocket / state cache survives
    across requests.
    """
    if not user_id:
        return None
    cfg = get_home(user_id, home_id, with_token=True)
    if not cfg or not cfg.get('ha_token'):
        return None

    cache_key = (user_id, cfg['home_id'])
    with _clients_lock:
        client = _clients.get(cache_key)
        if client is not None:
            # Same URL+token? reuse. Otherwise rebuild.
            if client.url == cfg['ha_url'].rstrip('/') and client.token == cfg['ha_token']:
                return client

        # Build new client. Avoid circular import.
        from home_assistant import HomeAssistantClient, EnhancedHAClient, HAS_HA_LIB
        cls = EnhancedHAClient if HAS_HA_LIB else HomeAssistantClient
        client = cls(url=cfg['ha_url'], token=cfg['ha_token'])
        client._home_id = cfg['home_id']  # diagnostic tag
        _clients[cache_key] = client
        return client


def _invalidate_client_cache(user_id: Optional[str] = None,
                             home_id: Optional[str] = None):
    """Drop cached clients. If both args None, clears all."""
    with _clients_lock:
        if user_id is None and home_id is None:
            _clients.clear()
            return
        keys = list(_clients.keys())
        for (uid, hid) in keys:
            if user_id and uid != user_id:
                continue
            if home_id and hid != home_id:
                continue
            _clients.pop((uid, hid), None)


# ═══════════════════════════════════════════════════════════════════
# WEBSOCKET SUPERVISOR — auto-start per-user real-time push
# ═══════════════════════════════════════════════════════════════════
# When the Flask app boots, this opens a WebSocket subscription to each
# registered home so HA → Radim state_changed events flow into the cache
# without HA needing to push (alongside the per-home webhook). Each
# client.start_websocket() spawns its own daemon thread with reconnect.

_supervisor_started = False
_supervisor_lock = threading.Lock()


def list_all_homes() -> list[dict]:
    """Return every (user_id, home_id) pair across all users — admin scan."""
    from database import db_context
    with db_context() as db:
        rows = db.execute(
            "SELECT home_id, user_id, label, ha_url, ha_token_encrypted, "
            "ha_webhook_secret, is_default, last_connected_at, last_error, "
            "created_at, updated_at FROM user_ha_homes"
        ).fetchall() or []
    return [_row_to_dict(r) for r in rows]


def start_websocket_supervisor():
    """Spin up WebSocket subscription for every registered home.

    Idempotent: safe to call multiple times. Each client's start_websocket
    has its own internal reconnect loop, so we only need to spawn once
    per (user_id, home_id) cache key.

    Called from app.py at startup (after blueprint registration).
    """
    global _supervisor_started
    with _supervisor_lock:
        if _supervisor_started:
            return
        _supervisor_started = True

    try:
        homes = list_all_homes()
    except Exception as e:
        logger.warning(f"WS supervisor: list_all_homes failed: {e}")
        return

    started = 0
    for h in homes:
        try:
            client = ha_for_user(h['user_id'], h['home_id'])
            if client is None:
                continue
            # client.start_websocket spawns daemon thread with reconnect
            client.start_websocket()
            # Hook: persist connection status when state changes
            def _make_handler(home_id):
                def _handler(entity_id, new_state):
                    record_connection_status(home_id, True)
                return _handler
            try:
                client.on_state_change(_make_handler(h['home_id']))
            except Exception:
                pass
            started += 1
        except Exception as e:
            logger.warning(f"WS supervisor: home {h['home_id'][:8]} failed: {e}")
    logger.info(f"🏠 WS supervisor: subscribed to {started}/{len(homes)} home(s)")


def reset_supervisor():
    """For tests — allows re-running start_websocket_supervisor()."""
    global _supervisor_started
    with _supervisor_lock:
        _supervisor_started = False
