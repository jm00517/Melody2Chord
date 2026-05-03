from __future__ import annotations

import cgi
import html
import json
import mimetypes
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote
import uuid
from wsgiref.simple_server import make_server

from .generator import BATCH_META_FILENAME, generate_candidates, load_batch_meta, reroll_candidate_bar, select_candidate
from .models import GenerationRequest

TITLE = "py2fl Studio"
TRACK_NAMES = ("Melody", "Chords", "Bass", "Drums")


class Py2FLWebApp:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def __call__(self, environ: dict, start_response: Callable):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")

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
        seed = _optional_int(form.getfirst("seed"))
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
            seed=seed,
            output_dir=self.output_dir,
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
            "seed": _string_value(batch_meta.get("seed")),
            "count": _string_value(batch_meta.get("candidate_count")) or str(len(candidates)),
            "melody_source": _string_value(batch_meta.get("source_melody")),
        }
        if _is_chords_batch(batch_meta):
            return self._render_chords_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_batch_chords(batch_meta, len(candidates)))
        return self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=form_state)


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
            "seed": _string_value(batch_meta.get("seed")),
            "count": _string_value(batch_meta.get("candidate_count")) or str(len(candidates)),
            "melody_source": _string_value(batch_meta.get("source_melody")),
        }
        if _is_chords_batch(batch_meta):
            return self._render_chords_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_batch_chords(batch_meta, len(candidates)))
        return self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=form_state)


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
    ) -> str:
        state = form_state or {}
        error_html = ""
        if error:
            error_html = f'<section class="panel error"><h2>Error</h2><p>{html.escape(error)}</p></section>'

        reroll_controls = ""
        comparison_bar = ""
        candidate_details = ""
        active_index = _active_candidate_index(candidates or [], batch_meta)
        if candidates:
            reroll_controls = f"""
            <div class="actions">
              <form method="post" action="/generate">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="all"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit">Reroll All</button></form>
              <form method="post" action="/generate">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="chords"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit" class="secondary">Reroll Chords</button></form>
            </div>
            """
            comparison_bar = '<section class="candidate-overview"><div class="overview-head"><h2>Candidate Overview</h2><p>Compare the full harmonic path first, then open one option in detail below.</p></div><div class="candidate-tabs">' + ''.join(_candidate_tab(result, active_index) for result in candidates) + '</div></section>'
            candidate_details = '<section class="candidate-details">' + ''.join(_candidate_detail(result, batch_meta, active_index) for result in candidates) + '</section>'

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
    @media (max-width: 1100px) {{ .detail-hero {{ grid-template-columns: 1fr; }} .detail-grid {{ grid-template-columns: 1fr; }} .layout {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} .mute-grid {{ grid-template-columns: 1fr; }} .candidate-tabs {{ grid-template-columns: 1fr; }} .timeline-grid {{ grid-template-columns: 1fr; }} .detail-meta {{ grid-template-columns: 1fr; }} .overview-head {{ display: grid; }} .progression-text {{ font-size: 28px; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div class="eyebrow">FL Studio MIDI Generator</div>
      <h1>Generate. Compare. Listen. Choose.</h1>
      <p class="lead">Create multiple arrangements from the same idea, compare the full progression at a glance, then inspect one candidate in detail with melody-to-chord matching all the way through.</p>
    </header>
    <section class="layout">
      <section class="panel">
        <h2>Create Candidate Set</h2>
        <form method="post" action="/generate" enctype="multipart/form-data">
          <label>
            Text Prompt or Lyrics
            <textarea name="text" placeholder="Example: dreamy rnb night drive with airy chords">{html.escape(state.get("text", ""))}</textarea>
          </label>
          <label>
            Melody MIDI Upload
            <input type="file" name="melody_midi" accept=".mid,.midi">
          </label>
          <div class="grid">
            <label>Tempo<input type="number" name="tempo" min="30" max="300" placeholder="auto" value="{html.escape(state.get("tempo", ""))}"></label>
            <label>Key<input type="text" name="key" placeholder="Example: F#, A minor" value="{html.escape(state.get("key", ""))}"></label>
            <label>Genre<input type="text" name="genre" placeholder="Example: trap, rnb, house" value="{html.escape(state.get("genre", ""))}"></label>
            <label>Bars<input type="number" name="bars" min="1" max="128" placeholder="auto" value="{html.escape(state.get("bars", ""))}"></label>
            {_select_field_html("Chord Density", "chord_density", state.get("chord_density", "auto"), [("auto", "Auto"), ("1", "1 per bar"), ("2", "2 per bar"), ("3", "3 per bar")])}
            {_select_field_html("Melody Density", "melody_density", state.get("melody_density", "auto"), [("auto", "Auto"), ("sparse", "Sparse"), ("normal", "Normal"), ("dense", "Dense"), ("xdense", "X-Dense")])}
            {_select_field_html("Chord Rhythm", "chord_rhythm_style", state.get("chord_rhythm_style", "auto"), [("auto", "Auto"), ("hold", "Hold"), ("stab", "Stab"), ("strum", "Strum")])}
            {_select_field_html("Humanize", "humanize", state.get("humanize", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html("Swing", "swing", state.get("swing", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html("Drum Dynamics", "drum_dynamics", state.get("drum_dynamics", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            <label>Seed<input type="number" name="seed" placeholder="optional" value="{html.escape(state.get("seed", ""))}"></label>
            <label>Options<input type="number" name="count" min="1" max="8" value="{html.escape(state.get("count", "4"))}"></label>
          </div>
          <input type="hidden" name="melody_source" value="{html.escape(state.get("melody_source", ""))}">
          <p class="hint">Enter text, a melody MIDI file, or both. The result view now shows the full chord path from start to finish plus a bar-by-bar melody match timeline.</p>
          <button type="submit">Generate Options</button>
        </form>
      </section>
      <aside class="panel">
        <h2>Session Controls</h2>
        <div class="session-controls">
          <div class="control-block">
            <div class="volume-row">
              <span class="volume-label">Preview Volume</span>
              <span class="volume-value" id="volume-value">20%</span>
            </div>
            <input class="volume-slider" id="volume-slider" type="range" min="0" max="100" value="20">
          </div>
          <div class="control-block">
            <div class="volume-label">Part Mutes</div>
            <div class="mute-grid">{mute_controls}</div>
          </div>
        </div>
        <div class="specs">
          <div class="spec"><strong>Candidate overview</strong>Use the top comparison bar to scan every option's progression before opening one in detail.</div>
          <div class="spec"><strong>Chord-to-melody mode</strong>Open <a href="/melody-from-chords">/melody-from-chords</a> to generate toplines from a fixed chord progression.</div>
          <div class="spec"><strong>Harmony timeline</strong>Each detailed view shows bar-by-bar chords, representative melody pitches, and a simple match percentage.</div>
          <div class="spec"><strong>Browser playback</strong>Each candidate previews its `full_arrangement.mid` file directly in the browser with a lightweight synth setup.</div>
          <div class="spec"><strong>Saved selection</strong>`Select This` stores the chosen option in <code>{BATCH_META_FILENAME}</code> inside the batch folder.</div>
          <div class="spec"><strong>Output root</strong>Files are written under {html.escape(str(self.output_dir))}, with batch folders and `option_01`, `option_02` style candidate directories.</div>
        </div>
      </aside>
    </section>
    {error_html}
    {reroll_controls}
    {comparison_bar}
    {candidate_details or '<section class="empty-state">Generate a candidate set to see the large comparison view and the melody/chord timeline.</section>'}
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

    async function rerollBar(form) {{
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
        const response = await fetch('/reroll-bar', {{ method: 'POST', body: formData }});
        const html = await response.text();
        if (!response.ok) {{
          throw new Error(html || `Reroll failed: ${{response.status}}`);
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

    function bindRerollForms(root = document) {{
      root.querySelectorAll('[data-reroll-bar-form]').forEach((form) => {{
        if (form.dataset.boundReroll === '1') return;
        form.dataset.boundReroll = '1';
        form.addEventListener('submit', async (event) => {{
          event.preventDefault();
          await rerollBar(form);
        }});
      }});
    }}

    bindPreviewButtons(document);
    bindStopButtons(document);
    bindCandidateTabs(document);
    bindRerollForms(document);

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
    ) -> str:
        state = form_state or {}
        error_html = ""
        if error:
            error_html = f'<section class="panel error"><h2>Error</h2><p>{html.escape(error)}</p></section>'

        reroll_controls = ""
        comparison_bar = ""
        candidate_details = ""
        active_index = _active_candidate_index(candidates or [], batch_meta)
        if candidates:
            reroll_controls = f"""
            <div class="actions">
              <form method="post" action="/generate-chords">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="all"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit">Reroll All</button></form>
              <form method="post" action="/generate-chords">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="melody"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit" class="secondary">Reroll Melody</button></form>
            </div>
            """
            comparison_bar = '<section class="candidate-overview"><div class="overview-head"><h2>Melody Candidates</h2><p>Compare toplines written against the same chord path, then open one candidate in detail below.</p></div><div class="candidate-tabs">' + ''.join(_candidate_tab(result, active_index) for result in candidates) + '</div></section>'
            candidate_details = '<section class="candidate-details">' + ''.join(_candidate_detail(result, batch_meta, active_index) for result in candidates) + '</section>'

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
    <header class="hero">
      <div class="eyebrow">FL Studio Melody Writer</div>
      <h1>Chord In. Melody Out.</h1>
      <p class="lead">Feed in a chord progression, generate multiple topline candidates, compare their contour, then reroll specific bars without changing the harmony.</p>
      <p><a href="/">Back to Arrangement Generator</a></p>
    </header>
    <section class="layout">
      <section class="panel">
        <h2>Generate Melody Candidates</h2>
        <form method="post" action="/generate-chords">
          <label>
            Chord Progression
            <textarea name="chord_progression" placeholder="Examples: 1-5-6-4 or Am-F-C-G">{html.escape(state.get("chord_progression", ""))}</textarea>
          </label>
          <label>
            Optional Style Prompt
            <textarea name="text" placeholder="Example: dreamy rnb topline with wide phrases">{html.escape(state.get("text", ""))}</textarea>
          </label>
          <div class="grid">
            <label>Tempo<input type="number" name="tempo" min="30" max="300" placeholder="auto" value="{html.escape(state.get("tempo", ""))}"></label>
            <label>Key<input type="text" name="key" placeholder="Optional for degree input, example: A minor" value="{html.escape(state.get("key", ""))}"></label>
            <label>Genre<input type="text" name="genre" placeholder="Example: trap, rnb, house" value="{html.escape(state.get("genre", ""))}"></label>
            <label>Bars<input type="number" name="bars" min="1" max="128" placeholder="default: token count" value="{html.escape(state.get("bars", ""))}"></label>
            {_select_field_html("Chord Density", "chord_density", state.get("chord_density", "auto"), [("auto", "Auto"), ("1", "1 per bar"), ("2", "2 per bar"), ("3", "3 per bar")])}
            {_select_field_html("Melody Density", "melody_density", state.get("melody_density", "auto"), [("auto", "Auto"), ("sparse", "Sparse"), ("normal", "Normal"), ("dense", "Dense"), ("xdense", "X-Dense")])}
            {_select_field_html("Chord Rhythm", "chord_rhythm_style", state.get("chord_rhythm_style", "auto"), [("auto", "Auto"), ("hold", "Hold"), ("stab", "Stab"), ("strum", "Strum")])}
            {_select_field_html("Humanize", "humanize", state.get("humanize", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html("Swing", "swing", state.get("swing", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            {_select_field_html("Drum Dynamics", "drum_dynamics", state.get("drum_dynamics", "off"), [("off", "Off"), ("low", "Low"), ("med", "Med"), ("high", "High"), ("auto", "Auto")])}
            <label>Seed<input type="number" name="seed" placeholder="optional" value="{html.escape(state.get("seed", ""))}"></label>
            <label>Options<input type="number" name="count" min="1" max="8" value="{html.escape(state.get("count", "4"))}"></label>
          </div>
          <p class="hint">Supports both degree notation and named chords. One token equals one bar by default.</p>
          <button type="submit">Generate Melodies</button>
        </form>
      </section>
      <aside class="panel">
        <h2>Session Controls</h2>
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

    function bindRerollForms(root = document) {{
      root.querySelectorAll('[data-reroll-bar-form]').forEach((form) => {{
        if (form.dataset.boundReroll === '1') return;
        form.dataset.boundReroll = '1';
        form.addEventListener('submit', async (event) => {{ event.preventDefault(); await rerollBar(form); }});
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


def _candidate_detail(result, batch_meta: dict[str, object] | None, active_index: int) -> str:
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
    select_form = f"""
      <form method="post" action="/select">
        <input type="hidden" name="batch_dir" value="{html.escape(str(batch_dir))}">
        <input type="hidden" name="candidate_index" value="{html.escape(str(meta.get('candidate_index')))}">
        <button type="submit" class="select-btn {'secondary' if selected else ''}">Select This</button>
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
          <div class="meta-card"><span>Drums</span><strong>{html.escape(str(meta.get('drum_pattern')))}</strong></div>
          <div class="meta-card"><span>Bass</span><strong>{html.escape(str(meta.get('bass_pattern')))}</strong></div>
        </div>
      </section>
      <section class="detail-grid">
        <div class="panel">
          <h3>Files and actions</h3>
          <div class="card-actions">
            <button type="button" class="ghost" data-preview-url="{html.escape(preview_url)}">Play</button>
            <button type="button" class="ghost" data-stop disabled>Stop</button>
            {select_form}
          </div>
          <ul class="files">{file_list}</ul>
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
              <div class="inline-error" hidden></div>
            </div>
    """


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
        "seed": "" if request.seed is None else str(request.seed),
        "count": str(count),
        "melody_source": "" if request.melody_midi_path is None else str(request.melody_midi_path),
    }


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
        "seed": "" if request.seed is None else str(request.seed),
        "count": str(count),
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


def run_server(host: str = "127.0.0.1", port: int = 8765, output_dir: Path = Path("exports")) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    app = Py2FLWebApp(output_dir=output_dir)
    with make_server(host, port, app) as server:
        print(f"py2fl web UI running at http://{host}:{port}")
        print(f"Output directory: {output_dir.resolve()}")
        server.serve_forever()


def main() -> int:
    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
