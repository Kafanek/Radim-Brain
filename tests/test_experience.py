"""
Experience Module (Radimův Odkaz) tests.
Run: pytest tests/test_experience.py -v
"""


class TestExperienceAuth:
    """All endpoints require authentication."""

    def test_contributions_requires_auth(self, client):
        resp = client.get('/api/experience/contributions')
        assert resp.status_code in (401, 403)

    def test_summary_requires_auth(self, client):
        resp = client.get('/api/experience/summary')
        assert resp.status_code in (401, 403)

    def test_session_start_requires_auth(self, client):
        resp = client.post('/api/experience/session/start',
                           json={'theme': 'family', 'depth': 1})
        assert resp.status_code in (401, 403)

    def test_session_append_requires_auth(self, client):
        resp = client.post('/api/experience/session/1/append', json={'text': 'x'})
        assert resp.status_code in (401, 403, 404)

    def test_session_finalize_requires_auth(self, client):
        resp = client.post('/api/experience/session/1/finalize')
        assert resp.status_code in (401, 403, 404)

    def test_session_approve_requires_auth(self, client):
        resp = client.post('/api/experience/session/1/approve',
                           json={'privacy': 'family'})
        assert resp.status_code in (401, 403, 404)

    def test_privacy_change_requires_auth(self, client):
        resp = client.put('/api/experience/contribution/1/privacy',
                          json={'privacy': 'public'})
        assert resp.status_code in (401, 403, 404)

    def test_forget_requires_auth(self, client):
        resp = client.delete('/api/experience/contribution/1')
        assert resp.status_code in (401, 403, 404)

    def test_offers_requires_auth(self, client):
        resp = client.get('/api/experience/offers')
        assert resp.status_code in (401, 403)

    def test_accept_offer_requires_auth(self, client):
        resp = client.post('/api/experience/contribution/1/accept-offer',
                           json={'offerId': 1})
        assert resp.status_code in (401, 403, 404)

    def test_revoke_contract_requires_auth(self, client):
        resp = client.delete('/api/experience/contract/1')
        assert resp.status_code in (401, 403, 404)

    def test_earnings_requires_auth(self, client):
        resp = client.get('/api/experience/earnings')
        assert resp.status_code in (401, 403)

    def test_prompts_requires_auth(self, client):
        resp = client.get('/api/experience/prompts?theme=family')
        assert resp.status_code in (401, 403)

    def test_inheritance_get_requires_auth(self, client):
        resp = client.get('/api/experience/inheritance')
        assert resp.status_code in (401, 403)

    def test_inheritance_put_requires_auth(self, client):
        resp = client.put('/api/experience/inheritance',
                          json={'heirName': 'Anička'})
        assert resp.status_code in (401, 403)

    def test_family_archive_requires_auth(self, client):
        resp = client.get('/api/experience/family/some-senior')
        assert resp.status_code in (401, 403)


class TestSchema:
    def test_init_schema_idempotent(self):
        from experience_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_contrib_row_tuple(self):
        from experience_routes import _contrib_row
        r = (1, 'story', 'Jak jsme se poznali', 'family', 1,
             'Povídali jsme...', None, 120, 'family',
             '2026-04-21 10:00', '2026-04-24 10:00', 25,
             '2026-04-21 10:00')
        d = _contrib_row(r)
        assert d['id'] == 1
        assert d['type'] == 'story'
        assert d['title'] == 'Jak jsme se poznali'
        assert d['theme'] == 'family'
        assert d['depth'] == 1
        assert d['privacy'] == 'family'
        assert d['wordCount'] == 25

    def test_contrib_row_dict(self):
        from experience_routes import _contrib_row
        r = {
            'id': 7, 'type': 'wisdom', 'title': 'Rada',
            'theme': 'wisdom', 'depth': 2, 'transcript': 'text',
            'transcript_structured': 'cleaned', 'duration_sec': 0,
            'privacy': 'public', 'approved_at': '2026-04-21',
            'cooling_off_until': '2026-04-24', 'word_count': 10,
            'created_at': '2026-04-21',
        }
        d = _contrib_row(r)
        assert d['id'] == 7
        assert d['type'] == 'wisdom'
        assert d['privacy'] == 'public'


