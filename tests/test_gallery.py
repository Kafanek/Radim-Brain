"""
Gallery Sprint C smoke + contract tests.
Run: pytest tests/test_gallery.py -v
"""

import io
import base64
import pytest


# Minimal valid 1×1 PNG bytes — enough to satisfy mime + size guards
_PNG_1x1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='
)


class TestGalleryAuth:
    """Every endpoint rejects unauthenticated access."""

    def test_list_requires_auth(self, client):
        resp = client.get('/api/gallery/photos')
        assert resp.status_code in (401, 403)

    def test_upload_requires_auth(self, client):
        resp = client.post('/api/gallery/upload',
                           data={'photo': (io.BytesIO(_PNG_1x1), 'x.png')},
                           content_type='multipart/form-data')
        assert resp.status_code in (401, 403)

    def test_get_photo_requires_auth(self, client):
        resp = client.get('/api/gallery/photo/1')
        assert resp.status_code in (401, 403, 404)

    def test_update_photo_requires_auth(self, client):
        resp = client.put('/api/gallery/photo/1', json={'caption': 'x'})
        assert resp.status_code in (401, 403, 404)

    def test_delete_photo_requires_auth(self, client):
        resp = client.delete('/api/gallery/photo/1')
        assert resp.status_code in (401, 403, 404)

    def test_caption_requires_auth(self, client):
        resp = client.post('/api/gallery/photo/1/caption')
        assert resp.status_code in (401, 403, 404)

    def test_animate_requires_auth(self, client):
        resp = client.post('/api/gallery/photo/1/animate')
        assert resp.status_code in (401, 403, 404, 429)

    def test_animation_status_requires_auth(self, client):
        resp = client.get('/api/gallery/animation/1')
        assert resp.status_code in (401, 403, 404)

    def test_family_view_requires_auth(self, client):
        resp = client.get('/api/gallery/family/abc/photos')
        assert resp.status_code in (401, 403)

    def test_family_upload_requires_auth(self, client):
        resp = client.post('/api/gallery/family/abc/upload',
                           data={'photo': (io.BytesIO(_PNG_1x1), 'x.png')},
                           content_type='multipart/form-data')
        assert resp.status_code in (401, 403)

    def test_raw_requires_auth(self, client):
        resp = client.get('/api/gallery/photo/1/raw')
        assert resp.status_code in (401, 403, 404)


class TestGallerySchema:
    def test_init_schema_idempotent(self):
        from gallery_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_row_to_dict_tuple(self):
        from gallery_routes import _row_to_dict
        r = (1, 'cli-1', 'http://cdn/x.jpg', 'Rodinný oběd', 'family',
             'oben.jpg', 'image/jpeg', 12345, True, None, True,
             '2026-04-21 10:00:00')
        d = _row_to_dict(r)
        assert d['id'] == 1
        assert d['clientId'] == 'cli-1'
        assert d['url'] == 'http://cdn/x.jpg'
        assert d['caption'] == 'Rodinný oběd'
        assert d['album'] == 'family'
        assert d['filename'] == 'oben.jpg'
        assert d['mime'] == 'image/jpeg'
        assert d['sizeBytes'] == 12345
        assert d['sharedWithFamily'] is True
        assert d['fromFamilyUserId'] is None
        assert d['aiCaption'] is True

    def test_row_to_dict_dict(self):
        from gallery_routes import _row_to_dict
        r = {
            'id': 9, 'client_id': None, 'url': 'data:image/png;base64,xxx',
            'caption': '', 'album': 'personal', 'filename': 'p.png',
            'mime': 'image/png', 'size_bytes': 42,
            'shared_with_family': False, 'from_family_user_id': 'fam-42',
            'ai_caption_generated': False, 'created_at': '2026-04-21',
        }
        d = _row_to_dict(r)
        assert d['id'] == 9
        assert d['album'] == 'personal'
        assert d['sharedWithFamily'] is False
        assert d['fromFamilyUserId'] == 'fam-42'


