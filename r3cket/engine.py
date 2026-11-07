"""Applies and undoes tweaks, GPU preferences and boost sessions."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Callable, Optional

from . import processes
from .platform_win import HKCU, REG_SZ, Backend
from .state import State
from .tweaks import Tweak, all_tweaks

GPU_PREF_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
GPU_HIGH_PERF = "GpuPreference=2;"

Log = Callable[[str], None]


class Optimizer:
    def __init__(self, backend: Backend, state: State, log: Optional[Log] = None) -> None:
        self.backend = backend
        self.state = state
        self.log = log or (lambda msg: None)
        self.tweaks = all_tweaks()

    # ---- tweaks ----------------------------------------------------------

    def enabled_tweak_ids(self) -> list[str]:
        chosen = self.state.settings.get("enabled_tweaks")
        if chosen is None:
            return [t.id for t in self.tweaks if t.default_on]
        return [t.id for t in self.tweaks if t.id in chosen]

    def status(self) -> dict[str, bool]:
        out = {}
        for t in self.tweaks:
            try:
                out[t.id] = t.is_applied(self.backend)
            except Exception:  # noqa: BLE001 - status must never crash the UI
                out[t.id] = False
        return out

    def _tweak(self, tweak_id: str) -> Tweak:
        return next(t for t in self.tweaks if t.id == tweak_id)

    def apply(self, tweak_ids: list[str]) -> list[str]:
        """Apply tweaks. Returns the ids this call actually changed."""
        changed = []
        saved = self.state.data["tweaks"]
        for tid in tweak_ids:
            tweak = self._tweak(tid)
            if tweak.is_applied(self.backend):
                self.log(f"Already on: {tweak.name}")
                continue
            try:
                snapshot = tweak.apply(self.backend)
            except Exception as exc:  # noqa: BLE001
                self.log(f"Skipped {tweak.name}: {exc}")
                continue
            # Keep the *first* original we saw, so repeated runs never lose it.
            saved.setdefault(tid, snapshot)
            self.state.save()
            changed.append(tid)
            self.log(f"Applied: {tweak.name}")
        return changed

    def revert(self, tweak_ids: list[str]) -> None:
        saved = self.state.data["tweaks"]
        for tid in tweak_ids:
            snapshot = saved.get(tid)
            if snapshot is None:
                continue
            tweak = self._tweak(tid)
            try:
                tweak.revert(self.backend, snapshot)
                self.log(f"Restored: {tweak.name}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"Could not restore {tweak.name}: {exc}")
                continue
            del saved[tid]
            self.state.save()

    # ---- per-game GPU preference ----------------------------------------

    def set_gpu_high_performance(self, exe: str) -> None:
        """Make Windows run this game on the dedicated GPU (Nvidia/AMD), not the Intel chip."""
        current = self.backend.reg_get(HKCU, GPU_PREF_KEY, exe)
        if current and current[0] == GPU_HIGH_PERF:
            return
        prefs = self.state.data["gpu_prefs"]
        if exe not in prefs:
            prefs[exe] = current[0] if current else None
        self.backend.reg_set(HKCU, GPU_PREF_KEY, exe, GPU_HIGH_PERF, REG_SZ)
        self.state.save()
        self.log(f"Set {os.path.basename(exe)} to use the high-performance GPU")

    def revert_gpu_preference(self, exe: str) -> None:
        prefs = self.state.data["gpu_prefs"]
        if exe not in prefs:
            return
        original = prefs.pop(exe)
        if original is None:
            self.backend.reg_delete(HKCU, GPU_PREF_KEY, exe)
        else:
            self.backend.reg_set(HKCU, GPU_PREF_KEY, exe, original, REG_SZ)
        self.state.save()

    # ---- undo everything -------------------------------------------------

    def restore_everything(self) -> None:
        self.revert(list(self.state.data["tweaks"].keys()))
        for exe in list(self.state.data["gpu_prefs"].keys()):
            self.revert_gpu_preference(exe)
        session = self.state.data.get("session")
        if session:
            processes.relaunch(session.get("closed_apps", []))
            self.state.data["session"] = None
            self.state.save()
        self.log("Everything is back to how it was before R3cket.")


class BoostSession:
    """Launch -> play -> land. Boosts the system, runs a game, cleans up after."""

    def __init__(self, optimizer: Optimizer) -> None:
        self.opt = optimizer
        self.state = optimizer.state
        self.log = optimizer.log
        self._stop = threading.Event()

    @property
    def active(self) -> bool:
        return self.state.data.get("session") is not None

    def start(self, apps_to_close: list[processes.RunningApp]) -> None:
        if self.active:
            self.log("Boost is already running.")
            return
        # Record the session before changing anything, so a crash is recoverable.
        self.state.data["session"] = {"tweaks": [], "closed_apps": [], "started": time.time()}
        self.state.save()
        changed = self.opt.apply(self.opt.enabled_tweak_ids())
        self.state.data["session"]["tweaks"] = changed
        self.state.save()
        if apps_to_close:
            names = ", ".join(a.label for a in apps_to_close)
            self.log(f"Closing: {names}")
            closed = processes.close_apps(apps_to_close)
            self.state.data["session"]["closed_apps"] = closed
            self.state.save()
            still = [a.label for a in apps_to_close if a.name not in {c['name'] for c in closed}]
            if still:
                self.log(f"Left running (did not close politely): {', '.join(still)}")
        self.log("Boost is on. Liftoff.")

    def end(self) -> None:
        session = self.state.data.get("session")
        if not session:
            return
        if self.state.settings.get("restore_after_game", True):
            self.opt.revert(session.get("tweaks", []))
        if self.state.settings.get("relaunch_closed_apps", True):
            processes.relaunch(session.get("closed_apps", []))
        self.state.data["session"] = None
        self.state.save()
        self.log("Boost ended. Your laptop is back to normal.")

    # ---- playing a game --------------------------------------------------

    def play(self, game: dict, apps_to_close: list[processes.RunningApp],
             on_finished: Optional[Callable[[], None]] = None) -> None:
        """Boost, launch the game, watch it, and land when it closes. Runs in a thread."""

        def worker() -> None:
            try:
                self.start(apps_to_close)
                exe = game["exe"]
                self.opt.set_gpu_high_performance(exe)
                args = [exe] + (game.get("args") or "").split()
                self.log(f"Launching {game['name']}...")
                subprocess.Popen(args, cwd=os.path.dirname(exe) or None)
                self._watch(os.path.basename(exe))
            except Exception as exc:  # noqa: BLE001
                self.log(f"Something went wrong: {exc}")
            finally:
                self.end()
                if on_finished:
                    on_finished()

        self._stop.clear()
        threading.Thread(target=worker, daemon=True).start()

    def stop_watching(self) -> None:
        self._stop.set()

    def _watch(self, exe_name: str) -> None:
        if not processes.available():
            self.log("Process watching needs psutil; press 'Land' when you finish playing.")
            self._stop.wait()
            return
        # Launchers (Steam, Epic) may restart the game, so wait for it to appear.
        deadline = time.time() + 90
        while not processes.find_processes(exe_name):
            if self._stop.is_set() or time.time() > deadline:
                self.log("Game process not seen - ending boost.")
                return
            time.sleep(1)
        if self.state.settings.get("game_priority_high", True):
            time.sleep(3)  # let it finish starting up
            if processes.set_high_priority(exe_name):
                self.log("Game set to High CPU priority.")
        self.log("Game running. R3cket will land automatically when you quit.")
        missing = 0
        while not self._stop.is_set():
            time.sleep(3)
            missing = 0 if processes.find_processes(exe_name) else missing + 1
            if missing >= 2:
                self.log("Game closed.")
                return
