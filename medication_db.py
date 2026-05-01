"""
💊 MEDICATION KNOWLEDGE BASE — Czech seniors
============================================
Curated database of ~35 most-prescribed medications for Czech seniors.

For each medication:
  name           — canonical Czech brand or generic name
  aliases        — alternative brand names / spellings (lowercase)
  group          — pharmacological class (slug)
  group_human    — human-readable Czech category
  indication     — what it treats (Czech, voice-friendly)
  typical_dose   — common dosing (Czech, voice-friendly)
  food           — food/timing instructions (Czech)
  warnings       — list of Czech warnings (each ≤120 chars for TTS)

NOT a substitute for a pharmacist or SPC. Advisory only.
Every reply MUST end with "Konzultujte s lékařem nebo lékárníkem."

v466 — initial DB (35 entries). Expand based on real telemetry of senior
medication_list profiles + lekarna.cz top-100 list.
"""

import logging
import re

logger = logging.getLogger(__name__)


MEDICATIONS = {
    # ───────────────────────────────────────────────────────────────
    # ANTIKOAGULANCIA / ANTITROMBOTIKA — ředění krve
    # ───────────────────────────────────────────────────────────────
    'warfarin': {
        'name': 'Warfarin',
        'aliases': ['lawarin', 'warfarin orion'],
        'group': 'anticoagulant',
        'group_human': 'lék na ředění krve',
        'indication': 'prevence sraženin po infarktu, mozkové mrtvici nebo při fibrilaci síní',
        'typical_dose': 'individuálně podle krevního testu INR, obvykle dvě a půl až sedm a půl miligramu denně',
        'food': 'každý den ve stejnou dobu, opatrně se zelenou listovou zeleninou a brusinkami',
        'warnings': [
            'při krvácení z nosu, modřinách bez příčiny nebo krvi v moči ihned k lékaři',
            'pravidelné kontroly INR každé čtyři týdny',
            'nekombinovat s ibuprofenem ani aspirinem, paracetamol je v pořádku',
        ],
        'allergy_classes': ['warfarin'],
    },
    'anopyrin': {
        'name': 'Anopyrin',
        'aliases': ['aspirin', 'acylpyrin', 'kyselina acetylsalicylová'],
        'group': 'antiplatelet',
        'group_human': 'lék na ředění krve',
        'indication': 'prevence infarktu a mrtvice u rizikových pacientů, někdy proti bolesti',
        'typical_dose': 'sto miligramů denně preventivně',
        'food': 'po jídle, kvůli žaludku',
        'warnings': [
            'může dráždit žaludek, opatrně při vředech',
            'nekombinovat s ibuprofenem ani warfarinem',
        ],
    },
    'eliquis': {
        'name': 'Eliquis',
        'aliases': ['apixaban'],
        'group': 'anticoagulant',
        'group_human': 'lék na ředění krve, novější typ',
        'indication': 'prevence mrtvice při fibrilaci síní, léčba hluboké žilní trombózy',
        'typical_dose': 'pět miligramů dvakrát denně',
        'food': 's jídlem nebo bez jídla',
        'warnings': [
            'při zranění nebo plánované operaci informovat lékaře',
            'pravidelné kontroly ledvin',
        ],
    },
    'xarelto': {
        'name': 'Xarelto',
        'aliases': ['rivaroxaban'],
        'group': 'anticoagulant',
        'group_human': 'lék na ředění krve, novější typ',
        'indication': 'prevence mrtvice při fibrilaci síní, prevence sraženin po operaci',
        'typical_dose': 'dvacet miligramů jednou denně',
        'food': 's jídlem (zlepší vstřebávání)',
        'warnings': [
            'při zranění nebo operaci informovat lékaře',
            'opatrně při onemocnění ledvin',
        ],
    },
    'pradaxa': {
        'name': 'Pradaxa',
        'aliases': ['dabigatran'],
        'group': 'anticoagulant',
        'group_human': 'lék na ředění krve, novější typ',
        'indication': 'prevence mrtvice při fibrilaci síní',
        'typical_dose': 'sto padesát miligramů dvakrát denně',
        'food': 'kapsle nedrtit ani neotevírat',
        'warnings': [
            'opatrně při onemocnění ledvin',
            'při krvácení nebo zranění ihned k lékaři',
        ],
    },
    'plavix': {
        'name': 'Plavix',
        'aliases': ['clopidogrel', 'klopidogrel'],
        'group': 'antiplatelet',
        'group_human': 'lék na ředění krve',
        'indication': 'prevence sraženin po infarktu nebo zavedení stentu',
        'typical_dose': 'sedmdesát pět miligramů jednou denně',
        'food': 's jídlem nebo bez jídla',
        'warnings': [
            'před operací informovat lékaře, případně přerušit',
            'může způsobovat modřiny',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # ANTIHYPERTENZIVA / KARDIOVASKULÁRNÍ
    # ───────────────────────────────────────────────────────────────
    'concor': {
        'name': 'Concor',
        'aliases': ['bisoprolol'],
        'group': 'beta_blocker',
        'group_human': 'beta-blokátor (lék na srdce a tlak)',
        'indication': 'vysoký krevní tlak, srdeční selhání, angina pectoris',
        'typical_dose': 'pět až deset miligramů jednou denně ráno',
        'food': 'ráno, s jídlem nebo bez',
        'warnings': [
            'nevynechávat náhle, dávku snižovat postupně',
            'při pomalém pulzu (pod padesát) informovat lékaře',
        ],
    },
    'betaloc': {
        'name': 'Betaloc',
        'aliases': ['metoprolol', 'vasocardin'],
        'group': 'beta_blocker',
        'group_human': 'beta-blokátor (lék na srdce a tlak)',
        'indication': 'vysoký krevní tlak, srdeční selhání, prevence migrény',
        'typical_dose': 'padesát až dvě stě miligramů denně, často ve dvou dávkách',
        'food': 's jídlem',
        'warnings': [
            'nevynechávat náhle',
            'opatrně při astmatu',
        ],
    },
    'tritace': {
        'name': 'Tritace',
        'aliases': ['ramipril', 'amprilan', 'piramil'],
        'group': 'ace_inhibitor',
        'group_human': 'ACE inhibitor (lék na tlak a srdce)',
        'indication': 'vysoký krevní tlak, srdeční selhání, ochrana ledvin u diabetiků',
        'typical_dose': 'pět až deset miligramů jednou denně',
        'food': 's jídlem nebo bez',
        'warnings': [
            'může způsobovat suchý dráždivý kašel — informovat lékaře',
            'pravidelné kontroly draslíku a ledvin',
        ],
    },
    'prestarium': {
        'name': 'Prestarium',
        'aliases': ['perindopril'],
        'group': 'ace_inhibitor',
        'group_human': 'ACE inhibitor (lék na tlak a srdce)',
        'indication': 'vysoký krevní tlak, srdeční selhání',
        'typical_dose': 'pět nebo deset miligramů jednou denně ráno',
        'food': 'ráno před jídlem',
        'warnings': [
            'může způsobovat suchý kašel',
            'kontroly draslíku',
        ],
    },
    'lozap': {
        'name': 'Lozap',
        'aliases': ['losartan', 'lozartan'],
        'group': 'arb',
        'group_human': 'sartan (lék na tlak)',
        'indication': 'vysoký krevní tlak, ochrana ledvin u diabetiků',
        'typical_dose': 'padesát až sto miligramů denně',
        'food': 's jídlem nebo bez',
        'warnings': [
            'nezpůsobuje kašel jako ACE inhibitory',
            'kontroly draslíku',
        ],
    },
    'norvasc': {
        'name': 'Norvasc',
        'aliases': ['amlodipin', 'amlessa', 'agen'],
        'group': 'calcium_channel_blocker',
        'group_human': 'blokátor vápníkových kanálů (lék na tlak)',
        'indication': 'vysoký krevní tlak, angina pectoris',
        'typical_dose': 'pět až deset miligramů jednou denně',
        'food': 's jídlem nebo bez',
        'warnings': [
            'může způsobit otoky kotníků — informovat lékaře',
            'opatrně se grapefruitem',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # DIURETIKA — odvodnění
    # ───────────────────────────────────────────────────────────────
    'furosemid': {
        'name': 'Furosemid',
        'aliases': ['furon', 'furorese', 'lasix'],
        'group': 'loop_diuretic',
        'group_human': 'silné diuretikum (odvodnění)',
        'indication': 'srdeční selhání, otoky, vysoký tlak',
        'typical_dose': 'čtyřicet až osmdesát miligramů ráno',
        'food': 'ráno, ne na noc kvůli časté potřebě močení',
        'warnings': [
            'doplňovat draslík (banány, brambory) nebo užívat kalium tablety',
            'pozor na závratě při rychlém vstávání',
            'dehydratace v horku — pít dostatek',
        ],
    },
    'verospiron': {
        'name': 'Verospiron',
        'aliases': ['spironolakton'],
        'group': 'potassium_sparing_diuretic',
        'group_human': 'diuretikum šetřící draslík',
        'indication': 'srdeční selhání, otoky, vysoký tlak',
        'typical_dose': 'dvacet pět až sto miligramů denně',
        'food': 's jídlem',
        'warnings': [
            'NEUŽÍVAT doplňky draslíku — riziko hyperkalemie',
            'může způsobit zvětšení prsou u mužů',
        ],
    },
    'tertensif': {
        'name': 'Tertensif',
        'aliases': ['indapamid'],
        'group': 'thiazide_diuretic',
        'group_human': 'mírné diuretikum',
        'indication': 'vysoký krevní tlak',
        'typical_dose': 'jedna a půl miligramu jednou denně ráno',
        'food': 'ráno s jídlem',
        'warnings': [
            'doplňovat draslík',
            'může způsobit suchá ústa',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # STATINY — cholesterol
    # ───────────────────────────────────────────────────────────────
    'sortis': {
        'name': 'Sortis',
        'aliases': ['atorvastatin', 'tulip', 'atoris'],
        'group': 'statin',
        'group_human': 'statin (lék na cholesterol)',
        'indication': 'snížení cholesterolu, prevence infarktu a mrtvice',
        'typical_dose': 'deset až čtyřicet miligramů večer',
        'food': 'večer, kdykoli, NIKDY s grapefruitem',
        'warnings': [
            'při bolesti svalů ihned informovat lékaře — riziko myopatie',
            'kontroly jaterních testů jednou ročně',
        ],
    },
    'vasilip': {
        'name': 'Vasilip',
        'aliases': ['simvastatin', 'zocor'],
        'group': 'statin',
        'group_human': 'statin (lék na cholesterol)',
        'indication': 'snížení cholesterolu, prevence infarktu a mrtvice',
        'typical_dose': 'dvacet až čtyřicet miligramů večer',
        'food': 'večer, NIKDY s grapefruitem',
        'warnings': [
            'při bolesti svalů ihned k lékaři',
            'kontroly jaterních testů',
        ],
    },
    'crestor': {
        'name': 'Crestor',
        'aliases': ['rosuvastatin'],
        'group': 'statin',
        'group_human': 'statin (lék na cholesterol)',
        'indication': 'snížení cholesterolu',
        'typical_dose': 'deset až čtyřicet miligramů jednou denně',
        'food': 'kdykoli, s jídlem nebo bez',
        'warnings': [
            'při bolesti svalů k lékaři',
            'opatrně při onemocnění jater',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # DIABETES
    # ───────────────────────────────────────────────────────────────
    'metformin': {
        'name': 'Metformin',
        'aliases': ['siofor', 'glucophage', 'metfogamma'],
        'group': 'antidiabetic',
        'group_human': 'lék na cukrovku (typ 2)',
        'indication': 'diabetes 2. typu, někdy prediabetes',
        'typical_dose': 'pět set až dva tisíce miligramů denně, rozděleno do dávek',
        'food': 'při jídle nebo po jídle, kvůli žaludku',
        'warnings': [
            'omezit alkohol — riziko laktátové acidózy',
            'při průjmech a zvracení dočasně přerušit',
            'kontroly ledvin',
        ],
    },
    'amaryl': {
        'name': 'Amaryl',
        'aliases': ['glimepirid'],
        'group': 'antidiabetic',
        'group_human': 'lék na cukrovku (typ 2)',
        'indication': 'diabetes 2. typu',
        'typical_dose': 'jeden až čtyři miligramy ráno',
        'food': 'ráno před snídaní',
        'warnings': [
            'pozor na hypoglykemii (nízkou hladinu cukru) — vždy mít kostku cukru',
            'pravidelně jíst, nevynechávat snídani',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # GASTRO — žaludek
    # ───────────────────────────────────────────────────────────────
    'helicid': {
        'name': 'Helicid',
        'aliases': ['omeprazol', 'omez', 'losec'],
        'group': 'ppi',
        'group_human': 'inhibitor protonové pumpy (lék na žaludek)',
        'indication': 'pálení žáhy, vředy, refluxní nemoc',
        'typical_dose': 'dvacet miligramů ráno',
        'food': 'ráno na lačno, půl hodiny před jídlem',
        'warnings': [
            'dlouhodobé užívání kontrolovat — vliv na vstřebávání B12 a hořčíku',
        ],
    },
    'controloc': {
        'name': 'Controloc',
        'aliases': ['pantoprazol'],
        'group': 'ppi',
        'group_human': 'inhibitor protonové pumpy (lék na žaludek)',
        'indication': 'vředy, refluxní nemoc',
        'typical_dose': 'čtyřicet miligramů ráno',
        'food': 'ráno na lačno',
        'warnings': [
            'dlouhodobé užívání kontrolovat',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # BOLEST / TEPLOTA
    # ───────────────────────────────────────────────────────────────
    'paralen': {
        'name': 'Paralen',
        'aliases': ['paracetamol', 'panadol'],
        'group': 'analgesic',
        'group_human': 'lék proti bolesti a horečce',
        'indication': 'bolest hlavy, horečka, mírná bolest',
        'typical_dose': 'pět set miligramů, maximálně čtyři tablety za den',
        'food': 's jídlem nebo bez',
        'warnings': [
            'NEPŘEKRAČOVAT čtyři gramy denně — riziko poškození jater',
            'opatrně při onemocnění jater',
        ],
    },
    'ibuprofen': {
        'name': 'Ibuprofen',
        'aliases': ['brufen', 'ibalgin', 'nurofen'],
        'group': 'nsaid',
        'group_human': 'nesteroidní protizánětlivý lék',
        'indication': 'bolest, zánět, horečka',
        'typical_dose': 'čtyři sta miligramů, maximálně třikrát denně',
        'food': 's jídlem, nikdy na lačno (dráždí žaludek)',
        'warnings': [
            'NEKOMBINOVAT s warfarinem ani anopyrinem',
            'opatrně při vředech a onemocnění ledvin',
        ],
    },
    'voltaren': {
        'name': 'Voltaren',
        'aliases': ['diclofenac', 'olfen', 'dolmina'],
        'group': 'nsaid',
        'group_human': 'protizánětlivý lék',
        'indication': 'bolest kloubů, zad, zánět',
        'typical_dose': 'padesát miligramů třikrát denně',
        'food': 's jídlem',
        'warnings': [
            'opatrně při vředech a srdečním selhání',
            'NEKOMBINOVAT s warfarinem',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # ŠTÍTNÁ ŽLÁZA
    # ───────────────────────────────────────────────────────────────
    'euthyrox': {
        'name': 'Euthyrox',
        'aliases': ['letrox', 'l-thyroxin', 'levothyroxin'],
        'group': 'thyroid',
        'group_human': 'hormon štítné žlázy',
        'indication': 'snížená funkce štítné žlázy (hypotyreóza)',
        'typical_dose': 'dle TSH, obvykle padesát až sto padesát mikrogramů ráno',
        'food': 'RÁNO NA LAČNO, půl hodiny před snídaní',
        'warnings': [
            'NIKDY neužívat společně s vápníkem, železem nebo kávou — sníží se vstřebávání',
            'pravidelné kontroly TSH (každých 6-12 měsíců)',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # PSYCHIATRIE / SPÁNEK
    # ───────────────────────────────────────────────────────────────
    'cipralex': {
        'name': 'Cipralex',
        'aliases': ['escitalopram'],
        'group': 'ssri',
        'group_human': 'antidepresivum (typ SSRI)',
        'indication': 'deprese, úzkosti',
        'typical_dose': 'deset miligramů ráno',
        'food': 's jídlem nebo bez',
        'warnings': [
            'účinek nastupuje za 2-4 týdny',
            'NEVYSAZOVAT náhle',
            'NEKOMBINOVAT s tramadolem bez konzultace',
        ],
    },
    'zoloft': {
        'name': 'Zoloft',
        'aliases': ['sertralin', 'asentra'],
        'group': 'ssri',
        'group_human': 'antidepresivum (typ SSRI)',
        'indication': 'deprese, úzkosti, panická porucha',
        'typical_dose': 'padesát až sto miligramů denně',
        'food': 's jídlem',
        'warnings': [
            'účinek za 2-4 týdny',
            'NEVYSAZOVAT náhle',
        ],
    },
    'lexaurin': {
        'name': 'Lexaurin',
        'aliases': ['bromazepam'],
        'group': 'benzodiazepine',
        'group_human': 'sedativum (uklidňující lék)',
        'indication': 'krátkodobě úzkost, neklid',
        'typical_dose': 'jeden a půl až tři miligramy podle potřeby',
        'food': 's jídlem nebo bez',
        'warnings': [
            'NIKDY nekombinovat s alkoholem',
            'riziko závislosti — neužívat dlouhodobě',
            'pozor na pády a zmatenost u seniorů',
        ],
    },
    'stilnox': {
        'name': 'Stilnox',
        'aliases': ['zolpidem', 'hypnogen'],
        'group': 'hypnotic',
        'group_human': 'lék na spaní',
        'indication': 'krátkodobě nespavost',
        'typical_dose': 'pět miligramů večer před spaním',
        'food': 'na lačno, hned před spaním',
        'warnings': [
            'NIKDY s alkoholem',
            'riziko nočního chození a pádů — opatrně',
            'neužívat déle než 4 týdny',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # VITAMÍNY / DOPLŇKY
    # ───────────────────────────────────────────────────────────────
    'vigantol': {
        'name': 'Vigantol',
        'aliases': ['vitamin d3', 'cholekalciferol', 'd-vitamin'],
        'group': 'vitamin',
        'group_human': 'vitamin D',
        'indication': 'prevence osteoporózy, podpora imunity',
        'typical_dose': 'dle vyšetření 1000-4000 IU denně',
        'food': 's tučným jídlem (lepší vstřebávání)',
        'warnings': [
            'kontroly hladiny vápníku při vysokých dávkách',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: ANTIBIOTIKA — penicillin family, macrolides, cephalosporins
    # ───────────────────────────────────────────────────────────────
    'amoxicilin': {
        'name': 'Amoxicilin',
        'aliases': ['amoxicillin', 'amoclen', 'duomox'],
        'group': 'antibiotic_penicillin',
        'group_human': 'antibiotikum (penicilínového typu)',
        'indication': 'bakteriální infekce dýchacích cest, močových cest, kůže',
        'typical_dose': 'pět set miligramů třikrát denně po osmi hodinách',
        'food': 's jídlem nebo bez',
        'warnings': [
            'při vyrážce, otoku tváře nebo dušnosti ihned přestat užívat',
            'doužívat celé balení i když se cítíte lépe',
        ],
    },
    'augmentin': {
        'name': 'Augmentin',
        'aliases': ['amoxiclav', 'curam', 'amoksiklav'],
        'group': 'antibiotic_penicillin',
        'group_human': 'antibiotikum (penicilínového typu s klavulánovou kyselinou)',
        'indication': 'bakteriální infekce dýchacích cest, dutin, močových cest',
        'typical_dose': 'sedm set padesát miligramů dvakrát denně',
        'food': 's jídlem (sníží žaludeční nevolnost)',
        'warnings': [
            'při alergii na penicilin NEUŽÍVAT',
            'doužívat celé balení',
            'může způsobit průjem',
        ],
    },
    'sumamed': {
        'name': 'Sumamed',
        'aliases': ['azitromycin', 'azithromycin', 'azitrox', 'azimed'],
        'group': 'antibiotic_macrolide',
        'group_human': 'antibiotikum (makrolid)',
        'indication': 'infekce dýchacích cest, ORL, kožní infekce',
        'typical_dose': 'pět set miligramů jednou denně po dobu tří dnů',
        'food': 'na lačno, hodinu před jídlem nebo dvě hodiny po',
        'warnings': [
            'opatrně při srdečních arytmiích — může prodloužit QT interval',
            'nekombinovat s warfarinem bez konzultace',
        ],
    },
    'klacid': {
        'name': 'Klacid',
        'aliases': ['clarithromycin', 'klaritromycin', 'fromilid'],
        'group': 'antibiotic_macrolide',
        'group_human': 'antibiotikum (makrolid)',
        'indication': 'infekce dýchacích cest, dutin, kůže',
        'typical_dose': 'pět set miligramů dvakrát denně',
        'food': 's jídlem',
        'warnings': [
            'mnoho lékových interakcí — informovat lékaře o všech lécích',
            'opatrně se statiny',
        ],
    },
    'cefuroxim': {
        'name': 'Cefuroxim',
        'aliases': ['zinnat', 'zinacef', 'cefurox'],
        'group': 'antibiotic_cephalosporin',
        'group_human': 'antibiotikum (cefalosporin)',
        'indication': 'infekce dýchacích cest, močových cest, kůže',
        'typical_dose': 'dvě stě padesát až pět set miligramů dvakrát denně',
        'food': 's jídlem',
        'warnings': [
            'při těžké alergii na penicilin opatrně — možná křížová reakce',
        ],
    },
    'biseptol': {
        'name': 'Biseptol',
        'aliases': ['cotrimoxazol', 'sumetrolim', 'bactrim', 'sulfametoxazol'],
        'group': 'antibiotic_sulfonamide',
        'group_human': 'antibiotikum (sulfonamid)',
        'indication': 'močové infekce, některé respirační infekce',
        'typical_dose': 'dvě tablety dvakrát denně po dvanácti hodinách',
        'food': 's jídlem a velkým množstvím tekutin',
        'warnings': [
            'při alergii na sulfonamidy NEUŽÍVAT',
            'pijte hodně vody — prevence krystalů v moči',
            'opatrně s warfarinem',
        ],
    },
    'ciprofloxacin': {
        'name': 'Ciprofloxacin',
        'aliases': ['ciprinol', 'ciplox', 'cifran'],
        'group': 'antibiotic_quinolone',
        'group_human': 'antibiotikum (chinolon)',
        'indication': 'močové infekce, infekce trávicího traktu',
        'typical_dose': 'pět set miligramů dvakrát denně',
        'food': 'na lačno, NIKDY s mlékem nebo mléčnými výrobky (sníží vstřebávání)',
        'warnings': [
            'opatrně při onemocnění šlach (riziko ruptury Achillovy šlachy)',
            'omezit pobyt na slunci',
            'nekombinovat s antacidy v stejný čas',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: ANTIHISTAMINIKA — alergie
    # ───────────────────────────────────────────────────────────────
    'zyrtec': {
        'name': 'Zyrtec',
        'aliases': ['cetirizin', 'analergin', 'zodac', 'cerex'],
        'group': 'antihistamine',
        'group_human': 'antihistaminikum (lék na alergii)',
        'indication': 'sezónní alergie, kopřivka, alergická rýma',
        'typical_dose': 'deset miligramů jednou denně večer',
        'food': 's jídlem nebo bez',
        'warnings': [
            'může způsobit ospalost',
            'opatrně při řízení',
        ],
    },
    'claritine': {
        'name': 'Claritine',
        'aliases': ['loratadin', 'flonidan', 'claritine repetabs'],
        'group': 'antihistamine',
        'group_human': 'antihistaminikum (lék na alergii)',
        'indication': 'sezónní alergie, kopřivka',
        'typical_dose': 'deset miligramů jednou denně',
        'food': 'kdykoli',
        'warnings': [
            'méně ospalosti než starší antihistaminika',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: GERD/ŽALUDEK — H2 blokátory
    # ───────────────────────────────────────────────────────────────
    'famotidin': {
        'name': 'Famotidin',
        'aliases': ['quamatel', 'famosan'],
        'group': 'h2_blocker',
        'group_human': 'lék na žaludek (H2 blokátor)',
        'indication': 'pálení žáhy, vředy, refluxní nemoc',
        'typical_dose': 'dvacet až čtyřicet miligramů večer',
        'food': 'večer, s jídlem nebo bez',
        'warnings': [
            'sníženě dávky při onemocnění ledvin',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: ASTMA / CHOPN — inhalátory
    # ───────────────────────────────────────────────────────────────
    'ventolin': {
        'name': 'Ventolin',
        'aliases': ['salbutamol', 'salamol', 'aerolin'],
        'group': 'bronchodilator',
        'group_human': 'inhalátor (rozšíření průdušek)',
        'indication': 'astma, rychlá úleva při dušnosti',
        'typical_dose': 'jeden až dva vdechy podle potřeby, max čtyřikrát denně',
        'food': 'inhalace, ne pro polykání',
        'warnings': [
            'při častějším použití než obvykle informovat lékaře',
            'může způsobit třes rukou nebo bušení srdce',
        ],
    },
    'symbicort': {
        'name': 'Symbicort',
        'aliases': ['budesonid+formoterol', 'easyhaler'],
        'group': 'bronchodilator',
        'group_human': 'inhalátor (kombinovaný)',
        'indication': 'astma, CHOPN — pravidelná léčba',
        'typical_dose': 'jeden až dva vdechy dvakrát denně, ráno a večer',
        'food': 'po inhalaci si vypláchnout ústa vodou (prevence kvasinkové infekce)',
        'warnings': [
            'NENÍ pro rychlou úlevu — k té slouží Ventolin',
            'pravidelná inhalace — nevynechávat',
        ],
    },
    'spiriva': {
        'name': 'Spiriva',
        'aliases': ['tiotropium', 'tiogiva'],
        'group': 'bronchodilator',
        'group_human': 'inhalátor pro CHOPN',
        'indication': 'chronická obstrukční plicní nemoc (CHOPN)',
        'typical_dose': 'jeden vdech jednou denně, vždy ve stejnou dobu',
        'food': 'inhalace ráno',
        'warnings': [
            'opatrně při glaukomu nebo zvětšené prostatě',
            'může způsobit suchá ústa',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: OČI — kapky
    # ───────────────────────────────────────────────────────────────
    'xalatan': {
        'name': 'Xalatan',
        'aliases': ['latanoprost', 'lataprost'],
        'group': 'eye_drops',
        'group_human': 'oční kapky (snížení nitroočního tlaku)',
        'indication': 'glaukom, vysoký nitrooční tlak',
        'typical_dose': 'jedna kapka do každého oka jednou denně večer',
        'food': 'kapky, ne pro polykání. Vyjmout kontaktní čočky předem.',
        'warnings': [
            'může změnit barvu duhovky (na hnědou)',
            'pravidelné kontroly tlaku',
        ],
    },
    'cosopt': {
        'name': 'Cosopt',
        'aliases': ['dorzolamid+timolol'],
        'group': 'eye_drops',
        'group_human': 'oční kapky (kombinované, glaukom)',
        'indication': 'glaukom — kombinovaná léčba',
        'typical_dose': 'jedna kapka dvakrát denně',
        'food': 'kapky',
        'warnings': [
            'opatrně při astmatu (timolol je beta-blokátor)',
            'po kapkání tisknout vnitřní koutek 1 minutu',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: ZÁCPA / TRÁVENÍ
    # ───────────────────────────────────────────────────────────────
    'forlax': {
        'name': 'Forlax',
        'aliases': ['macrogol', 'fortrans'],
        'group': 'laxative',
        'group_human': 'projímadlo (osmotické)',
        'indication': 'zácpa',
        'typical_dose': 'jeden až dva sáčky denně rozpuštěné ve vodě',
        'food': 'kdykoli, hodně tekutin',
        'warnings': [
            'pijte dostatečně vody',
            'při dlouhodobé zácpě informovat lékaře',
        ],
    },
    'lactulose': {
        'name': 'Lactulose',
        'aliases': ['duphalac', 'lactulose biomedica'],
        'group': 'laxative',
        'group_human': 'projímadlo (laktulóza)',
        'indication': 'zácpa, jaterní encefalopatie',
        'typical_dose': 'patnáct až třicet mililitrů denně',
        'food': 'ráno, hodně vody',
        'warnings': [
            'opatrně při cukrovce (obsahuje cukr)',
            'plynatost na začátku užívání je běžná',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: SILNÁ BOLEST — opiáty
    # ───────────────────────────────────────────────────────────────
    'tramal': {
        'name': 'Tramal',
        'aliases': ['tramadol', 'tramundin', 'noax'],
        'group': 'opioid',
        'group_human': 'silný lék proti bolesti (opioid)',
        'indication': 'středně silná až silná bolest',
        'typical_dose': 'padesát až sto miligramů každých šest hodin',
        'food': 's jídlem',
        'warnings': [
            'NEKOMBINOVAT s alkoholem ani sedativy',
            'může způsobit závratě, ospalost',
            'NIKDY s SSRI bez konzultace (riziko serotoninového syndromu)',
        ],
    },
    'zaldiar': {
        'name': 'Zaldiar',
        'aliases': ['tramadol+paracetamol', 'palgotal'],
        'group': 'opioid',
        'group_human': 'kombinovaný lék proti bolesti (tramadol + paracetamol)',
        'indication': 'středně silná bolest',
        'typical_dose': 'jedna až dvě tablety čtyřikrát denně, max osm tablet',
        'food': 's jídlem',
        'warnings': [
            'NEKOMBINOVAT s alkoholem',
            'maximálně osm tablet denně (kvůli paracetamolu)',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: NEVOLNOST / ZÁVRATĚ
    # ───────────────────────────────────────────────────────────────
    'cerucal': {
        'name': 'Cerucal',
        'aliases': ['metoclopramid', 'degan'],
        'group': 'antiemetic',
        'group_human': 'lék proti nevolnosti a zvracení',
        'indication': 'nevolnost, zvracení, migréna',
        'typical_dose': 'deset miligramů třikrát denně před jídlem',
        'food': 'patnáct minut před jídlem',
        'warnings': [
            'krátkodobá léčba (max 5 dní u seniorů)',
            'může způsobit neklid nebo třes',
        ],
    },
    'betaserc': {
        'name': 'Betaserc',
        'aliases': ['betahistin', 'serc', 'urutal'],
        'group': 'antivertigo',
        'group_human': 'lék proti závratím',
        'indication': 'Ménièrova choroba, závratě',
        'typical_dose': 'šestnáct až čtyřicet osm miligramů denně, rozděleno do dávek',
        'food': 's jídlem',
        'warnings': [
            'opatrně při astmatu',
            'účinek nastupuje postupně (týdny)',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: INSULIN
    # ───────────────────────────────────────────────────────────────
    'lantus': {
        'name': 'Lantus',
        'aliases': ['insulin glargin', 'toujeo', 'abasaglar'],
        'group': 'insulin',
        'group_human': 'inzulin (dlouhodobý)',
        'indication': 'diabetes 1. a 2. typu',
        'typical_dose': 'individuálně podle hladiny cukru, jednou denně',
        'food': 'injekce do podkoží, vždy ve stejnou dobu',
        'warnings': [
            'pozor na hypoglykemii — vždy mít kostku cukru',
            'rotovat místa vpichu',
            'NIKDY nemíchat s jiným inzulínem v stříkačce',
        ],
    },
    'humalog': {
        'name': 'Humalog',
        'aliases': ['insulin lispro', 'novorapid', 'apidra'],
        'group': 'insulin',
        'group_human': 'inzulin (rychlý, k jídlu)',
        'indication': 'diabetes — pokrytí jídla',
        'typical_dose': 'individuálně podle množství sacharidů v jídle',
        'food': 'krátce před jídlem (5-15 min) nebo s jídlem',
        'warnings': [
            'pozor na hypoglykemii pokud nesníte plánované jídlo',
            'rotovat místa vpichu',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: SEDATIVA — alternativy benzodiazepinů
    # ───────────────────────────────────────────────────────────────
    'atarax': {
        'name': 'Atarax',
        'aliases': ['hydroxyzin'],
        'group': 'sedative_antihistamine',
        'group_human': 'sedativum / antihistaminikum',
        'indication': 'úzkost, svědění, nespavost',
        'typical_dose': 'dvacet pět miligramů večer',
        'food': 'večer, s jídlem nebo bez',
        'warnings': [
            'může způsobit ospalost — opatrně při řízení',
            'NIKDY s alkoholem',
            'opatrně u seniorů (riziko zmatenosti)',
        ],
    },
    'mirtazapin': {
        'name': 'Mirtazapin',
        'aliases': ['remeron', 'esprital'],
        'group': 'antidepressant',
        'group_human': 'antidepresivum (zlepšuje spánek a chuť k jídlu)',
        'indication': 'deprese, nespavost u deprese',
        'typical_dose': 'patnáct až třicet miligramů večer před spaním',
        'food': 'večer, s jídlem nebo bez',
        'warnings': [
            'může zvyšovat hmotnost',
            'účinek nastupuje za 2-4 týdny',
            'NEVYSAZOVAT náhle',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: VOLBY HORMONŮ A KOSTI
    # ───────────────────────────────────────────────────────────────
    'fosamax': {
        'name': 'Fosamax',
        'aliases': ['alendronat', 'alendronic acid', 'fosavance'],
        'group': 'bisphosphonate',
        'group_human': 'lék na osteoporózu (bisfosfonát)',
        'indication': 'osteoporóza, prevence zlomenin',
        'typical_dose': 'sedmdesát miligramů jednou týdně ráno',
        'food': 'RÁNO NA LAČNO, půl hodiny před snídaní, zapít VELKÝM POHÁREM VODY',
        'warnings': [
            'po užití NESEDAT ANI NELEŽET 30 minut — riziko podráždění jícnu',
            'pouze čistá voda — žádná káva, čaj, mléko, džus',
            'kontroly zubů (riziko osteonekrózy čelisti při delším užívání)',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: DALŠÍ ČASTÉ
    # ───────────────────────────────────────────────────────────────
    'wobenzym': {
        'name': 'Wobenzym',
        'aliases': ['wobenzym mucos'],
        'group': 'enzyme',
        'group_human': 'enzymový přípravek',
        'indication': 'podpora imunity, hojení, otoky',
        'typical_dose': 'tři tablety třikrát denně',
        'food': 'půl hodiny před jídlem, zapít vodou',
        'warnings': [
            'opatrně při užívání léků na ředění krve',
        ],
    },
    'magnesium': {
        'name': 'Magnesium',
        'aliases': ['magnez', 'magneb6', 'magnesii lactici'],
        'group': 'mineral',
        'group_human': 'doplněk hořčíku',
        'indication': 'svalové křeče, podpora srdce, nervová soustava',
        'typical_dose': 'tři sta až čtyři sta miligramů denně',
        'food': 's jídlem',
        'warnings': [
            'může způsobit průjem při vysokých dávkách',
            'opatrně při onemocnění ledvin',
        ],
    },
    'detralex': {
        'name': 'Detralex',
        'aliases': ['diosmin+hesperidin', 'flavobion'],
        'group': 'venoactive',
        'group_human': 'lék na cévy (žilní problémy)',
        'indication': 'žilní nedostatečnost, hemoroidy, otoky nohou',
        'typical_dose': 'jedna tableta dvakrát denně',
        'food': 's jídlem',
        'warnings': [
            'dlouhodobé užívání obvykle bez problémů',
        ],
    },
    'kalium': {
        'name': 'Kalium chloratum',
        'aliases': ['draslík', 'kaldyum', 'kalnormin'],
        'group': 'mineral',
        'group_human': 'doplněk draslíku',
        'indication': 'při ztrátách draslíku (diuretika), svalové křeče',
        'typical_dose': 'jeden gram jednou až dvakrát denně',
        'food': 's jídlem a velkým množstvím vody',
        'warnings': [
            'NEUŽÍVAT s ACE inhibitory ani Verospironem bez konzultace',
            'kontroly hladiny draslíku',
        ],
    },

    # ───────────────────────────────────────────────────────────────
    # v467: KORTIKOIDY
    # ───────────────────────────────────────────────────────────────
    'prednison': {
        'name': 'Prednison',
        'aliases': ['prednisone', 'medrol', 'methylprednisolon'],
        'group': 'corticosteroid',
        'group_human': 'kortikoid (silný protizánětlivý lék)',
        'indication': 'záněty, autoimunitní choroby, alergické reakce',
        'typical_dose': 'individuálně, obvykle pět až čtyřicet miligramů denně',
        'food': 'ráno s jídlem',
        'warnings': [
            'NEVYSAZOVAT náhle — postupně snižovat dávku',
            'může zvýšit cukr a krevní tlak',
            'při dlouhodobé léčbě prevence osteoporózy',
        ],
    },
}


# Build reverse-lookup map (alias → canonical key) once at import time.
_ALIAS_INDEX = {}
for _key, _data in MEDICATIONS.items():
    _ALIAS_INDEX[_key.lower()] = _key
    for _alias in _data.get('aliases', []):
        _ALIAS_INDEX[_alias.lower().strip()] = _key


def lookup(name):
    """Find medication info by canonical name OR alias OR fuzzy substring.

    Returns the medication dict (with extra '_match' field) or None.
    Match priority: exact key > exact alias > substring of name > substring of alias.
    """
    if not name or not isinstance(name, str):
        return None
    q = name.strip().lower()
    if not q:
        return None

    # 1. Exact alias / key match
    if q in _ALIAS_INDEX:
        key = _ALIAS_INDEX[q]
        result = dict(MEDICATIONS[key])
        result['_match'] = 'exact'
        result['_key'] = key
        return result

    # 2. Substring match — q contains alias OR alias contains q
    for alias_lower, key in _ALIAS_INDEX.items():
        if alias_lower in q or q in alias_lower:
            if abs(len(alias_lower) - len(q)) <= 3 or len(alias_lower) >= 5:
                result = dict(MEDICATIONS[key])
                result['_match'] = 'substring'
                result['_key'] = key
                return result

    return None


def speak_brief(name):
    """Generate a short Czech voice-friendly description (≤2 sentences).

    Used by the medication_info intent — keeps it under 200 chars so TTS
    stays inside the senior-attention window.
    """
    m = lookup(name)
    if not m:
        return None
    return (
        f"{m['name']} je {m['group_human']}. "
        f"Užívá se na {m['indication']}. "
        f"Konzultujte vždy s lékařem."
    )


def speak_full(name):
    """Longer voice-friendly description with dose + food + warnings.
    Used when senior asks 'řekni mi víc o X'."""
    m = lookup(name)
    if not m:
        return None
    parts = [
        f"{m['name']} je {m['group_human']}.",
        f"Užívá se na {m['indication']}.",
        f"Běžná dávka: {m['typical_dose']}.",
        f"Užívání: {m['food']}.",
    ]
    if m.get('warnings'):
        parts.append(f"Důležité: {m['warnings'][0]}.")
    parts.append("Vždy konzultujte s lékařem nebo lékárníkem.")
    return ' '.join(parts)


def list_for_user(user_id):
    """Resolve every entry in a user's medications_list to drug-DB entries.
    Returns list of {input_name, db_entry_or_None}."""
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id) or {}
        names = profile.get('medications_list') or []
        if not isinstance(names, list):
            return []
        out = []
        for n in names:
            if not n:
                continue
            entry = lookup(n)
            out.append({'input_name': n, 'entry': entry})
        return out
    except Exception as e:
        logger.debug(f"list_for_user failed: {e}")
        return []


def db_stats():
    """Quick stats for the /api/medication/db/stats endpoint."""
    groups = {}
    for data in MEDICATIONS.values():
        g = data.get('group_human', 'jiné')
        groups[g] = groups.get(g, 0) + 1
    return {
        'total_medications': len(MEDICATIONS),
        'total_aliases': len(_ALIAS_INDEX),
        'by_group': groups,
    }
