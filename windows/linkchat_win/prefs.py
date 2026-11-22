"""Lightweight UI preference persistence stored outside linkchat.db."""

from __future__ import annotations

import json
from pathlib import Path

from .i18n import DEFAULT_LANG, Lang, normalize_lang

PREFS_FILENAME = "ui_prefs.json"


def load_language(data_dir: str | Path) -> Lang:
    """Load persisted UI language from data_dir/ui_prefs.json, defaulting to Persian."""
    path = Path(data_dir) / PREFS_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return normalize_lang(raw.get("language"))
    except (OSError, ValueError, TypeError):
        pass
    return DEFAULT_LANG


def save_language(data_dir: str | Path, lang: Lang) -> None:
    """Persist selected UI language to data_dir/ui_prefs.json."""
    target_dir = Path(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / PREFS_FILENAME
    existing: dict[str, object] = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, ValueError, TypeError):
        pass
    existing["language"] = normalize_lang(lang)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
