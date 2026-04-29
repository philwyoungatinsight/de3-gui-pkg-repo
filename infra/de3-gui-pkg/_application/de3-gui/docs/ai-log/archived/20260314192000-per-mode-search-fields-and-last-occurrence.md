# Per-mode file viewer search fields + jump to last occurrence

## What changed

**`homelab_gui/homelab_gui.py`**:

### State vars
- Removed `file_search_query: str`
- Added `unit_file_search_query: str` — search query for unit-file mode
- Added `config_data_search_query: str` — search query for config-data mode

### Helper property
- Added `_active_file_search` (Python `@property`, not `@rx.var`) — returns `config_data_search_query` or `unit_file_search_query` based on `file_viewer_mode`

### Search handler rename
- Renamed `set_file_search_query` → `set_active_search_query`: updates the mode-specific var (`config_data_search_query` or `unit_file_search_query`) based on `file_viewer_mode`; still uses `'init'` direction (first match) for manual typing

### Event handlers updated
- `file_search_next`, `file_search_prev`, `file_search_key_down`: all use `self._active_file_search` to get the active query; Escape clears the mode-specific var

### Node selection (always updates active mode's search)
- `select_node(path)`: always sets the active mode's query to `path`; loads file (unit_file) or leaves config content as-is; returns `_pre_search_js(path, "last")`
- `click_node(path)`: same — sets mode-specific query to `path`, returns `_pre_search_js(path, "last")`
- Both modes: unit-file and config-data get their search updated on node selection

### Mode switching
- `set_file_viewer_mode("config_data")`: if node selected, overrides `config_data_search_query = selected_node_path`; runs search with `'last'`
- `set_file_viewer_mode("unit_file")`: unchanged — uses `_search_reapply_script()` (init direction)

### Persistence
- `_save_current_config()`: saves both `unit_file_search_query` and `config_data_search_query`
- `on_load` restore: reads both new keys; migrates old `file_search_query` value into `unit_file_search_query` for backward compatibility

### App start (on_load)
- Uses `_active_file_search` and `'last'` direction when a node is selected; falls back to `'init'` when no node is selected (manual search query)

### `_pre_search_js` — new `'last'` direction
- Added `if(dir==='last') idx=marks.length-1;` before the next/init/prev branches
- Jumps to the final occurrence of the query in the file

### `_monaco_search_js` — new `'last'` direction
- Added `if(dir==='last') idx=matches.length-1;` to jump to the last match in the model

### UI
- Replaced single `rx.input(value=AppState.file_search_query, ...)` with `rx.cond(file_viewer_mode == "config_data", input(value=config_data_search_query, ...), input(value=unit_file_search_query, ...))`
- Both inputs use the same `set_active_search_query` handler and same keyboard handler
- Same `id="file-search-input"` so the JS `document.getElementById('file-search-input')` still works
