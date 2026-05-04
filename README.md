# py2fl

`py2fl` is a local Python tool for generating FL Studio-friendly MIDI arrangements from text prompts, melody MIDI, chord progressions, or combinations of those inputs.

It focuses on a practical file-based workflow:

- generate separate MIDI files for `melody`, `chords`, `bass`, `drums`
- generate a combined `full_arrangement.mid`
- preview and compare candidates in a local web UI
- reroll harmony globally or per bar
- save winning candidates to a personal library and recall them later
- render WAV audio previews via SoundFont (optional)
- get LLM-powered or rule-based parameter suggestions from a text prompt
- web UI in English or Korean with a language toggle
- configure the Gemini API key from the web Settings page
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
- Library page for saving winning candidates and continuing from them later

### Musical realism controls (opt-in)

All controls accept `off / low / med / high / auto` and default to `off`, so
existing seeds reproduce bit-for-bit unless you explicitly turn them on.

- **Humanize** — gaussian timing jitter and per-note velocity variation, with
  separate scaling for kick / snare / hi-hat and shared offsets across stacked
  chord notes
- **Swing** — pushes notes that land on the off-half of an 8th-note pair later
  in time; applied to melody, chords, and drum hi-hats only
- **Drum dynamics** — adds a hi-hat accent curve, randomized snare ghost notes,
  extra off-beat hats, and a 2-4 hit fill at the end of every 4-bar phrase
- **Harmony spice** — swaps some diatonic chord events for the secondary
  dominant of the next chord or for a borrowed chord from the parallel mode
  (bVII / bVI in major, IV in minor)
- **Section dynamics** — splits the bars into verse and chorus regions; chorus
  bars get melody +1 octave with louder velocity, lifted chord/drum volume,
  and a sub-octave bass; high setting on >=16 bars gives an A-B-A-B layout
- **Modulate** — when bars >= 16, transposes the last quarter of the melody,
  chord, and bass tracks up by 2 (low/med) or 5 (high) semitones

## Output Files

Each generated candidate folder contains:

- `melody.mid`
- `chords.mid`
- `bass.mid`
- `drums.mid`
- `full_arrangement.mid`
- `arrangement.rpp` (REAPER project — opens the four MIDI files into four pre-routed tracks)
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
- `--chord-density {1,2,3,auto}`: chords per bar
- `--melody-density {sparse,normal,dense,xdense,auto}`: melody note density
- `--chord-rhythm-style {hold,stab,strum,auto}`: chord playback style
- `--humanize {off,low,med,high,auto}`: timing + velocity jitter (default `off`)
- `--swing {off,low,med,high,auto}`: 8th-note swing feel (default `off`)
- `--drum-dynamics {off,low,med,high,auto}`: accent curve, ghost notes, fills (default `off`)
- `--harmony-spice {off,low,med,high,auto}`: secondary dominants and borrowed chords (default `off`)
- `--section-dynamics {off,low,med,high,auto}`: verse/chorus contrast (default `off`)
- `--modulate {off,low,med,high,auto}`: transpose final 1/4 of the track when bars >= 16 (default `off`)
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
py2fl generate --text "epic lift anthem" --bars 16 --humanize med --swing low --drum-dynamics high --harmony-spice med --section-dynamics high --modulate med --seed 42 --out ./exports
```

### Serve the web UI

```bash
py2fl serve [options]
```

Options:

- `--host`: default `127.0.0.1`
- `--port`: default `8765`
- `--out`: output root directory, default `exports`
- `--library-dir`: library directory, default `<out>/../library`
- `--soundfont`: path to a `.sf2` file for audio preview (or set `PY2FL_SOUNDFONT`)
- `--fluidsynth`: path to the fluidsynth binary (or set `PY2FL_FLUIDSYNTH`)

Example:

```bash
py2fl serve --host 127.0.0.1 --port 8765 --out ./exports
py2fl serve --soundfont ./TimGM6mb.sf2 --out ./exports
```

### Library

```bash
py2fl library list [--library-dir ./library] [--json]
```

Lists saved candidates from disk. Pass `--json` for machine-readable output.

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

## Library

Save winning candidates and recall them later, even after `exports/` is cleaned out.

- Default location: `library/` next to your `exports/` directory.
- Each saved entry is a **copy** of the candidate folder (immutable snapshot).
- Trigger: explicit `★ Save to Library` button on a candidate detail card.

### Storage layout

```
library/
├── index.json                 # catalog of saved entries
└── <slug>__<short_hash>/      # full copy of a candidate folder
    ├── melody.mid
    ├── chords.mid
    ├── bass.mid
    ├── drums.mid
    ├── full_arrangement.mid
    └── meta.json
