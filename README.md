# py2fl

`py2fl` is a local Python tool for generating FL Studio-friendly MIDI arrangements from text prompts, melody MIDI, chord progressions, or combinations of those inputs.

It focuses on a practical file-based workflow:

- generate separate MIDI files for `melody`, `chords`, `bass`, `drums`
- generate a combined `full_arrangement.mid`
- preview and compare candidates in a local web UI
- reroll harmony globally or per bar
- keep outputs easy to drag into FL Studio

For Korean documentation, see [READMEKR.md](READMEKR.md).

## Features

- Text-only generation
- Melody-only generation from an input MIDI file
- Hybrid generation from text + melody MIDI
- Chord-to-melody generation from degree or named chord progressions
- Candidate batch generation with multiple options
- Browser preview for full arrangements and per-bar timeline slices
- Per-part mute controls in the web UI
- Bar-level harmony reroll with partial DOM refresh
- Visual harmony timeline with chord names, melody focus notes, and match percentage
- Separate part exports plus a combined arrangement export

## Output Files

Each generated candidate folder contains:

- `melody.mid`
- `chords.mid`
- `bass.mid`
- `drums.mid`
- `full_arrangement.mid`
- `meta.json`

When generating more than one candidate, `py2fl` also creates a batch folder with:

- `option_01`, `option_02`, ... candidate subfolders
- `batch_meta.json`

## Requirements

- Python `>= 3.12`
- Windows, macOS, or Linux for CLI usage
- FL Studio is not required to generate files, but is the target DAW workflow

## Installation

### Editable install

```bash
pip install -e .
```

Installed entry points:

- `py2fl`
- `py2fl-web`

### Without installing

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

Options:

- `--text`: text prompt or lyrics
- `--melody-midi`: input melody MIDI path
- `--progression`: chord progression such as `1-5-6-4` or `Am-F-C-G`
- `--tempo`: tempo override in BPM
- `--key`: key override such as `C`, `F#`, `A minor`
- `--genre`: genre hint such as `trap`, `rnb`, `house`
- `--bars`: number of bars
- `--seed`: random seed for reproducible output
- `--count`: number of candidates to generate
- `--out`: base output directory

Notes:

- At least one of `--text`, `--melody-midi`, or `--progression` is required.
- `--count 1` returns a single candidate.
- `--count > 1` creates a batch directory with multiple candidate folders.

Examples:

```bash
py2fl generate --text "dark trap anthem" --bars 8 --seed 7 --out ./exports
py2fl generate --melody-midi ./idea.mid --tempo 100 --out ./exports
py2fl generate --text "dreamy rnb night drive" --melody-midi ./topline.mid --seed 3 --out ./exports
py2fl generate --text "dreamy rnb night drive" --count 4 --out ./exports
py2fl generate --progression "1-5-6-4" --text "dreamy rnb topline" --count 4 --out ./exports
```

### Serve the web UI

```bash
py2fl serve [options]
```

Options:

- `--host`: default `127.0.0.1`
- `--port`: default `8765`
- `--out`: output root directory, default `exports`

Example:

```bash
py2fl serve --host 127.0.0.1 --port 8765 --out ./exports
```

## Windows Batch Launcher

You can also start the web UI with:

```bat
run_web_ui.bat
```

Optional arguments:

```bat
run_web_ui.bat 127.0.0.1 8765 .\exports
```

## Web UI

The local web UI supports:

- generating 1 to 8 candidates at once
- switching between candidates from the top overview bar
- full-arrangement preview
- per-bar preview from the harmony timeline
- per-part mute toggles for `Melody`, `Chords`, `Bass`, `Drums`
- preview volume slider
- `Reroll All`
- `Reroll Chords`
- `Reroll Harmony` for a single timeline bar
- A dedicated `/melody-from-chords` page for writing toplines from chord progressions
- saving the selected candidate into `batch_meta.json`

### Harmony Timeline

Each bar card shows:

- bar index
- chord name
- degree
- chord tones
- representative melody pitches
- melody-to-chord match percentage

Actions:

- `Play Bar`: preview only that bar slice
- `Reroll Harmony`: replace harmony for only that bar

Behavior:

- bar reroll updates `chords.mid`, `bass.mid`, and `full_arrangement.mid`
- melody and drums stay unchanged for bar-level reroll
- the most recently rerolled bar is highlighted with a darker card and a `Recently Updated` label
- bar reroll now updates the relevant UI fragments without a full page reload


### Melody from Chords

Open `/melody-from-chords` in the local web UI to use the chord-to-melody flow.

This page supports:

- degree input such as `1-5-6-4`
- named chords such as `Am-F-C-G`
- optional style text such as `dreamy rnb topline`
- 1 to 8 melody candidates
- `Reroll All`, `Reroll Melody`, and per-bar `Reroll Melody`
- full-arrangement preview and per-bar preview

Behavior:

- user-entered chord progression stays fixed
- melody candidates change across seeds and rerolls
- bar reroll updates `melody.mid` and `full_arrangement.mid` while preserving the harmonic path

## Generation Rules

### Input modes

- Text only: generate melody, chords, bass, drums
- Melody MIDI only: preserve the melody and generate harmony + rhythm around it
- Text + melody MIDI: preserve melody and use text as a style constraint

### Melody alignment

If the input melody starts after tick `0`, `py2fl` aligns the first note to the start before analysis and generation.

Metadata fields:

- `source_start_offset_ticks`
- `melody_aligned_to_start`

### Chord generation

Melody-driven chord generation is rule-based and progression-aware.

Current behavior includes:

- per-bar melody analysis
- transition-aware chord scoring
- chord flavor variation such as `triad`, `7th`, `add9`, `sus2`, `sus4`
- candidate diversity across seeds

This is not a full functional-harmony engine. It is designed for stable, practical MIDI generation.

## Metadata

### `meta.json`

Common fields include:

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

Each bar entry contains values such as:

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

Batch metadata includes:

- original request inputs
- candidate count
- selected candidate
- candidate folders
- summary info for each candidate

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

## FL Studio Workflow

Typical workflow:

1. Generate a candidate set from text, melody MIDI, or both.
2. Audition candidates in the browser.
3. Keep the selected candidate.
4. Drag `melody.mid`, `chords.mid`, `bass.mid`, `drums.mid`, or `full_arrangement.mid` into FL Studio.
5. Continue arranging inside FL Studio.

## Testing

Quick checks:

```powershell
python -m compileall src tests
```

Pytest is configured in `pyproject.toml`, but in this environment it may fail early because Windows temp directory permissions block fixture setup.

## Limitations

- Rule-based generation, not an LLM composition system
- No direct FL Studio Python API integration
- No real-time MIDI/OSC bridge
- Browser preview uses lightweight synth playback, not DAW-accurate rendering
- Harmony reroll currently targets bar-level `chords + bass`, not full orchestration changes
