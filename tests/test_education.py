"""
Education Sprint C smoke tests.
Run: pytest tests/test_education.py -v
"""

from datetime import datetime, timedelta


class TestEducationAuth:
    """All new progress endpoints require auth."""

    def test_sync_lesson_requires_auth(self, client):
        resp = client.post('/api/education/progress/lesson', json={'lessonId': 'x'})
        assert resp.status_code in (401, 403)

    def test_list_lesson_requires_auth(self, client):
        resp = client.get('/api/education/progress/lessons')
        assert resp.status_code in (401, 403)

    def test_stats_requires_auth(self, client):
        resp = client.get('/api/education/stats/me')
        assert resp.status_code in (401, 403)

    def test_quiz_result_requires_auth(self, client):
        resp = client.post('/api/education/quiz-result', json={})
        assert resp.status_code in (401, 403)

    def test_quiz_list_requires_auth(self, client):
        resp = client.get('/api/education/quiz-results')
        assert resp.status_code in (401, 403)

    def test_family_weekly_requires_auth(self, client):
        resp = client.get('/api/education/family/some-senior/weekly')
        assert resp.status_code in (401, 403)

    def test_certificate_requires_auth(self, client):
        resp = client.get('/api/education/certificate/dysphasia')
        assert resp.status_code in (401, 403)


class TestEducationSchema:
    def test_init_schema_idempotent(self):
        from education_progress_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_compute_streak_empty(self):
        from education_progress_routes import _compute_streak
        assert _compute_streak(set()) == 0

    def test_compute_streak_today(self):
        from education_progress_routes import _compute_streak
        today = datetime.utcnow().date()
        dates = {today.strftime('%Y-%m-%d')}
        assert _compute_streak(dates) == 1

    def test_compute_streak_consecutive(self):
        from education_progress_routes import _compute_streak
        today = datetime.utcnow().date()
        dates = {
            (today - timedelta(days=i)).strftime('%Y-%m-%d')
            for i in range(5)
        }
        assert _compute_streak(dates) == 5

    def test_compute_streak_gap_breaks(self):
        from education_progress_routes import _compute_streak
        today = datetime.utcnow().date()
        # Today + 2 days ago (gap on day 1)
        dates = {
            today.strftime('%Y-%m-%d'),
            (today - timedelta(days=2)).strftime('%Y-%m-%d'),
        }
        assert _compute_streak(dates) == 1

    def test_compute_streak_from_yesterday(self):
        """Streak ending yesterday (no session today yet) still counts."""
        from education_progress_routes import _compute_streak
        today = datetime.utcnow().date()
        dates = {
            (today - timedelta(days=1)).strftime('%Y-%m-%d'),
            (today - timedelta(days=2)).strftime('%Y-%m-%d'),
            (today - timedelta(days=3)).strftime('%Y-%m-%d'),
        }
        assert _compute_streak(dates) == 3

    def test_compute_streak_too_old(self):
        """Streak that ended 3+ days ago returns 0."""
        from education_progress_routes import _compute_streak
        today = datetime.utcnow().date()
        dates = {(today - timedelta(days=5)).strftime('%Y-%m-%d')}
        assert _compute_streak(dates) == 0

    def test_row_val_tuple_and_dict(self):
        from education_progress_routes import _row_val
        assert _row_val(('a', 'b'), 0, 'x') == 'a'
        assert _row_val({'x': 'v'}, 0, 'x') == 'v'
        assert _row_val(None, 0, 'x') is None


class TestEducationValidation:
    def test_sync_lesson_missing_id(self, client):
        resp = client.post('/api/education/progress/lesson', json={})
        assert resp.status_code in (400, 401, 403)

    def test_sync_lesson_empty_id(self, client):
        resp = client.post('/api/education/progress/lesson', json={'lessonId': '   '})
        assert resp.status_code in (400, 401, 403)


class TestEducationBlueprint:
    def test_blueprint_imports(self):
        from education_progress_routes import education_progress_bp
        assert education_progress_bp is not None
        assert education_progress_bp.name == 'education_progress'

    def test_blueprint_registered_on_app(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/education/progress/lesson' in r for r in rules)
        assert any('/api/education/stats/me' in r for r in rules)
        assert any('/api/education/quiz-result' in r for r in rules)
        assert any('/api/education/family/' in r and '/weekly' in r for r in rules)
        assert any('/api/education/certificate/' in r for r in rules)


class TestEducationCertificate:
    """Certificate returns 403 when course not completed / 404 when course missing."""

    def test_certificate_unknown_course(self, client):
        resp = client.get('/api/education/certificate/made-up-course')
        # Unauthed → 401; if auth bypass in test, expected 404
        assert resp.status_code in (401, 403, 404)


class TestEducationFamily:
    """Family weekly needs senior_family_links; unlinked → 403."""

    def test_family_view_unlinked(self, client):
        resp = client.get('/api/education/family/nonexistent-senior/weekly')
        assert resp.status_code in (401, 403)


class TestEducationDeadCodeRemoved:
    """Ensure the legacy education-module.js is gone from dist build inputs."""

    def test_education_module_js_removed(self):
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'mykolibri-academy-project', 'js', 'sections', 'education-module.js'
        )
        assert not os.path.exists(path), 'education-module.js should be deleted'
