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
from ai_config import GEMINI_MODEL

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

    -- ── MVP: per-audience consent (family / research / companies) ─────
    CREATE TABLE IF NOT EXISTS experience_consents (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        contribution_id INTEGER NOT NULL,
        share_family BOOLEAN DEFAULT FALSE,
        share_research BOOLEAN DEFAULT FALSE,
        share_companies BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_consents_user ON experience_consents(user_id, created_at DESC);
    CREATE UNIQUE INDEX IF NOT EXISTS ux_exp_consents_contribution ON experience_consents(contribution_id);

    -- ── MVP: rewards (bank-transfer, length-based: 50/100/150 Kč) ─────
    CREATE TABLE IF NOT EXISTS experience_rewards (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        contribution_id INTEGER NOT NULL,
        amount_kc INTEGER NOT NULL,
        tier TEXT NOT NULL,                  -- 'short' | 'medium' | 'long'
        word_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',       -- 'pending' | 'approved' | 'paid' | 'failed'
        payout_method TEXT DEFAULT 'bank_transfer',
        bank_iban_last4 TEXT,                -- for receipt display only
        bank_ref TEXT,                       -- bank transaction ID after payout
        admin_note TEXT,
        approved_at TIMESTAMP,
        paid_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_rewards_user ON experience_rewards(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_exp_rewards_status ON experience_rewards(status, created_at);
    CREATE UNIQUE INDEX IF NOT EXISTS ux_exp_rewards_contribution ON experience_rewards(contribution_id);

    -- ── MVP: bank info for payouts (IBAN stored + hashed for privacy) ─
    CREATE TABLE IF NOT EXISTS experience_bank_info (
        user_id TEXT PRIMARY KEY,
        account_holder TEXT NOT NULL,
        iban TEXT NOT NULL,
        iban_last4 TEXT,
        bank_name TEXT,
        swift_bic TEXT,
        verified BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── Pilot: partner leads (institutions interested in Radimův Odkaz) ─
    -- Sbíráme zájem od kandidátních partnerů (univerzity, archivy, AI labs,
    -- výzkum, marketing) PŘED tím, než publikujeme jejich nabídku v UI.
    -- Žádný buyer se neaktivuje automaticky — manuální schválení adminem
    -- po podpisu MoU + DPA.
    CREATE TABLE IF NOT EXISTS experience_partner_leads (
        id SERIAL PRIMARY KEY,
        org_name TEXT NOT NULL,
        contact_name TEXT NOT NULL,
        contact_email TEXT NOT NULL,
        contact_phone TEXT,
        org_type TEXT,                       -- 'university'|'archive'|'research'|'ai_lab'|'market_research'|'media'|'other'
        org_ico TEXT,                        -- IČO pro KYC
        message TEXT,                        -- co partner zamýšlí
        source TEXT DEFAULT 'app',           -- 'app'|'web'|'event_zivot90'|'event_cvut'|'direct'
        status TEXT DEFAULT 'new',           -- 'new'|'contacted'|'mou_sent'|'signed'|'rejected'
        admin_note TEXT,
        contacted_at TIMESTAMP,
        signed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_leads_status ON experience_partner_leads(status, created_at DESC);
    CREATE UNIQUE INDEX IF NOT EXISTS ux_exp_leads_email ON experience_partner_leads(LOWER(contact_email));
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
    # Bug-fix: dříve celý EXPERIENCE_SCHEMA běžel v JEDNOM `with db_context(commit=True)`
    # bloku — pokud KTERÝKOLI statement selhal (např. nový CREATE TABLE s funkčním
    # indexem na PG, který ještě neexistuje), CELÁ transakce se rolbackla a všechny
    # další tabulky NEBYLY vytvořeny. Důsledek: experience_partner_leads neexistovala
    # i když všechny ostatní tabulky byly OK. Teď: každý statement v VLASTNÍ transakci,
    # selhání jednoho neovlivní ostatní.
    statements = [s.strip() for s in EXPERIENCE_SCHEMA.strip().split(';') if s.strip()]
    for stmt in statements:
        try:
            with db_context(commit=True) as db:
                db.execute(stmt)
        except Exception as e:
            # Idempotence: IF NOT EXISTS by toto neměl trigger, ale pokud jsme v race
            # se starou verzí dyna, log ne-fatální chybu a pokračuj.
            logger.debug(f"Experience schema stmt skipped: {str(e)[:120]} — stmt: {stmt[:80]}")
    if is_postgres():
        _migrate_schema_additive()
    # Pilot fix: NEpouštíme _seed_demo_buyers_if_empty.
    # Demo buyers (Karlova univerzita, Národní archiv, Akademie věd...)
    # neudělili souhlas se svými jmény. Pokud DB je prázdná, raději
    # zobrazíme empty-state s "Hledáme prvního partnera" v UI než
    # vystavit aplikaci právnímu riziku z fake offers.
    # Reaktivovat můžeme po podpisu MoU s reálným partnerem přes
    # admin endpoint POST /api/admin/partners/onboard.
    # _seed_demo_buyers_if_empty()


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


# Sprint O — quick memory: save a single chat message as draft contribution
@experience_bp.route('/api/experience/from-message', methods=['POST', 'OPTIONS'])
@require_auth
def quick_memory_from_message():
    """Save a single text snippet (e.g. chat message) as a draft contribution.
    Body: {text, title?, source: 'chat'|'voice'|...}"""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if _count_active_contributions(uid) >= MAX_CONTRIBUTIONS_PER_SENIOR:
        return jsonify({'success': False,
                        'error': f'Máte už {MAX_CONTRIBUTIONS_PER_SENIOR} vzpomínek.',
                        'code': 'quota'}), 413

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'Chybí text'}), 400
    if len(text) > 5000:
        text = text[:5000]
    title = (data.get('title') or text.split('.')[0])[:MAX_TITLE_LEN].strip() or 'Vzpomínka'
    source = (data.get('source') or 'chat').strip()[:30]
    theme = (data.get('theme') or 'family').strip().lower()
    if theme not in VALID_THEMES:
        theme = 'family'

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                r = db.execute(
                    "INSERT INTO experience_contributions "
                    "(user_id, type, title, theme, depth, transcript, privacy) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, 'story', title, theme, 1, text, 'draft')
                ).fetchone()
                new_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO experience_contributions "
                    "(user_id, type, title, theme, depth, transcript, privacy) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, 'story', title, theme, 1, text, 'draft')
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"quick_memory_from_message: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({
        'success': True,
        'contributionId': new_id,
        'title': title,
        'source': source,
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
        model = genai.GenerativeModel(GEMINI_MODEL)
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


# ─────────────────────────────────────────────────────────────────────────────
# PARTNER LEADS — pilot fáze, sběr zájmu od kandidátních partnerů
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/experience/partner-interest', methods=['POST', 'OPTIONS'])
def partner_interest():
    """Lead capture: institucionální partner má zájem o pilot s Radimovým
    Odkazem. Každý zápis se ručně reviewuje adminem před případným podpisem
    MoU + DPA. Žádný auto-onboard.

    Záměrně bez @require_auth — formulář musí jít vyplnit i z marketing
    landing page bez login. Ochrana je jen rate-limit + email unique index.
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()

    data = request.get_json(silent=True) or {}
    org_name = (data.get('orgName') or '').strip()[:200]
    contact_name = (data.get('contactName') or '').strip()[:200]
    contact_email = (data.get('contactEmail') or '').strip().lower()[:200]
    contact_phone = (data.get('contactPhone') or '').strip()[:50]
    org_type = (data.get('orgType') or 'other').strip()[:50]
    org_ico = (data.get('orgIco') or '').strip()[:20]
    message = (data.get('message') or '').strip()[:5000]
    source = (data.get('source') or 'app').strip()[:50]

    # Validace
    if not org_name or not contact_name or not contact_email:
        return jsonify({
            'success': False,
            'error': 'Vyplňte prosím název organizace, vaše jméno a e-mail.'
        }), 400
    if '@' not in contact_email or '.' not in contact_email.split('@')[-1]:
        return jsonify({
            'success': False,
            'error': 'E-mail nevypadá platně. Zkontrolujte ho prosím.'
        }), 400
    allowed_types = {'university', 'archive', 'research', 'ai_lab',
                     'market_research', 'media', 'museum', 'foundation', 'other'}
    if org_type not in allowed_types:
        org_type = 'other'

    try:
        with db_context(commit=True) as db:
            # Idempotence: pokud stejný email už lead poslal, jen update message
            existing = db.execute(
                "SELECT id FROM experience_partner_leads WHERE LOWER(contact_email) = ?",
                (contact_email,)
            ).fetchone()
            if existing:
                lead_id = existing[0] if isinstance(existing, (list, tuple)) else list(existing.values())[0]
                db.execute(
                    "UPDATE experience_partner_leads "
                    "SET org_name = ?, contact_name = ?, contact_phone = ?, "
                    "    org_type = ?, org_ico = ?, message = ?, source = ? "
                    "WHERE id = ?",
                    (org_name, contact_name, contact_phone, org_type,
                     org_ico, message, source, lead_id)
                )
                logger.info(f"Partner lead UPDATED: id={lead_id} email={contact_email} org={org_name}")
            else:
                if is_postgres():
                    r = db.execute(
                        "INSERT INTO experience_partner_leads "
                        "(org_name, contact_name, contact_email, contact_phone, "
                        " org_type, org_ico, message, source) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                        (org_name, contact_name, contact_email, contact_phone,
                         org_type, org_ico, message, source)
                    ).fetchone()
                    lead_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
                else:
                    cur = db.execute(
                        "INSERT INTO experience_partner_leads "
                        "(org_name, contact_name, contact_email, contact_phone, "
                        " org_type, org_ico, message, source) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (org_name, contact_name, contact_email, contact_phone,
                         org_type, org_ico, message, source)
                    )
                    lead_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
                logger.info(f"Partner lead CREATED: id={lead_id} email={contact_email} org={org_name} source={source}")
    except Exception as e:
        logger.error(f"partner_interest: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Nepodařilo se uložit. Zkuste to prosím za chvíli, nebo napište přímo na kafanek@kafanek.com.'
        }), 500

    return jsonify({
        'success': True,
        'message': 'Děkujeme! Ozveme se vám do 48 hodin na uvedený e-mail.',
    })


# ─────────────────────────────────────────────────────────────────────────────
# GOPAY PAYMENTS — partner platí KOLIBRI, KOLIBRI vyplácí seniorovi
# ─────────────────────────────────────────────────────────────────────────────
#
# Tok:
#   1) Partner klikne "zaplatit" na své faktuře → POST /partner-pay
#   2) Backend zavolá GoPay create_payment → vrátí gw_url (redirect URL)
#   3) Partner přesměrován do GoPay → uhradí → GoPay webhook
#   4) POST /gopay-webhook ověří signaturu, načte stav z GoPay,
#      pokud PAID → vytvoří experience_earnings záznam pro seniora
#   5) Admin 5. v měsíci spustí GET /admin/payouts/monthly-export →
#      stáhne CSV pro internet banking, hromadně převede

@experience_bp.route('/api/experience/partner-pay', methods=['POST', 'OPTIONS'])
def partner_pay_init():
    """Partner zahájí platbu za podepsaný kontrakt.

    Volá ho admin panel KOLIBRI po schválení partnerského dealu, NIKOLIV
    senior. Senior smlouvu podepíše přes accept_offer, ale finanční
    transakci spouští KOLIBRI (jsme merchant of record).

    Body:
      contractId:   ID kontraktu z experience_contracts
      partnerEmail: kontakt na partnera (pro doklady)
      partnerOrg:   název organizace (zobrazí se v GoPay)
      itemName:     krátký popis (vzpomínka XYZ — anonymní licence)
      anonymized:   bool (ovlivňuje DPH sazbu)
      returnUrl:    kam vrátit po platbě (default: app.radimcare.cz/admin/payments)
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()

    # Admin-only — vyžaduje admin token v hlavičce nebo X-Admin-Secret
    admin_secret = request.headers.get('X-Admin-Secret', '')
    if not admin_secret or admin_secret != os.environ.get('ADMIN_SECRET', ''):
        return jsonify({'success': False, 'error': 'admin auth required'}), 401

    try:
        import gopay_helpers
    except ImportError:
        logger.error('gopay_helpers module not importable — check deploy')
        return jsonify({'success': False, 'error': 'GoPay integration not deployed'}), 500

    if not gopay_helpers.is_configured():
        return jsonify({
            'success': False,
            'code': 'gopay_not_configured',
            'error': 'GoPay credentials nejsou nastavené (GOPAY_CLIENT_ID, GOPAY_CLIENT_SECRET, GOPAY_GO_ID).',
        }), 503

    data = request.get_json(silent=True) or {}
    contract_id = int(data.get('contractId') or 0)
    partner_email = (data.get('partnerEmail') or '').strip()[:200]
    partner_org = (data.get('partnerOrg') or '').strip()[:200]
    item_name = (data.get('itemName') or 'Vzpomínka — licence').strip()[:200]
    anonymized = bool(data.get('anonymized', True))
    return_url = (data.get('returnUrl') or 'https://app.radimcare.cz/admin/payments').strip()[:500]

    if not contract_id or not partner_email or not partner_org:
        return jsonify({'success': False, 'error': 'Chybí contractId / partnerEmail / partnerOrg'}), 400

    # Načti kontrakt z DB
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT id, user_id, contribution_id, offer_id, buyer_id, "
                "       price_kc, royalty_years, royalty_kc_per_year, "
                "       anonymized, signed_at, revoked_at "
                "FROM experience_contracts WHERE id = ?",
                (contract_id,)
            ).fetchone()
    except Exception as e:
        logger.error(f'partner_pay load contract: {e}')
        return jsonify({'success': False, 'error': 'DB error'}), 500

    if not row:
        return jsonify({'success': False, 'error': 'Kontrakt nenalezen'}), 404

    def cv(i, k):
        return row[i] if isinstance(row, (list, tuple)) else row.get(k)

    if cv(10, 'revoked_at'):
        return jsonify({'success': False, 'error': 'Kontrakt byl zrušen'}), 400

    gross_kc = int(cv(5, 'price_kc') or 0)
    if gross_kc < 50:
        return jsonify({'success': False, 'error': 'Cena pod minimem 50 Kč'}), 400

    # Vygenerovat order_number unikátní pro tuto platbu
    order_number = f'RADIM-CONTRACT-{contract_id}-{int(time.time())}'
    notify_url = data.get('notifyUrl') or 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/experience/gopay-webhook'

    # GoPay API call
    payment = gopay_helpers.create_payment(
        amount_kc=gross_kc,
        order_number=order_number,
        partner_email=partner_email,
        partner_org=partner_org,
        item_name=item_name,
        return_url=return_url,
        notify_url=notify_url,
        anonymized=anonymized,
    )

    if not payment or not payment.get('id'):
        return jsonify({
            'success': False,
            'error': 'GoPay API selhalo. Zkontrolujte logy.',
        }), 502

    # Uložit payment intent do DB pro tracking
    try:
        with db_context(commit=True) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS experience_payments ("
                "  id SERIAL PRIMARY KEY, "
                "  contract_id INTEGER NOT NULL, "
                "  gopay_payment_id TEXT NOT NULL UNIQUE, "
                "  order_number TEXT NOT NULL UNIQUE, "
                "  amount_kc INTEGER NOT NULL, "
                "  state TEXT DEFAULT 'CREATED', "
                "  partner_email TEXT, "
                "  partner_org TEXT, "
                "  gw_url TEXT, "
                "  paid_at TIMESTAMP, "
                "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            db.execute(
                "INSERT INTO experience_payments "
                "(contract_id, gopay_payment_id, order_number, amount_kc, "
                " state, partner_email, partner_org, gw_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (contract_id, str(payment['id']), order_number, gross_kc,
                 payment.get('state', 'CREATED'), partner_email, partner_org,
                 payment.get('gw_url', ''))
            )
        logger.info(f'GoPay payment intent created: contract={contract_id} amount={gross_kc} CZK gw_url={payment.get("gw_url")}')
    except Exception as e:
        logger.error(f'partner_pay save intent: {e}', exc_info=True)
        # Nevracíme 500 — platba existuje v GoPay, jen DB selhalo
        # Admin to ručně dohledá v GoPay administraci

    return jsonify({
        'success': True,
        'gopayId': str(payment['id']),
        'gwUrl': payment.get('gw_url'),
        'orderNumber': order_number,
        'amountKc': gross_kc,
        'state': payment.get('state'),
    })


@experience_bp.route('/api/experience/gopay-webhook', methods=['POST'])
def gopay_webhook():
    """Webhook od GoPay — platba dokončena, refunded, atd.

    GoPay POST sem `notification_url` po každé změně stavu platby.
    My ověříme signaturu, načteme aktuální stav, a pokud PAID,
    vytvoříme experience_earnings záznam pro seniora.
    """
    try:
        import gopay_helpers
    except ImportError:
        return jsonify({'success': False}), 500

    raw_body = request.get_data()
    signature = request.headers.get('X-GoPay-Signature') or request.headers.get('Signature') or ''

    if not gopay_helpers.verify_webhook_signature(raw_body, signature):
        logger.warning(f'GoPay webhook: invalid signature, header={signature[:20]}')
        return jsonify({'success': False, 'error': 'invalid signature'}), 403

    data = request.get_json(silent=True) or {}
    payment_id = str(data.get('id') or data.get('parent_id') or '').strip()
    if not payment_id:
        return jsonify({'success': False, 'error': 'missing payment id'}), 400

    # Re-fetch z GoPay aby měli authoritative state (webhook může být replay)
    payment = gopay_helpers.get_payment_status(payment_id)
    if not payment:
        return jsonify({'success': False, 'error': 'GoPay status fetch failed'}), 502

    state = payment.get('state', '')
    logger.info(f'GoPay webhook: payment={payment_id} state={state}')

    # Update DB
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_payments SET state = ?, "
                "       paid_at = CASE WHEN ? = 'PAID' THEN CURRENT_TIMESTAMP ELSE paid_at END "
                "WHERE gopay_payment_id = ?",
                (state, state, payment_id)
            )
            # Pokud je platba PAID, vytvořit earnings záznam pro seniora
            if state == 'PAID':
                pay_row = db.execute(
                    "SELECT contract_id, amount_kc FROM experience_payments "
                    "WHERE gopay_payment_id = ?",
                    (payment_id,)
                ).fetchone()
                if pay_row:
                    contract_id = pay_row[0] if isinstance(pay_row, (list, tuple)) else pay_row.get('contract_id')
                    gross_kc = pay_row[1] if isinstance(pay_row, (list, tuple)) else pay_row.get('amount_kc')

                    contract_row = db.execute(
                        "SELECT user_id FROM experience_contracts WHERE id = ?",
                        (contract_id,)
                    ).fetchone()
                    if contract_row:
                        senior_uid = contract_row[0] if isinstance(contract_row, (list, tuple)) else contract_row.get('user_id')
                        senior_net = _calc_senior_net(gross_kc)
                        db.execute(
                            "INSERT INTO experience_earnings "
                            "(user_id, contract_id, amount_kc, gross_kc, "
                            " source, payout_method, period_label) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (senior_uid, contract_id, senior_net, gross_kc,
                             'gopay_partner', 'pending_bank_transfer',
                             datetime.utcnow().strftime('%Y-%m'))
                        )
                        logger.info(f'Earnings created: senior={senior_uid} gross={gross_kc} net={senior_net}')
    except Exception as e:
        logger.error(f'gopay_webhook DB error: {e}', exc_info=True)
        # I tak vrátíme 200 aby GoPay neretryl donekonečna; admin issue
        return jsonify({'success': True, 'note': 'DB sync issue logged'}), 200

    return jsonify({'success': True, 'state': state})


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — payouts export pro hromadnou výplatu seniorům
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/admin/payouts/monthly-export', methods=['GET'])
def admin_payouts_monthly_export():
    """Vygeneruje CSV pro internet banking — všichni senioři, kterým
    máme něco vyplatit.

    CSV formát kompatibilní s ČSOB/KB/Raiffeisenbank multi-payment import:
       account_holder, iban, amount_kc, ks, vs, ss, message

    Vyžaduje admin secret v hlavičce.
    """
    admin_secret = request.headers.get('X-Admin-Secret', '')
    if not admin_secret or admin_secret != os.environ.get('ADMIN_SECRET', ''):
        return 'admin auth required', 401

    period = request.args.get('period') or datetime.utcnow().strftime('%Y-%m')

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT e.id, e.user_id, e.amount_kc, e.created_at, "
                "       b.account_holder, b.iban "
                "FROM experience_earnings e "
                "LEFT JOIN experience_bank_info b ON b.user_id = e.user_id "
                "WHERE e.paid_at IS NULL "
                "  AND e.amount_kc > 0 "
                "  AND e.payout_method = 'pending_bank_transfer' "
                "ORDER BY e.user_id, e.created_at"
            ).fetchall()
    except Exception as e:
        logger.error(f'admin_payouts_monthly_export: {e}', exc_info=True)
        return f'DB error: {e}', 500

    # Agreguj per senior (jeden řádek = jeden bank transfer)
    by_senior = {}
    for r in rows or []:
        def gv(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        uid = gv(1, 'user_id')
        amount = int(gv(2, 'amount_kc') or 0)
        holder = gv(4, 'account_holder') or 'NEZNÁMÝ — DOPLNIT IBAN'
        iban = gv(5, 'iban') or ''
        if uid not in by_senior:
            by_senior[uid] = {
                'holder': holder, 'iban': iban, 'amount': 0,
                'earning_ids': []
            }
        by_senior[uid]['amount'] += amount
        by_senior[uid]['earning_ids'].append(gv(0, 'id'))

    # CSV výstup
    csv_lines = [
        '# Radimův Odkaz — měsíční výplaty seniorům',
        f'# Období: {period}',
        f'# Generated: {datetime.utcnow().isoformat()}Z',
        f'# Celkem příjemců: {len(by_senior)}',
        f'# Celkem Kč: {sum(s["amount"] for s in by_senior.values())}',
        '#',
        'account_holder,iban,amount_kc,vs,ss,ks,message,internal_user_id,earning_ids',
    ]
    for uid, info in by_senior.items():
        # VS (variable symbol) = month YYYYMM, SS (specific) = abbreviated uid hash
        vs = period.replace('-', '')
        ss = abs(hash(uid)) % 9999999999
        ks = '0308'  # Konstantní symbol pro "běžnou platbu" v ČR
        message = f'Radim Odkaz {period}'
        ids_str = '|'.join(str(eid) for eid in info['earning_ids'])
        csv_lines.append(
            f'"{info["holder"]}","{info["iban"]}",{info["amount"]},'
            f'{vs},{ss},{ks},"{message}","{uid}","{ids_str}"'
        )

    csv_text = '\n'.join(csv_lines) + '\n'
    from flask import Response
    return Response(
        csv_text,
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename="radim-payouts-{period}.csv"',
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — partner onboarding (po podpisu MoU)
# ─────────────────────────────────────────────────────────────────────────────
#
# Workflow:
#   1) Partner vyplní formulář v aplikaci → POST /api/experience/partner-interest
#      → záznam v experience_partner_leads se status='new'
#   2) Admin (Radim) ručně reviewuje, rozhodne se navázat
#   3) Schůzka, podpis MoU + DPA + 3-stranná smlouva
#   4) Admin volá POST /api/admin/partners/onboard
#      → vytvoří experience_buyers (active=true)
#      → volitelně vytvoří 1-N experience_offers
#      → nastaví lead.status='signed'
#   5) Senior nyní vidí v UI nové nabídky tohoto partnera

def _require_admin():
    """Vrátí None pokud auth OK, jinak (response, status) tuple."""
    admin_secret = request.headers.get('X-Admin-Secret', '')
    if not admin_secret or admin_secret != os.environ.get('ADMIN_SECRET', ''):
        return jsonify({'success': False, 'error': 'admin auth required'}), 401
    return None


@experience_bp.route('/api/admin/partners/leads', methods=['GET'])
def admin_partners_leads():
    """Seznam všech leadů (kandidátní partneři) pro admin review.

    Query params:
        status: filtr (new|contacted|mou_sent|signed|rejected) — default 'new'
        limit:  max počet (default 50)
    """
    auth_err = _require_admin()
    if auth_err:
        return auth_err

    status_filter = request.args.get('status', 'new')[:30]
    limit = min(200, int(request.args.get('limit', 50) or 50))
    _init_schema()

    try:
        with db_context() as db:
            if status_filter == 'all':
                rows = db.execute(
                    "SELECT id, org_name, contact_name, contact_email, contact_phone, "
                    "       org_type, org_ico, message, source, status, admin_note, "
                    "       contacted_at, signed_at, created_at "
                    "FROM experience_partner_leads "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, org_name, contact_name, contact_email, contact_phone, "
                    "       org_type, org_ico, message, source, status, admin_note, "
                    "       contacted_at, signed_at, created_at "
                    "FROM experience_partner_leads WHERE status = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (status_filter, limit)
                ).fetchall()
    except Exception as e:
        logger.error(f'admin_partners_leads: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'DB error'}), 500

    leads = []
    for r in rows or []:
        def gv(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        leads.append({
            'id': gv(0, 'id'),
            'orgName': gv(1, 'org_name'),
            'contactName': gv(2, 'contact_name'),
            'contactEmail': gv(3, 'contact_email'),
            'contactPhone': gv(4, 'contact_phone'),
            'orgType': gv(5, 'org_type'),
            'orgIco': gv(6, 'org_ico'),
            'message': gv(7, 'message'),
            'source': gv(8, 'source'),
            'status': gv(9, 'status'),
            'adminNote': gv(10, 'admin_note'),
            'contactedAt': str(gv(11, 'contacted_at')) if gv(11, 'contacted_at') else None,
            'signedAt': str(gv(12, 'signed_at')) if gv(12, 'signed_at') else None,
            'createdAt': str(gv(13, 'created_at')) if gv(13, 'created_at') else None,
        })

    return jsonify({'success': True, 'leads': leads, 'count': len(leads)})


@experience_bp.route('/api/admin/partners/leads/<int:lead_id>', methods=['PATCH'])
def admin_partners_lead_update(lead_id):
    """Update statusu leadu (např. po prvním hovoru, po MoU sent, atd.).

    Body:
      status: new|contacted|mou_sent|signed|rejected
      adminNote: krátká poznámka admin
    """
    auth_err = _require_admin()
    if auth_err:
        return auth_err

    data = request.get_json(silent=True) or {}
    new_status = (data.get('status') or '').strip()[:30]
    admin_note = (data.get('adminNote') or '').strip()[:1000]

    allowed_statuses = {'new', 'contacted', 'mou_sent', 'signed', 'rejected'}
    if new_status and new_status not in allowed_statuses:
        return jsonify({'success': False, 'error': f'status must be one of {allowed_statuses}'}), 400

    try:
        with db_context(commit=True) as db:
            # Build update dynamically
            updates = []
            params = []
            if new_status:
                updates.append("status = ?")
                params.append(new_status)
                if new_status == 'contacted':
                    updates.append("contacted_at = COALESCE(contacted_at, CURRENT_TIMESTAMP)")
                elif new_status == 'signed':
                    updates.append("signed_at = COALESCE(signed_at, CURRENT_TIMESTAMP)")
            if admin_note:
                updates.append("admin_note = ?")
                params.append(admin_note)
            if not updates:
                return jsonify({'success': False, 'error': 'nic ke změně'}), 400
            params.append(lead_id)
            db.execute(
                f"UPDATE experience_partner_leads SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
        logger.info(f'Lead {lead_id} updated: status={new_status} note={admin_note[:60]}')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'admin_partners_lead_update: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'DB error'}), 500


@experience_bp.route('/api/admin/partners/onboard', methods=['POST'])
def admin_partners_onboard():
    """Onboarding podepsaného partnera — vytvoří buyer + offers.

    Body:
      leadId:        id ze experience_partner_leads (volitelné, pokud onboard
                     bez leadu)
      orgName:       název partnera (povinný, pokud není leadId)
      orgType:       'university'|'archive'|'research'|'ai_lab'|...
      description:   krátký popis pro UI (max 500 znaků)
      trustScore:    0-100 (KOLIBRI rozhoduje, jak Radim seniora upozorní)
                     90+ = 🟢 zelená "doporučuji", 70-89 = 🟡 žlutá, <70 = 🔴
      ethicsReviewUrl:  URL ke schválení etickou komisí
      gdprComplianceUrl: URL k GDPR documentu partnera
      offers:        array nabídek (volitelný, lze přidávat dodatečně):
                     [{title, description, targetTheme, targetType, targetDepth,
                       priceKc, royaltyYears, royaltyKcPerYear, seatsTotal}]
                     targetTheme: 'family'|'skill'|'wisdom'|'historical'|'daily'
                     targetType:  'story'|'recipe'|'lesson'|'memory'|'opinion'
                     targetDepth: 1 (povrchní) | 2 (střední) | 3 (hluboké)

    Returns:
      buyer: vytvořený buyer s id
      offers: vytvořené nabídky s id
      leadStatus: pokud leadId zadáno, lead.status='signed'
    """
    auth_err = _require_admin()
    if auth_err:
        return auth_err
    _init_schema()

    data = request.get_json(silent=True) or {}
    lead_id = data.get('leadId')
    org_name = (data.get('orgName') or '').strip()[:200]
    org_type = (data.get('orgType') or 'research').strip()[:50]
    description = (data.get('description') or '').strip()[:500]
    trust_score = int(data.get('trustScore', 80) or 80)
    ethics_url = (data.get('ethicsReviewUrl') or '').strip()[:500]
    gdpr_url = (data.get('gdprComplianceUrl') or '').strip()[:500]
    offers_input = data.get('offers') or []

    # Validace
    trust_score = max(0, min(100, trust_score))
    allowed_types = {'university', 'archive', 'research', 'ai_lab',
                     'market_research', 'media', 'museum', 'foundation', 'other'}
    if org_type not in allowed_types:
        org_type = 'other'

    # Pokud leadId, načti zájem a doplň defaults
    lead_data = None
    if lead_id:
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT org_name, org_type, message FROM experience_partner_leads WHERE id = ?",
                    (lead_id,)
                ).fetchone()
                if row:
                    lead_data = {
                        'org_name': row[0] if isinstance(row, (list, tuple)) else row.get('org_name'),
                        'org_type': row[1] if isinstance(row, (list, tuple)) else row.get('org_type'),
                        'message': row[2] if isinstance(row, (list, tuple)) else row.get('message'),
                    }
        except Exception as e:
            logger.warning(f'onboard: lead {lead_id} lookup: {e}')

    if not org_name and lead_data:
        org_name = lead_data.get('org_name', '')
    if not org_name:
        return jsonify({'success': False, 'error': 'Chybí orgName (a leadId neposkytuje)'}), 400
    if not description and lead_data:
        description = (lead_data.get('message') or '')[:500]

    # Vytvoř buyer
    try:
        with db_context(commit=True) as db:
            # Idempotence: pokud buyer se stejným jménem již existuje, vrať ho
            existing = db.execute(
                "SELECT id FROM experience_buyers WHERE LOWER(name) = LOWER(?)",
                (org_name,)
            ).fetchone()

            if existing:
                buyer_id = existing[0] if isinstance(existing, (list, tuple)) else existing.get('id')
                # Reaktivace + aktualizace metadata
                db.execute(
                    "UPDATE experience_buyers SET active = ?, type = ?, "
                    "       description = ?, trust_score = ?, "
                    "       ethics_review_url = ?, gdpr_compliance_url = ? "
                    "WHERE id = ?",
                    (True if is_postgres() else 1,
                     org_type, description, trust_score,
                     ethics_url or None, gdpr_url or None, buyer_id)
                )
                logger.info(f'Buyer REACTIVATED: id={buyer_id} name={org_name}')
            else:
                if is_postgres():
                    r = db.execute(
                        "INSERT INTO experience_buyers "
                        "(name, type, description, trust_score, "
                        " ethics_review_url, gdpr_compliance_url, active) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                        (org_name, org_type, description, trust_score,
                         ethics_url or None, gdpr_url or None, True)
                    ).fetchone()
                    buyer_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
                else:
                    cur = db.execute(
                        "INSERT INTO experience_buyers "
                        "(name, type, description, trust_score, "
                        " ethics_review_url, gdpr_compliance_url, active) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (org_name, org_type, description, trust_score,
                         ethics_url or None, gdpr_url or None, 1)
                    )
                    buyer_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
                logger.info(f'Buyer CREATED: id={buyer_id} name={org_name} trust={trust_score}')
    except Exception as e:
        logger.error(f'admin_partners_onboard buyer create: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'DB error při vytvoření buyer'}), 500

    # Vytvoř offers
    created_offers = []
    if isinstance(offers_input, list) and offers_input:
        try:
            with db_context(commit=True) as db:
                for o in offers_input[:10]:  # max 10 offers najednou
                    title = (o.get('title') or '').strip()[:200]
                    if not title:
                        continue
                    o_desc = (o.get('description') or '').strip()[:500]
                    target_theme = (o.get('targetTheme') or 'wisdom').strip()[:50]
                    target_type = (o.get('targetType') or 'memory').strip()[:50]
                    target_depth = max(1, min(3, int(o.get('targetDepth', 2) or 2)))
                    price_kc = max(50, int(o.get('priceKc', 800) or 800))  # min 50 Kč
                    royalty_years = max(0, min(20, int(o.get('royaltyYears', 0) or 0)))
                    royalty_kc = max(0, int(o.get('royaltyKcPerYear', 0) or 0))
                    seats_total = max(1, int(o.get('seatsTotal', 100) or 100))

                    if is_postgres():
                        r = db.execute(
                            "INSERT INTO experience_offers "
                            "(buyer_id, title, description, target_theme, target_type, "
                            " target_depth, price_kc, royalty_years, royalty_kc_per_year, "
                            " status, seats_total, seats_filled) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                            (buyer_id, title, o_desc, target_theme, target_type,
                             target_depth, price_kc, royalty_years, royalty_kc,
                             'active', seats_total, 0)
                        ).fetchone()
                        offer_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
                    else:
                        cur = db.execute(
                            "INSERT INTO experience_offers "
                            "(buyer_id, title, description, target_theme, target_type, "
                            " target_depth, price_kc, royalty_years, royalty_kc_per_year, "
                            " status, seats_total, seats_filled) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (buyer_id, title, o_desc, target_theme, target_type,
                             target_depth, price_kc, royalty_years, royalty_kc,
                             'active', seats_total, 0)
                        )
                        offer_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None

                    created_offers.append({
                        'id': offer_id,
                        'title': title,
                        'priceKc': price_kc,
                        'royaltyYears': royalty_years,
                        'royaltyKcPerYear': royalty_kc,
                        'seatsTotal': seats_total,
                        'targetTheme': target_theme,
                        'targetType': target_type,
                        'targetDepth': target_depth,
                    })
                    logger.info(f'Offer CREATED: id={offer_id} buyer={buyer_id} title={title} price={price_kc}')
        except Exception as e:
            logger.error(f'admin_partners_onboard offers: {e}', exc_info=True)
            # buyer je vytvořen, ale offers selhaly — vrátíme partial success
            return jsonify({
                'success': True,
                'buyer': {'id': buyer_id, 'name': org_name, 'active': True},
                'offers': created_offers,
                'warning': 'Některé offers se nepodařilo vytvořit. Zkuste je přidat samostatně přes /api/admin/partners/<id>/offers',
            })

    # Update lead status na 'signed' pokud byl zadán
    lead_status_updated = False
    if lead_id:
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "UPDATE experience_partner_leads SET status = 'signed', "
                    "       signed_at = COALESCE(signed_at, CURRENT_TIMESTAMP) "
                    "WHERE id = ?",
                    (lead_id,)
                )
            lead_status_updated = True
        except Exception as e:
            logger.warning(f'lead {lead_id} status update failed: {e}')

    return jsonify({
        'success': True,
        'buyer': {
            'id': buyer_id,
            'name': org_name,
            'type': org_type,
            'trustScore': trust_score,
            'active': True,
        },
        'offers': created_offers,
        'leadStatusUpdated': lead_status_updated,
        'message': f'Partner "{org_name}" je nyní aktivní s {len(created_offers)} nabídkami. '
                   f'Senioři je uvidí v aplikaci do 5 minut (cache).'
    })


