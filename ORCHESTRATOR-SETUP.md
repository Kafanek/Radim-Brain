# 🎭 Radim Orchestrator - Setup Guide

## Co bylo vytvořeno

### 1. Backend: `routers/orchestrator_routes.py`
FastAPI router s endpointy:
- `POST /api/orchestrator/orchestrate` – hlavní orchestrační endpoint
- `GET /api/orchestrator/health` – health check orchestrátoru
- `GET /api/orchestrator/systems` – přehled všech systémů

**Akce orchestrátoru:**
| Akce | Popis |
|------|-------|
| `health_all` | Paralelní kontrola všech systémů |
| `analyze` | AI analýza stavu (Gemini) |
| `monitor` | Real-time monitoring metrik |
| `chat` | Orchestrovaný chat přes agenty |
| `fix` | Diagnóza + návrh opravy |
| `logs` | Heroku logy |

### 2. MCP Server: `mcp-server/src/index.ts` (v2.0)
14 nástrojů pro Claude Desktop:
- 🎭 `orchestrate`, `check_health`, `get_systems_status`
- 🧠 `get_consciousness_state`
- 🤖 `get_agent_health`, `get_agent_capabilities`
- 💬 `radim_chat`, `radim_smart_chat`
- 👴 `radim_list_seniors`, `radim_get_senior`, `radim_get_vitals`
- 🏠 `radim_iot_status`
- 🚨 `radim_predict_crisis`

---

## Setup kroky

### Krok 1: Build MCP serveru
```bash
cd ~/Desktop/Kolibri-Hotel-Master/radim-brain-ecosystem/mcp-server
npm install
npm run build
```

### Krok 2: Přidej do Claude Desktop configu
Otevři `~/Library/Application Support/Claude/claude_desktop_config.json` a přidej:

```json
{
  "mcpServers": {
    "radim-orchestrator": {
      "command": "node",
      "args": [
        "/Users/kolibric/Desktop/Kolibri-Hotel-Master/radim-brain-ecosystem/mcp-server/build/index.js"
      ],
      "env": {
        "RADIM_BRAIN_URL": "https://radim-brain-2025-be1cd52b04dc.herokuapp.com"
      }
    }
  }
}
```

### Krok 3: Restart Claude Desktop
Zavři a znovu otevři Claude Desktop.

### Krok 4: Deploy orchestrator_routes.py na Heroku
```bash
cd ~/Desktop/Kolibri-Hotel-Master/radim-brain-ecosystem
git add routers/orchestrator_routes.py routers/__init__.py
git commit -m "feat: add orchestrator routes v2.0"
git push heroku main
```

**POZOR:** `main.py` importuje mnoho modulů z `api/` a `routers/` které lokálně neexistují.
Pokud deploy padne, bude potřeba buď:
- a) Stáhnout kompletní kód z Heroku (`heroku git:clone`)
- b) Nebo přidat orchestrator_routes.py přímo přes Heroku CLI

---

## Testování

Po setup:
```
Claude Desktop → "Orchestrate health_all"
Claude Desktop → "Zkontroluj stav Radim Brain"
Claude Desktop → "Chat s Radimem: Jak se máš?"
```

---

## Architektura

```
┌─────────────────────────────────────────────┐
│            CLAUDE DESKTOP (AI)               │
│                                              │
│  orchestrate → check_health → analyze → fix  │
└──────────────────┬──────────────────────────┘
                   │ MCP Protocol (stdio)
┌──────────────────▼──────────────────────────┐
│         RADIM ORCHESTRATOR MCP v2.0          │
│         (Node.js, 14 tools)                  │
└──────────────────┬──────────────────────────┘
                   │ HTTP/REST
┌──────────────────▼──────────────────────────┐
│         HEROKU BACKEND (FastAPI)             │
│                                              │
│  ┌─────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Agents  │ │Conscious-│ │ Orchestrator │  │
│  │ Rodina  │ │  ness    │ │   Routes     │  │
│  │Kafánků  │ │ Engine   │ │   (NEW!)     │  │
│  └─────────┘ └──────────┘ └──────────────┘  │
│  ┌─────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  IoT    │ │  Voice   │ │   Radim      │  │
│  │ Sensors │ │  TTS     │ │   Chat       │  │
│  └─────────┘ └──────────┘ └──────────────┘  │
└─────────────────────────────────────────────┘
```
