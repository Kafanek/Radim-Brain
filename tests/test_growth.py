"""
Growth (Náš vztah) Sprint C smoke + contract tests.
Run: pytest tests/test_growth.py -v
"""


class TestGrowthAuth:
    """All endpoints require authentication."""

    def test_relationship_requires_auth(self, client):
        resp = client.get('/api/growth/relationship')
        assert resp.status_code in (401, 403)

    def test_memories_list_requires_auth(self, client):
        resp = client.get('/api/growth/memories')
        assert resp.status_code in (401, 403)

    def test_memory_add_requires_auth(self, client):
        resp = client.post('/api/growth/memory', json={'text': 'Pamatuj si to'})
        assert resp.status_code in (401, 403)

    def test_memory_delete_requires_auth(self, client):
        resp = client.delete('/api/growth/memory/1')
        assert resp.status_code in (401, 403, 404)

    def test_memory_update_requires_auth(self, client):
        resp = client.put('/api/growth/memory/1', json={'text': 'x'})
        assert resp.status_code in (401, 403, 404)

    def test_mood_trend_requires_auth(self, client):
        resp = client.get('/api/growth/mood-trend')
        assert resp.status_code in (401, 403)

    def test_shared_moments_requires_auth(self, client):
        resp = client.get('/api/growth/shared-moments')
        assert resp.status_code in (401, 403)

    def test_intents_list_requires_auth(self, client):
        resp = client.get('/api/growth/intents')
        assert resp.status_code in (401, 403)

    def test_intent_toggle_requires_auth(self, client):
        resp = client.post('/api/growth/intent/toggle',
                           json={'key': 'morning_medication', 'enabled': False})
        assert resp.status_code in (401, 403)

    def test_narrative_get_requires_auth(self, client):
        resp = client.get('/api/growth/narrative')
        assert resp.status_code in (401, 403)

    def test_narrative_post_requires_auth(self, client):
        resp = client.post('/api/growth/narrative')
        assert resp.status_code in (401, 403)

    def test_caregiver_skillmap_requires_auth(self, client):
        resp = client.get('/api/growth/skillmap/some-senior')
        assert resp.status_code in (401, 403)

    def test_caregiver_report_requires_auth(self, client):
        resp = client.get('/api/growth/report/some-senior')
        assert resp.status_code in (401, 403)


class TestGrowthSchema:
    def test_init_schema_idempotent(self):
        from growth_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_mem_row_to_dict_tuple(self):
        from growth_routes import _mem_row_to_dict
        r = (7, 'Mám ráda buchty', 'food', 'user', 8, '2026-04-21 10:00:00')
        d = _mem_row_to_dict(r)
        assert d['id'] == 7
        assert d['text'] == 'Mám ráda buchty'
        assert d['category'] == 'food'
        assert d['source'] == 'user'
        assert d['importance'] == 8

    def test_mem_row_to_dict_dict(self):
        from growth_routes import _mem_row_to_dict
        r = {
            'id': 42, 'text': 'Vnučka Anička',
            'category': 'family', 'source': 'ai_promoted',
            'importance': 10, 'created_at': '2026-04-21',
        }
        d = _mem_row_to_dict(r)
        assert d['id'] == 42
        assert d['category'] == 'family'
        assert d['importance'] == 10


class TestGrowthBlueprint:
    def test_blueprint_imports(self):
        from growth_routes import growth_bp
        assert growth_bp is not None
        assert growth_bp.name == 'growth'

    def test_all_endpoints_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/growth/relationship') for r in rules)
        assert any(r.endswith('/api/growth/memories') for r in rules)
        assert any(r.endswith('/api/growth/memory') for r in rules)
        assert any('/api/growth/memory/<int:mem_id>' in r for r in rules)
        assert any(r.endswith('/api/growth/mood-trend') for r in rules)
        assert any(r.endswith('/api/growth/shared-moments') for r in rules)
        assert any(r.endswith('/api/growth/intents') for r in rules)
        assert any(r.endswith('/api/growth/intent/toggle') for r in rules)
        assert any(r.endswith('/api/growth/narrative') for r in rules)
        assert any('/api/growth/skillmap/<senior_id>' in r for r in rules)
        assert any('/api/growth/report/<senior_id>' in r for r in rules)


