"""Graphics quality advice: render resolution, upscalers, and which settings to sacrifice.

Old laptops can't add detail, but they can render fewer pixels and scale them up
cleverly (FSR, NIS, RSR, Magpie...), which looks far better than simply running
at a low resolution. This module works out what this laptop can use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .platform_win import is_windows
from .system import SystemInfo

# ---- GPU classification ------------------------------------------------------

INTEGRATED = "integrated"
ENTRY = "entry"  # weak dedicated: MX150, 940MX, GT 7xx...
DEDICATED = "dedicated"

_ENTRY_NV = re.compile(r"\b(mx\s?\d{3}|gt\s?\d{3}|9[0-4]0m|[78][0-4]0m|9[0-4]0mx)\b")
_RDNA_DGPU = re.compile(r"\brx\s?[5-9]\d{3}")
_RDNA_IGPU = re.compile(r"radeon\s*(\(tm\))?\s*[6-9]\d0m\b")  # 660M, 680M, 780M, 880M...


@dataclass
class GpuProfile:
    tier: str
    name: str
    nvidia: bool = False
    rtx: bool = False
    amd: bool = False
    amd_rsr: bool = False  # RX 5000+ or Ryzen 6000+ graphics
    intel_only: bool = False
    intel_gen11_plus: bool = False  # Iris Plus / Iris Xe / Arc: has Retro (integer) Scaling


def profile_gpu(info: SystemInfo) -> GpuProfile:
    names = [g for g in info.gpus if "basic" not in g.lower() and "virtual" not in g.lower()]
    lower = [g.lower() for g in names]
    nv = [g for g in lower if "nvidia" in g or "geforce" in g]
    amd_d = [g for g in lower if _RDNA_DGPU.search(g) or re.search(r"\b(rx|r9|r7|hd)\s?\d", g)
             and "radeon" in g]
    amd_any = [g for g in lower if "radeon" in g or "amd" in g]

    if nv:
        g = nv[0]
        tier = ENTRY if _ENTRY_NV.search(g) else DEDICATED
        return GpuProfile(tier, names[lower.index(g)], nvidia=True, rtx="rtx" in g)
    if amd_d:
        g = amd_d[0]
        return GpuProfile(DEDICATED, names[lower.index(g)], amd=True,
                          amd_rsr=bool(_RDNA_DGPU.search(g)))
    if amd_any:
        g = amd_any[0]
        return GpuProfile(INTEGRATED, names[lower.index(g)], amd=True,
                          amd_rsr=bool(_RDNA_IGPU.search(g)))
    if names:
        g = lower[0]
        modern = any(k in g for k in ("iris(r) plus", "iris plus", "iris(r) xe", "iris xe", "arc"))
        tier = DEDICATED if "arc(tm) a" in g or re.search(r"arc\s*a\d", g) else INTEGRATED
        return GpuProfile(tier, names[0], intel_only=True, intel_gen11_plus=modern)
    return GpuProfile(INTEGRATED, "Unknown graphics")


# ---- screen & render resolution -------------------------------------------


def screen_resolution() -> tuple[int, int] | None:
    if not is_windows():
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:  # noqa: BLE001
        return None


@dataclass
class RenderAdvice:
    screen: tuple[int, int] | None
    render: tuple[int, int] | None
    scale: float
    headline: str
    detail: str


_COMMON_HEIGHTS = (540, 600, 648, 720, 768, 810, 864, 900, 960, 1080, 1200, 1440)


def _snap(screen: tuple[int, int], scale: float) -> tuple[int, int]:
    """Nearest common resolution with the screen's shape (e.g. 1280x720, not 1286x724)."""
    target = screen[1] * scale
    height = min((h for h in _COMMON_HEIGHTS if h < screen[1]), key=lambda h: abs(h - target),
                 default=screen[1])
    width = int(round(screen[0] * height / screen[1] / 2) * 2)
    return width, height


def render_advice(gpu: GpuProfile, screen: tuple[int, int] | None) -> RenderAdvice:
    if gpu.tier == DEDICATED:
        scale, mode = 1.0, None
    elif gpu.tier == ENTRY:
        scale, mode = 0.77, "FSR Ultra Quality / 77%"
    else:
        scale, mode = 0.67, "FSR Quality / 67%"

    if screen and screen[1] <= 800:
        # 1366x768 and similar: already few pixels, upscaling from lower looks rough.
        return RenderAdvice(
            screen, screen, 1.0,
            f"Play at your screen's native {screen[0]}x{screen[1]}",
            "Your screen is already low-resolution, so dropping further looks blurry. "
            "Keep native resolution and lower the settings below instead. If a game "
            "is still too slow, try FSR Ultra Quality (77%) as a last step.",
        )
    if scale == 1.0:
        render = screen
        return RenderAdvice(
            screen, render, 1.0,
            "Play at native resolution" + (f" ({screen[0]}x{screen[1]})" if screen else ""),
            "Your graphics chip can usually drive your screen's full resolution in "
            "older and lighter games. For demanding new games, use the game's own "
            "upscaler on Quality.",
        )
    render = _snap(screen, scale) if screen else None
    where = f"{render[0]}x{render[1]}" if render else f"{int(scale * 100)}% of your screen"
    return RenderAdvice(
        screen, render, scale,
        f"Render at {where}, then upscale ({mode})",
        "That's roughly half the pixels of full resolution - often 50-80% more FPS - "
        "and a good upscaler with sharpening keeps it looking close to native. "
        "Use one of the upscalers below rather than just picking a lower resolution.",
    )


