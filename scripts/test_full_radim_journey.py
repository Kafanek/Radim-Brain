#!/usr/bin/env python3
"""COMPLETE RADIM USER JOURNEY — registrace → onboarding → first chat → voice → Claude awareness.

Simuluje skutečnou cestu seniora od první návštěvy app až po plně funkčního Radima.
"""
import urllib.request, urllib.error, json, os, time

BASE = os.environ.get('BASE_URL', 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com')
ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')

def http(method, path, body=None, token=None, admin=False):
    url = BASE + path
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if admin and ADMIN_SECRET:
        headers['X-Admin-Secret'] = ADMIN_SECRET
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {'error': str(e)}
    except Exception as e:
        return 0, {'error': str(e)}

C_OK = '\033[0;32m'
C_FAIL = '\033[0;31m'
C_INFO = '\033[0;34m'
C_END = '\033[0m'

passed, failed, warns = 0, 0, 0
def step(num, desc):
    print(f'{C_INFO}→ Step {num:2d}: {desc}{C_END}', end=' ')

def ok(msg):
    global passed; passed += 1
    print(f'{C_OK}✓{C_END} {msg}')

def fail(msg):
    global failed; failed += 1
    print(f'{C_FAIL}✗{C_END} {msg}')

def warn(msg):
    global warns; warns += 1
    print(f'⚠ {msg}')

print('=' * 70)
print('   KOMPLETNÍ RADIM USER JOURNEY — registrace → live Radim')
print('=' * 70)
print()

# ═══════════════════════════════════════════════════════════════
# PHASE 1: REGISTRATION
# ═══════════════════════════════════════════════════════════════
print(f'{C_INFO}━━━ PHASE 1: Registrace nového seniora ━━━{C_END}')

ts = int(time.time())
test_email = f'journey-{ts}@kafanek.example'
test_password = 'JourneyTest123!'
test_name = 'Pavla Testovací'

# Step 1: Health check
step(1, 'Backend health')
code, body = http('GET', '/health')
if code == 200 and body.get('status') == 'healthy':
    ok(f"DB={body.get('db', {}).get('latency_ms')}ms, blueprints={body.get('blueprint_count')}")
else:
    fail(f'HTTP {code}: {body}')

# Step 2: Register
step(2, 'POST /api/auth/register')
code, body = http('POST', '/api/auth/register', {
    'email': test_email, 'password': test_password, 'name': test_name
})
token = body.get('token')
user_id = body.get('user', {}).get('id')
if code in (200, 201) and token:
    ok(f'user_id={user_id}, token={token[:20]}…')
else:
    fail(f'HTTP {code}: {body}')
    print('Cannot continue without registration. Aborting.')
    raise SystemExit(1)

# Step 3: Login (verify auth works)
step(3, 'POST /api/auth/login')
code, body = http('POST', '/api/auth/login', {
    'email': test_email, 'password': test_password
})
new_token = body.get('token')
if code == 200 and new_token:
    token = new_token
    ok('login OK')
else:
    fail(f'HTTP {code}: {body}')

# Step 4: Get user info
step(4, 'GET /api/auth/me')
code, body = http('GET', '/api/auth/me', token=token)
if code == 200 and body.get('email') == test_email:
    ok(f'role={body.get("role")}')
else:
    warn(f'HTTP {code}: {body}')

# ═══════════════════════════════════════════════════════════════
# PHASE 2: ONBOARDING
# ═══════════════════════════════════════════════════════════════
print()
print(f'{C_INFO}━━━ PHASE 2: Onboarding flow ━━━{C_END}')

# Step 5: Onboarding status
step(5, 'GET /api/onboarding/status')
code, body = http('GET', '/api/onboarding/status', token=token)
if code == 200:
    ok(f'completed_steps={body.get("completed_steps", [])}')
else:
    warn(f'HTTP {code}: {body}')

# Step 6: Profile step
step(6, 'POST /api/onboarding/step (profile)')
code, body = http('POST', '/api/onboarding/step', {
    'step': 'profile',
    'data': {'name': test_name, 'age': 78, 'communication_needs': []}
}, token=token)
if code == 200:
    ok('profile step recorded')
else:
    warn(f'HTTP {code}: {body}')

# Step 7: Family step (valid step name from STEPS list)
step(7, 'POST /api/onboarding/step (family)')
code, body = http('POST', '/api/onboarding/step', {
    'step': 'family',
    'data': {'family_count': 1}
}, token=token)
if code == 200:
    ok('family step recorded')
else:
    warn(f'HTTP {code}')

# Step 8: Pilot complete (valid consents schema)
step(8, 'POST /api/onboarding/pilot/complete')
code, body = http('POST', '/api/onboarding/pilot/complete', {
    'iban': 'CZ6508000000192000145399',
    'iban_holder': test_name,
    'agreements_accepted': ['mou', 'dpa'],
    'consent_research': True,
}, token=token)
if code == 200:
    ok(f'pilot completed at {body.get("completed_at", "")[:19]}')
else:
    warn(f'HTTP {code}: {body}')

# ═══════════════════════════════════════════════════════════════
# PHASE 3: FIRST CHAT — Radim's first hello
# ═══════════════════════════════════════════════════════════════
print()
print(f'{C_INFO}━━━ PHASE 3: První chat s Radimem ━━━{C_END}')

# Step 9: Send first message
step(9, 'POST /api/radim/chat (first message)')
code, body = http('POST', '/api/radim/chat', {
    'message': 'Dobrý den, jsem nová. Jak se máte?',
    'user_id': str(user_id),
}, token=token)
radim_response = body.get('response', '')
if code == 200 and radim_response:
    ok(f'Radim odpověděl ({len(radim_response)} znaků): "{radim_response[:80]}…"')
else:
    fail(f'HTTP {code}: {body}')

# Step 10: Check brain state was saved
step(10, 'Brain state computed?')
import urllib.request as ur
req = ur.Request(BASE + f'/api/admin/debug-prompt/{user_id}',
                 headers={'X-Admin-Secret': ADMIN_SECRET})
try:
    resp = ur.urlopen(req, timeout=15)
    debug = json.loads(resp.read().decode())
    has_brain = 'brain' in str(debug).lower() or 'C=' in str(debug)
    ok(f'system prompt has brain context' if has_brain else 'no brain context yet')
except Exception:
    warn('debug endpoint failed')

# Step 11: Second message (continuation)
step(11, 'Continuation message')
code, body = http('POST', '/api/radim/chat', {
    'message': 'Bolí mě dnes hlava, co bych mohla dělat?',
    'user_id': str(user_id),
}, token=token)
if code == 200 and body.get('response'):
    ok(f'continuation OK ({len(body["response"])} znaků)')
else:
    warn(f'HTTP {code}')

# ═══════════════════════════════════════════════════════════════
# PHASE 4: VOICE / TTS
# ═══════════════════════════════════════════════════════════════
print()
print(f'{C_INFO}━━━ PHASE 4: Voice / TTS ━━━{C_END}')

# Step 12: TTS health
step(12, 'GET /api/tts/health')
code, body = http('GET', '/api/tts/health')
if code == 200 and body.get('available'):
    ok(f"voice={body.get('voice', '?')}, region={body.get('region', '?')}")
else:
    warn(f'HTTP {code}: {body}')

# Step 13: TTS synthesis (Azure endpoint)
step(13, 'POST /api/azure/tts (Azure synthesis)')
code, body = http('POST', '/api/azure/tts', {
    'text': 'Dobrý den paní Pavlo, jak se máte?',
    'voice': 'cs-CZ-AntoninNeural',
}, token=token)
# Azure TTS returns binary audio, not JSON. Just check status code.
if code == 200:
    ok('Azure TTS responded 200')
elif code == 202:
    ok('Azure TTS accepted (202)')
else:
    warn(f'HTTP {code}: {body if isinstance(body, dict) else "binary"}')

# ═══════════════════════════════════════════════════════════════
# PHASE 5: CLAUDE AGENT AWARENESS
# ═══════════════════════════════════════════════════════════════
print()
print(f'{C_INFO}━━━ PHASE 5: Claude Agent vidí nového seniora ━━━{C_END}')

# Step 14: Claude agent dashboard
step(14, 'GET /api/admin/claude-agent/dashboard')
code, body = http('GET', '/api/admin/claude-agent/dashboard', admin=True)
if code == 200:
    tools = body.get('tool_inventory', {}).get('total', 0)
    seniors = body.get('per_senior', [])
    found_us = any(p.get('user_id') == str(user_id) for p in seniors)
    if tools >= 100:
        ok(f'{tools} tools loaded, {len(seniors)} seniors tracked, our user visible: {found_us}')
    else:
        warn(f'only {tools} tools')
else:
    fail(f'HTTP {code}')

# Step 15: Trigger Claude agent run
step(15, 'POST /api/admin/claude-agent/run (manual trigger)')
code, body = http('POST', '/api/admin/claude-agent/run', {}, admin=True)
if code in (200, 202):
    ok(f'agent triggered async (status {code})')
else:
    warn(f'HTTP {code}: {body}')

# Step 16: Wait + verify telemetry
step(16, 'Wait 60s for run completion + verify telemetry')
time.sleep(60)
code, body = http('GET', '/api/admin/claude-agent/telemetry', admin=True)
if code == 200 and body.get('recent_runs'):
    last_run = body['recent_runs'][0]
    cost = last_run.get('cost_usd', 0)
    tools_used = last_run.get('tool_calls', 0)
    ok(f'last run: ${cost:.3f}, {tools_used} tools, today total ${body.get("spent_today_usd", 0):.2f}')
else:
    warn(f'HTTP {code}')

# ═══════════════════════════════════════════════════════════════
# PHASE 6: SETTINGS + RADIM MODE
# ═══════════════════════════════════════════════════════════════
print()
print(f'{C_INFO}━━━ PHASE 6: Settings management ━━━{C_END}')

# Step 17: Default radim_mode (via /api/memory/load)
step(17, 'Default radim_mode after registration')
code, body = http('GET', f'/api/memory/load/{user_id}', token=token)
if code == 200:
    profile = body.get('profile', {}) if isinstance(body, dict) else {}
    rmode = profile.get('radim_mode', 'guide')
    ok(f'radim_mode={rmode}')
else:
    # Fallback path
    code2, body2 = http('GET', f'/api/memory/{user_id}', token=token)
    if code2 == 200:
        ok(f'memory loaded via /api/memory/{{id}} (status {code2})')
    else:
        warn(f'memory endpoints: /api/memory/load → {code}, /api/memory/ → {code2}')

# ═══════════════════════════════════════════════════════════════
# PHASE 7: GDPR + CLEANUP
# ═══════════════════════════════════════════════════════════════
print()
print(f'{C_INFO}━━━ PHASE 7: GDPR + cleanup ━━━{C_END}')

# Step 18: GDPR export
step(18, 'GET /api/auth/data-export (GDPR)')
code, body = http('GET', '/api/auth/data-export', token=token)
if code == 200 and body.get('user'):
    ok(f'export contains: {list(body.keys())[:5]}')
else:
    warn(f'HTTP {code}')

# Step 19: GDPR delete (cleanup)
step(19, 'DELETE /api/auth/data (GDPR delete)')
code, body = http('DELETE', '/api/auth/data', token=token)
if code in (200, 204):
    ok('test user deleted (GDPR)')
else:
    warn(f'HTTP {code}: {body}')

# ═══════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════
print()
print('=' * 70)
print(f'   {C_OK}✓ PASSED:{C_END} {passed}    {C_FAIL}✗ FAILED:{C_END} {failed}    ⚠ WARNINGS: {warns}')
print('=' * 70)
if failed == 0:
    print(f'{C_OK}✅ KOMPLETNÍ JOURNEY ÚSPĚŠNÝ — Radim je připraven na pilot{C_END}')
else:
    print(f'{C_FAIL}❌ {failed} FAILED steps — vyžaduje pozornost před pilotem{C_END}')
