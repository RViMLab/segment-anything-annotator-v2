# Polygon list drag and merge checks (#57)

Close the annotator before switching branches:

```powershell
git switch fix/flat-polygon-drops
python .\annotator.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

Use disposable images/annotations and select an explicit Save Directory.
No SAM inference is needed. The existing synthetic test dataset can be used,
but use a fresh copy of its annotations for these checks.

1. Create two overlapping polygons with the same group ID, label, and metadata.
   Drag one entry onto the **centre** of the other entry in Polygon Labels.
   Choose **No**: both entries and polygons must remain unchanged. Repeat and
   dismiss the popup with its close button: this must also cancel.
2. Repeat and choose **Yes**: the polygons become their combined pixel area.
   Press **Ctrl+U**: both original polygons must return. Repeat the merge,
   save, and reopen the frame: the merged annotation must persist.
3. Try a centre drop with different group IDs. Expect an explanation and no
   changes. Repeat with the same ID but no overlapping pixels. Both entries
   must remain visible in the list, and their visibility checkboxes must work.
4. Try overlapping polygons with the same ID but different labels or metadata.
   The merge must be blocked to avoid discarding information. Existing checks
   also block unions with holes and merges across intervening overlapping rows.
5. Drag an entry to the **top or bottom edge** of another row, following the
   horizontal insertion line: entries must reorder without a merge popup.
   Check overlap order on the image, save/reopen, and test Ctrl+U after another
   reorder. No entry should disappear or become nested.
6. Select several entries and drop between rows: their relative order must
   remain intact. Dropping several entries onto a row centre must explain that
   only two annotations can be merged, leaving all entries intact.
7. Drop an entry onto itself or outside the list: nothing should change.

Class identity means the numeric group ID, including ID 0. A merge additionally
requires matching labels/metadata, and always asks before changing annotations.
The toolbar's existing Merge Polygons action retains its existing behaviour.
