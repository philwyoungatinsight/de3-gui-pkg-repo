# Add Inline Monaco File Editor

## Summary
Added an inline Monaco editor to the file viewer panel, allowing files to be edited directly in the GUI without launching an external editor.

## Changes

### `requirements.txt`
- Added `reflex-monaco>=0.0.3`

### `homelab_gui/homelab_gui.py`
- Imported `reflex_monaco.monaco` as `_monaco`
- **State vars added:** `file_editor_active`, `file_editor_draft`, `file_editor_save_error`
- **Computed vars added:** `file_editor_language` (maps file extension to Monaco language), `file_editor_monaco_theme` (maps `ui_theme` to Monaco theme)
- **Event handlers added:** `enter_file_edit_mode`, `cancel_file_edit`, `set_editor_draft`, `save_file_edit`, `_reset_file_editor`
- `_reset_file_editor()` called from `select_node`, `click_node`, `click_modules_node`, `set_file_viewer_mode`, `set_file_viewer_provider` to discard unsaved edits on file navigation
- **Component added:** `_file_viewer_monaco_editor()` — wraps the Monaco editor in a flex box sized to fill the panel
- **`bottom_left_panel()` updated:**
  - Menu bar: normal mode shows Edit button + editor menu; edit mode shows Save (green) + Cancel (gray) + optional error text
  - Content area: `rx.cond` swaps in Monaco editor when `file_editor_active` is True

### `config/de-gui.yaml`
- Added `embedded-editor` as first entry in `file_viewer.editors`

### `_FILE_VIEWER_EDITOR_DEFAULTS`
- Added `{"id": "embedded-editor", "label": "Embedded Editor", "type": "embedded"}` as first entry
- `open_file_in_editor` handles `type == "embedded"` by dispatching `enter_file_edit_mode`
- Edit button moved into the Editor dropdown menu as "Embedded Editor" (first item)
