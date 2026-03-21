from __future__ import annotations

from dataclasses import dataclass
import re

from .music_theory import MAJOR_SCALE, MINOR_SCALE, NAME_TO_PC, PITCH_CLASS_NAMES, normalize_key_name, scale_for
from .text_analysis import analyze_text


@dataclass(frozen=True, slots=True)
class ChordBar:
    source_token: str
    display_label: str
    degree: int | None
    root_pc: int
    pitch_classes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ParsedProgression:
    source_text: str
    notation: str
    key: str
    mode: str
    bars: int
    chord_bars: list[ChordBar]


_CHORD_RE = re.compile(r'^(?P<root>[A-Ga-g])(?P<accidental>[#b]?)(?P<body>.*)$')


def parse_progression(text: str, *, key_hint: str | None = None, bars: int | None = None, genre_hint: str | None = None, style_text: str | None = None) -> ParsedProgression:
    source_text = (text or '').strip()
    if not source_text:
        raise ValueError('Chord progression is required')
    tokens = _tokenize_progression(source_text)
    if not tokens:
        raise ValueError('Chord progression is empty')

    if all(token.isdigit() and 1 <= int(token) <= 7 for token in tokens):
        notation = 'degree'
        key, mode = _resolve_degree_key_mode(key_hint, genre_hint, style_text)
        chord_bars = [_degree_to_bar(token, key, mode) for token in tokens]
    else:
        notation = 'named'
        chord_bars = [_named_to_bar(token) for token in tokens]
        inferred_key, inferred_mode = infer_progression_key(chord_bars)
        key, mode = _resolve_named_key_mode(key_hint, inferred_key, inferred_mode)
        chord_bars = [_annotate_degree(bar, key, mode) for bar in chord_bars]

    target_bars = bars or len(chord_bars)
    if target_bars < 1:
        raise ValueError('bars must be at least 1')
    expanded = [chord_bars[index % len(chord_bars)] for index in range(target_bars)]
    return ParsedProgression(
        source_text=source_text,
        notation=notation,
        key=key,
        mode=mode,
        bars=target_bars,
        chord_bars=expanded,
    )


def infer_progression_key(chord_bars: list[ChordBar]) -> tuple[str, str]:
    pitch_counts = {index: 0 for index in range(12)}
    for bar in chord_bars:
        for pitch_class in bar.pitch_classes:
            pitch_counts[pitch_class] += 1
    best = ('C', 'major')
    best_score = -10**9
    for root_name, root_pc in NAME_TO_PC.items():
        major_score = _score_scale(root_pc, MAJOR_SCALE, pitch_counts)
        if major_score > best_score:
            best = (root_name, 'major')
            best_score = major_score
        minor_score = _score_scale(root_pc, MINOR_SCALE, pitch_counts)
        if minor_score > best_score:
            best = (root_name, 'minor')
            best_score = minor_score
    return best


def progression_display(chord_bars: list[ChordBar]) -> str:
    return ' -> '.join(bar.display_label for bar in chord_bars)


def _tokenize_progression(text: str) -> list[str]:
    tokens = [token.strip() for token in re.split(r'\s*(?:-|,|>|\|)+\s*|\s+', text) if token.strip()]
    return tokens


def _resolve_degree_key_mode(key_hint: str | None, genre_hint: str | None, style_text: str | None) -> tuple[str, str]:
    if key_hint:
        return _parse_key_hint(key_hint)
    text_features = analyze_text(style_text, genre_hint)
    if text_features and text_features.mood in {'dark', 'dreamy'}:
        return ('A', 'minor')
    return ('C', 'major')


def _resolve_named_key_mode(key_hint: str | None, inferred_key: str, inferred_mode: str) -> tuple[str, str]:
    if key_hint:
        return _parse_key_hint(key_hint)
    return inferred_key, inferred_mode


def _parse_key_hint(key_hint: str) -> tuple[str, str]:
    cleaned = key_hint.strip()
    lowered = cleaned.lower()
    if lowered.endswith(' minor'):
        return normalize_key_name(cleaned[:-6].strip()), 'minor'
    if lowered.endswith(' major'):
        return normalize_key_name(cleaned[:-6].strip()), 'major'
    return normalize_key_name(cleaned), 'major'


