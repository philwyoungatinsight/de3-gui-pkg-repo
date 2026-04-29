# File Viewer Mode Persistence Fix

## Bug
After adding the `file_viewer_mode` guard to `click_node`, clicking nodes in the
"separated" (unmerged) tree view no longer showed the unit file in the File Viewer.

## Root Cause
Reflex 0.8.x persists state vars across WebSocket reconnects within a browser session
(in-memory state, not page-load-fresh). `file_viewer_mode` was not being saved to
`state/current.yaml` or restored in `on_load`. If the user switched to "Config Data"
mode (e.g. to test it), the mode stayed as `"config_data"` in Reflex's internal state
even after a page reload. Clicking nodes in the unmerged tree then hit the guard
`if self.file_viewer_mode == "unit_file"` which failed silently — no HCL was loaded.

## Fix

### `_save_current_config`
Added `menu["file_viewer_mode"] = self.file_viewer_mode` so the mode is written to
`state/current.yaml` whenever any other setting changes.

### `on_load`
Added `self.file_viewer_mode = saved_menu.get("file_viewer_mode", "unit_file")` so the
mode is explicitly restored (defaulting to `"unit_file"`) on every page load.

### `set_file_viewer_mode`
Added `self._save_current_config()` call at the top so the mode is persisted to disk
as soon as the user switches it via the dropdown.

## Result
- `file_viewer_mode` is now a first-class persisted setting like `tree_mode`,
  `viz_framework`, etc.
- Clicking nodes in separated mode always correctly reflects the current mode.
- Switching between "Unit File" and "Config Data" is remembered across page reloads.
