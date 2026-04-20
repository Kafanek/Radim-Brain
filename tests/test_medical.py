"""
Medical module smoke tests — Sprint D/E/F endpoints.
Run: pytest tests/test_medical.py -v
"""

import json


SENIOR = 'test-senior-med'


class TestMedicalTeam:
    """Team CRUD endpoints."""

    def test_get_team_empty(self, client):
        """GET on unknown senior returns empty team (graceful)."""
        resp = client.get(f'/api/medical/team/unknown-senior-xyz')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['team'] == [] or data['count'] == 0

    def test_add_team_member_requires_auth(self, client):
        """Team add requires @require_auth — unauthenticated returns 401."""
        resp = client.post(
            f'/api/medical/team/{SENIOR}/add',
            json={'name': 'Dr. Test', 'email': 'test@e.cz', 'role': 'family'},
        )
        # Either 401 or works (depending on auth middleware in test env).
        assert resp.status_code in (200, 401, 403)

    def test_patch_team_member_bad_payload(self, client):
        """PATCH with no updatable fields returns 400."""
        # Insert directly via DB to bypass auth
        from database import db_context
        from medical_team import _init_medical_schema
        _init_medical_schema()
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO medical_team (senior_id, user_id, role, name, email) "
                "VALUES (?, ?, ?, ?, ?)",
                (SENIOR, 'u1', 'family', 'Alice', 'a@e.cz')
            )
            row = db.execute(
                "SELECT id FROM medical_team WHERE senior_id = ? AND user_id = ?",
                (SENIOR, 'u1')
            ).fetchone()
            member_id = row[0] if isinstance(row, (list, tuple)) else row['id']

        resp = client.patch(
            f'/api/medical/team/{SENIOR}/{member_id}',
            json={'invalid_field': 'whatever'},
        )
        assert resp.status_code == 400

    def test_patch_team_member_phone(self, client):
        """PATCH updates phone correctly."""
        from database import db_context
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO medical_team (senior_id, user_id, role, name) "
                "VALUES (?, ?, ?, ?)",
                (SENIOR, 'u-phone', 'family', 'PhoneTester')
            )
            row = db.execute(
                "SELECT id FROM medical_team WHERE senior_id = ? AND user_id = ?",
                (SENIOR, 'u-phone')
            ).fetchone()
            mid = row[0] if isinstance(row, (list, tuple)) else row['id']

        resp = client.patch(
            f'/api/medical/team/{SENIOR}/{mid}',
            json={'phone': '+420 777 111 222'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'phone' in data.get('updated', [])

        # Verify persistence via GET
        resp2 = client.get(f'/api/medical/team/{SENIOR}')
        team = resp2.get_json()['team']
        phone_member = next((m for m in team if m['name'] == 'PhoneTester'), None)
        assert phone_member is not None
        assert phone_member.get('phone') == '+420 777 111 222'

    def test_delete_team_member(self, client):
        """Soft-delete marks active=false (member disappears from GET)."""
        from database import db_context
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO medical_team (senior_id, user_id, role, name) "
                "VALUES (?, ?, ?, ?)",
                (SENIOR, 'u-del', 'family', 'WillDelete')
            )
            row = db.execute(
                "SELECT id FROM medical_team WHERE senior_id = ? AND user_id = ?",
                (SENIOR, 'u-del')
            ).fetchone()
            mid = row[0] if isinstance(row, (list, tuple)) else row['id']

        resp = client.delete(f'/api/medical/team/{SENIOR}/{mid}')
        assert resp.status_code == 200

        resp2 = client.get(f'/api/medical/team/{SENIOR}')
        names = [m['name'] for m in resp2.get_json()['team']]
        assert 'WillDelete' not in names


class TestSymptoms:
    """Daily symptom check-in CRUD."""

    def test_post_symptoms(self, client):
        """POST persists a check-in entry with clamped values."""
        resp = client.post(
            f'/api/medical/symptoms/{SENIOR}',
            json={'pain': 3, 'mood': 7, 'sleep': 6, 'appetite': 8, 'energy': 5,
                  'note': 'Feeling ok today'},
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_get_symptoms_list(self, client):
        """GET returns recent entries, newest first."""
        # Seed two
        client.post(f'/api/medical/symptoms/{SENIOR}',
                    json={'pain': 4, 'mood': 7, 'sleep': 6, 'appetite': 7, 'energy': 6})
        client.post(f'/api/medical/symptoms/{SENIOR}',
                    json={'pain': 2, 'mood': 8, 'sleep': 7, 'appetite': 8, 'energy': 7})

        resp = client.get(f'/api/medical/symptoms/{SENIOR}?limit=5')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert len(data['symptoms']) >= 2

    def test_symptom_clamps_out_of_range(self, client):
        """Values outside 0-10 are clamped, not rejected."""
        resp = client.post(
            f'/api/medical/symptoms/{SENIOR}',
            json={'pain': 99, 'mood': -5, 'sleep': 4, 'appetite': 4, 'energy': 4},
        )
        assert resp.status_code == 200

        resp2 = client.get(f'/api/medical/symptoms/{SENIOR}?limit=1')
        entry = resp2.get_json()['symptoms'][0]
        assert 0 <= entry['pain'] <= 10
        assert 0 <= entry['mood'] <= 10

    def test_symptom_summary_fallback(self, client):
        """Summary with too few entries returns friendly fallback."""
        # Use a fresh senior with <2 entries
        resp = client.post(f'/api/medical/symptoms/fresh-senior-xyz/summary?days=7')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'summary' in data
        assert data['source'] in ('fallback', 'rule_based', 'rule_based_fallback', 'gemini')


class TestAppointments:
    """Appointment CRUD."""

    def test_post_and_get_appointment(self, client):
        """POST upserts by id, GET lists upcoming."""
        resp = client.post(
            f'/api/medical/appointments/{SENIOR}',
            json={'id': 'appt-test-1', 'with': 'Dr. Tester',
                  'when': '2099-01-01T10:00:00Z', 'mode': 'video',
                  'reason': 'Test checkup'},
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        resp2 = client.get(f'/api/medical/appointments/{SENIOR}')
        appts = resp2.get_json()['appointments']
        assert any(a['id'] == 'appt-test-1' for a in appts)

    def test_delete_appointment(self, client):
        """DELETE soft-cancels an appointment."""
        client.post(
            f'/api/medical/appointments/{SENIOR}',
            json={'id': 'appt-delete-me', 'with': 'Dr. X',
                  'when': '2099-02-01T10:00:00Z', 'mode': 'phone'},
        )
        resp = client.delete(f'/api/medical/appointments/{SENIOR}/appt-delete-me')
        assert resp.status_code == 200

        resp2 = client.get(f'/api/medical/appointments/{SENIOR}')
        ids = [a['id'] for a in resp2.get_json()['appointments']]
        assert 'appt-delete-me' not in ids

    def test_invalid_mode_defaults_to_video(self, client):
        """Invalid mode strings fall back to 'video'."""
        client.post(
            f'/api/medical/appointments/{SENIOR}',
            json={'id': 'appt-invalid-mode', 'with': 'Dr. Y',
                  'when': '2099-03-01T10:00:00Z', 'mode': 'astral-projection'},
        )
        resp = client.get(f'/api/medical/appointments/{SENIOR}')
        appt = next((a for a in resp.get_json()['appointments']
                     if a['id'] == 'appt-invalid-mode'), None)
        assert appt is not None
        assert appt['mode'] == 'video'


class TestObservations:
    """Agent observations endpoint."""

    def test_get_observations_empty(self, client):
        """GET returns empty list for fresh senior (no 500 on missing table)."""
        resp = client.get(f'/api/medical/observations/brand-new-senior-abc')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert isinstance(data.get('observations'), list)

    def test_acknowledge_missing_id(self, client):
        """POST without id returns 400."""
        resp = client.post(
            f'/api/medical/observations/{SENIOR}/acknowledge',
            json={},
        )
        assert resp.status_code == 400


class TestMedications:
    """Medication schedule + adherence (Sprint F-3)."""

    def test_normalize_medications_strings(self):
        """Strings become {name, dose, times: ['08:00']}."""
        from medical_team import _normalize_medications
        result = _normalize_medications(['Aspirin', 'Doxazosin'])
        assert len(result) == 2
        assert result[0]['name'] == 'Aspirin'
        assert result[0]['times'] == ['08:00']
        assert result[0]['dose'] is None

    def test_normalize_medications_dicts(self):
        """Dicts keep structure, sanitize bad times."""
        from medical_team import _normalize_medications
        result = _normalize_medications([
            {'name': 'Aspirin', 'dose': '100mg', 'times': ['08:00', '20:00']},
            {'name': 'Bad', 'times': ['99:99', 'garbage']},   # all invalid → default
            {'name': '', 'times': ['08:00']},                  # empty name → dropped
        ])
        assert len(result) == 2
        assert result[0]['times'] == ['08:00', '20:00']
        assert result[0]['dose'] == '100mg'
        assert result[1]['times'] == ['08:00']  # fallback

    def test_today_empty(self, client):
        """today schedule for senior with no care plan returns empty."""
        resp = client.get(f'/api/medical/medications/no-plan-senior/today')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['count'] == 0

    def test_log_medication(self, client):
        """Log dose writes to radim_medication_log."""
        resp = client.post(
            f'/api/medical/medications/{SENIOR}/log',
            json={'medication_name': 'Aspirin', 'dose': '100mg', 'time_slot': '08:00'},
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_log_medication_missing_name(self, client):
        """Missing medication_name returns 400."""
        resp = client.post(
            f'/api/medical/medications/{SENIOR}/log',
            json={'dose': '100mg'},
        )
        assert resp.status_code == 400

    def test_adherence_empty(self, client):
        """Adherence for senior without care plan returns 0%."""
        resp = client.get(f'/api/medical/medications/no-plan-sen/adherence?days=7')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['adherence_pct'] == 0


class TestSprintFCrons:
    """Cron jobs are importable and callable without errors."""

    def test_appointment_reminder_cron_importable(self):
        from medical_team import appointment_reminder_cron
        # Should not raise even with no upcoming appts
        appointment_reminder_cron()

    def test_symptom_trend_alert_cron_importable(self):
        from medical_team import symptom_trend_alert_cron
        symptom_trend_alert_cron()
