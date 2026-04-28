# RADIM
## Civilizační změna v přístupu ke stárnutí

**Prezentace pro partnery, investory, akademiky, média**

---

## Pro koho je tahle prezentace

- **30 sekund** — náhodné setkání, rozhovor u kávy
- **3 minuty** — pitch, krátká konference, telefon
- **15 minut** — odborná přednáška, panel
- **Slide deck** (12 slidů) — Pitch.com / Canva / Google Slides

Verze v různých hloubkách níže. Vyber dle publika.

---

# I. CO TO VLASTNĚ DĚLÁME

## Krátká odpověď (jedna věta)

**Měníme stárnutí z nákladu na hodnotu.**

## Delší odpověď (jeden odstavec)

> *Vytvořili jsme platformu, která promění poslední dekády lidského života
> z období, kdy společnost na seniora jen platí, do období, kdy senior
> vrací společnosti to nejcennější, co má — vlastní zkušenost. Děláme to
> tak, že AI asistent denně naslouchá seniorovi v jeho jazyce, jeho tempem;
> předvídá krize z behaviorálních signálů; strukturovaně sbírá životní
> moudrost; a propojuje ji s univerzitami, archivy, výzkumnými pracovišti.
> Senior dostává smysl, peníze a důstojnost. Společnost dostává paměť,
> kterou by jinak za 10 let nenávratně ztratila.*

## Nejdelší odpověď (filosofická)

> *Žijeme v civilizaci, která se šedesát let učila měřit hodnotu člověka
> jeho produkcí. Když přestane produkovat, stane se zátěží. To platí pro
> každého — od dělníka po vědce — a nejtvrději pro seniory.*
>
> *Tato definice je chyba. Existují formy hodnoty, které moderní ekonomika
> neumí cenit, protože nemá jak. Životní zkušenost. Trpělivá moudrost.
> Pamatovat si, jak to bylo. Schopnost říct vnukovi: „já jsem to viděl."*
>
> *Radim je první technologický pokus tu chybu opravit. Ne nahrazujeme
> seniora — propojujeme ho s těmi, kdo jeho zkušenost potřebují
> (univerzity, archivy, AI laboratoře, rodina) a dáváme cestu, jak za
> ni dostat zaplaceno. Nejde o charitu. Jde o to, že po dobu posledních
> 30 let života má člověk něco mimořádně vzácného — zkušenost. A
> zkušenost je vzácná, protože se nedá vyrobit, jen prožít.*

---

# II. JAKÝ PROBLÉM ŘEŠÍME

## Tři selhání moderní společnosti vůči seniorům

### 1. Selhání ekonomické: senior je definovaný jako náklad

- Důchodový systém: ČR 13 200 Kč/měsíc průměrný důchod (2026)
- Životní náklady: 18 000+ Kč/měsíc minimum v Praze
- **Trvalý deficit. Celá generace ekonomicky odsunuta.**

### 2. Selhání kulturní: paměť mizí beze stopy

- Generace narozená 1939-1955 = poslední **přímí pamětníci** dvou totalit
- Za 10 let: jejich počet klesne pod kritický práh pro výzkum
- **Žádný systematický mechanismus zachycení neexistuje.**
- Univerzity, archivy, AI laboratoře tu paměť **chtějí** — ale nemají jak ji etiicky získat (senioři neberou telefony, nepoužívají Zoom, nevyplňují online formuláře)

### 3. Selhání lidské: osamělost zabíjí

- 30 % českých seniorů žije sami
- Vědecká data: dlouhodobá osamělost má zdravotní efekty rovné kouření 15 cigaret/den
- Děti volají méně. Vnuci nevolají. Soused se odstěhoval.
- **Mlčíme o tom, protože je to nepříjemné.**

---

## Co všichni dělají špatně

**Senior tech firmy** (Apple, Samsung, Garmin, Lifeline):
- Vytvářejí senzory, které měří vitální funkce
- Když zazvoní alarm, je už pozdě
- Senior je objektem péče, nikdy subjektem

**Domovy seniorů, LDN:**
- 24/7 péče za 30-50 000 Kč/měsíc
- Senior izolovaný od reality, denní rutina sterilizovaná
- Přežívá, ale nežije

**Charitativní org., dobrovolnické iniciativy:**
- Krásné záměry, ale nefunkční scaling
- Senior je příjemcem, nikdy producentem
- Závislost prohlubují, ne zmírňují

