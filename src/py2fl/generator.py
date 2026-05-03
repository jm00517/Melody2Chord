from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import random
import re

from .arrangement import build_arrangement, build_arrangement_from_progression
from .melody import analyze_melody_file
from .midi import parse_midi_notes, write_meta, write_midi
from .models import Arrangement, BAR_TICKS, GenerationRequest, GenerationResult, NoteEvent, PPQ, TrackData
from .music_theory import PITCH_CLASS_NAMES, key_label, scale_for
from .progression import ParsedProgression, parse_progression, progression_display
from .text_analysis import analyze_text

BATCH_META_FILENAME = "batch_meta.json"


def generate_song(request: GenerationRequest) -> GenerationResult:
    context = _prepare_context(request)
    arrangement, parsed_progression = _build_for_request(request, context)
    run_dir = _build_output_dir(request.output_dir, request.text, request.melody_midi_path, request.chord_progression)
    return _write_arrangement(
        run_dir,
        arrangement,
        request,
        melody_analysis=context["melody_analysis"],
        parsed_progression=parsed_progression,
        candidate_index=1,
        candidate_seed=request.seed,
        reroll_scope="all",
    )


def generate_candidates(request: GenerationRequest, count: int = 4, reroll_scope: str = "all", seed_offset: int = 0) -> list[GenerationResult]:
    if count < 1:
        raise ValueError("count must be at least 1")
    allowed_scopes = {"all", "chords", "melody"}
    if reroll_scope not in allowed_scopes:
        raise ValueError("reroll_scope must be 'all', 'chords', or 'melody'")

    context = _prepare_context(request)
    batch_dir = _build_output_dir(request.output_dir, request.text, request.melody_midi_path, request.chord_progression)
    batch_dir.mkdir(parents=True, exist_ok=True)

    if request.seed is not None:
        base_seed = request.seed + seed_offset
    else:
        base_seed = random.SystemRandom().randrange(1, 1_000_000_000) + seed_offset

    base_arrangement = None
    parsed_progression = context["parsed_progression"]
    if reroll_scope in {"chords", "melody"}:
        base_arrangement, _ = _build_for_request(
            GenerationRequest(
                text=request.text,
                melody_midi_path=request.melody_midi_path,
                chord_progression=request.chord_progression,
                tempo=request.tempo,
                key=request.key,
                genre=request.genre,
                bars=request.bars,
                chord_density=request.chord_density,
                melody_density=request.melody_density,
                chord_rhythm_style=request.chord_rhythm_style,
                humanize=request.humanize,
                swing=request.swing,
                seed=base_seed,
                output_dir=request.output_dir,
            ),
            context,
        )

    results: list[GenerationResult] = []
    seen_signatures: set[tuple[tuple[object, ...], str]] = set()
    for index in range(count):
        candidate_seed = base_seed + index * 101 + (5000 if reroll_scope != "all" else 0)
        arrangement = None
        final_seed = candidate_seed
        for attempt in range(12):
            attempt_seed = candidate_seed + attempt * 997
            candidate_request = GenerationRequest(
                text=request.text,
                melody_midi_path=request.melody_midi_path,
                chord_progression=request.chord_progression,
                tempo=request.tempo,
                key=request.key,
                genre=request.genre,
                bars=request.bars,
                chord_density=request.chord_density,
                melody_density=request.melody_density,
                chord_rhythm_style=request.chord_rhythm_style,
                humanize=request.humanize,
                swing=request.swing,
                seed=attempt_seed,
                output_dir=request.output_dir,
            )
            candidate_arrangement, parsed_progression = _build_for_request(candidate_request, context)
            signature = _candidate_signature(candidate_arrangement, context["parsed_progression"])
            if signature not in seen_signatures or attempt == 11:
                arrangement = candidate_arrangement
                final_seed = attempt_seed
                seen_signatures.add(signature)
                break
        if arrangement is None:
            raise RuntimeError("Failed to build candidate arrangement")
        if base_arrangement is not None:
            if reroll_scope == "chords":
                arrangement = Arrangement(
                    melody=base_arrangement.melody,
                    chords=arrangement.chords,
                    bass=arrangement.bass,
                    drums=base_arrangement.drums,
                    tempo_bpm=base_arrangement.tempo_bpm,
                    key=arrangement.key,
                    mode=arrangement.mode,
                    bars=base_arrangement.bars,
                    style_tags=base_arrangement.style_tags,
                    progression_label=arrangement.progression_label,
                    progression_degrees=arrangement.progression_degrees,
                    drum_pattern=base_arrangement.drum_pattern,
                    bass_pattern=arrangement.bass_pattern,
                    chord_density=arrangement.chord_density,
                    melody_density=base_arrangement.melody_density,
                    chord_rhythm_style=arrangement.chord_rhythm_style,
                    humanize=arrangement.humanize,
                    swing=arrangement.swing,
                )
            elif reroll_scope == "melody":
                arrangement = Arrangement(
                    melody=arrangement.melody,
                    chords=base_arrangement.chords,
                    bass=base_arrangement.bass,
                    drums=base_arrangement.drums,
                    tempo_bpm=base_arrangement.tempo_bpm,
                    key=base_arrangement.key,
                    mode=base_arrangement.mode,
                    bars=base_arrangement.bars,
                    style_tags=base_arrangement.style_tags,
                    progression_label=base_arrangement.progression_label,
                    progression_degrees=base_arrangement.progression_degrees,
                    drum_pattern=base_arrangement.drum_pattern,
                    bass_pattern=base_arrangement.bass_pattern,
                    chord_density=base_arrangement.chord_density,
                    melody_density=arrangement.melody_density,
                    chord_rhythm_style=base_arrangement.chord_rhythm_style,
                    humanize=arrangement.humanize,
                    swing=arrangement.swing,
                )
        candidate_dir = batch_dir / f"option_{index + 1:02d}"
        result = _write_arrangement(
            candidate_dir,
            arrangement,
            request,
            melody_analysis=context["melody_analysis"],
            parsed_progression=context["parsed_progression"],
            candidate_index=index + 1,
            candidate_seed=final_seed,
            reroll_scope=reroll_scope,
        )
        result.metadata["batch_dir"] = str(batch_dir)
        result.metadata["option_name"] = candidate_dir.name
        results.append(result)

    write_batch_meta(batch_dir, request, results, selected_option=None)
    return results


