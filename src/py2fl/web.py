from __future__ import annotations

import cgi
import html
import json
import mimetypes
import os
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote
import uuid
from wsgiref.simple_server import make_server

from . import audio as audio_module
from . import settings as settings_module
from .i18n import (
    COOKIE_NAME as LANG_COOKIE_NAME,
    SUPPORTED_LANGS,
    lang_from_environ,
    normalize_lang,
    t as translate,
)
from .audio import (
    FluidsynthMissing,
    PREVIEW_DIRNAME,
    SoundFontMissing,
    is_available as audio_is_available,
    preview_wav_path,
    render_candidate,
    resolve_fluidsynth_binary,
    resolve_soundfont,
)
from . import llm as llm_module
from .generator import BATCH_META_FILENAME, generate_candidates, load_batch_meta, reroll_candidate_bar, select_candidate, set_candidate_bar_chord
from .llm import is_available as llm_is_available, suggest_from_text
from .library import (
    CONTROL_KEYS as LIBRARY_CONTROL_KEYS,
    delete_entry as library_delete_entry,
    entry_dir as library_entry_dir,
    get_entry as library_get_entry,
    list_entries as library_list_entries,
    save_candidate as library_save_candidate,
)
from .models import GenerationRequest, PPQ

TITLE = "py2fl Studio"
TRACK_NAMES = ("Melody", "Chords", "Bass", "Drums")
TRACK_FILE_NAMES = ("melody.mid", "chords.mid", "bass.mid", "drums.mid", "full_arrangement.mid")


