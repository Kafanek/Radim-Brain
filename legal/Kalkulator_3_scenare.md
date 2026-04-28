# Finanční kalkulátor — Radimův Odkaz
## 3 scénáře pilotu a komerčního provozu

**Připraveno:** 28. 4. 2026 · KOLIBRI s.r.o.

---

## Scénář A — PILOT (3 měsíce, 1 partner, 30 seniorů)

| Položka | Hodnota |
|---|---|
| Počet seniorů | 30 |
| Vzpomínek na seniora (průměr) | 2 |
| Cena za vzpomínku (gross) | 1 000 Kč |
| Royalty (volitelná) | 200 Kč/rok × 5 let |
| Celkem vzpomínek | 60 |

**Tok peněz:**
| Strana | Částka | Detail |
|---|---|---|
| **Partner platí KOLIBRI** | **60 000 Kč** | 60 × 1 000 |
| Senior dostává (80 %) | 48 000 Kč | 60 × 800 (rozděleno mezi 30 seniorů = 1 600 Kč/senior průměr) |
| KOLIBRI hrubá provize (20 %) | 12 000 Kč | |
| KOLIBRI DPH 21 % | -2 083 Kč | |
| **KOLIBRI netto** | **9 917 Kč** | |

**Royalty (rok 2-6):**
| Rok | Partner platí | Senior dostává | KOLIBRI netto |
|---|---|---|---|
| 2 | 12 000 Kč | 9 600 Kč | 1 983 Kč |
| 3 | 12 000 Kč | 9 600 Kč | 1 983 Kč |
| 4 | 12 000 Kč | 9 600 Kč | 1 983 Kč |
| 5 | 12 000 Kč | 9 600 Kč | 1 983 Kč |
| 6 | 12 000 Kč | 9 600 Kč | 1 983 Kč |
| **5letý součet** | **120 000 Kč** | **96 000 Kč** | **19 832 Kč** |

**Celkem za 6 let:** 180 000 Kč obrat | 144 000 Kč seniorům | **29 750 Kč KOLIBRI netto**

---

## Scénář B — STAGE 1 (rok 1, 5 partnerů, 200 seniorů)

| Položka | Hodnota |
|---|---|
| Počet seniorů | 200 |
| Vzpomínek na seniora (průměr) | 4 |
| Cena za vzpomínku (gross) | 1 200 Kč |
| Royalty | 250 Kč/rok × 5 let |
| Celkem vzpomínek za rok | 800 |

**Roční tok peněz:**
| Strana | Částka |
|---|---|
| Partneři platí KOLIBRI (rok 1) | 960 000 Kč |
| Senior dostává (80 %) | 768 000 Kč (3 840 Kč/senior průměr) |
| KOLIBRI provize (20 %) | 192 000 Kč |
| KOLIBRI DPH | -33 333 Kč |
| **KOLIBRI netto rok 1** | **158 667 Kč** |

**Operativní náklady KOLIBRI rok 1:**
- Heroku + DB + Cloudflare: ~24 000 Kč
- Azure TTS + Gemini API: ~30 000 Kč
- GoPay poplatky (~1.4 %): ~13 500 Kč
- Účetnictví, právník: ~80 000 Kč
- Marketing, partner outreach: ~50 000 Kč
- Zaměstnanec (0.3 FTE caregiver helpdesk): ~150 000 Kč
- **Celkem náklady:** ~347 500 Kč

**EBITDA rok 1:** **-188 833 Kč** *(plánovaná investice — pilot scaling)*

---

## Scénář C — STAGE 2 (rok 3, 25 partnerů, 2 000 seniorů)

| Položka | Hodnota |
|---|---|
| Počet seniorů | 2 000 |
| Vzpomínek na seniora (průměr) | 6 |
| Cena za vzpomínku (gross) | 1 500 Kč |
| Royalty | 300 Kč/rok × 7 let |
| Celkem vzpomínek za rok | 12 000 |

**Roční tok peněz (rok 3):**
| Strana | Částka |
|---|---|
| Partneři platí KOLIBRI | 18 000 000 Kč |
| Z toho předchozí roky royalty (~30 %) | +5 400 000 Kč |
| **Hrubý obrat** | **23 400 000 Kč** |
| Senior dostává (80 %) | 18 720 000 Kč |
| KOLIBRI provize (20 %) | 4 680 000 Kč |
| KOLIBRI DPH | -812 397 Kč |
| **KOLIBRI gross profit** | **3 867 603 Kč** |

