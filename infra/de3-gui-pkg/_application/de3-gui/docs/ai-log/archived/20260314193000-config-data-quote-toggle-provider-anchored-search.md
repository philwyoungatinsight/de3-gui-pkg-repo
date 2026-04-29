# Config Data: quote toggle + provider-anchored search

## What changed

**`homelab_gui/homelab_gui.py`**:

### New state var
- `config_data_quote_path: bool = True` — when true, the node path placed in the config-data search is wrapped in double quotes (matching YAML `config_params` key syntax)

### New event handlers
- `toggle_config_data_quote_path(value: bool)`: sets `config_data_quote_path` to the given value; re-wraps or strips quotes from the current `config_data_search_query`; re-runs the provider-anchored search; called by `rx.switch` or other bool-passing callers
- `flip_config_data_quote_path()`: no-arg handler for the `""` button `on_click`; calls `toggle_config_data_quote_path(not self.config_data_quote_path)`. Needed because Reflex's `on_click` passes `PointerEventInfo` which is incompatible with `bool`.

### New helper function
- `_config_data_node_search_js(raw_path, provider, quoted)` — replaces the `'last'` direction used previously for config-data node navigation. Strategy:
  1. Builds `q = '"' + rawPath + '"'` if `quoted`, else `rawPath`
  2. Rebuilds `<mark data-fs>` elements using the same fragment-based approach as `_pre_search_js` (collected text nodes, then `replaceWith(frag)`)
  3. Walks text nodes to find the first occurrence of `providers/<provider>` and creates an anchor `Range` at the end of that text
  4. Iterates marks and picks the first one where `anchorRange.compareBoundaryPoints(Range.START_TO_START, markRange) <= 0` (anchor is before or at the mark)
  5. Falls back to `marks[0]` if no anchor is found
  6. Sets `pre._fsIdx` for ↑/↓ continuity, highlights active mark orange, smooth-scrolls into view

### Callers updated to use `_config_data_node_search_js`
- `select_node` — config_data branch
- `click_node` — config_data branch
- `set_file_viewer_mode("config_data")` — when a node is selected
- `on_load` — when restoring config_data mode with a selected node
- `toggle_config_data_quote_path` — after toggling

### Persistence
- `_save_current_config()` saves `config_data_quote_path`
- `on_load` restores it with `bool(saved_menu.get("config_data_quote_path", True))`

### UI
- Added `""` toggle button in the file viewer search bar, visible only in `config_data` mode (`rx.cond`)
- Appearance: `variant="solid" color_scheme="blue"` when active (quoting on), `variant="soft" color_scheme="gray"` when inactive
- `on_click=AppState.toggle_config_data_quote_path` (no-arg, flips current value)
