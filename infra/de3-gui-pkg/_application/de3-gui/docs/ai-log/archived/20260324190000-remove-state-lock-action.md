# Remove State Lock Context Menu Action

## Summary
Added "Remove state lock…" to the explorer context menu for terragrunt units, with a
confirmation dialog that warns about the dangers of force-unlocking and then opens the
action terminal to run the removal.

## Changes

### State vars
- `unlock_dialog_open: bool = False` — controls the confirmation dialog
- `unlock_pending_path: str = ""` — node path passed from context menu

### Handlers
- `begin_unlock(path)`: stores path, opens dialog
- `cancel_unlock()`: closes dialog
- `confirm_unlock()`: closes dialog, constructs unlock command, opens terminal via
  `shell_cwd` / `shell_initial_cmd`

### Command run in terminal
```bash
source $(git rev-parse --show-toplevel)/set_env.sh &&
echo '=== Detecting state lock ===' &&
LOCK_ID=$(terragrunt plan 2>&1 | grep -oP '(?<=ID:\s{1,10})[0-9a-f-]{36}' | head -1) &&
if [ -n "$LOCK_ID" ]; then
  echo "Lock ID: $LOCK_ID" &&
  terragrunt force-unlock -force "$LOCK_ID" &&
  echo '=== State lock removed ===';
else
  echo 'No active lock detected (or lock ID could not be parsed).';
fi
```
Auto-detects the lock ID from `terragrunt plan` error output (UUID regex) then runs
`terragrunt force-unlock -force`. Reports clearly if no lock is found.

### Context menu
- Added to "Actions" group in `open_context_menu`, only for nodes with `has_terragrunt=True`
- After "Show inputs" / "Show outputs"
- `action_type = "begin_unlock"`

### Confirmation dialog
- Title: "Remove state lock — are you sure?"
- Shows unit path
- Red callout warning: "Force-unlocking state is dangerous. Only do this if you are certain
  no other process is currently running Terraform on this unit."
- Shows command summary and auto-detection note
- Buttons: "Cancel" (gray) | "Remove lock" (red)

### Dispatch routing
- `dispatch_action`: added `elif action_type == "begin_unlock"` branch

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260324190000-remove-state-lock-action.md` (this file)
