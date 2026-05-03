from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


PREVIEW_DIRNAME = "preview"
TRACK_FILES = ("melody.mid", "chords.mid", "bass.mid", "drums.mid")
MIX_NAME = "full_arrangement.mid"
SAMPLE_RATE = 44100
ENV_SOUNDFONT = "PY2FL_SOUNDFONT"
ENV_FLUIDSYNTH = "PY2FL_FLUIDSYNTH"


@dataclass(slots=True)
class AudioRenderResult:
    candidate_dir: Path
    rendered: list[Path]
    skipped: list[Path]
    cache_hits: list[Path]


class SoundFontMissing(RuntimeError):
    pass


class FluidsynthMissing(RuntimeError):
    pass


def resolve_soundfont(explicit: Path | str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    env_value = os.environ.get(ENV_SOUNDFONT)
    if env_value:
        path = Path(env_value).expanduser()
        if path.is_file():
            return path
    return None


def resolve_fluidsynth_binary(explicit: str | None = None) -> str | None:
    if explicit and shutil.which(explicit):
        return explicit
    env_value = os.environ.get(ENV_FLUIDSYNTH)
    if env_value and shutil.which(env_value):
        return env_value
    found = shutil.which("fluidsynth")
    return found


def is_available(soundfont: Path | str | None = None, fluidsynth_binary: str | None = None) -> bool:
    return resolve_soundfont(soundfont) is not None and resolve_fluidsynth_binary(fluidsynth_binary) is not None


def render_candidate(
    candidate_dir: Path,
    soundfont: Path | str | None = None,
    fluidsynth_binary: str | None = None,
    *,
    force: bool = False,
    sample_rate: int = SAMPLE_RATE,
    timeout: float = 90.0,
) -> AudioRenderResult:
    """Render melody/chords/bass/drums and the full mix WAVs for a candidate folder.

    Per-track renders go into <candidate>/preview/<stem>.wav. Files are skipped
    when their .mid file is older than the cached .wav unless force is True.
    """
    candidate_dir = Path(candidate_dir)
    if not candidate_dir.is_dir():
        raise FileNotFoundError(f"candidate folder not found: {candidate_dir}")

    sf2 = resolve_soundfont(soundfont)
    if sf2 is None:
        raise SoundFontMissing(
            "No SoundFont found. Pass --soundfont or set PY2FL_SOUNDFONT to a .sf2 file path."
        )
    binary = resolve_fluidsynth_binary(fluidsynth_binary)
    if binary is None:
        raise FluidsynthMissing(
            "fluidsynth binary not found on PATH. Install fluidsynth or set PY2FL_FLUIDSYNTH."
        )

    preview_dir = candidate_dir / PREVIEW_DIRNAME
    preview_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[Path] = []
    skipped: list[Path] = []
    cache_hits: list[Path] = []

    targets = [(name, candidate_dir / name) for name in (*TRACK_FILES, MIX_NAME)]
    for name, midi_path in targets:
        if not midi_path.is_file():
            skipped.append(midi_path)
            continue
        wav_path = preview_dir / (Path(name).stem + ".wav")
        if not force and _cache_valid(midi_path, wav_path):
            cache_hits.append(wav_path)
            continue
        _render_one(binary, sf2, midi_path, wav_path, sample_rate=sample_rate, timeout=timeout)
        rendered.append(wav_path)

    return AudioRenderResult(
        candidate_dir=candidate_dir,
        rendered=rendered,
        skipped=skipped,
        cache_hits=cache_hits,
    )


def preview_wav_path(candidate_dir: Path, midi_name: str) -> Path:
    return Path(candidate_dir) / PREVIEW_DIRNAME / (Path(midi_name).stem + ".wav")


def _cache_valid(midi_path: Path, wav_path: Path) -> bool:
    if not wav_path.is_file():
        return False
    try:
        return wav_path.stat().st_mtime >= midi_path.stat().st_mtime and wav_path.stat().st_size > 0
    except OSError:
        return False


def _render_one(
    binary: str,
    soundfont: Path,
    midi_path: Path,
    wav_path: Path,
    *,
    sample_rate: int,
    timeout: float,
) -> None:
    cmd = [
        binary,
        "-ni",
        "-q",
        "-g", "0.8",
        "-r", str(sample_rate),
        "-T", "wav",
        "-F", str(wav_path),
        str(soundfont),
        str(midi_path),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"fluidsynth failed for {midi_path.name}: {stderr or exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"fluidsynth timed out for {midi_path.name}") from exc
