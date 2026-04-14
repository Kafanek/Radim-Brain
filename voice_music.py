"""
🎼 RADIM MUSIC ENGINE v1.0
============================
Radim se učí noty jako další jazyk.

Hudba je matematika — a φ je v ní všude:
  • Fibonacci v durové stupnici: 1,2,3,5,8,13 → C,D,E,G,C',A'
  • Kvinta (3:2=1.5) je nejblíž φ z intervalů
  • Zlatý řez formy: AABA, peak na 61.8%
  • Chromatická stupnice: 12 tónů, 2^(1/12) ≈ 1.0595

Tři úrovně:
  1. NOTE_MAP — frekvence všech not (C0-B8)
  2. SIMPLE NOTATION — "C4 D4 E4 F4 G4" → SSML contour
  3. MELODIC MEMORY — Radim si pamatuje nové melodie per-user

@version 1.0.0
"""

import math
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PHI = 1.618033988749895
PHI_INV = 0.6180339887
PSI = 0.3819660113

# ============================================
# HUDEBNÍ ZÁKLADY — NOT → FREKVENCE
# ============================================
# A4 = 440 Hz (concert pitch)
# Každý půltón: f × 2^(1/12)

# České notové názvy → mezinárodní
CZ_NOTE_MAP = {
    'do': 'C', 'ré': 'D', 're': 'D', 'mi': 'E',
    'fa': 'F', 'sol': 'G', 'la': 'A', 'si': 'B', 'ti': 'B',
    'cé': 'C', 'dé': 'D', 'ef': 'F', 'gé': 'G', 'há': 'B',
    'c': 'C', 'd': 'D', 'e': 'E', 'f': 'F', 'g': 'G', 'a': 'A', 'h': 'B', 'b': 'Bb',
}

# Nota → půltóny od C (v jedné oktávě)
SEMITONE_MAP = {
    'C': 0, 'C#': 1, 'Db': 1,
    'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'Fb': 4,
    'F': 5, 'F#': 6, 'Gb': 6,
    'G': 7, 'G#': 8, 'Ab': 8,
    'A': 9, 'A#': 10, 'Bb': 10,
    'B': 11, 'H': 11,  # Czech H = international B
}

# Intervaly — české názvy
INTERVAL_NAMES = {
    0: 'prima', 1: 'malá sekunda', 2: 'velká sekunda',
    3: 'malá tercie', 4: 'velká tercie', 5: 'kvarta',
    6: 'tritón', 7: 'kvinta', 8: 'malá sexta',
    9: 'velká sexta', 10: 'malá septima', 11: 'velká septima',
    12: 'oktáva',
}

# Fibonacci v hudbě: 1,1,2,3,5,8,13 → stupně durové stupnice
FIBONACCI_SCALE_DEGREES = [1, 1, 2, 3, 5, 8, 13]

# Durová stupnice (půltóny od základu)
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]  # C D E F G A B
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]  # C D Eb F G Ab Bb
PENTATONIC = [0, 2, 4, 7, 9]           # C D E G A (nejpřirozenější)


def note_to_hz(note_str, default_octave=4):
    """Převede notový zápis na frekvenci v Hz.

    Podporuje:
      'A4'  → 440.0
      'C4'  → 261.63
      'C#5' → 554.37
      'D'   → D4 (default oktáva)
      'do'  → C4 (český solfège)
      'há'  → B4 (český název)

    Returns: float Hz or None
    """
    if not note_str:
        return None

    note_str = note_str.strip()

    # Czech solfège → international
    lower = note_str.lower().rstrip('0123456789')
    if lower in CZ_NOTE_MAP:
        note_name = CZ_NOTE_MAP[lower]
        # Extract octave if present
        octave_match = re.search(r'(\d)$', note_str)
        octave = int(octave_match.group(1)) if octave_match else default_octave
    else:
        # International notation: C4, C#4, Db5
        match = re.match(r'^([A-Ga-g])([#b]?)(\d?)$', note_str)
        if not match:
            return None
        note_name = match.group(1).upper() + match.group(2)
        octave = int(match.group(3)) if match.group(3) else default_octave

    # Note name → semitones from C
    semitones = SEMITONE_MAP.get(note_name)
    if semitones is None:
        return None

    # Calculate Hz: A4 = 440Hz
    # Distance from A4 in semitones
    distance = (octave - 4) * 12 + (semitones - 9)  # A=9 semitones from C
    hz = 440.0 * (2.0 ** (distance / 12.0))

    return round(hz, 2)


