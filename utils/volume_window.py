"""A small NIfTI mode using the existing per-image annotation editor."""

import json
from copy import deepcopy
from pathlib import Path

from qtpy import QtWidgets

from utils.medical_volume import NiftiVolume


class VolumeWindowMixin:
    def _setupVolumePanel(self, layout):
        self.volume = None
        self.volume_panel = QtWidgets.QGroupBox("NIfTI volume — native slices")
        box = QtWidgets.QVBoxLayout(self.volume_panel)
        self.volume_info = QtWidgets.QLabel()
        self.volume_info.setWordWrap(True)
        self.volume_info.setMinimumHeight(self.volume_info.fontMetrics().lineSpacing() * 5)
        box.addWidget(self.volume_info)
        form = QtWidgets.QFormLayout()
        self.volume_center = QtWidgets.QDoubleSpinBox()
        self.volume_width = QtWidgets.QDoubleSpinBox()
        for widget in (self.volume_center, self.volume_width):
            widget.setDecimals(9)
            widget.setRange(-1e100, 1e100)
        self.volume_width.setMinimum(1e-9)
        form.addRow("Window centre", self.volume_center)
        form.addRow("Window width", self.volume_width)
        box.addLayout(form)
        apply = QtWidgets.QPushButton("Apply display window")
        apply.clicked.connect(self.applyVolumeWindow)
        box.addWidget(apply)
        export = QtWidgets.QPushButton("Export NIfTI mask…")
        export.clicked.connect(self.exportVolumeMask)
        box.addWidget(export)
        layout.addWidget(self.volume_panel)
        self.volume_panel.hide()

    def _volumeError(self, error):
        QtWidgets.QMessageBox.warning(self, "Volume operation not applied", str(error))
        return False

    def clickVolumeChoose(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open scalar 3D NIfTI volume", "", "NIfTI volumes (*.nii *.nii.gz)")
        return self.openVolume(filename) if filename else False

    def openVolume(self, filename):
        if self.review_config is not None:
            return self._volumeError("Native volume review is not included in this first implementation.")
        volume = None
        try:
            def prepare():
                source = NiftiVolume(filename)
                try:
                    source.use_render(source.render())
                    return source
                except Exception:
                    source.close()
                    raise
            volume = self._runVideoTask("Preparing native NIfTI slices…", prepare)
            first = Path(self.current_output_dir) / volume.folder_name / "slice_00000.json"
            if first.is_file():
                volume.validate_annotation(json.loads(first.read_text(encoding="utf-8")), 0)
            if not self._canLeaveVideoFrame():
                volume.close()
                return False
        except Exception as error:
            if volume is not None:
                volume.close()
            return self._volumeError(error)
        self.leaveVideoMode()
        self.leaveVolumeMode()
        self.volume = volume
        self.img_list, self.img_len = volume.paths, volume.shape[2]
        self.current_img_index, self.current_img = 0, volume.paths[0]
        self.img_progress_bar.setRange(0, self.img_len - 1)
        self.volume_center.setValue((volume.low + volume.high) / 2)
        self.volume_width.setValue(volume.high - volume.low)
        self.volume_panel.show()
        self.video_panel.set_volume_mode(True)
        self.video_panel.show()
        self.video_panel.track.setEnabled(True)
        self.video_panel.status.setText("Select reference objects, choose STCN and a direction, then Track selected.")
        self.button_last.setText("Previous slice (PgUp)")
        self.button_next.setText("Next slice (PgDown)")
        self.setWindowTitle(f"segment-anything-annotator — NIfTI: {volume.path.name}")
        return self.loadImg()

    def leaveVolumeMode(self):
        if getattr(self, "volume", None) is not None:
            self.stopVideoTracking()
            self.volume.close()
            self.volume = None
            self.volume_panel.hide()
            self.video_panel.set_volume_mode(False)
            self.video_panel.hide()
            self.video_panel.track.setEnabled(False)
            self._video_frame_metadata = None
            self._video_metadata_history = {}
            self._tracking_backup_metadata = {}
            self._tracking_undo_metadata = None

    def _volumeSliceLoaded(self):
        if self.volume is None:
            return
        index, volume = self.current_img_index, self.volume
        axes = "/".join(str(code) for code in volume.axis_codes)
        self.volume_info.setText(f"{volume.path.name}\nSlice {index + 1}/{volume.shape[2]} (index {index})\n"
                                 f"Native axis 2; voxel axes {axes}\nNo rotation or resampling")
        self.img_name.setText(f"{volume.path.name} — slice {index + 1}/{volume.shape[2]}")

    def _validateVolumeSlice(self, image):
        if getattr(self, "volume", None) is None:
            return True
        path = Path(self._frameAnnotationPath(image))
        try:
            if path.is_file():
                self.volume.validate_annotation(json.loads(path.read_text(encoding="utf-8")), self.current_img_index)
            return True
        except Exception as error:
            previous = getattr(self, "_loaded_image", None)
            if previous is not None:
                self.current_img, self.current_img_index = previous
            return self._volumeError(error)

    def applyVolumeWindow(self):
        if self.volume is None or not self._canLeaveVideoFrame():
            return False
        center, width = self.volume_center.value(), self.volume_width.value()
        try:
            rendered = self._runVideoTask("Updating NIfTI display slices…",
                                          lambda: self.volume.render(center - width / 2, center + width / 2))
        except Exception as error:
            return self._volumeError(error)
        self.stopVideoTracking()
        self.volume.use_render(rendered)
        self.img_list = self.volume.paths
        self.current_img = self.img_list[self.current_img_index]
        backups = deepcopy(self.canvas.shapesBackups)
        loaded = self.loadImg()
        if loaded:
            self.canvas.shapesBackups = backups
            self.actions.undo.setEnabled(self.canvas.isShapeRestorable)
            self.video_panel.status.setText("Display window applied. Select objects and initialize tracking again.")
        return loaded

    def exportVolumeMask(self):
        if self.volume is None or not self._canLeaveVideoFrame():
            return False
        annotation_dir = Path(self.current_output_dir) / self.volume.folder_name
        missing = sum(not (annotation_dir / f"slice_{i:05}.json").is_file() for i in range(self.img_len))
        if missing and QtWidgets.QMessageBox.question(
                self, "Unannotated slices",
                f"{missing} of {self.img_len} slices have no saved annotations. Their exported voxels will be zero, "
                "but the sidecar will mark them as unannotated, not confirmed background. Continue?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel) != QtWidgets.QMessageBox.Yes:
            return False
        parent = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose parent folder for a new mask export", self.current_output_dir)
        if not parent:
            return False
        try:
            published = self._runVideoTask("Exporting aligned NIfTI mask…",
                                           lambda: self.volume.export(annotation_dir, parent))
        except Exception as error:
            return self._volumeError(error)
        QtWidgets.QMessageBox.information(self, "NIfTI mask exported",
                                          f"Saved a new export bundle:\n{published}\n\n"
                                          "segmentation.nii.gz and segmentation.json\n"
                                          "Mask values are group ID + 1; zero is background/unannotated. "
                                          "Use the JSON mapping to interpret the mask.")
        return True
