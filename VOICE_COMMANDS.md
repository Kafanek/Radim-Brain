# Radim — Hlasové příkazy (v8.19.36)

## v8.19.36 STT-UNIFY — jednotná pipeline

Před touto verzí existovaly **2 paralelní STT pipeline**:
- `index.html:3518-3640` — inline 130 řádků s 6 GATES (aktivní)
- `VoiceGateway.js listen()` — 5 GATES + delegace (mrtvý kód, nikdo nevolal)

Po v8.19.36: **JEDNA cesta** přes `VoiceGateway.listen(onChat)` — index.html
je tenký wrapper (~50 řádků) s callback `_sttOnChat` který deleguje na
`kalService.chat`. VoiceGateway má všechny gates (HARD floor 0.45,
confirmation 0.45–0.70, min length 3, media noise, echo, sleep, command).

```
🎤 Mikrofon
   ↓ UnifiedVoiceManager.startListening(callback)
   ↓ {text, confidence, isFinal}
VoiceGateway.listen(onChat) — single STT pipeline
   ├── G0: min_text_length (3)
   ├── G1: HARD reject (conf < 0.45)
   ├── G1b: confirm request (0.45–0.70)
   ├── G2: rate limit (2s)
   ├── G3: echo protection (speechGate)
   ├── G3b: media noise (music/TV playing)
   ├── sleep_mode (only wake word passes)
   ├── handleSleepCommand
   ├── G4: processVoiceInput (LOCAL — no AI cost)
   └── G5: debounce → onChat(text)
              ↓
            _sttOnChat in index.html
              ↓ kalService.chat(text)
              ↓ /api/radim/chat
              ↓ orchestrator (Sprint 1-5 stack)
              ↓ Claude/Gemini → response
              ↓ window.speak (Azure TTS)
```

## /api/radim/chat callsites — 8 míst, všechny legit

Backend orchestrator je single source of truth. Frontend plural = různé UX:

| Callsite | Účel |
|---|---|
| `RadimSimpleChat.sendMessage` | Hlavní chat UI bubliny |
| `KalService.chat` | STT → AI pipeline (volá `_sttOnChat`) |
| `chat-module.js _call` | Legacy chat module (sekce) |
| `radim-core.js sendQuickChat` | Quick-input z home page (deleguje na RadimSimpleChat) |
| `radim-core.js searchInternet` | Search feature (zvláštní query) |
| `DailyInfoService` | Background daily briefing cron |
| `RadimOfflineStore` | Replay queued messages po offline |
| `RadimMessengerV3` | Deleguje na RadimSimpleChat |

Všechny → backend orchestrator → jednotný memory + identity stack.



Demo dokumentace pro prof. Nováka (ČVUT) + senior testing.

## Architektura — jak to teče

```
🎤 Mikrofon (cs-CZ continuous)
   ↓ Web Speech API
UnifiedVoiceManager.js — průběžný transcript
   ↓
WakeWordManager.js — detekce „Radime" (Levenshtein fuzzy)
   ↓ stripnutý dotaz
STT GATES (1–5) v index.html — confidence + media + speaking guards
   ↓ GATE 5
window.processVoiceInput(text)  ← JEDEN dispatcher (radim-core.js)
   │
   ├── 1. Wake word probuzení ze sleep mode
   ├── 2. Sleep příkazy (delegace na WakeWordManager.handleSleepCommand)
   ├── 3. Navigation: „otevři X / jdi na Y"
   ├── 4. Direct module name: „kvízy / zprávy"
   ├── 5. Calls: „zavolej dceři / zavěs"
   ├── 6. Action regex (30+ patterns) — média, recepty, web search, HA…
   ├── 7. window.radimVoiceCommands array (modul-registered handlers)
   └── 8. Fallback → KAL Service /api/radim/chat (AI)
```

## Jediná pravda: `window.processVoiceInput`

