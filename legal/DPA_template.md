# Smlouva o zpracování osobních údajů (DPA)
## podle čl. 28 GDPR

**Mezi:**

**KOLIBRI s.r.o.** — IČO: [DOPLNIT], sídlo: [DOPLNIT]  
*(„Zpracovatel" / „KOLIBRI")*

**a**

**[Název partnera]** — IČO: [DOPLNIT], sídlo: [DOPLNIT]  
*(„Další zpracovatel" / „Partner")*

---

## 1. Předmět

1.1. Tato smlouva upravuje **zpracování osobních údajů** v souvislosti s pilotem Radimův Odkaz (viz MoU ze dne ____).

1.2. **Správce dat** je vždy **konkrétní senior** (uživatel platformy), který svou vzpomínku nebo osobní údaje poskytuje.

1.3. **KOLIBRI** je technologickým **zpracovatelem** těchto dat ve smyslu Art. 28 GDPR.

1.4. **Partner** je v rámci pilotu **dalším zpracovatelem** dle Art. 28 odst. 4 GDPR. Senior dává souhlas s tímto propojením explicitně v okamžiku podpisu konkrétní licenční smlouvy.

---

## 2. Kategorie osobních údajů

Partner zpracovává **pouze tyto kategorie**:

2.1. **Identifikační údaje** (jen pokud licence není anonymní):
   - Jméno a příjmení seniora
   - Rok narození
   - Region (město / kraj)

2.2. **Obsah vzpomínky:**
   - Textový přepis (transkripce hlasového záznamu)
   - Audio záznam (volitelně, dle licence)
   - Video záznam (jen pokud explicitně povoleno)
   - Tematické anotace (témata, hloubka, emoční tón)

2.3. **Metadata:**
   - Datum a čas pořízení
   - Délka záznamu
   - Hash transkripce (pro integritu)

2.4. **Partner NIKDY neobdrží:**
   - ❌ Telefonní číslo, e-mail seniora
   - ❌ Bankovní údaje (IBAN, IČO, atd.)
   - ❌ Zdravotní data (ze zdravotního modulu Radim)
   - ❌ Lokační data (GPS)
   - ❌ Soukromé chaty s rodinou
   - ❌ Krizové konverzace (SOS, deprese, sebevražedné myšlenky)

---

## 3. Účely zpracování

3.1. Partner smí zpracovávat data **pouze pro účel uvedený v jeho Nabídce**, např.:
   - Vědecký výzkum (publikace, konference)
   - Vzdělávací činnost (přednášky, učební materiály)
   - Archivní zachování (digitální preservace)
   - Trénink AI modelů (jen pokud explicitně licencováno)
   - Komerční využití (jen pokud explicitně licencováno)

3.2. **Změna účelu** vyžaduje **nový souhlas seniora**, nikoli souhlas Partnera nebo KOLIBRI.

---

## 4. Bezpečnostní opatření

Partner se zavazuje:

4.1. **Šifrování dat at-rest** (AES-256 nebo ekvivalent) na všech systémech, kde jsou data uložena.

4.2. **Šifrování at-transit** (TLS 1.2+) při jakémkoliv přenosu.

4.3. **Přístupové oprávnění** podle principu nejnižšího privilegia — pouze osoby, které data k svému úkolu nezbytně potřebují.

4.4. **Audit log** přístupů k datům — kdo a kdy si data prohlížel/stahoval.

4.5. **Geografické omezení** — data zůstávají v rámci **EU/EHP**. Přenos mimo EU vyžaduje samostatný souhlas KOLIBRI a doplnění SCC (Standard Contractual Clauses).

4.6. **Pravidelné backupy** s šifrováním. Při ukončení smlouvy backupy se mažou do 90 dnů.

4.7. **Pseudonymizace** identifikátorů, kde to účel umožňuje.

4.8. **Penetration testing** alespoň 1× ročně, pokud Partner zpracovává >100 vzpomínek.

---

## 5. Práva seniora (subjektu údajů)

KOLIBRI a Partner společně zajišťují seniorovi:

5.1. **Právo na přístup** (Art. 15 GDPR) — KOLIBRI poskytuje seznam, Partner doplní informaci „kde a jak data využívá".

5.2. **Právo na opravu** (Art. 16) — senior si může změnit svou vzpomínku v aplikaci, Partner je povinen update reflektovat do 30 dnů.

