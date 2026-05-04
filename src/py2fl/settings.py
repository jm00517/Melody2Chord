from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CONFIG_DIRNAME = ".py2fl"
CONFIG_FILENAME = "config.json"
KEY_GEMINI_API_KEY = "gemini_api_key"
KEY_SOUNDFONT_PATH = "soundfont_path"
KEY_FLUIDSYNTH_PATH = "fluidsynth_path"


def config_path() -> Path:
    return Path.home() / CONFIG_DIRNAME / CONFIG_FILENAME


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(updates: dict[str, Any]) -> None:
    """Merge updates into the persisted config and write atomically."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_config()
    current.update(updates)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(current, indent=2, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def clear_config_key(key: str) -> None:
    path = config_path()
    if not path.is_file():
        return
    current = load_config()
    if key in current:
        del current[key]
        save_config_overwrite(current)


def save_config_overwrite(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def apply_to_environment() -> None:
    """Load the persisted config and copy known secrets/paths into os.environ."""
    config = load_config()
    api_key = config.get(KEY_GEMINI_API_KEY)
    if isinstance(api_key, str) and api_key.strip():
        os.environ.setdefault("GEMINI_API_KEY", api_key.strip())
    sf2 = config.get(KEY_SOUNDFONT_PATH)
    if isinstance(sf2, str) and sf2.strip():
        os.environ.setdefault("PY2FL_SOUNDFONT", sf2.strip())
    fluid = config.get(KEY_FLUIDSYNTH_PATH)
    if isinstance(fluid, str) and fluid.strip():
        os.environ.setdefault("PY2FL_FLUIDSYNTH", fluid.strip())


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    if len(cleaned) <= 4:
        return "•" * len(cleaned)
    return f"{'•' * (len(cleaned) - 4)}{cleaned[-4:]}"
