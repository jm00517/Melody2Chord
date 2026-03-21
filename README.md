# py2fl

`py2fl`은 FL Studio에 바로 드래그해서 쓸 수 있는 MIDI 세트를 생성하는 로컬 Python 도구입니다.
입력은 `텍스트`, `사용자 멜로디 MIDI`, 또는 `텍스트 + 멜로디 MIDI` 조합을 지원합니다. 출력은 기본적으로 아래 6개 파일입니다.

- `melody.mid`
- `chords.mid`
- `bass.mid`
- `drums.mid`
- `full_arrangement.mid`
- `meta.json`

이 프로젝트의 목적은 FL Studio를 직접 제어하는 것이 아니라, `FL Studio에 가져가서 빠르게 편집 가능한 MIDI 재료`를 만드는 것입니다.
현재는 규칙 기반 `v1` 생성기이며, CLI와 간단한 Web UI를 함께 제공합니다.

## 1. 핵심 기능

- 텍스트만 입력하면 코드, 멜로디, 베이스, 드럼을 모두 생성합니다.
- 멜로디 MIDI만 입력하면 원본 멜로디를 유지하면서 코드, 베이스, 드럼을 생성합니다.
- 텍스트와 멜로디 MIDI를 함께 입력하면 멜로디를 우선 보존하고 텍스트를 스타일 힌트로 사용합니다.
- 결과물을 파트별 MIDI와 통합 MIDI로 함께 저장합니다.
- 외부 MIDI 라이브러리 없이 Python 표준 라이브러리만으로 MIDI를 읽고 씁니다.
- CLI와 Web UI 모두 동일한 생성 로직을 사용합니다.
- 같은 입력과 같은 `seed`를 넣으면 같은 결과가 나오도록 설계되어 있습니다.

## 2. 현재 구현 범위

현재 버전은 `v1 규칙 기반 생성기`입니다.

- 생성 엔진: 규칙 기반
- 대상 워크플로: FL Studio 수동 import / 드래그 앤 드롭
- 제공 인터페이스: CLI, 로컬 Web UI, Python API
- 출력 포맷: Standard MIDI File
- 동작 환경: Python 3.12+

현재 포함되지 않는 기능:

- FL Studio Python API 직접 제어
- 실시간 MIDI/OSC 브리지
- 오디오/허밍 입력 분석
- LLM 호출
- 고급 송폼 설계, 전조, 텐션 중심 화성 처리, 사람 같은 드럼 휴먼라이즈

## 3. 프로젝트 구조

주요 파일:

- `src/py2fl/cli.py`
  - CLI 진입점
  - `generate`, `serve` 서브커맨드 제공
- `src/py2fl/web.py`
  - 로컬 Web UI 서버
  - 브라우저 폼 처리 및 HTML 렌더링
- `src/py2fl/generator.py`
  - 전체 생성 파이프라인 조립
- `src/py2fl/text_analysis.py`
  - 텍스트 기반 장르/무드/에너지 추출
- `src/py2fl/melody.py`
  - 멜로디 MIDI 분석, 키 추정, 마디 수 추정
- `src/py2fl/arrangement.py`
  - 코드/멜로디/베이스/드럼 생성 규칙
- `src/py2fl/midi.py`
  - MIDI 파싱 및 쓰기
- `tests/test_generate.py`
  - 생성기와 Web UI 기본 렌더링 테스트

## 4. 설치 및 실행

### 4.1 요구 사항

- Python `3.12` 이상
- 로컬 파일 시스템 쓰기 권한
- 브라우저 사용 시 로컬 포트 바인딩 가능 환경

생성 기능 자체에는 추가 패키지가 필요하지 않습니다.

### 4.2 설치 없이 실행

```bash
$env:PYTHONPATH='src'
python -m py2fl.cli generate --text "dark trap anthem" --bars 4 --out .\exports
```

Web UI 실행:

```bash
$env:PYTHONPATH='src'
python -m py2fl.cli serve --host 127.0.0.1 --port 8765 --out .\exports
```

### 4.3 개발 설치 후 실행

```bash
pip install -e .
```

설치 후 사용할 수 있는 명령:

- `py2fl`
- `py2fl-web`

