"""Flat polygon-list drops: between rows reorder, onto a row requests a merge."""

import uuid

from qtpy import QtCore, QtGui, QtWidgets
from labelme.widgets import LabelListWidget, LabelListWidgetItem
from labelme.widgets.label_list_widget import StandardItemModel


class FlatPolygonModel(StandardItemModel):
    def canDropMimeData(self, data, action, row, column, parent):
        if parent.isValid():
            return False
        return super().canDropMimeData(data, action, row, column, parent)

    def dropMimeData(self, data, action, row, column, parent):
        if parent.isValid():
            return False
        return super().dropMimeData(data, action, row, column, parent)


class PolygonLabelListWidget(LabelListWidget):
    mergeRequested = QtCore.Signal(object, object)
    dropRejected = QtCore.Signal(str)
    MIME_TYPE = "application/x-annotator-flat-polygon-drag"

    def __init__(self):
        super().__init__()
        old_model, old_selection = self.model(), self.selectionModel()
        model = FlatPolygonModel(self)
        prototype = LabelListWidgetItem()
        prototype.setDropEnabled(False)
        model.setItemPrototype(prototype)
        self.setModel(model)
        self.selectionModel().selectionChanged.connect(self.itemSelectionChangedEvent)
        old_selection.deleteLater()
        old_model.deleteLater()
        self.setDropIndicatorShown(False)
        self._dragged_items = []
        self._drag_token = None
        self._drop_hint = None

    def addItem(self, item):
        item.setDropEnabled(False)
        super().addItem(item)

    def startDrag(self, supported_actions):
        items = sorted(self.selectedItems(), key=lambda item: item.row())
        if not items:
            return
        self._dragged_items = items
        self._drag_token = uuid.uuid4().hex
        mime = QtCore.QMimeData()
        mime.setData(self.MIME_TYPE, self._drag_token.encode("ascii"))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        try:
            # Own the drag lifecycle: QAbstractItemView's post-move removal
            # must never remove a source row after our explicit reorder/merge.
            drag.exec_(QtCore.Qt.MoveAction, QtCore.Qt.MoveAction)
        finally:
            self._dragged_items = []
            self._drag_token = None
            self._clearDropHint()

    def _ourDrag(self, event):
        return (event.source() is self and self._drag_token is not None
                and event.mimeData().hasFormat(self.MIME_TYPE)
                and bytes(event.mimeData().data(self.MIME_TYPE)).decode("ascii", errors="ignore") == self._drag_token)

    def _location(self, position):
        if not self.viewport().rect().contains(position):
            return None
        index = self.indexAt(position)
        if not index.isValid():
            return ("insert", len(self))
        rectangle = self.visualRect(index)
        margin = max(4, min(8, rectangle.height() // 4))
        if position.y() < rectangle.top() + margin:
            return ("insert", index.row())
        if position.y() > rectangle.bottom() - margin:
            return ("insert", index.row() + 1)
        return ("merge", index.row())

    def dragEnterEvent(self, event):
        if self._ourDrag(event):
            event.setDropAction(QtCore.Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._ourDrag(event) and self._location(event.pos()) is not None:
            self._drop_hint = self._location(event.pos())
            self.viewport().update()
            event.setDropAction(QtCore.Qt.MoveAction)
            event.accept()
        else:
            self._clearDropHint()
            event.ignore()

    def dragLeaveEvent(self, event):
        self._clearDropHint()
        event.accept()

    def dropEvent(self, event):
        self._clearDropHint()
        if not self._ourDrag(event):
            event.ignore()
            return
        # Ignore the native move first. On-row drops never enter the model's
        # child-row insertion path, even when a merge is cancelled or blocked.
        event.ignore()
        if self.dropItems(self._dragged_items, event.pos()):
            event.setDropAction(QtCore.Qt.MoveAction)
            event.accept()

    def dropItems(self, items, position):
        location = self._location(position)
        try:
            if not items or any(item.model() is not self.model() or item.parent() is not None for item in items):
                return False
        except RuntimeError:
            return False  # A row changed while the drag was active.
        if location is None:
            return False
        kind, row = location
        if kind == "insert":
            return self.reorderItems(items, row)
        target = self[row]
        if target in items:
            return False
        if len(items) != 1:
            self.dropRejected.emit("Drop one annotation onto one other annotation to merge. "
                                   "Reorder multiple entries by dropping between rows.")
            return False
        source_shape, target_shape = items[0].shape(), target.shape()
        self.mergeRequested.emit(source_shape, target_shape)
        return False  # A merge is separate from a native list move.

    def reorderItems(self, items, destination):
        original = list(self)
        selected = sorted(set(items), key=lambda item: item.row())
        if not selected or not 0 <= destination <= len(original):
            return False
        insertion = destination - sum(item.row() < destination for item in selected)
        ordered = [item for item in original if item not in selected]
        ordered[insertion:insertion] = selected
        if ordered == original:
            return False
        selected_before = self.selectedItems()
        model, selection = self.model(), self.selectionModel()
        # Keep structural model notifications for the view's layout/indexes,
        # but do not propagate the temporary empty selection to the canvas.
        selection_block = QtCore.QSignalBlocker(selection)
        rows = {}
        for item in original:
            rows[item] = model.takeRow(0)
        for item in ordered:
            model.appendRow(rows[item])
        for item in selected_before:
            selection.select(model.indexFromItem(item), QtCore.QItemSelectionModel.Select)
        del selection_block
        self.itemSelectionChanged.emit(self.selectedItems(), [])
        model.itemDropped.emit()
        return True

    def _clearDropHint(self):
        self._drop_hint = None
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_hint is None:
            return
        kind, row = self._drop_hint
        painter = QtGui.QPainter(self.viewport())
        painter.setPen(QtGui.QPen(self.palette().highlight().color(), 2))
        if kind == "merge" and row < len(self):
            painter.drawRect(self.visualRect(self.model().index(row, 0)).adjusted(1, 1, -1, -1))
        else:
            y = (self.visualRect(self.model().index(row, 0)).top() if row < len(self)
                 else self.visualRect(self.model().index(len(self) - 1, 0)).bottom() + 1)
            painter.drawLine(0, y, self.viewport().width(), y)
