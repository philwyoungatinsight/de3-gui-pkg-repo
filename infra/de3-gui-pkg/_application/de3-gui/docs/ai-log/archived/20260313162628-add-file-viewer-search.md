# Add File Viewer Search

## Summary
Added a search bar to the file viewer panel with up/down navigation. Works in both read-only view mode and the inline Monaco editor mode.

## Changes

### `homelab_gui/homelab_gui.py`

**State vars added:**
- `file_search_open: bool` — controls search bar visibility
- `file_search_query: str` — current search text

**JS helper functions added** (module-level, near `_file_viewer_scroll_js`):
- `_pre_search_js(query, direction)` — walks `#file-viewer-pre` DOM, injects `<mark data-fs>` highlights, scrolls current match into view. Rebuilds marks only on query change.
- `_pre_search_clear_js()` — removes all injected search marks
- `_monaco_search_js(query, direction)` — drives Monaco's native find widget via `editor.contrib.findController`

**Event handlers added:**
- `toggle_file_search` — opens/closes the search bar; focuses input on open, clears marks on close
- `set_file_search_query` — updates query and jumps to first match (dispatches appropriate JS)
- `file_search_next` — next match
- `file_search_prev` — previous match

**`_reset_file_editor` updated:**
- Also resets `file_search_query` on file navigation (marks are cleared naturally by DOM re-render)

**`bottom_left_panel()` updated:**
- Menu bar: 🔍 icon button added after "⎘ abs"; turns orange when search is open
- Search bar row: appears between menu bar and path bar when `file_search_open` is True
  - Input field (auto-searches on change)
  - ↑ / ↓ buttons for previous/next match
  - Enter → next match, Escape → close bar
