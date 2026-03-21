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

from .generator import BATCH_META_FILENAME, generate_candidates, load_batch_meta, select_candidate
from .models import GenerationRequest

TITLE = "py2fl Studio"


class Py2FLWebApp:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def __call__(self, environ: dict, start_response: Callable):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")

        if method == "GET" and path == "/":
            return self._respond_html(start_response, "200 OK", self._render_page())

        if method == "GET" and path == "/files":
            return self._serve_file(environ, start_response)

        if method == "POST" and path == "/generate":
            try:
                body = self._handle_generate(environ)
                return self._respond_html(start_response, "200 OK", body)
            except Exception as exc:
                return self._respond_html(start_response, "400 Bad Request", self._render_page(error=str(exc)))

        if method == "POST" and path == "/select":
            try:
                body = self._handle_select(environ)
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
        seed = _optional_int(form.getfirst("seed"))
        count = _optional_int(form.getfirst("count")) or 4
        count = max(1, min(count, 8))
        reroll_scope = _optional_text(form.getfirst("reroll_scope")) or "all"
        seed_offset = _optional_int(form.getfirst("seed_offset")) or 0

        upload_root = self.output_dir / ".uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        melody_path = _resolve_melody_path(form, upload_root)

        if not text and melody_path is None:
            raise ValueError("텍스트 또는 멜로디 MIDI 중 하나는 입력해야 합니다.")

        request = GenerationRequest(
            text=text,
            melody_midi_path=melody_path,
            tempo=tempo,
            key=key,
            genre=genre,
            bars=bars,
            seed=seed,
            output_dir=self.output_dir,
        )
        candidates = generate_candidates(request, count=count, reroll_scope=reroll_scope, seed_offset=seed_offset)
        batch_dir = candidates[0].output_dir.parent if candidates else None
        batch_meta = load_batch_meta(batch_dir) if batch_dir else None
        return self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=_state_from_request(request, count))

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
            "seed": _string_value(batch_meta.get("seed")),
            "count": _string_value(batch_meta.get("candidate_count")) or str(len(candidates)),
            "melody_source": _string_value(batch_meta.get("source_melody")),
        }
        return self._render_page(candidates=candidates, batch_meta=batch_meta, form_state=form_state)

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
        candidate_cards = ""
        if candidates:
            reroll_controls = f"""
            <div class="actions">
              <form method="post" action="/generate">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="all"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit">Reroll All</button></form>
              <form method="post" action="/generate">{_hidden_state_fields(state)}<input type="hidden" name="reroll_scope" value="chords"><input type="hidden" name="seed_offset" value="{uuid.uuid4().int % 1_000_000}"><button type="submit" class="secondary">Reroll Chords</button></form>
            </div>
            """
            candidate_cards = '<section class="candidate-grid">' + ''.join(_candidate_card(result, index, batch_meta) for index, result in enumerate(candidates, start=1)) + '</section>'

        return f"""<!doctype html>
<html lang="ko">
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
    .layout {{ display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(280px, 0.9fr); gap: 24px; align-items: start; }}
    .panel {{ background: var(--surface); backdrop-filter: blur(10px); border: 1px solid var(--line); border-radius: 26px; padding: 22px; box-shadow: var(--shadow); }}
    .panel h2 {{ margin-top: 0; font-size: 22px; }}
    form {{ display: grid; gap: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    label {{ display: grid; gap: 8px; font-size: 14px; color: var(--muted); }}
    input, textarea {{ width: 100%; border: 1px solid rgba(31,26,20,0.14); border-radius: 16px; padding: 14px 16px; background: var(--surface-strong); color: var(--ink); font: inherit; }}
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
    .candidate-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 18px; }}
    .candidate {{ position: relative; padding-top: 18px; }}
    .candidate.selected {{ outline: 3px solid rgba(178,74,43,0.45); background: rgba(255,250,240,0.96); }}
    .candidate .badge {{ position: absolute; top: -10px; left: 18px; background: var(--accent-dark); color: white; border-radius: 999px; padding: 6px 10px; font-size: 12px; letter-spacing: 0.05em; text-transform: uppercase; }}
    .selected-mark {{ color: var(--accent-dark); font-weight: 700; margin-bottom: 10px; }}
    .meta {{ display: grid; gap: 6px; color: var(--muted); font-size: 14px; margin-bottom: 12px; }}
    .path {{ word-break: break-all; color: var(--accent-dark); font-size: 13px; }}
    .tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0 14px; }}
    .tag {{ background: rgba(178,74,43,0.08); color: var(--accent-dark); border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .files {{ padding-left: 20px; margin: 0 0 14px; }}
    .card-actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .card-actions form {{ display: block; }}
    @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div class="eyebrow">FL Studio MIDI Generator</div>
      <h1>Generate. Compare. Listen. Choose.</h1>
      <p class="lead">같은 입력에서 여러 진행 샘플을 만들고, 웹에서 전체 미리듣기를 재생한 뒤 원하는 후보를 선택할 수 있습니다.</p>
    </header>
    <section class="layout">
      <section class="panel">
        <h2>Create Candidate Set</h2>
        <form method="post" action="/generate" enctype="multipart/form-data">
          <label>
            텍스트 또는 가사
            <textarea name="text" placeholder="예: dreamy rnb night drive with airy chords">{html.escape(state.get("text", ""))}</textarea>
          </label>
          <label>
            멜로디 MIDI 업로드
            <input type="file" name="melody_midi" accept=".mid,.midi">
          </label>
          <div class="grid">
            <label>Tempo<input type="number" name="tempo" min="30" max="300" placeholder="auto" value="{html.escape(state.get("tempo", ""))}"></label>
            <label>Key<input type="text" name="key" placeholder="예: F#, A minor" value="{html.escape(state.get("key", ""))}"></label>
            <label>Genre<input type="text" name="genre" placeholder="예: trap, rnb, house" value="{html.escape(state.get("genre", ""))}"></label>
            <label>Bars<input type="number" name="bars" min="1" max="128" placeholder="auto" value="{html.escape(state.get("bars", ""))}"></label>
            <label>Seed<input type="number" name="seed" placeholder="optional" value="{html.escape(state.get("seed", ""))}"></label>
            <label>Options<input type="number" name="count" min="1" max="8" value="{html.escape(state.get("count", "4"))}"></label>
          </div>
          <input type="hidden" name="melody_source" value="{html.escape(state.get("melody_source", ""))}">
          <p class="hint">텍스트와 MIDI 중 하나는 반드시 입력해야 합니다. 후보 생성 후 각 카드에서 full_arrangement.mid를 바로 들어볼 수 있습니다.</p>
          <button type="submit">Generate Options</button>
        </form>
      </section>
      <aside class="panel">
        <h2>How It Works</h2>
        <div class="specs">
          <div class="spec"><strong>후보 생성</strong>한 번에 1~8개의 샘플을 생성합니다. 각 후보는 자체 progression, drum, bass 패턴을 가집니다.</div>
          <div class="spec"><strong>브라우저 재생</strong>각 후보의 <code>full_arrangement.mid</code>를 브라우저 내 MIDI 플레이어로 미리듣기 재생합니다.</div>
          <div class="spec"><strong>선택 저장</strong><code>Select This</code>를 누르면 배치 폴더의 <code>{BATCH_META_FILENAME}</code>에 선택된 후보 번호가 저장됩니다.</div>
          <div class="spec"><strong>저장 위치</strong>{html.escape(str(self.output_dir))} 아래 배치 폴더와 <code>option_01</code>, <code>option_02</code> 식의 후보 폴더를 생성합니다.</div>
        </div>
      </aside>
    </section>
    {error_html}
    {reroll_controls}
    {candidate_cards}
  </main>
  <script type="module">
    import * as Tone from 'https://cdn.jsdelivr.net/npm/tone@15.0.4/+esm';
    import {{ Midi }} from 'https://cdn.jsdelivr.net/npm/@tonejs/midi@2.0.28/+esm';

    let currentButtons = null;
    let currentStop = null;
    const synthRegistry = new Map();

    function makeSynthForTrack(name) {{
      if (name === 'Drums') return new Tone.MembraneSynth().toDestination();
      if (name === 'Bass') return new Tone.MonoSynth({{ oscillator: {{ type: 'square' }}, envelope: {{ attack: 0.01, release: 0.2 }} }}).toDestination();
      if (name === 'Chords') return new Tone.PolySynth(Tone.Synth, {{ oscillator: {{ type: 'triangle' }}, envelope: {{ attack: 0.02, release: 0.3 }} }}).toDestination();
      return new Tone.PolySynth(Tone.Synth, {{ oscillator: {{ type: 'sine' }}, envelope: {{ attack: 0.01, release: 0.2 }} }}).toDestination();
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

    async function playCandidate(url, buttons) {{
      await Tone.start();
      await stopPlayback();
      const response = await fetch(url);
      if (!response.ok) {{
        throw new Error(`Failed to load preview: ${{response.status}}`);
      }}
      const midi = new Midi(await response.arrayBuffer());
      let lastTime = 0;

      midi.tracks.forEach((track, index) => {{
        if (!track.notes.length) return;
        const name = track.name || `Track ${{index + 1}}`;
        let synth = synthRegistry.get(name);
        if (!synth) {{
          synth = makeSynthForTrack(name);
          synthRegistry.set(name, synth);
        }}
        track.notes.forEach((note) => {{
          lastTime = Math.max(lastTime, note.time + note.duration);
          Tone.Transport.schedule((time) => {{
            synth.triggerAttackRelease(note.name, note.duration, time, Math.max(0.2, note.velocity || 0.7));
          }}, note.time);
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

    document.querySelectorAll('[data-preview-url]').forEach((button) => {{
      button.addEventListener('click', async () => {{
        const card = button.closest('.candidate');
        const stop = card.querySelector('[data-stop]');
        try {{
          await playCandidate(button.dataset.previewUrl, {{ play: button, stop }});
        }} catch (error) {{
          console.error(error);
          await stopPlayback();
        }}
      }});
    }});

    document.querySelectorAll('[data-stop]').forEach((button) => {{
      button.addEventListener('click', async () => {{
        await stopPlayback();
      }});
    }});

    window.addEventListener('beforeunload', () => {{ stopPlayback(); }});
  </script>
</body>
</html>
"""

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