5.3. **Právo na výmaz** (Art. 17, „právo být zapomenut"):
   - Senior klikne v aplikaci „🗑️ Zapomenout"
   - KOLIBRI smaže data ze své strany
   - KOLIBRI **notifikuje Partnera do 24 hodin**
   - Partner smaže data ze svých systémů **do 30 kalendářních dnů**
   - Partner písemně potvrdí KOLIBRI dokončení výmazu

5.4. **Právo na omezení** (Art. 18) — pokud senior namítne, Partner přestane data aktivně zpracovávat (uchovává je read-only) do vyřešení.

5.5. **Právo na přenositelnost** (Art. 20) — KOLIBRI poskytuje JSON export. Partner doplní seznam uplatnění.

5.6. **Právo vznést námitku** (Art. 21) — senior může kdykoli zrušit smlouvu, Partner data již nesmí použít pro nové účely.

5.7. **14denní cooling-off** (zákon o ochraně spotřebitele) — senior má **14 dní bez sankce** odstoupit od smlouvy. Partner v tomto období nesmí data zveřejňovat.

---

## 6. Subdodavatelé Partnera

6.1. Partner smí zapojit **další zpracovatele** (např. cloud, transcription services) **pouze:**
   - se zachováním stejných podmínek dle této smlouvy
   - s 30denním předstihem písemně oznámeno KOLIBRI
   - po souhlasu KOLIBRI (KOLIBRI nesmí souhlas neodůvodněně odmítnout)

6.2. Partner uvede **seznam subdodavatelů** v Příloze A této DPA. Aktualizovaný seznam je dostupný KOLIBRI na vyžádání.

---

## 7. Hlášení incidentů

7.1. Při **incidentu narušení bezpečnosti osobních údajů** (data breach) Partner:
   - **Notifikuje KOLIBRI do 24 hodin** od zjištění
   - Poskytne dostupné informace (rozsah, příčiny, opatření)
   - Spolupracuje při notifikaci dotčených seniorů a UOOÚ

7.2. KOLIBRI je primárně odpovědné za notifikaci UOOÚ (do 72 hodin dle Art. 33 GDPR), pokud incident vznikl na straně Partnera, Partner KOLIBRI poskytne všechny potřebné informace.

---

## 8. Audit a kontrola

8.1. KOLIBRI má právo **provést audit** systémů Partnera, kde jsou data zpracovávána, **maximálně 1× za 12 měsíců**, s 30denním předstihem.

8.2. Audit může být **fyzický (inspekce)** nebo **dokumentární (vyžádání politik a protokolů)**.

8.3. Náklady běžného auditu nese **KOLIBRI**. Pokud audit odhalí závažné porušení, náklady nese Partner.

---

## 9. Doba zpracování a vrácení dat

9.1. Doba zpracování **odpovídá době licence** dohodnuté v konkrétní smlouvě se seniorem (obvykle neomezená pro výzkum, omezená pro komerční využití).

9.2. **Po skončení účelu** Partner data:
   - **Vrátí KOLIBRI** v původním formátu, NEBO
   - **Smaže ze všech systémů včetně backupů** a písemně to potvrdí

9.3. Partner zachovává **právní povinnost archivace** (např. publikace v recenzovaném časopise) v rozsahu nezbytném pro plnění této povinnosti.

---

## 10. Sankce a pokuty

10.1. Pokud Partner poruší povinnosti z této smlouvy a způsobí KOLIBRI nebo seniorovi škodu, **odpovídá za škodu** v plném rozsahu.

10.2. Pokud porušení vede k pokutě UOOÚ, Partner se podílí na pokutě **proporcionálně dle své odpovědnosti**.

10.3. Maximální celková odpovědnost je **omezena na 5× roční fakturovanou částku** mezi stranami za uplynulých 12 měsíců.

---

## 11. Závěrečná ustanovení

11.1. Tato smlouva nabývá platnosti **dnem podpisu** a trvá po dobu zpracovávání osobních údajů Partnerem.

11.2. Smlouva se řídí **právním řádem ČR a GDPR**.

11.3. V případě rozporu mezi DPA a MoU má **DPA přednost** v otázkách ochrany osobních údajů.

11.4. **DPO (Data Protection Officer):**
   - KOLIBRI: kafanek@kafanek.com (do jmenování formálního DPO)
   - Partner: [DOPLNIT]

---

**V _________ dne ________ 2026**

**Za KOLIBRI s.r.o.:** Radim Kafánek _____________________

**Za [Partner]:** [Jméno] _____________________

---

**Příloha A** — Seznam subdodavatelů Partnera  
**Příloha B** — Konkrétní bezpečnostní opatření Partnera (ISO 27001 cert, atd.)