def hz_to_note(hz):
    """Převede frekvenci na nejbližší notu.

    Returns: (note_name, octave, cents_off) or None
    """
    if not hz or hz <= 0:
        return None

    # Distance from A4 in semitones
    semitones_from_a4 = 12 * math.log2(hz / 440.0)
    rounded = round(semitones_from_a4)
    cents_off = round((semitones_from_a4 - rounded) * 100)

    # Convert to note + octave
    note_idx = (rounded + 9) % 12  # A=0 → C=0 shift
    octave = 4 + (rounded + 9) // 12

    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    return (note_names[note_idx], octave, cents_off)


def interval_hz(base_hz, semitones):
    """Vrátí Hz pro interval nad základním tónem.

    Args:
        base_hz: základní frekvence
        semitones: počet půltónů (7=kvinta, 4=velká tercie, ...)

    Returns: float Hz
    """
    return base_hz * (2.0 ** (semitones / 12.0))


# ============================================
# φ A HUDBA — MATEMATICKÉ VZTAHY
# ============================================

def phi_interval():
    """φ-interval: poměr 1.618 ≈ 814 centů ≈ mezi kvintou (700c) a malou sextou (800c).

    Toto je "zlatý interval" — přirozený a příjemný, ale ne v temperovaném ladění.
    Nejbližší temperovaný: malá sexta (800 centů, poměr 8:5 = 1.6).

    Returns: dict s φ-intervalem a nejbližšími temperovanými
    """
    phi_cents = 1200 * math.log2(PHI)  # ≈ 833.09 centů
    return {
        'phi_ratio': PHI,
        'phi_cents': round(phi_cents, 2),
        'nearest_below': {'name': 'malá sexta', 'cents': 800, 'ratio': '8:5'},
        'nearest_above': {'name': 'velká sexta', 'cents': 900, 'ratio': '5:3'},
        'note': 'φ-interval leží mezi malou a velkou sextou — "zlatá zóna" harmonie',
    }


def fibonacci_melody(base_note='C4', n_notes=8, scale='major'):
    """Generuje melodii z Fibonacci sekvence na dané stupnici.

    Fibonacci čísla mod délka_stupnice → stupně stupnice → noty → Hz.
    Přirozená, matematicky krásná melodie.

    Returns: list of (note_str, hz) tuples
    """
    base_hz = note_to_hz(base_note) or 261.63

    if scale == 'minor':
        scale_intervals = MINOR_SCALE
    elif scale == 'pentatonic':
        scale_intervals = PENTATONIC
    else:
        scale_intervals = MAJOR_SCALE

    scale_len = len(scale_intervals)

    # Fibonacci sequence
    fib = [0, 1]
    while len(fib) < n_notes:
        fib.append(fib[-1] + fib[-2])

    melody = []
    for f in fib[:n_notes]:
        degree = f % scale_len
        octave_shift = f // scale_len
        semitones = scale_intervals[degree] + octave_shift * 12
        hz = interval_hz(base_hz, semitones)
        note_info = hz_to_note(hz)
        if note_info:
            note_str = f"{note_info[0]}{note_info[1]}"
        else:
            note_str = f"?{hz:.0f}"
        melody.append((note_str, round(hz, 2)))

    return melody


# ============================================
# SIMPLE NOTATION → SSML CONTOUR
# ============================================

