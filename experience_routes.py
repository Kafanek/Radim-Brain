"""
🌿 EXPERIENCE ROUTES v1.0 — "Radimův Odkaz" (Má zkušenost)
=============================================================================
Core module of the Kolibri / Radimův Odkaz project.

Philosophy: Confucius meets GDPR.
    孝 (xiào) — respect for elders: Radim asks, never generates wisdom.
    禮 (lǐ)   — ritual: every sharing passes through a 4-step ceremony.
    名 (míng) — right names: senior is "učitel", Radim is "žák", rodina is "rod".

    GDPR-first: 4 senior rights encoded in UI + API:
        🔒 Right to silence (refuse, pause, delete)
        🌿 Right to choose audience (family / research / public)
        💰 Right to value (transparent price, fair share)
        🕊️ Right to forget (72h cooling-off, revocable forever)

Endpoints (senior-facing)
-------------------------
  GET    /api/experience/contributions              — own contributions list
  POST   /api/experience/session/start              — begin a Radim-led session
  POST   /api/experience/session/<id>/append        — append transcript chunk
  POST   /api/experience/session/<id>/finalize      — AI structures final text
  POST   /api/experience/session/<id>/approve       — senior approves & saves
  PUT    /api/experience/contribution/<id>/privacy  — change 🔒 / 🌿 / 🌍
  DELETE /api/experience/contribution/<id>          — soft delete (right to forget)
  GET    /api/experience/offers                     — current buyer offers
  POST   /api/experience/contribution/<id>/accept-offer  — sign contract
  DELETE /api/experience/contract/<id>              — revoke + refund
  GET    /api/experience/earnings                   — balance + history
  GET    /api/experience/prompts?theme=&depth=      — Radim's question library
  GET    /api/experience/inheritance                — legacy config
  PUT    /api/experience/inheritance                — set legacy beneficiary
  GET    /api/experience/summary                    — aggregate for masthead

Endpoints (family / caregiver)
------------------------------
  GET    /api/experience/family/<senior_id>         — read-only archive view

Tables (6)
----------
  experience_contributions  — recorded stories/skills/wisdom
  experience_buyers         — whitelisted institutions
  experience_offers         — open contracts
  experience_contracts      — senior→buyer signed agreements
  experience_earnings       — payout ledger
  experience_inheritance    — legacy beneficiary settings

Economics
---------
  70% senior · 20% platform · 5% Radim fund · 5% society fund
  Rate floor: 50 Kč minimum per contribution type
  Cooling-off: 72 hours on every new contract

Safeguards
----------
  Cognitive capacity brake: if behavior_baseline detects decline,
  new offers are auto-frozen and family is notified.
"""

import base64
import json
import logging
import os
import time
import threading
import hashlib
from collections import defaultdict, deque
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

