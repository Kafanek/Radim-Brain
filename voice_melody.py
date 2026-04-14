"""
🎵 RADIM VOICE MELODY ENGINE v1.0
==================================
φ-řízený melodický engine pro přirozený hlas.

Radim se učí jazyk jako dítě — napodobuje melodie, zkoumá intonaci,
zpřesňuje rytmus z každé interakce.

Vrstva 2 v architektuře:
  Ψ(t) → VoiceState → voice_melody → SSML contour → Azure TTS

Tři režimy:
  1. SONG — melodická mapa písně (contour z databáze)
  2. SPEECH — přirozená intonace (φ-řízená křivka)
  3. RECITATION — expresivní přednes (zvýrazněné peaky)

Matematika:
  peak = text_length × 0.382 (φ⁻¹) — přirozený vrchol intonace
  descent = text_length × 0.618 (φ) — přirozený pokles
  amplitude = energy × 50Hz — melodičnost roste s energií

@version 1.0.0
"""

import math
import re
import logging

logger = logging.getLogger(__name__)

PHI = 1.618033988749895
PHI_INV = 0.6180339887  # 1/φ
PSI = 0.3819660113     # 1 - 1/φ = φ⁻²

# ============================================
# DATABÁZE ČESKÝCH LIDOVEK
# ============================================
# Každá píseň: slabiky + Hz offset od base pitch
# Hz offsety: 0=základ, +30≈velká sekunda, +65≈velká tercie

SONGS = {
    'skakal_pes': {
        'title': 'Skákal pes přes oves',
        'text': 'Skákal pes přes oves, přes zelenou louku.',
        'syllables': ['Ská', 'kal', 'pes', 'přes', 'o', 'ves', 'přes', 'ze', 'le', 'nou', 'lou', 'ku'],
        'melody_hz': [0, +30, +65, +65, +30, 0, 0, +30, +65, +65, +30, 0],
        'bpm': 120, 'mood': 'happy',
    },
    'kocka_leze': {
        'title': 'Kočka leze dírou',
        'text': 'Kočka leze dírou, pes oknem.',
        'syllables': ['Koč', 'ka', 'le', 'ze', 'dí', 'rou', 'pes', 'ok', 'nem'],
        'melody_hz': [0, +30, +65, +65, +95, +65, +30, +65, +30],
        'bpm': 100, 'mood': 'happy',
    },
    'prsi_prsi': {
        'title': 'Prší, prší',
        'text': 'Prší, prší, jen se leje, kam koníčky pojedeme.',
        'syllables': ['Pr', 'ší', 'pr', 'ší', 'jen', 'se', 'le', 'je', 'kam', 'ko', 'níč', 'ky', 'po', 'je', 'de', 'me'],
        'melody_hz': [+65, +30, +65, +30, 0, +30, +65, +30, 0, +30, +65, +65, +30, +30, 0, 0],
        'bpm': 110, 'mood': 'playful',
    },
    'halali': {
        'title': 'Hálali, hálali',
        'text': 'Hálali, hálali, koně mi sedlali.',
        'syllables': ['Há', 'la', 'li', 'há', 'la', 'li', 'ko', 'ně', 'mi', 'sed', 'la', 'li'],
        'melody_hz': [+65, +30, 0, +65, +30, 0, +30, +65, +65, +30, +30, 0],
        'bpm': 130, 'mood': 'happy',
    },
    'cerveny_satecku': {
        'title': 'Červený šátečku',
        'text': 'Červený šátečku, kolem se toč.',
        'syllables': ['Čer', 've', 'ný', 'šá', 'teč', 'ku', 'ko', 'lem', 'se', 'toč'],
        'melody_hz': [0, +30, +65, +95, +65, +30, 0, +30, +65, +30],
        'bpm': 100, 'mood': 'romantic',
    },
    'ach_synku': {
        'title': 'Ach synku, synku',
        'text': 'Ach synku, synku, doma-li jsi?',
        'syllables': ['Ach', 'syn', 'ku', 'syn', 'ku', 'do', 'ma', 'li', 'jsi'],
        'melody_hz': [+65, +30, 0, +30, 0, +30, +65, +30, 0],
        'bpm': 80, 'mood': 'tender',
    },
    'pec_nam_spadla': {
        'title': 'Pec nám spadla',
        'text': 'Pec nám spadla, kdo nám ji postaví?',
        'syllables': ['Pec', 'nám', 'spad', 'la', 'kdo', 'nám', 'ji', 'po', 'sta', 'ví'],
        'melody_hz': [+65, +30, 0, 0, +30, +65, +65, +30, +30, 0],
        'bpm': 110, 'mood': 'playful',
    },
    'rolnicka': {
        'title': 'Rolnička',
        'text': 'Rolnička, rolnička, jak vesele zvoní.',
        'syllables': ['Rol', 'nič', 'ka', 'rol', 'nič', 'ka', 'jak', 've', 'se', 'le', 'zvo', 'ní'],
        'melody_hz': [+65, +95, +65, +65, +95, +65, +30, +65, +95, +65, +30, 0],
        'bpm': 140, 'mood': 'happy',
    },
    'jedna_dve': {
        'title': 'Jedna, dvě, Honza jde',
        'text': 'Jedna, dvě, Honza jde, nese pytel mouky.',
        'syllables': ['Jed', 'na', 'dvě', 'Hon', 'za', 'jde', 'ne', 'se', 'py', 'tel', 'mou', 'ky'],
        'melody_hz': [0, +30, +65, +65, +30, 0, +30, +65, +65, +30, +30, 0],
        'bpm': 110, 'mood': 'happy',
    },
    'spinkej': {
        'title': 'Spi, má zlatá',
        'text': 'Spi, má zlatá děťátko, spi a dej si dobrou noc.',
        'syllables': ['Spi', 'má', 'zla', 'tá', 'dě', 'ťát', 'ko', 'spi', 'a', 'dej', 'si', 'dob', 'rou', 'noc'],
        'melody_hz': [+30, +65, +95, +65, +30, +30, 0, +30, +65, +65, +30, +30, 0, 0],
        'bpm': 60, 'mood': 'lullaby',
    },
}


