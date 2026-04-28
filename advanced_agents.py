"""
🤖 ADVANCED AGENTS v1.0
========================
Extended agent capabilities for Radim senior care.

Agents:
    1. MedicationTracker — tracks if senior took meds
    2. SleepAgent — analyzes sleep quality from motion
    3. SocialIsolationAgent — scores loneliness risk
    4. WeatherAgent — adapts suggestions to weather
    5. WeeklyReportAgent — generates family reports
    6. EmergencyProtocol — full crisis automation
    7. LearningAgent — adapts detection thresholds
"""

import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning, db_load_profile, audit_log
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

agents_bp = Blueprint('advanced_agents', __name__)


# ═══════════════════════════════════════════════════════════════════
# 💊 MEDICATION TRACKER
# ═══════════════════════════════════════════════════════════════════

class MedicationTracker:
    """Track medication adherence for seniors."""

    @staticmethod
    def record_response(user_id, confirmed=True, method='voice'):
        """Record medication confirmation from morning checkin."""
        learning = db_load_learning(user_id)
        responses = learning.get("medication_responses", [])
        responses.append({
            "confirmed": confirmed,
            "method": method,  # voice, push, button
            "at": datetime.utcnow().isoformat(),
            "date": datetime.utcnow().strftime("%Y-%m-%d")
        })
        learning["medication_responses"] = responses[-90:]  # 3 months
        db_save_learning(user_id, learning)
        return True

    @staticmethod
    def get_compliance(user_id, days=30):
        """Get medication compliance stats."""
        learning = db_load_learning(user_id)
        responses = learning.get("medication_responses", [])
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = [r for r in responses if r.get("date", "") >= cutoff]

        if not recent:
            return {"compliance_pct": None, "total_days": 0, "confirmed": 0, "missed": 0, "streak": 0}

        confirmed = sum(1 for r in recent if r.get("confirmed"))
        missed = len(recent) - confirmed

        # Current streak
        streak = 0
        for r in reversed(recent):
            if r.get("confirmed"):
                streak += 1
            else:
                break

        return {
            "compliance_pct": round(confirmed / len(recent) * 100, 1) if recent else 0,
            "total_days": len(recent),
            "confirmed": confirmed,
            "missed": missed,
            "streak": streak,
            "last_confirmed": next((r["at"] for r in reversed(recent) if r.get("confirmed")), None),
        }


@agents_bp.route('/api/agents/medication/confirm', methods=['POST'])
def medication_confirm():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id', '')
    confirmed = data.get('confirmed', True)
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    MedicationTracker.record_response(user_id, confirmed, data.get('method', 'button'))
    return jsonify({'success': True, 'message': '💊 Zaznamenáno' if confirmed else '⚠️ Nezaznamenáno'})


@agents_bp.route('/api/agents/medication/compliance/<user_id>', methods=['GET'])
def medication_compliance(user_id):
    days = int(request.args.get('days', 30))
    return jsonify({'success': True, **MedicationTracker.get_compliance(user_id, days)})


# ═══════════════════════════════════════════════════════════════════
# 😴 SLEEP AGENT
# ═══════════════════════════════════════════════════════════════════

