from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PPQ = 480
BAR_TICKS = PPQ * 4


@dataclass(slots=True)
class NoteEvent:
    pitch: int
    start: int
    duration: int
    velocity: int = 96
    channel: int = 0

    @property
    def end(self) -> int:
        return self.start + self.duration


@dataclass(slots=True)
class TrackData:
    name: str
    notes: list[NoteEvent]
    channel: int = 0


@dataclass(slots=True)
class TextFeatures:
    raw_text: str
    style_tags: list[str]
    energy: str
    mood: str
    genre: str


@dataclass(slots=True)
class MelodyAnalysis:
    notes: list[NoteEvent]
    source_path: Path | None
    key: str
    mode: str
    tempo_bpm: int | None
    bars: int
    phrase_length: int
    source_start_offset_ticks: int = 0


@dataclass(slots=True)
class Arrangement:
    melody: list[NoteEvent]
    chords: list[NoteEvent]
    bass: list[NoteEvent]
    drums: list[NoteEvent]
    tempo_bpm: int
    key: str
    mode: str
    bars: int
    style_tags: list[str] = field(default_factory=list)
    progression_label: str = ""
    progression_degrees: list[int] = field(default_factory=list)
    drum_pattern: str = ""
    bass_pattern: str = ""
    chord_density: int = 1
    melody_density: str = "normal"
    chord_rhythm_style: str = "hold"
    humanize: str = "off"


@dataclass(slots=True)
class GenerationRequest:
    text: str | None = None
    melody_midi_path: Path | None = None
    chord_progression: str | None = None
    tempo: int | None = None
    key: str | None = None
    genre: str | None = None
    bars: int | None = None
    chord_density: str | None = None
    melody_density: str | None = None
    chord_rhythm_style: str | None = None
    humanize: str | None = None
    seed: int | None = None
    output_dir: Path = Path("exports")


@dataclass(slots=True)
class GenerationResult:
    output_dir: Path
    files: list[Path]
    metadata: dict[str, object]