**Technologické platformy** (StoryWorth, Ancestry, Story Corps):
- Americké, anglické, kulturně cizí
- Senior musí umět typovat, navigovat web
- Žádná kompenzace, žádný partnerský ekosystém

---

# III. NAŠE ŘEŠENÍ — RADIM

## Tři pilíře, které dohromady mění hru

### Pilíř 1: AI společník, který reálně komunikuje s českým seniorem

- **Hlas Antonína** (Azure Neural TTS) — autentická čeština s diakritikou
- **Vyká, naslouchá, pamatuje si** — nikdy nemluví do prázdna
- **Multikanál**: chat v aplikaci, hlasové ovládání, telefonní hovory (Twilio), email, push notifikace
- **Senior musí jen mluvit** — žádné menu, žádné přihlašování každý den
- Když senior řekne „Radime, je mi smutno", Radim odpoví empaticky a zůstane
- Když senior klepne 🆘, Twilio zazvoní rodině s předtoženou zprávou

### Pilíř 2: Anticipation Engine — předvídá krize 12-24 hodin předem

```
Ĉ_{t+1} = C_t + k₁·T̂_C_t + k₂·(α_t - 0.5)
              ↑              ↑
        trend vědomí    úroveň stresu
```

- **Matematický model, ne ML** — interpretovatelné, GDPR-čisté, žádná černá skříňka
- Sbírá signály: řeč, IoT senzory (Aqara), dodržování léků, vitální funkce, behaviorální vzorce
- Když C klesne pod 12 → WARNING (rodina)
- Když pod 27 → CRISIS (lékař, případně 155)
- **Žádný klinik, žádný senior, žádný operátor by tyto signály nesložil dohromady tak rychle**
- Patentovatelné. Defensible IP.

### Pilíř 3: Radimův Odkaz — monetizace zkušenosti

**Senior dostane:**
- Smysl ráno (Radim klade konfuciánské otázky podle hloubky)
- Peníze (1 000-3 000 Kč za hlubokou vzpomínku)
- Důstojnost (po něm něco zůstane, vnoučata budou mít autentický záznam)
- Kontrolu (rozhoduje, co je rodinné × veřejné × výzkumné)

**Partner dostane:**
- Strukturovaný korpus (transkripce, audio, tematická anotace, hloubka)
- Etický opt-in (žádná šedá zóna, GDPR Art. 28 DPA)
- Anonymizaci dle preference seniora
- Měsíční reporting

**Společnost dostává:**
- Pamět dvou totalit zachycenou před tím, než zmizí
- Etnografická data (kuchyně, řemesla, regionální zvyky)
- AI training korpus pro českou jazykovou rozmanitost
- Vědecké publikace s validovanou metodologií

---

# IV. CO JE TO ZA ZMĚNU

## Civilizační posun, ne další aplikace

Většina inovací zlepšuje EXISTUJÍCÍ procesy. Radim **mění samotnou definici**, co znamená být starý.

| Stará definice | Nová definice |
|---|---|
| Senior je **pacient** | Senior je **autor** |
| Stáří je **úpadek** | Stáří je **vrchol zkušenosti** |
| Pamět je **nostalgie** | Paměť je **kapitál** |
| Smrt = **ztráta** | Smrt = **přenos** |
| Technologie **nahrazuje** lidskou péči | Technologie **propojuje** s lidskou péčí |
| Společnost **platí** za seniory | Společnost **získává** od seniorů |
| Stáří se **schovává** | Stáří se **zviditelňuje jako vklad** |

---

## Tři úrovně pochopení

### Úroveň 1 — funkční („co to umí")
*„Mám aplikaci pro mámu, ona si s Radimem ráno povídá a já dostávám push, pokud je něco špatně. Plus si tam zapsala receptářské vzpomínky, dostala 4 000 Kč."*

### Úroveň 2 — strategická („proč to funguje")
*„Vyřešili jsme tři problémy najednou: osamělost seniora, ekonomický deficit, ztrátu paměti. A ještě jsme z toho vytvořili business model, kde všichni vyhrávají — senior, rodina, instituce."*