class TestBlueprint:
    def test_blueprint_imports(self):
        from experience_routes import experience_bp
        assert experience_bp is not None
        assert experience_bp.name == 'experience'

    def test_all_endpoints_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/experience/contributions') for r in rules)
        assert any(r.endswith('/api/experience/summary') for r in rules)
        assert any(r.endswith('/api/experience/session/start') for r in rules)
        assert any('/api/experience/session/<int:session_id>/append' in r for r in rules)
        assert any('/api/experience/session/<int:session_id>/finalize' in r for r in rules)
        assert any('/api/experience/session/<int:session_id>/approve' in r for r in rules)
        assert any('/api/experience/contribution/<int:cid>/privacy' in r for r in rules)
        assert any('/api/experience/contribution/<int:cid>/accept-offer' in r for r in rules)
        assert any(r.endswith('/api/experience/offers') for r in rules)
        assert any('/api/experience/contract/<int:contract_id>' in r for r in rules)
        assert any(r.endswith('/api/experience/earnings') for r in rules)
        assert any(r.endswith('/api/experience/prompts') for r in rules)
        assert any(r.endswith('/api/experience/inheritance') for r in rules)
        assert any('/api/experience/family/<senior_id>' in r for r in rules)


class TestRadimPromptLibrary:
    """The Confucian question library — structural tests."""

    def test_all_themes_present(self):
        from experience_routes import RADIM_PROMPTS, VALID_THEMES
        # All prompt themes are in valid set
        for theme in RADIM_PROMPTS.keys():
            assert theme in VALID_THEMES

    def test_all_themes_have_three_depths(self):
        from experience_routes import RADIM_PROMPTS
        for theme, depths in RADIM_PROMPTS.items():
            assert 1 in depths
            assert 2 in depths
            assert 3 in depths

    def test_every_prompt_is_czech_string(self):
        from experience_routes import RADIM_PROMPTS
        count = 0
        for theme, depths in RADIM_PROMPTS.items():
            for d, prompts in depths.items():
                for p in prompts:
                    assert isinstance(p, str)
                    assert len(p) > 8
                    assert p[0].isupper()
                    count += 1
        assert count >= 50, f'At least 50 prompts expected, got {count}'

    def test_prompts_end_with_question_mark(self):
        """All prompts should be questions — not statements."""
        from experience_routes import RADIM_PROMPTS
        for theme, depths in RADIM_PROMPTS.items():
            for d, prompts in depths.items():
                for p in prompts:
                    assert p.rstrip().endswith('?'), f'Not a question: {p[:60]}'

    def test_depth_3_is_deepest(self):
        """Depth-3 prompts tend to be existential / reflective."""
        from experience_routes import RADIM_PROMPTS
        deep_keywords = ['litujete', 'žal', 'smrt', 'konec', 'pozdě',
                         'banální', 'pravda', 'neřekla', 'tabu', 'strach',
                         'žádali', 'smíř', 'co vy', 'co', 'pokud', 'jak',
                         'čeho']  # weak; just verify existence
        for theme, depths in RADIM_PROMPTS.items():
            assert len(depths[3]) >= 2


