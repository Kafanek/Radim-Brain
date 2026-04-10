# ============================================
# 💊 DRUG INTERACTION CHECKER
# ============================================
# Basic Czech medication interaction database.
# Checks common dangerous combinations for seniors.
# NOT a substitute for pharmacist — advisory only.
# ============================================

import logging
import re

logger = logging.getLogger(__name__)

# Common dangerous drug interactions for seniors
# Format: (drug_a_patterns, drug_b_patterns, severity, warning_cz)
INTERACTIONS = [
    # Warfarin + NSAID → bleeding risk
    (['warfarin', 'anopyrin'],
     ['ibuprofen', 'brufen', 'diclofenac', 'voltaren', 'aspirin', 'acylpyrin'],
     'HIGH', 'Warfarin + NSAID (protizánětlivé) zvyšuje riziko krvácení! Konzultujte s lékařem.'),

    # ACE inhibitors + Potassium → hyperkalemia
    (['ramipril', 'enalapril', 'lisinopril', 'perindopril', 'prestarium'],
     ['draslík', 'kalium', 'kaldyum'],
     'MEDIUM', 'ACE inhibitor + draslík může způsobit hyperkalemii. Poraďte se s lékařem.'),

    # Metformin + Alcohol
    (['metformin', 'glucophage', 'siofor'],
     ['alkohol', 'víno', 'pivo'],
     'MEDIUM', 'Metformin + alkohol zvyšuje riziko laktátové acidózy. Omezte alkohol.'),

    # Statins + Grapefruit
    (['atorvastatin', 'simvastatin', 'rosuvastatin', 'sortis'],
     ['grapefruit', 'grep'],
     'LOW', 'Statiny + grapefruit může zesílit vedlejší účinky. Vyhněte se grapefruitu.'),

    # Beta-blockers + Calcium channel blockers
    (['bisoprolol', 'metoprolol', 'atenolol', 'concor', 'betaloc'],
     ['verapamil', 'diltiazem', 'isoptin'],
     'HIGH', 'Beta-blokátor + verapamil/diltiazem může způsobit nebezpečné zpomalení srdce!'),

    # Blood thinners + other blood thinners
    (['warfarin', 'anopyrin'],
     ['heparin', 'xarelto', 'eliquis', 'pradaxa', 'rivaroxaban', 'apixaban'],
     'HIGH', 'Kombinace dvou léků na ředění krve je velmi nebezpečná! Ihned kontaktujte lékaře.'),

    # Sedatives + Opioids
    (['diazepam', 'alprazolol', 'oxazepam', 'lexaurin', 'neurol', 'xanax'],
     ['tramadol', 'codein', 'kodein', 'morphin', 'fentanyl', 'oxycodon'],
     'HIGH', 'Sedativa + opiáty = vysoké riziko útlumu dýchání! NEBEZPEČNÁ kombinace.'),

    # Digoxin + Diuretics
    (['digoxin', 'lanoxin'],
     ['furosemid', 'hydrochlorothiazid', 'indapamid'],
     'MEDIUM', 'Digoxin + diuretika: pokles draslíku může zesílit účinek digoxinu. Kontrolujte hladiny.'),

    # SSRIs + MAOIs
    (['sertralin', 'citalopram', 'escitalopram', 'fluoxetin', 'paroxetin', 'zoloft'],
     ['selegilin', 'moklobemid', 'rasagilin'],
     'HIGH', 'SSRI + MAO inhibitor = serotoninový syndrom! NIKDY nekombinujte bez lékaře.'),

    # Multiple sedatives
    (['zolpidem', 'stilnox', 'zopiclone', 'imovane'],
     ['diazepam', 'alprazolol', 'oxazepam', 'lexaurin', 'neurol'],
     'HIGH', 'Kombinace hypnotik a sedativ je nebezpečná — riziko pádů a útlumu dýchání.'),
]


def check_interactions(medications):
    """Check list of medications for known interactions.

    Args:
        medications: list of medication names (Czech or generic)

    Returns:
        list of { drug_a, drug_b, severity, warning } dicts
    """
    if not medications or len(medications) < 2:
        return []

    # Normalize medication names
    meds_lower = [m.lower().strip() for m in medications if m]
    found = []

    for drug_a_patterns, drug_b_patterns, severity, warning in INTERACTIONS:
        match_a = None
        match_b = None

        for med in meds_lower:
            for pattern in drug_a_patterns:
                if pattern in med:
                    match_a = med
                    break
            for pattern in drug_b_patterns:
                if pattern in med:
                    match_b = med
                    break

        if match_a and match_b and match_a != match_b:
            found.append({
                'drug_a': match_a,
                'drug_b': match_b,
                'severity': severity,
                'warning': warning
            })

    return found


def check_user_interactions(user_id):
    """Check interactions for a specific user based on their medication profile.

    Returns list of warnings or empty list if safe.
    """
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id)
        if not profile:
            return []

        # Collect all meds from profile
        all_meds = []
        meds_list = profile.get('medications_list', [])
        if isinstance(meds_list, list):
            all_meds.extend(meds_list)

        med_times = profile.get('medication_times', {})
        if isinstance(med_times, dict):
            for period, period_meds in med_times.items():
                if isinstance(period_meds, list):
                    all_meds.extend(period_meds)

        # Deduplicate
        all_meds = list(set(all_meds))

        return check_interactions(all_meds)

    except Exception as e:
        logger.debug(f"Drug interaction check error: {e}")
        return []