def write_batch_meta(batch_dir: Path, request: GenerationRequest, results: list[GenerationResult], selected_option: int | None) -> Path:
    batch_dir = Path(batch_dir)
    selected_candidate = None
    if selected_option is not None:
        for result in results:
            if result.metadata.get("candidate_index") == selected_option:
                selected_candidate = result
                break

    payload = {
        "text": request.text,
        "genre": request.genre,
        "source_melody": str(request.melody_midi_path) if request.melody_midi_path else None,
        "source_progression": request.chord_progression,
        "tempo": request.tempo,
        "key": request.key,
        "bars": request.bars,
        "chord_density": request.chord_density,
        "melody_density": request.melody_density,
        "chord_rhythm_style": request.chord_rhythm_style,
        "humanize": request.humanize,
        "swing": request.swing,
        "seed": request.seed,
        "candidate_count": len(results),
        "selected_option": selected_option,
        "selected_output_dir": None if selected_candidate is None else str(selected_candidate.output_dir),
        "generator_mode": results[0].metadata.get("ui_mode") if results else "arrangement",
        "candidates": [
            {
                "candidate_index": result.metadata.get("candidate_index"),
                "option_name": result.metadata.get("option_name") or Path(result.output_dir).name,
                "output_dir": str(result.output_dir),
                "progression_label": result.metadata.get("progression_label"),
                "full_progression_text": result.metadata.get("full_progression_text"),
                "candidate_seed": result.metadata.get("candidate_seed"),
                "tempo": result.metadata.get("tempo"),
                "key": result.metadata.get("key"),
                "drum_pattern": result.metadata.get("drum_pattern"),
                "bass_pattern": result.metadata.get("bass_pattern"),
                "style_tags": result.metadata.get("style_tags"),
                "resolved_chord_density": result.metadata.get("resolved_chord_density"),
                "resolved_melody_density": result.metadata.get("resolved_melody_density"),
                "resolved_chord_rhythm_style": result.metadata.get("resolved_chord_rhythm_style"),
                "resolved_humanize": result.metadata.get("resolved_humanize"),
                "resolved_swing": result.metadata.get("resolved_swing"),
                "preview_file": "full_arrangement.mid",
                "bars": result.metadata.get("bars"),
            }
            for result in results
        ],
    }
    meta_path = batch_dir / BATCH_META_FILENAME
    write_meta(meta_path, payload)
    return meta_path


