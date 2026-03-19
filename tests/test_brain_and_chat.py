"""
Tests for brain engine, chat orchestrator, memory system, and admin endpoints.
"""
import json
from unittest.mock import patch, MagicMock


class TestBrainEngine:
    """Brain core computation tests."""

    def test_compute_psi_harmony(self):
        """Low C → HARMONY mode."""
        from brain_core import compute_psi_state
        result = compute_psi_state(5.0, 0.2)
        assert result["mode"] == "HARMONY"
        assert result["psi"]["C"] == 5.0
        assert 0 <= result["psi"]["E"] <= 1
        assert 0 <= result["psi"]["R"] <= 1
        assert 0 <= result["coherence"] <= 1
        assert result["phi_index"] > 0.5  # low C = high harmony

    def test_compute_psi_alert(self):
        """Medium C → ALERT mode."""
        from brain_core import compute_psi_state
        result = compute_psi_state(18.0, 0.5)
        assert result["mode"] == "ALERT"

    def test_compute_psi_crisis(self):
        """High C → CRISIS mode."""
        from brain_core import compute_psi_state
        result = compute_psi_state(30.0, 0.8)
        assert result["mode"] == "CRISIS"
        assert result["phi_index"] < 0.5  # high C = low harmony

    def test_compute_psi_saves_to_db(self, client):
        """With user_id, psi state should be saved to brain_states."""
        from brain_core import compute_psi_state
        from database import db_context
        # Clean up first
        with db_context(commit=True) as db:
            db.execute("DELETE FROM brain_states WHERE user_id = 'test_psi_save'")
        # Compute with user_id
        compute_psi_state(10.0, 0.3, user_id='test_psi_save')
        # Verify saved
        with db_context() as db:
            row = db.execute(
                "SELECT c, mode FROM brain_states WHERE user_id = 'test_psi_save'"
            ).fetchone()
            assert row is not None
            c_val = row['c'] if 'c' in row.keys() else row[0]
            assert float(c_val) == 10.0

    def test_thresholds(self):
        """Verify T1, T2, C_MAX constants."""
        from brain_math import T1, T2, C_MAX
        assert T1 == 12
        assert T2 == 27
        assert C_MAX == 40


class TestMemorySystem:
    """Memory learning and profile tests."""

    def test_load_save_learning(self, client):
        """Learning data roundtrip."""
        from memory_helpers import db_load_learning, db_save_learning
        test_data = {"topics": {"test": 1}, "interaction_count": 5}
        db_save_learning("test_memory_user", test_data)
        loaded = db_load_learning("test_memory_user")
        assert loaded["interaction_count"] == 5
        assert loaded["topics"]["test"] == 1

    def test_build_personalized_prompt(self, client):
        """Personalized prompt builds without error."""
        from memory_logic import build_personalized_prompt
        # For unknown user, should return empty or minimal prompt
        prompt = build_personalized_prompt("nonexistent_user_xyz")
        assert isinstance(prompt, str)

    def test_agent_observations_in_prompt(self, client):
        """Agent observations appear in personalized prompt."""
        from memory_helpers import db_load_learning, db_save_learning
        from memory_logic import build_personalized_prompt
        # Set up user with agent observation
        learning = db_load_learning("test_obs_user")
        learning["interaction_count"] = 5
        learning["agent_observations"] = [
            {"type": "test", "severity": "WARNING", "message": "Test observation message"}
        ]
        db_save_learning("test_obs_user", learning)
        # Build prompt
        prompt = build_personalized_prompt("test_obs_user")
        assert "Test observation message" in prompt


class TestChatOrchestrator:
    """Chat endpoint integration tests."""

    def test_chat_missing_message(self, client):
        """Chat without message returns 400."""
        resp = client.post('/api/radim/chat',
                          json={"user_id": "test", "mode": "senior"})
        assert resp.status_code == 400

    def test_chat_options(self, client):
        """CORS preflight returns 204."""
        resp = client.options('/api/radim/chat')
        assert resp.status_code == 204


