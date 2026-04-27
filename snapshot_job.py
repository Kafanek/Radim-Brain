# -*- coding: utf-8 -*-
"""
📸 Sprint AT — Weekly settings snapshot job

Pro každého aktivního seniora vytvoří snapshot nastavení 1× týdně.
Drží jen poslední 4 snapshoty (FIFO). Důvod: senior si změní theme nebo
hlas, po týdnu zjistí že to nesedí, ale nepamatuje si, co měl předtím.
"Předchozí já" mu vrátí stav z minulého týdne.

Co se snapshotuje:
  - appearance, voice_pref, accessibility, privacy
  - quiet_hours, radim_mode, simplified_ui, language

Co se NEsnapshotuje (záměrně):
  - jméno, telefon (identity)
  - léky, kontakty rodiny (zdravotní data)
  - paměť Radima, conversation history
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SNAPSHOT_KEYS = [
    'appearance', 'voice_pref', 'accessibility', 'privacy',
    'quiet_hours', 'radim_mode', 'simplified_ui', 'language',
]


def run_weekly_snapshots():
    """Find all users with profiles and snapshot their settings.

    Idempotent — if user already has a snapshot from THIS week, skip.
    """
    try:
        from database import db_context
        from memory_helpers import db_load_profile, db_save_profile

        with db_context() as db:
            try:
                rows = db.execute(
                    "SELECT user_id FROM memory_profiles"
                ).fetchall()
            except Exception:
                rows = []

        snapshotted = 0
        skipped = 0

        for r in (rows or []):
            try:
                uid = r.get('user_id') if hasattr(r, 'get') else r[0]
                profile = db_load_profile(uid) or {}

                # Idempotency — skip if a weekly snapshot exists from
                # the past 6 days
                snapshots = profile.get('settings_snapshots') or []
                now = datetime.utcnow()
                already_this_week = False
                for s in snapshots:
                    if s.get('reason') != 'weekly':
                        continue
                    try:
                        ca = datetime.fromisoformat(s.get('created_at', '').replace('Z', ''))
                        if (now - ca).days < 6:
                            already_this_week = True
                            break
                    except Exception:
                        pass
                if already_this_week:
                    skipped += 1
                    continue

                # Gather settings to snapshot
                snap_settings = {k: profile.get(k) for k in SNAPSHOT_KEYS if k in profile}
                if not snap_settings:
                    skipped += 1
                    continue

                new_id = max([s.get('id', 0) for s in snapshots], default=0) + 1
                snap = {
                    'id': new_id,
                    'created_at': now.isoformat(),
                    'reason': 'weekly',
                    'label': f'Týdenní záloha {now.strftime("%d.%m.%Y")}',
                    'settings': snap_settings,
                }
                snapshots.append(snap)
                profile['settings_snapshots'] = snapshots[-4:]
                profile['updated_at'] = now.isoformat()
                db_save_profile(uid, profile)
                snapshotted += 1
                logger.debug(f"📸 weekly snapshot for user={uid} (id={new_id})")
            except Exception as e:
                logger.debug(f"snapshot for user failed (non-fatal): {e}")

        logger.info(f"📸 Weekly snapshots: {snapshotted} created, {skipped} skipped")
    except Exception as e:
        logger.warning(f"run_weekly_snapshots failed: {e}")
