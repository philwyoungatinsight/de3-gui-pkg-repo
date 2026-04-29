# Apply Unit + Delete Dialog Button Fix

## Summary
Added "Apply unit…" context menu action (runs terragrunt apply in the action terminal).
Also fixed the root cause of confirm_delete never firing: action buttons in dialogs must
be wrapped in `rx.dialog.close()` for Radix UI to dispatch their events properly.

## Changes

### Apply unit feature
- State vars: `apply_dialog_open: bool`, `apply_pending_path: str`
- Handlers: `begin_apply(path)`, `cancel_apply()`, `confirm_apply(mode)`
  - mode `"unit"` → `terragrunt apply` in unit dir
  - mode `"recursive"` → `terragrunt run-all apply` in unit dir
  - Both open the action terminal (`shell_cwd` + `shell_initial_cmd`)
- Context menu: "Apply unit…" added for unit nodes (has_terragrunt=True)
- `dispatch_action` handles `"begin_apply"` action type
- Dialog in `index()` with Cancel / Apply unit (blue) / Apply recursively (green)

### Delete dialog fix (ghost bug root cause)
- Confirm buttons ("Delete unit", "Delete recursively") were NOT wrapped in
  `rx.dialog.close()`. Without this, Radix UI does not properly dispatch the
  button's on_click through its focus/portal layer, so `confirm_delete` never ran.
- The directory was never deleted; `state/current.yaml` retained the stale
  `selected_node_path` and `config_data_search_query`, causing the ghost to
  reappear on every `on_load`.
- Fix: wrapped both confirm buttons in `rx.dialog.close()`.
- Same pattern applied to the apply dialog from the start.
- Also: `confirm_delete` now calls `_save_current_config()` after success to clear
  stale paths from `current.yaml`.

## Files Modified
- `homelab_gui/homelab_gui.py`
- `state/current.yaml` (stale ghost path cleared manually)
