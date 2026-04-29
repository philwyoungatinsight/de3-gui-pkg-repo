# Apply/Delete: Separate Menu Rows + Command Fixes

## Summary
Fixed incorrect terragrunt recursive-apply command (was using deprecated `run-all`
syntax). Replaced combined dialog-based apply/delete menu items with individual
context menu rows per action so the user doesn't need an intermediate dialog.

## Changes

### Apply commands (from ~/bin/tg)
- **Single unit**: `terragrunt apply` (unchanged, was already correct)
- **Recursive**: was `terragrunt run-all apply` → now
  `terragrunt run --all apply --non-interactive --`
- Both commands are now prefixed with
  `source $(git rev-parse --show-toplevel)/set_env.sh &&`
  so env vars are set correctly before terragrunt runs.

### Delete comparison to tg script
- GUI "delete" = `rm -rf` of the HCL unit directory (removes infra definition)
- tg `destroy` = `terragrunt run --all destroy ...` (deprovisions cloud resources)
These are different operations; the GUI does not run `terragrunt destroy`.

### New context menu rows for unit nodes
Before (one combined dialog each):
- "Apply unit…" → dialog offering Apply unit / Apply recursively
- "Delete unit…" → dialog offering Delete unit / Delete recursively

After (separate rows, no intermediate dialog for apply):
- "Apply unit" → `apply_unit(path)` → terminal runs single apply immediately
- "Apply unit recursively" → `apply_recursive(path)` → terminal runs run --all apply
- "Delete unit…" → `begin_delete_file(path)` → confirm dialog (single confirm btn)
- "Delete unit recursively…" → `begin_delete_recursive(path)` → confirm dialog

### Handler changes
- Removed: `begin_apply`, `cancel_apply`, `confirm_apply`
- Added: `apply_unit(path)`, `apply_recursive(path)` — direct, no dialog
- Replaced: `begin_delete(path)` → `begin_delete_file(path)` + `begin_delete_recursive(path)`
- Changed: `confirm_delete(mode: str)` → `confirm_delete()` — reads `delete_pending_mode`
- Added state var: `delete_pending_mode: str = ""`

### Delete dialog
- Removed two-button dialog (was: "Delete unit" orange + "Delete recursively" red)
- New single confirm button whose label/color/variant reflect `delete_pending_mode`
- Title also switches: "Delete unit" vs "Delete unit recursively"

## Files Modified
- `homelab_gui/homelab_gui.py`
