"""Shared application identity and icon helpers."""

from __future__ import annotations

import ctypes
import sys
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


def configure_windows_app_id() -> None:
    """Give Windows a stable taskbar identity before QApplication starts."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APPLICATION_ID
        )
    except (AttributeError, OSError):
        # The icon still works in the window if the shell API is unavailable.
        pass


def configure_qt_application(application) -> None:
    """Apply shared metadata and the icon to a QApplication instance."""
    from PyQt5.QtGui import QIcon

    application.setApplicationName(APPLICATION_NAME)
    application.setOrganizationName(ORGANIZATION_NAME)
    icon_path = application_icon_path()
    if icon_path.is_file():
        application.setWindowIcon(QIcon(str(icon_path)))
