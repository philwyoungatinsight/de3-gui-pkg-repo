# Copy/Paste Unit via Explorer Context Menu

## Summary
Added copy/paste functionality for infra units via the Explorer context menu.

## Changes

### State vars added
- `clipboard_unit_path: str` — path of copied unit (empty = nothing in clipboard)
- `clipboard_unit_content: str` — raw HCL content of the copied unit file
- `clipboard_message: str` — status/error shown in toolbar banner
- `clipboard_message_is_error: bool` — controls banner color (red vs green)

### Computed var
- `clipboard_unit_name` — last path segment of `clipboard_unit_path`

### Event handlers
- `copy_unit(path)` — reads unit file via `_read_hcl_file`, stores content; sets message
- `paste_unit(target_path)` — validates provider match (path[1] segment), creates target dir, writes file, runs partial infra reload; sets message on success/failure
- `clear_clipboard_message()` — dismisses the banner

### Context menu injection (in `open_context_menu`)
- "Copy unit" appears for nodes with `has_terragrunt=True`
- "Paste unit: '<name>'" appears for folder nodes (no unit file) when clipboard is non-empty
- Added "clipboard" group to `group_labels`

### `dispatch_action` cases added
- `copy_unit` → `self.copy_unit(value)`
- `paste_unit` → `self.paste_unit(value)`

### Clipboard banner UI (in `left_panel()`)
- `clipboard_banner` strip between `filter_bar` and content area
- Shows `clipboard_message` in green (success) or red (error)
- "×" dismiss button calls `clear_clipboard_message`

## Files Modified
- `homelab_gui/homelab_gui.py`
