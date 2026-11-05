# Manual checks before merging the pending PRs

Close the annotator **before every branch switch**. Use your normal activated
Python environment in the repository folder. No SAM model loading/inference is
needed for these checks. The scripts below create synthetic data, not clinical
annotations. Do not commit the generated data.

## 1. Prepare disposable test data once

```powershell
git status --short
git switch feat/class-name-consistency-warning
python scripts/create_manual_test_data.py --output .manual-test-data
```

The script refuses to overwrite an existing directory. If you already generated
it, keep using it or choose a fresh name such as `.manual-test-data-2` and use
that name throughout these instructions.

The `images` folder has six synthetic frames, `manual_001.png` to `manual_006.png`.
Each original annotation has a large cat/ID 3 polygon, a smaller cat/ID 3 polygon
inside it, and an overlapping dog/ID 4 polygon. Copies for the warning and
geometry checks can be edited freely. Keep `original-annotations` untouched.
The generated directories survive branch switching because they are local data.

For each normal-mode test, launch:

```powershell
python .\annotator.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

In normal mode, **Save Directory also determines where existing JSONs are
loaded from**. Unless testing the no-folder flow explicitly, choose the stated
Save Directory first, then Image Directory `.manual-test-data/images`.

## 2. Class-name warning (#55)

```powershell
git switch feat/class-name-consistency-warning
```

1. Launch normally. Choose Save Directory `warning-two-annotations`, then Image
   Directory `images` inside `.manual-test-data`.
2. Go to `manual_002.png`. Edit each of its two ID 3 polygons: rename `cat` to
   `dog`, leaving ID 3 unchanged. Use Edit Label/the polygon list; do not change
   geometry. Both ID 3 shapes must be renamed for this cross-image-only test.
3. Click Save. The warning should cite **one image**, `manual_001.png`, where
   ID 3 is `cat`. There should be no “other images” suffix.
4. Choose **Review names**: remain on the same frame, with edits intact, and
   the old JSON unchanged. Try Next, Last/Previous, or Jump (answer Yes to save
   before jumping): Review names must also stop the pending departure.
5. Choose **Save anyway**. The entered names/IDs should save unchanged. Next
   should not repeat the same acknowledged warning. A different conflicting
   name or a changed name in a saved peer should produce a new warning.
6. On a clean/saved frame, switch Save Directory to `warning-many-annotations`.
   Use `manual_002.png` and rename both ID 3 shapes to `dog` again. Save should
   cite **up to three** peer filenames and **2 other images**: five other frames
   contain `cat` for ID 3. Count images, not the two polygons in each image.
7. For a same-image conflict, leave one ID 3 shape as `cat` and rename only the
   other to `dog`. The warning must explicitly identify different names in the
   current image too. Review names and Save anyway never rename anything.
8. Optionally repeat through Save As or review mode (a separate `warning-review`
   output is provided). In review mode, reviewed JSON takes precedence over
   the original for each peer frame.

The initial scan of a large real dataset can take time. Its progress dialog is
cancellable; cancelling keeps edits open and prevents the pending save/departure.
The warning does not implement a class-name/ID mapping or automatic labeling.

## 3. Output confirmation (#51 / PR #52)

```powershell
git switch fix/confirm-default-output
```

1. Launch normally. Choose **only** Image Directory `.manual-test-data/images`.
   Do not select Save Directory. Use a frame without a previous default-output
   test JSON. Draw and finish a manual polygon with N.
2. Click Save. Expect: **No output folder selected. Save to the app's output
   folder?** The actual default path should be visible.
3. Choose **Cancel**: edits remain and nothing is written. Try Next or closing
   with dirty edits; Cancel should keep the frame/window open.
4. Choose **Choose folder…**, then cancel the folder chooser: same result.
5. Repeat Save → Choose folder… → `.manual-test-data/save-confirmed`. The
   polygon must remain visible and save there. Subsequent saves should not
   repeat the destination question during this session.
6. On a fresh launch repeat with **Use default**. Check `<app-folder>/output`
   for the current image's JSON. The app should recreate that folder if absent.
   Only remove test files you no longer need; do not remove real annotations.
7. On another fresh launch, draw first and click Save Directory directly after
   drawing. Selecting a folder must not erase the unsaved polygon. Also verify
   Save Directory first → Image Directory still works without crashing.

The default output folder is created at startup. Git branches control code,
not these local JSONs: deleting an untracked/ignored JSON affects the local file
on every branch. Switching branches does not restore it.

## 4. Geometry safeguards (#36 / PR #53)

```powershell
git switch fix/geometry-operation-safety
```

1. Launch normally. Choose Save Directory `geometry-annotations`, then Image
   Directory `images` under `.manual-test-data`.
2. **Hole protection:** on frame 1 select the small inner cat polygon. Click
   Subtract Polygons, confirm the source-selection instruction, then select
   the large outer cat polygon. A hole would be created: the operation must be
   blocked, report the hole, and leave both shapes intact.
3. **Safe merge:** select the small inner cat polygon, click Merge Polygons,
   follow the target-selection prompts, then select the outer cat. They share
   all metadata. The diagnostic confirmation should show pixel/region/hole and
   vertex counts. Cancel once: no changes. Repeat and apply: the union should
   remain the same silhouette. Ctrl+U should restore both original polygons.
4. **Metadata conflict:** try merging a cat/ID 3 polygon with dog/ID 4. It must
   refuse without changing either shape. Aligning identities/metadata is a
   deliberate edit, not something Merge does automatically.
5. **Point reduction:** draw a polygon with several closely spaced vertices
   along an edge and enough other vertices to remain a polygon. Finish it,
   select it, and click Reduce Points. Inspect the counts; Cancel first, then
   apply and use Ctrl+U. Names, IDs, flags, and descriptions should survive.
6. Optional split test: draw a narrow strip across a polygon and subtract it.
   If representable, the result must retain all disconnected pieces. The
   source strip and other original polygons remain separate annotations; hide
   them individually using their list checkboxes to inspect the cut result.
   Tiny/thin results that cannot be represented faithfully must be blocked.
7. Save, navigate away/back, and reopen. Check the intended geometry and
   metadata. The original JSON format has no implicit hole representation.

## 5. Group-ID class-mask comparison (#35 / PR #54)

```powershell
git switch feat/group-class-mask-comparison
python .\annotator.py --review --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

