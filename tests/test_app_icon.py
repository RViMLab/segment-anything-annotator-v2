import unittest

from PIL import Image

from utils.app_icon import application_icon_path


class ApplicationIconTests(unittest.TestCase):
    def test_platform_icon_exists(self):
        self.assertTrue(application_icon_path().is_file())

    def test_windows_icon_contains_standard_sizes(self):
        icon_path = application_icon_path().parent / "app_icon.ico"
        with Image.open(icon_path) as icon:
            sizes = icon.ico.sizes()
        self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes)


if __name__ == "__main__":
    unittest.main()