class TestMoodTrendLogic:
    def test_empty_trend_summary(self):
        from growth_routes import _mood_summary_sentence
        assert 'signál' in _mood_summary_sentence([]).lower() or 'málo' in _mood_summary_sentence([]).lower()

    def test_good_mood_summary(self):
        from growth_routes import _mood_summary_sentence
        trend = [{'date': '2026-04-10', 'c': 0.65, 'mood': 'good', 'samples': 3}] * 14
        msg = _mood_summary_sentence(trend)
        assert isinstance(msg, str) and len(msg) > 10

    def test_heavy_mood_summary(self):
        from growth_routes import _mood_summary_sentence
        trend = [{'date': '2026-04-10', 'c': 0.25, 'mood': 'heavy', 'samples': 3}] * 14
        msg = _mood_summary_sentence(trend)
        assert isinstance(msg, str) and len(msg) > 10

    def test_improving_trend(self):
        """Last 7 better than prior 7 should yield improvement message."""
        from growth_routes import _mood_summary_sentence
        prev = [{'date': f'2026-04-{i:02d}', 'c': 0.30, 'mood': 'heavy', 'samples': 2}
                for i in range(1, 8)]
        last = [{'date': f'2026-04-{i:02d}', 'c': 0.60, 'mood': 'good', 'samples': 2}
                for i in range(8, 15)]
        msg = _mood_summary_sentence(prev + last)
        assert 'klid' in msg.lower() or 'lépe' in msg.lower() or 'těší' in msg.lower()


class TestDaysTogether:
    def test_zero_days_for_none(self):
        from growth_routes import _days_together
        assert _days_together(None) == 0

    def test_parses_iso_datetime_string(self):
        from growth_routes import _days_together
        # far in the past
        assert _days_together('2024-01-01 10:00:00') > 100

    def test_parses_t_separated(self):
        from growth_routes import _days_together
        assert _days_together('2024-01-01T10:00:00') > 100

    def test_survives_garbage(self):
        from growth_routes import _days_together
        assert _days_together('not-a-date') == 0


class TestDefaultIntents:
    def test_defaults_include_sos(self):
        from growth_routes import DEFAULT_INTENTS
        keys = {i['key'] for i in DEFAULT_INTENTS}
        assert 'sos_family' in keys
        assert 'morning_medication' in keys

    def test_sos_cannot_be_disabled(self):
        from growth_routes import DEFAULT_INTENTS
        sos = next(i for i in DEFAULT_INTENTS if i['key'] == 'sos_family')
        assert sos['can_disable'] is False

    def test_other_intents_can_be_disabled(self):
        from growth_routes import DEFAULT_INTENTS
        non_sos = [i for i in DEFAULT_INTENTS if i['key'] != 'sos_family']
        assert all(i['can_disable'] is True for i in non_sos)


class TestRateLimiter:
    def setup_method(self):
        from growth_routes import _rate_win
        _rate_win.clear()

    def test_add_within_limit(self):
        from growth_routes import _rate_ok, ADD_RATE
        user = 'rate-u-1'
        for _ in range(ADD_RATE):
            assert _rate_ok(user, 'mem_add', ADD_RATE) is True

    def test_add_over_limit(self):
        from growth_routes import _rate_ok, ADD_RATE
        user = 'rate-u-2'
        for _ in range(ADD_RATE):
            _rate_ok(user, 'mem_add', ADD_RATE)
        assert _rate_ok(user, 'mem_add', ADD_RATE) is False

    def test_buckets_isolated(self):
        from growth_routes import _rate_ok, ADD_RATE, DEL_RATE
        u = 'rate-u-3'
        for _ in range(ADD_RATE):
            _rate_ok(u, 'mem_add', ADD_RATE)
        # add exhausted, del should still be free
        assert _rate_ok(u, 'mem_del', DEL_RATE) is True


class TestNarrativeFallback:
    def test_narrative_no_gemini_returns_none(self, monkeypatch):
        from growth_routes import _generate_narrative_via_gemini
        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
        assert _generate_narrative_via_gemini('ctx') is None


class TestProfileFactsExtraction:
    def test_extract_facts_safe_on_missing_profile(self):
        from growth_routes import _extract_profile_facts
        result = _extract_profile_facts('nonexistent-user-zzz')
        assert isinstance(result, list)


class TestValidation:
    def test_add_memory_rejects_short_text(self, client):
        """Server rejects <3 char text OR returns auth error first."""
        resp = client.post('/api/growth/memory', json={'text': 'a'})
        assert resp.status_code in (400, 401, 403)

    def test_toggle_intent_rejects_unknown_key(self, client):
        resp = client.post('/api/growth/intent/toggle',
                           json={'key': 'does_not_exist', 'enabled': False})
        # Either auth fails first (401) or validation (400)
        assert resp.status_code in (400, 401, 403)

    def test_mood_trend_days_clamped(self, client):
        """days=5 (below min 7) and days=500 (above max 90) — endpoint survives."""
        resp = client.get('/api/growth/mood-trend?days=5')
        assert resp.status_code in (200, 401, 403)
        resp = client.get('/api/growth/mood-trend?days=500')
        assert resp.status_code in (200, 401, 403)


class TestFamilyGuard:
    def test_unrelated_caregiver_denied(self):
        from growth_routes import _is_family_of, _init_schema
        _init_schema()
        assert _is_family_of('senior-xyz', 'stranger-abc') is False

    def test_self_counts_as_family(self):
        from growth_routes import _is_family_of
        assert _is_family_of('u-1', 'u-1') is True
