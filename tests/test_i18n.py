import io
from pathlib import Path
from urllib.parse import urlencode

import pytest

from py2fl.i18n import STRINGS, lang_from_environ, normalize_lang, t
from py2fl.web import Py2FLWebApp


def test_translate_falls_back_to_english_for_missing_key() -> None:
    assert t("nonexistent_key_xyz", "ko") == "nonexistent_key_xyz"


def test_korean_strings_cover_every_english_key() -> None:
    en_keys = set(STRINGS["en"].keys())
    ko_keys = set(STRINGS["ko"].keys())
    missing = en_keys - ko_keys
    assert not missing, f"Korean translation missing: {missing}"


def test_lang_from_environ_uses_cookie() -> None:
    assert lang_from_environ({"HTTP_COOKIE": "py2fl_lang=ko"}) == "ko"
    assert lang_from_environ({"HTTP_COOKIE": "py2fl_lang=en"}) == "en"


def test_lang_from_environ_uses_query() -> None:
    assert lang_from_environ({"QUERY_STRING": "lang=ko"}) == "ko"


def test_lang_from_environ_defaults_to_english() -> None:
    assert lang_from_environ({}) == "en"
    assert lang_from_environ({"HTTP_COOKIE": "py2fl_lang=fr"}) == "en"


def test_normalize_lang_rejects_unknown() -> None:
    assert normalize_lang("ko") == "ko"
    assert normalize_lang("zh") == "en"
    assert normalize_lang(None) == "en"


def test_main_page_renders_korean(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)

    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/",
        "QUERY_STRING": "",
        "HTTP_COOKIE": "py2fl_lang=ko",
    }
    chunks = list(app(environ, start_response))
    page = b"".join(chunks).decode("utf-8")
    assert captured["status"].startswith("200")
    assert "후보 생성" in page
    assert "텍스트로부터 추천" in page
    assert "라이브러리" in page


def test_main_page_default_is_english(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)

    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    chunks = list(app({"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": ""}, start_response))
    page = b"".join(chunks).decode("utf-8")
    assert "Create Candidate Set" in page
    assert "Suggest from Text" in page


def test_lang_toggle_sets_cookie(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)

    body = urlencode({"lang": "ko", "return_to": "/"}).encode()
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/lang",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    list(app(environ, start_response))
    assert captured["status"].startswith("303")
    set_cookie = next((v for k, v in captured["headers"] if k == "Set-Cookie"), "")
    assert "py2fl_lang=ko" in set_cookie
    location = next((v for k, v in captured["headers"] if k == "Location"), "")
    assert location == "/"


def test_lang_toggle_rejects_external_redirect(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    app = Py2FLWebApp(output_dir=output_dir)

    body = urlencode({"lang": "ko", "return_to": "https://evil.example.com"}).encode()
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/lang",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    list(app(environ, start_response))
    location = next((v for k, v in captured["headers"] if k == "Location"), "")
    assert location == "/"
