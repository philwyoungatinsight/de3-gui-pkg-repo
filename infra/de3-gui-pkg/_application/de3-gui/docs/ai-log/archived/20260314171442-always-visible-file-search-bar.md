# Make file viewer search bar always visible

## What changed

**`homelab_gui/homelab_gui.py`**:
- Removed `file_search_open: bool` state var
- Removed `toggle_file_search` event handler
- Removed the 🔍 toggle button from the file viewer menu bar
- Replaced `rx.cond(file_search_open, search_hstack, rx.box())` with the search hstack rendered unconditionally
- `Escape` in the search input now clears the query (no longer closes the bar)
