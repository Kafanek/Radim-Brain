# ============================================
# Tests for Telemedicine Audit & Policy v4.1
# ============================================

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATABASE_URL', '')
os.environ.setdefault('GEMINI_API_KEY', 'test-key')


# ============================================
# POLICY MATRIX TESTS (Point 3)
# ============================================

class TestPolicyMatrix:
    """Test ABAC policy matrix correctness."""

    def test_organizer_has_all_permissions(self):
        from telemedicine_audit import POLICY_MATRIX
        perms = POLICY_MATRIX['organizer']
        assert perms['view_clinical'] is True
        assert perms['edit_summary'] is True
        assert perms['start_session'] is True
        assert perms['end_session'] is True
        assert perms['invite_participants'] is True
        assert perms['remove_participants'] is True
        assert perms['view_audit_trail'] is True
        assert perms['send_summary_email'] is True
        assert perms['lock_clinical_notes'] is True

    def test_patient_has_no_clinical_access(self):
        from telemedicine_audit import POLICY_MATRIX
        perms = POLICY_MATRIX['patient']
        assert perms['view_clinical'] is False
        assert perms['edit_own_notes'] is False
        assert perms['edit_summary'] is False
        assert perms['view_internal'] is False
        assert perms['start_session'] is False
        assert perms['view_audit_trail'] is False

    def test_observer_is_read_only(self):
        from telemedicine_audit import POLICY_MATRIX
        perms = POLICY_MATRIX['observer']
        for perm, val in perms.items():
            assert val is False, f"observer should not have {perm}"

    def test_specialist_can_edit_own_notes_only(self):
        from telemedicine_audit import POLICY_MATRIX
        perms = POLICY_MATRIX['specialist']
        assert perms['view_clinical'] is True
        assert perms['edit_own_notes'] is True
        assert perms['edit_summary'] is False
        assert perms['start_session'] is False
        assert perms['invite_participants'] is False

    def test_therapist_cannot_invite(self):
        from telemedicine_audit import POLICY_MATRIX
        perms = POLICY_MATRIX['therapist']
        assert perms['view_clinical'] is True
        assert perms['edit_summary'] is True
        assert perms['invite_participants'] is False
        assert perms['remove_participants'] is False

    def test_caregiver_proxy_same_as_patient(self):
        from telemedicine_audit import POLICY_MATRIX
        patient = POLICY_MATRIX['patient']
        proxy = POLICY_MATRIX['caregiver_proxy']
        for perm in patient:
            assert patient[perm] == proxy[perm], f"caregiver_proxy should match patient for {perm}"

    def test_all_roles_present(self):
        from telemedicine_audit import POLICY_MATRIX, VALID_CONSULTATION_ROLES
        expected = {'organizer', 'therapist', 'specialist', 'observer', 'patient', 'caregiver_proxy'}
        assert set(POLICY_MATRIX.keys()) == expected
        assert set(VALID_CONSULTATION_ROLES) == expected

    def test_all_roles_have_same_permissions(self):
        """Ensure no role is missing a permission key."""
        from telemedicine_audit import POLICY_MATRIX
        all_perms = set()
        for role_perms in POLICY_MATRIX.values():
            all_perms.update(role_perms.keys())
        for role, perms in POLICY_MATRIX.items():
            for perm in all_perms:
                assert perm in perms, f"Role '{role}' missing permission '{perm}'"


# ============================================
# CONSTANTS & ENUMS TESTS (Point 1)
# ============================================

class TestGDPRConstants:
    """Test GDPR classification constants."""

    def test_sensitivity_levels(self):
        from telemedicine_helpers import SENSITIVITY_LEVELS
        assert 'health_data' in SENSITIVITY_LEVELS
        assert 'special_category' in SENSITIVITY_LEVELS
        assert 'operational' in SENSITIVITY_LEVELS

    def test_legal_bases(self):
        from telemedicine_helpers import LEGAL_BASES
        assert 'consent_art9' in LEGAL_BASES
        assert 'vital_interest' in LEGAL_BASES

    def test_retention_classes(self):
        from telemedicine_helpers import RETENTION_CLASSES
        assert 'clinical_5y' in RETENTION_CLASSES
        assert 'operational_1y' in RETENTION_CLASSES
        assert 'audit_10y' in RETENTION_CLASSES

    def test_participant_roles_include_caregiver_proxy(self):
        from telemedicine_helpers import PARTICIPANT_ROLES
        assert 'caregiver_proxy' in PARTICIPANT_ROLES

    def test_email_modes(self):
        from telemedicine_helpers import EMAIL_MODES
        assert 'brief_notification' in EMAIL_MODES
        assert 'full_summary' in EMAIL_MODES