experience_bp = Blueprint('experience', __name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

MAX_CONTRIBUTIONS_PER_SENIOR = 500
MAX_TRANSCRIPT_LEN = 30000              # ~5000 words, enough for deep stories
MAX_TITLE_LEN = 200
COOLING_OFF_HOURS = 72
SENIOR_REVENUE_SHARE = 0.70
PLATFORM_SHARE = 0.20
RADIM_FUND_SHARE = 0.05
SOCIETY_FUND_SHARE = 0.05
MIN_PRICE_KC = 50                       # economic floor, protects from exploitation

VALID_TYPES = {'story', 'skill', 'wisdom', 'witness', 'data'}
VALID_THEMES = {'family', 'historical', 'skill', 'wisdom', 'witness', 'daily', 'work', 'love', 'place'}
VALID_PRIVACY = {'draft', 'family', 'research', 'public', 'deleted'}
VALID_DEPTHS = {1, 2, 3}

# Rate limiters — ritual-preserving, not performative
RATE_SESSION_START = 20       # max 20 new sessions per hour
RATE_CONTRACT_SIGN = 10
_rate_win = defaultdict(lambda: deque(maxlen=50))
_rate_lock = threading.Lock()


def _rate_ok(user_id, bucket, limit, window_seconds=3600):
    key = f"{user_id}:{bucket}"
    now = time.time()
    cutoff = now - window_seconds
    with _rate_lock:
        q = _rate_win[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA — 6 tables (all idempotent)
# ─────────────────────────────────────────────────────────────────────────────

EXPERIENCE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS experience_contributions (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        theme TEXT DEFAULT 'family',
        depth INTEGER DEFAULT 1,
        transcript TEXT NOT NULL,
        transcript_structured TEXT,
        audio_url TEXT,
        audio_size_bytes INTEGER DEFAULT 0,
        duration_sec INTEGER DEFAULT 0,
        privacy TEXT DEFAULT 'draft',
        approved_at TIMESTAMP,
        cooling_off_until TIMESTAMP,
        word_count INTEGER DEFAULT 0,
        parent_contribution_id INTEGER,
        gallery_photo_id INTEGER,
        gemini_consent BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_contrib_user ON experience_contributions(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_exp_contrib_privacy ON experience_contributions(user_id, privacy);
    CREATE INDEX IF NOT EXISTS idx_exp_contrib_theme ON experience_contributions(theme);
    CREATE INDEX IF NOT EXISTS idx_exp_contrib_parent ON experience_contributions(parent_contribution_id);

    CREATE TABLE IF NOT EXISTS experience_buyers (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        type TEXT DEFAULT 'research',
        description TEXT,
        trust_score INTEGER DEFAULT 80,
        ethics_review_url TEXT,
        gdpr_compliance_url TEXT,
        active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_buyers_active ON experience_buyers(active);

    CREATE TABLE IF NOT EXISTS experience_offers (
        id SERIAL PRIMARY KEY,
        buyer_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        target_theme TEXT,
        target_type TEXT,
        target_depth INTEGER DEFAULT 1,
        price_kc INTEGER NOT NULL,
        royalty_years INTEGER DEFAULT 0,
        royalty_kc_per_year INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        seats_total INTEGER DEFAULT 100,
        seats_filled INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_offers_status ON experience_offers(status, target_theme);

    CREATE TABLE IF NOT EXISTS experience_contracts (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        contribution_id INTEGER NOT NULL,
        offer_id INTEGER NOT NULL,
        buyer_id INTEGER NOT NULL,
        price_kc INTEGER NOT NULL,
        royalty_years INTEGER DEFAULT 0,
        royalty_kc_per_year INTEGER DEFAULT 0,
        anonymized BOOLEAN DEFAULT FALSE,
        cooling_off_until TIMESTAMP,
        signed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        revoked_at TIMESTAMP,
        last_royalty_at TIMESTAMP,
        requires_family_cosign BOOLEAN DEFAULT FALSE,
        cosigned_by TEXT,
        cosigned_at TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_contracts_user ON experience_contracts(user_id, signed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_exp_contracts_contribution ON experience_contracts(contribution_id);
    CREATE INDEX IF NOT EXISTS idx_exp_contracts_royalty ON experience_contracts(last_royalty_at, royalty_years);

    CREATE TABLE IF NOT EXISTS experience_earnings (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        contract_id INTEGER,
        amount_kc INTEGER NOT NULL,
        gross_kc INTEGER,
        source TEXT DEFAULT 'contract',
        payout_method TEXT,
        paid_at TIMESTAMP,
        period_label TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_earnings_user ON experience_earnings(user_id, created_at DESC);

    CREATE TABLE IF NOT EXISTS experience_inheritance (
        user_id TEXT PRIMARY KEY,
        heir_name TEXT,
        heir_relation TEXT,
        heir_contact TEXT,
        heir_contact_verified BOOLEAN DEFAULT FALSE,
        royalty_years_after_death INTEGER DEFAULT 5,
        unlock_family_archive BOOLEAN DEFAULT TRUE,
        unlock_on_events JSONB,
        public_memorial BOOLEAN DEFAULT FALSE,
        configured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS experience_audit_log (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        actor_id TEXT,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id INTEGER,
        detail TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_audit_user ON experience_audit_log(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_exp_audit_action ON experience_audit_log(action, created_at DESC);

    CREATE TABLE IF NOT EXISTS experience_scheduled_messages (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        recipient_name TEXT NOT NULL,
        recipient_relation TEXT,
        recipient_contact TEXT,
        message_type TEXT DEFAULT 'text',
        content TEXT NOT NULL,
        audio_url TEXT,
        release_event TEXT,
        release_date TIMESTAMP,
        status TEXT DEFAULT 'scheduled',
        released_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_scheduled_user ON experience_scheduled_messages(user_id, release_date);
    CREATE INDEX IF NOT EXISTS idx_exp_scheduled_status ON experience_scheduled_messages(status, release_date);
"""


def _migrate_schema_additive():
    """Add new columns to existing installations (idempotent, safe)."""
    extra = [
        # Contributions
        "ALTER TABLE experience_contributions ADD COLUMN IF NOT EXISTS parent_contribution_id INTEGER",
        "ALTER TABLE experience_contributions ADD COLUMN IF NOT EXISTS gallery_photo_id INTEGER",
        "ALTER TABLE experience_contributions ADD COLUMN IF NOT EXISTS gemini_consent BOOLEAN DEFAULT FALSE",
        "ALTER TABLE experience_contributions ADD COLUMN IF NOT EXISTS audio_size_bytes INTEGER DEFAULT 0",
        # Contracts
        "ALTER TABLE experience_contracts ADD COLUMN IF NOT EXISTS requires_family_cosign BOOLEAN DEFAULT FALSE",
        "ALTER TABLE experience_contracts ADD COLUMN IF NOT EXISTS cosigned_by TEXT",
        "ALTER TABLE experience_contracts ADD COLUMN IF NOT EXISTS cosigned_at TIMESTAMP",
        # Inheritance
        "ALTER TABLE experience_inheritance ADD COLUMN IF NOT EXISTS heir_contact_verified BOOLEAN DEFAULT FALSE",
    ]
    for stmt in extra:
        try:
            with db_context(commit=True) as db:
                db.execute(stmt)
        except Exception:
            pass  # SQLite/older PG — silently skip


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in EXPERIENCE_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Experience schema init: {e}")
    if is_postgres():
        _migrate_schema_additive()
    _seed_demo_buyers_if_empty()


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG — GDPR Article 30 compliance
# ─────────────────────────────────────────────────────────────────────────────

def _audit(user_id, action, target_type=None, target_id=None, detail=None, actor_id=None):
    """Record an auditable event. Best-effort — never raises."""
    if not user_id:
        return
    try:
        ip = None
        try:
            if request:
                ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:80]
        except Exception:
            pass
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO experience_audit_log "
                "(user_id, actor_id, action, target_type, target_id, detail, ip_address) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, actor_id or user_id, action, target_type,
                 target_id, (detail or '')[:500], ip)
            )
    except Exception as e:
        logger.debug(f"audit log: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# COGNITIVE CAPACITY BRAKE — Confucius safeguard for vulnerable elders
# ─────────────────────────────────────────────────────────────────────────────

def _check_cognitive_brake(user_id):
    """Return (brake_active, reason) tuple.
    brake_active=True means new contracts should require family co-sign.

    Heuristics (multi-signal, conservative):
      1. Average C over last 14d dropped >25% vs prior 14d
      2. Interaction count dropped >40%
      3. Age >= 85 (if known) — auto-cosign recommendation
    """
    try:
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        with db_context() as db:
            # Mood drop signal
            recent = db.execute(
                "SELECT AVG(C) FROM brain_states "
                "WHERE user_id = ? AND C IS NOT NULL AND created_at >= ?",
                (user_id, now - timedelta(days=14))
            ).fetchone()
            prior = db.execute(
                "SELECT AVG(C) FROM brain_states "
                "WHERE user_id = ? AND C IS NOT NULL "
                "AND created_at >= ? AND created_at < ?",
                (user_id, now - timedelta(days=28), now - timedelta(days=14))
            ).fetchone()

        def v(r):
            if not r:
                return None
            x = r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]
            try:
                return float(x) if x is not None else None
            except Exception:
                return None

        recent_c = v(recent)
        prior_c = v(prior)
        if recent_c is not None and prior_c is not None and prior_c > 0:
            delta = (recent_c - prior_c) / prior_c
            if delta <= -0.25:
                return (True, f'Pokles kognitivní koherence o {int(abs(delta) * 100)}% — doporučeno spolupodepsání rodinou.')
    except Exception as e:
        logger.debug(f"cognitive brake: {e}")
    return (False, None)


# ─────────────────────────────────────────────────────────────────────────────
# DEMO SEEDS — Kafánek starter ecosystem
# ─────────────────────────────────────────────────────────────────────────────

DEMO_BUYERS = [
    {
        'name': 'Karlova univerzita — Ústav pro soudobé dějiny',
        'type': 'university',
        'description': 'Sbírá ústní historii pro akademický výzkum. IRB schváleno.',
        'trust_score': 95,
    },
    {
        'name': 'Národní archiv ČR',
        'type': 'archive',
        'description': 'Zachovává občanskou paměť pro budoucí generace.',
        'trust_score': 98,
    },
    {
        'name': 'Akademie věd — Sociologický ústav',
        'type': 'research',
        'description': 'Výzkum stárnutí a mezigeneračního přenosu.',
        'trust_score': 92,
    },
    {
        'name': 'STEM/MARK — Consumer Insights',
        'type': 'market_research',
        'description': 'Tržní výzkum pro české FMCG značky. Anonymně agregované.',
        'trust_score': 85,
    },
    {
        'name': 'Projekt Wisdom Corpus (AI výzkum)',
        'type': 'ai_lab',
        'description': 'Etický tréninkový korpus pro AI. Data anonymizována + diferenciální soukromí.',
        'trust_score': 88,
    },
]

DEMO_OFFERS = [
    {
        'buyer_name': 'Karlova univerzita — Ústav pro soudobé dějiny',
        'title': 'Ústní historie 1968',
        'description': 'Nahrajte vzpomínku na Pražské jaro — kde jste byla, co jste cítila.',
        'target_theme': 'historical',
        'target_type': 'witness',
        'target_depth': 2,
        'price_kc': 1500,
        'royalty_years': 5,
        'royalty_kc_per_year': 300,
    },
    {
        'buyer_name': 'Národní archiv ČR',
        'title': 'Česká rodinná kuchyně před 1989',
        'description': 'Recepty a zvyky, které už mladí neznají. Video + text.',
        'target_theme': 'skill',
        'target_type': 'skill',
        'target_depth': 1,
        'price_kc': 800,
        'royalty_years': 10,
        'royalty_kc_per_year': 150,
    },
    {
        'buyer_name': 'Akademie věd — Sociologický ústav',
        'title': 'Dlouhé manželství — co funguje',
        'description': 'Rady pro mladé páry z vaší zkušenosti. Zcela anonymní.',
        'target_theme': 'wisdom',
        'target_type': 'wisdom',
        'target_depth': 2,
        'price_kc': 1200,
        'royalty_years': 3,
        'royalty_kc_per_year': 200,
    },
    {
        'buyer_name': 'Projekt Wisdom Corpus (AI výzkum)',
        'title': 'Moudrost pro trénink AI — měsíční příspěvek',
        'description': 'Jedna hluboká vzpomínka měsíčně. AI se učí od vás, jak hovořit s důstojností.',
        'target_theme': 'wisdom',
        'target_type': 'wisdom',
        'target_depth': 3,
        'price_kc': 600,
        'royalty_years': 0,
        'royalty_kc_per_year': 0,
    },
    {
        'buyer_name': 'STEM/MARK — Consumer Insights',
        'title': 'Spotřebitelské zvyky důchodců',
        'description': 'Stručný popis toho, co kupujete, jak volíte, co vás irituje. Plně anonymní.',
        'target_theme': 'daily',
        'target_type': 'data',
        'target_depth': 1,
        'price_kc': 400,
        'royalty_years': 6,
        'royalty_kc_per_year': 100,
    },
]


def _seed_demo_buyers_if_empty():
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM experience_buyers"
            ).fetchone()
        existing = int((row[0] if isinstance(row, (list, tuple)) else list(row.values())[0]) or 0) if row else 0
    except Exception:
        return
    if existing > 0:
        return

    # Seed buyers
    buyer_id_map = {}
    try:
        with db_context(commit=True) as db:
            for b in DEMO_BUYERS:
                if is_postgres():
                    r = db.execute(
                        "INSERT INTO experience_buyers (name, type, description, trust_score) "
                        "VALUES (?, ?, ?, ?) RETURNING id",
                        (b['name'], b['type'], b['description'], b['trust_score'])
                    ).fetchone()
                    bid = r[0] if isinstance(r, (list, tuple)) else r.get('id')
                else:
                    cur = db.execute(
                        "INSERT INTO experience_buyers (name, type, description, trust_score) "
                        "VALUES (?, ?, ?, ?)",
                        (b['name'], b['type'], b['description'], b['trust_score'])
                    )
                    bid = cur.lastrowid if hasattr(cur, 'lastrowid') else None
                buyer_id_map[b['name']] = bid
    except Exception as e:
        logger.debug(f"seed buyers: {e}")
        return

    # Seed offers
    try:
        with db_context(commit=True) as db:
            for o in DEMO_OFFERS:
                bid = buyer_id_map.get(o['buyer_name'])
                if not bid:
                    continue
                db.execute(
                    "INSERT INTO experience_offers "
                    "(buyer_id, title, description, target_theme, target_type, "
                    "target_depth, price_kc, royalty_years, royalty_kc_per_year, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (bid, o['title'], o['description'], o['target_theme'],
                     o['target_type'], o['target_depth'], o['price_kc'],
                     o['royalty_years'], o['royalty_kc_per_year'], 'active')
                )
    except Exception as e:
        logger.debug(f"seed offers: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# RADIM'S PROMPT LIBRARY — Confucian question structure
# 5 themes × 3 depths = 15 categories, 50+ prompts
# ─────────────────────────────────────────────────────────────────────────────

RADIM_PROMPTS = {
    'family': {
        1: [
            'Kdo z rodiny vám nejvíc pomáhal, když jste byla malá?',
            'Jak se u vás doma slavily Vánoce?',
            'Jaké jídlo připravovala vaše maminka nejraději?',
            'Vzpomenete si na první domov, kde jste žila?',
            'Jaké dobré rady vám dala vaše babička?',
        ],
        2: [
            'Co vám řekla maminka, co si pamatujete dodnes?',
            'Jaké to bylo poprvé držet vlastní dítě?',
            'Kdy vás rodina nejvíc potěšila?',
            'Jaký byl váš otec — jak si ho pamatujete?',
            'Co jste se naučila od své matky, co říkáte i svým dětem?',
        ],
        3: [
            'Čeho v rodině nejvíc litujete?',
            'Co byste chtěla, aby o vás vnoučata věděla?',
            'Komu z rodiny jste neřekla něco důležitého?',
            'Co ve vaší rodině bylo tabu, o čem se mlčelo?',
            'Pokud byste mohla napsat dopis mladé sobě — co by v něm bylo?',
        ],
    },
    'historical': {
        1: [
            'Vzpomínáte si na rok 1968?',
            'Kde jste byla 17. listopadu 1989?',
            'Jaké byly 90. léta pro vás?',
            'Pamatujete si, jak se žilo za socialismu?',
        ],
        2: [
            'Jaká byla vaše vesnice/město, když vy jste byla malá?',
            'Co jste slyšela z rádia nebo viděla v televizi v důležité chvíle?',
            'Kdo v rodině byl politicky aktivní, a jak to ovlivnilo vás?',
            'Jaký byl první obchod, kde jste nakupovala jako dospělá?',
        ],
        3: [
            'Jaké jste měla strachy v 70. letech?',
            'Jak jste prožívala rozdělení Československa?',
            'Co z minulého režimu vám nejvíc chybí, a co naopak vůbec?',
            'Jaký moment v historii vás osobně nejvíc změnil?',
        ],
    },
    'skill': {
        1: [
            'Jaký recept jste dělala nejčastěji?',
            'Co umíte, co se z mladé generace vytrácí?',
            'Jaké řemeslo jste se naučila od rodičů?',
            'Co se vám podařilo nejlépe vypěstovat na zahradě?',
        ],
        2: [
            'Jak jste naučila své děti hospodařit?',
            'Jaký je nejlepší tip, který máte pro opravu věcí?',
            'Kterou vaši techniku (v kuchyni, domácnosti) nikdo jiný neumí?',
            'Co jste zdědila po matce, co předáváte dál?',
        ],
        3: [
            'Jaká dovednost vám přinesla nejvíc pokory?',
            'Co jste se naučila opravdu pozdě, a proč škoda, že ne dříve?',
            'Jaké řemeslo nebo znalost podle vás naprosto vymizí, když zemře vaše generace?',
        ],
    },
    'wisdom': {
        1: [
            'Co byste si sama poradila, kdyby vám bylo 20?',
            'Jakou radu jste dostala a dodnes ji používáte?',
            'Co je podle vás nejdůležitější v životě?',
            'Jakou chybu nikomu nepřejete?',
        ],
        2: [
            'Jak jste překonala nejtěžší období svého života?',
            'Co vám pomohlo smířit se se ztrátou?',
            'Jaká rada pro dlouhodobé manželství skutečně funguje?',
            'Jak se naučit být spokojená, i když není všechno v pořádku?',
        ],
        3: [
            'Co je pravda, i když to zní banálně?',
            'Co byste chtěla vědět, než půjdete z tohoto světa?',
            'Co vám teď, po všech letech, přijde směšné, že jste kdy řešila?',
            'Pokud byste mohla říct jednu větu všem mladým lidem — jakou?',
        ],
    },
    'witness': {
        1: [
            'Kdo ze slavných osobností vás ovlivnil?',
            'Čemu jste byla svědkem, co by mělo zůstat zapsané?',
            'Jaké místo znáte tak, jak už ho nikdo neuvidí?',
            'Kdo ve vašem okolí byl výjimečný, a dnes se na něj zapomíná?',
        ],
        2: [
            'Jak se změnila vaše vesnice/čtvrť/město za váš život?',
            'Pamatujete si den, který změnil váš život?',
            'Co už nikdo nezažije, co vy jste zažila?',
        ],
        3: [
            'Co z té doby, kdy jste byla mladá, by mělo zůstat jako varování?',
            'Pokud jste někoho obdivovala, a potom se zklamala — co se stalo?',
            'Je něco, co jste viděla, a co byste raději zapomněla?',
        ],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in ('1', 'true', 'yes', 'on')
    return False


def _contrib_row(r):
    def v(i, k):
        if isinstance(r, (list, tuple)):
            try:
                return r[i]
            except IndexError:
                return None
        return r.get(k) if hasattr(r, 'get') else None
    return {
        'id': v(0, 'id'),
        'type': v(1, 'type'),
        'title': v(2, 'title'),
        'theme': v(3, 'theme'),
        'depth': v(4, 'depth'),
        'transcript': v(5, 'transcript'),
        'transcriptStructured': v(6, 'transcript_structured'),
        'durationSec': v(7, 'duration_sec') or 0,
        'privacy': v(8, 'privacy') or 'draft',
        'approvedAt': str(v(9, 'approved_at') or ''),
        'coolingOffUntil': str(v(10, 'cooling_off_until') or ''),
        'wordCount': v(11, 'word_count') or 0,
        'createdAt': str(v(12, 'created_at') or ''),
    }


_SELECT_CONTRIB = (
    "id, type, title, theme, depth, transcript, transcript_structured, "
    "duration_sec, privacy, approved_at, cooling_off_until, word_count, created_at"
)


def _word_count(text):
    if not text:
        return 0
    return len(text.split())


def _calc_senior_net(gross_kc):
    """Return integer Kč that goes to senior after fair revenue share."""
    return int(round(float(gross_kc) * SENIOR_REVENUE_SHARE))


def _count_active_contributions(user_id):
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM experience_contributions "
                "WHERE user_id = ? AND privacy <> ?",
                (user_id, 'deleted')
            ).fetchone()
        return int((row[0] if isinstance(row, (list, tuple)) else list(row.values())[0]) or 0) if row else 0
    except Exception:
        return 0


def _is_family_of(senior_id, family_uid):
    if senior_id == family_uid:
        return True
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_user_id = ? "
                "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (senior_id, family_uid)
            ).fetchone()
        return bool(r)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — LIST + SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/contributions', methods=['GET', 'OPTIONS'])
@require_auth
def list_contributions():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                f"SELECT {_SELECT_CONTRIB} FROM experience_contributions "
                "WHERE user_id = ? AND privacy <> ? "
                "ORDER BY created_at DESC LIMIT 200",
                (uid, 'deleted')
            ).fetchall()
    except Exception as e:
        logger.error(f"list contributions: {e}")
        return jsonify({'success': True, 'contributions': [], 'count': 0})

    contribs = [_contrib_row(r) for r in rows or []]
    return jsonify({
        'success': True,
        'contributions': contribs,
        'count': len(contribs),
        'limit': MAX_CONTRIBUTIONS_PER_SENIOR,
    })


@experience_bp.route('/api/experience/summary', methods=['GET', 'OPTIONS'])
@require_auth
def summary():
    """Aggregate for Kafánek masthead — this-month, all-time, active contracts."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    this_month_kc = 0
    all_time_kc = 0
    active_contracts = 0
    contributions_count = 0

    try:
        with db_context() as db:
            # This month earnings
            month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            r1 = db.execute(
                "SELECT COALESCE(SUM(amount_kc), 0) FROM experience_earnings "
                "WHERE user_id = ? AND created_at >= ?",
                (uid, month_start)
            ).fetchone()
            if r1:
                this_month_kc = int((r1[0] if isinstance(r1, (list, tuple)) else list(r1.values())[0]) or 0)

            # All time earnings
            r2 = db.execute(
                "SELECT COALESCE(SUM(amount_kc), 0) FROM experience_earnings "
                "WHERE user_id = ?",
                (uid,)
            ).fetchone()
            if r2:
                all_time_kc = int((r2[0] if isinstance(r2, (list, tuple)) else list(r2.values())[0]) or 0)

            # Active contracts
            r3 = db.execute(
                "SELECT COUNT(*) FROM experience_contracts "
                "WHERE user_id = ? AND revoked_at IS NULL",
                (uid,)
            ).fetchone()
            if r3:
                active_contracts = int((r3[0] if isinstance(r3, (list, tuple)) else list(r3.values())[0]) or 0)

            # Contributions
            r4 = db.execute(
                "SELECT COUNT(*) FROM experience_contributions "
                "WHERE user_id = ? AND privacy NOT IN (?, ?)",
                (uid, 'deleted', 'draft')
            ).fetchone()
            if r4:
                contributions_count = int((r4[0] if isinstance(r4, (list, tuple)) else list(r4.values())[0]) or 0)
    except Exception as e:
        logger.debug(f"summary: {e}")

    return jsonify({
        'success': True,
        'thisMonthKc': this_month_kc,
        'allTimeKc': all_time_kc,
        'activeContracts': active_contracts,
        'contributionsCount': contributions_count,
        'revenueShare': {
            'senior': int(SENIOR_REVENUE_SHARE * 100),
            'platform': int(PLATFORM_SHARE * 100),
            'radimFund': int(RADIM_FUND_SHARE * 100),
            'societyFund': int(SOCIETY_FUND_SHARE * 100),
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# SESSION LIFECYCLE — start → append → finalize → approve
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/session/start', methods=['POST', 'OPTIONS'])
@require_auth
def session_start():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _rate_ok(uid, 'session_start', RATE_SESSION_START):
        return jsonify({'success': False, 'error': 'Moc rychle. Zkuste to později.',
                        'code': 'rate_limit'}), 429
    if _count_active_contributions(uid) >= MAX_CONTRIBUTIONS_PER_SENIOR:
        return jsonify({'success': False,
                        'error': f'Máte už {MAX_CONTRIBUTIONS_PER_SENIOR} vzpomínek. Smažte některou starou.',
                        'code': 'quota'}), 413

    data = request.get_json() or {}
    ctype = (data.get('type') or 'story').strip().lower()
    theme = (data.get('theme') or 'family').strip().lower()
    depth = int(data.get('depth') or 1)
    title = (data.get('title') or 'Nová vzpomínka')[:MAX_TITLE_LEN]

    if ctype not in VALID_TYPES:
        return jsonify({'success': False, 'error': 'neplatný typ'}), 400
    if theme not in VALID_THEMES:
        theme = 'family'
    if depth not in VALID_DEPTHS:
        depth = 1

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                r = db.execute(
                    "INSERT INTO experience_contributions "
                    "(user_id, type, title, theme, depth, transcript, privacy) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, ctype, title, theme, depth, '', 'draft')
                ).fetchone()
                new_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO experience_contributions "
                    "(user_id, type, title, theme, depth, transcript, privacy) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, ctype, title, theme, depth, '', 'draft')
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"session start: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({
        'success': True,
        'sessionId': new_id,
        'type': ctype,
        'theme': theme,
        'depth': depth,
        'title': title,
        'prompts': RADIM_PROMPTS.get(theme, {}).get(depth, []),
    })


@experience_bp.route('/api/experience/session/<int:session_id>/append', methods=['POST'])
@require_auth
def session_append(session_id):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    chunk = (data.get('text') or '').strip()
    if not chunk:
        return jsonify({'success': False, 'error': 'Prázdný text.'}), 400

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT transcript, privacy FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
                (session_id, uid)
            ).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'not found'}), 404
        existing = row[0] if isinstance(row, (list, tuple)) else row.get('transcript')
        privacy = row[1] if isinstance(row, (list, tuple)) else row.get('privacy')
        if privacy != 'draft':
            return jsonify({'success': False,
                            'error': 'Vzpomínka už byla schválena. Nelze ji měnit — můžete ji smazat.',
                            'code': 'approved'}), 409
    except Exception as e:
        logger.error(f"append read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    new_transcript = ((existing or '') + ('\n' if existing else '') + chunk)[:MAX_TRANSCRIPT_LEN]
    wc = _word_count(new_transcript)

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions "
                "SET transcript = ?, word_count = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (new_transcript, wc, session_id, uid)
            )
    except Exception as e:
        logger.error(f"append write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({
        'success': True,
        'sessionId': session_id,
        'wordCount': wc,
        'transcriptLen': len(new_transcript),
    })


@experience_bp.route('/api/experience/session/<int:session_id>/finalize', methods=['POST'])
@require_auth
def session_finalize(session_id):
    """Optional AI-structure step. Uses Gemini to produce a cleaner
    structured version — BUT:

    - Only works on DRAFT contributions (approved ones are immutable)
    - Requires explicit per-session Gemini consent (stored on contribution)
    - Rate limited per user to prevent quota abuse
    - Original transcript is ALWAYS preserved; structured is opt-in via approval

    Request body: {allowAi: bool} — if true and not previously consented,
    records consent AND sends to Gemini. If false or missing, returns
    original transcript unchanged.
    """
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _rate_ok(uid, 'finalize', 30):
        return jsonify({'success': False, 'error': 'Moc rychle.',
                        'code': 'rate_limit'}), 429

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT transcript, title, type, theme, privacy, gemini_consent "
                "FROM experience_contributions WHERE id = ? AND user_id = ?",
                (session_id, uid)
            ).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'not found'}), 404
    except Exception as e:
        logger.error(f"finalize read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    def v(i, k):
        return row[i] if isinstance(row, (list, tuple)) else row.get(k)
    transcript = (v(0, 'transcript') or '').strip()
    privacy = v(4, 'privacy')
    existing_consent = bool(v(5, 'gemini_consent'))

    # Guard 1: only drafts can be finalized
    if privacy != 'draft':
        return jsonify({
            'success': False,
            'error': 'Vzpomínka už byla schválena. Nelze ji znovu upravovat.',
            'code': 'not_draft',
        }), 409

    if not transcript or len(transcript) < 50:
        return jsonify({'success': False, 'error': 'Text je příliš krátký.'}), 400

    # Guard 2: explicit per-session AI consent
    data = request.get_json(silent=True) or {}
    allow_ai = _to_bool(data.get('allowAi'))

    if not allow_ai and not existing_consent:
        # Return original transcript as-is; no Google call
        _audit(uid, 'finalize_local_only', 'contribution', session_id,
               'senior declined AI structure')
        return jsonify({
            'success': True,
            'sessionId': session_id,
            'structured': transcript,
            'aiGenerated': False,
            'reason': 'ai_not_consented',
            'note': 'Vzpomínku jsem nechal beze změny — AI souhlas nebyl udělen.',
        })

    # Record consent (persist for audit)
    if allow_ai and not existing_consent:
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "UPDATE experience_contributions SET gemini_consent = ? "
                    "WHERE id = ? AND user_id = ?",
                    (True if is_postgres() else 1, session_id, uid)
                )
        except Exception:
            pass
        _audit(uid, 'gemini_consent_granted', 'contribution', session_id)

    # AI structure via Gemini (best-effort, honest fallback)
    structured = _structure_via_gemini(transcript, v(1, 'title'), v(3, 'theme'))
    ai_used = bool(structured)
    if not structured:
        structured = transcript

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions "
                "SET transcript_structured = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (structured, session_id, uid)
            )
    except Exception as e:
        logger.debug(f"finalize write: {e}")

    _audit(uid, 'finalized', 'contribution', session_id,
           f'ai_used={ai_used}')

    return jsonify({
        'success': True,
        'sessionId': session_id,
        'structured': structured,
        'aiGenerated': ai_used,
    })


def _structure_via_gemini(transcript, title, theme):
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        prompt = (
            "Jsi Radim, pomocník seniora při zaznamenávání vzpomínky. "
            "Dostaneš přepis rozhovoru v češtině. Tvůj úkol:\n\n"
            "1. Zachovej přesně, CO senior řekl. Neměň fakta, jména, čísla.\n"
            "2. Zlepši strukturu: odstav odstavce, vynech 'éé', duplicity.\n"
            "3. Nepřidávej nic vlastního. Nic neinterpretuj.\n"
            "4. Zachovej citové zabarvení a jazyk seniora.\n"
            "5. Maximálně 500 slov.\n\n"
            f"Téma: {theme}\nNadpis: {title}\n\n"
            f"Přepis:\n{transcript}\n\n"
            "Upravený přepis (bez jakéhokoliv úvodu nebo vysvětlení):"
        )
        resp = model.generate_content(prompt, generation_config={
            'temperature': 0.2, 'max_output_tokens': 1500,
        })
        if resp and getattr(resp, 'text', None):
            return resp.text.strip()[:MAX_TRANSCRIPT_LEN]
    except Exception as e:
        logger.debug(f"structure gemini: {e}")
    return None


@experience_bp.route('/api/experience/session/<int:session_id>/approve', methods=['POST'])
@require_auth
def session_approve(session_id):
    """Senior approves the contribution, sets privacy, and the 72h cooling-off
    window begins. The contribution becomes visible/shareable per chosen privacy."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    privacy = (data.get('privacy') or 'family').strip().lower()
    use_structured = _to_bool(data.get('useStructured'))
    if privacy not in {'family', 'research', 'public'}:
        return jsonify({'success': False, 'error': 'Vyberte sdílení.'}), 400

    cooling_off_until = datetime.utcnow() + timedelta(hours=COOLING_OFF_HOURS)

    try:
        with db_context(commit=True) as db:
            # Fetch current to decide which transcript to promote
            row = db.execute(
                "SELECT transcript, transcript_structured FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
                (session_id, uid)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'not found'}), 404
            raw = row[0] if isinstance(row, (list, tuple)) else row.get('transcript')
            structured = row[1] if isinstance(row, (list, tuple)) else row.get('transcript_structured')
            final_text = (structured if use_structured and structured else raw) or ''
            if len(final_text.strip()) < 20:
                return jsonify({'success': False,
                                'error': 'Vzpomínka je příliš krátká pro uložení.'}), 400

            db.execute(
                "UPDATE experience_contributions "
                "SET privacy = ?, approved_at = CURRENT_TIMESTAMP, "
                "cooling_off_until = ?, transcript = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (privacy, cooling_off_until, final_text, session_id, uid)
            )
    except Exception as e:
        logger.error(f"approve: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({
        'success': True,
        'sessionId': session_id,
        'privacy': privacy,
        'coolingOffUntil': cooling_off_until.isoformat(),
        'message': 'Vzpomínka uložena. Máte 72 hodin na rozmyšlenou — kdykoli můžete změnit.',
    })


# ─────────────────────────────────────────────────────────────────────────────
# PRIVACY MANAGEMENT + RIGHT TO FORGET
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/contribution/<int:cid>/privacy', methods=['PUT'])
@require_auth
def change_privacy(cid):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _rate_ok(uid, 'privacy_change', 30):
        return jsonify({'success': False, 'code': 'rate_limit',
                        'error': 'Moc rychle. Zkuste to za chvilku.'}), 429
    data = request.get_json() or {}
    new_privacy = (data.get('privacy') or '').strip().lower()
    if new_privacy not in {'family', 'research', 'public'}:
        return jsonify({'success': False, 'error': 'Neplatná volba.'}), 400

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions "
                "SET privacy = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (new_privacy, cid, uid)
            )
    except Exception as e:
        logger.error(f"privacy: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'privacy_changed', 'contribution', cid, f'new={new_privacy}')
    return jsonify({'success': True, 'id': cid, 'privacy': new_privacy})


@experience_bp.route('/api/experience/contribution/<int:cid>', methods=['DELETE'])
@require_auth
def forget_contribution(cid):
    """Right to forget — soft delete + revoke all contracts."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _rate_ok(uid, 'forget', 30):
        return jsonify({'success': False, 'code': 'rate_limit',
                        'error': 'Moc rychle. Zkuste to za chvilku.'}), 429

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contracts SET revoked_at = CURRENT_TIMESTAMP "
                "WHERE contribution_id = ? AND user_id = ? AND revoked_at IS NULL",
                (cid, uid)
            )
            db.execute(
                "UPDATE experience_contributions "
                "SET privacy = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                ('deleted', cid, uid)
            )
    except Exception as e:
        logger.error(f"forget: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'forgotten', 'contribution', cid)
    return jsonify({'success': True, 'id': cid, 'deleted': True,
                    'message': 'Vzpomínka byla zapomenuta. Ctím vaše právo.'})


@experience_bp.route('/api/experience/session/<int:session_id>/replace', methods=['POST'])
@require_auth
def session_replace(session_id):
    """Replace the whole transcript (authoritative save from frontend).
    Used by frontend draft auto-save — avoids append/dedup desync bugs."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    new_transcript = (data.get('text') or '').strip()

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT privacy FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
                (session_id, uid)
            ).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'not found'}), 404
        privacy = row[0] if isinstance(row, (list, tuple)) else row.get('privacy')
        if privacy != 'draft':
            return jsonify({'success': False, 'code': 'approved',
                            'error': 'Vzpomínka už byla schválena.'}), 409
    except Exception as e:
        logger.error(f"replace read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    new_transcript = new_transcript[:MAX_TRANSCRIPT_LEN]
    wc = _word_count(new_transcript)
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions "
                "SET transcript = ?, word_count = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (new_transcript, wc, session_id, uid)
            )
    except Exception as e:
        logger.error(f"replace write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({
        'success': True,
        'sessionId': session_id,
        'wordCount': wc,
        'transcriptLen': len(new_transcript),
    })


@experience_bp.route('/api/experience/session/<int:session_id>/audio', methods=['POST'])
@require_auth
def upload_audio(session_id):
    """Upload audio recording for a draft contribution.
    Accepts multipart 'audio' file OR JSON { dataUrl: 'data:audio/...;base64,...' }.
    Stored as data URL (or CDN if available) — mirrors gallery pattern.
    Max 25 MB / 15 min audio."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Ownership + state check
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT privacy FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
                (session_id, uid)
            ).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'not found'}), 404
        privacy = row[0] if isinstance(row, (list, tuple)) else row.get('privacy')
        if privacy != 'draft':
            return jsonify({'success': False, 'error': 'Nelze nahrát audio do schválené vzpomínky.'}), 409
    except Exception as e:
        logger.error(f"audio read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    MAX_AUDIO_BYTES = 25 * 1024 * 1024
    ALLOWED_AUDIO = {'audio/webm', 'audio/ogg', 'audio/mpeg', 'audio/mp4', 'audio/wav'}

    file_storage = request.files.get('audio')
    url = None
    size = 0
    duration = 0
    if file_storage is not None:
        mime = (file_storage.mimetype or '').lower()
        if mime not in ALLOWED_AUDIO:
            return jsonify({'success': False, 'error': 'Nepodporovaný formát audio.'}), 415
        content = file_storage.read()
        size = len(content)
        if size > MAX_AUDIO_BYTES:
            return jsonify({'success': False, 'error': 'Audio je příliš velké (max 25 MB).'}), 413
        url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
    else:
        data = request.get_json(silent=True) or {}
        data_url = data.get('dataUrl')
        duration = int(data.get('durationSec') or 0)
        if not data_url or not isinstance(data_url, str) or not data_url.startswith('data:audio/'):
            return jsonify({'success': False, 'error': 'Chybí audio.'}), 400
        try:
            header, b64 = data_url.split(',', 1)
            content = base64.b64decode(b64)
        except Exception:
            return jsonify({'success': False, 'error': 'Neplatné audio data URL.'}), 400
        size = len(content)
        if size > MAX_AUDIO_BYTES:
            return jsonify({'success': False, 'error': 'Audio je příliš velké (max 25 MB).'}), 413
        url = data_url

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions "
                "SET audio_url = ?, audio_size_bytes = ?, "
                "duration_sec = COALESCE(NULLIF(?, 0), duration_sec), "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (url, size, duration, session_id, uid)
            )
    except Exception as e:
        logger.error(f"audio write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'audio_uploaded', 'contribution', session_id, f'size={size}b')
    return jsonify({'success': True, 'sessionId': session_id, 'sizeBytes': size})


@experience_bp.route('/api/experience/contribution/<int:cid>/attach-photo', methods=['POST'])
@require_auth
def attach_gallery_photo(cid):
    """Attach a photo from the Gallery module to this contribution.
    Both must belong to the same user."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    data = request.get_json() or {}
    photo_id = int(data.get('photoId') or 0)
    if not photo_id:
        return jsonify({'success': False, 'error': 'Chybí photoId.'}), 400

    # Verify photo ownership
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT id FROM gallery_photos WHERE id = ? AND user_id = ?",
                (photo_id, uid)
            ).fetchone()
        if not r:
            return jsonify({'success': False, 'error': 'photo not found'}), 404
    except Exception:
        return jsonify({'success': False, 'error': 'gallery not available'}), 503

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions "
                "SET gallery_photo_id = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (photo_id, cid, uid)
            )
    except Exception as e:
        logger.error(f"attach photo: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'photo_attached', 'contribution', cid, f'photo={photo_id}')
    return jsonify({'success': True, 'id': cid, 'photoId': photo_id})


# ─────────────────────────────────────────────────────────────────────────────
# OFFERS + CONTRACTS
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/offers', methods=['GET', 'OPTIONS'])
@require_auth
def list_offers():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT o.id, o.title, o.description, o.target_theme, o.target_type, "
                "o.target_depth, o.price_kc, o.royalty_years, o.royalty_kc_per_year, "
                "o.seats_total, o.seats_filled, b.name, b.type, b.trust_score "
                "FROM experience_offers o "
                "JOIN experience_buyers b ON b.id = o.buyer_id "
                "WHERE o.status = ? AND b.active = ? "
                "ORDER BY o.price_kc DESC LIMIT 50",
                ('active', True if is_postgres() else 1)
            ).fetchall()
    except Exception as e:
        logger.error(f"offers: {e}")
        rows = []

    offers = []
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        trust = int(v(13) or 80)
        if trust >= 90:
            radim_recommendation = 'green'
            radim_note = 'Doporučuji. Seriózní instituce, férová cena.'
        elif trust >= 70:
            radim_recommendation = 'yellow'
            radim_note = 'V pořádku, ale cena je průměrná.'
        else:
            radim_recommendation = 'red'
            radim_note = 'Nedoporučuji. Důvěra kupce je nízká.'
        senior_net = _calc_senior_net(v(6))
        offers.append({
            'id': v(0),
            'title': v(1),
            'description': v(2),
            'theme': v(3),
            'type': v(4),
            'depth': v(5),
            'grossPriceKc': v(6),
            'seniorNetKc': senior_net,
            'royaltyYears': v(7) or 0,
            'royaltyKcPerYear': _calc_senior_net(v(8) or 0),
            'seatsTotal': v(9),
            'seatsFilled': v(10),
            'buyer': {
                'name': v(11),
                'type': v(12),
                'trustScore': trust,
            },
            'radim': {
                'recommendation': radim_recommendation,
                'note': radim_note,
            },
        })
    return jsonify({'success': True, 'offers': offers, 'count': len(offers)})


@experience_bp.route('/api/experience/contribution/<int:cid>/accept-offer', methods=['POST'])
@require_auth
def accept_offer(cid):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _rate_ok(uid, 'contract_sign', RATE_CONTRACT_SIGN):
        return jsonify({'success': False, 'error': 'Moc rychle.',
                        'code': 'rate_limit'}), 429

    data = request.get_json() or {}
    offer_id = int(data.get('offerId') or 0)
    anonymized = _to_bool(data.get('anonymized'))
    if not offer_id:
        return jsonify({'success': False, 'error': 'Chybí offerId'}), 400

    # Verify contribution ownership + approved status + matches offer criteria
    try:
        with db_context() as db:
            cr = db.execute(
                "SELECT privacy, theme, type, depth FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
                (cid, uid)
            ).fetchone()
            if not cr:
                return jsonify({'success': False, 'error': 'contribution not found'}), 404
            def cv(i, k):
                return cr[i] if isinstance(cr, (list, tuple)) else cr.get(k)
            priv = cv(0, 'privacy')
            contrib_theme = cv(1, 'theme')
            contrib_type = cv(2, 'type')
            contrib_depth = int(cv(3, 'depth') or 1)
            if priv not in {'family', 'research', 'public'}:
                return jsonify({'success': False,
                                'error': 'Vzpomínka musí být nejprve schválena.'}), 400

            # Verify offer exists & active
            orow = db.execute(
                "SELECT buyer_id, price_kc, royalty_years, royalty_kc_per_year, "
                "status, target_theme, target_type, target_depth "
                "FROM experience_offers WHERE id = ?",
                (offer_id,)
            ).fetchone()
            if not orow:
                return jsonify({'success': False, 'error': 'offer not found'}), 404
            def ov(i, k):
                return orow[i] if isinstance(orow, (list, tuple)) else orow.get(k)
            buyer_id = ov(0, 'buyer_id')
            gross = int(ov(1, 'price_kc') or 0)
            royalty_y = int(ov(2, 'royalty_years') or 0)
            royalty_kc = int(ov(3, 'royalty_kc_per_year') or 0)
            status = ov(4, 'status')
            target_theme = ov(5, 'target_theme')
            target_type = ov(6, 'target_type')
            target_depth = int(ov(7, 'target_depth') or 1)

            if status != 'active':
                return jsonify({'success': False, 'error': 'Nabídka není aktivní.'}), 409
            if gross < MIN_PRICE_KC:
                return jsonify({'success': False,
                                'error': f'Cena pod minimem {MIN_PRICE_KC} Kč.'}), 400

            # Target criteria validation (prevent signing unrelated content)
            if target_theme and contrib_theme and target_theme != contrib_theme:
                return jsonify({
                    'success': False,
                    'error': f'Vzpomínka se netýká požadovaného tématu '
                             f'({target_theme}). Nabídka hledá: {target_theme}, '
                             f'vaše vzpomínka: {contrib_theme}.',
                    'code': 'theme_mismatch',
                }), 400
            if target_type and contrib_type and target_type != contrib_type:
                return jsonify({
                    'success': False,
                    'error': f'Vzpomínka má nesprávný typ. '
                             f'Nabídka hledá: {target_type}, máte: {contrib_type}.',
                    'code': 'type_mismatch',
                }), 400
            if target_depth > contrib_depth:
                return jsonify({
                    'success': False,
                    'error': 'Vzpomínka je příliš povrchová pro tuto nabídku. '
                             'Zkuste nejprve hlubší vyprávění.',
                    'code': 'depth_mismatch',
                }), 400

            # Duplicate guard: already signed this contribution to this offer?
            existing = db.execute(
                "SELECT id FROM experience_contracts "
                "WHERE contribution_id = ? AND offer_id = ? AND revoked_at IS NULL",
                (cid, offer_id)
            ).fetchone()
            if existing:
                return jsonify({
                    'success': False,
                    'error': 'Tuto vzpomínku jste už k této nabídce podepsal/a.',
                    'code': 'duplicate_contract',
                }), 409
    except Exception as e:
        logger.error(f"accept offer read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    # Cognitive capacity check — may require family co-sign
    brake_active, brake_reason = _check_cognitive_brake(uid)

    senior_price = _calc_senior_net(gross)
    senior_royalty = _calc_senior_net(royalty_kc)
    cooling_off = datetime.utcnow() + timedelta(hours=COOLING_OFF_HOURS)

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                r = db.execute(
                    "INSERT INTO experience_contracts "
                    "(user_id, contribution_id, offer_id, buyer_id, price_kc, "
                    "royalty_years, royalty_kc_per_year, anonymized, cooling_off_until, "
                    "requires_family_cosign) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, cid, offer_id, buyer_id, senior_price,
                     royalty_y, senior_royalty, anonymized, cooling_off, brake_active)
                ).fetchone()
                contract_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO experience_contracts "
                    "(user_id, contribution_id, offer_id, buyer_id, price_kc, "
                    "royalty_years, royalty_kc_per_year, anonymized, cooling_off_until, "
                    "requires_family_cosign) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, cid, offer_id, buyer_id, senior_price,
                     royalty_y, senior_royalty, 1 if anonymized else 0,
                     cooling_off, 1 if brake_active else 0)
                )
                contract_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None

            # Initial payout is pending until cosign if brake active
            if not brake_active:
                db.execute(
                    "INSERT INTO experience_earnings "
                    "(user_id, contract_id, amount_kc, gross_kc, source, period_label) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, contract_id, senior_price, gross, 'initial', 'initial_signing')
                )
            # Bump seats_filled
            db.execute(
                "UPDATE experience_offers SET seats_filled = seats_filled + 1 WHERE id = ?",
                (offer_id,)
            )
    except Exception as e:
        logger.error(f"accept offer write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'contract_signed', 'contract', contract_id,
           f'offer={offer_id} contribution={cid} cosign={brake_active}')

    response_msg = f'Smlouva podepsána. Na váš účet {senior_price} Kč. Máte 72 hodin na rozmyšlenou.'
    if brake_active:
        response_msg = ('Smlouva předpřipravena — čeká na spolupodepsání rodinou. ' + (brake_reason or ''))

    return jsonify({
        'success': True,
        'contractId': contract_id,
        'seniorPriceKc': senior_price if not brake_active else 0,
        'seniorRoyaltyKcPerYear': senior_royalty,
        'royaltyYears': royalty_y,
        'coolingOffUntil': cooling_off.isoformat(),
        'requiresFamilyCosign': brake_active,
        'cosignReason': brake_reason,
        'message': response_msg,
    })


@experience_bp.route('/api/experience/contract/<int:contract_id>/cosign', methods=['POST'])
@require_auth
def cosign_contract(contract_id):
    """Family member co-signs a contract flagged by cognitive capacity brake.
    Unlocks the initial payout to the senior."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT user_id, price_kc, requires_family_cosign, cosigned_at "
                "FROM experience_contracts WHERE id = ?",
                (contract_id,)
            ).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'not found'}), 404
        def v(i, k):
            return row[i] if isinstance(row, (list, tuple)) else row.get(k)
        senior_id = v(0, 'user_id')
        price = int(v(1, 'price_kc') or 0)
        needs_cosign = bool(v(2, 'requires_family_cosign'))
        already_signed = v(3, 'cosigned_at')
    except Exception as e:
        logger.error(f"cosign read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    if not _is_family_of(senior_id, uid) or senior_id == uid:
        return jsonify({'success': False, 'error': 'not linked family'}), 403
    if not needs_cosign:
        return jsonify({'success': False, 'error': 'Smlouva nevyžaduje spolupodepsání.'}), 400
    if already_signed:
        return jsonify({'success': False, 'error': 'Již spolupodepsáno.'}), 409

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contracts SET cosigned_by = ?, "
                "cosigned_at = CURRENT_TIMESTAMP WHERE id = ?",
                (uid, contract_id)
            )
            # Now release the initial payout
            db.execute(
                "INSERT INTO experience_earnings "
                "(user_id, contract_id, amount_kc, source, period_label) "
                "VALUES (?, ?, ?, ?, ?)",
                (senior_id, contract_id, price, 'initial', 'initial_signing_cosigned')
            )
    except Exception as e:
        logger.error(f"cosign write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(senior_id, 'contract_cosigned', 'contract', contract_id,
           f'by={uid}', actor_id=uid)

    return jsonify({
        'success': True,
        'contractId': contract_id,
        'message': f'Spolupodepsáno. {price} Kč uvolněno na účet vašeho blízkého.',
    })


@experience_bp.route('/api/experience/contract/<int:contract_id>', methods=['DELETE'])
@require_auth
def revoke_contract(contract_id):
    """Revoke a contract — within cooling-off period, refund; after, stop future royalty."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT price_kc, cooling_off_until, signed_at, revoked_at "
                "FROM experience_contracts WHERE id = ? AND user_id = ?",
                (contract_id, uid)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'not found'}), 404
            def v(i, k):
                return row[i] if isinstance(row, (list, tuple)) else row.get(k)
            if v(3, 'revoked_at'):
                return jsonify({'success': False, 'error': 'Již zrušeno.'}), 409

            db.execute(
                "UPDATE experience_contracts SET revoked_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (contract_id, uid)
            )
    except Exception as e:
        logger.error(f"revoke: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({'success': True, 'id': contract_id, 'revoked': True,
                    'message': 'Smlouva zrušena. Vaše data už kupec nebude dostávat.'})


# ─────────────────────────────────────────────────────────────────────────────
# EARNINGS
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/earnings', methods=['GET', 'OPTIONS'])
@require_auth
def earnings_view():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT e.id, e.amount_kc, e.gross_kc, e.source, e.period_label, "
                "e.paid_at, e.created_at, b.name "
                "FROM experience_earnings e "
                "LEFT JOIN experience_contracts c ON c.id = e.contract_id "
                "LEFT JOIN experience_buyers b ON b.id = c.buyer_id "
                "WHERE e.user_id = ? "
                "ORDER BY e.created_at DESC LIMIT 100",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"earnings: {e}")
        rows = []

    items = []
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        items.append({
            'id': v(0),
            'amountKc': v(1),
            'grossKc': v(2),
            'source': v(3),
            'periodLabel': v(4),
            'paidAt': str(v(5) or ''),
            'createdAt': str(v(6) or ''),
            'buyerName': v(7),
        })
    return jsonify({'success': True, 'earnings': items, 'count': len(items)})


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS LIBRARY
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/prompts', methods=['GET'])
@require_auth
def get_prompts():
    theme = (request.args.get('theme') or 'family').strip().lower()
    try:
        depth = int(request.args.get('depth') or 1)
    except Exception:
        depth = 1
    if theme not in VALID_THEMES:
        theme = 'family'
    if depth not in VALID_DEPTHS:
        depth = 1
    prompts = RADIM_PROMPTS.get(theme, {}).get(depth, [])
    return jsonify({
        'success': True,
        'theme': theme,
        'depth': depth,
        'prompts': prompts,
        'availableThemes': sorted(RADIM_PROMPTS.keys()),
        'availableDepths': [1, 2, 3],
    })


# ─────────────────────────────────────────────────────────────────────────────
# INHERITANCE — legacy beneficiary configuration
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/inheritance', methods=['GET', 'PUT', 'OPTIONS'])
@require_auth
def inheritance():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if request.method == 'GET':
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT heir_name, heir_relation, heir_contact, "
                    "royalty_years_after_death, unlock_family_archive, "
                    "public_memorial, configured_at, updated_at "
                    "FROM experience_inheritance WHERE user_id = ?",
                    (uid,)
                ).fetchone()
        except Exception:
            row = None
        if not row:
            return jsonify({'success': True, 'configured': False, 'inheritance': None})
        def v(i, k):
            return row[i] if isinstance(row, (list, tuple)) else row.get(k)
        return jsonify({
            'success': True,
            'configured': True,
            'inheritance': {
                'heirName': v(0, 'heir_name'),
                'heirRelation': v(1, 'heir_relation'),
                'heirContact': v(2, 'heir_contact'),
                'royaltyYearsAfterDeath': v(3, 'royalty_years_after_death'),
                'unlockFamilyArchive': bool(v(4, 'unlock_family_archive')),
                'publicMemorial': bool(v(5, 'public_memorial')),
                'configuredAt': str(v(6, 'configured_at') or ''),
                'updatedAt': str(v(7, 'updated_at') or ''),
            }
        })

    # PUT
    data = request.get_json() or {}
    heir_name = (data.get('heirName') or '').strip()[:200]
    heir_relation = (data.get('heirRelation') or '').strip()[:100]
    heir_contact = (data.get('heirContact') or '').strip()[:200]
    royalty_years = max(0, min(25, int(data.get('royaltyYearsAfterDeath') or 5)))
    unlock_family = _to_bool(data.get('unlockFamilyArchive'))
    public_memorial = _to_bool(data.get('publicMemorial'))

    if not heir_name:
        return jsonify({'success': False, 'error': 'Jméno dědice je povinné.'}), 400

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "INSERT INTO experience_inheritance "
                    "(user_id, heir_name, heir_relation, heir_contact, "
                    "royalty_years_after_death, unlock_family_archive, public_memorial) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "heir_name = EXCLUDED.heir_name, "
                    "heir_relation = EXCLUDED.heir_relation, "
                    "heir_contact = EXCLUDED.heir_contact, "
                    "royalty_years_after_death = EXCLUDED.royalty_years_after_death, "
                    "unlock_family_archive = EXCLUDED.unlock_family_archive, "
                    "public_memorial = EXCLUDED.public_memorial, "
                    "updated_at = CURRENT_TIMESTAMP",
                    (uid, heir_name, heir_relation, heir_contact,
                     royalty_years, unlock_family, public_memorial)
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO experience_inheritance "
                    "(user_id, heir_name, heir_relation, heir_contact, "
                    "royalty_years_after_death, unlock_family_archive, "
                    "public_memorial, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (uid, heir_name, heir_relation, heir_contact,
                     royalty_years, 1 if unlock_family else 0,
                     1 if public_memorial else 0)
                )
    except Exception as e:
        logger.error(f"inheritance: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({
        'success': True,
        'message': f'Dědictví nastaveno pro {heir_name}. Vaše vzpomínky budou v bezpečí.',
    })


# ─────────────────────────────────────────────────────────────────────────────
# FAMILY VIEW — read-only archive for linked family members
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/family/<senior_id>', methods=['GET', 'OPTIONS'])
@require_auth
def family_archive(senior_id):
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    try:
        with db_context() as db:
            rows = db.execute(
                f"SELECT {_SELECT_CONTRIB} FROM experience_contributions "
                "WHERE user_id = ? AND privacy IN (?, ?) "
                "ORDER BY created_at DESC LIMIT 200",
                (senior_id, 'family', 'public')
            ).fetchall()
    except Exception as e:
        logger.error(f"family archive: {e}")
        rows = []

    contribs = [_contrib_row(r) for r in rows or []]
    return jsonify({'success': True, 'contributions': contribs, 'count': len(contribs)})



# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULED MESSAGES — "Zprávy pro budoucnost"
# Senior records messages to be released on future dates/events.
# Unlike contributions (whole past), these are gifts to the future.
# ─────────────────────────────────────────────────────────────────────────────

VALID_SCHEDULED_EVENTS = {
    'date', 'birthday', 'graduation', 'wedding', 'first_child',
    'holiday', 'anniversary', 'custom'
}

VALID_SCHEDULED_STATUS = {'scheduled', 'delivered', 'cancelled', 'failed'}


@experience_bp.route('/api/experience/scheduled', methods=['GET', 'POST', 'OPTIONS'])
@require_auth
def scheduled_messages():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if request.method == 'GET':
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, recipient_name, recipient_relation, recipient_contact, "
                    "message_type, content, audio_url, release_event, release_date, "
                    "status, released_at, created_at "
                    "FROM experience_scheduled_messages "
                    "WHERE user_id = ? AND status <> ? "
                    "ORDER BY release_date ASC LIMIT 200",
                    (uid, 'cancelled')
                ).fetchall()
        except Exception as e:
            logger.error(f"scheduled list: {e}")
            rows = []
        items = []
        for r in rows or []:
            def v(i):
                return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
            items.append({
                'id': v(0),
                'recipientName': v(1),
                'recipientRelation': v(2),
                'recipientContact': v(3),
                'messageType': v(4),
                'content': v(5),
                'audioUrl': v(6),
                'releaseEvent': v(7),
                'releaseDate': str(v(8) or ''),
                'status': v(9),
                'releasedAt': str(v(10) or ''),
                'createdAt': str(v(11) or ''),
            })
        return jsonify({'success': True, 'messages': items, 'count': len(items)})

    # POST — create
    if not _rate_ok(uid, 'scheduled_create', 20):
        return jsonify({'success': False, 'code': 'rate_limit',
                        'error': 'Moc rychle. Zkuste to za chvilku.'}), 429

    data = request.get_json() or {}
    recipient_name = (data.get('recipientName') or '').strip()[:200]
    recipient_relation = (data.get('recipientRelation') or '').strip()[:100]
    recipient_contact = (data.get('recipientContact') or '').strip()[:200]
    message_type = (data.get('messageType') or 'text').strip().lower()
    content = (data.get('content') or '').strip()[:10000]
    release_event = (data.get('releaseEvent') or 'date').strip().lower()
    release_date = (data.get('releaseDate') or '').strip()

    if not recipient_name:
        return jsonify({'success': False, 'error': 'Jméno příjemce je povinné.'}), 400
    if not content:
        return jsonify({'success': False, 'error': 'Zpráva nesmí být prázdná.'}), 400
    if release_event not in VALID_SCHEDULED_EVENTS:
        release_event = 'date'
    if message_type not in {'text', 'audio'}:
        message_type = 'text'

    # Parse release_date — must be in the future
    parsed_date = None
    if release_date:
        try:
            parsed_date = datetime.strptime(release_date[:10], '%Y-%m-%d')
        except Exception:
            return jsonify({'success': False, 'error': 'Neplatné datum (YYYY-MM-DD).'}), 400
        if parsed_date <= datetime.utcnow():
            return jsonify({'success': False,
                            'error': 'Datum musí být v budoucnosti.'}), 400

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                r = db.execute(
                    "INSERT INTO experience_scheduled_messages "
                    "(user_id, recipient_name, recipient_relation, recipient_contact, "
                    "message_type, content, release_event, release_date, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, recipient_name, recipient_relation, recipient_contact,
                     message_type, content, release_event, parsed_date, 'scheduled')
                ).fetchone()
                new_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO experience_scheduled_messages "
                    "(user_id, recipient_name, recipient_relation, recipient_contact, "
                    "message_type, content, release_event, release_date, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, recipient_name, recipient_relation, recipient_contact,
                     message_type, content, release_event, parsed_date, 'scheduled')
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"scheduled insert: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'scheduled_created', 'scheduled_message', new_id,
           f'to={recipient_name} event={release_event} date={release_date}')

    return jsonify({
        'success': True,
        'id': new_id,
        'message': f'Zpráva pro {recipient_name} je uložena. Uvolní se v čas.',
    })


@experience_bp.route('/api/experience/scheduled/<int:msg_id>', methods=['DELETE'])
@require_auth
def cancel_scheduled(msg_id):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_scheduled_messages SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ? AND status = ?",
                ('cancelled', msg_id, uid, 'scheduled')
            )
    except Exception as e:
        logger.error(f"scheduled cancel: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'scheduled_cancelled', 'scheduled_message', msg_id)
    return jsonify({'success': True, 'id': msg_id})


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-SESSION THREADING — link contributions as chapters of a larger story
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/contribution/<int:cid>/link-parent', methods=['POST'])
@require_auth
def link_parent(cid):
    """Make this contribution a continuation (chapter) of parent contribution."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    data = request.get_json() or {}
    parent_id = int(data.get('parentId') or 0)
    if parent_id == cid:
        return jsonify({'success': False, 'error': 'Nelze odkázat na sebe.'}), 400

    # Verify parent ownership
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT id FROM experience_contributions WHERE id = ? AND user_id = ?",
                (parent_id, uid)
            ).fetchone() if parent_id else True
        if parent_id and not r:
            return jsonify({'success': False, 'error': 'parent not found'}), 404
    except Exception:
        pass

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions "
                "SET parent_contribution_id = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (parent_id if parent_id else None, cid, uid)
            )
    except Exception as e:
        logger.error(f"link parent: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'linked_parent', 'contribution', cid, f'parent={parent_id}')
    return jsonify({'success': True, 'id': cid, 'parentId': parent_id or None})


# ─────────────────────────────────────────────────────────────────────────────
# MEMORY INTEGRATION — inject contribution highlights into Radim's chat context
# ─────────────────────────────────────────────────────────────────────────────

def recent_contributions_for_memory(user_id, limit=5):
    """Public helper — consumed by memory_context_builder / personalized prompts.

    Returns recent APPROVED contributions with title + short snippet, suitable
    for prepending to Radim's system prompt. Respects senior's sharing choices:
    only 'family' and 'public' contributions are surfaced to Radim's memory,
    NOT 'research' ones (those are treated as anonymized third-party data).
    """
    if not user_id:
        return []
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, title, theme, transcript, created_at "
                "FROM experience_contributions "
                "WHERE user_id = ? AND privacy IN (?, ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, 'family', 'public', int(limit))
            ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        text = (v(3, 'transcript') or '').strip()
        snippet = text[:280] + ('…' if len(text) > 280 else '')
        out.append({
            'id': v(0, 'id'),
            'title': v(1, 'title'),
            'theme': v(2, 'theme'),
            'snippet': snippet,
            'createdAt': str(v(4, 'created_at') or ''),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ROYALTY SCHEDULER — background job, pays yearly royalties monthly/12
# ─────────────────────────────────────────────────────────────────────────────

def run_royalty_payout():
    """Check all active contracts with royalty_years > 0 and monthly-prorate.
    Creates earnings entries for contracts whose last_royalty_at is >=30 days ago
    (or never paid after initial). Safe to run daily — idempotent per contract."""
    _init_schema()
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    cutoff_30d = now - timedelta(days=30)
    paid_count = 0
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, user_id, royalty_years, royalty_kc_per_year, "
                "signed_at, last_royalty_at "
                "FROM experience_contracts "
                "WHERE revoked_at IS NULL AND royalty_years > 0 "
                "AND royalty_kc_per_year > 0"
            ).fetchall()
    except Exception as e:
        logger.debug(f"royalty scan: {e}")
        return 0
    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        contract_id = v(0, 'id')
        user_id = v(1, 'user_id')
        years = int(v(2, 'royalty_years') or 0)
        per_year = int(v(3, 'royalty_kc_per_year') or 0)
        signed = v(4, 'signed_at')
        last = v(5, 'last_royalty_at')
        # Monthly amount (1/12 of yearly)
        monthly = per_year // 12 if per_year >= 12 else per_year
        if monthly <= 0:
            continue
        # Check eligibility
        last_dt = None
        try:
            if last:
                last_dt = datetime.strptime(str(last)[:19], '%Y-%m-%d %H:%M:%S')
        except Exception:
            last_dt = None
        if last_dt and last_dt > cutoff_30d:
            continue  # already paid this month
        # Check contract hasn't expired
        try:
            signed_dt = datetime.strptime(str(signed)[:19], '%Y-%m-%d %H:%M:%S')
        except Exception:
            signed_dt = now
        expiry = signed_dt + timedelta(days=365 * years)
        if now > expiry:
            continue  # royalty period over
        # Pay
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO experience_earnings "
                    "(user_id, contract_id, amount_kc, source, period_label) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, contract_id, monthly, 'royalty',
                     now.strftime('%Y-%m'))
                )
                db.execute(
                    "UPDATE experience_contracts SET last_royalty_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (contract_id,)
                )
            paid_count += 1
        except Exception as e:
            logger.debug(f"royalty pay contract={contract_id}: {e}")
    logger.info(f"Royalty scheduler paid {paid_count} contracts")
    return paid_count


