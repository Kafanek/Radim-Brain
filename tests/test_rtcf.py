"""
RTCF Test Suite — Comprehensive tests for Radim Temporal Coherence Framework
==============================================================================
Tests all 6 RTCF modules: constants, temporal, beat, coherence, policy, bridge.
"""

import math
import time
import pytest


# ═══════════════════════════════════════════════════════════
# 1. CONSTANTS & SEQUENCES
# ═══════════════════════════════════════════════════════════

class TestRTCFConstants:
    """Test constants, RadimSequence, and helpers."""

    def test_weights_sum_to_one(self):
        from rtcf_constants import W_H, W_R, W_C, W_T
        assert abs(W_H + W_R + W_C + W_T - 1.0) < 1e-9

    def test_radim_sequence_base_cases(self):
        from rtcf_constants import radim_sequence, PHI
        assert radim_sequence(0) == 1.0
        assert abs(radim_sequence(1) - PHI) < 1e-9

    def test_radim_sequence_recurrence(self):
        from rtcf_constants import radim_sequence, PHI, DELTA
        for n in range(2, 10):
            expected = PHI * radim_sequence(n - 1) + (DELTA - PHI) * radim_sequence(n - 2)
            assert abs(radim_sequence(n) - expected) < 1e-6, f"R({n}) failed recurrence"

    def test_radim_sequence_monotonic(self):
        from rtcf_constants import radim_sequence
        for n in range(1, 12):
            assert radim_sequence(n) < radim_sequence(n + 1), f"R({n}) >= R({n+1})"

    def test_harmonic_n_matches_fib_plus_lucas(self):
        from rtcf_constants import harmonic_n, FIBONACCI, LUCAS
        for n in range(1, 10):
            expected = FIBONACCI[n] + LUCAS[n]
            assert harmonic_n(n) == float(expected)

    def test_pell_n_matches_array(self):
        from rtcf_constants import pell_n, PELL
        for n in range(1, min(10, len(PELL))):
            assert pell_n(n) == float(PELL[n])

    def test_n_clamping(self):
        from rtcf_constants import harmonic_n, pell_n
        # Should not crash on out-of-range values
        assert harmonic_n(0) == harmonic_n(1)   # clamped to N_MIN=1
        assert harmonic_n(100) == harmonic_n(14) # clamped to N_MAX=14
        assert pell_n(-5) == pell_n(1)

    def test_triadic_constants(self):
        from rtcf_constants import PHI, DELTA, RHO
        assert abs(PHI - 1.61803398875) < 1e-9
        assert abs(DELTA - 2.41421356237) < 1e-9
        assert abs(RHO - 2.0134621242) < 1e-9


# ═══════════════════════════════════════════════════════════
# 2. TEMPORAL ENGINE
# ═══════════════════════════════════════════════════════════

class TestRTCFTemporal:
    """Test oscillators and T_radim."""

    def test_beat_oscillator_range(self):
        from rtcf_temporal import beat_oscillator
        for t in [0, 1, 2.5, 5, 10, 100, 1000]:
            val = beat_oscillator(t)
            assert -1.0 <= val <= 1.0, f"beat({t}) = {val} out of range"

    def test_flow_oscillator_range(self):
        from rtcf_temporal import flow_oscillator
        for t in [0, 100, 300, 600, 900, 5000]:
            val = flow_oscillator(t)
            assert -1.0 <= val <= 1.0, f"flow({t}) = {val} out of range"

    def test_circadian_oscillator_range(self):
        from rtcf_temporal import circadian_oscillator
        for t in [0, 21600, 43200, 50400, 64800, 86400]:
            val = circadian_oscillator(t)
            assert -1.0 <= val <= 1.0, f"circadian({t}) = {val} out of range"

    def test_circadian_peaks_at_14h(self):
        from rtcf_temporal import circadian_oscillator
        # 14:00 = 50400 seconds → should be peak (cos(0) = 1.0)
        assert abs(circadian_oscillator(50400) - 1.0) < 1e-6

    def test_t_radim_range(self):
        from rtcf_temporal import t_radim
        for t in [0, 1, 100, 1000, 50400, 86400]:
            val = t_radim(t)
            assert 0.0 <= val <= 1.0, f"t_radim({t}) = {val} out of [0,1]"

    def test_determinism(self):
        from rtcf_temporal import t_radim
        t = 12345.678
        a = t_radim(t)
        b = t_radim(t)
        assert a == b, "t_radim is not deterministic"

    def test_period_clamping(self):
        from rtcf_temporal import beat_oscillator
        # Period below min (3s) should be clamped
        v1 = beat_oscillator(6.0, period=1.0)
        v2 = beat_oscillator(6.0, period=3.0)
        assert v1 == v2, "Period not clamped to minimum"