```

### Continue from this

The library page (`/library` in the web UI) lists every saved entry. Each row offers:

- `Open` — view files, controls, and download the MIDI directly
- `Continue from this` — preload the original prompt, key, tempo, bars, and all 9 controls into the generator form so you can iterate from a saved starting point
- `Delete` — remove the saved folder and index entry (asks for confirmation)

### CLI

```bash
py2fl library list                    # human-readable table
py2fl library list --json             # machine-readable JSON
py2fl library list --library-dir ./my_library
```

## Audio Preview (SoundFont)

The browser preview defaults to lightweight in-page MIDI synthesis. To get
DAW-style sound, render WAV stems through a SoundFont using
[fluidsynth](https://www.fluidsynth.org/).

### Setup

1. Install the `fluidsynth` binary. On Windows the easiest options are
   `choco install fluidsynth`, `scoop install fluidsynth`, or
   `winget install FluidSynth.FluidSynth`. Or download a release zip from
   <https://github.com/FluidSynth/fluidsynth/releases>, extract it, and add
   the `bin/` folder to PATH.
2. Download a `.sf2` SoundFont. A small free option is
   [`TimGM6mb.sf2`](https://musescore.org/sites/musescore.org/files/2018-07/TimGM6mb.sf2)
   (~5.7 MB, CC0).
3. Configure the path. Three options:
   - **Web UI**: open Settings, paste the SoundFont path (and optionally a
     fluidsynth binary override), click `Save paths`. Persists to
     `~/.py2fl/config.json`.
   - **Environment**: set `PY2FL_SOUNDFONT=/path/to/your.sf2` (and optionally
     `PY2FL_FLUIDSYNTH=/path/to/fluidsynth`).
   - **CLI**: pass `--soundfont /path/to/your.sf2 --fluidsynth /path/to/bin`
     when starting `py2fl serve`.

### Behavior

- Each candidate detail card and library entry page exposes an `Audio Preview`
  panel. Click `Render Audio Preview` to render five WAVs into
  `<candidate>/preview/`: `melody.wav`, `chords.wav`, `bass.wav`, `drums.wav`,
  and `full_arrangement.wav` (the mix).
- Renders are cached. Re-rendering only happens when the source `.mid` is newer
  than the cached `.wav`, or when you click `Re-render`.
- If `fluidsynth` or the SoundFont is missing, the panel falls back to the
  existing in-browser MIDI preview and shows a hint about what to configure.

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

## Smart Suggestions (Gemini Flash, optional)

The web UI has a `✨ Suggest from Text` button next to each `Generate` button.
It reads your text prompt and pre-fills tempo, key, genre, bars, and all 9
musical realism controls so you can tweak before generating.

### Two modes

- **LLM mode** (preferred when configured): if `GEMINI_API_KEY` (or
  `GOOGLE_API_KEY`) is set in your environment, py2fl calls
  [Google Gemini Flash](https://aistudio.google.com/app/apikey) to translate
  free-form prompts ("ethereal post-rock at golden hour") into concrete
  parameter values. Gemini's free tier covers personal use comfortably — no
  card required. Check your live quota at
  [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit);
  Google adjusts the limits over time.
- **Rule-based fallback**: with no key configured, py2fl uses the same
  `text_analysis.py` keyword heuristics that drive `auto` mode. The button
  still works, just with simpler logic.

### Setup (LLM mode)

There are two ways to provide the key:

**A. From the web UI** (recommended for casual use)

1. Get a free Gemini API key at <https://aistudio.google.com/app/apikey>.
2. Open the web UI, click **Settings** (top right) and paste your key.
3. Tick **Save to disk** to persist it across restarts (writes
   `~/.py2fl/config.json` with mode 600). Leave it unchecked for
   session-only use.

**B. From the shell** (recommended for headless / CI usage)

1. Set `GEMINI_API_KEY=your-key` in your shell or `.env`.
2. Optional: override the model with `PY2FL_GEMINI_MODEL=gemini-2.5-flash` (default is `gemini-flash-latest` which always points at the current Flash model).
3. Restart the web UI.

## Languages

The web UI supports English (default) and Korean. Use the **EN / 한국어**
toggle at the top of any page to switch — your choice is stored in a cookie.

The result panel shows the source (`llm` or `rule`) and a one-line rationale
so you can tell which path was taken. All API errors gracefully fall back to
rule-based output — you'll never get a broken page from a network blip.

## REAPER Workflow

Each candidate folder also contains an `arrangement.rpp` REAPER project file
that points to the four MIDI files in the same folder. Open it directly in
REAPER and you get four pre-routed tracks (`Melody`, `Chords`, `Bass`,
`Drums`) at the project's tempo, ready to play.

If the MIDI items show up empty in some REAPER builds, drag the `.mid` files
onto the existing tracks manually — they live in the same folder. The `.rpp`
is plain text so it is easy to inspect or hand-edit.

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
- Browser preview uses lightweight synth playback by default; SoundFont audio rendering is opt-in via `--soundfont`
- Harmony reroll currently targets bar-level `chords + bass`, not full orchestration changes
