"""
🩹 ALLERGY KNOWLEDGE BASE — drug-allergy cross-check (v467)
============================================================
Pairs with medication_db.py to detect when a user's medication
collides with a known allergy (or cross-reactive class).

Coverage:
  - Top 12 Czech-relevant drug allergies
  - Cross-reactivity (e.g. penicillin → all beta-lactams)
  - Group → allergy_class mapping (so we don't have to tag every drug)

NOT a substitute for an immunologist. Advisory only.
"""

import logging
import re

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 1. Catalog of common drug/substance allergies
# Each entry: (canonical_class, czech_label, aliases, severity_default)
# ─────────────────────────────────────────────────────────────────
ALLERGY_CATALOG = {
    'penicillin': {
        'label': 'penicilin',
        'aliases': ['penicilin', 'pn', 'penicilínu', 'penicilínem', 'amoxicilin',
                    'augmentin', 'ampicilin'],
        'severity_default': 'severe',
        'cross_reactive_with': ['beta_lactam'],
        'description': 'beta-laktamová antibiotika',
    },
    'beta_lactam': {
        'label': 'beta-laktamy',
        'aliases': ['beta laktam', 'beta-laktam'],
        'severity_default': 'severe',
        'cross_reactive_with': ['penicillin', 'cephalosporin'],
        'description': 'penicilíny, cefalosporiny, karbapenemy',
    },
    'cephalosporin': {
        'label': 'cefalosporiny',
        'aliases': ['cefalosporiny', 'cefuroxim', 'ceftriaxon'],
        'severity_default': 'moderate',
        'cross_reactive_with': ['penicillin', 'beta_lactam'],
        'description': 'antibiotika typu cefalosporinů',
    },
    'sulfonamide': {
        'label': 'sulfonamidy',
        'aliases': ['sulfonamidy', 'sulfa', 'biseptol', 'cotrimoxazol', 'bactrim'],
        'severity_default': 'severe',
        'cross_reactive_with': [],
        'description': 'sulfonamidová antibiotika',
    },
    'nsaid': {
        'label': 'protizánětlivé léky (NSAID)',
        'aliases': ['nsaid', 'protizánětliv', 'ibuprofen', 'brufen', 'ibalgin',
                    'diclofenac', 'voltaren', 'naproxen', 'aspirin', 'acylpyrin',
                    'anopyrin', 'aulin'],
        'severity_default': 'severe',
        'cross_reactive_with': ['aspirin'],
        'description': 'ibuprofen, diclofenac, naproxen, aspirin a podobné',
    },
    'aspirin': {
        'label': 'kyselina acetylsalicylová (Aspirin/Anopyrin)',
        'aliases': ['aspirin', 'anopyrin', 'acylpyrin', 'kyselina acetylsalicylová'],
        'severity_default': 'severe',
        'cross_reactive_with': ['nsaid'],
        'description': 'aspirin a NSAID obecně',
    },
    'iodine': {
        'label': 'jód',
        'aliases': ['jod', 'jód', 'kontrastní látka', 'kontrast', 'jodid'],
        'severity_default': 'severe',
        'cross_reactive_with': [],
        'description': 'jód, kontrastní látky pro CT/RTG',
    },
    'latex': {
        'label': 'latex',
        'aliases': ['latex', 'guma', 'rukavice'],
        'severity_default': 'moderate',
        'cross_reactive_with': [],
        'description': 'přírodní latex',
    },
    'opioid': {
        'label': 'opiáty',
        'aliases': ['opiát', 'opiaty', 'morfin', 'morphin', 'kodein', 'tramadol',
                    'fentanyl'],
        'severity_default': 'moderate',
        'cross_reactive_with': [],
        'description': 'morfin, kodein, tramadol a další opiáty',
    },
    'macrolide': {
        'label': 'makrolidy (Sumamed, Klacid)',
        'aliases': ['makrolid', 'makrolidy', 'azitromycin', 'sumamed', 'clarithromycin',
                    'klacid', 'erytromycin'],
        'severity_default': 'moderate',
        'cross_reactive_with': [],
        'description': 'azitromycin, klaritromycin, erytromycin',
    },
    'statin': {
        'label': 'statiny',
        'aliases': ['statin', 'statiny', 'sortis', 'atorvastatin', 'simvastatin'],
        'severity_default': 'moderate',
        'cross_reactive_with': [],
        'description': 'léky na cholesterol',
    },
    'ace_inhibitor': {
        'label': 'ACE inhibitory',
        'aliases': ['ace inhibitor', 'ace', 'ramipril', 'tritace', 'lisinopril',
                    'perindopril', 'prestarium', 'enalapril'],
        'severity_default': 'moderate',
        'cross_reactive_with': [],
        'description': 'ramipril, lisinopril, perindopril a podobné',
    },
}


# Build reverse-lookup index: alias_lower → class_key
_ALLERGY_ALIAS_INDEX = {}
for _class, _data in ALLERGY_CATALOG.items():
    _ALLERGY_ALIAS_INDEX[_class.lower()] = _class
    for _alias in _data.get('aliases', []):
        _ALLERGY_ALIAS_INDEX[_alias.lower().strip()] = _class


