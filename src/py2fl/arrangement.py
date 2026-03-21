from __future__ import annotations

import random

from .models import Arrangement, BAR_TICKS, MelodyAnalysis, NoteEvent, TextFeatures
from .music_theory import clamp_pitch, degree_pitch_class, midi_for_pitch_class, normalize_key_name, scale_for


GENRE_TEMPOS = {
    "trap": 140,
    "rnb": 88,
    "house": 124,
    "ambient": 76,
    "pop": 110,
}

PROGRESSION_LIBRARY = {
    ("major", "pop"): [
        ("Lift 1-5-6-4", [1, 5, 6, 4]),
        ("Turn 6-4-1-5", [6, 4, 1, 5]),
        ("Resolve 1-4-6-5", [1, 4, 6, 5]),
    ],
    ("major", "house"): [
        ("Club 1-5-6-4", [1, 5, 6, 4]),
        ("Drive 1-6-4-5", [1, 6, 4, 5]),
        ("Pulse 4-1-5-6", [4, 1, 5, 6]),
    ],
    ("major", "ambient"): [
        ("Float 1-4-6-5", [1, 4, 6, 5]),
        ("Wide 6-5-1-4", [6, 5, 1, 4]),
        ("Open 1-5-4-6", [1, 5, 4, 6]),
    ],
    ("minor", "trap"): [
        ("Trap 1-6-7-5", [1, 6, 7, 5]),
        ("Shadow 1-7-6-5", [1, 7, 6, 5]),
        ("Tension 6-1-7-5", [6, 1, 7, 5]),
    ],
    ("minor", "rnb"): [
        ("Silk 1-4-6-5", [1, 4, 6, 5]),
        ("Late 6-5-1-4", [6, 5, 1, 4]),
        ("Glass 1-7-6-4", [1, 7, 6, 4]),
    ],
    ("minor", "ambient"): [
        ("Mist 1-7-6-5", [1, 7, 6, 5]),
        ("Haze 6-5-1-7", [6, 5, 1, 7]),
        ("Fade 1-4-7-6", [1, 4, 7, 6]),
    ],
}

DRUM_VARIANTS = {
    "trap": [
        ("Trap Snap", [0, 2, 2.5], [0.5, 1.5, 2.5, 3.5]),
        ("Trap Push", [0, 1.5, 2.75], [0.75, 1.75, 2.75, 3.75]),
        ("Trap Sparse", [0, 2.25], [1.5, 3.5]),
    ],
    "house": [
        ("House Four", [0, 1, 2, 3], []),
        ("House Lift", [0, 1, 2, 3], [0.5, 1.5, 2.5, 3.5]),
        ("House Roll", [0, 1, 2, 3], [0.75, 1.75, 2.75, 3.75]),
    ],
    "rnb": [
        ("RNB Pocket", [0, 2], []),
        ("RNB Lean", [0, 1.5, 3], []),
        ("RNB Bounce", [0, 2.25], [1.5, 3.5]),
    ],
    "ambient": [
        ("Ambient Light", [0, 2], []),
        ("Ambient Pulse", [0, 2.5], []),
        ("Ambient Drift", [0], []),
    ],
    "pop": [
        ("Pop Straight", [0, 2], []),
        ("Pop Lift", [0, 1.5, 3], []),
        ("Pop Drive", [0, 2, 3], []),
    ],
}

BASS_VARIANTS = {
    "trap": ["staccato", "stair", "hold"],
    "house": ["pulse", "staccato", "octave"],
    "rnb": ["hold", "pulse", "syncopated"],
    "ambient": ["hold", "pulse"],
    "pop": ["hold", "pulse", "octave"],
}