def run_scheduled_messages():
    """Release scheduled messages whose release_date <= now."""
    _init_schema()
    from datetime import datetime
    released = 0
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, user_id, recipient_name, recipient_contact, content "
                "FROM experience_scheduled_messages "
                "WHERE status = ? AND release_date IS NOT NULL "
                "AND release_date <= ?",
                ('scheduled', datetime.utcnow())
            ).fetchall()
    except Exception as e:
        logger.debug(f"scheduled scan: {e}")
        return 0

    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        msg_id = v(0, 'id')
        user_id = v(1, 'user_id')
        recipient_name = v(2, 'recipient_name')
        # Best-effort notify: we cannot email without SMTP config; just mark delivered
        # and log. Real delivery (email/SMS) happens in downstream channel.
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "UPDATE experience_scheduled_messages SET status = ?, "
                    "released_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ('delivered', msg_id)
                )
            # Best-effort push to senior so they know it was released
            try:
                from notification_helpers import notify_user
                notify_user(
                    user_id=user_id,
                    type='info',
                    title='📬 Zpráva byla uvolněna',
                    body=f'Zpráva pro {recipient_name} právě dorazila svému adresátovi.',
                    severity='info',
                    data={'scheduled_message_id': msg_id},
                )
            except Exception:
                pass
            released += 1
        except Exception as e:
            logger.debug(f"scheduled release {msg_id}: {e}")
    if released:
        logger.info(f"Scheduled messages released: {released}")
    return released