def normalize_allergy(raw_text):
    """Map a free-form allergy mention ('penicilínu', 'aspirin', 'na NSAID')
    to a canonical class key. Returns None if not recognised — caller can
    still store the raw text but auto-cross-check won't fire for it."""
    if not raw_text:
        return None
    q = raw_text.strip().lower()
    # Strip Czech declensions for common cases
    for ending in ['ovi', 'ové', 'ové', 'em', 'eho', 'ého', 'u', 'í', 'a', 'y']:
        if q.endswith(ending) and len(q) > len(ending) + 2:
            stripped = q[:-len(ending)]
            if stripped in _ALLERGY_ALIAS_INDEX:
                return _ALLERGY_ALIAS_INDEX[stripped]
    if q in _ALLERGY_ALIAS_INDEX:
        return _ALLERGY_ALIAS_INDEX[q]
    # Substring fallback (only if alias is contained in the input)
    for alias_lower, key in _ALLERGY_ALIAS_INDEX.items():
        if alias_lower in q and len(alias_lower) >= 5:
            return key
    return None


# ─────────────────────────────────────────────────────────────────
# 2. Map medication_db `group` slug → list of allergy classes
# Used so we don't have to manually tag every medication entry.
# ─────────────────────────────────────────────────────────────────
GROUP_TO_ALLERGY_CLASSES = {
    'antiplatelet':                ['nsaid', 'aspirin'],
    'nsaid':                       ['nsaid'],
    'antibiotic_penicillin':       ['penicillin', 'beta_lactam'],
    'antibiotic_cephalosporin':    ['cephalosporin', 'beta_lactam'],
    'antibiotic_macrolide':        ['macrolide'],
    'antibiotic_sulfonamide':      ['sulfonamide'],
    'opioid':                      ['opioid'],
    'statin':                      ['statin'],
    'ace_inhibitor':               ['ace_inhibitor'],
}


def get_drug_allergy_classes(med_entry):
    """Return all allergy classes a medication belongs to.
    Combines explicit allergy_classes from the entry + classes derived
    from its pharmacological group."""
    if not med_entry:
        return []
    classes = list(med_entry.get('allergy_classes', []) or [])
    group = (med_entry.get('group') or '').lower()
    classes.extend(GROUP_TO_ALLERGY_CLASSES.get(group, []))
    # Dedupe preserving order
    seen = set()
    out = []
    for c in classes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def expand_with_cross_reactivity(allergy_classes):
    """For a set of user allergies, return the FULL set of classes that
    should trigger a warning — including cross-reactive families."""
    expanded = set(allergy_classes)
    for c in list(allergy_classes):
        cat = ALLERGY_CATALOG.get(c, {})
        for cross in cat.get('cross_reactive_with', []):
            expanded.add(cross)
    return expanded


# ─────────────────────────────────────────────────────────────────
# 3. The actual cross-check function
# ─────────────────────────────────────────────────────────────────
def check_allergies_against_meds(user_allergies, user_meds):
    """Find conflicts between a user's allergies and current meds.

    Args:
        user_allergies: list of dicts {substance, severity, notes} OR
                        list of plain strings (raw substance names)
        user_meds:     list of medication name strings

    Returns:
        list of {medication, allergy_class, allergy_label, severity, warning} dicts
    """
    if not user_allergies or not user_meds:
        return []

    # Normalize allergies → set of class keys
    allergy_classes_set = set()
    severity_by_class = {}
    for a in user_allergies:
        if isinstance(a, dict):
            raw = a.get('substance') or a.get('name') or ''
            sev = a.get('severity', 'moderate')
        else:
            raw = str(a)
            sev = 'moderate'
        cls = normalize_allergy(raw)
        if cls:
            allergy_classes_set.add(cls)
            severity_by_class[cls] = sev

    if not allergy_classes_set:
        return []

    # Expand for cross-reactivity
    full_classes = expand_with_cross_reactivity(allergy_classes_set)

    # Resolve each med to its allergy classes
    try:
        from medication_db import lookup
    except ImportError:
        return []

    findings = []
    for med_name in user_meds:
        if not med_name:
            continue
        entry = lookup(med_name)
        if not entry:
            continue
        med_classes = get_drug_allergy_classes(entry)
        for cls in med_classes:
            if cls in full_classes:
                # Determine severity (use original allergy severity if direct,
                # downgrade by 1 step for cross-reactive)
                is_direct = cls in allergy_classes_set
                base_sev = severity_by_class.get(cls, 'moderate')
                if not is_direct:
                    base_sev = {'severe': 'moderate', 'moderate': 'mild',
                                'mild': 'mild'}.get(base_sev, 'moderate')
                cat = ALLERGY_CATALOG.get(cls, {})
                findings.append({
                    'medication': entry['name'],
                    'allergy_class': cls,
                    'allergy_label': cat.get('label', cls),
                    'severity': base_sev,
                    'cross_reactive': not is_direct,
                    'warning': (
                        f"Lék {entry['name']} obsahuje {cat.get('label', cls)}"
                        + ('; uvedl/a jste alergii na tuto skupinu' if is_direct
                           else f' — křížová reakce s vaší alergií na příbuznou skupinu')
                        + '. Konzultujte s lékařem před užitím.'
                    ),
                })
                break  # one warning per med is enough
    return findings


def check_user_allergies(user_id):
    """Convenience: pull allergies + meds from profile and run check."""
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id) or {}
        allergies = profile.get('allergies') or []
        meds = profile.get('medications_list') or []
        return check_allergies_against_meds(allergies, meds)
    except Exception as e:
        logger.debug(f"check_user_allergies failed for {user_id}: {e}")
        return []


def db_stats():
    return {
        'total_classes': len(ALLERGY_CATALOG),
        'total_aliases': len(_ALLERGY_ALIAS_INDEX),
        'classes': list(ALLERGY_CATALOG.keys()),
    }
