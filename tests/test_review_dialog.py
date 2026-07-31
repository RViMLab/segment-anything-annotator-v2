import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy import QtCore, QtWidgets  # noqa: E402

from review.dialog import ReviewSessionDialog  # noqa: E402


class ReviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance()
        if cls.application is None:
            cls.application = QtWidgets.QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temporary_directory.name) / "settings.ini"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def settings(self):
        return QtCore.QSettings(
            str(self.settings_path), QtCore.QSettings.IniFormat
        )

    def test_reviewer_role_is_remembered_and_can_be_cleared(self):
        first = ReviewSessionDialog(settings=self.settings())
        first.reviewer_role_edit.setText("trained primary annotator")
        first.remember_reviewer_role()

        second = ReviewSessionDialog(settings=self.settings())
        self.assertEqual(
            second.reviewer_role_edit.text(),
            "trained primary annotator",
        )
        second.reviewer_role_edit.clear()
        second.remember_reviewer_role()

        third = ReviewSessionDialog(settings=self.settings())
        self.assertEqual(third.reviewer_role_edit.text(), "")


if __name__ == "__main__":
    unittest.main()
