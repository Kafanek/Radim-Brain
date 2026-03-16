# ============================================
# 🎓 EDUCATION DATA — Kurzy, učitelé, scénáře, novinky
# ============================================
# Extracted from education_routes.py for maintainability.
# Content data separated from route logic.
# Version: 2.0.0

# ============================================
# 📚 VZDĚLÁVACÍ KURZY
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
                        },
                        {
                            "id": "q4",
                            "question": "Spojte správně pojmy s jejich definicí:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Disfázie", "right": "Částečná porucha řeči"},
                                {"left": "Afázie", "right": "Úplná ztráta řeči"},
                                {"left": "Dysartrie", "right": "Porucha motoriky řeči"},
                                {"left": "Dysfagie", "right": "Porucha polykání"}
                            ],
                            "explanation": "Disfázie = částečná porucha řeči, afázie = úplná ztráta, dysartrie = motorický problém svalů, dysfagie = polykání (úplně jiný problém!)."
                        },
                        {
                            "id": "q5",
                            "question": "Jaká je nejčastější příčina získané disfázie u dospělých?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Stres a přepracování", "correct": False},
                                {"id": "b", "text": "Cévní mozková příhoda (CMP)", "correct": True},
                                {"id": "c", "text": "Nedostatek vitamínů", "correct": False},
                                {"id": "d", "text": "Stárnutí", "correct": False}
                            ],
                            "explanation": "CMP (mrtvice) je příčinou cca 80 % případů získané disfázie. Další příčiny zahrnují úrazy hlavy, nádory mozku a záněty."
                        },
                        {
                            "id": "q6",
                            "question": "Vývojová disfázie postihuje chlapce a dívky stejně často.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "Chlapci jsou postiženi 2–3× častěji než dívky. Důvody nejsou zcela jasné, ale souvisí s rozdíly ve vývoji mozku."
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
                        },
                        {
                            "id": "q4",
                            "question": "Seřaďte kroky správné komunikace s dítětem s disfázií:",
                            "type": "ordering",
                            "correct_order": [
                                "Zkraťte větu na jednu instrukci",
                                "Počkejte na odpověď (počítejte do 10)",
                                "Zrcadlete a rozšiřte odpověď dítěte",
                                "Pochvalte snahu komunikovat"
                            ],
                            "explanation": "Správný postup: 1) krátká instrukce, 2) trpělivé čekání, 3) zrcadlení odpovědi, 4) pochvala. Nikdy nespěchejte a neopravujte přímo."
                        },
                        {
                            "id": "q5",
                            "question": "Co NENÍ typickým projevem vývojové disfázie?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Pozdní začátek řeči", "correct": False},
                                {"id": "b", "text": "Snížená inteligence", "correct": True},
                                {"id": "c", "text": "Malá slovní zásoba", "correct": False},
                                {"id": "d", "text": "Záměny hlásek", "correct": False}
                            ],
                            "explanation": "Inteligence je při vývojové disfázii VŽDY zachovaná. To je jeden z nejdůležitějších faktů — disfázie NENÍ mentální postižení."
                        },
                        {
                            "id": "q6",
                            "question": "Přiřaďte správné a nesprávné reakce:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Správně: Zrcadlení", "right": "Dítě: 'kočka tam' → Vy: 'Ano, kočka je na zahradě!'"},
                                {"left": "Správně: Pochvala snahy", "right": "'Super, že jsi mi to řekl!'"},
                                {"left": "Špatně: Přímá oprava", "right": "'Neříká se kolomobil, říká se automobil'"},
                                {"left": "Špatně: Srovnávání", "right": "'Tvůj kamarád už mluví líp'"}
                            ],
                            "explanation": "Zrcadlení a pochvala podporují komunikaci. Přímé opravy a srovnávání dítě frustrují a blokují."
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
                        },
                        {
                            "id": "q4",
                            "question": "Spojte typ disfázie s jeho popisem:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Brocova (expresivní)", "right": "Rozumí dobře, ale těžko tvoří slova a věty"},
                                {"left": "Wernickeho (receptivní)", "right": "Mluví plynule, ale nerozumí a slova nemají smysl"},
                                {"left": "Smíšená (globální)", "right": "Obtíže jak s produkcí, tak s porozuměním řeči"}
                            ],
                            "explanation": "Brocova = problém s tvorbou řeči (levý čelní lalok), Wernickeho = problém s porozuměním (levý spánkový lalok), smíšená = postiženy obě oblasti."
                        },
                        {
                            "id": "q5",
                            "question": "Rehabilitace řeči je nejúčinnější v prvních 6 měsících po CMP.",
                            "type": "true_false",
                            "correct_answer": True,
                            "explanation": "Ano, prvních 6 měsíců je tzv. 'zlaté okno', kdy je mozek nejplastičtější. ALE — zlepšení je možné i po letech, takže rehabilitace má smysl vždy."
                        },
                        {
                            "id": "q6",
                            "question": "Jaká je nejlepší reakce, když osoba s expresivní disfázií nemůže najít slovo a začíná být frustrovaná?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Říct: 'Uklidněte se a zkuste to znovu.'", "correct": False},
                                {"id": "b", "text": "Rychle říct slovo za ni, ať se netrápí", "correct": False},
                                {"id": "c", "text": "Klidně říct: 'Máme čas. Můžete to ukázat, nakreslit, nebo zkusíme jinak?'", "correct": True},
                                {"id": "d", "text": "Změnit téma, aby na to zapomněla", "correct": False}
                            ],
                            "explanation": "Nabídněte alternativní způsoby komunikace (gesta, kreslení, psaní) a dejte najevo klid a trpělivost. Nikdy netlačte, neříkejte slovo za člověka a neměňte téma bez souhlasu."
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
                        },
                        {
                            "id": "q3",
                            "question": "Na návštěvě u lékaře s manželem, který má disfázii. Lékař se ptá manžela na příznaky, ale mluví jen na vás. Co uděláte?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Odpovíte za manžela — je to rychlejší a přesnější", "correct": False},
                                {"id": "b", "text": "Požádáte lékaře, aby se obracel přímo na manžela, a nabídnete se jako podpora", "correct": True},
                                {"id": "c", "text": "Nic neřeknete, ať to lékař vyřeší sám", "correct": False}
                            ],
                            "explanation": "Vždy komunikujte S člověkem, ne přes něj. I u lékaře má pacient právo být přímým účastníkem rozhovoru. Vy jste podpora, ne náhrada."
                        },
                        {
                            "id": "q4",
                            "question": "Seřaďte kroky správného postupu při komunikaci s dospělým s disfázií:",
                            "type": "ordering",
                            "correct_order": [
                                "Navažte oční kontakt a získejte pozornost",
                                "Mluvte pomalu, klidně a v krátkých větách",
                                "Počkejte na odpověď — dejte dostatek času",
                                "Pokud nerozumíte, požádejte o zopakování nebo nabídněte alternativu (psaní, ukazování)"
                            ],
                            "explanation": "Klíčový je postup: pozornost → pomalá řeč → trpělivost → alternativní kanály. Nikdy nespěchejte."
                        },
                        {
                            "id": "q5",
                            "question": "S člověkem s disfázií je nejlepší mluvit hlasitěji, aby lépe rozuměl.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! Hlasitější řeč nepomůže — problém není ve sluchu, ale ve zpracování řeči v mozku. Místo hlasitosti pomozte pomalejší řečí, kratšími větami a vizuální podporou."
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
                ],
                "quiz": {
                    "id": "dysphasia-m5-quiz",
                    "title": "Kvíz: Kde hledat pomoc",
                    "passing_score": 60,
                    "questions": [
                        {
                            "id": "dys-m5-q1",
                            "type": "single_choice",
                            "question": "Jaký odborník je první kontakt pro logopedickou rehabilitaci disfázie?",
                            "options": ["Neurolog", "Klinický logoped", "Psycholog", "Praktický lékař"],
                            "correct": 1,
                            "explanation": "Klinický logoped je primární odborník pro diagnostiku a rehabilitaci disfázie."
                        },
                        {
                            "id": "dys-m5-q2",
                            "type": "true_false",
                            "question": "FAST test slouží k rozpoznání podezření na cévní mozkovou příhodu.",
                            "correct": True,
                            "explanation": "FAST = Face, Arms, Speech, Time — rychlý test pro rozpoznání CMP."
                        },
                        {
                            "id": "dys-m5-q3",
                            "type": "matching",
                            "question": "Spoj organizaci s její oblastí pomoci:",
                            "pairs": [
                                {"left": "Cerebrum", "right": "Osoby po poranění mozku"},
                                {"left": "Ictus", "right": "Pacienti po CMP"},
                                {"left": "SAAK", "right": "Augmentativní komunikace"},
                                {"left": "Asociace klinických logopedů", "right": "Seznam odborníků"}
                            ],
                            "explanation": "Každá organizace se zaměřuje na specifickou oblast pomoci."
                        },
                        {
                            "id": "dys-m5-q4",
                            "type": "ordering",
                            "question": "Seřaďte písmena FAST testu ve správném pořadí:",
                            "options": ["Face (obličej)", "Arms (ruce)", "Speech (řeč)", "Time (čas — volejte 155)"],
                            "correct_order": ["Face (obličej)", "Arms (ruce)", "Speech (řeč)", "Time (čas — volejte 155)"],
                            "explanation": "FAST: Face → Arms → Speech → Time."
                        },
                        {
                            "id": "dys-m5-q5",
                            "type": "single_choice",
                            "question": "Které telefonní číslo voláte při podezření na CMP?",
                            "options": ["112", "155", "116 123", "158"],
                            "correct": 1,
                            "explanation": "155 je číslo Zdravotnické záchranné služby — při CMP každá minuta se počítá!"
                        }
                    ]
                }
            },
            {
                "id": "dysphasia-m6",
                "title": "Modul pro rodiče a pedagogy",
                "order": 6,
                "duration_minutes": 15,
                "icon": "👩‍🏫",
                "lessons": [
                    {
                        "id": "dysphasia-m6-l1",
                        "title": "Domaci cviceni pro rodice",
                        "type": "article",
                        "content": """<h2>Domaci logopedicka cviceni pro rodice</h2>

<p>Logopedka Radka doporucuje tato cviceni, ktera muzete delat doma kazdy den. <strong>Klicove je pravidelnost</strong> — kratsi cviceni kazdy den je lepsi nez dlouhe jednou tydne.</p>

<h3>Cviceni podle veku ditete</h3>

<h4>2–4 roky: Pojmenuj obrazek</h4>
<ul>
<li>Ukazujte obrazky zvirat, jidla, hracek</li>
<li>Rekni: <em>'Co to je?'</em> a pockejte (pocitejte do 10)</li>
<li>Pokud dite nereka — rekni vy a nechte ho zopakovat</li>
<li>Chvalte: <em>'Super, to je kocka! Skvele!'</em></li>
</ul>

<h4>3–5 let: Rymy a rikanky</h4>
<ul>
<li>Opakovane rikejte jednoduche rikanky</li>
<li>Nechte dite doplnit posledni slovo: <em>'Kocka leze...'</em> (dirou)</li>
<li>Rymovani rozviji fonologicke povedomi — zaklad pro cteni</li>
<li>Zpivejte — melodie pomaha zapamatovat si slova</li>
</ul>

<h4>4–6 let: Hra na obchod</h4>
<ul>
<li>Hrajte si na nakupovani — dite je zakaznik i prodavac</li>
<li>Procvicuje: pojmenovani veci, zadani o neco, dekovat</li>
<li><em>'Prosim, chtela bych dva rohliky a mleko.'</em></li>
<li>Meni role — dite se uci ruzne komunikacni situace</li>
</ul>

<h4>5–7 let: Pribeh podle obrazku</h4>
<ul>
<li>Dejte diteti 3–4 obrazky v rade</li>
<li>Dite vypravi, co se deje: <em>'Nejdriv... pak... nakonec...'</em></li>
<li>Pomahejte otazkami: <em>'A co se stalo potom?'</em></li>
<li>Rozviji: slovosled, casova posloupnost, slovni zasobu</li>
</ul>

<h4>5+ let: Denik s obrazky</h4>
<ul>
<li>Kazdy den dite nakresli, co zazilo</li>
<li>Spolecne popisete obrazek 2–3 vetami</li>
<li>Dite diktuje, rodic zapisuje (nebo naopak)</li>
<li>Vytvari navyk vyjadrovat zazitky slovy</li>
</ul>

<h3>Zlata pravidla domaciho cviceni</h3>
<ol>
<li><strong>Max 10–15 minut denne</strong> — kratke a hrave</li>
<li><strong>Zadny dril</strong> — pokud dite nechce, nenutte ho</li>
<li><strong>Chvalte snahu</strong>, ne spravnost</li>
<li><strong>Budte partakem</strong>, ne ucitelem</li>
<li><strong>Zapojte sourozence</strong> — deti se uci od sebe nejlepe</li>
</ol>

<p class="key-point">💡 <strong>Tip od logopedky Radky:</strong> Nejlepsi logopedicke cviceni je spolecne varani! Dite pojmenovava ingredience, popisuje co delas, zada o vec. A vysledek je jeste k jidlu.</p>""",
                        "key_points": [
                            "Pravidelnost je klicova — kratke cviceni kazdy den",
                            "Cviceni podle veku: obrazky, rymy, hra na obchod, pribehy",
                            "Max 10–15 minut denne, hravou formou",
                            "Chvalit snahu, ne spravnost vysledku",
                            "Zapojit cviceni do beznych cinnosti (varani, nakupy)"
                        ]
                    },
                    {
                        "id": "dysphasia-m6-l2",
                        "title": "Pruvodce pro ucitele a asistenty",
                        "type": "article",
                        "content": """<h2>Dite s disfazii ve skole — pruvodce pro pedagogy</h2>

<p>Dite s vyvojovou disfazii muze byt ve tride plne uspesne, pokud dostane <strong>spravnou podporu</strong>. Neni to o snizovani naroku — je to o prizpusobeni FORMY, ne OBSAHU.</p>

<h3>Zakladni opatreni ve tride</h3>

<h4>1. Individualni vzdelavaci plan (IVP)</h4>
<ul>
<li><strong>Narok ze zakona</strong> — rodic zada, skola MUSI vyhovet</li>
<li>Stanovi konkretni upravi: vice casu, jiny zpusob hodnoceni</li>
<li>Aktualizovat minimalne 1x rocne s SPC</li>
<li>Zapojit rodice, logopeda, tridiho ucitele, asistenta</li>
</ul>

<h4>2. Usazeni ve tride</h4>
<ul>
<li>Dite sedi <strong>vpredu</strong>, blizko ucitele</li>
<li>Daleko od okna a dveri (min rusivy zvuky)</li>
<li>Vedle klidneho spoluzaka, ktery muze pomoct</li>
</ul>

<h4>3. Vizualni podpora</h4>
<ul>
<li><strong>Vizualni rozvrh</strong> na tabuli nebo na lavici</li>
<li>Piktogramy pro instrukce (sedni, otevri sesit, poslouchej)</li>
<li>Obrazove karty pro klicova slova tematu</li>
<li>Barevne oznaceni dulezitych informaci</li>
</ul>

<h4>4. Komunikace s ditetem</h4>
<ul>
<li>Jedna instrukce najednou — pockejte na splneni</li>
<li>Overit porozumeni: <em>'Rekni mi, co mas delat'</em></li>
<li>Vice casu na odpoved — nepreskakovejte k jinemu diteti</li>
<li>NIKDY: <em>'Rekni to poradne'</em> nebo <em>'Mluv cesky'</em></li>
</ul>

<h4>5. Hodnoceni a testy</h4>
<ul>
<li><strong>Vice casu</strong> na pisemne prace (1,5x–2x)</li>
<li>Moznost <strong>ustniho zkoušeni</strong> misto pisemneho</li>
<li>Hodnotit OBSAH, ne jazykovou formu (pokud nejde o cestinu)</li>
<li>Zkraceny diktovat nebo nahradit jinou formou</li>
</ul>

<h3>Spoluprace s SPC</h3>
<p><strong>Specialne pedagogicke centrum</strong> (SPC) je klicovy partner:</p>
<ul>
<li>Provadi diagnostiku a doporucuje podpurna opatreni</li>
<li>Vystavuje doporuceni pro IVP</li>
<li>Konzultace pro ucitele — jak prizpusobit vyuku</li>
<li>Kontakt: kazdy kraj ma SPC pro poruchy reci</li>
</ul>

<h3>Prevence sikany</h3>
<ul>
<li>Vysvetlit spoluzakum, co disfazie je (primerenou formou)</li>
<li>Zduraznit: <em>'Tomas je chytry jako vy, jen mluvi trochu jinak'</em></li>
<li>Zapojit dite do skupinovych aktivit, kde vynikne (kresleni, sport)</li>
<li>Sledovat socialni dynamiku — dite se muze stahovat</li>
</ul>

<p class="key-point">💡 <strong>Klicova zprava:</strong> Dite s disfazii NENI linne, hlupe, ani neposlousne. Ma neurologickou poruchu, ktera ovlivnuje rec, ale NE inteligenci. S vasim porozumenim muze ve skole prospivat.</p>""",
                        "key_points": [
                            "IVP je narok ze zakona — rodic zada, skola musi vyhovet",
                            "Usadit vpredu, vizualni rozvrh, piktogramy",
                            "Vice casu na testy, hodnotit obsah ne formu",
                            "Spoluprace s SPC — diagnostika a doporuceni",
                            "Prevence sikany — vysvetlit spoluzakum, zapojit do aktivit"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dysphasia-m6-quiz",
                    "title": "Overite si: Podpora ditete s disfazii",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Jake domaci cviceni je vhodne pro 3–5lete dite s disfazii?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Diktovani slov a oprava chyb", "correct": False},
                                {"id": "b", "text": "Rymy, rikanky a zpivani", "correct": True},
                                {"id": "c", "text": "Cist nahlas minimalne 30 minut denne", "correct": False}
                            ],
                            "explanation": "Rymy a rikanky rozviji fonologicke povedomi hravou formou. Jsou idealni pro 3–5lete deti. Diktovani a nucene cteni jsou nevhodne — vytvarejipresne a odpor k komunikaci."
                        },
                        {
                            "id": "q2",
                            "question": "Co je IVP a kdo o nej zada?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "IVP = Individualni vzdelavaci plan, zada rodic", "correct": True},
                                {"id": "b", "text": "IVP = Intenzivni vyukovy program, zada ucitel", "correct": False},
                                {"id": "c", "text": "IVP = Integracni vyrovnavaci plan, zada SPC", "correct": False}
                            ],
                            "explanation": "IVP je Individualni vzdelavaci plan. Zakonny zastupce (rodic) o nej zada a skola je ze zakona povinna ho vytvorit na zaklade doporuceni SPC."
                        },
                        {
                            "id": "q3",
                            "question": "Jak by mel ucitel hodnotit pisemne prace ditete s disfazii?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Presne stejne jako ostatni deti", "correct": False},
                                {"id": "b", "text": "Hodnotit obsah a myslenky, ne jazykovou formu", "correct": True},
                                {"id": "c", "text": "Nehodnotit vubec a dat automaticky jednicku", "correct": False}
                            ],
                            "explanation": "Spravny pristup je hodnotit OBSAH a MYSLENKY ditete, ne jazykovou formu (krome hodin cestiny). Dite s disfazii muze mit skvele napady, i kdyz je vyjadri s gramatickymi chybami."
                        },
                        {
                            "id": "q4",
                            "question": "Jaky je nejdulezitejsi princip pri zapojeni ditete s disfazii do kolektivu?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Osvobodit dite od vsech skupinovych aktivit", "correct": False},
                                {"id": "b", "text": "Vysvetlit spoluzakum, co disfazie je, a zapojit dite do aktivit, kde vynikne", "correct": True},
                                {"id": "c", "text": "Nechat dite, at si poradi samo — otuzuje to", "correct": False},
                                {"id": "d", "text": "Preradit dite do specialni skoly", "correct": False}
                            ],
                            "explanation": "Klicove je informovat spoluzaky primerenou formou a najit aktivity, kde dite vynikne (sport, kresleni, hudba). Dite s disfazii patri do bezne skoly s podporou."
                        },
                        {
                            "id": "q5",
                            "question": "Dite s disfazii by nemelo mit ve skole zadne ulehceni — musí se naucit zvladat stejne naroky jako ostatni.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! Dite s disfazii ma ze zakona narok na IVP s upravami (vice casu, jiny zpusob hodnoceni). Nejde o snizovani naroku, ale o prizpusobeni FORMY — obsah zustava stejny."
                        }
                    ]
                }
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
                        },
                        {
                            "id": "q3",
                            "question": "Spojte správně:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Genetická příčina HD", "right": "Mutace genu HTT na chromozomu 4"},
                                {"left": "Typ dědičnosti", "right": "Autozomálně dominantní (50% šance)"},
                                {"left": "Typický věk nástupu", "right": "30–50 let"},
                                {"left": "Klíčový protein", "right": "Huntingtin"}
                            ],
                            "explanation": "HD je způsobena mutací genu HTT. Dědí se autozomálně dominantně — každé dítě postiženého rodiče má 50% šanci."
                        },
                        {
                            "id": "q4",
                            "question": "Huntingtonova choroba se dá v současnosti vyléčit.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "Bohužel zatím neexistuje lék. Léčba je symptomatická — zmírňuje příznaky (mimovolní pohyby, deprese, úzkost). Probíhá intenzivní výzkum genové terapie."
                        },
                        {
                            "id": "q5",
                            "question": "Které z těchto příznaků NEJSOU typické pro Huntingtonovu chorobu?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Mimovolní pohyby (chorea)", "correct": False},
                                {"id": "b", "text": "Změny osobnosti a nálad", "correct": False},
                                {"id": "c", "text": "Ztráta zraku", "correct": True},
                                {"id": "d", "text": "Potíže s polykáním", "correct": False}
                            ],
                            "explanation": "HD se projevuje motoricky (chorea, dystonie), psychicky (deprese, agrese) a kognitivně. Zrak nebývá přímo postižen."
                        }
                    ]
                }
            },
            {
                "id": "huntington-m2",
                "title": "Komunikace a kazdy den s HD",
                "order": 2,
                "duration_minutes": 12,
                "icon": "🗣️",
                "lessons": [
                    {
                        "id": "huntington-m2-l1",
                        "title": "Jak se meni komunikace pri HD",
                        "type": "article",
                        "content": """<h2>Komunikace pri Huntingtonove chorobe</h2>

<p>Huntingtonova choroba postupne ovlivnuje <strong>rec, polykani a schopnost vyjadrovat emoce</strong>. Zmeny jsou pozvolne, ale pro rodinu casto velmi tezke.</p>

<h3>Zmeny v reci podle stadia</h3>

<h4>Rane stadium</h4>
<ul>
<li>Rec je srozumitelna, ale muze byt <strong>zrychlena nebo nerovnomerna</strong></li>
<li>Obcas hledani slov, opakovanieee slabik</li>
<li>Podradeni nebo impulzivni reakce (psychiatricke prznaky)</li>
<li>Clovek si zmeny uvedomuje — frustrace a styd</li>
</ul>

<h4>Stredni stadium</h4>
<ul>
<li>Rec se stava <strong>obtizne srozumitelna</strong> — dysartrie</li>
<li>Mimovolni pohyby (chorea) narusujoi koordinaci rtluu a jazyka</li>
<li>Delsi vety jsou problematicke — clovek ztraci myslenku</li>
<li>Polykani se zhorsuje — riziko zachvaeni</li>
</ul>

<h4>Pozdni stadium</h4>
<ul>
<li>Rec muze byt <strong>zcela nesrozumitelna</strong> nebo nemozna</li>
<li>Komunikace predevsim neverbalni — vyrazy obliceje, dotyk, prritomnost</li>
<li>Clovek <strong>STALE rozumi</strong> vic, nez muze vyjadrit</li>
</ul>

<h3>Komunikacni strategie</h3>
<ol>
<li><strong>Ano/ne otazky</strong> — jednodussi nez otevrenee otazky</li>
<li><strong>Dejte cas</strong> — chorea zpomaluje artikulaci, ne mysleni</li>
<li><strong>Klidne prostredi</strong> — ruch zhorsuje soustredeni</li>
<li><strong>Ocni kontakt</strong> — udrzte pozornost a pokaz, ze naslouchaate</li>
<li><strong>Nepreruste</strong> — i kdyz vite, co chce rict</li>
<li><strong>Komunikacni pomucky</strong> — tabulky, tablety, piktogramy</li>
</ol>

<p class="key-point">💡 <strong>Dulezite:</strong> Podrazdeni a impulzivita u HD NEJSOU zloba — jsou to prznaky onemocneni. Clovek za ne NEMUZE. Trpelivost a porozumeni jsou nejlepsi 'lek'.</p>""",
                        "key_points": [
                            "Rec se meni od zrychlene pres dysartrii az po nesrozumitelnost",
                            "Mimovolni pohyby (chorea) narusuji artikulaci",
                            "Clovek rozumi vic nez muze vyjadrit",
                            "Ano/ne otazky, klidne prostredi, ocni kontakt",
                            "Podrazdeni a impulzivita jsou prznaky, ne zloba"
                        ]
                    },
                    {
                        "id": "huntington-m2-l2",
                        "title": "Geneticke testovani a rodina",
                        "type": "article",
                        "content": """<h2>HD a rodina — geneticke testovani</h2>

<p>Kazde dite rodice s HD ma <strong>50% riziko</strong>, ze gen zdedilo. Rozhodnuti o genetickem testu je <strong>jedno z nejtezsich v zivote</strong>.</p>

<h3>Prediktivni geneticky test</h3>
<ul>
<li>Krevni test, ktery ukaze, zda osoba nese mutaci genu HTT</li>
<li>Dostupny od 18 let (v CR presne od 18)</li>
<li>Povinny geneticky poradenstvi pred testem i po nem</li>
<li>Vysledek je DEFINITIVNI — pokud je pozitivni, onemocneni se projevi</li>
</ul>

<h3>Dilema: Testovat se, nebo ne?</h3>

<h4>Proc ANO</h4>
<ul>
<li>Jistota — konec nevedeni</li>
<li>Planovani zivota — kariery, rodiny, financi</li>
<li>Moznost preimplantacni diagnostiky (PGD) — mit deti BEZ HD genu</li>
<li>Ucast ve vyzkumnych studiich</li>
</ul>

<h4>Proc NE</h4>
<ul>
<li>Psychicka zatez pozitivniho vysledku</li>
<li>Aktualne neexistuje lecba — vedet predem muze byt tezke</li>
<li>Riziko diskriminace (pojistovny, zamestnavatele)</li>
<li>Nekteri lide zijou lepe v nevedeni</li>
</ul>

<h3>Pro rodiny</h3>
<ul>
<li><strong>Nikdy netlacte</strong> na blizkeho, aby se testoval</li>
<li>Respektujte jeho rozhodnuti — AT UZ je jakekoli</li>
<li>Svepomocne skupiny pro rodiny s HD: <strong>Spolecnost pro pomoc pri Huntingtonove chorobe</strong></li>
<li>Psychologicka podpora je NUTNOST — pro vsechny cleny rodiny</li>
</ul>

<p class="key-point">💡 <strong>Dulezite:</strong> Rozhodnuti o genetickem testu je osobni a intimni. Neexistuje spravna ani spatna volba. Oba pristupy — vedet i nevedet — jsou legitimni.</p>""",
                        "key_points": [
                            "50% riziko dedicnosti — prediktivni test od 18 let",
                            "Test je definitivni — povinne geneticke poradenstvi",
                            "PGD umoznuje mit deti bez HD genu",
                            "Nikdy netlacit na testovani — respektovat rozhodnuti",
                            "Psychologicka podpora pro celou rodinu"
                        ]
                    }
                ],
                "quiz": {
                    "id": "huntington-m2-quiz",
                    "title": "Overite si: Komunikace a rodina pri HD",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Proc je clovek s HD nekdy podrazdeny a impulzivni?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Je to priznak onemocneni, nemuze za to", "correct": True},
                                {"id": "b", "text": "Je to jeho povaaha", "correct": False},
                                {"id": "c", "text": "Dela to naschval", "correct": False}
                            ],
                            "explanation": "Podrazdeni a impulzivita jsou psychiatricke prznaky HD. Onemocneni poskoze oblast mozku, ktera reguluje emoce. Clovek za to NEMUZE."
                        },
                        {
                            "id": "q2",
                            "question": "Jake je riziko, ze dite rodice s HD zdedi gen?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "25 %", "correct": False},
                                {"id": "b", "text": "50 %", "correct": True},
                                {"id": "c", "text": "75 %", "correct": False}
                            ],
                            "explanation": "Huntingtonova choroba se dedi autozomalne dominantne — kazde dite postizeneho rodice ma presne 50% sanci, ze gen zdedilo."
                        },
                        {
                            "id": "q3",
                            "question": "Mel by se kazdy v ohrozene rodine testovat?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Ano, kazdý by mel vedet", "correct": False},
                                {"id": "b", "text": "Ne, rozhodnuti je osobni a oba pristupy jsou legitimni", "correct": True},
                                {"id": "c", "text": "Ano, kvuli detem", "correct": False}
                            ],
                            "explanation": "Rozhodnuti o genetickem testu je hluboce osobni. Neexistuje 'spravna' volba — nekteri lide chteji vedet, jini ne. Oba pristupy jsou legitimni a je treba je respektovat."
                        },
                        {
                            "id": "q4",
                            "question": "Seřaďte správný postup při komunikaci s osobou s HD, která je podrážděná:",
                            "type": "ordering",
                            "correct_order": [
                                "Zůstaňte klidní — nedávejte najevo frustraci",
                                "Validujte emoci: 'Vidím, že jsi naštvaný'",
                                "Nabídněte konkrétní řešení klidným hlasem",
                                "Po zklidnění mluvte o tom, co se stalo — bez obviňování"
                            ],
                            "explanation": "Podrážděnost u HD je PŘÍZNAK nemoci. Klid → validace → řešení → pozdější rozbor. Nikdy nereagujte konfrontačně."
                        },
                        {
                            "id": "q5",
                            "question": "Rozhodnutí o genetickém testování na HD by mělo být vždy osobním rozhodnutím dotyčného.",
                            "type": "true_false",
                            "correct_answer": True,
                            "explanation": "Ano! Genetické testování je vždy DOBROVOLNÉ. Nikdy netlačte ani jedním směrem. Před testem je povinné genetické poradenství."
                        }
                    ]
                }
            },
            {
                "id": "huntington-m3",
                "title": "Kde najit pomoc v CR",
                "order": 3,
                "duration_minutes": 6,
                "icon": "🏥",
                "lessons": [
                    {
                        "id": "huntington-m3-l1",
                        "title": "Zdroje a podpora pro rodiny s HD",
                        "type": "resources",
                        "content": """<h2>Pomoc pro rodiny s Huntingtonovou chorobou v CR</h2>

<h3>Specializovana centra</h3>
<ul>
<li><strong>FN Motol, Praha</strong> — Neurologicka klinika (prof. Klempir) — hlavni centrum pro HD v CR</li>
<li><strong>FN Brno</strong> — Neurologicka klinika</li>
<li><strong>Geneticke poradny</strong> — kazda fakultni nemocnice</li>
</ul>

<h3>Organizace</h3>
<ul>
<li><strong>Spolecnost pro pomoc pri Huntingtonove chorobe</strong> — svepomocna org pro rodiny</li>
<li><strong>EURORDIS</strong> — Evropska organizace pro vzacna onemocneni</li>
<li><strong>Narodni koordinacni centrum pro vzacna onemocneni</strong> (NKCVO)</li>
</ul>

<h3>Prakticka podpora</h3>
<ul>
<li>Prispevek na peci (zakon 108/2006 Sb.) — 4 stupne</li>
<li>Invalidni duchod — pri ztrate pracovni schopnosti</li>
<li>Prukaz ZTP/P — parkovani, slevy, pruvodce</li>
<li>Osobni asistence — pomoc v kazdodennim zivote</li>
</ul>

<h3>Vyzkum a nadeje</h3>
<ul>
<li>Genova terapie — vyzkum zamireny na ztiseni vadneho genu</li>
<li>ASO (antisense oligonukleotidy) — klinicke studie probihaji</li>
<li>Registr pacientu <strong>Enroll-HD</strong> — mezinarodni studie, ucast mozna i v CR</li>
</ul>

<p class="key-point">💡 <strong>Nadeje:</strong> Vyzkum HD rychle postupuje. I kdyz lecba zatim neexistuje, klinicke studie prinaseji realne vysledky. Ucast v registru Enroll-HD pomaha budoucim pacientum.</p>""",
                        "key_points": [
                            "Hlavni centrum pro HD v CR: FN Motol (prof. Klempir)",
                            "Spolecnost pro pomoc pri HD — svepomocna organizace",
                            "Prispevek na peci, invalidni duchod, prukaz ZTP/P",
                            "Genova terapie a ASO ve vyzkumu — nadeje pro budoucnost",
                            "Registr Enroll-HD — mezinarodni studie, ucast mozna v CR"
                        ]
                    }
                ],
                "quiz": {
                    "id": "huntington-m3-quiz",
                    "title": "Kvíz: Kde najít pomoc v ČR",
                    "passing_score": 60,
                    "questions": [
                        {
                            "id": "hunt-m3-q1",
                            "type": "single_choice",
                            "question": "Které nemocniční centrum je hlavní specializované pracoviště pro HD v ČR?",
                            "options": ["FN Brno", "FN Motol, Praha", "FN Olomouc", "VFN Praha"],
                            "correct": 1,
                            "explanation": "FN Motol v Praze (prof. Klempíř) je hlavní centrum pro Huntingtonovu chorobu v ČR."
                        },
                        {
                            "id": "hunt-m3-q2",
                            "type": "true_false",
                            "question": "Průkaz ZTP/P umožňuje mimo jiné parkování na vyhrazených místech a bezplatného průvodce.",
                            "correct": True,
                            "explanation": "Průkaz ZTP/P přináší výhody: parkování, slevy v dopravě, nárok na průvodce."
                        },
                        {
                            "id": "hunt-m3-q3",
                            "type": "matching",
                            "question": "Přiřaďte organizaci k jejímu zaměření:",
                            "pairs": [
                                {"left": "Společnost pro pomoc při HD", "right": "Svépomocná organizace pro rodiny"},
                                {"left": "EURORDIS", "right": "Evropská organizace pro vzácná onemocnění"},
                                {"left": "NKCVO", "right": "Koordinační centrum pro vzácná onemocnění"},
                                {"left": "Enroll-HD", "right": "Mezinárodní registr pacientů"}
                            ],
                            "explanation": "Každá organizace má specifické zaměření v oblasti HD."
                        },
                        {
                            "id": "hunt-m3-q4",
                            "type": "single_choice",
                            "question": "Jaký typ moderní terapie je ve výzkumu zaměřen na ztišení vadného genu pro HD?",
                            "options": ["Chemoterapie", "Genová terapie", "Radioterapie", "Fyzioterapie"],
                            "correct": 1,
                            "explanation": "Genová terapie se zaměřuje na ztišení nebo opravu vadného genu huntingtin."
                        },
                        {
                            "id": "hunt-m3-q5",
                            "type": "true_false",
                            "question": "Příspěvek na péči má v ČR 4 stupně podle míry závislosti.",
                            "correct": True,
                            "explanation": "Zákon 108/2006 Sb. stanoví 4 stupně příspěvku na péči: lehká, středně těžká, těžká a úplná závislost."
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
                        },
                        {
                            "id": "q2",
                            "question": "ALS primárně postihuje:",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Smyslové orgány (zrak, sluch)", "correct": False},
                                {"id": "b", "text": "Motorické neurony (nervové buňky ovládající svaly)", "correct": True},
                                {"id": "c", "text": "Krevní oběh", "correct": False},
                                {"id": "d", "text": "Kosti a klouby", "correct": False}
                            ],
                            "explanation": "ALS = Amyotrofická laterální skleróza. Postihuje motorické neurony — nervové buňky, které ovládají svaly. Inteligence a smysly zůstávají zachované."
                        },
                        {
                            "id": "q3",
                            "question": "Spojte správně pojmy související s ALS:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Eye-tracking komunikátor", "right": "Zařízení ovládané pohybem očí"},
                                {"left": "Dysartrie", "right": "Porucha motoriky řeči (svaly)"},
                                {"left": "Augmentativní komunikace", "right": "Podpůrné prostředky pro dorozumívání"},
                                {"left": "Respirační selhání", "right": "Nejčastější příčina úmrtí u ALS"}
                            ],
                            "explanation": "Eye-tracking umožňuje komunikaci pohybem očí. Dysartrie ztěžuje řeč. Augmentativní komunikace zahrnuje všechny podpůrné prostředky."
                        },
                        {
                            "id": "q4",
                            "question": "Inteligence lidí s ALS je zachována po celou dobu onemocnění.",
                            "type": "true_false",
                            "correct_answer": True,
                            "explanation": "ANO! To je klíčové — ALS postihuje svaly, ale myšlení, paměť a osobnost zůstávají. Člověk je 'uvězněný' v nefunkčním těle. Proto je komunikace tak důležitá."
                        },
                        {
                            "id": "q5",
                            "question": "Jaký je typický průběh ALS?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Náhlý nástup, rychlé uzdravení", "correct": False},
                                {"id": "b", "text": "Postupná ztráta svalové síly, průměrně 2–5 let", "correct": True},
                                {"id": "c", "text": "Střídání zhoršení a zlepšení", "correct": False}
                            ],
                            "explanation": "ALS je progresivní — postupně oslabuje svaly. Průměrná délka přežití je 2–5 let od diagnózy, ale někteří žijí mnohem déle (Stephen Hawking: 55 let!)."
                        }
                    ]
                }
            },
            {
                "id": "als-m2",
                "title": "Komunikace v ruznych fazich ALS",
                "order": 2,
                "duration_minutes": 12,
                "icon": "🗣️",
                "lessons": [
                    {
                        "id": "als-m2-l1",
                        "title": "Jak se meni rec pri ALS",
                        "type": "article",
                        "content": """<h2>Komunikace pri ALS — od reci k technologiim</h2>

<p>ALS postupne oslabuje svaly, vcetne tech, ktere pouzivame k mluveni. Zmeny jsou <strong>predvidatelne</strong> a pripravit se na ne DOPREDU je klicove.</p>

<h3>Faze zmeny reci</h3>

<h4>Faze 1: Rec je srozumitelna</h4>
<ul>
<li>Mirne zmeny — hlas je tissi, pomalejsi</li>
<li>Unava hlasu ke konci dne</li>
<li>Obcas nezretelne slabiky</li>
<li><strong>Nyni je cas:</strong> Nahrat svuj hlas pro budouci hlasovou banku!</li>
</ul>

<h4>Faze 2: Rec je obtizne srozumitelna</h4>
<ul>
<li>Dysartrie — slova splyvaji, hlas je slaby</li>
<li>Blizci rozumi, cizi lide obtizne</li>
<li>Kratke vety, klicova slova</li>
<li><strong>Nyni je cas:</strong> Zacit pouzivat komunikacni pomucky (tabulky, aplikace)</li>
</ul>

<h4>Faze 3: Rec neni mozna</h4>
<ul>
<li>Hlasova komunikace jiz neni mozna</li>
<li><strong>Ale komunikace pokracuje!</strong></li>
<li>Oci — sledovani pohledu (eye-tracking)</li>
<li>Prsty — prepinace, specialni klavesnice</li>
<li>Oci + pocitac = plna komunikace (jako Stephen Hawking)</li>
</ul>

<h3>Hlasova banka — zachrante svuj hlas</h3>
<p><strong>Hlasova banka</strong> je nahravka vaseho hlasu, ze ktere pocitac vytvori <strong>synteticky hlas, ktery zni jako VY</strong>. Kdyz pozdeji pouzijete komunikator, bude mluvit vasim hlasem.</p>
<ul>
<li><strong>ModelTalker</strong> — bezplatna hlasova banka</li>
<li><strong>Acapela my-own-voice</strong> — placena, vyssi kvalita</li>
<li>Idealni cas: kdyz rec jeste funguje dobre (faze 1!)</li>
<li>Clovek nahrava vety (cca 1 600 vet) — trva nekolik hodin</li>
</ul>

<p class="key-point">💡 <strong>Nejdulezitejsi rada:</strong> Neplanujtee komunikacni pomucky AZ kdyz rec selze — to je pozde. Zacnete SE PRIRAVOVAT v fazi 1, kdyz jeste mluvite dobre. Nahrajte si hlas. Vyzkousejte pomucky. Budete PRIPRAVENI.</p>""",
                        "key_points": [
                            "Rec se meni predvidatelne — od tissiho hlasu po nemoznost mluvit",
                            "Hlasova banka: nahrat svuj hlas VCAS (faze 1)",
                            "Eye-tracking umoznuje plnou komunikaci i bez reci",
                            "Pripravit se DOPREDU — ncekat, az rec selze",
                            "Komunikace NIKDY nekonci — jen se meni jeji forma"
                        ]
                    },
                    {
                        "id": "als-m2-l2",
                        "title": "Asistivni technologie pro ALS",
                        "type": "article",
                        "content": """<h2>Technologie, ktere pomahaji komunikovat</h2>

<h3>Komunikacni tabulky a knihy</h3>
<ul>
<li>Nejjednodussi pomucka — laminovane karty s pismeny, slovy, obrazky</li>
<li>Ukazovani prstem, pohledem nebo kyvnutim</li>
<li>Vzdy mit po ruce — jako "zakladni sada"</li>
</ul>

<h3>Tablety a aplikace</h3>
<ul>
<li><strong>Grid 3</strong> — profesionalni komunikacni software</li>
<li><strong>Proloquo2Go</strong> — pro iPad</li>
<li><strong>Tobii Dynavox</strong> — specialni zarizeni s eye-trackingem</li>
<li>Bezne tablety s prizpusobenym ovladanim</li>
</ul>

<h3>Eye-tracking (sledovani pohledu oci)</h3>
<ul>
<li>Kamera sleduje pohyb oci a prevadi na vstup do pocitace</li>
<li>Clovek "pise" pohledem — vybira pismena na obrazovce</li>
<li>Rychlost: cca 8–15 slov za minutu (pomale, ale FUNGUJE)</li>
<li><strong>Tobii</strong> — prumyslovy standard pro eye-tracking</li>
<li>Moznost ovladat cely pocitac, email, internet</li>
</ul>

<h3>Prepinace (switches)</h3>
<ul>
<li>Jednoduchy tlacitko ovladane prstem, hlavou, dechem</li>
<li>Funguje i pri minimalni pohyblivosti</li>
<li>Scanovaci system — pocitac zvyraznuje moznosti, clovek stiskne ve spravny okamzik</li>
</ul>

<h3>Mozek-pocitac rozhrani (BCI)</h3>
<ul>
<li>Experimentalni technologie — cteni mozkovych vln</li>
<li>Clovek "mysli" prikaz a pocitac reaguje</li>
<li>Zatim ve vyzkumu, ale rychly pokrok</li>
</ul>

<p class="key-point">💡 <strong>Klicove:</strong> Technologie muze udrzet plnou komunikaci i kdyz telo selze. Ale je treba JI NACVICIT VCAS — naucit se pouzivat pomucky, kdyz jeste muzete mluvit, je MNOHOKRAT snazsi nez kdyz uz ne.</p>""",
                        "key_points": [
                            "Od jednoduchych tabulek po eye-tracking a BCI",
                            "Eye-tracking: 8–15 slov/min — pomale, ale plna komunikace",
                            "Nacvicit pouzivani pomucek VCAS — dokud rec jeste funguje",
                            "Grid 3, Tobii Dynavox — profesionalni komunikacni systemy",
                            "Technologie muze udrzet komunikaci az do konce"
                        ]
                    }
                ],
                "quiz": {
                    "id": "als-m2-quiz",
                    "title": "Overite si: Komunikace a technologie pri ALS",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Kdy je idealni cas nahrat si hlasovou banku?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Az kdyz rec uplne selze", "correct": False},
                                {"id": "b", "text": "V rane fazi, kdyz rec jeste funguje dobre", "correct": True},
                                {"id": "c", "text": "Hlasova banka neexistuje", "correct": False}
                            ],
                            "explanation": "Hlasovou banku je treba nahrat V RANE FAZI, kdyz rec jeste funguje dobre. Pozdeji uz kvalita nahravky nebude dostatecna pro vytvoreni syntetickeho hlasu."
                        },
                        {
                            "id": "q2",
                            "question": "Co je eye-tracking?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Sledovani pohybu oci kamerou — umoznuje ovladat pocitac pohledem", "correct": True},
                                {"id": "b", "text": "Specialni bryle pro slabozrake", "correct": False},
                                {"id": "c", "text": "Vysetreni oci u lekare", "correct": False}
                            ],
                            "explanation": "Eye-tracking je technologie, kde kamera sleduje pohyb oci a prevadi ho na vstup do pocitace. Clovek 'pise' pohledem — vybira pismena na obrazovce."
                        },
                        {
                            "id": "q3",
                            "question": "Konci komunikace, kdyz clovek s ALS nemuze mluvit?",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! Komunikace NIKDY nekonci. Meni se jen jeji forma — od reci pres psani, gesta, komunikacni tabulky az po eye-tracking a mozkove rozhrani."
                        },
                        {
                            "id": "q4",
                            "question": "Seřaďte fáze komunikačních pomůcek u ALS od nejranějších po nejpokročilejší:",
                            "type": "ordering",
                            "correct_order": [
                                "Zpomalení řeči, důraz na artikulaci",
                                "Tabulka s písmeny a obrázky",
                                "Tablet nebo počítač s hlasovým výstupem",
                                "Eye-tracking komunikátor ovládaný očima"
                            ],
                            "explanation": "S progresí ALS se mění komunikační potřeby: nejdřív úprava řeči → papírové pomůcky → digitální pomůcky → eye-tracking. Důležité je začít VČAS!"
                        },
                        {
                            "id": "q5",
                            "question": "Nejhorší reakce na nesrozumitelnou řeč osoby s ALS je předstírat, že rozumíte.",
                            "type": "true_false",
                            "correct_answer": True,
                            "explanation": "ANO! Předstírání porozumění je nejhorší — osoba to pozná a cítí se neviditelná. Vždy řekněte upřímně, že nerozumíte, a nabídněte alternativu."
                        }
                    ]
                }
            },
            {
                "id": "als-m3",
                "title": "Kde najit pomoc v CR",
                "order": 3,
                "duration_minutes": 6,
                "icon": "🏥",
                "lessons": [
                    {
                        "id": "als-m3-l1",
                        "title": "Podpora pro lidi s ALS a jejich rodiny",
                        "type": "resources",
                        "content": """<h2>Pomoc pro lidi s ALS v Ceske republice</h2>

<h3>Specializovana centra</h3>
<ul>
<li><strong>ALS centrum FN Motol, Praha</strong> — hlavni centrum pro ALS v CR</li>
<li><strong>FN Brno</strong> — Neurologicka klinika</li>
<li><strong>FN Olomouc</strong> — Neurologicka klinika</li>
<li>Multidisciplinarni tymy: neurolog, pneumolog, logoped, fyzioterapeut, psycholog</li>
</ul>

<h3>Organizace</h3>
<ul>
<li><strong>ALS Liga CR</strong> — hlavni pacientska organizace</li>
<li><strong>Spolecnost E</strong> — podpora pro vzacna onemocneni</li>
<li><strong>Nadace pro ALS Karla Modracheho</strong></li>
<li><strong>EURORDIS</strong> — Evropska organizace pro vzacna onemocneni</li>
</ul>

<h3>Prakticke pomucky</h3>
<ul>
<li><strong>Elektricke voziky</strong> — hradene pojistovnou</li>
<li><strong>Komunikatory</strong> — predpis od logopeda/neurologa</li>
<li><strong>Domaci ventilace</strong> — bipap/CPAP zarizeni</li>
<li><strong>Polohovaci postele</strong> — pomucky pro domaci peci</li>
</ul>

<h3>Financni podpora</h3>
<ul>
<li>Prispevek na peci — stupne I–IV (880–19 200 Kc/mesic)</li>
<li>Prispevek na mobilitu — pro osoby s omezenou pohyblivosti</li>
<li>Prispevek na zvlastni pomucku — komunikatory, voziky</li>
<li>Invalidni duchod</li>
<li>Prukaz ZTP/P</li>
</ul>

<h3>Psychologicka podpora</h3>
<ul>
<li>Pro pacienta: zpracovani diagnozy, uzkost, deprese</li>
<li>Pro rodinu: pece o pecujicich, detske psychoterapie</li>
<li>Linky duvery: 116 123, 116 111 (pro deti)</li>
</ul>

<p class="key-point">💡 <strong>Dulezite:</strong> ALS je teezke onemocneni, ale clovek NENI sam. Multidisciplinarni tym, technologie a podpora rodiny mohou vyrazne zvysit kvalitu zivota. ALS Liga CR je prvni kontakt.</p>""",
                        "key_points": [
                            "ALS centrum FN Motol — hlavni specialisovane pracoviste v CR",
                            "ALS Liga CR — pacientska organizace, prvni kontakt",
                            "Komunikatory, voziky, ventilace — hrazene pojistovnou",
                            "Prispevky na peci, mobilitu, pomucky — financni podpora",
                            "Psychologicka podpora pro pacienta I rodinu"
                        ]
                    }
                ],
                "quiz": {
                    "id": "als-m3-quiz",
                    "title": "Kvíz: Kde najít pomoc v ČR",
                    "passing_score": 60,
                    "questions": [
                        {
                            "id": "als-m3-q1",
                            "type": "single_choice",
                            "question": "Která organizace je hlavní pacientskou organizací pro lidi s ALS v ČR?",
                            "options": ["Cerebrum", "ALS Liga ČR", "Společnost E", "EURORDIS"],
                            "correct": 1,
                            "explanation": "ALS Liga ČR je hlavní pacientská organizace a první kontakt pro pacienty a rodiny."
                        },
                        {
                            "id": "als-m3-q2",
                            "type": "true_false",
                            "question": "Komunikátory pro pacienty s ALS mohou být hrazeny zdravotní pojišťovnou na předpis od logopeda nebo neurologa.",
                            "correct": True,
                            "explanation": "Komunikátory patří mezi speciální pomůcky, které mohou být hrazeny pojišťovnou."
                        },
                        {
                            "id": "als-m3-q3",
                            "type": "matching",
                            "question": "Přiřaďte typ podpory ke správné kategorii:",
                            "pairs": [
                                {"left": "Příspěvek na péči", "right": "Finanční podpora 880–19 200 Kč/měs"},
                                {"left": "Průkaz ZTP/P", "right": "Slevy a průvodce"},
                                {"left": "Domácí ventilace", "right": "Technická pomůcka"},
                                {"left": "Linka 116 123", "right": "Psychologická podpora"}
                            ],
                            "explanation": "Různé typy podpory pokrývají finanční, technickou i psychologickou pomoc."
                        },
                        {
                            "id": "als-m3-q4",
                            "type": "single_choice",
                            "question": "Které specializované centrum je hlavním pracovištěm pro ALS v ČR?",
                            "options": ["FN Brno", "FN Olomouc", "ALS centrum FN Motol", "VFN Královské Vinohrady"],
                            "correct": 2,
                            "explanation": "ALS centrum FN Motol v Praze je hlavní specializované pracoviště pro ALS v ČR."
                        },
                        {
                            "id": "als-m3-q5",
                            "type": "ordering",
                            "question": "Seřaďte členy multidisciplinárního týmu pro ALS podle pořadí, jak je pacient typicky potřebuje:",
                            "options": ["Neurolog (diagnostika)", "Fyzioterapeut (pohyblivost)", "Logoped (komunikace)", "Pneumolog (dýchání)"],
                            "correct_order": ["Neurolog (diagnostika)", "Fyzioterapeut (pohyblivost)", "Logoped (komunikace)", "Pneumolog (dýchání)"],
                            "explanation": "ALS začíná diagnostikou u neurologa, pak řeší pohyblivost, později komunikaci a nakonec dýchání."
                        }
                    ]
                }
            }
        ]
    },

    # ─────────────────────────────────────────
    # DEMENCE — různé druhy
    # ─────────────────────────────────────────
    "dementia": {
        "id": "dementia",
        "title": "Demence — průvodce pro rodiny a pečovatele",
        "subtitle": "Alzheimer, Lewy body, vaskulární, frontotemporální a další formy demence",
        "icon": "🧠",
        "category": "Demence",
        "difficulty": "intermediate",
        "duration_minutes": 60,
        "tags": ["demence", "Alzheimer", "Lewy body", "vaskulární", "frontotemporální", "Parkinson", "pečovatel"],
        "description": "Kompletní průvodce nejčastějšími typy demence. Naučíte se rozlišit jednotlivé formy, porozumíte průběhu onemocnění a osvojíte si správné komunikační strategie.",
        "target_audience": ["pečovatelé", "rodina", "zdravotníci", "sociální pracovníci"],
        "learning_objectives": [
            "Pochopíte rozdíl mezi 5 hlavními typy demence",
            "Rozpoznáte varovné příznaky jednotlivých forem",
            "Naučíte se komunikační strategie pro každé stádium",
            "Porozumíte, jak správně reagovat na halucinace a zmatenost",
            "Zjistíte, kde v ČR najdete pomoc"
        ],
        "modules": [
            {
                "id": "dementia-m1",
                "title": "Co je demence? Přehled typů",
                "order": 1,
                "duration_minutes": 12,
                "icon": "📖",
                "lessons": [
                    {
                        "id": "dementia-m1-l1",
                        "title": "Demence není normální stárnutí",
                        "type": "article",
                        "content": """<h2>Demence — když zapomínání přestane být normální</h2>

<p><strong>Demence</strong> není jedno onemocnění, ale <strong>skupina příznaků</strong> (syndrom), které postihují paměť, myšlení a schopnost zvládat běžné denní činnosti. Postihuje přibližně <strong>160 000 lidí v ČR</strong> a toto číslo roste.</p>

<h3>Normální stárnutí vs. demence</h3>
<table>
<tr><th>Normální stárnutí</th><th>Demence</th></tr>
<tr><td>Občas zapomene jméno, ale vzpomene si později</td><td>Zapomíná jména blízkých a nevzpomene si</td></tr>
<tr><td>Občas hledá klíče</td><td>Dává klíče do lednice a neví proč</td></tr>
<tr><td>Pomaleji se učí nové věci</td><td>Nedokáže se naučit obsluhovat TV ovladač</td></tr>
<tr><td>Občas špatné rozhodnutí</td><td>Opakovaně špatné finanční rozhodnutí</td></tr>
</table>

<h3>5 hlavních typů demence</h3>
<ol>
<li><strong>Alzheimerova choroba</strong> (60–70 %) — nejčastější, postupná ztráta paměti</li>
<li><strong>Vaskulární demence</strong> (15–20 %) — po cévních příhodách, schodovité zhoršování</li>
<li><strong>Demence s Lewyho tělísky</strong> (10–15 %) — halucinace, kolísání pozornosti</li>
<li><strong>Frontotemporální demence</strong> (5–10 %) — změny chování a osobnosti</li>
<li><strong>Demence při Parkinsonově chorobě</strong> — zpomalené myšlení, halucinace</li>
</ol>

<p class="key-point">💡 <strong>Důležité:</strong> Každý typ demence se projevuje JINAK a vyžaduje JINÝ přístup. Proto je správná diagnóza tak důležitá — žádejte vyšetření u neurologa nebo v memory klinice.</p>""",
                        "key_points": [
                            "Demence postihuje 160 000 lidí v ČR",
                            "Není normální součást stárnutí — je to nemoc",
                            "5 hlavních typů: Alzheimer, vaskulární, Lewy body, frontotemporální, Parkinson",
                            "Každý typ se projevuje jinak a vyžaduje jiný přístup",
                            "Správná diagnóza je klíčová — neurolog nebo memory klinika"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dementia-m1-quiz",
                    "title": "Ověřte si: Základy demence",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Který typ demence je nejčastější?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Alzheimerova choroba", "correct": True},
                                {"id": "b", "text": "Vaskulární demence", "correct": False},
                                {"id": "c", "text": "Frontotemporální demence", "correct": False}
                            ],
                            "explanation": "Alzheimerova choroba tvoří 60–70 % všech demencí a je zdaleka nejčastějším typem."
                        },
                        {
                            "id": "q2",
                            "question": "Je demence normální součást stárnutí?",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "Demence NENÍ normální stárnutí. Je to onemocnění mozku, které vyžaduje diagnostiku a péči."
                        },
                        {
                            "id": "q3",
                            "question": "Který typ demence se projevuje především změnami chování a osobnosti?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Alzheimerova choroba", "correct": False},
                                {"id": "b", "text": "Frontotemporální demence", "correct": True},
                                {"id": "c", "text": "Vaskulární demence", "correct": False}
                            ],
                            "explanation": "Frontotemporální demence typicky začíná změnami osobnosti a chování — ztráta empatie, nevhodné chování — zatímco paměť může být dlouho zachovaná."
                        },
                        {
                            "id": "q4",
                            "question": "Spojte typ demence s jeho hlavní charakteristikou:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Alzheimerova choroba", "right": "Nejčastější typ, postupná ztráta paměti"},
                                {"left": "Vaskulární demence", "right": "Způsobena poruchami krevního oběhu v mozku"},
                                {"left": "Lewy body demence", "right": "Zrakové halucinace, kolísání pozornosti"},
                                {"left": "Frontotemporální demence", "right": "Změny osobnosti a chování jako první příznak"}
                            ],
                            "explanation": "Každý typ demence má odlišný průběh a projevy. Správná diagnóza je klíčová pro vhodnou léčbu a péči."
                        },
                        {
                            "id": "q5",
                            "question": "Demence je normální součástí stárnutí.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! Demence NENÍ normální stárnutí. Je to onemocnění mozku. Zapomínání klíčů je normální — zapomínání, k čemu klíče slouží, už ne."
                        }
                    ]
                }
            },
            {
                "id": "dementia-m2",
                "title": "Alzheimerova choroba — 3 stádia",
                "order": 2,
                "duration_minutes": 12,
                "icon": "🔬",
                "lessons": [
                    {
                        "id": "dementia-m2-l1",
                        "title": "Počáteční stádium Alzheimera",
                        "type": "article",
                        "content": """<h2>Alzheimer — počáteční stádium</h2>

<p>V počátečním stádiu člověk <strong>stále žije samostatně</strong>, ale objevují se varovné signály:</p>

<h3>Typické příznaky</h3>
<ul>
<li><strong>Zapomínání nedávných událostí</strong> — 'Co jsem měl k obědu?" (ale dávné vzpomínky jsou zachovány)</li>
<li><strong>Hledání slov</strong> — 'Ta věc na pití... sklenice!"</li>
<li><strong>Dezorientace v čase</strong> — neví, jaký je den v týdnu</li>
<li><strong>Problémy s financemi</strong> — zapomíná platit účty, chybné výpočty</li>
<li><strong>Opakování otázek</strong> — ptá se znovu na to, co už slyšel</li>
</ul>

<h3>Jak komunikovat v počátečním stádiu</h3>
<ul>
<li>Buďte trpěliví, když hledá slova — napovězte, ale netlačte</li>
<li>Strukturujte den — nástěnka s rozvrhem, připomínky</li>
<li>Neříkejte 'to jsem ti už říkal" — je to zraňující</li>
<li>Podporujte samostatnost — nechte dělat, co ještě zvládá</li>
<li>Zapojte do rozhovorů o minulosti — dávné vzpomínky fungují</li>
</ul>

<p class="key-point">💡 <strong>Tip pro rodinu:</strong> Počáteční stádium je nejlepší čas na plánování budoucnosti — právní záležitosti, přání ohledně péče, finanční plánování. Mluvte o tom, dokud to ještě jde.</p>""",
                        "key_points": [
                            "Zapomínání nedávných událostí, ale dávné vzpomínky zachovány",
                            "Hledání slov, dezorientace v čase",
                            "Člověk je stále relativně samostatný",
                            "Neopravujte, nepoukazujte na chyby — podporujte",
                            "Plánujte budoucnost, dokud to jde"
                        ]
                    },
                    {
                        "id": "dementia-m2-l2",
                        "title": "Střední a pokročilé stádium",
                        "type": "article",
                        "content": """<h2>Alzheimer — střední a pokročilé stádium</h2>

<h3>Střední stádium (nejdelší — může trvat roky)</h3>
<ul>
<li>Nepoznává některé blízké osoby</li>
<li>Bloudí v známém prostředí</li>
<li>Potřebuje pomoc s oblékáním, hygienou</li>
<li>Může být agresivní nebo úzkostný (ne ze zlé vůle!)</li>
<li>Noční neklid, převrácený rytmus den/noc</li>
<li>Opakování stále stejných vět nebo příběhů</li>
</ul>

<h3>Komunikace ve středním stádiu</h3>
<ul>
<li><strong>Krátké věty</strong> — max 5 slov, jedna myšlenka</li>
<li><strong>Ano/ne otázky</strong> — 'Chceš čaj?" místo 'Co chceš pít?"</li>
<li><strong>Oční kontakt a dotek</strong> — nejdřív navážete kontakt, pak mluvíte</li>
<li><strong>Klidný hlas</strong> — nervozita se přenáší</li>
<li><strong>Validace emocí</strong> — 'Vidím, že jsi smutný" místo 'Nemáš důvod být smutný"</li>
</ul>

<h3>Pokročilé stádium</h3>
<ul>
<li>Téměř úplná ztráta řeči</li>
<li>Plná závislost na péči</li>
<li>Komunikace skrze dotek, mimiku, přítomnost</li>
<li><strong>Člověk stále vnímá emoce</strong> — laskavý dotek a klidný hlas ho uklidní</li>
</ul>

<p class="key-point">💡 <strong>Nikdy nezapomínejte:</strong> I v pokročilém stádiu člověk CÍTÍ vaši lásku a přítomnost. Držte ho za ruku, pusťte oblíbenou hudbu, buďte prostě s ním.</p>""",
                        "key_points": [
                            "Střední stádium: potřebuje pomoc, bloudí, nepoznává blízké",
                            "Agrese/úzkost nejsou záměrné — je to nemoc",
                            "Krátké věty, Ano/ne otázky, klidný hlas",
                            "Pokročilé stádium: ztráta řeči, komunikace přes dotek",
                            "Emoce zůstávají do konce — láska a přítomnost pomáhá"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dementia-m2-quiz",
                    "title": "Ověřte si: Alzheimerova choroba",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Jaký typ otázek je vhodný ve středním stádiu Alzheimera?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Otevřené otázky (Co chceš?)", "correct": False},
                                {"id": "b", "text": "Ano/ne otázky (Chceš čaj?)", "correct": True},
                                {"id": "c", "text": "Složité otázky s více možnostmi", "correct": False}
                            ],
                            "explanation": "Ve středním stádiu jsou nejvhodnější jednoduché ano/ne otázky. Otevřené otázky mohou být příliš složité a frustrující."
                        },
                        {
                            "id": "q2",
                            "question": "Vnímá člověk v pokročilém stádiu Alzheimera emoce okolí?",
                            "type": "true_false",
                            "correct_answer": True,
                            "explanation": "Ano! I v pokročilém stádiu člověk vnímá emoce — laskavý dotek a klidný hlas ho uklidní. Emocionální vnímání přetrvává nejdéle."
                        },
                        {
                            "id": "q3",
                            "question": "Seřaďte stádia Alzheimerovy choroby od nejranějšího po nejpokročilejší:",
                            "type": "ordering",
                            "correct_order": [
                                "Mírné: zapomínání jmen, hledání slov, dezorientace v novém prostředí",
                                "Střední: potřeba pomoci s oblékáním, nepoznává blízké, bloudění",
                                "Těžké: úplná závislost na péči, ztráta řeči, neschopnost samostatného pohybu"
                            ],
                            "explanation": "Alzheimer postupuje od mírných potíží s pamětí přes střední stádium (potřeba pomoci) až po těžké stádium (úplná závislost). Průběh trvá průměrně 8–12 let."
                        },
                        {
                            "id": "q4",
                            "question": "Jak nejlépe reagovat, když osoba s Alzheimerem opakovaně klade stejnou otázku?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Odpovědět trpělivě pokaždé znovu, jako by to slyšeli poprvé", "correct": True},
                                {"id": "b", "text": "Říct: 'To jsi se už ptal/a, odpověděl/a jsem ti'", "correct": False},
                                {"id": "c", "text": "Ignorovat opakované otázky", "correct": False}
                            ],
                            "explanation": "Osoba s demencí si opravdu nepamatuje, že se ptala. Pro ni je to poprvé. Trpělivá odpověď snižuje úzkost a dává pocit bezpečí."
                        },
                        {
                            "id": "q5",
                            "question": "Člověku s demencí v pozdním stádiu je nejlepší připomínat, že jeho blízcí již nežijí.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NIKDY! Každé sdělení o smrti blízkého prožívá člověk s demencí ZNOVU, jako by to slyšel poprvé. Je lepší vstoupit do jeho reality a přesměrovat na pozitivní vzpomínky."
                        }
                    ]
                }
            },
            {
                "id": "dementia-m3",
                "title": "Lewy body a vaskulární demence",
                "order": 3,
                "duration_minutes": 12,
                "icon": "🔍",
                "lessons": [
                    {
                        "id": "dementia-m3-l1",
                        "title": "Demence s Lewyho tělísky",
                        "type": "article",
                        "content": """<h2>Demence s Lewyho tělísky — záhadný chameleon</h2>

<p>Demence s Lewyho tělísky (DLB) je <strong>druhá nejčastější degenerativní demence</strong> po Alzheimeru. Je zákeřná, protože se často zaměňuje s jinými diagnózami.</p>

<h3>Typické příznaky</h3>
<ul>
<li><strong>Kolísání pozornosti</strong> — jeden den je 'jasný", druhý den zmatený</li>
<li><strong>Vizuální halucinace</strong> — vidí lidi, zvířata, děti (velmi realistické!)</li>
<li><strong>Parkinsonismus</strong> — ztuhlost, pomalá chůze, třes</li>
<li><strong>Poruchy REM spánku</strong> — 'prožívání" snů, křičí, kope ve spánku</li>
<li><strong>Opakované pády</strong> a mdloby</li>
</ul>

<h3>⚠️ KRITICKÉ UPOZORNĚNÍ</h3>
<p class="key-point" style="background: #ffe0e0;">🚨 <strong>NEUROLEPTIKA MOHOU BÝT NEBEZPEČNÁ!</strong><br>
U DLB mohou klasická antipsychotika (haloperidol aj.) způsobit těžkou reakci — ztuhlost, horečku, až ohrožení života. Vždy informujte lékaře o diagnóze DLB!</p>

<h3>Jak reagovat na halucinace</h3>
<ul>
<li><strong>NEPOPÍREJTE</strong> — neříkejte 'tam nikdo není", pro něj jsou reálné</li>
<li><strong>Přesměrujte</strong> — 'Pojďme se podívat do druhého pokoje"</li>
<li><strong>Uklidněte</strong> — 'Jsem tady s tebou, jsi v bezpečí"</li>
<li><strong>Dobré osvětlení</strong> — stíny mohou vyvolat halucinace</li>
</ul>""",
                        "key_points": [
                            "Kolisani pozornosti — dobre a spatne dny",
                            "Vizuální halucinace jsou velmi realistické — nepopírejte je",
                            "POZOR na neuroleptika — mohou být nebezpečná!",
                            "Poruchy REM spánku — křik a pohyb ve spánku",
                            "Přesměrujte, uklidněte, zajistěte dobré osvětlení"
                        ]
                    },
                    {
                        "id": "dementia-m3-l2",
                        "title": "Vaskulární demence",
                        "type": "article",
                        "content": """<h2>Vaskulární demence — mozek bez kyslíku</h2>

<p><strong>Vaskulární demence</strong> vzniká, když mozek nedostává dostatek krve a kyslíku — nejčastěji po cévní mozkové příhodě nebo při postižení malých cév.</p>

<h3>Jak se liší od Alzheimera</h3>
<ul>
<li><strong>Schodovité zhoršování</strong> — náhlé zhoršení (po příhodě), pak stabilita, pak další zhoršení</li>
<li><strong>Pomalejší myšlení</strong> — pacient 'ví, ale trvá mu to déle"</li>
<li><strong>Paměť může být lepší</strong> než u Alzheimera — hlavní problém je rychlost a plánování</li>
<li><strong>Deprese</strong> — velmi častá a může zhoršovat kognitivní příznaky</li>
<li><strong>Emocionální labilita</strong> — náhlý pláč nebo smích bez zjevného důvodu</li>
</ul>

<h3>Prevence (jediná demence, kde funguje!)</h3>
<ul>
<li>Kontrola krevního tlaku (hypertenze je hlavní riziko!)</li>
<li>Léčba cukrovky a vysokého cholesterolu</li>
<li>Nekouřit, omezit alkohol</li>
<li>Pravidelný pohyb — 30 minut denně</li>
<li>Léčba fibrilace síní (prevence embolií)</li>
</ul>

<p class="key-point">💡 <strong>Dobrá zpráva:</strong> Vaskulární demence je jediný typ, kde skutečně funguje PREVENCE. Kontrola cévních rizikových faktorů může zastavit nebo zpomalit zhoršování!</p>""",
                        "key_points": [
                            "Vzniká po cévních příhodách — schodovité zhoršování",
                            "Hlavní problém: pomalost myšlení, ne paměť",
                            "Deprese je velmi častá — léčte ji!",
                            "Prevence funguje: tlak, cukrovka, cholesterol, pohyb",
                            "Jediná demence, kde lze zhoršování ZASTAVIT prevencí"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dementia-m3-quiz",
                    "title": "Ověřte si: Lewy body a vaskulární demence",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Proč je důležité u demence s Lewyho tělísky informovat lékaře o diagnóze?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Kvůli speciální dietě", "correct": False},
                                {"id": "b", "text": "Některá léky (neuroleptika) mohou být nebezpečná", "correct": True},
                                {"id": "c", "text": "Potřebuje jiný typ lůžka", "correct": False}
                            ],
                            "explanation": "U demence s Lewyho tělísky mohou klasická antipsychotika způsobit těžkou, až život ohrožující reakci. Proto je nutné vždy informovat lékaře."
                        },
                        {
                            "id": "q2",
                            "question": "Která demence je jediná, kde skutečně funguje prevence?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Alzheimerova choroba", "correct": False},
                                {"id": "b", "text": "Frontotemporální demence", "correct": False},
                                {"id": "c", "text": "Vaskulární demence", "correct": True}
                            ],
                            "explanation": "Vaskulární demence vzniká kvůli cévním problémům, které lze předcházet — kontrola krevního tlaku, cukrovky, cholesterolu a pravidelný pohyb."
                        },
                        {
                            "id": "q3",
                            "question": "Proč jsou neuroleptika nebezpečná u demence s Lewyho tělísky?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Mohou způsobit závažnou alergickou reakci", "correct": False},
                                {"id": "b", "text": "Mohou výrazně zhoršit příznaky a být život ohrožující", "correct": True},
                                {"id": "c", "text": "Nemají žádný účinek", "correct": False}
                            ],
                            "explanation": "⚠️ KRITICKÉ: Neuroleptika mohou u Lewy body demence způsobit neuroleptický maligní syndrom — potenciálně smrtelnou reakci. Vždy informujte lékaře o typu demence!"
                        },
                        {
                            "id": "q4",
                            "question": "Při vizuálních halucinacích u Lewy body demence je nejlepší halucinaci popřít — 'Tam nikdo není'.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! Popírání zvyšuje úzkost. Správně: validujte EMOCI ('vidím, že vás to znepokojuje'), nepopírejte realitu, a přesměrujte pozornost (změna místnosti, činnost)."
                        },
                        {
                            "id": "q5",
                            "question": "Přiřaďte typ demence ke správnému popisu:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Lewy body demence", "right": "Zrakové halucinace + parkinsonismus"},
                                {"left": "Vaskulární demence", "right": "Skokovité zhoršování, často po mini-mrtvicích"},
                                {"left": "Frontotemporální demence", "right": "Změny chování, ztráta empatie"},
                                {"left": "Parkinsonova demence", "right": "Demence vznikající u pacientů s Parkinsonem"}
                            ],
                            "explanation": "Každý typ má specifické projevy. Lewy body = halucinace, vaskulární = skoky, frontotemporální = osobnost, Parkinson demence = u existujícího Parkinsona."
                        }
                    ]
                }
            },
            {
                "id": "dementia-m4",
                "title": "Frontotemporální demence a Parkinson",
                "order": 4,
                "duration_minutes": 12,
                "icon": "🧬",
                "lessons": [
                    {
                        "id": "dementia-m4-l1",
                        "title": "Frontotemporální demence — skrytá demence",
                        "type": "article",
                        "content": """<h2>Frontotemporální demence — když se změní osobnost</h2>

<p><strong>Frontotemporální demence (FTD)</strong> je zákeřná, protože se často projeví <strong>u lidí mezi 45–65 lety</strong> — tedy v produktivním věku. A protože začíná změnami CHOVÁNÍ, ne paměti, je často zaměňována za psychiatrické onemocnění.</p>

<h3>Varovné příznaky</h3>
<ul>
<li><strong>Ztráta empatie</strong> — 'je mu jedno, co cítím"</li>
<li><strong>Nevhodné chování na veřejnosti</strong> — říká věci, které dřív neříkal</li>
<li><strong>Kompulzivní jednání</strong> — sbírání věcí, opakované rituály</li>
<li><strong>Změny stravovacích návyků</strong> — přejídání se sladkým</li>
<li><strong>Apatie</strong> — ztráta zájmů, iniciativy</li>
<li><strong>Paměť může být dlouho ZACHOVANÁ!</strong></li>
</ul>

<h3>Proč je diagnóza tak obtížná</h3>
<p>Rodina často říká: 'Změnil se, jako by to byl jiný člověk." Lékaři mohou diagnostikovat depresi nebo bipolární poruchu. Správná diagnóza trvá průměrně <strong>3–4 roky</strong>.</p>

<h3>Komunikace s člověkem s FTD</h3>
<ul>
<li>Nastavte jasná pravidla a strukturu</li>
<li>Nevyčítejte nevhodné chování — nedokáže ho kontrolovat</li>
<li>Jednoduché pokyny, rutina</li>
<li>Vizuální připomínky (obrázky, piktogramy)</li>
<li>Chraňte před rizikovými situacemi (finance, řízení)</li>
</ul>

<p class="key-point">💡 <strong>Pokud se osobnost blízkého člověka (45–65 let) výrazně změní a léčba antidepresivy nepomáhá — žádejte neurologické vyšetření na FTD.</strong></p>""",
                        "key_points": [
                            "Postihuje lidi v produktivním věku (45–65 let)",
                            "Začíná změnami chování a osobnosti, ne paměti",
                            "Často zaměňována za psychiatrické onemocnění",
                            "Diagnóza trvá průměrně 3–4 roky",
                            "Nevhodné chování nelze kontrolovat — je to nemoc"
                        ]
                    },
                    {
                        "id": "dementia-m4-l2",
                        "title": "Demence při Parkinsonově chorobě",
                        "type": "article",
                        "content": """<h2>Parkinsonova choroba a demence</h2>

<p>Až <strong>80 % lidí s Parkinsonovou chorobou</strong> vyvine v pozdějších stádiích demenci. Tato forma je podobná demenci s Lewyho tělísky, ale liší se pořadím příznaků.</p>

<h3>Rozdíl: Lewy body vs. Parkinson s demencí</h3>
<ul>
<li><strong>Lewy body demence:</strong> kognitivní příznaky se objeví PRVNÍ nebo současně s pohybovými</li>
<li><strong>Parkinson s demencí:</strong> pohybové příznaky (třes, ztuhlost) jsou NEJMÉNĚ 1 rok PŘED demencí</li>
</ul>

<h3>Příznaky demence při Parkinsonu</h3>
<ul>
<li>Zpomalené myšlení a reakce</li>
<li>Problémy s plánováním a organizací</li>
<li>Vizuální halucinace (podobně jako u Lewy body)</li>
<li>Deprese a apatie</li>
<li>Denní ospalost, noční neklid</li>
</ul>

<h3>Komunikační tipy</h3>
<ul>
<li>Dejte více času na odpověď — myšlení je pomalejší, ne hloupější</li>
<li>Tichá mimika neznamená lhostejnost (maskový obličej je příznak Parkinsonu)</li>
<li>Tichý hlas — přibližte se, nežádejte křičení</li>
<li>Halucinace: stejný přístup jako u Lewy body — uklidněte, přesměrujte</li>
</ul>

<p class="key-point">💡 <strong>Tichý obličej ≠ lhostejnost.</strong> U Parkinsona jsou oslabeny obličejové svaly — člověk CÍTÍ emoce, ale nedokáže je VYJÁDŘIT mimikou. Říkáme tomu 'maskový obličej" (hypomimie).</p>""",
                        "key_points": [
                            "Až 80 % lidí s Parkinsonem vyvine demenci",
                            "Pohybové příznaky přichází PŘED kognitivními (rozdíl od Lewy body)",
                            "Zpomalené myšlení — dejte více času na odpověď",
                            "Maskový obličej ≠ lhostejnost — svaly, ne emoce",
                            "Halucinace: uklidněte, přesměrujte, nepopírejte"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dementia-m4-quiz",
                    "title": "Ověřte si: FTD a Parkinson",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Jaký je hlavní rozdíl mezi frontotemporální demencí a Alzheimerem?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "FTD začíná ztrátou paměti", "correct": False},
                                {"id": "b", "text": "FTD začíná změnami chování a osobnosti, paměť je zachovaná", "correct": True},
                                {"id": "c", "text": "FTD postihuje jen starší lidi", "correct": False}
                            ],
                            "explanation": "Frontotemporální demence typicky začíná změnami osobnosti a chování, zatímco paměť může být dlouho zachovaná. Na rozdíl od Alzheimera postihuje často mladší lidi (45–65 let)."
                        },
                        {
                            "id": "q2",
                            "question": "Co znamená 'maskový obličej' u Parkinsonovy choroby?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Pacient je lhostejný", "correct": False},
                                {"id": "b", "text": "Pacient odmítá komunikovat", "correct": False},
                                {"id": "c", "text": "Oslabené obličejové svaly — emoce cítí, ale nedokáže je vyjádřit", "correct": True}
                            ],
                            "explanation": "Maskový obličej (hypomimie) je příznak Parkinsona — obličejové svaly jsou oslabeny. Člověk CÍTÍ emoce plně, jen je nedokáže vyjádřit mimikou."
                        },
                        {
                            "id": "q3",
                            "question": "Který typ demence se typicky projevuje NEJDŘÍVE změnami osobnosti a chování, nikoliv pamětí?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Alzheimerova choroba", "correct": False},
                                {"id": "b", "text": "Frontotemporální demence (FTD)", "correct": True},
                                {"id": "c", "text": "Vaskulární demence", "correct": False},
                                {"id": "d", "text": "Lewy body demence", "correct": False}
                            ],
                            "explanation": "FTD je unikátní tím, že první příznaky jsou změny chování a osobnosti — ne paměti. Člověk může být hrubý, ztratit empatii, nebo se chovat nevhodně."
                        },
                        {
                            "id": "q4",
                            "question": "Frontotemporální demence postihuje nejčastěji lidi nad 80 let.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! FTD má typicky RANĚJŠÍ nástup než Alzheimer — často mezi 45–65 lety. To ji dělá obzvlášť tragickou pro rodiny."
                        }
                    ]
                }
            },
            {
                "id": "dementia-m5",
                "title": "Kde hledat pomoc v ČR",
                "order": 5,
                "duration_minutes": 8,
                "icon": "🏥",
                "lessons": [
                    {
                        "id": "dementia-m5-l1",
                        "title": "Podpora pro rodiny a pečovatele",
                        "type": "article",
                        "content": """<h2>Kde najít pomoc — průvodce pro rodiny</h2>

<h3>Diagnostika</h3>
<ul>
<li><strong>Memory kliniky</strong> — specializovaná pracoviště: Motol, FN Brno, FN Olomouc, FN Hradec Králové</li>
<li><strong>Neurolog</strong> — první kontakt pro vyšetření</li>
<li><strong>Geriatr</strong> — pro seniory s více diagnózami</li>
</ul>

<h3>Organizace</h3>
<ul>
<li><strong>Česká alzheimerovská společnost</strong> (ČALS) — alzheimer.cz — poradenství, svépomocné skupiny</li>
<li><strong>Alzheimer nadační fond</strong> — finanční podpora rodin</li>
<li><strong>Diakonie, Charita</strong> — terénní a odlehčovací služby</li>
<li><strong>Centrum pro studium demence</strong> — výzkum a vzdělávání</li>
</ul>

<h3>Služby pro rodiny</h3>
<ul>
<li><strong>Denní stacionáře</strong> — péče přes den, pečovatel si odpočine</li>
<li><strong>Respitní péče</strong> — krátkodobé umístění pro odpočinek rodiny</li>
<li><strong>Pečovatelská služba</strong> — pomoc v domácnosti</li>
<li><strong>Tísňové linky:</strong>
  <ul>
    <li>116 123 — psychická podpora</li>
    <li>155 — při akutním zhoršení</li>
    <li>ČALS linka: 283 880 346</li>
  </ul>
</li>
</ul>

<h3>Pro pečovatele</h3>
<ul>
<li>Příspěvek na péči (zákon č. 108/2006 Sb.) — 4 stupně</li>
<li>Svépomocné skupiny — sdílení zkušeností s dalšími rodinami</li>
<li>Psychologická podpora — pečovatel TAKÉ potřebuje péči!</li>
</ul>

<p class="key-point">💡 <strong>Nejdůležitější rada pro pečovatele:</strong> Požádat o pomoc NENÍ slabost. Nemůžete pečovat o druhého, pokud se sami zhroutíte. Využívejte respitní péči, mluvte o svých pocitech, hledejte podporu.</p>""",
                        "key_points": [
                            "Memory kliniky pro diagnostiku — Motol, Brno, Olomouc, HK",
                            "ČALS (alzheimer.cz) — hlavní organizace pro rodiny",
                            "Denní stacionáře a respitní péče — odpočinek pro pečovatele",
                            "Příspěvek na péči — 4 stupně finanční podpory",
                            "Pečovatel TAKÉ potřebuje péči — není slabost požádat o pomoc"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dementia-m5-quiz",
                    "title": "Kvíz: Kde hledat pomoc v ČR",
                    "passing_score": 60,
                    "questions": [
                        {
                            "id": "dem-m5-q1",
                            "type": "single_choice",
                            "question": "Jak se nazývají specializovaná pracoviště pro diagnostiku demence?",
                            "options": ["Rehabilitační centra", "Memory kliniky", "Neurochirurgická oddělení", "Onkologická centra"],
                            "correct": 1,
                            "explanation": "Memory kliniky jsou specializovaná pracoviště zaměřená na diagnostiku a léčbu poruch paměti a demencí."
                        },
                        {
                            "id": "dem-m5-q2",
                            "type": "true_false",
                            "question": "Česká alzheimerovská společnost (ČALS) nabízí poradenství a svépomocné skupiny pro rodiny.",
                            "correct": True,
                            "explanation": "ČALS (alzheimer.cz) je hlavní organizace pro pomoc rodinám lidí s demencí v ČR."
                        },
                        {
                            "id": "dem-m5-q3",
                            "type": "matching",
                            "question": "Přiřaďte službu k jejímu popisu:",
                            "pairs": [
                                {"left": "Denní stacionář", "right": "Péče přes den — pečovatel si odpočine"},
                                {"left": "Respitní péče", "right": "Krátkodobé umístění pro odpočinek rodiny"},
                                {"left": "Pečovatelská služba", "right": "Pomoc v domácnosti"},
                                {"left": "Příspěvek na péči", "right": "Finanční podpora ve 4 stupních"}
                            ],
                            "explanation": "Různé služby zajišťují podporu jak pro osobu s demencí, tak pro pečovatele."
                        },
                        {
                            "id": "dem-m5-q4",
                            "type": "single_choice",
                            "question": "Jaké telefonní číslo je linka ČALS pro poradenství?",
                            "options": ["116 123", "155", "283 880 346", "112"],
                            "correct": 2,
                            "explanation": "ČALS linka 283 880 346 poskytuje specifické poradenství pro rodiny lidí s demencí."
                        },
                        {
                            "id": "dem-m5-q5",
                            "type": "true_false",
                            "question": "Požádat o pomoc jako pečovatel je projevem slabosti.",
                            "correct": False,
                            "explanation": "Požádat o pomoc NENÍ slabost! Pečovatel potřebuje péči stejně jako nemocný. Využívejte respitní péči a svépomocné skupiny."
                        }
                    ]
                }
            },
            {
                "id": "dementia-m6",
                "title": "Pece o pecujiciho — prevence vyhoreni",
                "order": 6,
                "duration_minutes": 12,
                "icon": "💚",
                "lessons": [
                    {
                        "id": "dementia-m6-l1",
                        "title": "Syndrom vyhoreni u pecovatelu",
                        "type": "article",
                        "content": """<h2>Pecovatel tez potrebuje peci</h2>

<p>Pece o cloveka s demenci je <strong>jednou z nejnarocnejsich zivtnich roli</strong>. Pecovatel casto zapomina na sebe. Statistiky ukazuji:</p>

<ul>
<li><strong>40–70 %</strong> rodinnych pecovatelu trpi depresivnimi prznaky</li>
<li><strong>50 %</strong> pecovatelu ma chronicke zdravotni problemy</li>
<li>Pecovatel o cloveka s demenci stravuje prumetrne <strong>9–12 hodin denne</strong> peci</li>
<li>Riziko onemocneni pecujiciho je <strong>2–3x vyssi</strong> nez u bezne populace</li>
</ul>

<h3>Varovne znaky vyhoreni</h3>
<ul>
<li><strong>Telesne:</strong> chronicka unava, bolesti hlavy a zad, poruchy spanku, castejsi nemoci</li>
<li><strong>Emocni:</strong> podrazdeni, plac, pocity viny ('delam to spatne'), beznadej</li>
<li><strong>Socialni:</strong> izolace, ztrata zajmu o vlastni koniciky, vyhybani se pratelum</li>
<li><strong>Chovani:</strong> zvysena spotreba alkoholu, zanedbalvani vlastniho zdravi, agrese vuci nemocnemu</li>
</ul>

<p class="key-point">💡 <strong>Dulezite:</strong> Pocit viny je NORMALNY. Pecovat je tezke a clovek nemuze byt dokonaly 24/7. Pokud citite vyhoreni, NENI to vase selhani — je to signal, ze potrebujete pomoc.</p>

<h3>5 pravidel sebepece pro pecovatele</h3>
<ol>
<li><strong>Odpocion si kazdy den</strong> — alespon 30 minut JEN pro sebe (procnhazka, kniha, kava)</li>
<li><strong>Neodmitatejt pomoc</strong> — kdyz nekdo nabidne pomoc, rikejte ANO</li>
<li><strong>Mluvte o svych pocitech</strong> — svepomocna skupina, psycholog, pritel</li>
<li><strong>Hlídejte sve zdravi</strong> — pravidelne prohlidky, pohyb, strava, spanek</li>
<li><strong>Plánujte respitni peci</strong> — pravidleny odpocion neni luxus, je to nutnost</li>
</ol>""",
                        "key_points": [
                            "40–70 % pecovatelu trpi depresivnimi prznaky",
                            "Varovne znaky: chronicka unava, podrazdeni, izolace, pocity viny",
                            "Pocit viny je normalni — neni to selhani",
                            "Kazdodenni odpocinek a pravidelna respitni pece jsou nutnost",
                            "Prijimat pomoc neni slabost"
                        ]
                    },
                    {
                        "id": "dementia-m6-l2",
                        "title": "Respitni pece a prakticka podpora",
                        "type": "article",
                        "content": """<h2>Respitni pece — jak si odpocinout</h2>

<p><strong>Respitni pece</strong> znamena docasne prevzeti pece o nemocneho, aby si pecovatel mohl odpocinout. Neni to odlozeni blizkeho — je to <strong>investice do kvality pece</strong>.</p>

<h3>Formy respitni pece v CR</h3>

<h4>Denni stacionare</h4>
<ul>
<li>Odborne zarizen kde je clovek pres den, vecer jde domu</li>
<li>Programy: cviceni pameti, pohyb, tvoriiva cinnost, spolecenske aktivity</li>
<li>Pecovatel ma celodennni prostor — prace, odpocinek, vyrizovani</li>
<li>Cena: cca 100–300 Kc/den (mozno hradit z prispevku na peci)</li>
</ul>

<h4>Odlehcovaci sluzby</h4>
<ul>
<li>Profesionalni pecovatel prijde DOMU — zastoupi vas na par hodin</li>
<li>Mozno i na cele dny (respitni pobyt v zarizen)</li>
<li>Vhodne pro pravidelny odpocink pecovatele</li>
</ul>

<h4>Kratkodoba ubytovaci pece</h4>
<ul>
<li>Domov seniru nebo specializovane zarizeni na 1–4 tydny</li>
<li>Idealni pro dovolenou pecovatele nebo hospitalizaci</li>
<li>Nutno objednat dopredu — kapacity byvaji omezene</li>
</ul>

<h3>Financni podpora</h3>
<ul>
<li><strong>Prispevek na peci</strong> (zakon 108/2006 Sb.)</li>
  <ul>
    <li>Stupen I: 880 Kc/mesic</li>
    <li>Stupen II: 4 400 Kc/mesic</li>
    <li>Stupen III: 12 800 Kc/mesic</li>
    <li>Stupen IV: 19 200 Kc/mesic</li>
  </ul>
<li>Zadost na Uradu prace</li>
<li>Mozno vyuzit na profesionalni peci i rodinneho pecovatele</li>
</ul>

<h3>Svepomocne skupiny</h3>
<ul>
<li><strong>CALS</strong> — pravidelna setkani po cele CR (i online)</li>
<li>Sdileni zkusenosti s lidmi, kteri rozumi vasi situaci</li>
<li>Praktickke rady: <em>'Jak zvladate nocni neklid?'</em></li>
<li>Emocni podpora: <em>'Nejste v tom sami'</em></li>
</ul>

<p class="key-point">💡 <strong>Pamatujte:</strong> Nemuzete nalit z prazdneho. Pokud se sami zhrouttite, kdo se postara o vaseho blizkeho? Pravidelny odpocinek je SOUCASI pece, ne jeji opak.</p>""",
                        "key_points": [
                            "Respitni pece = odpocion pro pecovatele, ne odlozeni blizkeho",
                            "Denni stacionare, odlehcovaci sluzby, kratkodoba ubytovaci pece",
                            "Prispevek na peci: 880–19 200 Kc mesicne podle stupne",
                            "CALS svepomocne skupiny po cele CR (i online)",
                            "Nemuzete nalit z prazdneho — odpocinek je soucast pece"
                        ]
                    }
                ],
                "quiz": {
                    "id": "dementia-m6-quiz",
                    "title": "Overite si: Pece o pecujiciho",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Jake procento rodinnych pecovatelu trpi depresivnimi prznaky?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Asi 10 %", "correct": False},
                                {"id": "b", "text": "40–70 %", "correct": True},
                                {"id": "c", "text": "Asi 5 %", "correct": False}
                            ],
                            "explanation": "Studie ukazuji, ze 40–70 % rodinnych pecovatelu o osoby s demenci trpi depresivnimi prznaky. Je to obrovske cislo a ukazuje, jak dulezita je podpora pecovatelu."
                        },
                        {
                            "id": "q2",
                            "question": "Co je respitni pece?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Trvale umisteni do domova senioru", "correct": False},
                                {"id": "b", "text": "Docasne prevzeti pece, aby si pecovatel odpocinul", "correct": True},
                                {"id": "c", "text": "Ukonceni pece o nemocneho", "correct": False}
                            ],
                            "explanation": "Respitni pece je docasne prevzeti pece o nemocneho (na hodiny, dny nebo tydny), aby si pecovatel mohl odpocinout a nabrat sily."
                        },
                        {
                            "id": "q3",
                            "question": "Pecovatel citi vinu, ze nezvlada. Co je spravna reakce?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Musi se vic snazit a nepripoustet si slabost", "correct": False},
                                {"id": "b", "text": "Je to normalni pocit, potrebuje pomoc a odpocinek", "correct": True},
                                {"id": "c", "text": "Mel by prestst pecovat a najit profesioonala", "correct": False}
                            ],
                            "explanation": "Pocit viny je u pecovatelu zcela normalni a NENI to selhani. Spravna reakce je priznat si unavu, pozadat o pomoc a pravidelne vyuzivat respitni peci."
                        },
                        {
                            "id": "q4",
                            "question": "Seřaďte kroky prevence vyhoření pečujícího:",
                            "type": "ordering",
                            "correct_order": [
                                "Přijměte, že nemůžete vše zvládnout sami",
                                "Požádejte rodinu nebo služby o pravidelnou výpomoc",
                                "Najděte si alespoň jednu aktivitu jen pro sebe",
                                "Pravidelně konzultujte svůj stav s odborníkem (psycholog, podpůrná skupina)"
                            ],
                            "explanation": "Prevence vyhoření vyžaduje systém: přijetí limitů → delegování → vlastní aktivity → profesionální podpora. Pečující musí pečovat i o sebe."
                        },
                        {
                            "id": "q5",
                            "question": "Pečující, který občas cítí hněv nebo frustraci vůči osobě s demencí, je špatný pečující.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "NE! Hněv a frustrace jsou NORMÁLNÍ emoce. Každý pečující je zažívá. Důležité je tyto emoce rozpoznat, nejednat pod jejich vlivem, a vyhledat podporu."
                        }
                    ]
                }
            }
        ]
    },

    # ============================================
    # KURZ 5: PARKINSONOVA CHOROBA (v256)
    # ============================================
    "parkinson": {
        "id": "parkinson",
        "title": "Parkinsonova choroba — komplexní průvodce",
        "subtitle": "Od prvních příznaků po každodenní péči a komunikaci",
        "icon": "🤲",
        "category": "Neurodegenerativní",
        "difficulty": "intermediate",
        "duration_minutes": 60,
        "tags": ["Parkinson", "neurodegenerace", "tremor", "dopamin", "komunikace", "pečovatel", "vzácné onemocnění", "young-onset", "burnout"],
        "description": "Komplexní průvodce Parkinsonovou chorobou — co je to, jak se projevuje, jak komunikovat s nemocným a kde v ČR najít pomoc. Pro pečovatele, rodiny i zdravotníky.",
        "target_audience": ["pečovatelé", "rodina", "zdravotníci", "sociální pracovníci"],
        "learning_objectives": [
            "Pochopíte podstatu Parkinsonovy choroby a úlohu dopaminu",
            "Rozpoznáte 4 hlavní motorické příznaky",
            "Porozumíte nemotorickým příznakům (deprese, poruchy spánku, halucinace)",
            "Naučíte se komunikovat s člověkem se změněnou řečí a mimikou",
            "Budete vědět, kde v ČR najít odbornou pomoc a podporu",
            "Pochopíte rizika vyhoření pečovatele a specifika Young-Onset Parkinsona"
        ],
        "modules": [
            # ---- MODUL 1: Co je Parkinsonova choroba? ----
            {
                "id": "parkinson-m1",
                "title": "Co je Parkinsonova choroba?",
                "order": 1,
                "duration_minutes": 10,
                "icon": "📖",
                "lessons": [
                    {
                        "id": "parkinson-m1-l1",
                        "title": "Základy Parkinsonovy choroby",
                        "type": "article",
                        "prerequisites": [],
                        "content": """<h2>Co je Parkinsonova choroba?</h2>
<p><strong>Parkinsonova choroba</strong> je druhé nejčastější neurodegenerativní onemocnění na světě — hned po Alzheimerově chorobě. Poprvé ji popsal londýnský lékař <em>James Parkinson</em> v roce 1817.</p>

<p>V České republice žije přibližně <strong>20 000 – 25 000</strong> lidí s Parkinsonovou chorobou. Typicky se objevuje mezi 55. a 65. rokem života, ale může přijít i dříve (tzv. Young Onset Parkinson).</p>

<h3>Co se děje v mozku?</h3>
<p>V hloubi mozku existuje oblast zvaná <strong>substantia nigra</strong> (černá substance). Zde se vyrábí <strong>dopamin</strong> — důležitý neurotransmiter, který řídí pohyby, motivaci a pocit odměny. U Parkinsonovy choroby tyto buňky postupně odumírají. Když mozek ztratí <strong>60–80 %</strong> dopaminových neuronů, začnou se objevovat viditelné příznaky.</p>

<table>
<tr><th>Pojem</th><th>Význam</th></tr>
<tr><td>Substantia nigra</td><td>Oblast mozku, kde se vyrábí dopamin</td></tr>
<tr><td>Dopamin</td><td>Neurotransmiter řídící pohyb a motivaci</td></tr>
<tr><td>Neurodegenerace</td><td>Postupné odumírání nervových buněk</td></tr>
</table>

<p class="key-point">💡 <strong>Klíčové:</strong> Parkinsonova choroba NENÍ jen „třes". Je to komplexní onemocnění postihující pohyb, náladu, spánek, trávení i myšlení. Není vyléčitelná, ale správná léčba umožňuje roky kvalitního života.</p>""",
                        "key_points": [
                            "Druhé nejčastější neurodegenerativní onemocnění po Alzheimeru",
                            "Podstatou je nedostatek dopaminu v substantia nigra",
                            "V ČR žije 20–25 tisíc lidí s Parkinsonem",
                            "Není to jen třes — je to komplexní onemocnění postihující pohyb, náladu i myšlení",
                            "Není vyléčitelný, ale správná léčba umožňuje roky kvalitního života"
                        ]
                    },
                    {
                        "id": "parkinson-m1-l2",
                        "title": "Jak Parkinsonova choroba vzniká a kdo je ohrožen?",
                        "type": "article",
                        "prerequisites": ["parkinson-m1-l1"],
                        "content": """<h2>Jak Parkinsonova choroba vzniká?</h2>
<p>Většina případů Parkinsonovy choroby je <strong>idiopatických</strong> — to znamená, že přesnou příčinu neznáme. Asi 10–15 % případů má genetickou složku.</p>

<h3>Rizikové faktory</h3>
<table>
<tr><th>Typ faktoru</th><th>Příklad</th><th>Míra rizika</th></tr>
<tr><td><strong>Věk</strong></td><td>Nejčastěji po 55. roce</td><td>Hlavní faktor — riziko roste s věkem</td></tr>
<tr><td><strong>Pohlaví</strong></td><td>Muži</td><td>1,5× vyšší riziko než ženy</td></tr>
<tr><td><strong>Genetika</strong></td><td>LRRK2, PARK2, PINK1 mutace</td><td>10–15 % případů; vyšší u Young-Onset</td></tr>
<tr><td><strong>Environmentální</strong></td><td>Pesticidy, herbicidy, těžké kovy</td><td>Zvýšené riziko u zemědělců</td></tr>
<tr><td><strong>Úrazy</strong></td><td>Opakovaná poranění hlavy</td><td>Mírně zvýšené riziko</td></tr>
<tr><td><strong>Ochranné faktory</strong></td><td>Káva, nikotín, fyzická aktivita</td><td>Snižují riziko (→ výzkum)</td></tr>
</table>

<h3>Co se děje na buněčné úrovni?</h3>
<p>V nervových buňkách se hromadí abnormální shluky bílkoviny <strong>alpha-synuklein</strong> — říkáme jim <em>Lewyho tělíska</em>. Tato tělíska poškozují a nakonec zabíjejí nervové buňky.</p>

<p>Příznaky se objeví až při ztrátě <strong>60–80 %</strong> dopaminových neuronů. To znamená, že nemoc tiše probíhá roky, než si jí všimneme.</p>

<h3>Zajímavost — osa střevo–mozek</h3>
<p>Nejnovější výzkumy ukazují, že Parkinsonova choroba může začínat v trávicím traktu. Alpha-synuklein byl nalezen v nervových buňkách střev, možná ještě předtím, než se objeví v mozku. Proto je <strong>zácpa</strong> tak častým raným příznakem.</p>

<p class="key-point">💡 <strong>Klíčové:</strong> Nemoc probíhá skrytě mnoho let. Když se objeví třes, mozek už ztratil většinu dopaminových neuronů.</p>""",
                        "key_points": [
                            "Většina případů je idiopatických (příčina neznámá)",
                            "Hlavní rizikový faktor je věk; muži onemocní 1,5× častěji",
                            "Lewyho tělíska — shluky bílkoviny alpha-synuklein poškozují neurony",
                            "Příznaky se objeví až při ztrátě 60–80 % dopaminových neuronů",
                            "Výzkum ukazuje možnou souvislost s trávicím traktem (osa střevo–mozek)"
                        ]
                    }
                ],
                "quiz": {
                    "id": "parkinson-m1-quiz",
                    "title": "Ověřte si: Co je Parkinsonova choroba?",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Která látka v mozku chybí při Parkinsonově chorobě?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Serotonin", "correct": False},
                                {"id": "b", "text": "Dopamin", "correct": True},
                                {"id": "c", "text": "Adrenalin", "correct": False},
                                {"id": "d", "text": "Melatonin", "correct": False}
                            ],
                            "explanation": "Dopamin je neurotransmiter vyráběný v substantia nigra. Při Parkinsonově chorobě buňky produkující dopamin postupně odumírají."
                        },
                        {
                            "id": "q2",
                            "question": "Parkinsonova choroba je nejčastější neurodegenerativní onemocnění na světě.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "Parkinsonova choroba je DRUHÉ nejčastější — po Alzheimerově chorobě."
                        },
                        {
                            "id": "q3",
                            "question": "Kolik lidí v ČR přibližně žije s Parkinsonovou chorobou?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Asi 5 000", "correct": False},
                                {"id": "b", "text": "Asi 20 000 – 25 000", "correct": True},
                                {"id": "c", "text": "Asi 50 000 – 60 000", "correct": False},
                                {"id": "d", "text": "Více než 100 000", "correct": False}
                            ],
                            "explanation": "V České republice žije přibližně 20 000 – 25 000 lidí s diagnostikovanou Parkinsonovou chorobou. Celosvětově je to asi 10 milionů lidí."
                        },
                        {
                            "id": "q4",
                            "question": "Spojte správně pojmy s jejich definicí:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Dopamin", "right": "Neurotransmiter pro pohyb a motivaci"},
                                {"left": "Substantia nigra", "right": "Oblast mozku postižená u Parkinsona"},
                                {"left": "Lewyho tělíska", "right": "Patologické shluky bílkovin v nervových buňkách"},
                                {"left": "Alpha-synuklein", "right": "Bílkovina tvořící Lewyho tělíska"}
                            ],
                            "explanation": "Dopamin se vyrábí v substantia nigra. Lewyho tělíska tvořená alpha-synukleinem poškozují neurony produkující dopamin."
                        },
                        {
                            "id": "q5",
                            "question": "Ve kterém věku se Parkinsonova choroba nejčastěji objeví?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "30–40 let", "correct": False},
                                {"id": "b", "text": "55–65 let", "correct": True},
                                {"id": "c", "text": "Nad 80 let", "correct": False},
                                {"id": "d", "text": "Může se objevit v jakémkoliv věku stejně", "correct": False}
                            ],
                            "explanation": "Typický nástup je mezi 55. a 65. rokem. Existuje i Young-Onset Parkinson (před 50. rokem, 5–10 % případů), ale u dětí se prakticky nevyskytuje."
                        },
                        {
                            "id": "q6",
                            "question": "Příznaky Parkinsona se objeví už při malé ztrátě dopaminových neuronů (asi 10 %).",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "Příznaky se objeví teprve při ztrátě 60–80 % dopaminových neuronů. Nemoc proto tiše probíhá roky, než si jí všimneme."
                        }
                    ]
                }
            },

            # ---- MODUL 2: Motorické příznaky ----
            {
                "id": "parkinson-m2",
                "title": "Motorické příznaky",
                "order": 2,
                "duration_minutes": 10,
                "icon": "🏃",
                "lessons": [
                    {
                        "id": "parkinson-m2-l1",
                        "title": "Čtyři hlavní motorické příznaky",
                        "type": "article",
                        "prerequisites": ["parkinson-m1-l2"],
                        "content": """<h2>Čtyři hlavní motorické příznaky — TRAP</h2>
<p>Parkinsonova choroba má 4 hlavní motorické příznaky, známé pod zkratkou <strong>TRAP</strong>:</p>

<table>
<tr><th>Příznak</th><th>Popis</th><th>Příklad</th></tr>
<tr><td><strong>T</strong>remor</td><td>Klidový třes</td><td>„Počítání peněz" (pill-rolling) jednou rukou</td></tr>
<tr><td><strong>R</strong>igidita</td><td>Ztuhlost svalů</td><td>„Ozubené kolečko" při vyšetření</td></tr>
<tr><td><strong>A</strong>kineze/Bradykineze</td><td>Zpomalení pohybů</td><td>Mikrografie, tichý hlas, pomalá chůze</td></tr>
<tr><td><strong>P</strong>osturální nestabilita</td><td>Problémy s rovnováhou</td><td>Freezing, riziko pádů</td></tr>
</table>

<h3>1. Tremor (klidový třes)</h3>
<p>Rytmický třes, typicky v klidu. Často začíná na jedné ruce — tzv. <em>„počítání peněz"</em> (pill-rolling). Třes se zhoršuje při stresu a únavě, naopak mizí při cíleném pohybu a ve spánku.</p>
<p class="key-point">💡 <strong>Důležité:</strong> 20–30 % lidí s Parkinsonem třes NIKDY nevyvine!</p>

<h3>2. Rigidita (ztuhlost)</h3>
<p>Svaly jsou trvale napjaté — jako ohýbání olověné trubky. Lékař při vyšetření cítí <em>„ozubené kolečko"</em> — drobné, trhavé odpory. Rigidita způsobuje bolest, omezenou pohyblivost a únavu.</p>

<h3>3. Bradykineze (zpomalení pohybu)</h3>
<p>Často <strong>nejvíce omezující příznak</strong>. Pohyby jsou pomalé, malé a vyčerpávající. Projevuje se: malé písmo (mikrografie), tichý hlas, pomalá chůze, ztráta souhybu paží, obtížné vstávání ze židle.</p>

<h3>4. Posturální nestabilita</h3>
<p>Přichází typicky v pozdějších stádiích. Problémy s rovnováhou, riziko pádů, <strong>freezing</strong> (náhlé „zamrznutí" při chůzi — nohy jako přilepené k podlaze).</p>

<p><strong>Asymetrický začátek</strong> je typický — příznaky začínají na jedné straně těla a postupně se rozšiřují na obě.</p>""",
                        "key_points": [
                            "4 hlavní příznaky: tremor, rigidita, bradykineze, posturální nestabilita",
                            "Třes NENÍ povinný — 20–30 % lidí s Parkinsonem nikdy netřese",
                            "Bradykineze (zpomalení) je často nejvíce omezující",
                            "Příznaky začínají typicky na jedné straně těla",
                            "Freezing (zamrznutí) = náhlé zastavení pohybu, zejména při chůzi"
                        ]
                    },
                    {
                        "id": "parkinson-m2-l2",
                        "title": "Jak motorické příznaky ovlivňují každodenní život",
                        "type": "article",
                        "prerequisites": ["parkinson-m2-l1"],
                        "content": """<h2>Motorické příznaky v každodenním životě</h2>
<p>Motorické příznaky Parkinsona mění každodenní život — zapínání knoflíků, jedení, chůze dveřmi. Zde jsou nejčastější problémy a jak pomoci:</p>

<h3>Freezing (zamrznutí při chůzi)</h3>
<p>Člověk se náhle zastaví — nohy „přilepené" k podlaze. Pomáhají:</p>
<table>
<tr><th>Typ podnětu</th><th>Technika</th><th>Příklad</th></tr>
<tr><td><strong>Vizuální</strong></td><td>Cíl na podlaze</td><td>Laserový ukazatel na botě, barevná páska</td></tr>
<tr><td><strong>Zvukový</strong></td><td>Rytmus</td><td>Metronom, počítání „raz, dva, tři"</td></tr>
<tr><td><strong>Mentální</strong></td><td>Slovní pobídka</td><td>„A… TEĎ krok!" — přeruší blok</td></tr>
<tr><td><strong>Taktilní</strong></td><td>Dotek</td><td>Lehký dotek na rameno, nabídnutá ruka</td></tr>
</table>

<h3>On/off fenomén</h3>
<p>Léky (L-DOPA) mají časově omezený účinek. V <strong>„on" fázi</strong> se člověk cítí relativně dobře, v <strong>„off" fázi</strong> se příznaky vrátí. Proto je důležité plánovat aktivity na dobu, kdy léky fungují.</p>

<h3>Festinace a mikrografie</h3>
<p><strong>Festinace</strong> = drobný, šouravý, zrychlující se krok — riziko pádu vpřed. <strong>Mikrografie</strong> = písmo se postupně zmenšuje. Obojí je projev bradykineze.</p>

<h3>Prevence pádů</h3>
<p>Pády jsou u Parkinsona velmi časté a nebezpečné. Pomáhá:</p>
<ul>
<li>Pravidelné cvičení (<strong>tai chi!</strong>)</li>
<li>Odstranění překážek doma (koberce, prahy)</li>
<li>Kvalitní obuv a dobré osvětlení</li>
<li>Madla v koupelně a na toaletě</li>
</ul>

<p class="key-point">💡 <strong>Klíčové:</strong> Plánujte náročné aktivity na dobu, kdy léky fungují nejlépe (období „on").</p>""",
                        "key_points": [
                            "Freezing = náhlé zamrznutí při chůzi; pomáhají vizuální a zvukové podněty",
                            "On/off fenomén: kolísání účinnosti léků během dne",
                            "Prevence pádů: pravidelné cvičení, odstranění překážek doma, kvalitní obuv",
                            "Mikrografie (drobné písmo) je častým projevem bradykineze",
                            "Plánujte náročné aktivity na dobu, kdy léky fungují nejlépe"
                        ]
                    }
                ],
                "quiz": {
                    "id": "parkinson-m2-quiz",
                    "title": "Ověřte si: Motorické příznaky",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Spojte motorický příznak s jeho popisem:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Tremor", "right": "Klidový třes, typicky začíná na jedné ruce"},
                                {"left": "Rigidita", "right": "Ztuhlost svalů, 'ozubené kolečko'"},
                                {"left": "Bradykineze", "right": "Zpomalení a zmenšení pohybů"},
                                {"left": "Posturální nestabilita", "right": "Nestabilita při stoji a chůzi"}
                            ],
                            "explanation": "TRAP: Tremor (třes), Rigidita (ztuhlost), Akineze/bradykineze (zpomalení), Posturální nestabilita (rovnováha)."
                        },
                        {
                            "id": "q2",
                            "question": "Každý člověk s Parkinsonem trpí třesem.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "20–30 % lidí s Parkinsonem třes nikdy nevyvine. Parkinson se může projevovat zejména ztuhlostí a zpomalením."
                        },
                        {
                            "id": "q3",
                            "question": "Co je freezing (zamrznutí)?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Náhlá neschopnost začít nebo pokračovat v kroku", "correct": True},
                                {"id": "b", "text": "Zamrznutí končetin chladem", "correct": False},
                                {"id": "c", "text": "Ztráta vědomí", "correct": False},
                                {"id": "d", "text": "Porucha rovnováhy způsobená závratí", "correct": False}
                            ],
                            "explanation": "Freezing je náhlé 'přilepení' nohou k podlaze — člověk chce jít, ale nohy neposlouchají. Nejčastěji se objevuje při průchodu dveřmi, při otáčení nebo na přechodu. Pomáhají vizuální a zvukové podněty (počítání, metronom)."
                        },
                        {
                            "id": "q4",
                            "question": "Seřaďte strategie pomoci při freezingu od nejjednodušší:",
                            "type": "ordering",
                            "correct_order": [
                                "Řekněte klidně: 'a… TEĎ krok!'",
                                "Počítejte 'raz, dva, tři' a nakročte",
                                "Položte na zem barevnou pásku jako cíl",
                                "Použijte laserový ukazatel na botě"
                            ],
                            "explanation": "Postupujeme od nejjednodušší (slovní pobídka) po technické pomůcky (laser). Vizuální a zvukové podněty pomáhají překonat freezing."
                        },
                        {
                            "id": "q5",
                            "question": "Který motorický příznak bývá nejvíce omezující v každodenním životě?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Tremor (třes)", "correct": False},
                                {"id": "b", "text": "Bradykineze — zpomalení pohybů", "correct": True},
                                {"id": "c", "text": "Rigidita (ztuhlost)", "correct": False},
                                {"id": "d", "text": "Posturální nestabilita", "correct": False}
                            ],
                            "explanation": "Bradykineze (zpomalení pohybů) je často nejvíce omezující — ztěžuje oblékání, jedení, chůzi, psaní i řeč. Tremor je nápadnější, ale bradykineze ovlivňuje každodenní aktivity víc."
                        }
                    ]
                }
            },

            # ---- MODUL 3: Nemotorické příznaky ----
            {
                "id": "parkinson-m3",
                "title": "Nemotorické příznaky",
                "order": 3,
                "duration_minutes": 10,
                "icon": "🧠",
                "lessons": [
                    {
                        "id": "parkinson-m3-l1",
                        "title": "Skryté příznaky: deprese, spánek, autonomní dysfunkce",
                        "type": "article",
                        "prerequisites": ["parkinson-m2-l2"],
                        "content": """<h2>Skryté příznaky Parkinsonovy choroby</h2>
<p>Parkinsonova choroba <strong>NENÍ jen o pohybu</strong>. Nemotorické příznaky mohou být stejně omezující — a často se objeví <strong>ROKY před</strong> třesem a ztuhlostí.</p>

<h3>Deprese a úzkost (40–50 % pacientů)</h3>
<p>Deprese u Parkinsona NENÍ jen „špatná nálada" — je to přímý důsledek změn v mozku (nedostatek dopaminu a serotoninu). Je to <strong>nejčastěji neléčený příznak</strong>!</p>
<p class="key-point">💡 <strong>Klíčové:</strong> Apatie a stažení se MOHOU být příznakem nemoci, ne lenost.</p>

<h3>Poruchy spánku</h3>
<ul>
<li><strong>REM porucha chování</strong> — člověk „hraje" své sny: křičí, praští, kope ve spánku. Může to být jeden z prvních příznaků, i roky před diagnózou.</li>
<li><strong>Nadměrná denní ospalost</strong> — usínání přes den</li>
<li><strong>Nespavost</strong> — obtížné usínání, časté buzení</li>
</ul>

<h3>Autonomní dysfunkce</h3>
<ul>
<li><strong>Zácpa</strong> — jeden z nejčasnějších příznaků (často roky před třesem)</li>
<li><strong>Ortostatická hypotenze</strong> — závratě při vstávání (pokles krevního tlaku)</li>
<li>Poruchy močení, nadměrné pocení</li>
</ul>

<h3>Ztráta čichu (hyposmie)</h3>
<p>Jeden z nejranějších signálů — může se objevit <strong>5–10 let před</strong> motorickými příznaky.</p>

<h3>Časový průběh nemotorických příznaků</h3>
<table>
<tr><th>Oblast</th><th>Prodromální fáze (roky před diagnózou)</th><th>Po diagnóze</th><th>Pokročilé stádium</th></tr>
<tr><td><strong>Autonomní</strong></td><td>Zácpa, ztráta čichu</td><td>Ortostatická hypotenze</td><td>Poruchy močení, pocení</td></tr>
<tr><td><strong>Spánek</strong></td><td>REM porucha chování</td><td>Nespavost, buzení</td><td>Nadměrná denní ospalost</td></tr>
<tr><td><strong>Psychika</strong></td><td>Úzkost</td><td>Deprese, apatie</td><td>Halucinace, demence</td></tr>
<tr><td><strong>Senzorické</strong></td><td>Hyposmie (čich)</td><td>Bolest, parestezie</td><td>Centrální bolest</td></tr>
</table>

<p class="key-point">💡 <strong>Klíčové:</strong> Nemotorické příznaky se vyvíjejí postupně — od prodromální fáze (roky před třesem) až po pokročilé stádium. Jejich včasné rozpoznání pomáhá dřívější diagnostice.</p>""",
                        "key_points": [
                            "Nemotorické příznaky se ČASTO objeví DŘÍVE než motorické",
                            "Deprese postihuje 40–50 % lidí s Parkinsonem — není to 'špatná nálada', je to součást nemoci",
                            "Zácpa je jedním z nejčasnějších příznaků (roky před třesem)",
                            "Porucha čichu (hyposmie) může být prvním signálem",
                            "Poruchy REM spánku (vykřikování, praštění ve spánku) — důležitý varovný příznak"
                        ]
                    },
                    {
                        "id": "parkinson-m3-l2",
                        "title": "Kognitivní změny a halucinace",
                        "type": "article",
                        "prerequisites": ["parkinson-m3-l1"],
                        "content": """<h2>Kognitivní změny a halucinace</h2>

<h3>Kognitivní změny</h3>
<p>Zpomalené myšlení u Parkinsona <strong>NENÍ hloupost</strong> — mozek potřebuje více času na zpracování informací. Člověk má problémy s plánováním, organizací a pozorností, ale paměť bývá zachována déle než u Alzheimera.</p>

<p>Až <strong>80 %</strong> lidí s Parkinsonem rozvine v pozdějších stádiích demenci.</p>

<table>
<tr><th>Parkinson vs. Alzheimer</th><th>Parkinson</th><th>Alzheimer</th></tr>
<tr><td>Nejdříve postiženo</td><td>Exekutivní funkce (plánování, rozhodování)</td><td>Paměť (zapomínání)</td></tr>
<tr><td>Paměť</td><td>Relativně zachována déle</td><td>Postižena brzy</td></tr>
<tr><td>Halucinace</td><td>Časté (vizuální)</td><td>Méně časté</td></tr>
</table>

<h3>Halucinace</h3>
<p>Vizuální halucinace jsou u Parkinsona časté — člověk vidí lidi, zvířata nebo předměty, které tam nejsou. Zpočátku mohou být mírné (tzv. <em>„průchodové halucinace"</em> — záblesk osoby na okraji zorného pole), později se mohou stát výraznější.</p>

<p>Halucinace jsou často vedlejším účinkem dopaminergních léků — paradoxně léky, které pomáhají s pohybem, mohou způsobit halucinace.</p>

<h3>Jak reagovat na halucinace?</h3>
<ul>
<li>✅ <strong>Validujte emoci:</strong> „Vidím, že se bojíš. Jsem tady s tebou."</li>
<li>✅ <strong>Přesměrujte pozornost:</strong> „Pojďme se podívat na zahradu."</li>
<li>❌ NEŘÍKEJTE: „To tam nic není!" nebo „To se ti zdá!"</li>
<li>❌ Nepopírejte, neargumentujte — to zvyšuje úzkost.</li>
</ul>

<p class="key-point">💡 <strong>Klíčové:</strong> Pokud se kognitivní příznaky a halucinace objeví BEZ předchozích pohybových příznaků — jde spíše o <em>demenci s Lewyho tělísky</em>. Pokud přijdou PO motorických příznacích — mluvíme o <em>Parkinsonově chorobě s demencí</em>.</p>""",
                        "key_points": [
                            "Zpomalené myšlení NENÍ hloupost — mozek potřebuje více času",
                            "Až 80 % lidí s Parkinsonem rozvine v pozdních stádiích demenci",
                            "Halucinace (vidiny) jsou časté — často vedlejší účinek léků",
                            "U halucinací: nepopirejte, nepotvrzujte, validujte emoci a přesměrujte",
                            "Rozdíl od Alzheimera: paměť bývá zachována déle, problémy jsou s plánováním a pozorností"
                        ]
                    }
                ],
                "quiz": {
                    "id": "parkinson-m3-quiz",
                    "title": "Ověřte si: Nemotorické příznaky",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Které nemotorické příznaky se mohou objevit ROKY před třesem?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Halucinace a poruchy řeči", "correct": False},
                                {"id": "b", "text": "Zácpa, ztráta čichu, poruchy spánku", "correct": True},
                                {"id": "c", "text": "Poruchy polykání a řeči", "correct": False},
                                {"id": "d", "text": "Tremor a rigidita", "correct": False}
                            ],
                            "explanation": "Zácpa, ztráta čichu a poruchy REM spánku patří mezi nejranější příznaky — mohou se objevit 5–10 let PŘED motorickými příznaky (třes, rigidita)."
                        },
                        {
                            "id": "q2",
                            "question": "Kolik procent lidí s Parkinsonem trpí depresí?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Asi 5 %", "correct": False},
                                {"id": "b", "text": "40–50 %", "correct": True},
                                {"id": "c", "text": "Asi 15–20 %", "correct": False},
                                {"id": "d", "text": "Více než 90 %", "correct": False}
                            ],
                            "explanation": "Deprese postihuje 40–50 % lidí s Parkinsonem. Není to jen 'špatná nálada' — je to přímý důsledek změn v mozku (nedostatek dopaminu a serotoninu). Je to nejčastěji neléčený příznak!"
                        },
                        {
                            "id": "q3",
                            "question": "Spojte příznak se správnou kategorií:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Zácpa", "right": "Autonomní dysfunkce"},
                                {"left": "Deprese", "right": "Psychiatrický příznak"},
                                {"left": "Živé sny s křikem", "right": "Porucha REM spánku"},
                                {"left": "Ztráta čichu", "right": "Senzorický příznak"}
                            ],
                            "explanation": "Nemotorické příznaky se dělí na autonomní (zácpa, hypotenze), psychiatrické (deprese, úzkost), spánkové (REM porucha) a senzorické (čich, bolest)."
                        },
                        {
                            "id": "q4",
                            "question": "Správná reakce na halucinace u Parkinsona je říct: 'To tam nic není, to se vám zdá.'",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "Nepopirejte halucinace — zvyšuje to úzkost. Správně: validujte emoci ('vidím, že se bojíš') a přesměrujte pozornost."
                        },
                        {
                            "id": "q5",
                            "question": "V jakém procentu případů se u Parkinsona v pozdních stádiích rozvine demence?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Přibližně 20 %", "correct": False},
                                {"id": "b", "text": "Přibližně 50 %", "correct": False},
                                {"id": "c", "text": "Přibližně 80 %", "correct": True},
                                {"id": "d", "text": "Prakticky 100 %", "correct": False}
                            ],
                            "explanation": "Až 80 % lidí s Parkinsonem rozvine v pozdějších stádiích demenci. Na rozdíl od Alzheimera jsou u Parkinsona nejdříve postiženy exekutivní funkce (plánování, rozhodování), zatímco paměť bývá zachována déle."
                        },
                        {
                            "id": "q6",
                            "question": "Seřaďte typický časový průběh nemotorických příznaků:",
                            "type": "ordering",
                            "correct_order": [
                                "Zácpa a ztráta čichu (roky před diagnózou)",
                                "Deprese a úzkost",
                                "Kognitivní zpomalení",
                                "Halucinace a demence"
                            ],
                            "explanation": "Nemotorické příznaky mají typický průběh: nejdříve senzorické a autonomní (čich, zácpa), pak psychiatrické, nakonec kognitivní."
                        }
                    ]
                }
            },

            # ---- MODUL 4: Komunikace a každodenní život ----
            {
                "id": "parkinson-m4",
                "title": "Komunikace a každodenní život",
                "order": 4,
                "duration_minutes": 10,
                "icon": "🗣️",
                "lessons": [
                    {
                        "id": "parkinson-m4-l1",
                        "title": "Změny řeči a mimiky",
                        "type": "article",
                        "prerequisites": ["parkinson-m3-l2"],
                        "content": """<h2>Změny řeči a mimiky u Parkinsona</h2>
<p>Parkinsonova choroba výrazně ovlivňuje komunikaci — a to způsobem, který okolí často špatně interpretuje.</p>

<h3>Hypofonie (tichý hlas)</h3>
<p>Hlas se stává tichým, monotónním, dýchavičným. Důležité: člověk si často <strong>NEUVĚDOMUJE</strong>, že mluví tiše — jeho vnitřní vnímání hlasitosti neodpovídá realitě.</p>
<p class="key-point">💡 <strong>Klíčové:</strong> NEŘÍKEJTE „mluv hlasitěji!" — to nefunguje a frustruje.</p>

<h3>Hypomimie (maskový obličej)</h3>
<p>Obličejové svaly jsou oslabeny — člověk <strong>CÍTÍ emoce</strong>, ale nedokáže je <strong>VYJÁDŘIT</strong> mimikou. Úsměv, překvapení, radost — vše je uvnitř, ale obličej zůstává nehybný.</p>
<p>Rodina si často myslí: <em>„Je mu to jedno"</em> nebo <em>„Nebaví ho to."</em> To je <strong>MYLNÉ</strong>. Maskový obličej je příznak nemoci, ne lhostejnost.</p>

<h3>LSVT LOUD — řešení pro hlas</h3>
<p><strong>Lee Silverman Voice Treatment</strong> je vědecky ověřený logopedický program. Princip je jednoduchý: <em>„MYSLI NAHLAS!"</em> (THINK LOUD!). 4 týdny intenzivního cvičení mohou výrazně zlepšit hlasitost a srozumitelnost řeči.</p>

<h3>Přehled komunikačních změn</h3>
<table>
<tr><th>Příznak</th><th>Co vidíte/slyšíte</th><th>Co si lidé myslí</th><th>Realita</th></tr>
<tr><td><strong>Hypofonie</strong></td><td>Tichý, monotónní hlas</td><td>„Nechce mluvit"</td><td>Hlasivky a dýchací svaly jsou oslabeny</td></tr>
<tr><td><strong>Hypomimie</strong></td><td>Nehybný obličej</td><td>„Je mu to jedno"</td><td>Cítí emoce, svaly je neumí vyjádřit</td></tr>
<tr><td><strong>Dysfagie</strong></td><td>Kašle při jídle, slintání</td><td>„Jí nepořádně"</td><td>Polykací svaly nepracují správně</td></tr>
<tr><td><strong>Mikrografie</strong></td><td>Drobné, nečitelné písmo</td><td>„Je líný psát pořádně"</td><td>Jemná motorika ruky je narušena</td></tr>
</table>

<h3>Jak komunikovat s člověkem s Parkinsonem?</h3>
<ul>
<li>✅ <strong>Přistupte blíže</strong> — nesedejte daleko</li>
<li>✅ <strong>Ztište TV/rádio</strong> před rozhovorem</li>
<li>✅ <strong>Dívejte se z očí do očí</strong></li>
<li>✅ <strong>Dejte čas na odpověď</strong> — nepřerušujte</li>
<li>✅ Pokud nerozumíte: <em>„Promiň, neslyšel/a jsem. Povíš mi to znovu?"</em></li>
<li>❌ NEŘÍKEJTE: <em>„Proč mluvíš tak tiše?"</em> nebo <em>„Mluv hlasitěji!"</em></li>
</ul>""",
                        "key_points": [
                            "Hypofonie = tichý, monotónní hlas. Člověk si NEUVĚDOMUJE, že mluví tiše",
                            "Maskový obličej (hypomimie) NEZNAMENÁ lhostejnost — cítí emoce, jen je nemůže vyjádřit",
                            "LSVT LOUD = účinný logopedický program pro zlepšení hlasu",
                            "Přistupte blíže, redukujte hluk, dívejte se z očí do očí",
                            "Neptejte se 'proč mluvíš tak tiše?' — spíše 'promiň, neslyšel/a jsem'"
                        ]
                    },
                    {
                        "id": "parkinson-m4-l2",
                        "title": "Praktické tipy pro každodenní život",
                        "type": "article",
                        "prerequisites": ["parkinson-m4-l1"],
                        "content": """<h2>Praktické tipy pro každodenní život</h2>

<h3>Polykání (dysfagie)</h3>
<p>Potíže s polykáním jsou u Parkinsona časté a mohou být nebezpečné — riziko <strong>aspirace</strong> (vdechnutí jídla do plic).</p>
<ul>
<li>Jezte vsedě, vzpřímeně</li>
<li>Malá sousta, důkladně žvýkejte</li>
<li>Nepospíchejte — žádné „jez rychleji!"</li>
<li>Hustší tekutiny jsou bezpečnější než řídké</li>
<li>Při opakovaném kašlání při jídle — <strong>návštěva logopeda!</strong></li>
</ul>

<h3>Pomůcky pro každodenní život</h3>
<table>
<tr><th>Oblast</th><th>Pomůcka / Tip</th></tr>
<tr><td>Oblékání</td><td>Suchý zip místo knoflíků, elastický pásek, boty slip-on</td></tr>
<tr><td>Jedení</td><td>Těžší příbory (tlumí třes), protiskluzové podložky, hrnek s velkým uchem</td></tr>
<tr><td>Koupelna</td><td>Madla u toalety a ve sprše, protiskluzová podložka, sedátko do sprchy</td></tr>
</table>

<h3>Cvičení jako „lék"</h3>
<p>Fyzická aktivita <strong>PROKAZATELNĚ</strong> zpomaluje progresi Parkinsona:</p>
<ul>
<li>🥊 <strong>Boxing</strong> (Rock Steady Boxing) — zlepšuje koordinaci a sílu</li>
<li>🩰 <strong>Tanec</strong> (zejména tango!) — zlepšuje rovnováhu a chůzi</li>
<li>🧘 <strong>Tai chi</strong> — snižuje riziko pádů</li>
<li>🚶 <strong>Nordic walking</strong> — bezpečná chůze s oporou</li>
<li>🏊 <strong>Plavání</strong> — šetrné k kloubům</li>
</ul>

<p class="key-point">💡 <strong>Klíčové:</strong> Plánujte cvičení a náročné aktivity na dobu, kdy léky fungují nejlépe (období „on").</p>""",
                        "key_points": [
                            "Dysfagie (porucha polykání) může být nebezpečná — aspirace jídla do plic",
                            "Suchý zip místo knoflíků, elastický pásek místo opasku",
                            "Těžší příbory a protiskluzové podložky pomohou při jídle",
                            "Fyzická aktivita je KLÍČOVÁ: tanec, tai chi, boxing — prokazatelně pomáhají",
                            "Plánujte náročné aktivity na dobu, kdy léky fungují nejlépe"
                        ]
                    },
                    {
                        "id": "parkinson-m4-l3",
                        "title": "Každodenní situace s Parkinsonem",
                        "type": "scenarios",
                        "prerequisites": ["parkinson-m4-l2"],
                        "content": """<h2>Praktické scénáře — jak reagovat?</h2>
<p>Typické situace, se kterými se můžete setkat. Ke každé uvádíme doporučenou reakci.</p>""",
                        "scenarios": [
                            {
                                "title": "V restauraci",
                                "situation": "Pan Josef (68) objednává jídlo v restauraci. Mluví tiše kvůli hypofonii, číšník mu nerozumí a obrací se na manželku: 'Co si váš manžel dá?'",
                                "wrong_approach": "Manželka objedná za Josefa. Ten se cítí neviditelný a příště odmítne jít do restaurace.",
                                "right_approach": "Manželka řekne: 'Zeptejte se přímo jeho.' Josef ukáže v menu prstem na vybraný pokrm. Číšník se dívá na Josefa a potvrdí objednávku.",
                                "principle": "Komunikujte vždy S člověkem, ne přes něj. Ukázání v menu je plnohodnotná komunikace."
                            },
                            {
                                "title": "U lékaře",
                                "situation": "Paní Marie (71) je u neurologa na kontrole. Nedokáže rychle popsat své příznaky — hlas je tichý, řeč pomalá. Lékař se obrací na manžela: 'Pane Novák, tak co jí je?'",
                                "wrong_approach": "Manžel odpovídá za Marii. Ta se cítí ponížená a příště nechce na kontrolu.",
                                "right_approach": "Lékař klade jednoduché ano/ne otázky přímo Marii: 'Bolí vás záda? Máte problémy se spánkem?' Dívá se na ni, dává čas.",
                                "principle": "Jednoduché otázky s ano/ne odpověďmi. Vždy se dívejte na pacienta, ne na doprovod."
                            },
                            {
                                "title": "Na procházce — freezing na přechodu",
                                "situation": "Pan Kovář (73) zamrzne uprostřed přechodu pro chodce. Auta čekají, kolemjdoucí panikaří. Manželka neví, co dělat.",
                                "wrong_approach": "Manželka ho tahá za ruku a křičí: 'Pojďte, lidi koukaj!' Pan Kovář spadne.",
                                "right_approach": "Manželka klidně řekne: 'Máme čas. Raz — dva — tři — krok.' Nabídne ruku jako oporu. Po několika vteřinách se nohy uvolní.",
                                "principle": "Freezing je dočasný. Klid, počítání nahlas a nabídnutí opory pomáhají překonat 'zamrznutí'."
                            },
                            {
                                "title": "Při telefonování",
                                "situation": "Pan Dvořák (66) volá na úřad kvůli příspěvku na péči. Operátorka mu nerozumí — jeho hlas je příliš tichý a monotónní. Několikrát řekne: 'Prosím? Nerozumím vám.'",
                                "wrong_approach": "Pan Dvořák volá znovu a znovu, pokaždé neúspěšně. Cítí frustraci a vzdá to.",
                                "right_approach": "Pan Dvořák si předem připraví klíčová slova na papír. Nebo požádá blízkého, aby zavolal s ním (na hlasitý odposlech). Ideálně použije e-mail nebo datovou schránku.",
                                "principle": "Telefonování je nejtěžší forma komunikace při hypofonii. Příprava, písemná forma nebo doprovod jsou legitimní řešení."
                            },
                            {
                                "title": "Young-Onset — jak říct dětem",
                                "situation": "Tomáš (48) má Parkinsona rok. Dcera (16) viděla na internetu video o pokročilém stádiu. Přijde domů vyděšená a pláče: 'Tati, ty budeš na vozíku? Ty umřeš?'",
                                "wrong_approach": "Tomáš řekne: 'O nic nejde, to je hloupost.' Nebo naopak dramaticky popíše budoucnost. Dcera se ještě víc uzavře.",
                                "right_approach": "Tomáš obejme dceru a řekne: 'Mám Parkinsona, to je pravda. Ale dneska jsem tady, mám dobré léky a žiju normální život. Nemůžu slíbit, že bude všechno perfektní — ale můžu slíbit, že to zvládneme společně. Můžeš se mě zeptat na cokoliv.'",
                                "principle": "Děti potřebují pravdivé informace přiměřené věku, ne útěšné lži. Otevřenost buduje důvěru. Nabídněte i dětského psychologa."
                            },
                            {
                                "title": "Bezpečné jedení — polykací potíže",
                                "situation": "Babička Jiřina (74) se při obědě často zakašle a jídlo jí 'padá špatně'. Rodina si toho všímá, ale Jiřina říká: 'To nic, jen jsem se zakuckala.'",
                                "wrong_approach": "Rodina to akceptuje a nic neřeší. Nebo naopak Jiřině zakáže jíst u stolu s ostatními.",
                                "right_approach": "Vnučka klidně řekne: 'Babi, všimli jsme si, že se při jídle často zakašleš. Mohli bychom se poradit s logopedem? Pomůže nám, jak jídlo připravit, abys jedla pohodlně a bezpečně.' Objedná logopedické vyšetření polykání.",
                                "principle": "Dysfagie (potíže s polykáním) je vážný příznak — riziko aspirační pneumonie. Logoped naučí bezpečné techniky polykání a úpravu konzistence jídla."
                            }
                        ],
                        "key_points": [
                            "Komunikujte vždy s člověkem, ne přes něj — i když mluví tiše",
                            "Jednoduché ano/ne otázky usnadňují komunikaci u lékaře",
                            "Freezing je dočasný — klid a počítání nahlas pomáhají",
                            "Telefonování je nejtěžší — preferujte osobní kontakt nebo písemnou formu",
                            "Dětem říkejte pravdu přiměřeně věku — otevřenost buduje důvěru",
                            "Kašel při jídle = vážný varovný signál → objednejte logopeda"
                        ]
                    }
                ],
                "quiz": {
                    "id": "parkinson-m4-quiz",
                    "title": "Ověřte si: Komunikace a každodenní život",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Co znamená hypomimie u Parkinsona?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Snížená mimika obličeje — člověk cítí emoce, ale nemůže je vyjádřit", "correct": True},
                                {"id": "b", "text": "Člověk necítí žádné emoce", "correct": False},
                                {"id": "c", "text": "Projev deprese", "correct": False},
                                {"id": "d", "text": "Ztráta zraku", "correct": False}
                            ],
                            "explanation": "Hypomimie (maskový obličej) znamená oslabenou mimiku. Člověk CÍTÍ emoce plně — jen je nedokáže VYJÁDŘIT obličejem."
                        },
                        {
                            "id": "q2",
                            "question": "Člověk s Parkinsonem mluví tiše naschvál, aby na sebe upozornil.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "Hypofonie je příznak Parkinsona — člověk si často NEUVĚDOMUJE, že mluví tiše. Jeho vnitřní vnímání hlasitosti neodpovídá realitě."
                        },
                        {
                            "id": "q3",
                            "question": "Jak se jmenuje účinný logopedický program pro zlepšení hlasu při Parkinsonu?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "LSVT LOUD", "correct": True},
                                {"id": "b", "text": "FAST metoda", "correct": False},
                                {"id": "c", "text": "Bobath koncept", "correct": False},
                                {"id": "d", "text": "Vojtova metoda", "correct": False}
                            ],
                            "explanation": "LSVT LOUD (Lee Silverman Voice Treatment) je vědecky ověřený logopedický program specificky pro Parkinsona. Princip: 'MYSLI NAHLAS!' — 4 týdny intenzivního cvičení (4×/týden). Bobath i Vojta jsou neurorehabilitační metody, ale nezaměřují se na hlas."
                        },
                        {
                            "id": "q4",
                            "question": "Spojte pomůcku s problémem, který řeší:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Těžké příbory", "right": "Třes rukou při jídle"},
                                {"left": "Suchý zip", "right": "Obtížné zapínání knoflíků"},
                                {"left": "Protiskluzová podložka", "right": "Ujíždějící talíře po stole"},
                                {"left": "Madla v koupelně", "right": "Riziko pádu"}
                            ],
                            "explanation": "Jednoduché pomůcky mohou výrazně zlepšit samostatnost — těžší příbory tlumí třes, suchý zip nahrazuje knoflíky."
                        },
                        {
                            "id": "q5",
                            "question": "Seřaďte správný postup, když člověku s Parkinsonem nerozumíte:",
                            "type": "ordering",
                            "correct_order": [
                                "Přibližte se a navažte oční kontakt",
                                "Ztište okolní hluk (TV, rádio)",
                                "Požádejte o zopakování klidným tónem",
                                "Pokud stále nerozumíte, nabídněte alternativu (napsat, ukázat)"
                            ],
                            "explanation": "Správný postup: přiblížit se → ztišit hluk → požádat o zopakování BEZ výčitek → nabídnout alternativu."
                        }
                    ]
                }
            },

            # ---- MODUL 5: Péče, zdroje a podpora v ČR ----
            {
                "id": "parkinson-m5",
                "title": "Péče, zdroje a podpora v ČR",
                "order": 5,
                "duration_minutes": 10,
                "icon": "🏥",
                "lessons": [
                    {
                        "id": "parkinson-m5-l1",
                        "title": "Léčba a rehabilitace",
                        "type": "article",
                        "prerequisites": ["parkinson-m4-l3"],
                        "content": """<h2>Léčba a rehabilitace Parkinsonovy choroby</h2>
<p>Parkinsonova choroba zatím nemá lék, který by ji vyléčil. Ale máme velmi účinné nástroje, jak příznaky zmírnit a kvalitu života zachovat.</p>

<h3>L-DOPA (levodopa) — zlatý standard</h3>
<p>Nejúčinnější lék. V mozku se přeměňuje na dopamin — přesně to, co chybí. Účinkuje nejlépe na bradykinezi a rigiditu. Při dlouhodobém užívání se mohou objevit komplikace (<em>dyskineze</em> — mimovolní pohyby, on/off kolísání).</p>

<h3>Přehled léků</h3>
<table>
<tr><th>Typ léku</th><th>Příklad</th><th>Mechanismus</th></tr>
<tr><td><strong>L-DOPA</strong></td><td>levodopa/karbidopa</td><td>Přeměna na dopamin v mozku</td></tr>
<tr><td>Dopaminoví agonisté</td><td>pramipexol, ropinirol</td><td>Napodobují dopamin</td></tr>
<tr><td>MAO-B inhibitory</td><td>rasagilin, selegilin</td><td>Zpomalují rozklad dopaminu</td></tr>
<tr><td>COMT inhibitory</td><td>entakapon</td><td>Prodlužují účinek L-DOPA</td></tr>
</table>

<h3>Hluboká mozková stimulace (DBS)</h3>
<p>Chirurgický zákrok, při kterém se do mozku zavedou elektrody. Pomáhá, když léky přestanou stačit. <strong>NEVYLÉČÍ</strong> Parkinsona, ale může výrazně zmírnit třes, ztuhlost a dyskineze.</p>

<h3>Rehabilitace — stejně důležitá jako léky!</h3>
<ul>
<li><strong>Fyzioterapie</strong> — pohyb, rovnováha, prevence pádů</li>
<li><strong>Ergoterapie</strong> — nácvik každodenních činností</li>
<li><strong>Logopedie</strong> — LSVT LOUD pro hlas, cvičení polykání</li>
<li><strong>Psychologická podpora</strong> — deprese, úzkost, kognitivní trénink</li>
</ul>

<p class="key-point">💡 <strong>Klíčové:</strong> <strong>Multidisciplinární tým</strong> je ideál: neurolog + fyzioterapeut + logoped + ergoterapeut + psycholog. Všichni spolupracují na jednom cíli — kvalita života.</p>""",
                        "key_points": [
                            "L-DOPA (levodopa) je základní a nejúčinnější lék — přeměna na dopamin v mozku",
                            "Hluboká mozková stimulace (DBS) může pomoci, když léky nestačí",
                            "Fyzioterapie, ergoterapie a logopedie jsou nedílnou součástí léčby",
                            "Pohyb je 'lék': tanec, tai chi, boxing, chůze — prokazatelně zpomalují progresi",
                            "Multidisciplinární tým (neurolog + fyzioterapeut + logoped + psycholog) je ideál"
                        ]
                    },
                    {
                        "id": "parkinson-m5-l2",
                        "title": "Kde najít pomoc v České republice",
                        "type": "resources",
                        "prerequisites": ["parkinson-m5-l1"],
                        "content": """<h2>Kde najít pomoc v České republice</h2>

<h3>Společnost Parkinson, z.s.</h3>
<p>Hlavní pacientská organizace v ČR. Nabízí:</p>
<ul>
<li>Regionální kluby po celé ČR — setkání, podpora, informace</li>
<li>Poradenství pro pacienty a rodiny</li>
<li>Vzdělávací akce a konference</li>
<li>Web: <strong>www.parkinson-cz.net</strong></li>
</ul>

<h3>Extrapyramidová centra (specializovaná péče)</h3>
<table>
<tr><th>Nemocnice</th><th>Pracoviště</th></tr>
<tr><td>FN Motol, Praha</td><td>Neurologická klinika</td></tr>
<tr><td>VFN Praha 2</td><td>1. neurologická klinika</td></tr>
<tr><td>FN Brno</td><td>Neurologická klinika</td></tr>
<tr><td>FN Olomouc</td><td>Neurologická klinika</td></tr>
<tr><td>FN Ostrava</td><td>Neurologická klinika</td></tr>
</table>

<h3>Důležité kontakty</h3>
<table>
<tr><th>Organizace / Služba</th><th>Kontakt</th><th>Co nabízí</th></tr>
<tr><td><strong>Společnost Parkinson</strong></td><td>www.parkinson-cz.net</td><td>Kluby, poradenství, vzdělávání</td></tr>
<tr><td><strong>Linka důvěry</strong></td><td>116 123 (nonstop, zdarma)</td><td>Krizová pomoc, psychická podpora</td></tr>
<tr><td><strong>Pečuj doma</strong></td><td>www.pecujdoma.cz</td><td>Portál pro neformální pečující</td></tr>
<tr><td><strong>Sociální poradna</strong></td><td>Obecní úřad s rozšířenou působností</td><td>Příspěvky, průkaz ZTP/P</td></tr>
<tr><td><strong>Česká asociace ergoterapeutů</strong></td><td>www.ergoterapie.cz</td><td>Vyhledání ergoterapeuta</td></tr>
</table>

<h3>Sociální podpora</h3>
<ul>
<li><strong>Příspěvek na péči</strong> (zákon 108/2006 Sb.) — 4 stupně podle závislosti (880–19 200 Kč/měsíc)</li>
<li><strong>Průkaz ZTP/P</strong> — parkování, slevy na dopravu, doprovod zdarma</li>
<li><strong>Invalidní důchod</strong> — při snížené pracovní schopnosti o více než 35 %</li>
<li><strong>Respitní péče</strong> — odlehčovací služby pro pečující (právo na odpočinek!)</li>
</ul>

<h3>Péče o pečujícího</h3>
<p>Syndrom vyhoření je u pečujících o člověka s Parkinsonem velmi reálný. Příznaky: vyčerpání, podrážděnost, pocit beznaděje, ztráta zájmů, zdravotní problémy.</p>
<p><strong>Nestydíte se požádat o pomoc!</strong> Možnosti:</p>
<ul>
<li>Svépomocné skupiny (Společnost Parkinson)</li>
<li>Psychologická podpora — právo každého pečujícího</li>
<li>Respitní péče — odpočinek pro pečujícího</li>
<li>Linka důvěry: <strong>116 123</strong> (nonstop, zdarma)</li>
</ul>

<p class="key-point">💛 <strong>Pečovat o sebe NENÍ sobectví</strong> — je to nutnost. Nemůžete pomáhat druhým, když sami padáte na kolena.</p>""",
                        "key_points": [
                            "Společnost Parkinson, z.s. — první kontakt, regionální kluby po celé ČR",
                            "Extrapyramidová centra ve fakultních nemocnicích — specializovaná péče",
                            "Příspěvek na péči, průkaz ZTP/P, invalidní důchod — právo každého pacienta",
                            "Péče o pečujícího: syndrom vyhoření je reálný — respitní péče, psycholog, svépomocné skupiny",
                            "Nestydíte se požádat o pomoc — pečovat o sebe je nutnost, ne sobectví"
                        ]
                    }
                ],
                "quiz": {
                    "id": "parkinson-m5-quiz",
                    "title": "Ověřte si: Péče a podpora",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Který lék je základem léčby Parkinsonovy choroby?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Aspirin", "correct": False},
                                {"id": "b", "text": "L-DOPA (levodopa)", "correct": True},
                                {"id": "c", "text": "Antibiotika", "correct": False},
                                {"id": "d", "text": "Ibuprofen", "correct": False}
                            ],
                            "explanation": "L-DOPA (levodopa) je zlatý standard léčby. V mozku se přeměňuje na dopamin — přesně to, co u Parkinsona chybí."
                        },
                        {
                            "id": "q2",
                            "question": "Hluboká mozková stimulace (DBS) Parkinsonovu chorobu zcela vyléčí.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "DBS Parkinsona NEVYLÉČÍ — ale může výrazně zmírnit příznaky (třes, ztuhlost, dyskineze), když léky přestanou stačit."
                        },
                        {
                            "id": "q3",
                            "question": "Která organizace je hlavní pacientskou organizací pro Parkinson v ČR?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "ALS Liga", "correct": False},
                                {"id": "b", "text": "Společnost Parkinson, z.s.", "correct": True},
                                {"id": "c", "text": "Cerebrum", "correct": False},
                                {"id": "d", "text": "EURORDIS", "correct": False}
                            ],
                            "explanation": "Společnost Parkinson, z.s. je hlavní pacientská organizace v ČR — nabízí regionální kluby, poradenství a vzdělávací akce."
                        },
                        {
                            "id": "q4",
                            "question": "Spojte typ podpory se správným popisem:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Příspěvek na péči", "right": "Finanční pomoc podle stupně závislosti"},
                                {"left": "Respitní péče", "right": "Odlehčovací služba pro pečujícího"},
                                {"left": "DBS", "right": "Chirurgická léčba elektrodami v mozku"},
                                {"left": "LSVT LOUD", "right": "Logopedický program pro zlepšení hlasu"}
                            ],
                            "explanation": "Příspěvek na péči pomáhá finančně, respitní péče dává pečujícímu odpočinek, DBS je operativní léčba, LSVT LOUD zlepšuje řeč."
                        },
                        {
                            "id": "q5",
                            "question": "Pečující, který cítí vyčerpání a podrážděnost, by měl:",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Víc se snažit a nevzdávat to", "correct": False},
                                {"id": "b", "text": "Vyhledat pomoc — psycholog, svépomocná skupina, respitní péče", "correct": True},
                                {"id": "c", "text": "Skrývat své emoce, aby neznepokojil rodinu", "correct": False},
                                {"id": "d", "text": "Přestat pečovat úplně a svěřit vše institucím", "correct": False}
                            ],
                            "explanation": "Syndrom vyhoření je reálný! Řešením není ani 'víc se snažit', ani úplné vzdání péče. Správná odpověď je aktivně hledat podporu — psycholog, respitní péče, svépomocné skupiny. Pečovat o sebe NENÍ sobectví."
                        },
                        {
                            "id": "q6",
                            "question": "Seřaďte členy multidisciplinárního týmu podle typického pořadí zapojení:",
                            "type": "ordering",
                            "correct_order": [
                                "Neurolog (diagnostika, léky)",
                                "Fyzioterapeut (pohyb, rovnováha)",
                                "Logoped (řeč, polykání)",
                                "Psycholog (deprese, pečující)"
                            ],
                            "explanation": "Neurolog stanoví diagnózu a nastaví léčbu (první kontakt). Fyzioterapeut se zapojuje brzy — pohyb je klíčový od začátku. Logoped přichází, když se objeví potíže s hlasem nebo polykáním. Psycholog pomáhá s depresí (postihuje 40 % pacientů) i pečujícím s burnoutem. V praxi se tým rozšiřuje postupně podle progrese nemoci."
                        }
                    ]
                }
            },

            # ---- MODUL 6: Pro pečovatele a rodiny (v258) ----
            {
                "id": "parkinson-m6",
                "title": "Pro pečovatele a rodiny",
                "order": 6,
                "duration_minutes": 10,
                "icon": "💛",
                "lessons": [
                    {
                        "id": "parkinson-m6-l1",
                        "title": "Jak pečovat a nepřehořet",
                        "type": "article",
                        "prerequisites": ["parkinson-m5-l2"],
                        "content": """<h2>Syndrom vyhoření u pečujících</h2>
<p>Péče o člověka s Parkinsonovou chorobou je maraton, ne sprint. Až <strong>80 % pečujících</strong> hlásí chronický stres a příznaky vyhoření.</p>

<h3>Co je burnout pečovatele?</h3>
<p>Syndrom vyhoření není slabost — je to přirozená reakce na dlouhodobou zátěž. Projevuje se ve třech rovinách:</p>
<ul>
<li><strong>Fyzické vyčerpání</strong> — chronická únava, bolesti zad, nespavost, oslabená imunita</li>
<li><strong>Emoční vyčerpání</strong> — podrážděnost, pláč, pocit beznaděje, ztráta radosti</li>
<li><strong>Sociální izolace</strong> — ztráta přátel, koníčků, pocit „nikdo nerozumí"</li>
</ul>

<h3>Varovné signály — poznejte burnout včas</h3>
<table>
<tr><th>Rovina</th><th>Varovné signály</th><th>Co pomáhá</th></tr>
<tr><td><strong>Tělo</strong></td><td>Chronická únava, nespavost, bolesti zad a hlavy, časté nemoci</td><td>Pravidelný odpočinek, lékař, pohyb</td></tr>
<tr><td><strong>Emoce</strong></td><td>Pláč bez důvodu, podrážděnost, pocit beznaděje, ztráta radosti</td><td>Psycholog, svépomocná skupina, Linka 116 123</td></tr>
<tr><td><strong>Vztahy</strong></td><td>Izolace od přátel, ztráta koníčků, „nikdo nerozumí"</td><td>Respitní péče, sdílení s dalšími pečujícími</td></tr>
<tr><td><strong>Myšlení</strong></td><td>„Měl/a bych zvládat víc", „jsem špatný/á pečovatel/ka"</td><td>Kognitivní restrukturalizace, terapie</td></tr>
</table>

<h3>Pocit viny — nejčastější past</h3>
<p><em>„Měl/a bych zvládat víc."</em> <em>„Jak si můžu stěžovat, když on/ona trpí víc?"</em> Tyto myšlenky jsou normální, ale NEJSOU pravdivé. Požádat o pomoc není selhání — je to zodpovědnost.</p>

<h3>Pravidlo kyslíkové masky</h3>
<p>V letadle vám řeknou: <strong>„Nejdřív nasaďte masku sobě, pak dítěti."</strong> Stejný princip platí pro péči. Nemůžete pomáhat druhým, když sami padáte na kolena.</p>

<h3>Kde hledat pomoc?</h3>
<ul>
<li><strong>Respitní péče</strong> — odlehčovací služby, aby si pečující mohl/a odpočinout</li>
<li><strong>Svépomocné skupiny</strong> — Společnost Parkinson má regionální kluby i pro pečující</li>
<li><strong>Psychologická podpora</strong> — je to PRÁVO každého pečujícího</li>
<li><strong>Linka důvěry: 116 123</strong> (nonstop, zdarma)</li>
<li><strong>Pečuj doma</strong> (www.pecujdoma.cz) — portál pro neformální pečující</li>
</ul>

<p class="key-point">💛 <strong>Klíčové:</strong> Pečovat o sebe NENÍ sobectví. Je to nutnost. Vyhoření pečovatele je emergentní situace — stejně jako pád pacienta.</p>""",
                        "key_points": [
                            "80 % pečujících hlásí chronický stres a příznaky vyhoření",
                            "Burnout má 3 roviny: fyzickou, emoční a sociální",
                            "Pocit viny je normální, ale požádat o pomoc je zodpovědnost",
                            "Pravidlo kyslíkové masky: nejdřív sebe, pak druhé",
                            "Respitní péče, svépomocné skupiny a psycholog jsou právo pečujícího"
                        ]
                    },
                    {
                        "id": "parkinson-m6-l2",
                        "title": "Young-onset Parkinson — když nemoc přijde brzy",
                        "type": "article",
                        "prerequisites": ["parkinson-m6-l1"],
                        "content": """<h2>Parkinson před padesátkou</h2>
<p><strong>5–10 %</strong> lidí s Parkinsonovou chorobou je diagnostikováno <strong>před 50. rokem</strong> věku. Říkáme tomu Young-Onset Parkinson Disease (YOPD). Tito lidé čelí specifickým výzvám, které se liší od seniorské populace.</p>

<h3>Specifické výzvy YOPD</h3>
<table>
<tr><th>Oblast</th><th>Výzva</th></tr>
<tr><td>Kariéra</td><td>Jak pokračovat v práci? Kdy říct zaměstnavateli?</td></tr>
<tr><td>Finance</td><td>Hypotéka, děti ve škole, invalidní důchod</td></tr>
<tr><td>Rodina</td><td>Malé děti, partnerský vztah, rodičovská role</td></tr>
<tr><td>Identita</td><td>„Jsem příliš mladý/á na Parkinsona" — stigma</td></tr>
</table>

<h3>Srovnání: Young-Onset vs. klasický Parkinson</h3>
<table>
<tr><th>Vlastnost</th><th>Young-Onset (pod 50 let)</th><th>Klasický (nad 60 let)</th></tr>
<tr><td><strong>Podíl</strong></td><td>5–10 % případů</td><td>90–95 % případů</td></tr>
<tr><td><strong>Progrese</strong></td><td>Pomalejší, ale delší průběh</td><td>Rychlejší, ale kratší průběh</td></tr>
<tr><td><strong>Dyskineze</strong></td><td>Častější a dřívější</td><td>Méně časté, později</td></tr>
<tr><td><strong>Genetika</strong></td><td>Vyšší pravděpodobnost (LRRK2, PARK2, PINK1)</td><td>Většinou sporadický</td></tr>
<tr><td><strong>Psychika</strong></td><td>Výraznější deprese a úzkost</td><td>Apatie převažuje</td></tr>
<tr><td><strong>Hlavní výzvy</strong></td><td>Kariéra, rodina, identita, stigma</td><td>Závislost, pády, demence</td></tr>
</table>

<h3>Partnerský vztah a sexuální dysfunkce</h3>
<p>Parkinson ovlivňuje intimitu — snížené libido (vedlejší účinek i nemoci i léků), erektilní dysfunkce, únava. Otevřená komunikace s partnerem a neurologem je klíčová. Sexuální dysfunkce <strong>není tabu</strong> — je to léčitelný příznak.</p>

<h3>Michael J. Fox — vzor a naděje</h3>
<p>Herec <em>Michael J. Fox</em> žije s Parkinsonem od 29 let. Jeho nadace (<strong>The Michael J. Fox Foundation</strong>) investovala přes 2 miliardy dolarů do výzkumu. Ukazuje, že diagnóza není konec — je to začátek jiného, ale smysluplného života.</p>

<h3>Plánování budoucnosti</h3>
<ul>
<li><strong>Právní dokumenty</strong> — plná moc, předběžné přání (advance directives)</li>
<li><strong>Finanční plánování</strong> — invalidní důchod, pojištění, úspory</li>
<li><strong>Podpora dětí</strong> — vysvětlení nemoci přiměřeně věku, dětský psycholog</li>
</ul>

<p class="key-point">💡 <strong>Klíčové:</strong> Young-Onset Parkinson NENÍ odsouzení. S moderní léčbou a podporou mohou tito lidé žít aktivní, smysluplný život desítky let.</p>""",
                        "key_points": [
                            "5–10 % pacientů je diagnostikováno pod 50 let — Young-Onset Parkinson",
                            "Specifické výzvy: kariéra, finance, rodina s malými dětmi, identita",
                            "Dyskineze se u mladších objevují častěji a dříve",
                            "Sexuální dysfunkce není tabu — je to léčitelný příznak",
                            "Plánování budoucnosti (právní, finanční) je důležité co nejdříve"
                        ]
                    }
                ],
                "quiz": {
                    "id": "parkinson-m6-quiz",
                    "title": "Ověřte si: Péče o pečovatele a Young-Onset Parkinson",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Co je syndrom vyhoření (burnout) pečovatele?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Přirozená reakce na dlouhodobou zátěž projevující se vyčerpáním a beznadějí", "correct": True},
                                {"id": "b", "text": "Znak slabého charakteru", "correct": False},
                                {"id": "c", "text": "Normální stav, který nevyžaduje pozornost", "correct": False},
                                {"id": "d", "text": "Psychiatrická diagnóza vyžadující hospitalizaci", "correct": False}
                            ],
                            "explanation": "Burnout je přirozená reakce na dlouhodobou zátěž, ne slabost ani psychiatrická diagnóza. Projevuje se ve 3 rovinách: fyzické (únava, nemoci), emoční (beznaděj, pláč) a sociální (izolace). Vyžaduje aktivní řešení — podporu, odpočinek, případně psychologa."
                        },
                        {
                            "id": "q2",
                            "question": "Pečovatel by měl zvládnout vše sám — požádat o pomoc je selhání.",
                            "type": "true_false",
                            "correct_answer": False,
                            "explanation": "Požádat o pomoc je ZODPOVĚDNOST, ne selhání. Respitní péče, psycholog a svépomocné skupiny jsou právo každého pečujícího."
                        },
                        {
                            "id": "q3",
                            "question": "Young-Onset Parkinson je diagnostikován u lidí pod:",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "30 let", "correct": False},
                                {"id": "b", "text": "50 let", "correct": True},
                                {"id": "c", "text": "65 let", "correct": False},
                                {"id": "d", "text": "40 let", "correct": False}
                            ],
                            "explanation": "Young-Onset Parkinson Disease (YOPD) se diagnostikuje u lidí pod 50 let. Tvoří 5–10 % všech případů. Juvenilní forma (pod 21 let) je extrémně vzácná. YOPD má pomalejší progresi, ale častější dyskineze a výraznější psychické dopady."
                        },
                        {
                            "id": "q4",
                            "question": "Spojte typ podpory se správným popisem:",
                            "type": "matching",
                            "pairs": [
                                {"left": "Respitní péče", "right": "Odlehčovací služba — odpočinek pro pečujícího"},
                                {"left": "Svépomocná skupina", "right": "Setkání lidí se stejnou zkušeností"},
                                {"left": "Sociální pracovník", "right": "Pomoc s příspěvky a sociálními službami"},
                                {"left": "Psycholog", "right": "Profesionální podpora duševního zdraví"}
                            ],
                            "explanation": "Každý typ podpory řeší jinou potřebu — od praktické pomoci po emoční podporu."
                        },
                        {
                            "id": "q5",
                            "question": "Co by měl pečovatel udělat, když cítí chronické vyčerpání a beznaděj?",
                            "type": "single_choice",
                            "options": [
                                {"id": "a", "text": "Více se snažit a přestat si stěžovat", "correct": False},
                                {"id": "b", "text": "Vyhledat pomoc — psycholog, respitní péče, svépomocná skupina", "correct": True},
                                {"id": "c", "text": "Čekat, až to přejde samo", "correct": False},
                                {"id": "d", "text": "Vzít si dlouhodobé léky na uklidnění", "correct": False}
                            ],
                            "explanation": "Vyhoření pečovatele je emergentní situace. Řešením nejsou léky na uklidnění ani 'víc se snažit'. Správný přístup: aktivně hledat podporu — psycholog, respitní péče (právo pečujícího!), svépomocná skupina, Linka 116 123. Pravidlo kyslíkové masky: nejdřív sebe, pak druhé."
                        },
                        {
                            "id": "q6",
                            "question": "Seřaďte kroky při hledání pomoci pro pečovatele:",
                            "type": "ordering",
                            "correct_order": [
                                "Přiznat si, že potřebuji pomoc",
                                "Oslovit rodinu nebo blízké",
                                "Kontaktovat Společnost Parkinson nebo sociálního pracovníka",
                                "Domluvit respitní péči nebo psychologickou podporu"
                            ],
                            "explanation": "První krok je nejtěžší — přiznat si, že potřebuji pomoc. Pak postupně aktivovat dostupnou podporu."
                        }
                    ]
                }
            }
        ]
    }
}

