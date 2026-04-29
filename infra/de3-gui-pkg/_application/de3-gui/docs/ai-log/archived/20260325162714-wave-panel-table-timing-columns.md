# Wave Panel: Table View, Timing Columns, UI Fixes

## Summary
Converted the wave panel list view to a proper `rx.table`, added Start Time / End Time /
Duration / Age columns with appearance-menu toggles, converted the folder view to a table
too (with indentation via padding-left), added live status polling after wave run/destroy,
and made several formatting and UI fixes.

## Changes

### Wave list view → `rx.table`
- `_wave_toggle_item` rewritten to return `rx.table.row` with `rx.table.cell` children
- `_wave_list_table()` new function: `rx.table.root` wrapping `_wave_table_header()` +
  `rx.foreach(AppState.waves_with_visibility, _wave_toggle_item)`
- Header row: `#`, Wave, Actions, Status, Start Time, End Time, Duration, Age
- Timing header cells hidden via `display=rx.cond(..., "table-cell", "none")`

### Wave folder view → `rx.table`
- `_wave_folder_item` rewritten to return `rx.table.row`
  - `wave_node` rows: same columns as list view
  - `folder_node` rows: name cell only (📁 + label), all other cells empty
  - Indentation via `padding_left=rx.match(item["indent"], ...)` on the name cell
    (not spacer boxes), so timing columns stay right-aligned at all indent depths
- `_wave_folder_table()` new function: same header as list, `rx.foreach(waves_folder_rows)`
- `_wave_table_header()` extracted as shared helper used by both tables

### Timing columns
- State vars: `wave_show_start_time`, `wave_show_end_time`, `wave_show_duration`,
  `wave_show_age` (all `bool = False`)
- `refresh_wave_log_statuses` extended to compute:
  - **Start time**: parsed from log directory name (`YYYYMMDD-HHMMSS`)
  - **End time**: mtime of `wave-{name}-{action}.log`
  - **Duration**: end − start via `_fmt_duration(..., show_seconds=True)`
  - **Age**: now − end (or now − start) via `_fmt_duration(..., show_seconds=False)`
- `_fmt_duration(seconds, show_seconds=True)`:
  - Format: `{d:>3}d-{h:02d}h-{m:02d}m[-{s:02d}s]`
  - Days space-padded to 3 chars; h/m/s zero-padded to 2 digits
- Timing fields propagated through `waves_with_visibility` and `waves_folder_rows`
- `_wave_time_cols()` helper retained for reference but no longer used in rendering

### Appearance menu — "Wave Panel Columns" section
- Four `_appearance_menu_item` checkboxes: Start time / End time / Duration / Age
- Handlers: `toggle_wave_show_*` (checked bool) + `flip_wave_show_*`
- Persisted in `_save_current_config` / `on_load` under same keys

### Live status polling after wave run/destroy
- `_WAVE_POLL_START_JS`: JS `setInterval` (3 s) clicking hidden `#wave-status-poll-trigger`
- `_WAVE_POLL_STOP_JS`: `clearInterval` on popup close
- `_open_wave_terminal` returns `rx.call_script(_WAVE_POLL_START_JS)`
- `toggle_wave_popup` (close path) and `close_wave_popup` return stop script
- Hidden `rx.el.div(id="wave-status-poll-trigger", on_click=AppState.refresh_wave_log_statuses)`
  added to wave popup alongside existing drag trigger

### Button spacing in action cell
- List and folder table action cells: `rx.box(width="32px")` spacer between ▶ and 🗑

### View mode label
- Toggle button in wave popup title bar now shows "Table" (was "List") when in list mode

### Dividers in file viewer menu bar
- Added `_fv_divider()` between Copy and Download buttons
- Added `_fv_divider()` after Download button (before Chrome profile dropdown)

### Bug fix: `_config_data_node_search_js` spurious `case_sensitive` kwarg
- Three call sites incorrectly passed `case_sensitive=self.file_search_case_sensitive`
  to `_config_data_node_search_js`, which does not accept that parameter
- Removed the kwarg from all three call sites

### Exit button removed
- `exit_app` handler, Exit menu item, its separator, and `/exit` page all removed
- The Help menu now ends at License

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260325162714-wave-panel-table-timing-columns.md` (this file)