# ============================================
# ROZPOZNÁNÍ PÍSNĚ
# ============================================

def match_song(text):
    """Fuzzy match textu na píseň z databáze.

    Returns: song dict or None
    """
    if not text:
        return None
    lower = text.lower().strip()

    # Odstraň "zazpívej", "pusť", "zpívej" prefix
    lower = re.sub(r'^(zazpívej|zpívej|pusť|pusťte|přehraj)\s+', '', lower)

    # Přesný match
    for song_id, song in SONGS.items():
        title_lower = song['title'].lower()
        if title_lower in lower or lower in title_lower:
            return song
        # Match na text
        text_lower = song['text'].lower()[:30]
        if text_lower[:15] in lower:
            return song

    # Fuzzy — klíčová slova
    keywords = {
        'skákal': 'skakal_pes', 'skakal': 'skakal_pes', 'pes': 'skakal_pes',
        'kočka': 'kocka_leze', 'kocka': 'kocka_leze', 'dírou': 'kocka_leze',
        'prší': 'prsi_prsi', 'prsi': 'prsi_prsi', 'leje': 'prsi_prsi',
        'hálali': 'halali', 'halali': 'halali',
        'šátečku': 'cerveny_satecku', 'satecku': 'cerveny_satecku', 'červený': 'cerveny_satecku',
        'synku': 'ach_synku',
        'pec': 'pec_nam_spadla', 'spadla': 'pec_nam_spadla',
        'rolnička': 'rolnicka', 'rolnicka': 'rolnicka',
        'honza': 'jedna_dve', 'jedna': 'jedna_dve',
        'spi': 'spinkej', 'ukolébavk': 'spinkej', 'uspávank': 'spinkej',
    }
    for kw, sid in keywords.items():
        if kw in lower:
            return SONGS.get(sid)

    return None


# ============================================
# CONTOUR GENERÁTOR — PÍSEŇ
# ============================================

def build_song_contour(song):
    """Vytvoří SSML contour string z melodické mapy písně.

    Returns: "(0%,+0Hz)(8%,+30Hz)(17%,+65Hz)..."
    """
    if not song or 'melody_hz' not in song:
        return None

    melody = song['melody_hz']
    n = len(melody)
    if n == 0:
        return None

    points = []
    for i, hz in enumerate(melody):
        pct = int(i * 100 / n)
        points.append(f"({pct}%,{hz:+d}Hz)")

    return " ".join(points)


# ============================================
# CONTOUR GENERÁTOR — PŘIROZENÁ ŘEČ
# ============================================