# ============================================
# PROGRESS TRACKING — DB persistence
# ============================================



# ============================================
# 👨‍🏫 AI UČITELÉ
# ============================================

TEACHERS = {
    "radim-tutor": {
        "id": "radim-tutor",
        "name": "Radim Učitel",
        "role": "AI Tutor",
        "specialization": ["disfázie", "komunikace", "vzácná onemocnění"],
        "avatar": "🤖",
        "description": "AI asistent specializovaný na vzdělávání o komunikačních potřebách",
        "target_groups": ["pečovatelé", "rodina", "zdravotníci"]
    },
    "dysphasia-child-tutor": {
        "id": "dysphasia-child-tutor",
        "name": "Logopedka Radka",
        "role": "Specialistka na dětskou disfázii",
        "specialization": ["vývojová disfázie", "dětská logopedie", "speciální pedagogika"],
        "avatar": "👩‍🏫",
        "description": "Specializovaná AI logopedka pro děti s vývojovou disfázií. Pomáhá rodičům i učitelům porozumět potřebám dítěte a nastavit správnou podporu.",
        "target_groups": ["rodiče", "učitelé MŠ/ZŠ", "asistenti pedagoga", "logopedi"],
        "teaching_approach": {
            "principles": [
                "Trpělivost — dítě potřebuje čas na formulování myšlenek",
                "Vizuální podpora — obrázky, piktogramy, gesta",
                "Krátké a jednoduché věty — max 3–5 slov",
                "Pozitivní zpětná vazba — chválit snahu, ne jen výsledek",
                "Rutina a předvídatelnost — jasný denní režim",
                "Hra jako základ — učení formou hry, ne drilu"
            ],
            "red_flags": [
                "Dítě ve 2 letech nemluví žádná slova",
                "Ve 3 letech netvoří dvouslovné věty",
                "Ve 4 letech mu nerozumí lidé mimo rodinu",
                "Dítě se vyhýbá komunikaci nebo je frustrované",
                "Nerozumí jednoduchým pokynům odpovídajícím věku"
            ],
            "exercises": [
                {"name": "Pojmenuj obrázek", "age": "2–4", "desc": "Ukazujte obrázky a pojmenovávejte je společně"},
                {"name": "Co je na obrázku špatně?", "age": "4–6", "desc": "Absurdní obrázky — dítě hledá, co tam nepatří"},
                {"name": "Příběh podle obrázků", "age": "5–7", "desc": "3–4 obrázky v řadě, dítě vypráví příběh"},
                {"name": "Rýmy a říkanky", "age": "3–5", "desc": "Opakování rýmů rozvíjí fonologické povědomí"},
                {"name": "Hra na obchod", "age": "4–6", "desc": "Hraní rolí procvičuje praktickou komunikaci"},
                {"name": "Deník s obrázky", "age": "5+", "desc": "Dítě kreslí a popisuje, co zažilo"}
            ],
            "school_tips": [
                "Zajistit IVP (individuální vzdělávací plán)",
                "Sednout dítě dopředu — blízko učitele",
                "Vizuální rozvrh na tabuli / na lavici",
                "Více času na testy a úkoly",
                "Asistent pedagoga při výuce",
                "Spolupráce s SPC (speciálně pedagogickým centrem)"
            ]
        }
    },
    "dementia-tutor": {
        "id": "dementia-tutor",
        "name": "Dr. Radim Neurolog",
        "role": "Specialista na demenci",
        "specialization": ["Alzheimer", "Lewy body demence", "vaskulární demence", "frontotemporální demence"],
        "avatar": "🧠",
        "description": "AI specialista na různé druhy demence. Pomáhá pečovatelům a rodinám porozumět průběhu onemocnění a správně komunikovat s nemocným.",
        "target_groups": ["pečovatelé", "rodina", "zdravotníci", "sociální pracovníci"],
        "dementia_guide": {
            "types": {
                "alzheimer": {
                    "name": "Alzheimerova choroba",
                    "prevalence": "60–70 % všech demencí",
                    "key_features": "Postupná ztráta paměti, dezorientace, problémy s řečí",
                    "stages": ["Počáteční — zapomínání, hledání slov", "Střední — potřebuje pomoc, bloudí, nerozeznává blízké", "Pokročilé — plná závislost na péči, ztráta řeči"]
                },
                "lewy_body": {
                    "name": "Demence s Lewyho tělísky",
                    "prevalence": "10–15 % demencí",
                    "key_features": "Kolísání pozornosti, vizuální halucinace, parkinsonismus, poruchy spánku",
                    "warning": "POZOR: Neuroleptika mohou být NEBEZPEČNÁ — vždy konzultujte neurologa!"
                },
                "vascular": {
                    "name": "Vaskulární demence",
                    "prevalence": "15–20 % demencí",
                    "key_features": "Schodovité zhoršování po mozkových příhodách, zpomalené myšlení, deprese",
                    "prevention": "Kontrola krevního tlaku, cukrovky, cholesterolu, nekouřit"
                },
                "frontotemporal": {
                    "name": "Frontotemporální demence",
                    "prevalence": "5–10 % demencí, častěji u mladších (45–65 let)",
                    "key_features": "Změny osobnosti a chování DŘÍVE než poruchy paměti, ztráta empatie, nevhodné chování",
                    "warning": "Často zaměňována za psychiatrické onemocnění. Paměť může být dlouho zachovaná."
                },
                "parkinson_dementia": {
                    "name": "Demence při Parkinsonově chorobě",
                    "prevalence": "Až 80 % pacientů s Parkinsonem v pozdních stádiích",
                    "key_features": "Zpomalené myšlení, halucinace, podobné Lewy body demenci",
                    "note": "Pokud se demence objeví BEZ pohybových příznaků — spíše Lewy body; pokud PO nich — Parkinson s demencí"
                }
            },
            "communication_rules": [
                "Mluvte pomalu, klidně, s úsměvem",
                "Krátké věty — jedna myšlenka = jedna věta",
                "Ano/ne otázky místo otevřených",
                "Nepopírejte halucinace — přesměrujte pozornost",
                "Neopravujte nesprávné vzpomínky — validujte emoce",
                "Oční kontakt a dotek — neverbální komunikace je klíčová",
                "Tiché prostředí bez rušivých zvuků",
                "Rutina a stabilní prostředí snižují úzkost"
            ]
        }
    },

    # ---- AI UČITEL 4: Dr. Radim Parkinson (v256) ----
    "parkinson-tutor": {
        "id": "parkinson-tutor",
        "name": "Dr. Radim Parkinson",
        "role": "Specialista na Parkinsonovu chorobu",
        "specialization": ["Parkinsonova choroba", "motorické poruchy", "hypofonie", "dopamin"],
        "avatar": "🤲",
        "description": "AI specialista na Parkinsonovu chorobu. Pomáhá pečovatelům a rodinám porozumět příznakům, komunikačním změnám a možnostem léčby.",
        "target_groups": ["pečovatelé", "rodina", "zdravotníci"],
        "parkinson_guide": {
            "stages": {
                "early": {
                    "name": "Rané stádium",
                    "motor": "Mírný klidový třes (často jednostranný), ztuhlost, zpomalení",
                    "non_motor": "Deprese, zácpa, ztráta čichu, poruchy spánku",
                    "communication": "Mírná hypofonie, bez zásadních omezení",
                    "tip": "Zahajte LSVT LOUD, pravidelný pohyb, nastavte dobré návyky"
                },
                "middle": {
                    "name": "Střední stádium",
                    "motor": "Oboustranné příznaky, freezing, on/off kolísání",
                    "non_motor": "Kognitivní zpomalení, halucinace, denní ospalost",
                    "communication": "Tichý monotónní hlas, snížená mimika, zhoršené polykání",
                    "tip": "Upravit prostředí, prevence pádů, logoped, ergoterapie"
                },
                "late": {
                    "name": "Pokročilé stádium",
                    "motor": "Výrazně omezená pohyblivost, časté pády, ztuhlé celé tělo",
                    "non_motor": "Demence (až 80 %), těžké halucinace, apatie",
                    "communication": "Řeč může být těžce srozumitelná, dysfagie",
                    "tip": "Multidisciplinární péče, respitní služby, komunikační pomůcky"
                }
            },
            "communication_rules": [
                "Přistupte blíže — nesedejte od stolu daleko",
                "Ztište TV/rádio před rozhovorem",
                "Maskový obličej NENÍ lhostejnost — cítí emoce",
                "Dejte čas na odpověď — zpomalené myšlení není hloupost",
                "Neptejte se 'proč mluvíš tak tiše?' — nabídněte blízkost",
                "Halucinace: nepopirejte, validujte emoci, přesměrujte"
            ],
            "exercises": [
                {"name": "LSVT LOUD doma", "frequency": "denně", "desc": "Říkejte 'AAAA' co nejhlasitěji 10×. Čtěte nahlas noviny. Princip: MYSLI NAHLAS!"},
                {"name": "Obličejová gymnastika", "frequency": "denně, 5 min", "desc": "Přehnané úsměvy, mračení, překvapení, foukání do balónku — proti hypomimii"},
                {"name": "Počítání kroků nahlas", "frequency": "při chůzi", "desc": "Nahlas 'raz-dva-raz-dva' jako prevence freezingu. Alternativa: metronom v telefonu"},
                {"name": "Tai chi rovnováha", "frequency": "3×/týden", "desc": "Pomalé přesuny váhy, stoj na jedné noze se zavřenýma očima — prevence pádů"},
                {"name": "Psaní velkými písmeny", "frequency": "denně", "desc": "Vědomě VELKÉ písmo na linkovaném papíře proti mikrografii. Cíl: udržet velikost celou stránku"},
                {"name": "Polykací cviky", "frequency": "před jídlem", "desc": "Důrazné polknutí naprázdno 3×, odkašlání, kontrola pozice hlavy (brada k hrudi)"}
            ],
            "red_flags": [
                "Náhlé zhoršení stavu ze dne na den — může signalizovat infekci nebo dehydrataci, kontaktujte lékaře",
                "Halucinace s neklidem nebo agresí — nebezpečné chování, volejte neurologa nebo 155",
                "Opakované pády (2+ za týden) — nutná návštěva fyzioterapeuta a revize léků",
                "Kašel při jídle a pití — riziko aspirační pneumonie, objednejte logopedické vyšetření",
                "Nechtěný úbytek váhy (5+ kg) — kontaktujte nutričního terapeuta a neurologa",
                "Pečovatel na pokraji sil — nespavost, pláč, beznaděj → okamžitě Linka důvěry 116 123 nebo psycholog"
            ]
        }
    }
}


