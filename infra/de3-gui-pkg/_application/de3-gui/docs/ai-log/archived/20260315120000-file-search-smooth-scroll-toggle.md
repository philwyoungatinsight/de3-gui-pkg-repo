# File viewer search: smooth scroll toggle

## What changed

**`homelab_gui/homelab_gui.py`**:

### New state var
- `file_search_smooth_scroll: bool = False` — when false (default), search navigation jumps instantly; when true, uses smooth CSS scroll animation

### New event handler
- `flip_file_search_smooth_scroll()`: no-arg button handler, flips the toggle and saves config

### JS functions updated
All three search JS helpers now accept a `smooth: bool = False` parameter:
- `_pre_search_js(query, direction, smooth)` — `scrollIntoView({behavior: 'smooth'|'instant'})`
- `_monaco_search_js(query, direction, smooth)` — `revealRangeInCenter(range, 0|1)` (Monaco `ScrollType.Smooth=0`, `ScrollType.Immediate=1`)
- `_config_data_node_search_js(raw_path, provider, quoted, smooth)` — same `scrollIntoView` as `_pre_search_js`

### Callers updated
All call sites pass `self.file_search_smooth_scroll` as the `smooth` argument:
- `on_load`, `_search_reapply_script`, `select_node`, `click_node`, `set_file_viewer_mode`,
  `set_active_search_query`, `toggle_config_data_quote_path`, `file_search_next`, `file_search_prev`, `file_search_key_down`

### Persistence
- `_save_current_config()` saves `file_search_smooth_scroll`
- `on_load` restores it with `bool(saved_menu.get("file_search_smooth_scroll", False))`

### UI
- Added `~` toggle button in the file viewer search bar (always visible, next to the `""` quote button)
- Blue/solid when smooth scroll is on, gray/soft when off (default)
- `on_click=AppState.flip_file_search_smooth_scroll`
