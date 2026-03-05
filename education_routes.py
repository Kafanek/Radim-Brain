# ============================================
# 🎓 RADIM EDUCATION API BLUEPRINT
# ============================================
# Version: 1.0.0 — Vzdělávací modul: Vzácná onemocnění
# Endpoints: /api/education/*
# Focus: Disfázie, vzácné neurodegenerativní a vývojové poruchy

from flask import Blueprint, request, jsonify
from datetime import datetime
import json

education_bp = Blueprint('education', __name__)

# ============================================
# HELPER
# ============================================

def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


# ============================================
# 📚 VZDĚLÁVACÍ KURZY — VZÁCNÁ ONEMOCNĚNÍ
# ============================================

EDUCATION_COURSES = {
    # ─────────────────────────────────────────
    # DISFÁZIE — hlavní kurz
    # ─────────────────────────────────────────
    "dysphasia": {
        "id": "dysphasia",
        "title": "Disfázie — porozumění a komunikace",
        "subtitle": "Jak porozumět lidem s disfázií a jak s nimi komunikovat",
        "icon": "🗣️",
        "category": "Poruchy řeči",
        "difficulty": "beginner",
        "duration_minutes": 45,
        "tags": ["disfázie", "řeč", "komunikace", "rehabilitace", "CMP"],
        "description": "Kompletní průvodce disfázií — vývojovou i získanou. Naučíte se, co disfázie je, jak se projevuje, jak správně komunikovat a jak můžete pomoci.",
        "target_audience": ["pečovatelé", "rodina", "zdravotníci", "senioři"],
        "learning_objectives": [
            "Pochopíte rozdíl mezi disfázií a afázií",
            "Rozpoznáte projevy vývojové i získané disfázie",
            "Naučíte se správné komunikační techniky",
            "Pochopíte rehabilitační možnosti",
            "Budete vědět, kdy vyhledat odborníka"
        ],
        "modules": [
            {
                "id": "dysphasia-m1",
                "title": "Co je disfázie?",
                "order": 1,
                "duration_minutes": 8,
                "icon": "📖",
                "lessons": [
                    {
                        "id": "dysphasia-m1-l1",
                        "title": "Definice a základní pojmy",
                        "type": "article",
                        "content": """<h2>Co je disfázie?</h2>
<p><strong>Disfázie</strong> je částečná porucha schopnosti rozumět řeči nebo ji produkovat. Na rozdíl od <em>afázie</em> (úplná ztráta řeči) jde o mírnější formu — člověk komunikovat dokáže, ale s obtížemi.</p>

<h3>Dva hlavní typy</h3>
<ul>
<li><strong>Vývojová disfázie</strong> — vrozená, projevuje se u dětí. Dítě se učí mluvit pomaleji a s obtížemi, přestože má normální inteligenci a sluch.</li>
<li><strong>Získaná disfázie</strong> — vzniká po poškození mozku (cévní mozková příhoda, úraz hlavy, nádor). Člověk, který dříve mluvil normálně, má náhle problémy s řečí.</li>
</ul>

<h3>Důležité rozlišení</h3>
<table>
<tr><th>Pojem</th><th>Význam</th></tr>
<tr><td>Disfázie</td><td>Částečná porucha řeči (lehčí forma)</td></tr>
<tr><td>Afázie</td><td>Úplná nebo téměř úplná ztráta řeči</td></tr>
<tr><td>Dysartrie</td><td>Porucha motoriky řeči (svalů) — člověk ví co říct, ale svaly nespolupracují</td></tr>
<tr><td>Dysfagie</td><td>Porucha polykání (jiný problém!)</td></tr>
</table>

<p class="key-point">💡 <strong>Klíčové:</strong> Disfázie NENÍ mentální postižení. Inteligence je zachovaná. Člověk ví, co chce říct — jen to nemůže vyjádřit tak, jak by chtěl.</p>""",
                        "key_points": [
                            "Disfázie = částečná porucha řeči, mírnější než afázie",
                            "Existuje vývojová (vrozená) a získaná (po úrazu/CMP) forma",
                            "Inteligence je vždy zachovaná — problém je jen v řečovém vyjádření",
                            "Neplést s dysartrií (motorika) ani dysfagií (polykání)"
                        ]
                    },
                    {
                        "id": "dysphasia-m1-l2",
                        "title": "Jak často se disfázie vyskytuje?",
                        "type": "article",
                        "content": """<h2>Výskyt disfázie v populaci</h2>

<h3>Vývojová disfázie</h3>
<ul>
<li>Postihuje přibližně <strong>3–7 % dětí</strong> předškolního věku</li>
<li>Chlapci jsou postiženi <strong>2–3× častěji</strong> než dívky</li>
<li>U mnoha dětí se stav výrazně zlepší logopedickou péčí</li>
<li>Přibližně 50 % dětí s vývojovou disfázií má obtíže i v dospělosti</li>
</ul>

<h3>Získaná disfázie (po CMP/úrazu)</h3>
<ul>
<li>Přibližně <strong>30–40 % lidí po CMP</strong> má nějakou formu poruchy řeči</li>
<li>Z toho cca polovina má disfázii (lehčí forma), polovina těžší afázii</li>
<li>V ČR prodělá CMP ročně cca 40 000 lidí — tedy tisíce nových případů ročně</li>
<li>S kvalitní rehabilitací se mnozí výrazně zlepší, zejména v prvních 6 měsících</li>
</ul>

<p class="key-point">💡 <strong>Disfázie rozhodně není vzácná!</strong> Pravděpodobně znáte někoho, kdo jí trpí nebo trpěl. Porozumění a trpělivost okolí hraje v uzdravení klíčovou roli.</p>""",
                        "key_points": [
                            "Vývojová disfázie: 3–7 % dětí, chlapci 2–3× častěji",
                            "Získaná: 30–40 % lidí po CMP má poruchu řeči",
                            "V ČR tisíce nových případů ročně",
                            "Rehabilitace je nejúčinnější prvních 6 měsíců"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dysphasia-m1-quiz",
                    "title": "Ověřte si znalosti: Co je disfázie?",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Co je hlavní rozdíl mezi disfázií a afázií?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Disfázie je částečná porucha, afázie je úplná ztráta řeči", "correct": True},
                                {"id": "b", "text": "Disfázie postihuje děti, afázie dospělé", "correct": False},
                                {"id": "c", "text": "Disfázie je porucha polykání, afázie porucha řeči", "correct": False}
                            ],
                            "explanation": "Disfázie je mírnější forma — člověk komunikovat může, ale s obtížemi. Afázie je těžší forma, kde je řeč výrazně narušena nebo zcela ztracena."
                        },
                        {
                            "id": "q2",
                            "question": "Je pravda, že disfázie znamená sníženou inteligenci?",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! Inteligence je při disfázii vždy zachovaná. Člověk ví, co chce říct — jen to nemůže snadno vyjádřit. Toto je jeden z nejčastějších a nejškodlivějších mýtů."
                        },
                        {
                            "id": "q3",
                            "question": "Kolik procent lidí po CMP má nějakou poruchu řeči?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Asi 5 %", "correct": False},
                                {"id": "b", "text": "Asi 30–40 %", "correct": True},
                                {"id": "c", "text": "Asi 80 %", "correct": False}
                            ],
                            "explanation": "Přibližně 30–40 % lidí po cévní mozkové příhodě má nějakou formu poruchy řeči. Je to velmi častý následek."
                        }
                    ]
                }
            },
            {
                "id": "dysphasia-m2",
                "title": "Vývojová disfázie u dětí",
                "order": 2,
                "duration_minutes": 10,
                "icon": "👶",
                "lessons": [
                    {
                        "id": "dysphasia-m2-l1",
                        "title": "Jak se projevuje vývojová disfázie",
                        "type": "article",
                        "content": """<h2>Projevy vývojové disfázie</h2>
<p>Vývojová disfázie se projevuje různě u každého dítěte. Klíčové je, že dítě má <strong>normální inteligenci, normální sluch</strong>, ale přesto se učí mluvit výrazně pomaleji.</p>

<h3>Typické projevy</h3>

<h4>V řeči (expresivní složka)</h4>
<ul>
<li>Pozdní začátek řeči — první slova po 2. roce, věty po 3.–4. roce</li>
<li>Malá slovní zásoba ve srovnání s vrstevníky</li>
<li>Obtíže se stavbou vět — špatný slovosled, vynechávání slov</li>
<li>Záměny hlásek a zkomolená slova ("kolomobil" místo "automobil")</li>
<li>Obtíže s vyprávěním — těžko převypráví příběh nebo popíše zážitek</li>
</ul>

<h4>V porozumění (receptivní složka)</h4>
<ul>
<li>Obtíže s porozuměním složitějším pokynům</li>
<li>Problém s rozlišením podobně znějících slov</li>
<li>Dítě "neslyší" — ve skutečnosti nerozumí, ale slyší výborně</li>
<li>Obtíže s abstraktními pojmy (ale konkrétní věci chápe)</li>
</ul>

<h4>Další průvodní znaky</h4>
<ul>
<li>Obtíže s pamětí na slova (pamatuje si věci, ale ne jejich názvy)</li>
<li>Možné obtíže s jemnou motorikou a koordinací</li>
<li>Někdy frustrace a emoční výbuchy (protože se nemůže vyjádřit)</li>
<li>V kolektivu se může stáhnout (pokud ho ostatní nerozumějí)</li>
</ul>

<p class="key-point">💡 <strong>Důležité pro rodiče:</strong> Pokud vaše dítě ve 2 letech nemluví nebo ve 3 letech nestaví věty, není důvod panikařit — ale je důvod navštívit logopeda. Čím dříve začne péče, tím lepší výsledky.</p>

<h3>Co vývojová disfázie NENÍ</h3>
<ul>
<li>Není to lenost ani neposlušnost</li>
<li>Není to vina rodičů ("málo jsme s ním mluvili")</li>
<li>Není to mentální postižení</li>
<li>Není to autismus (i když se některé projevy mohou podobat)</li>
</ul>""",
                        "key_points": [
                            "Pozdní začátek řeči, malá slovní zásoba, špatný slovosled",
                            "Rozumění bývá lepší než produkce řeči",
                            "Může být provázeno frustrací a stažením se",
                            "NENÍ to lenost, vina rodičů ani mentální postižení",
                            "Včasná logopedická péče je klíčová"
                        ]
                    },
                    {
                        "id": "dysphasia-m2-l2",
                        "title": "Jak komunikovat s dítětem s disfázií",
                        "type": "article",
                        "content": """<h2>Komunikační zásady pro dítě s vývojovou disfázií</h2>

<h3>✅ CO DĚLAT</h3>

<h4>1. Kratší věty, jedna instrukce</h4>
<p>Místo: <em>"Jdi do pokojíčku, oblékni si tepláky a přijď na snídani"</em><br>
Říkej: <em>"Jdi do pokojíčku."</em> (počkej) → <em>"Oblékni si tepláky."</em> (počkej) → <em>"Pojď na snídani."</em></p>

<h4>2. Dej čas na odpověď</h4>
<p>Počítej v duchu do 10, než zareaguješ. Dítě potřebuje víc času na zpracování a odpověď. Ticho není problém — je to čas na přemýšlení.</p>

<h4>3. Zrcadli a rozšiřuj</h4>
<p>Dítě řekne: <em>"Kočka tam"</em><br>
Ty řekneš: <em>"Ano! Kočka je tam venku na zahradě!"</em><br>
→ Potvrdíš, že rozumíš + přirozeně ukážeš správnou formu, aniž bys opravoval.</p>

<h4>4. Oceňuj snahu, ne správnost</h4>
<p><em>"Super, že jsi mi to řekl!"</em> je lepší než <em>"Řekni to správně."</em></p>

<h4>5. Buď hravý</h4>
<p>Říkanky, písničky, hry se slovy. Dítě se učí řeč nejlíp, když se baví.</p>

<h3>❌ CO NEDĚLAT</h3>
<ul>
<li><strong>Neopravuj přímo:</strong> <em>"Neříká se 'kolomobil', říká se 'automobil'"</em> → frustruje a blokuje</li>
<li><strong>Nedoplňuj za něj:</strong> Nech dítě dokončit, i když to trvá</li>
<li><strong>Neříkej "řekni to celé" / "řekni to správně"</strong></li>
<li><strong>Nesrovnávej s vrstevníky:</strong> <em>"Tvůj kamarád už mluví lépe"</em></li>
<li><strong>Neignoruj problém:</strong> <em>"On z toho vyroste"</em> — možná ano, ale logopedie pomůže víc</li>
</ul>

<p class="key-point">💡 <strong>Zlaté pravidlo:</strong> Komunikuj S dítětem, ne NA dítě. Buď jeho parťák v řeči, ne učitel.</p>""",
                        "key_points": [
                            "Kratší věty, jedna instrukce najednou",
                            "Dej čas na odpověď (počítej do 10)",
                            "Zrcadli a rozšiřuj — neopravuj přímo",
                            "Oceňuj snahu komunikovat, ne správnost",
                            "Hravost > terapeutický přístup"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dysphasia-m2-quiz",
                    "title": "Ověřte si: Vývojová disfázie u dětí",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Dítě řekne 'kočka tam'. Jaká je nejlepší reakce?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "\"Řekni to celou větou správně.\"", "correct": False},
                                {"id": "b", "text": "\"Ano! Kočka je tam venku na zahradě!\"", "correct": True},
                                {"id": "c", "text": "Ignorovat a pokračovat v činnosti.", "correct": False}
                            ],
                            "explanation": "Nejlepší je technika 'zrcadlení a rozšíření' — potvrdíte, že rozumíte, a přirozeně ukážete správnou formu věty, aniž byste dítě opravovali."
                        },
                        {
                            "id": "q2",
                            "question": "Vývojová disfázie je způsobena tím, že rodiče s dítětem málo mluvili.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! Vývojová disfázie je neurologická porucha. Není to vina rodičů. I děti v podnětném prostředí ji mohou mít."
                        },
                        {
                            "id": "q3",
                            "question": "Kdy je správný čas navštívit logopeda?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Až když dítě začne chodit do školy", "correct": False},
                                {"id": "b", "text": "Pokud dítě ve 2 letech nemluví nebo ve 3 nestaví věty", "correct": True},
                                {"id": "c", "text": "Nikdy — dítě z toho vyroste samo", "correct": False}
                            ],
                            "explanation": "Čím dříve začne logopedická péče, tím lepší výsledky. Zlaté okno je od 2–3 let. Čekání 'až z toho vyroste' může zmeškat nejlepší období pro intervenci."
                        }
                    ]
                }
            },
            {
                "id": "dysphasia-m3",
                "title": "Získaná disfázie u dospělých",
                "order": 3,
                "duration_minutes": 12,
                "icon": "🧠",
                "lessons": [
                    {
                        "id": "dysphasia-m3-l1",
                        "title": "Příčiny a typy získané disfázie",
                        "type": "article",
                        "content": """<h2>Získaná disfázie — když řeč přijde o svou samozřejmost</h2>

<p>Představte si, že jednoho dne ráno se probudíte a nemůžete najít správná slova. Víte přesně, co chcete říct, ale slova vám unikají. Nebo je vyslovíte, ale ve špatném pořadí. Přesně tak se cítí lidé se získanou disfázií.</p>

<h3>Nejčastější příčiny</h3>
<ol>
<li><strong>Cévní mozková příhoda (CMP / mrtvice)</strong> — zdaleka nejčastější příčina (80 % případů)</li>
<li><strong>Úraz hlavy</strong> — dopravní nehody, pády</li>
<li><strong>Nádor mozku</strong> — tlak na řečová centra</li>
<li><strong>Záněty mozku</strong> — encefalitida</li>
<li><strong>Neurologické operace</strong> — po zákrocích v oblasti řečových center</li>
</ol>

<h3>Typy podle projevů</h3>

<h4>Expresivní (Brocova) disfázie</h4>
<ul>
<li>Člověk <strong>rozumí dobře</strong>, ale těžko mluví</li>
<li>Hledá slova, mluví v krátkých, neúplných větách</li>
<li>Typicky: <em>"Já... chtěl... ten... no... kafe"</em></li>
<li>Ví, že dělá chyby — proto je často frustrovaný</li>
</ul>

<h4>Receptivní (Wernickeho) disfázie</h4>
<ul>
<li>Člověk mluví plynule, ale <strong>špatně rozumí</strong></li>
<li>Řeč může znít správně, ale nedává smysl</li>
<li>Používá špatná nebo neexistující slova</li>
<li>Často si neuvědomuje, že je něco špatně</li>
</ul>

<h4>Smíšená disfázie</h4>
<ul>
<li>Kombinace obou — obtíže s porozuměním i produkcí</li>
<li>Nejčastější forma po rozsáhlejší CMP</li>
</ul>

<p class="key-point">💡 <strong>Důležité:</strong> Typ a závažnost závisí na místě a rozsahu poškození mozku. Dva lidé po CMP mohou mít úplně odlišné obtíže.</p>""",
                        "key_points": [
                            "Nejčastější příčina: CMP (80 % případů)",
                            "Expresivní typ: rozumí, ale nemůže mluvit",
                            "Receptivní typ: mluví plynule, ale špatně rozumí",
                            "Typ závisí na místě poškození mozku",
                            "Každý případ je individuální"
                        ]
                    },
                    {
                        "id": "dysphasia-m3-l2",
                        "title": "Komunikace s dospělým s disfázií",
                        "type": "article",
                        "content": """<h2>Jak komunikovat s dospělým člověkem s disfázií</h2>

<p>Člověk se získanou disfázií je <strong>stejný člověk jako předtím</strong> — se stejnými znalostmi, zkušenostmi, inteligencí a city. Jen komunikační kanál je poškozený.</p>

<h3>Základní pravidla</h3>

<h4>1. Mluvte normálně — ne jako na dítě</h4>
<p>Zjednodušte FORMU (kratší věty), ale ne OBSAH. Člověk s disfázií rozumí dospělým tématům — jen potřebuje jiný způsob komunikace.</p>

<h4>2. Dejte čas</h4>
<p>Hledání slov trvá déle. Ticho není nepříjemné — je pracovní. Počkejte klidně i 20–30 sekund.</p>

<h4>3. Nabídněte volby, ne otevřené otázky</h4>
<p>Místo: <em>"Co chcete k jídlu?"</em><br>
Říkejte: <em>"Chcete polévku, nebo řízek?"</em></p>

<h4>4. Používejte více kanálů</h4>
<ul>
<li>Psaní — někdy je snazší napsat než říct</li>
<li>Ukazování — na obrázky, předměty, mapu</li>
<li>Gesta — přirozeně doplňují řeč</li>
<li>Kreslení — schematický nákres může pomoci</li>
</ul>

<h4>5. Potvrzujte porozumění</h4>
<p><em>"Rozumím, chcete čaj. Správně?"</em><br>
Nepředstírejte, že rozumíte, když nerozumíte — je to horší než se zeptat znovu.</p>

<h3>Emocionální stránka</h3>
<ul>
<li><strong>Frustrace</strong> — představte si, že nemůžete říct, co chcete. Frustraci uznávejte: <em>"Chápu, že je to těžké."</em></li>
<li><strong>Deprese</strong> — velmi častá (30–50 % pacientů). Všímejte si změn nálady.</li>
<li><strong>Izolace</strong> — lidé se stahují, protože komunikace je únavná. Udržujte kontakt, i krátký.</li>
<li><strong>Ztráta identity</strong> — učitel, který nemůže mluvit před třídou. Řidič, který nerozumí pokynům. Buďte citliví k tomu, co řeč pro člověka znamenala.</li>
</ul>

<p class="key-point">💡 <strong>Pamatujte:</strong> 10 minut kvalitní, trpělivé konverzace pomůže víc než hodina, kde za člověka mluvíte.</p>""",
                        "key_points": [
                            "Mluvte normálně, ne jako na dítě — zjednodušte formu, ne obsah",
                            "Dejte čas (i 20–30 sekund) — ticho je pracovní",
                            "Nabídněte volby místo otevřených otázek",
                            "Používejte i psaní, ukazování, gesta",
                            "30–50 % pacientů trpí depresí — buďte citliví"
                        ]
                    },
                    {
                        "id": "dysphasia-m3-l3",
                        "title": "Rehabilitace a zotavení",
                        "type": "article",
                        "content": """<h2>Rehabilitace disfázie — cesta zpět k řeči</h2>

<h3>Klíčové období: prvních 6 měsíců</h3>
<p>Mozek se nejvíce zotavuje v prvních 3–6 měsících po poškození. Toto je "zlaté okno" pro rehabilitaci. ALE zlepšení je možné i po letech — mozek je pozoruhodně plastický.</p>

<h3>Kdo pomáhá?</h3>
<ul>
<li><strong>Klinický logoped</strong> — hlavní terapeut pro řečovou rehabilitaci</li>
<li><strong>Neurolog</strong> — sleduje základní onemocnění</li>
<li><strong>Neuropsycholog</strong> — kognitivní rehabilitace</li>
<li><strong>Ergoterapeut</strong> — denní aktivity</li>
<li><strong>Rodina a blízcí</strong> — nejdůležitější "terapeuti" v každodenním životě</li>
</ul>

<h3>Typy rehabilitace</h3>

<h4>Logopedie</h4>
<ul>
<li>Individuální cvičení zaměřená na konkrétní obtíže</li>
<li>Pojmenovávání, stavba vět, porozumění</li>
<li>Frekvence: ideálně 3–5× týdně v akutní fázi</li>
</ul>

<h4>Domácí cvičení</h4>
<ul>
<li>Pojmenovávání předmětů kolem sebe</li>
<li>Popisování obrázků</li>
<li>Zpívání známých písniček (melodie pomáhá)</li>
<li>Čtení nahlas (i pomalu a s chybami)</li>
<li>Aplikace a počítačové programy pro trénink řeči</li>
</ul>

<h4>Technologické pomůcky</h4>
<ul>
<li>Komunikační tabulky a knihy s obrázky</li>
<li>Tablety a aplikace pro augmentativní komunikaci</li>
<li>Hlasové asistenty (jako Radim!) přizpůsobené pro osoby s disfázií</li>
</ul>

<h3>Reallistická očekávání</h3>
<p>Každý člověk se zotavuje jinak. Někteří dosáhnou téměř plného zotavení, jiní si nesou trvalé obtíže. <strong>Jakékoli zlepšení je úspěch.</strong> I malý pokrok v komunikaci znamená obrovský posun v kvalitě života.</p>

<p class="key-point">💡 <strong>Motivace:</strong> Mozek se dokáže přeorganizovat a vytvořit nové nervové spoje. Pravidelné cvičení a kvalitní komunikace s okolím jsou nejlepší "léky".</p>""",
                        "key_points": [
                            "Zlaté okno: prvních 6 měsíců, ale zlepšení možné i po letech",
                            "Klinický logoped je hlavní terapeut",
                            "Domácí cvičení: pojmenovávání, zpívání, čtení nahlas",
                            "Technologie mohou výrazně pomoci",
                            "Jakékoli zlepšení je úspěch"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dysphasia-m3-quiz",
                    "title": "Ověřte si: Získaná disfázie",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Pan Karel po CMP hledá slova, mluví v krátkých větách, ale rozumí dobře. O jaký typ disfázie se jedná?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Receptivní (Wernickeho) disfázie", "correct": False},
                                {"id": "b", "text": "Expresivní (Brocova) disfázie", "correct": True},
                                {"id": "c", "text": "Dysartrie", "correct": False}
                            ],
                            "explanation": "Pan Karel má expresivní (Brocovu) disfázii — rozumí dobře, ale má obtíže s produkcí řeči. To je typický projev poškození Brocova centra v levém čelním laloku."
                        },
                        {
                            "id": "q2",
                            "question": "Paní Marie říká: 'Chci ten... no ten... co je v kuchyni... ten...' Jaký je nejlepší způsob pomoci?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Říct jí: 'Zkuste se soustředit a říct to celé.'", "correct": False},
                                {"id": "b", "text": "Nabídnout: 'Myslíte hrnek? Talíř? Konvici?'", "correct": True},
                                {"id": "c", "text": "Říct to za ni, aby se netrápila.", "correct": False}
                            ],
                            "explanation": "Nabídněte 2–3 konkrétní možnosti. To pomůže najít správné slovo přirozeně, bez tlaku. Neříkejte to za člověka — dejte mu šanci komunikovat."
                        },
                        {
                            "id": "q3",
                            "question": "Po kolika měsících od CMP už nemá smysl rehabilitace řeči?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Po 3 měsících", "correct": False},
                                {"id": "b", "text": "Po 12 měsících", "correct": False},
                                {"id": "c", "text": "Zlepšení je možné i po letech", "correct": True}
                            ],
                            "explanation": "Mozek je pozoruhodně plastický. I když je 'zlaté okno' v prvních 6 měsících, zlepšení je prokazatelně možné i po mnoha letech. Nikdy není pozdě začít nebo pokračovat."
                        }
                    ]
                }
            },
            {
                "id": "dysphasia-m4",
                "title": "Praktické situace a řešení",
                "order": 4,
                "duration_minutes": 10,
                "icon": "💡",
                "lessons": [
                    {
                        "id": "dysphasia-m4-l1",
                        "title": "Každodenní situace s disfázií",
                        "type": "scenarios",
                        "content": """<h2>Praktické scénáře — jak reagovat?</h2>
<p>Tady jsou typické situace, se kterými se můžete setkat. Ke každé uvádíme doporučenou reakci.</p>""",
                        "scenarios": [
                            {
                                "title": "U lékaře",
                                "situation": "Paní Nováková (67) přišla k lékaři po CMP. Má disfázii. Lékař se jí ptá, kde ji bolí, ale ona nemůže najít slova.",
                                "wrong_approach": "Lékař se obrátí na doprovod: 'Tak mi řekněte vy, co jí je.' — Paní Nováková se cítí neviditelná.",
                                "right_approach": "Lékař se dívá na paní Novákovou: 'Bolí vás hlava? Břicho? Záda?' — Ukazuje na části těla. Paní Nováková může ukázat nebo přikývnout.",
                                "principle": "Vždy komunikujte s člověkem, ne přes něj. Nabídněte volby a multimodální komunikaci."
                            },
                            {
                                "title": "V obchodě",
                                "situation": "Pan Dvořák (72) chce v pekárně koupit rohlíky, ale slovo 'rohlík' mu nejde vyslovit. Stojí u pultu a marně hledá slovo.",
                                "wrong_approach": "Prodavačka netrpělivě: 'Tak co to bude?' Pan Dvořák odchází bez nákupu.",
                                "right_approach": "Prodavačka ukáže na sortiment: 'Chleba? Rohlíky? Koláče?' Nebo pan Dvořák může ukázat prstem.",
                                "principle": "Trpělivost a vizuální nápověda. Ukazování je plnohodnotná komunikace."
                            },
                            {
                                "title": "V rodině",
                                "situation": "Dědeček chce říct vnučce, že měl hezký den, ale mluví pomalu a s chybami. Vnučka (15) se dívá do telefonu.",
                                "wrong_approach": "Vnučka: 'Hmm, jasně, dědo.' — Ani se nepodívá. Dědeček se příště raději nesvěří.",
                                "right_approach": "Vnučka odloží telefon, dívá se na dědečka, přikyvuje. 'To jsem ráda, dědo! A co bylo nejlepší?' — Dá mu čas odpovědět.",
                                "principle": "Plná pozornost je ten nejcennější dar. Těch 5 minut může pro člověka s disfázií znamenat celý svět."
                            },
                            {
                                "title": "Na telefonu",
                                "situation": "Pan Horák potřebuje zavolat na úřad kvůli důchodu. Má disfázii a telefonování je pro něj nejtěžší (žádná vizuální nápověda).",
                                "wrong_approach": "Volá sám, úřednice mu nerozumí, zavěsí. Pan Horák se cítí ponížený.",
                                "right_approach": "Pan Horák si předem napíše klíčová slova na papír. Nebo zavolá společně s blízkou osobou, která pomůže jen tam, kde je potřeba. Případně použije písemnou komunikaci (e-mail, datová schránka).",
                                "principle": "Příprava a alternativní komunikační kanály. Telefonování je nejtěžší — preferujte osobní kontakt nebo písemnou formu."
                            }
                        ],
                        "key_points": [
                            "Komunikujte vždy s člověkem, ne přes něj",
                            "Trpělivost a vizuální nápověda jsou klíčové",
                            "Plná pozornost je nejcennější dar",
                            "Telefonování je nejtěžší — nabídněte alternativy"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dysphasia-m4-quiz",
                    "title": "Ověřte si: Praktické situace",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Člověk s disfázií stojí v obchodě a nemůže říct, co chce. Co je nejlepší přístup prodavačky?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Říct: 'Musíte mi říct, co chcete, jinak vám nepomůžu.'", "correct": False},
                                {"id": "b", "text": "Zavolat dalšího zákazníka a člověka ignorovat.", "correct": False},
                                {"id": "c", "text": "Ukázat na sortiment a nabídnout volby: 'Chleba? Rohlíky? Koláče?'", "correct": True}
                            ],
                            "explanation": "Nabídněte konkrétní volby a vizuální nápovědu. Ukazování je plnohodnotná komunikace — nemusíte vždy mluvit."
                        },
                        {
                            "id": "q2",
                            "question": "Které komunikační prostředí je pro člověka s disfázií NEJTĚŽŠÍ?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Osobní rozhovor", "correct": False},
                                {"id": "b", "text": "Telefonování", "correct": True},
                                {"id": "c", "text": "Psaní zpráv", "correct": False}
                            ],
                            "explanation": "Telefonování je nejtěžší, protože chybí vizuální kanál — mimika, gesta, ukazování. Při osobním kontaktu může člověk využít všechny dostupné kanály."
                        }
                    ]
                }
            },
            {
                "id": "dysphasia-m5",
                "title": "Kde hledat pomoc",
                "order": 5,
                "duration_minutes": 5,
                "icon": "🏥",
                "lessons": [
                    {
                        "id": "dysphasia-m5-l1",
                        "title": "Kontakty a zdroje pomoci v ČR",
                        "type": "resources",
                        "content": """<h2>Kde hledat pomoc v České republice</h2>

<h3>Odborníci</h3>
<ul>
<li><strong>Klinický logoped</strong> — seznam na <em>www.klinickalogopedie.cz</em></li>
<li><strong>Neurolog</strong> — přes praktického lékaře nebo přímo v nemocnici</li>
<li><strong>Neuropsycholog</strong> — pro kognitivní rehabilitaci</li>
</ul>

<h3>Organizace a sdružení</h3>
<ul>
<li><strong>Asociace klinických logopedů ČR</strong> — informace, seznam odborníků</li>
<li><strong>Sdružení pro augmentativní a alternativní komunikaci (SAAK)</strong> — pomůcky pro komunikaci</li>
<li><strong>Cerebrum</strong> — sdružení pro osoby po poranění mozku</li>
<li><strong>Ictus</strong> — sdružení pro pacienty po CMP</li>
</ul>

<h3>Rehabilitační centra</h3>
<ul>
<li>Rehabilitační ústav Kladruby</li>
<li>Rehabilitační centrum Slapy</li>
<li>RÚ Hrabyně</li>
<li>Nemocniční rehabilitační oddělení (dostupná v každém kraji)</li>
</ul>

<h3>Online zdroje a aplikace</h3>
<ul>
<li>Logopedické aplikace (např. Logopedie pro dospělé)</li>
<li>Komunikační tabulky ke stažení</li>
<li><strong>Radim</strong> — hlasový asistent přizpůsobený komunikačním potřebám</li>
</ul>

<h3>Krizové kontakty</h3>
<ul>
<li><strong>155</strong> — Zdravotnická záchranná služba (při podezření na CMP — FAST test!)</li>
<li><strong>116 123</strong> — Linka bezpečí (psychická podpora)</li>
</ul>

<p class="key-point">💡 <strong>FAST test pro CMP:</strong><br>
<strong>F</strong>ace — pokleslý koutek úst?<br>
<strong>A</strong>rms — nedokáže zvednout obě ruce?<br>
<strong>S</strong>peech — nemůže mluvit nebo mluví nesrozumitelně?<br>
<strong>T</strong>ime — čas volat 155! Každá minuta se počítá!</p>""",
                        "key_points": [
                            "Klinický logoped je první kontakt pro rehabilitaci",
                            "Cerebrum a Ictus — klíčová sdružení pro pacienty",
                            "Rehabilitační centra jsou v každém kraji",
                            "FAST test: Face, Arms, Speech, Time — při podezření na CMP volejte 155"
                        ]
                    }
                ]
            }
        ]
    },

    # ─────────────────────────────────────────
    # DALŠÍ VZÁCNÁ ONEMOCNĚNÍ
    # ─────────────────────────────────────────
    "huntington": {
        "id": "huntington",
        "title": "Huntingtonova choroba — průvodce pro rodiny",
        "subtitle": "Porozumění vzácnému neurodegenerativnímu onemocnění",
        "icon": "🧬",
        "category": "Neurodegenerativní",
        "difficulty": "intermediate",
        "duration_minutes": 30,
        "tags": ["Huntington", "neurodegenerace", "genetika", "vzácné onemocnění"],
        "description": "Co je Huntingtonova choroba, jak se projevuje, jak komunikovat s nemocným a kde najít pomoc. Průvodce pro rodiny a pečovatele.",
        "target_audience": ["pečovatelé", "rodina", "zdravotníci"],
        "learning_objectives": [
            "Pochopíte podstatu Huntingtonovy choroby",
            "Rozpoznáte typické příznaky",
            "Naučíte se komunikační strategie",
            "Pochopíte genetické aspekty a testování"
        ],
        "modules": [
            {
                "id": "huntington-m1",
                "title": "Co je Huntingtonova choroba?",
                "order": 1,
                "duration_minutes": 10,
                "icon": "📖",
                "lessons": [
                    {
                        "id": "huntington-m1-l1",
                        "title": "Základy Huntingtonovy choroby",
                        "type": "article",
                        "content": """<h2>Huntingtonova choroba — základní informace</h2>

<p><strong>Huntingtonova choroba (HD)</strong> je vzácné dědičné neurodegenerativní onemocnění, které postihuje přibližně <strong>5–10 lidí na 100 000</strong>. V ČR žije odhadem 1 000–1 500 lidí s touto diagnózou.</p>

<h3>Podstata onemocnění</h3>
<ul>
<li>Způsobena mutací v genu HTT na chromozomu 4</li>
<li>Dědičnost je <strong>autozomálně dominantní</strong> — pokud má jeden rodič HD, dítě má 50% riziko</li>
<li>Obvykle se projeví mezi <strong>30. a 50. rokem</strong> života</li>
<li>Postupně se zhoršuje a zatím nemá kauzální léčbu</li>
</ul>

<h3>Tři skupiny příznaků</h3>
<ol>
<li><strong>Pohybové</strong> — mimovolní pohyby (chorea), problémy s chůzí, koordinací, polykáním a řečí</li>
<li><strong>Kognitivní</strong> — zpomalené myšlení, obtíže s plánováním, koncentrací</li>
<li><strong>Psychiatrické</strong> — deprese (velmi častá), podrážděnost, apatie, někdy psychotické příznaky</li>
</ol>

<p class="key-point">💡 <strong>Důležité:</strong> Psychiatrické příznaky (deprese, podrážděnost) se často objevují ROKY před pohybovými obtížemi. Pokud máte v rodině HD a cítíte změny nálady, poraďte se s neurologem.</p>""",
                        "key_points": [
                            "Vzácné dědičné onemocnění: 5–10 na 100 000 obyvatel",
                            "50% riziko dědičnosti od postiženého rodiče",
                            "Projevuje se obvykle mezi 30.–50. rokem",
                            "Pohybové + kognitivní + psychiatrické příznaky",
                            "Psychiatrické příznaky často předchází pohybovým"
                        ]
                    }
                ],
                "quiz": {
                    "id": "huntington-m1-quiz",
                    "title": "Ověřte si: Huntingtonova choroba",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Jaké je riziko dědičnosti, pokud má jeden rodič Huntingtonovu chorobu?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "25 %", "correct": False},
                                {"id": "b", "text": "50 %", "correct": True},
                                {"id": "c", "text": "100 %", "correct": False}
                            ],
                            "explanation": "Huntingtonova choroba se dědí autozomálně dominantně — každé dítě postiženého rodiče má 50% riziko, že gen zdědí."
                        },
                        {
                            "id": "q2",
                            "question": "Které příznaky se často objevují jako PRVNÍ?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Pohybové (chorea)", "correct": False},
                                {"id": "b", "text": "Psychiatrické (deprese, podrážděnost)", "correct": True},
                                {"id": "c", "text": "Poruchy polykání", "correct": False}
                            ],
                            "explanation": "Psychiatrické příznaky jako deprese a podrážděnost se často objevují roky před viditelnými pohybovými obtížemi. Proto je důležité být na ně pozorný."
                        }
                    ]
                }
            }
        ]
    },

    "als": {
        "id": "als",
        "title": "ALS — Amyotrofická laterální skleróza",
        "subtitle": "Průvodce komunikací a péčí",
        "icon": "💪",
        "category": "Neurodegenerativní",
        "difficulty": "intermediate",
        "duration_minutes": 25,
        "tags": ["ALS", "neurodegenerace", "komunikace", "vzácné onemocnění"],
        "description": "Jak porozumět ALS, jak komunikovat s nemocným a jaké technologické pomůcky existují.",
        "target_audience": ["pečovatelé", "rodina", "zdravotníci"],
        "learning_objectives": [
            "Pochopíte podstatu ALS",
            "Naučíte se komunikační strategie pro různé fáze",
            "Poznáte technologické pomůcky pro komunikaci",
            "Porozumíte emocionální stránce péče"
        ],
        "modules": [
            {
                "id": "als-m1",
                "title": "Co je ALS?",
                "order": 1,
                "duration_minutes": 10,
                "icon": "📖",
                "lessons": [
                    {
                        "id": "als-m1-l1",
                        "title": "Základy ALS",
                        "type": "article",
                        "content": """<h2>ALS — když tělo přestává poslouchat, ale mysl zůstává</h2>

<p><strong>Amyotrofická laterální skleróza (ALS)</strong> je vzácné neurodegenerativní onemocnění, které postihuje motorické neurony — nervy ovládající svaly. Postupně vede k oslabení a ochrnutí svalů, zatímco <strong>inteligence, paměť a vnímání zůstávají plně zachovány</strong>.</p>

<h3>Klíčová fakta</h3>
<ul>
<li>Postihuje přibližně <strong>2–3 lidi na 100 000</strong></li>
<li>Obvykle se projeví mezi 50.–70. rokem, ale může i dříve</li>
<li>Slavný pacient: Stephen Hawking (žil s ALS 55 let — výjimečný případ)</li>
<li>Průměrná prognóza: 2–5 let od diagnózy (ale variabilita je velká)</li>
</ul>

<h3>Jak ALS ovlivňuje komunikaci</h3>
<ol>
<li><strong>Rané stadium:</strong> Řeč se stává méně zřetelnou (dysartrie), hlas je tišší</li>
<li><strong>Střední stadium:</strong> Řeč je obtížně srozumitelná, je třeba opakovat</li>
<li><strong>Pozdní stadium:</strong> Řeč není možná — člověk komunikuje očima, technologiemi</li>
</ol>

<h3>Co ZŮSTÁVÁ zachováno</h3>
<ul>
<li>Inteligence a myšlení</li>
<li>Vnímání a emoce</li>
<li>Smysly (zrak, sluch, čich, chuť)</li>
<li>Paměť</li>
</ul>

<p class="key-point">💡 <strong>Nejdůležitější věta o ALS:</strong> Člověk s ALS je uvězněn v těle, které ho neposlouchá. Ale UVNITŘ je pořád ten samý člověk — chytrý, vtipný, milující. Nikdy na to nezapomínejte.</p>""",
                        "key_points": [
                            "ALS postihuje motorické neurony — svaly slábnou, mysl zůstává",
                            "Inteligence, paměť a vnímání plně zachovány",
                            "Řeč se zhoršuje postupně — od dysartrie po úplnou ztrátu",
                            "Technologické pomůcky mohou udržet komunikaci",
                            "Člověk uvnitř je pořád stejný"
                        ]
                    }
                ],
                "quiz": {
                    "id": "als-m1-quiz",
                    "title": "Ověřte si: ALS",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Které z následujících je při ALS zachováno?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Svalová síla", "correct": False},
                                {"id": "b", "text": "Inteligence a paměť", "correct": True},
                                {"id": "c", "text": "Schopnost pohybu", "correct": False}
                            ],
                            "explanation": "ALS postihuje motorické neurony (svaly), ale kognitivní funkce — inteligence, paměť, vnímání a emoce — zůstávají plně zachovány."
                        }
                    ]
                }
            }
        ]
    }
}

