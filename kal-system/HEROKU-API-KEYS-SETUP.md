# 🔒 HEROKU API KEYS SETUP

## Bezpečné nastavení API klíčů na Heroku

> ⚠️ **KRITICKÉ BEZPEČNOSTNÍ OPATŘENÍ**
> API klíče NIKDY nepatří do kódu! Tento průvodce vás provede bezpečným nastavením.

---

## 🚨 OKAMŽITÉ KROKY (Pokud jste vystavili API klíče)

Pokud jste již commitli API klíče do Gitu:

### 1. **INVALIDUJTE všechny kompromitované klíče OKAMŽITĚ!**

#### Azure TTS

```bash
# 1. Přejděte na: [Azure Portal](https://portal.azure.com/)
# 2. Najděte váš Speech Service
# 3. Keys and Endpoint → Regenerate Key 1 a Key 2
```

#### ElevenLabs

```bash
# 1. Přejděte na: [ElevenLabs Settings](https://elevenlabs.io/app/settings)
# 2. API Keys → Regenerate
```

#### Google Calendar

```bash
# 1. Přejděte na: [Google Cloud Console](https://console.cloud.google.com/)
# 2. APIs & Services → Credentials
# 3. Smaž staré credentials
# 4. Vytvoř nové OAuth 2.0 Client ID
```

### 2. **Odstraňte klíče z Git historie**

```bash
# POZOR: Toto přepíše historii
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch mykolibri-academy-project/radim-dashboard.html" \
  --prune-empty --tag-name-filter cat -- --all

# Force push (POZOR: koordinujte s týmem!)
git push origin --force --all
```

---

## ✅ SPRÁVNÉ NASTAVENÍ - KROK ZA KROKEM

### Metoda 1: Heroku CLI (Doporučeno)

#### 1. Instalace Heroku CLI

```bash
# macOS
brew tap heroku/brew && brew install heroku

# Nebo stáhněte z: https://devcenter.heroku.com/articles/heroku-cli
```

#### 2. Přihlášení

```bash
heroku login
```

#### 3. Nastavení Config Vars

```bash
# Azure TTS
heroku config:set AZURE_TTS_KEY="your_new_azure_key_here" --app radim-brain-2025
heroku config:set AZURE_REGION="westeurope" --app radim-brain-2025

# ElevenLabs
heroku config:set ELEVENLABS_API_KEY="your_new_elevenlabs_key_here" --app radim-brain-2025
heroku config:set ELEVENLABS_VOICE_ID="uYFJyGaibp4N2VwYQshk" --app radim-brain-2025

# Google Calendar
heroku config:set GOOGLE_CLIENT_ID="your_client_id.apps.googleusercontent.com" --app radim-brain-2025
heroku config:set GOOGLE_CLIENT_SECRET="your_client_secret" --app radim-brain-2025
heroku config:set GOOGLE_API_KEY="your_google_api_key" --app radim-brain-2025
heroku config:set GOOGLE_REDIRECT_URI="https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/proxy/gcal/callback" --app radim-brain-2025

# Gemini AI (pokud používáte)
heroku config:set GEMINI_API_KEY="your_gemini_key" --app radim-brain-2025
```

#### 4. Ověření

```bash
# Zobrazí všechny nastavené proměnné (bez hodnot)
heroku config --app radim-brain-2025

# Zobrazí včetně hodnot (POZOR: citlivé!)
heroku config:get AZURE_TTS_KEY --app radim-brain-2025
```

---

### Metoda 2: Heroku Dashboard (Web UI)

#### 1. Přihlášení

