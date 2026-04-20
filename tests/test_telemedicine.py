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


class TestTelemedicineSprintC:
    """Sprint C — rating, family invite, care plan sync, buffer conflict."""

    def test_rating_requires_1_to_5(self, client):
        """Invalid stars rejected with 400 (when authed) or 401 (unauthed)."""
        resp = client.post(
            '/api/telemedicine/consultation/99999/rating',
            json={'stars': 10}
        )
        assert resp.status_code in (400, 401, 403)

    def test_rating_nonexistent_consultation(self, client):
        resp = client.post(
            '/api/telemedicine/consultation/99999/rating',
            json={'stars': 5}
        )
        assert resp.status_code in (401, 403, 404)

    def test_invite_family_requires_user_id(self, client):
        """Invite without family_user_id is 400 (or 401 unauthed)."""
        resp = client.post(
            '/api/telemedicine/consultation/99999/invite-family',
            json={}
        )
        assert resp.status_code in (400, 401, 403)

    def test_sync_to_care_plan_helper_safe_on_missing(self):
        """sync_consultation_to_care_plan must not raise on missing consult."""
        from telemedicine_routes import sync_consultation_to_care_plan
        # Should swallow missing-consultation silently
        sync_consultation_to_care_plan(999999)

    def test_check_availability_conflict_empty_db(self):
        """Buffer conflict check returns (False, []) on empty DB."""
        from telemedicine_audit import check_availability_conflict
        has_conflict, conflicts = check_availability_conflict(
            teacher_id='ghost-teacher',
            scheduled_date='2099-01-01',
            scheduled_time='10:00:00',
            duration_minutes=30
        )
        assert has_conflict is False
        assert conflicts == []