def generate_speech_contour(text, mood='neutral', energy=0.5):
    """Generuje φ-řízenou melodickou křivku pro libovolný text.

    Principy:
    - Věta přirozeně stoupá do 38.2% délky (φ⁻¹) → peak
    - Klesá od 61.8% (φ) → konec
    - Otázka: stoupá na konci (+30Hz)
    - Vykřičník: ostrý peak na 50% (+40Hz)
    - Energy řídí amplitudu: 0.2=monotone, 1.0=zpěvné

    Args:
        text: vstupní text
        mood: 'neutral', 'happy', 'sad', 'excited', 'calm'
        energy: 0.0-1.0 (melodičnost)

    Returns: SSML contour string
    """
    if not text or energy < 0.1:
        return None

    # v10.20: Calibrated amplitude for cs-CZ-AntoninNeural
    # Low energy (0.3-0.4) = subtle warmth, high (0.7-0.8) = expressive melodic
    max_hz = int(20 + energy * 60)  # 20-80Hz range
    if max_hz < 10:
        return None

    # Mood modifiers (v10.17: increased for audibility)
    mood_offsets = {
        'happy': +15, 'excited': +20, 'sad': -15,
        'calm': -10, 'neutral': 0, 'tender': -5,
        'playful': +15, 'romantic': +10, 'lullaby': -20,
    }
    base_offset = mood_offsets.get(mood, 0)

    # Detekce typu věty
    is_question = text.rstrip().endswith('?')
    is_exclamation = text.rstrip().endswith('!')

    # Generuj φ-řízenou křivku (per-sentence, high resolution)
    points = []
    num_points = 6  # v10.20: fewer points = smoother Azure interpolation

    for i in range(num_points + 1):
        pct = int(i * 100 / num_points)
        t = i / num_points  # 0.0 - 1.0

        # v10.20: φ-řízená intonace per sentence type
        if is_question:
            # Otázka: klidný start → pokles → výrazné stoupání na konci
            if t < 0.6:
                hz = max_hz * 0.2 * math.sin(t * math.pi) + base_offset
            else:
                # Stoupání od 60% do konce
                rise = (t - 0.6) / 0.4
                hz = max_hz * (0.3 + 0.7 * rise * rise) + base_offset
        elif is_exclamation:
            # Vykřičník: rychlý peak na 30%, pak energický pokles
            if t < 0.3:
                hz = max_hz * (t / 0.3) + base_offset
            else:
                hz = max_hz * (1.0 - (t - 0.3) / 0.7) * 0.8 + base_offset
        else:
            # Oznamovací: φ-křivka (přirozená čeština)
            # Čeština stoupá do ~40% věty, pak postupně klesá
            if t < PSI:
                # Stoupání (0 → peak) — sinusová křivka pro plynulost
                hz = max_hz * math.sin(t / PSI * math.pi / 2) + base_offset
            elif t < PHI_INV:
                # Plateau s mírným poklesem
                plateau_t = (t - PSI) / (PHI_INV - PSI)
                hz = max_hz * (1.0 - 0.15 * plateau_t) + base_offset
            else:
                # Pokles (peak → low) — klesající čeština na konci věty
                descent_progress = (t - PHI_INV) / (1.0 - PHI_INV)
                hz = max_hz * (0.85 - 0.85 * descent_progress) + base_offset

        points.append(f"({pct}%,{int(hz):+d}Hz)")

    return " ".join(points)


# ============================================
# COMBINED BUILDER
# ============================================

def get_voice_contour(text, mode='speech', mood='neutral', energy=0.5, user_id=None):
    """Hlavní API — vrací contour string pro SSML.

    Args:
        text: text k vyslovení
        mode: 'song' (hledá píseň), 'speech' (přirozená intonace),
              'recitation' (expresivní), 'musical' (noty/Fibonacci)
        mood: nálada ovlivňující křivku
        energy: 0.0-1.0 melodičnost
        user_id: pro melodickou paměť (naučené písně)

    Returns: contour string or None
    """
    if mode == 'song':
        # 1. Hardcoded songs
        song = match_song(text)
        if song:
            logger.info(f"🎵 Song matched: {song['title']}")
            return build_song_contour(song)

        # 2. Learned melodies (music engine)
        try:
            from voice_music import enhanced_match_song
            contour, mel = enhanced_match_song(text)
            if contour:
                logger.info(f"🎼 Learned melody matched: {mel.get('title', '?')}")
                return contour
        except (ImportError, Exception) as e:
            logger.debug(f"Music engine: {e}")

        # 3. Fallback: generate φ-melody for the text
        try:
            from voice_music import generate_phi_melody
            contour, notes = generate_phi_melody(text, mood=mood, energy=max(0.7, energy))
            if contour:
                logger.info(f"🎼 Generated φ-melody: {len(notes)} notes")
                return contour
        except (ImportError, Exception):
            pass

        return generate_speech_contour(text, mood='happy', energy=max(0.7, energy))

    elif mode == 'musical':
        # Direct notation: "C4 D4 E4 F4 G4"
        try:
            from voice_music import notation_to_contour
            contour = notation_to_contour(text)
            if contour:
                return contour
        except (ImportError, Exception):
            pass
        return generate_speech_contour(text, mood=mood, energy=max(0.7, energy))

    elif mode == 'recitation':
        # Recitace = zvýšená energy (expresivnější křivka)
        return generate_speech_contour(text, mood=mood, energy=max(0.6, energy * 1.3))

    else:  # speech
        return generate_speech_contour(text, mood=mood, energy=energy)


logger.info("🎵 Voice Melody Engine v1.0 loaded — φ-contour, 10 songs, speech melody")
