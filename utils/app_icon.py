"""Shared application identity and icon helpers."""

from __future__ import annotations

import ctypes
import sys
import warnings
from pathlib import Path


APPLICATION_ID = "RViMLab.SegmentAnythingAnnotator"
APPLICATION_NAME = "Segment Anything Annotator"
ORGANIZATION_NAME = "RViMLab"


def _asset_directory() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def application_icon_path() -> Path:
    """Return the preferred icon file for the current platform."""
    assets = _asset_directory()
    preferred = "app_icon.ico" if sys.platform == "win32" else "app_icon.png"
    path = assets / preferred
    if path.is_file():
        return path
    return assets / "app_icon.png"


def load_application_icon():
    """Decode an actual usable icon, falling back when a preferred file is bad."""
    from PyQt5.QtGui import QIcon

    names = ("app_icon.ico", "app_icon.png") if sys.platform == "win32" else ("app_icon.png", "app_icon.ico")
    assets = _asset_directory()
    for name in (*names, "SAMAnnLogo.png"):
        path = assets / name
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull() and not icon.pixmap(32, 32).isNull():
                return icon
    warnings.warn(f"No readable annotator icon found in {assets}. Restore the app icon assets.", RuntimeWarning)
    return QIcon()


def configure_windows_app_id() -> bool:
    """Give Windows a stable taskbar identity before QApplication starts."""
    if sys.platform != "win32":
        return True
    try:
        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        result = setter(APPLICATION_ID)
        if result != 0:
            raise OSError(f"Windows returned HRESULT 0x{result & 0xffffffff:08x}")
        return True
    except (AttributeError, OSError) as error:
        warnings.warn(f"Could not set the annotator taskbar identity: {error}", RuntimeWarning)
        return False


def configure_qt_application(application) -> None:
    """Apply shared metadata and the icon to a QApplication instance."""
    from PyQt5.QtCore import QEvent, QObject
    from PyQt5.QtWidgets import QWidget

    application.setApplicationName(APPLICATION_NAME)
    application.setOrganizationName(ORGANIZATION_NAME)
    icon = load_application_icon()
    if icon.isNull():
        return
    application.setWindowIcon(icon)

    class WindowIconFilter(QObject):
        def apply(self, window):
            window.setWindowIcon(self.icon)
            handle = window.windowHandle()
            if handle is not None:
                handle.setIcon(self.icon)

        def eventFilter(self, watched, event):
            if event.type() == QEvent.Show and isinstance(watched, QWidget) and watched.isWindow():
                self.apply(watched)
            return False

    icon_filter = getattr(application, "_annotator_icon_filter", None)
    if icon_filter is None:
        icon_filter = WindowIconFilter(application)
        application._annotator_icon_filter = icon_filter
        application.installEventFilter(icon_filter)
    icon_filter.icon = icon
    for window in application.topLevelWidgets():
        icon_filter.apply(window)