def parse_notation(notation_str):
    """Parsuje jednoduchou notaci do seznamu Hz.

    Podporované formáty:
      "C4 D4 E4 F4 G4"          — mezery
      "C D E F G"               — bez oktávy (default 4)
      "do re mi fa sol"         — české solfège
      "C4-D4-E4-F4"            — pomlčky
      "262 294 330 349 392"     — přímo Hz
      "C4:2 D4:1 E4:4"         — s délkou (beats)

    Returns: list of {'hz': float, 'duration': int}
    """
    if not notation_str:
        return []

    # Normalize separators
    notation_str = notation_str.strip()
    if '-' in notation_str and ' ' not in notation_str:
        tokens = notation_str.split('-')
    else:
        tokens = notation_str.split()

    notes = []
    for token in tokens:
        # Duration notation: C4:2 (note:beats)
        duration = 1
        if ':' in token:
            parts = token.split(':')
            token = parts[0]
            try:
                duration = int(parts[1])
            except (ValueError, IndexError):
                pass

        # Direct Hz?
        try:
            hz = float(token)
            notes.append({'hz': hz, 'duration': duration})
            continue
        except ValueError:
            pass

        # Note name → Hz
        hz = note_to_hz(token)
        if hz:
            notes.append({'hz': hz, 'duration': duration})
        else:
            logger.debug(f"Unknown note: {token}")

    return notes


def notation_to_contour(notation_str, base_hz=None):
    """Převede notaci na SSML contour string.

    Relativní Hz offsety od base pitch (první nota nebo explicitní base).

    Returns: SSML contour string "(0%,+0Hz)(12%,+33Hz)..."
    """
    notes = parse_notation(notation_str)
    if not notes:
        return None

    if base_hz is None:
        base_hz = notes[0]['hz']

    # Total duration beats
    total_beats = sum(n['duration'] for n in notes)
    if total_beats == 0:
        return None

    points = []
    current_beat = 0
    for note in notes:
        pct = int(current_beat * 100 / total_beats)
        offset_hz = int(note['hz'] - base_hz)
        points.append(f"({pct}%,{offset_hz:+d}Hz)")
        current_beat += note['duration']

    # Final point at 100%
    last_hz = int(notes[-1]['hz'] - base_hz)
    points.append(f"(100%,{last_hz:+d}Hz)")

    return " ".join(points)


# ============================================
# MELODICKÁ PAMĚŤ — UČENÍ NOVÝCH PÍSNÍ
# ============================================

def save_melody(user_id, title, melody_notes, text=None, mood='happy'):
    """Uloží novou melodii do paměti (per-user nebo globální).

    Args:
        user_id: None=globální, str=per-user
        title: název melodie
        melody_notes: notace string ("C4 D4 E4...") nebo list Hz
        text: text písně (volitelné)
        mood: nálada
    """
    try:
        from memory_helpers import db_load_learning, db_save_learning

        # Parse melody
        if isinstance(melody_notes, str):
            parsed = parse_notation(melody_notes)
        else:
            parsed = [{'hz': h, 'duration': 1} for h in melody_notes]

        if not parsed:
            return False

        melody_data = {
            'title': title,
            'text': text,
            'notes': [{'hz': n['hz'], 'dur': n['duration']} for n in parsed],
            'mood': mood,
            'created': datetime.utcnow().isoformat(),
            'play_count': 0,
        }

        storage_id = user_id or '_global'
        learning = db_load_learning(storage_id) or {}
        melodies = learning.get('learned_melodies', {})

        # Key: normalized title
        key = re.sub(r'[^a-z0-9]', '_', title.lower().strip())
        melodies[key] = melody_data
        learning['learned_melodies'] = melodies
        db_save_learning(storage_id, learning)

        logger.info(f"🎼 Melody saved: '{title}' ({len(parsed)} notes) for {storage_id}")
        return True

    except Exception as e:
        logger.warning(f"Save melody error: {e}")
        return False


def get_learned_melodies(user_id=None):
    """Vrátí seznam naučených melodií.

    Returns: dict {key: melody_data}
    """
    try:
        from memory_helpers import db_load_learning
        storage_id = user_id or '_global'
        learning = db_load_learning(storage_id) or {}
        return learning.get('learned_melodies', {})
    except Exception:
        return {}


