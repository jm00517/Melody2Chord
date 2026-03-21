from __future__ import annotations

from collections import Counter
from pathlib import Path

from .midi import infer_bars_from_notes, parse_midi_notes
from .models import BAR_TICKS, MelodyAnalysis, NoteEvent
from .music_theory import MAJOR_SCALE, MINOR_SCALE, NAME_TO_PC


def analyze_melody_file(path: Path) -> MelodyAnalysis:
    tracks, tempo_bpm = parse_midi_notes(path)
    melodic_track = max(tracks, key=lambda track: len(track.notes), default=None)
    if melodic_track is None or not melodic_track.notes:
        raise ValueError(f"No note data found in MIDI file: {path}")

    original_notes = melodic_track.notes
    start_offset = min(note.start for note in original_notes)
    notes = _align_notes_to_start(original_notes, start_offset)
    key, mode = infer_key(notes)
    bars = infer_bars_from_notes(notes)
    phrase_length = max(1, min(8, _detect_phrase_length(notes, bars)))
    return MelodyAnalysis(
        notes=notes,
        source_path=path,
        key=key,
        mode=mode,
        tempo_bpm=tempo_bpm,
        bars=bars,
        phrase_length=phrase_length,
        source_start_offset_ticks=start_offset,
    )


def infer_key(notes: list[NoteEvent]) -> tuple[str, str]:
    pitch_classes = Counter(note.pitch % 12 for note in notes)
    best_score = -1
    best_key = ("C", "major")
    for root_name, root_pc in NAME_TO_PC.items():
        major_score = _score_scale(root_pc, MAJOR_SCALE, pitch_classes)
        if major_score > best_score:
            best_score = major_score
            best_key = (root_name, "major")
        minor_score = _score_scale(root_pc, MINOR_SCALE, pitch_classes)
        if minor_score > best_score:
            best_score = minor_score
            best_key = (root_name, "minor")
    return best_key


def _align_notes_to_start(notes: list[NoteEvent], start_offset: int) -> list[NoteEvent]:
    if start_offset <= 0:
        return list(notes)
    return [
        NoteEvent(
            pitch=note.pitch,
            start=max(0, note.start - start_offset),
            duration=note.duration,
            velocity=note.velocity,
            channel=note.channel,
        )
        for note in notes
    ]


def _score_scale(root: int, intervals: list[int], counts: Counter[int]) -> int:
    scale = {(root + interval) % 12 for interval in intervals}
    score = 0
    for pitch_class, count in counts.items():
        score += count * 3 if pitch_class in scale else -count * 2
    return score


def _detect_phrase_length(notes: list[NoteEvent], bars: int) -> int:
    onset_counts = Counter(note.start // BAR_TICKS for note in notes)
    if bars <= 4:
        return bars
    first_half = sum(onset_counts[index] for index in range(min(4, bars)))
    second_half = sum(onset_counts[index] for index in range(4, min(8, bars)))
    if second_half and abs(first_half - second_half) <= max(1, first_half // 2):
        return 4
    return min(8, bars)