# ============================================
# EVENT TYPES TESTS (Point 2)
# ============================================

class TestEventTypes:
    """Test audit event type completeness."""

    def test_all_lifecycle_events_covered(self):
        from telemedicine_audit import EVENT_TYPES
        lifecycle = [
            'consultation_requested', 'consultation_confirmed',
            'consultation_started', 'consultation_completed',
            'consultation_cancelled',
        ]
        for ev in lifecycle:
            assert ev in EVENT_TYPES, f"Missing lifecycle event: {ev}"

    def test_participant_events_covered(self):
        from telemedicine_audit import EVENT_TYPES
        participant = [
            'participant_invited', 'participant_accepted',
            'participant_declined', 'participant_removed',
            'participant_joined', 'participant_left',
        ]
        for ev in participant:
            assert ev in EVENT_TYPES, f"Missing participant event: {ev}"

    def test_notes_and_join_events(self):
        from telemedicine_audit import EVENT_TYPES
        assert 'notes_written' in EVENT_TYPES
        assert 'notes_viewed' in EVENT_TYPES
        assert 'join_token_generated' in EVENT_TYPES
        assert 'join_url_accessed' in EVENT_TYPES
        assert 'summary_emailed' in EVENT_TYPES


# ============================================
# JOIN TOKEN TESTS (Point 4)
# ============================================

class TestJoinTokenConfig:
    """Test join token configuration."""

    def test_token_ttl_reasonable(self):
        from telemedicine_audit import JOIN_TOKEN_TTL_MINUTES
        assert 10 <= JOIN_TOKEN_TTL_MINUTES <= 60, "Token TTL should be 10-60 minutes"


# ============================================
# FUNCTIONAL TESTS WITH DB (using conftest app fixture)
# ============================================

class TestAuditWithDB:
    """Integration tests for audit functions with database."""

    def test_log_event_does_not_raise(self, app):
        """log_event should never raise, even with bad data."""
        with app.app_context():
            from telemedicine_audit import log_event
            # Should not raise — non-fatal by design
            log_event(99999, 'test_event', 'test_user')

    def test_get_audit_trail_empty(self, app):
        """get_audit_trail should return empty list for nonexistent consultation."""
        with app.app_context():
            from telemedicine_audit import get_audit_trail
            trail = get_audit_trail(99999)
            assert isinstance(trail, list)

    def test_compute_quality_kpis_empty(self, app):
        """compute_quality_kpis should handle empty data gracefully."""
        with app.app_context():
            from telemedicine_audit import compute_quality_kpis
            kpis = compute_quality_kpis(30)
            assert isinstance(kpis, dict)
            # Either error or zero consultations
            assert 'total_consultations' in kpis or 'error' in kpis

    def test_check_join_eligibility_nonexistent(self, app):
        """check_join_eligibility should fail gracefully for nonexistent consultation."""
        with app.app_context():
            from telemedicine_audit import check_join_eligibility
            eligible, reason = check_join_eligibility(99999, 'test_user')
            assert eligible is False
            assert 'nenalezena' in reason.lower()

    def test_check_availability_conflict_no_data(self, app):
        """check_availability_conflict should return no conflict when no data."""
        with app.app_context():
            from telemedicine_audit import check_availability_conflict
            has_conflict, conflicts = check_availability_conflict(
                'nonexistent_teacher', '2026-01-01', '10:00', 30
            )
            assert has_conflict is False
            assert conflicts == []

    def test_log_quality_metric_does_not_raise(self, app):
        """log_quality_metric should not raise."""
        with app.app_context():
            from telemedicine_audit import log_quality_metric
            # Should not raise
            log_quality_metric(None, 'test_metric', 42.0, {'note': 'test'})
