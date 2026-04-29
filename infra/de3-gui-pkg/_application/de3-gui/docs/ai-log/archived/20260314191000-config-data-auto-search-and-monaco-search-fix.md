# Config Data auto-search + Monaco editor search fix

## What changed

**`homelab_gui/homelab_gui.py`**:

### Feature 1: Auto-search when Config Data is shown

When a node is selected and the "Config Data" view is active, the selected node's path is automatically placed in the file viewer search bar and the search is invoked (highlights all occurrences, scrolls to first match).

Three handlers updated:

- **`set_file_viewer_mode("config_data")`**: when `selected_node_path` is set, now sets `file_search_query = selected_node_path` (before `_save_current_config()` so it persists) and returns `rx.call_script(_pre_search_js(..., "init"))` instead of the old scroll-to-line JS.

- **`select_node(path)`** (config_data branch): replaced the old scroll-to-line logic with `file_search_query = path` + `_save_current_config()` + `_pre_search_js(path, "init")`.

- **`click_node(path)`** (config_data branch): same replacement — was `_find_config_scroll_line` + `_file_viewer_scroll_js`, now sets search query and returns search JS.

`_find_config_scroll_line` and `_file_viewer_scroll_js` are now unused (kept as dead code; can be removed later).

### Feature 2: Monaco editor search up/down

Rewrote `_monaco_search_js()` to use `model.findMatches()` + `editor.setSelection()` + `editor.revealRangeInCenter()` instead of the old `FindController.setSearchString()` / `moveToNextMatch()` approach.

The old approach relied on internal Monaco FindController API that required the find widget to be open first. The new approach:
1. Calls `model.findMatches(q, true, false, false, null, false)` — case-insensitive substring search
2. Finds the next/prev match relative to the current cursor position, with wrap-around
3. Moves cursor to the match range and centers it in view

This works without opening Monaco's own find widget, so the search bar in the GUI is the only UI element needed.
