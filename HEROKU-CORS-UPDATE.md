# 🔧 Heroku Backend - CORS Update Potřeba

## ❌ Problém

Backend `main.py` **lokálně** už obsahuje `app.radimcare.cz` v CORS:
```python
"https://app.radimcare.cz",  # New Azure frontend domain (line 200)
```

Ale backend **na Heroku** tuto změnu NEMÁ → CORS blokáda.

---

## ✅ Řešení: Push na Heroku

### V Terminálu:

```bash
cd /Users/kolibric/Desktop/Kolibri\ app.

# Zkontrolovat Heroku remote
git remote -v

# Mělo by zobrazit:
# heroku  https://git.heroku.com/radim-brain-2025.git (fetch)
# heroku  https://git.heroku.com/radim-brain-2025.git (push)
```

### Pokud Heroku remote NENÍ:

```bash
# Přidat Heroku remote
heroku git:remote -a radim-brain-2025

# Nebo pokud nemáte Heroku CLI:
git remote add heroku https://git.heroku.com/radim-brain-2025.git
```

### Push na Heroku:

```bash
# Push na Heroku (triggers auto-deploy)
git push heroku main

# NEBO pokud je branch jiná:
git push heroku HEAD:main
```

---

## 🔍 Ověření po deployi

### 1. Sledovat Heroku build logs:

```bash
heroku logs --tail -a radim-brain-2025
```

**Nebo v browseru:**
- [dashboard.heroku.com/apps/radim-brain-2025/activity](https://dashboard.heroku.com/apps/radim-brain-2025/activity)

### 2. Test CORS:

```bash
# Test z terminálu
curl -H "Origin: https://app.radimcare.cz" \
     -H "Access-Control-Request-Method: GET" \
     -X OPTIONS \
     https://radim-brain-2025-be1cd52b04dc.herokuapp.com/health
```

**Měl by vrátit:**
```
Access-Control-Allow-Origin: https://app.radimcare.cz
```

### 3. Test ve frontendové console:

Otevřít `https://app.radimcare.cz` a mělo by být:
```
✅ Backend HEALTHY
✅ WebSocket connected
```

Místo:
```
❌ blocked by CORS policy
```

---

## 🚨 Pokud Heroku remote chybí

### Možnost A: Použít Heroku CLI

```bash
# Install Heroku CLI (pokud nemáte)
brew tap heroku/brew && brew install heroku

# Login
heroku login

# Přidat remote
heroku git:remote -a radim-brain-2025
```

### Možnost B: GitHub Auto-Deploy

**Pokud je Heroku připojeno k GitHubu:**

1. Push do GitHub repository (hlavní backend repo)
2. Heroku auto-deployuje z GitHubu

**Najít které repo:**
- Heroku Dashboard → radim-brain-2025
- Deploy tab → Deployment method
- Pokud je "GitHub" → vidíte connected repo

---

## 📝 Quick Commands

```bash
cd /Users/kolibric/Desktop/Kolibri\ app.

# Check current remote
git remote -v

# If heroku remote exists:
git push heroku main

# If not:
heroku git:remote -a radim-brain-2025
git push heroku main

# Watch logs:
heroku logs --tail -a radim-brain-2025
```

---

## ✅ Po úspěšném deployi

**app.radimcare.cz by mělo fungovat bez CORS chyb!**

```
https://app.radimcare.cz → ✅
Backend API calls → ✅
WebSocket → ✅
Chatbot → ✅
```
