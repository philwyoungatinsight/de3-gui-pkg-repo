# 20260405-094716 — Wave panel: "Log Update" optional column

## Feature

New optional column "Log Update" in the Waves panel (both table and folder
views), showing how long ago the active `run.log` was last written.

## Changes

### State var + persistence + handlers

`wave_show_log_update: bool = False` — same pattern as `wave_show_age`.
`toggle_wave_show_log_update` / `flip_wave_show_log_update` handlers.
Saved to / restored from `state/current.yaml`.

### `refresh_wave_log_statuses`

`entry["log_update_age"]` computed alongside `entry["age"]`:
```python
entry["log_update_age"] = (
    _fmt_duration((now - _dt.fromtimestamp(run_log_mtime)).total_seconds())
    if run_log_mtime else ""
)
```
`run_log_mtime` was already computed per-directory for the running-state
detection added in the previous session.

### `waves_with_visibility`

`"log_update_age"` added to `_empty_ls`, all three `result.append` call
sites (config wave list, orphan wave list, `_none` row).

### UI — column header and cells

- `_wave_table_header()`: "Log Update" header after "Age" (shared by both
  table and folder views)
- `_wave_list_row` table view: `rx.table.cell` with `display` conditional
- `_wave_folder_item` folder view: `rx.table.cell` with `display` conditional
- `_wave_time_cols` list-view hstack: `rx.cond` block after age

### Appearance menu

"Log Update" item added after "Age" under the Waves Columns section.