# ---- upscalers -----------------------------------------------------------


@dataclass
class Upscaler:
    name: str
    rank: str  # "best", "good", "alt"
    summary: str
    steps: list[str] = field(default_factory=list)
    link: tuple[str, str] | None = None  # (button text, url)


MAGPIE_URL = "https://github.com/Blinue/Magpie/releases"
LOSSLESS_URL = "https://store.steampowered.com/app/993090/Lossless_Scaling/"
NVIDIA_APP_URL = "https://www.nvidia.com/en-us/software/nvidia-app/"
AMD_DRIVERS_URL = "https://www.amd.com/en/support/download/drivers.html"


def upscalers_for(gpu: GpuProfile) -> list[Upscaler]:
    out: list[Upscaler] = []

    in_game = "FSR, XeSS" + (" or DLSS" if gpu.rtx else "")
    intel_note = ""
    if gpu.intel_only:
        intel_note = (" On Intel graphics try both: XeSS is Intel's own and often looks "
                      "sharper on Iris Xe/Arc, while FSR is usually lighter on older HD/UHD chips.")
    out.append(Upscaler(
        f"The game's own upscaler ({in_game})", "best",
        "Best quality, because the game feeds the upscaler extra information. Use it "
        "whenever the game has one." + (" DLSS usually looks best on your RTX GPU." if gpu.rtx
                                         else " FSR and XeSS work on any graphics chip.")
        + intel_note,
        ["Open the game's Graphics / Display settings.",
         "Look for 'Upscaling', 'Super Resolution', 'FidelityFX', 'XeSS' or 'Resolution scale'.",
         "Pick Quality first; Balanced if you still need more FPS.",
         "Turn on the sharpening slider if there is one (around 50-70%)."],
    ))

    if gpu.nvidia:
        out.append(Upscaler(
            "NVIDIA Image Scaling (driver)", "good",
            "Works in almost any game: set the game to a lower resolution and the "
            "driver upscales and sharpens it. On some laptops the option is missing "
            "because the screen is wired through the Intel chip - then use Magpie.",
            ["Open NVIDIA Control Panel (right-click desktop) or the NVIDIA app.",
             "Manage 3D settings > Image Scaling > On, sharpening around 50%.",
             "In the game, pick one of the new lower resolutions (e.g. 85% or 77%)."],
            ("Get the NVIDIA app", NVIDIA_APP_URL),
        ))
    if gpu.amd and gpu.amd_rsr:
        out.append(Upscaler(
            "Radeon Super Resolution (driver)", "good",
            "AMD's driver upscaler for almost any game. Needs the game in exclusive "
            "fullscreen mode.",
            ["Open AMD Software: Adrenalin Edition > Gaming > Graphics.",
             "Turn on Radeon Super Resolution.",
             "In the game: Fullscreen (not borderless), and a lower resolution."],
            ("AMD drivers", AMD_DRIVERS_URL),
        ))
    elif gpu.amd:
        out.append(Upscaler(
            "Radeon Image Sharpening (driver)", "good",
            "Your AMD chip doesn't have Super Resolution, but sharpening helps a lower "
            "resolution look crisper. Pair it with the game's resolution scale.",
            ["AMD Software (Adrenalin) > Gaming > Graphics > Radeon Image Sharpening: On.",
             "Set it before starting the game.",
             "Lower the game's resolution scale to 75-85%."],
            ("AMD drivers", AMD_DRIVERS_URL),
        ))

    if gpu.intel_only:
        out.append(Upscaler(
            "Intel Retro Scaling (integer scaling)", "alt",
            "Scales the image by exact whole numbers, so pixels stay perfectly sharp - "
            "e.g. 960x540 shown as crisp 2x on a 1080p screen. Great for pixel-art and "
            "older games; for modern 3D games an FSR upscaler usually looks better. "
            + ("Your Intel graphics supports it."
               if gpu.intel_gen11_plus else
               "Needs 10th-gen Ice Lake (Iris Plus) or newer Intel graphics - if you "
               "don't see the option, your chip doesn't have it."),
            ["Open Intel Graphics Command Center or Intel Graphics Software "
             "(search the Start menu; install it from the Microsoft Store if missing).",
             "Display > Scaling > Retro Scaling (or Integer Scaling).",
             "In the game, pick exactly half your screen resolution, in fullscreen."],
        ))

    out.append(Upscaler(
        "Magpie (free)", "good" if gpu.intel_only else "alt",
        "Free, open-source app that upscales any game running in windowed or borderless "
        "mode using FSR and other scalers. The best option for Intel graphics.",
        ["Download and run Magpie.",
         "Set the game to Windowed or Borderless at a lower resolution (e.g. 1280x720).",
         "Press Alt+Shift+A in the game (default hotkey) and choose the FSR mode."],
        ("Download Magpie", MAGPIE_URL),
    ))
    out.append(Upscaler(
        "Lossless Scaling (paid, Steam)", "alt",
        "Cheap Steam app that upscales any windowed game and can add generated frames. "
        "Frame generation only helps when the game already runs at 30+ FPS, adds a "
        "little input lag, and costs GPU power itself - try upscaling alone first on "
        "integrated graphics.",
        ["Set the game to Windowed or Borderless at a lower resolution.",
         "In Lossless Scaling choose LS1 or FSR scaling, then press Scale.",
         "Only enable frame generation if your base FPS is 30 or more."],
        ("View on Steam", LOSSLESS_URL),
    ))
    return out


