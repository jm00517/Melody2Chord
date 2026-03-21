from __future__ import annotations

import cgi
import html
import json
from pathlib import Path
import uuid
from typing import Callable
from wsgiref.simple_server import make_server

from .generator import generate_song
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

        if not text and "melody_midi" not in form:
            raise ValueError("텍스트 또는 멜로디 MIDI 중 하나는 입력해야 합니다.")

        upload_root = self.output_dir / ".uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        melody_path = None
        melody_field = form["melody_midi"] if "melody_midi" in form else None
        if melody_field is not None and getattr(melody_field, "filename", None):
            filename = Path(melody_field.filename).name or "upload.mid"
            melody_path = upload_root / f"{uuid.uuid4().hex}_{filename}"
            melody_path.write_bytes(melody_field.file.read())

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
        result = generate_song(request)
        return self._render_page(result=result)

    def _render_page(self, result: object | None = None, error: str | None = None) -> str:
        result_html = ""
        if result is not None:
            metadata = json.dumps(result.metadata, ensure_ascii=False, indent=2)
            file_list = "".join(f"<li><code>{html.escape(path.name)}</code></li>" for path in result.files)
            result_html = f"""
            <section class=\"panel result\">
              <h2>Generated</h2>
              <p class=\"path\">{html.escape(str(result.output_dir))}</p>
              <ul class=\"files\">{file_list}</ul>
              <pre>{html.escape(metadata)}</pre>
            </section>
            """

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
      --shadow: 0 24px 60px rgba(73, 48, 25, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(178,74,43,0.18), transparent 30%), radial-gradient(circle at right 20%, rgba(234,216,183,0.75), transparent 28%), linear-gradient(180deg, #f1ede3 0%, #f7f2e9 100%); min-height: 100vh; }}
    .shell {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px 64px; }}
    .hero {{ display: grid; gap: 14px; margin-bottom: 28px; }}
    .eyebrow {{ letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent-dark); font-size: 12px; }}
    h1 {{ margin: 0; font-size: clamp(36px, 7vw, 82px); line-height: 0.95; max-width: 9ch; }}
    .lead {{ max-width: 58ch; color: var(--muted); font-size: 18px; line-height: 1.6; }}
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
    button {{ border: 0; border-radius: 999px; padding: 14px 22px; background: linear-gradient(135deg, var(--accent), #d67b3d); color: white; font-size: 15px; font-weight: 700; cursor: pointer; }}
    .specs {{ display: grid; gap: 12px; }}
    .spec {{ padding: 14px 0; border-bottom: 1px solid var(--line); }}
    .spec:last-child {{ border-bottom: 0; }}
    .spec strong {{ display: block; margin-bottom: 4px; }}
    .result .path {{ word-break: break-all; color: var(--accent-dark); }}
    .files {{ padding-left: 20px; }}
    pre {{ overflow-x: auto; background: #201811; color: #f4ecde; border-radius: 18px; padding: 16px; font-size: 13px; line-height: 1.5; }}
    .error {{ border-color: rgba(178,74,43,0.3); background: rgba(255,238,229,0.92); }}
    @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class=\"shell\">
    <header class=\"hero\">
      <div class=\"eyebrow\">FL Studio MIDI Generator</div>
      <h1>Text in. Melody in. Arrangement out.</h1>
      <p class=\"lead\">텍스트 프롬프트, 사용자 멜로디 MIDI, 또는 둘 다 넣으면 FL Studio로 바로 드래그할 수 있는 파트별 MIDI 세트를 생성합니다.</p>
    </header>
    <section class=\"layout\">
      <section class=\"panel\">
        <h2>Create Arrangement</h2>
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
          </div>
          <p class=\"hint\">텍스트와 MIDI 중 하나는 반드시 입력해야 합니다. 둘 다 넣으면 멜로디를 우선 보존하고 텍스트를 스타일 힌트로 사용합니다.</p>
          <button type=\"submit\">Generate MIDI Set</button>
        </form>
      </section>
      <aside class=\"panel\">
        <h2>How It Works</h2>
        <div class=\"specs\">
          <div class=\"spec\"><strong>입력 모드</strong>텍스트 전용, 멜로디 전용, 텍스트+멜로디 혼합 입력을 지원합니다.</div>
          <div class=\"spec\"><strong>출력 파일</strong>`melody.mid`, `chords.mid`, `bass.mid`, `drums.mid`, `full_arrangement.mid`, `meta.json`을 생성합니다.</div>
          <div class=\"spec\"><strong>현재 엔진</strong>규칙 기반 생성기입니다. FL 직접 제어가 아니라 FL import용 MIDI를 만듭니다.</div>
          <div class=\"spec\"><strong>저장 위치</strong>{html.escape(str(self.output_dir))} 아래에 타임스탬프 폴더를 생성합니다.</div>
        </div>
      </aside>
    </section>
    {error_html}
    {result_html}
  </main>
</body>
</html>
"""

    @staticmethod
    def _respond(start_response: Callable, status: str, body: str):
        payload = body.encode("utf-8")
        headers = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(payload)))]
        start_response(status, headers)
        return [payload]


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