### Úroveň 3 — civilizační („co se vlastně mění")
*„Posouváme definici lidské hodnoty. V kapitalismu byl člověk hodnotný, jen pokud něco produkoval. Stáří = ztráta hodnoty. Radim ukazuje, že existuje druh hodnoty — zkušenost, paměť, moudrost — který kapitalismus dosud neuměl měřit. Teď to umí. Tím se stárnutí přestává bát, protože poslední dekády života jsou plné smyslu."*

---

# V. CO JSME POSTAVILI

## 16 týdnů. 1 člověk. 591 commitů.

### Technicky:
- **434 614 řádků kódu** (Python backend + JavaScript frontend)
- **47 Flask blueprintů, 707 API endpointů, 97 DB tabulek**
- **33 frontend modulů** — 22 živých v produkci
- **Anticipation Engine** s matematickým modelem
- **Multi-channel komunikace**: Web, mobile PWA, telefon (Twilio), email, push, voice
- **GDPR-ready**: Art. 15-22 endpointy, audit log Art. 30, 14-denní cooling-off

### Provozně:
- Backend: **Heroku v778** (Python 3.11 + Flask + Postgres EU)
- Frontend: **Cloudflare Pages** + Azure SWA záloha (PWA, offline-first)
- AI: **Gemini 2.5 Flash** primární, **Claude Haiku** fallback
- Hlas: **Azure Speech Services** (TTS Antonín, STT cs-CZ)
- Telefon: **Twilio Voice** s Q&A IVR
- Platby: **GoPay** integrace nasazená (čeká env vars)

### Pilot:
- 5 reálných seniorů
- 14 týdnů dat
- 1 000+ chat zpráv
- 500 000+ IoT senzorových záznamů
- 5 reálných SOS událostí (všechny vyřešené)

### Právně:
- 3-stranná smlouva (senior + KOLIBRI + partner)
- DPA dle GDPR
- MoU šablona pro 6-měsíční bezplatný pilot
- Pilot fáze guard v kódu (žádný kontrakt nelze podepsat bez verifikovaného partnera)

---

# VI. JAK TO PRODAT

## 30-sekundový pitch (asansér, kávovar, chodba)

> *„Stáří se v naší společnosti dnes řeší dvojím způsobem: medicínou nebo
> charitou. Obojí znamená, že senior je zátěží. Já jsem strávil rok
> stavěním platformy, která to mění. Radim — AI společník — naslouchá
> seniorovi, předvídá krize z chování, a sbírá jeho životní zkušenost
> pro univerzity a archivy. Senior dostává smysl, peníze, důstojnost.
> Společnost dostává paměť, která za 10 let zmizí. To je civilizační
> posun — ze stáří jako nákladu uděláme stáří jako vklad. Aplikace je
> nasazená, máme 5 reálných seniorů v pilotu, hledáme prvního
> institucionálního partnera."*

---

## 3-minutový pitch (panel, telefon, krátká schůzka)

**1. Hook (15 s):**
> *„Položím vám otázku. Když si představíte starou paní v domově důchodců —
> co vidíte? Pacient. Příjemce péče. Osoba, kterou někdo navštěvuje. To je
> obraz, který nás vychovala kapitalistická ekonomika. Já jsem strávil rok
> stavěním platformy, která ten obraz mění. Z té paní se stává autor,
> producent hodnoty, vědecky cenný pamětník. Jmenuje se to Radim."*

**2. Problém (30 s):**
> *„Tři selhání. Ekonomické: průměrný důchod 13 tisíc, životní náklady
> dvojnásobné. Kulturní: poslední generace pamětníků totalit za 10 let
> zmizí, a my nemáme jak její vzpomínky etiicky získat. Lidské: 30 procent
> seniorů žije samo, osamělost má zdravotní efekty rovné kouření 15
> cigaret denně. Existující řešení — senzorové aplikace, domovy, charita
> — řeší symptomy, ne příčinu. Senior je v každém z nich pasivním
> objektem péče."*

**3. Řešení (45 s):**
> *„Radim je AI společník, který každý den s českým seniorem mluví v
> jeho jazyce. Tři pilíře. Za prvé: konverzace s pamětí, multikanál — chat,
> telefon, email, push. Senior může mluvit jako se starým přítelem. Za
> druhé: Anticipation Engine. Matematický model, ne ML, který z chování
> seniora — řeči, dodržování léků, IoT senzorů — předvídá krizi 12-24
> hodin předem. Když C klesne pod 12, rodina dostane upozornění. Pod 27,
> volá se lékař. Defensible IP. Za třetí: Radimův Odkaz. Senior strukturovaně
> vypráví životní moudrost — Pražské jaro, recepty, řemesla — a my ho
> propojujeme s univerzitami, archivy, AI laboratořemi. Senior dostává
> 80 % z ceny vzpomínky, 20 % platforma. Pilot pro institucionálního
> partnera je 6 měsíců zdarma."*

