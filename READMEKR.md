# py2fl

`py2fl`은 텍스트 프롬프트, 멜로디 MIDI, 또는 둘 다를 입력으로 받아 FL Studio에 바로 가져갈 수 있는 MIDI 세트를 생성하는 로컬 Python 도구입니다.

기본 워크플로우는 파일 중심입니다.

- `melody.mid`, `chords.mid`, `bass.mid`, `drums.mid`를 각각 생성
- `full_arrangement.mid` 통합본도 함께 생성
- 로컬 Web UI에서 후보 비교 및 미리듣기
- 전체 리롤, 코드 리롤, bar 단위 harmony 리롤 지원
- FL Studio에 드래그해서 바로 편집할 수 있도록 출력 구조 유지

영문 기본 문서는 [README.md](README.md)를 참고하세요.

## 주요 기능

- 텍스트만으로 생성
- 멜로디 MIDI만으로 생성
- 텍스트 + 멜로디 MIDI 하이브리드 생성
- 여러 후보를 한 번에 만드는 candidate batch
- 브라우저에서 전체 arrangement 미리듣기
- Harmony Timeline에서 bar 단위 미리듣기
- `Melody`, `Chords`, `Bass`, `Drums` 파트별 mute
- Preview volume 슬라이더
- bar 단위 `Reroll Harmony`
- 가장 최근에 리롤된 bar 강조 표시

## 출력 파일

각 candidate 폴더에는 다음 파일이 생성됩니다.

- `melody.mid`
- `chords.mid`
- `bass.mid`
- `drums.mid`
- `full_arrangement.mid`
- `meta.json`

후보를 여러 개 생성하면 batch 폴더도 함께 생깁니다.

- `option_01`, `option_02`, ...
- `batch_meta.json`

## 요구사항

- Python `>= 3.12`
- CLI는 Windows, macOS, Linux에서 사용 가능
- FL Studio는 생성 자체에는 필요 없지만, 최종 사용 대상 DAW입니다

## 설치

### Editable install

```bash
pip install -e .
```

설치 후 사용 가능한 엔트리포인트:

- `py2fl`
- `py2fl-web`

### 설치 없이 실행

PowerShell:

```powershell
$env:PYTHONPATH='src'
python -m py2fl.cli generate --text "dark trap anthem" --bars 4 --out .\exports
python -m py2fl.cli serve --host 127.0.0.1 --port 8765 --out .\exports
```

## CLI

### Generate

```bash
py2fl generate [options]
```

옵션:

- `--text`: 텍스트 프롬프트 또는 가사
- `--melody-midi`: 입력 멜로디 MIDI 경로
- `--tempo`: BPM override
- `--key`: `C`, `F#`, `A minor` 같은 key override
- `--genre`: `trap`, `rnb`, `house` 같은 장르 힌트
- `--bars`: 마디 수
- `--seed`: 재현 가능한 랜덤 시드
- `--count`: 후보 개수
- `--out`: 출력 루트 디렉터리

규칙:

- `--text`와 `--melody-midi` 중 최소 하나는 필수입니다.
- `--count 1`이면 single candidate를 생성합니다.
- `--count > 1`이면 batch 폴더 아래 여러 candidate를 생성합니다.

예시:

```bash
py2fl generate --text "dark trap anthem" --bars 8 --seed 7 --out ./exports
py2fl generate --melody-midi ./idea.mid --tempo 100 --out ./exports
py2fl generate --text "dreamy rnb night drive" --melody-midi ./topline.mid --seed 3 --out ./exports
py2fl generate --text "dreamy rnb night drive" --count 4 --out ./exports
```

### Web UI 실행

```bash
py2fl serve [options]
```

옵션:

- `--host`: 기본값 `127.0.0.1`
- `--port`: 기본값 `8765`
- `--out`: 출력 루트, 기본값 `exports`

예시:

```bash
py2fl serve --host 127.0.0.1 --port 8765 --out ./exports
```

## Windows 배치 파일

다음으로도 Web UI를 실행할 수 있습니다.

```bat
run_web_ui.bat
```

옵션 인자:

```bat
run_web_ui.bat 127.0.0.1 8765 .\exports
```

## Web UI

Web UI에서는 다음이 가능합니다.

