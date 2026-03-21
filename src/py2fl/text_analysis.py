from __future__ import annotations

from .models import TextFeatures


GENRE_KEYWORDS = {
    "trap": {"trap", "808", "drill"},
    "rnb": {"rnb", "soul", "neo-soul"},
    "house": {"house", "club", "dance"},
    "ambient": {"ambient", "cinematic", "atmospheric"},
    "pop": {"pop", "anthem", "radio"},
}

MOOD_KEYWORDS = {
    "dark": {"dark", "moody", "brooding", "night"},
    "bright": {"bright", "uplifting", "sunny", "happy"},
    "dreamy": {"dreamy", "airy", "ethereal", "floaty"},
    "aggressive": {"aggressive", "hard", "punchy", "intense"},
}

ENERGY_KEYWORDS = {
    "high": {"energetic", "driving", "fast", "club", "anthem"},
    "low": {"slow", "soft", "gentle", "ambient", "chill"},
}


def analyze_text(text: str | None, genre_hint: str | None = None) -> TextFeatures | None:
    if not text and not genre_hint:
        return None

    raw_text = (text or "").strip()
    haystack = f"{raw_text} {genre_hint or ''}".lower()
    style_tags: list[str] = []

    genre = "pop"
    for candidate, words in GENRE_KEYWORDS.items():
        if any(word in haystack for word in words):
            genre = candidate
            style_tags.append(candidate)
            break

    mood = "neutral"
    for candidate, words in MOOD_KEYWORDS.items():
        if any(word in haystack for word in words):
            mood = candidate
            style_tags.append(candidate)
            break

    energy = "medium"
    for candidate, words in ENERGY_KEYWORDS.items():
        if any(word in haystack for word in words):
            energy = candidate
            style_tags.append(candidate)
            break

    if mood == "neutral" and genre in {"trap", "ambient", "rnb"}:
        mood = "dark" if genre == "trap" else "dreamy"
        style_tags.append(mood)

    return TextFeatures(
        raw_text=raw_text,
        style_tags=sorted(set(style_tags)),
        energy=energy,
        mood=mood,
        genre=genre_hint or genre,
    )
