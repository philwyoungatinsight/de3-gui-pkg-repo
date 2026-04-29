# Wave table: checkbox tooltip + click name to open definition

## Summary

Two related improvements to the wave table:

1. **Checkbox tooltip** — hovering over the wave checkbox now shows a native browser
   tooltip explaining all three interaction modes.
2. **Click name to open definition** — clicking the wave name text opens the stack
   config YAML in the file viewer and searches for that wave name.

---

## How it works

### Checkbox tooltip
Both list-view (`_wave_toggle_item`) and folder-view (`_wave_folder_item`) checkboxes
now carry a `title=` attribute:

```
"Click: toggle wave visibility\n"
"Double-click: solo (show only this wave)\n"
"Double-double-click: invert (show all except this wave)"
```

### Click/double-click split
Previously the entire name cell had `on_click=toggle_wave` and
`on_double_click=solo_wave`. These handlers are now on the checkbox `rx.box` wrapper
only, so clicking the name text no longer fires them.

### Wave name → open definition
The wave name text (`rx.text(item["name"], ...)`) in both list and folder views now has:
- `on_click=AppState.open_wave_definition(item["name"])`
- `title="Click to open wave definition in file viewer"`

### `open_wave_definition(name)` handler
New public event handler that:
1. Reads the primary stack config via `_read_stack_config_file()`
2. Sets `file_viewer_mode = "config_data"`
3. Sets `config_data_search_query = name` so the search highlights the wave definition
4. Returns `_search_reapply_script()` so the highlight runs after React commits

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331164639-wave-checkbox-tooltip-and-definition-link.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