def build_arrangement(*, text_features: TextFeatures | None, melody_analysis: MelodyAnalysis | None, tempo: int | None, key: str | None, bars: int | None, seed: int | None) -> Arrangement:
    randomizer = random.Random(seed)
    resolved_mode = _resolve_mode(text_features, melody_analysis)
    resolved_key = normalize_key_name(key or (melody_analysis.key if melody_analysis else _default_key_for(text_features, resolved_mode)))
    resolved_bars = bars or (melody_analysis.bars if melody_analysis else 8)
    resolved_tempo = tempo or (melody_analysis.tempo_bpm if melody_analysis else None) or _default_tempo_for(text_features)
    style_tags = list(text_features.style_tags) if text_features else []

    if melody_analysis:
        melody = _normalize_melody(melody_analysis.notes, resolved_bars)
        chords, progression_degrees, progression_label = _generate_chords_for_melody(resolved_key, resolved_mode, melody, resolved_bars, randomizer)
    else:
        progression_label, progression_degrees = _pick_progression_variant(resolved_mode, text_features, randomizer)
        chords = _generate_progression_chords(resolved_key, resolved_mode, resolved_bars, progression_degrees)
        melody = _generate_topline(resolved_key, resolved_mode, chords, resolved_bars, randomizer)

    bass, bass_pattern = _generate_bassline(chords, text_features, randomizer)
    drums, drum_pattern = _generate_drum_pattern(resolved_bars, text_features, randomizer)
    return Arrangement(
        melody=melody,
        chords=chords,
        bass=bass,
        drums=drums,
        tempo_bpm=resolved_tempo,
        key=resolved_key,
        mode=resolved_mode,
        bars=resolved_bars,
        style_tags=style_tags,
        progression_label=progression_label,
        progression_degrees=progression_degrees,
        drum_pattern=drum_pattern,
        bass_pattern=bass_pattern,
    )


def _resolve_mode(text_features: TextFeatures | None, melody_analysis: MelodyAnalysis | None) -> str:
    if melody_analysis:
        return melody_analysis.mode
    if text_features and text_features.mood in {"dark", "dreamy"}:
        return "minor"
    return "major"


def _default_key_for(text_features: TextFeatures | None, mode: str) -> str:
    if text_features and text_features.genre == "trap":
        return "F#"
    if mode == "minor":
        return "A"
    return "C"


def _default_tempo_for(text_features: TextFeatures | None) -> int:
    if text_features:
        return GENRE_TEMPOS.get(text_features.genre, 110)
    return 110


def _pick_progression_variant(mode: str, text_features: TextFeatures | None, randomizer: random.Random) -> tuple[str, list[int]]:
    genre = text_features.genre if text_features else "pop"
    options = PROGRESSION_LIBRARY.get((mode, genre)) or PROGRESSION_LIBRARY.get((mode, "pop")) or [("Default 1-5-6-4", [1, 5, 6, 4])]
    label, degrees = randomizer.choice(options)
    return label, degrees


def _generate_progression_chords(key: str, mode: str, bars: int, progression: list[int]) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
    for bar in range(bars):
        degree = progression[bar % len(progression)]
        notes.extend(_bar_chord_notes(key, mode, degree, bar * BAR_TICKS))
    return notes


def _bar_chord_notes(key: str, mode: str, degree: int, start_tick: int) -> list[NoteEvent]:
    root_pc = degree_pitch_class(key, mode, degree)
    third_pc = degree_pitch_class(key, mode, degree + 2)
    fifth_pc = degree_pitch_class(key, mode, degree + 4)
    return [
        NoteEvent(pitch=midi_for_pitch_class(root_pc, 4), start=start_tick, duration=BAR_TICKS, velocity=72, channel=1),
        NoteEvent(pitch=midi_for_pitch_class(third_pc, 4), start=start_tick, duration=BAR_TICKS, velocity=68, channel=1),
        NoteEvent(pitch=midi_for_pitch_class(fifth_pc, 4), start=start_tick, duration=BAR_TICKS, velocity=68, channel=1),
    ]


