# TTS Architecture — Unified Voice Pipeline

**Status:** Production, unified 2026-04-24 (after full-stack audit)
**Single source of truth for all Radim speech across the app.**

---

## ⚠️ For future devs + AI agents

**READ THIS FIRST** before adding any code that produces audio output.

Every text that becomes sound in the RadimCare app must go through **one** pipeline. Do not:

- ❌ Call `speechSynthesis.speak()` directly
- ❌ Call `new Audio('/api/azure/tts')` directly
- ❌ Invent new voice modes or emotions
- ❌ Define local mapping of mode → voice params
- ❌ Bypass master switch / channel controls

The architecture is designed so that when a senior toggles **"Hlas Radima"** off in Konverzace, every single module goes silent — no escape hatches.

---

## Frontend

### Single entry point: `window.radimVoice.say(text, opts)`

```js
await window.radimVoice.say('Dobré ráno, jak se máte?', {
    source:   'chat',        // 'chat'|'greeting'|'reading'|'crisis'|'call'|'notification'|'quiz'|'news'|'story'
    priority: 'reply',       // 'crisis'|'call'|'reply'|'reading'|'ambient'
    mode:     'HARMONY',     // 'HARMONY'|'FESTIVE'|'NARRATION'|'ALERT'|'CRISIS'
    interrupt: false,        // true = stop current + play this
    replace:  true,          // same-source replaces pending (default)
});
```

**Returns** a `Promise` that resolves when playback ends (or immediately if muted/skipped).

### Other helpers

```js
window.radimVoice.stop();               // stop everything
window.radimVoice.stopSource('reading'); // stop only one source
window.radimVoice.setEnabled(false);     // MASTER switch — kills app-wide
window.radimVoice.setChannel('chat', false); // disable one channel
window.radimVoice.isSpeaking();          // bool
window.radimVoice.diagnose();            // dev health check
```

### What happens under the hood

```
radimVoice.say(text, opts)
    │
    ├── Master switch check → drop if off
    ├── Channel check → drop if channel disabled
    ├── Source dedup → cancel prev same-source
    │
    ▼
SpeechOrchestrator.enqueue(text, { mode, priority, userId, context })
    │
    ├── Priority queue insert
    ├── FSM transition: IDLE → FETCHING → PLAYING → ENDED
    │
    ▼
POST /api/azure/tts  {text, voice, rate, pitch, emotion, C, alpha, mode, user_id}
    │
    ▼
Azure Cognitive Services TTS (cs-CZ-AntoninNeural)
    │
    ▼
Audio <blob> → TtsCache → <audio> element → speaker
```

### Shim for legacy `window.speak()`

Old modules still use `window.speak(text, opts)`. A shim in `RadimVoice.js` **hijacks** `window.speak` and routes through the policy layer. The shim is **locked via Object.defineProperty** so nothing can override it later.

Source is inferred from `opts.context` / `opts.mode`:

| context / mode | inferred source |
|---|---|
| `chat`, `chatroom` | `chat` |
| `festive`, mode `FESTIVE` | `greeting` |
| `narration`, mode `NARRATION` | `reading` |
| `education`, `quiz` | `quiz` |
| `news` | `news` |
| mode `CRISIS` | `crisis` |
| mode `ALERT` | `notification` |
| (anything else) | `notification` |

### Bypass blockers (in RadimVoice.js)

```js
// 1. speechSynthesis.speak() intercept
window.speechSynthesis.speak = (u) => radimVoice.say(u.text, {...});

// 2. new Audio('/api/.../tts') warning
window.Audio = HijackedAudio;  // logs warning, respects master mute

// 3. window.speak() LOCKED (non-writable, non-configurable)
Object.defineProperty(window, 'speak', { value: speakFn, writable: false });
```

If you see console warnings like `[RadimVoice] intercepted speechSynthesis.speak → policy`, someone is using a bypass path. **Fix that call site** — don't suppress the warning.

### Current consumers (who speaks)

| Module | Call pattern | Status |
|---|---|---|
| `chat-module.js` (Konverzace) | `radimVoice.say(reply, {source:'chat', priority:'reply'})` | ✅ compliant |
| `communication-module.js` (Komunikace) | `window.speak(...)` → shim → policy | ✅ via shim |
| `stories-module.js` | `window.speak(chunk)` → shim → policy | ✅ via shim |
| `quiz-module.js` | `window.speak(q)` → shim → policy | ✅ via shim |
| `medical-module.js` | `window.speak(alert)` → shim → policy | ✅ via shim |
| `translator-module.js` | was `speechSynthesis.speak` direct | ⚠️ hijacked by blocker |
| `experience-module.js` | mixed | ⚠️ hijacked by blocker |
| `help-module.js` | mixed | ⚠️ hijacked by blocker |
| All other 25+ modules | `window.speak(...)` | ✅ via shim |

---

## Backend

### Single mapping module: `voice_mapping.py`

**Every** backend file that triggers TTS must use this:

```python
from voice_mapping import resolve_voice_params, normalize_mode

params = resolve_voice_params(
    mode='HARMONY',          # or any alias: 'harmony', 'friendly', 'calm'
    user_id='abc',
    age=78,                   # extra slowdown for 75+
    anticipation={'C': 8},    # brain-state-aware rate adjustment
)
# → {voice, rate, pitch, style, styledegree, mode}
```

**Do NOT** define local `voice_mode → emotion` mappings. If you need a new mode, add it to `VOICE_MODES` in `voice_mapping.py`.