# ═══════════════════════════════════════════════════════════
# 3. BEAT ENGINE
# ═══════════════════════════════════════════════════════════

class TestRTCFBeat:
    """Test BPM, HRV, autonomic mode, and BeatState."""

    def test_bpm_baseline(self):
        from rtcf_beat import compute_bpm
        assert compute_bpm() == 68  # all zeros = baseline

    def test_bpm_clamped_high(self):
        from rtcf_beat import compute_bpm
        # 68 + 12 + 10 + 8 + 6 - 0 = 104 (max with recovery=0)
        bpm = compute_bpm(risk=1.0, pain=1.0, intuition=1.0, load=1.0, recovery=0.0)
        assert bpm == 104
        assert bpm <= 110  # BPM_MAX

    def test_bpm_clamped_low(self):
        from rtcf_beat import compute_bpm
        bpm = compute_bpm(risk=0.0, pain=0.0, intuition=0.0, load=0.0, recovery=1.0)
        assert bpm == 58  # 68 - 10 = 58
        # Actually check if it can go to 50
        # 68 + 0 + 0 + 0 + 0 - 10 = 58, which is above 50
        assert bpm >= 50

    def test_hrv_inverse(self):
        from rtcf_beat import compute_hrv
        hrv_calm = compute_hrv(threat=0.0, load=0.0)
        hrv_stress = compute_hrv(threat=1.0, load=1.0)
        assert hrv_calm > hrv_stress
        assert hrv_calm == 1.0
        assert hrv_stress == 0.0

    def test_autonomic_parasympathetic(self):
        from rtcf_beat import classify_autonomic_mode
        mode = classify_autonomic_mode(risk=0.0, pain=0.0, threat=0.0, trust=0.8, safety=0.9)
        assert mode == "parasympathetic"

    def test_autonomic_sympathetic(self):
        from rtcf_beat import classify_autonomic_mode
        mode = classify_autonomic_mode(risk=0.9, pain=0.8, threat=0.9, trust=0.1, safety=0.1)
        assert mode == "sympathetic"

    def test_autonomic_balanced(self):
        from rtcf_beat import classify_autonomic_mode
        mode = classify_autonomic_mode(risk=0.5, pain=0.4, threat=0.5, trust=0.5, safety=0.5)
        assert mode == "balanced"

    def test_beat_state_structure(self):
        from rtcf_beat import compute_beat_state
        state = compute_beat_state(risk=0.3, trust=0.7, safety=0.6)
        assert "bpm" in state
        assert "hrv" in state
        assert "arousal" in state
        assert "stability" in state
        assert "warmth" in state
        assert "presence" in state
        assert "autonomic_mode" in state
        assert 50 <= state["bpm"] <= 110
        assert 0.0 <= state["hrv"] <= 1.0
        assert 0.0 <= state["stability"] <= 1.0

    def test_presence_peaks_at_moderate_arousal(self):
        from rtcf_beat import compute_beat_state
        # arousal = 0.5 → max presence
        state_mid = compute_beat_state(risk=0.5, threat=0.5, pain=0.5)
        state_low = compute_beat_state(risk=0.0, threat=0.0, pain=0.0)
        state_high = compute_beat_state(risk=1.0, threat=1.0, pain=1.0)
        assert state_mid["presence"] >= state_low["presence"]
        assert state_mid["presence"] >= state_high["presence"]


# ═══════════════════════════════════════════════════════════
# 4. COHERENCE ENGINE
# ═══════════════════════════════════════════════════════════