# ============================================
# 🎭 INTERAKTIVNÍ KOMUNIKAČNÍ SCÉNÁŘE
# ============================================

COMMUNICATION_SCENARIOS = {
    "dysphasia": [
        {
            "id": "dys-s1",
            "title": "Dítě nechce mluvit",
            "context": "Pětileté dítě s disfázii odmítá komunikovat. Stahuje se a pláče. Snažíte se ho zapojit do aktivity.",
            "difficulty": "beginner",
            "character": "Tomasek (5 let, vyvojova disfázie)",
            "situation": "Tomášek sedí v koutě a nechce říkat, co chce k svačině. Dívá se do země.",
            "options": [
                {
                    "id": "a",
                    "text": "Tomášku, řekni mi, co chceš k svačině. Mluv!",
                    "score": 0,
                    "feedback": "Špatný přístup. Příkaz 'mluv!' vytváří tlak a zvyšuje úzkost dítěte. Tomasek se ještě víc stáhne.",
                    "consequence": "Tomášek začne plakat a odmítá spolupracovat."
                },
                {
                    "id": "b",
                    "text": "Tomášku, podívej — mam rohlíček a jablíčko. Co bys chtěl? Ukážeš prstíkem.",
                    "score": 100,
                    "feedback": "Výborně! Nabídli jste konkrétní volby a umožnili neverbální komunikaci (ukazání). Žádný tlak, jasná nabídka.",
                    "consequence": "Tomášek se usměje a ukáže na jablíčko. Vy reknete: 'Jablíčko! Skvělý výběr!' — přirozeně zrcadlíte."
                },
                {
                    "id": "c",
                    "text": "Tak to nevadí, svačinu si vybere učitelka.",
                    "score": 30,
                    "feedback": "Vyhýbáte se problému. Dítě nezískává šanci komunikovat a učit se. Lepší je nabídnout alternativy.",
                    "consequence": "Tomášek dostane rohlíček, ale chtěl jablíčko. Je naštvaný, ale neumí to říct."
                }
            ],
            "learning_point": "Vždy nabídněte 2–3 konkrétní volby. Umožněte i neverbální komunikaci (ukazování, kývání). Nikdy nenutit mluvit příkazem."
        },
        {
            "id": "dys-s2",
            "title": "Dospělý po CMP hledá slova",
            "context": "Pan Karel (65 let) prodělal CMP před 3 měsíci. Má expresivní disfázii — rozumi dobre, ale těžce hledá slova.",
            "difficulty": "intermediate",
            "character": "Pan Karel (65 let, expresivni disfázie po CMP)",
            "situation": "Pan Karel říká: 'Ja bych chtel... ten... no... je to v... tam...' a ukazuje směrem ke kuchyňi. Vypadá frustrovaně.",
            "options": [
                {
                    "id": "a",
                    "text": "Chcete něco z kuchyňě? Čaj? Kávu? Vodu?",
                    "score": 100,
                    "feedback": "Výborně! Potvrdili jste směr (kuchyň) a nabídli konkrétní možnosti. Pan Karel může vybrat bez tlaku.",
                    "consequence": "Pan Karel se usměje: 'Ano! Ká... kávu!' a kývne. Vy: 'Kafe, rozumím! Už ho dělám.'"
                },
                {
                    "id": "b",
                    "text": "Pane Karle, zkuste se soustředit a říct to celou větou.",
                    "score": 10,
                    "feedback": "Špatný přístup. Požadavek 'řekněte celou větou' vytvari enormní tlak. Pan Karel VÍ, co chce říct — jen nemůže. Tohle ho frustruje ještě víc.",
                    "consequence": "Pan Karel zrudne, práskne pěstí do stolu a přestane komunikovat na půl hodiny."
                },
                {
                    "id": "c",
                    "text": "Můžete mi to nakreslit nebo ukázat?",
                    "score": 80,
                    "feedback": "Dobrý přístup! Nabízíte alternativní komunikační kanál. Někteří lidé po CMP lépe kreslí nebo ukazují než mluví.",
                    "consequence": "Pan Karel nakreslí hrnek. Vy: 'Aha, hrnek! Chcete nápoj. Caj nebo kafe?'"
                }
            ],
            "learning_point": "Nabídněte volby NEBO alternativní komunikaci (kresba, ukazování). NIKDY nepožadujte 'celou větu' — clovek s disfázii VÍ, co chce říct, ale nemůže to formulovat."
        },
        {
            "id": "dys-s3",
            "title": "Spolužáci se smějou dítěti",
            "context": "Jste učitelka. Honzik (7 let, disfázie) cetl nahlas a spolužáci se smáli jeho výslovnosti.",
            "difficulty": "intermediate",
            "character": "Honzik (7 let, disfázie) a trida 2.B",
            "situation": "Honzík přečetl větu s obtížemi, někteří žáci se zasmáli. Honzík zrudl a sklopil hlavu.",
            "options": [
                {
                    "id": "a",
                    "text": "Ticho! Kdo se smál, ten dostane poznámku!",
                    "score": 30,
                    "feedback": "Tresty pomáhají jen krátkodobě a mohou Honzika stigmatizovat ještě víc ('kvůli němu máme problémy').",
                    "consequence": "Děti ztichnou, ale o přestávce říkají Honzíkovi: 'Kvůli tobě jsme dostali poznámku.'"
                },
                {
                    "id": "b",
                    "text": "Honzíku, skvěle jsi to přečetl! Děkuju. A vy ostatní — každý z nás se něco učí jinak. Honzík je v matice skvělý. Kdo je skvělý ve čtení, pomohl by Honzíkovi? A Honzík, pomohl bys zase jim s matikou?",
                    "score": 100,
                    "feedback": "Výborně! Pochválili jste Honzíka, normalizovali rozdíly a vytvořili spolupracující prostředí. Každý má svou silnou stránku.",
                    "consequence": "Honzík se usměje. Lucka se přihlásí, že by mu pomohla se čtením. Třída se učí respektu."
                },
                {
                    "id": "c",
                    "text": "Honzíku, příště to přečteš potichu a úkoly já. Není to na tebe.",
                    "score": 10,
                    "feedback": "Tohle Honzíka vyřadí a posiluje pocit, že je 'horší'. Každé dítě má právo číst nahlas a učit se.",
                    "consequence": "Honzik se citi odlisny a vylouceny. Příště odmítne číst vůbec."
                }
            ],
            "learning_point": "Zduraznete silne stranky dítěte, normalizujte rozdíly a vytvořte prostředí vzájemné pomoci. Nikdy dítě nevyřazujte z aktivity."
        }
    ],
    "dementia": [
        {
            "id": "dem-s1",
            "title": "Babička nepoznává vnučku",
            "context": "Vaše babička má střední stádium Alzheimera. Přijedete na návštěvu a babička vás nepoznává.",
            "difficulty": "beginner",
            "character": "Babicka Marie (82 let, Alzheimer — stredni stadium)",
            "situation": "Babička se na vás dívá a říká: 'Kdo jste? Já vás neznám. Jděte pryč!'",
            "options": [
                {
                    "id": "a",
                    "text": "Babičko, já jsem přece Jana! Tvoje vnučka! Pamatuješ si na mě?",
                    "score": 30,
                    "feedback": "Pochopitelná reakce, ale otázka 'pamatuješ si na mě?' vytváří tlak a může vyvolat úzkost. Babička SI nepamatuje a není to její vina.",
                    "consequence": "Babička je zmatená a rozrušená: 'Já žádnou Janu neznám!' Začíná plakat."
                },
                {
                    "id": "b",
                    "text": "Dobrý den, já jsem Jana. Přišla jsem vás navštívit. Mám pro vás koláčky. Máte ráda koláčky?",
                    "score": 100,
                    "feedback": "Skvěle! Představili jste se klidně, bez očekávání, že vás pozná. Přinesli jste pozitivní podnět (koláčky) a ptáte se na něco příjemného.",
                    "consequence": "Babička se usměje: 'Kolacky? Ja mam rada koláčky!' Napětí opadne a můžete strávit hezkou návštěvu."
                },
                {
                    "id": "c",
                    "text": "To je ale smutné. Minulý týden jste mě ještě poznala...",
                    "score": 10,
                    "feedback": "Vaše emoce jsou pochopitelné, ale toto babičce nepomůže. Ona žije v přítomnosti a nepotřebuje vidět váš smutek — potřebuje klid.",
                    "consequence": "Babička vidí váš smutek a je rozrušená, i když neví proč. Atmosféra je tíživá."
                }
            ],
            "learning_point": "Nepožadujte rozpoznání. Představte se klidně, nabídněte pozitivní podnět a buďte v přítomném okamžiku. Člověk s demencí nemůže za to, že si nepamatuje."
        },
        {
            "id": "dem-s2",
            "title": "Pacient má halucinace",
            "context": "Pečujete o pana Nováka (75 let), který má demenci s Lewyho tělísky. Vidíte, že je rozrušený.",
            "difficulty": "intermediate",
            "character": "Pan Novak (75 let, Lewy body demence)",
            "situation": "Pan Novák ukazuje do rohu místnosti a říká: 'Tam stojí cizí člověk! Vykopněte ho!'",
            "options": [
                {
                    "id": "a",
                    "text": "Pane Nováku, tam nikdo není. To se vám jenom zdá.",
                    "score": 20,
                    "feedback": "Popírání halucinací nefunguje. Pro pana Nováka je ten člověk REÁLNÝ. Popirani zvyšuje úzkost a neduveru.",
                    "consequence": "Pan Novák se rozčílí: 'Já přece vidím, že tam stojí! Vy jste s ním spolčený!'"
                },
                {
                    "id": "b",
                    "text": "Vidím, že vás to znepokojuje. Pojdte, pujdeme do kuchyňe, udělám vám čaj. Tady budeme v bezpečí.",
                    "score": 100,
                    "feedback": "Výborně! Validujete emoci (znepokojení), nepopíráte realitu, a přesměrujete pozornost do jiného prostoru. Nabídka bezpečí je klíčová.",
                    "consequence": "Pan Novak vas nasleduje do kuchyňe. Halucinace zmizí se změnou prostředí. Klidně pije čaj."
                },
                {
                    "id": "c",
                    "text": "Ano, vidím ho taky. Řekneme mu, ať odejde.",
                    "score": 40,
                    "feedback": "Potvrzení halucinace může krátkodobě uklidnit, ale dlouhodobě posiluje zmatení. Lepší je validovat EMOCI, ne obsah halucinace.",
                    "consequence": "Pan Novák se uklidní na chvíli, ale za 5 minut 'vidí' dalšího člověka. Očekává, že ho zase 'vyhodíte'."
                }
            ],
            "learning_point": "U halucinací: NEPOPÍREJTE a NEPOTVRZUJTE obsah. Validujte EMOCI ('vidím, že vás to trápí') a PŘESMĚRUJTE pozornost (změna místnosti, činnost, jídlo)."
        },
        {
            "id": "dem-s3",
            "title": "Máma chce jít domů (i když je doma)",
            "context": "Vaše máma (78 let, Alzheimer) žije s vámi. Každý večer chce 'jít domů' — myslí svůj dětský domov.",
            "difficulty": "intermediate",
            "character": "Mama Vera (78 let, Alzheimer — stredni stadium)",
            "situation": "Máma stojí u dveří a rika: 'Musím jít domů. Maminka na mě čeká. Pusťte mě!'",
            "options": [
                {
                    "id": "a",
                    "text": "Mámo, ty JSI doma. Tady bydlíš už 20 let. Tvoje maminka už nežije.",
                    "score": 10,
                    "feedback": "I když je to pravda, pro mámu je to krutá informace, kterou SI NEUŽIVÍ. Každé sdělení o smrti blízkého prožívá ZNOVU, jako by to slyšela poprvé.",
                    "consequence": "Máma začne plakat: 'Maminka umřela? Proč mi to nikdo neřekl?' Za hodinu se zeptá znovu."
                },
                {
                    "id": "b",
                    "text": "Maminka dneska volala, že máš zůstat tady. Říká, ať se nebojíš. Udělám ti kakao, co ty na to?",
                    "score": 90,
                    "feedback": "Vstoupili jste do její reality a uklidnili ji způsobem, kterému rozumí. 'Terapeutická lož' je u demence legitimní nástroj, když chrání před bolestí.",
                    "consequence": "Máma se uklidní: 'Maminka volala? Tak dobře. Kakao bych dala.' Sedí a je v pohodě."
                },
                {
                    "id": "c",
                    "text": "Rozumím, že chceš domů. Povídej mi o svém domě — jak tam vypadalo?",
                    "score": 100,
                    "feedback": "Skvěle! Validujete emoci, nepopíráte její realitu a přesměrujete na pozitivní vzpomínky. Vzpomínání na dětství může být uklidňující.",
                    "consequence": "Máma se usměje a začne vyprávět o svém dětském domě, zahradě, mamince. Pocit 'chci domů' se změní na hezké vzpomínání."
                }
            ],
            "learning_point": "NIKDY nepřipomínejte smrt blízkého — clovek s demenci ji prožívá ZNOVU. Vstupte do jeho reality, validujte emoce a přesměrujte na pozitivní vzpomínky."
        }
    ],
    "huntington": [
        {
            "id": "hd-s1",
            "title": "Partner s HD je podrážděný",
            "context": "Váš partner (42 let) má Huntingtonovu chorobu v raném stádiu. Dnes je velmi podrážděný a křičí na vás kvůli maličkosti.",
            "difficulty": "intermediate",
            "character": "Partner Tomas (42 let, HD — rane stadium)",
            "situation": "Tomáš křičí: 'Proč jsi zase zapomněla koupit mléko?! To nedokážeš jednu věc?!' Přitom jste mléko koupili — stojí v lednici.",
            "options": [
                {
                    "id": "a",
                    "text": "Mléko je v lednici! Přestaň na mě křičet, není to normální!",
                    "score": 20,
                    "feedback": "Pochopitelná reakce, ale konfrontace zvyšuje napětí. Tomáš svou podrážděnost NEOVLÁDÁ — je to příznak HD, ne zloba.",
                    "consequence": "Tomáš ještě víc zrudne a práskne dveřmi. Oba jste rozrušení. Konflikt eskaloval."
                },
                {
                    "id": "b",
                    "text": "Vidím, že jsi naštvaný. Pojďme se podívat do lednice společně — myslím, že tam mléko je.",
                    "score": 100,
                    "feedback": "Výborně! Validujete emoci (vidim, ze jsi nastvany), nehadate se o fakta, a nabizite spolecne reseni. Klidný hlas snižuje napětí.",
                    "consequence": "Tomáš vás následuje, vidí mléko a uklidní se. Za chvíli se omluví. Vy víte, že to byla HD, ne on."
                },
                {
                    "id": "c",
                    "text": "Odejít z místnosti a nechat ho vychladnout.",
                    "score": 60,
                    "feedback": "Není špatné si vzít prostor, ale Tomáš může odsunutí vnímat jako odmítání. Lepší je klidně reagovat a pak navrhnout pauzu SPOLEČNĚ.",
                    "consequence": "Tomáš se po chvíli uklidní, ale cítí se vinný a osamělý. Vy jste se konfliktu vyhnuli, ale nepomohli."
                }
            ],
            "learning_point": "Podrážděnost u HD je PŘÍZNAK, ne zloba. Nereagujte konfrontačně. Validujte emoci, nabídněte řešení klidně. Po zklidnění mluvte o tom, co se stalo — BEZ obviňování."
        },
        {
            "id": "hd-s2",
            "title": "Dítě se ptá na dědičnost",
            "context": "Vašemu synovi je 19 let. Jeho matka má HD. Syn se ptá: 'Mám se nechat testovat? Chci vědět.'",
            "difficulty": "intermediate",
            "character": "Syn Jakub (19 let, ohrozeny HD)",
            "situation": "Jakub říká: 'Tati, už to chci vědět. Budu mít Huntingtona jako máma? Chci se nechat testovat.'",
            "options": [
                {
                    "id": "a",
                    "text": "Určitě se nech testovat. Budeš aspoň vědět, na čem jsi.",
                    "score": 30,
                    "feedback": "Tlačit do testování není správné. Rozhodnutí musí být JEHO. Pozitivní výsledek může být devastující — musí být připraven.",
                    "consequence": "Jakub se nechá testovat bez přípravy. Výsledek je pozitivní. Nedokáže to zpracovat. Propadne depresi."
                },
                {
                    "id": "b",
                    "text": "Rozumím, že chceš vědět. Je to tvoje rozhodnutí. Pojďme nejdřív do genetické poradny — tam ti vysvětlí všechny možnosti a pomůžou ti se připravit.",
                    "score": 100,
                    "feedback": "Skvěle! Respektujete jeho přání, ale směřujete ho k profesionálnímu poradenství. Genetické poradenství PŘED testem je povinné a důležité.",
                    "consequence": "Jakub absolvuje genetické poradenství. S psychologem se připraví na oba výsledky. Ať už se rozhodne jakkoli, bude připraven."
                },
                {
                    "id": "c",
                    "text": "Raději se netestuj. K čemu ti to bude? Budeš se tím jen trápit.",
                    "score": 20,
                    "feedback": "Chránit dítě je přirozené, ale ZAKAZOVAT mu informace není správné. V 19 letech má právo se rozhodnout sám.",
                    "consequence": "Jakub se cítí, že mu upírá kontrolu nad jeho životem. Nechá se testovat tajně, bez podpory. Cokoli zjistí, bude na to sám."
                }
            ],
            "learning_point": "Rozhodnutí o genetickém testu je OSOBNÍ. Respektujte pranni dítěte, ale směřujte k profesionálnímu genetickému poradenství. Nikdy netlačte ANI jedním směrem."
        }
    ],
    "als": [
        {
            "id": "als-s1",
            "title": "Manželka se nemůže domluvit",
            "context": "Vaše manželka (58 let) má ALS ve středním stádiu. Řeč je těžce srozumitelná. Snaží se vám něco říct.",
            "difficulty": "beginner",
            "character": "Manzelka Eva (58 let, ALS — stredni stadium)",
            "situation": "Eva říká něco, ale rozumíte jen: '...te...fo...vnu...' Vypadá to důležité. Snaží se znovu a znovu, ale vy nerozumíte.",
            "options": [
                {
                    "id": "a",
                    "text": "Evicko, promiun, nerozumím. Zkus to napsat na tablet.",
                    "score": 90,
                    "feedback": "Dobrý přístup! Nabízíte alternativní kanál (psaní). Omluvit se za neporozumění je správné — ukazuje respekt.",
                    "consequence": "Eva pomalu napíše na tabletu: 'zavolej vnučce k narozeninám'. Problém vyřešen. Eva se usmívá."
                },
                {
                    "id": "b",
                    "text": "Aha, jasně! (Předstíráte, že rozumíte, abyste ji netrápili.)",
                    "score": 10,
                    "feedback": "Předstírání porozumění je NEJHORŠÍ reakce. Eva pozná, že nerozumíte. Cítí se neviditelná a bezmocná. A důležitá informace se ztratí.",
                    "consequence": "Eva vidí, že předstíráte. Přestane mluvit a otočí se. Vnučka nedostane přání k narozeninám. Eva pláče sama."
                },
                {
                    "id": "c",
                    "text": "Počkej, zkusíme to po písmenech. První písmeno? T? Te-le-fon? Telefonovat? Komu — vnučce?",
                    "score": 100,
                    "feedback": "Výborně! Pomáháte rozluštit zprávu po částech. Trpělivost, potvrzování a postupné upřesňování je zlatý standard komunikace při těžké dysartrii.",
                    "consequence": "Eva kývne: 'Ano! Zavolej vnučce!' Oba se usmíváte. Společně jste to zvládli."
                }
            ],
            "learning_point": "NIKDY nepředstírejte porozumění. Nabídněte alternativní kanály (psaní, ukazování, hláskování po písmenech). Trpělivost je klíčová — každá zpráva se dá dešifrovat."
        },
        {
            "id": "als-s2",
            "title": "Pacient odmítá komunikátor",
            "context": "Pan Horák (61 let) má ALS. Logoped mu doporučil začít s eye-tracking komunikátorem, ale pan Horák odmítá.",
            "difficulty": "intermediate",
            "character": "Pan Horák (61 let, ALS — stredni stadium)",
            "situation": "Pan Horák rika (obtížně): 'Já...nepotřebuju...ten...stroj. Ještě...mluvím.' Logoped vám říká, že za 3–6 měsíců už mluvit nebude.",
            "options": [
                {
                    "id": "a",
                    "text": "Pane Horáku, logoped říká, že za půl roku nebudete mluvit. Musíte se to naučit teď.",
                    "score": 20,
                    "feedback": "Konfrontace s prognózou je krutá a neúčinná. Pan Horák vi, co ho ceka. Odmítání je obranný mechanismus — potřebuje čas.",
                    "consequence": "Pan Horák se rozplache a odmítne jakoukoli spolupráci. Ztrácí důvěru k týmu."
                },
                {
                    "id": "b",
                    "text": "Rozumím, že ještě mluvíte a nechcete používat stroj. Co kdybychom to zatím jen vyzkoušeli — jako pojistku? Ukážeme vám, jak funguje. Bez závazků.",
                    "score": 100,
                    "feedback": "Skvěle! Respektujete jeho pocity, snižujete tlak ('bez závazků') a nabízíte to jako POJISTKU, ne náhražku řeči. Drobné kroky vedou k přijetí.",
                    "consequence": "Pan Horák souhlasi s ukazkou. Když vidí, že může ovládat počítač očima, je fascinován. Sám říká: 'To je jako kouzlo.'"
                },
                {
                    "id": "c",
                    "text": "Dobře, počkáme. Až budete připraven, dejte nám vědět.",
                    "score": 40,
                    "feedback": "Respektujete jeho přání, ale riskujete, že bude pozdě. Učit se používat eye-tracking je SNAZŠÍ, dokud člověk ještě mluví. Pak může srovnávat.",
                    "consequence": "Za 4 měsíce pan Horák ztratí řeč. Teď se pokusí o eye-tracking — ale učení je mnohokrát těžší. Lituje, že nezačal dřív."
                }
            ],
            "learning_point": "Nepřesvědčujte silou, ale ani nečekejte příliš. Nabídněte pomůcky jako POJISTKU bez závazků. Drobné kroky — ukázka, zkouška, postupné přijetí. Čas je klíčový faktor."
        }
    ],

    # ---- PARKINSON SCÉNÁŘE (v256) ----
    "parkinson": [
        {
            "id": "park-s1",
            "title": "Manžel mluví tiše a nerozumíte mu",
            "context": "Pečujete o manžela Josefa (68 let) s Parkinsonovou chorobou. Při večeři vám něco říká, ale neslyšíte.",
            "difficulty": "beginner",
            "character": {
                "name": "Josef",
                "age": 68,
                "diagnosis": "Parkinsonova choroba — střední stádium",
                "communication_level": "Tichý, monotónní hlas (hypofonie)"
            },
            "situation": "Josef vám přes stůl něco říká, ale slyšíte jen tichý, mumlavý zvuk. Televize je zapnutá v pozadí.",
            "options": [
                {
                    "id": "a",
                    "text": "Josefe, mluv hlasitěji! Vždycky mumleš!",
                    "score": 10,
                    "feedback": "Výtka zhoršuje frustraci. Člověk s Parkinsonem NEMŮŽE snadno mluvit hlasitěji — hypofonie je příznak nemoci, ne lenost.",
                    "consequence": "Josef se odmlčí a zbytek večeře jí v tichu. Cítí se provinile za něco, co nemůže ovlivnit."
                },
                {
                    "id": "b",
                    "text": "Vypnete TV, posadíte se blíže a řeknete: 'Josefe, promiň, neslyšela jsem. Povíš mi to znovu?'",
                    "score": 100,
                    "feedback": "Skvěle! Snížili jste hluk, přiblížili se a požádali o zopakování BEZ výčitek. Přesně tak se komunikuje s člověkem s hypofonií.",
                    "consequence": "Josef vám zopakuje, co chtěl říct. Cítí se respektovaný. Komunikace plyne dál."
                },
                {
                    "id": "c",
                    "text": "Kývnete a předstíráte, že rozumíte.",
                    "score": 10,
                    "feedback": "Předstírání je nejhorší varianta — člověk pozná, že nerozumíte, a cítí se bezvýznamný. Ztrácí motivaci komunikovat.",
                    "consequence": "Josef si všimne, že nerozumíte. Příště se nebude ani snažit mluvit. Postupně se izoluje."
                }
            ],
            "learning_point": "Nikdy neříkejte 'mluv hlasitěji' — místo toho snižte hluk, přibližte se a požádejte o zopakování BEZ výčitek."
        },
        {
            "id": "park-s2",
            "title": "Dcera si myslí, že tatínka nebaví návštěva",
            "context": "Navštěvujete tatínka Zdeňka (72 let) s Parkinsonem. Dcera Lucie (40 let) si stěžuje na jeho 'lhostejnost'.",
            "difficulty": "intermediate",
            "character": {
                "name": "Zdeněk",
                "age": 72,
                "diagnosis": "Parkinsonova choroba — střední stádium",
                "communication_level": "Výrazná hypomimie (maskový obličej)"
            },
            "situation": "Lucie vám říká: 'Víš co, už tam nebudu chodit. Táta se vůbec netváří, že má radost. Jen tam sedí jako socha. Je mu to jedno.'",
            "options": [
                {
                    "id": "a",
                    "text": "Máš pravdu, asi ho to nebaví.",
                    "score": 0,
                    "feedback": "Posilujete mylný dojem. Tatínek CÍTÍ radost, ale maskový obličej mu brání ji vyjádřit. Hypomimie je příznak nemoci, ne lhostejnost.",
                    "consequence": "Lucie přestane chodit na návštěvy. Tatínek ztrácí kontakt s rodinou a propadá izolaci."
                },
                {
                    "id": "b",
                    "text": "Luci, tatínek má něco, čemu se říká maskový obličej. Svaly obličeje jsou ztuhlé, ale UVNITŘ cítí radost úplně stejně. Všímej si jinak — stiskne ti ruku? Kývne? Požádej ho, ať řekne, jak se cítí.",
                    "score": 100,
                    "feedback": "Výborně! Vysvětlujete hypomimii a učíte dceru číst jiné signály emocí — stisk ruky, slova, gesta.",
                    "consequence": "Lucie pochopí. Při další návštěvě chytne tátu za ruku — a on ji stiskne. Říká: 'Lucko, jsem rád, že jsi přišla.' Oba pláčou štěstím."
                },
                {
                    "id": "c",
                    "text": "To je těžké. Zkus ho víc rozesmát.",
                    "score": 30,
                    "feedback": "Snaha o 'rozesmání' může být frustrující pro oba. Člověk s hypomimií se NEDOKÁŽE usmát, i když vnitřně chce. Lepší je pochopit příčinu.",
                    "consequence": "Lucie se snaží dělat vtipné věci, ale táta nereaguje mimikou. Oba jsou frustrovaní."
                }
            ],
            "learning_point": "Maskový obličej (hypomimie) je příznak Parkinsona, NE lhostejnost. Učte rodinu číst jiné signály: stisk ruky, hlas, slova."
        },
        {
            "id": "park-s3",
            "title": "Pacient odmítá chodit po pádu",
            "context": "Pan Moravec (74 let) má Parkinsona ve středním stádiu. Po nedávném pádu odmítá chodit sám.",
            "difficulty": "intermediate",
            "character": {
                "name": "Pan Moravec",
                "age": 74,
                "diagnosis": "Parkinsonova choroba — střední stádium, po pádu",
                "communication_level": "Komunikace zachována, strach z pádu"
            },
            "situation": "Pan Moravec říká: 'Já už nikam nepůjdu. Minule jsem spadl a bolelo to. Radši budu sedět v křesle.'",
            "options": [
                {
                    "id": "a",
                    "text": "Pane Moravče, musíte chodit! Jinak se vám svaly oslabí.",
                    "score": 20,
                    "feedback": "Pravda, ale příkaz zvyšuje úzkost. Strach z pádu je u Parkinsona LEGITIMNÍ — pády jsou reálné nebezpečí. Rozkazování nepomůže.",
                    "consequence": "Pan Moravec se cítí pod tlakem. Zkusí jít sám, aby nevzbudil nevoli — a znovu spadne. Strach se ještě prohloubí."
                },
                {
                    "id": "b",
                    "text": "Rozumím, že máte strach. Ten pád byl nepříjemný. Co kdybychom to zkusili pomalu — půjdeme spolu, já budu hned vedle. A požádáme fyzioterapeuta o cvičení na rovnováhu.",
                    "score": 100,
                    "feedback": "Skvěle! Validujete strach (je oprávněný), nabízíte bezpečí (společný krok) a odborné řešení (fyzioterapeut). Přesně správný postup.",
                    "consequence": "Pan Moravec souhlasí. S oporou udělá pár kroků. Fyzioterapeut nastaví cvičení na rovnováhu. Za týden chodí sám po chodbě."
                },
                {
                    "id": "c",
                    "text": "Dobře, tak budeme chodit s chodítkem.",
                    "score": 60,
                    "feedback": "Dobrý nápad, ale chybí validace strachu. A chodítko by měl doporučit odborník — ne každé chodítko je vhodné pro člověka s Parkinsonem (freezing s chodítkem může být nebezpečný).",
                    "consequence": "Pan Moravec dostane chodítko, ale při freezingu se o něj zakopne. Bez odborného vedení může být pomůcka i rizikem."
                }
            ],
            "learning_point": "Strach z pádu je u Parkinsona běžný a LEGITIMNÍ. Validujte ho, nabídněte bezpečí a zapojte fyzioterapeuta. Nikdy neříkejte 'musíte chodit' bez nabídky podpory."
        },
        {
            "id": "park-s4",
            "title": "Noční halucinace — manžel vidí 'děti v pokoji'",
            "context": "Paní Vlasta (78 let) má Parkinsona v pokročilém stádiu. V noci vidí děti, které si hrají v jejím pokoji.",
            "difficulty": "advanced",
            "character": {
                "name": "Paní Vlasta",
                "age": 78,
                "diagnosis": "Parkinsonova choroba — pokročilé stádium, vizuální halucinace",
                "communication_level": "Řeč tichá, ale srozumitelná. Při halucinacích úzkostná."
            },
            "situation": "Je 2:00 ráno. Paní Vlasta budí manžela: 'Podívej, ty děti si tu zase hrají! Kdo je sem pustil?' Manžel nevidí nic, je vyděšený a neví, jak reagovat.",
            "options": [
                {
                    "id": "a",
                    "text": "Žádné děti tu nejsou, Vlasto! To se ti zdá, to je ta nemoc. Jdi spát.",
                    "score": 0,
                    "feedback": "Popírání halucinací zvyšuje úzkost. Paní Vlasta vidí děti jako reálné — říct jí, že lže, je ponižující a neúčinné.",
                    "consequence": "Paní Vlasta je rozrušená, pláče. Manžel je frustrovaný. Situace eskaluje, nikdo nespí."
                },
                {
                    "id": "b",
                    "text": "Vidím, že tě to znervózňuje, Vlasto. Pojďme se podívat společně. (Po chvíli:) Vypadá to, že už odešly. Pojď, udělám ti čaj a posadíme se.",
                    "score": 100,
                    "feedback": "Výborně! Validujete emoci (strach), nepotvrzujete ani nepopíráte halucinaci, přesměrujete pozornost (čaj, společnost). Přesně správný postup.",
                    "consequence": "Paní Vlasta se uklidní. S čajem v ruce zapomene na vidiny. Za chvíli usne. Manžel ráno zavolá neurologovi — halucinace mohou signalizovat potřebu úpravy léků."
                },
                {
                    "id": "c",
                    "text": "Zavoláme záchranku, to není normální!",
                    "score": 30,
                    "feedback": "Bezpečná reakce, ale přehnaná. Vizuální halucinace jsou u pokročilého Parkinsona ČASTÉ — nejsou akutní emergencí (pokud nejsou spojené s agresí). Stačí informovat neurologa ráno.",
                    "consequence": "Záchranná služba přijede, konstatuje halucinace. Paní Vlasta je vystrašená z nemocnice. Neurolog ráno řekne, že stačil telefonát."
                }
            ],
            "learning_point": "Halucinace u pokročilého Parkinsona jsou časté (často vedlejší účinek léků). Nikdy nepopírejte — validujte emoci, přesměrujte pozornost. Informujte neurologa (úprava léků). Záchranku volejte jen při agresivním chování."
        },
        {
            "id": "park-s5",
            "title": "OFF fáze v supermarketu — náhlé 'zamrznutí'",
            "context": "Pan Novák (69 let) má Parkinsona ve středním stádiu. Při nákupu nastane náhlá OFF fáze.",
            "difficulty": "advanced",
            "character": {
                "name": "Pan Novák",
                "age": 69,
                "diagnosis": "Parkinsonova choroba — střední stádium, on/off fenomén",
                "communication_level": "V OFF fázi výrazně zpomalený, hlas téměř neslyšitelný"
            },
            "situation": "Pan Novák nakupuje v supermarketu s manželkou. Uprostřed uličky se náhle zastaví — nemůže pohnout nohama, ruce se třesou, hlas je téměř neslyšitelný. Lidé se dívají, někdo říká: 'Ten pán je asi opilý.'",
            "options": [
                {
                    "id": "a",
                    "text": "Pojďte, lidi koukaj! Musíme odtud! (a tahá ho za ruku)",
                    "score": 10,
                    "feedback": "Tahání za ruku při freezingu může způsobit pád! Sociální tlak ('lidi koukaj') situaci zhoršuje. Pan Novák nemůže chodit — není to volba.",
                    "consequence": "Pan Novák při tahu za ruku ztratí rovnováhu a spadne. V nemocnici zjistí zlomeninu zápěstí. Příště odmítne jít nakupovat."
                },
                {
                    "id": "b",
                    "text": "Máme čas, nespěchej. (Stojíte vedle něj jako opora.) Zkusíme to spolu: raz — dva — tři. Nebo si na chvíli sedneme na lavičku a počkáme na ON fázi.",
                    "score": 100,
                    "feedback": "Perfektní! Odstraňujete tlak ('máme čas'), nabízíte oporu, používáte počítání (překonání freezingu), nebo nabízíte alternativu (lavička, čekání na ON fázi). Kolemjdoucím stačí říct: 'Děkuji, zvládáme to.'",
                    "consequence": "Pan Novák se po minutě uvolní. S počítáním udělá pár kroků k lavičce. Po 20 minutách léky zaberou (ON fáze) a dokončí nákup."
                },
                {
                    "id": "c",
                    "text": "Zavolám záchranku, asi má mrtvici!",
                    "score": 40,
                    "feedback": "Pochopitelná reakce, pokud neznáte Parkinson. Ale OFF fáze NENÍ emergentní stav — je to dočasné období, kdy léky nepůsobí. Záchranná služba nepomůže víc než klid a čas.",
                    "consequence": "Záchranná služba přijede, konstatuje OFF fázi. Pan Novák se cítí ponížený. Celá situace trvá hodinu místo 20 minut."
                }
            ],
            "learning_point": "OFF fáze je dočasný stav (léky přestaly účinkovat). NENÍ to emergentní situace. Klid, trpělivost, počítání nahlas nebo čekání na ON fázi — to je správný postup. Nikdy netahejte za ruku — hrozí pád!"
        }
    ]
}


