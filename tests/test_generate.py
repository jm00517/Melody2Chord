import io
import json
from pathlib import Path

from py2fl.generator import BATCH_META_FILENAME, generate_candidates, generate_song, load_batch_meta, reroll_candidate_bar
from py2fl.melody import analyze_melody_file
from py2fl.midi import parse_midi_notes, write_midi
from py2fl.models import BAR_TICKS, GenerationRequest, NoteEvent, TrackData
from py2fl.web import Py2FLWebApp


def test_generate_from_text(tmp_path: Path) -> None:
    result = generate_song(GenerationRequest(text="dark trap anthem", bars=4, seed=7, output_dir=tmp_path))
    assert result.metadata["input_mode"] == "text"
    assert result.metadata["tempo"] == 140
    assert len(result.files) == 6
    assert result.metadata["full_progression_text"]
    assert len(result.metadata["bar_summary"]) == 4
    assert (result.output_dir / "full_arrangement.mid").exists()


def test_generate_candidates_creates_multiple_options(tmp_path: Path) -> None:
    results = generate_candidates(GenerationRequest(text="dreamy rnb night drive", bars=4, output_dir=tmp_path), count=4)
    assert len(results) == 4
    assert all(result.output_dir.name.startswith("option_") for result in results)
    labels = {result.metadata["progression_label"] for result in results}
    assert len(labels) >= 2

    batch_meta = load_batch_meta(results[0].output_dir.parent)
    assert batch_meta["candidate_count"] == 4
    assert batch_meta["selected_option"] is None
    assert len(batch_meta["candidates"]) == 4
    assert batch_meta["candidates"][0]["preview_file"] == "full_arrangement.mid"
    assert "full_progression_text" in batch_meta["candidates"][0]




def test_reroll_candidate_bar_updates_candidate_meta(tmp_path: Path) -> None:
    results = generate_candidates(GenerationRequest(text="dreamy rnb night drive", bars=4, seed=17, output_dir=tmp_path), count=2)
    batch_dir = results[0].output_dir.parent
    before = json.loads((results[0].output_dir / "meta.json").read_text(encoding="utf-8"))
    rerolled = reroll_candidate_bar(batch_dir, candidate_index=1, bar_index=2, reroll_nonce=654321)
    after = json.loads((results[0].output_dir / "meta.json").read_text(encoding="utf-8"))

    assert rerolled["candidates"][0]["full_progression_text"] == after["full_progression_text"]
    assert after["reroll_scope"] == "bar_harmony"
    assert len(after["bar_summary"]) == 4
    assert after["candidate_seed"] != before["candidate_seed"]
    assert after["recently_updated_bar"] == 2
    assert any(bar.get("recently_updated") for bar in after["bar_summary"])

