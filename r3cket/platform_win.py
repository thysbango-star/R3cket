"""Thin wrapper around the Windows bits R3cket touches.

Everything that reads or writes the system goes through a ``Backend`` so the
tweak logic can be tested on any OS with ``FakeBackend``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

HKCU = "HKCU"
HKLM = "HKLM"

REG_DWORD = "REG_DWORD"
REG_SZ = "REG_SZ"
REG_BINARY = "REG_BINARY"

# Hide console windows when we shell out from the GUI.
_CREATE_NO_WINDOW = 0x08000000


class Backend:
    """Interface every backend implements."""

    def reg_get(self, hive: str, key: str, name: str) -> Optional[tuple[object, str]]:
        """Return (value, type) or None if the value does not exist."""
        raise NotImplementedError

    def reg_set(self, hive: str, key: str, name: str, value: object, kind: str) -> None:
        raise NotImplementedError

    def reg_delete(self, hive: str, key: str, name: str) -> None:
        raise NotImplementedError

    def run(self, args: list[str]) -> tuple[int, str]:
        """Run a command, return (exit code, combined output)."""
        raise NotImplementedError


class WindowsBackend(Backend):
    def __init__(self) -> None:
        import winreg  # only importable on Windows

        self._wr = winreg
        self._hives = {HKCU: winreg.HKEY_CURRENT_USER, HKLM: winreg.HKEY_LOCAL_MACHINE}
        self._kinds = {
            REG_DWORD: winreg.REG_DWORD,
            REG_SZ: winreg.REG_SZ,
            REG_BINARY: winreg.REG_BINARY,
        }
        self._kind_names = {v: k for k, v in self._kinds.items()}

    def reg_get(self, hive, key, name):
        try:
            with self._wr.OpenKey(self._hives[hive], key) as k:
                value, kind = self._wr.QueryValueEx(k, name)
                return value, self._kind_names.get(kind, REG_SZ)
        except FileNotFoundError:
            return None

    def reg_set(self, hive, key, name, value, kind):
        with self._wr.CreateKeyEx(self._hives[hive], key, 0, self._wr.KEY_SET_VALUE) as k:
            self._wr.SetValueEx(k, name, 0, self._kinds[kind], value)

    def reg_delete(self, hive, key, name):
        try:
            with self._wr.OpenKey(self._hives[hive], key, 0, self._wr.KEY_SET_VALUE) as k:
                self._wr.DeleteValue(k, name)
        except FileNotFoundError:
            pass

    def run(self, args):
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                creationflags=_CREATE_NO_WINDOW,
                timeout=60,
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)


@dataclass
class FakeBackend(Backend):
    """In-memory backend for tests and for previewing on non-Windows machines."""

    registry: dict = field(default_factory=dict)
    commands: list = field(default_factory=list)
    responses: dict = field(default_factory=dict)

    def reg_get(self, hive, key, name):
        return self.registry.get((hive, key, name))

    def reg_set(self, hive, key, name, value, kind):
        self.registry[(hive, key, name)] = (value, kind)

    def reg_delete(self, hive, key, name):
        self.registry.pop((hive, key, name), None)

    def run(self, args):
        self.commands.append(list(args))
        for prefix, response in self.responses.items():
            if " ".join(args).startswith(prefix):
                return response
        return 0, ""


def is_windows() -> bool:
    return sys.platform == "win32"


def default_backend() -> Backend:
    return WindowsBackend() if is_windows() else FakeBackend()


def data_dir() -> str:
    """Where R3cket keeps its backup and settings files."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "R3cket")
    os.makedirs(path, exist_ok=True)
    return path