# ─────────────────────────────────────────────────────────────────────────────
# DIGNITY LOCK — gentle defer when senior appears distressed
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/dignity-check', methods=['GET', 'OPTIONS'])
@require_auth
def dignity_check():
    """Check if senior should be gently deferred from session right now.
    Uses last 2 hours of brain_states.C — if C avg < 0.32, suggest waiting."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT AVG(C), COUNT(*) FROM brain_states "
                "WHERE user_id = ? AND C IS NOT NULL "
                "AND created_at >= ?",
                (uid, datetime.utcnow() - timedelta(hours=2))
            ).fetchone()
    except Exception:
        row = None

    defer = False
    reason = None
    c_avg = None
    if row:
        def v(i):
            return row[i] if isinstance(row, (list, tuple)) else list(row.values())[i]
        try:
            c_avg = float(v(0) or 0.5)
        except Exception:
            c_avg = 0.5
        samples = int(v(1) or 0)
        if samples >= 3 and c_avg < 0.32:
            defer = True
            reason = ('Cítím, že vám dnes není dobře. '
                      'Vzpomínky počkají. Až budete chtít, vrátíme se k tomu.')

    return jsonify({
        'success': True,
        'defer': defer,
        'reason': reason,
        'cAvg': c_avg,
    })


# ─────────────────────────────────────────────────────────────────────────────
# RESTORE (undo forget) — 72h safety net on deleted contributions
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/contribution/<int:cid>/restore', methods=['POST'])
@require_auth
def restore_contribution(cid):
    """Restore a soft-deleted contribution within 72h window.
    privacy='deleted' → 'family' (safest default)."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            r = db.execute(
                "SELECT privacy, updated_at FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
                (cid, uid)
            ).fetchone()
        if not r:
            return jsonify({'success': False, 'error': 'not found'}), 404
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        if v(0, 'privacy') != 'deleted':
            return jsonify({'success': False, 'error': 'Vzpomínka není smazaná.'}), 409
        # 72h window check
        try:
            updated_str = str(v(1, 'updated_at') or '')[:19]
            updated = datetime.strptime(updated_str, '%Y-%m-%d %H:%M:%S')
            if datetime.utcnow() - updated > timedelta(hours=72):
                return jsonify({'success': False,
                                'error': 'Uplynulo 72 hodin — vzpomínku už nelze vrátit.',
                                'code': 'window_expired'}), 410
        except Exception:
            pass
    except Exception as e:
        logger.error(f"restore read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions "
                "SET privacy = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                ('family', cid, uid)
            )
    except Exception as e:
        logger.error(f"restore write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'restored', 'contribution', cid)
    return jsonify({'success': True, 'id': cid,
                    'message': 'Vzpomínka vrácena. Zařadil jsem ji zpět k vašim.'})


@experience_bp.route('/api/experience/trash', methods=['GET'])
@require_auth
def list_trash():
    """Recent deletions within 72h window — recoverable."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    cutoff = datetime.utcnow() - timedelta(hours=72)
    try:
        with db_context() as db:
            rows = db.execute(
                f"SELECT {_SELECT_CONTRIB} FROM experience_contributions "
                "WHERE user_id = ? AND privacy = ? AND updated_at >= ? "
                "ORDER BY updated_at DESC LIMIT 50",
                (uid, 'deleted', cutoff)
            ).fetchall()
    except Exception:
        rows = []
    items = [_contrib_row(r) for r in rows or []]
    return jsonify({'success': True, 'items': items, 'count': len(items)})


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG VIEW (senior sees who accessed what — GDPR čl. 15)
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/audit-log', methods=['GET'])
@require_auth
def view_audit_log():
    """Senior's GDPR audit log — last 100 events on their data."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, actor_id, action, target_type, target_id, "
                "detail, ip_address, created_at "
                "FROM experience_audit_log WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT 100",
                (uid,)
            ).fetchall()
    except Exception:
        rows = []
    out = []
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        out.append({
            'id': v(0),
            'actorId': v(1),
            'actorIsSelf': v(1) == uid,
            'action': v(2),
            'targetType': v(3),
            'targetId': v(4),
            'detail': v(5),
            'createdAt': str(v(7) or ''),
        })
    return jsonify({'success': True, 'entries': out, 'count': len(out)})