class SleepAgent:
    """Analyze sleep quality from motion sensor patterns."""

    @staticmethod
    def analyze_sleep(user_id, date=None):
        """Analyze one night's sleep (23:00 → 06:00)."""
        if not _AVAILABLE:
            return {"quality": "unknown"}

        try:
            with db_context() as db:
                if is_postgres():
                    rows = db.execute(
                        "SELECT recorded_at, value FROM iot_sensor_data "
                        "WHERE device_id IN (SELECT device_id FROM iot_devices WHERE user_id = ?) "
                        "AND sensor_type = 'motion' "
                        "AND recorded_at > NOW() - INTERVAL '24 hours' "
                        "ORDER BY recorded_at",
                        (user_id,)
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT recorded_at, value FROM iot_sensor_data "
                        "WHERE device_id IN (SELECT device_id FROM iot_devices WHERE user_id = ?) "
                        "AND sensor_type = 'motion' "
                        "AND recorded_at > datetime('now', '-24 hours') "
                        "ORDER BY recorded_at",
                        (user_id,)
                    ).fetchall()

            if not rows:
                return {"quality": "unknown", "reason": "Nedostatek dat z pohybových senzorů"}

            # Filter to nighttime (23:00-06:00)
            night_events = []
            for r in rows:
                ts = r['recorded_at'] if isinstance(r, dict) else r[0]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace('Z', ''))
                hour = ts.hour
                if hour >= 23 or hour <= 6:
                    val = r['value'] if isinstance(r, dict) else r[1]
                    if float(val) > 0:
                        night_events.append(ts)

            motion_count = len(night_events)

            # Score
            if motion_count <= 3:
                quality = "excellent"
                score = 95
                desc = "Výborný spánek — minimální pohyb v noci"
            elif motion_count <= 6:
                quality = "good"
                score = 80
                desc = "Dobrý spánek — normální noční aktivita"
            elif motion_count <= 12:
                quality = "fair"
                score = 55
                desc = "Průměrný spánek — zvýšený neklid"
            elif motion_count <= 20:
                quality = "poor"
                score = 30
                desc = "Špatný spánek — častý neklid a probouzení"
            else:
                quality = "very_poor"
                score = 10
                desc = "Velmi špatný spánek — vážný neklid nebo nespavost"

            return {
                "quality": quality,
                "score": score,
                "description": desc,
                "motion_events": motion_count,
                "date": (date or datetime.utcnow()).strftime("%Y-%m-%d"),
            }
        except Exception as e:
            return {"quality": "error", "error": str(e)}

    @staticmethod
    def get_sleep_history(user_id, days=7):
        """Get sleep quality trend."""
        learning = db_load_learning(user_id)
        history = learning.get("sleep_history", [])
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [h for h in history if h.get("date", "") >= cutoff]

    @staticmethod
    def save_sleep_analysis(user_id, analysis):
        """Store sleep analysis result."""
        learning = db_load_learning(user_id)
        history = learning.get("sleep_history", [])
        history.append(analysis)
        learning["sleep_history"] = history[-90:]
        db_save_learning(user_id, learning)

        # Sprint AG.4.5: emit poor sleep to bus so chat-time CareAgent
        # sees it without re-running the analysis. Dedupe per day so a
        # repeated analysis call doesn't spam the bus.
        try:
            from agent_bus import emit as _bus_emit, dedupe as _bus_dedupe
            quality = analysis.get('quality')
            if quality in ('poor', 'very_poor'):
                topic = 'poor_sleep'
                # Dedupe: one bus message per day per user
                if not _bus_dedupe(user_id, sender=None, topic=topic,
                                   within_minutes=720, any_sender=True,
                                   severity_min='warning'):
                    severity = 'alert' if quality == 'very_poor' else 'warning'
                    _bus_emit(
                        user_id=user_id,
                        sender='sleep_agent',
                        kind='context',
                        severity=severity,
                        topic=topic,
                        payload={
                            'quality': quality,
                            'score': analysis.get('score'),
                            'motion_events': analysis.get('motion_events'),
                            'message': f"Spánek byl {analysis.get('description', quality)}.",
                            'date': analysis.get('date'),
                        },
                        ttl_minutes=720,  # 12h — covers morning chat awareness
                    )
        except Exception:
            pass


@agents_bp.route('/api/agents/sleep/<user_id>', methods=['GET'])
def sleep_analysis(user_id):
    result = SleepAgent.analyze_sleep(user_id)
    SleepAgent.save_sleep_analysis(user_id, result)
    return jsonify({'success': True, **result})


@agents_bp.route('/api/agents/sleep/<user_id>/history', methods=['GET'])
def sleep_history(user_id):
    days = int(request.args.get('days', 7))
    history = SleepAgent.get_sleep_history(user_id, days)
    return jsonify({'success': True, 'history': history, 'count': len(history)})


# ═══════════════════════════════════════════════════════════════════
# 🤝 SOCIAL ISOLATION SCORE
# ═══════════════════════════════════════════════════════════════════

