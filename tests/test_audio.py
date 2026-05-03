import os
from pathlib import Path

import pytest

from py2fl import audio
from py2fl.audio import (
    AudioRenderResult,
    FluidsynthMissing,
    SoundFontMissing,
    is_available,
    preview_wav_path,
    render_candidate,
    resolve_fluidsynth_binary,
    resolve_soundfont,
)
from py2fl.generator import generate_song
from py2fl.models import GenerationRequest


def test_resolve_soundfont_returns_none_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PY2FL_SOUNDFONT", raising=False)
    assert resolve_soundfont(None) is None
    assert resolve_soundfont(tmp_path / "nope.sf2") is None


def test_resolve_soundfont_uses_explicit_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PY2FL_SOUNDFONT", raising=False)
    fake = tmp_path / "fake.sf2"
    fake.write_bytes(b"RIFF")
    assert resolve_soundfont(fake) == fake


def test_resolve_soundfont_reads_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "fake.sf2"
    fake.write_bytes(b"RIFF")
    monkeypatch.setenv("PY2FL_SOUNDFONT", str(fake))
    assert resolve_soundfont(None) == fake


def test_render_candidate_raises_when_soundfont_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PY2FL_SOUNDFONT", raising=False)
    result = generate_song(GenerationRequest(text="dark trap", bars=4, seed=5, output_dir=tmp_path / "exports"))
    with pytest.raises(SoundFontMissing):
        render_candidate(result.output_dir, soundfont=None)


def test_render_candidate_raises_when_fluidsynth_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sf2 = tmp_path / "fake.sf2"
    fake_sf2.write_bytes(b"RIFF")
    monkeypatch.delenv("PY2FL_FLUIDSYNTH", raising=False)
    monkeypatch.setattr(audio, "resolve_fluidsynth_binary", lambda explicit=None: None)
    result = generate_song(GenerationRequest(text="dark trap", bars=4, seed=5, output_dir=tmp_path / "exports"))
    with pytest.raises(FluidsynthMissing):
        render_candidate(result.output_dir, soundfont=fake_sf2)


def test_is_available_false_without_soundfont(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PY2FL_SOUNDFONT", raising=False)
    assert is_available(None, None) is False


def test_preview_wav_path_layout(tmp_path: Path) -> None:
    wav = preview_wav_path(tmp_path / "candidate", "melody.mid")
    assert wav == tmp_path / "candidate" / "preview" / "melody.wav"


def test_web_preview_render_invokes_audio_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    from urllib.parse import urlencode

    from py2fl import audio as audio_module
    from py2fl.generator import generate_song
    from py2fl.web import Py2FLWebApp

    import py2fl.web as web_module

    fake_sf2 = tmp_path / "fake.sf2"
    fake_sf2.write_bytes(b"RIFF")
    monkeypatch.setenv("PY2FL_SOUNDFONT", str(fake_sf2))
    monkeypatch.setattr(audio_module, "resolve_fluidsynth_binary", lambda explicit=None: "fluidsynth")
    monkeypatch.setattr(web_module, "resolve_fluidsynth_binary", lambda explicit=None: "fluidsynth")

    output_dir = tmp_path / "exports"
    result = generate_song(GenerationRequest(text="dreamy rnb", bars=4, seed=4, output_dir=output_dir))

    calls: dict = {}

    def fake_render(candidate_dir, soundfont=None, fluidsynth_binary=None, *, force=False, **kw):
        calls["candidate_dir"] = Path(candidate_dir)
        calls["soundfont"] = soundfont
        (Path(candidate_dir) / "preview").mkdir(exist_ok=True)
        (Path(candidate_dir) / "preview" / "full_arrangement.wav").write_bytes(b"WAV")

    monkeypatch.setattr(web_module, "render_candidate", fake_render)

    app = Py2FLWebApp(output_dir=output_dir)
    body = urlencode({
        "candidate_dir": str(result.output_dir),
        "return_to": "/",
    }).encode()
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/preview/render",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    list(app(environ, start_response))
    assert captured["status"].startswith("303")
    assert captured["headers"]["Location"] == "/"
    assert calls["candidate_dir"] == result.output_dir.resolve()


@pytest.mark.skipif(
    resolve_fluidsynth_binary() is None or resolve_soundfont() is None,
    reason="fluidsynth + PY2FL_SOUNDFONT required for live audio render",
)
def test_render_candidate_produces_wavs(tmp_path: Path) -> None:
    result = generate_song(GenerationRequest(text="dreamy rnb", bars=4, seed=9, output_dir=tmp_path / "exports"))
    render_result = render_candidate(result.output_dir)
    assert isinstance(render_result, AudioRenderResult)
    assert (result.output_dir / "preview" / "full_arrangement.wav").is_file()
    assert (result.output_dir / "preview" / "melody.wav").is_file()
    second = render_candidate(result.output_dir)
    assert second.cache_hits, "second render should use cache"