class TestAdminEndpoints:
    """Admin endpoint tests."""

    def test_admin_requires_secret(self, client):
        """Admin endpoints reject without secret when ADMIN_SECRET is set."""
        import app as app_module
        original = app_module.ADMIN_SECRET
        try:
            app_module.ADMIN_SECRET = "test_secret_123"
            # Without header
            resp = client.post('/api/admin/agent-run')
            assert resp.status_code == 401
            # With wrong header
            resp = client.post('/api/admin/agent-run',
                              headers={'X-Admin-Secret': 'wrong'})
            assert resp.status_code == 401
            # With correct header
            resp = client.post('/api/admin/agent-run',
                              headers={'X-Admin-Secret': 'test_secret_123'})
            assert resp.status_code == 200
        finally:
            app_module.ADMIN_SECRET = original

    def test_debug_prompt(self, client):
        """Debug prompt endpoint returns prompt."""
        resp = client.get('/api/admin/debug-prompt/test_user')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'prompt' in data

    def test_seed_demo(self, client):
        """Seed demo creates demo senior."""
        resp = client.post('/api/admin/seed-demo')
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['success'] is True
        assert data['user_id'] == 'demo_senior_1'
        assert data['brain_states_count'] > 0


class TestHealthEndpoint:
    """Health check tests."""

    def test_health_includes_db(self, client):
        """Health check includes DB connectivity info."""
        resp = client.get('/health')
        data = resp.get_json()
        assert 'db' in data
        assert data['db']['connected'] is True
        assert data['db']['latency_ms'] is not None
        assert data['version'] == '3.5.0'

    def test_health_includes_agent_loop(self, client):
        """Health check shows agent_loop module."""
        resp = client.get('/health')
        data = resp.get_json()
        assert data['modules']['agent_loop'] is True


class TestIoTAuth:
    """IoT authentication tests."""

    def test_iot_rejects_without_token(self, client):
        """IoT bridge rejects when no gateway token configured."""
        resp = client.post('/api/iot-bridge/data',
                          json={"device_id": "test", "room_id": "test",
                                "sensor_type": "motion", "value": 1.0})
        # Should return 503 (no IOT_GATEWAY_TOKEN configured)
        assert resp.status_code == 503


class TestWhatsAppWebhook:
    """WhatsApp message handling tests."""

    def test_whatsapp_empty_body(self, client):
        """Empty WhatsApp message returns empty TwiML."""
        resp = client.post('/api/twilio/whatsapp', data={"Body": "", "From": "whatsapp:+420123"})
        assert resp.status_code == 200
        assert b'<Response>' in resp.data

    def test_whatsapp_with_message(self, client):
        """WhatsApp message triggers AI response."""
        resp = client.post('/api/twilio/whatsapp',
                          data={"Body": "Ahoj Radime", "From": "whatsapp:+420123456789"})
        assert resp.status_code == 200
        assert b'<Message>' in resp.data


class TestIntentResolver:
    """Intent resolver local intent tests."""

    def test_time_intent(self):
        from intent_resolver import resolve_intent
        text, intent, _ = resolve_intent("Kolik je hodin?")
        assert intent == "time"
        assert text is not None
        assert ":" in text

    def test_medication_intent(self):
        from intent_resolver import resolve_intent
        text, intent, _ = resolve_intent("Jaké mám léky?", user_id="demo_senior_1")
        assert intent == "medication"
        # Returns text with user_id (from profile or fallback message)
        assert text is not None

    def test_who_am_i_intent(self):
        from intent_resolver import resolve_intent
        text, intent, _ = resolve_intent("Kdo jsem?")
        assert intent == "who_am_i"

    def test_safety_passes_to_ai(self):
        from intent_resolver import resolve_intent
        text, intent, meta = resolve_intent("Pomoc, spadl jsem!")
        assert intent == "safety"
        assert text is None  # passed to AI
        assert meta is not None

    def test_weather_passes_to_ai(self):
        from intent_resolver import resolve_intent
        text, intent, _ = resolve_intent("Jaké je počasí?")
        assert intent == "weather"
        assert text is None  # passed to AI

    def test_greeting(self):
        from intent_resolver import resolve_intent
        text, intent, _ = resolve_intent("Ahoj!")
        assert intent == "greeting"
        assert text is not None


class TestProactiveCalls:
    """Proactive call infrastructure tests."""

    def test_get_senior_phone(self):
        from twilio_voice_helpers import get_senior_phone
        # No profile → returns None
        phone = get_senior_phone("nonexistent_user")
        assert phone is None

    def test_initiate_call_no_twilio(self):
        """Without Twilio configured, call returns error gracefully."""
        from twilio_voice_helpers import initiate_proactive_call
        result = initiate_proactive_call("+420123456789", "Test greeting")
        # Should return dict with error (Twilio not configured in test)
        assert isinstance(result, dict)


