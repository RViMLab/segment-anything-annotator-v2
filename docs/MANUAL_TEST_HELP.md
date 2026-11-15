# Help and shortcut captions (#64)

Close the app before switching branches, then use your usual environment:

```powershell
git switch feat/shortcut-help
python .\annotator.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

1. Check the toolbar at normal and maximized sizes: **Help (F1)** should be
   visible at the start, and the main controls should show their keys (Accept A,
   New polygon N, Box prompt B, Edit polygons E, Save S). Hover for tooltips.
   At narrow sizes, remaining controls are available through the toolbar's
   normal overflow menu.
2. Click Help, close it, then press F1. It should reopen one nonmodal window;
   you can return to the annotator while leaving Help open.
3. Search for `donut`, `merge`, `small`, `save`, and `tracking`. Check that relevant
   topics appear. An unmatched search should explain that no topics match;
   clear the field to restore all topics.
4. With annotations loaded, type `n b a s u 0 1 2 3 k m l o` in the search field.
   Press Page Down, Page Up, Space, and Ctrl+U in the field and in the help text.
   No frame, visibility, proposal, edit, save, or review decision should change.
   Existing unsaved edits should remain unsaved; Help should not dirty a clean frame.
5. Return to the canvas. Confirm normal shortcuts still work: N, U on an
   unfinished polygon, E, H, class digits, and Page Up/Page Down/J. With SAM
   proposals active, 1–3 should still choose proposals rather than visibility.
6. Open Help during video annotation and during a review session. Check the
   guidance distinguishes Space propagation from Space timer control. Search
   `destination` and verify the displayed output folder matches the session.
   In review, typing K/M/L/O in Help must not submit decisions or advance frames.

No checkpoint downloads or tracking runs are needed solely to check Help.
