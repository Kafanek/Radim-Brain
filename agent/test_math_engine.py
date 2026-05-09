"""
Unit tests for math_engine.

Run:    python3 -m agent.test_math_engine
        (from /radim-brain-ecosystem/)

Or:     python3 test_math_engine.py
        (from /agent/ — uses stdlib unittest, no pytest required)
"""
import unittest
from datetime import datetime, timedelta

try:
    from .math_engine import (
        State, Trend, DomainWeights, EngineSnapshot, SpeechParams,
        PreemptiveCheck, run_engine, predict_step, predict_horizon,
        update_trend, classify, derive_speech, preemptive_check,
        clamp, mode_severity, PERSONA_WEIGHTS,
        C_HARMONY, C_ALERT, C_TARGET, ALPHA_TARGET, C_MAX,
        DAMPING_30MIN, PREDICT_STEPS_30MIN,
    )
except ImportError:
    # Allow running as a flat script too
    from math_engine import (  # type: ignore
        State, Trend, DomainWeights, EngineSnapshot, SpeechParams,
        PreemptiveCheck, run_engine, predict_step, predict_horizon,
        update_trend, classify, derive_speech, preemptive_check,
        clamp, mode_severity, PERSONA_WEIGHTS,
        C_HARMONY, C_ALERT, C_TARGET, ALPHA_TARGET, C_MAX,
        DAMPING_30MIN, PREDICT_STEPS_30MIN,
    )


BASE_T = datetime(2026, 5, 9, 10, 0, 0)


def at(min_offset, ce=10, env=10, soc=10, phy=10, alpha=0.3, e=0.0):
    return State(t=BASE_T + timedelta(minutes=min_offset),
                 c_emotional=ce, c_environmental=env, c_social=soc,
                 c_physical=phy, alpha=alpha, e_valence=e)


# ════════════════════════════════════════════════════════════════
# Pure helpers
# ════════════════════════════════════════════════════════════════

