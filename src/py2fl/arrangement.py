from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import random

from .models import Arrangement, BAR_TICKS, MelodyAnalysis, NoteEvent, TextFeatures
from .music_theory import clamp_pitch, midi_for_pitch_class, normalize_key_name, scale_for
from .progression import ChordBar, ParsedProgression


GENRE_TEMPOS = {
    "trap": 140,
    "rnb": 88,
    "house": 124,
    "ambient": 76,
    "pop": 110,
}

PROGRESSION_LIBRARY = {
    ("major", "pop"): [
        ("Lift 1-5-6-4", [1, 5, 6, 4]),
        ("Turn 6-4-1-5", [6, 4, 1, 5]),
        ("Resolve 1-4-6-5", [1, 4, 6, 5]),
    ],
    ("major", "house"): [
        ("Club 1-5-6-4", [1, 5, 6, 4]),
        ("Drive 1-6-4-5", [1, 6, 4, 5]),
        ("Pulse 4-1-5-6", [4, 1, 5, 6]),
    ],
    ("major", "ambient"): [
        ("Float 1-4-6-5", [1, 4, 6, 5]),
        ("Wide 6-5-1-4", [6, 5, 1, 4]),
        ("Open 1-5-4-6", [1, 5, 4, 6]),
    ],
    ("minor", "trap"): [
        ("Trap 1-6-7-5", [1, 6, 7, 5]),
        ("Shadow 1-7-6-5", [1, 7, 6, 5]),
        ("Tension 6-1-7-5", [6, 1, 7, 5]),
    ],
    ("minor", "rnb"): [
        ("Silk 1-4-6-5", [1, 4, 6, 5]),
        ("Late 6-5-1-4", [6, 5, 1, 4]),
        ("Glass 1-7-6-4", [1, 7, 6, 4]),
    ],
    ("minor", "ambient"): [
        ("Mist 1-7-6-5", [1, 7, 6, 5]),
        ("Haze 6-5-1-7", [6, 5, 1, 7]),
        ("Fade 1-4-7-6", [1, 4, 7, 6]),
    ],
}

DRUM_VARIANTS = {
    "trap": [
        ("Trap Snap", [0, 2, 2.5], [0.5, 1.5, 2.5, 3.5]),
        ("Trap Push", [0, 1.5, 2.75], [0.75, 1.75, 2.75, 3.75]),
        ("Trap Sparse", [0, 2.25], [1.5, 3.5]),
    ],
    "house": [
        ("House Four", [0, 1, 2, 3], []),
        ("House Lift", [0, 1, 2, 3], [0.5, 1.5, 2.5, 3.5]),
        ("House Roll", [0, 1, 2, 3], [0.75, 1.75, 2.75, 3.75]),
    ],
    "rnb": [
        ("RNB Pocket", [0, 2], []),
        ("RNB Lean", [0, 1.5, 3], []),
        ("RNB Bounce", [0, 2.25], [1.5, 3.5]),
    ],
    "ambient": [
        ("Ambient Light", [0, 2], []),
        ("Ambient Pulse", [0, 2.5], []),
        ("Ambient Drift", [0], []),
    ],
    "pop": [
        ("Pop Straight", [0, 2], []),
        ("Pop Lift", [0, 1.5, 3], []),
        ("Pop Drive", [0, 2, 3], []),
    ],
}

BASS_VARIANTS = {
    "trap": ["staccato", "stair", "hold"],
    "house": ["pulse", "staccato", "octave"],
    "rnb": ["hold", "pulse", "syncopated"],
    "ambient": ["hold", "pulse"],
    "pop": ["hold", "pulse", "octave"],
}

TRANSITION_WEIGHTS: dict[tuple[int, int], float] = {}
for progressions in PROGRESSION_LIBRARY.values():
    for _, degrees in progressions:
        for current, nxt in zip(degrees, degrees[1:] + degrees[:1]):
            TRANSITION_WEIGHTS[(current, nxt)] = TRANSITION_WEIGHTS.get((current, nxt), 0.0) + 1.0


@dataclass(frozen=True, slots=True)
class ChordOption:
    degree: int
    label: str
    pitch_classes: tuple[int, ...]
    root_pc: int


