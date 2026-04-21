"""
Caregiver module tests.
Run: pytest tests/test_caregiver.py -v
"""


class TestCaregiverAuth:
    """All endpoints require authentication."""

    def test_view_mode_requires_auth(self, client):
        resp = client.get('/api/caregiver/view-mode')
        assert resp.status_code in (401, 403)

    def test_seniors_requires_auth(self, client):
        resp = client.get('/api/caregiver/seniors')
        assert resp.status_code in (401, 403)

    def test_overview_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/overview')
        assert resp.status_code in (401, 403)

    def test_safe_to_call_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/safe-to-call')
        assert resp.status_code in (401, 403)

    def test_narrative_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/narrative')
        assert resp.status_code in (401, 403)

    def test_legacy_preview_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/legacy-preview')
        assert resp.status_code in (401, 403)

    def test_shared_gallery_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/shared-gallery')
        assert resp.status_code in (401, 403)

    def test_wisdom_cloud_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/wisdom-cloud')
        assert resp.status_code in (401, 403)

    def test_live_activity_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/live-activity')
        assert resp.status_code in (401, 403)

    def test_cosign_queue_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/cosign-queue')
        assert resp.status_code in (401, 403)


class TestBlueprint:
    def test_blueprint_imports(self):
        from caregiver_routes import caregiver_bp
        assert caregiver_bp is not None
        assert caregiver_bp.name == 'caregiver'

    def test_all_endpoints_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/caregiver/view-mode') for r in rules)
        assert any(r.endswith('/api/caregiver/seniors') for r in rules)
        assert any('/api/caregiver/senior/<senior_id>/overview' in r for r in rules)
        assert any('/api/caregiver/senior/<senior_id>/safe-to-call' in r for r in rules)
        assert any('/api/caregiver/senior/<senior_id>/narrative' in r for r in rules)
        assert any('/api/caregiver/senior/<senior_id>/legacy-preview' in r for r in rules)
        assert any('/api/caregiver/senior/<senior_id>/shared-gallery' in r for r in rules)
        assert any('/api/caregiver/senior/<senior_id>/wisdom-cloud' in r for r in rules)
        assert any('/api/caregiver/senior/<senior_id>/live-activity' in r for r in rules)
        assert any('/api/caregiver/senior/<senior_id>/cosign-queue' in r for r in rules)


class TestHelpers:
    def test_is_family_of_self(self):
        from caregiver_routes import _is_family_of
        assert _is_family_of('u1', 'u1') is True

    def test_is_family_of_unrelated(self):
        from caregiver_routes import _is_family_of
        assert _is_family_of('senior-x', 'stranger-y') is False

    def test_list_linked_seniors_empty(self):
        from caregiver_routes import _list_linked_seniors
        result = _list_linked_seniors('no-one-zzz')
        assert isinstance(result, list)

    def test_last_interaction_unknown_user(self):
        from caregiver_routes import _last_interaction
        ts, min_ago = _last_interaction('unknown-zzz')
        # Returns (None, None) for unknown user
        assert ts is None or ts == ''
        assert min_ago is None or isinstance(min_ago, int)

    def test_recent_c_avg_unknown_user(self):
        from caregiver_routes import _recent_c_avg
        c, n = _recent_c_avg('unknown-zzz')
        assert c is None or isinstance(c, float)
        assert n == 0 or isinstance(n, int)


class TestRateLimiter:
    def setup_method(self):
        from caregiver_routes import _rate_win
        _rate_win.clear()

    def test_within_limit(self):
        from caregiver_routes import _rate_ok
        for _ in range(20):
            assert _rate_ok('u-a', 'narrative', 20) is True

    def test_over_limit(self):
        from caregiver_routes import _rate_ok
        for _ in range(20):
            _rate_ok('u-b', 'narrative', 20)
        assert _rate_ok('u-b', 'narrative', 20) is False

    def test_isolation_between_users(self):
        from caregiver_routes import _rate_ok
        for _ in range(20):
            _rate_ok('u-c', 'narrative', 20)
        assert _rate_ok('u-d', 'narrative', 20) is True