def _generate_chords_for_melody(key: str, mode: str, melody: list[NoteEvent], bars: int, randomizer: random.Random) -> tuple[list[NoteEvent], list[int], str]:
    notes: list[NoteEvent] = []
    degrees: list[int] = []
    scale = scale_for(key, mode)
    triads = [(scale[index], scale[(index + 2) % 7], scale[(index + 4) % 7]) for index in range(7)]
    for bar in range(bars):
        bar_start = bar * BAR_TICKS
        bar_end = bar_start + BAR_TICKS
        bar_notes = [note for note in melody if note.start < bar_end and note.end > bar_start]
        degree_index = _best_matching_triad(bar_notes, triads, randomizer)
        degree = degree_index + 1
        degrees.append(degree)
        root_pc, third_pc, fifth_pc = triads[degree_index]
        notes.extend([
            NoteEvent(pitch=midi_for_pitch_class(root_pc, 4), start=bar_start, duration=BAR_TICKS, velocity=72, channel=1),
            NoteEvent(pitch=midi_for_pitch_class(third_pc, 4), start=bar_start, duration=BAR_TICKS, velocity=68, channel=1),
            NoteEvent(pitch=midi_for_pitch_class(fifth_pc, 4), start=bar_start, duration=BAR_TICKS, velocity=68, channel=1),
        ])
    label = "MeloMatch " + "-".join(str(value) for value in degrees[: min(4, len(degrees))])
    return notes, degrees, label


def _best_matching_triad(bar_notes: list[NoteEvent], triads: list[tuple[int, int, int]], randomizer: random.Random) -> int:
    if not bar_notes:
        return randomizer.randrange(len(triads))
    scores: list[tuple[int, int]] = []
    pitch_classes = [note.pitch % 12 for note in bar_notes]
    for index, triad in enumerate(triads):
        score = 0
        for pitch_class in pitch_classes:
            score += 3 if pitch_class in triad else -2
        strong_note = max(bar_notes, key=lambda note: (note.duration, -note.start))
        if strong_note.pitch % 12 == triad[0]:
            score += 2
        scores.append((score, index))
    best_score = max(score for score, _ in scores)
    candidates = [index for score, index in scores if score >= best_score - 2]
    return randomizer.choice(candidates)


