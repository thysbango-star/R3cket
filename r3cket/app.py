"""R3cket desktop app (tkinter - ships with Python, no heavy UI framework)."""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, processes, system
from .engine import BoostSession, Optimizer
from .platform_win import default_backend, is_windows
from .state import State

# ---- look --------------------------------------------------------------------

BG = "#12131a"
PANEL = "#1b1d27"
PANEL_2 = "#232634"
TEXT = "#e8e9f0"
MUTED = "#8b8fa3"
ACCENT = "#ff5a1f"  # rocket-exhaust orange
ACCENT_DARK = "#c94310"
GOOD = "#3ecf8e"
WARN = "#f5b83d"
BAD = "#ef5a5a"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_H2 = ("Segoe UI Semibold", 13)
FONT_TITLE = ("Segoe UI Black", 20)
FONT_BIG = ("Segoe UI Semibold", 16)

IMPACT_COLOURS = {"High": GOOD, "Medium": WARN, "Low": MUTED}
ADVICE_COLOURS = {"big": ACCENT, "medium": WARN, "tip": MUTED}


def _style(root: tk.Tk) -> None:
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, font=FONT, borderwidth=0)
    s.configure("TFrame", background=BG)
    s.configure("Panel.TFrame", background=PANEL)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    s.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=FONT_SMALL)
    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(12, 8, 12, 0))
    s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(16, 8), font=FONT_BOLD)
    s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])
    s.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=FONT)
    s.map("TCheckbutton", background=[("active", PANEL)], indicatorcolor=[("selected", ACCENT)])
    s.configure("Horizontal.TProgressbar", troughcolor=PANEL_2, background=ACCENT,
                bordercolor=PANEL_2, lightcolor=ACCENT, darkcolor=ACCENT)
    s.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=PANEL, arrowcolor=MUTED)


def _button(parent, text, command, primary=False, big=False) -> tk.Button:
    bg = ACCENT if primary else PANEL_2
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg=TEXT,
        activebackground=ACCENT_DARK if primary else "#2e3243", activeforeground=TEXT,
        relief="flat", bd=0, cursor="hand2",
        font=FONT_BIG if big else FONT_BOLD,
        padx=28 if big else 14, pady=12 if big else 6,
    )
    return btn


def _scrollable(parent) -> tuple[tk.Frame, tk.Canvas]:
    """A vertically scrolling frame (for lists that may outgrow small screens)."""
    outer = tk.Frame(parent, bg=PANEL)
    canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0, bd=0)
    bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=PANEL)
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    win = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
    canvas.configure(yscrollcommand=bar.set)
    canvas.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")

    def _wheel(event):
        canvas.yview_scroll(int(-event.delta / 120), "units")

    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
    outer.inner = inner  # type: ignore[attr-defined]
    return outer, canvas


# ---- the app ---------------------------------------------------------------


