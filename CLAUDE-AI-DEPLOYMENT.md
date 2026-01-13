# ============================================
# RADIM AI - DEPLOYMENT GUIDE
# Claude API + Web Search Integration
# ============================================

## 🎯 CO SE ZMĚNILO

Nahradili jsme Gemini za Claude API s web search pro:
- ✅ Chat s Radimem
- ✅ Aktuální zprávy (6 kategorií)
- ✅ Počasí (live z webu)
- ✅ Kvízy (generované AI)
- ✅ Příběhy (personalizované)
- ✅ Svátek (český kalendář)

---

## 📁 NOVÉ SOUBORY

### Backend (Heroku)
```
radim-brain-ecosystem/
├── claude_routes.py          # 🆕 Flask blueprint pro Claude AI
├── requirements.txt          # Aktualizovat - přidat anthropic
└── app.py                    # Aktualizovat - registrovat blueprint
```

### Frontend (Azure)
```
radim-frontend/
├── js/RadimAI.js            # 🆕 Centrální AI služba
└── js/news-handler.js       # Aktualizovaný - integrace s RadimAI
```

---

## 🔧 BACKEND DEPLOYMENT (HEROKU)

### 1. Přidat do requirements.txt
```
anthropic>=0.40.0
```

### 2. Přidat do app.py (po ostatních imports)
```python
# Import Claude AI routes
from claude_routes import claude_bp
app.register_blueprint(claude_bp)
```

### 3. Nastavit Environment Variable na Heroku
```bash
heroku config:set ANTHROPIC_API_KEY=sk-ant-xxx... -a radim-brain-2025
```

### 4. Deploy na Heroku
```bash
cd radim-brain-ecosystem
git add -A
git commit -m "🤖 Add Claude AI with Web Search"
git push heroku main
```

---

## 🌐 FRONTEND DEPLOYMENT (AZURE)

### 1. Přidat RadimAI.js do index.html
```html
<!-- Před news-handler.js -->
<script src="js/RadimAI.js?v=20260110"></script>
<script src="js/news-handler.js?v=20260110"></script>
```

### 2. Deploy na Azure
```bash
cd radim-frontend
git add -A
git commit -m "🤖 RadimAI integration"
git push
```

---

## 🔑 API KLÍČE

### Anthropic (Claude)
1. Jdi na https://console.anthropic.com/
2. Vytvoř API key
3. Nastav na Heroku:
```bash
heroku config:set ANTHROPIC_API_KEY=sk-ant-api03-xxx -a radim-brain-2025
```

### Volitelně - Model
```bash
# Pro levnější provoz (Haiku):
heroku config:set CLAUDE_MODEL=claude-haiku-4-5-20251001 -a radim-brain-2025

# Pro lepší kvalitu (Sonnet) - default:
heroku config:set CLAUDE_MODEL=claude-sonnet-4-20250514 -a radim-brain-2025
```

---

## 💰 NÁKLADY

| Model | Input | Output | Web Search |
|-------|-------|--------|------------|
| Haiku 4 | $0.25/1M | $1.25/1M | +$10/1000 |
| Sonnet 4 | $3/1M | $15/1M | +$10/1000 |

**Odhad pro RadimCare:**
- ~100 dotazů/den
- ~$1-3/den s Haiku
- ~$5-10/den se Sonnet

---

## 🧪 TESTOVÁNÍ

### Backend Health Check
```bash
curl https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/radim/health
```

### Test Chat
```bash
curl -X POST https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/radim/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Jaké je dnes počasí v Praze?"}'
```

### Test News
```bash
curl -X POST https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/radim/news \
  -H "Content-Type: application/json" \
  -d '{"category": "sports", "count": 3}'
```

---

## 📋 CHECKLIST

### Backend
- [ ] Přidat `anthropic` do requirements.txt
- [ ] Přidat `claude_routes.py` do projektu
- [ ] Importovat a registrovat blueprint v `app.py`
- [ ] Nastavit `ANTHROPIC_API_KEY` na Heroku
- [ ] Deploy na Heroku
- [ ] Ověřit /api/radim/health endpoint

### Frontend
- [ ] Přidat `RadimAI.js` do js/
- [ ] Aktualizovat `news-handler.js`
- [ ] Přidat script tagy do index.html
- [ ] Deploy na Azure
- [ ] Vyčistit cache (Cmd+Shift+R)
- [ ] Ověřit zprávy, počasí, svátek

---

## 🚀 QUICK START COMMANDS

```bash
# Backend
cd /Users/kolibric/Desktop/Kolibri-Hotel-Master/radim-brain-ecosystem
echo "anthropic>=0.40.0" >> requirements.txt
git add -A
git commit -m "🤖 Claude AI integration"
git push heroku main

# Frontend
cd /Users/kolibric/Desktop/Kolibri-Hotel-Master/radim-frontend
git add -A
git commit -m "🤖 RadimAI service"
git push
```

---

## ❓ FAQ

**Q: Mohu úplně vypnout Gemini?**
A: Ano, Claude API s web search pokrývá všechny funkce. Gemini můžete nechat jako fallback nebo úplně odstranit.

**Q: Co když Claude API selže?**
A: RadimAI.js a news-handler.js mají lokální fallback data - zprávy, počasí, svátek se zobrazí i bez AI.

**Q: Jak změnit model?**
A: `heroku config:set CLAUDE_MODEL=claude-haiku-4-5-20251001 -a radim-brain-2025`

---

Vytvořeno: 2026-01-10
Autor: Claude + Michal (Kolibri Team)
