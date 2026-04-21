"""
🖼️ GALLERY ROUTES v1.0 (Sprint C)
=============================================================================
Cloud-sync backend for the Gallery frontend module.

Endpoints
---------
- POST   /api/gallery/upload                    — multipart upload (≤15 MB, ≤500/senior)
- GET    /api/gallery/photos                    — list metadata for current user
- GET    /api/gallery/photo/<id>                — redirect/serve photo URL (owner + linked family)
- DELETE /api/gallery/photo/<id>                — delete own photo
- PUT    /api/gallery/photo/<id>                — update caption / album / shared flag
- POST   /api/gallery/photo/<id>/caption        — generate Czech caption via Gemini Vision
- POST   /api/gallery/photo/<id>/animate        — AI animate (Gemini Veo → Luma fallback → Ken-Burns)
- GET    /api/gallery/animation/<id>            — poll animation status
- POST   /api/gallery/family/<senior_id>/upload — linked family uploads photo TO senior
- GET    /api/gallery/family/<senior_id>/photos — linked family views senior's shared photos

Storage
-------
Photos are stored in table `gallery_photos` with either a Cloudinary CDN URL
(if CLOUDINARY_URL env set) or a base-64 data URL as inline fallback —
mirrors the `chat_media` pattern already used in media_push_routes.

Limits
------
- 15 MB per photo, enforced pre-insert (MAX_CONTENT_LENGTH 16 MB in app.py)
- 500 photos per senior
- 5 animations / senior / day (rate limited on this endpoint)
- Allowed MIME: image/jpeg, image/png, image/webp, image/gif
"""

import base64
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request, redirect

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

