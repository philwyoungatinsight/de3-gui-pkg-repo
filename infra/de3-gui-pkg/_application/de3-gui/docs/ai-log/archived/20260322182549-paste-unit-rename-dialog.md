# Paste Unit: Rename Dialog

## Summary
Extended the copy/paste unit feature so the user can rename the unit when pasting.

## Changes

### New state vars
- `paste_dialog_open: bool` — controls the rename dialog
- `paste_pending_target: str` — target folder path for the in-progress paste
- `paste_pending_name: str` — editable unit name (pre-filled from clipboard)

### New / changed event handlers
- `begin_paste(target_path)` — replaces old `paste_unit`; sets pending state and opens dialog
- `set_paste_name(name)` — two-way bind for the name input
- `paste_name_keydown(key)` — calls `confirm_paste()` on Enter
- `cancel_paste()` — closes dialog without pasting
- `confirm_paste()` — uses `paste_pending_target` + `paste_pending_name` to perform the paste (was `paste_unit`, now reads name from state instead of src path)

### Context menu update
- `action_type` for paste changed from `"paste_unit"` → `"begin_paste"`
- `dispatch_action` updated accordingly

### Dialog UI (`index()`)
- `rx.dialog.root` overlay with `open=AppState.paste_dialog_open`
- Shows target folder path (read-only)
- Editable unit name input, pre-filled with original name, auto-focused
- Enter key in input triggers confirm
- Cancel / Paste buttons

## Files Modified
- `homelab_gui/homelab_gui.py`