Před v8.19.35 existovaly **3 paralelní voice systémy** — jen jeden fungoval:
- ❌ `RadimVoiceCommands.js` (1041 řádků dead code) — class se nikdy neinstancovala. **Smazána.**
- ❌ `window.radimVoiceCommands` array — 8 modulů do něj `.push()` ale array nebyl inicializován → silent fail. **Opraveno.**
- ✅ `processVoiceInput()` v radim-core.js — jediný funkční dispatcher.

Od v8.19.35: `processVoiceInput()` čte i `window.radimVoiceCommands` array (sekce 7) → moduly mají single source of truth.

## Příkazy které fungují (live testovatelné)

### 🎵 Hudba & Rádio
| Příkaz | Co se stane |
|---|---|
| „Radime, zapni rádio Blaník" | HA media_player → Blaník na speaker; fallback: lokální audio |
| „Pusť rádio Impuls" | Stejně, stanice Impuls |
| „Pusť Vltavu / klasiku / jazz" | ČRo Vltava |
| „Pusť Radiožurnál / žurnál" | ČRo Radiožurnál |
| „Pusť relax / přírodu / meditaci" | Ambient stream (Drone Zone) |
| „Hlasitěji / tišeji" | Volume up/down |
| „Vypni rádio / zastav hudbu / ticho" | Stop |

### 📰 Zprávy (NEW v8.19.35: readDigest)
| Příkaz | Co se stane |
|---|---|
| „Přečti mi zprávy / co je nového / novinky" | Otevře news modul + nahlas přečte top-3 titulky + nabídne detail |
| „Přečti první / druhou / třetí" | Přečte detail vybraného článku |
| „Aktuality" | Otevře news modul |

### 🍰 Recepty (NEW v8.19.35)
| Příkaz | Co se stane |
|---|---|
| „Najdi mi recept na cheesecake" | Otevře internet modul + DuckDuckGo search „recept na cheesecake česky" |
| „Najdi mi recept na svíčkovou" | Stejně |
| „Hledám recept na bublaninu" | Stejně |

### 🔍 Web search (NEW v8.19.35)
| Příkaz | Co se stane |
|---|---|
| „Vyhledej mi Karlův most" | Otevře internet modul + search |
| „Co je to entropie" | Stejně |
| „Kdo je Karel Čapek" | Stejně |

### 📞 Volání
| Příkaz | Co se stane |
|---|---|
| „Zavolej dceři / synovi / Marii" | callsModule.startCall + speak „Volám…" |
| „Zavěs / ukonči hovor" | callsModule.endCall |
| „Zvedni to" | Přijme příchozí hovor |

### 🏠 Home Assistant
| Příkaz | Co se stane |
|---|---|
| „Zapni světlo (v kuchyni)" | HA light.turn_on (filtr na room) |
| „Zhasni / vypni světlo" | HA light.turn_off |
| „Jaká je teplota" | HA získá teplotu z sensor.temperature |
| „Zamkni / odemkni" | HA lock/unlock |
| „Nastav topení na 22 stupňů" | HA climate.set_temperature |

### 💊 Léky
| Příkaz | Co se stane |
|---|---|
| „Vzal jsem léky / beru léky" | _confirmMedication() — eviduje |
| „Jaké mám léky / moje léky" | _readMedications() přečte seznam |

### 🧠 Aktivity
| Příkaz | Co se stane |
|---|---|
| „Zahraj kvíz / trénink paměti" | Otevře quiz modul + spustí memory quiz |
| „Spusť cvičení / rozcvičku" | Otevře exercises modul |
| „Vyprávěj příběh / pusť pohádku" | Otevře stories + generuje |
| „Přečti báseň / recituj" | Otevře library |