def _degree_to_bar(token: str, key: str, mode: str) -> ChordBar:
    degree = int(token)
    scale = scale_for(key, mode)
    index = (degree - 1) % 7
    root_pc = scale[index]
    third_pc = scale[(index + 2) % 7]
    fifth_pc = scale[(index + 4) % 7]
    display_label = _triad_name(root_pc, third_pc, fifth_pc)
    return ChordBar(
        source_token=token,
        display_label=display_label,
        degree=degree,
        root_pc=root_pc,
        pitch_classes=(root_pc, third_pc, fifth_pc),
    )


def _named_to_bar(token: str) -> ChordBar:
    match = _CHORD_RE.match(token)
    if match is None:
        raise ValueError(f'Unsupported chord token: {token}')
    root_name = (match.group('root') + (match.group('accidental') or '')).upper().replace('DB', 'C#').replace('EB', 'D#').replace('GB', 'F#').replace('AB', 'G#').replace('BB', 'A#')
    if root_name not in NAME_TO_PC:
        raise ValueError(f'Unsupported chord root: {token}')
    body = (match.group('body') or '').strip()
    normalized = body.lower().replace('maj', 'maj')
    root_pc = NAME_TO_PC[root_name]
    pitch_classes = _named_pitch_classes(root_pc, normalized)
    display_label = _normalize_display_label(root_name, body)
    return ChordBar(
        source_token=token,
        display_label=display_label,
        degree=None,
        root_pc=root_pc,
        pitch_classes=pitch_classes,
    )


def _normalize_display_label(root_name: str, body: str) -> str:
    if not body:
        return root_name
    return root_name + body.strip()


def _named_pitch_classes(root_pc: int, body: str) -> tuple[int, ...]:
    lowered = body.lower()
    if lowered in {'m', 'min'}:
        return (root_pc, (root_pc + 3) % 12, (root_pc + 7) % 12)
    if lowered in {'m7', 'min7'}:
        return (root_pc, (root_pc + 3) % 12, (root_pc + 7) % 12, (root_pc + 10) % 12)
    if lowered in {'maj7'}:
        return (root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12, (root_pc + 11) % 12)
    if lowered in {'7'}:
        return (root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12, (root_pc + 10) % 12)
    if lowered in {'add9'}:
        return (root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12, (root_pc + 2) % 12)
    if lowered in {'sus2'}:
        return (root_pc, (root_pc + 2) % 12, (root_pc + 7) % 12)
    if lowered in {'sus4'}:
        return (root_pc, (root_pc + 5) % 12, (root_pc + 7) % 12)
    if lowered in {'dim'}:
        return (root_pc, (root_pc + 3) % 12, (root_pc + 6) % 12)
    if lowered in {'', 'maj'}:
        return (root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12)
    raise ValueError(f'Unsupported chord quality: {body}')


def _annotate_degree(bar: ChordBar, key: str, mode: str) -> ChordBar:
    scale = scale_for(key, mode)
    try:
        degree = scale.index(bar.root_pc) + 1
    except ValueError:
        degree = None
    return ChordBar(
        source_token=bar.source_token,
        display_label=bar.display_label,
        degree=degree,
        root_pc=bar.root_pc,
        pitch_classes=bar.pitch_classes,
    )


def _triad_name(root_pc: int, third_pc: int, fifth_pc: int) -> str:
    root = PITCH_CLASS_NAMES[root_pc]
    third_interval = (third_pc - root_pc) % 12
    fifth_interval = (fifth_pc - root_pc) % 12
    if third_interval == 3 and fifth_interval == 6:
        return f'{root}dim'
    if third_interval == 3:
        return f'{root}m'
    return root


def _score_scale(root: int, intervals: list[int], counts: dict[int, int]) -> int:
    scale = {(root + interval) % 12 for interval in intervals}
    score = 0
    for pitch_class, count in counts.items():
        score += count * 3 if pitch_class in scale else -count * 2
    return score
