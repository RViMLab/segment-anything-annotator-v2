"""Review-mode shortcut definitions and focus guards."""

from qtpy import QtWidgets

from .models import ReviewStatus


DECISION_SHORTCUTS = (
    ("K", ReviewStatus.NO_CHANGE),
    ("M", ReviewStatus.MINOR_CORRECTION),
    ("L", ReviewStatus.MAJOR_CORRECTION),
    ("O", ReviewStatus.UNABLE_TO_REVIEW),
)

EDITABLE_WIDGET_TYPES = (
    QtWidgets.QLineEdit,
    QtWidgets.QTextEdit,
    QtWidgets.QPlainTextEdit,
    QtWidgets.QComboBox,
    QtWidgets.QAbstractSpinBox,
)


def is_editable_focus(widget):
    return isinstance(widget, EDITABLE_WIDGET_TYPES)