def _candidate_card(result, index: int, batch_meta: dict[str, object] | None) -> str:
    meta = result.metadata
    tags = ''.join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in meta.get("style_tags", []))
    file_list = ''.join(f'<li><code>{html.escape(path.name)}</code></li>' for path in result.files)
    batch_dir = Path(result.output_dir).parent
    selected_option = None if not batch_meta else batch_meta.get("selected_option")
    selected = selected_option == meta.get("candidate_index")
    preview_path = Path(result.output_dir) / str(meta.get("preview_file", "full_arrangement.mid"))
    preview_url = f"/files?path={quote(str(preview_path))}"
    selected_html = '<div class="selected-mark">Selected Candidate</div>' if selected else ''
    select_form = f"""
      <form method="post" action="/select">
        <input type="hidden" name="batch_dir" value="{html.escape(str(batch_dir))}">
        <input type="hidden" name="candidate_index" value="{html.escape(str(meta.get('candidate_index')))}">
        <button type="submit" class="select-btn {'secondary' if selected else ''}">Select This</button>
      </form>
    """
    return f"""
    <article class="panel candidate {'selected' if selected else ''}" id="candidate-{index}">
      <div class="badge">Option {index:02d}</div>
      {selected_html}
      <h2>{html.escape(str(meta.get('progression_label', 'Candidate')))}</h2>
      <div class="meta">
        <div><strong>Seed</strong> {html.escape(str(meta.get('candidate_seed')))}</div>
        <div><strong>Tempo</strong> {html.escape(str(meta.get('tempo')))} BPM</div>
        <div><strong>Key</strong> {html.escape(str(meta.get('key')))}</div>
        <div><strong>Drums</strong> {html.escape(str(meta.get('drum_pattern')))}</div>
        <div><strong>Bass</strong> {html.escape(str(meta.get('bass_pattern')))}</div>
      </div>
      <div class="tags">{tags}</div>
      <p class="path">{html.escape(str(result.output_dir))}</p>
      <ul class="files">{file_list}</ul>
      <div class="card-actions">
        <button type="button" class="ghost" data-preview-url="{html.escape(preview_url)}">Play</button>
        <button type="button" class="ghost" data-stop disabled>Stop</button>
        {select_form}
      </div>
    </article>
    """


def _state_from_request(request: GenerationRequest, count: int) -> dict[str, str]:
    return {
        "text": request.text or "",
        "tempo": "" if request.tempo is None else str(request.tempo),
        "key": request.key or "",
        "genre": request.genre or "",
        "bars": "" if request.bars is None else str(request.bars),
        "seed": "" if request.seed is None else str(request.seed),
        "count": str(count),
        "melody_source": "" if request.melody_midi_path is None else str(request.melody_midi_path),
    }


def _hidden_state_fields(state: dict[str, str] | None) -> str:
    if not state:
        return ""
    parts = []
    for key, value in state.items():
        parts.append(f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">')
    return ''.join(parts)


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
