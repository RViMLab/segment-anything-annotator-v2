# NIfTI volume annotation (#70)

Use synthetic data first; the script never overwrites existing files. Close the
annotator, activate your usual environment, and run from the app folder:

```powershell
git switch feat/nifti-volume-annotation
python -m pip install -r requirements-volume.txt
python scripts/create_volume_test_data.py
python annotator.py --volume .manual-test-data-volume/toy_volume.nii.gz --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

1. Choose a fresh **Save Directory** (for example `output_nifti_manual`). The
   volume panel should show six native-axis-2 slices and the voxel-axis codes.
   The large object has a hole and a separate bright single pixel. This is a
   slice viewer in stored voxel order, not a radiological/anatomical reorientation.
   The toy is deliberately small; use **Ctrl+mouse wheel** over the canvas to zoom.
2. Draw a manual polygon with **N**, or Load SAM and try **B**. Accept and label
   normally. For a precise hole test, use the usual manual subtraction workflow
   and delete the temporary cutter. Save with **S**. Hidden polygons are saved too.
3. **PgDown/PgUp/J** navigate slices. Edits should save through the usual gates.
   Return to confirm the polygon/class ID and hole remain. Undo/edit/visibility
   should work as in image annotation. Check the slice JSON under
   `<output>/<volume-name>_<source-hash>/slice_00000.json`.
4. Change **Window centre/width** in scan units, then click **Apply display window**.
   Existing edits should save first and remain aligned. The scan file must stay
   untouched. The source voxel values are not replaced by the 8-bit preview.
5. Save several slices. Click **Export NIfTI mask**; if some slices were never
   saved, read and cancel the warning first. Repeat and continue, selecting an
   export parent folder. A new bundle should contain `segmentation.nii.gz` and
   `segmentation.json`. Never-saved slices are listed explicitly in the sidecar.
6. Inspect the sidecar: background is 0; **mask value = group ID + 1**. In
   particular, class ID 0 must export as value 1. Saved JSON class IDs stay unchanged.
   Last polygon in the list wins at overlaps; visibility does not remove it.
7. Close/reopen the **same** `.nii.gz` and choose the same output directory.
   Return to saved slices: annotations should reload. Temporary PNG paths may
   change; embedded images and volume metadata remain in JSON. Opening the
   uncompressed `.nii` is also supported but has a different file-content hash,
   so it deliberately uses a separate output folder.
8. Open ordinary Image Directory, then Video Directory. Existing modes and
   shortcuts should behave normally; volume controls disappear. Try an invalid
   `.nii` or unsupported 4D NIfTI: the currently open dataset should remain.

Optional export geometry check, after replacing the bundle path below:

```powershell
python -c "import nibabel as n, numpy as p; a=n.load('.manual-test-data-volume/toy_volume.nii.gz'); b=n.load('PATH_TO_EXPORT_BUNDLE/segmentation.nii.gz'); print(a.shape, b.shape); print('Affine matches:', p.allclose(a.affine,b.affine)); print('qform matches:', p.allclose(a.get_qform(),b.get_qform())); print('sform matches:', p.allclose(a.get_sform(),b.get_sform()))"
```

4D/vector data, alternate viewing planes and native volume review remain
unsupported. For CT/MRI DICOM folders use the [DICOM checklist](MANUAL_TEST_DICOM.md).
For optional experimental STCN slice propagation, use the separate
[propagation checklist](MANUAL_TEST_VOLUME_PROPAGATION.md). No real patient data is supplied.
