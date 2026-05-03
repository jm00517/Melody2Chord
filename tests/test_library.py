import io
import json
from pathlib import Path
from urllib.parse import urlencode

from py2fl.generator import generate_candidates, generate_song
from py2fl.library import (
    CONTROL_KEYS,
    delete_entry,
    entry_dir,
    get_entry,
    list_entries,
    save_candidate,
)
from py2fl.models import GenerationRequest
from py2fl.web import Py2FLWebApp


def _make_candidate(tmp_path: Path) -> Path:
    result = generate_song(
        GenerationRequest(
            text="dreamy rnb night drive",
            bars=4,
            seed=11,
            humanize="med",
            swing="low",
            output_dir=tmp_path / "exports",
        )
    )
    return result.output_dir


def test_save_then_list_returns_entry(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    library = tmp_path / "library"

    entry = save_candidate(candidate, "Dreamy v1", library)
    entries = list_entries(library)

    assert any(e["id"] == entry["id"] for e in entries)
    assert entry["name"] == "Dreamy v1"
    assert entry["text"] == "dreamy rnb night drive"
    assert entry["bars"] == 4
    assert get_entry(entry["id"], library) == entry


def test_save_copies_files(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    library = tmp_path / "library"

    entry = save_candidate(candidate, "Copy Test", library)
    folder = entry_dir(entry["id"], library)

    for name in ("melody.mid", "chords.mid", "bass.mid", "drums.mid", "full_arrangement.mid", "meta.json"):
        assert (folder / name).is_file(), f"missing {name} in saved entry"


def test_save_records_controls_for_continuation(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    library = tmp_path / "library"

    entry = save_candidate(candidate, "Controls", library)
    controls = entry["controls"]

    for key in CONTROL_KEYS:
        assert key in controls, f"missing control key {key}"
    assert controls["humanize"] == "med"
    assert controls["swing"] == "low"


def test_delete_removes_folder_and_entry(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    library = tmp_path / "library"

    entry = save_candidate(candidate, "ToDelete", library)
    folder = entry_dir(entry["id"], library)
    assert folder.is_dir()

    assert delete_entry(entry["id"], library) is True
    assert not folder.exists()
    assert get_entry(entry["id"], library) is None
    assert delete_entry(entry["id"], library) is False


def test_web_save_then_library_page_flow(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    library_dir = tmp_path / "library"
    output_dir.mkdir()
    results = generate_candidates(
        GenerationRequest(text="dreamy rnb", bars=4, seed=21, output_dir=output_dir),
        count=2,
    )
    batch_dir = results[0].output_dir.parent
    app = Py2FLWebApp(output_dir=output_dir, library_dir=library_dir)

    body = urlencode({"batch_dir": str(batch_dir), "candidate_index": "1", "name": "Web Save"}).encode()
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/library/save",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    list(app(environ, start_response))
    assert captured["status"].startswith("303")
    assert captured["headers"]["Location"] == "/library"

    captured.clear()
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/library", "QUERY_STRING": ""}
    chunks = list(app(environ, start_response))
    assert captured["status"].startswith("200")
    page = b"".join(chunks).decode("utf-8")
    assert "Web Save" in page
    assert "Continue from this" in page

    entries = list_entries(library_dir)
    assert len(entries) == 1
    assert entries[0]["name"] == "Web Save"


def test_web_continue_prefills_form_state(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    library_dir = tmp_path / "library"
    output_dir.mkdir()
    result = generate_song(
        GenerationRequest(text="silky neo soul", bars=4, seed=33, humanize="med", output_dir=output_dir)
    )
    entry = save_candidate(result.output_dir, "Silky", library_dir)
    app = Py2FLWebApp(output_dir=output_dir, library_dir=library_dir)

    body = urlencode({"entry_id": entry["id"]}).encode()
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/library/continue",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    chunks = list(app(environ, start_response))
    assert captured["status"].startswith("200")
    page = b"".join(chunks).decode("utf-8")
    assert "silky neo soul" in page
    assert 'value="med"' in page or 'value="med" selected' in page
    assert "From Library" in page


def test_save_handles_duplicate_names(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    library = tmp_path / "library"

    first = save_candidate(candidate, "Same Name", library)
    second = save_candidate(candidate, "Same Name", library)

    assert first["id"] != second["id"]
    assert entry_dir(first["id"], library).is_dir()
    assert entry_dir(second["id"], library).is_dir()

    index = json.loads((library / "index.json").read_text(encoding="utf-8"))
    assert len(index["entries"]) == 2
