# py2fl

`py2fl`은 FL Studio로 가져가서 바로 편집할 수 있는 MIDI 세트를 생성하는 로컬 Python 도구입니다. 입력은 `텍스트`, `사용자 멜로디 MIDI`, 또는 `텍스트 + 멜로디 MIDI` 조합을 지원합니다. 출력은 기본적으로 아래 6개 파일입니다.

- `melody.mid`
- `chords.mid`
- `bass.mid`
- `drums.mid`
- `full_arrangement.mid`
- `meta.json`

후보 여러 개를 생성하는 경우에는 상위 배치 폴더 아래에 `option_01`, `option_02` 같은 후보 폴더가 생기고, 배치 루트에는 `batch_meta.json`이 함께 저장됩니다.

이 프로젝트의 목적은 FL Studio를 직접 제어하는 것이 아니라, `FL Studio에서 빠르게 다듬을 수 있는 MIDI 스케치`를 만드는 것입니다. 현재는 규칙 기반 `v1` 생성기이며, CLI와 Web UI를 함께 제공합니다.

## 1. 핵심 기능

- 텍스트만 입력하면 코드, 멜로디, 베이스, 드럼을 모두 생성합니다.
- 멜로디 MIDI만 입력하면 원본 멜로디를 유지하면서 코드, 베이스, 드럼을 생성합니다.
- 텍스트와 멜로디 MIDI를 함께 입력하면 멜로디를 우선 보존하고, 텍스트를 스타일 힌트로 사용합니다.
- 결과물을 파트별 MIDI와 통합 MIDI로 함께 저장합니다.
- 외부 MIDI 라이브러리 없이 Python 표준 라이브러리만으로 MIDI를 읽고 씁니다.
- 같은 입력과 같은 `seed`를 쓰면 같은 결과가 나오도록 설계되어 있습니다.
- Web UI에서 한 번에 여러 후보를 생성하고, 카드별 비교, 전체 리롤, 코드만 리롤, 브라우저 미리듣기, 후보 선택 저장이 가능합니다.

## 2. 현재 구현 범위

현재 버전은 `v1 규칙 기반 생성기`입니다.

- 생성 엔진: 규칙 기반
- 대상 워크플로: FL Studio 수동 import / drag-and-drop
- 제공 인터페이스: CLI, 로컬 Web UI, Python API
- 출력 포맷: Standard MIDI File
- 동작 환경: Python 3.12+

현재 포함되지 않는 기능:

- FL Studio Python API 직접 제어
- 실시간 MIDI/OSC 브리지
- 오디오/허밍 입력 분석
- LLM 호출
- 고급 전조, 텐션 중심 화성 처리, 사람 같은 드럼 휴먼라이즈

## 3. 프로젝트 구조

주요 파일:

- `src/py2fl/cli.py`
  - CLI 진입점
  - `generate`, `serve` 서브커맨드 제공
- `src/py2fl/web.py`
  - Web UI HTML 렌더링, 폼 처리, 미리듣기용 파일 서빙, 후보 선택 저장
- `src/py2fl/generator.py`
  - 전체 생성 파이프라인 조립
  - 다중 후보 배치 메타데이터 저장
- `src/py2fl/text_analysis.py`
  - 텍스트 기반 장르/무드/에너지 추출
- `src/py2fl/melody.py`
  - 멜로디 MIDI 분석, 키 추정, 마디 수 추정
- `src/py2fl/arrangement.py`
  - 코드/멜로디/베이스/드럼 생성 규칙
- `src/py2fl/midi.py`
  - MIDI 파싱 및 쓰기
- `tests/test_generate.py`
  - 생성기와 Web UI 기본 동작 테스트
- `run_web_ui.bat`
  - Windows에서 Web UI를 바로 띄우는 실행 배치 파일

## 4. 설치 및 실행

### 4.1 요구 사항

- Python `3.12` 이상
- 로컬 파일 시스템 쓰기 권한
- 브라우저 사용 시 로컬 포트 바인딩 가능 환경

생성 기능 자체에는 추가 패키지가 필요하지 않습니다.

### 4.2 설치 없이 실행

```powershell
$env:PYTHONPATH='src'
python -m py2fl.cli generate --text "dark trap anthem" --bars 4 --out .\exports
```

Web UI 실행:

```powershell
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
py2fl generate --text "dreamy rnb night drive" --count 4 --out ./exports
py2fl serve --port 8765 --out ./exports
```

## 5. CLI 사양

### 5.1 `generate`

```bash
py2fl generate [options]
```

옵션:

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
- `--count`
  - 생성할 후보 개수
  - 기본값: `1`
  - `2` 이상이면 후보 배치 폴더 아래 `option_01`, `option_02` 식으로 저장