**Use only this disposable review output.** Opening an existing review database
on this branch upgrades it to schema 2, which older branches cannot reopen.
Do not point this test at a production review database.

In the review setup choose:

- Image directory: `.manual-test-data/images`
- Original annotations: `.manual-test-data/original-annotations`
- Reviewed output: `.manual-test-data/class-review`
- Reviewer ID: a test name such as `manual-test`

For each case record **Minor correction** to recompute the audit, then inspect
the CSV in `class-review` (use Export CSV if needed). Match the row by image
filename/relative_key. Saving alone is not the same as recording a decision.

1. **Numeric class change:** on frame 1 change only the large cat polygon's ID
   from 3 to 8. Keep the name/vertices unchanged. Expect `class_mask_changed=1`,
   `geometry_changed=0`, `raster_mask_changed=0`.
2. **Name-only change:** on frame 2 rename its cat polygons to `lynx`, keep
   ID 3 and all vertices. Expect `annotation_changed=1`, but
   `class_mask_changed=0` and both geometry/silhouette fields 0. If testing the
   combined branch with the name warning, choose Save anyway for this
   intentionally inconsistent test.
3. **Unassigned ID:** on frame 3 clear a polygon's group ID. Expect a blank
   `class_mask_changed` and a nonempty `class_mask_error`, not a false 0.
4. **Overlap order:** on frame 4 drag the dog/ID 4 entry above the outer cat/ID 3
   entry in the Polygon Labels list without moving vertices. The visible
   overlap class changes: expect class mask 1 while geometry/silhouette stay 0.
5. Ensure originals stayed unchanged, notes/decisions persist after restart on
   this branch, and old CSV columns remain alongside the three new class-mask
   columns. IDs are dataset-local; names do not imply a global numeric ontology.

## 6. Test the fixes together, or return to the merged version

After individual checks, use the updated local integration branch:

```powershell
git switch test/open-issue-fixes
```

Launch normally for output/warning/geometry tests, or with `--review` and the
disposable review paths for class-mask checks. This branch is local to this
checkout; the four PRs remain separate and unmerged.

To return to the currently merged version:

```powershell
git switch master
```

Do not open the schema-2 `class-review` database on master before #35 is merged.
Switching code branches does not roll back test JSONs/databases. No class-name
or ID changes are made automatically by the warning.