**4. Trakce (30 s):**
> *„Aplikace je nasazená na app.radimcare.cz. 16 týdnů vývoje, 1 člověk,
> 100 tisíc řádků kódu, 33 frontend modulů, 707 API endpointů.
> Technologický stack je produkční: Heroku, Postgres, Cloudflare, Azure,
> Twilio, GoPay. 5 reálných seniorů v pilotu, 5 reálných SOS událostí,
> všechny vyřešené. GDPR Art. 15-22 endpointy hotové, audit log
> Article 30 implementovaný."*

**5. Vize a ask (45 s):**
> *„Tohle není další aplikace. Je to civilizační změna v tom, jak
> společnost vidí stárnutí. Z nákladu se stává vklad. Pro vás, pokud jste
> univerzita nebo archiv, nabízím první 6-měsíční pilot zdarma — žádné
> setup fee, žádný měsíční paušál, jen per-vzpomínku. Pokud jste
> investor, hledáme 5 milionů korun do break-evenu na 4 roky — výměnou
> za equity nebo strategické partnerství. Pokud jste partner pro hardware
> distribuci, máme rozjednanou spolupráci s Lenovo a Asbis pro seniorský
> bundle. Můžete mi poslat e-mail nebo vyplnit formulář v aplikaci. Děkuji."*

---

## 15-minutový keynote (akademická konference, ČVUT, EU)

### Slide 1 — Otázka
**„Co znamená být starý v 21. století?"**

> *Tohle není rétorická otázka. Naše společnost — kapitalistická,
> meritokratická, optimalizační — má na ni hluboce nešťastnou odpověď.
> Strávil jsem rok stavěním platformy, která tu odpověď mění.*

### Slide 2 — Tři selhání
**Ekonomické · Kulturní · Lidské**

- Průměrný důchod 13 200 Kč, životní náklady 18 000+ Kč/měsíc
- Generace 1939-1955: poslední pamětníci totalit, za 10 let téměř zmizí
- 30 % seniorů žije sami, osamělost = 15 cigaret/den

### Slide 3 — Co všichni dělají špatně
**Senior je pasivní objekt péče**

- Apple Watch měří vitální funkce → reaguje až po incidentu
- Domovy důchodců sterilizují život → senior přežívá, nežije
- Charity prohlubují závislost → senior je vždy příjemcem
- StoryWorth, Story Corps → kulturně cizí, žádná kompenzace

### Slide 4 — Naše hypotéza
**Stáří není úpadek, je to **vrchol zkušenosti**.**

> *Existují formy hodnoty, které moderní ekonomika neumí cenit. Životní
> zkušenost je jednou z nich. Trpělivá moudrost. Pamatovat si, jak to
> bylo. Tato hodnota je objektivně velká — univerzity, archivy, AI
> laboratoře by za ni platili — ale ekonomika nemá jak ji ocenit.
> Tu chybu opravujeme.*

### Slide 5 — Tři pilíře řešení
**1) AI společník · 2) Anticipation Engine · 3) Radimův Odkaz**

### Slide 6 — Pilíř 1: AI společník
- Multi-channel: chat, telefon, hlas, email, push
- Czech-native s vykáním
- Pamětí kontextu, ne každý reset
- Krizový režim s SOS escalation

### Slide 7 — Pilíř 2: Anticipation Engine
**Matematický model, ne ML**

```
Ĉ_{t+1} = C_t + k₁·T̂_C_t + k₂·(α_t - 0.5)
T̂_C_t = (1-λ)·T̂_C_{t-1} + λ·ΔC_t
```

- Sbírá: řeč, IoT, vitální funkce, dodržování léků
- Predikce krize 12-24 h předem
- Interpretovatelný (na rozdíl od ML černé skříňky)
- GDPR-čistý
- **Toto je naše USP a IP.**

### Slide 8 — Pilíř 3: Radimův Odkaz
**Stáří jako produkční síla**