- `--out`
  - 결과물 저장 기본 폴더

유효성 규칙:

- `--text`와 `--melody-midi` 중 적어도 하나는 필수입니다.
- 둘 다 제공해도 됩니다.
- `--out`을 생략하면 기본값은 `exports`입니다.

출력:

- `--count 1`이면 단일 결과 JSON을 stdout에 출력합니다.
- `--count 2` 이상이면 배치 경로와 후보 목록 JSON을 stdout에 출력합니다.

### 5.2 `serve`

```bash
py2fl serve [options]
```

옵션:

- `--host`
  - 서버 바인드 주소
  - 기본값: `127.0.0.1`
- `--port`
  - 서버 포트
  - 기본값: `8765`
- `--out`
  - 생성 결과 저장 기본 폴더
  - 기본값: `exports`

예시:

```bash
py2fl serve --host 127.0.0.1 --port 8765 --out ./exports
```

## 6. Web UI 사용법

### 6.1 실행

```powershell
$env:PYTHONPATH='src'
python -m py2fl.cli serve --host 127.0.0.1 --port 8765 --out .\exports
```

또는:

```bash
py2fl serve --port 8765
```

Windows 배치 파일로 바로 실행:

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

### 6.2 입력 항목

- 텍스트 또는 가사
- 멜로디 MIDI 업로드 (`.mid`, `.midi`)
- Tempo
- Key
- Genre
- Bars
- Seed
- Options

입력 규칙:

- 텍스트와 MIDI 중 하나는 반드시 필요합니다.
- 업로드한 MIDI는 출력 루트 아래 `.uploads` 폴더에 저장될 수 있습니다.
- 기존 업로드 파일을 기준으로 리롤할 때는 `melody_source` hidden state를 사용해 다시 참조합니다.

### 6.3 Web UI 동작 방식

후보 생성:

- 한 번에 `1~8`개 후보를 생성합니다.
- 결과는 배치 폴더 아래 `option_01`, `option_02` 같은 하위 폴더로 나뉩니다.
- 배치 루트에는 `batch_meta.json`이 생성됩니다.

후보 카드:

- 각 카드에는 `progression_label`, `candidate_seed`, `tempo`, `key`, `drum_pattern`, `bass_pattern`, 파일 목록이 표시됩니다.
- 각 카드에는 `Play`, `Stop`, `Select This` 버튼이 있습니다.

리롤:

- `Reroll All`
  - 같은 입력으로 seed offset만 바꿔 전체 후보를 새로 생성합니다.
- `Reroll Chords`
  - 멜로디와 드럼은 유지하고, 코드와 베이스 후보만 다시 생성합니다.

미리듣기:

- 후보별 미리듣기는 `full_arrangement.mid`만 지원합니다.
- 브라우저에서 CDN 기반 라이브러리로 MIDI를 읽어서 간단한 신스 음색으로 재생합니다.
- 오디오 렌더가 아니라 브라우저 내 가상 악기 재생이므로, 실제 FL Studio 악기 소리와는 다릅니다.

후보 선택:

- `Select This`를 누르면 선택 상태가 카드에 반영됩니다.
- 선택 정보는 배치 폴더의 `batch_meta.json`에 저장됩니다.
- 다시 렌더링해도 `selected_option`이 유지됩니다.
- 선택은 메타데이터 저장만 수행하며, 파일 복사나 FL 프로젝트 반영은 자동으로 하지 않습니다.

파일 접근 보안:

- Web UI의 파일 서빙은 `output_dir` 아래 경로만 허용합니다.
- `batch_dir` 선택 요청도 `output_dir` 아래 경로만 허용합니다.

### 6.4 Web UI 제한 사항

- 미리듣기는 `full_arrangement.mid`만 지원합니다.
- 파트별 solo/mute는 없습니다.
- 브라우저 내 재생은 Tone.js 기반 간단 신스 음색입니다.
- 작업 이력 브라우징, 사용자 계정, 세션 관리 기능은 없습니다.

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
- 입력 MIDI의 PPQ가 `480`이 아니어도 내부 기준 `480 PPQ`로 정규화합니다.

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

## 10. 생성 알고리즘 상세

### 10.1 코드 생성

텍스트 전용 모드에서는 장르/모드 조합별 진행 라이브러리에서 하나를 고릅니다.

예시 진행 라이브러리:

- `major + pop`: `1-5-6-4`, `6-4-1-5`, `1-4-6-5`
- `major + house`: `1-5-6-4`, `1-6-4-5`, `4-1-5-6`
- `major + ambient`: `1-4-6-5`, `6-5-1-4`, `1-5-4-6`
- `minor + trap`: `1-6-7-5`, `1-7-6-5`, `6-1-7-5`
- `minor + rnb`: `1-4-6-5`, `6-5-1-4`, `1-7-6-4`
- `minor + ambient`: `1-7-6-5`, `6-5-1-7`, `1-4-7-6`

멜로디 입력이 있는 경우 알고리즘:

- 각 마디의 멜로디 노트를 모읍니다.
- 추정된 스케일 안에서 7개의 트라이어드 후보를 만듭니다.
- 멜로디 노트가 트라이어드 안에 있으면 가산점, 밖이면 감점합니다.
- 강하게 들리는 음이 루트와 일치하면 추가 가산점합니다.
- 점수가 가장 높은 트라이어드를 그 마디 코드로 선택합니다.
- 동점권 후보가 여러 개면 seed 기반 랜덤 선택으로 변주가 생깁니다.

현재 특성:

- 7th, 9th, slash chord는 지원하지 않습니다.
- 기능화성보다 `해당 마디 멜로디와 덜 충돌하는 코드`에 더 가깝습니다.

### 10.2 멜로디 생성

텍스트 전용 모드에서만 새 멜로디를 생성합니다.

규칙:

- 마디당 4개 노트 중심
- 리듬 오프셋은 여러 템플릿 중 하나를 선택
- 일부 음은 코드 톤, 일부 음은 스케일 내 랜덤 선택
- 직전 음과 간격이 너무 크면 옥타브 보정
- 출력 음역은 대략 `60~84`

멜로디 입력이 있을 때:

- 원본 멜로디를 우선 보존합니다.
- 마디 수 제한을 넘는 노트는 제거합니다.
- 끝이 잘리는 노트는 길이를 잘라 저장합니다.
- 출력 채널은 `0`입니다.

### 10.3 베이스 생성

규칙:

- 코드 루트에서 2옥타브 아래를 기본 베이스 음으로 사용합니다.
- 음역은 대략 `28~52`
- 장르별 패턴 후보 중 하나를 선택합니다.

패턴 예시:

- `hold`
- `pulse`
- `staccato`
- `stair`
- `octave`
- `syncopated`

출력 채널은 `2`입니다.

### 10.4 드럼 생성

공통 규칙:

- 하이햇: 매 4분박
- 스네어: 2박, 4박
- 장르별 킥/보조 하이햇 패턴 후보 중 하나 선택

GM 계열 노트:

- 킥: `36`
- 스네어: `38`
- 닫힌 하이햇: `42`
- 보조 하이햇: `44`

출력 채널은 `9`입니다.

## 11. MIDI 출력 사양

### 11.1 파일 목록

한 번 실행할 때 생성되는 파일:

- `melody.mid`
- `chords.mid`
- `bass.mid`
- `drums.mid`
- `full_arrangement.mid`
- `meta.json`

다중 후보 배치 추가 파일:

- `batch_meta.json`

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
exports/20260321_192054_dreamy_rnb_night_drive/option_01
```

### 11.3 MIDI 내부 구조

- PPQ: `480`
- 파일 포맷: `format 1`
- 각 MIDI 파일에는 컨트롤 트랙 포함
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

### 11.4 `meta.json`

포함 필드:

- `input_mode`
- `tempo`
- `key`
- `bars`
- `style_tags`
- `source_melody`
- `text`
- `files`
- `progression_label`
- `progression_degrees`
- `drum_pattern`
- `bass_pattern`
- `candidate_index`
- `candidate_seed`
- `reroll_scope`
- `preview_file`

### 11.5 `batch_meta.json`

포함 필드:

- `text`
- `source_melody`
- `tempo`
- `key`
- `genre`
- `bars`
- `seed`
- `candidate_count`
- `selected_option`
- `selected_output_dir`
- `candidates`

각 candidate 항목:

- `candidate_index`
- `option_name`
- `output_dir`
- `progression_label`
- `candidate_seed`
- `tempo`
- `key`
- `drum_pattern`
- `bass_pattern`
- `style_tags`
- `preview_file`

## 12. FL Studio에서 사용하는 방법

권장 흐름:

1. `py2fl` CLI 또는 Web UI로 MIDI 세트를 생성합니다.
2. 생성된 결과 폴더를 엽니다.
3. `melody.mid`, `chords.mid`, `bass.mid`, `drums.mid`를 FL Studio로 드래그합니다.
4. `full_arrangement.mid`로 전체 아이디어를 먼저 들어볼 수 있습니다.
5. FL Studio 안에서 악기 할당, 보이싱 수정, 드럼 교체, 패턴 분할을 진행합니다.

## 13. Python API 사용

```python
from pathlib import Path