Přejděte na: [Heroku Dashboard](https://dashboard.heroku.com/)

#### 2. Vyberte aplikaci

Klikněte na: **radim-brain-2025**

#### 3. Otevřete Settings

**Settings** → **Config Vars** → **Reveal Config Vars**

#### 4. Přidejte proměnné

Klikněte **Add** a zadejte:

| KEY | VALUE |
|-----|-------|
| `AZURE_TTS_KEY` | `váš-nový-azure-klíč` |
| `AZURE_REGION` | `westeurope` |
| `ELEVENLABS_API_KEY` | `váš-nový-elevenlabs-klíč` |
| `ELEVENLABS_VOICE_ID` | `uYFJyGaibp4N2VwYQshk` |
| `GOOGLE_CLIENT_ID` | `váš-client-id.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | `váš-client-secret` |
| `GOOGLE_API_KEY` | `váš-google-api-key` |
| `GOOGLE_REDIRECT_URI` | `<https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/proxy/gcal/callback`> |

#### 5. Uložení

Změny se aplikují automaticky. Backend se restartuje.

---

## 🧪 TESTOVÁNÍ

### 1. Health Check - Azure TTS

```bash
curl https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/proxy/azure/health
```

**Očekávaný výstup:**

```json
{
  "status": "healthy",
  "service": "Azure TTS Proxy",
  "region": "westeurope",
  "key_configured": true
}
```

### 2. Health Check - ElevenLabs

```bash
curl https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/proxy/elevenlabs/health
```

**Očekávaný výstup:**

```json
{
  "status": "healthy",
  "service": "ElevenLabs TTS Proxy",
  "voice_id": "uYFJyGaibp4N2VwYQshk",
  "key_configured": true
}
```

### 3. Health Check - Google Calendar

```bash
curl https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/proxy/gcal/health
```

**Očekávaný výstup:**

```json
{
  "status": "healthy",
  "service": "Google Calendar Proxy",
  "client_id_configured": true,
  "client_secret_configured": true
}
```

### 4. Test TTS přes Proxy

```bash
# Azure TTS test
curl -X POST https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/proxy/azure/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Ahoj, toto je test.", "voice": "cs-CZ-AntoninNeural"}'
```

---

## 📋 CHECKLIST PRO DEPLOYMENT

- [ ] ✅ Všechny staré API klíče invalidovány
- [ ] ✅ Nové klíče vygenerovány
- [ ] ✅ Config Vars nastaveny na Heroku
- [ ] ✅ `.env` soubor v `.gitignore`
- [ ] ✅ `.env.example` aktualizován (bez reálných klíčů!)
- [ ] ✅ Frontend odstraněny všechny hardcodované klíče
- [ ] ✅ Proxy endpointy implementovány
- [ ] ✅ Health checks fungují
- [ ] ✅ TTS test funguje
- [ ] ✅ Git historie vyčištěna (pokud byly klíče commitnuty)

---

## 🔐 BEST PRACTICES

### DO ✅

- ✅ Používej environment variables
- ✅ Používej `.env.example` pro dokumentaci
- ✅ Invaliduj klíče po kompromitaci
- ✅ Používej různé klíče pro dev/staging/production
- ✅ Pravidelně rotuj klíče (každých 90 dní)
- ✅ Monitoruj usage API klíčů

### DON'T ❌

- ❌ NIKDY necommituj `.env` do Gitu
- ❌ NIKDY nesdílej API klíče na Slacku/emailu
- ❌ NIKDY neloguj API klíče do konzole
- ❌ NIKDY neposílej API klíče přes URL parametry
- ❌ NIKDY nehardcoduj klíče v kódu
- ❌ NIKDY nepoužívej stejný klíč pro dev i production

---

## 🚀 DEPLOYMENT WORKFLOW

### 1. Local Development

```bash
# Zkopíruj .env.example
cp .env.example .env

# Nastav své lokální klíče
vim .env

# NIKDY necommituj .env
```

### 2. Staging/Production

```bash
# Nastav Config Vars na Heroku
heroku config:set KEY=value --app your-app

# Deploy
git push heroku main

# Ověř
heroku logs --tail --app your-app
```

---

## 📞 PODPORA

### Kde získat API klíče

#### Azure TTS - Získání klíčů

- **Portal:** [Azure Portal](https://portal.azure.com/)
- **Cesta:** Speech Services → Keys and Endpoint
- **Cena:** Free tier 5M znaků/měsíc

#### ElevenLabs - Získání klíčů

- **Portal:** [ElevenLabs Settings](https://elevenlabs.io/app/settings)
- **Cesta:** API Keys → Generate
- **Cena:** Free tier 10K znaků/měsíc

#### Google Calendar - Získání klíčů

- **Portal:** [Google Cloud Console](https://console.cloud.google.com/)
- **Cesta:** APIs & Services → Credentials
- **Cena:** Free (s rate limity)

---

## 🆘 TROUBLESHOOTING

### Error: "API key not configured"

```bash
# Zkontroluj, zda je klíč nastaven
heroku config:get AZURE_TTS_KEY --app radim-brain-2025

# Pokud je prázdný, nastav ho
heroku config:set AZURE_TTS_KEY="your_key" --app radim-brain-2025

# Restart backendu
heroku restart --app radim-brain-2025
```

### Error: "Unauthorized" nebo "401"

- Zkontroluj, že klíč je správný
- Zkontroluj, že klíč není expirovaný
- Vygeneruj nový klíč

### Error: "Rate limit exceeded"

- Azure: Upgrade na vyšší tier
- ElevenLabs: Počkej nebo upgrade
- Google: Zkontroluj quotas v Console

---

## 📚 DALŠÍ ZDROJE

- [Heroku Config Vars Documentation](https://devcenter.heroku.com/articles/config-vars)
- [12 Factor App - Config](https://12factor.net/config)
- [OWASP API Security](https://owasp.org/www-project-api-security/)

---

**Vytvořeno:** 2025-11-14
**Verze:** 1.0
**Autor:** Radim Brain Security Team