@dataclass(frozen=True, slots=True)
class HarmonyProfile:
    degree_bias: dict[int, float]
    flavor_bias: dict[str, float]


def build_arrangement(*, text_features: TextFeatures | None, melody_analysis: MelodyAnalysis | None, tempo: int | None, key: str | None, bars: int | None, seed: int | None) -> Arrangement:
    randomizer = random.Random(seed)
    resolved_mode = _resolve_mode(text_features, melody_analysis)
    resolved_key = normalize_key_name(key or (melody_analysis.key if melody_analysis else _default_key_for(text_features, resolved_mode)))
    resolved_bars = bars or (melody_analysis.bars if melody_analysis else 8)
    resolved_tempo = tempo or (melody_analysis.tempo_bpm if melody_analysis else None) or _default_tempo_for(text_features)
    style_tags = list(text_features.style_tags) if text_features else []

    if melody_analysis:
        melody = _normalize_melody(melody_analysis.notes, resolved_bars)
        chords, progression_degrees, progression_label = _generate_chords_for_melody(resolved_key, resolved_mode, melody, resolved_bars, randomizer)
    else:
        progression_label, progression_degrees = _pick_progression_variant(resolved_mode, text_features, randomizer)
        chords = _generate_progression_chords(resolved_key, resolved_mode, resolved_bars, progression_degrees, randomizer)
        melody = _generate_topline(resolved_key, resolved_mode, chords, resolved_bars, randomizer)

    bass, bass_pattern = _generate_bassline(chords, text_features, randomizer)
    drums, drum_pattern = _generate_drum_pattern(resolved_bars, text_features, randomizer)
    return Arrangement(
        melody=melody,
        chords=chords,
        bass=bass,
        drums=drums,
        tempo_bpm=resolved_tempo,
        key=resolved_key,
        mode=resolved_mode,
        bars=resolved_bars,
        style_tags=style_tags,
        progression_label=progression_label,
        progression_degrees=progression_degrees,
        drum_pattern=drum_pattern,
        bass_pattern=bass_pattern,
    )


def build_arrangement_from_progression(*, progression: ParsedProgression, text_features: TextFeatures | None, tempo: int | None, seed: int | None) -> Arrangement:
    randomizer = random.Random(seed)
    resolved_tempo = tempo or _default_tempo_for(text_features)
    style_tags = list(text_features.style_tags) if text_features else []
    chords = _generate_fixed_progression_chords(progression.chord_bars)
    melody = _generate_melody_from_progression(progression, text_features, randomizer)
    bass, bass_pattern = _generate_bassline(chords, text_features, randomizer)
    drums, drum_pattern = _generate_drum_pattern(progression.bars, text_features, randomizer)
    degrees = [bar.degree for bar in progression.chord_bars]
    preview = '-'.join(bar.source_token for bar in progression.chord_bars[:4])
    label = f'ChordLine {preview}' if preview else 'ChordLine'
    return Arrangement(
        melody=melody,
        chords=chords,
        bass=bass,
        drums=drums,
        tempo_bpm=resolved_tempo,
        key=progression.key,
        mode=progression.mode,
        bars=progression.bars,
        style_tags=style_tags,
        progression_label=label,
        progression_degrees=degrees,
        drum_pattern=drum_pattern,
        bass_pattern=bass_pattern,
    )


def _resolve_mode(text_features: TextFeatures | None, melody_analysis: MelodyAnalysis | None) -> str:
    if melody_analysis:
        return melody_analysis.mode
    if text_features and text_features.mood in {"dark", "dreamy"}:
        return "minor"
    return "major"


def _default_key_for(text_features: TextFeatures | None, mode: str) -> str:
    if text_features and text_features.genre == "trap":
        return "F#"
    if mode == "minor":
        return "A"
    return "C"


def _default_tempo_for(text_features: TextFeatures | None) -> int:
    if text_features:
        return GENRE_TEMPOS.get(text_features.genre, 110)
    return 110


def _pick_progression_variant(mode: str, text_features: TextFeatures | None, randomizer: random.Random) -> tuple[str, list[int]]:
    genre = text_features.genre if text_features else "pop"
    options = PROGRESSION_LIBRARY.get((mode, genre)) or PROGRESSION_LIBRARY.get((mode, "pop")) or [("Default 1-5-6-4", [1, 5, 6, 4])]
    label, degrees = randomizer.choice(options)
    return label, degrees


