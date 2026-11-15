# Segment Anything Annotator & Reviewer

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/RViMLab/segment-anything-annotator-v2)](https://github.com/RViMLab/segment-anything-annotator-v2/releases/latest)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21726097.svg)](https://doi.org/10.5281/zenodo.21726097)

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
- Optional dataset-specific class names filled from numeric group IDs
- Merge and subtract polygon operations
- Polygon simplification
- Hide/show controls for all polygons
- Brightness, contrast, and colour-inversion preview controls
- Jump-to-image dialog and keyboard navigation
- Labelme-compatible JSON output
- Resumable annotation review sessions with timing and audit metadata
- Original/reviewed JSON, polygon geometry, and raster-mask comparison
- Duplicate-safe CSV review export
- Optional video tracking in the same GUI, with sequence-safe outputs and review
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

## Class names from group IDs

Use **Class mapping** in the toolbar to define group IDs and class names for
your dataset, for example `3 → forceps`. New setups enable mapping by default;
enter the rows and click **Apply mapping**. Editing a disabled setup also
re-enables the mapping. To return to free-form labels, uncheck **Use mapping**
and click **Use free-form labels**.
When creating a polygon, accepting SAM results, or editing a label, enter an ID
or select a class: its name is filled automatically. Undefined IDs cannot be
confirmed. ID `0` is supported.

Click **Category File** to load a text file with one class name per line. The
app opens an editable mapping preview before using the proposed IDs:

- If every name has a numeric prefix, such as `7_forceps` or `1_retina`, use
  those numbers as proposed IDs. Names are kept exactly as written; edit the
  name in the preview if you want to remove its prefix.
- Otherwise propose IDs in file order, starting at `0`. Names are not sorted;
  blank lines are skipped. These are suggestions, not inferred dataset IDs.
- Check and edit the IDs before **Apply mapping**, especially for an existing
  dataset. Duplicate IDs and empty names must be corrected before applying.
- Cancel keeps the active mapping unchanged. The loaded text names are still
  available as suggestions when mapping is disabled. **Class mapping → Load…**
  also accepts category text files and mapping JSON files.

### Keep names and IDs consistent throughout a dataset

1. At the start, load the dataset's category text file and review its proposed
   mapping. For an existing dataset, match the IDs already used in its
   annotations/downstream tasks; for a new dataset, agree on IDs before drawing.
2. **Save…** the reviewed mapping as a separate file such as `classes.json`,
   then **Apply mapping** to activate it. Saving exports the setup; applying
   activates it. The toolbar shows **Class mapping ✓** when mapping is active.
3. Use the mapped class list or enter the ID for each manual polygon, SAM
   acceptance, or label edit. Undefined IDs cannot be confirmed. Keep one
   approved name per ID and avoid changing the mapping midway through a dataset.
4. When restarting or resuming on another device, load the same `classes.json`
   through **Class mapping → Load…**, review it, and **Apply mapping**. Mappings
   are not restored automatically on startup. Reusing the JSON preserves the
   reviewed IDs even if the category text file is reordered later.
5. When changing datasets, load its mapping or explicitly disable mapping.
   Mappings apply throughout the current app session, including review mode;
   there is no universal meaning for a particular numeric ID. Keep the mapping
   JSON with the dataset's supporting files and share it with collaborators.

Loading a mapping does not relabel existing annotations. Their names change
only when you confirm a label edit. Existing class-name consistency warnings
still check imported/older annotations: choose **Review names** to investigate
conflicts rather than repeatedly saving inconsistent names. If you deliberately
change a class definition, review existing annotations too; changing the setup
does not migrate them. Mapping JSON files use this format:

```json
{"version": 1, "classes": [{"group_id": 0, "label": "background"}, {"group_id": 3, "label": "forceps"}]}
```

## SAM checkpoints

Click **Load SAM** to download the selected checkpoint automatically. The
checkpoint is saved in the repository root as `vit_b.pth`, `vit_l.pth`, or
`vit_h.pth`.

Load the model before choosing Point, Box, or Circle Prompt. If you choose one
of these tools first (including P/B/C), the app asks you to click **Load SAM**
and keeps your current mode and unfinished drawing unchanged. Manual polygons
and construction shapes do not require SAM.

You can instead download a checkpoint manually from the
[official SAM repository](https://github.com/facebookresearch/segment-anything#model-checkpoints)
and place it in the repository root using the corresponding filename.

`vit_b` is the smallest and fastest option. `vit_l` and `vit_h` require more
memory but use larger model backbones.

## Image annotation workflow

1. For a new dataset, click **Category File**, select a text file containing
   one category per line, and review the proposed IDs before **Apply mapping**.
   For a resumed dataset, load its approved `classes.json` through
   **Class mapping → Load…** instead. See the consistency practices above.
2. Click **Image Directory** and select a folder containing `.jpg` or `.png`
   images.
3. Click **Save Directory** and select the output folder.
4. Click **Load SAM**.
5. Select a prompt mode and annotate the image.
6. Choose one of the mask proposals and click **Accept**.
7. Edit the resulting polygon if needed, then save the annotation.

The application writes one Labelme-compatible JSON file per image.

If no save directory was selected, the first Save asks **“No output folder
selected. Save to the app's output folder?”** Choose a folder, confirm **Use
default**, or cancel while keeping your edits open. The default is the
`output` directory beside `annotator.py`, created on startup and recreated
when needed. The confirmed choice is used for the rest of that session.
Changing the save directory after editing preserves unsaved polygons. Default
output is ignored by Git; deleting its contents is safe only when those files
are no longer needed. Review mode uses its configured output directory.

### Prompt and editing controls

- **Point Prompt:** left-click for positive points and right-click for negative
  points.
- **Box Prompt:** draw a bounding box around the object.
- **Circle Prompt:** draw a circular prompt around the object.
- **Manual Polygons:** click along the object boundary to create a polygon.

Point predictions appear as raster previews while you add clicks; polygon
conversion runs only when you click **Accept**, so intermediate thin or complex
predictions do not interrupt each click with conversion dialogs. SAM predictions
are suggestions: a single point may be ambiguous, and a negative point does not
guarantee the exact cut-out that a geometric subtraction provides.

**Point prompts: keep clicked regions**, below Invert colours, is enabled by
default. It previews only connected foreground regions containing a positive
click, excluding disconnected speckles while preserving holes. Add a positive
click in each desired disconnected region, or turn the option off to preview
all predicted regions. Toggling refreshes existing proposals without rerunning
SAM; previews show the mask that will be converted on acceptance. Negative-only
prompts and box/circle prompts retain all predicted regions. The status bar
reports filtered pixels. Empty predictions can be refined without a popup.

The controls below apply to manual drawing and polygon editing:

- **Undo last point (U):** remove the newest vertex from an unfinished manual
  polygon. The control becomes available after the first vertex and disables
  after completion, cancellation, or changing frames/modes. It does not remove
  SAM prompt clicks; **Ctrl+U** undoes completed shape edits.
- **Edit Polygons:** select and move polygon vertices. Arrow keys nudge the
  selected polygon.
- **Merge Polygons:** select a source polygon, activate Merge, then select the
  target.
- **Subtract Polygons:** select the polygon to subtract, activate Subtract, then
  select the target.

### Preserving annotation JSON

Loading and saving an existing annotation retains its version, flags,
descriptions, unknown metadata, image references, and ordered shape coordinates,
including repeated vertices. Missing standard image fields are filled when
saving; JSON whitespace and number formatting may change. Empty shape records
are retained in the file without being drawn. Newly created annotations use
the usual embedded image data and default fields.

Labels such as `"0"`, `"01"`, and `"-1"` are treated as literal text by default.
For older annotations that intentionally store nonnegative category indices,
launch with **`--legacy-label-indices`** to explicitly map those labels through
the current `categories.txt` order. Out-of-range and negative values stay
literal. Saving then writes the displayed labels; use a copied dataset or
separate review output when converting legacy files. An unedited **OK** decision
still copies the original JSON and does not convert labels by itself.

This preserves data that exists in the loaded file; it cannot reconstruct
metadata or vertices already removed by earlier saves. Geometry-changing tools
such as Reduce Points, merge, and subtract are tracked separately in
[#36](https://github.com/RViMLab/segment-anything-annotator-v2/issues/36).

### Geometry-changing operations

Merge, Subtract, and Reduce Points preview native-resolution pixel/region/hole
counts and vertex counts before asking whether to apply a change. Cancel leaves
the annotations unchanged. Undo restores geometry and metadata after applying.

The JSON format stores independently filled polygons. Holes from SAM, Merge,
or Subtract are preserved by splitting the result into ordinary filled polygon
parts whose combined mask leaves the holes empty. Parts share the class name,
group ID, flags, and metadata; they remain separate entries in Polygon Labels.
For example, a donut-shaped object is saved as **two or more polygon
annotations** around the empty centre. The number of parts depends on its
geometry; they collectively represent the holed object. There is no special
hole record, new JSON schema, or change to class-ID meaning.

SAM asks for confirmation before accepting a mask with holes. Conversion of
the selected preview must preserve every pixel in both OpenCV and PIL masks.
Small regions are retained unless explicitly excluded by the visible point-region
filter. If a selected mask cannot be represented exactly, or requires too many
parts, **Accept** explains why and leaves its preview/prompts available for
refinement. Other proposals remain selectable. Existing annotations are never
silently changed or automatically repaired.

To create a donut with **Subtract**, select the small inner cutter first,
activate Subtract, then select the large outer target and confirm. The target
becomes polygon parts surrounding the hole. **The cutter remains a separate
annotation:** delete it afterwards if it was only a temporary cutting tool.
Hiding its checkbox affects the view only; it does not remove it from saved
JSON/masks. Keeping a same-class cutter would fill the hole in that class's
combined mask; keeping a different-class cutter assigns that area to its class.

To move a donut-shaped object, **hold Ctrl and click each of its parts in
Polygon Labels**, then drag any selected part on the image. All selected parts,
and therefore the hole, move together. Editing one part moves/changes only
that part, and partition boundaries can appear as seams. Keep all parts with
the same class identity; downstream consumers should fill/union every polygon
of that class rather than treat each entry as a separate object instance.
Ordinary Labelme-style filled-polygon rasterization needs no special hole rule.
Save/reopen and Ctrl+U work with the parts. A ring cannot become one ordinary
filled polygon simply by merging its parts; the hole-preserving result still
uses multiple parts.

Each saved polygon has one point list, so it cannot describe both an outer
boundary and a separate inner boundary in one simple polygon. A compound
editable object would need an additional representation and object-linking
support; class/group IDs cannot provide that link because several independent
objects can share the same class. This feature preserves holes using compatible
parts rather than changing what existing JSON readers understand.

Reduce Points is blocked if it would remove a region, change holes, or leave
fewer than three vertices. Other pixel changes require explicit confirmation.

Merge requires matching labels, object IDs, flags, descriptions, and other
shape metadata. It also blocks merging across intervening overlapping shapes
that could change draw order. Deliberately align metadata or order first when
that is your intent. Existing annotation files are not migrated or rewritten.

### Image display controls

**Show labels** replaces the old Class On/Off button. Uncheck it to hide
polygon names and group/object-ID text while keeping outlines and vertex
handles visible and editable. This preference stays active when moving between
frames and does not change saved annotations. Accepting a SAM proposal always
opens the label/group dialog, whether labels are shown or hidden.

Press a digit **0–9** to toggle every polygon with that **group/object ID**
(not its class label or category-list position). For example, **H** hides all
polygons, then **3** shows object 3; another **3** hides it again. If part of an
object is visible, its digit hides the whole object. Digits with no matching
object do nothing. On image navigation, polygons start visible as usual.
These shortcuts work in annotation and review mode, and leave numeric typing
in text fields and dialogs alone. While SAM proposals are active, **1–3**
select **Proposal 1–3**, corresponding to SAM results 0–2, instead of toggling
objects. **0 and 4–9** still toggle objects. Accepting/rejecting proposals or
changing frames restores all digits to object visibility. There are three
proposal buttons labelled **1**, **2**, and **3**, disabled when no proposals
are active. Previews preserve the source image aspect ratio, including after
window resizing. Each card reserves a separate area for its larger, bold digit
so the caption stays readable beside the image in maximized windows.

Use **Invert colours** below **Reset B/C** to toggle a colour-negative preview,
for example when inspecting difficult endolaser frames. Inversion applies after
brightness and contrast and stays active when navigating between frames. Click
it again to restore the normal colours. **Reset B/C** resets the two sliders
only and leaves the inversion toggle unchanged.

These controls are available in annotation and review mode. They affect the
preview only; source images, saved image data, polygons, and SAM input stay
unchanged.

### Class-name consistency warnings

Before saving or leaving a completed frame, the app compares current names and
numeric group IDs with saved annotations for the loaded dataset. Review mode
prefers a reviewed JSON for each frame, falling back to its original. The check
also catches multiple names for one ID within the current image. Names are
compared case-sensitively after trimming surrounding whitespace; no saved text
is changed by the check.

Warnings show up to three example filenames and, only when needed, the number
of other images. **Review names** keeps the current frame/edits open and stops
the pending save or departure. **Save anyway** saves the entered values without
renaming or changing IDs. An unchanged acknowledged conflict is not repeated;
changed relevant names are checked again. Large scans run in a cancellable
worker and cache names/IDs only. Unreadable annotations are reported explicitly.

This is a warning, not an enforced class-name mapping or automatic labeling.
The synthetic-data generator and complete branch-by-branch test checklist are
in [docs/MANUAL_TEST_PENDING.md](docs/MANUAL_TEST_PENDING.md).

## Annotation review mode

Review mode reuses the image annotator and polygon canvas to inspect existing
Labelme JSON annotations. Original annotations are treated as read-only input;
all reviewed JSON files, session state, and audit exports are written to a
separate output directory.

The application uses the original SAM models for interactive segmentation.
The `SAM2 propagated frame` option described below is provenance metadata for
annotations generated by a separate SAM2 propagation workflow.

### Prepare the review directories

Create three separate directories:

```text
dataset/
|-- images/
|   |-- sequence-1/
|   |   |-- 000001.jpg
|   |   |-- 000002.jpg
|   |   `-- 000003.jpg
|-- original-json/
|   `-- sequence-1/
|       |-- 000001.json
|       `-- 000003.json
`-- reviewed-json/
```

The review output directory must already exist and must not be the original
annotation directory or a directory inside it. Using a separate output
directory per reviewer is recommended when reviewers work concurrently.

Images and annotations are discovered recursively. Supported images are
`.jpg`, `.jpeg`, and `.png`. They are matched by their case-insensitive relative
path without the extension; for example,
`images/sequence-1/000001.jpg` matches
`original-json/sequence-1/000001.json`.

Images without matching JSON files are reported as warnings and remain
available as view-only temporal context. Orphan JSON files, duplicate relative
keys, invalid JSON, malformed polygon points, unreadable images, and dimension
mismatches are also reported during validation. Errors block the session;
warnings can be reviewed and accepted.

### Start a review session

```bash
python annotator.py --review --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

The startup dialog requests:

- reviewer ID (required);
- reviewer role (optional and remembered for the next session);
- default provenance for newly created review targets;
- image directory;
- original annotation directory;
- reviewed annotation output directory.

The fields can be prefilled from the command line:

```bash
python annotator.py --review \
  --reviewer-id "reviewer-01" \
  --reviewer-role "grader" \
  --review-images "/path/to/images" \
  --review-annotations "/path/to/original-json" \
  --review-output "/path/to/reviewed-json"
```

Use quoted Windows paths in PowerShell or Git Bash when a directory contains
spaces.

| Review argument | Description |
| --- | --- |
| `--review` | Open the review-session configuration dialog |
| `--reviewer-id` | Prefill the required reviewer identifier |
| `--reviewer-role` | Prefill the optional reviewer role |
| `--review-images` | Prefill the image directory |
| `--review-annotations` | Prefill the read-only original JSON directory |
| `--review-output` | Prefill the reviewed JSON and session-output directory |

### Review workflow

1. Validate the directories and accept any understood warnings.
2. Inspect the image and its loaded annotation. A previously reviewed JSON in
   the output directory takes precedence when a session is resumed.
3. Optionally edit polygons manually or load SAM for prompt-assisted changes.
4. Select the annotation provenance.
5. Add an optional problem status or reviewer note.
6. Record one decision:
   - **No change:** discard unsaved edits and copy the original JSON exactly;
   - **Minor correction:** save the current annotation as a reviewed JSON;
   - **Major correction:** save the current annotation as a reviewed JSON;
   - **Unable to review:** record the outcome without requiring a new JSON.
7. The app saves the audit record and advances to the next unfinished review
   target.
8. Use **Finish review session** only when the session should no longer resume.

Closing the application does not complete a session. Notes, provenance, timer
state, decisions, and current progress are persisted in SQLite. Reopening the
same reviewer and directory configuration resumes the active session at the
first in-progress or unreviewed target. A completed session is never resumed;
the same configuration starts a new session instead.

### Timing and navigation

The active timer starts automatically on an annotated review target. **Pause**
and **Resume** exclude interruptions, while **Reset timer** resets only the
current target after confirmation. Context images pause the timer automatically
and disable review decisions.

Decision shortcuts submit the displayed decision, save or copy the annotation,
and advance. Navigation shortcuts never complete a target. Shortcuts are
suppressed while typing in notes or another editable field.

| Control | Review-mode action |
| --- | --- |
| `Page Up` / **Last Image** | Previous image, including context images |
| `Page Down` / **Next Image** | Next image, including context images |
| `J` / **Jump** | Select any image by index or filename |
| `K` | No change / OK; save and advance |
| `M` | Minor correction; save and advance |
| `L` | Major correction; save and advance |
| `O` | Unable to review; record and advance |
| `Space` | Pause or resume the active review timer |
| `Alt+Left` / **Previous target** | Previous matched target; navigation only |
| `Alt+Right` / **Next target** | Next matched target; navigation only |
| **Export review CSV** | Rewrite the current session CSV from SQLite |

The progress display counts annotation targets only, not view-only context
images. `Reviewed` includes the four explicit decisions, `Opened but undecided`
means `in_progress`, and `Not yet opened` means `unreviewed`. After at least five
completed targets, the approximate remaining time uses the median completed
target time so long interruptions do not dominate the estimate.

### Provenance categories

| Category | Meaning |
| --- | --- |
| `Unknown / legacy` | Source provenance is unavailable |
| `Manual keyframe` | Annotation was created manually on a selected keyframe |
| `SAM2 propagated frame` | Annotation came from an external SAM2 propagation step |
| `Reviewed propagated frame` | A propagated annotation was reviewed or corrected |

Provenance is stored per review target and can be changed when revisiting an
item. The configuration-dialog default is applied only to new targets; resumed
targets preserve their stored per-item values.

### Change detection and audit files

Every completed decision records:

- decision status and active review time;
- reviewer ID, role, notes, and problem status;
- original and reviewed JSON SHA-256 hashes;
- whether the exact JSON file changed;
- whether polygon geometry changed;
- whether the rasterised foreground mask changed;
- annotation provenance;
- start, completion, creation, and update timestamps;
- original, reviewed, and image paths.

Geometry comparison ignores polygon-list order, polygon start-point rotation,
and reversed polygon direction. The exact JSON hash still detects formatting,
metadata, label, or path changes. Raster comparison detects changes to the
combined foreground pixels independently of JSON formatting.

Review mode creates these files in the review output directory:

```text
reviewed-json/
|-- review_session.sqlite3
|-- review_session_<session-uuid>.csv
`-- sequence-1/
    |-- 000001.json
    `-- 000003.json
```

SQLite is the authoritative resumable record. The session-specific CSV is
rewritten atomically at session startup, after each decision, on manual export,
and when the session is completed. Repeated exports update existing rows rather
than appending duplicates. The CSV also retains inactive history if the dataset
changes during an active session.

Close the CSV in Excel while reviewing. Windows may lock an open CSV and block
replacement; the app will warn about the failed export while preserving the
SQLite record.

### Review data safety

- Never use the original JSON directory as the review output.
- Back up both the reviewed JSON files and `review_session.sqlite3`.
- Do not edit the SQLite database manually while the annotator is running.
- Keep reviewer output directories separate unless shared reviewed JSON files
  are explicitly intended.
- Use **Finish review session** deliberately; merely closing the app preserves
  the active session for resumption.
- Finishing a partial session leaves `in_progress` and `unreviewed` statuses
  unchanged but prevents that session from resuming automatically.

### Class-aware review comparison

Review decisions retain the existing `raster_mask_changed` binary-silhouette
check and add `class_mask_changed`, `class_mask_error`, and `class_mask_policy`
to the database/CSV. Classes use **numeric group IDs**, local to the dataset;
human-readable label names do not define the downstream class. ID `0` is a
valid class, separate from background. Integer strings (including leading
zeros) and integer-valued numbers are equivalent without rewriting source JSON.

The policy compares both per-class coverage (including regions hidden by
another class) and visible composition, where later shapes in the polygon list
win overlaps. Shapes are filled independently; groups and nested rings do not
imply holes. No global class-name ontology is assumed. A nonempty shape with
an unassigned/invalid numeric ID makes this check unavailable: the result is
blank and the reason is recorded in `class_mask_error`, rather than falsely
reporting no class change. The existing geometry/silhouette checks still run.

Old review records retain blank new fields until another decision is recorded.
Review databases migrate additively from schema 1 to 2 without changing existing
decisions, notes, or annotations. **Use a copied review output/database when
testing this PR:** older app versions cannot reopen a schema-2 database. The
comparison policy is recorded alongside each newly computed result.

## Image annotator shortcuts

| Shortcut | Action |
| --- | --- |
| `Shift+I` | Choose image directory |
| `Shift+L` | Choose save directory |
| `Page Up` | Previous image |
| `Page Down` | Next image |
| `J` | Jump to an image/frame |
| `N` or `Ctrl+W` | Manual polygon mode |
| `P` | Point prompt mode |
| `B` | Box prompt mode |
| `C` | Circle prompt mode |
| `A` | Accept the selected proposal |
| `R` | Reject proposals and clear prompts |
| `1`–`3` | Select Proposal 1–3 while SAM proposals are active |
| `0`–`9` | Hide/show the matching group/object ID (1–3 select active SAM proposals first) |
| `E` | Edit polygon mode |
| Arrow keys | Nudge a selected polygon |
| `D` | Delete selected polygons |
| `H` | Hide/show all polygons |
| `Shift+M` | Merge polygons |
| `Shift+S` | Subtract polygons |
| `Shift+R` | Reduce polygon points |
| `U` | Undo the last point |
| `Ctrl+U` | Undo the last shape edit |
| `S` | Save |
| `Alt+S` | Save as |
| `Ctrl` + mouse wheel | Zoom |
| `Esc` | Cancel an active merge or subtract operation |

## Video annotation

Video annotation now uses **the same GUI** as image annotation: the same class
mapping, polygon/hole editing, display controls, saving, Undo, and shortcuts.
Click **Video Directory** in the toolbar, or launch with video controls visible:

```powershell
python .\annotator.py --video --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720 --max-size-stcn 600
```

You can preselect the supplied demo using `--video-directory .\demo_video` or
`--video-directory .\demo_video\kunkun_00000_15_59`. The old
`python annotator_video.py ...` command is a compatibility launcher for this same
GUI; `--max_size_STCN` remains an alias for `--max-size-stcn`. There is no separate
legacy shortcut layout. Adding `--review` to that launcher opens ordinary
frame-by-frame review instead of tracking mode.

### Optional tracking prerequisites

Normal image annotation and review do **not** require STCN. To enable the STCN
tracking option, install the normal annotator dependencies and a compatible
PyTorch 2.x/torchvision pair, then add [STCN](https://github.com/hkchengrex/STCN) and its official
checkpoint beside `annotator.py`:

```text
segment-anything-annotator-v2/
├── STCN/
├── stcn.pth
├── annotator.py
└── ...
```

From the application folder, with the intended Python environment activated:

```powershell
git clone https://github.com/hkchengrex/STCN.git STCN
python -m pip install -r requirements-video.txt
python -c "import gdown; gdown.download(id='1mRrE0uCI2ktdWlUgapJI_KmgeIiF2eOm', output='stcn.pth', quiet=False)"
```

Clone/download only if those items are missing. `gdown` is needed for this
download, not for runtime inference. STCN's initial construction may also fetch
its ResNet backbone weights if they are not already cached. Its training and
standalone evaluation packages are not required by this GUI. Keep the project's
headless OpenCV dependency; do not replace it with a second Qt-enabled OpenCV.

Choose **STCN (optional)** explicitly in the video panel before **Track selected**.
It loads on demand, using CUDA/MPS if available to the active PyTorch build,
otherwise CPU. CPU-only PyTorch remains supported. SAM is needed only if you use
SAM to create annotations; manually drawn polygons can seed STCN without loading
SAM. Missing tracking files produce setup instructions and leave annotations intact.

The real CPU integration check used Python 3.13.9, PyTorch 2.13.0+cpu, and
torchvision 0.28.0+cpu. Keep PyTorch and torchvision versions compatible with
each other and the chosen device rather than changing a working environment
just to enable the optional controls.

STCN is an implemented option, **not a quality recommendation or automatic
default**. SAM 2/3 are not tracking backends in this release. Select a preferred
backend only after evaluating specific models on representative data and the
same hardware; parameter count alone does not establish speed, memory, or
annotation accuracy.

### Frame layout and output

Choose a folder directly containing extracted JPG/JPEG/PNG frames, or a parent
with one frame folder per clip. Use zero-padded filenames so alphabetical order
matches time. Compressed MP4/AVI files must first be extracted into frames.

```text
video_folder/
├── video_1/
│   ├── 00000.jpg
│   ├── 00001.jpg
│   └── ...
└── video_2/
    └── ...
```

Use **Save Directory** to select one output root. The app writes
`output_root/video_1/00000.json`, etc., so equal frame names in different
sequences cannot overwrite one another. Duplicate frame stems within a sequence
(such as `00000.jpg` and `00000.png`) are rejected. Selecting the output directory
before the video is supported; omitting it uses the normal default-output
confirmation on first save.

### Annotate, track, correct

1. Open **Video Directory**, select the clip using the video-panel sequence list,
   and choose the output folder. Load/reuse the approved class mapping for the
   dataset. Annotate the reference frame with SAM or Manual Polygons, assigning
   numeric class/group IDs as usual.
2. In Edit mode, Ctrl-select annotated objects in **Polygon Labels** or on the
   image. Choose a backend and click **Track selected**. This initializes the
   reference automatically; there is no separate memory-bank step.
3. If several same-class polygons are selected, the app asks whether they are
   parts of **one object** (Yes, for example donut parts) or **separate objects**
   (No). Different-class objects remain separate. Selecting a part of an already
   tracked object includes its other parts.
4. Press **Page Down** to advance, then **Space** or **Propagate frame** to predict
   the tracked objects on that frame. Inspect and save with **S**. Existing
   tracked annotations require replacement confirmation; unrelated annotations
   are kept, so check for duplicates. No other frame is changed by propagation.
5. To improve tracking, edit the current tracked polygons and click **Use
   correction**. It adds that frame as a reference for subsequent frames,
   retaining the initial reference and up to four recent corrections to bound
   memory. Correcting an earlier frame discards future references. Every
   tracked object must have annotation parts on a correction frame. To change
   the object set, select the desired annotations and use **Track selected** again.
6. Use **Page Up/Page Down** and **J** for navigation. Forward jumps use reference
   memory instead of an accidental future-frame prediction. To track from an
   earlier frame, initialize a reference there first. Changing sequence or opening
   an ordinary image directory stops tracking.

Tracking loads/processes individual frames rather than the whole clip. Model
work runs off the UI thread; editing controls remain locked during each model
step. Geometry conversion preserves holes and every displayed mask pixel in
OpenCV/PIL; unsupported thin/complex output is rejected without modifying
annotations or accepting that prediction into tracker memory.

**Class/group ID is still the class.** Tracking uses a separate `video_object_id`
extra field, so two forceps of the same class do not become one object. Generated
polygon parts share their object's tracking ID, class, label, flags, and custom
metadata. Duplicate Polygons / Copy here give copied objects new tracking IDs
while keeping their class IDs; copying an object must not silently link it to
the original. Hole parts are unioned for tracking, not XOR-filled. A `video_annotation`
record stores frame provenance/reference information for review; consumers may
ignore these extra fields and rasterize ordinary polygons as before.

**Ctrl+U** undoes annotation changes, including propagation. Undo stops the
active tracker to avoid using a reverted reference; select the desired objects
and **Track selected** to restart. Saved annotations/IDs persist, but tracker
memory does not: after restarting the app, load the saved frame and initialize
tracking again. **Use correction** is not an undoable history of model states.

| Shortcut | Image and video action |
| --- | --- |
| `Page Down` / `Page Up` | Next / previous image or frame |
| `J` | Jump within the current image/frame list |
| `N` / `Ctrl+W` | New manual polygon |
| `B` | SAM box prompt |
| `P` / `C` | SAM point / circle prompt |
| `E`, `A`, `R`, `S`, `Ctrl+U` | Edit, accept SAM, reject SAM, save, undo |
| `1`–`3` | Select active SAM proposals; otherwise normal class visibility |
| `Space` | Propagate to the current video frame when tracking is active |

### Reviewing video outputs

Use the ordinary **`--review`** workflow, without `--video`; STCN is not needed
to review saved annotations. For a sequence-parent image root, choose the video
output root as original annotations, and a separate reviewed-output directory.
Relative sequence/frame paths pair the files safely across clips. If choosing a
single frame folder instead, choose its corresponding annotation subfolder.

```powershell
python .\annotator.py --review --review-images .\demo_video --review-annotations .\output_STCN_unified_manual --review-output .\review_STCN_unified_manual
```

Create/select the separate reviewed folder before validating the session.
New review records infer manual-keyframe or STCN-propagated provenance from the
saved video metadata; legacy files use the configured default (which now also
offers **STCN propagated frame**). Existing review records retain their audit
values when resumed. Decisions, timing, name checks, geometry/class-mask
comparison, and CSV export work as for images. Original JSONs remain untouched.
Propagation and sequence switching are disabled in review: corrections and
decisions apply to individual reviewed frames rather than silently changing
other targets.

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

## Tests

Run the complete automated test suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

The tests cover review path validation, resumable SQLite storage, JSON and
geometry comparison, raster-mask comparison, provenance, duplicate-safe CSV
export, application icon assets, and the complete review audit workflow.

## Citation

If you use Segment Anything Annotator & Reviewer in your research, please cite
the specific software version used. The citation for version 1.0.0 is:

```bibtex
@software{namour_2026_21726098,
  author       = {Namour, Adriana and
                  Bergeles, Christos},
  title        = {Segment Anything Annotator \& Reviewer},
  month        = jul,
  year         = 2026,
  publisher    = {Zenodo},
  version      = {v1.0.0},
  doi          = {10.5281/zenodo.21726098},
  url          = {https://doi.org/10.5281/zenodo.21726098},
}
```

For other releases, use the repository's **Cite this repository** link or the
[Zenodo record for all versions](https://doi.org/10.5281/zenodo.21726097).

## Project history and acknowledgement

This repository is based on
[haochenheheda/segment-anything-annotator](https://github.com/haochenheheda/segment-anything-annotator).
It builds on
[Meta Segment Anything](https://github.com/facebookresearch/segment-anything),
[Labelme](https://github.com/wkentaro/labelme), and
[STCN](https://github.com/hkchengrex/STCN).

See [LICENSE](LICENSE) for licensing information.