# ============================================
# PROGRESS TRACKING (v paměti, DB v produkci)
# ============================================

EDUCATION_PROGRESS = {}

# ============================================
# ENDPOINTS
# ============================================

@education_bp.route('/api/education/courses', methods=['GET'])
def list_courses():
    """Seznam všech vzdělávacích kurzů"""
    category = request.args.get('category', None)
    difficulty = request.args.get('difficulty', None)
    search = request.args.get('query', request.args.get('search', None))

    courses = []
    for course in EDUCATION_COURSES.values():
        # Kompaktní verze (bez modulů/lekcí)
        compact = {
            "id": course["id"],
            "title": course["title"],
            "subtitle": course.get("subtitle", ""),
            "icon": course["icon"],
            "category": course["category"],
            "difficulty": course["difficulty"],
            "duration_minutes": course["duration_minutes"],
            "tags": course["tags"],
            "description": course["description"],
            "target_audience": course.get("target_audience", []),
            "module_count": len(course.get("modules", [])),
            "learning_objectives": course.get("learning_objectives", [])
        }
        courses.append(compact)

    # Filtry
    if category:
        courses = [c for c in courses if c["category"].lower() == category.lower()]
    if difficulty:
        courses = [c for c in courses if c["difficulty"] == difficulty]
    if search:
        sl = search.lower()
        courses = [c for c in courses if
                   sl in c["title"].lower() or
                   sl in c["description"].lower() or
                   any(sl in t.lower() for t in c["tags"])]

    return jsonify({
        "success": True,
        "count": len(courses),
        "courses": courses,
        "categories": list(set(c["category"] for c in EDUCATION_COURSES.values())),
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>', methods=['GET'])
def get_course(course_id):
    """Detail kurzu — moduly a struktura (bez plného obsahu lekcí)"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({
            "success": False,
            "error": f"Kurz '{course_id}' nenalezen",
            "available": list(EDUCATION_COURSES.keys())
        }), 404

    # Vrátit kurz s modulovou strukturou, ale bez plného HTML obsahu
    course_detail = {
        "id": course["id"],
        "title": course["title"],
        "subtitle": course.get("subtitle", ""),
        "icon": course["icon"],
        "category": course["category"],
        "difficulty": course["difficulty"],
        "duration_minutes": course["duration_minutes"],
        "tags": course["tags"],
        "description": course["description"],
        "target_audience": course.get("target_audience", []),
        "learning_objectives": course.get("learning_objectives", []),
        "modules": []
    }

    for module in course.get("modules", []):
        mod = {
            "id": module["id"],
            "title": module["title"],
            "order": module["order"],
            "duration_minutes": module.get("duration_minutes", 0),
            "icon": module.get("icon", "📄"),
            "lesson_count": len(module.get("lessons", [])),
            "has_quiz": "quiz" in module,
            "lessons": [
                {
                    "id": l["id"],
                    "title": l["title"],
                    "type": l.get("type", "article"),
                    "key_points": l.get("key_points", [])
                }
                for l in module.get("lessons", [])
            ]
        }
        course_detail["modules"].append(mod)

    return jsonify({
        "success": True,
        "course": course_detail,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>', methods=['GET'])
def get_module(course_id, module_id):
    """Detail modulu — plný obsah lekcí"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    return jsonify({
        "success": True,
        "course_id": course_id,
        "course_title": course["title"],
        "module": module,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>/lessons/<lesson_id>', methods=['GET'])
def get_lesson(course_id, module_id, lesson_id):
    """Detail jedné lekce — plný obsah"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    lesson = next((l for l in module.get("lessons", []) if l["id"] == lesson_id), None)
    if not lesson:
        return jsonify({"success": False, "error": f"Lekce '{lesson_id}' nenalezena"}), 404

    return jsonify({
        "success": True,
        "course_id": course_id,
        "module_id": module_id,
        "lesson": lesson,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>/quiz', methods=['GET'])
def get_quiz(course_id, module_id):
    """Získat kvíz pro modul"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    quiz = module.get("quiz")
    if not quiz:
        return jsonify({"success": False, "error": "Tento modul nemá kvíz"}), 404

    # Vrátit kvíz BEZ správných odpovědí (pro frontend)
    safe_quiz = {
        "id": quiz["id"],
        "title": quiz["title"],
        "question_count": len(quiz["questions"]),
        "questions": []
    }
    for q in quiz["questions"]:
        safe_q = {
            "id": q["id"],
            "question": q["question"],
            "type": q["type"]
        }
        if q["type"] == "single_choice":
            safe_q["options"] = [{"id": o["id"], "text": o["text"]} for o in q["options"]]
        elif q["type"] == "true_false":
            safe_q["options"] = [
                {"id": "true", "text": "Ano, je to pravda"},
                {"id": "false", "text": "Ne, není to pravda"}
            ]
        safe_quiz["questions"].append(safe_q)

    return jsonify({
        "success": True,
        "course_id": course_id,
        "module_id": module_id,
        "quiz": safe_quiz,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>/quiz/submit', methods=['POST'])
def submit_quiz(course_id, module_id):
    """Odeslat odpovědi na kvíz a získat hodnocení"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    quiz = module.get("quiz")
    if not quiz:
        return jsonify({"success": False, "error": "Tento modul nemá kvíz"}), 404

    data = request.json or {}
    answers = data.get("answers", {})
    user_id = data.get("userId", "anonymous")

    results = []
    correct_count = 0

    for q in quiz["questions"]:
        user_answer = answers.get(q["id"])
        is_correct = False

        if q["type"] == "single_choice":
            correct_option = next((o for o in q["options"] if o.get("correct")), None)
            is_correct = user_answer == correct_option["id"] if correct_option else False
        elif q["type"] == "true_false":
            expected = "true" if q["correct_answer"] else "false"
            is_correct = user_answer == expected

        if is_correct:
            correct_count += 1

        results.append({
            "question_id": q["id"],
            "question": q["question"],
            "user_answer": user_answer,
            "is_correct": is_correct,
            "explanation": q.get("explanation", "")
        })

    total = len(quiz["questions"])
    score = round((correct_count / total) * 100) if total > 0 else 0
    passed = score >= 60

    # Uložit do progress
    progress_key = f"{user_id}"
    if progress_key not in EDUCATION_PROGRESS:
        EDUCATION_PROGRESS[progress_key] = {}
    if course_id not in EDUCATION_PROGRESS[progress_key]:
        EDUCATION_PROGRESS[progress_key][course_id] = {"completed_modules": [], "quiz_scores": {}}

    EDUCATION_PROGRESS[progress_key][course_id]["quiz_scores"][module_id] = {
        "score": score,
        "correct": correct_count,
        "total": total,
        "passed": passed,
        "completed_at": now_iso()
    }

    if passed and module_id not in EDUCATION_PROGRESS[progress_key][course_id]["completed_modules"]:
        EDUCATION_PROGRESS[progress_key][course_id]["completed_modules"].append(module_id)

    # Motivační zpráva
    if score == 100:
        message = "Výborně! Perfektní skóre! Máte skvělé znalosti."
    elif score >= 80:
        message = "Velmi dobře! Máte solidní porozumění tématu."
    elif score >= 60:
        message = "Dobře! Prošli jste. Pokud chcete, můžete si lekce projít znovu pro lepší pochopení."
    else:
        message = "Zatím to není ono. Doporučujeme si lekce projít znovu a zkusit to později."

    return jsonify({
        "success": True,
        "score": score,
        "correct": correct_count,
        "total": total,
        "passed": passed,
        "message": message,
        "results": results,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/progress', methods=['GET', 'POST'])
def handle_progress():
    """Správa pokroku ve vzdělávání"""
    if request.method == 'POST':
        data = request.json or {}
        user_id = data.get('userId', 'anonymous')
        course_id = data.get('courseId')
        module_id = data.get('moduleId')
        lesson_id = data.get('lessonId')
        action = data.get('action', 'view')  # view, complete

        if not course_id:
            return jsonify({"success": False, "error": "courseId je vyžadováno"}), 400

        if user_id not in EDUCATION_PROGRESS:
            EDUCATION_PROGRESS[user_id] = {}
        if course_id not in EDUCATION_PROGRESS[user_id]:
            EDUCATION_PROGRESS[user_id][course_id] = {
                "completed_modules": [],
                "completed_lessons": [],
                "quiz_scores": {},
                "started_at": now_iso()
            }

        progress = EDUCATION_PROGRESS[user_id][course_id]

        if action == "complete" and lesson_id:
            if lesson_id not in progress.get("completed_lessons", []):
                progress.setdefault("completed_lessons", []).append(lesson_id)

        progress["last_activity"] = now_iso()
        if module_id:
            progress["last_module"] = module_id
        if lesson_id:
            progress["last_lesson"] = lesson_id

        return jsonify({
            "success": True,
            "message": "Pokrok uložen",
            "progress": progress,
            "timestamp": now_iso()
        })

    # GET
    user_id = request.args.get('userId', 'anonymous')
    progress = EDUCATION_PROGRESS.get(user_id, {})

    # Spočítat celkový pokrok
    summary = {}
    for cid, cprog in progress.items():
        course = EDUCATION_COURSES.get(cid)
        if not course:
            continue
        total_modules = len(course.get("modules", []))
        completed = len(cprog.get("completed_modules", []))
        summary[cid] = {
            "course_title": course["title"],
            "total_modules": total_modules,
            "completed_modules": completed,
            "percent": round((completed / total_modules) * 100) if total_modules > 0 else 0,
            "quiz_scores": cprog.get("quiz_scores", {}),
            "last_activity": cprog.get("last_activity")
        }

    return jsonify({
        "success": True,
        "user_id": user_id,
        "progress": summary,
        "courses_started": len(summary),
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/search', methods=['GET'])
def search_education():
    """Vyhledávání napříč kurzy a lekcemi"""
    query = request.args.get('query', request.args.get('q', ''))
    if not query:
        return jsonify({"success": False, "error": "Parametr 'query' je vyžadován"}), 400

    ql = query.lower()
    results = []

    for course in EDUCATION_COURSES.values():
        # Hledat v kurzu
        course_score = 0
        if ql in course["title"].lower():
            course_score += 10
        if ql in course["description"].lower():
            course_score += 5
        for tag in course["tags"]:
            if ql in tag.lower():
                course_score += 3

        if course_score > 0:
            results.append({
                "type": "course",
                "id": course["id"],
                "title": course["title"],
                "description": course["description"],
                "icon": course["icon"],
                "relevance": course_score
            })

        # Hledat v modulech a lekcích
        for module in course.get("modules", []):
            for lesson in module.get("lessons", []):
                lesson_score = 0
                if ql in lesson["title"].lower():
                    lesson_score += 8
                content = lesson.get("content", "")
                if ql in content.lower():
                    lesson_score += 4
                for kp in lesson.get("key_points", []):
                    if ql in kp.lower():
                        lesson_score += 2

                if lesson_score > 0:
                    results.append({
                        "type": "lesson",
                        "id": lesson["id"],
                        "title": lesson["title"],
                        "course_id": course["id"],
                        "course_title": course["title"],
                        "module_id": module["id"],
                        "module_title": module["title"],
                        "icon": module.get("icon", "📄"),
                        "relevance": lesson_score
                    })

    results.sort(key=lambda x: x["relevance"], reverse=True)

    return jsonify({
        "success": True,
        "query": query,
        "count": len(results),
        "results": results[:20],
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/stats', methods=['GET'])
def education_stats():
    """Statistiky vzdělávacího modulu"""
    total_courses = len(EDUCATION_COURSES)
    total_modules = sum(len(c.get("modules", [])) for c in EDUCATION_COURSES.values())
    total_lessons = sum(
        len(m.get("lessons", []))
        for c in EDUCATION_COURSES.values()
        for m in c.get("modules", [])
    )
    total_quizzes = sum(
        1 for c in EDUCATION_COURSES.values()
        for m in c.get("modules", [])
        if "quiz" in m
    )
    total_questions = sum(
        len(m.get("quiz", {}).get("questions", []))
        for c in EDUCATION_COURSES.values()
        for m in c.get("modules", [])
        if "quiz" in m
    )

    categories = {}
    for c in EDUCATION_COURSES.values():
        cat = c["category"]
        categories[cat] = categories.get(cat, 0) + 1

    return jsonify({
        "success": True,
        "stats": {
            "total_courses": total_courses,
            "total_modules": total_modules,
            "total_lessons": total_lessons,
            "total_quizzes": total_quizzes,
            "total_questions": total_questions,
            "categories": categories,
            "active_learners": len(EDUCATION_PROGRESS),
            "available_courses": [
                {"id": c["id"], "title": c["title"], "icon": c["icon"]}
                for c in EDUCATION_COURSES.values()
            ]
        },
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/communication-needs', methods=['GET'])
def get_communication_needs():
    """Propojení se systémem komunikačních potřeb z memory_routes"""
    need_type = request.args.get('type', None)

    # Mapování vzdělávacích kurzů na komunikační potřeby
    course_to_needs = {
        "dysphasia": ["dysphasia_child", "dysphasia_adult", "aphasia"],
        "huntington": ["huntington"],
        "als": ["als"]
    }

    if need_type:
        # Najdi kurzy relevantní pro danou komunikační potřebu
        relevant_courses = []
        for course_id, needs in course_to_needs.items():
            if need_type in needs:
                course = EDUCATION_COURSES.get(course_id)
                if course:
                    relevant_courses.append({
                        "id": course["id"],
                        "title": course["title"],
                        "icon": course["icon"],
                        "description": course["description"],
                        "communication_need": need_type
                    })

        return jsonify({
            "success": True,
            "communication_need": need_type,
            "relevant_courses": relevant_courses,
            "timestamp": now_iso()
        })

    # Vrátit celou mapu
    return jsonify({
        "success": True,
        "mapping": course_to_needs,
        "description": "Mapování vzdělávacích kurzů na komunikační potřeby (z memory_routes)",
        "timestamp": now_iso()
    })