class Py2FLWebApp:
    def __init__(
        self,
        output_dir: Path,
        library_dir: Path | None = None,
        soundfont: Path | str | None = None,
        fluidsynth_binary: str | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.library_dir = Path(library_dir) if library_dir is not None else self.output_dir.parent / "library"
        self._soundfont_explicit = soundfont
        self._fluidsynth_explicit = fluidsynth_binary
        if soundfont is not None:
            sf_path = Path(soundfont).expanduser()
            if sf_path.is_file():
                os.environ.setdefault(audio_module.ENV_SOUNDFONT, str(sf_path))
        if fluidsynth_binary is not None:
            os.environ.setdefault(audio_module.ENV_FLUIDSYNTH, fluidsynth_binary)
        settings_module.apply_to_environment()
        self._autodetect_audio_paths()
        self._current_lang = "en"

    def _autodetect_audio_paths(self) -> None:
        """Look for a SoundFont and fluidsynth binary inside the project tree.

        Only fills env vars that are still empty after explicit settings and
        config-file values are applied — user choice always wins.
        """
        try:
            project_root = self.output_dir.resolve().parent
        except OSError:
            return
        if not os.environ.get(audio_module.ENV_SOUNDFONT):
            sf_dir = project_root / "soundfonts"
            if sf_dir.is_dir():
                for pattern in ("*.sf2", "*.sf3"):
                    hits = sorted(sf_dir.glob(pattern))
                    if hits:
                        os.environ[audio_module.ENV_SOUNDFONT] = str(hits[0])
                        break
        if not os.environ.get(audio_module.ENV_FLUIDSYNTH) and not resolve_fluidsynth_binary():
            tools_dir = project_root / "tools"
            if tools_dir.is_dir():
                for candidate in tools_dir.rglob("fluidsynth.exe"):
                    if candidate.is_file():
                        os.environ[audio_module.ENV_FLUIDSYNTH] = str(candidate)
                        return
                for candidate in tools_dir.rglob("fluidsynth"):
                    if candidate.is_file():
                        os.environ[audio_module.ENV_FLUIDSYNTH] = str(candidate)
                        return

    def t(self, key: str) -> str:
        return translate(key, self._current_lang)

    def _resolved_soundfont(self) -> Path | None:
        return resolve_soundfont(self._soundfont_explicit)

    def _resolved_fluidsynth(self) -> str | None:
        return resolve_fluidsynth_binary(self._fluidsynth_explicit)

    def _audio_ready(self) -> bool:
        return self._resolved_soundfont() is not None and self._resolved_fluidsynth() is not None

    def __call__(self, environ: dict, start_response: Callable):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        self._current_lang = lang_from_environ(environ)

        if method == "POST" and path == "/lang":
            return self._handle_lang_toggle(environ, start_response)

        if method == "GET" and path == "/":
            return self._respond_html(start_response, "200 OK", self._render_page())

        if method == "GET" and path == "/melody-from-chords":
            return self._respond_html(start_response, "200 OK", self._render_chords_page())

        if method == "GET" and path == "/files":
            return self._serve_file(environ, start_response)

        if method == "POST" and path == "/generate":
            try:
                body = self._handle_generate(environ)
                return self._respond_html(start_response, "200 OK", body)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_page(error=str(exc)))

        if method == "POST" and path == "/generate-chords":
            try:
                body = self._handle_generate_chords(environ)
                return self._respond_html(start_response, "200 OK", body)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_chords_page(error=str(exc)))

        if method == "POST" and path == "/select":
            try:
                body = self._handle_select(environ)
                return self._respond_html(start_response, "200 OK", body)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_page(error=str(exc)))

        if method == "POST" and path == "/reroll-bar":
            try:
                body = self._handle_reroll_bar(environ)
                return self._respond_html(start_response, "200 OK", body)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_page(error=str(exc)))

        if method == "POST" and path == "/timeline/chord":
            try:
                body = self._handle_set_bar_chord(environ)
                return self._respond_html(start_response, "200 OK", body)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_page(error=str(exc)))

        if method == "GET" and path == "/library":
            return self._respond_html(start_response, "200 OK", self._render_library_page(environ))

        if method == "GET" and path.startswith("/library/"):
            entry_id = path[len("/library/"):]
            return self._respond_html(start_response, "200 OK", self._render_library_entry_page(entry_id))

        if method == "POST" and path == "/library/save":
            try:
                return self._handle_library_save(environ, start_response)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_page(error=str(exc)))

        if method == "POST" and path == "/library/continue":
            try:
                return self._handle_library_continue(environ, start_response)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_library_page(environ, error=str(exc)))

        if method == "POST" and path == "/library/delete":
            try:
                return self._handle_library_delete(environ, start_response)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_library_page(environ, error=str(exc)))

        if method == "POST" and path == "/preview/render":
            try:
                return self._handle_preview_render(environ, start_response)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_page(error=str(exc)))

        if method == "POST" and path == "/llm/suggest":
            try:
                body = self._handle_llm_suggest(environ)
                return self._respond_html(start_response, "200 OK", body)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_page(error=str(exc)))

        if method == "GET" and path == "/settings":
            return self._respond_html(start_response, "200 OK", self._render_settings_page(environ=environ))

        if method == "POST" and path == "/settings/save":
            try:
                return self._handle_settings_save(environ, start_response)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_settings_page(error=str(exc)))

        if method == "POST" and path == "/settings/clear":
            try:
                return self._handle_settings_clear(environ, start_response)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_settings_page(error=str(exc)))

        if method == "POST" and path == "/settings/audio":
            try:
                return self._handle_settings_audio_save(environ, start_response)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_settings_page(error=str(exc)))

        if method == "POST" and path == "/settings/audio/clear":
            try:
                return self._handle_settings_audio_clear(environ, start_response)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_settings_page(error=str(exc)))

        if method == "POST" and path == "/melody/analyze":
            try:
                return self._handle_melody_analyze(environ, start_response)
            except Exception as exc:
                return self._respond_json(start_response, "400 Bad Request", {"error": str(exc)})

        if method == "POST" and path == "/llm/suggest-chords":
            try:
                body = self._handle_llm_suggest(environ, chords_mode=True)
                return self._respond_html(start_response, "200 OK", body)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_chords_page(error=str(exc)))

        return self._respond_html(start_response, "404 Not Found", "<h1>Not Found</h1>")

    def _handle_generate(self, environ: dict) -> str:
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        text = _optional_text(form.getfirst("text"))
        tempo = _optional_int(form.getfirst("tempo"))
        key = _optional_text(form.getfirst("key"))
        genre = _optional_text(form.getfirst("genre"))
        bars = _optional_int(form.getfirst("bars"))
        chord_density = _normalize_auto_option(form.getfirst("chord_density"))
        melody_density = _normalize_auto_option(form.getfirst("melody_density"))
        chord_rhythm_style = _normalize_auto_option(form.getfirst("chord_rhythm_style"))
        humanize = _normalize_humanize_option(form.getfirst("humanize"))
        swing = _normalize_humanize_option(form.getfirst("swing"))
        drum_dynamics = _normalize_humanize_option(form.getfirst("drum_dynamics"))
        harmony_spice = _normalize_humanize_option(form.getfirst("harmony_spice"))
        section_dynamics = _normalize_humanize_option(form.getfirst("section_dynamics"))
        modulate = _normalize_humanize_option(form.getfirst("modulate"))
        seed = _optional_int(form.getfirst("seed"))
        melody_offset_beats = _optional_float(form.getfirst("melody_offset_beats")) or 0.0
        count = _optional_int(form.getfirst("count")) or 4
        count = max(1, min(count, 8))
        reroll_scope = _optional_text(form.getfirst("reroll_scope")) or "all"
        seed_offset = _optional_int(form.getfirst("seed_offset")) or 0

        upload_root = self.output_dir / ".uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        melody_path = _resolve_melody_path(form, upload_root)

        if not text and melody_path is None:
            raise ValueError("Enter text, a melody MIDI file, or both.")

        request = GenerationRequest(
            text=text,
            melody_midi_path=melody_path,
            tempo=tempo,
            key=key,
            genre=genre,
            bars=bars,
            chord_density=chord_density,
            melody_density=melody_density,
            chord_rhythm_style=chord_rhythm_style,
            humanize=humanize,
            swing=swing,
            drum_dynamics=drum_dynamics,
            harmony_spice=harmony_spice,
            section_dynamics=section_dynamics,
            modulate=modulate,
            seed=seed,
            output_dir=self.output_dir,
            melody_offset_beats=melody_offset_beats,
        )
        candidates = generate_candidates(request, count=count, reroll_scope=reroll_scope, seed_offset=seed_offset)
        batch_dir = candidates[0].output_dir.parent if candidates else None
        batch_meta = load_batch_meta(batch_dir) if batch_dir else None
        return self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_request(request, count))

    def _handle_generate_chords(self, environ: dict) -> str:
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        progression = _optional_text(form.getfirst("chord_progression"))
        text_value = _optional_text(form.getfirst("text"))
        tempo = _optional_int(form.getfirst("tempo"))
        key = _optional_text(form.getfirst("key"))
        genre = _optional_text(form.getfirst("genre"))
        bars = _optional_int(form.getfirst("bars"))
        chord_density = _normalize_auto_option(form.getfirst("chord_density"))
        melody_density = _normalize_auto_option(form.getfirst("melody_density"))
        chord_rhythm_style = _normalize_auto_option(form.getfirst("chord_rhythm_style"))
        humanize = _normalize_humanize_option(form.getfirst("humanize"))
        swing = _normalize_humanize_option(form.getfirst("swing"))
        drum_dynamics = _normalize_humanize_option(form.getfirst("drum_dynamics"))
        harmony_spice = _normalize_humanize_option(form.getfirst("harmony_spice"))
        section_dynamics = _normalize_humanize_option(form.getfirst("section_dynamics"))
        modulate = _normalize_humanize_option(form.getfirst("modulate"))
        seed = _optional_int(form.getfirst("seed"))
        count = _optional_int(form.getfirst("count")) or 4
        count = max(1, min(count, 8))
        reroll_scope = _optional_text(form.getfirst("reroll_scope")) or "all"
        seed_offset = _optional_int(form.getfirst("seed_offset")) or 0

        if not progression:
            raise ValueError("Enter a chord progression like 1-5-6-4 or Am-F-C-G.")

        request = GenerationRequest(
            text=text_value,
            chord_progression=progression,
            tempo=tempo,
            key=key,
            genre=genre,
            bars=bars,
            chord_density=chord_density,
            melody_density=melody_density,
            chord_rhythm_style=chord_rhythm_style,
            humanize=humanize,
            swing=swing,
            drum_dynamics=drum_dynamics,
            harmony_spice=harmony_spice,
            section_dynamics=section_dynamics,
            modulate=modulate,
            seed=seed,
            output_dir=self.output_dir,
        )
        candidates = generate_candidates(request, count=count, reroll_scope=reroll_scope, seed_offset=seed_offset)
        batch_dir = candidates[0].output_dir.parent if candidates else None
        batch_meta = load_batch_meta(batch_dir) if batch_dir else None
        return self._render_chords_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_chords_request(request, count))

    def _handle_select(self, environ: dict) -> str:
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        batch_dir_value = _optional_text(form.getfirst("batch_dir"))
        candidate_index = _optional_int(form.getfirst("candidate_index"))
        if not batch_dir_value or candidate_index is None:
            raise ValueError("batch_dir and candidate_index are required")

        batch_dir = self._resolve_under_output(Path(batch_dir_value))
        batch_meta = select_candidate(batch_dir, candidate_index)
        candidates = _load_candidate_results_from_batch(batch_meta)
        form_state = {
            "text": _string_value(batch_meta.get("text")),
            "tempo": _string_value(batch_meta.get("tempo")),
            "key": _string_value(batch_meta.get("key")),
            "genre": _string_value(batch_meta.get("genre")),
            "bars": _string_value(batch_meta.get("bars")),
            "chord_density": _string_value(batch_meta.get("chord_density")) or "auto",
            "melody_density": _string_value(batch_meta.get("melody_density")) or "auto",
            "chord_rhythm_style": _string_value(batch_meta.get("chord_rhythm_style")) or "auto",
            "humanize": _string_value(batch_meta.get("humanize")) or "off",
        "swing": _string_value(batch_meta.get("swing")) or "off",
        "drum_dynamics": _string_value(batch_meta.get("drum_dynamics")) or "off",
        "harmony_spice": _string_value(batch_meta.get("harmony_spice")) or "off",
        "section_dynamics": _string_value(batch_meta.get("section_dynamics")) or "off",
        "modulate": _string_value(batch_meta.get("modulate")) or "off",
            "seed": _string_value(batch_meta.get("seed")),
            "count": _string_value(batch_meta.get("candidate_count")) or str(len(candidates)),
            "melody_source": _string_value(batch_meta.get("source_melody")),
            "melody_offset_beats": _format_offset_beats(float(batch_meta.get("melody_offset_beats") or 0.0)),
        }
        if _is_chords_batch(batch_meta):
            return self._render_chords_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_batch_chords(batch_meta, len(candidates)))
        return self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=form_state)


    def _handle_set_bar_chord(self, environ: dict) -> str:
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        batch_dir_value = _optional_text(form.getfirst("batch_dir"))
        candidate_index = _optional_int(form.getfirst("candidate_index"))
        bar_index = _optional_int(form.getfirst("bar_index"))
        chord_token = _optional_text(form.getfirst("chord")) or ""
        reroll_nonce = _optional_int(form.getfirst("reroll_nonce")) or 0
        fragment = form.getfirst("fragment") == "1"
        if not batch_dir_value or candidate_index is None or bar_index is None or not chord_token:
            raise ValueError("batch_dir, candidate_index, bar_index, and chord are required")
        batch_dir = self._resolve_under_output(Path(batch_dir_value))
        batch_meta = set_candidate_bar_chord(batch_dir, candidate_index, bar_index, chord_token, reroll_nonce=reroll_nonce)
        candidates = _load_candidate_results_from_batch(batch_meta)
        if fragment:
            return self._render_reroll_bar_fragment(candidates, batch_meta, candidate_index, bar_index)
        if _is_chords_batch(batch_meta):
            return self._render_chords_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_batch_chords(batch_meta, len(candidates)))
        return self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_batch_meta(batch_meta, len(candidates)))


    def _handle_reroll_bar(self, environ: dict) -> str:
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        batch_dir_value = _optional_text(form.getfirst("batch_dir"))
        candidate_index = _optional_int(form.getfirst("candidate_index"))
        bar_index = _optional_int(form.getfirst("bar_index"))
        reroll_nonce = _optional_int(form.getfirst("reroll_nonce")) or 0
        chord_density_override = _normalize_bar_density_option(form.getfirst("bar_chord_density"))
        fragment = form.getfirst("fragment") == "1"
        if not batch_dir_value or candidate_index is None or bar_index is None:
            raise ValueError("batch_dir, candidate_index, and bar_index are required")

        batch_dir = self._resolve_under_output(Path(batch_dir_value))
        batch_meta = reroll_candidate_bar(batch_dir, candidate_index, bar_index, reroll_nonce=reroll_nonce, chord_density_override=chord_density_override)
        candidates = _load_candidate_results_from_batch(batch_meta)
        if fragment:
            return self._render_reroll_bar_fragment(candidates, batch_meta, candidate_index, bar_index)
        form_state = {
            "text": _string_value(batch_meta.get("text")),
            "tempo": _string_value(batch_meta.get("tempo")),
            "key": _string_value(batch_meta.get("key")),
            "genre": _string_value(batch_meta.get("genre")),
            "bars": _string_value(batch_meta.get("bars")),
            "chord_density": _string_value(batch_meta.get("chord_density")) or "auto",
            "melody_density": _string_value(batch_meta.get("melody_density")) or "auto",
            "chord_rhythm_style": _string_value(batch_meta.get("chord_rhythm_style")) or "auto",
            "humanize": _string_value(batch_meta.get("humanize")) or "off",
        "swing": _string_value(batch_meta.get("swing")) or "off",
        "drum_dynamics": _string_value(batch_meta.get("drum_dynamics")) or "off",
        "harmony_spice": _string_value(batch_meta.get("harmony_spice")) or "off",
        "section_dynamics": _string_value(batch_meta.get("section_dynamics")) or "off",
        "modulate": _string_value(batch_meta.get("modulate")) or "off",
            "seed": _string_value(batch_meta.get("seed")),
            "count": _string_value(batch_meta.get("candidate_count")) or str(len(candidates)),
            "melody_source": _string_value(batch_meta.get("source_melody")),
            "melody_offset_beats": _format_offset_beats(float(batch_meta.get("melody_offset_beats") or 0.0)),
        }
        if _is_chords_batch(batch_meta):
            return self._render_chords_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_batch_chords(batch_meta, len(candidates)))
        return self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=form_state)


    def _handle_library_save(self, environ: dict, start_response: Callable):
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        batch_dir_value = _optional_text(form.getfirst("batch_dir"))
        candidate_index = _optional_int(form.getfirst("candidate_index"))
        name = _optional_text(form.getfirst("name")) or ""
        if not batch_dir_value or candidate_index is None:
            raise ValueError("batch_dir and candidate_index are required")

        batch_dir = self._resolve_under_output(Path(batch_dir_value))
        candidate_dir = batch_dir / f"option_{candidate_index:02d}"
        if not candidate_dir.is_dir():
            candidate_meta = next(
                (item for item in load_batch_meta(batch_dir).get("candidates", []) if int(item.get("candidate_index") or 0) == candidate_index),
                None,
            )
            if candidate_meta and candidate_meta.get("output_dir"):
                candidate_dir = self._resolve_under_output(Path(str(candidate_meta["output_dir"])))
        candidate_dir = self._resolve_under_output(candidate_dir)
        library_save_candidate(candidate_dir, name, self.library_dir)
        return self._redirect(start_response, "/library")

    def _handle_library_continue(self, environ: dict, start_response: Callable):
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        entry_id = _optional_text(form.getfirst("entry_id"))
        if not entry_id:
            raise ValueError("entry_id is required")
        entry = library_get_entry(entry_id, self.library_dir)
        if entry is None:
            raise ValueError(f"library entry not found: {entry_id}")
        state = _state_from_library_entry(entry)
        info_text = self.t("lib_loaded_message").format(name=entry.get("name") or entry_id)
        if entry.get("ui_mode") == "melody_from_chords":
            body = self._render_chords_page(form_state=state, info=info_text)
        else:
            body = self._render_page(form_state=state, info=info_text)
        return self._respond_html(start_response, "200 OK", body)

    def _handle_library_delete(self, environ: dict, start_response: Callable):
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        entry_id = _optional_text(form.getfirst("entry_id"))
        if not entry_id:
            raise ValueError("entry_id is required")
        library_delete_entry(entry_id, self.library_dir)
        return self._redirect(start_response, "/library")

    def _handle_settings_save(self, environ: dict, start_response: Callable):
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        api_key = _optional_text(form.getfirst("gemini_api_key")) or ""
        persist = form.getfirst("persist") == "1"
        if not api_key:
            raise ValueError("Enter a Gemini API key.")
        os.environ["GEMINI_API_KEY"] = api_key
        if persist:
            settings_module.save_config({settings_module.KEY_GEMINI_API_KEY: api_key})
        return self._redirect(start_response, "/settings?saved=1")

    def _handle_settings_clear(self, environ: dict, start_response: Callable):
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        settings_module.clear_config_key(settings_module.KEY_GEMINI_API_KEY)
        return self._redirect(start_response, "/settings?cleared=1")

    def _handle_settings_audio_save(self, environ: dict, start_response: Callable):
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        sf2_input = _optional_text(form.getfirst("soundfont_path")) or ""
        fluid_input = _optional_text(form.getfirst("fluidsynth_path")) or ""
        if not sf2_input and not fluid_input:
            raise ValueError("Provide at least a SoundFont path.")
        updates: dict = {}
        if sf2_input:
            sf2_path = Path(sf2_input).expanduser()
            if not sf2_path.is_file():
                raise ValueError(f"SoundFont file not found: {sf2_path}")
            os.environ["PY2FL_SOUNDFONT"] = str(sf2_path)
            updates[settings_module.KEY_SOUNDFONT_PATH] = str(sf2_path)
        if fluid_input:
            os.environ["PY2FL_FLUIDSYNTH"] = fluid_input
            updates[settings_module.KEY_FLUIDSYNTH_PATH] = fluid_input
        if updates:
            settings_module.save_config(updates)
        return self._redirect(start_response, "/settings?audio_saved=1")

    def _handle_settings_audio_clear(self, environ: dict, start_response: Callable):
        os.environ.pop("PY2FL_SOUNDFONT", None)
        os.environ.pop("PY2FL_FLUIDSYNTH", None)
        settings_module.clear_config_key(settings_module.KEY_SOUNDFONT_PATH)
        settings_module.clear_config_key(settings_module.KEY_FLUIDSYNTH_PATH)
        return self._redirect(start_response, "/settings?audio_cleared=1")

    def _render_settings_page(self, error: str | None = None, environ: dict | None = None) -> str:
        query = parse_qs((environ or {}).get("QUERY_STRING", ""))
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        active_sf2 = self._resolved_soundfont()
        active_fluid = self._resolved_fluidsynth()
        persisted_sf2 = settings_module.load_config().get(settings_module.KEY_SOUNDFONT_PATH)
        persisted_fluid = settings_module.load_config().get(settings_module.KEY_FLUIDSYNTH_PATH)
        if active_sf2 is None:
            audio_status = self.t("settings_audio_status_missing_sf2")
        elif active_fluid is None:
            audio_status = self.t("settings_audio_status_missing_binary")
        else:
            audio_status = self.t("settings_audio_status_ready")
        sf2_display = str(active_sf2) if active_sf2 else self.t("settings_not_set")
        fluid_display = active_fluid or self.t("settings_not_set")
        audio_clear_form = ""
        if active_sf2 or active_fluid or persisted_sf2 or persisted_fluid:
            audio_clear_form = f"""
            <form method="post" action="/settings/audio/clear" onsubmit="return confirm('{self.t('settings_clear_confirm')}');" style="margin-top: 10px;">
              <button type="submit" class="btn danger">{html.escape(self.t('settings_btn_clear_paths'))}</button>
            </form>
            """
        audio_section_html = f"""
    <section class="panel">
      <h2>{html.escape(self.t('settings_section_soundfont'))}</h2>
      <p class="hint">{html.escape(self.t('settings_soundfont_hint'))}</p>
      <div class="status">
        <strong>{html.escape(self.t('settings_active_soundfont'))}:</strong> <code>{html.escape(sf2_display)}</code><br>
        <strong>{html.escape(self.t('settings_active_fluidsynth'))}:</strong> <code>{html.escape(fluid_display)}</code><br>
        <strong>Status:</strong> {html.escape(audio_status)}
      </div>
      <form method="post" action="/settings/audio" style="margin-top: 18px; display: grid; gap: 14px;">
        <label>
          {html.escape(self.t('settings_label_soundfont'))}
          <input type="text" name="soundfont_path" placeholder="{html.escape(self.t('settings_soundfont_placeholder'))}" value="{html.escape(str(persisted_sf2 or ''))}">
        </label>
        <label>
          {html.escape(self.t('settings_label_fluidsynth'))}
          <input type="text" name="fluidsynth_path" placeholder="{html.escape(self.t('settings_fluidsynth_placeholder'))}" value="{html.escape(str(persisted_fluid or ''))}">
        </label>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
          <button type="submit">{html.escape(self.t('settings_btn_save_paths'))}</button>
        </div>
      </form>
      {audio_clear_form}
    </section>"""
        masked = settings_module.mask_secret(env_key) if env_key else ""
        persisted = bool(settings_module.load_config().get(settings_module.KEY_GEMINI_API_KEY))
        config_path_text = str(settings_module.config_path())
        notice = ""
        if error:
            notice = f'<section class="panel error"><h2>Error</h2><p>{html.escape(error)}</p></section>'
        status_lines = []
        if env_key:
            status_lines.append(f"<strong>{html.escape(self.t('settings_active'))}:</strong> <code>{html.escape(masked)}</code>")
        else:
            status_lines.append(f"<strong>{html.escape(self.t('settings_active'))}:</strong> <em>{html.escape(self.t('settings_not_set'))}</em>")
        if persisted:
            status_lines.append(f"<strong>{html.escape(self.t('settings_disk'))}:</strong> {html.escape(self.t('settings_yes'))} — {html.escape(config_path_text)}")
        else:
            status_lines.append(f"<strong>{html.escape(self.t('settings_disk'))}:</strong> {html.escape(self.t('settings_no'))}")
        clear_form = ""
        if env_key or persisted:
            clear_form = f"""
            <form method="post" action="/settings/clear" onsubmit="return confirm('{self.t('settings_clear_confirm')}');" style="margin-top: 10px;">
              <button type="submit" class="btn danger">{html.escape(self.t('settings_btn_clear'))}</button>
            </form>
            """
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{TITLE} — Settings</title>
  <style>
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: #f1ede3; color: #1f1a14; min-height: 100vh; }}
    .shell {{ max-width: 760px; margin: 0 auto; padding: 32px 20px 64px; }}
    .panel {{ background: rgba(255,255,255,0.82); border: 1px solid rgba(31,26,20,0.15); border-radius: 24px; padding: 22px; box-shadow: 0 24px 60px rgba(73, 48, 25, 0.12); margin-bottom: 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 36px; }}
    label {{ display: grid; gap: 8px; font-size: 14px; color: #6d614e; }}
    input[type=password], input[type=text] {{ width: 100%; padding: 12px 14px; border-radius: 14px; border: 1px solid rgba(31,26,20,0.14); background: #fffaf0; font: inherit; box-sizing: border-box; }}
    input[type=checkbox] {{ margin-right: 6px; }}
    button, .btn {{ border: 0; border-radius: 999px; padding: 10px 18px; background: linear-gradient(135deg, #b24a2b, #d67b3d); color: white; font-size: 13px; font-weight: 700; cursor: pointer; font-family: inherit; }}
    .btn.danger {{ background: linear-gradient(135deg, #6b2018, #8a3324); }}
    .status {{ display: grid; gap: 6px; font-size: 14px; line-height: 1.6; }}
    .status code {{ background: rgba(178,74,43,0.08); padding: 2px 8px; border-radius: 6px; }}
    .topbar a {{ color: #7f2f18; text-decoration: none; font-weight: 700; }}
    .saved-banner {{ background: rgba(54, 91, 61, 0.18); color: #2e4a2e; border-radius: 12px; padding: 10px 14px; margin-bottom: 14px; }}
    .hint {{ color: #6d614e; font-size: 13px; line-height: 1.5; }}
    .hint a {{ color: #7f2f18; }}
  </style>
</head>
<body>
  <main class="shell">
    {_lang_toggle_html(self._current_lang, "/settings")}
    <div class="topbar"><a href="/">{html.escape(self.t('back_to_studio'))}</a></div>
    <h1>{html.escape(self.t('settings_heading'))}</h1>
    {self._settings_query_banner(query)}
    {notice}
    <section class="panel">
      <h2>{html.escape(self.t('settings_section_gemini'))}</h2>
      <p class="hint">{html.escape(self.t('settings_hint_pre'))}<code>{html.escape(self.t('btn_suggest'))}</code>{html.escape(self.t('settings_hint_mid'))}<a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener">aistudio.google.com/app/apikey</a>{html.escape(self.t('settings_hint_post'))}</p>
      <div class="status">{('<br>'.join(status_lines))}</div>
      <form method="post" action="/settings/save" style="margin-top: 18px; display: grid; gap: 14px;">
        <label>
          {html.escape(self.t('settings_label_apikey'))}
          <input type="password" name="gemini_api_key" placeholder="{html.escape(self.t('settings_apikey_placeholder'))}" autocomplete="off" required>
        </label>
        <label style="flex-direction: row; align-items: center;">
          <input type="checkbox" name="persist" value="1">
          {html.escape(self.t('settings_label_persist_pre'))}<code>{html.escape(config_path_text)}</code>{html.escape(self.t('settings_label_persist_post'))}
        </label>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
          <button type="submit">{html.escape(self.t('settings_btn_save'))}</button>
        </div>
      </form>
      {clear_form}
      <p class="hint" style="margin-top: 14px;">{html.escape(self.t('settings_security_note'))}</p>
    </section>
    {audio_section_html}
  </main>
</body>
</html>"""

    def _settings_query_banner(self, query: dict) -> str:
        if query.get("saved"):
            return f'<div class="saved-banner">{html.escape(self.t("settings_saved_banner"))}</div>'
        if query.get("cleared"):
            return f'<div class="saved-banner">{html.escape(self.t("settings_cleared_banner"))}</div>'
        if query.get("audio_saved"):
            return f'<div class="saved-banner">{html.escape(self.t("settings_saved_banner"))}</div>'
        if query.get("audio_cleared"):
            return f'<div class="saved-banner">{html.escape(self.t("settings_cleared_banner"))}</div>'
        return ""

    def _redirect(self, start_response: Callable, location: str):
        start_response("303 See Other", [("Location", location), ("Content-Length", "0")])
        return [b""]

    def _handle_melody_analyze(self, environ: dict, start_response: Callable):
        from .melody import analyze_melody_file
        from .music_theory import key_label

        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        upload_root = self.output_dir / ".uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        melody_path = _resolve_melody_path(form, upload_root)
        if melody_path is None:
            raise ValueError("Attach a melody MIDI file to analyze.")

        analysis = analyze_melody_file(melody_path)
        suggested_offset_beats = -round((analysis.source_start_offset_ticks / PPQ) * 4) / 4 if analysis.source_start_offset_ticks else 0.0
        payload = {
            "melody_source": str(melody_path),
            "tempo": analysis.tempo_bpm,
            "key": key_label(analysis.key, analysis.mode),
            "bars": analysis.bars,
            "phrase_length": analysis.phrase_length,
            "source_start_offset_ticks": analysis.source_start_offset_ticks,
            "suggested_offset_beats": suggested_offset_beats,
        }
        return self._respond_json(start_response, "200 OK", payload)

    @staticmethod
    def _respond_json(start_response: Callable, status: str, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))]
        start_response(status, headers)
        return [payload]

    def _handle_lang_toggle(self, environ: dict, start_response: Callable):
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        lang = normalize_lang(_optional_text(form.getfirst("lang")))
        return_to = _optional_text(form.getfirst("return_to")) or "/"
        if not return_to.startswith("/"):
            return_to = "/"
        cookie_value = f"{LANG_COOKIE_NAME}={lang}; Path=/; Max-Age=31536000; SameSite=Lax"
        start_response(
            "303 See Other",
            [("Location", return_to), ("Set-Cookie", cookie_value), ("Content-Length", "0")],
        )
        return [b""]

    def _handle_llm_suggest(self, environ: dict, chords_mode: bool = False) -> str:
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        text_value = _optional_text(form.getfirst("text")) or ""
        chord_progression = _optional_text(form.getfirst("chord_progression")) or ""
        if not text_value and not chord_progression:
            raise ValueError("Enter a text prompt before requesting a suggestion.")
        prompt = text_value
        if chord_progression and chords_mode:
            prompt = f"{text_value} (chord progression: {chord_progression})".strip()

        suggestion = suggest_from_text(prompt)

        state = _state_from_form(form, chords_mode=chords_mode)
        state = _apply_suggestion_to_state(state, suggestion.fields)

        notice_parts = [f"Source: {suggestion.source}"]
        if suggestion.rationale:
            notice_parts.append(suggestion.rationale)
        if suggestion.error:
            notice_parts.append(f"Note: {suggestion.error}")
        if not llm_is_available() and suggestion.source == "rule":
            notice_parts.append("Set GEMINI_API_KEY to enable LLM suggestions.")
        info = " · ".join(notice_parts)

        if chords_mode:
            return self._render_chords_page(form_state=state, info=info)
        return self._render_page(form_state=state, info=info)

    def _handle_preview_render(self, environ: dict, start_response: Callable):
        form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)
        candidate_dir_value = _optional_text(form.getfirst("candidate_dir"))
        return_to = _optional_text(form.getfirst("return_to")) or "/"
        force = form.getfirst("force") == "1"
        if not candidate_dir_value:
            raise ValueError("candidate_dir is required")
        candidate_dir = self._resolve_candidate_dir(Path(candidate_dir_value))
        sf2 = self._resolved_soundfont()
        if sf2 is None:
            raise SoundFontMissing("No SoundFont configured. Set PY2FL_SOUNDFONT or pass --soundfont when starting the server.")
        binary = self._resolved_fluidsynth()
        if binary is None:
            raise FluidsynthMissing("fluidsynth binary not found on PATH.")
        render_candidate(candidate_dir, soundfont=sf2, fluidsynth_binary=binary, force=force)

        if return_to.startswith("/library/"):
            return self._redirect(start_response, return_to)

        batch_dir = candidate_dir.parent
        batch_meta_path = batch_dir / BATCH_META_FILENAME
        if batch_meta_path.is_file():
            try:
                batch_meta = load_batch_meta(batch_dir)
                candidates = _load_candidate_results_from_batch(batch_meta)
                form_state = _state_from_batch_meta(batch_meta, len(candidates))
                if _is_chords_batch(batch_meta):
                    body = self._render_chords_page(candidates=candidates, batch_meta=batch_meta, form_state=form_state)
                else:
                    body = self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=form_state)
                return self._respond_html(start_response, "200 OK", body)
            except Exception:
                pass
        return self._redirect(start_response, return_to)

    def _resolve_candidate_dir(self, path: Path) -> Path:
        resolved = path.resolve(strict=False)
        output_root = self.output_dir.resolve(strict=False)
        library_root = self.library_dir.resolve(strict=False)
        if resolved == output_root or output_root in resolved.parents:
            return resolved
        if resolved == library_root or library_root in resolved.parents:
            return resolved
        raise ValueError("Access denied")

    def _render_library_page(self, environ: dict, error: str | None = None) -> str:
        entries = library_list_entries(self.library_dir)
        error_html = ""
        if error:
            error_html = f'<section class="panel error"><h2>Error</h2><p>{html.escape(error)}</p></section>'
        if not entries:
            rows_html = f'<section class="empty-state">{self.t("lib_empty")}</section>'
        else:
            rows = []
            for entry in entries:
                rows.append(_library_entry_row(entry, self))
            rows_html = '<section class="library-grid">' + "".join(rows) + "</section>"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{TITLE} — Library</title>
  <style>
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: #f1ede3; color: #1f1a14; min-height: 100vh; }}
    .shell {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1 {{ margin: 0 0 8px; font-size: 42px; }}
    .lead {{ color: #6d614e; max-width: 60ch; margin-bottom: 20px; }}
    .topbar {{ display: flex; justify-content: space-between; align-items: end; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }}
    .topbar a {{ color: #7f2f18; text-decoration: none; font-weight: 700; }}
    .panel {{ background: rgba(255,255,255,0.82); border: 1px solid rgba(31,26,20,0.15); border-radius: 24px; padding: 18px; box-shadow: 0 24px 60px rgba(73, 48, 25, 0.12); }}
    .empty-state {{ background: rgba(255,255,255,0.6); border: 1px dashed rgba(31,26,20,0.2); border-radius: 18px; padding: 36px 24px; color: #6d614e; text-align: center; }}
    .library-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .lib-card {{ display: grid; gap: 10px; padding: 18px; }}
    .lib-card h3 {{ margin: 0; font-size: 22px; }}
    .lib-meta {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 14px; color: #6d614e; font-size: 13px; }}
    .lib-meta strong {{ color: #1f1a14; font-size: 14px; }}
    .lib-tags {{ display: flex; gap: 6px; flex-wrap: wrap; font-size: 12px; }}
    .lib-tag {{ background: rgba(178,74,43,0.1); color: #7f2f18; border-radius: 999px; padding: 4px 10px; }}
    .lib-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .lib-actions form {{ display: block; margin: 0; }}
    button, .btn {{ border: 0; border-radius: 999px; padding: 10px 16px; background: linear-gradient(135deg, #b24a2b, #d67b3d); color: white; font-size: 13px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; font-family: inherit; }}
    .btn.ghost {{ background: rgba(178,74,43,0.08); color: #7f2f18; border: 1px solid rgba(178,74,43,0.2); }}
    .btn.danger {{ background: linear-gradient(135deg, #6b2018, #8a3324); }}
    .lib-prompt {{ font-size: 14px; line-height: 1.5; }}
    .error {{ border-color: rgba(178,74,43,0.3); background: rgba(255,238,229,0.92); }}
  </style>
</head>
<body>
  <main class="shell">
    {_lang_toggle_html(self._current_lang, "/library")}
    <div class="topbar">
      <div>
        <h1>{html.escape(self.t('lib_heading'))}</h1>
        <p class="lead">{html.escape(self.t('lib_lead_pre'))}<code>{html.escape(str(self.output_dir))}</code>{html.escape(self.t('lib_lead_post'))}</p>
      </div>
      <a href="/">{html.escape(self.t('back_to_studio'))}</a>
    </div>
    {error_html}
    {rows_html}
  </main>
</body>
</html>"""

    def _render_library_entry_page(self, entry_id: str) -> str:
        entry = library_get_entry(entry_id, self.library_dir)
        if entry is None:
            return f"""<!doctype html><html><body style="font-family: serif; padding: 40px;"><h1>Not found</h1><p>No library entry with id <code>{html.escape(entry_id)}</code>.</p><p><a href="/library">← Library</a></p></body></html>"""
        folder = library_entry_dir(entry_id, self.library_dir)
        preview_file = entry.get("preview_file") or "full_arrangement.mid"
        preview_path = folder / str(preview_file)
        preview_url = f"/files?path={quote(str(preview_path))}"
        files = sorted(p.name for p in folder.glob("*.mid"))
        files_html = "".join(f'<li><code>{html.escape(name)}</code> — <a href="/files?path={quote(str(folder / name))}" download>download</a></li>' for name in files)
        controls = entry.get("controls") or {}
        controls_html = "".join(
            f'<div class="meta-card"><span>{html.escape(key)}</span><strong>{html.escape(str(controls.get(key, "off")))}</strong></div>'
            for key in LIBRARY_CONTROL_KEYS
        )
        progression = entry.get("full_progression_text") or entry.get("progression_label") or "-"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{TITLE} — {html.escape(str(entry.get('name') or entry_id))}</title>
  <style>
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: #f1ede3; color: #1f1a14; min-height: 100vh; }}
    .shell {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1 {{ margin: 0 0 8px; font-size: 36px; }}
    .panel {{ background: rgba(255,255,255,0.82); border: 1px solid rgba(31,26,20,0.15); border-radius: 24px; padding: 22px; box-shadow: 0 24px 60px rgba(73, 48, 25, 0.12); margin-bottom: 18px; }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }}
    .meta-card {{ background: rgba(255,250,240,0.75); border: 1px solid rgba(31,26,20,0.12); border-radius: 16px; padding: 12px 14px; display: grid; gap: 4px; }}
    .meta-card span {{ color: #6d614e; font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; }}
    .meta-card strong {{ font-size: 16px; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    .actions form {{ margin: 0; }}
    button, .btn {{ border: 0; border-radius: 999px; padding: 10px 16px; background: linear-gradient(135deg, #b24a2b, #d67b3d); color: white; font-size: 13px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; font-family: inherit; }}
    .btn.ghost {{ background: rgba(178,74,43,0.08); color: #7f2f18; border: 1px solid rgba(178,74,43,0.2); }}
    .btn.danger {{ background: linear-gradient(135deg, #6b2018, #8a3324); }}
    audio {{ width: 100%; margin-top: 8px; }}
    code {{ font-family: ui-monospace, Menlo, monospace; font-size: 12px; }}
    .progression {{ font-size: 24px; line-height: 1.2; }}
    ul {{ padding-left: 18px; }}
    .audio-panel {{ margin-top: 14px; padding: 14px; border-radius: 16px; border: 1px solid rgba(31,26,20,0.12); background: rgba(255,250,240,0.7); display: grid; gap: 10px; }}
    .audio-panel h4 {{ margin: 0; font-size: 16px; }}
    .audio-stems {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .audio-stem {{ font-size: 12px; padding: 6px 10px; border-radius: 999px; background: rgba(178,74,43,0.1); color: #7f2f18; text-decoration: none; }}
    .hint {{ color: #6d614e; font-size: 13px; margin: 0; }}
  </style>
</head>
<body>
  <main class="shell">
    {_lang_toggle_html(self._current_lang, f"/library/{entry_id}")}
    <p><a href="/library">← {html.escape(self.t('lib_heading'))}</a></p>
    <section class="panel">
      <h1>{html.escape(str(entry.get('name') or entry_id))}</h1>
      <p class="progression">{html.escape(progression)}</p>
      <div class="meta-grid">
        <div class="meta-card"><span>{html.escape(self.t('lib_saved_at'))}</span><strong>{html.escape(str(entry.get('saved_at') or '-'))}</strong></div>
        <div class="meta-card"><span>{html.escape(self.t('lib_mode'))}</span><strong>{html.escape(str(entry.get('input_mode') or '-'))}</strong></div>
        <div class="meta-card"><span>{html.escape(self.t('label_tempo'))}</span><strong>{html.escape(str(entry.get('tempo') or '-'))}</strong></div>
        <div class="meta-card"><span>{html.escape(self.t('label_key'))}</span><strong>{html.escape(str(entry.get('key') or '-'))}</strong></div>
        <div class="meta-card"><span>{html.escape(self.t('label_bars'))}</span><strong>{html.escape(str(entry.get('bars') or '-'))}</strong></div>
        <div class="meta-card"><span>{html.escape(self.t('label_genre'))}</span><strong>{html.escape(str(entry.get('genre') or '-'))}</strong></div>
        <div class="meta-card"><span>{html.escape(self.t('label_seed'))}</span><strong>{html.escape(str(entry.get('candidate_seed') or '-'))}</strong></div>
      </div>
    </section>
    <section class="panel">
      <h2>{html.escape(self.t('lib_controls'))}</h2>
      <div class="meta-grid">{controls_html}</div>
    </section>
    <section class="panel">
      <h2>{html.escape(self.t('files_actions'))}</h2>
      <ul>{files_html}</ul>
      {_audio_preview_panel(folder, return_to=f"/library/{quote(entry_id)}", app=self)}
      <div class="actions">
        <form method="post" action="/library/continue">
          <input type="hidden" name="entry_id" value="{html.escape(entry_id)}">
          <button type="submit">{html.escape(self.t('lib_continue'))}</button>
        </form>
        <form method="post" action="/library/delete" onsubmit="return confirm('{self.t('lib_confirm_delete')}');">
          <input type="hidden" name="entry_id" value="{html.escape(entry_id)}">
          <button type="submit" class="btn danger">{html.escape(self.t('lib_delete'))}</button>
        </form>
      </div>
    </section>
  </main>
</body>
</html>"""

    def _render_reroll_bar_fragment(self, candidates: list, batch_meta: dict[str, object], candidate_index: int, bar_index: int) -> str:
        result = next((item for item in candidates if int(item.metadata.get("candidate_index") or 0) == candidate_index), None)
        if result is None:
            raise ValueError("Candidate not found for fragment render")
        meta = result.metadata
        preview_path = Path(result.output_dir) / str(meta.get("preview_file", "full_arrangement.mid"))
        preview_url = html.escape(f"/files?path={quote(str(preview_path))}")
        tempo = int(meta.get("tempo") or 120)
        bar_summary = meta.get("bar_summary", [])
        bar_data = next((bar for bar in bar_summary if int(bar.get("bar_index") or 0) == bar_index), None)
        if bar_data is None:
            raise ValueError("Bar not found for fragment render")
        active_index = _active_candidate_index(candidates, batch_meta)
        tab_html = _candidate_tab(result, active_index)
        progress_html = _candidate_progress_header(result, batch_meta)
        bar_html = _bar_card(bar_data, Path(result.output_dir).parent, candidate_index, preview_url, tempo, str(meta.get("bar_action_label", "Reroll Harmony")))
        return f"""<div data-fragment-root="reroll-bar">
  <div data-fragment="candidate-tab">{tab_html}</div>
  <div data-fragment="candidate-progress">{progress_html}</div>
  <div data-fragment="bar-card">{bar_html}</div>
</div>"""

    def _serve_file(self, environ: dict, start_response: Callable):
        query = parse_qs(environ.get("QUERY_STRING", ""))
        path_value = query.get("path", [""])[0]
        if not path_value:
            return self._respond_text(start_response, "400 Bad Request", "Missing path parameter")
        try:
            resolved = self._resolve_under_output(Path(path_value))
        except ValueError:
            try:
                resolved = self._resolve_candidate_dir(Path(path_value))
            except ValueError as exc:
                return self._respond_text(start_response, "403 Forbidden", str(exc))
        if not resolved.exists() or not resolved.is_file():
            return self._respond_text(start_response, "404 Not Found", "File not found")
        mime_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        payload = resolved.read_bytes()
        headers = [("Content-Type", mime_type), ("Content-Length", str(len(payload)))]
        start_response("200 OK", headers)
        return [payload]

    def _resolve_under_output(self, path: Path) -> Path:
        resolved = path.resolve(strict=False)
        output_root = self.output_dir.resolve(strict=False)
        if resolved != output_root and output_root not in resolved.parents:
            raise ValueError("Access denied")
        return resolved

    def _render_page(
        self,
        candidates: list | None = None,
        batch_meta: dict[str, object] | None = None,
        form_state: dict[str, str] | None = None,
        error: str | None = None,
        info: str | None = None,
    ) -> str:
        state = form_state or {}
        error_html = ""
        if error:
            error_html = f'<section class="panel error"><h2>Error</h2><p>{html.escape(error)}</p></section>'
        if info:
            error_html += f'<section class="panel"><h2>{html.escape(self.t("from_library_heading"))}</h2><p>{html.escape(info)}</p></section>'

        reroll_controls = ""
        comparison_bar = ""
        candidate_details = ""
        active_index = _active_candidate_index(candidates or [], batch_meta)
        if candidates:
            reroll_controls = f"""
            <div class="actions">
              <form method="post" action="/generate">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="all"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit">{html.escape(self.t('reroll_all'))}</button></form>
              <form method="post" action="/generate">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="chords"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit" class="secondary">{html.escape(self.t('reroll_chords'))}</button></form>
            </div>
            """
            comparison_bar = f'<section class="candidate-overview"><div class="overview-head"><h2>{html.escape(self.t("candidate_overview_heading"))}</h2><p>{html.escape(self.t("candidate_overview_lead"))}</p></div><div class="candidate-tabs">' + ''.join(_candidate_tab(result, active_index) for result in candidates) + '</div></section>'
            candidate_details = '<section class="candidate-details">' + ''.join(_candidate_detail(result, batch_meta, active_index, self) for result in candidates) + '</section>'

        mute_controls = ''.join(
            f'<button type="button" class="ghost mute-toggle" data-track-toggle="{track_name}" aria-pressed="false">Mute {track_name}</button>'
            for track_name in TRACK_NAMES
        )

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{TITLE}</title>
  <style>
    :root {{
      --bg: #f1ede3;
      --surface: rgba(255,255,255,0.82);
      --surface-strong: #fffaf0;
      --ink: #1f1a14;
      --muted: #6d614e;
      --line: rgba(31,26,20,0.15);
      --accent: #b24a2b;
      --accent-dark: #7f2f18;
      --accent-soft: #d67b3d;
      --shadow: 0 24px 60px rgba(73, 48, 25, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(178,74,43,0.18), transparent 30%), radial-gradient(circle at right 20%, rgba(234,216,183,0.75), transparent 28%), linear-gradient(180deg, #f1ede3 0%, #f7f2e9 100%); min-height: 100vh; }}
    .shell {{ max-width: 1280px; margin: 0 auto; padding: 32px 20px 64px; }}
    .hero {{ display: grid; gap: 14px; margin-bottom: 28px; }}
    .eyebrow {{ letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent-dark); font-size: 12px; }}
    h1 {{ margin: 0; font-size: clamp(36px, 7vw, 82px); line-height: 0.95; max-width: 10ch; }}
    .lead {{ max-width: 62ch; color: var(--muted); font-size: 18px; line-height: 1.6; }}
    .layout {{ display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr); gap: 24px; align-items: start; }}
    .panel {{ background: var(--surface); backdrop-filter: blur(10px); border: 1px solid var(--line); border-radius: 26px; padding: 22px; box-shadow: var(--shadow); }}
    .panel h2 {{ margin-top: 0; font-size: 22px; }}
    form {{ display: grid; gap: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    label {{ display: grid; gap: 8px; font-size: 14px; color: var(--muted); }}
    input, textarea, select {{ width: 100%; border: 1px solid rgba(31,26,20,0.14); border-radius: 16px; padding: 14px 16px; background: var(--surface-strong); color: var(--ink); font: inherit; }}
    textarea {{ min-height: 180px; resize: vertical; }}
    input[type=file] {{ padding: 12px; }}
    .hint {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    button {{ border: 0; border-radius: 999px; padding: 12px 18px; background: linear-gradient(135deg, var(--accent), var(--accent-soft)); color: white; font-size: 14px; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: linear-gradient(135deg, #6b5840, #9b866c); }}
    button.ghost {{ background: rgba(178,74,43,0.08); color: var(--accent-dark); border: 1px solid rgba(178,74,43,0.2); }}
    button:disabled {{ opacity: 0.45; cursor: default; }}
    .specs {{ display: grid; gap: 12px; }}
    .spec {{ padding: 14px 0; border-bottom: 1px solid var(--line); }}
    .spec:last-child {{ border-bottom: 0; }}
    .spec strong {{ display: block; margin-bottom: 4px; }}
    .error {{ border-color: rgba(178,74,43,0.3); background: rgba(255,238,229,0.92); }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 26px 0 18px; }}
    .actions form {{ display: block; }}
    .candidate-overview {{ display: grid; gap: 18px; margin: 16px 0 18px; }}
    .overview-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: end; }}
    .overview-head p {{ margin: 0; color: var(--muted); max-width: 56ch; }}
    .candidate-tabs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .candidate-tab {{ width: 100%; text-align: left; background: rgba(255,250,240,0.72); color: var(--ink); border: 1px solid var(--line); border-radius: 24px; padding: 18px; display: grid; gap: 10px; box-shadow: var(--shadow); }}
    .candidate-tab.is-busy {{ opacity: 0.65; }}
    .candidate-tab.active {{ background: linear-gradient(180deg, rgba(178,74,43,0.15), rgba(255,250,240,0.92)); border-color: rgba(178,74,43,0.35); }}
    .candidate-tab-header {{ display: flex; justify-content: space-between; gap: 10px; align-items: start; }}
    .candidate-tab strong {{ font-size: 17px; }}
    .candidate-tab .mini {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-dark); }}
    .candidate-tab .progression {{ font-size: 14px; line-height: 1.45; color: var(--ink); }}
    .candidate-tab .micro {{ display: flex; gap: 8px; flex-wrap: wrap; color: var(--muted); font-size: 12px; }}
    .candidate-details {{ display: grid; gap: 18px; }}
    .candidate-detail {{ display: none; gap: 18px; }}
    .candidate-detail.active {{ display: grid; }}
    .detail-hero {{ display: grid; gap: 18px; grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.9fr); align-items: start; }}
    .progression-block {{ display: grid; gap: 12px; }}
    .progression-block .label {{ font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent-dark); }}
    .progression-text {{ font-size: clamp(26px, 4vw, 46px); line-height: 1.08; letter-spacing: -0.02em; }}
    .detail-meta {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .meta-card {{ background: rgba(255,250,240,0.75); border: 1px solid var(--line); border-radius: 18px; padding: 14px 16px; display: grid; gap: 4px; }}
    .meta-card span {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.07em; }}
    .meta-card strong {{ font-size: 18px; }}
    .selected-mark {{ color: #365b3d; font-weight: 700; }}
    .path {{ word-break: break-all; color: var(--accent-dark); font-size: 13px; }}
    .tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 0; }}
    .tag {{ background: rgba(178,74,43,0.08); color: var(--accent-dark); border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .detail-grid {{ display: grid; grid-template-columns: minmax(280px, 0.65fr) minmax(0, 1.35fr); gap: 18px; }}
    .files {{ padding-left: 20px; margin: 0; }}
    .card-actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .card-actions form {{ display: block; }}
    .timeline-panel {{ display: grid; gap: 16px; }}
    .timeline-head p {{ margin: 6px 0 0; color: var(--muted); }}
    .timeline-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }}
    .bar-card {{ border: 1px solid var(--line); border-radius: 20px; padding: 14px; background: rgba(255,250,240,0.72); display: grid; gap: 10px; transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease; }}
    .bar-card.recently-updated {{ background: rgba(214, 123, 61, 0.18); border-color: rgba(178, 74, 43, 0.55); box-shadow: inset 0 0 0 1px rgba(178, 74, 43, 0.18); }}
    .bar-card.is-busy {{ opacity: 0.65; pointer-events: none; }}
    .bar-top {{ display: flex; align-items: start; justify-content: space-between; gap: 10px; }}
    .bar-index {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.07em; }}
    .chord-name {{ font-size: 22px; }}
    .bar-degree {{ color: var(--accent-dark); font-size: 13px; }}
    .timeline-lane {{ display: grid; gap: 6px; }}
    .lane-row {{ display: grid; gap: 6px; }}
    .lane-label {{ font-size: 11px; text-transform: uppercase; color: var(--muted); letter-spacing: 0.08em; }}
    .lane-track {{ position: relative; height: 16px; border-radius: 999px; background: rgba(31,26,20,0.08); overflow: hidden; }}
    .lane-fill {{ position: absolute; inset: 0 auto 0 0; border-radius: 999px; }}
    .lane-fill.match {{ background: linear-gradient(90deg, #b24a2b, #d67b3d); }}
    .lane-fill.full {{ width: 100%; background: linear-gradient(90deg, rgba(31,26,20,0.18), rgba(31,26,20,0.05)); }}
    .bar-meta {{ display: grid; gap: 8px; color: var(--muted); font-size: 13px; }}
    .bar-meta strong {{ color: var(--ink); }}
    .chord-chip-row {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .chord-chip {{ background: rgba(178,74,43,0.1); color: var(--accent-dark); border: 1px solid rgba(178,74,43,0.18); border-radius: 999px; padding: 6px 10px; font-size: 12px; cursor: help; }}
    .bar-density-select {{ min-width: 110px; padding: 8px 12px; }}
    .bar-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .bar-actions form {{ display: block; }}
    .bar-action-btn {{ padding: 9px 14px; font-size: 12px; }}
    .bar-chord-form {{ display: flex; gap: 6px; align-items: center; }}
    .bar-chord-input {{ flex: 1; min-width: 0; padding: 7px 10px; font-size: 12px; border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,0.7); }}
    .bar-chord-btn {{ padding: 7px 12px; font-size: 12px; }}
    .match-pill {{ justify-self: start; border-radius: 999px; padding: 6px 10px; background: rgba(178,74,43,0.1); color: var(--accent-dark); font-size: 12px; font-weight: 700; }}
    .updated-pill {{ justify-self: start; border-radius: 999px; padding: 5px 10px; background: rgba(127, 47, 24, 0.18); color: #6f2412; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; }}
    .inline-error {{ color: #8a2f1b; font-size: 12px; line-height: 1.4; }}
    .empty-state {{ color: var(--muted); font-size: 16px; padding: 24px 0 8px; }}
    .session-controls {{ display: grid; gap: 16px; margin-bottom: 18px; }}
    .control-block {{ display: grid; gap: 8px; }}
    .volume-row {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .volume-label {{ font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}
    .volume-value {{ font-size: 14px; color: var(--accent-dark); font-weight: 700; min-width: 52px; text-align: right; }}
    .volume-slider {{ width: 100%; accent-color: var(--accent); }}
    .mute-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .mute-toggle.active {{ background: linear-gradient(135deg, #6b5840, #9b866c); color: white; }}
    .audio-panel {{ margin-top: 14px; padding: 14px; border-radius: 16px; border: 1px solid var(--line); background: rgba(255,250,240,0.7); display: grid; gap: 10px; }}
    .audio-panel h4 {{ margin: 0; font-size: 16px; }}
    .audio-panel audio {{ width: 100%; }}
    .audio-stems {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .audio-stem {{ font-size: 12px; padding: 6px 10px; border-radius: 999px; background: rgba(178,74,43,0.1); color: var(--accent-dark); text-decoration: none; }}
    .audio-rerender {{ margin: 0; }}
    .save-form {{ display: flex; gap: 8px; align-items: center; }}
    .save-form input {{ padding: 8px 12px; border-radius: 12px; border: 1px solid rgba(31,26,20,0.14); background: var(--surface-strong); font: inherit; flex: 1; min-width: 140px; }}
    .form-actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .topnav {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }}
    .topnav-links {{ display: flex; gap: 14px; }}
    .topnav-link {{ color: var(--accent-dark); text-decoration: none; font-weight: 700; font-size: 14px; }}
    .topnav-link:hover {{ text-decoration: underline; }}
    .lang-form {{ margin: 0; }}
    .lang-btn {{ padding: 6px 14px; font-size: 12px; background: rgba(178,74,43,0.1); color: var(--accent-dark); border: 1px solid rgba(178,74,43,0.25); }}
    @media (max-width: 1100px) {{ .detail-hero {{ grid-template-columns: 1fr; }} .detail-grid {{ grid-template-columns: 1fr; }} .layout {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} .mute-grid {{ grid-template-columns: 1fr; }} .candidate-tabs {{ grid-template-columns: 1fr; }} .timeline-grid {{ grid-template-columns: 1fr; }} .detail-meta {{ grid-template-columns: 1fr; }} .overview-head {{ display: grid; }} .progression-text {{ font-size: 28px; }} }}
  </style>
</head>
<body>
  <main class="shell">
    {_lang_toggle_html(self._current_lang, "/")}
    <header class="hero">
      <div class="eyebrow">{html.escape(self.t('hero_eyebrow'))}</div>
      <h1>{html.escape(self.t('hero_title'))}</h1>
      <p class="lead">{html.escape(self.t('hero_lead'))}</p>
    </header>
    <section class="layout">
      <section class="panel">
        <h2>{html.escape(self.t('panel_create'))}</h2>
        <form method="post" action="/generate" enctype="multipart/form-data">
          <label>
            {html.escape(self.t('label_text'))}
            <textarea name="text" placeholder="{html.escape(self.t('placeholder_text'))}">{html.escape(state.get("text", ""))}</textarea>
          </label>
          <label>
            {html.escape(self.t('label_melody_upload'))}
            <input type="file" name="melody_midi" accept=".mid,.midi">
          </label>
          <div class="grid">
            <label>{html.escape(self.t('label_tempo'))}<input type="number" name="tempo" min="30" max="300" placeholder="{html.escape(self.t('placeholder_auto'))}" value="{html.escape(state.get("tempo", ""))}"></label>
            <label>{html.escape(self.t('label_key'))}<input type="text" name="key" placeholder="{html.escape(self.t('placeholder_key'))}" value="{html.escape(state.get("key", ""))}"></label>
            <label>{html.escape(self.t('label_genre'))}<input type="text" name="genre" placeholder="{html.escape(self.t('placeholder_genre'))}" value="{html.escape(state.get("genre", ""))}"></label>
            <label>{html.escape(self.t('label_bars'))}<input type="number" name="bars" min="1" max="128" placeholder="{html.escape(self.t('placeholder_auto'))}" value="{html.escape(state.get("bars", ""))}"></label>
            {_select_field_html(self.t('label_chord_density'), "chord_density", state.get("chord_density", "auto"), [("auto", "Auto"), ("1", "1 per bar"), ("2", "2 per bar"), ("3", "3 per bar")])}
            {_select_field_html(self.t('label_melody_density'), "melody_density", state.get("melody_density", "auto"), [("auto", "Auto"), ("sparse", "Sparse"), ("normal", "Normal"), ("dense", "Dense"), ("xdense", "X-Dense")])}
            {_select_field_html(self.t('label_chord_rhythm'), "chord_rhythm_style", state.get("chord_rhythm_style", "auto"), [("auto", "Auto"), ("hold", "Hold"), ("stab", "Stab"), ("strum", "Strum")])}
            {_select_field_html(self.t('label_humanize'), "humanize", state.get("humanize", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_swing'), "swing", state.get("swing", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_drum_dynamics'), "drum_dynamics", state.get("drum_dynamics", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_harmony_spice'), "harmony_spice", state.get("harmony_spice", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_section_dynamics'), "section_dynamics", state.get("section_dynamics", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_modulate'), "modulate", state.get("modulate", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            <label>{html.escape(self.t('label_melody_offset'))}<input type="number" name="melody_offset_beats" step="0.25" min="-16" max="16" value="{html.escape(state.get("melody_offset_beats", "0"))}" title="{html.escape(self.t('melody_offset_help'))}"></label>
            <label>{html.escape(self.t('label_seed'))}<input type="number" name="seed" placeholder="{html.escape(self.t('placeholder_optional'))}" value="{html.escape(state.get("seed", ""))}"></label>
            <label>{html.escape(self.t('label_options'))}<input type="number" name="count" min="1" max="8" value="{html.escape(state.get("count", "4"))}"></label>
          </div>
          <input type="hidden" name="melody_source" value="{html.escape(state.get("melody_source", ""))}">
          <p class="hint">{html.escape(self.t('hint_main'))}</p>
          <div class="form-actions">
            <button type="submit">{html.escape(self.t('btn_generate'))}</button>
            <button type="submit" class="ghost" formaction="/llm/suggest" formenctype="application/x-www-form-urlencoded">{html.escape(self.t('btn_suggest'))}</button>
          </div>
        </form>
      </section>
      <aside class="panel">
        <h2>{html.escape(self.t('panel_session'))}</h2>
        <div class="session-controls">
          <div class="control-block">
            <div class="volume-row">
              <span class="volume-label">{html.escape(self.t('preview_volume'))}</span>
              <span class="volume-value" id="volume-value">20%</span>
            </div>
            <input class="volume-slider" id="volume-slider" type="range" min="0" max="100" value="20">
          </div>
          <div class="control-block">
            <div class="volume-label">{html.escape(self.t('part_mutes'))}</div>
            <div class="mute-grid">{mute_controls}</div>
          </div>
        </div>
        <div class="specs">
          <div class="spec"><strong>{html.escape(self.t('spec_overview_title'))}</strong>{html.escape(self.t('spec_overview_text'))}</div>
          <div class="spec"><strong>{html.escape(self.t('spec_chords_title'))}</strong>{html.escape(self.t('spec_chords_text_pre'))}<a href="/melody-from-chords">/melody-from-chords</a>{html.escape(self.t('spec_chords_text_post'))}</div>
          <div class="spec"><strong>{html.escape(self.t('spec_library_title'))}</strong>{html.escape(self.t('spec_library_text_pre'))}<a href="/library">/library</a>{html.escape(self.t('spec_library_text_post'))}</div>
          <div class="spec"><strong>{html.escape(self.t('spec_smart_title'))}</strong>{html.escape(self.t('spec_smart_text_pre'))}<code>{html.escape(self.t('btn_suggest'))}</code>{html.escape(self.t('spec_smart_text_mid'))}<a href="/settings">/settings</a>{html.escape(self.t('spec_smart_text_post'))}</div>
          <div class="spec"><strong>{html.escape(self.t('spec_timeline_title'))}</strong>{html.escape(self.t('spec_timeline_text'))}</div>
          <div class="spec"><strong>{html.escape(self.t('spec_playback_title'))}</strong>{html.escape(self.t('spec_playback_text'))}</div>
          <div class="spec"><strong>{html.escape(self.t('spec_selection_title'))}</strong>{html.escape(self.t('spec_selection_text_pre'))}<code>{BATCH_META_FILENAME}</code>{html.escape(self.t('spec_selection_text_post'))}</div>
          <div class="spec"><strong>{html.escape(self.t('spec_output_title'))}</strong>{html.escape(self.t('spec_output_text_pre'))}{html.escape(str(self.output_dir))}{html.escape(self.t('spec_output_text_post'))}</div>
        </div>
      </aside>
    </section>
    {error_html}
    {reroll_controls}
    {comparison_bar}
    {candidate_details or f'<section class="empty-state">{html.escape(self.t("empty_state"))}</section>'}
  </main>
  <script type="module">
    import * as Tone from 'https://cdn.jsdelivr.net/npm/tone@15.0.4/+esm';
    import {{ Midi }} from 'https://cdn.jsdelivr.net/npm/@tonejs/midi@2.0.28/+esm';

    const TRACK_NAMES = ['Melody', 'Chords', 'Bass', 'Drums'];
    let currentButtons = null;
    let currentStop = null;
    const synthRegistry = new Map();
    const mutedTracks = new Set();
    const DEFAULT_VOLUME = 20;
    const volumeSlider = document.getElementById('volume-slider');
    const volumeValue = document.getElementById('volume-value');
    const masterGain = new Tone.Gain(DEFAULT_VOLUME / 100).toDestination();

    function setPreviewVolume(value) {{
      const normalized = Math.max(0, Math.min(100, Number(value) || 0));
      masterGain.gain.value = normalized / 100;
      if (volumeSlider) volumeSlider.value = String(normalized);
      if (volumeValue) volumeValue.textContent = `${{normalized}}%`;
    }}

    function setTrackMuted(trackName, muted) {{
      if (muted) {{
        mutedTracks.add(trackName);
      }} else {{
        mutedTracks.delete(trackName);
      }}
      const synth = synthRegistry.get(trackName);
      if (muted) {{
        synth?.releaseAll?.();
      }}
      document.querySelectorAll(`[data-track-toggle="${{trackName}}"]`).forEach((button) => {{
        button.classList.toggle('active', muted);
        button.setAttribute('aria-pressed', muted ? 'true' : 'false');
        button.textContent = `${{muted ? 'Unmute' : 'Mute'}} ${{trackName}}`;
      }});
    }}

    function setActiveCandidate(candidateId) {{
      document.querySelectorAll('[data-candidate-tab]').forEach((button) => {{
        button.classList.toggle('active', button.dataset.candidateTab === candidateId);
      }});
      document.querySelectorAll('[data-candidate-detail]').forEach((panel) => {{
        panel.classList.toggle('active', panel.dataset.candidateDetail === candidateId);
      }});
    }}

    setPreviewVolume(DEFAULT_VOLUME);
    TRACK_NAMES.forEach((trackName) => setTrackMuted(trackName, false));

    function makeSynthForTrack(name) {{
      if (name === 'Drums') return new Tone.MembraneSynth().connect(masterGain);
      if (name === 'Bass') return new Tone.MonoSynth({{ oscillator: {{ type: 'square' }}, envelope: {{ attack: 0.01, release: 0.2 }}, volume: -14 }}).connect(masterGain);
      if (name === 'Chords') return new Tone.PolySynth(Tone.Synth, {{ oscillator: {{ type: 'triangle' }}, envelope: {{ attack: 0.02, release: 0.3 }}, volume: -18 }}).connect(masterGain);
      return new Tone.PolySynth(Tone.Synth, {{ oscillator: {{ type: 'sine' }}, envelope: {{ attack: 0.01, release: 0.2 }}, volume: -16 }}).connect(masterGain);
    }}

    async function stopPlayback() {{
      if (currentStop) {{
        currentStop();
        currentStop = null;
      }}
      Tone.Transport.stop();
      Tone.Transport.cancel();
      for (const synth of synthRegistry.values()) {{
        synth.releaseAll?.();
      }}
      if (currentButtons) {{
        currentButtons.play.disabled = false;
        currentButtons.stop.disabled = true;
        currentButtons = null;
      }}
    }}

    async function playCandidate(url, buttons, segment = null) {{
      await Tone.start();
      await stopPlayback();
      const response = await fetch(url);
      if (!response.ok) {{
        throw new Error(`Failed to load preview: ${{response.status}}`);
      }}
      const midi = new Midi(await response.arrayBuffer());
      let lastTime = 0;

      const ppq = midi.header.ppq || 480;
      const tempo = segment?.tempo || 120;
      const secPerTick = 60 / tempo / ppq;

      midi.tracks.forEach((track, index) => {{
        if (!track.notes.length) return;
        const name = track.name || `Track ${{index + 1}}`;
        let synth = synthRegistry.get(name);
        if (!synth) {{
          synth = makeSynthForTrack(name);
          synthRegistry.set(name, synth);
        }}
        track.notes.forEach((note) => {{
          let startTime = note.time;
          let duration = note.duration;
          if (segment) {{
            const noteStart = note.ticks ?? Math.round(note.time / secPerTick);
            const noteDurationTicks = note.durationTicks ?? Math.round(note.duration / secPerTick);
            const noteEnd = noteStart + noteDurationTicks;
            if (noteEnd <= segment.startTick || noteStart >= segment.endTick) return;
            const overlapStart = Math.max(noteStart, segment.startTick);
            const overlapEnd = Math.min(noteEnd, segment.endTick);
            startTime = (overlapStart - segment.startTick) * secPerTick;
            duration = Math.max(secPerTick / 4, (overlapEnd - overlapStart) * secPerTick);
          }}
          lastTime = Math.max(lastTime, startTime + duration);
          Tone.Transport.schedule((time) => {{
            if (mutedTracks.has(name)) return;
            synth.triggerAttackRelease(note.name, duration, time, Math.max(0.08, (note.velocity || 0.7) * 0.35));
          }}, startTime);
        }});
      }});

      Tone.Transport.position = 0;
      Tone.Transport.start();
      buttons.play.disabled = true;
      buttons.stop.disabled = false;
      currentButtons = buttons;
      currentStop = () => {{
        Tone.Transport.stop();
        Tone.Transport.cancel();
      }};
      setTimeout(() => {{
        if (currentButtons === buttons) {{
          stopPlayback();
        }}
      }}, Math.ceil((lastTime + 0.5) * 1000));
    }}

    if (volumeSlider) {{
      volumeSlider.addEventListener('input', (event) => {{
        setPreviewVolume(event.target.value);
      }});
    }}

    document.querySelectorAll('[data-track-toggle]').forEach((button) => {{
      button.addEventListener('click', () => {{
        const trackName = button.dataset.trackToggle;
        setTrackMuted(trackName, !mutedTracks.has(trackName));
      }});
    }});

    function bindPreviewButtons(root = document) {{
      root.querySelectorAll('[data-preview-url]').forEach((button) => {{
        if (button.dataset.boundPreview === '1') return;
        button.dataset.boundPreview = '1';
        button.addEventListener('click', async () => {{
          const card = button.closest('[data-candidate-detail]') || button.closest('.bar-card');
          const detail = button.closest('[data-candidate-detail]');
          const stop = detail ? detail.querySelector('[data-stop]') : document.querySelector('[data-candidate-detail].active [data-stop]');
          const segment = button.dataset.previewStart ? {{
            startTick: Number(button.dataset.previewStart),
            endTick: Number(button.dataset.previewEnd),
            tempo: Number(button.dataset.previewTempo || 120),
          }} : null;
          try {{
            await playCandidate(button.dataset.previewUrl, {{ play: button, stop }}, segment);
          }} catch (error) {{
            console.error(error);
            await stopPlayback();
          }}
        }});
      }});
    }}

    function bindStopButtons(root = document) {{
      root.querySelectorAll('[data-stop]').forEach((button) => {{
        if (button.dataset.boundStop === '1') return;
        button.dataset.boundStop = '1';
        button.addEventListener('click', async () => {{
          await stopPlayback();
        }});
      }});
    }}

    function bindCandidateTabs(root = document) {{
      root.querySelectorAll('[data-candidate-tab]').forEach((button) => {{
        if (button.dataset.boundTab === '1') return;
        button.dataset.boundTab = '1';
        button.addEventListener('click', () => {{
          setActiveCandidate(button.dataset.candidateTab);
        }});
      }});
    }}

    async function postBarUpdate(form, endpoint) {{
      const barCard = form.closest('.bar-card');
      const candidateIndex = form.querySelector('[name="candidate_index"]').value;
      const barIndex = form.querySelector('[name="bar_index"]').value;
      const tab = document.getElementById(`candidate-tab-${{candidateIndex}}`);
      const progress = document.getElementById(`candidate-progress-${{candidateIndex}}`);
      const errorNode = barCard?.querySelector('.inline-error');
      const formData = new FormData(form);
      formData.set('fragment', '1');
      if (errorNode) {{
        errorNode.hidden = true;
        errorNode.textContent = '';
      }}
      barCard?.classList.add('is-busy');
      tab?.classList.add('is-busy');
      try {{
        const response = await fetch(endpoint, {{ method: 'POST', body: formData }});
        const html = await response.text();
        if (!response.ok) {{
          throw new Error(html || `Update failed: ${{response.status}}`);
        }}
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const nextTab = doc.querySelector('[data-fragment="candidate-tab"] > *');
        const nextProgress = doc.querySelector('[data-fragment="candidate-progress"] > *');
        const nextBar = doc.querySelector('[data-fragment="bar-card"] > *');
        if (nextTab && tab) {{
          tab.replaceWith(nextTab);
          bindCandidateTabs(document);
        }}
        if (nextProgress && progress) {{
          progress.replaceWith(nextProgress);
        }}
        const currentBar = document.getElementById(`candidate-${{candidateIndex}}-bar-${{barIndex}}`);
        if (nextBar && currentBar) {{
          currentBar.replaceWith(nextBar);
          bindPreviewButtons(document);
          bindRerollForms(document);
        }}
      }} catch (error) {{
        console.error(error);
        if (errorNode) {{
          errorNode.hidden = false;
          errorNode.textContent = error instanceof Error ? error.message : String(error);
        }}
      }} finally {{
        barCard?.classList.remove('is-busy');
        tab?.classList.remove('is-busy');
      }}
    }}

    async function rerollBar(form) {{
      await postBarUpdate(form, '/reroll-bar');
    }}

    async function setBarChord(form) {{
      await postBarUpdate(form, '/timeline/chord');
    }}

    function bindRerollForms(root = document) {{
      root.querySelectorAll('[data-reroll-bar-form]').forEach((form) => {{
        if (form.dataset.boundReroll === '1') return;
        form.dataset.boundReroll = '1';
        form.addEventListener('submit', async (event) => {{
          event.preventDefault();
          await rerollBar(form);
        }});
      }});
      root.querySelectorAll('[data-set-chord-form]').forEach((form) => {{
        if (form.dataset.boundSetChord === '1') return;
        form.dataset.boundSetChord = '1';
        form.addEventListener('submit', async (event) => {{
          event.preventDefault();
          const input = form.querySelector('input[name="chord"]');
          if (!input || !input.value.trim()) return;
          await setBarChord(form);
        }});
      }});
    }}

    bindPreviewButtons(document);
    bindStopButtons(document);
    bindCandidateTabs(document);
    bindRerollForms(document);

    const melodyInput = document.querySelector('input[type=file][name="melody_midi"]');
    const tempoField = document.querySelector('input[name="tempo"]');
    const keyField = document.querySelector('input[name="key"]');
    const barsField = document.querySelector('input[name="bars"]');
    const melodySourceField = document.querySelector('input[name="melody_source"]');
    const offsetField = document.querySelector('input[name="melody_offset_beats"]');
    let melodyInfoBanner = null;

    function setLockedField(field, value) {{
      if (!field) return;
      field.value = value !== null && value !== undefined ? String(value) : '';
      field.dataset.lockedByMelody = '1';
      field.readOnly = true;
      field.style.background = 'rgba(54, 91, 61, 0.10)';
      field.title = 'Detected from melody MIDI';
    }}
    function unlockField(field) {{
      if (!field) return;
      delete field.dataset.lockedByMelody;
      field.readOnly = false;
      field.style.background = '';
      field.title = '';
    }}
    function showMelodyBanner(text) {{
      if (!melodyInput) return;
      if (!melodyInfoBanner) {{
        melodyInfoBanner = document.createElement('p');
        melodyInfoBanner.className = 'hint';
        melodyInfoBanner.style.color = '#365b3d';
        melodyInput.closest('label').insertAdjacentElement('afterend', melodyInfoBanner);
      }}
      melodyInfoBanner.textContent = text;
    }}
    function hideMelodyBanner() {{
      if (melodyInfoBanner) {{ melodyInfoBanner.remove(); melodyInfoBanner = null; }}
    }}

    if (melodyInput) {{
      melodyInput.addEventListener('change', async () => {{
        const file = melodyInput.files?.[0];
        if (!file) {{
          [tempoField, keyField, barsField].forEach(unlockField);
          if (melodySourceField) melodySourceField.value = '';
          hideMelodyBanner();
          return;
        }}
        showMelodyBanner('Analyzing melody...');
        const fd = new FormData();
        fd.append('melody_midi', file);
        try {{
          const response = await fetch('/melody/analyze', {{ method: 'POST', body: fd }});
          const data = await response.json();
          if (!response.ok) throw new Error(data?.error || 'Analyze failed');
          if (data.tempo) setLockedField(tempoField, data.tempo);
          if (data.key) setLockedField(keyField, data.key);
          if (data.bars) setLockedField(barsField, data.bars);
          if (offsetField && typeof data.suggested_offset_beats === 'number' && data.suggested_offset_beats !== 0) {{
            offsetField.value = String(data.suggested_offset_beats);
            offsetField.style.background = 'rgba(54, 91, 61, 0.10)';
            offsetField.title = 'Auto-suggested from melody pickup. Edit if wrong.';
          }}
          if (melodySourceField && data.melody_source) melodySourceField.value = data.melody_source;
          const offsetNote = (typeof data.suggested_offset_beats === 'number' && data.suggested_offset_beats !== 0) ? ` · pickup ${{data.suggested_offset_beats}} beats` : '';
          showMelodyBanner(`Detected from melody · ${{data.tempo || '?'}} BPM · ${{data.key || '?'}} · ${{data.bars || '?'}} bars${{offsetNote}}`);
        }} catch (err) {{
          showMelodyBanner(`Could not analyze: ${{err.message}}`);
          [tempoField, keyField, barsField].forEach(unlockField);
        }}
      }});
    }}

    const initialCandidate = document.querySelector('[data-candidate-tab].active')?.dataset.candidateTab;
    if (initialCandidate) {{
      setActiveCandidate(initialCandidate);
    }}

    window.addEventListener('beforeunload', () => {{ stopPlayback(); }});
  </script>
</body>
</html>
"""

    def _render_chords_page(
        self,
        candidates: list | None = None,
        batch_meta: dict[str, object] | None = None,
        form_state: dict[str, str] | None = None,
        error: str | None = None,
        info: str | None = None,
    ) -> str:
        state = form_state or {}
        error_html = ""
        if error:
            error_html = f'<section class="panel error"><h2>Error</h2><p>{html.escape(error)}</p></section>'
        if info:
            error_html += f'<section class="panel"><h2>{html.escape(self.t("from_library_heading"))}</h2><p>{html.escape(info)}</p></section>'

        reroll_controls = ""
        comparison_bar = ""
        candidate_details = ""
        active_index = _active_candidate_index(candidates or [], batch_meta)
        if candidates:
            reroll_controls = f"""
            <div class="actions">
              <form method="post" action="/generate-chords">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="all"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit">{html.escape(self.t('reroll_all'))}</button></form>
              <form method="post" action="/generate-chords">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="melody"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit" class="secondary">{html.escape(self.t('reroll_melody'))}</button></form>
            </div>
            """
            comparison_bar = f'<section class="candidate-overview"><div class="overview-head"><h2>{html.escape(self.t("candidate_overview_heading"))}</h2><p>{html.escape(self.t("candidate_overview_lead"))}</p></div><div class="candidate-tabs">' + ''.join(_candidate_tab(result, active_index) for result in candidates) + '</div></section>'
            candidate_details = '<section class="candidate-details">' + ''.join(_candidate_detail(result, batch_meta, active_index, self) for result in candidates) + '</section>'

        mute_controls = ''.join(
            f'<button type="button" class="ghost mute-toggle" data-track-toggle="{track_name}" aria-pressed="false">Mute {track_name}</button>'
            for track_name in TRACK_NAMES
        )

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{TITLE} - Melody from Chords</title>
  <style>
    :root {{
      --bg: #f1ede3;
      --surface: rgba(255,255,255,0.82);
      --surface-strong: #fffaf0;
      --ink: #1f1a14;
      --muted: #6d614e;
      --line: rgba(31,26,20,0.15);
      --accent: #b24a2b;
      --accent-dark: #7f2f18;
      --accent-soft: #d67b3d;
      --shadow: 0 24px 60px rgba(73, 48, 25, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(178,74,43,0.18), transparent 30%), radial-gradient(circle at right 20%, rgba(234,216,183,0.75), transparent 28%), linear-gradient(180deg, #f1ede3 0%, #f7f2e9 100%); min-height: 100vh; }}
    .shell {{ max-width: 1280px; margin: 0 auto; padding: 32px 20px 64px; }}
    .hero {{ display: grid; gap: 14px; margin-bottom: 28px; }}
    .eyebrow {{ letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent-dark); font-size: 12px; }}
    h1 {{ margin: 0; font-size: clamp(36px, 7vw, 82px); line-height: 0.95; max-width: 12ch; }}
    .lead {{ max-width: 62ch; color: var(--muted); font-size: 18px; line-height: 1.6; }}
    .layout {{ display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr); gap: 24px; align-items: start; }}
    .panel {{ background: var(--surface); backdrop-filter: blur(10px); border: 1px solid var(--line); border-radius: 26px; padding: 22px; box-shadow: var(--shadow); }}
    .panel h2 {{ margin-top: 0; font-size: 22px; }}
    form {{ display: grid; gap: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    label {{ display: grid; gap: 8px; font-size: 14px; color: var(--muted); }}
    input, textarea, select {{ width: 100%; border: 1px solid rgba(31,26,20,0.14); border-radius: 16px; padding: 14px 16px; background: var(--surface-strong); color: var(--ink); font: inherit; }}
    textarea {{ min-height: 180px; resize: vertical; }}
    .hint {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    button {{ border: 0; border-radius: 999px; padding: 12px 18px; background: linear-gradient(135deg, var(--accent), var(--accent-soft)); color: white; font-size: 14px; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: linear-gradient(135deg, #6b5840, #9b866c); }}
    button.ghost {{ background: rgba(178,74,43,0.08); color: var(--accent-dark); border: 1px solid rgba(178,74,43,0.2); }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 26px 0 18px; }}
    .actions form {{ display: block; }}
    .specs {{ display: grid; gap: 12px; }}
    .spec {{ padding: 14px 0; border-bottom: 1px solid var(--line); }}
    .spec:last-child {{ border-bottom: 0; }}
    .candidate-overview,.candidate-details {{ display: grid; gap: 18px; margin-top: 18px; }}
    .overview-head p {{ margin: 0; color: var(--muted); }}
    .candidate-tabs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .session-controls {{ display: grid; gap: 16px; margin-bottom: 18px; }}
    .control-block {{ display: grid; gap: 8px; }}
    .mute-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} .grid {{ grid-template-columns: 1fr; }} .mute-grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class="shell">
    {_lang_toggle_html(self._current_lang, "/melody-from-chords")}
    <header class="hero">
      <div class="eyebrow">{html.escape(self.t('hero_eyebrow'))}</div>
      <h1>{html.escape(self.t('from_chords_title'))}</h1>
      <p class="lead">{html.escape(self.t('from_chords_lead'))}</p>
      <p><a href="/">{html.escape(self.t('back_to_studio'))}</a></p>
    </header>
    <section class="layout">
      <section class="panel">
        <h2>{html.escape(self.t('panel_create'))}</h2>
        <form method="post" action="/generate-chords">
          <label>
            {html.escape(self.t('label_chord_progression'))}
            <textarea name="chord_progression" placeholder="{html.escape(self.t('placeholder_chord_progression'))}">{html.escape(state.get("chord_progression", ""))}</textarea>
          </label>
          <label>
            {html.escape(self.t('label_text'))}
            <textarea name="text" placeholder="{html.escape(self.t('placeholder_text'))}">{html.escape(state.get("text", ""))}</textarea>
          </label>
          <div class="grid">
            <label>{html.escape(self.t('label_tempo'))}<input type="number" name="tempo" min="30" max="300" placeholder="{html.escape(self.t('placeholder_auto'))}" value="{html.escape(state.get("tempo", ""))}"></label>
            <label>{html.escape(self.t('label_key'))}<input type="text" name="key" placeholder="{html.escape(self.t('placeholder_key'))}" value="{html.escape(state.get("key", ""))}"></label>
            <label>{html.escape(self.t('label_genre'))}<input type="text" name="genre" placeholder="{html.escape(self.t('placeholder_genre'))}" value="{html.escape(state.get("genre", ""))}"></label>
            <label>{html.escape(self.t('label_bars'))}<input type="number" name="bars" min="1" max="128" placeholder="{html.escape(self.t('placeholder_auto'))}" value="{html.escape(state.get("bars", ""))}"></label>
            {_select_field_html(self.t('label_chord_density'), "chord_density", state.get("chord_density", "auto"), [("auto", "Auto"), ("1", "1 per bar"), ("2", "2 per bar"), ("3", "3 per bar")])}
            {_select_field_html(self.t('label_melody_density'), "melody_density", state.get("melody_density", "auto"), [("auto", "Auto"), ("sparse", "Sparse"), ("normal", "Normal"), ("dense", "Dense"), ("xdense", "X-Dense")])}
            {_select_field_html(self.t('label_chord_rhythm'), "chord_rhythm_style", state.get("chord_rhythm_style", "auto"), [("auto", "Auto"), ("hold", "Hold"), ("stab", "Stab"), ("strum", "Strum")])}
            {_select_field_html(self.t('label_humanize'), "humanize", state.get("humanize", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_swing'), "swing", state.get("swing", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_drum_dynamics'), "drum_dynamics", state.get("drum_dynamics", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_harmony_spice'), "harmony_spice", state.get("harmony_spice", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_section_dynamics'), "section_dynamics", state.get("section_dynamics", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html(self.t('label_modulate'), "modulate", state.get("modulate", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            <label>{html.escape(self.t('label_seed'))}<input type="number" name="seed" placeholder="{html.escape(self.t('placeholder_optional'))}" value="{html.escape(state.get("seed", ""))}"></label>
            <label>{html.escape(self.t('label_options'))}<input type="number" name="count" min="1" max="8" value="{html.escape(state.get("count", "4"))}"></label>
          </div>
          <p class="hint">{html.escape(self.t('from_chords_hint'))}</p>
          <div class="form-actions">
            <button type="submit">{html.escape(self.t('btn_generate_melodies'))}</button>
            <button type="submit" class="ghost" formaction="/llm/suggest-chords">{html.escape(self.t('btn_suggest'))}</button>
          </div>
        </form>
      </section>
      <aside class="panel">
        <h2>{html.escape(self.t('panel_session'))}</h2>
        <div class="session-controls">
          <div class="control-block">
            <div><strong>Preview Volume</strong> <span id="volume-value">20%</span></div>
            <input id="volume-slider" type="range" min="0" max="100" value="20">
          </div>
          <div class="control-block">
            <div><strong>Part Mutes</strong></div>
            <div class="mute-grid">{mute_controls}</div>
          </div>
        </div>
        <div class="specs">
          <div class="spec"><strong>Dual input format</strong>Use either degree input like <code>1-5-6-4</code> or named chords like <code>Am-F-C-G</code>.</div>
          <div class="spec"><strong>Melody timeline</strong>Each detailed view shows the fixed chord path, melody focus notes, and chord-tone landing strength per bar.</div>
          <div class="spec"><strong>Bar reroll</strong>Use <code>Reroll Melody</code> to regenerate only the selected bar while keeping the harmony fixed.</div>
          <div class="spec"><strong>Saved selection</strong><code>Select This</code> stores the chosen option in <code>{BATCH_META_FILENAME}</code>.</div>
        </div>
      </aside>
    </section>
    {error_html}
    {reroll_controls}
    {comparison_bar}
    {candidate_details or '<section class="panel"><p class="hint">Generate a candidate set to compare toplines against your chord progression.</p></section>'}
  </main>
  <script type="module">
    import * as Tone from 'https://cdn.jsdelivr.net/npm/tone@15.0.4/+esm';
    import {{ Midi }} from 'https://cdn.jsdelivr.net/npm/@tonejs/midi@2.0.28/+esm';

    const TRACK_NAMES = ['Melody', 'Chords', 'Bass', 'Drums'];
    let currentButtons = null;
    let currentStop = null;
    const synthRegistry = new Map();
    const mutedTracks = new Set();
    const DEFAULT_VOLUME = 20;
    const volumeSlider = document.getElementById('volume-slider');
    const volumeValue = document.getElementById('volume-value');
    const masterGain = new Tone.Gain(DEFAULT_VOLUME / 100).toDestination();

    function setPreviewVolume(value) {{
      const normalized = Math.max(0, Math.min(100, Number(value) || 0));
      masterGain.gain.value = normalized / 100;
      if (volumeSlider) volumeSlider.value = String(normalized);
      if (volumeValue) volumeValue.textContent = `${{normalized}}%`;
    }}

    function setTrackMuted(trackName, muted) {{
      if (muted) mutedTracks.add(trackName); else mutedTracks.delete(trackName);
      const synth = synthRegistry.get(trackName);
      if (muted) synth?.releaseAll?.();
      document.querySelectorAll(`[data-track-toggle="${{trackName}}"]`).forEach((button) => {{
        button.classList.toggle('active', muted);
        button.setAttribute('aria-pressed', muted ? 'true' : 'false');
        button.textContent = `${{muted ? 'Unmute' : 'Mute'}} ${{trackName}}`;
      }});
    }}

    function setActiveCandidate(candidateId) {{
      document.querySelectorAll('[data-candidate-tab]').forEach((button) => button.classList.toggle('active', button.dataset.candidateTab === candidateId));
      document.querySelectorAll('[data-candidate-detail]').forEach((panel) => panel.classList.toggle('active', panel.dataset.candidateDetail === candidateId));
    }}

    setPreviewVolume(DEFAULT_VOLUME);
    TRACK_NAMES.forEach((trackName) => setTrackMuted(trackName, false));

    function makeSynthForTrack(name) {{
      if (name === 'Drums') return new Tone.MembraneSynth().connect(masterGain);
      if (name === 'Bass') return new Tone.MonoSynth({{ oscillator: {{ type: 'square' }}, envelope: {{ attack: 0.01, release: 0.2 }}, volume: -14 }}).connect(masterGain);
      if (name === 'Chords') return new Tone.PolySynth(Tone.Synth, {{ oscillator: {{ type: 'triangle' }}, envelope: {{ attack: 0.02, release: 0.3 }}, volume: -18 }}).connect(masterGain);
      return new Tone.PolySynth(Tone.Synth, {{ oscillator: {{ type: 'sine' }}, envelope: {{ attack: 0.01, release: 0.2 }}, volume: -16 }}).connect(masterGain);
    }}

    async function stopPlayback() {{
      if (currentStop) {{ currentStop(); currentStop = null; }}
      Tone.Transport.stop();
      Tone.Transport.cancel();
      for (const synth of synthRegistry.values()) synth.releaseAll?.();
      if (currentButtons) {{ currentButtons.play.disabled = false; currentButtons.stop.disabled = true; currentButtons = null; }}
    }}

    async function playCandidate(url, buttons, segment = null) {{
      await Tone.start();
      await stopPlayback();
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Failed to load preview: ${{response.status}}`);
      const midi = new Midi(await response.arrayBuffer());
      let lastTime = 0;
      const ppq = midi.header.ppq || 480;
      const tempo = segment?.tempo || 120;
      const secPerTick = 60 / tempo / ppq;
      midi.tracks.forEach((track, index) => {{
        if (!track.notes.length) return;
        const name = track.name || `Track ${{index + 1}}`;
        let synth = synthRegistry.get(name);
        if (!synth) {{ synth = makeSynthForTrack(name); synthRegistry.set(name, synth); }}
        track.notes.forEach((note) => {{
          let startTime = note.time;
          let duration = note.duration;
          if (segment) {{
            const noteStart = note.ticks ?? Math.round(note.time / secPerTick);
            const noteDurationTicks = note.durationTicks ?? Math.round(note.duration / secPerTick);
            const noteEnd = noteStart + noteDurationTicks;
            if (noteEnd <= segment.startTick || noteStart >= segment.endTick) return;
            const overlapStart = Math.max(noteStart, segment.startTick);
            const overlapEnd = Math.min(noteEnd, segment.endTick);
            startTime = (overlapStart - segment.startTick) * secPerTick;
            duration = Math.max(secPerTick / 4, (overlapEnd - overlapStart) * secPerTick);
          }}
          lastTime = Math.max(lastTime, startTime + duration);
          Tone.Transport.schedule((time) => {{
            if (mutedTracks.has(name)) return;
            synth.triggerAttackRelease(note.name, duration, time, Math.max(0.08, (note.velocity || 0.7) * 0.35));
          }}, startTime);
        }});
      }});
      Tone.Transport.position = 0;
      Tone.Transport.start();
      buttons.play.disabled = true;
      buttons.stop.disabled = false;
      currentButtons = buttons;
      currentStop = () => {{ Tone.Transport.stop(); Tone.Transport.cancel(); }};
      setTimeout(() => {{ if (currentButtons === buttons) stopPlayback(); }}, Math.ceil((lastTime + 0.5) * 1000));
    }}

    function bindPreviewButtons(root = document) {{
      root.querySelectorAll('[data-preview-url]').forEach((button) => {{
        if (button.dataset.boundPreview === '1') return;
        button.dataset.boundPreview = '1';
        button.addEventListener('click', async () => {{
          const detail = button.closest('[data-candidate-detail]');
          const stop = detail ? detail.querySelector('[data-stop]') : document.querySelector('[data-candidate-detail].active [data-stop]');
          const segment = button.dataset.previewStart ? {{ startTick: Number(button.dataset.previewStart), endTick: Number(button.dataset.previewEnd), tempo: Number(button.dataset.previewTempo || 120) }} : null;
          try {{ await playCandidate(button.dataset.previewUrl, {{ play: button, stop }}, segment); }} catch (error) {{ console.error(error); await stopPlayback(); }}
        }});
      }});
    }}

    function bindStopButtons(root = document) {{
      root.querySelectorAll('[data-stop]').forEach((button) => {{
        if (button.dataset.boundStop === '1') return;
        button.dataset.boundStop = '1';
        button.addEventListener('click', async () => {{ await stopPlayback(); }});
      }});
    }}

    function bindCandidateTabs(root = document) {{
      root.querySelectorAll('[data-candidate-tab]').forEach((button) => {{
        if (button.dataset.boundTab === '1') return;
        button.dataset.boundTab = '1';
        button.addEventListener('click', () => {{ setActiveCandidate(button.dataset.candidateTab); }});
      }});
    }}

    async function rerollBar(form) {{
      const candidateIndex = form.querySelector('[name="candidate_index"]').value;
      const barIndex = form.querySelector('[name="bar_index"]').value;
      const tab = document.getElementById(`candidate-tab-${{candidateIndex}}`);
      const progress = document.getElementById(`candidate-progress-${{candidateIndex}}`);
      const errorNode = form.closest('.bar-card')?.querySelector('.inline-error') || form.closest('.bar')?.querySelector('.inline-error');
      const formData = new FormData(form);
      formData.set('fragment', '1');
      try {{
        const response = await fetch('/reroll-bar', {{ method: 'POST', body: formData }});
        const html = await response.text();
        if (!response.ok) throw new Error(html || `Reroll failed: ${{response.status}}`);
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const nextTab = doc.querySelector('[data-fragment="candidate-tab"] > *');
        const nextProgress = doc.querySelector('[data-fragment="candidate-progress"] > *');
        const nextBar = doc.querySelector('[data-fragment="bar-card"] > *');
        if (nextTab && tab) {{ tab.replaceWith(nextTab); bindCandidateTabs(document); }}
        if (nextProgress && progress) progress.replaceWith(nextProgress);
        const currentBar = document.getElementById(`candidate-${{candidateIndex}}-bar-${{barIndex}}`);
        if (nextBar && currentBar) {{ currentBar.replaceWith(nextBar); bindPreviewButtons(document); bindRerollForms(document); }}
      }} catch (error) {{
        if (errorNode) {{ errorNode.hidden = false; errorNode.textContent = error instanceof Error ? error.message : String(error); }}
      }}
    }}

    async function setBarChord(form) {{
      const candidateIndex = form.querySelector('[name="candidate_index"]').value;
      const barIndex = form.querySelector('[name="bar_index"]').value;
      const tab = document.getElementById(`candidate-tab-${{candidateIndex}}`);
      const progress = document.getElementById(`candidate-progress-${{candidateIndex}}`);
      const errorNode = form.closest('.bar-card')?.querySelector('.inline-error');
      const formData = new FormData(form);
      formData.set('fragment', '1');
      try {{
        const response = await fetch('/timeline/chord', {{ method: 'POST', body: formData }});
        const html = await response.text();
        if (!response.ok) throw new Error(html || `Update failed: ${{response.status}}`);
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const nextTab = doc.querySelector('[data-fragment="candidate-tab"] > *');
        const nextProgress = doc.querySelector('[data-fragment="candidate-progress"] > *');
        const nextBar = doc.querySelector('[data-fragment="bar-card"] > *');
        if (nextTab && tab) {{ tab.replaceWith(nextTab); bindCandidateTabs(document); }}
        if (nextProgress && progress) progress.replaceWith(nextProgress);
        const currentBar = document.getElementById(`candidate-${{candidateIndex}}-bar-${{barIndex}}`);
        if (nextBar && currentBar) {{ currentBar.replaceWith(nextBar); bindPreviewButtons(document); bindRerollForms(document); }}
      }} catch (error) {{
        if (errorNode) {{ errorNode.hidden = false; errorNode.textContent = error instanceof Error ? error.message : String(error); }}
      }}
    }}

    function bindRerollForms(root = document) {{
      root.querySelectorAll('[data-reroll-bar-form]').forEach((form) => {{
        if (form.dataset.boundReroll === '1') return;
        form.dataset.boundReroll = '1';
        form.addEventListener('submit', async (event) => {{ event.preventDefault(); await rerollBar(form); }});
      }});
      root.querySelectorAll('[data-set-chord-form]').forEach((form) => {{
        if (form.dataset.boundSetChord === '1') return;
        form.dataset.boundSetChord = '1';
        form.addEventListener('submit', async (event) => {{
          event.preventDefault();
          const input = form.querySelector('input[name="chord"]');
          if (!input || !input.value.trim()) return;
          await setBarChord(form);
        }});
      }});
    }}

    if (volumeSlider) volumeSlider.addEventListener('input', (event) => setPreviewVolume(event.target.value));
    document.querySelectorAll('[data-track-toggle]').forEach((button) => button.addEventListener('click', () => setTrackMuted(button.dataset.trackToggle, !mutedTracks.has(button.dataset.trackToggle))));
    bindPreviewButtons(document);
    bindStopButtons(document);
    bindCandidateTabs(document);
    bindRerollForms(document);
    const initialCandidate = document.querySelector('[data-candidate-tab].active')?.dataset.candidateTab;
    if (initialCandidate) setActiveCandidate(initialCandidate);
    window.addEventListener('beforeunload', () => {{ stopPlayback(); }});
  </script>
</body>
</html>"""

    @staticmethod
    def _respond_html(start_response: Callable, status: str, body: str):
        payload = body.encode("utf-8")
        headers = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(payload)))]
        start_response(status, headers)
        return [payload]

    @staticmethod
    def _respond_text(start_response: Callable, status: str, body: str):
        payload = body.encode("utf-8")
        headers = [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(payload)))]
        start_response(status, headers)
        return [payload]


def _active_candidate_index(candidates: list, batch_meta: dict[str, object] | None) -> int:
    if batch_meta:
        selected_option = batch_meta.get("selected_option")
        if isinstance(selected_option, int):
            return selected_option
    if candidates:
        value = candidates[0].metadata.get("candidate_index")
        return int(value) if value is not None else 1
    return 1


def _candidate_tab(result, active_index: int) -> str:
    meta = result.metadata
    candidate_index = int(meta.get("candidate_index") or 1)
    active = candidate_index == active_index
    tags = " ".join(str(tag) for tag in meta.get("style_tags", [])[:3])
    return f"""
    <button type="button" id="candidate-tab-{candidate_index}" class="candidate-tab {'active' if active else ''}" data-candidate-tab="candidate-{candidate_index}" data-candidate-index="{candidate_index}">
      <div class="candidate-tab-header">
        <div>
          <div class="mini">Option {candidate_index:02d}</div>
          <strong>{html.escape(str(meta.get('progression_label', 'Candidate')))}</strong>
        </div>
        <span class="mini">Seed {html.escape(str(meta.get('candidate_seed')))}</span>
      </div>
      <div class="progression">{html.escape(str(meta.get('full_progression_text', meta.get('progression_label', ''))))}</div>
      <div class="micro">
        <span>{html.escape(str(meta.get('key')))}</span>
        <span>{html.escape(str(meta.get('tempo')))} BPM</span>
        <span>{html.escape(str(meta.get('drum_pattern')))}</span>
        <span>{html.escape(str(meta.get('bass_pattern')))}</span>
        <span>{html.escape(tags or 'No tags')}</span>
      </div>
    </button>
    """


def _candidate_progress_header(result, batch_meta: dict[str, object] | None) -> str:
    meta = result.metadata
    candidate_index = int(meta.get("candidate_index") or 1)
    selected_option = None if not batch_meta else batch_meta.get("selected_option")
    selected = selected_option == meta.get("candidate_index")
    tags = ''.join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in meta.get("style_tags", []))
    selected_html = '<div class="selected-mark">Selected Candidate</div>' if selected else ''
    return f"""
        <div class="progression-block" id="candidate-progress-{candidate_index}" data-candidate-progress="{candidate_index}">
          <div class="label">Full progression</div>
          <div class="progression-text">{html.escape(str(meta.get('full_progression_text', meta.get('progression_label', 'Candidate'))))}</div>
          <div class="tags">{tags}</div>
          {selected_html}
          <p class="path">{html.escape(str(result.output_dir))}</p>
        </div>
    """


def _candidate_detail(result, batch_meta: dict[str, object] | None, active_index: int, app=None) -> str:
    def _t(key: str) -> str:
        return app.t(key) if app is not None else translate(key, "en")
    meta = result.metadata
    candidate_index = int(meta.get("candidate_index") or 1)
    active = candidate_index == active_index
    batch_dir = Path(result.output_dir).parent
    preview_path = Path(result.output_dir) / str(meta.get("preview_file", "full_arrangement.mid"))
    preview_url = f"/files?path={quote(str(preview_path))}"
    preview_url_escaped = html.escape(preview_url)
    tempo = int(meta.get("tempo") or 120)
    file_list = ''.join(f'<li><code>{html.escape(path.name)}</code></li>' for path in result.files)
    timeline = _timeline_blocks(meta.get("bar_summary", []), batch_dir, candidate_index, preview_url_escaped, tempo, str(meta.get("bar_action_label", "Reroll Harmony")))
    selected_option = None if not batch_meta else batch_meta.get("selected_option")
    selected = selected_option == meta.get("candidate_index")
    audio_panel = _audio_preview_panel(Path(result.output_dir), return_to="/", soundfont_label=None, app=app)
    default_save_name = str(meta.get("text") or meta.get("progression_label") or f"Option {candidate_index:02d}")[:60]
    select_form = f"""
      <form method="post" action="/select">
        <input type="hidden" name="batch_dir" value="{html.escape(str(batch_dir))}">
        <input type="hidden" name="candidate_index" value="{html.escape(str(meta.get('candidate_index')))}">
        <button type="submit" class="select-btn {'secondary' if selected else ''}">{html.escape(_t('btn_select'))}</button>
      </form>
      <form method="post" action="/library/save" class="save-form">
        <input type="hidden" name="batch_dir" value="{html.escape(str(batch_dir))}">
        <input type="hidden" name="candidate_index" value="{html.escape(str(meta.get('candidate_index')))}">
        <input type="text" name="name" placeholder="{html.escape(_t('save_name_placeholder'))}" value="{html.escape(default_save_name)}" required>
        <button type="submit" class="ghost">{html.escape(_t('btn_save_to_library'))}</button>
      </form>
    """
    return f"""
    <article class="panel candidate-detail {'active' if active else ''}" data-candidate-detail="candidate-{candidate_index}" id="candidate-{candidate_index}">
      <section class="detail-hero">
        {_candidate_progress_header(result, batch_meta)}
        <div class="detail-meta">
          <div class="meta-card"><span>Progression Label</span><strong>{html.escape(str(meta.get('progression_label')))}</strong></div>
          <div class="meta-card"><span>Seed</span><strong>{html.escape(str(meta.get('candidate_seed')))}</strong></div>
          <div class="meta-card"><span>Tempo</span><strong>{html.escape(str(meta.get('tempo')))} BPM</strong></div>
          <div class="meta-card"><span>Key</span><strong>{html.escape(str(meta.get('key')))}</strong></div>
          <div class="meta-card"><span>Chord Density</span><strong>{html.escape(str(meta.get('resolved_chord_density')))}</strong></div>
          <div class="meta-card"><span>Melody Density</span><strong>{html.escape(str(meta.get('resolved_melody_density')))}</strong></div>
          <div class="meta-card"><span>Chord Rhythm</span><strong>{html.escape(str(meta.get('resolved_chord_rhythm_style')))}</strong></div>
          <div class="meta-card"><span>Humanize</span><strong>{html.escape(str(meta.get('resolved_humanize') or 'off'))}</strong></div>
          <div class="meta-card"><span>Swing</span><strong>{html.escape(str(meta.get('resolved_swing') or 'off'))}</strong></div>
          <div class="meta-card"><span>Drum Dynamics</span><strong>{html.escape(str(meta.get('resolved_drum_dynamics') or 'off'))}</strong></div>
          <div class="meta-card"><span>Harmony Spice</span><strong>{html.escape(str(meta.get('resolved_harmony_spice') or 'off'))}</strong></div>
          <div class="meta-card"><span>Section Dyn.</span><strong>{html.escape(str(meta.get('resolved_section_dynamics') or 'off'))}</strong></div>
          <div class="meta-card"><span>Modulate</span><strong>{html.escape(str(meta.get('resolved_modulate') or 'off'))}</strong></div>
          <div class="meta-card"><span>Drums</span><strong>{html.escape(str(meta.get('drum_pattern')))}</strong></div>
          <div class="meta-card"><span>Bass</span><strong>{html.escape(str(meta.get('bass_pattern')))}</strong></div>
        </div>
      </section>
      <section class="detail-grid">
        <div class="panel">
          <h3>{html.escape(_t('files_actions'))}</h3>
          <div class="card-actions">
            <button type="button" class="ghost" data-preview-url="{html.escape(preview_url)}">{html.escape(_t('btn_play'))}</button>
            <button type="button" class="ghost" data-stop disabled>{html.escape(_t('btn_stop'))}</button>
            {select_form}
          </div>
          <ul class="files">{file_list}</ul>
          {audio_panel}
        </div>
        <div class="panel timeline-panel">
          <div class="timeline-head">
            <h3>{html.escape(str(meta.get("timeline_title", "Harmony Timeline")))}</h3>
            <p>{html.escape(str(meta.get("timeline_description", "Each bar shows the chosen chord, representative melody tones, and how much of the melody sits inside the chord tones.")))}</p>
          </div>
          <div class="timeline-grid">{timeline}</div>
        </div>
      </section>
    </article>
    """


def _timeline_blocks(bar_summary: list[dict[str, object]], batch_dir: Path, candidate_index: int, preview_url: str, tempo: int, action_label: str) -> str:
    if not bar_summary:
        return '<div class="bar-card"><div class="bar-meta">No timeline data available.</div></div>'
    cards = []
    for bar in bar_summary:
        cards.append(_bar_card(bar, batch_dir, candidate_index, preview_url, tempo, action_label))
    return ''.join(cards)


def _bar_card(bar: dict[str, object], batch_dir: Path, candidate_index: int, preview_url: str, tempo: int, action_label: str) -> str:
    percent = int(bar.get("matching_percent", 0) or 0)
    melody = ", ".join(str(value) for value in bar.get("representative_melody_pitches", [])) or "-"
    chord_tones = ", ".join(str(value) for value in bar.get("chord_tones", [])) or "-"
    degree_label = str(bar.get("degree_label") or "-")
    degree_text = f"Degree {degree_label}"
    start_tick = int(bar.get("start_tick") or 0)
    end_tick = int(bar.get("end_tick") or start_tick)
    bar_index = int(bar.get("bar_index") or 0)
    reroll_nonce = uuid.uuid4().int % 1_000_000
    recently_updated = bool(bar.get("recently_updated"))
    chord_events = bar.get("chord_events", [])
    if chord_events:
        chip_parts = []
        for event in chord_events:
            tooltip = ", ".join(str(tone) for tone in event.get("chord_tones", [])) or "-"
            degree_value = event.get("degree")
            if degree_value:
                tooltip = f"Degree {degree_value} | {tooltip}"
            chip_parts.append(
                f'<span class="chord-chip" title="{html.escape(tooltip)}">{html.escape(str(event.get("chord_name", "-")))}</span>'
            )
        chord_events_html = '<div class="chord-chip-row">' + ''.join(chip_parts) + '</div>'
    else:
        fallback_tooltip = chord_tones
        if degree_label != '-':
            fallback_tooltip = f"Degree {degree_label} | {fallback_tooltip}"
        chord_events_html = f'<div class="chord-chip-row"><span class="chord-chip" title="{html.escape(fallback_tooltip)}">{html.escape(str(bar.get("chord_name", "No chord")))}</span></div>'
    density_control_html = ''
    if action_label == 'Reroll Harmony':
        current_density = str(min(3, max(1, len(chord_events) or 1)))
        density_control_html = _select_field_html(
            'Density',
            'bar_chord_density',
            current_density,
            [('1', '1 chord'), ('2', '2 chords'), ('3', '3 chords')],
            css_class='bar-density-select',
        )
    updated_pill = "<div class=\"updated-pill\">Recently Updated</div>" if recently_updated else ""
    return f"""
            <div class="bar-card {'recently-updated' if recently_updated else ''}" id="candidate-{candidate_index}-bar-{bar_index}" data-bar-card="{bar_index}" data-candidate-index="{candidate_index}">
              <div class="bar-top">
                <div>
                  <div class="bar-index">Bar {html.escape(str(bar_index))}</div>
                  <div class="chord-name">{html.escape(str(bar.get('chord_name', 'No chord')))}</div>
                </div>
                <div class="bar-degree">{html.escape(degree_text)}</div>
              </div>
              <div class="timeline-lane">
                <div class="lane-row">
                  <div class="lane-label">Chord span</div>
                  <div class="lane-track"><div class="lane-fill full"></div></div>
                </div>
                <div class="lane-row">
                  <div class="lane-label">Melody match</div>
                  <div class="lane-track"><div class="lane-fill match" style="width: {percent}%;"></div></div>
                </div>
              </div>
              <div class="match-pill">{percent}% match</div>
              {updated_pill}
              <div class="bar-meta">
                {chord_events_html}
                <div><strong>Melody focus</strong> {html.escape(melody)}</div>
              </div>
              <div class="bar-actions">
                <button type="button" class="ghost bar-action-btn" data-preview-url="{preview_url}" data-preview-start="{start_tick}" data-preview-end="{end_tick}" data-preview-tempo="{tempo}">Play Bar</button>
                <form method="post" action="/reroll-bar" data-reroll-bar-form>
                  <input type="hidden" name="batch_dir" value="{html.escape(str(batch_dir))}">
                  <input type="hidden" name="candidate_index" value="{candidate_index}">
                  <input type="hidden" name="bar_index" value="{bar_index}">
                  <input type="hidden" name="reroll_nonce" value="{reroll_nonce}">
                  {density_control_html}
                  <button type="submit" class="secondary bar-action-btn">{html.escape(action_label)}</button>
                </form>
              </div>
              <form method="post" action="/timeline/chord" class="bar-chord-form" data-set-chord-form>
                <input type="hidden" name="batch_dir" value="{html.escape(str(batch_dir))}">
                <input type="hidden" name="candidate_index" value="{candidate_index}">
                <input type="hidden" name="bar_index" value="{bar_index}">
                <input type="text" name="chord" class="bar-chord-input" placeholder="Am, F, G7, Cmaj7..." autocomplete="off" spellcheck="false">
                <button type="submit" class="ghost bar-chord-btn">Set Chord</button>
              </form>
              <div class="inline-error" hidden></div>
            </div>
    """


def _lang_toggle_html(current: str, return_to: str) -> str:
    other = "ko" if current == "en" else "en"
    label = "한국어" if other == "ko" else "EN"
    extra_links = (
        '<a class="topnav-link" href="/library">Library</a>'
        '<a class="topnav-link" href="/settings">Settings</a>'
    )
    if current == "ko":
        extra_links = (
            '<a class="topnav-link" href="/library">라이브러리</a>'
            '<a class="topnav-link" href="/settings">설정</a>'
        )
    return f"""<div class="topnav">
      <div class="topnav-links">{extra_links}</div>
      <form method="post" action="/lang" class="lang-form">
        <input type="hidden" name="lang" value="{other}">
        <input type="hidden" name="return_to" value="{html.escape(return_to)}">
        <button type="submit" class="lang-btn">{html.escape(label)}</button>
      </form>
    </div>"""


def _audio_preview_panel(candidate_dir: Path, return_to: str, soundfont_label: str | None = None, app=None) -> str:
    def _t(key: str) -> str:
        return app.t(key) if app is not None else translate(key, "en")
    sf2 = resolve_soundfont()
    binary = resolve_fluidsynth_binary()
    ready = sf2 is not None and binary is not None
    if not ready:
        missing = []
        if sf2 is None:
            missing.append("a SoundFont (.sf2) — set <code>PY2FL_SOUNDFONT</code> or pass <code>--soundfont</code>")
        if binary is None:
            missing.append("the <code>fluidsynth</code> binary on PATH")
        return (
            '<div class="audio-panel"><h4>Audio Preview</h4>'
            f'<p class="hint">Audio render needs {", and ".join(missing)}. Falling back to in-browser MIDI preview.</p>'
            '</div>'
        )
    preview_dir = Path(candidate_dir) / PREVIEW_DIRNAME
    mix_wav = preview_dir / "full_arrangement.wav"
    has_mix = mix_wav.is_file()
    label = soundfont_label or sf2.name
    if not has_mix:
        return f"""<div class="audio-panel">
          <h4>{html.escape(_t('audio_preview_heading'))}</h4>
          <p class="hint">{html.escape(_t('audio_hint_soundfont'))}: <code>{html.escape(label)}</code></p>
          <form method="post" action="/preview/render">
            <input type="hidden" name="candidate_dir" value="{html.escape(str(candidate_dir))}">
            <input type="hidden" name="return_to" value="{html.escape(return_to)}">
            <button type="submit">{html.escape(_t('btn_render_audio'))}</button>
          </form>
        </div>"""
    mix_url = f"/files?path={quote(str(mix_wav))}"
    stems_html = []
    for stem in ("melody", "chords", "bass", "drums"):
        wav = preview_dir / f"{stem}.wav"
        if wav.is_file():
            stems_html.append(
                f'<a class="audio-stem" href="/files?path={quote(str(wav))}" download>{stem}.wav</a>'
            )
    rerender = f"""<form method="post" action="/preview/render" class="audio-rerender">
        <input type="hidden" name="candidate_dir" value="{html.escape(str(candidate_dir))}">
        <input type="hidden" name="return_to" value="{html.escape(return_to)}">
        <input type="hidden" name="force" value="1">
        <button type="submit" class="ghost">{html.escape(_t('btn_rerender'))}</button>
      </form>"""
    return f"""<div class="audio-panel">
      <h4>{html.escape(_t('audio_preview_heading'))}</h4>
      <p class="hint">{html.escape(_t('audio_hint_soundfont'))}: <code>{html.escape(label)}</code></p>
      <audio controls preload="metadata" src="{html.escape(mix_url)}"></audio>
      <div class="audio-stems">{''.join(stems_html)}</div>
      {rerender}
    </div>"""


def _library_entry_row(entry: dict[str, object], app=None) -> str:
    def _t(key: str) -> str:
        return app.t(key) if app is not None else translate(key, "en")
    entry_id = str(entry.get("id") or "")
    name = str(entry.get("name") or entry_id)
    saved_at = str(entry.get("saved_at") or "-")
    progression = str(entry.get("full_progression_text") or entry.get("progression_label") or "-")
    text = str(entry.get("text") or "")
    style_tags = entry.get("style_tags") or []
    if isinstance(style_tags, list):
        tags_html = "".join(f'<span class="lib-tag">{html.escape(str(tag))}</span>' for tag in style_tags[:5])
    else:
        tags_html = ""
    controls = entry.get("controls") or {}
    if isinstance(controls, dict):
        active_controls = [(k, v) for k, v in controls.items() if v not in (None, "off", "auto", "")]
    else:
        active_controls = []
    controls_summary = ", ".join(f"{k}: {v}" for k, v in active_controls) or "defaults"
    text_block = html.escape(text) if text else _t('lib_no_text')
    return f"""
    <article class="panel lib-card">
      <h3>{html.escape(name)}</h3>
      <div class="lib-meta">
        <div><span>{html.escape(_t('lib_saved_at'))}</span><strong>{html.escape(saved_at)}</strong></div>
        <div><span>{html.escape(_t('lib_mode'))}</span><strong>{html.escape(str(entry.get('input_mode') or '-'))}</strong></div>
        <div><span>{html.escape(_t('label_tempo'))}</span><strong>{html.escape(str(entry.get('tempo') or '-'))}</strong></div>
        <div><span>{html.escape(_t('label_key'))}</span><strong>{html.escape(str(entry.get('key') or '-'))}</strong></div>
        <div><span>{html.escape(_t('label_bars'))}</span><strong>{html.escape(str(entry.get('bars') or '-'))}</strong></div>
        <div><span>{html.escape(_t('label_genre'))}</span><strong>{html.escape(str(entry.get('genre') or '-'))}</strong></div>
      </div>
      <p class="lib-prompt">{text_block}</p>
      <p class="lib-prompt"><strong>{html.escape(_t('lib_progression'))}:</strong> {html.escape(progression)}</p>
      <div class="lib-tags">{tags_html}</div>
      <p class="lib-prompt"><strong>{html.escape(_t('lib_controls'))}:</strong> {html.escape(controls_summary)}</p>
      <div class="lib-actions">
        <a class="btn ghost" href="/library/{quote(entry_id)}">{html.escape(_t('lib_open'))}</a>
        <form method="post" action="/library/continue">
          <input type="hidden" name="entry_id" value="{html.escape(entry_id)}">
          <button type="submit">{html.escape(_t('lib_continue'))}</button>
        </form>
        <form method="post" action="/library/delete" onsubmit="return confirm('{_t('lib_confirm_delete')}');">
          <input type="hidden" name="entry_id" value="{html.escape(entry_id)}">
          <button type="submit" class="btn danger">{html.escape(_t('lib_delete'))}</button>
        </form>
      </div>
    </article>
    """


def _state_from_library_entry(entry: dict[str, object]) -> dict[str, str]:
    controls = entry.get("controls") or {}
    if not isinstance(controls, dict):
        controls = {}
    state = {
        "text": _string_value(entry.get("text")),
        "tempo": _string_value(entry.get("tempo")),
        "key": _string_value(entry.get("key")),
        "genre": _string_value(entry.get("genre")),
        "bars": _string_value(entry.get("bars")),
        "chord_density": _string_value(controls.get("chord_density")) or "auto",
        "melody_density": _string_value(controls.get("melody_density")) or "auto",
        "chord_rhythm_style": _string_value(controls.get("chord_rhythm_style")) or "auto",
        "humanize": _string_value(controls.get("humanize")) or "off",
        "swing": _string_value(controls.get("swing")) or "off",
        "drum_dynamics": _string_value(controls.get("drum_dynamics")) or "off",
        "harmony_spice": _string_value(controls.get("harmony_spice")) or "off",
        "section_dynamics": _string_value(controls.get("section_dynamics")) or "off",
        "modulate": _string_value(controls.get("modulate")) or "off",
        "seed": _string_value(entry.get("candidate_seed")),
        "count": "4",
        "melody_source": _string_value(entry.get("source_melody")),
        "chord_progression": _string_value(entry.get("source_progression") or entry.get("full_progression_text")),
    }
    return state


def _state_from_form(form: cgi.FieldStorage, chords_mode: bool = False) -> dict[str, str]:
    state = {
        "text": _optional_text(form.getfirst("text")) or "",
        "tempo": _optional_text(form.getfirst("tempo")) or "",
        "key": _optional_text(form.getfirst("key")) or "",
        "genre": _optional_text(form.getfirst("genre")) or "",
        "bars": _optional_text(form.getfirst("bars")) or "",
        "chord_density": _optional_text(form.getfirst("chord_density")) or "auto",
        "melody_density": _optional_text(form.getfirst("melody_density")) or "auto",
        "chord_rhythm_style": _optional_text(form.getfirst("chord_rhythm_style")) or "auto",
        "humanize": _optional_text(form.getfirst("humanize")) or "off",
        "swing": _optional_text(form.getfirst("swing")) or "off",
        "drum_dynamics": _optional_text(form.getfirst("drum_dynamics")) or "off",
        "harmony_spice": _optional_text(form.getfirst("harmony_spice")) or "off",
        "section_dynamics": _optional_text(form.getfirst("section_dynamics")) or "off",
        "modulate": _optional_text(form.getfirst("modulate")) or "off",
        "seed": _optional_text(form.getfirst("seed")) or "",
        "count": _optional_text(form.getfirst("count")) or "4",
        "melody_source": _optional_text(form.getfirst("melody_source")) or "",
    }
    if chords_mode:
        state["chord_progression"] = _optional_text(form.getfirst("chord_progression")) or ""
    return state


def _apply_suggestion_to_state(state: dict[str, str], fields: dict[str, object]) -> dict[str, str]:
    out = dict(state)
    for key in ("tempo", "bars"):
        if fields.get(key) is not None:
            out[key] = str(fields[key])
    for key in ("key", "genre"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    for key in (
        "chord_density",
        "melody_density",
        "chord_rhythm_style",
        "humanize",
        "swing",
        "drum_dynamics",
        "harmony_spice",
        "section_dynamics",
        "modulate",
    ):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _state_from_request(request: GenerationRequest, count: int) -> dict[str, str]:
    return {
        "text": request.text or "",
        "tempo": "" if request.tempo is None else str(request.tempo),
        "key": request.key or "",
        "genre": request.genre or "",
        "bars": "" if request.bars is None else str(request.bars),
        "chord_density": request.chord_density or "auto",
        "melody_density": request.melody_density or "auto",
        "chord_rhythm_style": request.chord_rhythm_style or "auto",
        "humanize": request.humanize or "off",
        "swing": request.swing or "off",
        "drum_dynamics": request.drum_dynamics or "off",
        "harmony_spice": request.harmony_spice or "off",
        "section_dynamics": request.section_dynamics or "off",
        "modulate": request.modulate or "off",
        "seed": "" if request.seed is None else str(request.seed),
        "count": str(count),
        "melody_source": "" if request.melody_midi_path is None else str(request.melody_midi_path),
        "melody_offset_beats": _format_offset_beats(request.melody_offset_beats or 0.0),
    }


def _format_offset_beats(value: float) -> str:
    if value == 0:
        return "0"
    rounded = round(value * 4) / 4
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _state_from_chords_request(request: GenerationRequest, count: int) -> dict[str, str]:
    return {
        "text": request.text or "",
        "chord_progression": request.chord_progression or "",
        "tempo": "" if request.tempo is None else str(request.tempo),
        "key": request.key or "",
        "genre": request.genre or "",
        "bars": "" if request.bars is None else str(request.bars),
        "chord_density": request.chord_density or "auto",
        "melody_density": request.melody_density or "auto",
        "chord_rhythm_style": request.chord_rhythm_style or "auto",
        "humanize": request.humanize or "off",
        "swing": request.swing or "off",
        "drum_dynamics": request.drum_dynamics or "off",
        "harmony_spice": request.harmony_spice or "off",
        "section_dynamics": request.section_dynamics or "off",
        "modulate": request.modulate or "off",
        "seed": "" if request.seed is None else str(request.seed),
        "count": str(count),
    }


def _state_from_batch_meta(batch_meta: dict[str, object], count: int) -> dict[str, str]:
    return {
        "text": _string_value(batch_meta.get("text")),
        "tempo": _string_value(batch_meta.get("tempo")),
        "key": _string_value(batch_meta.get("key")),
        "genre": _string_value(batch_meta.get("genre")),
        "bars": _string_value(batch_meta.get("bars")),
        "chord_density": _string_value(batch_meta.get("chord_density")) or "auto",
        "melody_density": _string_value(batch_meta.get("melody_density")) or "auto",
        "chord_rhythm_style": _string_value(batch_meta.get("chord_rhythm_style")) or "auto",
        "humanize": _string_value(batch_meta.get("humanize")) or "off",
        "swing": _string_value(batch_meta.get("swing")) or "off",
        "drum_dynamics": _string_value(batch_meta.get("drum_dynamics")) or "off",
        "harmony_spice": _string_value(batch_meta.get("harmony_spice")) or "off",
        "section_dynamics": _string_value(batch_meta.get("section_dynamics")) or "off",
        "modulate": _string_value(batch_meta.get("modulate")) or "off",
        "seed": _string_value(batch_meta.get("seed")),
        "count": _string_value(batch_meta.get("candidate_count")) or str(count),
        "melody_source": _string_value(batch_meta.get("source_melody")),
        "melody_offset_beats": _format_offset_beats(float(batch_meta.get("melody_offset_beats") or 0.0)),
    }


def _state_from_batch_chords(batch_meta: dict[str, object], count: int) -> dict[str, str]:
    return {
        "text": _string_value(batch_meta.get("text")),
        "chord_progression": _string_value(batch_meta.get("source_progression")),
        "tempo": _string_value(batch_meta.get("tempo")),
        "key": _string_value(batch_meta.get("key")),
        "genre": _string_value(batch_meta.get("genre")),
        "bars": _string_value(batch_meta.get("bars")),
        "chord_density": _string_value(batch_meta.get("chord_density")) or "auto",
        "melody_density": _string_value(batch_meta.get("melody_density")) or "auto",
        "chord_rhythm_style": _string_value(batch_meta.get("chord_rhythm_style")) or "auto",
        "humanize": _string_value(batch_meta.get("humanize")) or "off",
        "swing": _string_value(batch_meta.get("swing")) or "off",
        "drum_dynamics": _string_value(batch_meta.get("drum_dynamics")) or "off",
        "harmony_spice": _string_value(batch_meta.get("harmony_spice")) or "off",
        "section_dynamics": _string_value(batch_meta.get("section_dynamics")) or "off",
        "modulate": _string_value(batch_meta.get("modulate")) or "off",
        "seed": _string_value(batch_meta.get("seed")),
        "count": _string_value(batch_meta.get("candidate_count")) or str(count),
    }


def _is_chords_batch(batch_meta: dict[str, object] | None) -> bool:
    if not batch_meta:
        return False
    if batch_meta.get("generator_mode") == "melody_from_chords":
        return True
    return bool(batch_meta.get("source_progression"))


def _hidden_state_fields(state: dict[str, str] | None) -> str:
    if not state:
        return ""
    parts = []
    for key, value in state.items():
        parts.append(f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">')
    return ''.join(parts)


def _select_field_html(label: str, name: str, selected: str, options: list[tuple[str, str]], css_class: str = '') -> str:
    option_html = ''.join(
        f'<option value="{html.escape(value)}"{" selected" if value == selected else ""}>{html.escape(title)}</option>'
        for value, title in options
    )
    class_attr = f' class="{html.escape(css_class)}"' if css_class else ''
    return f'<label>{html.escape(label)}<select name="{html.escape(name)}"{class_attr}>{option_html}</select></label>'


def _resolve_melody_path(form: cgi.FieldStorage, upload_root: Path) -> Path | None:
    melody_field = form["melody_midi"] if "melody_midi" in form else None
    if melody_field is not None and getattr(melody_field, "filename", None):
        filename = Path(melody_field.filename).name or "upload.mid"
        melody_path = upload_root / f"{uuid.uuid4().hex}_{filename}"
        melody_path.write_bytes(melody_field.file.read())
        return melody_path
    melody_source = _optional_text(form.getfirst("melody_source"))
    if melody_source:
        path = Path(melody_source)
        if path.exists():
            return path
    return None


def _load_candidate_results_from_batch(batch_meta: dict[str, object]) -> list:
    from .models import GenerationResult

    results = []
    for candidate in batch_meta.get("candidates", []):
        output_dir = Path(str(candidate.get("output_dir")))
        meta_path = output_dir / "meta.json"
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        metadata["batch_dir"] = str(output_dir.parent)
        metadata["option_name"] = candidate.get("option_name")
        files = [output_dir / name for name in metadata.get("files", [])] + [meta_path]
        results.append(GenerationResult(output_dir=output_dir, files=files, metadata=metadata))
    return results


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return int(value)


def _optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _normalize_auto_option(value: str | None) -> str | None:
    cleaned = _optional_text(value)
    if cleaned in {None, 'auto'}:
        return None
    return cleaned


def _normalize_humanize_option(value: str | None) -> str | None:
    cleaned = _optional_text(value)
    if cleaned in {None, ''}:
        return None
    if cleaned in {'off', 'low', 'med', 'high', 'auto'}:
        return cleaned
    return None


def _normalize_bar_density_option(value: str | None) -> str | None:
    cleaned = _optional_text(value)
    if cleaned in {None, '1', '2', '3'}:
        return cleaned
    return None


def _string_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    output_dir: Path = Path("exports"),
    library_dir: Path | None = None,
    soundfont: Path | str | None = None,
    fluidsynth_binary: str | None = None,
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    app = Py2FLWebApp(
        output_dir=output_dir,
        library_dir=library_dir,
        soundfont=soundfont,
        fluidsynth_binary=fluidsynth_binary,
    )
    with make_server(host, port, app) as server:
        print(f"py2fl web UI running at http://{host}:{port}")
        print(f"Output directory: {output_dir.resolve()}")
        print(f"Library directory: {app.library_dir.resolve()}")
        sf2 = app._resolved_soundfont()
        binary = app._resolved_fluidsynth()
        if sf2 and binary:
            print(f"Audio preview ready (SoundFont: {sf2}, fluidsynth: {binary})")
        else:
            print("Audio preview disabled (set PY2FL_SOUNDFONT and install fluidsynth to enable).")
        server.serve_forever()


def main() -> int:
    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
