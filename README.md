# Segment Anything Annotator

A PyQt desktop application for pixel-level image annotation with Meta's
[Segment Anything Model (SAM)](https://github.com/facebookresearch/segment-anything).
Generate masks from point, box, or circle prompts; refine them as polygons; and
save annotations in Labelme-compatible JSON files.

> This project uses the original SAM models (`vit_b`, `vit_l`, and `vit_h`), not
> SAM 2.

<p align="center">
  <img src="demo.gif" alt="Segment Anything Annotator demo" width="720">
</p>

## Features

- SAM-assisted segmentation using positive/negative points, boxes, and circles
- Manual polygon creation and vertex editing
- Multiple mask proposals
- Category and object ID annotation
- Merge and subtract polygon operations
- Polygon simplification
- Hide/show controls for all polygons
- Brightness and contrast preview controls
- Jump-to-image dialog and keyboard navigation
- Labelme-compatible JSON output
- Optional STCN-based video annotation workflow
- CUDA, Apple MPS, and CPU device selection

## Quick start

### 1. Create an environment

Python 3.8 or newer is required. A virtual environment is recommended.

Windows PowerShell:

```powershell
python -m venv annotator_env
.\annotator_env\Scripts\Activate.ps1
```

Linux or macOS:

```bash
python3 -m venv annotator_env
source annotator_env/bin/activate
```

### 2. Install PyTorch

Install the build appropriate for your operating system and accelerator using
the [official PyTorch installer](https://pytorch.org/get-started/locally/).

For a CPU-only installation:

```bash
python -m pip install torch torchvision
```

### 3. Install the application dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Start the image annotator

```bash
python annotator.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

The `--app_resolution` value is `height,width`.

| Argument | Description |
| --- | --- |
| `--model_type` | SAM checkpoint type: `vit_b`, `vit_l`, or `vit_h` |
| `--keep_input_size` | Keep the original image size for SAM when `True` |
| `--max_size` | Maximum input dimension when resizing is enabled |

## SAM checkpoints

Click **Load SAM** to download the selected checkpoint automatically. The
checkpoint is saved in the repository root as `vit_b.pth`, `vit_l.pth`, or
`vit_h.pth`.

You can instead download a checkpoint manually from the
[official SAM repository](https://github.com/facebookresearch/segment-anything#model-checkpoints)
and place it in the repository root using the corresponding filename.

`vit_b` is the smallest and fastest option. `vit_l` and `vit_h` require more
memory but use larger model backbones.

## Image annotation workflow

1. Click **Category File** and select a text file containing one category per
   line, such as `categories.txt`.
2. Click **Image Directory** and select a folder containing `.jpg` or `.png`
   images.
3. Click **Save Directory** and select the output folder.
4. Click **Load SAM**.
5. Select a prompt mode and annotate the image.
6. Choose one of the mask proposals and click **Accept**.
7. Edit the resulting polygon if needed, then save the annotation.

The application writes one Labelme-compatible JSON file per image.

### Prompt and editing controls

- **Point Prompt:** left-click for positive points and right-click for negative
  points.
- **Box Prompt:** draw a bounding box around the object.
- **Circle Prompt:** draw a circular prompt around the object.
- **Manual Polygons:** click along the object boundary to create a polygon.
- **Edit Polygons:** select and move polygon vertices. Arrow keys nudge the
  selected polygon.
- **Merge Polygons:** select a source polygon, activate Merge, then select the
  target.
- **Subtract Polygons:** select the polygon to subtract, activate Subtract, then
  select the target.

## Image annotator shortcuts

| Shortcut | Action |
| --- | --- |
| `Shift+I` | Choose image directory |
| `Shift+L` | Choose save directory |
| `Page Up` | Previous image |
| `Page Down` | Next image |
| `J` | Jump to an image |
| `N` or `Ctrl+W` | Manual polygon mode |
| `P` | Point prompt mode |
| `B` | Box prompt mode |
| `C` | Circle prompt mode |
| `A` | Accept the selected proposal |
| `R` | Reject proposals and clear prompts |
| `1`–`4` | Select a mask proposal |
| `E` | Edit polygon mode |
| Arrow keys | Nudge a selected polygon |
| `D` | Delete selected polygons |
| `H` | Hide/show all polygons |
| `M` | Merge polygons |
| `Shift+S` | Subtract polygons |
| `Shift+R` | Reduce polygon points |
| `U` | Undo the last point |
| `Ctrl+U` | Undo the last shape edit |
| `S` | Save |
| `Alt+S` | Save as |
| `Ctrl` + mouse wheel | Zoom |
| `Esc` | Cancel an active merge or subtract operation |

## Video annotation

Video annotation additionally requires
[STCN](https://github.com/hkchengrex/STCN) and its `stcn.pth` checkpoint:

```text
segment-anything-annotator-v2/
├── STCN/
├── stcn.pth
├── annotator_video.py
└── ...
```

Organize extracted video frames as:

```text
video_folder/
├── video_1/
│   ├── 00000.jpg
│   ├── 00001.jpg
│   └── ...
└── video_2/
    └── ...
```

Start the video annotator with:

```bash
python annotator_video.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720 --max_size_STCN 600
```

Annotate the first frame with SAM, select objects with `Ctrl` + left-click, add
them to memory, and use **Propagate** on subsequent frames.

| Shortcut | Video action |
| --- | --- |
| `N` | Next frame |
| `B` | Previous frame |
| `E` | Edit mode |
| `A` | Accept proposal |
| `R` | Reject proposal |
| `D` | Delete |
| `S` | Save |
| `Space` | Propagate |
| `1`–`3` | Select a mask proposal |

## Platform notes

### Windows

- Use a current graphics driver and the matching PyTorch build for CUDA.
- PowerShell may require permission to activate a virtual environment. See
  Microsoft's documentation for `Set-ExecutionPolicy` if activation is blocked.
- The application also runs on CPU when CUDA is unavailable.

### macOS

- Apple Silicon systems use PyTorch's MPS backend when it is available.
- The application falls back to CPU if MPS is unavailable.

### Linux: Qt `xcb` plugin error

This project uses `opencv-python-headless` because the GUI is provided by
PyQt5. The headless OpenCV package avoids a conflict between OpenCV's bundled
Qt plugins and PyQt5's `xcb` plugin.

Older versions of this project also installed `metaseg`, which depends on the
GUI-enabled OpenCV package. When updating an existing environment, remove that
unused dependency and both OpenCV variants before reinstalling:

```bash
python -m pip uninstall -y metaseg opencv-python opencv-python-headless
python -m pip install -r requirements.txt
```

As a temporary workaround without reinstalling, point Qt to PyQt5's plugins:

```bash
export QT_PLUGIN_PATH="$(python -c 'import PyQt5, pathlib; print(pathlib.Path(PyQt5.__file__).parent / "Qt5" / "plugins")')"
```

If `xcb` still fails after using the headless OpenCV package, install the Qt/XCB
system libraries supplied by your Linux distribution.

## Project history and acknowledgement

This repository is based on
[haochenheheda/segment-anything-annotator](https://github.com/haochenheheda/segment-anything-annotator).
It builds on
[Meta Segment Anything](https://github.com/facebookresearch/segment-anything),
[Labelme](https://github.com/wkentaro/labelme), and
[STCN](https://github.com/hkchengrex/STCN).

See [LICENSE](LICENSE) for licensing information.