class R3cketApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.backend = default_backend()
        self.state = State()
        self.opt = Optimizer(self.backend, self.state, log=self.log_queue.put)
        self.session = BoostSession(self.opt)
        self.busy = False
        self.playing = False
        self.app_vars: dict[str, tuple[tk.BooleanVar, processes.RunningApp]] = {}
        self.tweak_vars: dict[str, tk.BooleanVar] = {}
        self.tweak_status_labels: dict[str, tk.Label] = {}

        root.title(f"R3cket {__version__}")
        root.geometry("900x680")
        root.minsize(760, 560)
        _style(root)
        self._build()
        self._poll_log()
        self._tick_monitor()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        if not is_windows():
            self.log("Preview mode: not on Windows, so nothing on this machine is changed.")
        if not processes.available():
            self.log("psutil is not installed - app closing, game watching and live stats are off. "
                     "Run: pip install psutil")
        if self.session.active:
            self.log("A boost from last time is still active (R3cket may have been closed "
                     "mid-game). Press LAND to restore your settings.")
        self.refresh_all()

    # ---- layout --------------------------------------------------------

    def _build(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(header, text="R3CKET", font=FONT_TITLE, fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(header, text="  game booster for older laptops", font=FONT, fg=MUTED,
                 bg=BG).pack(side="left", pady=(10, 0))
        self.status_label = tk.Label(header, text="", font=FONT_BOLD, bg=BG)
        self.status_label.pack(side="right")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        self.tab_launch = ttk.Frame(nb, style="Panel.TFrame")
        self.tab_games = ttk.Frame(nb, style="Panel.TFrame")
        self.tab_tweaks = ttk.Frame(nb, style="Panel.TFrame")
        self.tab_system = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(self.tab_launch, text="  Launch  ")
        nb.add(self.tab_games, text="  Games  ")
        nb.add(self.tab_tweaks, text="  Tweaks  ")
        nb.add(self.tab_system, text="  My laptop  ")

        self._build_launch()
        self._build_games()
        self._build_tweaks()
        self._build_system()

        logf = tk.Frame(self.root, bg=BG)
        logf.pack(fill="x", padx=12, pady=(6, 12))
        self.log_text = tk.Text(logf, height=5, bg=PANEL, fg=MUTED, font=("Consolas", 9),
                                relief="flat", bd=0, padx=10, pady=6, wrap="word")
        self.log_text.pack(fill="x")
        self.log_text.configure(state="disabled")

    def _build_launch(self) -> None:
        tab = self.tab_launch
        top = tk.Frame(tab, bg=PANEL)
        top.pack(fill="x", padx=20, pady=(20, 10))
        self.launch_title = tk.Label(top, text="", font=FONT_H2, fg=TEXT, bg=PANEL, anchor="w")
        self.launch_title.pack(fill="x")
        self.launch_sub = tk.Label(top, text="", font=FONT, fg=MUTED, bg=PANEL, anchor="w",
                                   justify="left", wraplength=780)
        self.launch_sub.pack(fill="x", pady=(2, 12))
        row = tk.Frame(top, bg=PANEL)
        row.pack(fill="x")
        self.launch_btn = _button(row, "LAUNCH BOOST", self.on_launch, primary=True, big=True)
        self.launch_btn.pack(side="left")
        self.battery_label = tk.Label(row, text="", font=FONT_BOLD, bg=PANEL, fg=WARN)
        self.battery_label.pack(side="left", padx=16)

        lst = tk.Frame(tab, bg=PANEL)
        lst.pack(fill="both", expand=True, padx=20, pady=(6, 16))
        hdr = tk.Frame(lst, bg=PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Close these while boosting", font=FONT_BOLD, fg=TEXT,
                 bg=PANEL).pack(side="left")
        _button(hdr, "Refresh", self.refresh_apps).pack(side="right")
        tk.Label(lst, text="Browsers and chat apps get a polite close, like clicking X - you "
                 "won't lose tabs. They reopen when the boost ends.", font=FONT_SMALL,
                 fg=MUTED, bg=PANEL, anchor="w", justify="left", wraplength=780).pack(fill="x",
                                                                                      pady=(2, 6))
        self.apps_box, _ = _scrollable(lst)
        self.apps_box.pack(fill="both", expand=True)

    def _build_games(self) -> None:
        tab = self.tab_games
        wrap = tk.Frame(tab, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)
        tk.Label(wrap, text="Your games", font=FONT_H2, fg=TEXT, bg=PANEL,
                 anchor="w").pack(fill="x")
        tk.Label(wrap, text="Play through R3cket and it boosts your laptop, starts the game on "
                 "your fastest graphics chip at High priority, then puts everything back when "
                 "you quit. For Steam games, pick the game's .exe inside "
                 "Steam\\steamapps\\common\\<game>.", font=FONT, fg=MUTED, bg=PANEL,
                 anchor="w", justify="left", wraplength=780).pack(fill="x", pady=(2, 12))
        self.games_list = tk.Listbox(wrap, bg=PANEL_2, fg=TEXT, font=FONT_BOLD, relief="flat",
                                     bd=0, highlightthickness=0, selectbackground=ACCENT,
                                     selectforeground=TEXT, activestyle="none", height=10)
        self.games_list.pack(fill="both", expand=True)
        self.games_list.bind("<Double-Button-1>", lambda e: self.on_play())
        btns = tk.Frame(wrap, bg=PANEL)
        btns.pack(fill="x", pady=(12, 0))
        self.play_btn = _button(btns, "PLAY WITH R3CKET", self.on_play, primary=True)
        self.play_btn.pack(side="left")
        _button(btns, "Add game...", self.on_add_game).pack(side="left", padx=8)
        _button(btns, "Remove", self.on_remove_game).pack(side="left")

    def _build_tweaks(self) -> None:
        tab = self.tab_tweaks
        box, _ = _scrollable(tab)
        box.pack(fill="both", expand=True, padx=20, pady=(20, 6))
        inner = box.inner
        tk.Label(inner, text="What the boost changes", font=FONT_H2, fg=TEXT, bg=PANEL,
                 anchor="w").pack(fill="x")
        tk.Label(inner, text="Tick what Launch should do. Every change is backed up first and "
                 "can be undone. Impact is our honest estimate for games.", font=FONT,
                 fg=MUTED, bg=PANEL, anchor="w", justify="left",
                 wraplength=760).pack(fill="x", pady=(2, 10))
        enabled = set(self.opt.enabled_tweak_ids())
        for t in self.opt.tweaks:
            card = tk.Frame(inner, bg=PANEL_2, padx=12, pady=10)
            card.pack(fill="x", pady=4)
            top = tk.Frame(card, bg=PANEL_2)
            top.pack(fill="x")
            var = tk.BooleanVar(value=t.id in enabled)
            self.tweak_vars[t.id] = var
            tk.Checkbutton(top, text=t.name, variable=var, command=self._save_tweak_choice,
                           bg=PANEL_2, fg=TEXT, selectcolor=PANEL, activebackground=PANEL_2,
                           activeforeground=TEXT, font=FONT_BOLD, bd=0,
                           highlightthickness=0).pack(side="left")
            status = tk.Label(top, text="", font=FONT_SMALL, bg=PANEL_2)
            status.pack(side="right")
            self.tweak_status_labels[t.id] = status
            tk.Label(top, text=f"{t.impact} impact", font=FONT_SMALL,
                     fg=IMPACT_COLOURS[t.impact], bg=PANEL_2).pack(side="right", padx=12)
            text = t.description + (f"\n{t.note}" if t.note else "")
            tk.Label(card, text=text, font=FONT_SMALL, fg=MUTED, bg=PANEL_2, anchor="w",
                     justify="left", wraplength=720).pack(fill="x", padx=(26, 0))

        tk.Label(inner, text="Options", font=FONT_H2, fg=TEXT, bg=PANEL,
                 anchor="w").pack(fill="x", pady=(16, 4))
        self.setting_vars = {}
        for key, label in [
            ("restore_after_game", "Undo the tweaks automatically when the boost ends"),
            ("relaunch_closed_apps", "Reopen the apps I closed when the boost ends"),
            ("game_priority_high", "Run games at High CPU priority"),
        ]:
            var = tk.BooleanVar(value=bool(self.state.settings.get(key, True)))
            self.setting_vars[key] = var
            tk.Checkbutton(inner, text=label, variable=var,
                           command=lambda k=key, v=var: self.state.set_setting(k, v.get()),
                           bg=PANEL, fg=TEXT, selectcolor=PANEL_2, activebackground=PANEL,
                           activeforeground=TEXT, font=FONT, bd=0, highlightthickness=0,
                           anchor="w").pack(fill="x")

        btns = tk.Frame(tab, bg=PANEL)
        btns.pack(fill="x", padx=20, pady=(4, 16))
        _button(btns, "Apply ticked tweaks permanently", self.on_apply_permanent).pack(side="left")
        _button(btns, "Restore everything", self.on_restore_all).pack(side="right")

    def _build_system(self) -> None:
        tab = self.tab_system
        box, _ = _scrollable(tab)
        box.pack(fill="both", expand=True, padx=20, pady=20)
        inner = box.inner

        live = tk.Frame(inner, bg=PANEL)
        live.pack(fill="x")
        self.meters = {}
        for key, label in [("cpu", "CPU"), ("ram", "Memory")]:
            row = tk.Frame(live, bg=PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=8, anchor="w", font=FONT_BOLD, fg=TEXT,
                     bg=PANEL).pack(side="left")
            bar = ttk.Progressbar(row, maximum=100, style="Horizontal.TProgressbar")
            bar.pack(side="left", fill="x", expand=True, padx=8)
            val = tk.Label(row, text="--", width=6, anchor="e", font=FONT, fg=MUTED, bg=PANEL)
            val.pack(side="left")
            self.meters[key] = (bar, val)

        tk.Label(inner, text="Specs", font=FONT_H2, fg=TEXT, bg=PANEL,
                 anchor="w").pack(fill="x", pady=(16, 4))
        self.specs_label = tk.Label(inner, text="Checking your hardware...", font=FONT,
                                    fg=MUTED, bg=PANEL, anchor="w", justify="left")
        self.specs_label.pack(fill="x")
        tk.Label(inner, text="Advice for this laptop", font=FONT_H2, fg=TEXT, bg=PANEL,
                 anchor="w").pack(fill="x", pady=(16, 4))
        self.advice_box = tk.Frame(inner, bg=PANEL)
        self.advice_box.pack(fill="x")

    # ---- refresh -------------------------------------------------------

    def refresh_all(self) -> None:
        self.refresh_status()
        self.refresh_apps()
        self.refresh_games()
        self._in_thread(self._load_system, quiet=True)

    def refresh_status(self) -> None:
        active = self.session.active
        if active:
            self.status_label.configure(text="IN ORBIT  ●", fg=GOOD)
            self.launch_title.configure(text="Boost is on")
            self.launch_sub.configure(text="Your laptop is tuned for gaming. Press LAND when "
                                      "you're done to put everything back.")
            self.launch_btn.configure(text="LAND", bg=PANEL_2, activebackground="#2e3243",
                                      command=self.on_land)
        else:
            self.status_label.configure(text="GROUNDED  ●", fg=MUTED)
            self.launch_title.configure(text="Ready for liftoff")
            self.launch_sub.configure(text="LAUNCH BOOST switches your laptop into gaming mode "
                                      "(see the Tweaks tab) and closes the apps ticked below. "
                                      "Or add a game in the Games tab and R3cket does it all "
                                      "automatically.")
            self.launch_btn.configure(text="LAUNCH BOOST", bg=ACCENT,
                                      activebackground=ACCENT_DARK, command=self.on_launch)
        self.launch_btn.configure(state="disabled" if self.busy else "normal")
        self.play_btn.configure(
            state="disabled" if (self.busy or self.playing or active) else "normal")

        statuses = self.opt.status()
        for tid, label in self.tweak_status_labels.items():
            on = statuses.get(tid)
            label.configure(text="● ON" if on else "○ off", fg=GOOD if on else MUTED)

        plugged, pct = system.battery_status()
        if plugged is False:
            self.battery_label.configure(text=f"On battery ({pct}%) - plug in for full speed")
        else:
            self.battery_label.configure(text="")

    def refresh_apps(self) -> None:
        for child in self.apps_box.inner.winfo_children():
            child.destroy()
        previous = {name: var.get() for name, (var, _) in self.app_vars.items()}
        saved = self.state.settings.get("apps_to_close")
        self.app_vars = {}
        apps = processes.running_background_apps()
        if not apps:
            msg = ("Nothing to close - nice and clean." if processes.available()
                   else "Install psutil to see running apps.")
            tk.Label(self.apps_box.inner, text=msg, font=FONT, fg=MUTED, bg=PANEL,
                     anchor="w").pack(fill="x", pady=8)
            return
        for app in apps:
            if app.name in previous:
                ticked = previous[app.name]
            elif saved is not None:
                ticked = app.name in saved
            else:
                ticked = app.suggested
            var = tk.BooleanVar(value=ticked)
            self.app_vars[app.name] = (var, app)
            row = tk.Frame(self.apps_box.inner, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Checkbutton(row, text=app.label, variable=var, command=self._save_app_choice,
                           bg=PANEL, fg=TEXT, selectcolor=PANEL_2, activebackground=PANEL,
                           activeforeground=TEXT, font=FONT, bd=0, highlightthickness=0,
                           anchor="w").pack(side="left")
            tk.Label(row, text=f"{app.memory_mb:,.0f} MB", font=FONT_SMALL, fg=MUTED,
                     bg=PANEL).pack(side="right", padx=8)

    def refresh_games(self) -> None:
        self.games_list.delete(0, "end")
        for g in self.state.data["games"]:
            self.games_list.insert("end", f"   ▸  {g['name']}")
        if not self.state.data["games"]:
            self.games_list.insert("end", "   No games yet - click 'Add game...'")

    def _load_system(self) -> None:
        info = system.detect(self.backend)
        plugged, _ = system.battery_status()
        advice = system.advise(info, plugged)
        self.root.after(0, lambda: self._show_system(info, advice))

    def _show_system(self, info, advice) -> None:
        lines = [
            f"Processor:  {info.cpu}" + (f"  ({info.cores} cores / {info.threads} threads)"
                                          if info.cores else ""),
            f"Memory:     {info.ram_gb:g} GB" if info.ram_gb else "Memory:     unknown",
            "Graphics:   " + (", ".join(info.gpus) if info.gpus else "unknown"),
            "Storage:    " + (", ".join(d.split("|")[0] + " " + d.split("|")[-1]
                                         for d in info.disks) if info.disks else "unknown"),
            f"Windows:    {info.os}" if info.os else "",
        ]
        self.specs_label.configure(text="\n".join(l for l in lines if l), fg=TEXT,
                                   font=("Consolas", 10))
        for child in self.advice_box.winfo_children():
            child.destroy()
        for a in advice:
            card = tk.Frame(self.advice_box, bg=PANEL_2, padx=12, pady=8)
            card.pack(fill="x", pady=3)
            tk.Frame(card, bg=ADVICE_COLOURS[a.level], width=4).pack(side="left", fill="y",
                                                                     padx=(0, 10))
            body = tk.Frame(card, bg=PANEL_2)
            body.pack(side="left", fill="x", expand=True)
            tk.Label(body, text=a.title, font=FONT_BOLD, fg=TEXT, bg=PANEL_2,
                     anchor="w").pack(fill="x")
            tk.Label(body, text=a.detail, font=FONT_SMALL, fg=MUTED, bg=PANEL_2, anchor="w",
                     justify="left", wraplength=700).pack(fill="x")

    def _tick_monitor(self) -> None:
        if processes.available():
            ps = processes.psutil
            cpu = ps.cpu_percent(interval=None)
            ram = ps.virtual_memory().percent
            for key, value in (("cpu", cpu), ("ram", ram)):
                bar, label = self.meters[key]
                bar.configure(value=value)
                label.configure(text=f"{value:.0f}%")
        self.root.after(2000, self._tick_monitor)

    # ---- actions -------------------------------------------------------

    def _selected_apps(self) -> list[processes.RunningApp]:
        return [app for var, app in self.app_vars.values() if var.get()]

    def _save_app_choice(self) -> None:
        self.state.set_setting("apps_to_close",
                               [name for name, (var, _) in self.app_vars.items() if var.get()])

    def _save_tweak_choice(self) -> None:
        self.state.set_setting("enabled_tweaks",
                               [tid for tid, var in self.tweak_vars.items() if var.get()])

    def _in_thread(self, fn, quiet: bool = False) -> None:
        if not quiet:
            self.busy = True
            self.refresh_status()

        def run():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"Error: {exc}")
            finally:
                if not quiet:
                    self.busy = False
                self.root.after(0, self.refresh_status)

        threading.Thread(target=run, daemon=True).start()

    def on_launch(self) -> None:
        apps = self._selected_apps()
        self._in_thread(lambda: self.session.start(apps))

    def on_land(self) -> None:
        if self.playing:
            # The game-watching thread notices this, lands, and refreshes the UI.
            self.session.stop_watching()
            return
        self._in_thread(self.session.end)
        self.root.after(1500, self.refresh_apps)

    def on_apply_permanent(self) -> None:
        ids = [tid for tid, var in self.tweak_vars.items() if var.get()]
        self._in_thread(lambda: self.opt.apply(ids))

    def on_restore_all(self) -> None:
        if messagebox.askyesno("Restore everything",
                               "Put every setting R3cket has changed back to how it was?"):
            self.session.stop_watching()
            self._in_thread(self.opt.restore_everything)

    def on_add_game(self) -> None:
        path = filedialog.askopenfilename(title="Pick the game's .exe",
                                          filetypes=[("Programs", "*.exe")])
        if not path:
            return
        path = os.path.normpath(path)
        default = os.path.splitext(os.path.basename(path))[0]
        name = _ask_text(self.root, "Name this game", "Game name:", default) or default
        self.state.data["games"].append({"name": name, "exe": path, "args": ""})
        self.state.save()
        self.refresh_games()
        self.log(f"Added {name}.")

    def _selected_game(self):
        sel = self.games_list.curselection()
        games = self.state.data["games"]
        if not sel or sel[0] >= len(games):
            return None, None
        return sel[0], games[sel[0]]

    def on_remove_game(self) -> None:
        idx, game = self._selected_game()
        if game is None:
            return
        self.opt.revert_gpu_preference(game["exe"])
        del self.state.data["games"][idx]
        self.state.save()
        self.refresh_games()

    def on_play(self) -> None:
        if self.session.active:
            return
        _, game = self._selected_game()
        if game is None:
            if self.state.data["games"]:
                messagebox.showinfo("R3cket", "Pick a game from the list first.")
            else:
                self.on_add_game()
            return
        if not os.path.exists(game["exe"]):
            messagebox.showerror("R3cket", f"Can't find {game['exe']}.\nRemove it and add it again.")
            return
        self.playing = True
        self.refresh_status()

        def finished():
            self.playing = False
            self.root.after(0, self.refresh_status)
            self.root.after(1500, self.refresh_apps)

        self.session.play(game, self._selected_apps(), on_finished=finished)
        self.root.after(1500, self.refresh_status)

    # ---- log & lifecycle -------------------------------------------------

    def log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def _poll_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", f"› {msg}\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log)

    def _on_close(self) -> None:
        if self.session.active:
            answer = messagebox.askyesnocancel(
                "R3cket", "A boost is still on. Land it (restore your settings) before quitting?")
            if answer is None:
                return
            if answer:
                self.session.stop_watching()
                self.session.end()
        self.root.destroy()


def _ask_text(root, title, prompt, default="") -> str:
    win = tk.Toplevel(root, bg=PANEL, padx=16, pady=16)
    win.title(title)
    win.transient(root)
    win.resizable(False, False)
    tk.Label(win, text=prompt, bg=PANEL, fg=TEXT, font=FONT).pack(anchor="w")
    var = tk.StringVar(value=default)
    entry = tk.Entry(win, textvariable=var, width=36, bg=PANEL_2, fg=TEXT, relief="flat",
                     insertbackground=TEXT, font=FONT)
    entry.pack(fill="x", pady=8, ipady=4)
    entry.select_range(0, "end")
    entry.focus_set()
    result = {"value": default}

    def ok(_=None):
        result["value"] = var.get().strip()
        win.destroy()

    entry.bind("<Return>", ok)
    _button(win, "OK", ok, primary=True).pack(anchor="e")
    win.grab_set()
    root.wait_window(win)
    return result["value"]


def main() -> None:
    if is_windows():
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    R3cketApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