class SocialIsolationAgent:
    """Compute social isolation risk score."""

    @staticmethod
    def compute_score(user_id):
        """Compute isolation score 0-100 (0=connected, 100=isolated)."""
        if not _AVAILABLE:
            return {"score": 0, "level": "unknown"}

        signals = {}
        try:
            with db_context() as db:
                # 1. Chat interactions (7 days)
                if is_postgres():
                    row = db.execute(
                        "SELECT COUNT(*) as cnt FROM memory_history "
                        "WHERE user_id = ? AND role = 'user' AND created_at > NOW() - INTERVAL '7 days'",
                        (user_id,)
                    ).fetchone()
                else:
                    row = db.execute(
                        "SELECT COUNT(*) as cnt FROM memory_history "
                        "WHERE user_id = ? AND role = 'user' AND created_at > datetime('now', '-7 days')",
                        (user_id,)
                    ).fetchone()
                chat_count = row['cnt'] or row[0] or 0
                signals['chat'] = min(1.0, max(0.0, 1 - chat_count / 20))  # 20+ = fully connected

                # 2. Hours since last interaction
                if is_postgres():
                    row2 = db.execute(
                        "SELECT EXTRACT(EPOCH FROM NOW() - MAX(created_at))/3600 as hours "
                        "FROM memory_history WHERE user_id = ? AND role = 'user'",
                        (user_id,)
                    ).fetchone()
                else:
                    row2 = db.execute(
                        "SELECT (julianday('now') - julianday(MAX(created_at))) * 24 as hours "
                        "FROM memory_history WHERE user_id = ? AND role = 'user'",
                        (user_id,)
                    ).fetchone()
                hours = float(row2['hours'] or row2[0] or 0) if row2 else 48
                signals['silence'] = min(1.0, max(0.0, hours / 48))  # 48h = max

        except Exception:
            signals = {'chat': 0.5, 'silence': 0.5}

        # 3. Family mentions in recent chats
        learning = db_load_learning(user_id)
        family_mentions = len(learning.get("family_mentions", []))
        signals['family'] = min(1.0, max(0.0, 1 - family_mentions / 10))

        # 4. Activity variety
        interests = learning.get("interests", {})
        active_interests = sum(1 for v in interests.values() if v > 0)
        signals['variety'] = min(1.0, max(0.0, 1 - active_interests / 5))

        # Weighted score
        weights = {'silence': 0.35, 'chat': 0.30, 'family': 0.20, 'variety': 0.15}
        score = sum(signals[k] * weights[k] for k in weights) * 100
        score = min(100, round(score))

        if score < 25:
            level = "low"
            desc = "Dobrá sociální aktivita"
        elif score < 50:
            level = "moderate"
            desc = "Mírné riziko izolace — doporučujeme více sociálních aktivit"
        elif score < 75:
            level = "high"
            desc = "Vysoké riziko izolace — senior potřebuje více kontaktu"
        else:
            level = "critical"
            desc = "Kritická izolace — nutný okamžitý kontakt"

        # Sprint AG.4.5: emit isolation level to bus for chat awareness +
        # caregiver dashboard. Only when level >= high (avoid noise).
        # Dedupe per 6h so repeated calls don't spam.
        try:
            if level in ('high', 'critical'):
                from agent_bus import emit as _bus_emit, dedupe as _bus_dedupe
                topic = 'isolation_high' if level == 'high' else 'isolation_critical'
                if not _bus_dedupe(user_id, sender=None, topic=topic,
                                   within_minutes=360, any_sender=True,
                                   severity_min='warning'):
                    severity = 'alert' if level == 'critical' else 'warning'
                    _bus_emit(
                        user_id=user_id,
                        sender='social_isolation_agent',
                        kind='context',
                        severity=severity,
                        topic=topic,
                        payload={
                            'score': score,
                            'level': level,
                            'signals': signals,
                            'message': desc,
                        },
                        ttl_minutes=360,  # 6h
                    )
        except Exception:
            pass

        return {
            "score": score,
            "level": level,
            "description": desc,
            "signals": signals,
        }


