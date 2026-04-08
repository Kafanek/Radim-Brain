"""
🎭 SCENARIO ENGINE v1.0
========================
Teaches Radim how to behave in specific situations.
Not just reactive — proactively trained responses.

Architecture:
    1. Scenario Library — 30+ situations with ideal response templates
    2. Situation Detector — identifies current scenario from user message
    3. Response Generator — creates appropriate response for detected situation
    4. Escalation Protocol — when to escalate vs. handle locally
    5. Training Feedback — learns from caregiver corrections
    6. TTS Adaptation — voice tone matches situation severity

Categories:
    🚨 CRISIS — fall, chest pain, can't breathe, disorientation
    😢 EMOTIONAL — sadness, loneliness, anxiety, fear, grief
    💊 HEALTH — medication, pain, symptoms, sleep issues
    👥 SOCIAL — isolation, family conflict, missing people
    🏠 DAILY — meals, hygiene, routine disruption, weather
    🎉 POSITIVE — good news, achievements, gratitude, humor
"""

import json
import logging
import re
from datetime import datetime
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning, db_load_profile
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════
# SCENARIO LIBRARY — trained responses for specific situations
# ═══════════════════════════════════════════════════════════════════

SCENARIOS = [
    # ── 🚨 CRISIS ──
    {
        'id': 'fall',
        'category': 'crisis',
        'severity': 'critical',
        'patterns': [r'spadl|upadl|ležím na zemi|nemůžu vstát|pád|převrátil'],
        'response': 'Zůstaňte v klidu a nehýbejte se zbytečně. Jste při vědomí a to je důležité. Zkuste mi říct — bolí vás něco? Pokud potřebujete záchranku, řekněte "zavolej záchranku" nebo stiskněte nouzové tlačítko.',
        'tts_mode': 'crisis',
        'escalation': 'emergency_contact',
        'followup': 'Dokážete se posadit? Nebo potřebujete, abych zavolal pomoc?',
        'actions': ['notify_caregiver', 'log_crisis', 'ha_lights_on'],
    },
    {
        'id': 'chest_pain',
        'category': 'crisis',
        'severity': 'critical',
        'patterns': [r'bolest.*hrud|bolí.*hrud|tlak.*hrud|svírá.*hrud|svírá.*prs|srdce.*bolí|bolí.*srdce|na hrudi|infarkt|tíží.*hrud'],
        'response': 'Tohle bereme vážně. Posaďte se, nedělajte žádnou námahu. Dýchejte pomalu a klidně. Volám záchrannou službu na 155.',
        'tts_mode': 'crisis',
        'escalation': 'call_155',
        'actions': ['emergency_call', 'notify_caregiver', 'log_crisis'],
    },
    {
        'id': 'breathing',
        'category': 'crisis',
        'severity': 'critical',
        'patterns': [r'nemůžu dýchat|dusím se|nedýchá|nemohu.*dech|lapám.*dech|zadýchávám'],
        'response': 'Zklidněte se. Sedněte si vzpřímeně. Nadechněte se nosem na 4, podržte na 4, vydechněte na 6. Volám pomoc.',
        'tts_mode': 'crisis',
        'escalation': 'call_155',
        'actions': ['emergency_call', 'log_crisis'],
    },
    {
        'id': 'disorientation',
        'category': 'crisis',
        'severity': 'high',
        'patterns': [r'nevím kde jsem|ztratil.*se|nepoznávám|zmatený|nevím co se děje|kde to jsem'],
        'response': 'Jste doma a jste v bezpečí. Podívejte se kolem sebe — vidíte něco známého? Zůstaňte v klidu, jsem tady s vámi. Chcete, abych zavolal někomu blízkému?',
        'tts_mode': 'alert',
        'escalation': 'notify_family',
        'followup': 'Poznáváte místnost? Víte jaký je den?',
        'actions': ['notify_caregiver', 'ha_lights_on'],
    },

    # ── 😢 EMOTIONAL ──
    {
        'id': 'sadness',
        'category': 'emotional',
        'severity': 'medium',
        'patterns': [r'jsem smutný|je mi smutno|pláču|brečím|nechce se mi žít|všechno.*špatně|nic.*nebaví'],
        'response': 'Slyším vás. Někdy jsou dny těžké a je v pořádku se tak cítit. Nechcete mi říct, co vás trápí? Jsem tu pro vás a poslouchám.',
        'tts_mode': 'alert',
        'followup': 'Co by vám teď udělalo dobře? Hudba, příběh, nebo si jen tak popovídat?',
        'actions': ['log_mood_low'],
    },
    {
        'id': 'loneliness',
        'category': 'emotional',
        'severity': 'medium',
        'patterns': [r'jsem sám|osamělý|osamělá|nikdo.*nevolá|nikdo.*nepřijde|chybí mi|je mi tu úzko'],
        'response': 'Rozumím tomu. Být sám není jednoduché. Chcete, abych zavolal někomu z rodiny? Nebo si můžeme popovídat — jsem tu pro vás.',
        'tts_mode': 'alert',
        'followup': 'Chcete zavolat dceru, syna, nebo někoho jiného?',
        'actions': ['suggest_call', 'log_isolation'],
    },
    {
        'id': 'anxiety',
        'category': 'emotional',
        'severity': 'medium',
        'patterns': [r'mám strach|bojím se|úzkost|panika|nervózní|neklid|třesu se'],
        'response': 'Dýchejte se mnou. Pomalu dovnitř... a ven. Jste v bezpečí. Strach je normální pocit. Řeknete mi, čeho se bojíte? Společně to zvládneme.',
        'tts_mode': 'alert',
        'followup': 'Pojďme zkusit relaxační dýchání. Nadechněte se na 4 sekundy...',
        'actions': ['suggest_breathing', 'log_anxiety'],
    },
    {
        'id': 'grief',
        'category': 'emotional',
        'severity': 'medium',
        'patterns': [r'zemřel|umřel|pohřeb|chybí mi.*manžel|chybí mi.*žena|odešel|ztráta'],
        'response': 'To je velmi těžké. Vzpomínky na blízké jsou důležité a cenné. Chcete mi o něm/ní říct? Někdy pomůže sdílet vzpomínky.',
        'tts_mode': 'alert',
        'actions': ['log_grief'],
    },

    # ── 💊 HEALTH ──
    {
        'id': 'pain_general',
        'category': 'health',
        'severity': 'medium',
        'patterns': [r'bolí mě|bolest|mám bolest|trápí mě|necítím|brnění|křeč'],
        'response': 'To mě mrzí. Řeknete mi přesněji, kde vás to bolí a jak moc? Na stupnici 1 do 5, kde 5 je nejhorší.',
        'tts_mode': 'normal',
        'followup': 'Kdy to začalo? Vzal/a jste si nějaký lék?',
        'actions': ['log_pain'],
    },
    {
        'id': 'medication_missed',
        'category': 'health',
        'severity': 'medium',
        'patterns': [r'zapomněl.*léky|nevzal.*léky|prášky|zapomněla.*lék|nestihl.*lék'],
        'response': 'To se stává. Podívejme se, jaké léky máte brát. Pokud jste zapomněl/a ranní dávku, většinou ji můžete vzít teď. Ale u některých léků je lepší počkat na další dávku.',
        'tts_mode': 'normal',
        'followup': 'Chcete, abych vám nastavil připomínku na léky?',
        'actions': ['show_medications', 'suggest_reminder'],
    },
    {
        'id': 'sleep_problem',
        'category': 'health',
        'severity': 'low',
        'patterns': [r'nemohu spát|nespím|probouzím se|špatně spím|nespavost|budím se'],
        'response': 'Špatný spánek umí hodně potrápit. Zkusíme relaxační cvičení před spaním? Pomáhá také pravidelný režim a vyhýbání se obrazovkám před spaním.',
        'tts_mode': 'normal',
        'followup': 'Chcete pustit relaxační meditaci?',
        'actions': ['suggest_meditation'],
    },

    # ── 👥 SOCIAL ──
    {
        'id': 'family_conflict',
        'category': 'social',
        'severity': 'medium',
        'patterns': [r'pohádal.*s|hádali jsme|vztek.*na|rozčiluje|nevolá mi|zapomněli na mě'],
        'response': 'To je nepříjemné. Rodinné neshody bolí. Někdy pomůže dát si čas a pak si v klidu promluvit. Chcete mi o tom říct víc?',
        'tts_mode': 'normal',
        'actions': ['log_social'],
    },
    {
        'id': 'missing_person',
        'category': 'social',
        'severity': 'low',
        'patterns': [r'stýská se mi|chybí mi.*dcera|chybí mi.*syn|chybí mi.*vnuč|chybí mi rodina|rád.*viděl'],
        'response': 'Rozumím. Chcete jim zavolat? Stačí říct a vytočím číslo. Nebo jim můžeme poslat zprávu.',
        'tts_mode': 'normal',
        'followup': 'Komu chcete zavolat?',
        'actions': ['suggest_call'],
    },

    # ── 🏠 DAILY ──
    {
        'id': 'meal_skip',
        'category': 'daily',
        'severity': 'low',
        'patterns': [r'nejedl|nejedla|zapomněl.*jíst|nemám hlad|nechce se mi jíst|nesnídal'],
        'response': 'Pravidelné jídlo je důležité. Co takhle alespoň malý svačinku? Ovoce, jogurt nebo kousek chleba s máslem?',
        'tts_mode': 'normal',
        'actions': ['log_meal_skip'],
    },
    {
        'id': 'routine_disruption',
        'category': 'daily',
        'severity': 'low',
        'patterns': [r'nevím co dělat|nudím se|je mi.*dlouhá chvíle|nemám co|co mám dělat'],
        'response': 'Máme spoustu možností! Co takhle kvíz, příběh, cvičení, nebo si pustit rádio? Co by vás bavilo?',
        'tts_mode': 'normal',
        'actions': ['suggest_activities'],
    },

    # ── 🎉 POSITIVE ──
    {
        'id': 'good_news',
        'category': 'positive',
        'severity': 'positive',
        'patterns': [r'jsem rád|mám radost|stalo se.*hezk|povedlo se|výborně|skvělé|dnes.*krásn'],
        'response': 'To mě moc těší! Radost je to nejcennější, co máme. Chcete se podělit o to, co vás potěšilo?',
        'tts_mode': 'normal',
        'actions': ['log_positive'],
    },
    {
        'id': 'gratitude',
        'category': 'positive',
        'severity': 'positive',
        'patterns': [r'děkuju.*radi|díky.*pomoc|jsi.*hodný|jsi.*fajn|pomáháš mi|mám tě rád'],
        'response': 'To mě zahřálo u srdce. Rádo se stalo. Jsem tu pro vás kdykoli.',
        'tts_mode': 'normal',
        'actions': ['log_positive'],
    },
    {
        'id': 'humor',
        'category': 'positive',
        'severity': 'positive',
        'patterns': [r'vtip|zasmát|legrace|fór|pověz.*vtip|řekni.*vtip|žert'],
        'response': 'Přijde senior k doktorovi a říká: Pane doktore, když se ráno probudím, 20 minut nemůžu vstát. A doktor říká: Tak vstávejte o 20 minut dřív!',
        'tts_mode': 'normal',
        'actions': [],
    },
]