class TestClassification(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(classify(0), "HARMONY")
        self.assertEqual(classify(11.99), "HARMONY")
        self.assertEqual(classify(12.0), "ALERT")
        self.assertEqual(classify(20.0), "ALERT")
        self.assertEqual(classify(26.99), "ALERT")
        self.assertEqual(classify(27.0), "CRISIS")
        self.assertEqual(classify(40.0), "CRISIS")

    def test_severity_ordering(self):
        self.assertLess(mode_severity("HARMONY"), mode_severity("ALERT"))
        self.assertLess(mode_severity("ALERT"), mode_severity("CRISIS"))


class TestClamp(unittest.TestCase):
    def test_within(self): self.assertEqual(clamp(5, 0, 10), 5)
    def test_below(self):  self.assertEqual(clamp(-1, 0, 10), 0)
    def test_above(self):  self.assertEqual(clamp(11, 0, 10), 10)


# ════════════════════════════════════════════════════════════════
# Domain weights
# ════════════════════════════════════════════════════════════════

class TestDomainWeights(unittest.TestCase):
    def test_default_normalized(self):
        w = DomainWeights().normalized()
        self.assertAlmostEqual(w.emotional + w.environmental + w.social + w.physical, 1.0)

    def test_normalize_arbitrary(self):
        w = DomainWeights(2, 1, 1, 0).normalized()  # sum 4
        self.assertEqual(w.emotional, 0.5)
        self.assertEqual(w.environmental, 0.25)
        self.assertEqual(w.physical, 0.0)

    def test_normalize_zero(self):
        # Should not divide by zero
        w = DomainWeights(0, 0, 0, 0).normalized()
        self.assertAlmostEqual(w.emotional, 0.4)  # falls back to default


# ════════════════════════════════════════════════════════════════
# State.total
# ════════════════════════════════════════════════════════════════

class TestStateTotal(unittest.TestCase):
    def test_default_weights(self):
        s = at(0, ce=20, env=10, soc=5, phy=15)
        # default: 0.4*20 + 0.2*10 + 0.2*5 + 0.2*15 = 8 + 2 + 1 + 3 = 14
        self.assertAlmostEqual(s.total(DomainWeights()), 14.0)

    def test_persona_changes_outcome(self):
        # High environmental load
        s = at(0, ce=10, env=30, soc=10, phy=10)
        senior = s.total(PERSONA_WEIGHTS["senior"])
        autism = s.total(PERSONA_WEIGHTS["child_autism"])
        # autism weights env at 0.4 vs senior 0.2 → higher total when env is high
        self.assertGreater(autism, senior)


# ════════════════════════════════════════════════════════════════
# Trend
# ════════════════════════════════════════════════════════════════

class TestTrend(unittest.TestCase):
    def test_zero_when_no_change(self):
        s1 = at(0)
        s2 = at(5)
        tr = update_trend(Trend(), s1, s2)
        self.assertAlmostEqual(tr.c_emotional, 0.0)
        self.assertAlmostEqual(tr.alpha, 0.0)

    def test_positive_when_rising(self):
        s1 = at(0, ce=10, alpha=0.3)
        s2 = at(5, ce=14, alpha=0.4)
        tr = update_trend(Trend(), s1, s2)
        self.assertGreater(tr.c_emotional, 0)
        self.assertGreater(tr.alpha, 0)

    def test_negative_when_falling(self):
        s1 = at(0, ce=20)
        s2 = at(5, ce=15)
        tr = update_trend(Trend(), s1, s2)
        self.assertLess(tr.c_emotional, 0)

    def test_ema_smoothing(self):
        # Sudden jump should NOT immediately register full magnitude
        s1 = at(0, ce=10)
        s2 = at(5, ce=20)  # +10 in one step
        tr = update_trend(Trend(), s1, s2)
        # With λ=0.3, trend = 0.3 * 10 = 3 (not full 10)
        self.assertAlmostEqual(tr.c_emotional, 3.0, places=5)

    def test_dt_normalization(self):
        # Same delta over 10 min should give half the rate of 5 min
        s1 = at(0, ce=10)
        s2_5min  = at(5, ce=14)
        s2_10min = at(10, ce=14)
        tr_5  = update_trend(Trend(), s1, s2_5min)
        tr_10 = update_trend(Trend(), s1, s2_10min)
        self.assertAlmostEqual(tr_10.c_emotional, tr_5.c_emotional / 2.0, places=5)


# ════════════════════════════════════════════════════════════════
# Predict step
# ════════════════════════════════════════════════════════════════

class TestPredictStep(unittest.TestCase):
    def test_advances_5_min(self):
        s = at(0)
        s2 = predict_step(s, Trend())
        self.assertEqual(s2.t - s.t, timedelta(minutes=5))

    def test_no_change_when_steady_at_target(self):
        s = at(0, alpha=ALPHA_TARGET)  # alpha at target → no stress kick
        s2 = predict_step(s, Trend())
        self.assertAlmostEqual(s2.c_emotional, s.c_emotional)

    def test_trend_pushes_value(self):
        s = at(0, ce=10, alpha=ALPHA_TARGET)
        tr = Trend(c_emotional=3.0)
        s2 = predict_step(s, tr)
        self.assertAlmostEqual(s2.c_emotional, 13.0)

    def test_high_alpha_pushes_emotional_up(self):
        s = at(0, ce=10, alpha=0.8)
        s2 = predict_step(s, Trend())
        # K2 * (0.8 - 0.4) / 4 = 7.5 * 0.1 = 0.75
        self.assertAlmostEqual(s2.c_emotional, 10.75, places=3)
        self.assertAlmostEqual(s2.c_physical, 10.75, places=3)
        # Environmental & social NOT coupled to alpha directly
        self.assertAlmostEqual(s2.c_environmental, 10.0)
        self.assertAlmostEqual(s2.c_social, 10.0)

    def test_clamped_to_max(self):
        s = at(0, ce=39)
        tr = Trend(c_emotional=10.0)
        s2 = predict_step(s, tr)
        self.assertEqual(s2.c_emotional, C_MAX)


# ════════════════════════════════════════════════════════════════
# Multi-step horizon
# ════════════════════════════════════════════════════════════════

class TestPredictHorizon(unittest.TestCase):
    def test_returns_correct_step_count(self):
        s = at(0)
        h = predict_horizon(s, Trend(), steps=6)
        self.assertEqual(len(h), 6)

    def test_damping_dampens_growth(self):
        s = at(0, ce=10, alpha=ALPHA_TARGET)
        tr = Trend(c_emotional=4.0)
        h = predict_horizon(s, tr, steps=6, damping=DAMPING_30MIN)
        # Without damping, would reach 10 + 6*4 = 34
        self.assertLess(h[-1].c_emotional, 34)
        # With damping 0.85: 10 + 4*(1 + 0.85 + 0.85^2 + ... + 0.85^5)
        expected = 10 + 4 * sum(0.85 ** k for k in range(6))
        self.assertAlmostEqual(h[-1].c_emotional, expected, places=3)

    def test_horizon_monotonic_when_only_positive_trend(self):
        s = at(0, ce=10, alpha=ALPHA_TARGET)
        tr = Trend(c_emotional=2.0)
        h = predict_horizon(s, tr)
        for i in range(1, len(h)):
            self.assertGreaterEqual(h[i].c_emotional, h[i - 1].c_emotional)


# ════════════════════════════════════════════════════════════════
# Speech params
# ════════════════════════════════════════════════════════════════

class TestSpeech(unittest.TestCase):
    def test_calm_when_low_C(self):
        s = at(0, ce=5, env=5, soc=5, phy=5, alpha=0.2)
        sp = derive_speech(s, DomainWeights())
        self.assertEqual(sp.mode, "HARMONY")
        self.assertAlmostEqual(sp.rate, 1.0)
        self.assertAlmostEqual(sp.pitch, 0.0)
        self.assertEqual(sp.pause_ms, 300)

    def test_slows_in_alert(self):
        s = at(0, ce=20, env=20, soc=20, phy=20, alpha=0.5)
        sp = derive_speech(s, DomainWeights())
        self.assertEqual(sp.mode, "ALERT")
        self.assertLess(sp.rate, 1.0)
        self.assertGreater(sp.pause_ms, 300)

    def test_very_slow_in_crisis(self):
        s = at(0, ce=35, env=35, soc=35, phy=35, alpha=0.9)
        sp = derive_speech(s, DomainWeights())
        self.assertEqual(sp.mode, "CRISIS")
        self.assertLessEqual(sp.rate, 0.7)  # rate clamped at 0.7
        self.assertEqual(sp.pause_ms, 800)  # pause clamped at 800
        self.assertLessEqual(sp.pitch, -4.0)  # pitch clamped at -4

    def test_empathy_grows_with_arousal(self):
        s_low  = at(0, ce=5, env=5, soc=5, phy=5, alpha=0.2)
        s_high = at(0, ce=30, env=30, soc=30, phy=30, alpha=0.8)
        e_low  = derive_speech(s_low,  DomainWeights()).empathy
        e_high = derive_speech(s_high, DomainWeights()).empathy
        self.assertGreater(e_high, e_low)

    def test_ssml_format(self):
        s = at(0, ce=25, env=25, soc=25, phy=25, alpha=0.6)
        sp = derive_speech(s, DomainWeights())
        prosody = sp.to_ssml_prosody()
        self.assertIn("rate=", prosody)
        self.assertIn("pitch=", prosody)
        self.assertIn("st", prosody)


# ════════════════════════════════════════════════════════════════
# Preemptive
# ════════════════════════════════════════════════════════════════

class TestPreemptive(unittest.TestCase):
    def test_no_crossing_when_steady(self):
        history = [at(-5), at(0)]
        snap = run_engine(history, DomainWeights())
        self.assertFalse(snap.preemptive.crosses_up)
        self.assertFalse(snap.preemptive.crosses_down)

    def test_detects_upward_crossing(self):
        # Steep emotional rise — currently HARMONY but trending into ALERT
        history = [
            at(-15, ce=8),
            at(-10, ce=10),
            at(-5, ce=12.5),
            at(0,  ce=14, alpha=0.4),
        ]
        snap = run_engine(history, DomainWeights())
        # Current total = 0.4*14 + 0.6*10 = 5.6+6 = 11.6 → still HARMONY
        self.assertEqual(snap.mode, "HARMONY")
        # Predicted should rise into ALERT
        self.assertTrue(snap.preemptive.crosses_up)
        self.assertEqual(snap.preemptive.predicted_mode, "ALERT")

    def test_horizon_totals_populated(self):
        history = [at(-5), at(0, ce=12)]
        snap = run_engine(history, DomainWeights())
        self.assertEqual(len(snap.preemptive.horizon_totals), PREDICT_STEPS_30MIN)


# ════════════════════════════════════════════════════════════════
# Engine end-to-end
# ════════════════════════════════════════════════════════════════

class TestEngine(unittest.TestCase):
    def test_empty_history_raises(self):
        with self.assertRaises(ValueError):
            run_engine([], DomainWeights())

    def test_single_state_cold_start(self):
        snap = run_engine([at(0)], DomainWeights())
        self.assertEqual(snap.trend.c_emotional, 0.0)
        self.assertEqual(snap.mode, "HARMONY")  # all defaults give 10 → HARMONY
        self.assertEqual(len(snap.horizon_30min), PREDICT_STEPS_30MIN)

    def test_full_snapshot_fields(self):
        snap = run_engine([at(-5), at(0)], DomainWeights())
        self.assertIsInstance(snap.state, State)
        self.assertIsInstance(snap.trend, Trend)
        self.assertIsInstance(snap.speech, SpeechParams)
        self.assertIsInstance(snap.preemptive, PreemptiveCheck)
        self.assertGreaterEqual(snap.c_total, 0)

    def test_persona_choice_affects_mode(self):
        # Sensory-heavy state: high env, modest emotional/social/physical
        history = [
            at(-5, ce=10, env=22, soc=8, phy=12),
            at(0,  ce=10, env=24, soc=8, phy=12),
        ]
        senior_snap = run_engine(history, PERSONA_WEIGHTS["senior"])
        autism_snap = run_engine(history, PERSONA_WEIGHTS["child_autism"])
        # autism weights environmental higher → higher c_total
        self.assertGreater(autism_snap.c_total, senior_snap.c_total)


# ════════════════════════════════════════════════════════════════
# Realistic scenarios (smoke tests of the whole system)
# ════════════════════════════════════════════════════════════════

class TestScenarios(unittest.TestCase):
    def _series(self, fn, n=6):
        return [State(t=BASE_T + timedelta(minutes=5 * i), **fn(i))
                for i in range(n)]

    def test_calm_morning_stays_harmony(self):
        history = self._series(lambda i: dict(
            c_emotional=8, c_environmental=10, c_social=8, c_physical=9,
            alpha=0.3, e_valence=0.2,
        ))
        snap = run_engine(history, PERSONA_WEIGHTS["senior"])
        self.assertEqual(snap.mode, "HARMONY")
        self.assertFalse(snap.preemptive.crosses_up)

    def test_rising_anxiety_triggers_preemptive_alert(self):
        history = self._series(lambda i: dict(
            c_emotional   = 8 + i * 2.0,
            c_environmental = 10 + i * 0.7,
            c_social      = 8,
            c_physical    = 9 + i * 1.0,
            alpha         = 0.3 + i * 0.07,
            e_valence     = 0.0,
        ))
        snap = run_engine(history, PERSONA_WEIGHTS["senior"])
        # Should at least flag preemptive crossing — current may already be ALERT
        # but we want to confirm horizon flags higher mode
        self.assertIn(snap.mode, ("HARMONY", "ALERT"))
        self.assertTrue(snap.preemptive.crosses_up
                        or snap.preemptive.predicted_mode in ("ALERT", "CRISIS"))

    def test_crisis_state_yields_calm_speech_params(self):
        history = self._series(lambda i: dict(
            c_emotional=20 + i * 2.5, c_environmental=18 + i * 2.0,
            c_social=15, c_physical=20 + i * 1.5,
            alpha=0.5 + i * 0.07, e_valence=-0.4,
        ))
        snap = run_engine(history, PERSONA_WEIGHTS["senior"])
        self.assertEqual(snap.mode, "CRISIS")
        # Radim must slow down significantly
        self.assertLess(snap.speech.rate, 0.95)
        self.assertGreater(snap.speech.pause_ms, 500)
        self.assertGreater(snap.speech.empathy, 0.7)


# ════════════════════════════════════════════════════════════════
# Run
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