def _generate_progression_chords(key: str, mode: str, bars: int, progression: list[int], randomizer: random.Random) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
    for bar in range(bars):
        degree = progression[bar % len(progression)]
        option = _pick_text_chord_option(key, mode, degree, bar, bars, randomizer)
        notes.extend(_bar_chord_notes(option, bar * BAR_TICKS))
    return notes


def _generate_fixed_progression_chords(chord_bars: list[ChordBar]) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
    for bar_index, chord_bar in enumerate(chord_bars):
        notes.extend(_bar_notes_from_pitch_classes(chord_bar.root_pc, chord_bar.pitch_classes, bar_index * BAR_TICKS))
    return notes


def _generate_chords_for_melody(key: str, mode: str, melody: list[NoteEvent], bars: int, randomizer: random.Random) -> tuple[list[NoteEvent], list[int], str]:
    scale = scale_for(key, mode)
    profile = _build_harmony_profile(randomizer)
    bar_options = [_build_degree_options(scale, degree) for degree in range(1, 8)]
    choices = [option for options in bar_options for option in options]
    states: list[dict[int, tuple[float, int | None]]] = []

    for bar in range(bars):
        bar_notes = _notes_for_bar(melody, bar)
        current_scores: dict[int, tuple[float, int | None]] = {}
        for option_index, option in enumerate(choices):
            base_score = _score_chord_option(bar_notes, option, bar, bars, profile)
            if bar == 0:
                current_scores[option_index] = (base_score, None)
                continue
            best_previous: tuple[float, int] | None = None
            for previous_index, (previous_score, _) in states[bar - 1].items():
                previous_option = choices[previous_index]
                total_score = previous_score + base_score + _transition_bonus(previous_option, option, bar, bars, profile)
                if best_previous is None or total_score > best_previous[0]:
                    best_previous = (total_score, previous_index)
            if best_previous is not None:
                current_scores[option_index] = best_previous
        states.append(current_scores)

    final_scores = states[-1]
    ranked = sorted(final_scores.items(), key=lambda item: item[1][0], reverse=True)
    top_choices = [option_index for option_index, _ in ranked[: min(3, len(ranked))]]
    best_option_index = randomizer.choice(top_choices)

    selected_indices: list[int] = []
    for bar in range(bars - 1, -1, -1):
        selected_indices.append(best_option_index)
        _, previous_index = states[bar][best_option_index]
        if previous_index is None:
            break
        best_option_index = previous_index
    selected_indices.reverse()

    selected_options = [choices[index] for index in selected_indices]
    notes: list[NoteEvent] = []
    degrees: list[int | None] = []
    flavors: list[str] = []
    for bar, option in enumerate(selected_options):
        notes.extend(_bar_chord_notes(option, bar * BAR_TICKS))
        degrees.append(option.degree)
        flavors.append(option.label)

    label = "MeloFlow " + "-".join(str(value) for value in degrees[: min(4, len(degrees))])
    if flavors:
        dominant_flavors = [name for name, _ in Counter(flavors).most_common(3)]
        label += " | " + ", ".join(dominant_flavors)
    return notes, degrees, label


def _pick_text_chord_option(key: str, mode: str, degree: int, bar: int, bars: int, randomizer: random.Random) -> ChordOption:
    scale = scale_for(key, mode)
    options = _build_degree_options(scale, degree)
    weighted: list[tuple[ChordOption, float]] = []
    for option in options:
        weight = 1.0
        if option.label == "triad":
            weight = 1.8
        elif option.label == "7th":
            weight = 1.6
        elif option.label == "add9":
            weight = 1.4
        else:
            weight = 0.9
        if bar == bars - 1 and option.degree == 1 and option.label in {"triad", "7th"}:
            weight += 1.2
        weighted.append((option, weight))
    return randomizer.choices([item[0] for item in weighted], weights=[item[1] for item in weighted], k=1)[0]


