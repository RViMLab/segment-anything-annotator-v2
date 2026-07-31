import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy import QtCore, QtWidgets  # noqa: E402

from review import (  # noqa: E402
    DECISION_SHORTCUTS,
    ReviewStatus,
    is_editable_focus,
)
from review.panel import ReviewPanel  # noqa: E402


class ReviewShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance()
        if cls.application is None:
            cls.application = QtWidgets.QApplication([])

    def test_decision_shortcut_mapping(self):
        self.assertEqual(
            dict(DECISION_SHORTCUTS),
            {
                "K": ReviewStatus.NO_CHANGE,
                "M": ReviewStatus.MINOR_CORRECTION,
                "L": ReviewStatus.MAJOR_CORRECTION,
                "O": ReviewStatus.UNABLE_TO_REVIEW,
            },
        )

    def test_editable_focus_guard(self):
        for widget in (
            QtWidgets.QLineEdit(),
            QtWidgets.QPlainTextEdit(),
            QtWidgets.QTextEdit(),
            QtWidgets.QComboBox(),
            QtWidgets.QSpinBox(),
        ):
            self.assertTrue(is_editable_focus(widget))
        self.assertFalse(is_editable_focus(QtWidgets.QPushButton()))

    def test_panel_decisions_share_one_signal_and_respect_disabled_state(self):
        panel = ReviewPanel()
        received = []
        panel.decisionRequested.connect(received.append)

        panel.request_decision(ReviewStatus.MINOR_CORRECTION)
        self.assertEqual(received, [ReviewStatus.MINOR_CORRECTION])

        panel.decision_button_by_status[
            ReviewStatus.MINOR_CORRECTION
        ].setEnabled(False)
        panel.request_decision(ReviewStatus.MINOR_CORRECTION)
        self.assertEqual(received, [ReviewStatus.MINOR_CORRECTION])

    def test_last_decision_highlight_moves_without_focus(self):
        panel = ReviewPanel()
        panel.highlight_decision(ReviewStatus.NO_CHANGE)
        no_change = panel.decision_button_by_status[ReviewStatus.NO_CHANGE]
        major = panel.decision_button_by_status[
            ReviewStatus.MAJOR_CORRECTION
        ]
        self.assertIn("background", no_change.styleSheet())
        panel.highlight_decision(ReviewStatus.MAJOR_CORRECTION)
        self.assertEqual(no_change.styleSheet(), "")
        self.assertIn("background", major.styleSheet())
        self.assertEqual(major.focusPolicy(), QtCore.Qt.NoFocus)


if __name__ == "__main__":
    unittest.main()
