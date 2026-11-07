# R3cket 🚀

**A game booster for older Windows laptops.** R3cket switches your laptop into
gaming mode, launches your game on the fastest graphics chip, and puts every
setting back the way it was when you quit.

No placebo "RAM cleaners", no registry voodoo — only changes that measurably
help games, every one of them backed up and undoable.

## What it does

| | What | Expected impact |
|---|---|---|
| ⚡ | **High Performance power plan** — stops the CPU/GPU throttling down mid-game (creates the plan if your laptop hides it) | High |
| 🎥 | **Turns off background game recording** (Xbox Game DVR) | High |
| 🎮 | **Windows Game Mode on** | Medium |
| 🪟 | **Visual effects: best performance** — no animations/transparency, frees GPU on integrated graphics | Medium |
| 💤 | **Stops Store apps running in the background** (mostly Windows 10) | Low |
| 🧹 | **Closes background apps** you tick (OneDrive, Teams, browsers…) — politely, so you never lose tabs — and reopens them afterwards | Medium–High on 4–8 GB RAM |
| 🎯 | **Per-game: dedicated GPU** — forces Nvidia/AMD instead of Intel graphics on dual-GPU laptops | High (on those laptops) |
| 🔺 | **Per-game: High CPU priority** (never Realtime, which can freeze Windows) | Low–Medium |

### Better graphics, not just more FPS

The **Graphics** tab detects your GPU and screen and tells you how to get the
best picture your laptop can afford:

- **Render resolution** — e.g. render at 1280x720 on a 1080p screen with
  integrated graphics, then upscale. Low-res screens (1366x768) stay native.
- **Upscalers that fit your hardware**, ranked, with step-by-step setup: the
  game's own FSR / XeSS / DLSS (RTX only), NVIDIA Image Scaling, Radeon Super
  Resolution (RX 5000+ / Ryzen 6000+ graphics) or Radeon Image Sharpening,
  [Magpie](https://github.com/Blinue/Magpie) (free, great on Intel) and Lossless
  Scaling.
- **Which settings to sacrifice first** — shadows, volumetrics, AA and AO cost
  the most FPS for the least visible difference; textures and anisotropic
  filtering are nearly free and keep games looking good.

The **My laptop** tab reads your hardware and gives tailored advice — charger,
RAM, hard drive vs SSD, integrated graphics settings, heat — because on old
hardware those matter more than any software tweak.

## How to use

1. **Launch tab → LAUNCH BOOST** to tune the laptop now; **LAND** to undo.
2. Or **Games tab → Add game… → PLAY WITH R3CKET**: it boosts, starts the game,
   and lands automatically when you close the game.
3. **Tweaks tab → Restore everything** puts back every setting R3cket ever changed.

R3cket doesn't need admin rights — it only changes your own user settings and
power plan. Its backup lives in `%APPDATA%\R3cket\state.json`; if R3cket is
closed mid-game, the next start offers to land the boost.

## Run it

**From source** (Python 3.9+ from python.org):

```bat
pip install -r requirements.txt
python -m r3cket
```

**Build a single .exe:** double-click `build.bat` → `dist\R3cket.exe`.

## Honest expectations

Software can remove what's holding your laptop back — throttling, background
junk, the wrong GPU. Gains vary: small on a clean laptop, big on one that was
throttling, running on the Intel chip, or short on RAM. It can't add hardware. If the game still
struggles, the **My laptop** tab tells you which setting or upgrade will help
most.

## Development

```bash
python -m unittest -v   # runs on any OS using an in-memory fake of Windows
```

```
r3cket/
  app.py           tkinter UI
  engine.py        apply / undo / boost sessions / game watching
  tweaks.py        the tweak catalogue (each one reversible)
  processes.py     background apps & game priority (psutil)
  system.py        hardware detection & advice
  graphics.py      upscaler, render-resolution & settings advice
  state.py         backup + settings (JSON, atomic writes)
  platform_win.py  registry/command backend + FakeBackend for tests
```