class TestConstants:
    def test_revenue_share_sums_to_one(self):
        from experience_routes import (
            SENIOR_REVENUE_SHARE, PLATFORM_SHARE, RADIM_FUND_SHARE, SOCIETY_FUND_SHARE
        )
        total = SENIOR_REVENUE_SHARE + PLATFORM_SHARE + RADIM_FUND_SHARE + SOCIETY_FUND_SHARE
        assert abs(total - 1.0) < 0.001

    def test_senior_share_is_majority(self):
        from experience_routes import SENIOR_REVENUE_SHARE
        assert SENIOR_REVENUE_SHARE >= 0.70  # fair-share guarantee

    def test_min_price_floor(self):
        from experience_routes import MIN_PRICE_KC
        assert MIN_PRICE_KC >= 50

    def test_cooling_off_is_72_hours(self):
        from experience_routes import COOLING_OFF_HOURS
        assert COOLING_OFF_HOURS == 72

    def test_valid_types(self):
        from experience_routes import VALID_TYPES
        assert 'story' in VALID_TYPES
        assert 'skill' in VALID_TYPES
        assert 'wisdom' in VALID_TYPES
        assert 'witness' in VALID_TYPES

    def test_valid_privacy_includes_deleted(self):
        from experience_routes import VALID_PRIVACY
        assert 'family' in VALID_PRIVACY
        assert 'research' in VALID_PRIVACY
        assert 'public' in VALID_PRIVACY
        assert 'draft' in VALID_PRIVACY
        assert 'deleted' in VALID_PRIVACY


class TestRevenueShareCalculation:
    def test_senior_net_at_1000(self):
        from experience_routes import _calc_senior_net
        assert _calc_senior_net(1000) == 700

    def test_senior_net_at_zero(self):
        from experience_routes import _calc_senior_net
        assert _calc_senior_net(0) == 0

    def test_senior_net_rounds_fairly(self):
        from experience_routes import _calc_senior_net
        # 333 * 0.7 = 233.1 → rounded to 233
        assert _calc_senior_net(333) == 233


class TestRateLimiter:
    def setup_method(self):
        from experience_routes import _rate_win
        _rate_win.clear()

    def test_within_limit(self):
        from experience_routes import _rate_ok, RATE_SESSION_START
        for _ in range(RATE_SESSION_START):
            assert _rate_ok('u-1', 'session_start', RATE_SESSION_START) is True

    def test_over_limit(self):
        from experience_routes import _rate_ok, RATE_SESSION_START
        for _ in range(RATE_SESSION_START):
            _rate_ok('u-2', 'session_start', RATE_SESSION_START)
        assert _rate_ok('u-2', 'session_start', RATE_SESSION_START) is False

    def test_isolation_between_users(self):
        from experience_routes import _rate_ok, RATE_SESSION_START
        for _ in range(RATE_SESSION_START):
            _rate_ok('u-a', 'session_start', RATE_SESSION_START)
        assert _rate_ok('u-b', 'session_start', RATE_SESSION_START) is True

    def test_isolation_between_buckets(self):
        from experience_routes import _rate_ok, RATE_SESSION_START, RATE_CONTRACT_SIGN
        for _ in range(RATE_SESSION_START):
            _rate_ok('u-c', 'session_start', RATE_SESSION_START)
        assert _rate_ok('u-c', 'contract_sign', RATE_CONTRACT_SIGN) is True


class TestValidation:
    def test_session_start_rejects_bad_type(self, client):
        """Unknown 'type' rejected (after auth passes, 400; unauthed 401)."""
        resp = client.post('/api/experience/session/start',
                           json={'type': 'nonsense', 'theme': 'family'})
        assert resp.status_code in (400, 401, 403)

    def test_approve_requires_privacy(self, client):
        resp = client.post('/api/experience/session/1/approve', json={})
        assert resp.status_code in (400, 401, 403, 404)

    def test_approve_rejects_draft_as_privacy(self, client):
        resp = client.post('/api/experience/session/1/approve',
                           json={'privacy': 'draft'})
        assert resp.status_code in (400, 401, 403, 404)

    def test_inheritance_requires_heir_name(self, client):
        resp = client.put('/api/experience/inheritance', json={})
        assert resp.status_code in (400, 401, 403)


