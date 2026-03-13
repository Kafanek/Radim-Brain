# 📋 RADIM CARE — INSTALAČNÍ CHECKLIST (tisk na A4)

---

## Pokoj: _________ Senior: ___________________________ Datum: ___________

---

### 🔧 HARDWARE — krabice rozbalena?
| ✓ | Položka | Sériové č. / MAC |
|---|---------|------------------|
| ☐ | Tablet Samsung Tab A9 | ________________ |
| ☐ | Stojan na tablet | — |
| ☐ | Aqara Teploměr (WSDCGQ11LM) | ________________ |
| ☐ | Aqara Pohybový senzor (RTCGQ11LM) | ________________ |
| ☐ | Aqara Dveřní kontakt (MCCGQ11LM) | ________________ |
| ☐ | Aqara SOS tlačítko (WXKG11LM) | ________________ |
| ☐ | Aqara FP1 senzor pádu (volitelně) | ________________ |
| ☐ | USB-C kabel + adaptér | — |
| ☐ | 3M Command Strips | — |

---

### 📡 PÁROVÁNÍ SENZORŮ (Zigbee2MQTT)
| ✓ | Senzor | Zigbee jméno | Spárován? | Signal |
|---|--------|-------------|-----------|--------|
| ☐ | Teploměr | zigbee_temp_____  | ☐ Ano | ☐ OK |
| ☐ | Vlhkoměr | zigbee_hum_____   | ☐ Ano | ☐ OK |
| ☐ | Pohyb | zigbee_motion_____ | ☐ Ano | ☐ OK |
| ☐ | Dveře | zigbee_door_____   | ☐ Ano | ☐ OK |
| ☐ | SOS | zigbee_sos_____     | ☐ Ano | ☐ OK |
| ☐ | Pád | zigbee_fall_____    | ☐ Ano | ☐ OK |

---

### 🏠 UMÍSTĚNÍ SENZORŮ
| ✓ | Senzor | Kde přesně | Výška |
|---|--------|-----------|-------|
| ☐ | Teploměr | _________________ | ~1m |
| ☐ | Pohyb | _________________ | strop/~2.4m |
| ☐ | Dveře | hlavní dveře | zárubeň |
| ☐ | SOS | _________________ | ~0.8m |
| ☐ | Pád | _________________ | ~1.3m |

**Schéma pokoje** (nakresli):
```
┌─────────────────────────┐
│                         │
│                         │
│                         │
│                         │
│                         │
│                    🚪   │
└─────────────────────────┘
```
Zakresli: 🛏️ postel, 📱 tablet, 🌡️ teploměr, 🚶 pohyb, 🆘 SOS, 🚪 dveře

---

### 📱 TABLET
| ✓ | Úkon |
|---|------|
| ☐ | Tablet zapnut, počáteční nastavení hotové |
| ☐ | Wi-Fi připojeno: SSID _________________ |
| ☐ | Systém aktualizován |
| ☐ | Písmo: Extra Large |
| ☐ | Radim aplikace nainstalována (PWA) |
| ☐ | Hlas Antonín funguje (test v Settings) |
| ☐ | Kiosk mode / Stay Awake zapnuto |
| ☐ | Stojan připevněn |
| ☐ | Nabíjecí kabel bezpečně veden |

---

### ⚙️ BACKEND REGISTRACE
| ✓ | Úkon |
|---|------|
| ☐ | Zařízení registrována (curl / setup_rooms.sh) |
| ☐ | Alert pravidla vytvořena |
| ☐ | Pečovatel přiřazen: ____________ tel: ____________ |
| ☐ | Rodina přiřazena: ____________ tel: ____________ |

---

### ✅ FUNKČNÍ TESTY
| ✓ | Test | Výsledek |
|---|------|---------|
| ☐ | Teplota se zobrazuje na dashboardu | ☐ OK ☐ FAIL |
| ☐ | Pohyb detekován (projdi se) | ☐ OK ☐ FAIL |
| ☐ | Dveře otevření/zavření | ☐ OK ☐ FAIL |
| ☐ | SOS → CRITICAL alert na dashboardu | ☐ OK ☐ FAIL |
| ☐ | SMS notifikace přijata pečovatelem | ☐ OK ☐ FAIL |
| ☐ | Tablet — chat s Radimem funguje | ☐ OK ☐ FAIL |
| ☐ | Tablet — hlasový výstup funguje | ☐ OK ☐ FAIL |

---

### 👴 EDUKACE SENIORA (~15 min)
| ✓ | Co vysvětlit |
|---|-------------|
| ☐ | Kde je SOS tlačítko a jak ho zmáčknout |
| ☐ | Jak mluvit s Radimem (chat na tabletu) |
| ☐ | Že senzory sledují teplotu a pohyb (ne kamery!) |
| ☐ | Koho kontaktovat při problému |
| ☐ | Že tablet nechávat stále připojený k nabíjení |

---

### 📝 POZNÁMKY
```
_____________________________________________
_____________________________________________
_____________________________________________
_____________________________________________
```

**Podpis instalátora:** _________________ **Podpis seniora/opatrovníka:** _________________

---
*Radim Care v5.1 — IoT Installation Checklist*
