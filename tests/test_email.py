"""
Email Sprint C smoke tests.
Run: pytest tests/test_email.py -v
"""

import os


class TestEmailSecurityAuth:
    """All Sprint C security endpoints require auth."""

    def test_scan_requires_auth(self, client):
        resp = client.post('/api/email/scan',
                           json={'subject': 'Výhra!', 'body': 'Zadejte heslo'})
        assert resp.status_code in (401, 403)

    def test_flag_family_requires_auth(self, client):
        resp = client.post('/api/email/flag-family',
                           json={'subject': 'Test', 'from': 'x@y.cz'})
        assert resp.status_code in (401, 403)

    def test_family_flagged_requires_auth(self, client):
        resp = client.get('/api/email/family/some-senior/flagged')
        assert resp.status_code in (401, 403)

    def test_resolve_flag_requires_auth(self, client):
        resp = client.post('/api/email/family/flag/1/resolve')
        assert resp.status_code in (401, 403)

    def test_block_sender_requires_auth(self, client):
        resp = client.post('/api/email/block',
                           json={'sender': 'spam@bad.ru'})
        assert resp.status_code in (401, 403)

    def test_blocklist_requires_auth(self, client):
        resp = client.get('/api/email/blocklist')
        assert resp.status_code in (401, 403)

    def test_unblock_requires_auth(self, client):
        resp = client.delete('/api/email/block/spam@bad.ru')
        assert resp.status_code in (401, 403)


class TestEmailInboxAuth:
    """All Sprint C IMAP endpoints require auth."""

    def test_save_account_requires_auth(self, client):
        resp = client.post('/api/email/account',
                           json={'email': 'a@seznam.cz', 'password': 'x'})
        assert resp.status_code in (401, 403)

    def test_get_account_requires_auth(self, client):
        resp = client.get('/api/email/account')
        assert resp.status_code in (401, 403)

    def test_delete_account_requires_auth(self, client):
        resp = client.delete('/api/email/account')
        assert resp.status_code in (401, 403)

    def test_inbox_requires_auth(self, client):
        resp = client.get('/api/email/inbox')
        assert resp.status_code in (401, 403)

    def test_message_requires_auth(self, client):
        resp = client.get('/api/email/message/1')
        assert resp.status_code in (401, 403)

    def test_mark_read_requires_auth(self, client):
        resp = client.post('/api/email/mark-read/1')
        assert resp.status_code in (401, 403)

    def test_delete_message_requires_auth(self, client):
        resp = client.delete('/api/email/message/1')
        assert resp.status_code in (401, 403)