**Operativní náklady rok 3:**
- Infra (Heroku Standard, Postgres dedicated): ~120 000 Kč
- AI services: ~600 000 Kč (Gemini + Azure)
- GoPay poplatky: ~328 000 Kč
- Tým (3 FTE: dev, partner manager, helpdesk): ~3 600 000 Kč
- Marketing + sales: ~800 000 Kč
- Právní, účetní, audit, GDPR: ~400 000 Kč
- Pojištění (E&O, kyber): ~150 000 Kč
- **Celkem náklady:** **~6 000 000 Kč**

**EBITDA rok 3:** **-2 132 397 Kč** *(continuing investment, ale ramp je positivní)*

---

## Break-even analýza

**Předpoklad:**
- Náklady fix: ~6 000 000 Kč/rok (Stage 2)
- Marže netto za vzpomínku: ~248 Kč (z 1500 Kč gross po DPH)

**Break-even:** **24 200 vzpomínek/rok** = **~4 000 seniorů × 6 vzpomínek**

**Achievable:** rok 4-5 při zachování 35 % YoY growth.

---

## Capital requirements (do break-even)

| Rok | Roční cash burn | Kumulovaná investice |
|---|---|---|
| 1 (pilot) | 200 000 Kč | 200 000 Kč |
| 2 | 1 200 000 Kč | 1 400 000 Kč |
| 3 | 2 100 000 Kč | 3 500 000 Kč |
| 4 | 1 200 000 Kč | 4 700 000 Kč |
| 5 (break-even) | 0 Kč | 4 700 000 Kč |

**Total funding needed:** **~5 000 000 Kč** (€200 000) do break-evenu.

**Sources:**
- Vlastní zdroje + bootstrapping: 1 000 000 Kč
- EU granty (Horizon, NPO, AAL): 2 500 000 Kč
- Strategický partner (Lenovo/Asbis hardware bundle, success-based): 500 000 Kč
- Angel/seed investor: 1 000 000 Kč

---

## Sensitivita — co kdyby

### Co kdyby cena vzpomínky byla 800 Kč místo 1 500 Kč?
- Stage 2 obrat: **12 480 000 Kč** (-47 %)
- KOLIBRI netto provize: **2 064 000 Kč** (-47 %)
- Break-even posunut na **rok 6-7**

### Co kdyby provoz byl 25 % místo 20 %?
- Stage 2 KOLIBRI gross: **5 850 000 Kč** (+25 %)
- ALE riskujeme nižší atraktivitu pro seniory (méně peněz)

### Co kdyby GoPay → SuperFaktura (1.0 % místo 1.4 %)?
- Stage 2 úspora: **~94 000 Kč** ročně
- Worth the migration only at scale (>10K transakcí/měs)

---

## Klíčové KPIs k monitoringu

1. **Conversion rate seniorů** (z registrace na 1. vzpomínku): cíl >40 %
2. **Vzpomínek na seniora ročně:** cíl 4-8 (Stage 1) → 6-12 (Stage 2)
3. **Partner churn:** cíl <15 % ročně
4. **Senior NPS:** cíl >50
5. **Average revenue per senior (ARPS) ročně:** cíl 4 800 Kč → 9 000 Kč
6. **Customer acquisition cost (CAC) per senior:** cíl <500 Kč
7. **CAC payback period:** cíl <6 měsíců

---

## Scénář partnera — co dostává za své peníze

**Partner X** (Karlova Univerzita, fictivní příklad pilot):
- Platí: 60 000 Kč na první rok (60 vzpomínek × 1 000 Kč)
- Dostává:
  - 60 strukturovaných vzpomínek s anotacemi
  - Anonymizované verze (pseudonymizace seniorů)
  - Audio + transkripce
  - Měsíční kvalitativní report
  - Right to use in research, citation s original source

**ROI partnera:**
- Korpus pro 1 doktorskou disertaci: hodnota ~1 000 000 Kč v grantových penězích
- Korpus pro 1 publikaci v Q1 časopisu: prestige + indexing
- Etická data bez gray-area: brand safety

**Partner ROI ratio:** typicky **15-50× jejich investice** v podobě grantů, publikací, prestige.

---

*Tento kalkulátor je projekce na základě best-effort odhadů. Reálná čísla se mohou lišit. Aktualizovat každý kvartál.*