gallery_bp = Blueprint('gallery', __name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

MAX_PHOTO_BYTES = 15 * 1024 * 1024          # 15 MB
MAX_PHOTOS_PER_SENIOR = 500
MAX_ANIMATIONS_PER_DAY = 5
ALLOWED_MIMES = {'image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif'}
ALLOWED_ALBUMS = {'personal', 'family', 'travel', 'memories', 'events', 'pets', 'nature', 'other'}

# Per-user sliding-window animation rate limiter (in-process; Heroku single dyno OK)
_ANIM_WINDOW = defaultdict(lambda: deque(maxlen=MAX_ANIMATIONS_PER_DAY + 1))
_ANIM_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

GALLERY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS gallery_photos (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        client_id TEXT,
        url TEXT NOT NULL,
        caption TEXT DEFAULT '',
        album TEXT DEFAULT 'personal',
        filename TEXT,
        mime TEXT,
        size_bytes INTEGER,
        shared_with_family BOOLEAN DEFAULT FALSE,
        from_family_user_id TEXT,
        ai_caption_generated BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_gallery_user ON gallery_photos(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_gallery_shared ON gallery_photos(shared_with_family, user_id);
    CREATE INDEX IF NOT EXISTS idx_gallery_client ON gallery_photos(user_id, client_id);
    CREATE INDEX IF NOT EXISTS idx_gallery_album ON gallery_photos(user_id, album);

    CREATE TABLE IF NOT EXISTS gallery_animations (
        id SERIAL PRIMARY KEY,
        photo_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        provider TEXT,
        operation_id TEXT,
        video_url TEXT,
        prompt TEXT,
        sent_to_family_at TIMESTAMP,
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_gallery_anim_user ON gallery_animations(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_gallery_anim_photo ON gallery_animations(photo_id);
    CREATE INDEX IF NOT EXISTS idx_gallery_anim_op ON gallery_animations(operation_id);
"""


def _add_anim_columns_if_missing():
    """Additive migration for pre-v1 gallery_animations rows."""
    extra = [
        "ALTER TABLE gallery_animations ADD COLUMN IF NOT EXISTS operation_id TEXT",
        "ALTER TABLE gallery_animations ADD COLUMN IF NOT EXISTS prompt TEXT",
        "ALTER TABLE gallery_animations ADD COLUMN IF NOT EXISTS sent_to_family_at TIMESTAMP",
    ]
    for stmt in extra:
        try:
            with db_context(commit=True) as db:
                db.execute(stmt)
        except Exception:
            pass  # SQLite/older PG will error on IF NOT EXISTS — ignored


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in GALLERY_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Gallery schema init: {e}")
    # Best-effort additive migration (safe if columns already exist)
    if is_postgres():
        _add_anim_columns_if_missing()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_to_dict(r):
    """Accept tuple (SQLite) or dict-like (psycopg)."""
    def v(i, k, default=None):
        if isinstance(r, (list, tuple)):
            try:
                return r[i]
            except IndexError:
                return default
        return r.get(k, default) if hasattr(r, 'get') else default
    return {
        'id': v(0, 'id'),
        'clientId': v(1, 'client_id'),
        'url': v(2, 'url'),
        'caption': v(3, 'caption') or '',
        'album': v(4, 'album') or 'personal',
        'filename': v(5, 'filename'),
        'mime': v(6, 'mime'),
        'sizeBytes': v(7, 'size_bytes'),
        'sharedWithFamily': bool(v(8, 'shared_with_family')),
        'fromFamilyUserId': v(9, 'from_family_user_id'),
        'aiCaption': bool(v(10, 'ai_caption_generated')),
        'createdAt': str(v(11, 'created_at') or ''),
    }


_SELECT_PHOTO_COLS = (
    "id, client_id, url, caption, album, filename, mime, size_bytes, "
    "shared_with_family, from_family_user_id, ai_caption_generated, created_at"
)


def _get_photo(photo_id, owner_id):
    try:
        with db_context() as db:
            row = db.execute(
                f"SELECT {_SELECT_PHOTO_COLS} "
                "FROM gallery_photos WHERE id = ? AND user_id = ?",
                (photo_id, owner_id)
            ).fetchone()
        return row
    except Exception as e:
        logger.error(f"_get_photo: {e}")
        return None


def _is_family_linked(senior_id, family_uid):
    """True if family_uid is a confirmed family link for senior_id."""
    if not senior_id or not family_uid or senior_id == family_uid:
        return senior_id == family_uid  # allow self
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_user_id = ? "
                "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (senior_id, family_uid)
            ).fetchone()
        return bool(row)
    except Exception:
        return False


def _count_user_photos(user_id):
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM gallery_photos WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        if not row:
            return 0
        return int(row[0] if isinstance(row, (list, tuple)) else list(row.values())[0])
    except Exception:
        return 0


def _get_upload_fn():
    """Return a callable(file_storage) -> {url, public_id, size} or None."""
    try:
        from media_push_routes import _get_upload_fn as media_uploader
        return media_uploader()
    except Exception:
        return None


def _store_image(file_storage, content_bytes, mime):
    """Upload to Cloudinary if available; else inline base-64 data URL."""
    uploader = _get_upload_fn()
    if uploader:
        try:
            # media_push uploader takes a file-like; reset cursor
            file_storage.stream.seek(0)
            result = uploader(file_storage, resource_type='image')
            if result and result.get('url'):
                return result['url'], result.get('public_id'), result.get('size') or len(content_bytes)
        except Exception as e:
            logger.debug(f"Cloudinary upload failed, falling back to data-url: {e}")
    # Fallback: inline base-64 data URL
    b64 = base64.b64encode(content_bytes).decode('ascii')
    data_url = f"data:{mime};base64,{b64}"
    return data_url, None, len(content_bytes)


def _to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in ('1', 'true', 'yes', 'on')
    return False


def _anim_rate_ok(user_id):
    """Return (allowed, remaining, reset_ts) using a 24 h sliding window."""
    now = time.time()
    cutoff = now - 86400
    with _ANIM_LOCK:
        q = _ANIM_WINDOW[user_id]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= MAX_ANIMATIONS_PER_DAY:
            reset = q[0] + 86400
            return False, 0, reset
        q.append(now)
        remaining = MAX_ANIMATIONS_PER_DAY - len(q)
        return True, remaining, now + 86400


# ─────────────────────────────────────────────────────────────────────────────
# LIST + UPLOAD
# ─────────────────────────────────────────────────────────────────────────────

@gallery_bp.route('/api/gallery/photos', methods=['GET', 'OPTIONS'])
@require_auth
def list_photos():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    limit = max(1, min(int(request.args.get('limit', 500)), MAX_PHOTOS_PER_SENIOR))
    album = (request.args.get('album') or '').strip().lower()

    try:
        with db_context() as db:
            if album and album in ALLOWED_ALBUMS:
                rows = db.execute(
                    f"SELECT {_SELECT_PHOTO_COLS} FROM gallery_photos "
                    "WHERE user_id = ? AND album = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (uid, album, limit)
                ).fetchall()
            else:
                rows = db.execute(
                    f"SELECT {_SELECT_PHOTO_COLS} FROM gallery_photos "
                    "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (uid, limit)
                ).fetchall()
    except Exception as e:
        logger.error(f"list_photos: {e}")
        return jsonify({'success': True, 'photos': [], 'count': 0})

    photos = [_row_to_dict(r) for r in rows or []]
    return jsonify({
        'success': True,
        'photos': photos,
        'count': len(photos),
        'limit': MAX_PHOTOS_PER_SENIOR,
    })


@gallery_bp.route('/api/gallery/upload', methods=['POST', 'OPTIONS'])
@require_auth
def upload_photo():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Quota check
    if _count_user_photos(uid) >= MAX_PHOTOS_PER_SENIOR:
        return jsonify({
            'success': False,
            'error': f'Dosáhli jste limitu {MAX_PHOTOS_PER_SENIOR} fotek. Smažte starší pro uložení nových.',
            'code': 'quota_exceeded',
        }), 413

    # Accept either multipart file OR JSON with a data URL (for client-side base64)
    file_storage = request.files.get('photo') or request.files.get('file')
    caption = (request.form.get('caption') or '').strip()[:500]
    album = (request.form.get('album') or 'personal').strip().lower()
    shared = _to_bool(request.form.get('shared'))
    client_id = (request.form.get('clientId') or '').strip()[:64] or None

    if file_storage is None:
        # JSON fallback
        data = request.get_json(silent=True) or {}
        data_url = data.get('dataUrl') or data.get('url')
        if not data_url or not isinstance(data_url, str) or not data_url.startswith('data:image/'):
            return jsonify({'success': False, 'error': 'No image provided'}), 400
        # parse data url
        try:
            header, b64 = data_url.split(',', 1)
            mime = header.split(';')[0].replace('data:', '') or 'image/jpeg'
            content_bytes = base64.b64decode(b64)
        except Exception:
            return jsonify({'success': False, 'error': 'invalid dataUrl'}), 400
        if mime not in ALLOWED_MIMES:
            return jsonify({'success': False, 'error': f'Unsupported mime: {mime}'}), 415
        if len(content_bytes) > MAX_PHOTO_BYTES:
            return jsonify({'success': False, 'error': 'Photo exceeds 15 MB'}), 413
        filename = (data.get('filename') or 'photo.jpg')[:200]
        caption = (data.get('caption') or caption)[:500]
        album = (data.get('album') or album).lower()
        shared = _to_bool(data.get('shared')) or shared
        client_id = (data.get('clientId') or client_id or '')[:64] or None
        url = f"data:{mime};base64,{base64.b64encode(content_bytes).decode('ascii')}"
        size = len(content_bytes)
    else:
        # Multipart upload
        mime = (file_storage.mimetype or '').lower()
        if mime not in ALLOWED_MIMES:
            return jsonify({
                'success': False,
                'error': f'Nepodporovaný formát. Povolené: JPEG, PNG, WEBP, GIF.',
            }), 415
        content_bytes = file_storage.read()
        if len(content_bytes) > MAX_PHOTO_BYTES:
            return jsonify({'success': False, 'error': 'Photo exceeds 15 MB'}), 413
        if not content_bytes:
            return jsonify({'success': False, 'error': 'Empty file'}), 400
        filename = (file_storage.filename or 'photo.jpg')[:200]
        url, _pub, size = _store_image(file_storage, content_bytes, mime)

    if album not in ALLOWED_ALBUMS:
        album = 'personal'

    # Idempotent upsert by (user_id, client_id)
    try:
        with db_context(commit=True) as db:
            if client_id:
                existing = db.execute(
                    "SELECT id FROM gallery_photos WHERE user_id = ? AND client_id = ?",
                    (uid, client_id)
                ).fetchone()
                if existing:
                    eid = existing[0] if isinstance(existing, (list, tuple)) else existing.get('id')
                    return jsonify({'success': True, 'id': eid, 'deduped': True})

            shared_val = (True if is_postgres() else 1) if shared else (False if is_postgres() else 0)
            if is_postgres():
                row = db.execute(
                    "INSERT INTO gallery_photos "
                    "(user_id, client_id, url, caption, album, filename, mime, "
                    "size_bytes, shared_with_family) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, client_id, url, caption, album, filename, mime, size, shared_val)
                ).fetchone()
                new_id = row[0] if isinstance(row, (list, tuple)) else row.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO gallery_photos "
                    "(user_id, client_id, url, caption, album, filename, mime, "
                    "size_bytes, shared_with_family) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, client_id, url, caption, album, filename, mime, size, shared_val)
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"gallery upload: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({
        'success': True,
        'id': new_id,
        'url': url if url.startswith('http') else None,  # don't return full data URL in response
        'size': size,
        'album': album,
    })


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE PHOTO — read / update / delete
# ─────────────────────────────────────────────────────────────────────────────

@gallery_bp.route('/api/gallery/photo/<int:photo_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@require_auth
def photo_item(photo_id):
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if request.method == 'DELETE':
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "DELETE FROM gallery_animations WHERE photo_id = ? AND user_id = ?",
                    (photo_id, uid)
                )
                db.execute(
                    "DELETE FROM gallery_photos WHERE id = ? AND user_id = ?",
                    (photo_id, uid)
                )
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"gallery delete: {e}")
            return jsonify({'success': False, 'error': 'internal'}), 500

    if request.method == 'GET':
        row = _get_photo(photo_id, uid)
        if not row:
            return jsonify({'success': False, 'error': 'not found'}), 404
        return jsonify({'success': True, 'photo': _row_to_dict(row)})

    # PUT — partial update (caption / album / shared / ai_caption flag ignored)
    data = request.get_json() or {}
    allowed = {
        'caption': ('caption', lambda v: str(v or '').strip()[:500]),
        'album': ('album',
                  lambda v: (str(v or 'personal').strip().lower()
                             if str(v or '').strip().lower() in ALLOWED_ALBUMS else 'personal')),
        'sharedWithFamily': ('shared_with_family',
                             lambda v: (True if is_postgres() else 1) if _to_bool(v)
                             else (False if is_postgres() else 0)),
    }
    updates = {}
    for k, (col, fn) in allowed.items():
        if k in data:
            updates[col] = fn(data[k])
    if not updates:
        return jsonify({'success': False, 'error': 'no updatable fields'}), 400

    try:
        set_clause = ', '.join(f"{c} = ?" for c in updates.keys())
        params = list(updates.values()) + [photo_id, uid]
        with db_context(commit=True) as db:
            db.execute(
                f"UPDATE gallery_photos SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id = ? AND user_id = ?",
                tuple(params)
            )
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"gallery update: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500


@gallery_bp.route('/api/gallery/photo/<int:photo_id>/raw', methods=['GET'])
@require_auth
def photo_raw(photo_id):
    """Return 302 redirect to the CDN URL or inline the data URL.
    Owner OR linked family may fetch."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT url, user_id, shared_with_family FROM gallery_photos WHERE id = ?",
                (photo_id,)
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return jsonify({'success': False, 'error': 'not found'}), 404
    url = row[0] if isinstance(row, (list, tuple)) else row.get('url')
    owner = row[1] if isinstance(row, (list, tuple)) else row.get('user_id')
    shared = bool(row[2] if isinstance(row, (list, tuple)) else row.get('shared_with_family'))
    if owner != uid and not (shared and _is_family_linked(owner, uid)):
        return jsonify({'success': False, 'error': 'forbidden'}), 403
    if url.startswith('http'):
        return redirect(url, code=302)
    return jsonify({'success': True, 'url': url})


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI VISION CAPTION
# ─────────────────────────────────────────────────────────────────────────────

def _generate_caption_gemini(image_bytes, mime):
    """Return short Czech caption via Gemini 2.0 Flash vision, or None."""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        prompt = (
            "Stručně v češtině popiš, co vidíš na fotografii, dvěma větami. "
            "Piš vřele, tak aby potěšilo staršího uživatele. "
            "Nepoužívej emoji. Max 140 znaků."
        )
        resp = model.generate_content(
            [
                prompt,
                {'mime_type': mime, 'data': image_bytes},
            ],
            generation_config={'temperature': 0.5, 'max_output_tokens': 200},
        )
        if resp and getattr(resp, 'text', None):
            return resp.text.strip()[:500]
    except Exception as e:
        logger.warning(f"Gemini vision failed: {e}")
    return None


@gallery_bp.route('/api/gallery/photo/<int:photo_id>/caption', methods=['POST'])
@require_auth
def generate_caption(photo_id):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    row = _get_photo(photo_id, uid)
    if not row:
        return jsonify({'success': False, 'error': 'not found'}), 404
    photo = _row_to_dict(row)
    url = photo.get('url') or ''

    # Extract image bytes
    if url.startswith('data:image/'):
        try:
            header, b64 = url.split(',', 1)
            mime = header.split(';')[0].replace('data:', '')
            image_bytes = base64.b64decode(b64)
        except Exception:
            return jsonify({'success': False, 'error': 'corrupt data url'}), 500
    else:
        # CDN — fetch
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
                image_bytes = resp.read()
                mime = resp.headers.get('Content-Type', photo.get('mime') or 'image/jpeg')
        except Exception as e:
            logger.warning(f"caption fetch CDN failed: {e}")
            return jsonify({'success': False, 'error': 'fetch failed'}), 502

    if mime not in ALLOWED_MIMES:
        mime = 'image/jpeg'

    caption = _generate_caption_gemini(image_bytes, mime)
    if not caption:
        return jsonify({
            'success': False,
            'error': 'AI popis není momentálně dostupný. Zkuste to později.',
            'code': 'ai_unavailable',
        }), 503

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE gallery_photos "
                "SET caption = ?, ai_caption_generated = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (caption, True if is_postgres() else 1, photo_id, uid)
            )
    except Exception as e:
        logger.error(f"caption save: {e}")

    return jsonify({'success': True, 'caption': caption, 'aiGenerated': True})


# ─────────────────────────────────────────────────────────────────────────────
# AI ANIMATE — Gemini Veo → Luma → Ken-Burns fallback
# ─────────────────────────────────────────────────────────────────────────────

def _animate_via_veo(image_bytes, mime, prompt=None):
    """Gemini Veo image-to-video call. Returns (video_url, provider, operation_id)
    or (None, None, None).

    Requires:
      - GEMINI_API_KEY (or GEMINI_VEO_API_KEY)
      - ENABLE_VEO_ANIMATE=1   (feature flag; Veo is on a limited preview list)

    Veo returns a long-running operation. We poll up to ~90 s. For longer
    generations the caller can pass `poll_async=True` and resolve later via
    `_veo_poll_operation(operation_name)` — stored in animation row.
    """
    api_key = os.environ.get('GEMINI_VEO_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key or not os.environ.get('ENABLE_VEO_ANIMATE'):
        return None, None, None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        # Veo 2 image-to-video — uses generate_videos on vision models.
        # Note: Google client SDK surface varies across versions; we guard on
        # AttributeError and fall through to the REST shim.
        if hasattr(genai, 'generate_videos'):
            op = genai.generate_videos(
                model='veo-2.0-generate-001',
                image={'mime_type': mime, 'data': image_bytes},
                prompt=(prompt or 'Plynulá jemná animace fotografie — pomalý pohyb kamery, zachovat detaily, neměnit obličeje.'),
                duration_seconds=4,
            )
            # poll — Veo operations usually finish in 30-60 s
            import time as _t
            for _ in range(18):  # ~90 s max
                if getattr(op, 'done', False):
                    break
                _t.sleep(5)
                op = genai.get_operation(op.name) if hasattr(genai, 'get_operation') else op
            if getattr(op, 'done', False):
                video = getattr(op.response, 'generated_videos', [None])[0]
                url = getattr(video, 'uri', None) if video else None
                if url:
                    return url, 'gemini-veo', op.name
            # Not done yet — return operation name so client can poll
            return None, 'gemini-veo', getattr(op, 'name', None)
    except Exception as e:
        logger.warning(f"Veo animate failed: {e}")
    return None, None, None


def _animate_via_replicate(image_bytes, mime, prompt=None):
    """Replicate image-to-video (Stable Video Diffusion / kling). Returns
    (video_url, provider, operation_id). Requires REPLICATE_API_TOKEN.
    Uses replicate's official HTTP API — no SDK needed."""
    token = os.environ.get('REPLICATE_API_TOKEN')
    if not token:
        return None, None, None
    try:
        import urllib.request
        import json as _json

        # Upload image as base-64 data URL
        b64 = base64.b64encode(image_bytes).decode('ascii')
        data_url = f"data:{mime};base64,{b64}"

        # Stable Video Diffusion — good free-tier image-to-video
        payload = {
            'version': os.environ.get(
                'REPLICATE_VIDEO_MODEL_VERSION',
                'stability-ai/stable-video-diffusion'
            ),
            'input': {
                'input_image': data_url,
                'video_length': '14_frames_with_svd',
                'frames_per_second': 6,
                'motion_bucket_id': 127,
                'cond_aug': 0.02,
            },
        }
        req = urllib.request.Request(
            'https://api.replicate.com/v1/predictions',
            data=_json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': f'Token {token}',
                'Content-Type': 'application/json',
                'Prefer': 'wait=60',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
            j = _json.loads(resp.read().decode('utf-8'))
        op_id = j.get('id')
        status = j.get('status')
        if status == 'succeeded':
            out = j.get('output')
            video_url = out[0] if isinstance(out, list) and out else out
            if video_url:
                return video_url, 'replicate-svd', op_id
        # Still processing — return op id for later polling
        return None, 'replicate-svd', op_id
    except Exception as e:
        logger.warning(f"Replicate animate failed: {e}")
    return None, None, None


def _poll_replicate(op_id):
    """Poll a replicate prediction by id. Returns video_url or None."""
    token = os.environ.get('REPLICATE_API_TOKEN')
    if not token or not op_id:
        return None
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(
            f'https://api.replicate.com/v1/predictions/{op_id}',
            headers={'Authorization': f'Token {token}'},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            j = _json.loads(resp.read().decode('utf-8'))
        if j.get('status') == 'succeeded':
            out = j.get('output')
            return out[0] if isinstance(out, list) and out else out
    except Exception as e:
        logger.debug(f"Replicate poll failed: {e}")
    return None


@gallery_bp.route('/api/gallery/photo/<int:photo_id>/animate', methods=['POST'])
@require_auth
def animate_photo(photo_id):
    """Trigger AI animation of a still photo.

    Provider cascade:
      1. Gemini Veo (ENABLE_VEO_ANIMATE + GEMINI_API_KEY)
      2. Replicate Stable Video Diffusion (REPLICATE_API_TOKEN)
      3. Frontend Ken Burns fallback (always works)

    Request JSON: {prompt?: string} — user can steer the motion.
    Response: animationId, status, provider, videoUrl (if ready),
              operationId (for async polling), remainingToday, fallback.
    """
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    ok, remaining, reset = _anim_rate_ok(uid)
    if not ok:
        return jsonify({
            'success': False,
            'error': f'Denní limit {MAX_ANIMATIONS_PER_DAY} animací vyčerpán. Zkuste to zítra.',
            'code': 'rate_limit',
            'resetAt': int(reset),
        }), 429

    row = _get_photo(photo_id, uid)
    if not row:
        return jsonify({'success': False, 'error': 'not found'}), 404
    photo = _row_to_dict(row)
    url = photo.get('url') or ''

    data = request.get_json(silent=True) or {}
    user_prompt = (data.get('prompt') or '').strip()[:500] or None

    # Insert pending animation record (capture id)
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                anim = db.execute(
                    "INSERT INTO gallery_animations (photo_id, user_id, status, prompt) "
                    "VALUES (?, ?, ?, ?) RETURNING id",
                    (photo_id, uid, 'pending', user_prompt)
                ).fetchone()
                anim_id = anim[0] if isinstance(anim, (list, tuple)) else anim.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO gallery_animations (photo_id, user_id, status, prompt) "
                    "VALUES (?, ?, ?, ?)",
                    (photo_id, uid, 'pending', user_prompt)
                )
                anim_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"anim insert: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    # Fetch source image bytes
    image_bytes = None
    mime = photo.get('mime') or 'image/jpeg'
    try:
        if url.startswith('data:image/'):
            _, b64 = url.split(',', 1)
            image_bytes = base64.b64decode(b64)
        else:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
                image_bytes = resp.read()
    except Exception as e:
        logger.debug(f"animate fetch: {e}")

    provider = None
    video_url = None
    operation_id = None
    if image_bytes:
        video_url, provider, operation_id = _animate_via_veo(image_bytes, mime, user_prompt)
        if not video_url and not operation_id:
            video_url, provider, operation_id = _animate_via_replicate(image_bytes, mime, user_prompt)

    # Determine final status
    if video_url:
        status = 'ready'
    elif operation_id:
        status = 'processing'          # async — client will poll /animation/<id>
    else:
        status = 'fallback_kenburns'
        provider = provider or 'kenburns'

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE gallery_animations SET status = ?, provider = ?, "
                "operation_id = ?, video_url = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (status, provider, operation_id, video_url, anim_id, uid)
            )
    except Exception as e:
        logger.debug(f"anim update: {e}")

    return jsonify({
        'success': True,
        'animationId': anim_id,
        'status': status,
        'provider': provider,
        'videoUrl': video_url,
        'operationId': operation_id,
        'remainingToday': remaining,
        'fallback': status == 'fallback_kenburns',
        'processing': status == 'processing',
        'message': (
            'Animace je hotová.' if video_url
            else 'AI pracuje — hotovo za 30–90 vteřin.' if operation_id
            else 'AI video teď není dostupné — použijte plynulou animaci Ken Burns.'
        ),
    })


@gallery_bp.route('/api/gallery/animation/<int:anim_id>/poll', methods=['POST'])
@require_auth
def animation_poll(anim_id):
    """Poll a pending/processing animation. Refreshes status from the provider.
    Used by the frontend while AI video is being generated."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT id, status, provider, operation_id, video_url "
                "FROM gallery_animations WHERE id = ? AND user_id = ?",
                (anim_id, uid)
            ).fetchone()
    except Exception as e:
        logger.error(f"anim poll read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500
    if not row:
        return jsonify({'success': False, 'error': 'not found'}), 404

    def v(i, k):
        return row[i] if isinstance(row, (list, tuple)) else row.get(k)
    status = v(1, 'status')
    provider = v(2, 'provider')
    op_id = v(3, 'operation_id')
    existing_url = v(4, 'video_url')

    if status == 'ready' and existing_url:
        return jsonify({'success': True, 'status': 'ready', 'videoUrl': existing_url,
                        'provider': provider, 'animationId': anim_id})
    if status in ('fallback_kenburns', 'failed'):
        return jsonify({'success': True, 'status': status, 'provider': provider,
                        'animationId': anim_id, 'videoUrl': None})

    # Processing — poll provider
    video_url = None
    if provider == 'replicate-svd' and op_id:
        video_url = _poll_replicate(op_id)
    # Veo polling would go here if supported by the SDK build in use

    if video_url:
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "UPDATE gallery_animations SET status = ?, video_url = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                    ('ready', video_url, anim_id, uid)
                )
        except Exception:
            pass
        return jsonify({'success': True, 'status': 'ready', 'videoUrl': video_url,
                        'provider': provider, 'animationId': anim_id})

    return jsonify({'success': True, 'status': 'processing', 'provider': provider,
                    'animationId': anim_id, 'videoUrl': None})


@gallery_bp.route('/api/gallery/animation/<int:anim_id>/send-family', methods=['POST'])
@require_auth
def animation_send_family(anim_id):
    """Notify all linked family members about a ready animation.
    Sends a push notification with a link to the video + optional caption.

    Only the owner of the animation can trigger this endpoint."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    caption = (data.get('caption') or '').strip()[:240]

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT id, status, video_url, photo_id FROM gallery_animations "
                "WHERE id = ? AND user_id = ?",
                (anim_id, uid)
            ).fetchone()
    except Exception as e:
        logger.error(f"anim send read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500
    if not row:
        return jsonify({'success': False, 'error': 'not found'}), 404

    def v(i, k):
        return row[i] if isinstance(row, (list, tuple)) else row.get(k)
    status = v(1, 'status')
    video_url = v(2, 'video_url')
    photo_id = v(3, 'photo_id')
    if status != 'ready' or not video_url:
        return jsonify({
            'success': False,
            'error': 'Animace ještě není hotová.',
            'code': 'not_ready',
        }), 409

    # List linked family members
    try:
        with db_context() as db:
            fams = db.execute(
                "SELECT family_user_id FROM senior_family_links "
                "WHERE senior_id = ? AND family_user_id IS NOT NULL "
                "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (uid,)
            ).fetchall()
    except Exception:
        fams = []

    recipients = []
    for r in fams or []:
        fid = r[0] if isinstance(r, (list, tuple)) else r.get('family_user_id')
        if fid:
            recipients.append(fid)

    if not recipients:
        return jsonify({
            'success': False,
            'error': 'Zatím nemáte propojenou rodinu. Pozvěte rodinu z nastavení.',
            'code': 'no_family',
        }), 400

    sent = 0
    try:
        from notification_helpers import notify_user
        for fid in recipients:
            try:
                notify_user(
                    user_id=fid,
                    type='gallery_animation',
                    title='💌 Živá vzpomínka od blízkého',
                    body=(caption or 'Váš blízký vám poslal živou vzpomínku.'),
                    severity='info',
                    data={
                        'animation_id': anim_id,
                        'photo_id': photo_id,
                        'video_url': video_url,
                        'sender_id': uid,
                    },
                )
                sent += 1
            except Exception as e:
                logger.debug(f"family send notify one: {e}")
    except ImportError:
        logger.warning("notify_user helper unavailable — animation send skipped push")

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE gallery_animations SET sent_to_family_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (anim_id, uid)
            )
    except Exception:
        pass

    return jsonify({
        'success': True,
        'sent': sent,
        'recipients': len(recipients),
        'videoUrl': video_url,
    })


@gallery_bp.route('/api/gallery/animation/<int:anim_id>', methods=['GET'])
@require_auth
def animation_status(anim_id):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT id, photo_id, status, provider, video_url, error, "
                "created_at, updated_at "
                "FROM gallery_animations WHERE id = ? AND user_id = ?",
                (anim_id, uid)
            ).fetchone()
    except Exception as e:
        logger.error(f"anim status: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500
    if not row:
        return jsonify({'success': False, 'error': 'not found'}), 404

    def v(i, k):
        return row[i] if isinstance(row, (list, tuple)) else row.get(k)
    return jsonify({
        'success': True,
        'animation': {
            'id': v(0, 'id'),
            'photoId': v(1, 'photo_id'),
            'status': v(2, 'status'),
            'provider': v(3, 'provider'),
            'videoUrl': v(4, 'video_url'),
            'error': v(5, 'error'),
            'createdAt': str(v(6, 'created_at') or ''),
            'updatedAt': str(v(7, 'updated_at') or ''),
        }
    })


# ─────────────────────────────────────────────────────────────────────────────
# FAMILY SHARE VIEW + FAMILY-TO-SENIOR UPLOAD
# ─────────────────────────────────────────────────────────────────────────────

@gallery_bp.route('/api/gallery/family/<senior_id>/photos', methods=['GET'])
@require_auth
def family_view(senior_id):
    """Linked family member lists senior's shared photos."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_linked(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    limit = max(1, min(int(request.args.get('limit', 200)), MAX_PHOTOS_PER_SENIOR))
    try:
        with db_context() as db:
            rows = db.execute(
                f"SELECT {_SELECT_PHOTO_COLS} FROM gallery_photos "
                "WHERE user_id = ? AND shared_with_family = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (senior_id, True if is_postgres() else 1, limit)
            ).fetchall()
    except Exception as e:
        logger.error(f"family_view: {e}")
        return jsonify({'success': True, 'photos': [], 'count': 0})

    photos = [_row_to_dict(r) for r in rows or []]
    return jsonify({'success': True, 'photos': photos, 'count': len(photos)})


@gallery_bp.route('/api/gallery/family/<senior_id>/upload', methods=['POST'])
@require_auth
def family_upload(senior_id):
    """Family member uploads a photo INTO the senior's gallery.
    Photo is marked with from_family_user_id and shared_with_family=True."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_linked(senior_id, uid) or senior_id == uid:
        return jsonify({'success': False, 'error': 'not linked'}), 403

    # Quota check against the senior
    if _count_user_photos(senior_id) >= MAX_PHOTOS_PER_SENIOR:
        return jsonify({
            'success': False,
            'error': 'Galerie seniora je plná.',
            'code': 'quota_exceeded',
        }), 413

    file_storage = request.files.get('photo') or request.files.get('file')
    if file_storage is None:
        return jsonify({'success': False, 'error': 'No image provided'}), 400

    mime = (file_storage.mimetype or '').lower()
    if mime not in ALLOWED_MIMES:
        return jsonify({'success': False, 'error': 'Unsupported mime'}), 415
    content_bytes = file_storage.read()
    if not content_bytes:
        return jsonify({'success': False, 'error': 'Empty file'}), 400
    if len(content_bytes) > MAX_PHOTO_BYTES:
        return jsonify({'success': False, 'error': 'Photo exceeds 15 MB'}), 413

    caption = (request.form.get('caption') or '').strip()[:500]
    album = (request.form.get('album') or 'family').strip().lower()
    if album not in ALLOWED_ALBUMS:
        album = 'family'
    filename = (file_storage.filename or 'family.jpg')[:200]
    url, _pub, size = _store_image(file_storage, content_bytes, mime)

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                row = db.execute(
                    "INSERT INTO gallery_photos "
                    "(user_id, url, caption, album, filename, mime, size_bytes, "
                    "shared_with_family, from_family_user_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (senior_id, url, caption, album, filename, mime, size, True, uid)
                ).fetchone()
                new_id = row[0] if isinstance(row, (list, tuple)) else row.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO gallery_photos "
                    "(user_id, url, caption, album, filename, mime, size_bytes, "
                    "shared_with_family, from_family_user_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (senior_id, url, caption, album, filename, mime, size, 1, uid)
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"family_upload: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    # Notify senior + push + attach to brain memory context
    try:
        from notification_helpers import notify_user
        notify_user(
            user_id=senior_id,
            type='info',
            title='📷 Nová fotka od rodiny',
            body='Někdo z rodiny vám poslal novou fotografii.',
            severity='info',
            data={'photo_id': new_id},
        )
    except Exception as e:
        logger.debug(f"family_upload notify: {e}")

    return jsonify({'success': True, 'id': new_id, 'seniorId': senior_id})


# ─────────────────────────────────────────────────────────────────────────────
# MEMORY HOOK — recent memorable photos for Radim chat context
# ─────────────────────────────────────────────────────────────────────────────

def recent_memorable_photos(user_id, limit=3):
    """Return a short list of recent/memorable photos for the brain memory
    injection system. Public helper — consumed by memory_context_builder."""
    if not user_id:
        return []
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, caption, album, created_at FROM gallery_photos "
                "WHERE user_id = ? AND caption <> '' "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, int(limit))
            ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        out.append({
            'id': v(0, 'id'),
            'caption': v(1, 'caption'),
            'album': v(2, 'album'),
            'when': str(v(3, 'created_at') or ''),
        })
    return out


logger.info("🖼️ Gallery routes v1.0 loaded — CRUD + Vision caption + AI animate + family share")