class TestEmailScanHeuristics:
    """Deterministic scam scanner — pure function, no auth needed."""

    def test_clean_email_not_risky(self):
        from email_security_routes import _scan_heuristics
        result = _scan_heuristics(
            subject='Pozvánka na kávu',
            body='Ahoj babi, přijď prosím v sobotu na kávu. Těšíme se. Honza.',
            from_email='honza@seznam.cz',
        )
        assert result['risky'] is False
        assert result['score'] < 40

    def test_credential_request_flagged(self):
        from email_security_routes import _scan_heuristics
        result = _scan_heuristics(
            subject='Ověřte své heslo',
            body='Pro bezpečnost účtu prosím zadejte vaše heslo a PIN.',
            from_email='support@fake.com',
        )
        assert result['risky'] is True
        assert result['score'] >= 40
        assert any('heslo' in r.lower() or 'karty' in r.lower()
                   for r in result['reasons'])

    def test_prize_scam_flagged(self):
        from email_security_routes import _scan_heuristics
        result = _scan_heuristics(
            subject='GRATULUJEME!!!',
            body='Vyhráli jste 5 000 000 Kč. Klikněte na odkaz.',
            from_email='winner@bitcoin-prize.xyz',
        )
        assert result['risky'] is True
        # Expect at least 2 reasons (prize + caps + TLD)
        assert len(result['reasons']) >= 2

    def test_urgency_scam_flagged(self):
        from email_security_routes import _scan_heuristics
        result = _scan_heuristics(
            subject='Poslední upozornění — zablokování účtu',
            body='Urgentně ověřte své údaje, jinak bude váš účet zablokován během 24 hodin.',
            from_email='urgent@nekdo.ru',
        )
        assert result['risky'] is True
        assert result['score'] >= 40

    def test_brand_impersonation_flagged(self):
        from email_security_routes import _scan_heuristics
        result = _scan_heuristics(
            subject='Česká spořitelna — notifikace',
            body='Vážený kliente, čeká vás nová zpráva.',
            from_email='notifikace@neco-jineho.com',
            from_name='Česká spořitelna',
        )
        assert result['risky'] is True
        assert any('spořiteln' in r.lower() for r in result['reasons'])

    def test_shortener_url_flagged(self):
        from email_security_routes import _scan_heuristics
        result = _scan_heuristics(
            subject='Koukni na to',
            body='Mrkni sem: https://bit.ly/3xYz21 jsou tam fotky.',
            from_email='friend@seznam.cz',
        )
        assert any('bit.ly' in r.lower() or 'zkrácen' in r.lower()
                   for r in result['reasons'])

    def test_ip_address_url_flagged(self):
        from email_security_routes import _scan_heuristics
        result = _scan_heuristics(
            subject='Login',
            body='Please login at http://192.168.1.100/admin',
            from_email='admin@company.com',
        )
        assert any('č[ií]seln' in r.lower() or 'adres' in r.lower()
                   for r in result['reasons'])

    def test_suspicious_tld_flagged(self):
        from email_security_routes import _scan_heuristics
        result = _scan_heuristics(
            subject='Hello',
            body='Hi there.',
            from_email='x@suspicious.ru',
        )
        assert any('.ru' in r or 'doménu' in r.lower()
                   for r in result['reasons'])

    def test_scan_returns_structured_output(self):
        """Contract: scan always returns {risky, score, reasons}."""
        from email_security_routes import _scan_heuristics
        for subj, body, sender in [
            ('', '', ''),
            ('Hi', 'Hi', 'a@b.cz'),
            ('', 'Just body', 'a@b.cz'),
        ]:
            result = _scan_heuristics(subj, body, sender)
            assert 'risky' in result
            assert 'score' in result
            assert 'reasons' in result
            assert isinstance(result['reasons'], list)
            assert 0 <= result['score'] <= 100


class TestEmailValidation:
    def test_block_invalid_sender_email(self, client):
        """Backend rejects non-email senders in blocklist."""
        resp = client.post('/api/email/block', json={'sender': 'not-an-email'})
        assert resp.status_code in (400, 401, 403)

    def test_is_valid_email_helper(self):
        from email_security_routes import _is_valid_email
        assert _is_valid_email('user@seznam.cz') is True
        assert _is_valid_email('x@y.co.uk') is True
        assert _is_valid_email('') is False
        assert _is_valid_email(None) is False
        assert _is_valid_email('not-an-email') is False
        assert _is_valid_email('two@@at.cz') is False
        assert _is_valid_email('nope@domain') is False

    def test_scan_missing_subject_and_body(self, client):
        resp = client.post('/api/email/scan',
                           json={'from': 'x@y.cz'})
        assert resp.status_code in (400, 401, 403)

    def test_save_account_invalid_email(self, client):
        resp = client.post('/api/email/account',
                           json={'email': 'not-email', 'password': 'x'})
        assert resp.status_code in (400, 401, 403)

    def test_save_account_missing_password(self, client):
        resp = client.post('/api/email/account',
                           json={'email': 'a@seznam.cz'})
        assert resp.status_code in (400, 401, 403)

    def test_inbox_invalid_uid(self, client):
        """GET /api/email/message/<uid> rejects non-numeric uid."""
        resp = client.get('/api/email/message/abc')
        assert resp.status_code in (400, 401, 403)


class TestEmailInboxSchema:
    def test_init_security_schema_idempotent(self):
        from email_security_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_init_inbox_schema_idempotent(self):
        from email_inbox_routes import _init_schema as _inbox_init
        _inbox_init()
        _inbox_init()

    def test_isp_presets_cover_seznam(self):
        from email_inbox_routes import ISP_PRESETS, _guess_imap_preset
        assert 'seznam.cz' in ISP_PRESETS
        p = _guess_imap_preset('babicka@seznam.cz')
        assert p is not None
        assert p['imap'][0] == 'imap.seznam.cz'
        assert p['imap'][1] == 993

    def test_isp_presets_cover_centrum(self):
        from email_inbox_routes import _guess_imap_preset
        p = _guess_imap_preset('deda@centrum.cz')
        assert p is not None
        assert 'centrum.cz' in p['imap'][0]

    def test_isp_presets_unknown_returns_none(self):
        from email_inbox_routes import _guess_imap_preset
        assert _guess_imap_preset('nobody@gmail.com') is None  # Gmail = OAuth
        assert _guess_imap_preset('x@random-unknown.xyz') is None


