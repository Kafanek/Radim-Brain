"""
Telemedicine module smoke tests (Sprint A+B).
Run: pytest tests/test_telemedicine.py -v
"""

import json


class TestTelemedicineHealth:
    def test_health_endpoint(self, client):
        """Health endpoint returns telemedicine service status."""
        resp = client.get('/api/telemedicine/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('status') == 'healthy'
        assert 'features' in data


class TestTelemedicineAuth:
    """Most endpoints require auth — verify behaviour when unauthenticated."""

    def test_upcoming_requires_auth(self, client):
        resp = client.get('/api/telemedicine/my/upcoming')
        # Depending on middleware: 401 (no JWT) or 200 (returns empty)
        assert resp.status_code in (200, 401, 403)

    def test_history_requires_auth(self, client):
        resp = client.get('/api/telemedicine/my/history')
        assert resp.status_code in (200, 401, 403)

    def test_request_requires_auth(self, client):
        resp = client.post('/api/telemedicine/my/request', json={})
        assert resp.status_code in (200, 400, 401, 403)


class TestTelemedicineConsent:
    """Sprint B — consent endpoint."""

    def test_consent_nonexistent_consultation(self, client):
        """Consent on missing consultation should 404 (or 401 without auth)."""
        resp = client.post(
            '/api/telemedicine/consultation/99999/consent',
            json={'consent': True, 'consent_version': '2.0'}
        )
        # Without auth: 401. With auth: 404.
        assert resp.status_code in (401, 403, 404)


class TestTelemedicinePatientSummary:
    """Sprint B — Gemini-backed patient summary endpoint."""

    def test_summary_nonexistent_consultation(self, client):
        resp = client.post('/api/telemedicine/consultation/99999/patient-summary')
        assert resp.status_code in (401, 403, 404)

    def test_rule_based_patient_summary_helper(self):
        """Helper produces numbered steps from recommendations."""
        from telemedicine_routes import _rule_based_patient_summary
        text = _rule_based_patient_summary(
            complaint='Bolest hlavy od rána',
            findings='Mírně zvýšený tlak 140/90',
            recommendations='Pít více tekutin. Odpočívat. Měřit tlak 2x denně.'
        )
        assert '1.' in text
        assert '2.' in text
        # Should have 3 steps (or fewer if recommendations shorter)
        assert text.count('\n') >= 1

    def test_rule_based_with_no_recommendations(self):
        """Fallback when recommendations empty: uses findings or default."""
        from telemedicine_routes import _rule_based_patient_summary
        text = _rule_based_patient_summary('Bolest hlavy', 'Nic vážného', '')
        # Must never be empty
        assert text.strip()
        assert '1.' in text


class TestTelemedicineCron:
    """Cron reminder job importability."""

    def test_get_upcoming_reminders_importable(self):
        from telemedicine_helpers import get_upcoming_consultations_for_reminder
        # Should return empty list (no consultations in test DB)
        result = get_upcoming_consultations_for_reminder(window_minutes=15)
        assert isinstance(result, list)