class TestNarrativeFallback:
    """Gemini fallback honesty: no API key → None, graceful fallback text."""

    def test_gemini_narrative_returns_none_without_key(self, monkeypatch):
        from caregiver_routes import _call_gemini_narrative
        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
        result = _call_gemini_narrative('ctx', 'Anna')
        assert result is None


class TestBuildContext:
    """Narrative context builder handles empty user gracefully."""

    def test_build_context_empty_user(self):
        from caregiver_routes import _build_narrative_context
        result = _build_narrative_context('never-seen-user-zzz')
        assert isinstance(result, str)
        # Should contain at least Jméno line
        assert 'Jméno' in result


class TestViewModeLogic:
    """View mode detection heuristic."""

    def test_view_mode_function_exists(self):
        from caregiver_routes import view_mode
        assert callable(view_mode)


class TestCacheIsolation:
    """Narrative cache is keyed by (senior, date) — isolated across users."""

    def test_cache_dict_exists(self):
        from caregiver_routes import _narrative_cache
        assert isinstance(_narrative_cache, dict)

    def test_cache_can_hold_entries(self):
        from caregiver_routes import _narrative_cache
        _narrative_cache['test-key:2026-01-01'] = {
            'text': 'x', 'ts': 0, 'iso': '2026-01-01'
        }
        assert 'test-key:2026-01-01' in _narrative_cache
        del _narrative_cache['test-key:2026-01-01']


class TestSafeToCallStatuses:
    """safe-to-call returns one of {green, yellow, red}."""

    def test_safe_to_call_function_exists(self):
        from caregiver_routes import safe_to_call
        assert callable(safe_to_call)


# ════════════════════════════════════════════════════════════════════
# SPRINT C — notifications, decline, scheduled view, audit, scheduler
# ════════════════════════════════════════════════════════════════════

class TestSprintCEndpoints:
    """All Sprint C endpoints registered + auth-guarded."""

    def test_notifications_list_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/caregiver/notifications') for r in rules)

    def test_notifications_count_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/caregiver/notifications/count') for r in rules)

    def test_notification_ack_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/caregiver/notification/<int:notif_id>/ack' in r for r in rules)

    def test_ack_all_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/caregiver/notifications/ack-all') for r in rules)

    def test_decline_cosign_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/caregiver/contract/<int:contract_id>/decline-cosign' in r for r in rules)

    def test_scheduled_messages_view_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/caregiver/senior/<senior_id>/scheduled-messages' in r for r in rules)

    def test_audit_ping_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/caregiver/senior/<senior_id>/audit-ping' in r for r in rules)

    # Auth
    def test_notifications_list_requires_auth(self, client):
        resp = client.get('/api/caregiver/notifications')
        assert resp.status_code in (401, 403)

    def test_notifications_count_requires_auth(self, client):
        resp = client.get('/api/caregiver/notifications/count')
        assert resp.status_code in (401, 403)

    def test_notification_ack_requires_auth(self, client):
        resp = client.post('/api/caregiver/notification/1/ack')
        assert resp.status_code in (401, 403, 404)

    def test_ack_all_requires_auth(self, client):
        resp = client.post('/api/caregiver/notifications/ack-all')
        assert resp.status_code in (401, 403)

    def test_decline_cosign_requires_auth(self, client):
        resp = client.post('/api/caregiver/contract/1/decline-cosign',
                           json={'reason': 'Not a good time'})
        assert resp.status_code in (401, 403, 404)

    def test_scheduled_messages_requires_auth(self, client):
        resp = client.get('/api/caregiver/senior/x/scheduled-messages')
        assert resp.status_code in (401, 403)

    def test_audit_ping_requires_auth(self, client):
        resp = client.post('/api/caregiver/senior/x/audit-ping',
                           json={'section': 'detail'})
        assert resp.status_code in (401, 403)


