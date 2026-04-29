# File Viewer menu bar: separator + match-count arrow highlight

## What changed

**`homelab_gui/homelab_gui.py`**:

### Separator fix
- Replaced the ad-hoc `rx.box(width="1px", height="16px", background="var(--gui-border)")` separator in the file viewer menu bar with `rx.box(width="1px", height="16px", background="var(--gui-divider)", flex_shrink="0", margin_x="4px")` — now matches the style used in the nav bar and other panel headers

### ↑/↓ arrow buttons
- `color_scheme` changed from hardcoded `"gray"` to `rx.cond(AppState.file_search_match_count > 1, "blue", "gray")` — buttons appear blue when there is more than one match for the current query

### New state var
- `file_search_match_count: int = 0` — updated via JS callback after every search navigation

### New event handler
- `set_file_search_match_count(count: int)` — callback target; safely coerces to int

### New helper method
- `_search_script(js: str)` — wraps `rx.call_script(js, callback=AppState.set_file_search_match_count)`; used at all search call sites so the match count is always updated

### JS functions updated to return match count
- `_pre_search_js` — `return marks.length;` at end
- `_monaco_search_js` — `return matches.length;` at end
- `_config_data_node_search_js` — `return marks.length;` at end
- `_pre_search_clear_js` — `return 0;` at end

### Call sites
All 17 `rx.call_script(<search_fn>(...))` calls replaced with `self._search_script(<search_fn>(...))`.
