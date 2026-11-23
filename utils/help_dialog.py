"""Searchable, nonmodal guidance for the shared image/video/review editor."""

from html import escape

from qtpy import QtCore, QtGui, QtWidgets


ACTION_GROUPS = (
    ("Files and setup", ("imageDirectory", "openVolume", "saveDirectory", "save", "saveAs", "loadSAM", "classMapping")),
    ("SAM prompts", ("createPointMode", "createRectangleMode", "createCircleMode", "promptSeg", "cleanPrompt")),
    ("Polygon editing", ("createMode", "editMode", "undoLastPoint", "undo", "delete", "reduce_point", "subtract", "merge")),
    ("Video tracking", ("propagateVideo",)),
)

TOPICS = (
    ("How do I annotate a NIfTI medical volume?",
     "Install requirements-volume.txt in your environment, then Open Volume or launch with --volume PATH. "
     "Scalar 3D .nii/.nii.gz files use native axis-2 slices, without reorientation or resampling; the panel labels voxel axes. "
     "PgUp/PgDown/J navigate slices. Use SAM/manual polygons and Save as usual. "
     "Window centre/width change previews in source intensity units, leaving scan data intact. "
     "Export NIfTI mask writes a native-grid segmentation and JSON mapping in a new bundle. "
     "Mask value = group ID + 1, with zero background; original annotation group IDs stay unchanged. "
     "Never-saved slices are zero-filled and listed as unannotated. DICOM, alternate planes, native volume review "
     "and 4D data are not included."),
    ("How do I propagate objects through NIfTI slices with STCN?",
     "Install the optional STCN code/checkpoint from the README. This use is experimental, not medically validated. "
     "Annotate a reference slice, Ctrl-select the objects, choose STCN and increasing/decreasing slice index, then Track selected. "
     "Advance with PgDown/PgUp in that direction, Propagate slice (Space), inspect/edit and Save. "
     "Use correction adds a reference; every tracked object needs nonempty parts. If a target disappears, stop and "
     "reinitialize the remaining object set. For the other direction, Stop tracking, return to an annotated reference, "
     "change direction, select objects and Track selected again. Undo, volume changes and applied intensity-window changes "
     "stop tracking. Reopening saves polygons/provenance, not model memory. Original voxel alignment and export mapping remain intact."),
    ("Why can't I merge polygons?",
     "Merge requires matching labels, class/group IDs, flags, and other metadata. "
     "Draw-order checks also prevent changing the visible overlap class. Read the rejection message for the specific conflict. "
     "Dropping an entry onto another row additionally requires overlapping pixels and your confirmation; "
     "the Merge Polygons command can combine disconnected regions. Row dragging never nests annotations."),
    ("Why is a donut or holed object several polygons?",
     "Compatible annotation JSON stores ordinary filled polygons, so a hole is preserved using two or more parts. "
     "In Edit mode, Ctrl-select all parts in Polygon Labels, then drag a selected part to move them together. "
     "Class/group IDs describe classes, not individual objects. Video tracking uses a separate video_object_id to link parts."),
    ("Why does subtraction still look filled?",
     "Subtract keeps the temporary cutter polygon. Delete that cutter when you no longer want it in the annotation. "
     "Hiding an entry only changes its display: hidden polygons are still saved and exported."),
    ("Why are there no SAM predictions?",
     "Click Load SAM first, then choose Point, Box, or Circle Prompt. Use left-click positive points and right-click negative points, "
     "or draw a box around the object. Circle Prompt supplies a bounding box to SAM; SAM does not receive a native circle prompt. "
     "Choose a preview and Accept to label it. Conversion checks run on Accept. Small and one-pixel-wide regions are retained; "
     "failed pixel-preservation checks or excessive complexity leave annotations unchanged."),
    ("Why do point predictions have speckles or miss a disconnected region?",
     "Point prompts: keep clicked regions retains foreground components containing a positive click. "
     "Add a positive click to each desired region, or turn this option off to retain all predicted regions. "
     "Toggling updates existing previews without rerunning SAM. Box and circle prompts keep all predicted regions."),
    ("What is U versus Ctrl+U?",
     "U removes the last vertex of an unfinished manual polygon; it is disabled when there is no unfinished polygon. "
     "Ctrl+U undoes completed annotation changes. Undoing video changes stops active tracking to avoid stale reference memory; "
     "select the desired objects and Track selected again."),
    ("H, number keys, and Show labels: what gets hidden?",
     "H hides or shows all polygons. Outside an active SAM proposal, digits 0–9 toggle polygons with that numeric class/group ID. "
     "While proposals are active, 1–3 select proposals instead; Accept or Reject ends that context. "
     "Show labels only hides or shows captions, keeping polygons visible and editable. Visibility does not remove saved annotations."),
    ("Where are annotations saved?",
     "Choose Save Directory explicitly. Without an explicit choice, the app asks before using its default output folder inside the app folder. "
     "Images save as <output>/<frame>.json; videos save as <output>/<sequence>/<frame>.json. "
     "Save and navigate away/back to check the result. Review writes to its separate configured review output, preserving source annotations."),
    ("How do I keep class names and group IDs consistent?",
     "Load your Category File, review the proposed class-name/group-ID mapping, and Apply mapping. "
     "Numeric prefixes supply IDs when every name has one; otherwise IDs start at zero in file order. "
     "Double-check these IDs against downstream requirements, then save and reuse the approved mapping JSON for the dataset. "
     "With mapping enabled, choose the group ID to fill the name. Warnings flag conflicting names within or across images; "
     "they do not automatically relabel existing annotations. Another dataset may use a different mapping."),
    ("How do I track multiple objects or polygon parts?",
     "Open Video Directory and annotate a reference frame. Ctrl-select all desired objects, choose STCN (optional), and Track selected. "
     "Different classes can track together in one pass. For matching metadata and distinct identities, Yes combines parts of one object; "
     "No keeps same-class objects separate. Already-linked parts skip the question. Check Tracking N object(s). "
     "Advance with Page Down and use Propagate frame (Space), inspect, then Save. "
     "Edit and Use correction to improve subsequent predictions. Changing the object set requires Track selected again. "
     "Polygon counts can change while the tracking identity stays the same. Predictions still need inspection."),
    ("Why is the app using CPU instead of GPU?",
     "Device choice depends on the active Python environment's PyTorch build and available CUDA or Apple MPS support. "
     "A CPU-only PyTorch installation uses CPU even if the computer has a GPU. GPU support also needs compatible hardware, drivers, "
     "and a matching PyTorch build. There is currently no manual device selector. STCN is an optional backend, "
     "not a claim of better accuracy than SAM 2 or SAM 3."),
    ("How do I review video annotations?",
     "Launch review mode and select the video image root, annotation root, and a separate reviewed-output folder. "
     "Nested sequences are paired by relative frame path. Review is frame-by-frame; propagation is disabled. "
     "Page Up/Page Down include context frames; Alt+Left/Alt+Right move between review targets. "
     "Decision buttons save and advance. Space pauses/resumes the review timer, rather than propagating video."),
)