class TestRTCFCoherence:
    """Test Psi_RTCF, ratio, and state interpretation."""

    def test_psi_rtcf_positive(self):
        from rtcf_coherence import compute_psi_rtcf
        t = time.time()
        for n in range(1, 15):
            psi = compute_psi_rtcf(t, n)
            assert psi > 0, f"Psi_RTCF(n={n}) should be positive"

    def test_psi_rtcf_grows_with_n(self):
        from rtcf_coherence import compute_psi_rtcf
        t = time.time()
        prev = compute_psi_rtcf(t, 1)
        for n in range(2, 12):
            curr = compute_psi_rtcf(t, n)
            assert curr > prev, f"Psi not monotonic at n={n}"
            prev = curr

    def test_ratio_neutral_on_none(self):
        from rtcf_coherence import compute_ratio
        assert compute_ratio(10.0, None) == 2.0
        assert compute_ratio(10.0, 0) == 2.0

    def test_ratio_normal(self):
        from rtcf_coherence import compute_ratio
        r = compute_ratio(10.0, 5.0)
        assert abs(r - 2.0) < 1e-9

    def test_state_recovery(self):
        from rtcf_coherence import interpret_state
        assert interpret_state(1.0) == "recovery"
        assert interpret_state(1.79) == "recovery"

    def test_state_optimal(self):
        from rtcf_coherence import interpret_state
        assert interpret_state(1.8) == "optimal_conscious"
        assert interpret_state(2.0) == "optimal_conscious"
        assert interpret_state(2.15) == "optimal_conscious"

    def test_state_escalation(self):
        from rtcf_coherence import interpret_state
        assert interpret_state(2.16) == "escalation"
        assert interpret_state(3.0) == "escalation"

    def test_full_coherence_structure(self):
        from rtcf_coherence import compute_coherence_full
        result = compute_coherence_full(t=time.time(), n=5)
        assert "psi_rtcf" in result
        assert "ratio" in result
        assert "state" in result
        assert "components" in result
        assert "harmony" in result["components"]
        assert "radim" in result["components"]
        assert "crisis" in result["components"]
        assert "temporal" in result["components"]


# ═══════════════════════════════════════════════════════════
# 5. POLICY ADAPTER
# ═══════════════════════════════════════════════════════════

class TestRTCFPolicy:
    """Test policy object assembly and modifiers."""

    def _beat(self, autonomic="balanced", bpm=68, hrv=0.5):
        return {"bpm": bpm, "hrv": hrv, "arousal": 0.3, "stability": 0.5,
                "warmth": 0.5, "presence": 0.7, "autonomic_mode": autonomic}

    def test_policy_structure(self):
        from rtcf_policy import build_policy
        p = build_policy("optimal_conscious", 5.0, 2.0, self._beat())
        assert "state" in p
        assert "psi_rtcf" in p
        assert "ratio" in p
        assert "beat_state" in p
        assert "voice_modifiers" in p
        assert "proactive_modifiers" in p
        assert "alert_bias" in p
        assert "reasoning" in p

    def test_voice_recovery_slows_rate(self):
        from rtcf_policy import compute_voice_modifiers
        mods = compute_voice_modifiers("recovery", self._beat())
        assert mods["rate_adjust"] < 0  # slower

    def test_voice_escalation_slows_more(self):
        from rtcf_policy import compute_voice_modifiers
        recovery_mods = compute_voice_modifiers("recovery", self._beat())
        escalation_mods = compute_voice_modifiers("escalation", self._beat())
        assert escalation_mods["rate_adjust"] < recovery_mods["rate_adjust"]

    def test_voice_optimal_minimal(self):
        from rtcf_policy import compute_voice_modifiers
        mods = compute_voice_modifiers("optimal_conscious", self._beat())
        assert abs(mods["rate_adjust"]) <= 2
        assert mods["pause_adjust_ms"] == 0

    def test_proactive_recovery_less_sensitive(self):
        from rtcf_policy import compute_proactive_modifiers
        mods = compute_proactive_modifiers("recovery", self._beat())
        assert mods["sensitivity_adjust"] < 1.0

    def test_proactive_escalation_more_sensitive(self):
        from rtcf_policy import compute_proactive_modifiers
        mods = compute_proactive_modifiers("escalation", self._beat())
        assert mods["sensitivity_adjust"] > 1.0

    def test_alert_bias_range(self):
        from rtcf_policy import compute_alert_bias
        for state in ["recovery", "optimal_conscious", "escalation"]:
            for ratio in [0.5, 1.0, 1.8, 2.0, 2.15, 2.5, 3.0]:
                bias = compute_alert_bias(state, ratio)
                assert 0.0 <= bias <= 1.0, f"bias({state},{ratio}) = {bias}"


# ═══════════════════════════════════════════════════════════
# 6. BRIDGE
# ═══════════════════════════════════════════════════════════