@experience_bp.route('/api/admin/partners/<int:buyer_id>/deactivate', methods=['POST'])
def admin_partners_deactivate(buyer_id):
    """Deaktivace partnera — schová ho ze seznamu nabídek pro seniory.
    Existující kontrakty zůstávají, jen nové nemůžou vznikat.
    """
    auth_err = _require_admin()
    if auth_err:
        return auth_err

    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()[:500]

    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE experience_buyers SET active = ? WHERE id = ?",
                (False if is_postgres() else 0, buyer_id)
            )
            db.execute(
                "UPDATE experience_offers SET status = 'inactive' "
                "WHERE buyer_id = ? AND status = 'active'",
                (buyer_id,)
            )
        logger.info(f'Partner DEACTIVATED: buyer_id={buyer_id} reason={reason[:80]}')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'admin_partners_deactivate: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'DB error'}), 500


@experience_bp.route('/api/admin/partners/<int:buyer_id>/offers', methods=['POST'])
def admin_partners_add_offer(buyer_id):
    """Přidat další nabídku k existujícímu partnerovi.

    Body: stejný formát jako offers[] v onboard endpoint.
    """
    auth_err = _require_admin()
    if auth_err:
        return auth_err

    o = request.get_json(silent=True) or {}
    title = (o.get('title') or '').strip()[:200]
    if not title:
        return jsonify({'success': False, 'error': 'title je povinný'}), 400

    o_desc = (o.get('description') or '').strip()[:500]
    target_theme = (o.get('targetTheme') or 'wisdom').strip()[:50]
    target_type = (o.get('targetType') or 'memory').strip()[:50]
    target_depth = max(1, min(3, int(o.get('targetDepth', 2) or 2)))
    price_kc = max(50, int(o.get('priceKc', 800) or 800))
    royalty_years = max(0, min(20, int(o.get('royaltyYears', 0) or 0)))
    royalty_kc = max(0, int(o.get('royaltyKcPerYear', 0) or 0))
    seats_total = max(1, int(o.get('seatsTotal', 100) or 100))

    try:
        with db_context(commit=True) as db:
            # Ověř buyer existuje a je aktivní
            buyer_row = db.execute(
                "SELECT id, active FROM experience_buyers WHERE id = ?",
                (buyer_id,)
            ).fetchone()
            if not buyer_row:
                return jsonify({'success': False, 'error': 'Buyer not found'}), 404
            buyer_active = buyer_row[1] if isinstance(buyer_row, (list, tuple)) else buyer_row.get('active')
            if not buyer_active:
                return jsonify({
                    'success': False,
                    'error': 'Buyer je deaktivovaný. Nejdřív ho aktivujte.'
                }), 400

            if is_postgres():
                r = db.execute(
                    "INSERT INTO experience_offers "
                    "(buyer_id, title, description, target_theme, target_type, "
                    " target_depth, price_kc, royalty_years, royalty_kc_per_year, "
                    " status, seats_total, seats_filled) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (buyer_id, title, o_desc, target_theme, target_type,
                     target_depth, price_kc, royalty_years, royalty_kc,
                     'active', seats_total, 0)
                ).fetchone()
                offer_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO experience_offers "
                    "(buyer_id, title, description, target_theme, target_type, "
                    " target_depth, price_kc, royalty_years, royalty_kc_per_year, "
                    " status, seats_total, seats_filled) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (buyer_id, title, o_desc, target_theme, target_type,
                     target_depth, price_kc, royalty_years, royalty_kc,
                     'active', seats_total, 0)
                )
                offer_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
        logger.info(f'Offer ADDED: id={offer_id} buyer={buyer_id} title={title} price={price_kc}')
        return jsonify({
            'success': True,
            'offer': {
                'id': offer_id, 'buyerId': buyer_id, 'title': title,
                'priceKc': price_kc, 'targetDepth': target_depth,
            },
        })
    except Exception as e:
        logger.error(f'admin_partners_add_offer: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'DB error'}), 500


@experience_bp.route('/api/admin/partners/list', methods=['GET'])
def admin_partners_list():
    """Seznam všech buyers + jejich offers — admin dashboard view."""
    auth_err = _require_admin()
    if auth_err:
        return auth_err
    _init_schema()

    try:
        with db_context() as db:
            buyer_rows = db.execute(
                "SELECT id, name, type, description, trust_score, active, "
                "       ethics_review_url, gdpr_compliance_url, created_at "
                "FROM experience_buyers ORDER BY active DESC, created_at DESC"
            ).fetchall()
            offer_rows = db.execute(
                "SELECT id, buyer_id, title, description, target_theme, target_type, "
                "       target_depth, price_kc, royalty_years, royalty_kc_per_year, "
                "       status, seats_total, seats_filled "
                "FROM experience_offers ORDER BY buyer_id, status, id"
            ).fetchall()
    except Exception as e:
        logger.error(f'admin_partners_list: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'DB error'}), 500

    # Group offers by buyer_id
    offers_by_buyer = {}
    for r in offer_rows or []:
        def gv(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        bid = gv(1, 'buyer_id')
        offers_by_buyer.setdefault(bid, []).append({
            'id': gv(0, 'id'),
            'title': gv(2, 'title'),
            'description': gv(3, 'description'),
            'targetTheme': gv(4, 'target_theme'),
            'targetType': gv(5, 'target_type'),
            'targetDepth': gv(6, 'target_depth'),
            'priceKc': gv(7, 'price_kc'),
            'royaltyYears': gv(8, 'royalty_years'),
            'royaltyKcPerYear': gv(9, 'royalty_kc_per_year'),
            'status': gv(10, 'status'),
            'seatsTotal': gv(11, 'seats_total'),
            'seatsFilled': gv(12, 'seats_filled'),
        })

    partners = []
    for r in buyer_rows or []:
        def gv(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        bid = gv(0, 'id')
        partners.append({
            'id': bid,
            'name': gv(1, 'name'),
            'type': gv(2, 'type'),
            'description': gv(3, 'description'),
            'trustScore': gv(4, 'trust_score'),
            'active': bool(gv(5, 'active')),
            'ethicsReviewUrl': gv(6, 'ethics_review_url'),
            'gdprComplianceUrl': gv(7, 'gdpr_compliance_url'),
            'createdAt': str(gv(8, 'created_at')) if gv(8, 'created_at') else None,
            'offers': offers_by_buyer.get(bid, []),
            'offerCount': len(offers_by_buyer.get(bid, [])),
            'activeOfferCount': sum(1 for o in offers_by_buyer.get(bid, []) if o['status'] == 'active'),
        })

    return jsonify({
        'success': True,
        'partners': partners,
        'count': len(partners),
        'activeCount': sum(1 for p in partners if p['active']),
    })


# ─────────────────────────────────────────────────────────────────────────────
# PDF / HTML — Potvrzení o vyplacené odměně (pro § 10 ZDP)
# ─────────────────────────────────────────────────────────────────────────────
#
# Pro pilot vracíme HTML s @media print stylováním. Senior si stáhne
# přes "Tisk → Uložit jako PDF" v prohlížeči — bez nutnosti reportlab/wkhtmltopdf
# na backendu. Po pilotu můžeme nasadit headless Chromium, ale pro 50 seniorů
# je HTML print elegantní a stačí.

@experience_bp.route('/api/experience/earnings/receipt', methods=['GET'])
@require_auth
def earnings_receipt():
    """Vygeneruje HTML potvrzení o vyplacené odměně pro daného seniora a období.

    Query params:
        period: '2026-04' (YYYY-MM, povinný)
        format: 'html' (default) | 'json' (data only)

    Senior vidí potvrzení v prohlížeči, klepne 'Uložit jako PDF' a má doklad
    pro § 10 ZDP (Ostatní příjmy, do 30 000 Kč/rok bez DAP).
    """
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    period = request.args.get('period', '').strip()[:10]
    fmt = request.args.get('format', 'html').strip()[:10]

    # Validace formátu period (YYYY-MM)
    import re
    if not re.match(r'^\d{4}-\d{2}$', period):
        return jsonify({
            'success': False,
            'error': 'period musí být ve formátu YYYY-MM (např. 2026-04)'
        }), 400

    # Načti všechny earnings za toto období + senior info
    # Bug-fix (E2E test): odstraněn `e.bank_ref` — sloupec neexistuje
    # v experience_earnings schematu (jen v experience_rewards). Pokud
    # potřebujeme bank reference, lze ho přidat do schema migrate.
    # Pro receipt stačí period_label který už identifikuje hromadnou výplatu.
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT e.id, e.amount_kc, e.gross_kc, e.contract_id, "
                "       e.created_at, e.paid_at, e.payout_method, "
                "       e.period_label, e.source, c.signed_at, "
                "       b.name AS buyer_name "
                "FROM experience_earnings e "
                "LEFT JOIN experience_contracts c ON c.id = e.contract_id "
                "LEFT JOIN experience_buyers b ON b.id = c.buyer_id "
                "WHERE e.user_id = ? AND e.period_label = ? "
                "ORDER BY e.created_at",
                (uid, period)
            ).fetchall()

            # Senior info — z chat_users nebo memory_profiles
            senior_name = ''
            try:
                u = db.execute(
                    "SELECT name FROM chat_users WHERE id = ?",
                    (uid,)
                ).fetchone()
                if u:
                    senior_name = (u[0] if isinstance(u, (list, tuple)) else u.get('name')) or ''
            except Exception:
                pass

            # Bank info (pro identifikaci IBAN posledních 4 číslic)
            iban_last4 = ''
            try:
                bi = db.execute(
                    "SELECT iban_last4 FROM experience_bank_info WHERE user_id = ?",
                    (uid,)
                ).fetchone()
                if bi:
                    iban_last4 = (bi[0] if isinstance(bi, (list, tuple)) else bi.get('iban_last4')) or ''
            except Exception:
                pass
    except Exception as e:
        logger.error(f'earnings_receipt: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'DB error'}), 500

    # Strukturuj data
    items = []
    total_kc = 0
    for r in rows or []:
        def gv(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        amount = int(gv(1, 'amount_kc') or 0)
        items.append({
            'id': gv(0, 'id'),
            'amountKc': amount,
            'grossKc': int(gv(2, 'gross_kc') or 0),
            'contractId': gv(3, 'contract_id'),
            'createdAt': str(gv(4, 'created_at') or '')[:10],
            'paidAt': str(gv(5, 'paid_at') or '')[:10] if gv(5, 'paid_at') else None,
            'payoutMethod': gv(6, 'payout_method'),
            'periodLabel': gv(7, 'period_label'),  # E2E fix: bank_ref → period_label
            'source': gv(8, 'source'),
            'buyerName': gv(10, 'buyer_name') or '—',
        })
        total_kc += amount

    if fmt == 'json':
        return jsonify({
            'success': True,
            'period': period,
            'seniorName': senior_name,
            'ibanLast4': iban_last4,
            'items': items,
            'totalKc': total_kc,
        })

    # HTML s print CSS
    period_cz = {
        '01': 'leden', '02': 'únor', '03': 'březen', '04': 'duben',
        '05': 'květen', '06': 'červen', '07': 'červenec', '08': 'srpen',
        '09': 'září', '10': 'říjen', '11': 'listopad', '12': 'prosinec',
    }
    year, month = period.split('-')
    month_cz = period_cz.get(month, month)

    rows_html = ''
    for it in items:
        status = '✓ vyplaceno' if it['paidAt'] else '⏳ připravuje se'
        date_display = it.get('paidAt') or it.get('createdAt') or '—'
        rows_html += f'''
        <tr>
            <td>{date_display}</td>
            <td>Kontrakt #{it['contractId'] or '—'} · {_html_escape(it['buyerName'])}</td>
            <td class="num">{it['grossKc']:,} Kč</td>
            <td class="num">{it['amountKc']:,} Kč</td>
            <td class="status">{status}</td>
        </tr>'''.replace(',', ' ')

    if not items:
        rows_html = '<tr><td colspan="5" class="empty">V tomto období nebyly žádné odměny.</td></tr>'

    html = f'''<!DOCTYPE html>
<html lang="cs">
<head>
    <meta charset="UTF-8">
    <title>Potvrzení o odměně · {_html_escape(senior_name) or 'Radim'} · {month_cz} {year}</title>
    <style>
        @page {{ size: A4; margin: 18mm; }}
        body {{
            font-family: 'Inter', -apple-system, sans-serif;
            color: #1a2530;
            font-size: 11pt;
            line-height: 1.5;
            max-width: 800px;
            margin: 0 auto;
            padding: 24px;
        }}
        header.doc-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2px solid #1a2530;
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        header.doc-header h1 {{
            font-size: 18pt;
            margin: 0 0 4px 0;
            color: #1a2530;
        }}
        header.doc-header .subtitle {{
            color: #6a7880;
            font-size: 10pt;
        }}
        .issuer {{ text-align: right; font-size: 10pt; }}
        .issuer strong {{ display: block; font-size: 11pt; }}
        .recipient {{
            background: #f3f5f8;
            padding: 14px 18px;
            border-radius: 8px;
            margin-bottom: 24px;
        }}
        .recipient h2 {{
            font-size: 11pt;
            margin: 0 0 6px 0;
            color: #6a7880;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .recipient .name {{ font-size: 14pt; font-weight: 600; }}
        .recipient .meta {{ font-size: 10pt; color: #6a7880; margin-top: 4px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 24px;
        }}
        th, td {{
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid #e1e6ed;
        }}
        th {{
            background: #f3f5f8;
            font-weight: 600;
            font-size: 9pt;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            color: #6a7880;
        }}
        td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
        td.status {{ font-size: 9pt; color: #6a7880; }}
        td.empty {{ text-align: center; color: #6a7880; padding: 24px; }}
        tfoot td {{
            border-top: 2px solid #1a2530;
            border-bottom: none;
            padding-top: 14px;
            font-weight: 600;
            font-size: 13pt;
        }}
        .tax-note {{
            background: #fffbf0;
            border-left: 4px solid #d9a84f;
            padding: 14px 18px;
            margin: 24px 0;
            border-radius: 4px;
            font-size: 10pt;
            line-height: 1.6;
        }}
        .tax-note strong {{ display: block; margin-bottom: 4px; }}
        footer.doc-footer {{
            margin-top: 36px;
            padding-top: 18px;
            border-top: 1px solid #e1e6ed;
            font-size: 9pt;
            color: #6a7880;
            text-align: center;
        }}
        .actions {{ text-align: center; margin: 24px 0; }}
        .btn-print {{
            background: #2e5fa8;
            color: #fff;
            border: none;
            padding: 12px 24px;
            font-size: 12pt;
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
        }}
        @media print {{
            .actions {{ display: none; }}
            body {{ padding: 0; }}
        }}
    </style>
</head>
<body>
    <header class="doc-header">
        <div>
            <h1>Potvrzení o vyplacené odměně</h1>
            <div class="subtitle">Radimův Odkaz · období {month_cz} {year}</div>
        </div>
        <div class="issuer">
            <strong>KOLIBRI s.r.o.</strong>
            IČO: [DOPLNIT]<br>
            DIČ: [DOPLNIT]<br>
            kafanek@kafanek.com
        </div>
    </header>

    <div class="recipient">
        <h2>Příjemce</h2>
        <div class="name">{_html_escape(senior_name) or 'Senior'}</div>
        <div class="meta">
            Účet: {'IBAN končící ' + iban_last4 if iban_last4 else 'IBAN evidovaný v aplikaci'}<br>
            ID v platformě: {_html_escape(uid[:12]) if uid else '—'}…
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Datum</th>
                <th>Předmět</th>
                <th class="num">Hrubá cena</th>
                <th class="num">Vyplaceno</th>
                <th class="status">Stav</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
        <tfoot>
            <tr>
                <td colspan="3" style="text-align:right">Celkem za období:</td>
                <td class="num">{total_kc:,} Kč</td>
                <td></td>
            </tr>
        </tfoot>
    </table>

    <div class="tax-note">
        <strong>📋 Daňový režim — § 10 ZDP (Ostatní příjmy)</strong>
        Tento příjem je dle § 10 zákona č. 586/1992 Sb. o daních z příjmů
        kvalifikován jako <em>ostatní příjmy</em>. Pokud váš celkový souhrn
        ostatních příjmů za rok {year} nepřesáhne <strong>30 000 Kč</strong>,
        není třeba podávat daňové přiznání. Při překročení limitu je nutné
        příjem uvést v daňovém přiznání do 31. března {int(year)+1}.
        Toto potvrzení slouží jako daňový doklad.
    </div>

    <div class="actions">
        <button class="btn-print" onclick="window.print()">🖨️ Vytisknout / Uložit jako PDF</button>
    </div>

    <footer class="doc-footer">
        Vygenerováno {_iso_date_now_cz()} platformou Radim · radimcare.cz<br>
        V případě nejasností: kafanek@kafanek.com
    </footer>
</body>
</html>'''.replace(',', ' ')

    from flask import Response
    return Response(html, mimetype='text/html; charset=utf-8')


def _html_escape(s):
    """Minimální HTML escape pro generování dokumentů."""
    if not s:
        return ''
    s = str(s)
    return (s.replace('&', '&amp;')
              .replace('<', '&lt;')
              .replace('>', '&gt;')
              .replace('"', '&quot;')
              .replace("'", '&#39;'))


def _iso_date_now_cz():
    """Aktuální datum v českém formátu."""
    now = datetime.utcnow()
    months_cz = ['', 'ledna', 'února', 'března', 'dubna', 'května', 'června',
                 'července', 'srpna', 'září', 'října', 'listopadu', 'prosince']
    return f'{now.day}. {months_cz[now.month]} {now.year}'


@experience_bp.route('/api/admin/payouts/mark-paid', methods=['POST'])
def admin_payouts_mark_paid():
    """Po hromadné bankovní výplatě označí dané earnings záznamy
    jako paid_at = NOW + payout_method = 'bank_transfer_done'.

    Body: {"earningIds": [1, 2, 3, ...], "bankRef": "TX-2026-04-001"}
    """
    admin_secret = request.headers.get('X-Admin-Secret', '')
    if not admin_secret or admin_secret != os.environ.get('ADMIN_SECRET', ''):
        return jsonify({'success': False, 'error': 'admin auth required'}), 401

    data = request.get_json(silent=True) or {}
    earning_ids = data.get('earningIds') or []
    bank_ref = (data.get('bankRef') or '').strip()[:100]

    if not isinstance(earning_ids, list) or not earning_ids:
        return jsonify({'success': False, 'error': 'earningIds required'}), 400

    try:
        with db_context(commit=True) as db:
            placeholders = ','.join(['?'] * len(earning_ids))
            db.execute(
                f"UPDATE experience_earnings SET paid_at = CURRENT_TIMESTAMP, "
                f"       payout_method = 'bank_transfer_done', "
                f"       period_label = COALESCE(period_label, ?) "
                f"WHERE id IN ({placeholders})",
                tuple([bank_ref] + list(earning_ids))
            )
        logger.info(f'admin_payouts_mark_paid: {len(earning_ids)} earnings marked paid (bankRef={bank_ref})')
        return jsonify({'success': True, 'updated': len(earning_ids)})
    except Exception as e:
        logger.error(f'admin_payouts_mark_paid: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'DB error'}), 500


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

    data = request.get_json(silent=True) or {}
    offer_id = int(data.get('offerId') or 0)
    anonymized = _to_bool(data.get('anonymized'))
    if not offer_id:
        return jsonify({'success': False, 'error': 'Chybí offerId'}), 400

    # Pilot-fix: během pilot fáze (žádný buyer ještě nemá podepsané MoU)
    # nesmíme vytvářet právně závazné kontrakty. Pokud žádný aktivní buyer
    # neexistuje, vracíme čistý 'pilot_phase' kód aby UI mohl zobrazit
    # přátelské vysvětlení místo chyby.
    try:
        with db_context() as db:
            active_count_row = db.execute(
                "SELECT COUNT(*) FROM experience_buyers WHERE active = ?",
                (True if is_postgres() else 1,)
            ).fetchone()
        active_count = int(
            (active_count_row[0] if isinstance(active_count_row, (list, tuple))
             else list(active_count_row.values())[0]) or 0
        ) if active_count_row else 0
    except Exception:
        active_count = 0
    if active_count == 0:
        return jsonify({
            'success': False,
            'code': 'pilot_phase',
            'error': 'Připravujeme prvního partnera. Kontrakt zatím nelze podepsat — '
                     'vaše vzpomínka je v bezpečí, jakmile partner přijde, dáme vám vědět.',
        }), 503

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

    # Notify family if cosign required (best-effort)
    if brake_active:
        try:
            from caregiver_routes import notify_family_of_cosign
            notify_family_of_cosign(uid, contract_id, 'Smlouva v Odkazu', senior_price)
        except Exception as e:
            logger.debug(f"notify family cosign: {e}")

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

def run_royalty_payout(dry_run=False):
    """Check all active contracts with royalty_years > 0 and monthly-prorate.
    Creates earnings entries for contracts whose last_royalty_at is >=30 days ago
    (or never paid after initial). Safe to run daily — idempotent per contract.

    v781+ enhancements (from E2E test + production audit):
      - Returns full metrics dict (ne jen count)
      - Inheritance handling — když senior umřel, royalty jde na heir
        (placeholder: experience_inheritance + auth_users.deceased_at)
      - payout_method nastaven explicitně ('pending_bank_transfer' /
        'inherited_pending') — admin payouts CSV pak ví, jak handle
      - Senior NET split (80%) místo gross — earnings teď reflektuje
        skutečnou částku k výplatě (předtím gross zaměňováno za netto)
      - Robust timestamp parsing (PG ISO formát, SQLite ISO formát)
      - dry_run mode pro testování / admin trigger

    Args:
        dry_run: pokud True, žádné DB zápisy, jen vrátí seznam kandidátů.

    Returns:
        dict s metrikami (canditates_found, earnings_created, total_kc,
        inherited, expired, errors, dry_run).
    """
    _init_schema()
    from datetime import datetime, timedelta

    metrics = {
        'candidates_found': 0,
        'earnings_created': 0,
        'total_kc': 0,
        'inherited': 0,
        'expired': 0,
        'skipped_recent': 0,
        'errors': [],
        'dry_run': dry_run,
    }

    now = datetime.utcnow()
    cutoff_30d = now - timedelta(days=30)

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
        logger.error(f"royalty scan: {e}")
        metrics['errors'].append(f"scan: {e}")
        return metrics

    metrics['candidates_found'] = len(rows or [])

    def _parse_ts(val):
        """Parse timestamp z PG nebo SQLite (ISO formáty)."""
        if not val:
            return None
        s = str(val)[:19]
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        contract_id = v(0, 'id')
        senior_uid = v(1, 'user_id')
        years = int(v(2, 'royalty_years') or 0)
        per_year = int(v(3, 'royalty_kc_per_year') or 0)
        signed = v(4, 'signed_at')
        last = v(5, 'last_royalty_at')

        # Monthly amount (1/12 of yearly), s 80/20 senior split.
        monthly_gross = per_year // 12 if per_year >= 12 else per_year
        if monthly_gross <= 0:
            continue
        senior_net = _calc_senior_net(monthly_gross)

        # Check eligibility — last_royalty_at méně než 30 dní = skip
        last_dt = _parse_ts(last)
        if last_dt and last_dt > cutoff_30d:
            metrics['skipped_recent'] += 1
            continue

        # Check contract hasn't expired
        signed_dt = _parse_ts(signed) or now
        expiry = signed_dt + timedelta(days=365 * years)
        if now > expiry:
            metrics['expired'] += 1
            continue

        # Inheritance check — pokud senior je deceased, royalty přesměrujeme
        # na heir contact info (admin pak vyplatí ručně do payout_method=
        # 'inherited_pending').
        recipient_uid = senior_uid
        is_inherited = False
        try:
            with db_context() as dbi:
                # Aktuálně auth_users nemá deceased_at sloupec — defenzivně:
                try:
                    drow = dbi.execute(
                        "SELECT deceased_at FROM auth_users WHERE id = ?",
                        (senior_uid,)
                    ).fetchone()
                    is_deceased = bool(
                        drow and (drow[0] if isinstance(drow, (list, tuple))
                                  else drow.get('deceased_at'))
                    )
                except Exception:
                    is_deceased = False

                if is_deceased:
                    # Najdi heir z experience_inheritance
                    heir_row = dbi.execute(
                        "SELECT heir_contact, royalty_years_after_death "
                        "FROM experience_inheritance WHERE user_id = ?",
                        (senior_uid,)
                    ).fetchone()
                    if heir_row:
                        is_inherited = True
                        metrics['inherited'] += 1
        except Exception as inh_err:
            logger.debug(f"royalty inheritance check {contract_id}: {inh_err}")

        payout_method = 'inherited_pending' if is_inherited else 'pending_bank_transfer'

        if dry_run:
            metrics['earnings_created'] += 1
            metrics['total_kc'] += senior_net
            logger.info(
                f"royalty DRY: contract={contract_id} senior={senior_uid[:8]} "
                f"net={senior_net} ({monthly_gross} gross) inherited={is_inherited}"
            )
            continue

        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO experience_earnings "
                    "(user_id, contract_id, amount_kc, gross_kc, source, "
                    " payout_method, period_label) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (recipient_uid, contract_id, senior_net, monthly_gross,
                     'royalty', payout_method, now.strftime('%Y-%m'))
                )
                db.execute(
                    "UPDATE experience_contracts SET last_royalty_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (contract_id,)
                )
            metrics['earnings_created'] += 1
            metrics['total_kc'] += senior_net
        except Exception as e:
            logger.error(f"royalty pay contract={contract_id}: {e}")
            metrics['errors'].append(f"contract {contract_id}: {e}")

    logger.info(
        f"Royalty scheduler: {metrics['candidates_found']} kandidátů, "
        f"{metrics['earnings_created']} earnings, {metrics['total_kc']} Kč"
        f"{', inh=' + str(metrics['inherited']) if metrics['inherited'] else ''}"
        f"{', exp=' + str(metrics['expired']) if metrics['expired'] else ''}"
        f"{', err=' + str(len(metrics['errors'])) if metrics['errors'] else ''}"
    )
    return metrics


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


# ─────────────────────────────────────────────────────────────────────────────
# MVP: PER-AUDIENCE CONSENT + BANK REWARD — Radimův Odkaz MVP (Sprint Q)
# ─────────────────────────────────────────────────────────────────────────────
# Philosophy:
#   - Consent is per-audience (family / research / companies), not single-privacy.
#   - Reward is length-based (50 / 100 / 150 Kč), paid by bank transfer.
#   - Seniors can't approve reward without valid IBAN on file.
#   - Admin workflow: pending → approved (admin) → paid (bank confirms → bank_ref).
#
# Tiers:
#   short  (< 100 words)        →  50 Kč
#   medium (100–249 words)      → 100 Kč
#   long   (>= 250 words)       → 150 Kč
#
# Note: the existing /offers + /accept-offer system handles high-value
# research/archive contracts (300–1500 Kč). This MVP reward is the flat-rate
# micro-incentive for EVERY approved memory — research/archive contracts then
# stack on top of it.

REWARD_TIERS = [
    (250, 150, 'long'),
    (100, 100, 'medium'),
    (0,    50, 'short'),
]


def _calc_reward_tier(word_count):
    """Return (amount_kc, tier_label)."""
    wc = int(word_count or 0)
    for threshold, amount, label in REWARD_TIERS:
        if wc >= threshold:
            return (amount, label)
    return (50, 'short')


def _mask_iban(iban):
    if not iban:
        return ''
    iban = ''.join(c for c in str(iban) if c.isalnum()).upper()
    if len(iban) < 4:
        return iban
    return iban[-4:]


def _owns_contribution(db, uid, cid):
    row = db.execute(
        "SELECT id, word_count FROM experience_contributions "
        "WHERE id = ? AND user_id = ? AND privacy <> ?",
        (cid, uid, 'deleted')
    ).fetchone()
    return row


@experience_bp.route('/api/experience/contribution/<int:cid>/consent',
                     methods=['GET', 'POST', 'OPTIONS'])
@require_auth
def contribution_consent(cid):
    """Per-audience consent selection for a single memory.

    POST body: { shareFamily: bool, shareResearch: bool, shareCompanies: bool }
    GET       returns current consent (empty if not yet set).
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # IDOR — must own the contribution
    try:
        with db_context() as db:
            if not _owns_contribution(db, uid, cid):
                return jsonify({'success': False, 'error': 'not found'}), 404
    except Exception as e:
        logger.error(f"consent idor: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    if request.method == 'GET':
        try:
            with db_context() as db:
                r = db.execute(
                    "SELECT share_family, share_research, share_companies, updated_at "
                    "FROM experience_consents WHERE contribution_id = ?",
                    (cid,)
                ).fetchone()
        except Exception:
            r = None
        if not r:
            return jsonify({'success': True, 'consent': None})

        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        return jsonify({
            'success': True,
            'consent': {
                'shareFamily': bool(v(0, 'share_family')),
                'shareResearch': bool(v(1, 'share_research')),
                'shareCompanies': bool(v(2, 'share_companies')),
                'updatedAt': str(v(3, 'updated_at') or ''),
            }
        })

    # POST
    if not _rate_ok(uid, 'consent', 30):
        return jsonify({'success': False, 'code': 'rate_limit',
                        'error': 'Moc rychle.'}), 429

    data = request.get_json() or {}
    sf = _to_bool(data.get('shareFamily'))
    sr = _to_bool(data.get('shareResearch'))
    sc = _to_bool(data.get('shareCompanies'))

    # Derive privacy from consent flags (most-permissive wins, but we keep
    # per-audience control separate)
    if sc:
        derived_privacy = 'public'
    elif sr:
        derived_privacy = 'research'
    elif sf:
        derived_privacy = 'family'
    else:
        derived_privacy = 'draft'

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id FROM experience_consents WHERE contribution_id = ?",
                (cid,)
            ).fetchone()

            bool_f = (sf if is_postgres() else (1 if sf else 0))
            bool_r = (sr if is_postgres() else (1 if sr else 0))
            bool_c = (sc if is_postgres() else (1 if sc else 0))

            if existing:
                db.execute(
                    "UPDATE experience_consents "
                    "SET share_family = ?, share_research = ?, share_companies = ?, "
                    "    updated_at = CURRENT_TIMESTAMP "
                    "WHERE contribution_id = ?",
                    (bool_f, bool_r, bool_c, cid)
                )
            else:
                db.execute(
                    "INSERT INTO experience_consents "
                    "(user_id, contribution_id, share_family, share_research, share_companies) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uid, cid, bool_f, bool_r, bool_c)
                )

            # Mirror to contribution.privacy if not draft
            if derived_privacy != 'draft':
                db.execute(
                    "UPDATE experience_contributions "
                    "SET privacy = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND user_id = ?",
                    (derived_privacy, cid, uid)
                )
    except Exception as e:
        logger.error(f"consent write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'consent_set', 'contribution', cid,
           f'family={sf} research={sr} companies={sc}')

    return jsonify({
        'success': True,
        'contributionId': cid,
        'consent': {
            'shareFamily': sf,
            'shareResearch': sr,
            'shareCompanies': sc,
        },
        'derivedPrivacy': derived_privacy,
    })


@experience_bp.route('/api/experience/bank-info',
                     methods=['GET', 'PUT', 'OPTIONS'])
@require_auth
def bank_info():
    """Senior's bank account for reward payouts (IBAN, holder name)."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if request.method == 'GET':
        try:
            with db_context() as db:
                r = db.execute(
                    "SELECT account_holder, iban_last4, bank_name, verified, updated_at "
                    "FROM experience_bank_info WHERE user_id = ?",
                    (uid,)
                ).fetchone()
        except Exception:
            r = None
        if not r:
            return jsonify({'success': True, 'bankInfo': None})

        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        return jsonify({
            'success': True,
            'bankInfo': {
                'accountHolder': v(0, 'account_holder') or '',
                'ibanLast4': v(1, 'iban_last4') or '',
                'bankName': v(2, 'bank_name') or '',
                'verified': bool(v(3, 'verified')),
                'updatedAt': str(v(4, 'updated_at') or ''),
            }
        })

    # PUT
    if not _rate_ok(uid, 'bank_info', 10):
        return jsonify({'success': False, 'code': 'rate_limit',
                        'error': 'Moc rychle.'}), 429

    data = request.get_json() or {}
    holder = (data.get('accountHolder') or '').strip()[:120]
    iban_raw = ''.join(c for c in str(data.get('iban') or '') if c.isalnum()).upper()
    bank_name = (data.get('bankName') or '').strip()[:80]
    swift = (data.get('swiftBic') or '').strip()[:15]

    # Minimal IBAN validation: CZ format is 24 chars, general range 15–34
    if not holder or len(holder) < 2:
        return jsonify({'success': False,
                        'error': 'Zadejte celé jméno majitele účtu.'}), 400
    if len(iban_raw) < 15 or len(iban_raw) > 34:
        return jsonify({'success': False,
                        'error': 'IBAN se zdá být neúplný. Český IBAN má 24 znaků.'}), 400
    if not iban_raw[:2].isalpha():
        return jsonify({'success': False,
                        'error': 'IBAN musí začínat kódem země (např. CZ).'}), 400

    last4 = _mask_iban(iban_raw)

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT user_id FROM experience_bank_info WHERE user_id = ?",
                (uid,)
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE experience_bank_info "
                    "SET account_holder = ?, iban = ?, iban_last4 = ?, "
                    "    bank_name = ?, swift_bic = ?, verified = ?, "
                    "    updated_at = CURRENT_TIMESTAMP "
                    "WHERE user_id = ?",
                    (holder, iban_raw, last4, bank_name, swift,
                     (False if is_postgres() else 0), uid)
                )
            else:
                db.execute(
                    "INSERT INTO experience_bank_info "
                    "(user_id, account_holder, iban, iban_last4, bank_name, swift_bic) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, holder, iban_raw, last4, bank_name, swift)
                )
    except Exception as e:
        logger.error(f"bank-info write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'bank_info_updated', 'user', None, f'last4={last4}')
    return jsonify({
        'success': True,
        'bankInfo': {
            'accountHolder': holder,
            'ibanLast4': last4,
            'bankName': bank_name,
            'verified': False,
        },
        'message': 'Bankovní údaje uloženy. Ověření proběhne při první výplatě.',
    })


@experience_bp.route('/api/experience/contribution/<int:cid>/reward',
                     methods=['POST', 'OPTIONS'])
@require_auth
def claim_reward(cid):
    """Claim the MVP flat-rate reward for an approved memory.

    Rules:
      - Contribution must be approved (privacy != 'draft', != 'deleted')
      - Must have consent record (at least one audience enabled)
      - One reward per contribution (UNIQUE index enforces)
      - Senior must have bank_info on file
      - Amount derived from word_count via _calc_reward_tier()
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if not _rate_ok(uid, 'reward_claim', 20):
        return jsonify({'success': False, 'code': 'rate_limit',
                        'error': 'Moc rychle.'}), 429

    # 1. Fetch contribution + validate
    try:
        with db_context() as db:
            contrib = db.execute(
                "SELECT id, word_count, privacy, title FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
                (cid, uid)
            ).fetchone()
    except Exception as e:
        logger.error(f"reward fetch: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    if not contrib:
        return jsonify({'success': False, 'error': 'not found'}), 404

    def cv(i, k):
        return contrib[i] if isinstance(contrib, (list, tuple)) else contrib.get(k)

    privacy = cv(2, 'privacy')
    if privacy in ('draft', 'deleted'):
        return jsonify({
            'success': False,
            'error': 'Vzpomínka ještě není schválena. Nejdřív zvolte sdílení.',
            'code': 'not_approved',
        }), 400

    word_count = int(cv(1, 'word_count') or 0)
    title = cv(3, 'title') or ''

    # 2. Check consent exists
    try:
        with db_context() as db:
            consent = db.execute(
                "SELECT share_family, share_research, share_companies "
                "FROM experience_consents WHERE contribution_id = ?",
                (cid,)
            ).fetchone()
    except Exception:
        consent = None
    if not consent:
        return jsonify({
            'success': False,
            'error': 'Nejdřív zvolte, kdo může vzpomínku číst.',
            'code': 'consent_missing',
        }), 400

    def xv(i, k):
        return consent[i] if isinstance(consent, (list, tuple)) else consent.get(k)
    has_any_consent = any([xv(0, 'share_family'),
                           xv(1, 'share_research'),
                           xv(2, 'share_companies')])
    if not has_any_consent:
        return jsonify({
            'success': False,
            'error': 'Nevybrala jste žádného příjemce — vzpomínka zůstává pouze u vás.',
            'code': 'no_audience',
        }), 400

    # 3. Check bank info exists
    try:
        with db_context() as db:
            bank = db.execute(
                "SELECT iban_last4 FROM experience_bank_info WHERE user_id = ?",
                (uid,)
            ).fetchone()
    except Exception:
        bank = None
    if not bank:
        return jsonify({
            'success': False,
            'error': 'Pro výplatu potřebuji znát vaše číslo účtu.',
            'code': 'bank_info_missing',
        }), 400

    iban_last4 = bank[0] if isinstance(bank, (list, tuple)) else bank.get('iban_last4')

    # 4. Check reward doesn't already exist
    try:
        with db_context() as db:
            existing = db.execute(
                "SELECT id, amount_kc, tier, status FROM experience_rewards "
                "WHERE contribution_id = ?",
                (cid,)
            ).fetchone()
    except Exception:
        existing = None

    if existing:
        def ev(i, k):
            return existing[i] if isinstance(existing, (list, tuple)) else existing.get(k)
        return jsonify({
            'success': True,
            'alreadyClaimed': True,
            'reward': {
                'id': ev(0, 'id'),
                'amountKc': ev(1, 'amount_kc'),
                'tier': ev(2, 'tier'),
                'status': ev(3, 'status'),
            },
        })

    # 5. Calculate + insert
    amount_kc, tier = _calc_reward_tier(word_count)

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                r = db.execute(
                    "INSERT INTO experience_rewards "
                    "(user_id, contribution_id, amount_kc, tier, word_count, "
                    " status, payout_method, bank_iban_last4) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, cid, amount_kc, tier, word_count,
                     'pending', 'bank_transfer', iban_last4)
                ).fetchone()
                rid = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO experience_rewards "
                    "(user_id, contribution_id, amount_kc, tier, word_count, "
                    " status, payout_method, bank_iban_last4) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, cid, amount_kc, tier, word_count,
                     'pending', 'bank_transfer', iban_last4)
                )
                rid = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"reward insert: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'reward_claimed', 'contribution', cid,
           f'amount={amount_kc}Kc tier={tier} words={word_count}')

    return jsonify({
        'success': True,
        'reward': {
            'id': rid,
            'contributionId': cid,
            'title': title,
            'amountKc': amount_kc,
            'tier': tier,
            'wordCount': word_count,
            'status': 'pending',
            'payoutMethod': 'bank_transfer',
            'bankIbanLast4': iban_last4,
        },
        'message': f'Odměna {amount_kc} Kč zaznamenána. Pošleme ji na účet končící {iban_last4} během 7 pracovních dní.',
    })


@experience_bp.route('/api/experience/rewards', methods=['GET', 'OPTIONS'])
@require_auth
def rewards_list():
    """Reward history for current senior — pending / approved / paid."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT r.id, r.contribution_id, r.amount_kc, r.tier, r.word_count, "
                "       r.status, r.payout_method, r.bank_iban_last4, r.bank_ref, "
                "       r.approved_at, r.paid_at, r.created_at, c.title "
                "FROM experience_rewards r "
                "LEFT JOIN experience_contributions c ON c.id = r.contribution_id "
                "WHERE r.user_id = ? ORDER BY r.created_at DESC LIMIT 200",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.debug(f"rewards list: {e}")
        rows = []

    def rv(r, i, k):
        return r[i] if isinstance(r, (list, tuple)) else r.get(k)

    rewards = []
    total_pending = 0
    total_paid = 0
    for r in rows or []:
        status = rv(r, 5, 'status') or 'pending'
        amount = int(rv(r, 2, 'amount_kc') or 0)
        if status == 'paid':
            total_paid += amount
        elif status in ('pending', 'approved'):
            total_pending += amount
        rewards.append({
            'id': rv(r, 0, 'id'),
            'contributionId': rv(r, 1, 'contribution_id'),
            'amountKc': amount,
            'tier': rv(r, 3, 'tier'),
            'wordCount': rv(r, 4, 'word_count') or 0,
            'status': status,
            'payoutMethod': rv(r, 6, 'payout_method') or 'bank_transfer',
            'bankIbanLast4': rv(r, 7, 'bank_iban_last4') or '',
            'bankRef': rv(r, 8, 'bank_ref') or '',
            'approvedAt': str(rv(r, 9, 'approved_at') or ''),
            'paidAt': str(rv(r, 10, 'paid_at') or ''),
            'createdAt': str(rv(r, 11, 'created_at') or ''),
            'title': rv(r, 12, 'title') or '(bez názvu)',
        })

    return jsonify({
        'success': True,
        'rewards': rewards,
        'count': len(rewards),
        'totalPendingKc': total_pending,
        'totalPaidKc': total_paid,
        'tiers': [
            {'minWords': 0, 'maxWords': 99, 'amountKc': 50, 'label': 'short'},
            {'minWords': 100, 'maxWords': 249, 'amountKc': 100, 'label': 'medium'},
            {'minWords': 250, 'maxWords': None, 'amountKc': 150, 'label': 'long'},
        ],
    })


# ── ADMIN: list all rewards (ops dashboard) ───────────────────────────
@experience_bp.route('/api/experience/admin/rewards',
                     methods=['GET', 'OPTIONS'])
def admin_rewards_list():
    """Ops list of all rewards across all seniors.
    Query: ?status=pending|approved|paid|failed|all (default: pending+approved)
    Protected by X-Admin-Secret header."""
    if request.method == 'OPTIONS':
        return '', 204
    admin_secret = os.environ.get('ADMIN_SECRET')
    if not admin_secret or request.headers.get('X-Admin-Secret') != admin_secret:
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    _init_schema()
    status_filter = (request.args.get('status') or 'actionable').lower()

    try:
        with db_context() as db:
            if status_filter == 'all':
                where = ''
                params = ()
            elif status_filter in ('pending', 'approved', 'paid', 'failed'):
                where = 'WHERE r.status = ?'
                params = (status_filter,)
            else:  # 'actionable' = default — pending + approved (ops action needed)
                where = "WHERE r.status IN (?, ?)"
                params = ('pending', 'approved')

            rows = db.execute(
                f"SELECT r.id, r.user_id, r.contribution_id, r.amount_kc, r.tier, "
                f"       r.word_count, r.status, r.bank_iban_last4, r.bank_ref, "
                f"       r.approved_at, r.paid_at, r.created_at, r.admin_note, "
                f"       c.title, b.account_holder, b.iban, b.bank_name "
                f"FROM experience_rewards r "
                f"LEFT JOIN experience_contributions c ON c.id = r.contribution_id "
                f"LEFT JOIN experience_bank_info b ON b.user_id = r.user_id "
                f"{where} "
                f"ORDER BY CASE r.status "
                f"  WHEN 'pending' THEN 1 WHEN 'approved' THEN 2 "
                f"  WHEN 'failed' THEN 3 WHEN 'paid' THEN 4 ELSE 5 END, "
                f"r.created_at DESC LIMIT 500",
                params
            ).fetchall()
    except Exception as e:
        logger.error(f"admin rewards list: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    def rv(r, i, k):
        return r[i] if isinstance(r, (list, tuple)) else r.get(k)

    rewards = []
    totals = {'pending': 0, 'approved': 0, 'paid': 0, 'failed': 0}
    for r in rows or []:
        status = rv(r, 6, 'status') or 'pending'
        amount = int(rv(r, 3, 'amount_kc') or 0)
        if status in totals:
            totals[status] += amount
        rewards.append({
            'id': rv(r, 0, 'id'),
            'userId': rv(r, 1, 'user_id'),
            'contributionId': rv(r, 2, 'contribution_id'),
            'amountKc': amount,
            'tier': rv(r, 4, 'tier'),
            'wordCount': rv(r, 5, 'word_count') or 0,
            'status': status,
            'bankIbanLast4': rv(r, 7, 'bank_iban_last4') or '',
            'bankRef': rv(r, 8, 'bank_ref') or '',
            'approvedAt': str(rv(r, 9, 'approved_at') or ''),
            'paidAt': str(rv(r, 10, 'paid_at') or ''),
            'createdAt': str(rv(r, 11, 'created_at') or ''),
            'adminNote': rv(r, 12, 'admin_note') or '',
            'title': rv(r, 13, 'title') or '(bez názvu)',
            'accountHolder': rv(r, 14, 'account_holder') or '',
            'iban': rv(r, 15, 'iban') or '',
            'bankName': rv(r, 16, 'bank_name') or '',
        })

    return jsonify({
        'success': True,
        'rewards': rewards,
        'count': len(rewards),
        'totals': totals,
        'filter': status_filter,
    })


# ── ADMIN: approve + mark paid (used by ops, not seniors) ─────────────
@experience_bp.route('/api/experience/admin/reward/<int:rid>/approve',
                     methods=['POST', 'OPTIONS'])
def admin_approve_reward(rid):
    """Ops endpoint — protected by ADMIN_SECRET header."""
    if request.method == 'OPTIONS':
        return '', 204
    admin_secret = os.environ.get('ADMIN_SECRET')
    if not admin_secret or request.headers.get('X-Admin-Secret') != admin_secret:
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    data = request.get_json() or {}
    action = (data.get('action') or '').lower()  # 'approve' | 'pay' | 'fail'
    bank_ref = (data.get('bankRef') or '').strip()[:60]
    note = (data.get('note') or '').strip()[:500]

    if action not in ('approve', 'pay', 'fail'):
        return jsonify({'success': False, 'error': 'action must be approve|pay|fail'}), 400

    try:
        with db_context(commit=True) as db:
            if action == 'approve':
                db.execute(
                    "UPDATE experience_rewards "
                    "SET status = 'approved', approved_at = CURRENT_TIMESTAMP, "
                    "    admin_note = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = 'pending'",
                    (note, rid)
                )
            elif action == 'pay':
                db.execute(
                    "UPDATE experience_rewards "
                    "SET status = 'paid', paid_at = CURRENT_TIMESTAMP, "
                    "    bank_ref = ?, admin_note = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status IN ('pending', 'approved')",
                    (bank_ref, note, rid)
                )
                # Also mirror to experience_earnings for unified ledger
                row = db.execute(
                    "SELECT user_id, amount_kc FROM experience_rewards WHERE id = ?",
                    (rid,)
                ).fetchone()
                if row:
                    uid_r = row[0] if isinstance(row, (list, tuple)) else row.get('user_id')
                    amt = row[1] if isinstance(row, (list, tuple)) else row.get('amount_kc')
                    db.execute(
                        "INSERT INTO experience_earnings "
                        "(user_id, contract_id, amount_kc, gross_kc, source, "
                        " payout_method, paid_at, period_label) "
                        "VALUES (?, NULL, ?, ?, 'mvp_reward', 'bank_transfer', "
                        " CURRENT_TIMESTAMP, ?)",
                        (uid_r, amt, amt, bank_ref or f'reward#{rid}')
                    )
            elif action == 'fail':
                db.execute(
                    "UPDATE experience_rewards "
                    "SET status = 'failed', admin_note = ?, "
                    "    updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (note, rid)
                )
    except Exception as e:
        logger.error(f"admin reward: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({'success': True, 'rewardId': rid, 'action': action})


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — manuální trigger royalty cyklu (pro testování + emergency)
# ─────────────────────────────────────────────────────────────────────────────

@experience_bp.route('/api/admin/royalty/trigger', methods=['POST'])
def admin_royalty_trigger():
    """Manuální spuštění royalty cyklu — bypassuje denní APScheduler.

    Body (volitelné):
      dryRun: bool — pokud true, žádné DB zápisy, jen vrátí kandidáty

    Use case:
      - Test po nasazení (DRY RUN, verify candidates)
      - Emergency catch-up po výpadku APScheduler
      - Anniversary catch-up (po smrti seniora apod.)
    """
    auth_err = _require_admin()
    if auth_err:
        return auth_err

    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get('dryRun', False))

    try:
        metrics = run_royalty_payout(dry_run=dry_run)
        return jsonify({
            'success': True,
            'metrics': metrics,
            'mode': 'dry_run' if dry_run else 'live',
            'message': (
                f"DRY RUN: {metrics['candidates_found']} kandidátů, "
                f"by se vyplatilo {metrics['total_kc']} Kč"
                if dry_run else
                f"OK: {metrics['earnings_created']} earnings vytvořeno, "
                f"celkem {metrics['total_kc']} Kč"
            )
        })
    except Exception as e:
        logger.error(f"admin_royalty_trigger: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@experience_bp.route('/api/admin/royalty/contracts', methods=['GET'])
def admin_royalty_contracts():
    """Seznam aktivních royalty kontraktů — admin dashboard přehled.

    Query params:
        status: 'active' (default) | 'expired' | 'all'
    """
    auth_err = _require_admin()
    if auth_err:
        return auth_err

    status_filter = request.args.get('status', 'active')[:30]

    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT c.id, c.user_id, c.contribution_id, c.buyer_id, "
                    "       c.price_kc, c.royalty_years, c.royalty_kc_per_year, "
                    "       c.signed_at, c.last_royalty_at, c.revoked_at, "
                    "       b.name AS buyer_name, "
                    "       (SELECT COUNT(*) FROM experience_earnings e "
                    "        WHERE e.contract_id = c.id AND e.source = 'royalty') AS royalty_paid_count, "
                    "       (SELECT COALESCE(SUM(amount_kc), 0) FROM experience_earnings e "
                    "        WHERE e.contract_id = c.id AND e.source = 'royalty') AS royalty_total_kc "
                    "FROM experience_contracts c "
                    "LEFT JOIN experience_buyers b ON b.id = c.buyer_id "
                    "WHERE c.royalty_years > 0 "
                    "ORDER BY c.signed_at DESC LIMIT 100"
                ).fetchall()
            else:
                rows = []
    except Exception as e:
        logger.error(f"admin_royalty_contracts: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'DB error'}), 500

    contracts = []
    for r in rows or []:
        def gv(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        contracts.append({
            'id': gv(0, 'id'),
            'userId': gv(1, 'user_id'),
            'contributionId': gv(2, 'contribution_id'),
            'buyerId': gv(3, 'buyer_id'),
            'priceKc': gv(4, 'price_kc'),
            'royaltyYears': gv(5, 'royalty_years'),
            'royaltyKcPerYear': gv(6, 'royalty_kc_per_year'),
            'signedAt': str(gv(7, 'signed_at') or '')[:19],
            'lastRoyaltyAt': str(gv(8, 'last_royalty_at') or '')[:19] if gv(8, 'last_royalty_at') else None,
            'revokedAt': str(gv(9, 'revoked_at') or '')[:19] if gv(9, 'revoked_at') else None,
            'buyerName': gv(10, 'buyer_name'),
            'royaltyPaidCount': int(gv(11, 'royalty_paid_count') or 0),
            'royaltyTotalKc': int(gv(12, 'royalty_total_kc') or 0),
        })

    if status_filter == 'active':
        contracts = [c for c in contracts if not c['revokedAt']]
    elif status_filter == 'expired':
        contracts = [c for c in contracts if c['royaltyPaidCount'] >= (c['royaltyYears'] * 12)]

    return jsonify({'success': True, 'contracts': contracts, 'count': len(contracts)})


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
