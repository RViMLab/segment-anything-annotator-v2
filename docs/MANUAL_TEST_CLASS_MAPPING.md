# Class mapping (#59)

Close the annotator before changing branches, then launch from your usual environment:

```powershell
git switch feat/group-id-class-mapping
python .\annotator.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

Use disposable images and an explicit Save Directory for these checks.

1. Click **Class mapping** in the toolbar. Add rows `0 / background`,
   `3 / forceps`, and `125 / retina`. Mapping should already be enabled for a
   new setup. Click **Apply mapping**, including while the last cell is still
   being edited. Check the toolbar shows **Class mapping ✓**. Setup must also
   work before loading images. Repeat after restarting to check the reported
   fresh-session failure without manually touching the checkbox.
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
8. Disable the mapping and click **Use free-form labels**. New annotations and label edits must return
   to the normal free-form dialog. The configured rows remain available in
   setup for re-enabling.
9. Restart and use **Category File** to open a text file containing `zebra` then
   `forceps`, one name per line. Expect a mapping preview `0 / zebra`,
   `1 / forceps` in file order. Change forceps to ID 3 and **Apply mapping**.
   Try both a manual polygon and accepting a SAM proposal: selecting forceps
   must fill ID 3. Repeat via **Class mapping → Load…** with the text file.
10. Load `categories_retina.txt` through Category File. Check that proposed IDs
    follow its numeric prefixes, such as `7 / 7_forceps`; the names retain
    their prefixes. Edit any name/ID before applying. Try duplicate IDs: they
    must be rejected with an explanation. Cancel an import and confirm the
    previous active mapping still works and existing annotations are untouched.
11. Restart, load a category file, and **Cancel** its mapping preview. The text
    names should remain normal suggestions with mapping disabled. Then open
    Class mapping, add `3 / forceps`, and Apply mapping. Both manual polygons
    and SAM acceptance must now show the mapped choice rather than the text
    suggestions. This reproduces the originally reported sequence.

Mappings are optional, explicitly loaded, and apply throughout the current app
session, including review mode. When changing datasets, load that dataset's
mapping or disable the feature. **Save…** exports the setup; **Apply** activates
it. The mapping file is separate from annotation JSON and is not embedded in it.
