"""Persistent state: original settings (for undo), saved games and preferences.

Saved as JSON in %APPDATA%\\R3cket\\state.json. Writes go to a temp file first so
a crash never leaves a half-written backup behind.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .platform_win import data_dir

_DEFAULTS: dict[str, Any] = {
    "tweaks": {},  # tweak id -> snapshot of the original settings
    "gpu_prefs": {},  # exe path -> original GPU preference value (or None)
    "games": [],  # [{"name": ..., "exe": ..., "args": ...}]
    "session": None,  # active boost session, so a crash can be undone
    "settings": {
        "restore_after_game": True,
        "relaunch_closed_apps": True,
        "game_priority_high": True,
        "enabled_tweaks": None,  # None = each tweak's default
        "apps_to_close": None,  # None = built-in suggestions
    },
}


class State:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.path.join(data_dir(), "state.json")
        self._lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict:
        data = json.loads(json.dumps(_DEFAULTS))  # deep copy
        try:
            with open(self.path, encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return data
        for key, value in saved.items():
            if key == "settings" and isinstance(value, dict):
                data["settings"].update(value)
            else:
                data[key] = value
        return data

    def save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2)
            os.replace(tmp, self.path)

    # Convenience accessors -------------------------------------------------

    @property
    def settings(self) -> dict:
        return self.data["settings"]

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self.data["settings"][key] = value
            self.save()