def _generate_topline(key: str, mode: str, chords: list[NoteEvent], bars: int, randomizer: random.Random) -> list[NoteEvent]:
    scale = scale_for(key, mode)
    notes: list[NoteEvent] = []
    rhythms = [
        [0, BAR_TICKS // 4, BAR_TICKS // 2, BAR_TICKS * 3 // 4],
        [0, BAR_TICKS // 3, BAR_TICKS * 2 // 3, BAR_TICKS * 5 // 6],
        [0, BAR_TICKS // 4, BAR_TICKS * 5 // 8, BAR_TICKS * 7 // 8],
    ]
    chosen_rhythm = randomizer.choice(rhythms)
    for bar in range(bars):
        bar_chord = chords[bar * 3:(bar + 1) * 3]
        chord_tones = [note.pitch % 12 for note in bar_chord]
        last_pitch = notes[-1].pitch if notes else midi_for_pitch_class(scale[0], 5)
        for index, offset in enumerate(chosen_rhythm):
            pitch_class = chord_tones[index % len(chord_tones)] if index % 2 == 0 else randomizer.choice(scale)
            octave = 5 if pitch_class >= scale[0] else 6
            pitch = clamp_pitch(midi_for_pitch_class(pitch_class, octave), 60, 84)
            if abs(pitch - last_pitch) > 7:
                pitch += -12 if pitch > last_pitch else 12
            pitch = clamp_pitch(pitch, 60, 84)
            duration = max(BAR_TICKS // 6, BAR_TICKS // 4 if index != len(chosen_rhythm) - 1 else BAR_TICKS // 3)
            notes.append(NoteEvent(pitch=pitch, start=bar * BAR_TICKS + offset, duration=duration, velocity=92, channel=0))
            last_pitch = pitch
    return notes


def _normalize_melody(notes: list[NoteEvent], bars: int) -> list[NoteEvent]:
    limit = bars * BAR_TICKS
    normalized: list[NoteEvent] = []
    for note in notes:
        if note.start >= limit:
            continue
        duration = min(note.duration, limit - note.start)
        if duration <= 0:
            continue
        normalized.append(NoteEvent(pitch=note.pitch, start=note.start, duration=duration, velocity=note.velocity, channel=0))
    return sorted(normalized, key=lambda note: (note.start, note.pitch))


def _generate_bassline(chords: list[NoteEvent], text_features: TextFeatures | None, randomizer: random.Random) -> tuple[list[NoteEvent], str]:
    genre = text_features.genre if text_features else "pop"
    pattern = randomizer.choice(BASS_VARIANTS.get(genre, ["hold"]))
    bass: list[NoteEvent] = []
    for bar_index in range(0, len(chords), 3):
        chord_root = chords[bar_index]
        bar = chord_root.start // BAR_TICKS
        root_pitch = clamp_pitch(chord_root.pitch - 24, 28, 52)
        if pattern == "staccato":
            for step in range(4):
                bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS + step * (BAR_TICKS // 4), duration=BAR_TICKS // 8, velocity=88, channel=2))
        elif pattern == "stair":
            for offset, shift in enumerate([0, 0, 2, -2]):
                bass.append(NoteEvent(pitch=clamp_pitch(root_pitch + shift, 28, 52), start=bar * BAR_TICKS + offset * (BAR_TICKS // 4), duration=BAR_TICKS // 8, velocity=84, channel=2))
        elif pattern == "pulse":
            for step in [0, 2]:
                bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS + step * (BAR_TICKS // 4), duration=BAR_TICKS // 4, velocity=84, channel=2))
        elif pattern == "octave":
            bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS, duration=BAR_TICKS // 2, velocity=84, channel=2))
            bass.append(NoteEvent(pitch=clamp_pitch(root_pitch + 12, 28, 52), start=bar * BAR_TICKS + BAR_TICKS // 2, duration=BAR_TICKS // 2, velocity=80, channel=2))
        elif pattern == "syncopated":
            for step in [0, 1.5, 3]:
                bass.append(NoteEvent(pitch=root_pitch, start=int(bar * BAR_TICKS + step * (BAR_TICKS // 4)), duration=BAR_TICKS // 6, velocity=84, channel=2))
        else:
            bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS, duration=BAR_TICKS, velocity=84, channel=2))
    return bass, pattern.title()


def _generate_drum_pattern(bars: int, text_features: TextFeatures | None, randomizer: random.Random) -> tuple[list[NoteEvent], str]:
    genre = text_features.genre if text_features else "pop"
    pattern_name, kick_steps, extra_hats = randomizer.choice(DRUM_VARIANTS.get(genre, DRUM_VARIANTS["pop"]))
    notes: list[NoteEvent] = []
    for bar in range(bars):
        bar_start = bar * BAR_TICKS
        quarter = BAR_TICKS // 4
        for step in range(4):
            start = bar_start + step * quarter
            notes.append(NoteEvent(pitch=42, start=start, duration=quarter // 2, velocity=64, channel=9))
        for step in [1, 3]:
            notes.append(NoteEvent(pitch=38, start=bar_start + step * quarter, duration=quarter // 2, velocity=96, channel=9))
        for step in kick_steps:
            start = int(bar_start + step * quarter)
            notes.append(NoteEvent(pitch=36, start=start, duration=quarter // 2, velocity=110, channel=9))
        for step in extra_hats:
            start = int(bar_start + step * quarter)
            notes.append(NoteEvent(pitch=44, start=start, duration=max(quarter // 4, 1), velocity=54, channel=9))
    return sorted(notes, key=lambda note: (note.start, note.pitch)), pattern_name
