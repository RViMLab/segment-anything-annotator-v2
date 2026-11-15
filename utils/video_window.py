"""Video workflow mixed into the normal annotator, using its save/edit/undo gates."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import json

import numpy as np
import cv2
from qtpy import QtCore, QtWidgets

from utils.annotation_document import shape_to_annotation
from utils.class_name_consistency import numeric_group_id
from utils.geometry_operations import exact_mask_polygons
from utils.video_panel import TrackingProgressDialog, VideoPanel
from utils.video_tracking import StcnTracker, VideoTrackingError, discover_sequences


class VideoWindowMixin:
    def _initVideoState(self, max_size):
        self.video_mode = False
        self.video_sequences = ()
        self.video_sequence_index = 0
        self.video_tracker = None
        self.video_objects = []
        self.max_size_stcn = int(max_size)
        self._video_frame_metadata = None
        self._video_metadata_history = {}

    def _setupVideoPanel(self, layout):
        self.video_panel = VideoPanel(self.actions.propagateVideo, self)
        self.video_panel.sequenceRequested.connect(self.switchVideoSequence)
        self.video_panel.trackRequested.connect(self.trackVideoSelection)
        self.video_panel.correctionRequested.connect(self.useVideoCorrection)
        self.video_panel.stopRequested.connect(self.stopVideoTracking)
        layout.addWidget(self.video_panel)
        self.video_panel.hide()
        self.addAction(self.actions.propagateVideo)

    def _frameAnnotationPath(self, image, sequence=None):
        folder = Path(self.current_output_dir)
        if self.video_mode and self.video_sequences:
            sequence = sequence or self.video_sequences[self.video_sequence_index]
            folder /= sequence.name
        return str(folder / (Path(image).stem + ".json"))

    def _canLeaveVideoFrame(self):
        if self.actions.save.isEnabled():
            return self.saveFile()
        return not self.current_img or self._checkClassNameConsistency(self.current_output_filename)

    def clickVideoChoose(self):
        if self.review_config is not None:
            return False
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose video frames or sequence parent", ".")
        return self.openVideoDirectory(directory) if directory else False

    def openVideoDirectory(self, directory):
        if self.review_config is not None:
            return False
        try:
            sequences = discover_sequences(directory)
            if cv2.imread(str(sequences[0].frames[0])) is None:
                raise VideoTrackingError("The first frame cannot be read. Choose a valid sequence.")
        except (OSError, ValueError) as error:
            self._videoError(error)
            return False
        if not self._canLeaveVideoFrame():
            return False
        self.stopVideoTracking()
        self.video_mode = True
        self.video_sequences = sequences
        self.video_sequence_index = 0
        blocker = QtCore.QSignalBlocker(self.video_panel.sequence)
        self.video_panel.sequence.clear()
        for sequence in sequences:
            self.video_panel.sequence.addItem(sequence.name)
        self.video_panel.sequence.setCurrentIndex(0)
        del blocker
        self.video_panel.show()
        self._activateVideoSequence(0)
        return True

    def _activateVideoSequence(self, index):
        sequence = self.video_sequences[index]
        self.video_sequence_index = index
        self.img_list = [str(path) for path in sequence.frames]
        self.img_len = len(self.img_list)
        self.current_img_index = 0
        self.current_img = self.img_list[0]
        self.img_progress_bar.setMinimum(0)
        self.img_progress_bar.setMaximum(self.img_len - 1)
        self.button_last.setText("Previous frame (PgUp)")
        self.button_next.setText("Next frame (PgDown)")
        self.setWindowTitle(f"segment-anything-annotator — Video: {sequence.name}")
        self.loadImg()
        self.video_panel.track.setEnabled(True)

    def switchVideoSequence(self, index):
        if not self.video_mode or not 0 <= index < len(self.video_sequences) or index == self.video_sequence_index:
            return
        readable = cv2.imread(str(self.video_sequences[index].frames[0])) is not None
        if not readable:
            self._videoError("The selected sequence's first frame cannot be read. The current sequence was kept.")
        if not readable or not self._canLeaveVideoFrame():
            blocker = QtCore.QSignalBlocker(self.video_panel.sequence)
            self.video_panel.sequence.setCurrentIndex(self.video_sequence_index)
            del blocker
            return
        self.stopVideoTracking()
        self._activateVideoSequence(index)

    def leaveVideoMode(self):
        self.stopVideoTracking()
        self.video_mode = False
        self.video_sequences = ()
        self._video_frame_metadata = None
        self.video_panel.hide()
        self.video_panel.track.setEnabled(False)
        self.button_last.setText("Last Image")
        self.button_next.setText("Next Image")
        self.setWindowTitle("segment-anything-annotator")

    def stopVideoTracking(self):
        self.video_tracker = None
        self.video_objects = []
        if hasattr(self, "video_panel"):
            self.video_panel.set_running(False, "Select annotated objects, choose a backend, then Track selected.")
            self.actions.propagateVideo.setEnabled(False)

    def _videoError(self, error):
        QtWidgets.QMessageBox.warning(self, "Video tracking not applied", str(error) + "\n\nAnnotations were not changed.")

    def _runVideoTask(self, message, operation):
        # Native inference runs off the UI thread. Keep controls modal until it
        # completes so no other action changes its frame/model beneath it.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-tracking") as executor:
            future = executor.submit(operation)
            progress = TrackingProgressDialog(message, None, 0, 0, self)
            progress.setWindowModality(QtCore.Qt.ApplicationModal)
            progress.setCancelButton(None)
            progress.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
            loop = QtCore.QEventLoop(self)
            timer = QtCore.QTimer(progress)
            timer.timeout.connect(lambda: loop.quit() if future.done() else None)
            timer.start(25)
            progress.show()
            try:
                if not future.done():
                    loop.exec_()
                return future.result()
            finally:
                timer.stop()
                progress.allow_close = True
                progress.close()
                progress.deleteLater()
                loop.deleteLater()

    def _makeVideoTracker(self):
        import torch
        device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        return StcnTracker(Path(__file__).resolve().parents[1], self.max_size_stcn, device)

    @staticmethod
    def _trackingMetadata(shape):
        metadata = shape_to_annotation(shape)
        metadata.pop("points", None)
        metadata.pop("video_object_id", None)
        metadata.setdefault("description", "")
        metadata.setdefault("flags", {})
        return metadata

    def _videoStateKey(self):
        return json.dumps([shape_to_annotation(s) for s in self.canvas.shapes], sort_keys=True)

    def _rememberVideoMetadata(self):
        self._video_metadata_history[self._videoStateKey()] = deepcopy(self._video_frame_metadata)
        if len(self._video_metadata_history) > 64:
            self._video_metadata_history.pop(next(iter(self._video_metadata_history)))

    def _canUpdateVideoMetadata(self):
        if self._video_frame_metadata is not None and not isinstance(self._video_frame_metadata, dict):
            self._videoError("Existing video_annotation metadata is not a tracking record. It was not overwritten.")
            return False
        return True

    def _restoreVideoMetadataAfterUndo(self):
        if self.video_mode:
            key = self._videoStateKey()
            if key in self._video_metadata_history:
                self._video_frame_metadata = deepcopy(self._video_metadata_history[key])
            if self.video_tracker is not None:
                self.stopVideoTracking()
                self.video_panel.status.setText("Tracking stopped after Undo. Select objects and Track selected to restart.")

    def _renewCopiedVideoIdentities(self, shapes):
        identities = {}
        for shape in shapes:
            old = shape.other_data.get("video_object_id")
            if isinstance(old, str) and old:
                shape.other_data["video_object_id"] = identities.setdefault(old, uuid4().hex)
        if identities and self.canvas.shapesBackups:
            # Canvas already stored the post-copy state; keep that snapshot's
            # identities in sync so a later Undo cannot relink the duplicate.
            self.canvas.shapesBackups[-1] = [shape.copy() for shape in self.canvas.shapes]

    def trackVideoSelection(self):
        if not self.video_mode or not self.video_sequences or self.review_config is not None:
            return False
        if not self._canUpdateVideoMetadata():
            return False
        if self.video_panel.backend.currentData() != "stcn":
            self._videoError("Choose a tracking backend explicitly. STCN is available; no quality default is assumed.")
            return False
        selected = [item.shape() for item in self.labelList if item in self.labelList.selectedItems()]
        if not selected:
            self._videoError("Select an annotated object in Polygon Labels or on the image first.")
            return False
        if any(s.shape_type != "polygon" or numeric_group_id(s.group_id) is None for s in selected):
            self._videoError("Select polygon annotations with numeric class/group IDs. Assign IDs with Edit Label first.")
            return False
        if any("video_object_id" in s.other_data and
               (not isinstance(s.other_data["video_object_id"], str) or not s.other_data["video_object_id"])
               for s in selected):
            self._videoError("Existing video_object_id metadata must be a nonempty string; it was not overwritten.")
            return False
        identities = {s.other_data["video_object_id"] for s in selected if "video_object_id" in s.other_data}
        selected = [item.shape() for item in self.labelList if item.shape() in selected
                    or (isinstance(item.shape().other_data.get("video_object_id"), str)
                        and item.shape().other_data["video_object_id"] in identities)]
        groups = {}
        for shape in selected:
            identity = shape.other_data.get("video_object_id") or uuid4().hex
            groups.setdefault(str(identity), []).append(shape)
        if len(groups) > 1 and all(self._trackingMetadata(s) == self._trackingMetadata(selected[0]) for s in selected):
            reply = QtWidgets.QMessageBox.question(
                self, "Track selected polygons",
                "Are these parts of one object?\n\nYes: combine their masks for tracking.\n"
                "No: track them as separate objects, even if they share a class.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.Cancel:
                return False
            if reply == QtWidgets.QMessageBox.Yes:
                groups = {uuid4().hex: selected}
        objects, masks = [], []
        for identity, parts in groups.items():
            if any(self._trackingMetadata(s) != self._trackingMetadata(parts[0]) for s in parts):
                self._videoError("Parts of a tracked object have conflicting labels or metadata. Align them deliberately first.")
                return False
            mask = np.zeros((self.raw_h, self.raw_w), dtype=np.uint8)
            for shape in parts:
                mask |= self._shapeMask(shape)
            template = parts[0].copy()
            template.other_data["video_object_id"] = identity
            objects.append({"id": identity, "template": template, "parts": parts})
            masks.append(mask)
        try:
            def start():
                tracker = self._makeVideoTracker()
                tracker.start(self.current_img, masks, self.current_img_index)
                return tracker
            tracker = self._runVideoTask("Starting selected-object tracking…", start)
        except Exception as error:
            self._videoError(error)
            return False
        # Object identity is separate from class/group ID and persists as an
        # ordinary extra JSON field. No metadata is committed on startup failure.
        self._rememberVideoMetadata()
        self.canvas.storeShapes()
        for obj in objects:
            for shape in obj.pop("parts"):
                shape.other_data["video_object_id"] = obj["id"]
        self.canvas.storeShapes()
        self.video_tracker, self.video_objects = tracker, objects
        self._video_frame_metadata = {**(self._video_frame_metadata or {}),
                                      "sequence": self.video_sequences[self.video_sequence_index].name,
                                      "source": "manual_keyframe", "reference_frame": Path(self.current_img).name,
                                      "reference_frame_index": self.current_img_index,
                                      "reference_frame_indices": list(getattr(tracker, "reference_indices",
                                                                              [self.current_img_index]))}
        self._rememberVideoMetadata()
        self.video_panel.set_running(True, f"Tracking {len(objects)} object(s). PgDown → Propagate frame, or edit → Use correction.")
        self.actions.propagateVideo.setEnabled(True)
        self.setDirty()
        return True

    def useVideoCorrection(self):
        if self.review_config is not None or self.video_tracker is None:
            return False
        if not self._canUpdateVideoMetadata():
            return False
        masks, updated = [], []
        for obj in self.video_objects:
            parts = [item.shape() for item in self.labelList
                     if item.shape().other_data.get("video_object_id") == obj["id"]]
            if (not parts or numeric_group_id(parts[0].group_id) is None
                    or any(self._trackingMetadata(s) != self._trackingMetadata(parts[0]) for s in parts)):
                self._videoError("Every tracked object needs consistent annotation parts on a correction frame. "
                                 "Use Track selected to change the tracked objects.")
                return False
            mask = np.zeros((self.raw_h, self.raw_w), dtype=np.uint8)
            for shape in parts:
                mask |= self._shapeMask(shape)
            masks.append(mask)
            updated.append({"id": obj["id"], "template": parts[0].copy()})
        try:
            correct = getattr(self.video_tracker, "correct", self.video_tracker.start)
            self._runVideoTask("Updating tracking from this correction…",
                               lambda: correct(self.current_img, masks, self.current_img_index))
        except Exception as error:
            self._videoError(error)
            return False
        self.video_objects = updated
        self._rememberVideoMetadata()
        self._video_frame_metadata = {**(self._video_frame_metadata or {}),
                                      "sequence": self.video_sequences[self.video_sequence_index].name,
                                      "source": "manual_keyframe", "reference_frame": Path(self.current_img).name,
                                      "reference_frame_index": self.current_img_index,
                                      "reference_frame_indices": list(getattr(self.video_tracker, "reference_indices",
                                                                              [self.current_img_index]))}
        self._rememberVideoMetadata()
        self.setDirty()
        self.video_panel.status.setText("Correction is now the tracking reference. Navigate forward and propagate.")
        return True

    def propagateVideoFrame(self):
        if self.review_config is not None or not self.video_mode or self.video_tracker is None:
            return False
        if not self._canUpdateVideoMetadata():
            return False
        existing = list(self.labelList)
        if existing and QtWidgets.QMessageBox.question(
            self, "Propagate to this frame?",
            "Replace tracked annotations, including their labels and metadata, on this frame? "
            "Use correction first to retain deliberate edits as the reference. "
            "Other polygons will be kept; check for duplicates.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel, QtWidgets.QMessageBox.Cancel,
        ) != QtWidgets.QMessageBox.Yes:
            return False
        try:
            masks = self._runVideoTask("Propagating to this frame…",
                                      lambda: self.video_tracker.predict(self.current_img, self.current_img_index))
            if len(masks) != len(self.video_objects):
                raise VideoTrackingError("Tracking returned an unexpected number of objects.")
            replacements = {}
            for obj, mask in zip(self.video_objects, masks):
                if np.asarray(mask).shape != (self.raw_h, self.raw_w):
                    raise VideoTrackingError("Tracking mask dimensions do not match the current frame.")
                parts = []
                for points in exact_mask_polygons(mask):
                    shape = obj["template"].copy()
                    shape.points = [QtCore.QPointF(float(x), float(y)) for x, y in points]
                    shape.selected = False
                    shape.close()
                    parts.append(shape)
                replacements[obj["id"]] = parts
        except Exception as error:
            discard = getattr(self.video_tracker, "discard_prediction", None)
            if discard:
                discard()
            self._videoError(error)
            return False
        ordered, visibility, inserted = [], {}, set()
        for item in existing:
            shape = item.shape()
            identity = shape.other_data.get("video_object_id")
            if isinstance(identity, str) and identity in replacements:
                if identity not in inserted:
                    for part in replacements[identity]:
                        ordered.append(part)
                        visibility[part] = item.checkState()
                    inserted.add(identity)
            else:
                ordered.append(shape)
                visibility[shape] = item.checkState()
        for identity, parts in replacements.items():
            if identity not in inserted:
                for part in parts:
                    ordered.append(part)
                    visibility[part] = QtCore.Qt.Checked
        self._rememberVideoMetadata()
        self.canvas.storeShapes()
        self.canvas.deSelectShape()
        self._noSelectionSlot = True
        try:
            self.labelList.clear()
            for shape in ordered:
                self.addLabel(shape)
                self.labelList.findItemByShape(shape).setCheckState(visibility[shape])
        finally:
            self._noSelectionSlot = False
        self.canvas.loadShapes(ordered)
        self._video_frame_metadata = {**(self._video_frame_metadata or {}),
                                      "sequence": self.video_sequences[self.video_sequence_index].name,
                                      "source": "stcn_propagated_frame", "backend": "stcn",
                                      "reference_frame_indices": list(getattr(self.video_tracker, "reference_indices",
                                                                              [self.video_tracker.reference_index])),
                                      "reference_frame": self.video_sequences[self.video_sequence_index].frames[
                                          self.video_tracker.reference_index].name,
                                      "reference_frame_index": self.video_tracker.reference_index}
        self._rememberVideoMetadata()
        commit = getattr(self.video_tracker, "commit_prediction", None)
        if commit:
            commit()
        self.setDirty()
        count = sum(bool(parts) for parts in replacements.values())
        self.video_panel.status.setText(f"{count}/{len(replacements)} objects visible. Inspect and save; edit → Use correction if needed.")
        return True

    def _onVideoFrameLoaded(self):
        if self.video_mode:
            self.actions.undo.setEnabled(self.canvas.isShapeRestorable)
            self._video_frame_metadata = deepcopy((self._annotation_data or {}).get("video_annotation"))
            self._video_metadata_history = {}
            self._rememberVideoMetadata()
