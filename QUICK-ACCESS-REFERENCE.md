# 🔐 QUICK ACCESS REFERENCE

**Datum:** 31.12.2025  
**Status:** ✅ Vše funguje (backend na Heroku)

---

## 🤖 CLAUDE DESKTOP CONFIG

**Config file:**

```bash
~/Library/Application Support/Claude/claude_desktop_config.json
```

**MCP Server pro Radim Brain:**

```json
{
  "mcpServers": {
    "radim-brain-2025": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-fetch",
        "https://radim-brain-2025-be1cd52b04dc.herokuapp.com"
      ]
    }
  }
}
```

**Dokumentace:** `CLAUDE-DESKTOP-MCP-CONFIG.md`

---

## 🌐 HEROKU (Backend)

**App:** `radim-brain-2025`  
**URL:** https://radim-brain-2025-be1cd52b04dc.herokuapp.com  
**Git Remote:** heroku

**Commands:**

```bash
# Logs
heroku logs --tail -a radim-brain-2025

# Restart
heroku restart -a radim-brain-2025

# Config vars
heroku config -a radim-brain-2025

# Deploy
git push heroku heroku-deploy-fix:main --force
```

---

## ☁️ AZURE

**App:** `radim-app`  
**URL:** https://radim-app-b6d5bjgxakake0fa.scm.westeurope-01.azurewebsites.net  
**Git Remote:** azure

---

## 🗂️ GIT REMOTES

```bash
# Heroku
heroku: https://git.heroku.com/radim-brain-2025.git

# Azure
azure: radim-app-b6d5bjgxakake0fa.scm.westeurope-01.azurewebsites.net

# GitHub (Windsurf)
windsurf: https://github.com/Kafanek/windsurf-connector.git
```

---

## ⚠️ DEPLOYMENT STATUS

### ✅ CO FUNGUJE

- Backend běží na Heroku (v60)
- RADIM Conscious TTS aktivní
- Azure TTS + ElevenLabs proxy
- Antonín mluví česky

### ❌ CO NEFUNGUJE

- **Local backend** (Python 3.13 + SQLAlchemy konflikt)
- **Řešení:** Používej Heroku backend

### 🔧 AKTUÁLNÍ STAV

**Branch:** `heroku-deploy-fix`  
**Uncommitted changes:** markdown lints, __pycache__

**Frontend:** http://localhost:8080 (běží)  
**Backend:** Heroku (běží)

---

## 🚀 RYCHLÝ START

```bash
# 1. Frontend
cd /Users/kolibric/Desktop/Kolibri\ app./mykolibri-academy-project
python3 -m http.server 8080

# 2. Test Antonína
open http://localhost:8080/radim-simple.html

# 3. Deploy na Heroku (pokud změny)
git add .
git commit -m "feat: popis"
git push heroku heroku-deploy-fix:main --force
```

---

## 📚 DŮLEŽITÉ DOKUMENTY

- `CLAUDE-DESKTOP-MCP-CONFIG.md` - Claude Desktop setup
- `HEROKU-DEPLOYMENT-SUCCESS-2025-12-16.md` - Deployment info
- `RADIM-BRAIN-API-REFERENCE.md` - API endpoints
- `ANTONIN-VOICE-COMPLETE-REFERENCE.md` - Voice system

---

**Poslední update:** 31.12.2025 18:47
