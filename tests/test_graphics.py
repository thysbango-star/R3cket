import unittest

from r3cket.graphics import (DEDICATED, ENTRY, INTEGRATED, intel_tips, profile_gpu,
                             render_advice, settings_guide, upscalers_for)
from r3cket.system import advise
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


class IntelTests(unittest.TestCase):
    def test_generations(self):
        self.assertTrue(gpu("Intel(R) Iris(R) Xe Graphics").intel_gen11_plus)
        self.assertTrue(gpu("Intel(R) Iris(R) Plus Graphics").intel_gen11_plus)
        self.assertFalse(gpu("Intel(R) UHD Graphics 620").intel_gen11_plus)
        self.assertEqual(gpu("Intel(R) Arc(TM) A370M Graphics").tier, DEDICATED)
        self.assertEqual(gpu("Intel(R) Arc(TM) Graphics").tier, INTEGRATED)

    def test_retro_scaling_and_xess_note(self):
        ups = upscalers_for(gpu("Intel(R) HD Graphics 620"))
        retro = next(u for u in ups if "Retro" in u.name)
        self.assertIn("Needs 10th-gen", retro.summary)
        self.assertIn("XeSS is Intel's own", ups[0].summary)
        self.assertNotIn("Retro", " ".join(u.name for u in upscalers_for(gpu("NVIDIA GeForce GTX 1650"))))

    def test_single_channel_flagged(self):
        info = SystemInfo(gpus=["Intel(R) UHD Graphics 620"], ram_gb=8, memory_modules=1)
        tips = intel_tips(profile_gpu(info), info)
        self.assertIn("dual channel", tips[0].title)
        self.assertIn("single channel", " ".join(a.title for a in advise(info, True)))
        two = SystemInfo(gpus=["Intel(R) UHD Graphics 620"], ram_gb=8, memory_modules=2, ram_mhz=2400)
        self.assertIn("good", intel_tips(profile_gpu(two), two)[0].title)
        arc = SystemInfo(gpus=["Intel(R) Arc(TM) A370M Graphics"], memory_modules=1)
        self.assertNotIn("dual", " ".join(t.title for t in intel_tips(profile_gpu(arc), arc)))
        self.assertEqual(intel_tips(gpu("NVIDIA GeForce GTX 1650"), SystemInfo()), [])


if __name__ == "__main__":
    unittest.main()
