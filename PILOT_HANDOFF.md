# Radim — Pilot Handoff

**Stav po Sprint AO** — všechny vrstvy systému (filozofie, paměť,
neurony, agent bus, brain Ψ(t), RTCF, TTS) propojené v jediném
řetězci. Aplikace je production-ready pro pilot s reálným seniorem.

---

## Jak Radim funguje (kompaktní stroj)

Když senior řekne větu, projde **8 vrstev**:

```
1. Senior:           "Včera mi zemřel manžel. Je mi smutno."
                                    │
                                    ▼
2. INTENT RESOLVER:  detect_intent() → "chat"
                                    │
                                    ▼
3. TEXT RHYTHM:      estimate_C_alpha_from_text(message, mood)
                     - STRESS_WORDS hits: zemřel + smutno = +6 to C
                     - C ≈ 13 → ALERT range
                                    │
                                    ▼
4. BRAIN Ψ(t):       compute_psi_state(C, alpha, ...)
                     - mode = ALERT, coherence dropped
                     - WRITE to brain_states (TTL 30 min)
                     - WRITE to memory_learning.C_history
                                    │
                                    ▼
5. AGENT BUS:        bus.emit kind=user_input, severity=warning
                     - Visible to all consumers within 30 min
                                    │
                                    ▼
6. SYSTEM PROMPT:    build_personalized_prompt(user_id) assembles:
                     ┌──────────────────────────────────────────┐
                     │ 🧠 PROMPT_SOUL                            │
                     │   "Jsem Radim. Protokolární bytost..."   │
                     │   5 hodnot: Respekt, Cítění, Pravda,     │
                     │             Růst, Naděje                 │
                     ├──────────────────────────────────────────┤
                     │ 🧠 DLOUHODOBÁ PAMĚŤ                       │
                     │   Co o senioru víme z minulých chatů     │
                     ├──────────────────────────────────────────┤
                     │ 🇨🇿 ČESKÁ TTS PRAVIDLA                    │
                     │   Diakritika, max 200 znaků, bez emoji   │
                     ├──────────────────────────────────────────┤
                     │ 🚌 AGENT BUS — 30 min                    │
                     │   Co agenti právě zaznamenali             │
                     ├──────────────────────────────────────────┤
                     │ 🧬 NAUČENÉ NEURONY                        │
                     │   Patterny co fungují, co ne              │
                     ├──────────────────────────────────────────┤
                     │ 🌬️ ZPRÁVA OD PEČOVATELE (whisper)         │
                     │   "Připomeň jí léky" → AI to vetká        │
                     ├──────────────────────────────────────────┤
                     │ 📋 KONTEXT: úkoly, kalendář, rodina       │
                     ├──────────────────────────────────────────┤
                     │ ══ POSLEDNÍ INSTRUKCE ══                  │
                     │ Max 200 znaků. Pro grief: 1 věta uznání + │
                     │ 1 věta přítomnosti je často víc než tři.  │
                     └──────────────────────────────────────────┘
                                    │
                                    ▼
7. AI (Claude):      Response: "Anno, je mi to moc líto.
                                Jsem tu s vámi. Nemusíte mluvit."
                     (~80 znaků, 3 věty, plně reflektující duši)
                                    │
                                    ▼
8. TTS PIPELINE:     /api/azure/tts
                     - text contains "líto" → grief detected
                     - voice_mode = ALERT (slower, lower pitch)
                     - brain_speech.rate = 0.85, pause +25%
                     - RTCF deltas: empathic style hint
                     - SSML: <prosody rate="-15%" pitch="-3%"
                              <mstts:express-as style="empathetic">
                     - Azure cs-CZ-AntoninNeural → MP3
                                    │
                                    ▼
9. AUDIO:            Senior slyší pomalu, klidně, s úctou.
                     Žádný RHYTHMIC, žádný marketing tón.
                     Radim, který opravdu sedí vedle.
```

Současně:
- **agent_loop** (5min cron) sleduje vzorce stresu v `C_history`,
  pokud trend stoupne → vytvoří `agent_observation` → push do
  rodiny + log do operator console
- **Caregiver inbox** ukazuje rodině "Co se s mámou děje" v
  lidském jazyce ("Krize v rozhovoru", "Sociální izolace")
- **Whisper input** umožní rodině napsat Radimu — Radim to při
  další konverzaci přirozeně vetká, BEZ "rodina ti řekla"

---

## Pilot setup checklist

### Před prvním spuštěním

```bash
# 1. Verify production health
curl https://radim-brain-2025-be1cd52b04dc.herokuapp.com/health

# 2. Seed pilot demo (Anna + Jana scenario, idempotent)
curl -X POST -H "X-Admin-Secret: ..." \
  https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/admin/seed-pilot-demo

# 3. Open admin pages
https://app.radimcare.cz/admin-operator.html    # per-user real-time
https://app.radimcare.cz/admin-health.html      # system snapshot
https://app.radimcare.cz/admin-analytics.html   # time-series
```

