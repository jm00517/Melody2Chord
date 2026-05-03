from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


INDEX_FILE = "index.json"
INDEX_VERSION = 1
CONTROL_KEYS = (
    "chord_density",
    "melody_density",
    "chord_rhythm_style",
    "humanize",
    "swing",
    "drum_dynamics",
    "harmony_spice",
    "section_dynamics",
    "modulate",
)


def save_candidate(candidate_dir: Path, name: str, library_dir: Path) -> dict[str, Any]:
    """Copy a generated candidate folder into the library and record an index entry."""
    candidate_dir = Path(candidate_dir)
    library_dir = Path(library_dir)
    if not candidate_dir.is_dir():
        raise FileNotFoundError(f"candidate folder not found: {candidate_dir}")

    meta_path = candidate_dir / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"meta.json missing in candidate folder: {candidate_dir}")
    with meta_path.open("r", encoding="utf-8") as fh:
        meta = json.load(fh)

    library_dir.mkdir(parents=True, exist_ok=True)

    display_name = (name or "").strip() or _fallback_name(meta)
    slug = _slugify(display_name) or _slugify(_fallback_name(meta)) or "entry"
    entry_id = _allocate_id(library_dir, slug)
    target_dir = library_dir / entry_id
    shutil.copytree(candidate_dir, target_dir)

    entry = {
        "id": entry_id,
        "name": display_name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "input_mode": meta.get("input_mode"),
        "ui_mode": meta.get("ui_mode"),
        "text": meta.get("text"),
        "genre": meta.get("genre"),
        "tempo": meta.get("tempo"),
        "key": meta.get("key"),
        "bars": meta.get("bars"),
        "style_tags": list(meta.get("style_tags") or []),
        "progression_label": meta.get("progression_label"),
        "progression_degrees": list(meta.get("progression_degrees") or []),
        "full_progression_text": meta.get("full_progression_text"),
        "candidate_seed": meta.get("candidate_seed"),
        "preview_file": meta.get("preview_file") or "full_arrangement.mid",
        "source_progression": meta.get("source_progression"),
        "source_melody": meta.get("source_melody"),
        "controls": {key: meta.get(f"requested_{key}", "auto") for key in CONTROL_KEYS},
    }

    index = _load_index(library_dir)
    index["entries"].append(entry)
    _write_index(library_dir, index)
    return entry


def list_entries(library_dir: Path) -> list[dict[str, Any]]:
    library_dir = Path(library_dir)
    if not library_dir.is_dir():
        return []
    index = _load_index(library_dir)
    entries = list(index.get("entries") or [])
    entries.sort(key=lambda e: e.get("saved_at") or "", reverse=True)
    return entries


def get_entry(entry_id: str, library_dir: Path) -> dict[str, Any] | None:
    for entry in list_entries(library_dir):
        if entry.get("id") == entry_id:
            return entry
    return None


def delete_entry(entry_id: str, library_dir: Path) -> bool:
    library_dir = Path(library_dir)
    if not library_dir.is_dir():
        return False
    index = _load_index(library_dir)
    entries = list(index.get("entries") or [])
    remaining = [e for e in entries if e.get("id") != entry_id]
    if len(remaining) == len(entries):
        return False
    target = library_dir / entry_id
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    index["entries"] = remaining
    _write_index(library_dir, index)
    return True


def entry_dir(entry_id: str, library_dir: Path) -> Path:
    return Path(library_dir) / entry_id


def _allocate_id(library_dir: Path, slug: str) -> str:
    for _ in range(8):
        candidate = f"{slug}__{secrets.token_hex(3)}"
        if not (library_dir / candidate).exists():
            return candidate
    return f"{slug}__{secrets.token_hex(6)}"


def _fallback_name(meta: dict[str, Any]) -> str:
    for key in ("text", "progression_label", "full_progression_text", "source_melody"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:40]
    return "arrangement"


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣]+", "_", (text or "").strip().lower())
    return cleaned.strip("_")


def _load_index(library_dir: Path) -> dict[str, Any]:
    path = library_dir / INDEX_FILE
    if not path.is_file():
        return {"version": INDEX_VERSION, "entries": []}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"version": INDEX_VERSION, "entries": []}
    if not isinstance(data, dict):
        return {"version": INDEX_VERSION, "entries": []}
    data.setdefault("version", INDEX_VERSION)
    entries = data.get("entries")
    if not isinstance(entries, list):
        data["entries"] = []
    return data


def _write_index(library_dir: Path, index: dict[str, Any]) -> None:
    library_dir.mkdir(parents=True, exist_ok=True)
    path = library_dir / INDEX_FILE
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(index, indent=2, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
