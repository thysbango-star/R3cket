"""Background apps and game process priority."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - lets tests run without psutil
    psutil = None

# Apps that commonly eat CPU, disk or RAM while gaming.
# (friendly name, ticked by default, safe to force-close if it ignores a polite close)
SUGGESTIONS: dict[str, tuple[str, bool, bool]] = {
    "onedrive.exe": ("OneDrive (file sync)", True, True),
    "dropbox.exe": ("Dropbox (file sync)", True, True),
    "googledrivefs.exe": ("Google Drive (file sync)", True, True),
    "ms-teams.exe": ("Microsoft Teams", True, False),
    "teams.exe": ("Microsoft Teams (classic)", True, False),
    "skype.exe": ("Skype", True, False),
    "phoneexperiencehost.exe": ("Phone Link", True, True),
    "yourphone.exe": ("Phone Link", True, True),
    "creative cloud.exe": ("Adobe Creative Cloud", True, True),
    "ccxprocess.exe": ("Adobe Creative Cloud helper", True, True),
    "adobearm.exe": ("Adobe updater", True, True),
    "widgets.exe": ("Windows Widgets", True, True),
    "chrome.exe": ("Google Chrome", False, False),
    "msedge.exe": ("Microsoft Edge", False, False),
    "firefox.exe": ("Firefox", False, False),
    "opera.exe": ("Opera", False, False),
    "brave.exe": ("Brave", False, False),
    "spotify.exe": ("Spotify", False, False),
}

# Relaunch these quietly in the tray rather than popping open a window.
_RELAUNCH_ARGS = {"onedrive.exe": ["/background"]}


@dataclass
class RunningApp:
    name: str  # exe name, lower case
    label: str
    exe: str  # full path if known
    count: int
    memory_mb: float
    suggested: bool  # ticked by default

    @property
    def force_ok(self) -> bool:
        return SUGGESTIONS.get(self.name, ("", False, False))[2]


def available() -> bool:
    return psutil is not None


def running_background_apps() -> list[RunningApp]:
    """Running apps we know about, biggest memory users first."""
    if psutil is None:
        return []
    found: dict[str, RunningApp] = {}
    for proc in psutil.process_iter(["name", "exe", "memory_info"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name not in SUGGESTIONS:
                continue
            mem = proc.info["memory_info"].rss / (1024 * 1024) if proc.info["memory_info"] else 0
            label, suggested, _ = SUGGESTIONS[name]
            app = found.get(name)
            if app is None:
                found[name] = RunningApp(name, label, proc.info["exe"] or "", 1, mem, suggested)
            else:
                app.count += 1
                app.memory_mb += mem
                app.exe = app.exe or proc.info["exe"] or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(found.values(), key=lambda a: a.memory_mb, reverse=True)


def _alive(name: str) -> bool:
    if psutil is None:
        return False
    for proc in psutil.process_iter(["name"]):
        if (proc.info["name"] or "").lower() == name:
            return True
    return False


def close_apps(apps: list[RunningApp], wait: float = 4.0) -> list[dict]:
    """Ask each app to close. Returns the ones that closed, for relaunching later.

    Browsers and chat apps only get a polite close (like clicking X) so you
    never lose tabs or messages. Sync tools and updaters are force-closed if
    they ignore the polite request.
    """
    closed = []
    for app in apps:
        subprocess.run(
            ["taskkill", "/IM", app.name, "/T"],
            capture_output=True,
            creationflags=0x08000000,
        )
    deadline = time.time() + wait
    pending = list(apps)
    while pending and time.time() < deadline:
        time.sleep(0.5)
        pending = [a for a in pending if _alive(a.name)]
    for app in pending:
        if app.force_ok:
            subprocess.run(
                ["taskkill", "/IM", app.name, "/T", "/F"],
                capture_output=True,
                creationflags=0x08000000,
            )
    time.sleep(0.5)
    for app in apps:
        if not _alive(app.name):
            closed.append({"name": app.name, "exe": app.exe})
    return closed


def relaunch(apps: list[dict]) -> None:
    for app in apps:
        exe = app.get("exe")
        if not exe or not os.path.exists(exe):
            continue
        args = [exe] + _RELAUNCH_ARGS.get(app["name"], [])
        try:
            subprocess.Popen(args, close_fds=True, creationflags=0x00000008)  # DETACHED
        except OSError:
            pass


def find_processes(exe_name: str) -> list:
    if psutil is None:
        return []
    exe_name = exe_name.lower()
    out = []
    for proc in psutil.process_iter(["name"]):
        if (proc.info["name"] or "").lower() == exe_name:
            out.append(proc)
    return out


def set_high_priority(exe_name: str) -> int:
    """Raise the game to High priority (never Realtime - that can freeze Windows)."""
    if psutil is None:
        return 0
    count = 0
    for proc in find_processes(exe_name):
        try:
            proc.nice(psutil.HIGH_PRIORITY_CLASS)
            count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue
    return count