def _build_degree_options(scale: list[int], degree: int) -> list[ChordOption]:
    index = (degree - 1) % 7
    root_pc = scale[index]
    second_pc = scale[(index + 1) % 7]
    third_pc = scale[(index + 2) % 7]
    fourth_pc = scale[(index + 3) % 7]
    fifth_pc = scale[(index + 4) % 7]
    seventh_pc = scale[(index + 6) % 7]

    triad = (root_pc, third_pc, fifth_pc)
    options = [
        ChordOption(degree=degree, label="triad", pitch_classes=triad, root_pc=root_pc),
        ChordOption(degree=degree, label="7th", pitch_classes=(root_pc, third_pc, fifth_pc, seventh_pc), root_pc=root_pc),
        ChordOption(degree=degree, label="add9", pitch_classes=(root_pc, third_pc, fifth_pc, second_pc), root_pc=root_pc),
    ]

    diminished = ((third_pc - root_pc) % 12 == 3) and ((fifth_pc - third_pc) % 12 == 3)
    if not diminished:
        options.append(ChordOption(degree=degree, label="sus2", pitch_classes=(root_pc, second_pc, fifth_pc), root_pc=root_pc))
        options.append(ChordOption(degree=degree, label="sus4", pitch_classes=(root_pc, fourth_pc, fifth_pc), root_pc=root_pc))
    return options


def _score_chord_option(bar_notes: list[NoteEvent], option: ChordOption, bar: int, bars: int, profile: HarmonyProfile) -> float:
    if not bar_notes:
        score = 1.0 + profile.degree_bias.get(option.degree, 0.0) + profile.flavor_bias.get(option.label, 0.0)
        if option.label == "7th":
            score += 0.4
        elif option.label == "add9":
            score += 0.25
        return score

    score = 0.0
    pitch_classes = set(option.pitch_classes)
    for note in bar_notes:
        weight = max(1.0, note.duration / (BAR_TICKS / 4))
        pitch_class = note.pitch % 12
        if pitch_class in pitch_classes:
            score += 2.4 * weight
        else:
            score -= 1.8 * weight

    strong_note = max(bar_notes, key=lambda note: (note.duration, -note.start))
    strong_pc = strong_note.pitch % 12
    if strong_pc == option.root_pc:
        score += 3.0
    elif strong_pc in pitch_classes:
        score += 1.8

    if option.label == "7th":
        score += 0.8
        if strong_pc == option.pitch_classes[-1]:
            score += 0.9
    elif option.label == "add9":
        score += 0.7
        if strong_pc == option.pitch_classes[-1]:
            score += 0.8
    elif option.label in {"sus2", "sus4"}:
        score += 0.2
        if strong_pc == option.pitch_classes[1]:
            score -= 1.2

    score += profile.degree_bias.get(option.degree, 0.0)
    score += profile.flavor_bias.get(option.label, 0.0)
    if (bar + 1) % 4 == 0 and option.degree in {1, 5, 6}:
        score += 1.2
    if bar == bars - 1 and option.degree in {1, 6}:
        score += 1.6
    return score


def _transition_bonus(previous: ChordOption, current: ChordOption, bar: int, bars: int, profile: HarmonyProfile) -> float:
    score = TRANSITION_WEIGHTS.get((previous.degree, current.degree), 0.0) * 0.7
    if previous.degree == current.degree:
        score -= 0.9
    if previous.label == current.label and current.label in {"sus2", "sus4"}:
        score -= 0.4
    if current.label == "7th":
        score += 0.15
    elif current.label == "add9":
        score += 0.1
    score += profile.degree_bias.get(current.degree, 0.0) * 0.35
    score += profile.flavor_bias.get(current.label, 0.0) * 0.5
    if (bar + 1) % 4 == 0 and current.degree in {1, 5, 6}:
        score += 0.7
    if bar == bars - 1 and current.degree == 1:
        score += 1.0
    return score


def _build_harmony_profile(randomizer: random.Random) -> HarmonyProfile:
    degree_bias = {degree: randomizer.uniform(-1.0, 1.0) for degree in range(1, 8)}
    flavor_bias = {label: randomizer.uniform(-0.7, 0.7) for label in ("triad", "7th", "add9", "sus2", "sus4")}
    favored_degree = randomizer.choice([1, 4, 5, 6])
    degree_bias[favored_degree] += 0.8
    flavor_bias[randomizer.choice(["7th", "add9", "sus2", "sus4"])] += 0.6
    return HarmonyProfile(degree_bias=degree_bias, flavor_bias=flavor_bias)


