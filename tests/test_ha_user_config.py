"""
Per-user / per-home Home Assistant config — unit + route tests (v395).

Covers:
- Token encryption round-trip (Fernet)
- save_home / get_home / list_homes / delete_home / set_default_home
- ha_for_user returns None when no config, real client when configured
- API endpoints: auth required, validation, no-token-leak, ownership
- Per-home webhook secret + 401 wrong / 200 right / 404 unknown
"""

import json
import pytest


# ============================================================================
# 1. ENCRYPTION ROUND-TRIP
# ============================================================================

class TestTokenEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        from ha_user_config import encrypt_token, decrypt_token
        plain = 'eyJhbGc.fake.token-with-special_chars-and=padding'
        enc = encrypt_token(plain)
        assert enc != plain
        assert decrypt_token(enc) == plain

    def test_ciphertext_changes_each_call(self):
        """Fernet uses random IV — same plaintext → different ciphertext."""
        from ha_user_config import encrypt_token
        a = encrypt_token('x' * 200)
        b = encrypt_token('x' * 200)
        assert a != b

    def test_decrypt_rejects_garbage(self):
        from cryptography.fernet import InvalidToken
        from ha_user_config import decrypt_token
        with pytest.raises(InvalidToken):
            decrypt_token('not-a-valid-fernet-token-base64')


# ============================================================================
# 2. DB OPERATIONS
# ============================================================================

class TestSaveHome:
    def test_save_home_first_is_default(self, app):
        """First home a user creates is auto-default."""
        from ha_user_config import save_home, _invalidate_client_cache
        _invalidate_client_cache()
        with app.app_context():
            home = save_home(
                user_id='alice',
                label='Hlavní byt',
                ha_url='http://10.0.0.5:8123',
                ha_token='fake-token-1' * 20,
                is_default=False,  # explicitly false but should still be default
            )
        assert home['is_default'] is True
        assert home['label'] == 'Hlavní byt'
        assert 'ha_token' not in home  # API never returns token
        assert 'ha_token_encrypted' not in home

    def test_save_second_home_not_default_unless_asked(self, app):
        from ha_user_config import save_home, get_home
        with app.app_context():
            save_home('bob', 'Hlavní', 'http://h1:8123', 'tok-' + 'a' * 200)
            second = save_home('bob', 'Chata', 'http://h2:8123', 'tok-' + 'b' * 200,
                               is_default=False)
            default = get_home('bob')
        assert second['is_default'] is False
        assert default['label'] == 'Hlavní'  # first is still default

    def test_promote_to_default_unsets_others(self, app):
        from ha_user_config import save_home, set_default_home, list_homes
        with app.app_context():
            h1 = save_home('carol', 'A', 'http://h1:8123', 'tok-' + 'a' * 200)
            h2 = save_home('carol', 'B', 'http://h2:8123', 'tok-' + 'b' * 200)
            ok = set_default_home('carol', h2['home_id'])
            homes = list_homes('carol')
        assert ok
        defaults = [h for h in homes if h['is_default']]
        assert len(defaults) == 1
        assert defaults[0]['home_id'] == h2['home_id']

    def test_per_user_isolation(self, app):
        """Two users with their own homes — different home_ids and secrets."""
        from ha_user_config import save_home, list_homes
        with app.app_context():
            save_home('user_a', 'A home', 'http://a:8123', 'tok-' + 'a' * 200)
            save_home('user_b', 'B home', 'http://b:8123', 'tok-' + 'b' * 200)
            a_homes = list_homes('user_a')
            b_homes = list_homes('user_b')
        assert len(a_homes) == 1
        assert len(b_homes) == 1
        assert a_homes[0]['home_id'] != b_homes[0]['home_id']
        assert a_homes[0]['ha_webhook_secret'] != b_homes[0]['ha_webhook_secret']

    def test_get_home_with_token_decrypts(self, app):
        from ha_user_config import save_home, get_home
        with app.app_context():
            saved = save_home('dave', 'Home', 'http://h:8123', 'plain-token-' + 'x' * 100)
            with_tok = get_home('dave', saved['home_id'], with_token=True)
        assert with_tok['ha_token'] == 'plain-token-' + 'x' * 100
        # API-style (no with_token) never has it
        without = get_home('dave', saved['home_id'])
        assert 'ha_token' not in without

    def test_delete_home_removes_row(self, app):
        from ha_user_config import save_home, delete_home, list_homes
        with app.app_context():
            saved = save_home('eve', 'Home', 'http://h:8123', 'tok-' + 'x' * 200)
            ok = delete_home('eve', saved['home_id'])
            after = list_homes('eve')
        assert ok
        assert after == []

    def test_delete_other_users_home_fails(self, app):
        """Ownership check — eve cannot delete frank's home."""
        from ha_user_config import save_home, delete_home, list_homes
        with app.app_context():
            f_home = save_home('frank', 'Home', 'http://h:8123', 'tok-' + 'f' * 200)
            ok = delete_home('eve', f_home['home_id'])  # wrong user
            after = list_homes('frank')
        assert ok is False
        assert len(after) == 1  # still there


# ============================================================================
# 3. ha_for_user FACTORY
# ============================================================================

