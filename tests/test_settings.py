import io
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import pytest

from py2fl import settings as settings_module
from py2fl.web import Py2FLWebApp


@pytest.fixture(autouse=True)
def isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def _post(app: Py2FLWebApp, path: str, data: dict) -> dict:
    body = urlencode(data).encode()
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    list(app(environ, start_response))
    return captured


def test_save_to_disk_persists_and_loads_on_init(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)

    captured = _post(app, "/settings/save", {"gemini_api_key": "sekret-1234", "persist": "1"})
    assert captured["status"].startswith("303")
    assert os.environ.get("GEMINI_API_KEY") == "sekret-1234"
    assert json.loads(settings_module.config_path().read_text(encoding="utf-8"))[settings_module.KEY_GEMINI_API_KEY] == "sekret-1234"

    os.environ.pop("GEMINI_API_KEY", None)
    Py2FLWebApp(output_dir=output_dir)
    assert os.environ.get("GEMINI_API_KEY") == "sekret-1234"


def test_session_only_does_not_persist(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)

    _post(app, "/settings/save", {"gemini_api_key": "session-key"})
    assert os.environ.get("GEMINI_API_KEY") == "session-key"
    assert not settings_module.config_path().is_file()


def test_clear_removes_env_and_disk(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)
    _post(app, "/settings/save", {"gemini_api_key": "to-be-cleared", "persist": "1"})
    assert settings_module.config_path().is_file()

    captured = _post(app, "/settings/clear", {})
    assert captured["status"].startswith("303")
    assert os.environ.get("GEMINI_API_KEY") is None
    config = settings_module.load_config()
    assert settings_module.KEY_GEMINI_API_KEY not in config


def test_settings_page_masks_active_key(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    os.environ["GEMINI_API_KEY"] = "abcdefghij1234"
    app = Py2FLWebApp(output_dir=output_dir)

    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/settings", "QUERY_STRING": ""}
    chunks = list(app(environ, start_response))
    page = b"".join(chunks).decode("utf-8")
    assert captured["status"].startswith("200")
    assert "abcdefghij1234" not in page
    assert "1234" in page
    assert "•" in page


def test_audio_save_persists_soundfont_path(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    fake_sf2 = tmp_path / "fake.sf2"
    fake_sf2.write_bytes(b"RIFF")

    app = Py2FLWebApp(output_dir=output_dir)
    captured = _post(app, "/settings/audio", {"soundfont_path": str(fake_sf2), "fluidsynth_path": ""})
    assert captured["status"].startswith("303")
    assert os.environ.get("PY2FL_SOUNDFONT") == str(fake_sf2)

    config = settings_module.load_config()
    assert config[settings_module.KEY_SOUNDFONT_PATH] == str(fake_sf2)

    os.environ.pop("PY2FL_SOUNDFONT", None)
    Py2FLWebApp(output_dir=output_dir)
    assert os.environ.get("PY2FL_SOUNDFONT") == str(fake_sf2)


def test_audio_save_rejects_missing_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)
    captured = _post(app, "/settings/audio", {"soundfont_path": str(tmp_path / "nonexistent.sf2")})
    assert captured["status"].startswith("400")


def test_audio_clear_removes_paths(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    fake_sf2 = tmp_path / "fake.sf2"
    fake_sf2.write_bytes(b"RIFF")

    app = Py2FLWebApp(output_dir=output_dir)
    _post(app, "/settings/audio", {"soundfont_path": str(fake_sf2)})
    captured = _post(app, "/settings/audio/clear", {})
    assert captured["status"].startswith("303")
    assert os.environ.get("PY2FL_SOUNDFONT") is None
    assert settings_module.load_config().get(settings_module.KEY_SOUNDFONT_PATH) is None


def test_autodetect_picks_up_project_soundfont_and_fluidsynth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    output_dir = project / "exports"
    output_dir.mkdir(parents=True)
    (project / "soundfonts").mkdir()
    fake_sf = project / "soundfonts" / "demo.sf3"
    fake_sf.write_bytes(b"RIFF")
    tools_subdir = project / "tools" / "fluidsynth-build" / "bin"
    tools_subdir.mkdir(parents=True)
    fake_bin = tools_subdir / "fluidsynth.exe"
    fake_bin.write_bytes(b"MZ")

    monkeypatch.delenv("PY2FL_SOUNDFONT", raising=False)
    monkeypatch.delenv("PY2FL_FLUIDSYNTH", raising=False)

    Py2FLWebApp(output_dir=output_dir)
    assert os.environ.get("PY2FL_SOUNDFONT") == str(fake_sf)
    assert os.environ.get("PY2FL_FLUIDSYNTH") == str(fake_bin)


def test_autodetect_does_not_overwrite_explicit_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    output_dir = project / "exports"
    output_dir.mkdir(parents=True)
    (project / "soundfonts").mkdir()
    auto_sf = project / "soundfonts" / "auto.sf3"
    auto_sf.write_bytes(b"RIFF")
    explicit_sf = tmp_path / "explicit.sf3"
    explicit_sf.write_bytes(b"RIFF")

    monkeypatch.setenv("PY2FL_SOUNDFONT", str(explicit_sf))
    Py2FLWebApp(output_dir=output_dir)
    assert os.environ.get("PY2FL_SOUNDFONT") == str(explicit_sf)


def test_save_rejects_empty_key(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)
    captured = _post(app, "/settings/save", {"gemini_api_key": "", "persist": "1"})
    assert captured["status"].startswith("400")
