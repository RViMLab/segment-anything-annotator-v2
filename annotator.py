import sys
import functools
import cv2
import glob
import os
import os.path as osp
import imgviz
import html
import json
import math
import argparse
import numpy as np
import tempfile
import torch
import base64

from PyQt5.QtWidgets import QWidget, QApplication, QMainWindow, QApplication, QPushButton, QLabel, QFileDialog, QProgressBar, QComboBox, QScrollArea, QDockWidget, QMessageBox
from PyQt5.QtGui import QPixmap, QIcon, QImage
from PyQt5.Qt import QSize
from qtpy.QtCore import Qt
from qtpy import QtCore
from qtpy import QtGui, QtWidgets
from canvas import Canvas
import utils
from utils.download_model import download_model

from labelme.widgets import ToolBar, UniqueLabelQListWidget, LabelDialog, LabelListWidget, LabelListWidgetItem, ZoomWidget
from labelme import PY2
from labelme.label_file import LabelFile
from labelme.label_file import LabelFileError


from shape import Shape

from PIL import Image

from collections import namedtuple
Click = namedtuple('Click', ['is_positive', 'coords'])

from segment_anything import sam_model_registry, SamPredictor





LABEL_COLORMAP = imgviz.label_colormap()

class MainWindow(QMainWindow):

    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = 0, 1, 2

    def __init__(self, parent=None, global_w=1000, global_h=1800, model_type='vit_b', keep_input_size=True, max_size=1080):
        super(MainWindow, self).__init__(parent)
        self.resize(global_w, global_h)
        self.model_type = model_type
        self.keep_input_size = keep_input_size
        self.max_size = float(max_size)

        self.setWindowTitle('segment-anything-annotator')
        self.canvas = Canvas(self,
            epsilon=10.0,
            double_click='close',
            num_backups=10,
            app=self,
        )

        
        self._noSelectionSlot = False
        self.current_output_dir = 'output'
        os.makedirs(self.current_output_dir, exist_ok=True)
        self.current_output_filename = ''
        self.canvas.zoomRequest.connect(self.zoomRequest)

        self.memory_shapes = []
        self.sam_mask = []
        self.sam_mask_proposal = []
        self.image_encoded_flag = False
        self.min_point_dis = 4
        self.subtract_mode = False
        self.subtract_shape = None
        self.merge_mode = False
        self.merge_shape = None

        self.predictor = None

        self.scroll_values = {
            Qt.Horizontal: {},
            Qt.Vertical: {},
        }
        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidget(self.canvas)
        self.scrollArea.setWidgetResizable(True)
        self.scrollBars = {
            Qt.Vertical: self.scrollArea.verticalScrollBar(),
            Qt.Horizontal: self.scrollArea.horizontalScrollBar(),
        }
        self.canvas.scrollRequest.connect(self.scrollRequest)
        self.canvas.newShape.connect(self.newShape)
        self.canvas.shapeMoved.connect(self.setDirty)
        self.canvas.selectionChanged.connect(self.shapeSelectionChanged)
        self.canvas.drawingPolygon.connect(self.toggleDrawingSensitive)

        self.uniqLabelList = UniqueLabelQListWidget()
        self.uniqLabelList.setToolTip(
            self.tr(
                "Select label to start annotating for it. "
                "Press 'Esc' to deselect."
            )
        )
        self.labelDialog = LabelDialog(
            parent=self,
            labels=[],
            sort_labels=False,
            show_text_field=True,
            completion='contains',
            fit_to_content={'column': True, 'row': False},
        )

        self.labelList = LabelListWidget()
        self.labelList.itemSelectionChanged.connect(self.labelSelectionChanged)
        self.labelList.itemDoubleClicked.connect(self.editLabel)
        self.labelList.itemChanged.connect(self.labelItemChanged)
        self.labelList.itemDropped.connect(self.labelOrderChanged)

        self.shape_dock = QDockWidget(
            self.tr("Polygon Labels"), self
        )
        self.shape_dock.setObjectName("Labels")
        self.shape_dock.setWidget(self.labelList)

        self.category_list = [i.strip() for i in open('categories.txt', 'r', encoding='utf-8').readlines()]
        self.labelDialog = LabelDialog(
            parent=self,
            labels=self.category_list,
            sort_labels=False,
            show_text_field=True,
            completion='contains',
            fit_to_content={'column': True, 'row': False},
        )
        self.zoom_values = {}
        self.video_directory = ''
        self.video_list = []
        self.video_len = len(self.video_list)

        self.img_list = []
        self.img_len = len(self.img_list)
        self.current_img_index = 0
        self.current_img = ''
        self.current_img_data = ''

        self.button_next = QPushButton('Next Image', self)
        self.button_next.clicked.connect(self.clickButtonNext)
        self.button_last = QPushButton('Last Image', self)
        self.button_last.clicked.connect(self.clickButtonLast)
        self.button_jump = QPushButton('Jump', self)
        self.button_jump.setShortcut('J')
        self.button_jump.clicked.connect(self.clickButtonJump)

        self.img_progress_bar = QProgressBar(self)
        self.img_progress_bar.setMinimum(0)
        self.img_progress_bar.setMaximum(1)
        self.img_progress_bar.setValue(0)
        self.button_proposal1 = QPushButton('Proposal1', self)
        self.button_proposal1.clicked.connect(self.choose_proposal1)
        self.button_proposal1.setShortcut('1')
        self.button_proposal2 = QPushButton('Proposal2', self)
        self.button_proposal2.clicked.connect(self.choose_proposal2)
        self.button_proposal2.setShortcut('2')
        self.button_proposal3 = QPushButton('Proposal3', self)
        self.button_proposal3.clicked.connect(self.choose_proposal3)
        self.button_proposal3.setShortcut('3')
        self.button_proposal4 = QPushButton('Proposal4', self)
        self.button_proposal4.clicked.connect(self.choose_proposal4)
        self.button_proposal4.setShortcut('4')
        self.button_proposal_list = [self.button_proposal1, self.button_proposal2, self.button_proposal3, self.button_proposal4]
        
        self.class_on_flag = True
        self.class_on_text = QLabel("Class On", self)
        self.img_name = QLabel("", self)
        self.img_name.setAlignment(Qt.AlignCenter)
        self.img_name.setStyleSheet("font-size: 10pt; color: black;")

        # ── Brightness / Contrast sliders ────────────────────────────────────
        from PyQt5.QtWidgets import QSlider
        from PyQt5.QtCore import QTimer

        self._raw_pixmap = None  # stores the unmodified image pixmap

        # Brightness slider  (-100 … +100, step 1, default 0)
        self.brightness_label = QLabel("Bright\n0", self)
        self.brightness_label.setStyleSheet("font-size: 8pt; qproperty-alignment: 'AlignHCenter';")
        self.brightness_slider = QSlider(Qt.Vertical, self)
        self.brightness_slider.setRange(-100, 100)
        self.brightness_slider.setValue(0)
        self.brightness_slider.setTickPosition(QSlider.TicksRight)
        self.brightness_slider.setTickInterval(25)
        self.brightness_slider.valueChanged.connect(self._on_bc_slider_changed)

        # Contrast slider  (10 … 300 → maps to 0.1 … 3.0×, default 100 = 1.0×)
        self.contrast_label = QLabel("Contrast\n1.0×", self)
        self.contrast_label.setStyleSheet("font-size: 8pt; qproperty-alignment: 'AlignHCenter';")
        self.contrast_slider = QSlider(Qt.Vertical, self)
        self.contrast_slider.setRange(10, 300)
        self.contrast_slider.setValue(100)
        self.contrast_slider.setTickPosition(QSlider.TicksRight)
        self.contrast_slider.setTickInterval(50)
        self.contrast_slider.valueChanged.connect(self._on_bc_slider_changed)

        # Reset button
        self.button_bc_reset = QPushButton("Reset B/C", self)
        self.button_bc_reset.clicked.connect(self.resetBrightnessContrast)

        # Debounce timer – fires 80 ms after the last slider move
        self._bc_timer = QTimer(self)
        self._bc_timer.setSingleShot(True)
        self._bc_timer.timeout.connect(self.applyBrightnessContrast)
        

        #naive layout
        # shifted down to make room for filename label
        self.scrollArea.move(int(0.02 * global_w), int(0.12 * global_h))
        self.scrollArea.resize(int(0.69 * global_w), int(0.7 * global_h))   # narrowed to make room for B/C panel
        self.shape_dock.move(int(0.79 * global_w), int(0.12 * global_h))
        self.shape_dock.resize(int(0.2 * global_w), int(0.7 * global_h))
        self.button_next.move(int(0.18 * global_w), int(0.89 * global_h))
        self.button_next.resize(int(0.1 * global_w),int(0.04 * global_h))
        self.button_last.move(int(0.01 * global_w), int(0.89 * global_h))
        self.button_last.resize(int(0.1 * global_w),int(0.04 * global_h))
        self.button_jump.move(int(0.12 * global_w), int(0.89 * global_h))
        self.button_jump.resize(int(0.05 * global_w),int(0.04 * global_h))
        self.class_on_text.move(int(0.01 * global_w), int(0.94 * global_h))
        # place filename label centered above the scroll area
        self.img_name.move(int(0.02 * global_w), int(0.09 * global_h))
        self.img_name.resize(int(0.69 * global_w), int(0.03 * global_h))
        self.img_progress_bar.move(int(0.01 * global_w), int(0.84 * global_h))
        self.img_progress_bar.resize(int(0.3 * global_w),int(0.04 * global_h))
        
        self.button_proposal1.resize(int(0.17 * global_w),int(0.14 * global_h))
        self.button_proposal1.move(int(0.33 * global_w), int(0.84 * global_h))
        self.button_proposal2.resize(int(0.17 * global_w),int(0.14 * global_h))
        self.button_proposal2.move(int(0.50 * global_w), int(0.84 * global_h))
        self.button_proposal3.resize(int(0.17 * global_w),int(0.14 * global_h))
        self.button_proposal3.move(int(0.67 * global_w), int(0.84 * global_h))
        self.button_proposal4.resize(int(0.17 * global_w),int(0.14 * global_h))
        self.button_proposal4.move(int(0.84 * global_w), int(0.84 * global_h))

        # ── Brightness / Contrast – vertical panel between image view and dock ──
        # The gap spans from x=0.72*w to x=0.78*w (6% of window width).
        # Each slider column is ~2.5% wide; the two columns are centred in the gap
        # with a small spacing between them.
        _vc_col_w   = int(0.028 * global_w)   # width of each slider column
        _vc_sld_h   = int(0.52 * global_h)    # tall slider
        _vc_lbl_h   = int(0.04 * global_h)    # label height above each slider
        _vc_btn_h   = int(0.03 * global_h)    # reset button height
        _vc_top     = int(0.13 * global_h)    # top of the label row
        _vc_gap     = int(0.015 * global_w)   # horizontal gap between the two columns

        # Centre the two columns inside the gap
        _vc_x1 = int(0.722 * global_w)        # brightness column left edge
        _vc_x2 = _vc_x1 + _vc_col_w + _vc_gap  # contrast column left edge

        # Brightness column
        self.brightness_label.move(_vc_x1, _vc_top)
        self.brightness_label.resize(_vc_col_w, _vc_lbl_h)
        self.brightness_slider.move(_vc_x1, _vc_top + _vc_lbl_h + 2)
        self.brightness_slider.resize(_vc_col_w, _vc_sld_h)

        # Contrast column
        self.contrast_label.move(_vc_x2, _vc_top)
        self.contrast_label.resize(_vc_col_w, _vc_lbl_h)
        self.contrast_slider.move(_vc_x2, _vc_top + _vc_lbl_h + 2)
        self.contrast_slider.resize(_vc_col_w, _vc_sld_h)

        # Reset button – spans both columns, sits below the sliders
        _vc_reset_y = _vc_top + _vc_lbl_h + 2 + _vc_sld_h + 6
        _vc_reset_w = _vc_x2 + _vc_col_w - _vc_x1
        self.button_bc_reset.move(_vc_x1, _vc_reset_y)
        self.button_bc_reset.resize(_vc_reset_w, _vc_btn_h)
        
        
        
        self.zoomWidget = ZoomWidget()

        action = functools.partial(utils.newAction, self)
        

        categoryFile = action(
            self.tr("Category File"),
            lambda: self.clickCategoryChoose(),
            'None',
            "objects",
            self.tr("Category File"),
            enabled=True,
        )
        imageDirectory = action(
            self.tr("Image Directory"),
            lambda: self.clickFileChoose(),
            'None',
            "objects",
            self.tr("Image Directory"),
            enabled=True,
        )
        LoadSAM = action(
            self.tr("Load SAM"),
            lambda: self.clickLoadSAM(),
            'None',
            "objects",
            self.tr("Load SAM"),
            enabled=True,
        )
        AutoSeg = action(
            self.tr("AutoSeg"),
            lambda: self.clickAutoSeg(),
            'None',
            "objects",
            self.tr("AutoSeg"),
            enabled=False,
        )
        promptSeg = action(
            self.tr("Accept"),
            lambda: self.addSamMask(),
            'a',
            "objects",
            self.tr("Accept"),
            enabled=False,
        )

        saveDirectory = action(
            self.tr("Save Directory"),
            lambda: self.clickSaveChoose(),
            'None',
            "objects",
            self.tr("Save Directory"),
            enabled=True,
        )

        createMode = action(
            self.tr("Manual Polygons"),
            lambda: self.toggleDrawMode(False, createMode="polygon"),
            'Ctrl+W',
            "objects",
            self.tr("Start drawing polygons"),
            enabled=True,
        )
        createPointMode = action(
            self.tr("Point Prompt"),
            lambda: self.toggleDrawMode(False, createMode="point"),
            'None',
            "objects",
            self.tr("Point Prompt"),
            enabled=True,
        )
        createRectangleMode = action(
            self.tr("Box Prompt"),
            lambda: self.toggleDrawMode(False, createMode="rectangle"),
            'None',
            "objects",
            self.tr("Box Prompt"),
            enabled=True,
        )
        createCircleMode = action(
            self.tr("Circle Prompt"),
            lambda: self.toggleDrawMode(False, createMode="circle"),
            'None',
            "objects",
            self.tr("Circle Prompt"),
            enabled=True,
        )
        cleanPrompt = action(
            self.tr("Reject"),
            lambda: self.cleanPrompt(),
            'r',
            "objects",
            self.tr("Reject"),
            enabled=True,
        )
        
        self.switchClass = action(
            self.tr("Class On/Off"),
            lambda: self.clickSwitchClass(),
            'none',
            "objects",
            self.tr("Class On/Off"),
            enabled=True,
        )

        editMode = action(
            self.tr("Edit Polygons"),
            self.setEditMode,
            'e',
            "edit",
            self.tr("Move and edit the selected polygons"),
            enabled=False,
        )
        saveAs = action(
            self.tr("&Save As"),
            self.saveFileAs,
            'ALT+s',
            "save-as",
            self.tr("Save labels to a different file"),
            enabled=True,
        )

        undoLastPoint = action(
            self.tr("Undo last point"),
            self.canvas.undoLastPoint,
            'U',
            "undo",
            self.tr("Undo last drawn point"),
            enabled=False,
        )

        hideAll = action(
            self.tr("&Hide\nPolygons"),
            functools.partial(self.togglePolygons, False),
            icon="eye",
            tip=self.tr("Hide all polygons"),
            enabled=False,
        )
        showAll = action(
            self.tr("&Show\nPolygons"),
            functools.partial(self.togglePolygons, True),
            icon="eye",
            tip=self.tr("Show all polygons"),
            enabled=False,
        )

        undo = action(
            self.tr("Undo"),
            self.undoShapeEdit,
            'Ctrl+U',
            "undo",
            self.tr("Undo last add and edit of shape"),
            enabled=False,
        )

        save = action(
            self.tr("&Save"),
            self.saveFile,
            'S',
            "save",
            self.tr("Save labels to file"),
            enabled=False,
        )

        delete = action(
            self.tr("Delete Polygons"),
            self.deleteSelectedShape,
            'd',
            "cancel",
            self.tr("Delete the selected polygons"),
            enabled=False,
        )
        duplicate = action(
            self.tr("Duplicate Polygons"),
            self.duplicateSelectedShape,
            'None',
            "copy",
            self.tr("Create a duplicate of the selected polygons"),
            enabled=False,
        )
        reduce_point = action(
            self.tr("Reduce Points"),
            self.reducePoint,
            'Shift+R',
            "copy",
            self.tr("Reduce Points"),
            enabled=True,
        )            
        subtract = action(
            self.tr("Subtract Polygons"),
            lambda: self.startSubtract(),
            'Shift+S',
            "edit",
            self.tr("Subtract selected polygon from another"),
            enabled=True,
        )
        merge = action(
            self.tr("Merge Polygons"),
            lambda: self.startMerge(),
            'm',
            "edit",
            self.tr("Merge two selected polygons"),
            enabled=True,
        )
        edit = action(
            self.tr("&Edit Label"),
            self.editLabel,
            'None',
            "edit",
            self.tr("Modify the label of the selected polygon"),
            enabled=False,
        )
        

        self.actions = utils.struct(
            categoryFile=categoryFile,
            imageDirectory=imageDirectory,
            saveDirectory=saveDirectory,
            switchClass=self.switchClass,
            loadSAM=LoadSAM,
            #autoSeg=AutoSeg,
            promptSeg=promptSeg,
            cleanPrompt=cleanPrompt,
            createMode=createMode,
            createPointMode=createPointMode,
            createRectangleMode=createRectangleMode,
            createCircleMode=createCircleMode,
            editMode=editMode,
            undoLastPoint=undoLastPoint,
            undo=undo,
            delete=delete,
            edit=edit,
            duplicate=duplicate,
            reduce_point=reduce_point,
            subtract=subtract,
            merge=merge,
            save=save,
            onShapesPresent=(saveAs, hideAll, showAll),
            menu=(
                createMode,
                editMode,
                undoLastPoint,
                undo,
                save,
            )
            )

        # Custom context menu for the canvas widget:
        utils.addActions(self.canvas.menus[0], self.actions.menu)
        utils.addActions(
            self.canvas.menus[1],
            (
                action("&Copy here", self.copyShape),
                action("&Move here", self.moveShape),
            ),
        )

        self.toolbar = self.addToolBar('Tool')
        self.toolbar.addAction(categoryFile)
        self.toolbar.addAction(imageDirectory)
        self.toolbar.addAction(saveDirectory)
        self.toolbar.addAction(self.switchClass)
        self.toolbar.addAction(LoadSAM)
        #self.toolbar.addAction(AutoSeg)
        self.toolbar.addAction(promptSeg)
        self.toolbar.addAction(cleanPrompt)
        self.toolbar.addAction(createMode)
        self.toolbar.addAction(createPointMode)
        self.toolbar.addAction(createRectangleMode)
        self.toolbar.addAction(createCircleMode)
        self.toolbar.addAction(editMode)
        self.toolbar.addAction(undoLastPoint)
        self.toolbar.addAction(undo)
        self.toolbar.addAction(delete)
        self.toolbar.addAction(edit)
        self.toolbar.addAction(duplicate)
        self.toolbar.addAction(reduce_point)
        self.toolbar.addAction(subtract)
        self.toolbar.addAction(merge)
        self.toolbar.addAction(save)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)

        zoom = QtWidgets.QWidgetAction(self)
        zoom.setDefaultWidget(self.zoomWidget)
        self.zoomWidget.setWhatsThis(
            str(
                self.tr(
                    "Zoom in or out of the image. Also accessible with "
                    "{} from the canvas."
                )
            ).format(
                #utils.fmtShortcut(
                #    "{},{}".format(shortcuts["zoom_in"], shortcuts["zoom_out"])
                #),
                utils.fmtShortcut(self.tr("Ctrl+Wheel")),
            )
        )
        self.zoomWidget.setEnabled(True)

        self.zoomWidget.valueChanged.connect(self.paintCanvas)
        self.canvas.actions = self.actions
        # preview state (no interactive reduce slider)


    def saveFileAs(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._saveFile(self.saveFileDialog())

    def saveFile(self, _value=False):
        # assert not self.image.isNull(), "cannot save empty image"
        # if self.labelFile:
        #     # DL20180323 - overwrite when in directory
        #     self._saveFile(self.labelFile.filename)
        # elif self.output_file:
        #     self._saveFile(self.output_file)
        #     self.close()
        # else:
        #     self._saveFile(self.saveFileDialog())
        #self._saveFile(self.saveFileDialog())
        #print(self.current_output_filename)
        self._saveFile(self.current_output_filename)

    def _saveFile(self, filename):
        if filename and self.saveLabels(filename):
            self.setClean()

    def saveLabels(self, filename):
        lf = LabelFile()

        def format_shape(s):
            data = s.other_data.copy()
            data.update(
                dict(
                    label=s.label.encode("utf-8") if PY2 else s.label,
                    points=[[p.x(), p.y()] for p in s.points],
                    group_id=s.group_id,
                    description="",
                    shape_type=s.shape_type,
                    flags=s.flags,
                )
            )
            return data

        shapes = [format_shape(item.shape()) for item in self.labelList]
        imageData = base64.b64encode(self.current_img_data).decode("utf-8")
        save_data = {
            "version": "1.0.0",
            "flags": {},
            "shapes": shapes,
            "imagePath": self.current_img,
            "imageData": imageData,
            "imageHeight": self.raw_h,
            "imageWidth": self.raw_w
        }

        with open(filename, 'w') as f:
            json.dump(save_data, f)
        return True

    def setClean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.createMode.setEnabled(True)

    def saveFileDialog(self):
        caption = self.tr("Choose File")
        filters = self.tr("Label files")
        if self.output_dir:
            dlg = QtWidgets.QFileDialog(
                self, caption, self.output_dir, filters
            )
        else:
            dlg = QtWidgets.QFileDialog(
                self, caption, self.currentPath(), filters
            )
        dlg.setDefaultSuffix(LabelFile.suffix[1:])
        dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dlg.setOption(QtWidgets.QFileDialog.DontConfirmOverwrite, False)
        dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, False)
        basename = os.path.basename(self.current_img)[:-4]
        if self.output_dir:
            default_labelfile_name = osp.join(
                self.output_dir, basename + LabelFile.suffix
            )
        else:
            default_labelfile_name = osp.join(
                self.currentPath(), basename + LabelFile.suffix
            )
        filename = dlg.getSaveFileName(
            self,
            self.tr("Choose File"),
            default_labelfile_name,
            self.tr("Label files (*%s)") % LabelFile.suffix,
        )
        if isinstance(filename, tuple):
            filename, _ = filename
        return filename

    def currentPath(self):
        #return osp.dirname(str(self.filename)) if self.filename else "."
        return "."

    def loadAnno(self, filename):
        with open(filename,'r') as f:
            data = json.load(f)
        for shape in data['shapes']:
            label = shape["label"]
            try:
                ttt = int(label)
                label = self.category_list[ttt]
            except:
                pass

            points = shape["points"]
            shape_type = shape["shape_type"]
            flags = shape["flags"]
            group_id = shape["group_id"]
            if not points:
                # skip point-empty shape
                continue
            shape = Shape(
                label=label,
                shape_type=shape_type,
                group_id=group_id,
                flags=flags
            )
            for x, y in points:
                shape.addPoint(QtCore.QPointF(x, y))
            shape.close()
            self.addLabel(shape)
        self.canvas.loadShapes([item.shape() for item in self.labelList])

    def clickButtonNext(self):
        if self.actions.save.isEnabled():
            self.saveFile()
        if self.current_img_index < self.img_len - 1:
            self.current_img_index += 1
            self.current_img = self.img_list[self.current_img_index]
            self.loadImg()

    def clickButtonLast(self):
        if self.actions.save.isEnabled():
            self.saveFile()
        if self.current_img_index > 0:
            self.current_img_index -= 1
            self.current_img = self.img_list[self.current_img_index]
            self.loadImg()


    def clickButtonJump(self):
        if self.actions.save.isEnabled():
            reply = QMessageBox.question(
                self,
                self.tr("Unsaved changes"),
                self.tr("You have unsaved changes. Save before jumping?"),
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Yes:
                self.saveFile()
        if self.img_len == 0:
            return
        items = [f"{i} - {os.path.basename(p)}" for i, p in enumerate(self.img_list)]
        current_text = items[self.current_img_index] if 0 <= self.current_img_index < len(items) else items[0]
        item, ok = QtWidgets.QInputDialog.getItem(
            self,
            self.tr("Jump to image"),
            self.tr("Select image (type to search):"),
            items,
            current=items.index(current_text),
            editable=True,
        )
        if ok and item:
            try:
                idx = int(item.split(' - ', 1)[0])
                if not (0 <= idx < len(self.img_list)):
                    QMessageBox.warning(
                        self,
                        self.tr("Invalid index"),
                        self.tr("Image index must be between 0 and {max_val}.").format(max_val=len(self.img_list) - 1)
                    )
                    return
            except Exception:
                return
            self.current_img_index = int(idx)
            self.current_img = self.img_list[self.current_img_index]
            self.loadImg()


    def choose_proposal1(self):
        if len(self.sam_mask_proposal) > 0:
            self.sam_mask = self.sam_mask_proposal[0]
            self.canvas.setHiding()
            self.canvas.update()

    def choose_proposal2(self):
        if len(self.sam_mask_proposal) > 1:
            self.sam_mask = self.sam_mask_proposal[1]
            self.canvas.setHiding()
            self.canvas.update()
            
    def choose_proposal3(self):
        if len(self.sam_mask_proposal) > 2:
            self.sam_mask = self.sam_mask_proposal[2]
            self.canvas.setHiding()
            self.canvas.update()
            
    def choose_proposal4(self):
        if len(self.sam_mask_proposal) > 3:
            self.sam_mask = self.sam_mask_proposal[3]
            self.canvas.setHiding()
            self.canvas.update()
            
    def loadImg(self):
        self.raw_h, self.raw_w = cv2.imread(self.current_img).shape[:2]
        pixmap = QPixmap(self.current_img)
        # Keep an unmodified copy for brightness/contrast adjustments
        self._raw_pixmap = pixmap
        self.canvas.loadPixmap(pixmap)
        self.img_progress_bar.setValue(self.current_img_index)

        img_name = os.path.basename(self.current_img)[:-4]
        self.current_output_filename = osp.join(self.current_output_dir, img_name + '.json')
        # show filename (including extension) centered above the image area
        try:
            self.img_name.setText(os.path.basename(self.current_img))
        except Exception:
            self.img_name.setText("")
        self.labelList.clear()
        if os.path.isfile(self.current_output_filename):
            self.loadAnno(self.current_output_filename)
        self.image_encoded_flag = False
        self.current_img_data = LabelFile.load_image_file(self.current_img)

        # Reset brightness/contrast sliders to neutral on every new image
        self.brightness_slider.blockSignals(True)
        self.contrast_slider.blockSignals(True)
        self.brightness_slider.setValue(0)
        self.contrast_slider.setValue(100)
        self.brightness_slider.blockSignals(False)
        self.contrast_slider.blockSignals(False)
        self.brightness_label.setText("Bright\n0")
        self.contrast_label.setText("Contrast\n1.0\u00d7")


    def clickFileChoose(self):
        directory = QFileDialog.getExistingDirectory(self, 'choose target fold','.')
        if directory == '':
            return
        #self.img_list = glob.glob(directory + '/*.{jpg,png,JPG,PNG}')
        self.img_list = glob.glob(directory + '/*.jpg') + glob.glob(directory + '/*.png')
        self.img_list.sort()
        self.img_len = len(self.img_list)
        if self.img_len == 0:
            return
        self.current_img_index = 0
        self.current_img = self.img_list[self.current_img_index]
        self.img_progress_bar.setMinimum(0)
        self.img_progress_bar.setMaximum(self.img_len-1)
        self.loadImg()

    def clickSaveChoose(self):
        directory = QFileDialog.getExistingDirectory(self, 'choose target fold','.')
        if directory == '':
            return
        else:
            self.current_output_dir = directory
            os.makedirs(self.current_output_dir, exist_ok=True)
            self.loadImg()
            return directory


    def clickSwitchClass(self):
        if self.class_on_flag:
            self.class_on_flag = False
            self.class_on_text.setText('Class Off')
        else:
            self.class_on_flag = True
            self.class_on_text.setText('Class On')


    def clickCategoryChoose(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'choose target file','.')
        try:
            with open(filename, 'r') as f:
                data = f.readlines()
                self.category_list = [i.strip() for i in data]
                self.category_list.sort()
                self.labelDialog = LabelDialog(
                    parent=self,
                    labels=self.category_list,
                    sort_labels=False,
                    show_text_field=True,
                    completion='contains',
                    fit_to_content={'column': True, 'row': False},
                )
        except Exception as e:
            pass

    def clickLoadSAM(self):
        download_model(self.model_type)
        self.sam = sam_model_registry[self.model_type](checkpoint='{}.pth'.format(self.model_type))
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.sam.to(device=self.device)
        self.predictor = SamPredictor(self.sam)
        self.actions.loadSAM.setEnabled(False)
        #self.actions.autoSeg.setEnabled(True)
        self.actions.promptSeg.setEnabled(True)

    def startSubtract(self):
        # Begin subtract flow: require a currently selected polygon as the source
        item = self.currentItem()
        if item is None:
            QMessageBox.information(self, self.tr("Subtract"), self.tr("Select a polygon to subtract (source) first."))
            return
        shape = item.shape()
        if shape is None or shape.shape_type != 'polygon':
            QMessageBox.information(self, self.tr("Subtract"), self.tr("Source must be a polygon."))
            return
        # ask user to confirm or cancel; Esc will cancel
        reply = QMessageBox.question(
            self,
            self.tr("Subtract"),
            self.tr("Now select the polygon to cut from (target). Press Cancel or Esc to abort."),
            QMessageBox.Ok | QMessageBox.Cancel,
        )
        if reply == QMessageBox.Cancel:
            return
        self.subtract_shape = shape
        self.subtract_mode = True

    def startMerge(self):
        item = self.currentItem()
        if item is None:
            QMessageBox.information(self, self.tr("Merge"), self.tr("Select the first polygon to merge (source) first."))
            return
        shape = item.shape()
        if shape is None or shape.shape_type != 'polygon':
            QMessageBox.information(self, self.tr("Merge"), self.tr("Source must be a polygon."))
            return
        reply = QMessageBox.question(
            self,
            self.tr("Merge"),
            self.tr("Now select the polygon to merge with (target). Press Cancel or Esc to abort."),
            QMessageBox.Ok | QMessageBox.Cancel,
        )
        if reply == QMessageBox.Cancel:
            return
        self.merge_shape = shape
        self.merge_mode = True
        QMessageBox.information(self, self.tr("Merge"), self.tr("Select the target polygon to complete the merge."))
    
    def clickAutoSeg(self):
        pass
    
    def getMaxId(self):
        max_id = -1
        for label in self.labelList:
            if label.shape().group_id != None:
                max_id = max(max_id, int(label.shape().group_id))
        return max_id
        
    def show_proposals(self, masks=None, flag=1):
        if flag != 1:
            img = cv2.imread(self.current_img)
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            for msk_idx in range(masks.shape[0]):
                tmp_mask = masks[msk_idx]
                tmp_vis = img.copy()
                tmp_vis[tmp_mask > 0] = 0.5 * tmp_vis[tmp_mask > 0] + 0.5 * np.array([30,30,220])
                tmp_vis = cv2.resize(tmp_vis,(int(0.17 * global_w),int(0.14 * global_h)))
                tmp_vis = tmp_vis.astype(np.uint8)
                pixmap = QPixmap.fromImage(QImage(tmp_vis, tmp_vis.shape[1], tmp_vis.shape[0], tmp_vis.shape[1] * 3 , QImage.Format_RGB888))
                #self.button_proposal_list[msk_idx].setPixmap(pixmap)
                self.button_proposal_list[msk_idx].setIcon(QIcon(pixmap))
                self.button_proposal_list[msk_idx].setIconSize(QSize(tmp_vis.shape[1], tmp_vis.shape[0]))
                self.button_proposal_list[msk_idx].setShortcut(str(msk_idx+1))
        else:
            for idx, button_proposal in enumerate(self.button_proposal_list):
                button_proposal.setText('proprosal{}'.format(idx))
                button_proposal.setIconSize(QSize(0,0))
                self.button_proposal_list[idx].setShortcut(str(idx+1))

    def transform_input(self, image, box=None, points=None):
        if self.keep_input_size == True:
            return image, box, points
        else:
            h,w = image.shape[:2]
            scale_ratio = self.max_size / max(h,w)
            image = cv2.resize(image, (int(w*scale_ratio), int(h*scale_ratio)))
            if box is not None:
                box = box * scale_ratio
            if points is not None:
                points = points * scale_ratio
            return image, box, points
    
    def transform_output(self, masks, size):
        if self.keep_input_size == True:
            return masks
        else:
            h,w = size
            N = masks.shape[0]
            new_masks = np.zeros((N,h,w), dtype=np.uint8)
            for idx in range(N):
                new_masks[idx] = cv2.resize(masks[idx], (w,h))
            return new_masks

    def clickManualSegBBox(self):
        Box = self.canvas.currentBox
        if self.predictor is None or self.current_img == '' or Box == None:
            return
        img = cv2.imread(self.current_img)[:,:,::-1]
        rh, rw = img.shape[:2]
        input_box = np.array([Box[0].x(), Box[0].y(), Box[1].x(), Box[1].y()])
        img, input_box, _ = self.transform_input(img, box=input_box)
        if self.image_encoded_flag == False:
            self.predictor.set_image(img)
            self.image_encoded_flag = True
        masks, iou_prediction, _ = self.predictor.predict(
            point_coords=None,
            point_labels=None,
            box=input_box[None, :],
            multimask_output=True,
        )
        masks = self.transform_output(masks.astype(np.uint8), (rh,rw))

        target_idx = np.argmax(iou_prediction)
        self.show_proposals(masks, 0)
        self.sam_mask_proposal = []
        for msk_idx in range(masks.shape[0]):
            mask = masks[msk_idx].astype(np.uint8)

            points_list = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)[0]
            shape_type = 'polygon'
            tmp_sam_mask = []
            for points in points_list:
                area = cv2.contourArea(points)
                if area < 100 and len(points_list) > 1:
                    continue
                pointsx = points[:,0,0]
                pointsy = points[:,0,1]

                shape = Shape(
                    label='Object',
                    shape_type=shape_type,
                    group_id=self.getMaxId() + 1,
                )
                for point_index in range(pointsx.shape[0]):
                    shape.addPoint(QtCore.QPointF(pointsx[point_index], pointsy[point_index]))
                shape.close()
                #self.addLabel(shape)
                tmp_sam_mask.append(shape)
            if msk_idx == target_idx:
                self.sam_mask = tmp_sam_mask
            self.sam_mask_proposal.append(tmp_sam_mask)


    def clickManualSegCircle(self):
        Circle = self.canvas.currentCircle
        if self.predictor is None or self.current_img == '' or Circle == None or len(Circle.points) != 2:
            return
        img = cv2.imread(self.current_img)[:,:,::-1]
        rh, rw = img.shape[:2]
        
        c = Circle.points[0]
        r = Circle.points[0] - Circle.points[1]
        d = math.sqrt(math.pow(r.x(), 2) + math.pow(r.y(), 2))
        input_box = np.array([c.x() - d, c.y() - d, c.x() + d, c.y() + d])
        
        img, input_box, _ = self.transform_input(img, box=input_box)
        if self.image_encoded_flag == False:
            self.predictor.set_image(img)
            self.image_encoded_flag = True
        masks, iou_prediction, _ = self.predictor.predict(
            point_coords=None,
            point_labels=None,
            box=input_box[None, :],
            multimask_output=True,
        )
        masks = self.transform_output(masks.astype(np.uint8), (rh,rw))

        target_idx = np.argmax(iou_prediction)
        self.show_proposals(masks, 0)
        self.sam_mask_proposal = []
        for msk_idx in range(masks.shape[0]):
            mask = masks[msk_idx].astype(np.uint8)

            points_list = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)[0]
            shape_type = 'polygon'
            tmp_sam_mask = []
            for points in points_list:
                area = cv2.contourArea(points)
                if area < 100 and len(points_list) > 1:
                    continue
                pointsx = points[:,0,0]
                pointsy = points[:,0,1]

                shape = Shape(
                    label='Object',
                    shape_type=shape_type,
                    group_id=self.getMaxId() + 1,
                )
                for point_index in range(pointsx.shape[0]):
                    shape.addPoint(QtCore.QPointF(pointsx[point_index], pointsy[point_index]))
                shape.close()
                tmp_sam_mask.append(shape)
            if msk_idx == target_idx:
                self.sam_mask = tmp_sam_mask
            self.sam_mask_proposal.append(tmp_sam_mask)


    def clickManualSegBox(self):
        ClickPos = self.canvas.currentPos
        ClickNeg = self.canvas.currentNeg
        if self.predictor is None or self.current_img == '' or (ClickPos == None and ClickNeg == None):
            return
        img = cv2.imread(self.current_img)[:,:,::-1]
        rh, rw = img.shape[:2]

        input_clicks = []
        input_types = []
        if ClickPos != None:
            for pos in ClickPos:
                input_clicks.append([int(pos.x()), int(pos.y())])
                input_types.append(1)

        if ClickNeg != None:
            for neg in ClickNeg:
                input_clicks.append([int(neg.x()), int(neg.y())])
                input_types.append(0)
        if len(input_clicks) == 0:
            input_clicks = None
            input_types = None
        else:
            input_clicks = np.array(input_clicks)
            input_types = np.array(input_types)

        img, _, input_clicks = self.transform_input(img, points=input_clicks)

        if self.image_encoded_flag == False:
            self.predictor.set_image(img)
            self.image_encoded_flag = True
        masks, iou_prediction, _ = self.predictor.predict(
            point_coords=input_clicks,
            point_labels=input_types,
            multimask_output=True,
        )
        masks = self.transform_output(masks.astype(np.uint8), (rh,rw))
        
        target_idx = np.argmax(iou_prediction)
        self.show_proposals(masks,0)
        self.sam_mask_proposal = []
        
        for msk_idx in range(masks.shape[0]):
            mask = masks[msk_idx].astype(np.uint8)
            
            points_list = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)[0]
            shape_type = 'polygon'
            tmp_sam_mask = []
            for points in points_list:
                area = cv2.contourArea(points)
                if area < 100 and len(points_list) > 1:
                    continue
                pointsx = points[:,0,0]
                pointsy = points[:,0,1]

                shape = Shape(
                    label='Object',
                    shape_type=shape_type,
                    group_id=self.getMaxId() + 1,
                )
                for point_index in range(pointsx.shape[0]):
                    shape.addPoint(QtCore.QPointF(pointsx[point_index], pointsy[point_index]))
                shape.close()
                #self.addLabel(shape)
                tmp_sam_mask.append(shape)
            if msk_idx == target_idx:
                self.sam_mask = tmp_sam_mask
            self.sam_mask_proposal.append(tmp_sam_mask)
            
    def addSamMask(self):
        if len(self.sam_mask) > 0:
            label = 'Object'
            group_id = self.getMaxId() + 1
            if self.class_on_flag:
                xx = self.labelDialog.popUp(
                    text=label,
                    flags={},
                    group_id=group_id,
                )
                if len(xx) == 4:
                    label, _, group_id,_ = xx
                else:
                    label, _, group_id = xx
            if label == None:
                label = 'Object'
            if type(group_id) != int:
                group_id=self.getMaxId() + 1
            for sam_mask in self.sam_mask:
                sam_mask.label = label
                sam_mask.group_id = group_id
                self.addLabel(sam_mask)
        self.canvas.cancelDrawing()
        self.sam_mask = []
        self.sam_mask_proposal = []
        self.show_proposals()
        self.canvas.loadShapes([item.shape() for item in self.labelList])
        self.actions.save.setEnabled(True)
        self.actions.editMode.setEnabled(True)



    def cleanPrompt(self):
        self.canvas.cancelDrawing()
        self.sam_mask = []
        self.sam_mask_proposal = []
        self.show_proposals()
        self.canvas.setHiding()
        self.canvas.update()
        self.actions.editMode.setEnabled(True)



    def zoomRequest(self, delta, pos):
        canvas_width_old = self.canvas.width()
        units = 1.1
        if delta < 0:
            units = 0.9
        self.addZoom(units)

        canvas_width_new = self.canvas.width()
        if canvas_width_old != canvas_width_new:
            canvas_scale_factor = canvas_width_new / canvas_width_old

            x_shift = round(pos.x() * canvas_scale_factor) - pos.x()
            y_shift = round(pos.y() * canvas_scale_factor) - pos.y()

            self.setScroll(
                Qt.Horizontal,
                self.scrollBars[Qt.Horizontal].value() + x_shift,
            )
            self.setScroll(
                Qt.Vertical,
                self.scrollBars[Qt.Vertical].value() + y_shift,
            )

    def scrollRequest(self, delta, orientation):
        units = -delta * 0.1  # natural scroll
        bar = self.scrollBars[orientation]
        value = bar.value() + bar.singleStep() * units
        self.setScroll(orientation, value)

    def newShape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        items = self.uniqLabelList.selectedItems()
        text = None
        if items:
            text = items[0].data(Qt.UserRole)
        flags = {}
        group_id = None
        if not text:
            previous_text = self.labelDialog.edit.text()
            xx = self.labelDialog.popUp(text)
            if len(xx) == 4:
                text, flags, group_id, _ = xx
            else:
                text, flags, group_id = xx
            if not text:
                self.labelDialog.edit.setText(previous_text)

        if text and not self.validateLabel(text):
            self.errorMessage(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            text = ""
        if text:
            self.labelList.clearSelection()
            shape = self.canvas.setLastLabel(text, flags)
            shape.group_id = group_id
            self.addLabel(shape)
            self.actions.editMode.setEnabled(True)
            self.actions.undoLastPoint.setEnabled(False)
            self.actions.undo.setEnabled(True)
            self.setDirty()
        else:
            self.canvas.undoLastLine()
            self.canvas.shapesBackups.pop()

    def setDirty(self):
        # Even if we autosave the file, we keep the ability to undo
        self.actions.undo.setEnabled(self.canvas.isShapeRestorable)

        # if self._config["auto_save"] or self.actions.saveAuto.isChecked():
        #     label_file = osp.splitext(self.imagePath)[0] + ".json"
        #     if self.output_dir:
        #         label_file_without_path = osp.basename(label_file)
        #         label_file = osp.join(self.output_dir, label_file_without_path)
        #     self.saveLabels(label_file)
        #     return
        # self.dirty = True
        self.actions.save.setEnabled(True)
        # title = __appname__
        # if self.filename is not None:
        #     title = "{} - {}*".format(title, self.filename)
        # self.setWindowTitle(title)

    # React to canvas signals.
    def shapeSelectionChanged(self, selected_shapes):
        self._noSelectionSlot = True
        for shape in self.canvas.selectedShapes:
            shape.selected = False
        self.labelList.clearSelection()
        self.canvas.selectedShapes = selected_shapes
        for shape in self.canvas.selectedShapes:
            shape.selected = True
            item = self.labelList.findItemByShape(shape)
            self.labelList.selectItem(item)
            self.labelList.scrollToItem(item)
        self._noSelectionSlot = False
        n_selected = len(selected_shapes)
        self.actions.delete.setEnabled(n_selected)
        self.actions.duplicate.setEnabled(n_selected)
        self.actions.edit.setEnabled(n_selected == 1)
        # If we are in subtract mode and user selected a target, perform subtraction
        if getattr(self, 'subtract_mode', False):
            # require exactly one selected shape as target
            if n_selected == 1 and self.subtract_shape is not None:
                target = selected_shapes[0]
                # don't subtract from itself
                if target is not self.subtract_shape:
                    try:
                        self._perform_subtract(self.subtract_shape, target)
                    except Exception as e:
                        QMessageBox.warning(self, self.tr("Subtract"), self.tr(f"Subtract failed: {e}"))
                else:
                    QMessageBox.information(self, self.tr("Subtract"), self.tr("Cannot subtract a polygon from itself."))
            # reset mode
            self.subtract_mode = False
            self.subtract_shape = None
        # If we are in merge mode and user selected a target, perform merge
        if getattr(self, 'merge_mode', False):
            if n_selected == 1 and self.merge_shape is not None:
                target = selected_shapes[0]
                if target is not self.merge_shape:
                    try:
                        self._perform_merge(self.merge_shape, target)
                    except Exception as e:
                        QMessageBox.warning(self, self.tr("Merge"), self.tr(f"Merge failed: {e}"))
                else:
                    QMessageBox.information(self, self.tr("Merge"), self.tr("Cannot merge a polygon with itself."))
            self.merge_mode = False
            self.merge_shape = None
        # If we are in merge mode and user selected a target, perform merge
        if getattr(self, 'merge_mode', False):
            if n_selected == 1 and self.merge_shape is not None:
                target = selected_shapes[0]
                if target is not self.merge_shape:
                    try:
                        self._perform_merge(self.merge_shape, target)
                    except Exception as e:
                        QMessageBox.warning(self, self.tr("Merge"), self.tr(f"Merge failed: {e}"))
                else:
                    QMessageBox.information(self, self.tr("Merge"), self.tr("Cannot merge a polygon with itself."))
            self.merge_mode = False
            self.merge_shape = None

    def toggleDrawingSensitive(self, drawing=True):
        """Toggle drawing sensitive.

        In the middle of drawing, toggling between modes should be disabled.
        """
        self.actions.editMode.setEnabled(not drawing)
        # self.actions.undoLastPoint.setEnabled(drawing)
        # self.actions.undo.setEnabled(not drawing)
        # self.actions.delete.setEnabled(not drawing)
    def setScroll(self, orientation, value):
        self.scrollBars[orientation].setValue(int(value))
        self.scroll_values[orientation][self.current_img] = value

    def toolbar(self, title, actions=None):
        toolbar = self.addToolBar("%sToolBar" % title)
        # toolbar.setOrientation(Qt.Vertical)
        if actions:
            utils.addActions(toolbar, actions)
        return toolbar

    def setEditMode(self):
        self.toggleDrawMode(True)

    def toggleDrawMode(self, edit=True, createMode="polygon"):
        self.canvas.cancelDrawing()
        self.canvas.setEditing(edit)
        self.canvas.createMode = createMode
        if edit:
            self.actions.createMode.setEnabled(True)
            self.actions.createPointMode.setEnabled(True)
            self.actions.createRectangleMode.setEnabled(True)
            self.actions.createCircleMode.setEnabled(True)

        else:
            if createMode == "polygon":
                self.actions.createPointMode.setEnabled(True)
                self.actions.createMode.setEnabled(False)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)

            elif createMode == "point":
                self.actions.createMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(False)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
            elif createMode == "rectangle":
                self.actions.createMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(False)
                self.actions.createCircleMode.setEnabled(True)
            elif createMode == "circle":
                self.actions.createMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(False)

    def keyPressEvent(self, ev):
        # Allow cancelling subtract/merge modes with Esc
        try:
            key = ev.key()
        except Exception:
            return
        if key == Qt.Key_Escape:
            cancelled = False
            if getattr(self, 'subtract_mode', False):
                self.subtract_mode = False
                self.subtract_shape = None
                cancelled = True
            if getattr(self, 'merge_mode', False):
                self.merge_mode = False
                self.merge_shape = None
                cancelled = True
            if cancelled:
                QMessageBox.information(self, self.tr("Cancelled"), self.tr("Operation cancelled."))
            return
        # delegate other key events to base
        return super(MainWindow, self).keyPressEvent(ev)

    def validateLabel(self, label):
        return True

    def labelSelectionChanged(self):
        if self._noSelectionSlot:
            return
        if self.canvas.editing():
            selected_shapes = []
            for item in self.labelList.selectedItems():
                selected_shapes.append(item.shape())
            if selected_shapes:
                self.canvas.selectShapes(selected_shapes)
            else:
                self.canvas.deSelectShape()

    def iou(self, target_mask, mask_list):
        target_mask = target_mask.reshape(1,-1)
        mask_list = mask_list.reshape(mask_list.shape[0], -1)
        i = (target_mask * mask_list)
        u = target_mask + mask_list - i
        return i.sum(1)/u.sum(1)


    def polygon2mask(self,polygon, size):
        mask = np.zeros((size)) # h,w
        contours = np.array(polygon)
        mask = cv2.fillPoly(mask, [contours.astype(np.int32)],1)
        return mask.astype(np.uint8)

    def mask2polygon(self, mask):
        contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        contours = np.array(contours[0])
        return contours

    def _perform_subtract(self, source_shape, target_shape):
        # Convert Shape points to polygon arrays
        if source_shape is None or target_shape is None:
            return
        if source_shape.shape_type != 'polygon' or target_shape.shape_type != 'polygon':
            raise ValueError('Both shapes must be polygons')
        # build numpy polygons
        src_pts = np.array([[p.x(), p.y()] for p in source_shape.points])
        tgt_pts = np.array([[p.x(), p.y()] for p in target_shape.points])
        h, w = int(self.raw_h), int(self.raw_w)
        src_mask = self.polygon2mask(src_pts, (h, w))
        tgt_mask = self.polygon2mask(tgt_pts, (h, w))
        # (undo snapshot handled by canvas.loadShapes after modification)
        # subtract source from target
        new_mask = np.logical_and(tgt_mask > 0, np.logical_not(src_mask > 0)).astype(np.uint8)
        # if new_mask empty, remove target shape
        if new_mask.sum() == 0:
            # remove target from canvas and label list
            try:
                self.canvas.deleteShape(target_shape)
            except Exception:
                pass
            self.remLabels([target_shape])
            self.canvas.loadShapes([item.shape() for item in self.labelList])
            self.setDirty()
            return
        # convert mask back to polygons (keep all contours)
        contours = cv2.findContours(new_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)[0]
        if not contours:
            return
        # remove original target shape from canvas and label list
        try:
            self.canvas.deleteShape(target_shape)
        except Exception:
            pass
        self.remLabels([target_shape])
        # create new shapes from contours
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 1.0:
                continue
            pts = np.squeeze(cnt)
            if pts.ndim != 2:
                continue
            shape_obj = Shape(label=target_shape.label, shape_type='polygon', flags=target_shape.flags, group_id=target_shape.group_id)
            qt_points = [QtCore.QPointF(float(x), float(y)) for x, y in pts]
            shape_obj.points = qt_points
            shape_obj.close()
            shape_obj.fill = True
            self.addLabel(shape_obj)
        # refresh canvas and labels (this will also store shapes)
        self.canvas.loadShapes([item.shape() for item in self.labelList])
        self.setDirty()

    def _perform_merge(self, source_shape, target_shape):
        if source_shape is None or target_shape is None:
            return
        if source_shape.shape_type != 'polygon' or target_shape.shape_type != 'polygon':
            raise ValueError('Both shapes must be polygons')
        src_pts = np.array([[p.x(), p.y()] for p in source_shape.points])
        tgt_pts = np.array([[p.x(), p.y()] for p in target_shape.points])
        h, w = int(self.raw_h), int(self.raw_w)
        src_mask = self.polygon2mask(src_pts, (h, w))
        tgt_mask = self.polygon2mask(tgt_pts, (h, w))
        # (undo snapshot handled by canvas.loadShapes after modification)
        # union
        new_mask = np.logical_or(src_mask > 0, tgt_mask > 0).astype(np.uint8)
        if new_mask.sum() == 0:
            return
        contours = cv2.findContours(new_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)[0]
        if not contours:
            return
        # remove original shapes from canvas first
        try:
            self.canvas.deleteShape(source_shape)
        except Exception:
            pass
        try:
            self.canvas.deleteShape(target_shape)
        except Exception:
            pass
        # remove from label list
        self.remLabels([source_shape, target_shape])
        created = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 1.0:
                continue
            pts = np.squeeze(cnt)
            if pts.ndim != 2:
                continue
            shape_obj = Shape(label=source_shape.label, shape_type='polygon', flags=source_shape.flags, group_id=source_shape.group_id)
            qt_points = [QtCore.QPointF(float(x), float(y)) for x, y in pts]
            shape_obj.points = qt_points
            shape_obj.close()
            shape_obj.fill = True
            created.append(shape_obj)
            self.addLabel(shape_obj)
        self.canvas.loadShapes([item.shape() for item in self.labelList])
        self.setDirty()

    def editLabel(self, item=None):
        if item and not isinstance(item, LabelListWidgetItem):
            raise TypeError("item must be LabelListWidgetItem type")

        if not self.canvas.editing():
            return
        if not item:
            item = self.currentItem()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return
        xx = self.labelDialog.popUp(
            text=shape.label,
            flags=shape.flags,
            group_id=shape.group_id,
        )
        if len(xx) == 4:
            text, flags, group_id,_ = xx
        else:
            text, flags, group_id = xx
        if text is None:
            return
        if not self.validateLabel(text):
            self.errorMessage(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            return
        shape.label = text
        shape.flags = flags
        shape.group_id = group_id

        self._update_shape_color(shape)
        if shape.group_id is None:
            item.setText(
                '{} <font color="#{:02x}{:02x}{:02x}">●</font>'.format(
                    html.escape(shape.label), *shape.fill_color.getRgb()[:3]
                )
            )
        else:
            item.setText("({}) {}".format(shape.group_id, shape.label))
        self.setDirty()
        if self.uniqLabelList.findItemByLabel(shape.label) is None:
            item = self.uniqLabelList.createItemFromLabel(shape.label)
            self.uniqLabelList.addItem(item)
            # rgb = self._get_rgb_by_label(shape.label)
            rgb = self._get_rgb_by_label(shape.group_id)
            self.uniqLabelList.setItemLabel(item, shape.label, rgb)

    def labelItemChanged(self, item):
        shape = item.shape()
        self.canvas.setShapeVisible(shape, item.checkState() == Qt.Checked)

    def labelOrderChanged(self):
        self.setDirty()
        self.canvas.loadShapes([item.shape() for item in self.labelList])

    def addLabel(self, shape):
        if shape.group_id is None:
            text = shape.label
        else:
            text = "({}) {}".format(shape.group_id, shape.label)
        label_list_item = LabelListWidgetItem(text, shape)
        self.labelList.addItem(label_list_item)
        if self.uniqLabelList.findItemByLabel(shape.label) is None:
            item = self.uniqLabelList.createItemFromLabel(shape.label)
            self.uniqLabelList.addItem(item)
            # rgb = self._get_rgb_by_label(shape.label)
            rgb = self._get_rgb_by_label(shape.group_id)
            self.uniqLabelList.setItemLabel(item, shape.label, rgb)
        self.labelDialog.addLabelHistory(shape.label)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)

        self._update_shape_color(shape)
        label_list_item.setText(
            '{} <font color="#{:02x}{:02x}{:02x}">●</font>'.format(
                html.escape(text), *shape.fill_color.getRgb()[:3]
            )
        )
    def _get_rgb_by_label(self, label):
        label = str(label)
        item = self.uniqLabelList.findItemByLabel(label)
        if item is None:
            item = self.uniqLabelList.createItemFromLabel(label)
            self.uniqLabelList.addItem(item)
            rgb = self._get_rgb_by_label(label)
            self.uniqLabelList.setItemLabel(item, label, rgb)
        label_id = self.uniqLabelList.indexFromItem(item).row() + 1
        label_id += 0
        return LABEL_COLORMAP[label_id % len(LABEL_COLORMAP)]

    def togglePolygons(self, value):
        for item in self.labelList:
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def _update_shape_color(self, shape):
        # r, g, b = self._get_rgb_by_label(shape.label)
        r, g, b = self._get_rgb_by_label(shape.group_id)
        shape.line_color = QtGui.QColor(r, g, b)
        shape.vertex_fill_color = QtGui.QColor(r, g, b)
        shape.hvertex_fill_color = QtGui.QColor(255, 255, 255)
        shape.fill_color = QtGui.QColor(r, g, b, 128)
        shape.select_line_color = QtGui.QColor(255, 255, 255)
        shape.select_fill_color = QtGui.QColor(r, g, b, 155)

    def undoShapeEdit(self):
        self.canvas.restoreShape()
        self.labelList.clear()
        self.loadShapes(self.canvas.shapes)
        self.actions.undo.setEnabled(self.canvas.isShapeRestorable)

    def loadShapes(self, shapes, replace=True):
        self._noSelectionSlot = True
        for shape in shapes:
            self.addLabel(shape)
        self.labelList.clearSelection()
        self._noSelectionSlot = False
        self.canvas.loadShapes(shapes, replace=replace)


    def moveShape(self):
        self.canvas.endMove(copy=False)
        self.setDirty()

    def copyShape(self):
        self.canvas.endMove(copy=True)
        for shape in self.canvas.selectedShapes:
            self.addLabel(shape)
        self.labelList.clearSelection()
        self.setDirty()
    def deleteSelectedShape(self):
        #yes, no = QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No
        #msg = self.tr(
        #    "You are about to permanently delete {} polygons, "
        #    "proceed anyway?"
        #).format(len(self.canvas.selectedShapes))
        #if yes == QtWidgets.QMessageBox.warning(
        #    self, self.tr("Attention"), msg, yes | no, yes
        #):
        self.remLabels(self.canvas.deleteSelected())
        self.setDirty()
        if self.noShapes():
            for action in self.actions.onShapesPresent:
                action.setEnabled(False)
    def duplicateSelectedShape(self):
        added_shapes = self.canvas.duplicateSelectedShapes()
        self.labelList.clearSelection()
        for shape in added_shapes:
            self.addLabel(shape)
        self.setDirty()

    def reducePoint(self):
        # undo snapshot will be created by canvas.loadShapes after modifications
        def format_shape(s):
            data = s.other_data.copy()
            data.update(
                dict(
                    label=s.label.encode("utf-8") if PY2 else s.label,
                    points=[(p.x(), p.y()) for p in s.points],
                    group_id=s.group_id,
                    shape_type=s.shape_type,
                    flags=s.flags,
                )
            )
            return data
        shapes = self.current_img
        shapes = [format_shape(item.shape()) for item in self.labelList.selectedItems()]
        rm_shapes = [item.shape() for item in self.labelList.selectedItems()]
        self.remLabels(rm_shapes)
        for shape in shapes:
            points = shape['points']
            min_dis = self.get_min_dis(points)
            points_new = [points[0]]
            for i in range(1,len(points)):
                d = math.sqrt((points[i][0] - points_new[-1][0]) ** 2 + (points[i][1] - points_new[-1][1]) ** 2)
                if d > (min_dis * 1.5):
                    points_new.append(points[i])
            shape['points'] = points_new
        #self.labelList.clear()
        for tmp_shape in shapes:
            shape = Shape(
                label=tmp_shape['label'],
                shape_type=tmp_shape['shape_type'],
                group_id=tmp_shape['group_id'],
            )
            for point_index in range(len(tmp_shape['points'])):
                shape.addPoint(QtCore.QPointF(tmp_shape['points'][point_index][0], tmp_shape['points'][point_index][1]))
            shape.close()
            self.addLabel(shape)
            tmp_item = self.labelList.findItemByShape(shape)
            self.labelList.selectItem(tmp_item)
            self.labelList.scrollToItem(tmp_item)
        self.canvas.loadShapes([item.shape() for item in self.labelList])
        self.actions.save.setEnabled(True)

    def get_min_dis(self, points):
        min_dis = 10000
        if len(points) >= 2:
            points_new = [points[0]]
            for i in range(1,len(points)):
                d = math.sqrt((points[i][0] - points_new[-1][0]) ** 2 + (points[i][1] - points_new[-1][1]) ** 2)
                min_dis = min(min_dis, d)
                points_new.append(points[i])
        return min_dis



    def pasteSelectedShape(self):
        self.loadShapes(self._copied_shapes, replace=False)
        self.setDirty()

    def copySelectedShape(self):
        self._copied_shapes = [s.copy() for s in self.canvas.selectedShapes]
        self.actions.paste.setEnabled(len(self._copied_shapes) > 0)

    def currentItem(self):
        items = self.labelList.selectedItems()
        if items:
            return items[0]
        return None

    def remLabels(self, shapes):
        for shape in shapes:
            item = self.labelList.findItemByShape(shape)
            self.labelList.removeItem(item)


    def noShapes(self):
        return not len(self.labelList)

    def addZoom(self, increment=1.1):
        zoom_value = self.zoomWidget.value() * increment
        if increment > 1:
            zoom_value = math.ceil(zoom_value)
        else:
            zoom_value = math.floor(zoom_value)
        self.setZoom(zoom_value)

    def setZoom(self, value):
        self.zoomMode = self.MANUAL_ZOOM
        self.zoomWidget.setValue(value)
        self.zoom_values[self.current_img] = (self.zoomMode, value)

    def paintCanvas(self):
        self.canvas.scale = 0.01 * self.zoomWidget.value()
        self.canvas.adjustSize()
        self.canvas.update()

    # ── Brightness / Contrast ────────────────────────────────────────────────

    def _on_bc_slider_changed(self):
        """Update slider labels immediately; debounce the actual pixel update."""
        bv = self.brightness_slider.value()
        cv = self.contrast_slider.value()
        self.brightness_label.setText(f"Bright\n{bv:+d}")
        self.contrast_label.setText(f"Contrast\n{cv / 100:.1f}\u00d7")
        # Restart the 80 ms debounce timer
        self._bc_timer.start(80)

    def applyBrightnessContrast(self):
        """Apply current slider values to a copy of the raw pixmap.

        Uses cv2.convertScaleAbs (CPU-only, <5 ms on typical images).
        The raw pixmap and the SAM encoding are never modified.
        """
        if self._raw_pixmap is None or self._raw_pixmap.isNull():
            return

        brightness = self.brightness_slider.value()   # –100 … +100
        contrast   = self.contrast_slider.value() / 100.0  # 0.1 … 3.0

        # Convert QPixmap → numpy (RGB)
        qimg = self._raw_pixmap.toImage().convertToFormat(QtGui.QImage.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        ptr  = qimg.bits()
        ptr.setsize(h * w * 3)
        img  = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 3)).copy()

        # Apply:  output = clip(contrast × pixel + brightness)
        adjusted = cv2.convertScaleAbs(img, alpha=contrast, beta=brightness)

        # Convert back to QPixmap
        adj_qimg = QImage(adjusted.data, w, h, w * 3, QImage.Format_RGB888)
        adj_pixmap = QPixmap.fromImage(adj_qimg)

        # clear_shapes=False → swap the background image only, keep all polygons
        self.canvas.loadPixmap(adj_pixmap, clear_shapes=False)
        self.canvas.update()

    def resetBrightnessContrast(self):
        """Snap both sliders back to neutral (brightness=0, contrast=1.0×)."""
        self.brightness_slider.setValue(0)
        self.contrast_slider.setValue(100)
        # applyBrightnessContrast fires automatically via the debounce timer


def get_parser():
    parser = argparse.ArgumentParser(description="pixel annotator by GroundedSAM")
    parser.add_argument(
        "--app_resolution",
        default='1000,1600',
    )
    parser.add_argument(
        "--model_type",
        default='vit_b',
    )
    parser.add_argument(
        "--keep_input_size",
        type=bool,
        default=True,
    )   
    parser.add_argument(
        "--max_size",
        default=720,
    )   
    return parser

if __name__ == '__main__':
    parser = get_parser()
    global_h, global_w = [int(i) for i in parser.parse_args().app_resolution.split(',')]
    model_type = parser.parse_args().model_type
    keep_input_size = parser.parse_args().keep_input_size
    max_size = parser.parse_args().max_size
    app = QApplication(sys.argv)
    main = MainWindow(global_h=global_h, global_w=global_w, model_type=model_type, keep_input_size=keep_input_size, max_size=max_size)
    main.show()
    sys.exit(app.exec_())
