# Unified video GUI (#65)

Close the app before switching branches. Use your usual `test_env` environment:

```powershell
git switch feat/unified-video-annotation
python .\annotator.py --video --video-directory .\demo_video --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720 --max-size-stcn 600
```

STCN's code/checkpoint and the SAM vit_b checkpoint are already installed on
this machine from the successful legacy preflight. Other machines should follow
the README's optional prerequisites. A backend is selected explicitly; this is
not a STCN-versus-SAM2/3 accuracy benchmark.

## Basic tracking on the original demo

1. The current GUI should show the first frame of `kunkun_00000_15_59` and the
   Video tracking controls above Polygon Labels. All image display controls and
   class mapping should still work. **Track selected** stays disabled until a
   valid sequence is opened.
2. Choose a fresh Save Directory, for example `output_STCN_unified_manual`
   (create it through the chooser). Output selection before video selection
   should also work on a separate launch.
3. Annotate the person on frame `00000.jpg`: Load SAM → Box Prompt (B) →
   top-left to bottom-right box → choose a proposal → Accept (A). Enter class
   name `person` and numeric group ID `1` (or use your approved mapping). Save.
4. Edit (E), Ctrl-select the person's polygon, choose **STCN (optional)**, then
   **Track selected**. The model loads automatically; there is no separate
   Add-to-memory step. Starting without choosing a backend should explain what
   is missing rather than choose a model silently.
5. **Page Down** advances to `00001.jpg`. **Space** / **Propagate frame** predicts
   only this frame. Inspect and Save (S). Repeat for `00002` and `00003`.
   **Page Up** goes back and **J** opens Jump. **N** still starts a polygon;
   **B** still selects Box Prompt, never navigation.
6. Edit a propagated polygon and click **Use correction**. Advance and propagate
   again. Check the reference uses your correction. A backward/forward jump is
   safe; propagating at/before the current reference asks for a new reference.
7. Propagate again on a frame already containing annotations. Cancel its
   replacement confirmation: nothing should change. Repeat and confirm:
   tracked entries may change, unrelated polygons must remain in their order.
8. Ctrl+U after propagation: the annotation should revert and tracking should
   stop, with guidance to select objects and Track selected again. Undo after
   the initial Track selected also restores the previous object-ID metadata.
9. Save, close, and reopen the same sequence/output. Annotations should reload;
   select a saved object and Track selected to initialize a new tracking session.
   Saved JSON is under `output_STCN_unified_manual/kunkun_00000_15_59/`.

## Identity, holes, and failure safety

1. On disposable annotations, create two separate polygons with the same class
   ID, label, and other metadata. Use fresh manual polygons, rather than two
   propagated parts of an existing tracked object. In Edit mode, Ctrl-select
   both entries in **Polygon Labels**, then click **Track selected**. The
   **Are these parts of one object?** question appears at this point: choose
   **No**. The status should say **Tracking 2 object(s)**. Save this reference
   frame and inspect `video_object_id`: the two polygons should have different
   values while retaining the same class/group ID. Check this before advancing;
   prediction quality and the number of output polygons are separate checks.
   Two parts already sharing a tracking ID are automatically treated as one
   object, without asking again. Different labels or other metadata also skip
   the question, keeping distinct identities separate.
2. For donut parts, select all fresh parts with matching labels and metadata,
   then choose **Yes** to combine them as one tracking object. Already-linked
   parts need no question. The reference mask must keep its hole. Predictions
   remain model suggestions and can need manual correction. Generated parts
   share one tracking ID and preserve labels, flags, descriptions, and custom
   metadata. One tracked object can produce one, two, or more polygon parts on
   different frames; the tracking ID, rather than the polygon count, identifies it.
   To test multiple classes together, annotate hair and a basketball on the
   same reference frame with different class/group IDs. Ctrl-select both and
   click **Track selected**: they stay separate without a grouping question.
   Advance and propagate both together; no separate pass or rewind is needed.
3. Try STCN on a copy of the app without its optional STCN/checkpoint files:
   Track selected should show setup guidance, while images/review still open.
   Do not move/delete your working weights for this check; the automated tests
   already cover the missing-dependency path.
4. Switching sequence saves pending edits through normal save gates and clears
   tracker memory. An empty/corrupt new directory must preserve the current
   dataset/tracker. Cancel/fail a save and verify switching is blocked.
5. The model progress window must keep repainting while the model runs; Escape
   or its close controls must not dismiss it and expose changing frame controls
   mid-inference. Unsupported geometry must leave annotations and accepted
   tracker memory unchanged.

## Review of video frames

Create a separate `review_STCN_unified_manual` directory, then launch:

```powershell
python .\annotator.py --review --review-images .\demo_video --review-annotations .\output_STCN_unified_manual --review-output .\review_STCN_unified_manual
```

1. Confirm nested frame pairs and context frames are found. The reviewed output
   retains the sequence subfolder, so equal frame names in different clips stay
   separate (also covered by automated two-sequence tests).
2. New review items should show **Manual keyframe** or **STCN propagated frame**
   based on the saved metadata. Existing resumed review audit values must remain.
3. Mark OK on one frame and make/save a minor correction on another. Revisit,
   resume the session, and inspect CSV export. Originals must remain unchanged;
   reviewed labels, IDs, geometry, metadata, notes, and decisions must persist.
4. Page Up/Page Down and J retain their navigation meaning. Video propagation
   and sequence switching are unavailable in review; STCN need not be installed.

Finally, check `python annotator_video.py --help` / launch: this compatibility
entry point should open the same GUI with the same shortcuts, not the old UI.