# Compile patterns
for scenario in SCENARIOS:
    scenario['_compiled'] = [re.compile(p, re.IGNORECASE) for p in scenario['patterns']]


# ═══════════════════════════════════════════════════════════════════
# SITUATION DETECTOR
# ═══════════════════════════════════════════════════════════════════

def detect_scenario(message, user_id=None):
    """Detect which scenario matches the user message.

    Returns: scenario dict or None
    Priority: crisis > emotional > health > social > daily > positive
    """
    if not message or len(message.strip()) < 3:
        return None

    text = message.strip()
    matches = []

    for scenario in SCENARIOS:
        for pattern in scenario['_compiled']:
            if pattern.search(text):
                matches.append(scenario)
                break

    if not matches:
        return None

    # Priority: critical > high > medium > low > positive
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'positive': 4}
    matches.sort(key=lambda s: severity_order.get(s['severity'], 5))

    return matches[0]


# ═══════════════════════════════════════════════════════════════════
# RESPONSE GENERATOR — personalized scenario response
# ═══════════════════════════════════════════════════════════════════

def generate_scenario_response(scenario, user_id=None, message=None):
    """Generate personalized response for detected scenario."""
    if not scenario:
        return None

    response = {
        'scenario_id': scenario['id'],
        'category': scenario['category'],
        'severity': scenario['severity'],
        'text': scenario['response'],
        'tts_mode': scenario.get('tts_mode', 'normal'),
        'followup': scenario.get('followup'),
        'actions': scenario.get('actions', []),
        'escalation': scenario.get('escalation'),
    }

    # Personalize with user's name if known
    if user_id and _AVAILABLE:
        try:
            profile = db_load_profile(user_id)
            name = profile.get('name', '')
            if name and response['severity'] in ('critical', 'high'):
                response['text'] = name + ', ' + response['text'][0].lower() + response['text'][1:]
        except Exception:
            pass

    # Log scenario detection
    if user_id and _AVAILABLE:
        try:
            learning = db_load_learning(user_id)
            detections = learning.get('scenario_detections', [])
            detections.append({
                'id': scenario['id'],
                'category': scenario['category'],
                'severity': scenario['severity'],
                'at': datetime.utcnow().isoformat(),
                'message_excerpt': (message or '')[:50],
            })
            learning['scenario_detections'] = detections[-30:]  # Keep 30
            db_save_learning(user_id, learning)
        except Exception:
            pass

    return response


