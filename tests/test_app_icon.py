import unittest
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from annotator import MainWindow
from PyQt5 import QtCore, QtGui, QtWidgets

from PIL import Image

from utils.app_icon import (
    APPLICATION_ID, application_icon_path, configure_qt_application,
    configure_windows_app_id, load_application_icon,
)
from scripts.build_app_icon import build_icons, square_png


class ApplicationIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_platform_icon_exists(self):
        self.assertTrue(application_icon_path().is_file())

    def test_windows_icon_contains_standard_sizes(self):
        icon_path = application_icon_path().parent / "app_icon.ico"
        with Image.open(icon_path) as icon:
            sizes = icon.ico.sizes()
        self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes)

    def test_generated_assets_are_square_transparent_and_all_ico_frames_decode(self):
        with Image.open(application_icon_path().parent / "app_icon.png") as png:
            self.assertEqual(png.size, (1024, 1024))
            self.assertEqual(png.mode, "RGBA")
            self.assertEqual(png.getpixel((0, 0))[3], 0)
        with Image.open(application_icon_path().parent / "app_icon.ico") as icon:
            for size in (16, 24, 32, 48, 64, 128, 256):
                frame = icon.ico.getimage((size, size)).convert("RGBA")
                self.assertEqual(frame.size, (size, size))
                self.assertIsNotNone(frame.getchannel("A").getbbox())

    def test_build_pads_non_square_png_without_stretching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGBA", (400, 200), "red").save(root / "source.png")
            build_icons(root / "source.png", root / "icon.png", root / "icon.ico")
            with Image.open(root / "icon.png") as icon:
                self.assertEqual(icon.getchannel("A").getbbox(), (312, 412, 712, 612))

    def test_app_png_preserves_inkscape_export_pixels_and_red_exactly(self):
        assets = application_icon_path().parent
        with Image.open(assets / "SAMAnnLogo.png") as source, Image.open(assets / "app_icon.png") as generated:
            source = source.convert("RGBA")
            x = (generated.width - source.width) // 2
            y = (generated.height - source.height) // 2
            self.assertEqual(generated.crop((x, y, x + source.width, y + source.height)).tobytes(), source.tobytes())
            self.assertIn((255, 63, 51, 255), source.getdata())

    def test_editable_svg_renders_without_changing_source(self):
        source = application_icon_path().parent / "SAMAnnLogo.svg"
        before = source.read_bytes()
        rendered = square_png(source)
        self.assertEqual(rendered.size, (1024, 1024))
        self.assertIsNotNone(rendered.getchannel("A").getbbox())
        self.assertEqual(source.read_bytes(), before)

    def test_corrupt_or_missing_windows_ico_falls_back_to_decodable_png(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGBA", (64, 64), "lime").save(root / "app_icon.png")
            for corrupt in (False, True):
                with self.subTest(corrupt=corrupt):
                    if corrupt:
                        (root / "app_icon.ico").write_bytes(b"not an icon")
                    with patch("utils.app_icon._asset_directory", return_value=root), patch("utils.app_icon.sys.platform", "win32"):
                        icon = load_application_icon()
                    self.assertFalse(icon.isNull())
                    self.assertEqual(icon.pixmap(32, 32).toImage().pixelColor(16, 16).green(), 255)

    def test_missing_assets_warn_instead_of_silently_using_a_generic_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("utils.app_icon._asset_directory", return_value=Path(directory)):
                with self.assertWarnsRegex(RuntimeWarning, "No readable annotator icon"):
                    self.assertTrue(load_application_icon().isNull())

    def test_windows_identity_checks_hresult(self):
        setter = Mock(return_value=0)
        shell = SimpleNamespace(shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=setter))
        with patch("utils.app_icon.sys.platform", "win32"), patch("utils.app_icon.ctypes.windll", shell, create=True):
            self.assertTrue(configure_windows_app_id())
            setter.assert_called_once_with(APPLICATION_ID)
            setter.return_value = -1
            with self.assertWarnsRegex(RuntimeWarning, "taskbar identity"):
                self.assertFalse(configure_windows_app_id())

    def test_direct_window_and_parentless_warning_use_logo_but_keep_warning_symbol(self):
        window = MainWindow(global_w=1600, global_h=1000)
        message = QtWidgets.QMessageBox()
        try:
            self.assertFalse(window.windowIcon().isNull())
            self.assertEqual(window.windowIcon().cacheKey(), self.app.windowIcon().cacheKey())
            filter_before = self.app._annotator_icon_filter
            configure_qt_application(self.app)
            self.assertIs(self.app._annotator_icon_filter, filter_before)
            message.setIcon(QtWidgets.QMessageBox.Warning)
            message.setWindowIcon(QtGui.QIcon())
            message.setWindowModality(QtCore.Qt.NonModal)
            message.setText("Icon verification")
            # Exercise the show-event filter without entering the Windows
            # offscreen plugin's native QMessageBox rendering path.
            self.app.sendEvent(message, QtCore.QEvent(QtCore.QEvent.Show))
            self.assertEqual(message.windowIcon().cacheKey(), self.app.windowIcon().cacheKey())
            self.assertEqual(message.icon(), QtWidgets.QMessageBox.Warning)
            handle = Mock()
            native_window = SimpleNamespace(setWindowIcon=Mock(), windowHandle=lambda: handle)
            self.app._annotator_icon_filter.apply(native_window)
            handle.setIcon.assert_called_once_with(self.app._annotator_icon_filter.icon)
        finally:
            message.close()
            message.deleteLater()
            self.app.removeEventFilter(window)
            window._bc_timer.stop()
            window.setClean()
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
