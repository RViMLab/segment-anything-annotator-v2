# CT/MRI DICOM folders (#74)

Close the app, activate your usual environment, and run from the app folder:

```powershell
git switch feat/dicom-series-import
python -m pip install -r requirements-dicom.txt
python scripts/create_dicom_test_data.py
python annotator.py --dicom-directory .manual-test-data-dicom --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

The optional readers are already installed in this machine's `test_env`. The
generator creates two nonclinical, uncompressed series and never overwrites
nonempty folders. Their filenames/InstanceNumber deliberately reverse spatial
order. The CT uses rescaled intensities; the MR uses a different intensity range.

1. The series chooser should offer CT and MR with six slices each. Cancel once:
   the previous dataset should remain. Reopen through **Open DICOM**, select CT,
   then choose a fresh **Save Directory**, such as `output_dicom_manual`.
2. Check the panel identifies a DICOM volume, native slice index and orientation.
   Use Ctrl+mouse wheel to zoom into the small toy. PgUp/PgDown/J should navigate
   in spatial order. The middle region's brightness increases through the stack
   despite reversed filenames. Adjust Window centre/width in rescaled units.
3. Annotate using Manual Polygons or Load SAM/Box Prompt, label and Save. Try
   class/group ID 0, holes/subtraction, small objects, visibility, and Undo as
   usual. Navigate away/back, then close/reopen the same series/output: geometry,
   labels and class IDs should reload under `DICOM_<series-hash>_<content-hash>`.
4. Optionally run STCN as in the [slice-propagation checklist](MANUAL_TEST_VOLUME_PROPAGATION.md):
   select reference objects, explicitly choose STCN and direction, Track selected,
   advance and Propagate. Inspect, correct and Save. It remains experimental.
5. Export a NIfTI mask. Check the bundle contains `segmentation.nii.gz` and
   `segmentation.json`; missing slices should trigger the usual warning. The
   mask uses class ID + 1, and the sidecar's DICOM section lists ordered SOP
   instance UIDs. Each slice JSON has its own SOP UID. No patient demographics
   or private headers should appear in the output. Originals stay unchanged.
6. Open MR from the same root: it should use a different annotation folder and
   clear tracking memory. Opening `.manual-test-data-dicom/CT_series` directly
   should skip the chooser because it contains one series. The optional CLI
   `--dicom-series UID` uses the full UID shown by the generator/chooser.
7. Return to ordinary Image Directory, Video Directory and NIfTI Open Volume.
   Their normal editing/navigation/tracking controls should still work. F1
   should explain the DICOM scope and NIfTI export.

Start with synthetic data before trying a representative local CT/MRI folder.
This version rejects compressed pixels, enhanced/multiframe or mosaic images,
duplicate instances/positions, missing geometry and nonregular/mixed grids.
Errors must preserve the current annotations and dataset. Test rejection only
on disposable copies; do not delete or edit real scan slices to provoke errors.

This is an annotation workflow, not a diagnostic DICOM viewer. It starts from
a consistent global intensity range and does not apply embedded VOI/presentation
LUT presets. No DICOM SEG/RTSTRUCT output or native volume review is implemented.
