from __future__ import annotations

import cgi
import html
import json
from pathlib import Path
import uuid
from typing import Callable
from wsgiref.simple_server import make_server

from .generator import generate_candidates
from .models import GenerationRequest


TITLE = "py2fl Studio"


class Py2FLWebApp:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def __call__(self, environ: dict, start_response: Callable):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")

        if method == "GET" and path == "/":
            body = self._render_page()
            return self._respond(start_response, "200 OK", body)

        if method == "POST" and path == "/generate":
            try:
                body = self._handle_generate(environ)
                return self._respond(start_response, "200 OK", body)
            except Exception as exc:
                body = self._render_page(error=str(exc))
                return self._respond(start_response, "400 Bad Request", body)

        return self._respond(start_response, "404 Not Found", "<h1>Not Found</h1>")

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
        return self._render_page(candidates=candidates, form_state=_state_from_request(request, count))

    def _render_page(self, candidates: list | None = None, form_state: dict[str, str] | None = None, error: str | None = None) -> str:
        reroll_controls = ""
        candidate_cards = ""
        if candidates:
            reroll_controls = f"""
            <div class=\"actions\">
              <form method=\"post\" action=\"/generate\">{_hidden_state_fields(form_state)}<input type=\"hidden\" name=\"reroll_scope\" value=\"all\"><input type=\"hidden\" name=\"seed_offset\" value=\"{uuid.uuid4().int % 1_000_000}\"><button type=\"submit\">Reroll All</button></form>
              <form method=\"post\" action=\"/generate\">{_hidden_state_fields(form_state)}<input type=\"hidden\" name=\"reroll_scope\" value=\"chords\"><input type=\"hidden\" name=\"seed_offset\" value=\"{uuid.uuid4().int % 1_000_000}\"><button type=\"submit\" class=\"secondary\">Reroll Chords</button></form>
            </div>
            """
            candidate_cards = "<section class=\"candidate-grid\">" + "".join(_candidate_card(result, index) for index, result in enumerate(candidates, start=1)) + "</section>"

        error_html = ""
        if error:
            error_html = f"<section class=\"panel error\"><h2>Error</h2><p>{html.escape(error)}</p></section>"

        return f"""<!doctype html>
<html lang=\"ko\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
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
    .shell {{ max-width: 1240px; margin: 0 auto; padding: 32px 20px 64px; }}
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
    button {{ border: 0; border-radius: 999px; padding: 14px 22px; background: linear-gradient(135deg, var(--accent), var(--accent-soft)); color: white; font-size: 15px; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: linear-gradient(135deg, #6b5840, #9b866c); }}
    .specs {{ display: grid; gap: 12px; }}
    .spec {{ padding: 14px 0; border-bottom: 1px solid var(--line); }}
    .spec:last-child {{ border-bottom: 0; }}
    .spec strong {{ display: block; margin-bottom: 4px; }}
    .error {{ border-color: rgba(178,74,43,0.3); background: rgba(255,238,229,0.92); }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 26px 0 18px; }}
    .actions form {{ display: block; }}
    .candidate-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }}
    .candidate {{ position: relative; padding-top: 18px; }}
    .candidate.selected {{ outline: 3px solid rgba(178,74,43,0.35); }}
    .candidate .badge {{ position: absolute; top: -10px; left: 18px; background: var(--accent-dark); color: white; border-radius: 999px; padding: 6px 10px; font-size: 12px; letter-spacing: 0.05em; text-transform: uppercase; }}
    .meta {{ display: grid; gap: 6px; color: var(--muted); font-size: 14px; margin-bottom: 12px; }}
    .path {{ word-break: break-all; color: var(--accent-dark); font-size: 13px; }}
    .tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0 14px; }}
    .tag {{ background: rgba(178,74,43,0.08); color: var(--accent-dark); border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .files {{ padding-left: 20px; margin: 0; }}
    pre {{ overflow-x: auto; background: #201811; color: #f4ecde; border-radius: 18px; padding: 16px; font-size: 13px; line-height: 1.5; }}
    .select-btn {{ margin-top: 14px; width: 100%; }}
    @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class=\"shell\">
    <header class=\"hero\">
      <div class=\"eyebrow\">FL Studio MIDI Generator</div>
      <h1>Generate. Compare. Reroll.</h1>
      <p class=\"lead\">같은 입력에서 여러 진행 샘플을 한 번에 만들고, Web UI에서 바로 후보를 비교하거나 전체 리롤, 코드만 리롤을 할 수 있습니다.</p>
    </header>
    <section class=\"layout\">
      <section class=\"panel\">
        <h2>Create Candidate Set</h2>
        <form method=\"post\" action=\"/generate\" enctype=\"multipart/form-data\">
          <label>
            텍스트 또는 가사
            <textarea name=\"text\" placeholder=\"예: dreamy rnb night drive with airy chords\"></textarea>
          </label>
          <label>
            멜로디 MIDI 업로드
            <input type=\"file\" name=\"melody_midi\" accept=\".mid,.midi\">
          </label>
          <div class=\"grid\">
            <label>Tempo<input type=\"number\" name=\"tempo\" min=\"30\" max=\"300\" placeholder=\"auto\"></label>
            <label>Key<input type=\"text\" name=\"key\" placeholder=\"예: F#, A minor\"></label>
            <label>Genre<input type=\"text\" name=\"genre\" placeholder=\"예: trap, rnb, house\"></label>
            <label>Bars<input type=\"number\" name=\"bars\" min=\"1\" max=\"128\" placeholder=\"auto\"></label>
            <label>Seed<input type=\"number\" name=\"seed\" placeholder=\"optional\"></label>
            <label>Options<input type=\"number\" name=\"count\" min=\"1\" max=\"8\" value=\"4\"></label>
          </div>
          <p class=\"hint\">텍스트와 MIDI 중 하나는 반드시 입력해야 합니다. 멜로디가 있으면 멜로디를 우선 보존하고, 리롤 시에는 seed와 패턴 템플릿을 바꿔 다른 후보를 생성합니다.</p>
          <button type=\"submit\">Generate Options</button>
        </form>
      </section>
      <aside class=\"panel\">
        <h2>How It Works</h2>
        <div class=\"specs\">
          <div class=\"spec\"><strong>후보 생성</strong>한 번에 1~8개의 샘플을 생성합니다. 각 후보는 자체 progression, drum, bass 패턴을 가집니다.</div>
          <div class=\"spec\"><strong>리롤 범위</strong>`Reroll All`은 전체 후보를 새로 만들고, `Reroll Chords`는 멜로디와 드럼을 유지한 채 코드/베이스 위주로 다시 뽑습니다.</div>
          <div class=\"spec\"><strong>출력 파일</strong>각 후보는 `melody.mid`, `chords.mid`, `bass.mid`, `drums.mid`, `full_arrangement.mid`, `meta.json`을 생성합니다.</div>
          <div class=\"spec\"><strong>저장 위치</strong>{html.escape(str(self.output_dir))} 아래에 배치 폴더를 만들고, 그 안에 `option_01`, `option_02` 식으로 저장합니다.</div>
        </div>
      </aside>
    </section>
    {error_html}
    {reroll_controls}
    {candidate_cards}
  </main>
  <script>
    document.querySelectorAll('.select-btn').forEach((button) => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('.candidate').forEach((card) => card.classList.remove('selected'));
        const card = button.closest('.candidate');
        if (card) card.classList.add('selected');
      }});
    }});
  </script>
</body>
</html>
"""

    @staticmethod
    def _respond(start_response: Callable, status: str, body: str):
        payload = body.encode("utf-8")
        headers = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(payload)))]
        start_response(status, headers)
        return [payload]