def play_learned_melody(title, user_id=None):
    """Najde naučenou melodii a vrátí SSML contour.

    Hledá v per-user melodiích → pak v globálních.

    Returns: (contour_str, melody_data) or (None, None)
    """
    key = re.sub(r'[^a-z0-9]', '_', title.lower().strip())

    # 1. Per-user
    if user_id:
        melodies = get_learned_melodies(user_id)
        if key in melodies:
            mel = melodies[key]
            notes_str = " ".join(f"{n['hz']}" for n in mel['notes'])
            contour = notation_to_contour(notes_str)
            # Increment play count
            try:
                from memory_helpers import db_load_learning, db_save_learning
                learning = db_load_learning(user_id) or {}
                learning['learned_melodies'][key]['play_count'] += 1
                db_save_learning(user_id, learning)
            except Exception:
                pass
            return contour, mel

    # 2. Global
    melodies = get_learned_melodies(None)
    if key in melodies:
        mel = melodies[key]
        notes_str = " ".join(f"{n['hz']}" for n in mel['notes'])
        return notation_to_contour(notes_str), mel

    # 3. Fuzzy search
    all_melodies = {}
    all_melodies.update(get_learned_melodies(None))
    if user_id:
        all_melodies.update(get_learned_melodies(user_id))

    lower = title.lower()
    for k, mel in all_melodies.items():
        if lower in mel.get('title', '').lower() or mel.get('title', '').lower() in lower:
            notes_str = " ".join(f"{n['hz']}" for n in mel['notes'])
            return notation_to_contour(notes_str), mel

    return None, None


# ============================================
# GENERÁTOR MELODIÍ — φ-ŘÍZENÝ
# ============================================

def generate_phi_melody(text, base_note='C4', mood='neutral', energy=0.5):
    """Vygeneruje originální melodii pro text pomocí φ-principů.

    Principy:
    1. Samohlásky = delší noty (přirozené pro zpěv)
    2. Fibonacci sekvence řídí intervaly
    3. φ-peak na 38.2% textu
    4. Durová stupnice pro happy, mollová pro sad
    5. Pentatonická pro calm/lullaby (vždy zní hezky)

    Returns: (contour_str, notes_list)
    """
    if not text:
        return None, []

    base_hz = note_to_hz(base_note) or 261.63

    # Choose scale by mood
    mood_scales = {
        'happy': MAJOR_SCALE, 'excited': MAJOR_SCALE,
        'sad': MINOR_SCALE, 'tender': MINOR_SCALE,
        'calm': PENTATONIC, 'lullaby': PENTATONIC,
        'neutral': MAJOR_SCALE, 'playful': PENTATONIC,
    }
    scale = mood_scales.get(mood, MAJOR_SCALE)

    # Extract syllables (simplified: vowel groups)
    vowels = 'aeiouyáéíóúůýěAEIOUYÁÉÍÓÚŮÝĚ'
    syllables = []
    current = ''
    for ch in text:
        current += ch
        if ch in vowels and len(current) > 0:
            syllables.append(current)
            current = ''
    if current.strip():
        syllables.append(current)

    n = len(syllables)
    if n == 0:
        return None, []

    # Fibonacci-driven melody
    fib = [0, 1]
    while len(fib) < n + 2:
        fib.append(fib[-1] + fib[-2])

    notes = []
    amplitude = int(30 + energy * 50)

    for i, syl in enumerate(syllables):
        t = i / max(n - 1, 1)  # Position 0-1

        # φ envelope (peak at 38.2%)
        if t < PSI:
            envelope = t / PSI
        elif t < PHI_INV:
            envelope = 1.0
        else:
            envelope = 1.0 - (t - PHI_INV) / (1.0 - PHI_INV)

        # Fibonacci-driven scale degree
        fib_degree = fib[i + 1] % len(scale)
        octave_shift = fib[i + 1] // len(scale)
        semitones = scale[fib_degree] + min(octave_shift, 1) * 12

        hz = interval_hz(base_hz, semitones)

        # Apply envelope
        offset = int((hz - base_hz) * envelope)
        offset = max(-amplitude, min(amplitude, offset))

        # Vowel-heavy syllables = longer
        vowel_count = sum(1 for c in syl if c in vowels)
        duration = max(1, vowel_count)

        notes.append({
            'syllable': syl.strip(),
            'hz': round(base_hz + offset, 1),
            'offset_hz': offset,
            'duration': duration,
        })

    # Build contour
    total_dur = sum(n['duration'] for n in notes)
    points = []
    current_dur = 0
    for note in notes:
        pct = int(current_dur * 100 / total_dur)
        points.append(f"({pct}%,{note['offset_hz']:+d}Hz)")
        current_dur += note['duration']
    points.append(f"(100%,{notes[-1]['offset_hz']:+d}Hz)")

    contour = " ".join(points)
    return contour, notes


