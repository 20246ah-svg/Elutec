import unittest

from src.gui.theme import get_palette


class WorkspaceThemeTests(unittest.TestCase):
    def test_overview_reference_has_light_and_graphite_palettes(self):
        light = get_palette(True)
        dark = get_palette(False)

        self.assertEqual(light["background"], "#F7F8FA")
        self.assertEqual(light["surface"], "#FFFFFF")
        self.assertEqual(dark["background"], "#111827")
        self.assertEqual(dark["text"], "#F3F6FB")
        self.assertEqual(light["accent"], "#5B7CE5")
        self.assertEqual(dark["accent"], "#6D8AF0")
        self.assertNotEqual(light["background"], dark["background"])
        self.assertNotEqual(light["text"], dark["text"])


if __name__ == "__main__":
    unittest.main()