def _candidate_card(result, index: int) -> str:
    meta = result.metadata
    tags = "".join(f"<span class=\"tag\">{html.escape(str(tag))}</span>" for tag in meta.get("style_tags", []))
    file_list = "".join(f"<li><code>{html.escape(path.name)}</code></li>" for path in result.files)
    return f"""
    <article class=\"panel candidate\" id=\"candidate-{index}\">
      <div class=\"badge\">Option {index:02d}</div>
      <h2>{html.escape(str(meta.get('progression_label', 'Candidate')))}</h2>
      <div class=\"meta\">
        <div><strong>Seed</strong> {html.escape(str(meta.get('candidate_seed')))}</div>
        <div><strong>Tempo</strong> {html.escape(str(meta.get('tempo')))} BPM</div>
        <div><strong>Key</strong> {html.escape(str(meta.get('key')))}</div>
        <div><strong>Drums</strong> {html.escape(str(meta.get('drum_pattern')))}</div>
        <div><strong>Bass</strong> {html.escape(str(meta.get('bass_pattern')))}</div>
      </div>
      <div class=\"tags\">{tags}</div>
      <p class=\"path\">{html.escape(str(result.output_dir))}</p>
      <ul class=\"files\">{file_list}</ul>
      <button type=\"button\" class=\"select-btn secondary\">Select This</button>
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
    return "".join(parts)


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
