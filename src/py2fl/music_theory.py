from __future__ import annotations

PITCH_CLASS_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NAME_TO_PC = {name: index for index, name in enumerate(PITCH_CLASS_NAMES)}
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]


def normalize_key_name(name: str) -> str:
    cleaned = name.strip().upper()
    for suffix in (" MINOR", " MAJOR", "MINOR", "MAJOR", "M"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    cleaned = cleaned.strip()
    if cleaned in NAME_TO_PC:
        return cleaned
    cleaned = cleaned.replace("DB", "C#").replace("EB", "D#").replace("GB", "F#").replace("AB", "G#").replace("BB", "A#")
    if cleaned in NAME_TO_PC:
        return cleaned
    raise ValueError(f"Unsupported key name: {name}")


def scale_for(key: str, mode: str) -> list[int]:
    root = NAME_TO_PC[normalize_key_name(key)]
    intervals = MINOR_SCALE if mode == "minor" else MAJOR_SCALE
    return [(root + interval) % 12 for interval in intervals]


def degree_pitch_class(key: str, mode: str, degree: int) -> int:
    scale = scale_for(key, mode)
    return scale[(degree - 1) % 7]


def midi_for_pitch_class(pitch_class: int, octave: int) -> int:
    return (octave + 1) * 12 + pitch_class


def clamp_pitch(value: int, low: int = 0, high: int = 127) -> int:
    return max(low, min(high, value))


def key_label(key: str, mode: str) -> str:
    return f"{normalize_key_name(key)} {mode}"