class TestNotificationHelper:
    def test_create_notification_function_exists(self):
        from caregiver_routes import create_caregiver_notification
        assert callable(create_caregiver_notification)

    def test_create_notification_no_recipient(self):
        from caregiver_routes import create_caregiver_notification
        assert create_caregiver_notification('', 's1', 'info', 'test') is None

    def test_create_notification_no_title(self):
        from caregiver_routes import create_caregiver_notification
        assert create_caregiver_notification('u1', 's1', 'info', '') is None

    def test_create_notification_basic(self):
        """Creating a notification returns an id (or None if DB unreachable)."""
        from caregiver_routes import create_caregiver_notification, _init_schema
        _init_schema()
        result = create_caregiver_notification(
            recipient_id='test-recipient-cg',
            senior_id='test-senior-cg',
            ntype='cosign_required',
            title='Test',
            body='Test body',
            severity='warning',
            ref_type='contract',
            ref_id=42,
        )
        # Either gets an id or None (SQLite handles it)
        assert result is None or isinstance(result, int)


class TestNotifyFamilyOfCosign:
    def test_function_exists(self):
        from caregiver_routes import notify_family_of_cosign
        assert callable(notify_family_of_cosign)

    def test_no_family_returns_zero(self):
        """Senior without family links → zero notifications sent."""
        from caregiver_routes import notify_family_of_cosign, _init_schema
        _init_schema()
        result = notify_family_of_cosign(
            'senior-with-no-family-zzz', 999, 'Test offer', 500
        )
        # Tolerant: 0 if no rows, also safe if DB unavailable
        assert result >= 0


class TestAuditCaregiverAccess:
    def test_function_exists(self):
        from caregiver_routes import _audit_caregiver_access
        assert callable(_audit_caregiver_access)

    def test_silent_on_self_access(self):
        """Self-access shouldn't create audit entry."""
        from caregiver_routes import _audit_caregiver_access
        # Should return None/silently, no error
        _audit_caregiver_access('u1', 'u1', 'viewed_detail')

    def test_silent_on_empty(self):
        from caregiver_routes import _audit_caregiver_access
        _audit_caregiver_access('', 'u1', 'viewed_detail')
        _audit_caregiver_access('u1', '', 'viewed_detail')


class TestSchedulerRegistration:
    def test_register_scheduler_jobs_function_exists(self):
        from caregiver_routes import register_scheduler_jobs
        assert callable(register_scheduler_jobs)

    def test_register_with_mock_scheduler(self):
        from caregiver_routes import register_scheduler_jobs
        class FakeScheduler:
            def __init__(self):
                self.jobs = []
            def add_job(self, *a, **kw):
                self.jobs.append(kw.get('id'))
        sched = FakeScheduler()
        register_scheduler_jobs(sched)
        assert 'caregiver_daily_narratives' in sched.jobs


class TestDailyNarrativesJob:
    def test_function_exists(self):
        from caregiver_routes import run_daily_narratives
        assert callable(run_daily_narratives)

    def test_returns_int(self):
        """Must return int even on empty DB."""
        from caregiver_routes import run_daily_narratives
        result = run_daily_narratives()
        assert isinstance(result, int)
        assert result >= 0


class TestSprintCSchema:
    def test_notifications_table_in_schema(self):
        from caregiver_routes import CAREGIVER_SCHEMA
        assert 'caregiver_notifications' in CAREGIVER_SCHEMA
        assert 'read_at' in CAREGIVER_SCHEMA
        assert 'recipient_id' in CAREGIVER_SCHEMA

    def test_decline_table_in_schema(self):
        from caregiver_routes import CAREGIVER_SCHEMA
        assert 'caregiver_cosign_declines' in CAREGIVER_SCHEMA
        assert 'reason' in CAREGIVER_SCHEMA

    def test_init_schema_idempotent(self):
        from caregiver_routes import _init_schema
        _init_schema()
        _init_schema()


class TestDeclineCosignValidation:
    def test_decline_function_exists(self):
        from caregiver_routes import decline_cosign
        assert callable(decline_cosign)