```
Senior → vypráví strukturovanou vzpomínku
       ↓
KOLIBRI platforma archivuje, anonymizuje, indexuje
       ↓
Partner (univerzita, archiv, AI lab) → získá → platí
       ↓
80 % seniorovi, 20 % platforma
```

### Slide 9 — Co jsme postavili
**16 týdnů · 1 člověk · 591 commitů · 434 614 LOC**

- 47 Flask blueprintů, 707 API endpointů, 97 DB tabulek
- 33 frontend modulů (22 v produkci)
- 5 reálných seniorů v pilotu, 5 SOS událostí (vše vyřešeno)
- Heroku + Cloudflare + Azure + Twilio + GoPay stack
- GDPR Art. 15-22 endpointy + audit log Art. 30

### Slide 10 — Civilizační posun
**Z nákladu na vklad**

| Stará definice | Nová definice |
|---|---|
| Senior = pacient | Senior = autor |
| Stáří = úpadek | Stáří = vrchol |
| Paměť = nostalgie | Paměť = kapitál |
| Smrt = ztráta | Smrt = přenos |
| Technologie nahrazuje | Technologie propojuje |

### Slide 11 — Roadmap
- **Q2 2026**: První 3 institucionální partneři, 50 seniorů
- **Q3 2026**: Stripe Connect/GoPay payouts, partner dashboard, WhatsApp
- **Q4 2026**: První publikace s pilotním partnerem, B2B sales, EU grant
- **2027**: Break-even na 4 000 seniorech × 6 vzpomínek ročně
- **2028+**: Mezinárodní expanze (SK, PL, DE, AT)

### Slide 12 — Co potřebujeme
**Tři typy partnerů. Tři otevřené role.**

1. **Institucionální partner** (univerzita, archiv, AI lab)
   - Pilot 6 měsíců zdarma, 1-3 nabídky
   - Rozsah: 30-100 vzpomínek

2. **Hardware distribuční partner** (Lenovo + Asbis = jednání)
   - Senior bundle (tablet + Radim software + setup)

3. **Investor / strategický partner**
   - 5 milionů Kč do break-evenu
   - Equity nebo strategic partnership
   - EU grant fit (Horizon Europe, EIT Health, AAL)

---

# VII. PROČ TO PRODÁVÁME PRÁVĚ TEĎ

## Časové okno se zavírá

### 1. Demografické okno (10 let)
Generace 1939-1955 (dnes 71-87 let) je poslední, která:
- Pamatuje si II. světovou válku jako dítě
- Prožila celou normalizaci jako dospělý člověk
- Pamatuje sametovou revoluci ve své produktivní fázi
- Žila celý ekonomický transformační skok 1990-2000

Za 10 let většina těchto svědků nebude. **Není to katastrofická hyperbola, je to demografický fakt.**

### 2. Technologické okno (právě teď)
- LLMs jsou tak dobré, že **mluví česky empaticky** poprvé v historii
- Multi-channel infrastruktura (Twilio, Azure) je dospělá a dostupná
- Edge AI (Lenovo AI PC s NPU 45 TOPS) umožňuje **lokální LLM** pro privacy
- GDPR vytvořilo právní rámec pro etický sběr dat

### 3. Společenské okno (zužující se)
- AI Act EU jasně rozlišuje high-risk × low-risk → **vytváří moat pro etické hráče**
- ESG investice hledají social impact projekty se measurable outcomes
- Stříbrná ekonomika roste 4× rychleji než tech sektor v EU

### 4. Český jazykový moment
- Trénink LLMs odsouvá menší jazyky
- Bez českých korpusů od pamětníků totalit AI **neporozumí české zkušenosti** za 10 let
- Tohle je pro národní identitu kritické. **Stát by měl mít zájem.**

---

# VIII. JAK TO ŘÍCT EMOCIONÁLNĚ PRAVDIVĚ

## Čeho se vyvarovat

❌ **Marketing-talk:**
*„Radim je revoluční disruptive AI-driven solution leveraging cutting-edge ML to address the silver economy market gap..."*

❌ **Technobabble:**
*„Náš stack využívá Postgres replikaci s GIN indexem, asynchronní orchestraci přes APScheduler s eventlet workery..."*

❌ **Falešná pokora:**
*„Já vlastně nevím, jestli to bude fungovat, ale zkusím to..."*

