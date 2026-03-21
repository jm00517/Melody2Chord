from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import random
import re

from .arrangement import build_arrangement
from .melody import analyze_melody_file
from .midi import write_meta, write_midi
from .models import Arrangement, GenerationRequest, GenerationResult, TrackData
from .music_theory import key_label
from .text_analysis import analyze_text

BATCH_META_FILENAME = "batch_meta.json"


def generate_song(request: GenerationRequest) -> GenerationResult:
    context = _prepare_context(request)
    arrangement = build_arrangement(
        text_features=context["text_features"],
        melody_analysis=context["melody_analysis"],
        tempo=request.tempo,
        key=request.key,
        bars=request.bars,
        seed=request.seed,
    )
    run_dir = _build_output_dir(request.output_dir, request.text, request.melody_midi_path)
    return _write_arrangement(run_dir, arrangement, request, candidate_index=1, candidate_seed=request.seed, reroll_scope="all")


def generate_candidates(request: GenerationRequest, count: int = 4, reroll_scope: str = "all", seed_offset: int = 0) -> list[GenerationResult]:
    if count < 1:
        raise ValueError("count must be at least 1")
    if reroll_scope not in {"all", "chords"}:
        raise ValueError("reroll_scope must be 'all' or 'chords'")

    context = _prepare_context(request)
    batch_dir = _build_output_dir(request.output_dir, request.text, request.melody_midi_path)
    batch_dir.mkdir(parents=True, exist_ok=True)

    if request.seed is not None:
        base_seed = request.seed + seed_offset
    else:
        base_seed = random.SystemRandom().randrange(1, 1_000_000_000) + seed_offset

    base_arrangement = None
    if reroll_scope == "chords":
        base_arrangement = build_arrangement(
            text_features=context["text_features"],
            melody_analysis=context["melody_analysis"],
            tempo=request.tempo,
            key=request.key,
            bars=request.bars,
            seed=base_seed,
        )

    results: list[GenerationResult] = []
    for index in range(count):
        candidate_seed = base_seed + index * 101 + (5000 if reroll_scope == "chords" else 0)
        arrangement = build_arrangement(
            text_features=context["text_features"],
            melody_analysis=context["melody_analysis"],
            tempo=request.tempo,
            key=request.key,
            bars=request.bars,
            seed=candidate_seed,
        )
        if base_arrangement is not None:
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
            )
        candidate_dir = batch_dir / f"option_{index + 1:02d}"
        result = _write_arrangement(candidate_dir, arrangement, request, candidate_index=index + 1, candidate_seed=candidate_seed, reroll_scope=reroll_scope)
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
        "source_melody": str(request.melody_midi_path) if request.melody_midi_path else None,
        "tempo": request.tempo,
        "key": request.key,
        "genre": request.genre,
        "bars": request.bars,
        "seed": request.seed,
        "candidate_count": len(results),
        "selected_option": selected_option,
        "selected_output_dir": None if selected_candidate is None else str(selected_candidate.output_dir),
        "candidates": [
            {
                "candidate_index": result.metadata.get("candidate_index"),
                "option_name": result.metadata.get("option_name") or Path(result.output_dir).name,
                "output_dir": str(result.output_dir),
                "progression_label": result.metadata.get("progression_label"),
                "candidate_seed": result.metadata.get("candidate_seed"),
                "tempo": result.metadata.get("tempo"),
                "key": result.metadata.get("key"),
                "drum_pattern": result.metadata.get("drum_pattern"),
                "bass_pattern": result.metadata.get("bass_pattern"),
                "style_tags": result.metadata.get("style_tags"),
                "preview_file": "full_arrangement.mid",
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
    if not request.text and not request.melody_midi_path:
        raise ValueError("At least one input is required: text or melody_midi_path")
    return {
        "text_features": analyze_text(request.text, request.genre),
        "melody_analysis": analyze_melody_file(request.melody_midi_path) if request.melody_midi_path else None,
    }


def _write_arrangement(run_dir: Path, arrangement: Arrangement, request: GenerationRequest, *, candidate_index: int | None, candidate_seed: int | None, reroll_scope: str) -> GenerationResult:
    run_dir.mkdir(parents=True, exist_ok=True)

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

    metadata = {
        "input_mode": _input_mode(request),
        "tempo": arrangement.tempo_bpm,
        "key": key_label(arrangement.key, arrangement.mode),
        "bars": arrangement.bars,
        "style_tags": arrangement.style_tags,
        "source_melody": str(request.melody_midi_path) if request.melody_midi_path else None,
        "text": request.text,
        "files": [file.name for file in files],
        "progression_label": arrangement.progression_label,
        "progression_degrees": arrangement.progression_degrees,
        "drum_pattern": arrangement.drum_pattern,
        "bass_pattern": arrangement.bass_pattern,
        "candidate_index": candidate_index,
        "candidate_seed": candidate_seed,
        "reroll_scope": reroll_scope,
        "preview_file": "full_arrangement.mid",
    }
    meta_path = run_dir / "meta.json"
    write_meta(meta_path, metadata)
    files.append(meta_path)
    return GenerationResult(output_dir=run_dir, files=files, metadata=metadata)


def _build_output_dir(base_dir: Path, text: str | None, melody_path: Path | None) -> Path:
    base_dir = Path(base_dir)
    base_name = None
    if text:
        base_name = _slugify(text[:40])
    elif melody_path:
        base_name = _slugify(melody_path.stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir / f"{timestamp}_{base_name or 'arrangement'}"


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    return cleaned.strip("_") or "arrangement"


def _input_mode(request: GenerationRequest) -> str:
    if request.text and request.melody_midi_path:
        return "text+melody"
    if request.melody_midi_path:
        return "melody"
    return "text"