# ============================================
# 📰 STATICKÉ NOVINKY
# ============================================

HEALTH_NEWS_CACHE = {"articles": [], "updated": None}

STATIC_NEWS = {
    "health": [
        {
            "title": "Disfázie po CMP — důležitost včasné rehabilitace",
            "description": "Logopedická péče v prvních 6 měsících po cévní mozkové příhodě výrazně zvyšuje šanci na zotavení řeči. Čím dříve rehabilitace začne, tím lepší výsledky.",
            "source": "Asociace klinických logopedů ČR",
            "category": "health",
            "relevance": "dysphasia",
            "url": None
        },
        {
            "title": "Huntingtonova choroba — nové výzkumy genové terapie",
            "description": "Vědci z Univerzity Karlovy publikovali nové poznatky o možnostech genové terapie u Huntingtonovy choroby. Výzkum je stále v rané fázi, ale výsledky jsou slibné.",
            "source": "Akademie věd ČR",
            "category": "science",
            "relevance": "huntington",
            "url": None
        },
        {
            "title": "Komunikační pomůcky pro seniory — co je nového",
            "description": "Nová generace tabletů a aplikací usnadňuje komunikaci lidem s poruchami řeči. Augmentativní komunikace je stále dostupnější.",
            "source": "SAAK",
            "category": "technology",
            "relevance": "als,dysphasia",
            "url": None
        },
        {
            "title": "FAST test zachraňuje životy — naučte se ho",
            "description": "Face, Arms, Speech, Time — jednoduchý test, který pozná cévní mozkovou příhodu. Každá minuta se počítá. Pokud vidíte příznaky, volejte 155.",
            "source": "MZ ČR",
            "category": "health",
            "relevance": "dysphasia",
            "url": None
        },
        {
            "title": "ALS Ice Bucket Challenge — 10 let poté",
            "description": "Virální kampaň přinesla miliardy na výzkum ALS. Co se díky tomu změnilo a jaké nové léky jsou ve vývoji.",
            "source": "ALS Liga",
            "category": "health",
            "relevance": "als",
            "url": None
        },
        {
            "title": "Nový lék na Alzheimera schválen v EU",
            "description": "Evropská léková agentura schválila lecanemab — první lék, který prokazatelně zpomaluje úbytek kognitivních funkcí v počátečním stádiu Alzheimera.",
            "source": "EMA",
            "category": "health",
            "relevance": "dementia",
            "url": None
        },
        {
            "title": "Demence v ČR — 160 000 lidí potřebuje pomoc",
            "description": "Česká alzheimerovská společnost upozorňuje na rostoucí počet lidí s demencí a nedostatek specializované péče. Nový Národní akční plán slibuje změnu.",
            "source": "ČALS",
            "category": "health",
            "relevance": "dementia",
            "url": None
        },
        {
            "title": "Dětská disfázie — kdy navštívit logopeda?",
            "description": "Včasná diagnostika vývojové disfázie je klíčová. Logopedi doporučují vyšetření, pokud dítě ve 2 letech nemluví žádná slova nebo ve 3 letech netvoří věty.",
            "source": "Asociace klinických logopedů ČR",
            "category": "health",
            "relevance": "dysphasia",
            "url": None
        },
        {
            "title": "Společnost Parkinson otevírá nové regionální kluby",
            "description": "Pacientská organizace rozšiřuje síť svépomocných klubů po celé ČR. Setkání nabízí podporu, informace a společnost pro lidi s Parkinsonem a jejich rodiny.",
            "source": "Společnost Parkinson, z.s.",
            "category": "health",
            "relevance": "parkinson",
            "url": None
        },
        {
            "title": "Tanec a tai chi prokazatelně pomáhají při Parkinsonově chorobě",
            "description": "Studie potvrzují, že pravidelný tanec (zejm. tango) a tai chi zlepšují rovnováhu, snižují riziko pádů a zpomalují progresi motorických příznaků.",
            "source": "Movement Disorders Journal",
            "category": "science",
            "relevance": "parkinson",
            "url": None
        }
    ],
    "politics": [
        {
            "title": "Vláda schválila vyšší příspěvek na péči",
            "description": "Příspěvek na péči se zvyšuje o 10 % pro osoby se stupněm III a IV. Změna platí od července.",
            "source": "MPSV",
            "category": "politics",
            "relevance": "general",
            "url": None
        },
        {
            "title": "Nový zákon o sociálních službách",
            "description": "Ministerstvo práce připravuje novelu zákona o sociálních službách. Rozšíří se nabídka terénních služeb pro seniory.",
            "source": "ČTK",
            "category": "politics",
            "relevance": "general",
            "url": None
        }
    ],
    "sports": [
        {
            "title": "Pohyb jako prevence — sport pro seniory",
            "description": "Pravidelný pohyb snižuje riziko demence o 30 %. Stačí 30 minut chůze denně.",
            "source": "FTVS UK",
            "category": "sports",
            "relevance": "general",
            "url": None
        },
        {
            "title": "Český paralympijský tým — inspirace pro všechny",
            "description": "Čeští paralympionici ukazují, že handicap není překážka. Příběhy odhodlání a vítězství.",
            "source": "Paralympijský výbor",
            "category": "sports",
            "relevance": "general",
            "url": None
        }
    ]
}


# ============================================
# 🗺️ MAPOVÁNÍ KURZŮ NA KOMUNIKAČNÍ POTŘEBY
# ============================================

COURSE_TO_NEEDS = {
    "dysphasia": ["dysphasia_child", "dysphasia_adult", "aphasia"],
    "huntington": ["huntington"],
    "als": ["als"],
    "dementia": ["alzheimer", "alzheimer_early", "alzheimer_middle", "alzheimer_late",
                  "lewy_body", "vascular", "frontotemporal", "parkinson_dementia"],
    "parkinson": ["parkinson", "parkinson_dementia", "parkinson_motor", "parkinson_communication"]
}