from py2fl.generator import generate_candidates, generate_song
from py2fl.models import GenerationRequest

single = generate_song(
    GenerationRequest(
        text="dark trap anthem",
        melody_midi_path=Path("idea.mid"),
        bars=8,
        seed=7,
        output_dir=Path("exports"),
    )
)

batch = generate_candidates(
    GenerationRequest(
        text="dreamy rnb night drive",
        bars=8,
        seed=7,
        output_dir=Path("exports"),
    ),
    count=4,
)
```

## 14. 테스트 및 검증

- 텍스트 전용 생성
- 멜로디 전용 생성
- 텍스트 + 멜로디 혼합 생성
- 멜로디 보존 검증
- 비표준 PPQ 입력 정규화 검증
- 후보 배치 메타 생성 검증
- Web UI 홈 렌더링 검증
- Web UI 선택 저장 검증
- Web UI 미리듣기 파일 서빙 검증

실행 예:

```powershell
$env:PYTHONPATH='src'
pytest -q
python -m compileall src
```

주의:

- 일부 Windows 샌드박스 환경에서는 `pytest` 임시 디렉터리 정리 단계에서 권한 오류가 날 수 있습니다.
- 그 경우 CLI 실행과 수동 검증을 함께 사용하는 것이 좋습니다.

## 15. 현재 제약 사항

- Web UI 미리듣기는 Tone.js 기반 간단 신스 음색입니다.
- 미리듣기는 `full_arrangement.mid`만 지원합니다.
- 후보 선택은 메타데이터 저장만 수행하며, FL 프로젝트에 자동 반영되지 않습니다.
- 코드 보이싱은 기본 트라이어드 중심입니다.
- 코드 추론은 기능화성보다는 멜로디 적합도 중심입니다.
- 드럼은 장르 스케치 수준입니다.
- 업로드 파일은 `.uploads` 폴더에 남을 수 있습니다.

## 16. 향후 확장 포인트

- 박 단위 또는 프레이즈 단위 코드 분석
- 7th, 9th, slash chord 지원
- 파트별 solo/mute 미리듣기
- 후보 선택 결과를 대표 출력으로 승격하는 기능
- Web UI 파일 목록/다운로드/히스토리 추가
- LLM 기반 텍스트 해석 추가
- FL Studio import 보조 메타 구조 추가
- 실시간 MIDI/OSC 브리지
- 오디오/허밍 입력 지원

## 17. 빠른 예시 모음

```bash
py2fl generate --text "dark trap anthem" --bars 8 --seed 7 --out ./exports
py2fl generate --melody-midi ./idea.mid --tempo 100 --out ./exports
py2fl generate --text "dreamy rnb night drive" --melody-midi ./topline.mid --seed 3 --out ./exports
py2fl generate --text "dreamy rnb night drive" --count 4 --out ./exports
py2fl serve --port 8765 --out ./exports
```

- Web UI ?????? `Preview Volume` ????? ???, ?? ?????? ??? ?????.

## Latest Web Preview Updates

- Added a global `Preview Volume` slider for browser playback.
- Added session-scoped part mute buttons for `Melody`, `Chords`, `Bass`, and `Drums`.
- Mute and volume settings apply only to the current page session and reset on refresh.

## Latest Harmony Updates

- Melody-driven chord generation now uses progression-aware scoring instead of simple per-bar triad matching.
- Chord candidates can include `7th`, `add9`, `sus2`, and `sus4` voicings.
- Browser candidate previews should now expose more harmonic variation when melody input is provided.


## Latest Web Layout Updates


- Each `Harmony Timeline` bar now includes `Play Bar` for bar-local preview and `Reroll Harmony` for bar-local chord+bass replacement.
- The most recently rerolled bar is highlighted with a darker card background and a `Recently Updated` label.
- Bar preview is browser-side only and plays the selected timeline slice from `full_arrangement.mid`.
- Bar reroll preserves melody and drums, and rewrites only that bar's harmony layer in the candidate output files.
- The result view now uses a top `Candidate Overview` comparison bar instead of showing all options as equal-width cards.
- Each candidate now exposes `full_progression_text` and `bar_summary` in `meta.json`.
- The detailed candidate view shows a large full progression header, expanded metadata, and a `Harmony Timeline` section.
- `Harmony Timeline` renders one bar per block with chord name, degree, representative melody pitches, chord tones, and a simple melody-to-chord match percentage.
- Browser playback, preview volume, reroll actions, and part mute controls are still shared across the page.
