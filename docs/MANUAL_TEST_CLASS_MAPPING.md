# Class mapping (#59)

Close the annotator before changing branches, then launch from your usual environment:

```powershell
git switch feat/group-id-class-mapping
python .\annotator.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

Use disposable images and an explicit Save Directory for these checks.

1. Click **Class mapping** in the toolbar. Add rows `0 / background`,
   `3 / forceps`, and `125 / retina`. Enable **Use mapping to fill class names
   from group IDs**, then **Apply**. Setup must also work before loading images.
2. Draw a manual polygon. In the label dialog, type `3`: **forceps** must fill
   automatically and be read-only. Confirm, then check the name and ID in
   Polygon Labels. Repeat with ID `0` and select another class from the list.
3. Try an undefined ID such as `4`, then a blank ID. **OK** must be disabled.
   Cancel: no incorrectly labelled polygon should be added.
4. Edit an existing annotation with a different name for ID 3. Loading or
   enabling the mapping must not change it. Open Edit Label and cancel: it
   must remain unchanged. Repeat and confirm: its name becomes **forceps**.
   Check that vertices, description, and flags remain intact; save and reopen.
   Other annotations must remain as they were. Existing name warnings can
   still appear if older annotations elsewhere use a different name for ID 3.
5. With SAM loaded, generate proposals and click **Accept**. Cancel the class
   dialog: proposals should remain available. Click Accept again, select ID 3,
   and confirm: all components of that proposal must receive **forceps / 3**.
6. Reopen **Class mapping**. Add a duplicate ID or leave a name blank: Apply
   must explain the problem rather than enable an invalid mapping. Remove the
   invalid row, save as `classes.json`, and Apply.
7. Close/restart the app. Open Class mapping, **Load…** `classes.json`, then
   **Apply**. Check that IDs/names are restored. Loading a malformed JSON
   should explain the error and retain the current draft. Cancelling setup
   should leave the active mapping unchanged.
8. Disable the mapping and Apply. New annotations and label edits must return
   to the normal free-form dialog. The configured rows remain available in
   setup for re-enabling. Category File should still load ordinary name lists.

Mappings are optional, explicitly loaded, and apply throughout the current app
session, including review mode. When changing datasets, load that dataset's
mapping or disable the feature. **Save…** exports the setup; **Apply** activates
it. The mapping file is separate from annotation JSON and is not embedded in it.