# ---- Intel-specific tips ------------------------------------------------------

INTEL_DRIVER_URL = ("https://www.intel.com/content/www/us/en/support/"
                    "intel-driver-support-assistant.html")


@dataclass
class Tip:
    title: str
    detail: str
    link: tuple[str, str] | None = None


def intel_tips(gpu: GpuProfile, info: SystemInfo) -> list[Tip]:
    """Things that matter specifically when gaming on Intel integrated graphics."""
    if not gpu.intel_only:
        return []
    tips = []
    integrated = gpu.tier == INTEGRATED  # Arc A-series cards have their own memory
    if integrated and info.memory_modules == 1:
        tips.append(Tip(
            "Add a second memory stick (dual channel)",
            "Intel graphics have no memory of their own - they borrow your RAM, so RAM "
            "speed is graphics speed. Windows sees one module, so you're probably in single "
            "channel. A matching second stick can be the biggest upgrade this laptop can get "
            "for games (if it has a free slot - some have soldered memory)."))
    elif integrated and info.memory_modules >= 2:
        tips.append(Tip(
            "Dual-channel memory: good",
            f"Windows sees {info.memory_modules} memory modules"
            + (f" at {info.ram_mhz} MHz" if info.ram_mhz else "")
            + ", which is what Intel graphics need for full speed."))
    tips.append(Tip(
        "Set the Intel driver to maximum performance",
        "In Intel Graphics Command Center (or Intel Graphics Software), look for "
        "System > Power and set 'Plugged in' to Maximum Performance. By default the "
        "driver may hold the graphics clock back to save power."))
    tips.append(Tip(
        "Use Intel's own driver, not just Windows Update's",
        "Intel's newer drivers include game-specific fixes. Intel Driver & Support "
        "Assistant finds the right one. Some laptop makers lock their custom driver - "
        "if Intel's installer refuses, use the newest one from your laptop maker's site.",
        ("Intel Driver Assistant", INTEL_DRIVER_URL)))
    if integrated and info.ram_gb and info.ram_gb <= 8.5:
        tips.append(Tip(
            "Leave memory free for the graphics",
            "Intel graphics carve their video memory out of your RAM, so every app you "
            "close gives the game more. Let R3cket's boost close browsers before playing."))
    return tips


# ---- settings priority -------------------------------------------------------


@dataclass
class SettingTip:
    setting: str
    fps_cost: str  # "Huge", "High", "Medium", "Low", "Tiny"
    looks: str  # how much you notice it
    action: str


def settings_guide(gpu: GpuProfile, ram_gb: float) -> list[SettingTip]:
    weak = gpu.tier != DEDICATED
    low_memory = gpu.tier == INTEGRATED and ram_gb and ram_gb <= 8.5
    return [
        SettingTip("Shadows", "Huge", "Some", "Low or Medium. Biggest FPS win for the least visual loss."),
        SettingTip("Volumetric fog / clouds / lighting", "High", "Little", "Low or Off."),
        SettingTip("Anti-aliasing", "High", "Some",
                   "Avoid MSAA/SSAA. Use FXAA or TAA - or rely on the upscaler's own AA."),
        SettingTip("Ambient occlusion (SSAO/HBAO)", "High", "Little", "Off or Low."),
        SettingTip("Reflections", "High", "Some", "Low (screen-space), never ray-traced."),
        SettingTip("Motion blur & depth of field", "Medium", "Blurs the image",
                   "Off - you gain FPS and a sharper picture."),
        SettingTip("Draw / view distance", "Medium", "Noticeable",
                   "Medium. Mostly costs CPU, so drop it if your CPU is maxed."),
        SettingTip("Grass / foliage density", "Medium", "Little", "Low."),
        SettingTip("Texture quality", "Tiny FPS, uses video memory", "A lot",
                   "Medium (low-memory laptop) - integrated graphics borrow your RAM."
                   if low_memory else
                   "Keep High if the game doesn't stutter - it's the cheapest way to look good."),
        SettingTip("Anisotropic filtering", "Tiny", "A lot", "8x or 16x - almost free, keeps floors sharp."),
        SettingTip("Frame rate cap", "-", "Smoothness",
                   "Cap at 30, 40 or 45 for a steady feel" if weak else
                   "Cap a little below your average FPS for steady frame times."),
    ]
