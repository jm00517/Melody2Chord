from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from .arrangement import build_arrangement
from .melody import analyze_melody_file
from .midi import write_meta, write_midi
from .models import GenerationRequest, GenerationResult, TrackData
from .music_theory import key_label
from .text_analysis import analyze_text


def generate_song(request: GenerationRequest) -> GenerationResult:
    if not request.text and not request.melody_midi_path:
        raise ValueError("At least one input is required: text or melody_midi_path")

    text_features = analyze_text(request.text, request.genre)
    melody_analysis = analyze_melody_file(request.melody_midi_path) if request.melody_midi_path else None
    arrangement = build_arrangement(
        text_features=text_features,
        melody_analysis=melody_analysis,
        tempo=request.tempo,
        key=request.key,
        bars=request.bars,
        seed=request.seed,
    )

    run_dir = _build_output_dir(request.output_dir, request.text, request.melody_midi_path)
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