@agents_bp.route('/api/agents/isolation/<user_id>', methods=['GET'])
def isolation_score(user_id):
    return jsonify({'success': True, **SocialIsolationAgent.compute_score(user_id)})


# ═══════════════════════════════════════════════════════════════════
# 🌤️ WEATHER-ADAPTIVE AGENT
# ═══════════════════════════════════════════════════════════════════

class WeatherAgent:
    """Generate weather-based activity suggestions."""

    @staticmethod
    def get_suggestions(temperature=None, conditions=None):
        """Generate suggestions based on weather."""
        # If no weather data, get from HA
        if temperature is None:
            try:
                from home_assistant import ha
                sensors = ha().get_sensors_summary()
                temps = sensors.get('temperature', [])
                if temps:
                    temperature = sum(t['value'] for t in temps) / len(temps)
            except Exception:
                temperature = 20  # default

        suggestions = []
        if temperature is not None:
            if temperature < 5:
                suggestions = [
                    "🏠 Dnes je velká zima. Zůstaňte v teple a udělejte si čaj.",
                    "🧘 Ideální den na cvičení doma — zkuste protahovací cviky.",
                    "📚 Přečtěte si knihu nebo si poslechněte pohádku.",
                    "☕ Zahřejte se teplým nápojem a zavolejte rodině.",
                ]
            elif temperature < 15:
                suggestions = [
                    "🧥 Oblečte se teple, pokud jdete ven.",
                    "🚶 Krátká procházka kolem domu prospěje.",
                    "🍲 Uvařte si teplou polévku.",
                    "🎵 Pusťte si oblíbenou hudbu a protáhněte se.",
                ]
            elif temperature < 25:
                suggestions = [
                    "☀️ Krásné počasí na procházku!",
                    "🌳 Ideální den pro zahradu nebo balkon.",
                    "🚶 30 minut chůze denně je skvělé pro zdraví.",
                    "👥 Pozvěte sousedy na kafe.",
                ]
            else:
                suggestions = [
                    "🌡️ Dnes je horko! Pijte dostatek tekutin.",
                    "💧 Připravte si studený nápoj a zůstaňte v chládku.",
                    "🏠 Zavřete okna přes den a otevřete večer.",
                    "🍉 Jezte hodně ovoce a zeleniny s vodou.",
                ]

        return {
            "temperature": temperature,
            "suggestions": suggestions,
            "generated_at": datetime.utcnow().isoformat()
        }


@agents_bp.route('/api/agents/weather/suggestions', methods=['GET'])
def weather_suggestions():
    temp = request.args.get('temperature', type=float)
    return jsonify({'success': True, **WeatherAgent.get_suggestions(temp)})


# ═══════════════════════════════════════════════════════════════════
# 📊 WEEKLY FAMILY REPORT
# ═══════════════════════════════════════════════════════════════════

