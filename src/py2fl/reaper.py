from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable

from .models import BAR_TICKS


REAPER_FILENAME = "arrangement.rpp"

DEFAULT_TRACKS: tuple[tuple[str, str, int], ...] = (
    ("Melody", "melody.mid", 0x00FFFF),
    ("Chords", "chords.mid", 0xFFAA00),
    ("Bass", "bass.mid", 0x66CCFF),
    ("Drums", "drums.mid", 0xFF6666),
)


def write_reaper_project(
    candidate_dir: Path,
    *,
    tempo: int,
    bars: int,
    output_path: Path | None = None,
    tracks: Iterable[tuple[str, str, int]] | None = None,
) -> Path | None:
    """Write a REAPER .rpp project that references the candidate's .mid files.

    Returns the path to the written .rpp, or None if no .mid files exist in
    candidate_dir (in which case nothing is written).
    """
    candidate_dir = Path(candidate_dir)
    selected = []
    for name, midi_filename, color in (tracks or DEFAULT_TRACKS):
        if (candidate_dir / midi_filename).is_file():
            selected.append((name, midi_filename, color))
    if not selected:
        return None

    seconds_per_beat = 60.0 / max(1, int(tempo))
    item_length = max(1, int(bars or 1)) * 4 * seconds_per_beat

    output_path = Path(output_path) if output_path else candidate_dir / REAPER_FILENAME
    output_path.write_text(
        _render_project(selected, tempo=tempo, item_length=item_length),
        encoding="utf-8",
    )
    return output_path


def _render_project(
    tracks: list[tuple[str, str, int]],
    *,
    tempo: int,
    item_length: float,
) -> str:
    lines: list[str] = []
    lines.append('<REAPER_PROJECT 0.1 "6.0/win64" 1700000000')
    lines.append("  RIPPLE 0")
    lines.append("  GROUPOVERRIDE 0 0 0")
    lines.append("  AUTOXFADE 1")
    lines.append("  ENVATTACH 3")
    lines.append("  POOLEDENVATTACH 0")
    lines.append("  MIXERUIFLAGS 11 48")
    lines.append("  PEAKGAIN 1")
    lines.append("  FEEDBACK 0")
    lines.append("  PANLAW 1")
    lines.append("  PROJOFFS 0 0 0")
    lines.append("  MAXPROJLEN 0 0")
    lines.append("  GRID 3199 8 1 8 1 0 0 0")
    lines.append("  TIMEMODE 1 5 -1 30 0 0 -1")
    lines.append("  VIDEO_CONFIG 0 0 256")
    lines.append("  PANMODE 3")
    lines.append("  CURSOR 0")
    lines.append("  ZOOM 100 0 0")
    lines.append("  VZOOMEX 6 0")
    lines.append("  USE_REC_CFG 0")
    lines.append("  RECMODE 1")
    lines.append("  SMPTESYNC 0 30 100 40 1000 300 0 0 1 0 0")
    lines.append("  LOOP 0")
    lines.append("  LOOPGRAN 0 4")
    lines.append("  RECORD_PATH \"\" \"\"")
    lines.append("  <RECORD_CFG")
    lines.append("  >")
    lines.append("  <APPLYFX_CFG")
    lines.append("  >")
    lines.append("  RENDER_FILE \"\"")
    lines.append("  RENDER_PATTERN \"\"")
    lines.append("  RENDER_FMT 0 2 0")
    lines.append("  RENDER_1X 0")
    lines.append("  RENDER_RANGE 1 0 0 18 1000")
    lines.append("  RENDER_RESAMPLE 3 0 1")
    lines.append("  RENDER_ADDTOPROJ 0")
    lines.append("  RENDER_STEMS 0")
    lines.append("  RENDER_DITHER 0")
    lines.append("  TIMELOCKMODE 1")
    lines.append("  TEMPOENVLOCKMODE 1")
    lines.append("  ITEMMIX 0")
    lines.append("  DEFPITCHMODE 589824 0")
    lines.append("  TAKELANE 1")
    lines.append("  SAMPLERATE 44100 0 0")
    lines.append("  <RENDER_CFG")
    lines.append("  >")
    lines.append("  LOCK 1")
    lines.append("  <METRONOME 6 2")
    lines.append("    VOL 0.25 0.125")
    lines.append("    FREQ 800 1600 1")
    lines.append("    BEATLEN 4")
    lines.append("    SAMPLES \"\" \"\"")
    lines.append("    PATTERN 2863311530 2863311529")
    lines.append("  >")
    lines.append("  GLOBAL_AUTO -1")
    lines.append(f"  TEMPO {int(tempo)} 4 4")
    lines.append("  PLAYRATE 1 0 0.25 4")
    lines.append("  SELECTION 0 0")
    lines.append("  SELECTION2 0 0")
    lines.append("  MASTERAUTOMODE 0")
    lines.append("  MASTERTRACKHEIGHT 0 0")
    lines.append("  MASTERPEAKCOL 16576")
    lines.append("  MASTERMUTESOLO 0")
    lines.append("  MASTERTRACKVIEW 0 0.6667 0.5 0.5 0 0 0 0 0 0 0 0 0")
    lines.append("  MASTERHWOUT 0 0 1 0 0 0 0 -1")
    lines.append("  MASTER_NCH 2 2")
    lines.append("  MASTER_VOLUME 1 0 -1 -1 1")
    lines.append("  MASTER_FX 1")
    lines.append("  MASTER_SEL 0")

    for name, midi_filename, color in tracks:
        lines.extend(_render_track(name, midi_filename, color, item_length))

    lines.append(">")
    return "\n".join(lines) + "\n"


