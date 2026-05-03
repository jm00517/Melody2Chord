from pathlib import Path

import pytest

from py2fl.generator import generate_song
from py2fl.models import GenerationRequest
from py2fl.reaper import REAPER_FILENAME, write_reaper_project


def _make_candidate(tmp_path: Path) -> Path:
    result = generate_song(
        GenerationRequest(text="dreamy rnb", bars=4, seed=15, output_dir=tmp_path / "exports")
    )
    return result.output_dir


def test_generate_song_writes_reaper_project(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    rpp_path = candidate / REAPER_FILENAME
    assert rpp_path.is_file()
    text = rpp_path.read_text(encoding="utf-8")
    assert text.startswith("<REAPER_PROJECT")
    assert text.rstrip().endswith(">")
    for filename in ("melody.mid", "chords.mid", "bass.mid", "drums.mid"):
        assert filename in text, f"{filename} should be referenced from .rpp"


def test_rpp_contains_one_track_per_present_midi(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    text = (candidate / REAPER_FILENAME).read_text(encoding="utf-8")
    assert text.count("<TRACK") == 4
    assert text.count("<SOURCE MIDI") == 4
    assert text.count("<ITEM") == 4


def test_rpp_skips_missing_midi_files(tmp_path: Path) -> None:
    fake = tmp_path / "candidate"
    fake.mkdir()
    (fake / "melody.mid").write_bytes(b"MThd")
    (fake / "drums.mid").write_bytes(b"MThd")
    rpp_path = write_reaper_project(fake, tempo=120, bars=4)
    assert rpp_path is not None and rpp_path.is_file()
    text = rpp_path.read_text(encoding="utf-8")
    assert text.count("<TRACK") == 2
    assert "melody.mid" in text and "drums.mid" in text
    assert "chords.mid" not in text


def test_rpp_returns_none_when_no_midi_present(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert write_reaper_project(empty, tempo=120, bars=4) is None


def test_rpp_uses_unique_guids_per_track(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    text = (candidate / REAPER_FILENAME).read_text(encoding="utf-8")
    track_ids = [line.strip() for line in text.splitlines() if line.strip().startswith("TRACKID ")]
    assert len(track_ids) == 4
    assert len(set(track_ids)) == 4, "TRACKIDs must be unique"


def test_rpp_tempo_and_length_reflect_arrangement(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    text = (candidate / REAPER_FILENAME).read_text(encoding="utf-8")
    assert "TEMPO " in text
    tempo_line = next(line for line in text.splitlines() if line.strip().startswith("TEMPO "))
    parts = tempo_line.split()
    assert int(parts[1]) > 0
    assert "LENGTH " in text


def test_rpp_filename_is_quoted(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    text = (candidate / REAPER_FILENAME).read_text(encoding="utf-8")
    assert 'FILE "melody.mid"' in text
