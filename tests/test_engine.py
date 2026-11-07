"""Tests run on any OS using the in-memory FakeBackend."""

import os
import tempfile
import unittest

from r3cket.engine import GPU_HIGH_PERF, GPU_PREF_KEY, BoostSession, Optimizer
from r3cket.platform_win import HKCU, REG_DWORD, FakeBackend
from r3cket.state import State
from r3cket.system import SystemInfo, advise
from r3cket.tweaks import HIGH_PERF_GUID, all_tweaks

BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"


def make(responses=None):
    tmp = tempfile.mkdtemp()
    backend = FakeBackend(responses=responses or {})
    state = State(os.path.join(tmp, "state.json"))
    return backend, state, Optimizer(backend, state)


class RegistryTweakTests(unittest.TestCase):
    def test_apply_then_revert_restores_original_values(self):
        backend, state, opt = make()
        key = r"System\GameConfigStore"
        backend.reg_set(HKCU, key, "GameDVR_Enabled", 1, REG_DWORD)

        self.assertEqual(opt.apply(["game_dvr_off"]), ["game_dvr_off"])
        self.assertEqual(backend.reg_get(HKCU, key, "GameDVR_Enabled")[0], 0)

        opt.revert(["game_dvr_off"])
        self.assertEqual(backend.reg_get(HKCU, key, "GameDVR_Enabled")[0], 1)
        # A value that did not exist before is deleted again, not left at 0.
        self.assertIsNone(backend.reg_get(
            HKCU, r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled"))

    def test_binary_values_survive_the_json_backup(self):
        backend, state, opt = make()
        original = bytes.fromhex("9e1e078012000000")
        backend.reg_set(HKCU, r"Control Panel\Desktop", "UserPreferencesMask", original, "REG_BINARY")
        opt.apply(["visual_effects"])
        # Reload state from disk, as after a restart.
        opt2 = Optimizer(backend, State(state.path))
        opt2.revert(["visual_effects"])
        self.assertEqual(backend.reg_get(HKCU, r"Control Panel\Desktop", "UserPreferencesMask")[0],
                         original)

    def test_applying_twice_keeps_the_first_original(self):
        backend, state, opt = make()
        opt.apply(["game_mode_on"])
        opt.apply(["game_mode_on"])  # already on: no new snapshot
        opt.revert(["game_mode_on"])
        self.assertIsNone(backend.reg_get(HKCU, r"Software\Microsoft\GameBar", "AutoGameModeEnabled"))


class PowerPlanTests(unittest.TestCase):
    def test_switches_and_switches_back(self):
        backend, state, opt = make({
            "powercfg /getactivescheme": (0, f"Power Scheme GUID: {BALANCED}  (Balanced)"),
        })
        opt.apply(["power_plan"])
        self.assertIn(["powercfg", "/setactive", HIGH_PERF_GUID], backend.commands)
        opt.revert(["power_plan"])
        self.assertEqual(backend.commands[-1], ["powercfg", "/setactive", BALANCED])

    def test_creates_plan_when_hidden_and_deletes_it_after(self):
        new = "11111111-2222-3333-4444-555555555555"
        backend, state, opt = make({
            "powercfg /getactivescheme": (0, f"Power Scheme GUID: {BALANCED}  (Balanced)"),
            f"powercfg /setactive {HIGH_PERF_GUID}": (1, "Invalid"),
            "powercfg -duplicatescheme": (0, f"Power Scheme GUID: {new}  (High performance)"),
        })
        opt.apply(["power_plan"])
        self.assertIn(["powercfg", "/setactive", new], backend.commands)
        opt.revert(["power_plan"])
        self.assertIn(["powercfg", "/delete", new], backend.commands)


class GpuAndRestoreTests(unittest.TestCase):
    def test_gpu_preference_round_trip(self):
        backend, state, opt = make()
        exe = r"C:\Games\game.exe"
        opt.set_gpu_high_performance(exe)
        self.assertEqual(backend.reg_get(HKCU, GPU_PREF_KEY, exe)[0], GPU_HIGH_PERF)
        opt.restore_everything()
        self.assertIsNone(backend.reg_get(HKCU, GPU_PREF_KEY, exe))

    def test_session_restores_only_what_it_changed(self):
        backend, state, opt = make()
        opt.apply(["game_mode_on"])  # user turned this on permanently
        session = BoostSession(opt)
        state.data["settings"]["enabled_tweaks"] = ["game_mode_on", "game_dvr_off"]
        session.start([])
        self.assertEqual(state.data["session"]["tweaks"], ["game_dvr_off"])
        session.end()
        self.assertIsNone(state.data["session"])
        status = opt.status()
        self.assertTrue(status["game_mode_on"])
        self.assertFalse(status["game_dvr_off"])

    def test_crashed_session_is_recoverable(self):
        backend, state, opt = make()
        BoostSession(opt).start([])
        # Simulate a crash: new process, new objects, same files.
        opt2 = Optimizer(backend, State(state.path))
        self.assertTrue(BoostSession(opt2).active)
        opt2.restore_everything()
        self.assertFalse(any(opt2.status().values()))


class AdviceTests(unittest.TestCase):
    def test_old_laptop_gets_the_big_ones(self):
        info = SystemInfo(ram_gb=4.0, gpus=["Intel(R) HD Graphics 520"], disks=["HDD|SATA|WDC"])
        titles = " ".join(a.title for a in advise(info, plugged_in=False))
        self.assertIn("charger", titles)
        self.assertIn("Integrated graphics", titles)
        self.assertIn("RAM", titles)
        self.assertIn("hard drive", titles)

    def test_hybrid_graphics_detected(self):
        info = SystemInfo(gpus=["Intel(R) UHD Graphics 620", "NVIDIA GeForce MX150"])
        self.assertTrue(info.has_dedicated_gpu and info.has_integrated_gpu)

    def test_every_tweak_has_honest_metadata(self):
        for t in all_tweaks():
            self.assertIn(t.impact, {"High", "Medium", "Low"})
            self.assertTrue(t.description)


if __name__ == "__main__":
    unittest.main()
