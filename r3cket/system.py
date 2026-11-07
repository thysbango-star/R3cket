"""Hardware detection and plain-English advice for the laptop R3cket runs on."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import processes
from .platform_win import Backend

_PS_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs  = Get-CimInstance Win32_ComputerSystem
$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
$disks = @(Get-PhysicalDisk | ForEach-Object { "$($_.MediaType)|$($_.BusType)|$($_.FriendlyName)" })
$os = Get-CimInstance Win32_OperatingSystem
[pscustomobject]@{
  cpu = $cpu.Name; cores = $cpu.NumberOfCores; threads = $cpu.NumberOfLogicalProcessors
  ram = $cs.TotalPhysicalMemory; gpus = $gpus; disks = $disks; os = $os.Caption
} | ConvertTo-Json -Compress
"""

_INTEGRATED_HINTS = ("intel", "uhd", "iris", "hd graphics", "vega", "radeon(tm) graphics",
                     "radeon graphics", "radeon r", "microsoft basic")
_DEDICATED_HINTS = ("nvidia", "geforce", "quadro", "rtx", "gtx", "mx1", "mx2", "mx3", "mx4",
                    "mx5", "radeon rx", "radeon pro", "radeon hd 7", "radeon r9")


@dataclass
class SystemInfo:
    cpu: str = "Unknown CPU"
    cores: int = 0
    threads: int = 0
    ram_gb: float = 0.0
    gpus: list[str] = field(default_factory=list)
    disks: list[str] = field(default_factory=list)
    os: str = ""

    @property
    def has_dedicated_gpu(self) -> bool:
        return any(any(h in g.lower() for h in _DEDICATED_HINTS) for g in self.gpus)

    @property
    def has_integrated_gpu(self) -> bool:
        return any(
            any(h in g.lower() for h in _INTEGRATED_HINTS)
            and not any(h in g.lower() for h in _DEDICATED_HINTS)
            for g in self.gpus
        )

    @property
    def has_hdd(self) -> bool:
        return any(d.lower().startswith("hdd") for d in self.disks)

    @property
    def has_ssd(self) -> bool:
        return any(d.lower().startswith("ssd") for d in self.disks)


def detect(backend: Backend) -> SystemInfo:
    code, out = backend.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_QUERY])
    info = SystemInfo()
    if code != 0 or not out.strip():
        return info
    try:
        raw = json.loads(out.strip().splitlines()[-1])
    except ValueError:
        return info
    info.cpu = (raw.get("cpu") or info.cpu).strip()
    info.cores = int(raw.get("cores") or 0)
    info.threads = int(raw.get("threads") or 0)
    info.ram_gb = round((raw.get("ram") or 0) / 1024**3, 1)
    gpus = raw.get("gpus") or []
    info.gpus = [gpus] if isinstance(gpus, str) else list(gpus)
    disks = raw.get("disks") or []
    info.disks = [disks] if isinstance(disks, str) else list(disks)
    info.os = raw.get("os") or ""
    return info


def battery_status() -> tuple[bool | None, int | None]:
    """(plugged_in, percent) or (None, None) if unknown / desktop."""
    if not processes.available():
        return None, None
    batt = processes.psutil.sensors_battery()
    if batt is None:
        return None, None
    return bool(batt.power_plugged), int(batt.percent)


@dataclass
class Advice:
    level: str  # "big", "medium", "tip"
    title: str
    detail: str


def advise(info: SystemInfo, plugged_in: bool | None) -> list[Advice]:
    """Tailored, honest advice. Software tweaks only go so far on old hardware."""
    out: list[Advice] = []

    if plugged_in is False:
        out.append(Advice("big", "Plug in your charger",
                          "On battery, most laptops cut CPU and GPU speed by 30-50%. "
                          "This is often the single biggest FPS difference."))

    if info.has_dedicated_gpu and info.has_integrated_gpu:
        out.append(Advice("big", "Make sure games use your dedicated GPU",
                          "You have two graphics chips. R3cket sets each game you add to "
                          "the high-performance GPU automatically - add your games in the "
                          "Games tab."))
    elif info.gpus and not info.has_dedicated_gpu:
        out.append(Advice("big", "Integrated graphics: lower resolution, not detail",
                          "Run games at 1280x720 (or use a render/resolution scale of "
                          "60-75%, or AMD FSR if the game has it). Turn off shadows, "
                          "anti-aliasing and motion blur first - they cost the most."))

    if info.ram_gb and info.ram_gb <= 4.5:
        out.append(Advice("big", f"Only {info.ram_gb:g} GB of RAM",
                          "Close your web browser before playing - it can use 1-2 GB on "
                          "its own. Upgrading to 8 GB is cheap on most older laptops and "
                          "removes a lot of stutter."))
    elif info.ram_gb and info.ram_gb <= 8.5:
        out.append(Advice("medium", f"{info.ram_gb:g} GB of RAM",
                          "Enough for most older games, but close browsers and chat apps "
                          "while playing. R3cket's Boost can do that for you."))

    if info.has_hdd:
        if info.has_ssd:
            out.append(Advice("medium", "Install games on your SSD",
                              "You have both a hard drive and an SSD. Games on the SSD load "
                              "faster and stutter less when loading new areas."))
        else:
            out.append(Advice("big", "Your laptop uses a hard drive (HDD)",
                              "Swapping it for an SSD is the best upgrade an old laptop can "
                              "get: much faster loading and far fewer hitches."))

    out.append(Advice("medium", "Keep it cool",
                      "Hot laptops slow themselves down (thermal throttling). Play on a hard "
                      "surface, blow dust out of the vents, and consider a cooling pad. "
                      "On 5+ year old laptops new thermal paste can help a lot."))
    out.append(Advice("tip", "Cap your frame rate",
                      "A steady 30 or 45 FPS feels smoother than a jumpy 30-60. Use the "
                      "game's own frame limiter, or your GPU control panel."))
    out.append(Advice("tip", "Update your graphics driver",
                      "Get it from Intel, Nvidia or AMD (or your laptop maker). New drivers "
                      "often fix performance in specific games."))
    return out