def _bar_chord_notes(option: ChordOption, start_tick: int) -> list[NoteEvent]:
    pitches = _voice_pitch_classes(option.root_pc, option.pitch_classes)
    velocities = [72, 68, 68, 64, 62]
    return [
        NoteEvent(pitch=pitch, start=start_tick, duration=BAR_TICKS, velocity=velocities[min(index, len(velocities) - 1)], channel=1)
        for index, pitch in enumerate(pitches)
    ]


def _bar_notes_from_pitch_classes(root_pc: int, pitch_classes: tuple[int, ...], start_tick: int) -> list[NoteEvent]:
    pitches = _voice_pitch_classes(root_pc, pitch_classes)
    velocities = [72, 68, 68, 64, 62]
    return [
        NoteEvent(pitch=pitch, start=start_tick, duration=BAR_TICKS, velocity=velocities[min(index, len(velocities) - 1)], channel=1)
        for index, pitch in enumerate(pitches)
    ]


def _voice_pitch_classes(root_pc: int, pitch_classes: tuple[int, ...]) -> list[int]:
    root_pitch = midi_for_pitch_class(root_pc, 4)
    pitches = [root_pitch]
    reference = root_pitch + 1
    for pitch_class in pitch_classes[1:]:
        pitch = _pitch_at_or_above(pitch_class, reference)
        pitches.append(clamp_pitch(pitch, 48, 84))
        reference = pitch + 1
    return pitches


def _pitch_at_or_above(pitch_class: int, minimum_pitch: int) -> int:
    pitch = midi_for_pitch_class(pitch_class, 3)
    while pitch < minimum_pitch:
        pitch += 12
    return pitch


def _notes_for_bar(notes: list[NoteEvent], bar: int) -> list[NoteEvent]:
    bar_start = bar * BAR_TICKS
    bar_end = bar_start + BAR_TICKS
    return [note for note in notes if note.start < bar_end and note.end > bar_start]