class TestHaForUser:
    def test_no_config_returns_none(self, app):
        from ha_user_config import ha_for_user
        with app.app_context():
            client = ha_for_user('user-without-config')
        assert client is None

    def test_empty_user_id_returns_none(self):
        from ha_user_config import ha_for_user
        assert ha_for_user('') is None
        assert ha_for_user(None) is None

    def test_returns_real_client_when_configured(self, app):
        """Even with a fake URL, ha_for_user should construct a client.
        We check the type and that token decrypt works."""
        from ha_user_config import save_home, ha_for_user
        with app.app_context():
            saved = save_home('grace', 'Home', 'http://1.2.3.4:8123',
                              'fake-token-' + 'x' * 200)
            client = ha_for_user('grace')
        assert client is not None
        assert client.url == 'http://1.2.3.4:8123'
        assert client.token == 'fake-token-' + 'x' * 200
        assert getattr(client, '_home_id', None) == saved['home_id']


# ============================================================================
# 4. API ROUTES — auth + validation + no token leak
# ============================================================================

class TestConfigRoutesRequireAuth:
    def test_list_requires_auth(self, client):
        r = client.get('/api/ha/config')
        assert r.status_code in (401, 403)

    def test_create_requires_auth(self, client):
        r = client.post('/api/ha/config', json={
            'label': 'X', 'ha_url': 'http://h:8123', 'ha_token': 'x' * 200
        })
        assert r.status_code in (401, 403)

    def test_get_requires_auth(self, client):
        r = client.get('/api/ha/config/some-id')
        assert r.status_code in (401, 403)

    def test_update_requires_auth(self, client):
        r = client.put('/api/ha/config/some-id', json={'label': 'X'})
        assert r.status_code in (401, 403)

    def test_delete_requires_auth(self, client):
        r = client.delete('/api/ha/config/some-id')
        assert r.status_code in (401, 403)

    def test_test_requires_auth(self, client):
        r = client.post('/api/ha/config/some-id/test')
        assert r.status_code in (401, 403)

    def test_default_requires_auth(self, client):
        r = client.post('/api/ha/config/some-id/default')
        assert r.status_code in (401, 403)


# ============================================================================
# 5. PER-HOME WEBHOOK
# ============================================================================

class TestPerHomeWebhook:
    def test_unknown_home_returns_404(self, client):
        r = client.post(
            '/api/ha/webhook/00000000-0000-0000-0000-000000000000',
            headers={'X-HA-Secret': 'whatever'},
            json={'event_type': 'test'},
        )
        assert r.status_code == 404

    def test_correct_secret_accepts(self, app, client):
        from ha_user_config import save_home
        with app.app_context():
            home = save_home('hank', 'Home', 'http://h:8123', 'tok-' + 'x' * 200)
        secret = home['ha_webhook_secret']
        r = client.post(
            f'/api/ha/webhook/{home["home_id"]}',
            headers={'X-HA-Secret': secret},
            json={'event_type': 'motion_detected',
                  'entity_id': 'binary_sensor.motion_kitchen',
                  'new_state': 'on'},
        )
        assert r.status_code == 200
        assert r.get_json()['home_id'] == home['home_id']

    def test_wrong_secret_rejects(self, app, client):
        from ha_user_config import save_home
        with app.app_context():
            home = save_home('iris', 'Home', 'http://h:8123', 'tok-' + 'x' * 200)
        r = client.post(
            f'/api/ha/webhook/{home["home_id"]}',
            headers={'X-HA-Secret': 'definitely-not-the-secret'},
            json={'event_type': 'test'},
        )
        assert r.status_code == 401

    def test_missing_secret_rejects(self, app, client):
        from ha_user_config import save_home
        with app.app_context():
            home = save_home('jane', 'Home', 'http://h:8123', 'tok-' + 'x' * 200)
        r = client.post(
            f'/api/ha/webhook/{home["home_id"]}',
            json={'event_type': 'test'},
        )
        assert r.status_code == 401

    def test_secret_per_home_uniqueness(self, app):
        """Two homes for same user → different webhook secrets."""
        from ha_user_config import save_home
        with app.app_context():
            h1 = save_home('kyle', 'A', 'http://a:8123', 'tok-' + 'a' * 200)
            h2 = save_home('kyle', 'B', 'http://b:8123', 'tok-' + 'b' * 200)
        assert h1['ha_webhook_secret'] != h2['ha_webhook_secret']


# ============================================================================
# 6. NO TOKEN LEAK
# ============================================================================

class TestNoTokenLeak:
    def test_list_homes_never_includes_token(self, app):
        from ha_user_config import save_home, list_homes
        with app.app_context():
            save_home('leon', 'Home', 'http://h:8123', 'super-secret-token-' + 'x' * 100)
            homes = list_homes('leon')
        for h in homes:
            assert 'ha_token' not in h
            assert 'ha_token_encrypted' not in h

    def test_get_home_default_no_token(self, app):
        from ha_user_config import save_home, get_home
        with app.app_context():
            saved = save_home('mara', 'Home', 'http://h:8123', 'super-secret-' + 'x' * 100)
            home = get_home('mara', saved['home_id'])
        assert 'ha_token' not in home
        assert 'ha_token_encrypted' not in home