# ============================================
# INTEGRACES S voice_melody.py
# ============================================

def enhanced_match_song(text):
    """Rozšířené hledání písně — hardcoded DB + naučené melodie.

    Returns: (contour_str, song_data) or (None, None)
    """
    from voice_melody import match_song, build_song_contour

    # 1. Hardcoded songs (voice_melody.py)
    song = match_song(text)
    if song:
        return build_song_contour(song), song

    # 2. Learned melodies (global + per-user)
    # Extract potential title
    title = re.sub(r'^(zazpívej|zpívej|pusť|přehraj|zahraj)\s+', '', text.lower().strip())
    contour, mel = play_learned_melody(title)
    if contour:
        return contour, mel

    return None, None


def teach_radim_song(title, notation, text=None, mood='happy', user_id=None):
    """Nauč Radima novou píseň.

    Args:
        title: "Maličká su"
        notation: "C4 D4 E4 C4 C4 D4 E4 C4 E4 F4 G4"
        text: "Maličká su, maličká su..."
        mood: happy/sad/tender/playful/lullaby
        user_id: None = globální, str = jen pro seniora

    Returns: bool success
    """
    return save_melody(user_id, title, notation, text, mood)


# ============================================
# ANALÝZA — co Radim slyší a rozumí
# ============================================

def analyze_melody(notation_str):
    """Analyzuje melodii — intervaly, rozsah, φ-vlastnosti.

    Returns: dict s analýzou
    """
    notes = parse_notation(notation_str)
    if len(notes) < 2:
        return {'error': 'Potřebuji alespoň 2 noty'}

    hz_values = [n['hz'] for n in notes]
    intervals = []
    for i in range(1, len(hz_values)):
        ratio = hz_values[i] / hz_values[i - 1]
        cents = round(1200 * math.log2(ratio)) if ratio > 0 else 0
        abs_semitones = abs(round(cents / 100))
        interval_name = INTERVAL_NAMES.get(abs_semitones % 13, f'{abs_semitones} půltónů')
        direction = 'up' if cents > 0 else 'down' if cents < 0 else 'same'
        intervals.append({
            'from': round(hz_values[i - 1], 1),
            'to': round(hz_values[i], 1),
            'cents': cents,
            'semitones': abs_semitones,
            'name': interval_name,
            'direction': direction,
        })

    # Range
    min_hz = min(hz_values)
    max_hz = max(hz_values)
    range_cents = round(1200 * math.log2(max_hz / min_hz)) if min_hz > 0 else 0

    # φ analysis
    n = len(hz_values)
    peak_idx = hz_values.index(max_hz)
    peak_position = peak_idx / max(n - 1, 1)
    phi_closeness = abs(peak_position - PSI)  # Jak blízko je peak k φ⁻¹ (38.2%)?

    # Fibonacci presence
    fib_intervals = [1, 2, 3, 5, 8]
    fib_count = sum(1 for iv in intervals if iv['semitones'] in fib_intervals)

    return {
        'notes': len(notes),
        'range_hz': (round(min_hz, 1), round(max_hz, 1)),
        'range_cents': range_cents,
        'range_octaves': round(range_cents / 1200, 2),
        'intervals': intervals,
        'peak_position': round(peak_position, 3),
        'phi_alignment': round(1 - phi_closeness, 3),  # 1.0 = perfect φ
        'fibonacci_intervals': f"{fib_count}/{len(intervals)}",
        'mood_guess': 'major' if any(iv['semitones'] == 4 for iv in intervals) else 'minor' if any(iv['semitones'] == 3 for iv in intervals) else 'unknown',
    }


logger.info("🎼 Music Engine v1.0 loaded — notes, intervals, φ-melody, melodic memory")