class WeeklyReportAgent:
    """Generate weekly summary report for family/caregivers."""

    @staticmethod
    def generate_report(user_id, days=7):
        """Generate comprehensive weekly report."""
        if not _AVAILABLE:
            return {"error": "Dependencies unavailable"}

        profile = db_load_profile(user_id)
        learning = db_load_learning(user_id)
        name = profile.get("name", "Senior")

        report = {
            "user_id": user_id,
            "name": name,
            "period": f"Posledních {days} dní",
            "generated_at": datetime.utcnow().isoformat(),
            "sections": {}
        }

        try:
            with db_context() as db:
                # 1. Interaction stats
                if is_postgres():
                    row = db.execute(
                        "SELECT COUNT(*) as cnt FROM memory_history "
                        "WHERE user_id = ? AND role = 'user' AND created_at > NOW() - INTERVAL '%s days'" % days,
                        (user_id,)
                    ).fetchone()
                else:
                    row = db.execute(
                        "SELECT COUNT(*) as cnt FROM memory_history "
                        "WHERE user_id = ? AND role = 'user' AND created_at > datetime('now', '-%d days')" % days,
                        (user_id,)
                    ).fetchone()
                interactions = row['cnt'] or row[0] or 0

                # 2. Brain state stats
                if is_postgres():
                    brain_rows = db.execute(
                        "SELECT C, mode FROM brain_states "
                        "WHERE user_id = ? AND created_at > NOW() - INTERVAL '%s days' ORDER BY created_at" % days,
                        (user_id,)
                    ).fetchall()
                else:
                    brain_rows = db.execute(
                        "SELECT C, mode FROM brain_states "
                        "WHERE user_id = ? AND created_at > datetime('now', '-%d days') ORDER BY created_at" % days,
                        (user_id,)
                    ).fetchall()

                c_values = [float(r['C'] if isinstance(r, dict) else r[0]) for r in brain_rows if (r.get('C') if isinstance(r, dict) else r[0])]
                modes = [r['mode'] if isinstance(r, dict) else r[1] for r in brain_rows if (r.get('mode') if isinstance(r, dict) else (len(r) > 1 and r[1]))]

                # 3. Agent observations
                if is_postgres():
                    obs_rows = db.execute(
                        "SELECT severity, message, created_at FROM agent_observations "
                        "WHERE user_id = ? AND created_at > NOW() - INTERVAL '%s days' ORDER BY created_at DESC" % days,
                        (user_id,)
                    ).fetchall()
                else:
                    obs_rows = db.execute(
                        "SELECT severity, message, created_at FROM agent_observations "
                        "WHERE user_id = ? AND created_at > datetime('now', '-%d days') ORDER BY created_at DESC" % days,
                        (user_id,)
                    ).fetchall()

        except Exception as e:
            return {"error": str(e)}

        # Build report sections
        report["sections"]["activity"] = {
            "title": "📊 Aktivita",
            "interactions": interactions,
            "daily_average": round(interactions / max(days, 1), 1),
            "assessment": "✅ Aktivní" if interactions > days * 2 else "⚠️ Méně aktivní" if interactions > days else "🔴 Nízká aktivita"
        }

        if c_values:
            avg_c = sum(c_values) / len(c_values)
            max_c = max(c_values)
            report["sections"]["wellbeing"] = {
                "title": "🧠 Pohoda",
                "avg_stress": round(avg_c, 1),
                "max_stress": round(max_c, 1),
                "readings": len(c_values),
                "assessment": "✅ Klidný" if avg_c < 8 else "⚠️ Mírný stres" if avg_c < 15 else "🔴 Vysoký stres",
                "dominant_mode": max(set(modes), key=modes.count) if modes else "HARMONY"
            }

        # Medication compliance
        med_compliance = MedicationTracker.get_compliance(user_id, days)
        report["sections"]["medication"] = {
            "title": "💊 Léky",
            **med_compliance,
            "assessment": "✅ Pravidelně" if (med_compliance.get("compliance_pct") or 0) > 80 else "⚠️ Nepravidelně"
        }

        # Sleep
        sleep_history = SleepAgent.get_sleep_history(user_id, days)
        if sleep_history:
            avg_score = sum(h.get("score", 0) for h in sleep_history) / len(sleep_history)
            report["sections"]["sleep"] = {
                "title": "😴 Spánek",
                "avg_score": round(avg_score),
                "nights_tracked": len(sleep_history),
                "assessment": "✅ Dobrý" if avg_score > 70 else "⚠️ Průměrný" if avg_score > 40 else "🔴 Špatný"
            }

        # Social isolation
        isolation = SocialIsolationAgent.compute_score(user_id)
        report["sections"]["social"] = {
            "title": "🤝 Sociální kontakt",
            "isolation_score": isolation["score"],
            "isolation_level": isolation["level"],
            "assessment": isolation["description"]
        }

        # Alerts
        alerts = []
        for obs in (obs_rows or []):
            sev = obs['severity'] if isinstance(obs, dict) else obs[0]
            msg = obs['message'] if isinstance(obs, dict) else obs[1]
            alerts.append({"severity": sev, "message": msg})

        report["sections"]["alerts"] = {
            "title": "⚠️ Upozornění",
            "count": len(alerts),
            "items": alerts[:10],
            "assessment": "✅ Žádné problémy" if not alerts else f"⚠️ {len(alerts)} upozornění"
        }

        # Prediction
        try:
            from predictive_agent import predict_risk
            prediction = predict_risk(user_id)
            report["sections"]["prediction"] = {
                "title": "🔮 Predikce",
                "risk_score": prediction["risk_score"],
                "risk_level": prediction["risk_level"],
                "prediction": prediction["prediction"],
                "actions": prediction["recommended_actions"][:3]
            }
        except Exception:
            pass

        # Overall summary
        section_assessments = [s.get("assessment", "") for s in report["sections"].values() if isinstance(s, dict)]
        red_count = sum(1 for a in section_assessments if "🔴" in a)
        yellow_count = sum(1 for a in section_assessments if "⚠️" in a)

        if red_count > 0:
            report["overall"] = f"🔴 {name} potřebuje zvýšenou pozornost ({red_count} kritických oblastí)"
        elif yellow_count > 1:
            report["overall"] = f"🟡 {name} je celkově v pořádku, ale {yellow_count} oblasti vyžadují pozornost"
        else:
            report["overall"] = f"🟢 {name} se daří dobře"

        return report


