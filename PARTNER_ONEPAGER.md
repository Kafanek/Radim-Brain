# Radimův Odkaz — Partnerství
**KOLIBRI s.r.o. · radimcare.cz · kafanek@kafanek.com · 28. 4. 2026**

---

## Co je Radimův Odkaz

**AI společník pro seniory, který sbírá životní moudrost** — vzpomínky, zkušenosti, hodnoty — a strukturovaně je archivuje. Senioři mluví, Radim naslouchá, kompletní transkripce + audio + emoční tagy se ukládají do osobního archivu.

Senior dostane:
- důstojnou cestu, jak po sobě něco zanechat
- finanční ohodnocení (tisíce Kč) za vědecky/kulturně cenné vzpomínky
- bezpečí (žádný cloud sdílení bez souhlasu)

Aplikace je nasazena, **15 modulů** (chat, kalendář, kvízy, hudba, telemedicína, smart home, paměť, …), pilot s 5 reálnými seniory, **stack Python/Flask + Postgres + Cloudflare**, deployed na app.radimcare.cz.

---

## Co partner dostává

| Partner | Use case | Hodnota |
|---|---|---|
| **Univerzita / archiv** | digitalizovaná ústní historie (1968, 1989, normalizace, transformace, rodinné kuchyně, řemesla) | jedinečný korpus pro výzkum + publikace + EU granty |
| **AI lab / tech** | autentický český korpus pro trénink (cca 50K slov/měsíc/senior) | etický training data, opt-in souhlas, GDPR-clean |
| **Marketing / consumer research** | spotřebitelské zvyky důchodců, anonymizovaně | data, která jinak nelze získat (senioři neodpovídají na panel průzkumy) |
| **Média / nakladatelství** | příběhy s licencí na zpracování (kniha, podcast, dokument) | exkluzivní obsah s lidským rozměrem |
| **Nadace / nezisk** | kontakt s "neviditelnou" cílovkou | platforma pro intervenci (osamělost, kognice, zdraví) |

---

## Co partner zaplatí (a kdy)

**Pilot (6 měsíců, **zdarma**):**
- Partner publikuje 1-3 nabídky na platformě
- Senioři dobrovolně přispívají
- KOLIBRI dodá anonymizovaný export po 6 měsících
- **Žádné jednorázové fee, žádný royalty share**

**Pilot evaluation kritéria:**
- Počet souhlasných smluv ≥ 30
- Hodnocení partnera (CSAT) ≥ 4/5
- Kvalita dat (manuální review 10% sample) ≥ 80%

**Po pilotu (ostrý provoz):**

| Položka | Sazba |
|---|---|
| **Platforma** | 20% z hrubé ceny smlouvy |
| **Senior** | 80% (na bankovní účet, výplata 5. v měsíci) |
| **Royalty seniora** | dle smlouvy (typ. 100-300 Kč/rok × 3-10 let) |
| **Setup fee partnera** | žádné — jen integrační čas |
| **Měsíční minimum** | 0 Kč (pay-per-use) |

**Příklad:** partner zaplatí seniorovi **1500 Kč** za vzpomínku → senior dostane 1200 Kč netto, KOLIBRI 300 Kč na provoz.

---

## Právní rámec

- **MoU** (Memorandum of Understanding) na pilot
- **DPA** (Data Processing Agreement) podle GDPR
- **Smlouva o licenci** mezi seniorem a partnerem (KOLIBRI je technologický prostředník)
- **14denní odstupné** (consumer protection EU) pro seniora
- **Audit log** každé smlouvy s timestampem (právní důkaz)
- **Anonymizace na vyžádání** (pseudonymizace nebo úplná anonymizace)
- **Právo na výmaz** (Article 17 GDPR) — senior i partner

---

## Bezpečnost a etika

- 🔒 **Zdravotní a krizové rozhovory** se NIKDY nesdílí (filter na backendu)
- 🛑 **Cooling-off period** 14 dní — senior si může smlouvu rozmyslet bez sankce
- 🤝 **Family co-sign** — pro seniory ≥85 let nebo s kognitivním deficitem vyžaduje podpis pečující osoby
- 📊 **Brake pedál** — Radim sám detekuje, pokud senior zveřejňuje příliš osobní obsah, a navrhne stáhnout
- 🦉 **Trust score** každého partnera viditelný seniorovi (95% Radim doporučí, 70% varuje, <70% odrazuje)
- 📜 **Audit přístup** — partner i senior mohou kdykoli stáhnout log "kdo si četl mou vzpomínku"

---

## Technický status

| Co | Stav | Detail |
|---|---|---|
| Aplikace | ✅ Live | app.radimcare.cz |
| Backend | ✅ Heroku v775 | Postgres, 17 blueprintů, /health 2.3ms |
| Frontend | ✅ Cloudflare | mobile-ready, offline-first PWA |
| Telefon | ✅ Twilio | proaktivní volání + příchozí Q&A |
| AI | ⚙️ Gemini 2.5 → Claude flip | rozpracováno |
| Stripe payouts | 🚧 Q3 2026 | pro pilot stačí ruční převod |
| Partner dashboard | 🚧 14.5. před ČVUT | v3-fázovém roadmap |

---

## Pilot — co bych potřeboval od partnera

1. **30-min úvodní hovor** (kafanek@kafanek.com / +420 …)
2. **Zájem písemně** (i e-mailem) — typ instituce, IČO, kontaktní osoba
3. **Definice 1-3 nabídek** — typ vzpomínky, cenový strop, royalty model
4. **Jméno a ETC** — osoba zodpovědná za pilot na partnerově straně
5. **Podpis MoU + DPA** (~1 týden, můžu připravit šablonu)

---

## Časový plán

```
TÝDEN    AKCE
1        Úvodní hovor, MoU draft
2-3      Podpis MoU + DPA, technický onboarding
4        Partner publikuje 1. nabídku
4-25     Pilot fáze (6 měsíců aktivního sběru)
26       Pilot evaluation, rozhodnutí o ostrém provozu
27+      Komerční smlouva, Stripe Connect, payouts
```

---

## Kontakt

**Radim Kafánek** — zakladatel, KOLIBRI s.r.o.  
📧 kafanek@kafanek.com  
🌐 app.radimcare.cz  
📍 Praha, ČR

---

*Tento dokument je pracovní verze. Konečné podmínky se sjednávají případ od případu.*
