"""Tracking controls shared with the current annotation editing workflow."""

from qtpy import QtCore, QtWidgets


class TrackingProgressDialog(QtWidgets.QProgressDialog):
    """Do not dismiss an in-flight model operation and expose mutable controls."""

    allow_close = False

    def closeEvent(self, event):
        if self.allow_close:
            super().closeEvent(event)
        else:
            event.ignore()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape and not self.allow_close:
            event.accept()
        else:
            super().keyPressEvent(event)


class VideoPanel(QtWidgets.QGroupBox):
    sequenceRequested = QtCore.Signal(int)
    trackRequested = QtCore.Signal()
    correctionRequested = QtCore.Signal()
    stopRequested = QtCore.Signal()

    def __init__(self, propagate_action, parent=None):
        super().__init__("Video tracking", parent)
        layout = QtWidgets.QVBoxLayout(self)
        self.sequence = QtWidgets.QComboBox()
        self.sequence.currentIndexChanged.connect(self.sequenceRequested)
        layout.addWidget(self.sequence)
        self.backend = QtWidgets.QComboBox()
        self.backend.addItem("Choose tracking backend…", None)
        self.backend.addItem("STCN (optional)", "stcn")
        self.backend.setToolTip("Choose explicitly. STCN has not been benchmarked against SAM 2/3 on your dataset.")
        layout.addWidget(self.backend)
        self.track = QtWidgets.QPushButton("Track selected")
        self.track.setToolTip("Select annotated objects first. STCN loads when needed.")
        self.track.clicked.connect(self.trackRequested)
        layout.addWidget(self.track)
        self.propagate = QtWidgets.QToolButton()
        self.propagate.setDefaultAction(propagate_action)
        self.propagate.setText("Propagate frame (Space)")
        self.propagate.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.propagate.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.propagate)
        row = QtWidgets.QHBoxLayout()
        self.correction = QtWidgets.QPushButton("Use correction")
        self.correction.clicked.connect(self.correctionRequested)
        self.stop = QtWidgets.QPushButton("Stop tracking")
        self.stop.clicked.connect(self.stopRequested)
        row.addWidget(self.correction)
        row.addWidget(self.stop)
        layout.addLayout(row)
        self.status = QtWidgets.QLabel("Annotate → select objects → Track selected → PgDown → Propagate.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.set_running(False)
        self.track.setEnabled(False)

    def set_running(self, running, message=None):
        self.correction.setEnabled(running)
        self.stop.setEnabled(running)
        self.backend.setEnabled(not running)
        if message:
            self.status.setText(message)