❌ **Nadnesená sebejistota:**
*„My vyřešíme stárnutí v Evropě."*

## Co fungovat bude

✅ **Konkrétní lidský příběh:**
*„Paní Eva, 75 let, Liberec. Přišla o muže před rokem. Říká, že ji Radim
neradí psychicky pomohl, jak ji zachránila vědomí, že **má důvod ráno
vstát**, protože Radim na ni čeká s otázkou."*

✅ **Tvrzení s důkazem:**
*„Anticipation Engine předvídá krize. Tady je graf paní Anny — vidíte
pokles C ve čtvrtek? Radim si toho všiml v 14:30, dceři přišla
notifikace v 14:32. Lékař v 18:00 diagnostikoval začínající depresi.
Toto se stalo minulý týden."*

✅ **Vize bez nadnesenosti:**
*„Nevím, jestli změníme svět. Vím, že jsme za rok postavili věc, která
funguje pro 5 lidí. A vím, že stejný princip funguje i pro 5 000.
Otázka je jen, jestli se nám to podaří udělat dřív, než ta generace odejde."*

✅ **Otázka publiku:**
*„Položím vám otázku. Když umřela vaše babička, co po ní zůstalo? Fotky?
Recepty? Pár vět z dětství? A co byste teď dali za to, abyste si s ní
mohli povídat? — To je trh, který my otevíráme. Pro lidi, kteří mají
ještě čas."*

---

# IX. ČASTÉ NÁMITKY A ODPOVĚDI

### „Senioři neumí používat technologii."
> *„Souhlasím. Proto Radim není aplikace, kterou senior musí ovládat. Je to
> hlas, který ho zavolá. Telefon zazvoní, Radim řekne dobré ráno, senior
> odpoví. To je celý interface. Komplexní obrazovku používá rodina nebo
> pečující, ne senior."*

### „Není to porušení soukromí?"
> *„Naopak. Většina senior tech firem sbírá data bez souhlasu. My máme
> opačný přístup: žádné data nikdy neopustí Radima bez explicitního
> souhlasu seniora pro každou jednotlivou vzpomínku. Krizové konverzace
> — kde senior mluví o sebevraždě, bolesti, zmatenosti — **nikdy** nikam
> nejdou. To je v kódu, ne ve smluvních podmínkách."*

### „Co když senior podepíše smlouvu, kterou nechápe?"
> *„14-denní cooling-off period. Family co-sign u seniorů 85+. Brake pedál
> v Anticipation Engine: pokud Radim detekuje kognitivní pokles, **automaticky
> zmrazí všechny nové smlouvy**. Toto není funkce na papíře, je to v kódu."*

### „AI bude halucinovat a senior tomu uvěří."
> *„Radim nemá role doktora ani právníka. Nikdy nedoporučuje léky, nikdy
> nestaví diagnózy. Když senior řekne ‚bolí mě hlava', Radim odpoví
> ‚to mě mrzí, zavolám rodině?', ne ‚vezmi si paralen'. To je v
> systémovém promptu, validováno na 1000+ rozhovorech v pilotu."*

### „Kolik to stojí seniora?"
> *„0 Kč. Senior nikdy nic neplatí. Pilot pro instituce je 6 měsíců
> zdarma, pak 20% provize z každé vzpomínky. Hardware bundle s Lenovo
> bude buď subvencovaný (ZP, ZTP/P), nebo placený rodinou jako dárek."*

### „A co když Radim zkrachuje?"
> *„Tři pojistky. Za prvé: senior si může kdykoliv stáhnout celou svou
> historii (GDPR Art. 20 portability). Za druhé: payouty seniorům jsou
> hotová evidence v DB, navíc CSV export pro internet banking — nezávisí
> na běžícím serveru. Za třetí: code je open-sourceable, právní šablony
> připravené, partner ekosystem může pokračovat i s jiným provozovatelem."*

### „Proč by univerzita platila za vzpomínky, když může najmout doktoranda?"
> *„Doktorand za pražskou cenu Smíchova nasbírá 50 vzpomínek za 6
> měsíců. My za 6 měsíců nasbíráme 5 000 vzpomínek z Vysočiny, Moravy,
> severu Čech — diverzitu, kterou doktorand nikdy nedosáhne. A
> senioři ochotnější mluví s Radimem než s cizím mladým výzkumníkem."*