# ─────────────────────────────────────────────────────────────────────────────
# COSIGN QUEUE (family view)
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/cosign-queue/<senior_id>', methods=['GET'])
@require_auth
def cosign_queue(senior_id):
    """List contracts flagged for family co-sign — family view."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid) or senior_id == uid:
        return jsonify({'success': False, 'error': 'not linked'}), 403

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT c.id, c.price_kc, c.signed_at, c.cooling_off_until, "
                "c.cosigned_at, o.title, b.name "
                "FROM experience_contracts c "
                "LEFT JOIN experience_offers o ON o.id = c.offer_id "
                "LEFT JOIN experience_buyers b ON b.id = c.buyer_id "
                "WHERE c.user_id = ? AND c.requires_family_cosign = ? "
                "AND c.revoked_at IS NULL "
                "ORDER BY c.signed_at DESC LIMIT 50",
                (senior_id, True if is_postgres() else 1)
            ).fetchall()
    except Exception:
        rows = []
    items = []
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        items.append({
            'id': v(0),
            'priceKc': v(1),
            'signedAt': str(v(2) or ''),
            'coolingOffUntil': str(v(3) or ''),
            'cosignedAt': str(v(4) or ''),
            'offerTitle': v(5),
            'buyerName': v(6),
            'pending': not v(4),
        })
    return jsonify({'success': True, 'contracts': items,
                    'pendingCount': sum(1 for x in items if x['pending'])})


# ─────────────────────────────────────────────────────────────────────────────
# INTELLIGENT NEXT-STEP SUGGESTIONS (Gemini-based)
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/suggest-next', methods=['GET'])
@require_auth
def suggest_next():
    """Radim suggests next meaningful step based on recent history.
    Heuristic + optional Gemini enrichment."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Fetch recent approved contributions
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT title, theme, depth, created_at FROM experience_contributions "
                "WHERE user_id = ? AND privacy IN (?, ?, ?) "
                "ORDER BY created_at DESC LIMIT 10",
                (uid, 'family', 'research', 'public')
            ).fetchall()
    except Exception:
        rows = []

    # Theme counting
    theme_counts = defaultdict(int)
    latest_theme = None
    latest_title = None
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        theme_counts[v(1)] += 1
        if not latest_theme:
            latest_theme = v(1)
            latest_title = v(0)

    # Build suggestion
    if not rows:
        return jsonify({
            'success': True,
            'suggestion': {
                'kind': 'first',
                'prompt': 'Rád bych vás slyšel. Začneme rodinnou vzpomínkou?',
                'theme': 'family',
                'depth': 1,
            },
        })

    # If 3+ in one theme, suggest different theme
    used_themes = sorted(theme_counts.items(), key=lambda x: -x[1])
    dominant = used_themes[0][0] if used_themes else 'family'
    if theme_counts[dominant] >= 3:
        alternatives = [t for t in ['family', 'historical', 'skill', 'wisdom', 'witness']
                        if t != dominant and theme_counts.get(t, 0) < 2]
        if alternatives:
            target = alternatives[0]
            prompts = RADIM_PROMPTS.get(target, {}).get(1, [])
            suggestion_text = (
                f'Mnoho jste mi dala o rodině. Chcete zkusit něco jiného? '
                f'Mám pro vás otázku.'
            )
            return jsonify({
                'success': True,
                'suggestion': {
                    'kind': 'new_theme',
                    'prompt': suggestion_text,
                    'theme': target,
                    'depth': 1,
                    'alternativeQuestion': prompts[0] if prompts else None,
                },
            })

    # If 3+ in one theme AT depth 1, offer depth 2
    if theme_counts[latest_theme] >= 2:
        prompts_d2 = RADIM_PROMPTS.get(latest_theme, {}).get(2, [])
        if prompts_d2:
            return jsonify({
                'success': True,
                'suggestion': {
                    'kind': 'deeper',
                    'prompt': (f'Známe se dost. Chcete jít hlouběji '
                               f'v tématu {latest_theme}?'),
                    'theme': latest_theme,
                    'depth': 2,
                    'alternativeQuestion': prompts_d2[0],
                },
            })

    # Default — continuation in same theme, same depth
    prompts = RADIM_PROMPTS.get(latest_theme, {}).get(1, [])
    return jsonify({
        'success': True,
        'suggestion': {
            'kind': 'continue',
            'prompt': f'Minule jste mluvila o „{latest_title}". Pokračujeme?',
            'theme': latest_theme,
            'depth': 1,
            'alternativeQuestion': prompts[0] if prompts else None,
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# GDPR — Article 20 (portability) + Article 17 (erasure)
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/export-all', methods=['GET'])
@require_auth
def export_all():
    """GDPR Article 20 — machine-readable export of ALL senior's data in module."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    bundle = {
        'exportedAt': datetime.utcnow().isoformat() + 'Z',
        'userId': uid,
        'schemaVersion': '1.1',
    }

    try:
        with db_context() as db:
            # Contributions
            rows = db.execute(
                f"SELECT {_SELECT_CONTRIB} FROM experience_contributions "
                "WHERE user_id = ? ORDER BY created_at ASC",
                (uid,)
            ).fetchall()
            bundle['contributions'] = [_contrib_row(r) for r in rows or []]
            # Contracts
            rows = db.execute(
                "SELECT id, contribution_id, offer_id, buyer_id, price_kc, "
                "royalty_years, royalty_kc_per_year, anonymized, "
                "signed_at, revoked_at, cosigned_by, cosigned_at "
                "FROM experience_contracts WHERE user_id = ? "
                "ORDER BY signed_at ASC",
                (uid,)
            ).fetchall()
            bundle['contracts'] = []
            for r in rows or []:
                def v(i):
                    return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
                bundle['contracts'].append({
                    'id': v(0), 'contributionId': v(1), 'offerId': v(2),
                    'buyerId': v(3), 'priceKc': v(4),
                    'royaltyYears': v(5), 'royaltyKcPerYear': v(6),
                    'anonymized': bool(v(7)),
                    'signedAt': str(v(8) or ''),
                    'revokedAt': str(v(9) or ''),
                    'cosignedBy': v(10), 'cosignedAt': str(v(11) or ''),
                })
            # Earnings
            rows = db.execute(
                "SELECT id, contract_id, amount_kc, gross_kc, source, "
                "period_label, paid_at, created_at "
                "FROM experience_earnings WHERE user_id = ? ORDER BY created_at ASC",
                (uid,)
            ).fetchall()
            bundle['earnings'] = []
            for r in rows or []:
                def v(i):
                    return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
                bundle['earnings'].append({
                    'id': v(0), 'contractId': v(1), 'amountKc': v(2),
                    'grossKc': v(3), 'source': v(4),
                    'periodLabel': v(5), 'paidAt': str(v(6) or ''),
                    'createdAt': str(v(7) or ''),
                })
            # Inheritance
            r = db.execute(
                "SELECT heir_name, heir_relation, heir_contact, "
                "heir_contact_verified, royalty_years_after_death, "
                "unlock_family_archive, public_memorial "
                "FROM experience_inheritance WHERE user_id = ?",
                (uid,)
            ).fetchone()
            if r:
                def v(i, k):
                    return r[i] if isinstance(r, (list, tuple)) else r.get(k)
                bundle['inheritance'] = {
                    'heirName': v(0, 'heir_name'),
                    'heirRelation': v(1, 'heir_relation'),
                    'heirContact': v(2, 'heir_contact'),
                    'heirContactVerified': bool(v(3, 'heir_contact_verified')),
                    'royaltyYearsAfterDeath': v(4, 'royalty_years_after_death'),
                    'unlockFamilyArchive': bool(v(5, 'unlock_family_archive')),
                    'publicMemorial': bool(v(6, 'public_memorial')),
                }
            # Scheduled
            rows = db.execute(
                "SELECT id, recipient_name, recipient_relation, "
                "message_type, content, release_event, release_date, "
                "status, released_at, created_at "
                "FROM experience_scheduled_messages WHERE user_id = ? "
                "ORDER BY release_date ASC",
                (uid,)
            ).fetchall()
            bundle['scheduledMessages'] = []
            for r in rows or []:
                def v(i):
                    return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
                bundle['scheduledMessages'].append({
                    'id': v(0), 'recipientName': v(1), 'recipientRelation': v(2),
                    'messageType': v(3), 'content': v(4),
                    'releaseEvent': v(5), 'releaseDate': str(v(6) or ''),
                    'status': v(7), 'releasedAt': str(v(8) or ''),
                    'createdAt': str(v(9) or ''),
                })
    except Exception as e:
        logger.error(f"export-all: {e}")

    _audit(uid, 'gdpr_export', 'all', None, 'Article 20 — data portability')
    return jsonify({'success': True, 'export': bundle})


@experience_bp.route('/api/experience/erase-all', methods=['POST'])
@require_auth
def erase_all():
    """GDPR Article 17 — right to erasure. Requires explicit confirmation token.
    Soft-deletes contributions, revokes contracts, clears inheritance+scheduled.
    Audit log is preserved as legal record.
    """
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    confirm = (data.get('confirm') or '').strip().upper()
    if confirm != 'SMAZAT VSE':
        return jsonify({
            'success': False,
            'error': 'Pro úplné smazání zadejte potvrzovací text "SMAZAT VSE".',
            'code': 'confirmation_required',
        }), 400

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_contributions SET privacy = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND privacy <> ?",
                ('deleted', uid, 'deleted')
            )
            db.execute(
                "UPDATE experience_contracts SET revoked_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ? AND revoked_at IS NULL",
                (uid,)
            )
            db.execute(
                "DELETE FROM experience_inheritance WHERE user_id = ?",
                (uid,)
            )
            db.execute(
                "UPDATE experience_scheduled_messages SET status = ? "
                "WHERE user_id = ? AND status = ?",
                ('cancelled', uid, 'scheduled')
            )
    except Exception as e:
        logger.error(f"erase-all: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'gdpr_erasure', 'all', None, 'Article 17 — right to erasure')
    return jsonify({
        'success': True,
        'message': 'Vaše údaje byly smazány. Auditní záznam zůstal jako právní doklad.',
    })


def register_scheduler_jobs(scheduler):
    """Hook into main APScheduler (called from app.py). Safe to call twice —
    uses replace_existing=True."""
    try:
        scheduler.add_job(
            run_royalty_payout,
            'cron', hour=3, minute=30, id='experience_royalty_payout',
            replace_existing=True,
        )
        scheduler.add_job(
            run_scheduled_messages,
            'interval', minutes=15, id='experience_scheduled_messages',
            replace_existing=True,
        )
        logger.info("✅ Experience scheduler jobs registered (royalty daily 03:30, scheduled every 15 min)")
    except Exception as e:
        logger.warning(f"⚠️ Experience scheduler registration: {e}")


logger.info("🌿 Experience routes v1.1 loaded — Radimův Odkaz (hardened MVP)")
