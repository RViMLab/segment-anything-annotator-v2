"""A proposal card with a dedicated, readable numeric caption."""

from qtpy import QtCore, QtGui, QtWidgets


class ProposalButton(QtWidgets.QPushButton):
    def captionFont(self):
        font = QtGui.QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(14.0, min(22.0, self.height() / 8.0)))
        return font

    def captionRect(self):
        area = self.contentsRect().adjusted(8, 6, -8, -6)
        metrics = QtGui.QFontMetrics(self.captionFont())
        width = max(48, metrics.horizontalAdvance(self.text()) + 24)
        return QtCore.QRect(area.right() - width + 1, area.top(), width, area.height())

    def previewRect(self):
        area = self.contentsRect().adjusted(8, 6, -8, -6)
        return QtCore.QRect(area.left(), area.top(),
                            max(1, self.captionRect().left() - area.left() - 12),
                            max(1, area.height()))

    def paintEvent(self, event):
        painter = QtWidgets.QStylePainter(self)
        option = QtWidgets.QStyleOptionButton()
        self.initStyleOption(option)
        # Keep the native button frame/hover/focus states. Draw the preview
        # and caption ourselves so style-specific icon spacing cannot crowd it.
        option.text = ""
        option.icon = QtGui.QIcon()
        painter.drawControl(QtWidgets.QStyle.CE_PushButton, option)
        if not self.icon().isNull():
            mode = QtGui.QIcon.Normal if self.isEnabled() else QtGui.QIcon.Disabled
            pixmap = self.icon().pixmap(self.iconSize(), mode)
            area = self.previewRect()
            ratio = pixmap.devicePixelRatioF()
            painter.drawPixmap(QtCore.QPointF(
                area.x() + (area.width() - pixmap.width() / ratio) / 2,
                area.y() + (area.height() - pixmap.height() / ratio) / 2,
            ), pixmap)
        painter.setFont(self.captionFont())
        group = QtGui.QPalette.Active if self.isEnabled() else QtGui.QPalette.Disabled
        painter.setPen(self.palette().color(group, QtGui.QPalette.ButtonText))
        painter.drawText(self.captionRect(), QtCore.Qt.AlignCenter, self.text())