class TestGalleryBlueprint:
    def test_blueprint_imports(self):
        from gallery_routes import gallery_bp
        assert gallery_bp is not None
        assert gallery_bp.name == 'gallery'

    def test_blueprint_registered_on_app(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/gallery/photos') for r in rules)
        assert any(r.endswith('/api/gallery/upload') for r in rules)
        assert any('/api/gallery/photo/<int:photo_id>' in r for r in rules)
        assert any('/caption' in r and '/api/gallery' in r for r in rules)
        assert any('/animate' in r and '/api/gallery' in r for r in rules)
        assert any('/api/gallery/animation/' in r for r in rules)
        assert any('/api/gallery/family/' in r and '/photos' in r for r in rules)
        assert any('/api/gallery/family/' in r and '/upload' in r for r in rules)


class TestGalleryValidation:
    def test_upload_empty_payload(self, client):
        """POST without photo + without JSON → 400 or 401."""
        resp = client.post('/api/gallery/upload')
        assert resp.status_code in (400, 401, 403)

    def test_upload_unsupported_mime(self, client):
        """Non-image file → 415 or 401 unauthed (auth first)."""
        resp = client.post(
            '/api/gallery/upload',
            data={'photo': (io.BytesIO(b'\x00' * 100), 'x.exe', 'application/x-msdownload')},
            content_type='multipart/form-data',
        )
        assert resp.status_code in (401, 403, 415)


class TestGalleryConstants:
    def test_limits_defined(self):
        from gallery_routes import (
            MAX_PHOTO_BYTES, MAX_PHOTOS_PER_SENIOR, MAX_ANIMATIONS_PER_DAY,
            ALLOWED_MIMES, ALLOWED_ALBUMS,
        )
        assert MAX_PHOTO_BYTES == 15 * 1024 * 1024
        assert MAX_PHOTOS_PER_SENIOR == 500
        assert MAX_ANIMATIONS_PER_DAY == 5
        assert 'image/jpeg' in ALLOWED_MIMES
        assert 'image/png' in ALLOWED_MIMES
        assert 'image/webp' in ALLOWED_MIMES
        assert 'application/pdf' not in ALLOWED_MIMES
        assert 'personal' in ALLOWED_ALBUMS
        assert 'family' in ALLOWED_ALBUMS


class TestAnimationRateLimiter:
    """The 5/day sliding-window limiter blocks the 6th request."""

    def setup_method(self):
        from gallery_routes import _ANIM_WINDOW
        _ANIM_WINDOW.clear()

    def test_first_five_allowed(self):
        from gallery_routes import _anim_rate_ok, MAX_ANIMATIONS_PER_DAY
        user = 'rate-user-1'
        for i in range(MAX_ANIMATIONS_PER_DAY):
            ok, remaining, _ = _anim_rate_ok(user)
            assert ok is True, f"call {i} should be allowed"

    def test_sixth_blocked(self):
        from gallery_routes import _anim_rate_ok, MAX_ANIMATIONS_PER_DAY
        user = 'rate-user-2'
        for _ in range(MAX_ANIMATIONS_PER_DAY):
            _anim_rate_ok(user)
        ok, remaining, reset = _anim_rate_ok(user)
        assert ok is False
        assert remaining == 0
        assert reset > 0

    def test_per_user_isolation(self):
        from gallery_routes import _anim_rate_ok, MAX_ANIMATIONS_PER_DAY
        for _ in range(MAX_ANIMATIONS_PER_DAY):
            _anim_rate_ok('u-A')
        ok, _, _ = _anim_rate_ok('u-B')
        assert ok is True, "user B should not be rate-limited by user A's activity"


class TestFamilyLinkGuard:
    """_is_family_linked returns False when no link exists."""

    def test_unrelated_users_not_linked(self):
        from gallery_routes import _is_family_linked, _init_schema
        _init_schema()
        assert _is_family_linked('senior-xyz', 'family-abc') is False

    def test_self_counts_as_linked(self):
        from gallery_routes import _is_family_linked
        assert _is_family_linked('u1', 'u1') is True


class TestCaptionFallback:
    """Caption endpoint returns 503 when no GEMINI_API_KEY set."""

    def test_gemini_caption_returns_none_without_key(self, monkeypatch):
        from gallery_routes import _generate_caption_gemini
        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
        result = _generate_caption_gemini(_PNG_1x1, 'image/png')
        assert result is None


class TestAnimateFallback:
    """Veo + Replicate return (None, None, None) when keys not set."""

    def test_veo_no_key_returns_none(self, monkeypatch):
        from gallery_routes import _animate_via_veo
        monkeypatch.delenv('GEMINI_VEO_API_KEY', raising=False)
        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
        monkeypatch.delenv('ENABLE_VEO_ANIMATE', raising=False)
        url, provider, op = _animate_via_veo(_PNG_1x1, 'image/png')
        assert url is None
        assert provider is None
        assert op is None

    def test_veo_no_flag_returns_none(self, monkeypatch):
        """Even with Gemini key, Veo is opt-in via ENABLE_VEO_ANIMATE."""
        from gallery_routes import _animate_via_veo
        monkeypatch.setenv('GEMINI_API_KEY', 'fake-key')
        monkeypatch.delenv('ENABLE_VEO_ANIMATE', raising=False)
        url, provider, op = _animate_via_veo(_PNG_1x1, 'image/png')
        assert url is None
        assert provider is None
        assert op is None

    def test_replicate_no_token_returns_none(self, monkeypatch):
        from gallery_routes import _animate_via_replicate
        monkeypatch.delenv('REPLICATE_API_TOKEN', raising=False)
        url, provider, op = _animate_via_replicate(_PNG_1x1, 'image/png')
        assert url is None
        assert provider is None
        assert op is None

    def test_replicate_poll_no_token_returns_none(self, monkeypatch):
        from gallery_routes import _poll_replicate
        monkeypatch.delenv('REPLICATE_API_TOKEN', raising=False)
        assert _poll_replicate('xyz') is None

    def test_replicate_poll_empty_op_returns_none(self, monkeypatch):
        from gallery_routes import _poll_replicate
        monkeypatch.setenv('REPLICATE_API_TOKEN', 'fake')
        assert _poll_replicate('') is None
        assert _poll_replicate(None) is None


class TestAnimationNewEndpoints:
    """Polling + send-to-family endpoints are registered and auth-guarded."""

    def test_poll_endpoint_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/gallery/animation/' in r and '/poll' in r for r in rules)

    def test_send_family_endpoint_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/gallery/animation/' in r and '/send-family' in r for r in rules)

    def test_poll_requires_auth(self, client):
        resp = client.post('/api/gallery/animation/1/poll')
        assert resp.status_code in (401, 403, 404)

    def test_send_family_requires_auth(self, client):
        resp = client.post('/api/gallery/animation/1/send-family', json={})
        assert resp.status_code in (401, 403, 404)


class TestMemoryHook:
    """recent_memorable_photos returns list (possibly empty) without crashing."""

    def test_memory_hook_empty_user(self):
        from gallery_routes import recent_memorable_photos
        assert recent_memorable_photos('') == []

    def test_memory_hook_unknown_user(self):
        from gallery_routes import recent_memorable_photos, _init_schema
        _init_schema()
        result = recent_memorable_photos('nonexistent-user-zzz', limit=3)
        assert isinstance(result, list)
        assert result == []


class TestToBool:
    def test_to_bool_truthy(self):
        from gallery_routes import _to_bool
        assert _to_bool(True) is True
        assert _to_bool(1) is True
        assert _to_bool('true') is True
        assert _to_bool('1') is True
        assert _to_bool('YES') is True
        assert _to_bool('on') is True

    def test_to_bool_falsy(self):
        from gallery_routes import _to_bool
        assert _to_bool(False) is False
        assert _to_bool(0) is False
        assert _to_bool('false') is False
        assert _to_bool('') is False
        assert _to_bool('0') is False
        assert _to_bool(None) is False
