"""
Unit tests for agent/automations.py — pure trigger / condition logic.
DB writes covered separately by integration on Heroku.

Run: python3 -m agent.test_automations
"""
import unittest
from datetime import datetime, timedelta, timezone

try:
    from .automations import (
        TRIGGER_TYPES, ACTION_TYPES, SENSITIVE_HA_DOMAINS,
        SEVERITY_RANK, MAX_RULES_PER_USER, DEFAULT_COOLDOWN_MIN,
        list_trigger_types, list_action_types,
        trigger_matches, conditions_pass,
        _trigger_matches_mode_change, _trigger_matches_observation,
        _trigger_matches_goal_drift, _trigger_matches_time_of_day,
    )
except ImportError:
    from automations import (  # type: ignore
        TRIGGER_TYPES, ACTION_TYPES, SENSITIVE_HA_DOMAINS,
        SEVERITY_RANK, MAX_RULES_PER_USER, DEFAULT_COOLDOWN_MIN,
        list_trigger_types, list_action_types,
        trigger_matches, conditions_pass,
        _trigger_matches_mode_change, _trigger_matches_observation,
        _trigger_matches_goal_drift, _trigger_matches_time_of_day,
    )


# ─── Constants & registries ────────────────────────────────────────────────


class TestRegistry(unittest.TestCase):
    def test_four_trigger_types(self):
        self.assertEqual(set(TRIGGER_TYPES),
            {'agent_mode_change', 'observation_emitted',
             'goal_drift', 'time_of_day'})

    def test_four_action_types(self):
        self.assertEqual(set(ACTION_TYPES),
            {'ha_service_call', 'notify_caregiver', 'send_sms', 'radim_say'})

    def test_sensitive_ha_domains_locked(self):
        self.assertIn('lock', SENSITIVE_HA_DOMAINS)
        self.assertIn('alarm_control_panel', SENSITIVE_HA_DOMAINS)

    def test_max_rules_reasonable(self):
        self.assertGreater(MAX_RULES_PER_USER, 5)
        self.assertLess(MAX_RULES_PER_USER, 1000)

    def test_severity_rank_order(self):
        self.assertLess(SEVERITY_RANK['INFO'], SEVERITY_RANK['WARNING'])
        self.assertLess(SEVERITY_RANK['WARNING'], SEVERITY_RANK['ALERT'])
        self.assertLess(SEVERITY_RANK['ALERT'], SEVERITY_RANK['CRISIS'])

    def test_list_helpers_format(self):
        for t in list_trigger_types():
            self.assertIn('id', t); self.assertIn('label', t)
            self.assertIn('config_keys', t)
        for a in list_action_types():
            self.assertIn('id', a); self.assertIn('label', a)
            self.assertIn('config_keys', a)


# ─── Mode change trigger ───────────────────────────────────────────────────


class TestModeChangeTrigger(unittest.TestCase):
    def _rule(self, to_mode='CRISIS', from_mode=''):
        return {'trigger_type': 'agent_mode_change',
                'trigger_config': {'to_mode': to_mode, 'from_mode': from_mode}}

    def test_fires_on_mode_match(self):
        ctx = {'event': 'mode_change', 'prev_mode': 'ALERT', 'new_mode': 'CRISIS'}
        self.assertTrue(trigger_matches(self._rule('CRISIS'), ctx))

    def test_does_not_fire_when_to_mode_differs(self):
        ctx = {'event': 'mode_change', 'prev_mode': 'ALERT', 'new_mode': 'HARMONY'}
        self.assertFalse(trigger_matches(self._rule('CRISIS'), ctx))

    def test_from_mode_filter(self):
        ctx = {'event': 'mode_change', 'prev_mode': 'HARMONY', 'new_mode': 'CRISIS'}
        # from_mode=ALERT but prev=HARMONY → doesn't match
        self.assertFalse(trigger_matches(self._rule('CRISIS', 'ALERT'), ctx))
        # from_mode='' (any) → matches
        self.assertTrue(trigger_matches(self._rule('CRISIS', ''), ctx))

    def test_does_not_fire_for_other_events(self):
        ctx = {'event': 'observation', 'observation_type': 'foo'}
        self.assertFalse(trigger_matches(self._rule(), ctx))


# ─── Observation trigger ──────────────────────────────────────────────────


class TestObservationTrigger(unittest.TestCase):
    def _rule(self, otype='ha_realtime_smoke', min_sev='ALERT'):
        return {'trigger_type': 'observation_emitted',
                'trigger_config': {'observation_type': otype,
                                    'min_severity': min_sev}}

    def test_fires_on_match(self):
        ctx = {'event': 'observation',
                'observation_type': 'ha_realtime_smoke', 'severity': 'CRISIS'}
        self.assertTrue(trigger_matches(self._rule(), ctx))

    def test_severity_below_min(self):
        ctx = {'event': 'observation',
                'observation_type': 'ha_realtime_smoke', 'severity': 'WARNING'}
        # min=ALERT, actual=WARNING → no match
        self.assertFalse(trigger_matches(self._rule(min_sev='ALERT'), ctx))

    def test_type_mismatch(self):
        ctx = {'event': 'observation',
                'observation_type': 'sleep_drift', 'severity': 'CRISIS'}
        self.assertFalse(trigger_matches(self._rule('ha_realtime_smoke'), ctx))

    def test_empty_type_matches_any(self):
        ctx = {'event': 'observation',
                'observation_type': 'sleep_drift', 'severity': 'ALERT'}
        # observation_type='' → any
        self.assertTrue(trigger_matches(self._rule(otype='', min_sev='ALERT'), ctx))


