# 🔑 API Klíče - Kompletní Audit

**Datum:** 17. října 2025, 23:45
**Status:** ⚠️ NALEZENY PROBLÉMY

---

## 📊 Současný Stav

### ✅ Gemini API (SPRÁVNĚ)

```javascript
// kolibri-senior-app.html řádky 236-242
window.APP_CONFIG = {
    GEMINI_API_KEY: 'YOUR_GEMINI_API_KEY_HERE',
    GEMINI_ENDPOINT: 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent',
    GEMINI_MODEL: 'gemini-1.5-flash'
}
```

**Používá se v:**
- ✅ `callGeminiAPI()` - řádek 5088-5124
- ✅ `GeminiService.generateText()` - řádek 4991-5040

---

### ✅ Azure TTS (SPRÁVNĚ)

```javascript
// kolibri-senior-app.html řádky 243-250
AZURE_TTS: {
    KEY: 'YOUR_AZURE_SPEECH_KEY_HERE',
    REGION: 'westeurope',
    VOICE: 'cs-CZ-AntoninNeural'
}
```

**Používá se v:**
- ✅ `initializeAzureTTS()` - řádek 9262-9290
- ✅ `speak()` funkce

---

### ❌ OpenAI API (PROBLÉM!)

**CHYBÍ v APP_CONFIG!** Ale kód na něj odkazuje:

```javascript
// ❌ Řádek 8309: Neexistující klíč
if (window.APP_CONFIG.OPENAI_API_KEY) { ... }

// ❌ Řádek 8356: Neexistující klíč
if (!window.APP_CONFIG?.OPENAI_API_KEY) { ... }

// ❌ Řádek 8809: Pokusy o nastavení
window.APP_CONFIG.OPENAI_API_KEY = apiKey;

// ❌ Řádek 10402-10403: Quiz generování
const apiKey = window.APP_CONFIG.OPENAI_API_KEY;
const endpoint = window.APP_CONFIG.OPENAI_ENDPOINT;
```

---

## 🔍 Analýza Problémů

### Problém #1: Zaměnené názvy

V kódu jsou **4 místa**, kde se používá `OPENAI_API_KEY` místo `GEMINI_API_KEY`:

1. **Řádek 8309** - `improveTranscriptWithGemini()` funkce
2. **Řádek 8356** - kontrola API klíče
3. **Řádek 8809** - test Gemini připojení
4. **Řádek 10402** - `generateQuizWithGemini()` funkce

### Problém #2: Neexistující OPENAI_ENDPOINT

Funkce očekávají `window.APP_CONFIG.OPENAI_ENDPOINT`, který není definován.

---

## 🛠️ Opravy

### Oprava #1: Řádek 8309 (improveTranscriptWithGemini)

```javascript
// ❌ PŘED:
if ((confidence < 0.7 || isFragmented) && window.APP_CONFIG && window.APP_CONFIG.OPENAI_API_KEY) {

// ✅ PO:
if ((confidence < 0.7 || isFragmented) && window.APP_CONFIG && window.APP_CONFIG.GEMINI_API_KEY) {
```

### Oprava #2: Řádek 8356 (improveTranscriptWithGemini)

```javascript
// ❌ PŘED:
if (!window.APP_CONFIG?.OPENAI_API_KEY) {
    console.log('OpenAI API klíč není k dispozici');
    return transcript;
}

// ✅ PO:
if (!window.APP_CONFIG?.GEMINI_API_KEY) {
    console.log('Gemini API klíč není k dispozici');
    return transcript;
}
```

### Oprava #3: Řádek 8809 (testGeminiConnection)

```javascript
// ❌ PŘED:
window.APP_CONFIG.OPENAI_API_KEY = apiKey;

// ✅ PO:
window.APP_CONFIG.GEMINI_API_KEY = apiKey;
```

### Oprava #4: Řádek 10402-10403 (generateQuizWithGemini)

```javascript
// ❌ PŘED:
const apiKey = window.APP_CONFIG.OPENAI_API_KEY;
const endpoint = window.APP_CONFIG.OPENAI_ENDPOINT;

// ✅ PO:
const apiKey = window.APP_CONFIG.GEMINI_API_KEY;
const endpoint = window.APP_CONFIG.GEMINI_ENDPOINT;
```

---

## 📋 Checklist Oprav

- [ ] Opravit řádek 8309 (OPENAI_API_KEY → GEMINI_API_KEY)
- [ ] Opravit řádek 8356 (OPENAI_API_KEY → GEMINI_API_KEY)
- [ ] Opravit řádek 8809 (OPENAI_API_KEY → GEMINI_API_KEY)
- [ ] Opravit řádek 10402 (OPENAI_API_KEY → GEMINI_API_KEY)
- [ ] Opravit řádek 10403 (OPENAI_ENDPOINT → GEMINI_ENDPOINT)
- [ ] Test funkčnosti po opravách

---

## 🎯 Správná Konfigurace

### Development (localhost):

```javascript
window.APP_CONFIG = {
    // ✅ GEMINI API
    GEMINI_API_KEY: 'YOUR_GEMINI_API_KEY_HERE',
    GEMINI_ENDPOINT: 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent',
    GEMINI_MODEL: 'gemini-1.5-flash',

    // ✅ AZURE TTS
    AZURE_TTS: {
        KEY: 'YOUR_AZURE_SPEECH_KEY_HERE',
        REGION: 'westeurope',
        VOICE: 'cs-CZ-AntoninNeural'
    },

    // ❌ NEPOUŽÍVÁ SE - OpenAI API není potřeba!
    // Aplikace používá POUZE Gemini AI
}
```

---

## ⚠️ DŮLEŽITÉ

**Aplikace NEPOUŽÍVÁ OpenAI API!**

Všechny AI funkce běží na **Google Gemini API**:
- Chat odpovědi
- Vylepšení rozpoznávání řeči
- Generování kvízů
- AI asistence

**Kdykoliv vidíte `OPENAI_API_KEY` nebo `OPENAI_ENDPOINT`, je to CHYBA!**

---

## 🔍 Verifikace po Opravách

```javascript
// Test v browser console:

// 1. Zkontrolovat CONFIG
console.log('Gemini Key:', window.APP_CONFIG.GEMINI_API_KEY ? '✅ Nastaven' : '❌ Chybí');
console.log('OpenAI Key:', window.APP_CONFIG.OPENAI_API_KEY ? '⚠️ Neměl by existovat!' : '✅ OK');

// 2. Test Gemini volání
await callGeminiAPI('Ahoj');

// 3. Test Quiz generování
await generateQuizWithGemini('Historie');
```

---

**Závěr:** Je potřeba opravit 5 míst v kódu, kde se chybně odkazuje na OpenAI místo Gemini.