def _render_track(name: str, midi_filename: str, color: int, item_length: float) -> list[str]:
    track_guid = _guid()
    item_guid = _guid()
    source_guid = _guid()
    safe_name = _quote(name)
    safe_filename = _quote(midi_filename)
    return [
        "  <TRACK",
        f"    NAME {safe_name}",
        f"    PEAKCOL {color}",
        "    BEAT -1",
        "    AUTOMODE 0",
        "    VOLPAN 1 0 -1 -1 1",
        "    MUTESOLO 0 0 0",
        "    IPHASE 0",
        "    PLAYOFFS 0 1",
        "    ISBUS 0 0",
        "    BUSCOMP 0 0 0 0 0",
        "    SHOWINMIX 1 0.6667 0.5 1 0.5 0 0 0",
        "    FREEMODE 0",
        "    SEL 0",
        "    REC 0 0 1 0 0 0 0 0",
        "    VU 2",
        "    TRACKHEIGHT 0 0 0 0 0 0 0",
        "    INQ 0 0 0 0.5 100 0 0 100",
        "    NCHAN 2",
        "    FX 1",
        f"    TRACKID {track_guid}",
        "    PERF 0",
        "    MIDIOUT -1",
        "    MAINSEND 1 0",
        "    <ITEM",
        "      POSITION 0",
        "      SNAPOFFS 0",
        f"      LENGTH {item_length:.6f}",
        "      LOOP 0",
        "      ALLTAKES 0",
        "      FADEIN 1 0 0 1 0 0 0",
        "      FADEOUT 1 0 0 1 0 0 0",
        "      MUTE 0 0",
        "      SEL 0",
        f"      IGUID {item_guid}",
        "      IID 1",
        f"      NAME {safe_name}",
        "      VOLPAN 1 0 1 -1",
        "      SOFFS 0",
        "      PLAYRATE 1 1 0 -1 0 0.0025",
        "      CHANMODE 0",
        f"      GUID {source_guid}",
        "      <SOURCE MIDI",
        f"        FILE {safe_filename} 0",
        "      >",
        "    >",
        "  >",
    ]


def _guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def _quote(value: str) -> str:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    if "`" not in value:
        return f"`{value}`"
    return f'"{value.replace(chr(34), "")}"'