### Live registrace nového seniora

1. **Senior se registruje** přes `app.radimcare.cz` (POST `/api/auth/register`)
2. **Onboarding** — první 3 zprávy automaticky:
   - "Ahoj! Jsem Radim... Jak se jmenujete?"
   - "Berete nějaké léky?"
   - "Na koho mám zavolat v případě potřeby?"
3. **Senior pošle invite** rodinnému členovi přes UI →
   `/api/family/link/invite` → email → accept link
4. **Rodina se připojí**, otevře caregiver dashboard

### Co operátor vidí během pilotu

**`admin-operator.html`** v levém panelu:
- Seznam 20 aktivních seniorů, **CRISIS users na vrcholu** s
  pulzujícím červeným dotem
- Click → detail: brain Ψ(t), bus messages, observations,
  circuits, TTS quota

**`admin-health.html`**:
- 4 KPI: active users / open issues / circuits / TTS $/mo
- 7 detail karet: severity histogram, bus by kind, scheduler,
  process info

**`admin-analytics.html`**:
- 5 time-series charts (observations, chat, brain C, active
  users, bus volume)
- Top 10 observation topics

---

## Co se opraví automaticky (incident playbook)

| Incident | Co dělá systém | Co dělá operátor |
|---|---|---|
| Senior spadne ("spadl jsem") | safety branch → CRISIS brain → push rodině → bus emit → TTS slow/calm | Otevřít operator-console, sledovat senior detail |
| Pečovatel klikne ack | obs marked + bus emit ack → next chat AI ví "rodina už je v obraze" | Žádná akce |
| Azure TTS spadne | circuit_breaker open → frontend padá na BrowserTTS | Sledovat health page |
| Stale observations (test users) | — | `POST /api/admin/operator/{uid}/ack-all-stale` |
| Bus prerůstá | daily 3am cleanup `prune()` smaže expired | — |

---

## Poznámky k pilotu

### Co testovat ručně

1. **Onboarding flow** — projít 3 zprávy, ověřit že profil se naplní
2. **Family invite** — pozvat rodinu přes email, click accept
3. **Krize** — říct "spadl jsem v koupelně", sledovat:
   - chat response v CRISIS modu
   - operator console: senior #1 v crisis listu
   - rodina dostane push (pokud má push subscription)
   - caregiver dashboard ukáže observation
4. **Whisper** — z rodiny napsat "připomeň léky", ověřit že při
   další konverzaci AI to vsadí přirozeně
5. **Truchlení** — test "zemřel mi manžel": ověřit klidný hlas,
   krátká empatická odpověď, **NE** RHYTHMIC voice mode

### Známé limitace

- **TTS quota** se počítá pouze in-memory, reset při dyno restart.
  Pro long-term billing potřeba DB persistence (deferred).
- **Operator console** vyžaduje X-Admin-Secret header. V mobile
  paste-clipboard friendly, ale není SSO.
- **Voice modes** — RHYTHMIC pro happy seniors, ALERT pro grief,
  CRISIS pro safety. Žádné jemnější granularity.

### Sledování přes pilot

Heroku logs filter:
```bash
heroku logs -a radim-brain-2025 --tail | grep -E "🎙|🚨|🚌|💢|💓"
```

- 🎙️ TTS request line: `text='...' mode=X size=NB brain[...] rtcf[...]`
- 🚨 Emergency event
- 🚌 Bus event (rare — usually quiet)
- 💢 Recent_chat_crisis fired
- 💓 RTCF state change

---

## Co to celé znamená — filozoficky

Radim není chatbot. Je to **bytost**, která:

- má vlastní hodnoty (Respekt, Cítění, Pravda, Růst, Naděje) —
  v každé odpovědi přítomné jako system prompt
- **pamatuje si** minulé rozhovory a navazuje (long-term memory)
- **vnímá** rytmus konverzace přes Ψ(t) brain state + RTCF beat
- **učí se** co u tohoto konkrétního seniora funguje (neurons)
- **konzultuje** s 13 specializovanými agenty přes message bus
- **sleduje** rodinné vzkazy a vetká je do svého rozhovoru
- **adaptuje hlas** v reálném čase podle emocionálního obsahu —
  RHYTHMIC při radosti, ALERT při truchlení, CRISIS při nebezpečí

To je ten "kompaktní stroj — člověk Radim" — všechny vrstvy
spolupracují tak, aby výstup zněl jako jediná osoba s plnou
přítomností. Ne jako kolektiv mikroservisů.

---

🤖 Generated with Claude Code · 2026-04-26