예시:

```bash
py2fl generate --text "dark trap anthem" --bars 8 --out ./exports
py2fl serve --port 8765 --out ./exports
py2fl-web
```

## 5. CLI 사용법

기본 명령:

```bash
py2fl generate [OPTIONS]
py2fl serve [OPTIONS]
```

### 5.1 `generate` 옵션

- `--text`
  - 자연어 프롬프트 또는 가사
- `--melody-midi`
  - 사용자 멜로디 MIDI 파일 경로
- `--tempo`
  - BPM 강제 지정
- `--key`
  - 키 강제 지정. 예: `C`, `F#`, `Bb`, `A minor`, `Db major`
- `--genre`
  - 장르 힌트 강제 지정
- `--bars`
  - 생성 마디 수 강제 지정
- `--seed`
  - 난수 시드 고정
- `--out`
  - 결과물 저장 기본 폴더

유효성 규칙:

- `--text`와 `--melody-midi` 중 적어도 하나는 필수입니다.
- 둘 다 제공해도 됩니다.
- `--out`을 생략하면 기본값은 `exports`입니다.

### 5.2 `serve` 옵션

- `--host`
  - 서버 바인드 주소
  - 기본값: `127.0.0.1`
- `--port`
  - 서버 포트
  - 기본값: `8765`
- `--out`
  - 생성 결과 기본 저장 폴더
  - 기본값: `exports`

예시:

```bash
py2fl serve --host 127.0.0.1 --port 8765 --out ./exports
```

## 6. Web UI 사용법

### 6.1 실행

```bash
$env:PYTHONPATH='src'
python -m py2fl.cli serve --host 127.0.0.1 --port 8765 --out .\exports
```

또는:

```bash
py2fl serve --port 8765
```

배치 파일로 바로 실행:

```bat
run_web_ui.bat
```

호스트, 포트, 출력 폴더를 직접 넘길 수도 있습니다.

```bat
run_web_ui.bat 127.0.0.1 8765 .\exports
```

브라우저에서 아래 주소로 접속합니다.

```text
http://127.0.0.1:8765
```

### 6.2 Web UI에서 입력 가능한 항목

- 텍스트 또는 가사
- 멜로디 MIDI 업로드 (`.mid`, `.midi`)
- Tempo
- Key
- Genre
- Bars
- Seed

### 6.3 Web UI 동작 방식

- 텍스트와 MIDI 중 하나는 반드시 입력해야 합니다.
- 둘 다 입력하면 멜로디를 우선 보존합니다.
- 업로드한 MIDI 파일은 `.uploads` 아래에 저장된 뒤 생성에 사용됩니다.
- 생성이 끝나면 결과 폴더 경로, 생성된 파일 목록, 메타데이터가 페이지에 표시됩니다.
- 실제 결과물은 `--out` 아래의 타임스탬프 폴더에 저장됩니다.

### 6.4 Web UI 용도

이 UI는 빠른 실험용입니다.

- CLI를 기억하지 않고 바로 입력할 수 있습니다.
- 프롬프트와 MIDI 업로드를 한 화면에서 처리할 수 있습니다.
- 생성 결과 경로를 즉시 확인할 수 있습니다.

현재 Web UI에는 포함되지 않는 기능:

- 파일 브라우저 내장
- 생성 결과 미리듣기
- 브라우저에서 직접 MIDI 다운로드 스트리밍
- 멀티 유저 세션 관리
- 작업 이력 보관

## 7. 입력 모드별 동작

### 7.1 텍스트 전용 모드

예시:

```bash
py2fl generate --text "dark trap anthem" --bars 8 --seed 7
```

동작:

- 텍스트에서 장르, 무드, 에너지 힌트를 추출합니다.
- 추출 결과를 바탕으로 키, 모드, 템포 기본값을 결정합니다.
- 코드 진행을 만든 뒤 그 위에 멜로디를 생성합니다.
- 코드 기반 베이스와 장르 기반 드럼을 생성합니다.

### 7.2 멜로디 MIDI 전용 모드

예시:

```bash
py2fl generate --melody-midi .\idea.mid --out .\exports
```

동작:

- MIDI에서 노트 수가 가장 많은 트랙을 멜로디로 간주합니다.
- 멜로디를 분석해 키, 모드, 템포, 마디 수를 추정합니다.
- 원본 멜로디를 유지하면서 코드, 베이스, 드럼을 생성합니다.

### 7.3 텍스트 + 멜로디 혼합 모드

예시:

```bash
py2fl generate --text "dreamy rnb night drive" --melody-midi .\topline.mid
```

동작:

- 멜로디 MIDI의 실제 노트가 최우선입니다.
- 텍스트는 장르/무드 스타일 힌트로 사용됩니다.
- 멜로디에 맞는 코드를 만들고, 텍스트 스타일에 맞는 베이스/드럼을 생성합니다.

## 8. 입력 해석 규칙

### 8.1 텍스트 해석

텍스트는 키워드 규칙으로 해석됩니다.

장르 키워드:

- `trap`: `trap`, `808`, `drill`
- `rnb`: `rnb`, `soul`, `neo-soul`
- `house`: `house`, `club`, `dance`
- `ambient`: `ambient`, `cinematic`, `atmospheric`
- `pop`: `pop`, `anthem`, `radio`

무드 키워드:

- `dark`: `dark`, `moody`, `brooding`, `night`
- `bright`: `bright`, `uplifting`, `sunny`, `happy`
- `dreamy`: `dreamy`, `airy`, `ethereal`, `floaty`
- `aggressive`: `aggressive`, `hard`, `punchy`, `intense`

에너지 키워드:

- `high`: `energetic`, `driving`, `fast`, `club`, `anthem`
- `low`: `slow`, `soft`, `gentle`, `ambient`, `chill`

기본값:

- 장르를 못 찾으면 `pop`
- 무드를 못 찾으면 `neutral`
- 에너지를 못 찾으면 `medium`
- 장르가 `trap`이면 기본 무드 `dark`
- 장르가 `ambient` 또는 `rnb`이면 기본 무드 `dreamy`

### 8.2 멜로디 MIDI 해석

멜로디 분석 순서:

1. MIDI 파일을 읽습니다.
2. 노트 수가 가장 많은 트랙을 멜로디 트랙으로 선택합니다.
3. pitch class 분포를 기준으로 키와 모드를 추정합니다.
4. 마지막 노트 종료 시점을 기준으로 마디 수를 추정합니다.
5. onset 분포를 이용해 phrase length를 계산합니다.

제약:

- SMPTE division MIDI는 지원하지 않습니다.
- 노트 이벤트가 없는 MIDI는 오류가 발생합니다.
- 여러 트랙이 있어도 가장 노트 수가 많은 하나의 트랙만 멜로디로 사용합니다.

## 9. 값 결정 우선순위

### 9.1 템포 결정

우선순위:

1. `--tempo`
2. 멜로디 MIDI 내부 템포 메타 이벤트
3. 텍스트 장르별 기본 템포
4. 최종 기본값 `110`

장르별 기본 템포:

- `trap`: `140`
- `rnb`: `88`
- `house`: `124`
- `ambient`: `76`
- `pop`: `110`

### 9.2 키 결정

우선순위:

1. `--key`
2. 멜로디 분석 결과
3. 텍스트 기반 기본값

텍스트 기반 기본 키:

- 장르가 `trap`이면 `F#`
- 모드가 `minor`이면 `A`
- 그 외는 `C`

지원 예시:

- `C`
- `F#`
- `Bb`
- `Db major`
- `A minor`

### 9.3 모드 결정

우선순위:

1. 멜로디 분석 결과
2. 텍스트 무드가 `dark` 또는 `dreamy`면 `minor`
3. 그 외 `major`

### 9.4 마디 수 결정

우선순위:

1. `--bars`
2. 멜로디에서 추정한 마디 수
3. 최종 기본값 `8`

## 10. 생성 규칙 상세

### 10.1 코드 생성

텍스트 전용 모드에서는 장르/모드 조합별 기본 진행을 사용합니다.

현재 내장 진행:

- `major + pop`: `1-5-6-4`
- `major + house`: `1-5-6-4`
- `major + ambient`: `1-4-6-5`
- `minor + trap`: `1-6-7-5`
- `minor + rnb`: `1-4-6-5`
- `minor + ambient`: `1-7-6-5`

