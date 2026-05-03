from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .text_analysis import analyze_text


ENV_API_KEY = "GEMINI_API_KEY"
ENV_API_KEY_FALLBACK = "GOOGLE_API_KEY"
ENV_MODEL = "PY2FL_GEMINI_MODEL"
DEFAULT_MODEL = "gemini-2.0-flash"
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

CHORD_DENSITY_OPTIONS = {"1", "2", "3", "auto"}
MELODY_DENSITY_OPTIONS = {"sparse", "normal", "dense", "xdense", "auto"}
CHORD_RHYTHM_OPTIONS = {"hold", "stab", "strum", "auto"}
LEVEL_OPTIONS = {"off", "low", "med", "high", "auto"}
LEVEL_CONTROLS = (
    "humanize",
    "swing",
    "drum_dynamics",
    "harmony_spice",
    "section_dynamics",
    "modulate",
)


@dataclass(slots=True)
class Suggestion:
    source: str  # "llm" or "rule"
    fields: dict[str, Any] = field(default_factory=dict)
    rationale: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fields": dict(self.fields),
            "rationale": self.rationale,
            "error": self.error,
        }


class LLMUnavailable(RuntimeError):
    pass


def resolve_api_key(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    return os.environ.get(ENV_API_KEY) or os.environ.get(ENV_API_KEY_FALLBACK)


def is_available(api_key: str | None = None) -> bool:
    return bool(resolve_api_key(api_key))


def suggest_from_text(
    text: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 12.0,
) -> Suggestion:
    """Suggest BPM/key/genre/9 controls from a free-form text prompt.

    Calls Gemini Flash if a key is configured; otherwise returns a rule-based
    suggestion derived from text_analysis. Always returns a Suggestion — never
    raises for missing keys or network errors.
    """
    text = (text or "").strip()
    if not text:
        return Suggestion(source="rule", fields={}, rationale="empty prompt")

    key = resolve_api_key(api_key)
    if not key:
        return _rule_based_suggestion(text)

    model_name = model or os.environ.get(ENV_MODEL) or DEFAULT_MODEL
    try:
        raw = _call_gemini(text, api_key=key, model=model_name, timeout=timeout)
    except LLMUnavailable as exc:
        fallback = _rule_based_suggestion(text)
        fallback.error = str(exc)
        return fallback

    fields = _coerce_fields(raw.get("fields") or raw)
    rationale = raw.get("rationale") if isinstance(raw, dict) else None
    if not fields:
        fallback = _rule_based_suggestion(text)
        fallback.error = "LLM returned no usable fields"
        return fallback
    return Suggestion(source="llm", fields=fields, rationale=rationale)


def _rule_based_suggestion(text: str) -> Suggestion:
    features = analyze_text(text)
    if features is None:
        return Suggestion(source="rule", fields={}, rationale="no features detected")

    fields: dict[str, Any] = {
        "genre": features.genre,
        "humanize": "auto",
        "swing": "auto",
        "drum_dynamics": "auto",
        "harmony_spice": "auto",
        "section_dynamics": "auto",
        "modulate": "auto",
        "chord_density": "auto",
        "melody_density": "auto",
        "chord_rhythm_style": "auto",
    }
    if features.energy == "high":
        fields["drum_dynamics"] = "high"
        fields["humanize"] = "med"
    elif features.energy == "low":
        fields["drum_dynamics"] = "low"
        fields["humanize"] = "low"
    if features.mood == "dreamy":
        fields["chord_rhythm_style"] = "hold"
        fields["harmony_spice"] = "med"
    elif features.mood == "aggressive":
        fields["chord_rhythm_style"] = "stab"
        fields["humanize"] = "high"
    if features.genre == "trap":
        fields["swing"] = "low"
    elif features.genre == "house":
        fields["swing"] = "med"

    rationale = (
        f"rule-based — genre={features.genre}, mood={features.mood}, energy={features.energy}"
    )
    return Suggestion(source="rule", fields=fields, rationale=rationale)


def _call_gemini(text: str, *, api_key: str, model: str, timeout: float) -> dict[str, Any]:
    prompt = _build_prompt(text)
    url = API_URL_TEMPLATE.format(model=model, key=api_key)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.4,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise LLMUnavailable(f"Gemini HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMUnavailable(f"Gemini network error: {exc.reason}") from exc
    except (json.JSONDecodeError, TimeoutError) as exc:
        raise LLMUnavailable(f"Gemini parse/timeout: {exc}") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        block = data.get("promptFeedback", {}).get("blockReason")
        raise LLMUnavailable(f"Gemini returned no candidates ({block or 'unknown'})")
    parts = candidates[0].get("content", {}).get("parts") or []
    text_part = next((p.get("text") for p in parts if p.get("text")), None)
    if not text_part:
        raise LLMUnavailable("Gemini returned empty content")
    try:
        parsed = json.loads(text_part)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"Gemini JSON decode failed: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMUnavailable("Gemini returned non-object JSON")
    return parsed


def _build_prompt(text: str) -> str:
    return (
        "You are a music production assistant. Read the user's free-form description of a track "
        "and output JSON with concrete generation hints. Return ONLY a JSON object with this shape:\n\n"
        "{\n"
        '  "fields": {\n'
        '    "tempo": <int 30-300 or null>,\n'
        '    "key": "<like C, F#, A minor, or null>",\n'
        '    "genre": "<short word like trap, rnb, house, ambient, pop, drill, ... or null>",\n'
        '    "bars": <int 4-32 or null>,\n'
        '    "chord_density": "1" | "2" | "3" | "auto",\n'
        '    "melody_density": "sparse" | "normal" | "dense" | "xdense" | "auto",\n'
        '    "chord_rhythm_style": "hold" | "stab" | "strum" | "auto",\n'
        '    "humanize": "off" | "low" | "med" | "high" | "auto",\n'
        '    "swing": "off" | "low" | "med" | "high" | "auto",\n'
        '    "drum_dynamics": "off" | "low" | "med" | "high" | "auto",\n'
        '    "harmony_spice": "off" | "low" | "med" | "high" | "auto",\n'
        '    "section_dynamics": "off" | "low" | "med" | "high" | "auto",\n'
        '    "modulate": "off" | "low" | "med" | "high" | "auto"\n'
        "  },\n"
        '  "rationale": "<one short sentence>"\n'
        "}\n\n"
        "Pick values that match the vibe described. Use null only if truly ambiguous. "
        "Prefer concrete numbers for tempo and bars when the user implies them. "
        "Default bars to 8 for normal songs, 16 for build-up tracks. "
        "Swing should usually be off for trap/drill, low/med for hip-hop/rnb, med/high for shuffle/jazz. "
        "Section dynamics and modulate are most useful at bars >= 16.\n\n"
        f"User description: {text}"
    )


def _coerce_fields(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}

    tempo = _coerce_int(raw.get("tempo"), 30, 300)
    if tempo is not None:
        out["tempo"] = tempo
    bars = _coerce_int(raw.get("bars"), 1, 128)
    if bars is not None:
        out["bars"] = bars
    key_value = raw.get("key")
    if isinstance(key_value, str) and key_value.strip():
        out["key"] = key_value.strip()[:32]
    genre_value = raw.get("genre")
    if isinstance(genre_value, str) and genre_value.strip():
        out["genre"] = genre_value.strip()[:32]

    chord_density = _coerce_choice(raw.get("chord_density"), CHORD_DENSITY_OPTIONS)
    if chord_density is not None:
        out["chord_density"] = chord_density
    melody_density = _coerce_choice(raw.get("melody_density"), MELODY_DENSITY_OPTIONS)
    if melody_density is not None:
        out["melody_density"] = melody_density
    chord_rhythm = _coerce_choice(raw.get("chord_rhythm_style"), CHORD_RHYTHM_OPTIONS)
    if chord_rhythm is not None:
        out["chord_rhythm_style"] = chord_rhythm

    for control in LEVEL_CONTROLS:
        value = _coerce_choice(raw.get(control), LEVEL_OPTIONS)
        if value is not None:
            out[control] = value

    return out


def _coerce_int(value: Any, lo: int, hi: int) -> int | None:
    if value is None:
        return None
    try:
        as_int = int(value)
    except (TypeError, ValueError):
        return None
    if as_int < lo or as_int > hi:
        return None
    return as_int


def _coerce_choice(value: Any, options: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    if cleaned in options:
        return cleaned
    return None
