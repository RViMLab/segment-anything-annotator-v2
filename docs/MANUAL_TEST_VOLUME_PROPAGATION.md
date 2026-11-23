# Experimental NIfTI slice propagation (#72)

Use the same activated `test_env`. The NIfTI reader, STCN code and checkpoint
are already installed on this machine. Other machines need the README's volume
and optional STCN prerequisites. Close the app before switching branches:

```powershell
git switch feat/nifti-slice-propagation
python scripts/create_volume_test_data.py
python annotator.py --volume .manual-test-data-volume/toy_volume.nii.gz --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

1. Choose a **fresh Save Directory**, such as `output_volume_tracking_manual`.
   The Slice propagation panel should say experimental. Use Ctrl+mouse wheel to
   enlarge the small toy scan. Go to slice **index 2** (shown as slice **3/6**).
2. Manually annotate an object, or Load SAM and accept a proposal. Save. In Edit
   mode, Ctrl-select its polygon parts. Explicitly select **STCN (experimental
   slices)** and **Increasing slice index (PgDown)**, then **Track selected**.
   Selecting no backend should give guidance. Same-class independent objects
   can use No at the grouping question; multipart objects use Yes. Different
   classes can track together. Check **Tracking N object(s)**.
3. **PgDown** to index 3; press **Space / Propagate slice**. Inspect the
   suggestion and Save. Class IDs must remain the same. The prediction need
   not perfectly match this synthetic scan; this is a workflow/geometry check.
4. Edit the result, click **Use correction**, advance to index 4 and propagate
   again. Save. If an object has vanished, Use correction must explain that it
   needs annotation parts; Stop tracking and initialize the remaining objects.
5. On an annotated slice, propagate again and **Cancel** replacement. Existing
   annotations must remain. Unrelated annotations must survive a confirmed
   propagation. Ctrl+U should restore annotations/provenance and stop tracking.
6. **Stop tracking**, return to saved index 2, select the objects, choose
   **Decreasing slice index (PgUp)**, and **Track selected**. PgUp to index 1,
   propagate, inspect and Save; optionally correct and continue to index 0.
   A slice on the wrong side of the current reference must be refused. Stop
   and reinitialize to change direction; running direction controls are locked.
7. Apply a different **Window centre/width**: annotations should save/reload
   normally, while tracking stops and asks for reinitialization. Open a different
   volume, image folder or video folder: model memory must not carry across.
   Existing ordinary video tracking should still work with frame captions and
   without the volume direction controls.
8. Export the NIfTI mask as usual. The sidecar should include
   `slice_tracking_provenance` with direction `1` or `-1`, native reference slice
   indices, source hash and display range. Shape/affine and the group-ID-plus-one
   export mapping must remain unchanged. Never-saved slices are still explicitly
   unannotated. Model predictions must not be marked as reviewed automatically.
9. Save, close and reopen the same volume/output. Polygons, IDs and provenance
   should reload, but STCN must be explicitly selected and initialized again.
   F1 should explain experimental volume propagation and direction changes.

STCN is video-trained; medical accuracy and suitable correction frequency still
need evaluation on representative scans. This PR makes no accuracy claim.