@agents_bp.route('/api/agents/report/<user_id>', methods=['GET'])
def weekly_report(user_id):
    days = int(request.args.get('days', 7))
    report = WeeklyReportAgent.generate_report(user_id, days)
    return jsonify({'success': True, 'report': report})


# ═══════════════════════════════════════════════════════════════════
# 🚨 EMERGENCY PROTOCOL
# ═══════════════════════════════════════════════════════════════════

class EmergencyProtocol:
    """Full automated emergency response."""

    @staticmethod
    def execute(user_id, trigger, app=None):
        """Execute full emergency protocol.

        Steps:
            1. Log crisis event
            2. HA: all lights ON, unlock doors
            3. Call senior (Twilio)
            4. SMS to emergency contacts
            5. Push to caregiver + medical team
            6. Notify family
            7. If no response in 5 min → suggest calling 155
        """
        logger.critical(f"🚨 EMERGENCY PROTOCOL for {user_id}: {trigger}")
        actions_taken = []

        # 1. Log
        audit_log(user_id, "emergency_protocol", "system", f"Trigger: {trigger}")
        actions_taken.append("📝 Crisis logged")

        # 2. HA actions
        try:
            from home_assistant import ha
            client = ha()
            if client.connected:
                devices = client.get_devices_by_type()
                for light in devices.get('light', []):
                    client.light_on(light['entity_id'], brightness=100)
                for lock_dev in devices.get('lock', []):
                    client.unlock(lock_dev['entity_id'])
                actions_taken.append("🏠 All lights ON, doors unlocked")
        except Exception as e:
            logger.warning(f"HA emergency error: {e}")

        # 3. Call senior
        try:
            from agent_loop import _call_senior
            _call_senior(user_id, {"severity": "CRISIS", "message": trigger})
            actions_taken.append("📞 Calling senior")
        except Exception as e:
            logger.warning(f"Call error: {e}")

        # 4. SMS to emergency contacts
        try:
            profile = db_load_profile(user_id)
            contacts = profile.get("emergency_contacts", [])
            name = profile.get("name", "Senior")
            for contact in contacts:
                phone = contact.get("phone")
                if phone:
                    try:
                        from twilio_voice_helpers import send_sms
                        send_sms(phone, f"🚨 KRIZE: {name} potřebuje pomoc! Důvod: {trigger}. Kontaktujte ho/ji prosím.")
                        actions_taken.append(f"📱 SMS to {contact.get('name', phone)}")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"SMS error: {e}")

        # 5. Push + medical team
        try:
            from agent_loop import _push_to_senior, _alert_caregiver, _route_to_medical_team
            obs = {"type": "emergency", "severity": "CRISIS", "message": trigger, "details": {}}
            if app:
                _push_to_senior(user_id, obs, app)
                _alert_caregiver(user_id, obs, app)
            _route_to_medical_team(user_id, obs, app)
            actions_taken.append("🔔 Push + medical team notified")
        except Exception as e:
            logger.warning(f"Push error: {e}")

        result = {
            "user_id": user_id,
            "trigger": trigger,
            "actions_taken": actions_taken,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "executed"
        }

        # Save to learning
        try:
            learning = db_load_learning(user_id)
            emergencies = learning.get("emergency_events", [])
            emergencies.append(result)
            learning["emergency_events"] = emergencies[-10:]
            db_save_learning(user_id, learning)
        except Exception:
            pass

        return result