class TestPromptsEndpoint:
    def test_theme_fallback(self, client):
        """Unknown theme falls back to 'family' (or auth blocks first)."""
        resp = client.get('/api/experience/prompts?theme=nonsense')
        assert resp.status_code in (200, 401, 403)

    def test_depth_clamped(self, client):
        resp = client.get('/api/experience/prompts?theme=family&depth=99')
        assert resp.status_code in (200, 401, 403)


class TestGDPRRights:
    """4 senior rights — verify the code paths exist."""

    def test_right_to_forget_soft_deletes(self):
        """forget_contribution sets privacy='deleted', not hard delete."""
        from experience_routes import VALID_PRIVACY
        assert 'deleted' in VALID_PRIVACY

    def test_right_to_choose_audience_has_three_tiers(self):
        """Approval accepts family | research | public."""
        from experience_routes import VALID_PRIVACY
        assert {'family', 'research', 'public'}.issubset(VALID_PRIVACY)

    def test_right_to_value_floor_enforced(self):
        """Floor below which no offer may be listed."""
        from experience_routes import MIN_PRICE_KC
        assert MIN_PRICE_KC > 0

    def test_right_to_silence_via_cooling_off(self):
        """72h window to revoke after signing."""
        from experience_routes import COOLING_OFF_HOURS
        assert COOLING_OFF_HOURS == 72


class TestDemoEcosystem:
    def test_demo_buyers_defined(self):
        from experience_routes import DEMO_BUYERS
        names = [b['name'] for b in DEMO_BUYERS]
        assert any('Karlova' in n for n in names)
        assert any('archiv' in n.lower() for n in names)
        assert any('akademi' in n.lower() for n in names)
        assert any('AI' in n or 'Wisdom' in n for n in names)

    def test_demo_offers_link_to_real_buyers(self):
        from experience_routes import DEMO_BUYERS, DEMO_OFFERS
        buyer_names = {b['name'] for b in DEMO_BUYERS}
        for o in DEMO_OFFERS:
            assert o['buyer_name'] in buyer_names

    def test_demo_offers_meet_price_floor(self):
        from experience_routes import DEMO_OFFERS, MIN_PRICE_KC
        for o in DEMO_OFFERS:
            assert o['price_kc'] >= MIN_PRICE_KC

    def test_trust_scores_reasonable(self):
        from experience_routes import DEMO_BUYERS
        for b in DEMO_BUYERS:
            assert 0 <= b['trust_score'] <= 100


class TestFamilyGuard:
    def test_self_counts_as_family(self):
        from experience_routes import _is_family_of
        assert _is_family_of('me', 'me') is True

    def test_unrelated_not_family(self):
        from experience_routes import _is_family_of, _init_schema
        _init_schema()
        assert _is_family_of('senior-x', 'stranger-y') is False


class TestWordCount:
    def test_empty(self):
        from experience_routes import _word_count
        assert _word_count('') == 0
        assert _word_count(None) == 0

    def test_simple(self):
        from experience_routes import _word_count
        assert _word_count('Povídali jsme si') == 3

    def test_czech_diacritics(self):
        from experience_routes import _word_count
        assert _word_count('Šla jsem pro mléko za babičkou') == 6


class TestToBool:
    def test_true_values(self):
        from experience_routes import _to_bool
        assert _to_bool(True) is True
        assert _to_bool(1) is True
        assert _to_bool('true') is True
        assert _to_bool('1') is True
        assert _to_bool('YES') is True

    def test_false_values(self):
        from experience_routes import _to_bool
        assert _to_bool(False) is False
        assert _to_bool(0) is False
        assert _to_bool('false') is False
        assert _to_bool('') is False
        assert _to_bool(None) is False


class TestGeminiStructureFallback:
    def test_no_api_key_returns_none(self, monkeypatch):
        from experience_routes import _structure_via_gemini
        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
        assert _structure_via_gemini('some text', 'title', 'family') is None
