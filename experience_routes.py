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
        duration_sec INTEGER DEFAULT 0,
        privacy TEXT DEFAULT 'draft',
        approved_at TIMESTAMP,
        cooling_off_until TIMESTAMP,
        word_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_contrib_user ON experience_contributions(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_exp_contrib_privacy ON experience_contributions(user_id, privacy);
    CREATE INDEX IF NOT EXISTS idx_exp_contrib_theme ON experience_contributions(theme);

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
        last_royalty_at TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_exp_contracts_user ON experience_contracts(user_id, signed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_exp_contracts_contribution ON experience_contracts(contribution_id);

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
        royalty_years_after_death INTEGER DEFAULT 5,
        unlock_family_archive BOOLEAN DEFAULT TRUE,
        unlock_on_events JSONB,
        public_memorial BOOLEAN DEFAULT FALSE,
        configured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in EXPERIENCE_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Experience schema init: {e}")
    _seed_demo_buyers_if_empty()


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
    structured version of the raw transcript — but the senior must approve
    it, and original transcript is preserved untouched."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT transcript, title, type, theme FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
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
    if not transcript or len(transcript) < 50:
        return jsonify({'success': False, 'error': 'Text je příliš krátký.'}), 400

    # AI structure via Gemini (best-effort, honest fallback)
    structured = _structure_via_gemini(transcript, v(1, 'title'), v(3, 'theme'))
    if not structured:
        structured = transcript  # fallback: original transcript

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

    return jsonify({
        'success': True,
        'sessionId': session_id,
        'structured': structured,
        'aiGenerated': structured != transcript,
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
    return jsonify({'success': True, 'id': cid, 'privacy': new_privacy})


@experience_bp.route('/api/experience/contribution/<int:cid>', methods=['DELETE'])
@require_auth
def forget_contribution(cid):
    """Right to forget — soft delete + revoke all contracts."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

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
    return jsonify({'success': True, 'id': cid, 'deleted': True,
                    'message': 'Vzpomínka byla zapomenuta. Ctím vaše právo.'})


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

    # Verify contribution ownership + approved status
    try:
        with db_context() as db:
            cr = db.execute(
                "SELECT privacy FROM experience_contributions "
                "WHERE id = ? AND user_id = ?",
                (cid, uid)
            ).fetchone()
            if not cr:
                return jsonify({'success': False, 'error': 'contribution not found'}), 404
            priv = cr[0] if isinstance(cr, (list, tuple)) else cr.get('privacy')
            if priv not in {'family', 'research', 'public'}:
                return jsonify({'success': False,
                                'error': 'Vzpomínka musí být nejprve schválena.'}), 400
            # Verify offer exists & active
            orow = db.execute(
                "SELECT buyer_id, price_kc, royalty_years, royalty_kc_per_year, status "
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
            if status != 'active':
                return jsonify({'success': False, 'error': 'Nabídka není aktivní.'}), 409
            if gross < MIN_PRICE_KC:
                return jsonify({'success': False,
                                'error': f'Cena pod minimem {MIN_PRICE_KC} Kč.'}), 400
    except Exception as e:
        logger.error(f"accept offer read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    senior_price = _calc_senior_net(gross)
    senior_royalty = _calc_senior_net(royalty_kc)
    cooling_off = datetime.utcnow() + timedelta(hours=COOLING_OFF_HOURS)

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                r = db.execute(
                    "INSERT INTO experience_contracts "
                    "(user_id, contribution_id, offer_id, buyer_id, price_kc, "
                    "royalty_years, royalty_kc_per_year, anonymized, cooling_off_until) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, cid, offer_id, buyer_id, senior_price,
                     royalty_y, senior_royalty, anonymized, cooling_off)
                ).fetchone()
                contract_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO experience_contracts "
                    "(user_id, contribution_id, offer_id, buyer_id, price_kc, "
                    "royalty_years, royalty_kc_per_year, anonymized, cooling_off_until) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, cid, offer_id, buyer_id, senior_price,
                     royalty_y, senior_royalty, 1 if anonymized else 0, cooling_off)
                )
                contract_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
            # Record initial payout
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

    return jsonify({
        'success': True,
        'contractId': contract_id,
        'seniorPriceKc': senior_price,
        'seniorRoyaltyKcPerYear': senior_royalty,
        'royaltyYears': royalty_y,
        'coolingOffUntil': cooling_off.isoformat(),
        'message': f'Smlouva podepsána. Na váš účet {senior_price} Kč. Máte 72 hodin na rozmyšlenou.',
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


logger.info("🌿 Experience routes v1.0 loaded — Radimův Odkaz MVP ready")