@agents_bp.route('/api/agents/emergency/<user_id>', methods=['POST'])
def emergency_trigger(user_id):
    """Manually trigger emergency protocol."""
    data = request.get_json(silent=True) or {}
    trigger = data.get('trigger', 'Manual emergency activation')
    # Verify admin or caregiver
    from flask import current_app
    result = EmergencyProtocol.execute(user_id, trigger, current_app._get_current_object())
    return jsonify({'success': True, **result})


# ═══════════════════════════════════════════════════════════════════
# 🧠 LEARNING AGENT — adaptive thresholds
# ═══════════════════════════════════════════════════════════════════

class LearningAgent:
    """Adapts detection thresholds based on user history."""

    @staticmethod
    def update_thresholds(user_id):
        """Recompute personal thresholds from observation history."""
        learning = db_load_learning(user_id)
        observations = learning.get("agent_observations", [])

        # Count false positives (user said "I'm fine" after alert)
        false_positives = learning.get("false_positives", 0)
        true_positives = learning.get("true_positives", 0)

        # Adjust sensitivity
        if false_positives > true_positives * 2:
            # Too many false alarms → reduce sensitivity
            sensitivity = max(0.5, 1.0 - false_positives * 0.05)
        elif true_positives > 3:
            # Good detection → keep or slightly increase
            sensitivity = min(1.5, 1.0 + true_positives * 0.02)
        else:
            sensitivity = 1.0

        # Store
        learning["agent_sensitivity"] = sensitivity
        learning["thresholds_updated"] = datetime.utcnow().isoformat()
        db_save_learning(user_id, learning)

        return {"sensitivity": sensitivity, "false_positives": false_positives, "true_positives": true_positives}

    @staticmethod
    def record_feedback(user_id, observation_type, was_accurate):
        """Record user feedback on agent observation accuracy."""
        learning = db_load_learning(user_id)
        if was_accurate:
            learning["true_positives"] = learning.get("true_positives", 0) + 1
        else:
            learning["false_positives"] = learning.get("false_positives", 0) + 1
        db_save_learning(user_id, learning)
        return LearningAgent.update_thresholds(user_id)


@agents_bp.route('/api/agents/feedback', methods=['POST'])
def agent_feedback():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id', '')
    obs_type = data.get('observation_type', '')
    accurate = data.get('was_accurate', True)
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    result = LearningAgent.record_feedback(user_id, obs_type, accurate)
    return jsonify({'success': True, **result})


@agents_bp.route('/api/agents/thresholds/<user_id>', methods=['GET'])
def agent_thresholds(user_id):
    result = LearningAgent.update_thresholds(user_id)
    return jsonify({'success': True, **result})


# ═══════════════════════════════════════════════════════════════════
# 🌐 BROWSER AGENT — Safe read-only web research tool for other agents
# v10.34 — proxy around browser_agent module so it shows up here
# ═══════════════════════════════════════════════════════════════════

