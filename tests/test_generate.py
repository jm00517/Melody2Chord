import io
from pathlib import Path

from py2fl.generator import generate_song
from py2fl.midi import parse_midi_notes, write_midi
from py2fl.models import BAR_TICKS, GenerationRequest, NoteEvent, TrackData
from py2fl.web import Py2FLWebApp


def test_generate_from_text(tmp_path: Path) -> None:
    result = generate_song(GenerationRequest(text="dark trap anthem", bars=4, seed=7, output_dir=tmp_path))
    assert result.metadata["input_mode"] == "text"
    assert result.metadata["tempo"] == 140
    assert len(result.files) == 6
    assert (result.output_dir / "full_arrangement.mid").exists()


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
    assert "Create Arrangement" in body
    assert "Generate MIDI Set" in body