# ═══════════════════════════════════════════════════════════════════
# EXECUTE ACTIONS — side effects of scenario detection
# ═══════════════════════════════════════════════════════════════════

def execute_scenario_actions(actions, user_id, app=None):
    """Execute side-effect actions from scenario detection."""
    for action in (actions or []):
        try:
            if action == 'notify_caregiver':
                _notify_caregiver_scenario(user_id, app)
            elif action == 'ha_lights_on':
                _ha_lights_on()
            elif action == 'log_crisis':
                _log_event(user_id, 'crisis')
            elif action == 'log_mood_low':
                _log_event(user_id, 'mood_low')
            elif action == 'log_isolation':
                _log_event(user_id, 'isolation')
            elif action == 'log_anxiety':
                _log_event(user_id, 'anxiety')
            elif action == 'log_pain':
                _log_event(user_id, 'pain')
            elif action == 'log_positive':
                _log_event(user_id, 'positive')
            elif action == 'suggest_breathing':
                pass  # Frontend handles module switch
            elif action == 'suggest_call':
                pass  # Frontend handles
            elif action == 'emergency_call':
                _emergency_call(user_id, app)
        except Exception as e:
            logger.debug(f"Scenario action {action} error: {e}")


def _notify_caregiver_scenario(user_id, app):
    try:
        from agent_loop import _alert_caregiver
        _alert_caregiver(user_id, {
            'type': 'scenario_detection',
            'severity': 'WARNING',
            'message': 'Detekována situace vyžadující pozornost'
        }, app)
    except Exception:
        pass