### 💭 Identita Radima (Sprints 1-5)
| Příkaz | Co se stane |
|---|---|
| „Kdo jsi / představ se / jsi robot" | Autentická odpověď ze seed identity (rotující šablona) |
| „Co máš rád / co tě baví / pověz o sobě" | Konkrétní položka ze seed |
| „Máš rád podzim / klavír / knihy" | Subject matching → najde v LOVES |
| TTS prosody | Pomalejší (rate 0.92) + 'gentle' style pro intimnější tón |

### 💤 Vypnutí (sleep)
| Příkaz | Co se stane |
|---|---|
| „Spi / usni / dost / dobrou noc" | WakeWordManager.goToSleep() — ztichne, čeká na „Radime" |
| „Buď ticho / ticho / přestaň" | Stop speaking |
| „Stop" (když Radim mluví) | Barge-in stop |

### 🔄 Systém
| Příkaz | Co se stane |
|---|---|
| „Mluv pomaleji / rychleji" | Rate −0.1 / +0.1 |
| „Opakuj / zopakuj / cože" | Replay last response |
| „Otevři nastavení" | showModule('settings') |

## Modul-specifické voice handlery (registrované přes array)

Po v8.19.35 tyto **konečně fungují** (bylo dead code):

| Modul | Voice handler |
|---|---|
| smart-home | `smartHomeModule.handleVoiceCommand(text)` |
| gallery | foto-related commands |
| learning | „začni kurz X" |
| library | „přečti knihu X" |
| internet | search + navigate |
| experience | „nová vzpomínka" |
| caregiver | dashboard commands |
| relationship | family commands |
| news | „přečti první/druhou/třetí" |

## Ovládání tlačítkové (pro prof. Nováka — non-voice users)

Vše dostupné i bez hlasu:
- **Domů**: 6 hlavních kartiček (rodina, dnes, mood, quick-chat, akce, Radim doporučuje)
- **Sidebar**: 12 modulů + Více (35+)
- **Sticky nav** v Nastavení: 8 sekcí (Přístupnost, Oznámení, Profil, Radim, Hlas, Vzhled, Soukromí, O aplikaci)
- **Floating mini-player** při hudbě
- **SOS top-bar** (kdykoliv viditelné, 🆘 Nouze 155)

## Test checklist (pro Heroku v884+)

Pošlete tyto na živé `/api/radim/chat` jako POST `{message, user_id, mode: 'senior'}`:

```bash
# 1. RÁDIO
curl -X POST $PROXY/api/radim/chat -H "Content-Type: application/json" \
  -d '{"message":"Zapni rádio Blaník","user_id":"test1","mode":"senior"}'
# Očekávaný response (HA nedostupné): "__RADIO_FALLBACK__|blanik|<url>|Zapínám Blaník."
# intent: ha_radio_play

# 2. ZPRÁVY
curl -X POST $PROXY/api/radim/chat -H "Content-Type: application/json" \
  -d '{"message":"Co je nového","user_id":"test1","mode":"senior"}'
# Očekávaný: passthrough (intent: chat) — frontend voice patterns chytí na klientu

# 3. RECEPT — frontend-only (processVoiceInput pattern)

# 4. SLEEP
curl -X POST $PROXY/api/radim/chat -H "Content-Type: application/json" \
  -d '{"message":"Dobrou noc","user_id":"test1","mode":"senior"}'
# intent: goodbye

# 5. IDENTITA
curl -X POST $PROXY/api/radim/chat -H "Content-Type: application/json" \
  -d '{"message":"Co máš rád","user_id":"existing-user","mode":"senior"}'
# intent: identity, voice_intimate: true
```

## Co zbývá (post-MVP)

- **HA setup wizard** v Nastavení — průvodce „kde jsou vaše světla, jaký máte speaker"
- **Recipe ukládání** — „uložím tento recept" → user_recipes tabulka
- **News kategorie hlasově** — „zprávy ze sportu / politiky"
- **Multi-room HA media** — „pusť rádio v kuchyni" (room-aware)
- **Voice diagnostika** — admin endpoint co ukáže poslední 20 STT příkazů + jak byly zpracovány