- 1~8개 후보를 한 번에 생성
- 상단 Candidate Overview에서 후보 비교
- 전체 arrangement 미리듣기
- Harmony Timeline에서 bar 단위 미리듣기
- `Melody`, `Chords`, `Bass`, `Drums` mute
- Preview volume 조절
- `Reroll All`
- `Reroll Chords`
- 특정 bar의 `Reroll Harmony`
- 선택 후보를 `batch_meta.json`에 저장

### Harmony Timeline

각 bar 카드에는 다음 정보가 표시됩니다.

- bar index
- chord name
- degree
- chord tones
- representative melody pitches
- melody-to-chord match percentage

동작:

- `Play Bar`: 해당 bar만 미리듣기
- `Reroll Harmony`: 해당 bar의 harmony만 다시 생성

리롤 시 동작:

- `chords.mid`, `bass.mid`, `full_arrangement.mid`가 갱신됩니다
- melody와 drums는 유지됩니다
- 가장 최근에 리롤된 bar는 더 진한 배경과 `Recently Updated` 라벨로 표시됩니다
- bar 리롤은 전체 페이지 새로고침 없이 필요한 UI 조각만 갱신합니다

## 생성 규칙

### 입력 모드

- Text only: melody, chords, bass, drums를 모두 생성
- Melody MIDI only: 멜로디를 보존하고 반주를 생성
- Text + melody MIDI: 멜로디를 보존하고 텍스트를 스타일 제약으로 사용

### 멜로디 시작 정렬

입력 멜로디가 tick `0`에서 시작하지 않으면, 첫 노트를 기준으로 앞으로 당긴 뒤 분석하고 생성합니다.

관련 메타:

- `source_start_offset_ticks`
- `melody_aligned_to_start`

### 코드 생성

멜로디 기반 코드 생성은 규칙 기반이며 progression-aware 방식입니다.

현재 특징:

- bar 단위 멜로디 분석
- transition-aware chord scoring
- `triad`, `7th`, `add9`, `sus2`, `sus4` 변형 사용
- seed에 따른 candidate 다양화

완전한 기능화성 분석기는 아니고, 실용적인 MIDI 생성에 초점을 맞춘 구조입니다.

## 메타데이터

### `meta.json`

주요 필드:

- `input_mode`
- `tempo`
- `key`
- `bars`
- `style_tags`
- `source_melody`
- `source_start_offset_ticks`
- `melody_aligned_to_start`
- `progression_label`
- `progression_degrees`
- `full_progression_text`
- `bar_summary`
- `drum_pattern`
- `bass_pattern`
- `candidate_index`
- `candidate_seed`
- `reroll_scope`
- `recently_updated_bar`
- `preview_file`

### `bar_summary`

각 bar 항목에는 다음 값이 들어갑니다.

- `bar_index`
- `start_tick`
- `end_tick`
- `degree`
- `chord_name`
- `chord_tones`
- `representative_melody_pitches`
- `matching_ratio`
- `matching_percent`
- `recently_updated`

### `batch_meta.json`

다음 내용을 포함합니다.

- 원본 요청 입력값
- 후보 개수
- 선택된 후보
- candidate 폴더 목록
- 각 candidate의 요약 정보

## Python API

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

## FL Studio 사용 흐름

일반적인 사용 순서:

1. 텍스트, 멜로디 MIDI, 또는 둘 다를 이용해 후보를 생성합니다.
2. 브라우저에서 후보를 비교하고 미리듣습니다.
3. 원하는 후보를 선택합니다.
4. `melody.mid`, `chords.mid`, `bass.mid`, `drums.mid`, `full_arrangement.mid`를 FL Studio로 가져옵니다.
5. FL Studio 안에서 계속 편곡합니다.

## 테스트

빠른 검증:

```powershell
python -m compileall src tests
```

`pyproject.toml`에 pytest 설정은 들어 있지만, 현재 환경에서는 Windows temp 디렉터리 권한 문제 때문에 pytest가 fixture setup 단계에서 실패할 수 있습니다.

## 제한사항

- 규칙 기반 생성기이며 LLM 작곡 시스템은 아닙니다
- FL Studio Python API 직접 제어는 하지 않습니다
- 실시간 MIDI/OSC 브리지 없음
- 브라우저 미리듣기는 lightweight synth 기반이므로 DAW 렌더와 동일하지 않습니다
- bar 리롤은 현재 `chords + bass` 중심이며 전체 편곡 변화를 대신하지는 않습니다
