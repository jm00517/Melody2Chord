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

PROGRESSIONS = {
    ("major", "pop"): [1, 5, 6, 4],
    ("major", "house"): [1, 5, 6, 4],
    ("major", "ambient"): [1, 4, 6, 5],
    ("minor", "trap"): [1, 6, 7, 5],
    ("minor", "rnb"): [1, 4, 6, 5],
    ("minor", "ambient"): [1, 7, 6, 5],
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
        chords = _generate_chords_for_melody(resolved_key, resolved_mode, melody, resolved_bars)
    else:
        chords = _generate_progression_chords(resolved_key, resolved_mode, resolved_bars, text_features)
        melody = _generate_topline(resolved_key, resolved_mode, chords, resolved_bars, randomizer)

    bass = _generate_bassline(chords, text_features)
    drums = _generate_drum_pattern(resolved_bars, text_features)
    return Arrangement(melody=melody, chords=chords, bass=bass, drums=drums, tempo_bpm=resolved_tempo, key=resolved_key, mode=resolved_mode, bars=resolved_bars, style_tags=style_tags)


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


def _progression(mode: str, text_features: TextFeatures | None) -> list[int]:
    genre = text_features.genre if text_features else "pop"
    return PROGRESSIONS.get((mode, genre), PROGRESSIONS.get((mode, "pop"), [1, 5, 6, 4]))


def _generate_progression_chords(key: str, mode: str, bars: int, text_features: TextFeatures | None) -> list[NoteEvent]:
    progression = _progression(mode, text_features)
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


def _generate_chords_for_melody(key: str, mode: str, melody: list[NoteEvent], bars: int) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
    scale = scale_for(key, mode)
    triads = [(scale[index], scale[(index + 2) % 7], scale[(index + 4) % 7]) for index in range(7)]
    for bar in range(bars):
        bar_start = bar * BAR_TICKS
        bar_end = bar_start + BAR_TICKS
        bar_notes = [note for note in melody if note.start < bar_end and note.end > bar_start]
        degree_index = _best_matching_triad(bar_notes, triads)
        root_pc, third_pc, fifth_pc = triads[degree_index]
        notes.extend([
            NoteEvent(pitch=midi_for_pitch_class(root_pc, 4), start=bar_start, duration=BAR_TICKS, velocity=72, channel=1),
            NoteEvent(pitch=midi_for_pitch_class(third_pc, 4), start=bar_start, duration=BAR_TICKS, velocity=68, channel=1),
            NoteEvent(pitch=midi_for_pitch_class(fifth_pc, 4), start=bar_start, duration=BAR_TICKS, velocity=68, channel=1),
        ])
    return notes


def _best_matching_triad(bar_notes: list[NoteEvent], triads: list[tuple[int, int, int]]) -> int:
    if not bar_notes:
        return 0
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
    scores.sort(reverse=True)
    return scores[0][1]


def _generate_topline(key: str, mode: str, chords: list[NoteEvent], bars: int, randomizer: random.Random) -> list[NoteEvent]:
    scale = scale_for(key, mode)
    notes: list[NoteEvent] = []
    for bar in range(bars):
        bar_chord = chords[bar * 3:(bar + 1) * 3]
        chord_tones = [note.pitch % 12 for note in bar_chord]
        rhythm = [0, BAR_TICKS // 4, BAR_TICKS // 2, BAR_TICKS * 3 // 4]
        last_pitch = notes[-1].pitch if notes else midi_for_pitch_class(scale[0], 5)
        for index, offset in enumerate(rhythm):
            pitch_class = chord_tones[index % len(chord_tones)] if index % 2 == 0 else randomizer.choice(scale)
            octave = 5 if pitch_class >= scale[0] else 6
            pitch = clamp_pitch(midi_for_pitch_class(pitch_class, octave), 60, 84)
            if abs(pitch - last_pitch) > 7:
                pitch += -12 if pitch > last_pitch else 12
            pitch = clamp_pitch(pitch, 60, 84)
            notes.append(NoteEvent(pitch=pitch, start=bar * BAR_TICKS + offset, duration=BAR_TICKS // 4, velocity=92, channel=0))
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


def _generate_bassline(chords: list[NoteEvent], text_features: TextFeatures | None) -> list[NoteEvent]:
    bass: list[NoteEvent] = []
    staccato = text_features.genre in {"trap", "house"} if text_features else False
    for bar_index in range(0, len(chords), 3):
        chord_root = chords[bar_index]
        bar = chord_root.start // BAR_TICKS
        root_pitch = clamp_pitch(chord_root.pitch - 24, 28, 52)
        if staccato:
            for step in range(4):
                bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS + step * (BAR_TICKS // 4), duration=BAR_TICKS // 8, velocity=88, channel=2))
        else:
            bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS, duration=BAR_TICKS, velocity=84, channel=2))
    return bass


def _generate_drum_pattern(bars: int, text_features: TextFeatures | None) -> list[NoteEvent]:
    genre = text_features.genre if text_features else "pop"
    notes: list[NoteEvent] = []
    for bar in range(bars):
        bar_start = bar * BAR_TICKS
        quarter = BAR_TICKS // 4
        for step in range(4):
            start = bar_start + step * quarter
            notes.append(NoteEvent(pitch=42, start=start, duration=quarter // 2, velocity=64, channel=9))
        for step in [1, 3]:
            notes.append(NoteEvent(pitch=38, start=bar_start + step * quarter, duration=quarter // 2, velocity=96, channel=9))
        if genre == "house":
            kick_steps = [0, 1, 2, 3]
        elif genre == "trap":
            kick_steps = [0, 2, 2.5]
        else:
            kick_steps = [0, 2]
        for step in kick_steps:
            start = int(bar_start + step * quarter)
            notes.append(NoteEvent(pitch=36, start=start, duration=quarter // 2, velocity=110, channel=9))
        if genre == "trap":
            for step in [0.5, 1.5, 2.5, 3.5]:
                start = int(bar_start + step * quarter)
                notes.append(NoteEvent(pitch=44, start=start, duration=quarter // 4, velocity=54, channel=9))
    return sorted(notes, key=lambda note: (note.start, note.pitch))