def test_generate_from_melody_preserves_melody(tmp_path: Path) -> None:
    melody_path = tmp_path / "melody_input.mid"
    input_notes = [
        NoteEvent(pitch=60, start=0, duration=BAR_TICKS // 2),
        NoteEvent(pitch=62, start=BAR_TICKS // 2, duration=BAR_TICKS // 2),
        NoteEvent(pitch=64, start=BAR_TICKS, duration=BAR_TICKS // 2),
        NoteEvent(pitch=67, start=BAR_TICKS + BAR_TICKS // 2, duration=BAR_TICKS // 2),
    ]
    write_midi(melody_path, [TrackData(name="Input Melody", notes=input_notes)], tempo_bpm=100)

    result = generate_song(GenerationRequest(melody_midi_path=melody_path, output_dir=tmp_path))
    parsed_tracks, tempo = parse_midi_notes(result.output_dir / "melody.mid")
    melodic_track = next(track for track in parsed_tracks if track.notes)

    assert result.metadata["input_mode"] == "melody"
    assert tempo == 100
    assert [(note.pitch, note.start, note.duration) for note in melodic_track.notes] == [
        (note.pitch, note.start, note.duration) for note in input_notes
    ]


def test_generate_from_non_480_ppq_melody_keeps_timing(tmp_path: Path) -> None:
    melody_path = tmp_path / "melody_96ppq.mid"
    input_notes = [
        NoteEvent(pitch=60, start=480, duration=480),
        NoteEvent(pitch=64, start=960, duration=240),
    ]
    write_midi(melody_path, [TrackData(name="Input Melody", notes=input_notes)], tempo_bpm=120, ppq=96)

    result = generate_song(GenerationRequest(melody_midi_path=melody_path, output_dir=tmp_path))
    parsed_tracks, tempo = parse_midi_notes(result.output_dir / "melody.mid")
    melodic_track = next(track for track in parsed_tracks if track.notes)

    assert tempo == 120
    assert [(note.pitch, note.start, note.duration) for note in melodic_track.notes] == [
        (60, 2400, 2400),
        (64, 4800, 1200),
    ]


def test_melody_analysis_aligns_offset_to_zero(tmp_path: Path) -> None:
    melody_path = tmp_path / "pickup.mid"
    input_notes = [
        NoteEvent(pitch=67, start=BAR_TICKS // 2, duration=BAR_TICKS // 4),
        NoteEvent(pitch=69, start=BAR_TICKS, duration=BAR_TICKS // 4),
    ]
    write_midi(melody_path, [TrackData(name="Pickup", notes=input_notes)], tempo_bpm=110)

    analysis = analyze_melody_file(melody_path)

    assert analysis.source_start_offset_ticks == BAR_TICKS // 2
    assert analysis.notes[0].start == 0
    assert analysis.notes[1].start == BAR_TICKS // 2


def test_generate_from_offset_melody_aligns_output_and_meta(tmp_path: Path) -> None:
    melody_path = tmp_path / "offset_input.mid"
    input_notes = [
        NoteEvent(pitch=67, start=BAR_TICKS // 2, duration=BAR_TICKS // 4),
        NoteEvent(pitch=71, start=BAR_TICKS, duration=BAR_TICKS // 2),
        NoteEvent(pitch=72, start=BAR_TICKS + BAR_TICKS // 2, duration=BAR_TICKS // 4),
    ]
    write_midi(melody_path, [TrackData(name="Pickup", notes=input_notes)], tempo_bpm=98)

    result = generate_song(GenerationRequest(melody_midi_path=melody_path, output_dir=tmp_path))
    parsed_tracks, _ = parse_midi_notes(result.output_dir / "melody.mid")
    melodic_track = next(track for track in parsed_tracks if track.notes)
    chord_tracks, _ = parse_midi_notes(result.output_dir / "chords.mid")
    chord_track = next(track for track in chord_tracks if track.notes)

    assert melodic_track.notes[0].start == 0
    assert chord_track.notes[0].start == 0
    assert result.metadata["source_start_offset_ticks"] == BAR_TICKS // 2
    assert result.metadata["melody_aligned_to_start"] is True


def test_generate_from_text_and_melody(tmp_path: Path) -> None:
    melody_path = tmp_path / "hybrid.mid"
    input_notes = [
        NoteEvent(pitch=69, start=0, duration=BAR_TICKS // 4),
        NoteEvent(pitch=72, start=BAR_TICKS // 2, duration=BAR_TICKS // 4),
    ]
    write_midi(melody_path, [TrackData(name="Topline", notes=input_notes)], tempo_bpm=92)

    result = generate_song(
        GenerationRequest(
            text="dreamy rnb night drive",
            melody_midi_path=melody_path,
            seed=3,
            output_dir=tmp_path,
        )
    )

    assert result.metadata["input_mode"] == "text+melody"
    assert result.metadata["tempo"] == 92
    assert "rnb" in result.metadata["style_tags"]


def test_generate_from_melody_adds_chord_variation(tmp_path: Path) -> None:
    melody_path = tmp_path / "variation.mid"
    input_notes = [
        NoteEvent(pitch=64, start=0, duration=BAR_TICKS // 2),
        NoteEvent(pitch=67, start=BAR_TICKS // 2, duration=BAR_TICKS // 2),
        NoteEvent(pitch=71, start=BAR_TICKS, duration=BAR_TICKS // 2),
        NoteEvent(pitch=69, start=BAR_TICKS + BAR_TICKS // 2, duration=BAR_TICKS // 2),
        NoteEvent(pitch=72, start=BAR_TICKS * 2, duration=BAR_TICKS // 2),
        NoteEvent(pitch=74, start=BAR_TICKS * 2 + BAR_TICKS // 2, duration=BAR_TICKS // 2),
        NoteEvent(pitch=76, start=BAR_TICKS * 3, duration=BAR_TICKS // 2),
        NoteEvent(pitch=79, start=BAR_TICKS * 3 + BAR_TICKS // 2, duration=BAR_TICKS // 2),
    ]
    write_midi(melody_path, [TrackData(name="Topline", notes=input_notes)], tempo_bpm=96)

    result = generate_song(GenerationRequest(melody_midi_path=melody_path, seed=12, output_dir=tmp_path))
    parsed_tracks, _ = parse_midi_notes(result.output_dir / "chords.mid")
    chord_track = next(track for track in parsed_tracks if track.notes)
    notes_per_bar = {}
    for note in chord_track.notes:
        notes_per_bar.setdefault(note.start // BAR_TICKS, 0)
        notes_per_bar[note.start // BAR_TICKS] += 1

    assert any(count > 3 for count in notes_per_bar.values())
    assert "MeloFlow" in result.metadata["progression_label"]


def test_generate_with_density_options_updates_metadata_and_sub_chords(tmp_path: Path) -> None:
    result = generate_song(
        GenerationRequest(
            text="dreamy rnb night drive",
            bars=4,
            chord_density="3",
            melody_density="dense",
            chord_rhythm_style="strum",
            seed=22,
            output_dir=tmp_path,
        )
    )

    assert result.metadata["requested_chord_density"] == "3"
    assert result.metadata["resolved_chord_density"] == 3
    assert result.metadata["resolved_melody_density"] == "dense"
    assert result.metadata["resolved_chord_rhythm_style"] == "strum"
    assert any(bar["chord_event_count"] > 1 for bar in result.metadata["bar_summary"])


def test_dense_melody_density_increases_generated_note_count(tmp_path: Path) -> None:
    normal = generate_song(GenerationRequest(text="dreamy rnb night drive", bars=4, melody_density="normal", seed=30, output_dir=tmp_path / "normal"))
    dense = generate_song(GenerationRequest(text="dreamy rnb night drive", bars=4, melody_density="xdense", seed=30, output_dir=tmp_path / "dense"))

    normal_tracks, _ = parse_midi_notes(normal.output_dir / "melody.mid")
    dense_tracks, _ = parse_midi_notes(dense.output_dir / "melody.mid")
    normal_count = len(next(track for track in normal_tracks if track.notes).notes)
    dense_count = len(next(track for track in dense_tracks if track.notes).notes)

    assert dense_count > normal_count


def test_chord_density_and_strum_change_chord_timing(tmp_path: Path) -> None:
    result = generate_song(
        GenerationRequest(
            chord_progression="Am-F-C-G",
            text="dreamy rnb topline",
            bars=4,
            chord_density="2",
            chord_rhythm_style="strum",
            seed=31,
            output_dir=tmp_path,
        )
    )

    chord_tracks, _ = parse_midi_notes(result.output_dir / "chords.mid")
    chord_notes = next(track for track in chord_tracks if track.notes).notes
    starts_in_first_bar = sorted({note.start for note in chord_notes if note.start < BAR_TICKS})

    assert len(starts_in_first_bar) >= 2
    assert any(start not in {0, BAR_TICKS // 2} for start in starts_in_first_bar)


def test_web_app_renders_home(tmp_path: Path) -> None:
    app = Py2FLWebApp(output_dir=tmp_path)
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(app({
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
        "CONTENT_TYPE": "text/plain",
    }, start_response)).decode("utf-8")

    assert captured["status"] == "200 OK"
    assert "Generate Options" in body
    assert "Preview Volume" in body
    assert "large comparison view" in body
    assert "Mute Melody" in body
    assert "Mute Chords" in body




def test_web_reroll_bar_fragment_response(tmp_path: Path) -> None:
    app = Py2FLWebApp(output_dir=tmp_path)
    results = generate_candidates(GenerationRequest(text="dreamy rnb night drive", bars=4, seed=19, output_dir=tmp_path), count=2)
    batch_dir = results[0].output_dir.parent
    body_bytes = f"batch_dir={batch_dir}&candidate_index=1&bar_index=2&reroll_nonce=42&fragment=1".encode("utf-8")
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(app({
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/reroll-bar",
        "wsgi.input": io.BytesIO(body_bytes),
        "CONTENT_LENGTH": str(len(body_bytes)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
    }, start_response)).decode("utf-8")

    assert captured["status"] == "200 OK"
    assert 'data-fragment="candidate-tab"' in body
    assert 'data-fragment="candidate-progress"' in body
    assert 'data-fragment="bar-card"' in body
    assert 'candidate-progress-1' in body
    assert 'candidate-1-bar-2' in body
    assert 'Recently Updated' in body

def test_web_select_persists_batch_choice(tmp_path: Path) -> None:
    app = Py2FLWebApp(output_dir=tmp_path)
    results = generate_candidates(GenerationRequest(text="dreamy rnb night drive", bars=4, seed=11, output_dir=tmp_path), count=3)
    batch_dir = results[0].output_dir.parent
    body_bytes = f"batch_dir={batch_dir}&candidate_index=2".encode("utf-8")
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(app({
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/select",
        "wsgi.input": io.BytesIO(body_bytes),
        "CONTENT_LENGTH": str(len(body_bytes)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
    }, start_response)).decode("utf-8")

    batch_meta = json.loads((batch_dir / BATCH_META_FILENAME).read_text(encoding="utf-8"))
    assert captured["status"] == "200 OK"
    assert batch_meta["selected_option"] == 2
    assert "Selected Candidate" in body
    assert "Harmony Timeline" in body
    assert "Play Bar" in body
    assert "Reroll Harmony" in body
    assert "Recently Updated" in body


def test_web_files_serves_preview_midi(tmp_path: Path) -> None:
    app = Py2FLWebApp(output_dir=tmp_path)
    results = generate_candidates(GenerationRequest(text="dark trap anthem", bars=4, seed=9, output_dir=tmp_path), count=2)
    preview_file = results[0].output_dir / "full_arrangement.mid"
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    payload = b"".join(app({
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/files",
        "QUERY_STRING": f"path={preview_file}",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
        "CONTENT_TYPE": "text/plain",
    }, start_response))

    assert captured["status"] == "200 OK"
    assert payload[:4] == b"MThd"

def test_generate_from_chord_progression(tmp_path: Path) -> None:
    result = generate_song(
        GenerationRequest(
            chord_progression="1-5-6-4",
            text="dreamy rnb topline",
            bars=4,
            seed=21,
            output_dir=tmp_path,
        )
    )

    assert result.metadata["input_mode"] == "text+chords"
    assert result.metadata["ui_mode"] == "melody_from_chords"
    assert result.metadata["timeline_title"] == "Melody Timeline"
    assert result.metadata["bar_action_label"] == "Reroll Melody"
    assert len(result.metadata["bar_summary"]) == 4
    parsed_tracks, _ = parse_midi_notes(result.output_dir / "melody.mid")
    melodic_track = next(track for track in parsed_tracks if track.notes)
    assert melodic_track.notes


def test_reroll_chord_progression_bar_updates_melody(tmp_path: Path) -> None:
    results = generate_candidates(
        GenerationRequest(
            chord_progression="Am-F-C-G",
            text="dreamy rnb topline",
            bars=4,
            seed=31,
            output_dir=tmp_path,
        ),
        count=2,
    )
    batch_dir = results[0].output_dir.parent
    before_tracks, _ = parse_midi_notes(results[0].output_dir / "melody.mid")
    before = next(track for track in before_tracks if track.notes).notes
    rerolled = reroll_candidate_bar(batch_dir, candidate_index=1, bar_index=2, reroll_nonce=1234)
    after_tracks, _ = parse_midi_notes(results[0].output_dir / "melody.mid")
    after = next(track for track in after_tracks if track.notes).notes

    assert rerolled["candidates"][0]["full_progression_text"]
    assert before != after
    meta = json.loads((results[0].output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["reroll_scope"] == "bar_melody"
    assert meta["bar_action_label"] == "Reroll Melody"


def test_web_chord_page_renders(tmp_path: Path) -> None:
    app = Py2FLWebApp(output_dir=tmp_path)
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(app({
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/melody-from-chords",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
        "CONTENT_TYPE": "text/plain",
    }, start_response)).decode("utf-8")

    assert captured["status"] == "200 OK"
    assert "Chord In. Melody Out." in body
    assert "Generate Melodies" in body
    assert "1-5-6-4" in body