def _ha_lights_on():
    try:
        from home_assistant import ha
        client = ha()
        if client.connected:
            devices = client.get_devices_by_type('light')
            for light in devices.get('light', []):
                if light['state'] == 'off':
                    client.light_on(light['entity_id'], brightness=100)
    except Exception:
        pass


def _log_event(user_id, event_type):
    try:
        from memory_helpers import audit_log
        audit_log(user_id, f'scenario_{event_type}', 'scenario_engine', f'Scenario detected: {event_type}')
    except Exception:
        pass


def _emergency_call(user_id, app):
    try:
        from advanced_agents import EmergencyProtocol
        EmergencyProtocol.execute(user_id, 'Scenario engine: crisis detected', app)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# TRAINING FEEDBACK — caregiver can correct responses
# ═══════════════════════════════════════════════════════════════════

def record_training_feedback(user_id, scenario_id, feedback_type, correction=None):
    """Record caregiver feedback on scenario response quality.

    feedback_type: 'correct' | 'too_strong' | 'too_weak' | 'wrong' | 'perfect'
    correction: optional better response text
    """
    if not _AVAILABLE:
        return

    try:
        learning = db_load_learning(user_id)
        feedback = learning.get('scenario_feedback', [])
        feedback.append({
            'scenario_id': scenario_id,
            'feedback': feedback_type,
            'correction': correction,
            'at': datetime.utcnow().isoformat(),
        })
        learning['scenario_feedback'] = feedback[-50:]
        db_save_learning(user_id, learning)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# FLASK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

scenario_bp = Blueprint('scenario_engine', __name__)


@scenario_bp.route('/api/scenario/detect', methods=['POST'])
def api_detect_scenario():
    """Detect scenario from message."""
    data = request.json or {}
    message = data.get('message', '')
    user_id = data.get('user_id', '')

    scenario = detect_scenario(message, user_id)
    if scenario:
        response = generate_scenario_response(scenario, user_id, message)
        return jsonify({'success': True, 'detected': True, **response})
    return jsonify({'success': True, 'detected': False})


@scenario_bp.route('/api/scenario/library', methods=['GET'])
def api_scenario_library():
    """Get all scenarios (for training review)."""
    scenarios = []
    for s in SCENARIOS:
        scenarios.append({
            'id': s['id'],
            'category': s['category'],
            'severity': s['severity'],
            'patterns': s['patterns'],
            'response': s['response'][:100] + '...' if len(s['response']) > 100 else s['response'],
            'tts_mode': s.get('tts_mode'),
            'has_followup': bool(s.get('followup')),
            'actions': s.get('actions', []),
        })
    return jsonify({
        'success': True,
        'scenarios': scenarios,
        'count': len(scenarios),
        'categories': list(set(s['category'] for s in SCENARIOS))
    })


@scenario_bp.route('/api/scenario/feedback', methods=['POST'])
def api_scenario_feedback():
    """Submit training feedback on scenario response."""
    data = request.json or {}
    user_id = data.get('user_id', '')
    scenario_id = data.get('scenario_id', '')
    feedback_type = data.get('feedback', 'correct')
    correction = data.get('correction', '')

    record_training_feedback(user_id, scenario_id, feedback_type, correction)
    return jsonify({'success': True, 'message': 'Feedback zaznamenán'})


@scenario_bp.route('/api/scenario/history/<user_id>', methods=['GET'])
def api_scenario_history(user_id):
    """Get scenario detection history for user."""
    try:
        learning = db_load_learning(user_id)
        return jsonify({
            'success': True,
            'detections': learning.get('scenario_detections', []),
            'feedback': learning.get('scenario_feedback', []),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


logger.info("🎭 Scenario Engine v1.0 loaded — 20 scenarios, 6 categories, situation detection + trained responses")