# ─── Goal drift trigger ────────────────────────────────────────────────────


class TestGoalDriftTrigger(unittest.TestCase):
    def _rule(self, goal='medication_compliance', min_count=1):
        return {'trigger_type': 'goal_drift',
                'trigger_config': {'goal_type': goal,
                                    'min_drift_count': min_count}}

    def test_fires_on_drift(self):
        ctx = {'event': 'goal_drift',
                'goal_type': 'medication_compliance', 'drift_count': 2}
        self.assertTrue(trigger_matches(self._rule(), ctx))

    def test_below_min_count(self):
        ctx = {'event': 'goal_drift',
                'goal_type': 'medication_compliance', 'drift_count': 1}
        self.assertFalse(trigger_matches(self._rule(min_count=3), ctx))

    def test_goal_mismatch(self):
        ctx = {'event': 'goal_drift',
                'goal_type': 'sleep_quality', 'drift_count': 5}
        self.assertFalse(trigger_matches(self._rule('medication_compliance'), ctx))


# ─── Time of day trigger ──────────────────────────────────────────────────


class TestTimeOfDayTrigger(unittest.TestCase):
    def _rule(self, hour=22, minute=0, days=None):
        return {'trigger_type': 'time_of_day',
                'trigger_config': {'hour': hour, 'minute': minute,
                                    'days_of_week': days
                                    if days is not None else [0,1,2,3,4,5,6]}}

    def test_fires_at_exact_time(self):
        # 2026-05-10 was a Sunday (weekday=6)
        ctx = {'event': 'cycle_tick',
                'now': datetime(2026, 5, 10, 22, 0, 0)}
        self.assertTrue(trigger_matches(self._rule(22, 0), ctx))

    def test_within_5min_window(self):
        ctx = {'event': 'cycle_tick',
                'now': datetime(2026, 5, 10, 22, 4, 30)}
        self.assertTrue(trigger_matches(self._rule(22, 0), ctx))

    def test_outside_window(self):
        ctx = {'event': 'cycle_tick',
                'now': datetime(2026, 5, 10, 22, 10, 0)}
        self.assertFalse(trigger_matches(self._rule(22, 0), ctx))

    def test_day_filter(self):
        # 2026-05-10 is Sunday (weekday=6); rule limited to weekdays only
        ctx = {'event': 'cycle_tick',
                'now': datetime(2026, 5, 10, 22, 0, 0)}
        rule = self._rule(22, 0, days=[0, 1, 2, 3, 4])  # Mon-Fri
        self.assertFalse(trigger_matches(rule, ctx))

    def test_does_not_fire_for_other_events(self):
        ctx = {'event': 'mode_change'}
        self.assertFalse(trigger_matches(self._rule(), ctx))


# ─── Conditions ────────────────────────────────────────────────────────────


class TestConditions(unittest.TestCase):
    def test_no_cooldown_passes(self):
        rule = {'condition_config': {}}
        self.assertTrue(conditions_pass(rule, {}))

    def test_cooldown_active_blocks(self):
        # Last fired 5 minutes ago, cooldown 30 min → blocked
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        rule = {'condition_config': {'cooldown_minutes': 30},
                'last_fired_at': recent}
        self.assertFalse(conditions_pass(rule, {}))

    def test_cooldown_expired_passes(self):
        # Last fired 35 min ago, cooldown 30 min → ok
        old = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
        rule = {'condition_config': {'cooldown_minutes': 30},
                'last_fired_at': old}
        self.assertTrue(conditions_pass(rule, {}))

    def test_cooldown_zero_disabled(self):
        # cooldown=0 → no time gate
        recent = datetime.now(timezone.utc).isoformat()
        rule = {'condition_config': {'cooldown_minutes': 0},
                'last_fired_at': recent}
        self.assertTrue(conditions_pass(rule, {}))

    def test_require_mode_passes_when_higher(self):
        rule = {'condition_config': {'require_mode': 'ALERT'}}
        self.assertTrue(conditions_pass(rule, {'current_mode': 'CRISIS'}))

    def test_require_mode_blocks_when_lower(self):
        rule = {'condition_config': {'require_mode': 'ALERT'}}
        self.assertFalse(conditions_pass(rule, {'current_mode': 'HARMONY'}))

    def test_require_mode_passes_when_equal(self):
        rule = {'condition_config': {'require_mode': 'ALERT'}}
        self.assertTrue(conditions_pass(rule, {'current_mode': 'ALERT'}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