### Canonical modes (5 only)

| Mode | Style | Rate | Pitch | When |
|---|---|---|---|---|
| `HARMONY` | friendly (1.2) | 0.85 | -3% | Normal chat (default) |
| `FESTIVE` | cheerful (1.5) | 0.88 | 0% | Greetings, holidays |
| `NARRATION` | narration-professional (1.0) | 0.80 | -2% | Stories, quiz |
| `ALERT` | empathetic (1.4) | 0.78 | -5% | Check-ins, health concerns |
| `CRISIS` | serious (1.8) | 0.72 | -8% | Emergency, falls, SOS |

### Backend endpoints

| Endpoint | Purpose | Auth | Notes |
|---|---|---|---|
| `POST /api/azure/tts` | Main TTS proxy (frontend audio) | public | Called by SpeechOrchestrator |
| `POST /api/speech/synthesize` | REST API synonym | public | Legacy / third-party integrations |
| `POST /api/speech/synthesize/stream` | Chunked stream | public | Rare usage |
| `GET /api/speech/azure-token` | Azure client token | public | For frontend Azure SDK (STT) |
| `GET /api/twilio/tts` | Twilio call audio | Twilio-signed | Phone calls via IVR |
| `POST /api/elevenlabs/tts` | Fallback voice | public | Unused; kept for future |

### Triggers that produce audio

| Trigger | File | Function | Output |
|---|---|---|---|
| Chat reply | `radim_orchestrator.py` | `radim_chat()` | Client streams via Orchestrator |
| Morning check-in | `agent_loop.py` | `initiate_proactive_call()` | Twilio call |
| Crisis escalation | `agent_loop.py` | `initiate_proactive_call(reason='crisis')` | Twilio call (priority) |
| Anticipation-driven | `anticipation_routes.py` | via agent loop | Twilio call |
| Incoming IVR | `twilio_voice_routes.py` | `twiml_say()` | IVR response |

All of the above → `voice_mapping.resolve_voice_params()` → same SSML builder in `twilio_voice_helpers.py` / `speech_helpers.py`.

---

## Agent layer

### AI agents (Python) that speak

Agents use the same pipeline as regular backend calls:

```python
from voice_mapping import resolve_voice_params
from twilio_voice_helpers import initiate_proactive_call

params = resolve_voice_params('ALERT', user_id=senior_id)
result = initiate_proactive_call(
    phone_number=phone,
    greeting=text,
    user_id=senior_id,
    reason='health_alert',
    voice_mode='ALERT',   # canonical — mapped inside
)
```

### Agent triggers inventory

| Agent | File | Triggers TTS via |
|---|---|---|
| `agent_loop` (5-min cron) | `agent_loop.py` | `initiate_proactive_call()` when observation severity ≥ ALERT |
| `morning_checkin` (8 AM cron) | `agent_loop.py` | Twilio call + push |
| `anticipation` | `anticipation_routes.py` | Feeds `{C, alpha, mode}` into `resolve_voice_params` for brain-aware rate |
| `orchestrator` | `radim_orchestrator.py` | Returns `voice_mode` in JSON, frontend plays via `radimVoice.say` |
| `brain_speech` | `brain_speech.py` | RTCF state → voice_mode recommendation |

---

## Troubleshooting

### "My module doesn't speak"

1. Check `window.radimVoice.isEnabled()` — master switch
2. Check `window.radimVoice.getChannel('chat')` — channel for your source
3. Run `window.radimVoice.diagnose()` in console:
   ```js
   {
     version: '2.0',
     masterEnabled: true,
     currentSource: null,
     pendingSources: [],
     speechOrchestrator: true,
     speakLocked: true,
     speechSynthesisHijacked: true,
     audioHijacked: true,
     channels: { chat: true, reading: true, ... }
   }
   ```
4. Check network tab: `/api/azure/tts` responds 200?
5. Check `azure-token` endpoint works: `curl https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/speech/azure-token`

### "Multiple voices playing simultaneously"

This should be impossible after the 2026-04-24 unification. If it happens:

1. Check `diagnose()` — is `speakLocked: true`? If false, the shim failed to install
2. Check for direct `Audio(...)` elements in DOM
3. Check for `<audio autoplay>` tags in HTML
4. File a bug with `diagnose()` output

### "TTS has no Czech diacritics"

Browser's native `speechSynthesis` probably took over (lang=en-US default). This means Azure/orchestrator failed and fell through to emergency fallback. Check:

1. `SENTRY_DSN` for recent errors
2. Azure Speech Service key is valid (Heroku `AZURE_SPEECH_KEY`)
3. Rate limit: `/api/azure/tts` has per-IP limit

### Adding a new voice mode

1. Add to `VOICE_MODES` in `voice_mapping.py` with style/rate/pitch
2. (Optional) Add alias to `_ALIASES` for back-compat variants
3. If frontend-visible: add to RadimVoice `SOURCE_DEFAULTS` if new source, or pass `mode` param
4. Document here with "when to use" guidance
5. **Do not** define the mapping anywhere else

---

## Version history

| Date | Change |
|---|---|
| 2026-04-24 | TTS Unification — 3 bypass blockers + voice_mapping.py + this doc |
| 2026-04-23 | Sprint T — RadimVoice singleton introduced |
| 2026-04-23 | Sprint M — voice notes + audio bubble |
| (earlier) | Azure TTS + SpeechOrchestrator established |
