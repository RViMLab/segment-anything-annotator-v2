# Annotating 3D volumes (NIfTI/DICOM) — EXPERIMENTAL

This guide is for your own medical scans. Install the app using
[INSTALL.md](../INSTALL.md) first, then run the commands below from the app folder
with your Python environment activated.

**Medical-volume use is experimental.** Import/export and editing have automated
checks and synthetic-data tests; they have not been clinically validated.
SAM works on individual displayed slices, and STCN propagation is an optional,
video-trained suggestion tool. Inspect the results for your dataset. The app is
an annotation tool, not a diagnostic DICOM viewer.

## 1. Check the input and install its optional reader

| Input | Supported now | Install command |
| --- | --- | --- |
| NIfTI | Scalar 3D `.nii` or `.nii.gz` | `python -m pip install -r requirements-volume.txt` |
| DICOM folder | Classic, uncompressed single-frame grayscale CT/MR slices on a regular grid; at least two spatial slices | `python -m pip install -r requirements-dicom.txt` |

Python 3.10 or newer is required for these optional readers. The DICOM install
includes the NIfTI reader. Image annotation does not need STCN; propagation
additionally requires the [STCN code/checkpoint setup](../README.md#optional-tracking-prerequisites).

Not supported: 4D/time-series volumes, vector/color volumes, enhanced or
multiframe DICOM, Siemens mosaics, compressed DICOM pixels, arbitrary irregular
stacks, native volume review, or DICOM SEG/RTSTRUCT output.

Keep your source scan unchanged during annotation. For DICOM, keep the complete
acquisition together; subfolders are searched automatically. Do not rename,
delete, or edit slices to get around an import error. Choose a separate output
folder, and keep the original scan alongside your annotation backups.

The app does not anonymize scans. Editable JSON embeds slice previews, and
DICOM outputs retain source UIDs for traceability. Treat these outputs as scan
data even though patient demographics and private DICOM headers are not copied.

Allow temporary disk space: `.nii.gz` needs an unpacked copy and previews;
DICOM uses roughly eight bytes per voxel for its backing volume, plus previews.
The current limit is 256 million voxels and 10,000 slices. Temporary files are
removed when leaving volume mode or closing normally; they are not your saved
annotations.

## 2. Open your scan

Replace the quoted example paths with your actual locations. Windows paths can
use forward slashes, for example `"C:/scans/case_001/scan.nii.gz"`; on macOS/Linux
use a path such as `"/home/you/scans/case_001/scan.nii.gz"`.

**NIfTI:** click **Open Volume**, or run:

```bash
python annotator.py --volume "/path/to/scan.nii.gz" --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

**DICOM:** click **Open DICOM**, or run:

```bash
python annotator.py --dicom-directory "/path/to/dicom-folder" --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

For multiple DICOM series, choose the intended acquisition using its modality,
series number/description, slice count and UID. A single series opens directly.
For repeatable CLI selection, add `--dicom-series "FULL_SERIES_UID"` to the DICOM
command. Slices are sorted by spatial position, **not filenames or InstanceNumber**.

Choose **Save Directory** explicitly. Load your approved dataset class mapping,
or review the proposed mapping when loading a Category File. Use consistent
numeric class/group IDs throughout the dataset.

## 3. Understand the view and set the window

The panel shows the source, orientation codes and native slice index. The view
uses the stored third voxel axis (**axis 2**); it is not necessarily an anatomical
axial view. There is no axial/coronal/sagittal plane selector, radiological
reorientation, or 3D rendering.

The canvas shows native pixels with square display pixels. Non-square physical
spacing can therefore make anatomy look stretched; physical spacing/orientation
are preserved in the export rather than used to reformat the preview.

- **Page Down / Page Up:** next/previous native slice.
- **J:** jump to a slice. Indices start at zero: index 2 is shown as slice 3/N.
- **Ctrl+mouse wheel:** zoom; this does not change annotation coordinates.

Set **Window centre/width**, then click **Apply display window** before starting
model-assisted work. DICOM values use the modality-rescaled units (often HU for
CT); MR values are not assumed to have standardized quantitative units. The
initial display uses the volume's global range, not the scan's embedded vendor
window/VOI presets. MONOCHROME1 display polarity is handled by the importer.

Applying the window updates the model-input previews consistently, saves pending
edits through the normal save gates, and stops active tracking. Original scan
intensities stay unchanged. **Brightness, Contrast and Invert colours** are
canvas-only previews; they do not change the cached SAM/STCN input window.

## 4. Annotate and save slices

1. Use **New polygon (N)** for manual contours, or **Load SAM** followed by a
   prompt such as **Box prompt (B)**. Select proposal **1–3**, then **Accept (A)**
   and confirm its class/group ID. SAM predictions require inspection on medical
   images; a plausible preview does not establish accuracy.
2. Use **Edit polygons (E)** to adjust vertices or move selected parts. Holes
   use two or more filled polygon parts. Ctrl-select those parts to move them
   together. A shared class ID alone does not link individual objects.
3. **Save (S)**. Navigation uses the usual save gates; if saving fails, resolve
   the error before continuing. **U** undoes an unfinished polygon vertex;
   **Ctrl+U** undoes completed edits and stops active tracking.

Hiding polygons with **H**, digits, or checkboxes does not remove them from saved
annotations or exported masks. After subtraction, delete a temporary cutter if
it should not remain in the annotation. Overlapping classes follow list order:
the last polygon wins where masks overlap.

## 5. Optional STCN propagation — experimental

Annotate a reference slice where the targets can be identified, then:

1. In Edit mode, Ctrl-select all objects/parts to propagate. Choose **STCN** and
   increasing or decreasing slice index, then **Track selected**. Different
   classes can track together. If asked about matching same-class polygons,
   **Yes** combines parts of one object; **No** keeps independent objects separate.
2. Move **PgDown** for increasing indices or **PgUp** for decreasing indices,
   then **Space / Propagate slice**. Inspect, correct and Save each result.
3. Click **Use correction** after editing a slice to make it a reference for
   later predictions in that direction. Every tracked object needs nonempty
   annotation parts on a correction slice. If a target disappears, stop and
   reinitialize the remaining object set; do not assume the model knows when
   anatomical structures should end.
4. For the other direction, **Stop tracking**, return to a suitable annotated
   reference, change direction, select the objects and **Track selected** again.

Each direction starts a fresh model session. Applying a new input window,
changing volume, or Undo stops tracking. Source changes block reuse. Saved
annotations retain instance IDs and provenance, but reopening does not restore
model memory. Prediction provenance does not mark a slice as reviewed.

## 6. Export a mask and check alignment

Click **Export NIfTI mask**, then select an export parent folder. It creates a
new bundle containing both:

- `segmentation.nii.gz`: the native-grid label volume.
- `segmentation.json`: class mapping, source geometry/identity, saved and
  unannotated slice indices, and available tracking provenance. DICOM exports
  also include source SOP instance UIDs in slice order.

**Mask value = class/group ID + 1.** Zero is reserved for background/unannotated
voxels. For example, class ID 0 exports as 1, and class ID 3 exports as 4.
Editable slice JSON keeps the original class IDs. Keep the sidecar with the
mask and use its mapping in downstream tasks.

Never-saved slices are zero-filled and listed as **unannotated**, with a GUI
confirmation before export. Zero does not prove that these slices contain no
target. Saving a slice after deliberately clearing its annotations records a
saved empty slice. Neither saving nor exporting certifies completeness or review.

The export retains the source grid and spatial mapping. DICOM patient LPS
coordinates are represented in NIfTI RAS coordinates; regular tilt is retained
in the sform. On the first case of a dataset, open the mask alongside its source
in your usual volume viewer and check overlay alignment, left/right orientation,
slice correspondence and class values before processing more cases.

The app exports **NIfTI**, including for DICOM inputs. It does not write DICOM
SEG or RTSTRUCT, and `--review` cannot currently review native medical volumes.
Inspect/correct them in the volume annotation UI.

## 7. Resume and troubleshoot

Reopen the **same source file or DICOM series**, choose the same Save Directory,
and navigate to saved slices. JSON files reload from the app-managed
source-identity folder. Converting/recompressing a scan can create a different
source identity; annotations are not automatically transferred between sources.

Back up the original scan/series, the editable output folder, approved class
mapping and any exported mask/sidecar bundles. Temporary PNG paths may change;
slice JSON embeds its preview, but those previews do not replace the original
high-bit-depth scan.

| Problem | Action |
| --- | --- |
| Missing optional reader | Activate the app's environment and install the appropriate requirements file above. |
| DICOM mixed planes, duplicate positions or irregular spacing | Select one acquisition/echo/time point, or obtain a correctly prepared regular 3D input. Do not alter geometry tags just to bypass the error. |
| Compressed, enhanced/multiframe or mosaic DICOM | This importer does not support it. Prepare a supported copy with appropriate imaging software and verify its geometry before annotating. |
| Source changed or annotations do not match it | Reopen the correct unchanged source/series and output folder; do not force JSON into another source's folder. |
| Export rejects polygons or class IDs | Correct the reported annotation; export requires valid polygons and nonnegative integer class IDs. |

For keyboard shortcuts and common editing questions, press **F1** or click
**Help (F1)** inside the annotator. The searchable help window can stay open
while you work.
