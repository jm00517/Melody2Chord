import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from py2fl import llm
from py2fl.llm import (
    LEVEL_CONTROLS,
    LEVEL_OPTIONS,
    Suggestion,
    _coerce_fields,
    is_available,
    resolve_api_key,
    suggest_from_text,
)


def test_resolve_api_key_prefers_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert resolve_api_key("explicit") == "explicit"
    assert resolve_api_key(None) == "from-env"


def test_resolve_api_key_fallback_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-only")
    assert resolve_api_key(None) == "google-only"


def test_is_available_false_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert is_available() is False


def test_suggest_falls_back_to_rules_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    suggestion = suggest_from_text("dark trap anthem with hard 808s")
    assert suggestion.source == "rule"
    assert suggestion.fields.get("genre") == "trap"
    assert suggestion.fields.get("swing") == "low"


def test_suggest_empty_prompt() -> None:
    suggestion = suggest_from_text("   ")
    assert suggestion.source == "rule"
    assert suggestion.fields == {}


def test_coerce_fields_filters_invalid_values() -> None:
    raw = {
        "tempo": 999,
        "bars": "16",
        "key": "F#",
        "genre": "trap",
        "chord_density": "5",
        "melody_density": "dense",
        "chord_rhythm_style": "BAD",
        "humanize": "med",
        "swing": "off",
        "drum_dynamics": "high",
        "harmony_spice": "low",
        "section_dynamics": "auto",
        "modulate": "off",
    }
    fields = _coerce_fields(raw)
    assert "tempo" not in fields
    assert fields["bars"] == 16
    assert fields["key"] == "F#"
    assert fields["genre"] == "trap"
    assert "chord_density" not in fields
    assert fields["melody_density"] == "dense"
    assert "chord_rhythm_style" not in fields
    for control in LEVEL_CONTROLS:
        assert fields[control] in LEVEL_OPTIONS


def test_suggest_with_mocked_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_response = {
        "candidates": [{
            "content": {"parts": [{"text": json.dumps({
                "fields": {
                    "tempo": 92,
                    "bars": 8,
                    "key": "A minor",
                    "genre": "rnb",
                    "humanize": "med",
                    "swing": "low",
                    "drum_dynamics": "high",
                    "harmony_spice": "med",
                    "section_dynamics": "high",
                    "modulate": "med",
                    "chord_density": "2",
                    "melody_density": "normal",
                    "chord_rhythm_style": "hold",
                },
                "rationale": "smooth rnb groove",
            })}]}
        }]
    }

    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("py2fl.llm.urllib.request.urlopen", return_value=fake_resp) as mocked:
        suggestion = suggest_from_text("dreamy rnb night drive at midnight")

    assert suggestion.source == "llm"
    assert suggestion.fields["tempo"] == 92
    assert suggestion.fields["genre"] == "rnb"
    assert suggestion.fields["humanize"] == "med"
    assert suggestion.rationale == "smooth rnb groove"
    assert mocked.called


def test_suggest_falls_back_when_gemini_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    err = urllib.error.HTTPError(
        url="https://example",
        code=429,
        msg="rate limited",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"too many requests"}'),
    )
    with patch("py2fl.llm.urllib.request.urlopen", side_effect=err):
        suggestion = suggest_from_text("dark trap anthem")

    assert suggestion.source == "rule"
    assert suggestion.error and "429" in suggestion.error
    assert suggestion.fields.get("genre") == "trap"


def test_web_suggest_route_fills_form_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import urlencode

    from py2fl.web import Py2FLWebApp

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)

    body = urlencode({"text": "dark trap anthem with hard 808s", "count": "4"}).encode()
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/llm/suggest",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    chunks = list(app(environ, start_response))
    assert captured["status"].startswith("200")
    page = b"".join(chunks).decode("utf-8")
    assert "From Library" in page or "Source: rule" in page
    assert "trap" in page


@pytest.mark.skipif(
    resolve_api_key() is None,
    reason="GEMINI_API_KEY required for live LLM call",
)
def test_live_gemini_call() -> None:
    suggestion = suggest_from_text("ethereal dreamy ambient at sunrise, slow tempo")
    assert suggestion.source == "llm"
    assert suggestion.fields, "live LLM call should return at least one field"
