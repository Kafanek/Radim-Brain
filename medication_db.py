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
