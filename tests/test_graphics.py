import unittest

from r3cket.graphics import (DEDICATED, ENTRY, INTEGRATED, profile_gpu, render_advice,
                             settings_guide, upscalers_for)
from r3cket.system import SystemInfo


def gpu(*names):
    return profile_gpu(SystemInfo(gpus=list(names)))


class ProfileTests(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(gpu("Intel(R) HD Graphics 520").tier, INTEGRATED)
        self.assertEqual(gpu("Intel(R) UHD Graphics 620", "NVIDIA GeForce MX150").tier, ENTRY)
        self.assertEqual(gpu("Intel(R) HD Graphics 530", "NVIDIA GeForce 940MX").tier, ENTRY)
        self.assertEqual(gpu("Intel UHD 630", "NVIDIA GeForce GTX 1050 Ti").tier, DEDICATED)
        self.assertTrue(gpu("NVIDIA GeForce RTX 3050 Laptop GPU").rtx)
        self.assertEqual(gpu("AMD Radeon(TM) RX Vega 10 Graphics").tier, INTEGRATED)
        self.assertTrue(gpu("AMD Radeon RX 5500M").amd_rsr)
        self.assertTrue(gpu("AMD Radeon(TM) 680M").amd_rsr)
        self.assertFalse(gpu("AMD Radeon(TM) Vega 8 Graphics").amd_rsr)
        self.assertTrue(gpu("Intel(R) Iris(R) Xe Graphics").intel_only)

    def test_upscaler_choices_match_hardware(self):
        names = lambda g: " ".join(u.name for u in upscalers_for(g))
        self.assertIn("NVIDIA Image Scaling", names(gpu("NVIDIA GeForce GTX 1650")))
        self.assertIn("DLSS", names(gpu("NVIDIA GeForce RTX 2060")))
        self.assertNotIn("DLSS", names(gpu("NVIDIA GeForce GTX 1650")))
        self.assertIn("Super Resolution", names(gpu("AMD Radeon RX 6600M")))
        self.assertIn("Image Sharpening", names(gpu("AMD Radeon(TM) Vega 8 Graphics")))
        intel = upscalers_for(gpu("Intel(R) UHD Graphics 620"))
        self.assertNotIn("NVIDIA", " ".join(u.name for u in intel))
        self.assertEqual(next(u for u in intel if "Magpie" in u.name).rank, "good")


class RenderTests(unittest.TestCase):
    def test_integrated_1080p_renders_720p(self):
        adv = render_advice(gpu("Intel(R) UHD Graphics 620"), (1920, 1080))
        self.assertEqual(adv.render, (1280, 720))
        entry = render_advice(gpu("NVIDIA GeForce MX150"), (1920, 1080))
        self.assertEqual(entry.render, (1440, 810))

    def test_low_res_screen_stays_native(self):
        adv = render_advice(gpu("Intel(R) HD Graphics 4000"), (1366, 768))
        self.assertEqual(adv.render, (1366, 768))

    def test_dedicated_native_and_unknown_screen(self):
        self.assertEqual(render_advice(gpu("NVIDIA GeForce GTX 1060"), (1920, 1080)).scale, 1.0)
        self.assertIsNone(render_advice(gpu("Intel HD 520"), None).render)

    def test_settings_guide(self):
        tips = settings_guide(gpu("Intel HD 520"), 8)
        self.assertEqual(tips[0].setting, "Shadows")
        tex = next(t for t in tips if t.setting == "Texture quality")
        self.assertIn("Medium", tex.action)


if __name__ == "__main__":
    unittest.main()
