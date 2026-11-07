"""The system tweaks R3cket can apply.

Rules every tweak follows:
  * It records the original setting before changing anything.
  * It can be undone exactly (restore the old value, or delete one we created).
  * It does something real and measurable. No placebo "RAM boosters".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .platform_win import (
    HKCU,
    REG_BINARY,
    REG_DWORD,
    REG_SZ,
    Backend,
)

# ---------------------------------------------------------------------------
# Snapshot helpers (registry values -> JSON-safe dicts and back)
# ---------------------------------------------------------------------------


def _encode(found: Optional[tuple[object, str]]) -> Optional[dict]:
    if found is None:
        return None
    value, kind = found
    if isinstance(value, (bytes, bytearray)):
        return {"value": bytes(value).hex(), "kind": kind, "hex": True}
    return {"value": value, "kind": kind}


def _decode(snap: dict) -> tuple[object, str]:
    value = bytes.fromhex(snap["value"]) if snap.get("hex") else snap["value"]
    return value, snap["kind"]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


@dataclass
class Tweak:
    id: str
    name: str
    description: str
    impact: str  # "High", "Medium" or "Low" - honest expected effect on games
    note: str = ""  # e.g. "Takes full effect after you sign out"
    default_on: bool = True

    def is_applied(self, backend: Backend) -> bool:
        raise NotImplementedError

    def apply(self, backend: Backend) -> dict:
        """Apply and return a snapshot that ``revert`` can use."""
        raise NotImplementedError

    def revert(self, backend: Backend, snapshot: dict) -> None:
        raise NotImplementedError


@dataclass
class RegValue:
    hive: str
    key: str
    name: str
    value: object
    kind: str = REG_DWORD


@dataclass
class RegistryTweak(Tweak):
    values: list[RegValue] = field(default_factory=list)

    def is_applied(self, backend):
        for v in self.values:
            found = backend.reg_get(v.hive, v.key, v.name)
            if found is None or found[0] != v.value:
                return False
        return True

    def apply(self, backend):
        originals = []
        for v in self.values:
            originals.append(_encode(backend.reg_get(v.hive, v.key, v.name)))
            backend.reg_set(v.hive, v.key, v.name, v.value, v.kind)
        return {"originals": originals}

    def revert(self, backend, snapshot):
        for v, orig in zip(self.values, snapshot.get("originals", [])):
            if orig is None:
                backend.reg_delete(v.hive, v.key, v.name)
            else:
                value, kind = _decode(orig)
                backend.reg_set(v.hive, v.key, v.name, value, kind)


# ---------------------------------------------------------------------------
# Power plan
# ---------------------------------------------------------------------------

HIGH_PERF_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
_GUID_RE = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


def active_power_scheme(backend: Backend) -> Optional[str]:
    code, out = backend.run(["powercfg", "/getactivescheme"])
    if code != 0:
        return None
    match = _GUID_RE.search(out)
    return match.group(0).lower() if match else None


@dataclass
class PowerPlanTweak(Tweak):
    """Switch to the High Performance plan.

    Many newer laptops hide that plan, so if switching fails we create a copy
    of it and delete that copy again on revert.
    """

    def is_applied(self, backend):
        code, out = backend.run(["powercfg", "/getactivescheme"])
        if code != 0:
            return False
        if HIGH_PERF_GUID in out.lower():
            return True
        # A copy we created ourselves is labelled with the plan's own name.
        return "r3cket" in out.lower()

    def apply(self, backend):
        previous = active_power_scheme(backend)
        created = None
        code, _ = backend.run(["powercfg", "/setactive", HIGH_PERF_GUID])
        if code != 0:
            code, out = backend.run(["powercfg", "-duplicatescheme", HIGH_PERF_GUID])
            match = _GUID_RE.search(out) if code == 0 else None
            if not match:
                raise RuntimeError("This laptop does not offer a High Performance power plan.")
            created = match.group(0).lower()
            backend.run(["powercfg", "-changename", created, "R3cket High Performance"])
            code, out = backend.run(["powercfg", "/setactive", created])
            if code != 0:
                raise RuntimeError(f"Could not switch power plan: {out.strip()}")
        return {"previous": previous, "created": created}

    def revert(self, backend, snapshot):
        previous = snapshot.get("previous")
        if previous:
            backend.run(["powercfg", "/setactive", previous])
        created = snapshot.get("created")
        if created and created != previous:
            backend.run(["powercfg", "/delete", created])


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

_GAMEBAR = r"Software\Microsoft\GameBar"
_GAMEDVR = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
_GAMECFG = r"System\GameConfigStore"
_VISFX = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"
_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_DESKTOP = r"Control Panel\Desktop"
_WINMETRICS = r"Control Panel\Desktop\WindowMetrics"
_BGAPPS = r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications"

# Windows' own "Adjust for best performance" mask.
_BEST_PERF_MASK = bytes.fromhex("9012038010000000")


def all_tweaks() -> list[Tweak]:
    return [
        PowerPlanTweak(
            id="power_plan",
            name="High Performance power plan",
            description="Stops the CPU and GPU from down-clocking to save power while you play.",
            impact="High",
            note="Plug your charger in - on battery most laptops cap performance anyway.",
        ),
        RegistryTweak(
            id="game_dvr_off",
            name="Turn off background game recording",
            description="Xbox Game DVR quietly records your gameplay in the background, "
            "costing CPU/GPU time. This switches it off (the Game Bar overlay still works).",
            impact="High",
            values=[
                RegValue(HKCU, _GAMECFG, "GameDVR_Enabled", 0),
                RegValue(HKCU, _GAMEDVR, "AppCaptureEnabled", 0),
            ],
        ),
        RegistryTweak(
            id="game_mode_on",
            name="Windows Game Mode on",
            description="Tells Windows to prioritise the game and hold back updates and "
            "background work while it is running.",
            impact="Medium",
            values=[
                RegValue(HKCU, _GAMEBAR, "AutoGameModeEnabled", 1),
                RegValue(HKCU, _GAMEBAR, "AllowAutoGameMode", 1),
            ],
        ),
        RegistryTweak(
            id="visual_effects",
            name="Windows visual effects: best performance",
            description="Turns off animations, shadows and transparency so the desktop "
            "uses less GPU - matters most on integrated graphics.",
            impact="Medium",
            note="Fully takes effect after you sign out and back in.",
            values=[
                RegValue(HKCU, _VISFX, "VisualFXSetting", 2),
                RegValue(HKCU, _DESKTOP, "UserPreferencesMask", _BEST_PERF_MASK, REG_BINARY),
                RegValue(HKCU, _WINMETRICS, "MinAnimate", "0", REG_SZ),
                RegValue(HKCU, _PERSONALIZE, "EnableTransparency", 0),
            ],
        ),
        RegistryTweak(
            id="background_apps_off",
            name="Stop Store apps running in the background",
            description="Prevents Microsoft Store apps (Mail, Weather, News...) from "
            "waking up in the background. Windows 10 mainly.",
            impact="Low",
            values=[RegValue(HKCU, _BGAPPS, "GlobalUserDisabled", 1)],
        ),
    ]


def tweak_by_id(tweak_id: str) -> Tweak:
    for t in all_tweaks():
        if t.id == tweak_id:
            return t
    raise KeyError(tweak_id)
