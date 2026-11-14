# Hole-preserving annotation (#61)

Close the app, then use your usual Python environment:

```powershell
git switch feat/polygon-holes
python .\annotator.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

Use disposable images/annotation copies. Keep the original toy annotations and
clinical data untouched. No old JSON is automatically converted to a ring.

## Subtract on the toy dataset (no SAM needed)

1. Choose a Save Directory containing a **copy** of the toy annotations, then
   Image Directory `.manual-test-data/images`. Use a frame with the large cat
   rectangle and the smaller cat rectangle inside it. Hide the dog polygon
   temporarily if it obscures your view.
2. Select the **small inner rectangle** in Polygon Labels. Click **Subtract**,
   confirm the source/target instruction, then select the **large rectangle**.
3. The operation confirmation should report an added hole and explain that it
   uses multiple filled parts. Cancel first: all entries must remain unchanged.
   Repeat and apply: the large rectangle becomes parts surrounding the hole.
4. The small cutter still fills the middle until you remove it. Delete the
   cutter entry if it is only a temporary tool. A hidden checkbox only hides
   it on screen; it would still be saved. Delete/hide any unrelated overlapping
   annotations as appropriate to distinguish the class mask you are checking.
5. Check the hole is empty. Ctrl-click each ring part in Polygon Labels, then
   drag a selected part on the image to move the selection: the
   hole should move with the ring. Undo movement with **Ctrl+U**. Undo deleting
   the cutter, then undo subtraction: the two original rectangles should return.
6. Repeat subtraction and delete the cutter, then Save and revisit/reopen the
   frame. The ring should retain its hole. Parts have the same class/name and
   metadata as the target; seams and multiple list entries are expected.

## SAM and normal editing

1. Load SAM. On a suitable test image, use a positive point in the desired
   foreground and a negative point in the inner area to try to obtain a mask
   with a hole. SAM may choose a different segmentation: select a proposal
   whose preview actually has the desired excluded area.
2. Try proposal buttons/digits 1–3, then Accept. A proposal containing a hole
   explains that it will become filled polygon parts. Cancel: keep proposals
   available and leave existing annotations untouched. Repeat and confirm,
   then choose a class (including testing the optional class mapping).
3. The inner boundary must not appear as a separate filled foreground polygon.
   Check Save/reopen, and Ctrl+U immediately after acceptance (before changing
   frames): all newly accepted parts should be undone together.
4. Check box and circle prompts still work, as well as ordinary hole-free masks.
   The automated tests exercise hole conversion through all three prompt paths
   with deterministic masks; actual SAM prediction quality is independent.
5. Verify multiple holes and disconnected foreground if available. Unsupported
   very thin/complex masks must explain why conversion is unavailable **on Accept**; they
   must never be silently filled/dropped. Other valid proposals remain usable.

## Point-prompt regression and model readiness

1. Start a fresh app without clicking Load SAM. Try Point, Box, and Circle
   Prompt, and their P/B/C shortcuts. Expect a clear Load SAM warning; no
   inactive prompt mode should be entered. An unfinished manual polygon must
   remain intact. Manual polygons and construction shapes still work.
2. Load SAM, choose Point Prompt, and make one positive click. Nonempty
   predictions should appear immediately, even if their geometry is too complex
   to save. Add positive/negative clicks: no polygon-conversion popup should
   interrupt each click. Try all three proposal buttons/digits.
3. With **Point prompts: keep clicked regions** enabled below Invert colours,
   check that detached speckles disappear from the preview. Disable it to view
   the complete SAM prediction, then re-enable it. Add a positive click inside
   each disconnected region you want to retain. Negative-only prompts do not
   apply this region filter. Box/circle predictions must be unaffected.
4. Accept a suitable preview. Polygon conversion must match the displayed
   mask, including holes. Unsupported conversion should explain the problem
   only at this step and retain prompts/proposals for further refinement.
5. Reject, change mode, and navigate frames. The raster overlay and old proposal
   state must clear. Recheck Save/reopen and Ctrl+U after a successful acceptance.

## Compatibility

Saved shapes remain ordinary filled polygons. A downstream class mask is the
union of all polygon parts for that class; it must keep the excluded centre.
Tools counting one polygon as one instance will see several parts, not a new
compound object. No custom hole/group-ID convention is required. Review masks
use the same filled-polygon interpretation and retain the holes.