def _generate_topline(key: str, mode: str, chords: list[NoteEvent], bars: int, randomizer: random.Random) -> list[NoteEvent]:
    scale = scale_for(key, mode)
    notes: list[NoteEvent] = []
    rhythms = [
        [0, BAR_TICKS // 4, BAR_TICKS // 2, BAR_TICKS * 3 // 4],
        [0, BAR_TICKS // 3, BAR_TICKS * 2 // 3, BAR_TICKS * 5 // 6],
        [0, BAR_TICKS // 4, BAR_TICKS * 5 // 8, BAR_TICKS * 7 // 8],
    ]
    chosen_rhythm = randomizer.choice(rhythms)
    for bar in range(bars):
        bar_chord = _notes_for_bar(chords, bar)
        chord_tones = [note.pitch % 12 for note in bar_chord] or scale[:3]
        last_pitch = notes[-1].pitch if notes else midi_for_pitch_class(scale[0], 5)
        for index, offset in enumerate(chosen_rhythm):
            pitch_class = chord_tones[index % len(chord_tones)] if index % 2 == 0 else randomizer.choice(scale)
            octave = 5 if pitch_class >= scale[0] else 6
            pitch = clamp_pitch(midi_for_pitch_class(pitch_class, octave), 60, 84)
            if abs(pitch - last_pitch) > 7:
                pitch += -12 if pitch > last_pitch else 12
            pitch = clamp_pitch(pitch, 60, 84)
            duration = max(BAR_TICKS // 6, BAR_TICKS // 4 if index != len(chosen_rhythm) - 1 else BAR_TICKS // 3)
            notes.append(NoteEvent(pitch=pitch, start=bar * BAR_TICKS + offset, duration=duration, velocity=92, channel=0))
            last_pitch = pitch
    return notes


def _generate_melody_from_progression(progression: ParsedProgression, text_features: TextFeatures | None, randomizer: random.Random) -> list[NoteEvent]:
    scale = scale_for(progression.key, progression.mode)
    genre = text_features.genre if text_features else 'pop'
    energy = text_features.energy if text_features else 'medium'
    rhythm_pool = _rhythm_pool_for(genre, energy)
    contour_bias = randomizer.choice([-1, 1])
    notes: list[NoteEvent] = []
    last_pitch = midi_for_pitch_class(progression.chord_bars[0].root_pc, 5)
    phrase_length = 4 if progression.bars >= 4 else progression.bars

    for bar_index, chord_bar in enumerate(progression.chord_bars):
        bar_start = bar_index * BAR_TICKS
        rhythm = randomizer.choice(rhythm_pool)
        melody_targets = list(chord_bar.pitch_classes)
        if chord_bar.root_pc not in melody_targets:
            melody_targets.insert(0, chord_bar.root_pc)
        for step_index, offset in enumerate(rhythm):
            strong = step_index == 0 or offset % (BAR_TICKS // 2) == 0
            cadence = ((bar_index + 1) % phrase_length == 0 and step_index == len(rhythm) - 1) or (bar_index == progression.bars - 1 and step_index == len(rhythm) - 1)
            pitch_class = _pick_melody_pitch_class(scale, melody_targets, chord_bar, strong, cadence, last_pitch, contour_bias, randomizer)
            pitch = _nearest_melodic_pitch(pitch_class, last_pitch, 60, 84)
            next_offset = rhythm[step_index + 1] if step_index + 1 < len(rhythm) else BAR_TICKS
            duration = max(BAR_TICKS // 8, min(BAR_TICKS // 2, next_offset - offset))
            velocity = 96 if strong else 84
            notes.append(NoteEvent(pitch=pitch, start=bar_start + offset, duration=duration, velocity=velocity, channel=0))
            last_pitch = pitch
        contour_bias *= -1 if randomizer.random() < 0.35 else 1
    return notes


def _rhythm_pool_for(genre: str, energy: str) -> list[list[int]]:
    if genre == 'house':
        return [
            [0, BAR_TICKS // 4, BAR_TICKS // 2, BAR_TICKS * 3 // 4],
            [0, BAR_TICKS // 4, BAR_TICKS // 2, BAR_TICKS * 5 // 8, BAR_TICKS * 7 // 8],
        ]
    if genre == 'trap':
        return [
            [0, BAR_TICKS * 3 // 8, BAR_TICKS // 2, BAR_TICKS * 3 // 4],
            [0, BAR_TICKS // 4, BAR_TICKS * 5 // 8, BAR_TICKS * 7 // 8],
            [0, BAR_TICKS // 6, BAR_TICKS // 2, BAR_TICKS * 5 // 6],
        ]
    if genre == 'rnb':
        return [
            [0, BAR_TICKS // 3, BAR_TICKS * 2 // 3],
            [0, BAR_TICKS // 4, BAR_TICKS * 5 // 8, BAR_TICKS * 7 // 8],
            [0, BAR_TICKS // 4, BAR_TICKS // 2, BAR_TICKS * 3 // 4],
        ]
    if energy == 'low':
        return [
            [0, BAR_TICKS // 2],
            [0, BAR_TICKS // 3, BAR_TICKS * 2 // 3],
        ]
    return [
        [0, BAR_TICKS // 4, BAR_TICKS // 2, BAR_TICKS * 3 // 4],
        [0, BAR_TICKS // 3, BAR_TICKS * 2 // 3, BAR_TICKS * 5 // 6],
        [0, BAR_TICKS // 2, BAR_TICKS * 3 // 4],
    ]


def _pick_melody_pitch_class(scale: list[int], melody_targets: list[int], chord_bar: ChordBar, strong: bool, cadence: bool, last_pitch: int, contour_bias: int, randomizer: random.Random) -> int:
    if cadence:
        return chord_bar.root_pc
    if strong:
        return randomizer.choice(melody_targets[: min(3, len(melody_targets))])
    last_pc = last_pitch % 12
    if randomizer.random() < 0.65:
        return randomizer.choice(melody_targets)
    scale_index = scale.index(last_pc) if last_pc in scale else 0
    shift = randomizer.choice([1, 1, 2]) * contour_bias
    return scale[(scale_index + shift) % len(scale)]


def _nearest_melodic_pitch(pitch_class: int, reference: int, low: int, high: int) -> int:
    candidates = []
    for octave in range(3, 8):
        pitch = midi_for_pitch_class(pitch_class, octave)
        if low <= pitch <= high:
            candidates.append(pitch)
    if not candidates:
        return clamp_pitch(midi_for_pitch_class(pitch_class, 5), low, high)
    return min(candidates, key=lambda pitch: (abs(pitch - reference), pitch))


def _normalize_melody(notes: list[NoteEvent], bars: int) -> list[NoteEvent]:
    limit = bars * BAR_TICKS
    normalized: list[NoteEvent] = []
    for note in notes:
        if note.start >= limit:
            continue
        duration = min(note.duration, limit - note.start)
        if duration <= 0:
            continue
        normalized.append(NoteEvent(pitch=note.pitch, start=note.start, duration=duration, velocity=note.velocity, channel=0))
    return sorted(normalized, key=lambda note: (note.start, note.pitch))


def _generate_bassline(chords: list[NoteEvent], text_features: TextFeatures | None, randomizer: random.Random) -> tuple[list[NoteEvent], str]:
    genre = text_features.genre if text_features else "pop"
    pattern = randomizer.choice(BASS_VARIANTS.get(genre, ["hold"]))
    bass: list[NoteEvent] = []
    max_bar = max((note.start for note in chords), default=0) // BAR_TICKS + 1
    for bar in range(max_bar):
        bar_chord = _notes_for_bar(chords, bar)
        if not bar_chord:
            continue
        root_pitch = clamp_pitch(min(bar_chord, key=lambda note: note.pitch).pitch - 24, 28, 52)
        if pattern == "staccato":
            for step in range(4):
                bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS + step * (BAR_TICKS // 4), duration=BAR_TICKS // 8, velocity=88, channel=2))
        elif pattern == "stair":
            for offset, shift in enumerate([0, 0, 2, -2]):
                bass.append(NoteEvent(pitch=clamp_pitch(root_pitch + shift, 28, 52), start=bar * BAR_TICKS + offset * (BAR_TICKS // 4), duration=BAR_TICKS // 8, velocity=84, channel=2))
        elif pattern == "pulse":
            for step in [0, 2]:
                bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS + step * (BAR_TICKS // 4), duration=BAR_TICKS // 4, velocity=84, channel=2))
        elif pattern == "octave":
            bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS, duration=BAR_TICKS // 2, velocity=84, channel=2))
            bass.append(NoteEvent(pitch=clamp_pitch(root_pitch + 12, 28, 52), start=bar * BAR_TICKS + BAR_TICKS // 2, duration=BAR_TICKS // 2, velocity=80, channel=2))
        elif pattern == "syncopated":
            for step in [0, 1.5, 3]:
                bass.append(NoteEvent(pitch=root_pitch, start=int(bar * BAR_TICKS + step * (BAR_TICKS // 4)), duration=BAR_TICKS // 6, velocity=84, channel=2))
        else:
            bass.append(NoteEvent(pitch=root_pitch, start=bar * BAR_TICKS, duration=BAR_TICKS, velocity=84, channel=2))
    return bass, pattern.title()


def _generate_drum_pattern(bars: int, text_features: TextFeatures | None, randomizer: random.Random) -> tuple[list[NoteEvent], str]:
    genre = text_features.genre if text_features else "pop"
    pattern_name, kick_steps, extra_hats = randomizer.choice(DRUM_VARIANTS.get(genre, DRUM_VARIANTS["pop"]))
    notes: list[NoteEvent] = []
    for bar in range(bars):
        bar_start = bar * BAR_TICKS
        quarter = BAR_TICKS // 4
        for step in range(4):
            start = bar_start + step * quarter
            notes.append(NoteEvent(pitch=42, start=start, duration=quarter // 2, velocity=64, channel=9))
        for step in [1, 3]:
            notes.append(NoteEvent(pitch=38, start=bar_start + step * quarter, duration=quarter // 2, velocity=96, channel=9))
        for step in kick_steps:
            start = int(bar_start + step * quarter)
            notes.append(NoteEvent(pitch=36, start=start, duration=quarter // 2, velocity=110, channel=9))
        for step in extra_hats:
            start = int(bar_start + step * quarter)
            notes.append(NoteEvent(pitch=44, start=start, duration=max(quarter // 4, 1), velocity=54, channel=9))
    return sorted(notes, key=lambda note: (note.start, note.pitch)), pattern_name