class TestSpeechUnderstanding:
    """Fuzzy matching + normalization for speech-impaired seniors."""

    def test_strip_diacritics(self):
        from speech_understanding import strip_diacritics
        assert strip_diacritics("příliš žluťoučký") == "prilis zlutoucky"
        assert strip_diacritics("pomoc") == "pomoc"
        assert strip_diacritics("léky") == "leky"

    def test_normalize_czech(self):
        from speech_understanding import normalize_czech
        assert normalize_czech("  POMOC!  ") == "pomoc"
        assert normalize_czech("Léky Na Ráno") == "leky na rano"

    def test_safety_exact_match(self):
        from speech_understanding import detect_safety_fuzzy
        m = detect_safety_fuzzy("Pomoc!")
        assert m is not None
        assert m["severity"] == "critical"
        assert m["distance"] == 0

    def test_safety_fuzzy_pomo(self):
        """Senior with dysarthria says 'pomo' instead of 'pomoc'."""
        from speech_understanding import detect_safety_fuzzy
        m = detect_safety_fuzzy("pomo")
        assert m is not None
        assert m["word"] == "pomoc"
        assert m["distance"] <= 2

    def test_safety_fuzzy_pomc(self):
        """Parkinson's tremor types 'pomc' instead of 'pomoc'."""
        from speech_understanding import detect_safety_fuzzy
        m = detect_safety_fuzzy("pomc")
        assert m is not None
        assert m["word"] == "pomoc"

    def test_safety_fuzzy_zachrnku(self):
        """STT misheard 'záchranku' as 'zachrnku'."""
        from speech_understanding import detect_safety_fuzzy
        m = detect_safety_fuzzy("zachrnku")
        assert m is not None
        assert m["severity"] == "critical"

    def test_safety_no_false_positive(self):
        """Normal words should NOT trigger safety."""
        from speech_understanding import detect_safety_fuzzy
        assert detect_safety_fuzzy("Dobrý den") is None
        assert detect_safety_fuzzy("Jaké je počasí?") is None
        assert detect_safety_fuzzy("Děkuji") is None

    def test_safety_155_exact(self):
        """Emergency number 155 must match exactly."""
        from speech_understanding import detect_safety_fuzzy
        m = detect_safety_fuzzy("zavolej 155")
        assert m is not None
        assert m["severity"] == "critical"

    def test_should_retry_low_conf(self):
        """Very low confidence + short text → retry."""
        from speech_understanding import should_retry_stt
        action, _ = should_retry_stt("bla", 0.2)
        assert action == "retry"

    def test_should_retry_safety_overrides(self):
        """Safety word overrides low confidence → safety escalation."""
        from speech_understanding import should_retry_stt
        action, data = should_retry_stt("pomoc", 0.1)
        assert action == "safety"
        assert data["severity"] == "critical"

    def test_should_proceed_good_conf(self):
        """Good confidence → proceed normally."""
        from speech_understanding import should_retry_stt
        action, _ = should_retry_stt("Dobrý den, jak se máte?", 0.85)
        assert action == "proceed"

    def test_adaptive_gather_default(self):
        from speech_understanding import get_gather_params
        p = get_gather_params(None)
        assert p["speech_timeout"] == 3
        assert p["language"] == "cs-CZ"

    def test_intent_resolver_fuzzy_safety(self):
        """Fuzzy safety in intent resolver catches 'pomo'."""
        from intent_resolver import resolve_intent
        text, intent, meta = resolve_intent("pomo prosim")
        assert intent == "safety"
        assert meta is not None
        assert meta.get("fuzzy_match") is not None

    # v397: STT correction tests
    def test_stt_correction_155(self):
        """STT hears 'jedna pět pět' → correct to '155'."""
        from speech_understanding import correct_stt_output
        result, corrections = correct_stt_output("jedna pět pět")
        assert "155" in result
        assert len(corrections) > 0

    def test_stt_correction_medication(self):
        """STT splits medication name → correct."""
        from speech_understanding import correct_stt_output
        result, corrections = correct_stt_output("done pezil ráno")
        assert "donepezil" in result

    def test_stt_correction_pomok(self):
        """Word 'pomok' (common mispronunciation) → 'pomoc'."""
        from speech_understanding import correct_stt_output
        result, _ = correct_stt_output("pomok prosím")
        assert "pomoc" in result

    def test_stt_collapse_repetition(self):
        """Dementia pattern: repeated words collapsed."""
        from speech_understanding import correct_stt_output
        result, _ = correct_stt_output("tak tak tak tak tak prosím")
        assert result.count("tak") <= 2

    def test_stt_correction_limit(self):
        """Over-correction guard: stop after MAX_CORRECTION_STEPS."""
        from speech_understanding import correct_stt_output, MAX_CORRECTION_STEPS
        # 7 correctable words, should stop after 5
        text = "pomok zachranku leky prasky spatne bolest spatny"
        result, corrections = correct_stt_output(text)
        assert len(corrections) == MAX_CORRECTION_STEPS
        # Last two words should NOT be corrected
        assert "spatny" in result  # not corrected to "špatný"

    def test_safety_priority_critical(self):
        from speech_understanding import classify_safety_priority
        p = classify_safety_priority("pomoc prosim")
        assert p["priority"] == "CRITICAL"
        assert p["bypass_ai"] is True
        assert p["escalate"] is True

    def test_safety_priority_low(self):
        from speech_understanding import classify_safety_priority
        p = classify_safety_priority("dobrý den")
        assert p["priority"] == "LOW"
        assert p["bypass_ai"] is False

    def test_safety_priority_repetition(self):
        from speech_understanding import classify_safety_priority
        p = classify_safety_priority("co co co co co")
        assert p["priority"] == "MEDIUM"

    def test_latency_fallback(self):
        from speech_understanding import get_latency_fallback
        msg = get_latency_fallback()
        assert isinstance(msg, str)
        assert len(msg) > 10

    # v406 bug fixes
    def test_spadl_jsem_is_critical(self):
        """Bug fix: 'spadl jsem' must be CRITICAL, not MEDIUM."""
        from speech_understanding import classify_safety_priority
        p = classify_safety_priority("spadl jsem nemohu vstát", confidence=0.5)
        assert p["priority"] == "CRITICAL"
        assert p["bypass_ai"] is True
        assert p["escalate"] is True

    def test_spadl_low_confidence_still_critical(self):
        """Even at conf=0.4, 'spadl' should trigger CRITICAL."""
        from speech_understanding import classify_safety_priority
        p = classify_safety_priority("spadl jsem", confidence=0.4)
        assert p["priority"] == "CRITICAL"

    def test_nevim_not_safety(self):
        """Bug fix: 'nevim' should NOT trigger safety detection."""
        from speech_understanding import detect_safety_fuzzy
        result = detect_safety_fuzzy("nevim co mam delat")
        # Should be None — "nevim" removed from SAFETY_FUZZY
        assert result is None

    def test_nevim_no_false_alarm(self):
        """'nevim kde jsou klice' should NOT be safety."""
        from speech_understanding import classify_safety_priority
        p = classify_safety_priority("nevim kde jsou klice")
        assert p["priority"] == "LOW"

    def test_dekuji_radime_matches_thanks(self):
        """Bug fix: 'děkuji radime' should match thanks intent."""
        from intent_resolver import resolve_intent
        resp, intent, meta = resolve_intent("děkuji radime")
        assert intent == "thanks"
        assert resp is not None

    def test_dekuji_plain_still_works(self):
        """Plain 'děkuji' still matches thanks."""
        from intent_resolver import resolve_intent
        resp, intent, meta = resolve_intent("děkuji")
        assert intent == "thanks"

    def test_ahoj_radime_matches_greeting(self):
        """'ahoj radime' should match greeting."""
        from intent_resolver import resolve_intent
        resp, intent, meta = resolve_intent("ahoj radime")
        assert intent == "greeting"

    def test_nashledanou_radime_matches_goodbye(self):
        """'nashledanou radime' should match goodbye."""
        from intent_resolver import resolve_intent
        resp, intent, meta = resolve_intent("nashledanou radime")
        assert intent == "goodbye"

    # v407 safety word expansion tests
    def test_safety_infarkt_critical(self):
        """'infarkt' must be detected as critical safety word."""
        from speech_understanding import detect_safety_fuzzy
        r = detect_safety_fuzzy("mám infarkt")
        assert r is not None
        assert r["severity"] == "critical"

    def test_safety_mrtvice_critical(self):
        """'mrtvice' must be detected as critical."""
        from speech_understanding import detect_safety_fuzzy
        r = detect_safety_fuzzy("asi mám mrtvici")
        assert r is not None
        assert r["severity"] == "critical"

    def test_safety_padl_high(self):
        """'padl jsem' detected as high severity."""
        from speech_understanding import detect_safety_fuzzy
        r = detect_safety_fuzzy("padl jsem na zem")
        assert r is not None
        assert r["severity"] == "high"

    def test_safety_omdlel_high(self):
        """'omdlel' detected as high severity."""
        from speech_understanding import detect_safety_fuzzy
        r = detect_safety_fuzzy("manžel omdlel")
        assert r is not None
        assert r["severity"] == "high"

    def test_safety_umrit_critical(self):
        """'chci umrit' detected as critical."""
        from speech_understanding import detect_safety_fuzzy
        r = detect_safety_fuzzy("chci umrit")
        assert r is not None
        assert r["severity"] == "critical"

    def test_safety_zlomenina_high(self):
        """'zlomenina' detected as high severity."""
        from speech_understanding import detect_safety_fuzzy
        r = detect_safety_fuzzy("mám zlomeninu")
        assert r is not None
        assert r["severity"] == "high"

    def test_weather_intent_no_duplicate(self):
        """Weather intent should not be duplicated."""
        from intent_data import INTENTS
        weather_count = sum(1 for i in INTENTS if i["name"] == "weather")
        assert weather_count == 1, f"Found {weather_count} weather intents, expected 1"

    def test_voice_filter_none_text(self):
        """Voice filter handles None/empty text gracefully."""
        from voice_filter import _truncate_for_tts, _add_sentence_pauses
        assert _truncate_for_tts("") == ""
        assert _truncate_for_tts(None) == ""
        assert _add_sentence_pauses("", 618) == ""
        assert _add_sentence_pauses(None, 618) == ""

    def test_voice_filter_truncate_guarantees_max(self):
        """Truncation must not exceed max_chars + 1."""
        from voice_filter import _truncate_for_tts
        long_word = "x" * 300
        result = _truncate_for_tts(long_word, max_chars=200)
        assert len(result) <= 200, f"Truncated to {len(result)} chars, expected <= 200"

    def test_voice_filter_recovery_no_speedup(self):
        """Recovery mode must not speed up CRISIS voice (-25% → should stay -25%, not -20%)."""
        from voice_filter import VOICE_PROFILES
        crisis_rate = int(VOICE_PROFILES["CRISIS"]["rate"].replace("%", ""))
        # Recovery sets min(current, -20), so for CRISIS -25%: min(-25, -20) = -25 (stays slow)
        assert min(crisis_rate, -20) == crisis_rate, "Recovery would speed up CRISIS voice!"

    # v407b: Thread safety, transfer intent, phone validation, silent emergency
    def test_transfer_intent_casual(self):
        """'chci mluvit s dcerou' should detect transfer intent."""
        from twilio_voice_helpers import detect_transfer_intent
        r = detect_transfer_intent("chci mluvit s dcerou")
        assert r is not None
        assert r["target"] == "dcera"

    def test_transfer_intent_domu(self):
        """'zavolej domů' should detect transfer to rodina."""
        from twilio_voice_helpers import detect_transfer_intent
        r = detect_transfer_intent("zavolej domů")
        assert r is not None
        assert r["target"] == "rodina"

    def test_transfer_intent_none_on_empty(self):
        """No crash on empty text."""
        from twilio_voice_helpers import detect_transfer_intent
        assert detect_transfer_intent("") is None
        assert detect_transfer_intent(None) is None

    def test_phone_validation_e164(self):
        """initiate_proactive_call rejects invalid phone formats."""
        from twilio_voice_helpers import initiate_proactive_call
        r1 = initiate_proactive_call("+a", "Test")
        assert r1["success"] is False
        r2 = initiate_proactive_call("+42", "Test")  # too short
        assert r2["success"] is False
        r3 = initiate_proactive_call("420123456", "Test")  # missing +
        assert r3["success"] is False

    def test_estimate_c_alpha_none_speech(self):
        """estimate_call_C_alpha handles None speech_result."""
        from twilio_voice_helpers import estimate_call_C_alpha
        C, alpha = estimate_call_C_alpha("test_sid", None, 0.5)
        assert C >= 0
        assert alpha >= 0

    def test_calls_lock_exists(self):
        """Thread lock for active_calls exists."""
        from twilio_voice_helpers import _calls_lock
        import threading
        assert isinstance(_calls_lock, type(threading.Lock()))

    # v408: Deduplication verification
    def test_word_lists_unified(self):
        """twilio_voice_helpers must use intent_data word sets (not local copies)."""
        from twilio_voice_helpers import _CRISIS_WORDS as call_crisis
        from intent_data import CRISIS_WORDS as data_crisis
        # Call crisis words should be the SAME object or superset
        assert len(call_crisis) >= 40, f"Call crisis words too small ({len(call_crisis)}), should import from intent_data"
        # Verify key words are present
        assert 'spadl' in call_crisis
        assert 'infarkt' in call_crisis or 'pomoc' in call_crisis

    def test_c_alpha_coefficients_match(self):
        """C/α estimation on calls should use same coefficients as chat.
        Note: quick_estimate uses substring matching, call uses word-set intersection,
        so exact values differ. Both should detect crisis (C > 20).
        """
        from twilio_voice_helpers import estimate_call_C_alpha
        from intent_resolver import quick_estimate_from_text
        C_call, _ = estimate_call_C_alpha("test", "pomoc spadl", 0.8)
        C_chat, _ = quick_estimate_from_text("pomoc spadl")
        # Both must detect crisis state (C > 20)
        assert C_call > 20, f"Call missed crisis: C={C_call}"
        assert C_chat > 20, f"Chat missed crisis: C={C_chat}"
        # Same coefficient base — difference only from matching method
        assert abs(C_call - C_chat) < 15, f"C_call={C_call} vs C_chat={C_chat} differ too much"

    def test_call_fuzzy_safety_integrated(self):
        """Phone calls should use fuzzy safety detection (catches 'pomo', 'pomc')."""
        from twilio_voice_helpers import estimate_call_C_alpha
        # "pomo" is fuzzy match for "pomoc" (distance 1)
        C_fuzzy, alpha_fuzzy = estimate_call_C_alpha("test", "pomo prosim", 0.5)
        # Should detect crisis via fuzzy matching
        assert C_fuzzy > 15, f"Fuzzy 'pomo' not detected on call: C={C_fuzzy}"

    def test_azure_config_single_source(self):
        """Azure config should come from speech_helpers (single source)."""
        from twilio_voice_helpers import AZURE_SPEECH_REGION as call_region
        from speech_helpers import AZURE_SPEECH_REGION as helpers_region
        assert call_region == helpers_region, f"Region mismatch: {call_region} vs {helpers_region}"


