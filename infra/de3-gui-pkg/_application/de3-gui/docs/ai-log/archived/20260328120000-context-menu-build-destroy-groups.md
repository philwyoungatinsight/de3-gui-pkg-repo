# Context Menu: Build / Destroy Groups, Remove State Lock

## Summary
Restructured the node tree context menu into "Build" and "Destroy" groups.
Removed all "Remove state lock" options and associated code entirely.

## Changes

### Context menu groups restructured
- **"Build"** group (top): Apply unit, Apply unit (recursive), Copy unit,
  Copy unit (recursive), Show inputs, Show outputs
- **"Destroy"** group: Destroy unit, Destroy unit (recursive), Taint unit,
  Taint unit (recursive), Remove unit and config block, Remove unit (recursive)
- **"Clipboard"** group: Paste items only (unchanged)
- **"Shell" / "Provider UI" / …** groups: unchanged, appear after Build/Destroy

### State lock code — only terragrunt force-unlock removed
Only the `terragrunt force-unlock` CLI variant was removed:
- Menu item: "Remove state lock…" (`begin_unlock` action type)
- State vars: `unlock_dialog_open`, `unlock_pending_path`
- Handlers: `begin_unlock`, `cancel_unlock`, `confirm_unlock`
- Force-unlock confirmation dialog

The direct backend lock-file delete options are retained and moved to the **Build** group:
- "Remove state lock file…" (`begin_unlock_file`) — single unit, for `has_tg` nodes
- "Remove state lock files (recursive)…" (`begin_unlock_file_recursive`) — all nodes
- `_build_unlock_file_cmd()`, state vars, `unlock_file_lock_uri` computed var,
  handlers, dispatch routing, and confirmation dialog all kept

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260328120000-context-menu-build-destroy-groups.md` (this file)
