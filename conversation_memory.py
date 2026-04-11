# ============================================
# 🧠 CONVERSATION MEMORY — Auto-extract facts from chat
# ============================================
# Listens to every chat message and extracts:
# - Senior's name ("Jmenuji se Marie")
# - Medications ("Beru warfarin a metformin")
# - Family ("Dcera se jmenuje Jana")
# - Interests ("Rád zahradničím")
# - Health ("Špatně spím", "Bolí mě kolena")
#
# Saves to memory_profiles automatically.
# ============================================

import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def extract_and_save(user_id: str, message: str, ai_response: str = ''):
    """Extract facts from user message and save to profile.

    Called after every chat response. Non-blocking, fire-and-forget.
    """
    if not user_id or not message:
        return

    lower = message.lower().strip()
    updates = {}

    # 1. NAME — "Jmenuji se Marie", "Já jsem Karel", "Říkejte mi Pepa"
    name_match = re.search(
        r'(?:jmenuj[ui] se|jsem|říkejte mi|říkej mi|moje jméno je|volám se)\s+([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+)',
        message, re.IGNORECASE
    )
    if name_match:
        updates['name'] = name_match.group(1)
        logger.info(f"🧠 Memory: learned name '{updates['name']}' for {user_id}")

    # 2. MEDICATIONS — "Beru warfarin", "Moje léky jsou...", "Užívám metformin"
    med_patterns = [
        r'(?:beru|užívám|mám předepsaný|předepsal mi|dávám si)\s+(.+?)(?:\.|,|$)',
        r'(?:léky|prášky|tablety)(?:\s+jsou)?\s*:?\s*(.+?)(?:\.|$)',
    ]
    for pattern in med_patterns:
        med_match = re.search(pattern, lower)
        if med_match:
            meds_text = med_match.group(1).strip()
            # Split by "a", ","
            meds = [m.strip() for m in re.split(r'\s*[,a]\s*', meds_text) if len(m.strip()) > 2]
            if meds:
                updates['medications_found'] = meds
                logger.info(f"🧠 Memory: learned meds {meds} for {user_id}")
                break

    # 3. FAMILY — "Dcera se jmenuje Jana", "Můj syn Karel", "Manželka Marie"
    family_patterns = [
        (r'(?:dcera|dcerka)\s+(?:se jmenuje\s+)?(\w+)', 'dcera'),
        (r'(?:syn|synek)\s+(?:se jmenuje\s+)?(\w+)', 'syn'),
        (r'(?:manžel|muž)\s+(?:se jmenuje\s+)?(\w+)', 'manžel'),
        (r'(?:manželka|žena)\s+(?:se jmenuje\s+)?(\w+)', 'manželka'),
        (r'(?:vnuk|vnouček)\s+(?:se jmenuje\s+)?(\w+)', 'vnuk'),
        (r'(?:vnučka)\s+(?:se jmenuje\s+)?(\w+)', 'vnučka'),
        (r'(?:bratr)\s+(?:se jmenuje\s+)?(\w+)', 'bratr'),
        (r'(?:sestra)\s+(?:se jmenuje\s+)?(\w+)', 'sestra'),
    ]
    for pattern, role in family_patterns:
        fm = re.search(pattern, message, re.IGNORECASE)
        if fm:
            name = fm.group(1)
            if name[0].isupper() and len(name) > 2:
                updates.setdefault('family_members', []).append({'role': role, 'name': name})
                logger.info(f"🧠 Memory: learned family {role}={name} for {user_id}")

    # 4. INTERESTS — "Rád zahradničím", "Mám rád hudbu", "Zajímá mě historie"
    interest_patterns = [
        r'(?:rád|ráda|mám rád|mám ráda|zajímá mě|baví mě|miluju|miluji)\s+(.+?)(?:\.|,|$)',
    ]
    for pattern in interest_patterns:
        im = re.search(pattern, lower)
        if im:
            interest = im.group(1).strip()
            if len(interest) > 2 and len(interest) < 50:
                updates.setdefault('interests_found', []).append(interest)

    # 5. HEALTH CONCERNS — "Špatně spím", "Bolí mě kolena", "Mám cukrovku"
    health_patterns = [
        (r'(?:špatně spím|nespím|probouzím se)', 'sleep_issues'),
        (r'(?:bolí mě|bolest)\s+(\w+)', 'pain'),
        (r'(?:mám|trpím)\s+(cukrovk|diabet|tlak|astma|artróz)', 'condition'),
        (r'(?:sluch|neslyším|špatně slyším)', 'hearing_issue'),
        (r'(?:nevidím|špatně vidím|brýle)', 'vision_issue'),
    ]
    for pattern, concern_type in health_patterns:
        hm = re.search(pattern, lower)
        if hm:
            updates.setdefault('health_concerns', []).append(concern_type)

    # Save updates to profile
    if updates:
        _save_updates(user_id, updates)


def _save_updates(user_id: str, updates: dict):
    """Save extracted facts to memory_profiles."""
    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(user_id) or {}

        if 'name' in updates:
            profile['name'] = updates['name']

        if 'medications_found' in updates:
            existing = profile.get('medications_list', [])
            for med in updates['medications_found']:
                if med not in existing:
                    existing.append(med)
            profile['medications_list'] = existing

        if 'family_members' in updates:
            existing = profile.get('family', [])
            for member in updates['family_members']:
                # Don't duplicate
                if not any(f.get('name') == member['name'] for f in existing):
                    existing.append(member)
            profile['family'] = existing

        if 'interests_found' in updates:
            existing = profile.get('interests', [])
            for interest in updates['interests_found']:
                if interest not in existing:
                    existing.append(interest)
            profile['interests'] = existing[:10]  # Max 10

        if 'health_concerns' in updates:
            existing = profile.get('health_concerns', [])
            for concern in updates['health_concerns']:
                if concern not in existing:
                    existing.append(concern)
            profile['health_concerns'] = existing

        # Hearing/vision detection
        if 'hearing_issue' in updates.get('health_concerns', []):
            profile['hearing'] = 'impaired'
        if 'vision_issue' in updates.get('health_concerns', []):
            profile['vision'] = 'impaired'

        profile['last_memory_update'] = datetime.utcnow().isoformat()
        db_save_profile(user_id, profile)
        logger.info(f"🧠 Memory updated for {user_id}: {list(updates.keys())}")

    except Exception as e:
        logger.debug(f"Memory save error (non-fatal): {e}")


logger.info("🧠 Conversation Memory loaded — auto-extracts name, meds, family, interests, health from chat")