fallback 규칙:

- 해당 장르 조합이 없으면 `(mode, "pop")`
- 그것도 없으면 `1-5-6-4`

코드 보이싱:

- 각 마디에 루트, 3도, 5도의 트라이어드만 배치
- 코드 길이는 1마디
- 채널은 `1`
- 주 음역은 4옥타브대

멜로디 입력이 있는 경우:

- 각 마디에 대해 스케일 기반 7개 트라이어드를 후보로 생성
- 해당 마디의 멜로디와 가장 잘 맞는 트라이어드를 선택
- 멜로디 음 포함 여부와 강박 음의 루트 일치 여부를 점수에 반영

### 10.2 멜로디 생성

텍스트 전용 모드에서만 새 멜로디를 생성합니다.

규칙:

- 마디당 4개 노트
- 리듬 오프셋은 `0`, `1/4`, `1/2`, `3/4 bar`
- 일부 음은 코드 톤을 우선 사용
- 일부 음은 스케일 내 랜덤 선택
- 직전 음과 간격이 너무 크면 옥타브 보정
- 출력 음역은 대략 `60~84`

멜로디 입력이 있는 경우:

- 원본 멜로디를 우선 보존
- 마디 수 제한을 넘는 노트는 제거
- 끝이 잘리는 노트는 길이를 잘라서 저장
- 채널은 `0`

### 10.3 베이스 생성

- 코드 루트에서 2옥타브 아래를 기본 베이스 음으로 사용
- 음역은 대략 `28~52`
- 장르가 `trap` 또는 `house`면 staccato 패턴 사용
- 그 외 장르는 마디당 롱톤 1개 사용
- 채널은 `2`

### 10.4 드럼 생성

공통 규칙:

- 하이햇: 매 4분박
- 스네어: 2박, 4박

장르별 킥:

- `house`: 4-on-the-floor
- `trap`: `0`, `2`, `2.5` 박 위치
- 그 외: 기본 2회 킥

추가 trap 규칙:

- 오프비트 보조 하이햇 추가

GM 계열 노트:

- 킥: `36`
- 스네어: `38`
- 닫힌 하이햇: `42`
- 보조 하이햇: `44`

드럼 채널은 `9`입니다.

## 11. MIDI 출력 사양

### 11.1 파일 목록

한 번 실행할 때 생성되는 파일:

- `melody.mid`
- `chords.mid`
- `bass.mid`
- `drums.mid`
- `full_arrangement.mid`
- `meta.json`

### 11.2 저장 경로 규칙

출력 폴더 이름 형식:

```text
{YYYYMMDD_HHMMSS}_{slug}
```

`slug` 생성 기준:

- 텍스트 입력이 있으면 텍스트 앞부분 사용
- 텍스트가 없고 멜로디 입력만 있으면 MIDI 파일명 사용
- 둘 다 적절하지 않으면 `arrangement`

예시:

```text
exports/20260321_192054_dreamy_rnb_night_drive
```

### 11.3 MIDI 내부 구조

- PPQ: `480`
- 파일 포맷: `format 1`
- 각 파일에는 컨트롤 트랙 포함
- 컨트롤 트랙 메타 이벤트:
  - track name
  - tempo
  - time signature `4/4`
  - end of track

파트별 채널:

- Melody: `0`
- Chords: `1`
- Bass: `2`
- Drums: `9`

### 11.4 `meta.json` 구조

포함되는 필드:

- `input_mode`
- `tempo`
- `key`
- `bars`
- `style_tags`
- `source_melody`
- `text`
- `files`

예시:

```json
{
  "input_mode": "text+melody",
  "tempo": 92,
  "key": "C major",
  "bars": 1,
  "style_tags": ["dark", "rnb"],
  "source_melody": "manual_test_runs\\hybrid.mid",
  "text": "dreamy rnb night drive",
  "files": [
    "melody.mid",
    "chords.mid",
    "bass.mid",
    "drums.mid",
    "full_arrangement.mid"
  ]
}
```

## 12. FL Studio에서 사용하는 방법

권장 흐름:

1. `py2fl` CLI 또는 Web UI로 MIDI 세트를 생성합니다.
2. 생성된 결과 폴더를 엽니다.
3. `melody.mid`, `chords.mid`, `bass.mid`, `drums.mid`를 FL Studio로 드래그합니다.
4. `full_arrangement.mid`로 먼저 전체 아이디어를 청취할 수 있습니다.
5. FL Studio 안에서 악기 할당, 보이싱 수정, 드럼 교체, 패턴 분할을 진행합니다.

권장 역할:

- `melody.mid`: 피아노롤 세부 편집용
- `chords.mid`: 화성 수정용
- `bass.mid`: 808 또는 베이스 레이어용
- `drums.mid`: 리듬 재배치용
- `full_arrangement.mid`: 빠른 청취용

## 13. Python API 사용

CLI 외에도 직접 호출할 수 있습니다.

```python
from pathlib import Path

from py2fl.generator import generate_song
from py2fl.models import GenerationRequest

result = generate_song(
    GenerationRequest(
        text="dark trap anthem",
        melody_midi_path=Path("idea.mid"),
        bars=8,
        seed=7,
        output_dir=Path("exports"),
    )
)

print(result.output_dir)
print(result.files)
print(result.metadata)
```

주요 타입:

- `GenerationRequest`
  - `text: str | None`
  - `melody_midi_path: Path | None`
  - `tempo: int | None`
  - `key: str | None`
  - `genre: str | None`
  - `bars: int | None`
  - `seed: int | None`
  - `output_dir: Path`
- `GenerationResult`
  - `output_dir: Path`
  - `files: list[Path]`
  - `metadata: dict[str, object]`

## 14. 테스트 및 검증

테스트 파일:

- `tests/test_generate.py`

포함 시나리오:

- 텍스트 전용 생성
- 멜로디 전용 생성
- 텍스트 + 멜로디 혼합 생성
- 멜로디 보존 검증
- Web UI 홈 렌더링 검증

실행 예:

```bash
$env:PYTHONPATH='src'
pytest -q
```

주의:

- 일부 Windows 샌드박스 환경에서는 `pytest` 임시 디렉터리 정리 단계에서 권한 오류가 날 수 있습니다.
- 그 경우에는 CLI 실행과 수동 검증을 같이 사용하는 것이 좋습니다.

## 15. 현재 제약 사항

현재 구현은 의도적으로 단순합니다.

- 멜로디 분석은 노트 수가 가장 많은 트랙만 사용합니다.
- 키 추정은 pitch class 기반 점수화입니다.
- 코드 보이싱은 기본 트라이어드 중심입니다.
- 드럼은 장르 스케치 수준입니다.
- Web UI는 빠른 실험용이며 파일 매니저나 미리듣기를 제공하지 않습니다.
- 업로드 파일은 `.uploads` 폴더에 남을 수 있습니다.

즉, 이 도구는 `최종 자동 편곡기`가 아니라 `FL Studio 작업 전 단계의 스케치 생성기`에 가깝습니다.

## 16. 향후 확장 포인트

- 멜로디 phrase 기반 섹션 분리
- 코드 텐션, 전위, 보이싱 개선
- 베이스 리듬 다양화
- 장르별 드럼 템플릿 고도화
- Web UI 파일 목록/다운로드/히스토리 추가
- LLM 기반 텍스트 해석 추가
- FL Studio import 보조 메타 구조 추가
- 실시간 MIDI/OSC 브리지
- 오디오/허밍 입력 지원

## 17. 빠른 예시 모음

텍스트만:

```bash
py2fl generate --text "dark trap anthem" --bars 8 --seed 7 --out ./exports
```

멜로디만:

```bash
py2fl generate --melody-midi ./idea.mid --tempo 100 --out ./exports
```

텍스트 + 멜로디:

```bash
py2fl generate --text "dreamy rnb night drive" --melody-midi ./topline.mid --seed 3 --out ./exports
```

Web UI 실행:

```bash
py2fl serve --port 8765 --out ./exports
```

키와 장르 강제:

```bash
py2fl generate --text "club energy" --genre house --key "Db major" --bars 16 --out ./exports
```
