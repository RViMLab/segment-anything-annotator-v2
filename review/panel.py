from __future__ import annotations

import time

from qtpy import QtCore, QtWidgets

from .models import ReviewStatus, SourceProvenance


class ReviewPanel(QtWidgets.QWidget):
    """Controls and live state for one annotation review session."""

    decisionRequested = QtCore.Signal(object)
    previousRequested = QtCore.Signal()
    nextRequested = QtCore.Signal()
    finishRequested = QtCore.Signal()
    resetTimerRequested = QtCore.Signal()
    exportRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stored_seconds = 0.0
        self._running_since = None

        layout = QtWidgets.QVBoxLayout(self)
        self.reviewer_label = QtWidgets.QLabel("")
        self.reviewer_label.setWordWrap(True)
        self.progress_label = QtWidgets.QLabel("Reviewed 0 / 0")
        self.progress_label.setStyleSheet("font-weight: bold;")
        self.item_label = QtWidgets.QLabel("No review item loaded")
        self.item_label.setWordWrap(True)
        layout.addWidget(self.reviewer_label)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.item_label)

        timer_row = QtWidgets.QHBoxLayout()
        self.timer_label = QtWidgets.QLabel("00:00")
        self.timer_label.setStyleSheet("font-size: 13pt; font-weight: bold;")
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_timer)
        self.reset_timer_button = QtWidgets.QPushButton("Reset timer")
        self.reset_timer_button.clicked.connect(self.resetTimerRequested)
        timer_row.addWidget(QtWidgets.QLabel("Active:"))
        timer_row.addWidget(self.timer_label)
        timer_row.addStretch()
        layout.addLayout(timer_row)
        timer_buttons = QtWidgets.QHBoxLayout()
        timer_buttons.addWidget(self.pause_button)
        timer_buttons.addWidget(self.reset_timer_button)
        layout.addLayout(timer_buttons)

        decision_label = QtWidgets.QLabel("Decision (save and next)")
        decision_label.setWordWrap(True)
        layout.addWidget(decision_label)
        decisions = (
            ("No change", ReviewStatus.NO_CHANGE),
            ("Minor correction", ReviewStatus.MINOR_CORRECTION),
            ("Major correction", ReviewStatus.MAJOR_CORRECTION),
            ("Unable to review", ReviewStatus.UNABLE_TO_REVIEW),
        )
        self.decision_buttons = []
        for text, status in decisions:
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, value=status:
                self.decisionRequested.emit(value)
            )
            button.setMinimumHeight(34)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Ignored,
                QtWidgets.QSizePolicy.Fixed,
            )
            self.decision_buttons.append(button)
            layout.addWidget(button)

        provenance_label = QtWidgets.QLabel("Annotation provenance")
        provenance_label.setWordWrap(True)
        layout.addWidget(provenance_label)
        self.provenance_combo = QtWidgets.QComboBox()
        self.provenance_combo.addItem(
            "Unknown / legacy", SourceProvenance.UNKNOWN.value
        )
        self.provenance_combo.addItem(
            "Manual keyframe", SourceProvenance.MANUAL_KEYFRAME.value
        )
        self.provenance_combo.addItem(
            "SAM2 propagated frame",
            SourceProvenance.SAM2_PROPAGATED_FRAME.value,
        )
        self.provenance_combo.addItem(
            "Reviewed propagated frame",
            SourceProvenance.REVIEWED_PROPAGATED_FRAME.value,
        )
        layout.addWidget(self.provenance_combo)

        problem_label = QtWidgets.QLabel("Problem / validation status")
        problem_label.setWordWrap(True)
        layout.addWidget(problem_label)
        self.problem_combo = QtWidgets.QComboBox()
        self.problem_combo.setEditable(True)
        self.problem_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,
            QtWidgets.QSizePolicy.Fixed,
        )
        self.problem_combo.addItems(("", "Needs discussion", "Invalid annotation", "Image issue"))
        layout.addWidget(self.problem_combo)

        layout.addWidget(QtWidgets.QLabel("Optional notes"))
        self.notes_edit = QtWidgets.QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Add reviewer notes…")
        self.notes_edit.setMaximumHeight(75)
        layout.addWidget(self.notes_edit)

        nav = QtWidgets.QHBoxLayout()
        previous_button = QtWidgets.QPushButton("Previous target")
        next_button = QtWidgets.QPushButton("Next target")
        previous_button.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,
            QtWidgets.QSizePolicy.Fixed,
        )
        next_button.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,
            QtWidgets.QSizePolicy.Fixed,
        )
        previous_button.clicked.connect(self.previousRequested)
        next_button.clicked.connect(self.nextRequested)
        nav.addWidget(previous_button)
        nav.addWidget(next_button)
        layout.addLayout(nav)

        self.finish_button = QtWidgets.QPushButton("Finish review session")
        self.finish_button.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,
            QtWidgets.QSizePolicy.Fixed,
        )
        self.finish_button.clicked.connect(self.finishRequested)
        layout.addWidget(self.finish_button)
        self.export_button = QtWidgets.QPushButton("Export review CSV")
        self.export_button.clicked.connect(self.exportRequested)
        layout.addWidget(self.export_button)
        layout.addStretch()

        self._display_timer = QtCore.QTimer(self)
        self._display_timer.setInterval(250)
        self._display_timer.timeout.connect(self._update_timer_label)

    def set_item(self, item, reviewed_count, total_count):
        self.stop_timer()
        self._set_review_controls_enabled(True)
        self._stored_seconds = item.active_review_seconds
        self.item_label.setText(
            f"Target {item.ordinal + 1} / {total_count}\n"
            f"{item.relative_key}\nStatus: {item.status.value.replace('_', ' ')}"
        )
        self.progress_label.setText(
            f"Reviewed {reviewed_count} / {total_count}"
        )
        self.notes_edit.setPlainText(item.reviewer_notes)
        self.problem_combo.setCurrentText(item.problem_status)
        provenance_index = self.provenance_combo.findData(
            item.source_provenance
        )
        self.provenance_combo.setCurrentIndex(max(0, provenance_index))
        self.start_timer()

    def set_reviewer(self, reviewer_id, reviewer_role):
        role = f" — {reviewer_role}" if reviewer_role else ""
        self.reviewer_label.setText(f"Reviewer: {reviewer_id}{role}")

    def set_progress(self, reviewed_count, total_count):
        self.progress_label.setText(
            f"Reviewed {reviewed_count} / {total_count}"
        )

    def start_timer(self):
        if self._running_since is None:
            self._running_since = time.monotonic()
        self.pause_button.setText("Pause")
        self._display_timer.start()
        self._update_timer_label()

    def reset_timer(self):
        self._stored_seconds = 0.0
        self._running_since = time.monotonic()
        self._update_timer_label()

    def set_context(self, image_number, image_count, reviewed_count, target_count):
        self.stop_timer()
        self.item_label.setText(
            f"Context image {image_number} / {image_count}\n"
            "No matched annotation — view only"
        )
        self.set_progress(reviewed_count, target_count)
        self.notes_edit.setEnabled(False)
        self.problem_combo.setEnabled(False)
        self.provenance_combo.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.reset_timer_button.setEnabled(False)
        for button in self.decision_buttons:
            button.setEnabled(False)

    def _set_review_controls_enabled(self, enabled):
        self.notes_edit.setEnabled(enabled)
        self.problem_combo.setEnabled(enabled)
        self.provenance_combo.setEnabled(enabled)
        self.pause_button.setEnabled(enabled)
        self.reset_timer_button.setEnabled(enabled)
        for button in self.decision_buttons:
            button.setEnabled(enabled)

    def stop_timer(self):
        if self._running_since is not None:
            self._stored_seconds += time.monotonic() - self._running_since
            self._running_since = None
        self._display_timer.stop()
        self.pause_button.setText("Resume")
        self._update_timer_label()

    def toggle_timer(self):
        if self._running_since is None:
            self.start_timer()
        else:
            self.stop_timer()

    def elapsed_seconds(self):
        elapsed = self._stored_seconds
        if self._running_since is not None:
            elapsed += time.monotonic() - self._running_since
        return elapsed

    def _update_timer_label(self):
        seconds = int(self.elapsed_seconds())
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            text = f"{minutes:02d}:{seconds:02d}"
        self.timer_label.setText(text)