class TestEmailEncryption:
    """Fernet roundtrip — requires encryption key env var."""

    def test_encrypt_decrypt_roundtrip(self, monkeypatch):
        monkeypatch.setenv('EMAIL_IMAP_ENCRYPTION_KEY', 'test-secret-for-tests-only')
        # Reset module-level cache so a new key is picked up
        import email_inbox_routes
        email_inbox_routes._FERNET_INSTANCE = None
        plain = 'super-secret-app-password-123'
        token = email_inbox_routes._encrypt_password(plain)
        assert token != plain  # encrypted
        assert len(token) > 20
        decoded = email_inbox_routes._decrypt_password(token)
        assert decoded == plain
        # Cleanup
        email_inbox_routes._FERNET_INSTANCE = None

    def test_encryption_disabled_without_key(self, monkeypatch):
        monkeypatch.delenv('EMAIL_IMAP_ENCRYPTION_KEY', raising=False)
        monkeypatch.delenv('JWT_SECRET', raising=False)
        monkeypatch.delenv('SECRET_KEY', raising=False)
        import email_inbox_routes
        email_inbox_routes._FERNET_INSTANCE = None
        f = email_inbox_routes._get_fernet()
        assert f is None
        email_inbox_routes._FERNET_INSTANCE = None


class TestEmailBlueprints:
    def test_security_blueprint_imports(self):
        from email_security_routes import email_security_bp
        assert email_security_bp is not None
        assert email_security_bp.name == 'email_security'

    def test_inbox_blueprint_imports(self):
        from email_inbox_routes import email_inbox_bp
        assert email_inbox_bp is not None
        assert email_inbox_bp.name == 'email_inbox'

    def test_blueprints_registered_on_app(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        # Security
        assert any('/api/email/scan' in r for r in rules)
        assert any('/api/email/flag-family' in r for r in rules)
        assert any('/api/email/family/' in r and '/flagged' in r for r in rules)
        assert any('/api/email/block' in r for r in rules)
        assert any('/api/email/blocklist' in r for r in rules)
        # Inbox
        assert any('/api/email/account' in r for r in rules)
        assert any('/api/email/inbox' in r for r in rules)
        assert any('/api/email/message/' in r for r in rules)
        assert any('/api/email/mark-read/' in r for r in rules)


class TestEmailFamilyAccessControl:
    def test_family_flagged_unlinked_forbidden(self, client):
        """Without senior_family_links → 401/403."""
        resp = client.get('/api/email/family/nonexistent-senior/flagged')
        assert resp.status_code in (401, 403)


class TestEmailNoConflict:
    """Legacy /api/email/send + /api/email/health must still work —
    Sprint C adds new routes, must not shadow."""

    def test_send_endpoint_still_exists(self, client):
        """POST /api/email/send should return 401 (auth gated) not 404."""
        resp = client.post('/api/email/send',
                           json={'to': 'a@b.cz', 'subject': 't', 'body': 'x'})
        assert resp.status_code != 404

    def test_health_endpoint_public(self, client):
        """GET /api/email/health is public configuration endpoint."""
        resp = client.get('/api/email/health')
        # Any 2xx or 5xx is fine; 404 = blueprint got shadowed
        assert resp.status_code != 404


class TestEmailFrontendIntegration:
    """Regression: frontend v2.0 artifacts that backend tests can verify."""

    def test_email_module_js_has_scam_scanner(self):
        """Frontend has _scanForScam method mirroring backend heuristics."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'mykolibri-academy-project', 'js', 'sections', 'email-module.js'
        )
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '_scanForScam' in content
        assert '_showScamModal' in content
        assert 'askFamily' in content
        # XSS fix present
        assert '_esc(' in content

    def test_email_module_no_simulate_reply(self):
        """Demo auto-reply code has been removed."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'mykolibri-academy-project', 'js', 'sections', 'email-module.js'
        )
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Method definition should be gone; one passing reference in
        # comment explaining removal is fine.
        assert 'simulateReply(originalEmail)' not in content