def load_batch_meta(batch_dir: Path) -> dict[str, object]:
    meta_path = Path(batch_dir) / BATCH_META_FILENAME
    if not meta_path.exists():
        raise FileNotFoundError(f"Batch metadata not found: {meta_path}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def reroll_candidate_bar(batch_dir: Path, candidate_index: int, bar_index: int, reroll_nonce: int = 0, chord_density_override: str | None = None) -> dict[str, object]:
    batch_dir = Path(batch_dir)
    batch_meta = load_batch_meta(batch_dir)
    candidates = batch_meta.get("candidates", [])
    selected = None
    for candidate in candidates:
        if candidate.get("candidate_index") == candidate_index:
            selected = candidate
            break
    if selected is None:
        raise ValueError(f"Candidate {candidate_index} not found in batch")

    output_dir = Path(str(selected.get("output_dir")))
    meta_path = output_dir / "meta.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    bars = int(metadata.get("bars") or selected.get("bars") or 0)
    if bar_index < 1 or bar_index > bars:
        raise ValueError("bar_index is out of range")

    if metadata.get("input_mode") in {"chords", "text+chords"}:
        batch_meta = _reroll_melody_bar(batch_dir, selected, metadata, bar_index, reroll_nonce)
    else:
        batch_meta = _reroll_harmony_bar(batch_dir, selected, metadata, bar_index, reroll_nonce, chord_density_override=chord_density_override)
    return batch_meta


def select_candidate(batch_dir: Path, candidate_index: int) -> dict[str, object]:
    batch_dir = Path(batch_dir)
    meta = load_batch_meta(batch_dir)
    candidates = meta.get("candidates", [])
    selected = None
    for candidate in candidates:
        if candidate.get("candidate_index") == candidate_index:
            selected = candidate
            break
    if selected is None:
        raise ValueError(f"Candidate {candidate_index} not found in batch")
    meta["selected_option"] = candidate_index
    meta["selected_output_dir"] = selected.get("output_dir")
    write_meta(batch_dir / BATCH_META_FILENAME, meta)
    return meta


def _prepare_context(request: GenerationRequest) -> dict[str, object]:
    if not request.text and not request.melody_midi_path and not request.chord_progression:
        raise ValueError("At least one input is required: text, melody_midi_path, or chord_progression")
    text_features = analyze_text(request.text, request.genre)
    parsed_progression = None
    if request.chord_progression:
        parsed_progression = parse_progression(
            request.chord_progression,
            key_hint=request.key,
            bars=request.bars,
            genre_hint=request.genre,
            style_text=request.text,
        )
    return {
        "text_features": text_features,
        "melody_analysis": analyze_melody_file(request.melody_midi_path) if request.melody_midi_path else None,
        "parsed_progression": parsed_progression,
    }


def _build_for_request(request: GenerationRequest, context: dict[str, object]) -> tuple[Arrangement, ParsedProgression | None]:
    parsed_progression = context["parsed_progression"]
    if parsed_progression is not None:
        arrangement = build_arrangement_from_progression(
            progression=parsed_progression,
            text_features=context["text_features"],
            tempo=request.tempo,
            chord_density=request.chord_density,
            melody_density=request.melody_density,
            chord_rhythm_style=request.chord_rhythm_style,
            humanize=request.humanize,
            swing=request.swing,
            seed=request.seed,
        )
        return arrangement, parsed_progression
    arrangement = build_arrangement(
        text_features=context["text_features"],
        melody_analysis=context["melody_analysis"],
        tempo=request.tempo,
        key=request.key,
        bars=request.bars,
        chord_density=request.chord_density,
        melody_density=request.melody_density,
        chord_rhythm_style=request.chord_rhythm_style,
        humanize=request.humanize,
        swing=request.swing,
        seed=request.seed,
    )
    return arrangement, None


def _write_arrangement(
    run_dir: Path,
    arrangement: Arrangement,
    request: GenerationRequest,
    *,
    melody_analysis,
    parsed_progression: ParsedProgression | None,
    candidate_index: int | None,
    candidate_seed: int | None,
    reroll_scope: str,
) -> GenerationResult:
    run_dir.mkdir(parents=True, exist_ok=True)
    bar_summary = _build_bar_summary(arrangement)
    full_progression_text = progression_display(parsed_progression.chord_bars) if parsed_progression else (" -> ".join(bar["chord_name"] for bar in bar_summary) if bar_summary else arrangement.progression_label)

    track_map = {
        "melody.mid": TrackData(name="Melody", notes=arrangement.melody, channel=0),
        "chords.mid": TrackData(name="Chords", notes=arrangement.chords, channel=1),
        "bass.mid": TrackData(name="Bass", notes=arrangement.bass, channel=2),
        "drums.mid": TrackData(name="Drums", notes=arrangement.drums, channel=9),
    }

    files: list[Path] = []
    for filename, track in track_map.items():
        file_path = run_dir / filename
        write_midi(file_path, [track], arrangement.tempo_bpm)
        files.append(file_path)

    full_arrangement = run_dir / "full_arrangement.mid"
    write_midi(full_arrangement, list(track_map.values()), arrangement.tempo_bpm)
    files.append(full_arrangement)

    mode = _input_mode(request)
    metadata = {
        "input_mode": mode,
        "ui_mode": "melody_from_chords" if parsed_progression else "arrangement",
        "tempo": arrangement.tempo_bpm,
        "key": key_label(arrangement.key, arrangement.mode),
        "bars": arrangement.bars,
        "style_tags": arrangement.style_tags,
        "source_melody": str(request.melody_midi_path) if request.melody_midi_path else None,
        "source_progression": request.chord_progression,
        "progression_notation": None if parsed_progression is None else parsed_progression.notation,
        "source_start_offset_ticks": None if melody_analysis is None else melody_analysis.source_start_offset_ticks,
        "melody_aligned_to_start": melody_analysis is not None,
        "text": request.text,
        "genre": request.genre,
        "requested_chord_density": request.chord_density or "auto",
        "requested_melody_density": request.melody_density or "auto",
        "requested_chord_rhythm_style": request.chord_rhythm_style or "auto",
        "requested_humanize": request.humanize or "off",
        "requested_swing": request.swing or "off",
        "resolved_chord_density": arrangement.chord_density,
        "resolved_melody_density": arrangement.melody_density,
        "resolved_chord_rhythm_style": arrangement.chord_rhythm_style,
        "resolved_humanize": arrangement.humanize,
        "resolved_swing": arrangement.swing,
        "files": [file.name for file in files],
        "progression_label": arrangement.progression_label,
        "progression_degrees": arrangement.progression_degrees,
        "full_progression_text": full_progression_text,
        "bar_summary": bar_summary,
        "recently_updated_bar": None,
        "drum_pattern": arrangement.drum_pattern,
        "bass_pattern": arrangement.bass_pattern,
        "candidate_index": candidate_index,
        "candidate_seed": candidate_seed,
        "reroll_scope": reroll_scope,
        "preview_file": "full_arrangement.mid",
        "timeline_title": "Melody Timeline" if parsed_progression else "Harmony Timeline",
        "timeline_description": "Each bar shows the fixed chord, melody focus notes, and how strongly the topline lands inside the chord tones." if parsed_progression else "Each bar shows the chosen chord, representative melody tones, and how much of the melody sits inside the chord tones.",
        "bar_action_label": "Reroll Melody" if parsed_progression else "Reroll Harmony",
    }
    meta_path = run_dir / "meta.json"
    write_meta(meta_path, metadata)
    files.append(meta_path)
    return GenerationResult(output_dir=run_dir, files=files, metadata=metadata)


def _build_output_dir(base_dir: Path, text: str | None, melody_path: Path | None, chord_progression: str | None) -> Path:
    base_dir = Path(base_dir)
    base_name = None
    if text:
        base_name = _slugify(text[:40])
    elif melody_path:
        base_name = _slugify(melody_path.stem)
    elif chord_progression:
        base_name = _slugify(chord_progression[:40])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir / f"{timestamp}_{base_name or 'arrangement'}"


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    return cleaned.strip("_") or "arrangement"


def _input_mode(request: GenerationRequest) -> str:
    if request.chord_progression and request.text:
        return "text+chords"
    if request.chord_progression:
        return "chords"
    if request.text and request.melody_midi_path:
        return "text+melody"
    if request.melody_midi_path:
        return "melody"
    return "text"


def _candidate_signature(arrangement: Arrangement, parsed_progression: ParsedProgression | None) -> tuple[tuple[object, ...], str]:
    if parsed_progression is not None:
        melody_signature = tuple((note.pitch, note.start, note.duration) for note in arrangement.melody[:16])
        return melody_signature, arrangement.progression_label
    return tuple(arrangement.progression_degrees), arrangement.progression_label


def _build_bar_summary(arrangement: Arrangement) -> list[dict[str, object]]:
    summary: list[dict[str, object]] = []
    for bar_index in range(arrangement.bars):
        bar_start = bar_index * BAR_TICKS
        bar_end = bar_start + BAR_TICKS
        chord_notes = _notes_for_span(arrangement.chords, bar_start, bar_end)
        melody_notes = _notes_for_span(arrangement.melody, bar_start, bar_end)
        chord_events = _chord_events_for_span(chord_notes, bar_start, bar_end, arrangement.key, arrangement.mode)
        event_names = _unique_event_names(chord_events)
        event_degrees = _unique_event_degrees(chord_events)
        chord_name = ' / '.join(event_names) if len(event_names) > 1 else (event_names[0] if event_names else 'No chord')
        chord_tones = _sorted_pitch_class_names(chord_notes)
        representative = _representative_melody_pitches(melody_notes)
        match_ratio = _match_ratio(melody_notes, chord_notes)
        summary.append(
            {
                'bar_index': bar_index + 1,
                'start_tick': bar_start,
                'end_tick': bar_end,
                'degree': arrangement.progression_degrees[bar_index] if bar_index < len(arrangement.progression_degrees) else None,
                'degrees': event_degrees,
                'degree_label': ' / '.join(str(value) for value in event_degrees) if event_degrees else (str(arrangement.progression_degrees[bar_index]) if bar_index < len(arrangement.progression_degrees) and arrangement.progression_degrees[bar_index] else '-'),
                'chord_name': chord_name,
                'chord_tones': chord_tones,
                'representative_melody_pitches': representative,
                'matching_ratio': match_ratio,
                'matching_percent': round(match_ratio * 100),
                'chord_event_count': len(chord_events),
                'chord_events': chord_events,
            }
        )
    return summary


def _notes_for_span(notes: list[NoteEvent], start_tick: int, end_tick: int) -> list[NoteEvent]:
    return [note for note in notes if note.start < end_tick and note.end > start_tick]


def _chord_events_for_span(notes: list[NoteEvent], start_tick: int, end_tick: int, key: str, mode: str) -> list[dict[str, object]]:
    sorted_notes = sorted(notes, key=lambda note: (note.start, note.pitch))
    if not sorted_notes:
        return []
    events: list[dict[str, object]] = []
    cluster: list[NoteEvent] = []
    cluster_start = 0
    cluster_end = 0
    merge_window = PPQ // 8

    def flush_cluster(active_cluster: list[NoteEvent], active_start: int, active_end: int) -> None:
        if not active_cluster:
            return
        events.append({
            'start_tick': active_start,
            'end_tick': min(active_end, end_tick),
            'degree': _degree_for_notes(active_cluster, key, mode),
            'chord_name': _detect_chord_name(active_cluster),
            'chord_tones': _sorted_pitch_class_names(active_cluster),
        })

    for note in sorted_notes:
        if not cluster:
            cluster = [note]
            cluster_start = note.start
            cluster_end = note.end
            continue
        same_event = note.start <= cluster_start + merge_window or note.start < cluster_end
        if same_event:
            cluster.append(note)
            cluster_end = max(cluster_end, note.end)
            continue
        flush_cluster(cluster, cluster_start, cluster_end)
        cluster = [note]
        cluster_start = note.start
        cluster_end = note.end

    flush_cluster(cluster, cluster_start, cluster_end)
    return events


def _unique_event_names(chord_events: list[dict[str, object]]) -> list[str]:
    unique: list[str] = []
    for event in chord_events:
        name = str(event.get('chord_name') or 'No chord')
        if not unique or unique[-1] != name:
            unique.append(name)
    return unique


def _unique_event_degrees(chord_events: list[dict[str, object]]) -> list[int]:
    unique: list[int] = []
    for event in chord_events:
        degree = event.get('degree')
        if isinstance(degree, int) and (not unique or unique[-1] != degree):
            unique.append(degree)
    return unique


def _degree_for_notes(notes: list[NoteEvent], key: str, mode: str) -> int | None:
    if not notes:
        return None
    scale = scale_for(key, mode)
    root_pc = min(notes, key=lambda note: note.pitch).pitch % 12
    if root_pc not in scale:
        return None
    return scale.index(root_pc) + 1


def _unique_event_names(chord_events: list[dict[str, object]]) -> list[str]:
    unique: list[str] = []
    for event in chord_events:
        name = str(event.get('chord_name') or 'No chord')
        if not unique or unique[-1] != name:
            unique.append(name)
    return unique


def _detect_chord_name(notes: list[NoteEvent]) -> str:
    if not notes:
        return "No chord"
    root_pc = min(notes, key=lambda note: note.pitch).pitch % 12
    pitch_classes = {note.pitch % 12 for note in notes}
    intervals = {((pitch_class - root_pc) % 12) for pitch_class in pitch_classes}
    root = PITCH_CLASS_NAMES[root_pc]
    if intervals == {0, 2, 7}:
        return f"{root}sus2"
    if intervals == {0, 5, 7}:
        return f"{root}sus4"
    third = 4 if 4 in intervals else 3 if 3 in intervals else None
    fifth = 7 in intervals
    seventh = 11 if 11 in intervals else 10 if 10 in intervals else None
    add9 = 2 in intervals
    if third is None or not fifth:
        return root
    quality = "" if third == 4 else "m"
    if add9 and seventh is None:
        return f"{root}{quality}add9"
    if seventh == 11:
        return f"{root}{quality}maj7"
    if seventh == 10:
        return f"{root}{quality}7"
    return f"{root}{quality}"


def _sorted_pitch_class_names(notes: list[NoteEvent]) -> list[str]:
    pitch_classes = sorted({note.pitch % 12 for note in notes})
    return [PITCH_CLASS_NAMES[pitch_class] for pitch_class in pitch_classes]


def _representative_melody_pitches(notes: list[NoteEvent]) -> list[str]:
    ranked = sorted(notes, key=lambda note: (-note.duration, note.start, note.pitch))
    unique: list[str] = []
    for note in ranked:
        name = PITCH_CLASS_NAMES[note.pitch % 12]
        if name not in unique:
            unique.append(name)
        if len(unique) == 3:
            break
    return unique


def _match_ratio(melody_notes: list[NoteEvent], chord_notes: list[NoteEvent]) -> float:
    if not melody_notes or not chord_notes:
        return 0.0
    chord_tones = {note.pitch % 12 for note in chord_notes}
    total = sum(max(1, note.duration) for note in melody_notes)
    matches = sum(max(1, note.duration) for note in melody_notes if note.pitch % 12 in chord_tones)
    return round(matches / total, 3) if total else 0.0


def _read_existing_arrangement(output_dir: Path, metadata: dict[str, object]) -> Arrangement:
    melody_tracks, tempo = parse_midi_notes(output_dir / "melody.mid")
    chord_tracks, _ = parse_midi_notes(output_dir / "chords.mid")
    bass_tracks, _ = parse_midi_notes(output_dir / "bass.mid")
    drum_tracks, _ = parse_midi_notes(output_dir / "drums.mid")
    key_name, mode = _split_key_label(str(metadata.get("key") or "C major"))
    return Arrangement(
        melody=_first_notes(melody_tracks),
        chords=_first_notes(chord_tracks),
        bass=_first_notes(bass_tracks),
        drums=_first_notes(drum_tracks),
        tempo_bpm=tempo or int(metadata.get("tempo") or 110),
        key=key_name,
        mode=mode,
        bars=int(metadata.get("bars") or 4),
        style_tags=list(metadata.get("style_tags") or []),
        progression_label=str(metadata.get("progression_label") or ""),
        progression_degrees=list(metadata.get("progression_degrees") or []),
        drum_pattern=str(metadata.get("drum_pattern") or ""),
        bass_pattern=str(metadata.get("bass_pattern") or ""),
        chord_density=int(metadata.get("resolved_chord_density") or 1),
        melody_density=str(metadata.get("resolved_melody_density") or "normal"),
        chord_rhythm_style=str(metadata.get("resolved_chord_rhythm_style") or "hold"),
        humanize=str(metadata.get("resolved_humanize") or "off"),
        swing=str(metadata.get("resolved_swing") or "off"),
    )


def _first_notes(tracks: list[TrackData]) -> list[NoteEvent]:
    for track in tracks:
        if track.notes:
            return track.notes
    return []


def _optional_int_value(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _split_key_label(label: str) -> tuple[str, str]:
    cleaned = (label or "C major").strip()
    if cleaned.lower().endswith(" minor"):
        return cleaned[:-6].strip(), "minor"
    if cleaned.lower().endswith(" major"):
        return cleaned[:-6].strip(), "major"
    return cleaned or "C", "major"


def _key_name_from_label(label: str | None) -> str | None:
    if not label:
        return None
    return _split_key_label(label)[0]


def _reroll_harmony_bar(batch_dir: Path, selected: dict[str, object], metadata: dict[str, object], bar_index: int, reroll_nonce: int, chord_density_override: str | None = None) -> dict[str, object]:
    request = GenerationRequest(
        text=_optional_string(load_batch_meta(batch_dir).get("text")),
        melody_midi_path=Path(str(load_batch_meta(batch_dir).get("source_melody"))) if load_batch_meta(batch_dir).get("source_melody") else None,
        tempo=_optional_int_value(load_batch_meta(batch_dir).get("tempo")) or _optional_int_value(metadata.get("tempo")),
        key=_key_name_from_label(_optional_string(metadata.get("key"))),
        genre=_optional_string(load_batch_meta(batch_dir).get("genre")),
        bars=int(metadata.get("bars") or 4),
        chord_density=chord_density_override or _optional_string(load_batch_meta(batch_dir).get("chord_density")) or _optional_string(metadata.get("requested_chord_density")),
        melody_density=_optional_string(load_batch_meta(batch_dir).get("melody_density")) or _optional_string(metadata.get("requested_melody_density")),
        chord_rhythm_style=_optional_string(load_batch_meta(batch_dir).get("chord_rhythm_style")) or _optional_string(metadata.get("requested_chord_rhythm_style")),
        humanize=_optional_string(load_batch_meta(batch_dir).get("humanize")) or _optional_string(metadata.get("requested_humanize")),
        swing=_optional_string(load_batch_meta(batch_dir).get("swing")) or _optional_string(metadata.get("requested_swing")),
        seed=_optional_int_value(metadata.get("candidate_seed")),
        output_dir=batch_dir,
    )
    context = _prepare_context(request)
    current = _read_existing_arrangement(Path(str(selected.get("output_dir"))), metadata)
    base_seed = int(metadata.get("candidate_seed") or 0) + reroll_nonce + bar_index * 1009
    start_tick = (bar_index - 1) * BAR_TICKS
    end_tick = start_tick + BAR_TICKS
    replacement = None
    for attempt in range(10):
        candidate_request = GenerationRequest(
            text=request.text,
            melody_midi_path=request.melody_midi_path,
            chord_progression=request.chord_progression,
            tempo=request.tempo,
            key=request.key,
            genre=request.genre,
            bars=request.bars,
            chord_density=request.chord_density,
            melody_density=request.melody_density,
            chord_rhythm_style=request.chord_rhythm_style,
            humanize=request.humanize,
            swing=request.swing,
            seed=base_seed + attempt * 313,
            output_dir=request.output_dir,
        )
        candidate_arrangement, _ = _build_for_request(candidate_request, context)
        new_chords = _notes_for_span(candidate_arrangement.chords, start_tick, end_tick)
        old_chords = _notes_for_span(current.chords, start_tick, end_tick)
        new_bass = _notes_for_span(candidate_arrangement.bass, start_tick, end_tick)
        old_bass = _notes_for_span(current.bass, start_tick, end_tick)
        if _note_signature(new_chords) != _note_signature(old_chords) or _note_signature(new_bass) != _note_signature(old_bass) or attempt == 9:
            replacement = candidate_arrangement
            break
    if replacement is None:
        raise RuntimeError("Failed to reroll bar")
    updated = Arrangement(
        melody=current.melody,
        chords=_replace_bar_notes(current.chords, replacement.chords, start_tick, end_tick),
        bass=_replace_bar_notes(current.bass, replacement.bass, start_tick, end_tick),
        drums=current.drums,
        tempo_bpm=current.tempo_bpm,
        key=current.key,
        mode=current.mode,
        bars=current.bars,
        style_tags=current.style_tags,
        progression_label=str(metadata.get("progression_label") or current.progression_label),
        progression_degrees=_replace_progression_degree(list(metadata.get("progression_degrees") or current.progression_degrees), replacement.progression_degrees, bar_index),
        drum_pattern=current.drum_pattern,
        bass_pattern=str(metadata.get("bass_pattern") or current.bass_pattern),
        chord_density=current.chord_density,
        melody_density=current.melody_density,
        chord_rhythm_style=current.chord_rhythm_style,
        humanize=current.humanize,
        swing=current.swing,
    )
    result = _write_arrangement(
        Path(str(selected.get("output_dir"))),
        updated,
        request,
        melody_analysis=context["melody_analysis"],
        parsed_progression=None,
        candidate_index=int(metadata.get("candidate_index") or selected.get("candidate_index") or 1),
        candidate_seed=base_seed,
        reroll_scope="bar_harmony",
    )
    return _finalize_bar_reroll(batch_dir, selected, result, bar_index)


def _reroll_melody_bar(batch_dir: Path, selected: dict[str, object], metadata: dict[str, object], bar_index: int, reroll_nonce: int) -> dict[str, object]:
    batch_meta = load_batch_meta(batch_dir)
    request = GenerationRequest(
        text=_optional_string(batch_meta.get("text")),
        chord_progression=_optional_string(batch_meta.get("source_progression")),
        tempo=_optional_int_value(batch_meta.get("tempo")) or _optional_int_value(metadata.get("tempo")),
        key=_key_name_from_label(_optional_string(metadata.get("key"))),
        genre=_optional_string(batch_meta.get("genre")),
        bars=int(metadata.get("bars") or 4),
        chord_density=_optional_string(batch_meta.get("chord_density")) or _optional_string(metadata.get("requested_chord_density")),
        melody_density=_optional_string(batch_meta.get("melody_density")) or _optional_string(metadata.get("requested_melody_density")),
        chord_rhythm_style=_optional_string(batch_meta.get("chord_rhythm_style")) or _optional_string(metadata.get("requested_chord_rhythm_style")),
        humanize=_optional_string(batch_meta.get("humanize")) or _optional_string(metadata.get("requested_humanize")),
        swing=_optional_string(batch_meta.get("swing")) or _optional_string(metadata.get("requested_swing")),
        seed=_optional_int_value(metadata.get("candidate_seed")),
        output_dir=batch_dir,
    )
    context = _prepare_context(request)
    current = _read_existing_arrangement(Path(str(selected.get("output_dir"))), metadata)
    base_seed = int(metadata.get("candidate_seed") or 0) + reroll_nonce + bar_index * 1009
    start_tick = (bar_index - 1) * BAR_TICKS
    end_tick = start_tick + BAR_TICKS
    replacement = None
    for attempt in range(10):
        candidate_request = GenerationRequest(
            text=request.text,
            melody_midi_path=request.melody_midi_path,
            chord_progression=request.chord_progression,
            tempo=request.tempo,
            key=request.key,
            genre=request.genre,
            bars=request.bars,
            chord_density=request.chord_density,
            melody_density=request.melody_density,
            chord_rhythm_style=request.chord_rhythm_style,
            humanize=request.humanize,
            swing=request.swing,
            seed=base_seed + attempt * 313,
            output_dir=request.output_dir,
        )
        candidate_arrangement, parsed_progression = _build_for_request(candidate_request, context)
        new_melody = _notes_for_span(candidate_arrangement.melody, start_tick, end_tick)
        old_melody = _notes_for_span(current.melody, start_tick, end_tick)
        if _note_signature(new_melody) != _note_signature(old_melody) or attempt == 9:
            replacement = candidate_arrangement
            break
    if replacement is None:
        raise RuntimeError("Failed to reroll melody bar")
    updated = Arrangement(
        melody=_replace_bar_notes(current.melody, replacement.melody, start_tick, end_tick),
        chords=current.chords,
        bass=current.bass,
        drums=current.drums,
        tempo_bpm=current.tempo_bpm,
        key=current.key,
        mode=current.mode,
        bars=current.bars,
        style_tags=current.style_tags,
        progression_label=str(metadata.get("progression_label") or current.progression_label),
        progression_degrees=list(metadata.get("progression_degrees") or current.progression_degrees),
        drum_pattern=current.drum_pattern,
        bass_pattern=current.bass_pattern,
        chord_density=current.chord_density,
        melody_density=current.melody_density,
        chord_rhythm_style=current.chord_rhythm_style,
        humanize=current.humanize,
        swing=current.swing,
    )
    result = _write_arrangement(
        Path(str(selected.get("output_dir"))),
        updated,
        request,
        melody_analysis=None,
        parsed_progression=context["parsed_progression"],
        candidate_index=int(metadata.get("candidate_index") or selected.get("candidate_index") or 1),
        candidate_seed=base_seed,
        reroll_scope="bar_melody",
    )
    return _finalize_bar_reroll(batch_dir, selected, result, bar_index)


def _finalize_bar_reroll(batch_dir: Path, selected: dict[str, object], result: GenerationResult, bar_index: int) -> dict[str, object]:
    result.metadata["recently_updated_bar"] = bar_index
    for bar in result.metadata.get("bar_summary", []):
        bar["recently_updated"] = int(bar.get("bar_index") or 0) == bar_index
    write_meta(Path(result.output_dir) / "meta.json", result.metadata)
    result.metadata["batch_dir"] = str(batch_dir)
    result.metadata["option_name"] = selected.get("option_name") or Path(result.output_dir).name
    batch_meta = load_batch_meta(batch_dir)
    _refresh_batch_candidate(batch_meta, result)
    write_meta(batch_dir / BATCH_META_FILENAME, batch_meta)
    return batch_meta


def _replace_bar_notes(current_notes: list[NoteEvent], replacement_notes: list[NoteEvent], start_tick: int, end_tick: int) -> list[NoteEvent]:
    kept = [note for note in current_notes if note.end <= start_tick or note.start >= end_tick]
    inserted = [note for note in replacement_notes if note.start < end_tick and note.end > start_tick]
    return sorted(kept + inserted, key=lambda note: (note.start, note.pitch))


def _replace_progression_degree(current: list[object], replacement: list[object], bar_index: int) -> list[object]:
    if len(current) < bar_index:
        current.extend([None] * (bar_index - len(current)))
    if replacement and len(replacement) >= bar_index:
        current[bar_index - 1] = replacement[bar_index - 1]
    return current


def _note_signature(notes: list[NoteEvent]) -> tuple[tuple[int, int, int], ...]:
    return tuple((note.pitch, note.start, note.duration) for note in notes)


def _refresh_batch_candidate(batch_meta: dict[str, object], result: GenerationResult) -> None:
    for candidate in batch_meta.get("candidates", []):
        if candidate.get("candidate_index") == result.metadata.get("candidate_index"):
            candidate["candidate_seed"] = result.metadata.get("candidate_seed")
            candidate["progression_label"] = result.metadata.get("progression_label")
            candidate["full_progression_text"] = result.metadata.get("full_progression_text")
            candidate["tempo"] = result.metadata.get("tempo")
            candidate["key"] = result.metadata.get("key")
            candidate["drum_pattern"] = result.metadata.get("drum_pattern")
            candidate["bass_pattern"] = result.metadata.get("bass_pattern")
            candidate["style_tags"] = result.metadata.get("style_tags")
            candidate["resolved_chord_density"] = result.metadata.get("resolved_chord_density")
            candidate["resolved_melody_density"] = result.metadata.get("resolved_melody_density")
            candidate["resolved_chord_rhythm_style"] = result.metadata.get("resolved_chord_rhythm_style")
            candidate["resolved_humanize"] = result.metadata.get("resolved_humanize")
            candidate["resolved_swing"] = result.metadata.get("resolved_swing")
            candidate["bars"] = result.metadata.get("bars")
            break