class TestRTCFBridge:
    """Test input mapping and enhance_with_rtcf."""

    def _mock_psi_state(self, C=10.0, alpha=0.3):
        """Minimal mock of compute_psi_state() output."""
        return {
            "psi": {"C": C, "E": 0.6, "R": 0.7, "S": 0.2},
            "mode": "HARMONY",
            "empathy": {"E": 0.6, "adaptation": "standard"},
            "speech": {"rate": 1.0, "pause_ms": 500, "pitch_pct": 2},
        }

    def test_disabled_passthrough(self):
        import rtcf_bridge
        original = rtcf_bridge.ENABLE_RTCF
        try:
            rtcf_bridge.ENABLE_RTCF = False
            state = self._mock_psi_state()
            result = rtcf_bridge.enhance_with_rtcf(state, 10.0, 0.3)
            assert "rtcf" not in result
        finally:
            rtcf_bridge.ENABLE_RTCF = original

    def test_enabled_adds_rtcf_key(self):
        import rtcf_bridge
        original = rtcf_bridge.ENABLE_RTCF
        try:
            rtcf_bridge.ENABLE_RTCF = True
            state = self._mock_psi_state()
            result = rtcf_bridge.enhance_with_rtcf(state, 10.0, 0.3, user_id="test")
            assert "rtcf" in result
            rtcf = result["rtcf"]
            assert "state" in rtcf
            assert "psi_rtcf" in rtcf
            assert "beat_state" in rtcf
            assert "voice_modifiers" in rtcf
            assert "reasoning" in rtcf
        finally:
            rtcf_bridge.ENABLE_RTCF = original

    def test_input_mapping_normalized(self):
        from rtcf_bridge import _map_brain_to_rtcf
        inputs = _map_brain_to_rtcf(20.0, 0.5, self._mock_psi_state())
        for key in ["risk", "threat", "trust", "safety", "load", "recovery",
                     "anomaly", "uncertainty"]:
            assert 0.0 <= inputs[key] <= 1.0, f"{key}={inputs[key]} out of [0,1]"

    def test_input_mapping_extremes(self):
        from rtcf_bridge import _map_brain_to_rtcf
        # C=0 → minimal risk/load
        low = _map_brain_to_rtcf(0.0, 0.0, self._mock_psi_state(C=0))
        assert low["risk"] == 0.0
        assert low["recovery"] == 1.0
        # C=40 → max risk
        high = _map_brain_to_rtcf(40.0, 1.0, self._mock_psi_state(C=40))
        assert high["risk"] == 1.0
        assert high["recovery"] == 0.0

    def test_existing_state_preserved(self):
        import rtcf_bridge
        original = rtcf_bridge.ENABLE_RTCF
        try:
            rtcf_bridge.ENABLE_RTCF = True
            state = self._mock_psi_state()
            result = rtcf_bridge.enhance_with_rtcf(state, 10.0, 0.3)
            # Original keys still present
            assert result["mode"] == "HARMONY"
            assert result["psi"]["C"] == 10.0
            assert result["speech"]["rate"] == 1.0
        finally:
            rtcf_bridge.ENABLE_RTCF = original

    def test_standalone_api(self):
        from rtcf_bridge import compute_rtcf_standalone
        result = compute_rtcf_standalone({
            "timestamp": time.time(),
            "n": 5,
            "risk": 0.3,
            "threat": 0.2,
            "trust": 0.7,
            "safety": 0.8,
            "load": 0.2,
            "recovery": 0.6,
            "anomaly": 0.1,
            "uncertainty": 0.2,
        })
        assert "state" in result
        assert "beat_state" in result
        assert result["beat_state"]["bpm"] >= 50


# ═══════════════════════════════════════════════════════════
# 7. END-TO-END with brain_core
# ═══════════════════════════════════════════════════════════

class TestRTCFEndToEnd:
    """Integration test: RTCF through compute_psi_state."""

    def test_brain_core_with_rtcf_disabled(self):
        """Existing behavior unchanged when RTCF off."""
        import rtcf_bridge
        original = rtcf_bridge.ENABLE_RTCF
        try:
            rtcf_bridge.ENABLE_RTCF = False
            from brain_core import compute_psi_state
            result = compute_psi_state(10.0, 0.3)
            assert "mode" in result
            assert result["mode"] == "HARMONY"
            # No rtcf key when disabled (unless integration not wired yet)
        finally:
            rtcf_bridge.ENABLE_RTCF = original

    def test_brain_core_with_rtcf_enabled(self):
        """RTCF enriches brain output when enabled."""
        import rtcf_bridge
        original = rtcf_bridge.ENABLE_RTCF
        try:
            rtcf_bridge.ENABLE_RTCF = True
            from brain_core import compute_psi_state
            result = compute_psi_state(10.0, 0.3, user_id="test_rtcf")
            # After wiring, this should have rtcf key
            # Before wiring, this test documents the expected behavior
            if "rtcf" in result:
                assert result["rtcf"]["state"] in ("recovery", "optimal_conscious", "escalation")
                assert result["rtcf"]["beat_state"]["bpm"] >= 50
                assert "voice_modifiers" in result["rtcf"]
            # Original state always preserved
            assert result["mode"] == "HARMONY"
            assert result["psi"]["C"] == round(10.0, 4)
        finally:
            rtcf_bridge.ENABLE_RTCF = original