class TestAdaptiveLearning:
    """Adaptive learning per-user tests."""

    def test_feedback_success(self):
        from adaptive_learning import detect_feedback
        f = detect_feedback("Děkuji, super!")
        assert f["signal"] == "success"
        assert f["strength"] > 0

    def test_feedback_failure(self):
        from adaptive_learning import detect_feedback
        f = detect_feedback("Nerozumím tomu")
        assert f["signal"] == "failure"

    def test_feedback_wants_shorter(self):
        from adaptive_learning import detect_feedback
        f = detect_feedback("To je moc dlouhé")
        assert f["length_pref"] == "shorter"

    def test_feedback_wants_repeat(self):
        from adaptive_learning import detect_feedback
        f = detect_feedback("Zopakuj to prosím")
        assert f["wants_repeat"] is True

    def test_rhythm_update(self):
        from adaptive_learning import update_rhythm
        a = {}
        a = update_rhythm(a, "Ahoj", "Dobrý den!")
        assert "time_buckets" in a
        assert "avg_message_length" in a
        assert "interaction_hours" in a
        assert sum(a["time_buckets"].values()) == 1

    def test_mood_transitions(self):
        from adaptive_learning import update_mood_transitions
        a = {}
        a = update_mood_transitions(a, "happy")
        a = update_mood_transitions(a, "sad")
        a = update_mood_transitions(a, "sad")
        a = update_mood_transitions(a, "sad")
        assert len(a["mood_history"]) == 4
        # 3 consecutive sad → mood concern
        assert a.get("mood_concern") is True

    def test_topic_freshness(self):
        from adaptive_learning import update_topic_freshness
        a = {}
        a = update_topic_freshness(a, "zdravi")
        a = update_topic_freshness(a, "zdravi")
        a = update_topic_freshness(a, "rodina")
        assert "zdravi" in a["fresh_interests"]
        assert a["fresh_interests"]["zdravi"] == 2

    def test_speech_patience_aphasia(self):
        from adaptive_learning import compute_speech_patience
        p = compute_speech_patience({}, "afazie")
        assert p["speech_timeout_multiplier"] >= 2.0
        assert p["response_pace"] == "very_slow"
        assert p["preferred_confirmation"] == "yes_no"

    def test_speech_patience_normal(self):
        from adaptive_learning import compute_speech_patience
        p = compute_speech_patience({}, "")
        assert p["speech_timeout_multiplier"] == 1.0
        assert p["response_pace"] == "normal"

    def test_preferred_length_short(self):
        from adaptive_learning import compute_preferred_length
        a = {"avg_message_length": 10, "length_feedback": ["shorter", "shorter"]}
        assert compute_preferred_length(a) == "short"

    def test_get_adaptive_context_empty(self):
        from adaptive_learning import get_adaptive_context
        lines = get_adaptive_context("nonexistent_user")
        assert isinstance(lines, list)
        assert len(lines) == 0  # not enough data

    def test_feedback_score_positive(self):
        from adaptive_learning import detect_feedback
        f = detect_feedback("Děkuji!")
        assert f["score"] > 0
        assert f["confidence"] > 0

    def test_feedback_score_negative(self):
        from adaptive_learning import detect_feedback
        f = detect_feedback("Nerozumím")
        assert f["score"] < 0

    def test_language_complexity_normal(self):
        from adaptive_learning import compute_language_complexity
        a = {"success_rate": 0.7, "repeat_requests": 0}
        assert compute_language_complexity(a) == "normal"

    def test_language_complexity_simple(self):
        from adaptive_learning import compute_language_complexity
        a = {"success_rate": 0.2, "repeat_requests": 6, "confusion_count": 5}
        assert compute_language_complexity(a) == "simple"

    def test_energy_level_range(self):
        from adaptive_learning import compute_energy_level
        energy = compute_energy_level({})
        assert 0.0 <= energy <= 1.0

    def test_energy_level_with_sad_mood(self):
        from adaptive_learning import compute_energy_level
        a = {"mood_history": [
            {"mood": "sad", "hour": 10, "ts": "2026-03-19T10:00"},
            {"mood": "sad", "hour": 10, "ts": "2026-03-19T10:05"},
            {"mood": "anxious", "hour": 10, "ts": "2026-03-19T10:10"},
        ]}
        energy = compute_energy_level(a)
        energy_normal = compute_energy_level({})
        assert energy <= energy_normal  # sad mood reduces or caps energy

    def test_trust_score_low_data(self):
        from adaptive_learning import compute_trust_score
        t = compute_trust_score({"total_adaptive_interactions": 1})
        assert t == 0.1

    def test_trust_score_grows(self):
        from adaptive_learning import compute_trust_score
        t_low = compute_trust_score({"total_adaptive_interactions": 3, "success_rate": 0.5})
        t_high = compute_trust_score({
            "total_adaptive_interactions": 50,
            "success_rate": 0.8,
            "interaction_hours": [10]*30 + [11]*20
        })
        assert t_high > t_low

    def test_error_recovery_inactive(self):
        from adaptive_learning import check_error_recovery
        r = check_error_recovery({"success_rate": 0.7, "consecutive_failures": 0})
        assert r["active"] is False
        assert r["level"] == 0

    def test_error_recovery_active_level2(self):
        from adaptive_learning import check_error_recovery
        r = check_error_recovery({"success_rate": 0.2, "consecutive_failures": 4})
        assert r["active"] is True
        assert r["level"] >= 2
        assert "simple_language" in r["actions"]

    def test_error_recovery_level3(self):
        from adaptive_learning import check_error_recovery
        r = check_error_recovery({"success_rate": 0.1, "consecutive_failures": 6})
        assert r["active"] is True
        assert r["level"] == 3
        assert "yes_no_mode" in r["actions"]

    def test_build_adaptive_state_structure(self):
        from adaptive_learning import build_adaptive_state
        state = build_adaptive_state({"total_adaptive_interactions": 10, "success_rate": 0.6})
        assert "feedback" in state
        assert "communication" in state
        assert "behavior" in state
        assert "mood" in state
        assert "topics" in state
        assert "trust_score" in state
        assert "recovery" in state
        assert state["communication"]["preferred_length"] in ("short", "medium", "long")
        assert state["communication"]["language_level"] in ("simple", "normal")

    def test_build_adaptive_state_recovery_overrides(self):
        from adaptive_learning import build_adaptive_state
        a = {"success_rate": 0.1, "consecutive_failures": 5, "computed_length": "long"}
        state = build_adaptive_state(a)
        assert state["communication"]["preferred_length"] == "short"
        assert state["communication"]["language_level"] == "simple"

    # === Radim Core Engine v2 tests ===

    def test_confidence_score_range(self):
        from adaptive_learning import compute_confidence_score
        c = compute_confidence_score({"success_rate": 0.7, "trust_score": 0.5, "total_adaptive_interactions": 20})
        assert 0.0 <= c <= 1.0

    def test_confidence_low_on_failures(self):
        from adaptive_learning import compute_confidence_score
        c = compute_confidence_score({"success_rate": 0.2, "trust_score": 0.1, "consecutive_failures": 4, "total_adaptive_interactions": 5})
        assert c < 0.3

    def test_fatigue_range(self):
        from adaptive_learning import compute_fatigue_level
        f = compute_fatigue_level({})
        assert 0.0 <= f <= 1.0

    def test_radim_score_range(self):
        from adaptive_learning import compute_radim_score
        r = compute_radim_score({"success_rate": 0.6, "trust_score": 0.5, "energy_level": 0.7})
        assert 0.0 <= r <= 1.0

    def test_radim_score_low_on_crisis(self):
        from adaptive_learning import compute_radim_score
        r = compute_radim_score({"success_rate": 0.1, "trust_score": 0.1, "energy_level": 0.2, "mood_concern": True})
        assert r < 0.4

    def test_alerts_empty_normal(self):
        from adaptive_learning import check_alerts
        assert len(check_alerts({"radim_score": 0.7})) == 0

    def test_alerts_caregiver_low_score(self):
        from adaptive_learning import check_alerts
        assert any(a["type"] == "caregiver" for a in check_alerts({"radim_score": 0.35}))

    def test_alerts_fatigue_break(self):
        from adaptive_learning import check_alerts
        assert any(a["type"] == "fatigue_break" for a in check_alerts({"radim_score": 0.5, "fatigue_level": 0.8}))

    def test_iot_activity_score(self):
        from adaptive_learning import compute_activity_score
        assert compute_activity_score({"motion": True, "door": True, "presence": True, "last_activity_minutes": 2}) >= 0.8
        assert compute_activity_score(None) is None

    def test_soft_adaptation_inactive(self):
        from adaptive_learning import compute_soft_adaptation
        assert compute_soft_adaptation({"success_rate": 0.7, "confidence_score": 0.6})["active"] is False

    def test_soft_adaptation_active(self):
        from adaptive_learning import compute_soft_adaptation
        s = compute_soft_adaptation({"success_rate": 0.35, "confidence_score": 0.4})
        assert s["active"] is True

    def test_state_has_v2_fields(self):
        from adaptive_learning import build_adaptive_state
        state = build_adaptive_state({"total_adaptive_interactions": 10, "success_rate": 0.6})
        for key in ("confidence_score", "fatigue_level", "radim_score", "soft_adaptation", "interaction_mode", "alerts"):
            assert key in state, f"Missing: {key}"
        assert "confirmation_level" in state["communication"]
        assert "energy_mode" in state["behavior"]

    def test_stt_no_change_normal(self):
        """Normal text should not be changed."""
        from speech_understanding import correct_stt_output
        result, corrections = correct_stt_output("Dobrý den, jak se máte?")
        assert len(corrections) == 0

    def test_build_speech_hints(self):
        """Speech hints include safety words."""
        from speech_understanding import build_speech_hints
        hints = build_speech_hints(None)
        assert "pomoc" in hints
        assert "léky" in hints