def shortcut_text(action):
    return ", ".join(key.toString(QtGui.QKeySequence.NativeText)
                     for key in action.shortcuts() if not key.isEmpty())


def decorate_shortcut_actions(window):
    """Keep compact toolbar captions and tooltip keys derived from real actions."""
    captions = {
        "promptSeg": "Accept", "cleanPrompt": "Reject", "createMode": "New polygon",
        "createPointMode": "Point prompt", "createRectangleMode": "Box prompt",
        "createCircleMode": "Circle prompt", "editMode": "Edit polygons",
        "undoLastPoint": "Undo last point", "undo": "Undo", "save": "Save",
    }
    for value in vars(window.actions).values():
        if not isinstance(value, QtWidgets.QAction):
            continue
        keys = shortcut_text(value)
        if keys:
            tip = f"{value.toolTip()} ({keys})"
            value.setToolTip(tip)
            value.setStatusTip(tip)
    for name, caption in captions.items():
        action = getattr(window.actions, name)
        primary = action.shortcuts()[0].toString(QtGui.QKeySequence.NativeText)
        action.setIconText(f"{caption}\n({primary})")


def help_sections(window):
    """Read actual QAction/QShortcut bindings each time help opens."""
    sections = []
    for title, names in ACTION_GROUPS:
        rows = []
        for name in names:
            action = getattr(window.actions, name)
            label = action.text().replace("&", "")
            rows.append(f"{shortcut_text(action) or 'Button'} — {label}")
        sections.append((title, "\n".join(rows)))
    sections.append(("Navigation and visibility — shared image/video shortcuts", "\n".join((
        f"{window.previous_image_shortcut.key().toString()} — Previous image/frame",
        f"{window.next_image_shortcut.key().toString()} — Next image/frame",
        f"{window.jump_image_shortcut.key().toString()} — Jump to image/frame",
        f"{shortcut_text(window.actions.onShapesPresent[-1])} — Hide/show all polygons",
        "0–9 — Toggle class/group visibility (1–3 select active SAM proposals)",
        "Show labels — Toggle captions only", "Ctrl+click — Select multiple polygon entries",
        "Enter — Finish a closable manual polygon; Esc — Cancel an unfinished polygon",
        "Arrow keys — Move selected polygons in Edit mode", "Ctrl+mouse wheel — Zoom on the canvas",
        f"{shortcut_text(window.actions.help)} — Open Help",
    ))))
    from review import DECISION_SHORTCUTS
    review_rows = [f"{key} — {status.value.replace('_', ' ')}" for key, status in DECISION_SHORTCUTS]
    review_rows += ["Space — Pause/resume review timer", "Alt+Left / Alt+Right — Previous/next review target"]
    sections.append(("Review mode shortcuts", "\n".join(review_rows)))
    output = window.review_config.output_directory if window.review_config is not None else window.current_output_dir
    sections.append(("Current save destination", str(output)))
    return sections + list(TOPICS)


class HelpDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent, QtCore.Qt.Window)
        self.setWindowTitle("Annotator Help — shortcuts and common questions")
        self.setModal(False)
        self.resize(760, 680)
        self.sections = []
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel("Search shortcuts and common questions. Keep this window open while annotating.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search, e.g. holes, small objects, save, tracking…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render)
        layout.addWidget(self.search)
        self.results = QtWidgets.QTextBrowser()
        self.results.setOpenExternalLinks(False)
        layout.addWidget(self.results)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        close.rejected.connect(self.close)
        layout.addWidget(close)
        QtWidgets.QApplication.instance().installEventFilter(self)

    def refresh(self, window):
        self.sections = help_sections(window)
        self.render()

    def render(self):
        words = self.search.text().casefold().split()
        matches = [(title, body) for title, body in self.sections
                   if all(word in (title + " " + body).casefold() for word in words)]
        content = "".join(f"<h3>{escape(title)}</h3><p>{escape(body).replace(chr(10), '<br>')}</p>"
                          for title, body in matches)
        self.results.setHtml(content or "<p>No matching topics. Try a shorter search or clear the search field.</p>")

    def eventFilter(self, watched, event):
        # Application-wide navigation/review shortcuts must not activate while
        # searching OR browsing help. Preserve the normal text widget key event.
        if (event.type() == QtCore.QEvent.ShortcutOverride
                and isinstance(watched, QtWidgets.QWidget)
                and (watched is self or self.isAncestorOf(watched))):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_F1:
            self.search.setFocus()
            self.search.selectAll()
            event.accept()
        else:
            super().keyPressEvent(event)
