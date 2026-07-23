from __future__ import annotations

from pathlib import Path
from typing import Optional

from qtpy import QtWidgets

from .models import ReviewConfig, ValidationReport
from .validation import validate_review_config


class ReviewSessionDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent=None,
        initial_config: Optional[ReviewConfig] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Configure annotation review session")
        self.resize(760, 520)
        self.validation_report: Optional[ValidationReport] = None

        self.reviewer_id_edit = QtWidgets.QLineEdit()
        self.reviewer_role_edit = QtWidgets.QLineEdit()
        self.image_directory_edit = QtWidgets.QLineEdit()
        self.annotation_directory_edit = QtWidgets.QLineEdit()
        self.output_directory_edit = QtWidgets.QLineEdit()

        form = QtWidgets.QFormLayout()
        form.addRow("Reviewer ID *", self.reviewer_id_edit)
        form.addRow("Reviewer role", self.reviewer_role_edit)
        form.addRow(
            "Image directory *",
            self._directory_field(self.image_directory_edit),
        )
        form.addRow(
            "Original annotation directory *",
            self._directory_field(self.annotation_directory_edit),
        )
        form.addRow(
            "Reviewed annotation output *",
            self._directory_field(self.output_directory_edit),
        )

        notice = QtWidgets.QLabel(
            "Original annotations are read-only inputs. Reviewed annotations "
            "must be written to a separate directory."
        )
        notice.setWordWrap(True)

        self.report_view = QtWidgets.QPlainTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setPlaceholderText(
            "Select the session paths, then click Validate."
        )

        self.validate_button = QtWidgets.QPushButton("Validate")
        self.validate_button.clicked.connect(self.validate_configuration)
        self.start_button = QtWidgets.QPushButton("Start review")
        self.start_button.clicked.connect(self._accept_if_valid)
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.validate_button)
        buttons.addStretch(1)
        buttons.addWidget(self.start_button)
        buttons.addWidget(cancel_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addLayout(form)
        layout.addWidget(QtWidgets.QLabel("Validation summary"))
        layout.addWidget(self.report_view, 1)
        layout.addLayout(buttons)

        if initial_config is not None:
            self._set_initial_config(initial_config)

    def _directory_field(self, line_edit):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        browse_button = QtWidgets.QPushButton("Browse…")
        browse_button.clicked.connect(
            lambda: self._browse_directory(line_edit)
        )
        line_edit.textChanged.connect(self._clear_validation)
        layout.addWidget(line_edit, 1)
        layout.addWidget(browse_button)
        return widget

    def _browse_directory(self, line_edit):
        start_directory = line_edit.text().strip() or "."
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose directory",
            start_directory,
        )
        if directory:
            line_edit.setText(directory)

    def _set_initial_config(self, config):
        self.reviewer_id_edit.setText(config.reviewer_id)
        self.reviewer_role_edit.setText(config.reviewer_role)
        self.image_directory_edit.setText(str(config.image_directory))
        self.annotation_directory_edit.setText(
            str(config.annotation_directory)
        )
        self.output_directory_edit.setText(str(config.output_directory))

    def _clear_validation(self):
        self.validation_report = None

    def config(self) -> ReviewConfig:
        return ReviewConfig(
            reviewer_id=self.reviewer_id_edit.text(),
            reviewer_role=self.reviewer_role_edit.text(),
            image_directory=Path(self.image_directory_edit.text() or "."),
            annotation_directory=Path(
                self.annotation_directory_edit.text() or "."
            ),
            output_directory=Path(self.output_directory_edit.text() or "."),
        )

    def validate_configuration(self) -> ValidationReport:
        self.validation_report = validate_review_config(self.config())
        self.report_view.setPlainText(self.validation_report.summary())
        return self.validation_report

    def _accept_if_valid(self):
        report = self.validate_configuration()
        if not report.is_valid:
            QtWidgets.QMessageBox.warning(
                self,
                "Review session is not valid",
                "Resolve the validation errors before starting review.",
            )
            return
        if report.warnings:
            warning_text = "\n".join(
                issue.display_text() for issue in report.warnings[:10]
            )
            remaining = len(report.warnings) - 10
            if remaining > 0:
                warning_text += f"\n... and {remaining} more warning(s)"
            response = QtWidgets.QMessageBox.question(
                self,
                "Continue with validation warnings?",
                (
                    f"{len(report.warnings)} warning(s) were found:\n\n"
                    f"{warning_text}\n\n"
                    "Only matched, valid image/annotation pairs will be loaded. "
                    "Continue?"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if response != QtWidgets.QMessageBox.Yes:
                return
        self.accept()
