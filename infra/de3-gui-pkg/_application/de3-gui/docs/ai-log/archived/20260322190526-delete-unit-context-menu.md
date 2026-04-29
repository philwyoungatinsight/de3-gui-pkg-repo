# Delete Unit from Explorer Tree

## Summary
Added "Delete unit…" context menu action for unit nodes, with a confirmation dialog
offering "Unit file only" or "Delete recursively". The rm runs in the actions terminal
so the user can see the output; the config block is removed from the stack YAML via
Python, followed by an infra reload.

## Changes

### State vars added
- `delete_dialog_open: bool` — controls the confirmation dialog
- `delete_pending_path: str` — node path of the unit to delete

### Event handlers
- `begin_delete(path)` — opens dialog, sets `delete_pending_path`
- `cancel_delete()` — closes dialog
- `confirm_delete(mode)` — background task:
  1. Locates unit file via `_read_hcl_file`
  2. Removes exact-match `config_params` entry from stack YAML + reloads `_STACK_CONFIG`
  3. Sets `shell_cwd` (parent dir) and `shell_initial_cmd` (rm command) to run in terminal
  4. Clears selection if the deleted node was selected
  5. Sleeps 2s for the terminal rm to finish
  6. Partial infra reload + file viewer refresh
  - mode `"file"` → `rm <unit_file>`
  - mode `"recursive"` → `rm -rf <unit_dir>`

### Context menu
- "Delete unit…" added to Clipboard group for unit nodes (`has_terragrunt=True`)
- `dispatch_action` handles `"begin_delete"` action type

### Dialog UI (`index()`)
- Shows unit path
- "Cancel" (gray), "Unit file only" (orange outline), "Delete recursively" (red)

## Files Modified
- `homelab_gui/homelab_gui.py`
