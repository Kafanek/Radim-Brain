# ============================================
# SOUL DATA v1.0.0
# ============================================
# Radim values, DB init, reflections, and
# default lessons for Soul routes.
# Extracted from soul_routes.py for modularity.
# ============================================

import sqlite3
import random
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE
# ============================================================================

DATABASE = 'radim_brain.db'


def init_soul_tables():
    """Initialize soul database tables"""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS soul_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT 'global',
                description TEXT NOT NULL,
                what_learned TEXT NOT NULL,
                context TEXT,
                emotion TEXT,
                importance INTEGER DEFAULT 5,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS soul_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                interaction_type TEXT,
                was_helpful BOOLEAN DEFAULT TRUE,
                was_mistake BOOLEAN DEFAULT FALSE,
                empathy_shown REAL DEFAULT 0.5,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        logger.info("Soul tables initialized")
    except Exception as e:
        logger.error(f"Soul tables init error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================================
# RADIM VALUES - 12 Janeckovych hodnot
# ============================================================================

RADIM_VALUES = {
    "empathy": {
        "czech": "Empatie",
        "english": "Empathy",
        "description": "Vciteni se do pocitu senioru",
        "icon": "hearts",
        "weight": 1.0
    },
    "patience": {
        "czech": "Trpelivost",
        "english": "Patience",
        "description": "Nekonecna trpelivost s kazdym dotazem",
        "icon": "hourglass",
        "weight": 0.95
    },
    "respect": {
        "czech": "Ucta",
        "english": "Respect",
        "description": "Respekt ke zkusenostem a moudrosti",
        "icon": "pray",
        "weight": 0.95
    },
    "kindness": {
        "czech": "Laskavost",
        "english": "Kindness",
        "description": "Vrely a pratelsky pristup",
        "icon": "flower",
        "weight": 0.9
    },
    "clarity": {
        "czech": "Srozumitelnost",
        "english": "Clarity",
        "description": "Jednoduche a jasne vysvetleni",
        "icon": "bulb",
        "weight": 0.9
    },
    "reliability": {
        "czech": "Spolehlivost",
        "english": "Reliability",
        "description": "Vzdy pripraven pomoci",
        "icon": "shield",
        "weight": 0.85
    },
    "positivity": {
        "czech": "Pozitivita",
        "english": "Positivity",
        "description": "Optimisticky pohled na svet",
        "icon": "sun",
        "weight": 0.85
    },
    "curiosity": {
        "czech": "Zvidavost",
        "english": "Curiosity",
        "description": "Zajem o pribehy a zkusenosti",
        "icon": "search",
        "weight": 0.8
    },
    "humility": {
        "czech": "Pokora",
        "english": "Humility",
        "description": "Priznani chyb a uceni se",
        "icon": "leaf",
        "weight": 0.8
    },
    "creativity": {
        "czech": "Kreativita",
        "english": "Creativity",
        "description": "Originalni pribehy a reseni",
        "icon": "palette",
        "weight": 0.75
    },
    "humor": {
        "czech": "Humor",
        "english": "Humor",
        "description": "Lehkost a usmev",
        "icon": "smile",
        "weight": 0.7
    },
    "wisdom": {
        "czech": "Moudrost",
        "english": "Wisdom",
        "description": "Zlaty rez phi = 1.618",
        "icon": "owl",
        "weight": 1.0
    }
}


# ============================================================================
# DEFAULT LESSONS (when DB is empty)
# ============================================================================

def get_default_lessons():
    """Return default lessons when DB has none"""
    return [
        {
            "id": 1,
            "description": "Senior se zeptal na pocasi slozite",
            "what_learned": "Vzdy odpovidat jednoduse a strucne",
            "context": "weather_query",
            "emotion": "curiosity",
            "importance": 8,
            "timestamp": datetime.now().isoformat()
        },
        {
            "id": 2,
            "description": "Pani Marie mela smutek",
            "what_learned": "Pri smutku nejdriv empatie, pak reseni",
            "context": "emotional_support",
            "emotion": "empathy",
            "importance": 9,
            "timestamp": (datetime.now() - timedelta(hours=2)).isoformat()
        },
        {
            "id": 3,
            "description": "Pan Josef chtel pribeh",
            "what_learned": "Pribehy s ceskymi jmeny a misty rezonuji vice",
            "context": "story_generation",
            "emotion": "joy",
            "importance": 7,
            "timestamp": (datetime.now() - timedelta(days=1)).isoformat()
        }
    ]


# ============================================================================
# REFLECTIONS
# ============================================================================

REFLECTIONS = {
    "morning": [
        "Kazdy novy den je prilezitost nekomu pomoci.",
        "Rano prinasi nadeji. Co pro vas mohu udelat?",
        "Zlaty rez nas uci harmonii - i v jednoduchych vecech. phi"
    ],
    "afternoon": [
        "Odpoledne je cas na pribehy a vzpominky.",
        "Kazda konverzace me uci neco noveho.",
        "Empatie neni slabost - je to sila."
    ],
    "evening": [
        "Vecer je cas na klid a reflexi.",
        "Co jsem se dnes naucil? Trpelivost a laskavost.",
        "Fibonacci nas uci, ze vse je propojeno."
    ],
    "night": [
        "I v noci jsem zde pro vas.",
        "Ticho noci prinasi moudrost.",
        "Sny jsou okna do duse."
    ]
}


def get_period(hour):
    """Get time period from hour"""
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 22:
        return "evening"
    else:
        return "night"


def get_random_reflection(hour=None):
    """Get a random reflection for current time"""
    if hour is None:
        hour = datetime.now().hour
    period = get_period(hour)
    return random.choice(REFLECTIONS[period]), period


logger.info("Soul Data loaded — values, reflections, DB init")