class BrowserAgent:
    """Safe read-only web access for internal AI agents.

    Usage (from radim_orchestrator or any agent):
        result = BrowserAgent.research("Počasí v Praze", user_id="...")
        if result['success']:
            context = result['summary']  # text for AI context injection

    All calls honor ENABLE_BROWSER_AGENT feature flag in browser_agent module.
    Every call is audit-logged to agent_observations.
    """

    @staticmethod
    def open_url(url, user_id=None):
        """Open a URL — thin wrapper around browser_agent.open_page."""
        try:
            from browser_agent import open_page
            return open_page(url, user_id=user_id)
        except ImportError:
            return {'success': False, 'error_code': 'NOT_AVAILABLE',
                    'error': 'Browser agent module not installed'}

    @staticmethod
    def research(url, user_id=None, max_chars=2000):
        """Open URL and return a compact summary suitable for AI context.

        Returns:
            {success, summary, title, url, links_count} or error dict.
        """
        result = BrowserAgent.open_url(url, user_id=user_id)
        if not result.get('success'):
            return result

        main = result.get('main_content', '')
        summary = main[:max_chars]
        if len(main) > max_chars:
            # Cut at sentence boundary if possible
            cut_at = max(summary.rfind('. '), summary.rfind('? '), summary.rfind('! '))
            if cut_at > max_chars // 2:
                summary = summary[:cut_at + 1]
            summary += ' […]'

        return {
            'success': True,
            'title': result.get('title', ''),
            'url': result.get('final_url', result.get('url', '')),
            'summary': summary,
            'links_count': len(result.get('links', [])),
            'session_id': result.get('session_id'),
            'language': result.get('metadata', {}).get('language', 'cs'),
        }

    @staticmethod
    def find(session_id, query):
        try:
            from browser_agent import find_on_page
            return find_on_page(session_id, query)
        except ImportError:
            return {'success': False, 'error_code': 'NOT_AVAILABLE'}

    @staticmethod
    def close(session_id):
        try:
            from browser_agent import close_session
            return close_session(session_id)
        except ImportError:
            return {'success': False, 'error_code': 'NOT_AVAILABLE'}


# ═══════════════════════════════════════════════════════════════════
# 📋 AGENT OVERVIEW ENDPOINT
# ═══════════════════════════════════════════════════════════════════

@agents_bp.route('/api/agents/overview', methods=['GET'])
def agents_overview():
    """List all agents and their status."""
    # Browser agent flag
    try:
        from browser_agent import ENABLE_BROWSER_AGENT
        browser_status = 'active' if ENABLE_BROWSER_AGENT else 'disabled'
    except ImportError:
        browser_status = 'unavailable'

    return jsonify({
        'success': True,
        'agents': [
            {"id": "predictive", "name": "🔮 Prediktivní agent", "status": "active", "endpoint": "/api/predict/risk/<user_id>"},
            {"id": "medication", "name": "💊 Medication Tracker", "status": "active", "endpoint": "/api/agents/medication/compliance/<user_id>"},
            {"id": "sleep", "name": "😴 Sleep Agent", "status": "active", "endpoint": "/api/agents/sleep/<user_id>"},
            {"id": "isolation", "name": "🤝 Social Isolation", "status": "active", "endpoint": "/api/agents/isolation/<user_id>"},
            {"id": "weather", "name": "🌤️ Weather Agent", "status": "active", "endpoint": "/api/agents/weather/suggestions"},
            {"id": "report", "name": "📊 Weekly Report", "status": "active", "endpoint": "/api/agents/report/<user_id>"},
            {"id": "browser", "name": "🌐 Browser Agent", "status": browser_status, "endpoint": "/api/browser/open"},
            {"id": "emergency", "name": "🚨 Emergency Protocol", "status": "active", "endpoint": "/api/agents/emergency/<user_id>"},
            {"id": "learning", "name": "🧠 Learning Agent", "status": "active", "endpoint": "/api/agents/thresholds/<user_id>"},
            {"id": "agent_loop", "name": "🔄 Agent Loop", "status": "active", "endpoint": "/api/admin/agent-run"},
            {"id": "morning_checkin", "name": "🌅 Morning Checkin", "status": "active", "schedule": "daily 8:00"},
            {"id": "daily_cleanup", "name": "🧹 Daily Cleanup", "status": "active", "schedule": "daily 3:00"},
            {"id": "daily_engagement", "name": "💬 Daily Engagement", "status": "active", "schedule": "daily 14:00"},
            {"id": "daily_summary", "name": "📧 Daily Summary", "status": "active", "schedule": "daily 20:00"},
        ],
        'total': 13
    })


logger.info("🤖 Advanced Agents v1.0 loaded — medication, sleep, isolation, weather, report, emergency, learning")