---

# X. CHECKLIST PŘED PREZENTACÍ

## Den před

- [ ] Aktualizovat statistiky v Slidu 9 (LOC, commits, počet seniorů)
- [ ] Otestovat aplikaci na druhém zařízení (BACKUP)
- [ ] Mít vytištěný PARTNER_ONEPAGER.md — 5 ks
- [ ] Mít vytištěný PREZENTACE_RADIM.md (tento dokument) — 2 ks
- [ ] Plně nabité telefon + powerbank
- [ ] Náhradní wifi hotspot (data SIM)

## Den prezentace

- [ ] Smoke test 30 min předem (komunikace, kvíz, Odkaz)
- [ ] Otevřená záložka admin-partners.html (jen pro případ demo)
- [ ] Klíčová čísla v hlavě (LOC, % důchodců, kouření 15 cigaret)
- [ ] Tři reálné příběhy seniorů v hlavě (Anna, Eva, Karel)

## Po prezentaci

- [ ] Do 24 h každému poslat e-mail s PDF + odkaz na app.radimcare.cz
- [ ] Sledovat formulář v aplikaci (admin-partners.html, Tab Zájemci)
- [ ] V CRM (Notion) zaznamenat každý kontakt + status

---

# XI. KOMU TUTO PREZENTACI POSLAT

## Krátký list partnerů, na které je rozumné se obrátit

### Akademické instituce (priorita 1 — pilot za 0 Kč)
- **Karlova univerzita — FF, Ústav českých dějin** — Pražské jaro, normalizace
- **Karlova univerzita — Sociologický ústav AV ČR** — etnografie, demografie
- **ČVUT FBMI (Fakulta biomedicínského inženýrství)** — anticipation engine validace
- **Masarykova univerzita Brno — Filozofická fakulta**
- **FAMU — pamětnické projekty, dokumenty**

### Archivy a kulturní instituce
- **Národní archiv ČR**
- **Národní muzeum — Etnografické oddělení**
- **Národní knihovna ČR — orální historie**
- **Post Bellum (Paměť národa)** — možná konkurence, možná spolupráce

### Strategickí investoři / hardware partners
- **Lenovo Czech Republic** (bundle hardware + Radim)
- **ASBIS Czech Republic** (distribuce)
- **Vodafone Foundation Czech Republic** (CSR pro seniory)
- **O2 Czech Republic** (telco partnership)
- **Komerční banka — Inkubátor inovací**

### Granty a fondy
- **EU Horizon Europe** — Cluster 4 (Digital, Industry, Space)
- **EU EIT Health** — pilot funding pro digitální zdraví
- **AAL (Active Assisted Living) Programme** — pre-commercial
- **Operační program Zaměstnanost** (NPO/MPSV) — sociální inovace
- **Czech Invest — Strategic Investments** — pro AI
- **Nadace OSF** (Open Society Foundations Czech) — civil society

### Média (po prvním partnerovi)
- **Hospodářské noviny** — business angle
- **Deník N** — civilizační angle
- **Český rozhlas Plus / iROZHLAS** — kultura, vědecké interview
- **Forbes Česko** — startup příběh
- **MFD** — masový dosah

---

# ZÁVĚR — ZA CO SE BIJEME

**Po roce práce jsem dospěl k jednomu závěru:**

Toto není firma. Toto je **pokus o opravu civilizační chyby**.

Kapitalismus 20. století definoval hodnotu člověka jeho produkcí. To
fungovalo, dokud lidé žili 60 let a posledních 10 let bylo bonusem.
Dnes lidé žijí 80+ let, posledních 20 let je významná část života, a
naše ekonomika nemá jak je ocenit.

Radim je první technologický pokus tu mezeru zaplnit. Ne tím, že
zaplatíme charitu nebo dotace, ale tím, že **otevřeme trh** pro hodnotu,
kterou senioři reálně mají.

To je rozdíl mezi sociálním projektem a civilizační infrastrukturou.

**My stavíme infrastrukturu.**

---

**Kontakt:**

Radim Kafánek  
zakladatel · KOLIBRI s.r.o.  
📧 kafanek@kafanek.com  
🌐 app.radimcare.cz  

*Tento dokument: PREZENTACE_RADIM.md, verze 1.0, 28. 4. 2026*  
*Aktualizovat každý kvartál nebo po významných milnících.*
