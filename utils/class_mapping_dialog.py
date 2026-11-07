"""Optional class setup and an ID-driven replacement for the free-form editor."""

from qtpy import QtCore, QtWidgets
from labelme.widgets import LabelDialog

from utils.class_mapping import load_mapping, mapping_from_rows, save_mapping
from utils.class_name_consistency import numeric_group_id


class ClassMappingDialog(QtWidgets.QDialog):
    def __init__(self, parent, mapping, enabled):
        super().__init__(parent)
        self.setWindowTitle("Class mapping")
        self.resize(480, 420)
        layout = QtWidgets.QVBoxLayout(self)
        help_text = QtWidgets.QLabel(
            "Define class names for this dataset's group IDs.\n"
            "Existing annotations change only when you confirm a label edit.\n"
            "Load the appropriate mapping when changing datasets."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.enabled = QtWidgets.QCheckBox("Use mapping to fill class names from group IDs")
        self.enabled.setChecked(enabled)
        layout.addWidget(self.enabled)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Group ID", "Class name"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        for caption, handler in [("Add row", self.addRow), ("Remove selected", self.removeRows),
                                 ("Load…", self.loadFile), ("Save…", self.saveFile)]:
            button = QtWidgets.QPushButton(caption)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self.apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.result_mapping = dict(mapping)
        self.setRows(mapping)

    def setRows(self, mapping):
        self.table.setRowCount(0)
        for group, label in mapping.items():
            self.addRow(group, label)

    def addRow(self, group=None, label=""):
        # QPushButton.clicked supplies a bool, not a group ID.
        if isinstance(group, bool):
            group = None
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem("" if group is None else str(group)))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(label))

    def removeRows(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def readRows(self):
        return mapping_from_rows([
            tuple(self.table.item(row, col).text().strip() if self.table.item(row, col) else ""
                  for col in range(2)) for row in range(self.table.rowCount())
        ])

    def apply(self):
        try:
            # Disabling remains possible even with an unfinished draft row.
            if self.enabled.isChecked():
                self.result_mapping = self.readRows()
            else:
                try:
                    self.result_mapping = self.readRows()
                except ValueError:
                    pass
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()

    def loadFile(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load class mapping", "", "Class mapping (*.json)")
        if not filename:
            return
        try:
            mapping = load_mapping(filename)
        except (OSError, ValueError) as error:
            self.error.setText(str(error))
            return
        self.setRows(mapping)
        self.enabled.setChecked(True)
        self.error.clear()

    def saveFile(self):
        try:
            mapping = self.readRows()
        except ValueError as error:
            self.error.setText(str(error))
            return
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save class mapping", "", "Class mapping (*.json)")
        if not filename:
            return
        if not filename.lower().endswith(".json"):
            filename += ".json"
        try:
            save_mapping(filename, mapping)
        except (OSError, ValueError) as error:
            self.error.setText(str(error))
            return
        self.error.setText("Mapping file saved. Click Apply to use this setup.")


class MappedLabelDialog(LabelDialog):
    def __init__(self, *args, mapping=None, **kwargs):
        self.mapping = dict(mapping or {})
        super().__init__(*args, **kwargs)
        self.mapping_hint = QtWidgets.QLabel()
        self.mapping_hint.setWordWrap(True)
        self.layout().insertWidget(0, self.mapping_hint)
        if self.mapping:
            self.setWindowTitle("Choose class by group ID")
            self.setMinimumWidth(420)
            self.edit.setReadOnly(True)
            self.edit.setPlaceholderText("Class name (filled from group ID)")
            self.edit_group_id.setPlaceholderText("Class/group ID")
            self.edit.setCompleter(None)
            self.labelList.clear()
            self.labelList.setDragDropMode(QtWidgets.QAbstractItemView.NoDragDrop)
            for group, label in self.mapping.items():
                item = QtWidgets.QListWidgetItem(f"{group}: {label}")
                item.setData(QtCore.Qt.UserRole, group)
                self.labelList.addItem(item)
            self.edit_group_id.textChanged.connect(self.updateMappedLabel)
        else:
            self.mapping_hint.hide()

    def updateMappedLabel(self):
        group = numeric_group_id(self.edit_group_id.text())
        valid = group in self.mapping
        self.edit.setText(self.mapping[group] if valid else "")
        self.mapping_hint.setText("Enter a group ID or select a class below." if valid
                                  else "Choose a group ID defined in the class mapping.")
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(valid)

    def labelSelected(self, item):
        if not self.mapping:
            return super().labelSelected(item)
        if item is not None:
            self.edit_group_id.setText(str(item.data(QtCore.Qt.UserRole)))

    def addLabelHistory(self, label):
        if not self.mapping:
            super().addLabelHistory(label)

    def updateFlags(self, label_new):
        # Mapping a name must not erase flags imported from annotation JSON.
        if not self.mapping:
            super().updateFlags(label_new)

    def validate(self):
        if not self.mapping:
            return super().validate()
        self.updateMappedLabel()
        if numeric_group_id(self.edit_group_id.text()) in self.mapping:
            self.accept()

    def popUp(self, text=None, move=True, flags=None, group_id=None, description=None):
        if not self.mapping:
            return super().popUp(text, move, flags, group_id, description)
        self.editDescription.setPlainText(description or "")
        self.setFlags(flags or {})
        self.labelList.clearSelection()
        self.labelList.setCurrentRow(-1)
        normalized = numeric_group_id(group_id)
        self.edit_group_id.setText("" if group_id is None else str(
            normalized if normalized is not None else group_id))
        self.updateMappedLabel()
        self.edit_group_id.setFocus(QtCore.Qt.PopupFocusReason)
        self.edit_group_id.selectAll()
        if self.exec_() == QtWidgets.QDialog.Accepted:
            group = numeric_group_id(self.edit_group_id.text())
            if group in self.mapping:
                return self.mapping[group], self.getFlags(), group, self.editDescription.toPlainText()
        return None, None, None, None
