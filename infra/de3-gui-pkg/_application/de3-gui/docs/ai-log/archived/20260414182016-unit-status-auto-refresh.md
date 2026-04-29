# Unit Status Auto-Refresh from unit-state.yaml

## What changed

Added an "Auto-refresh" option that keeps unit build statuses in sync with
`unit-state.yaml` automatically — no manual button press required.

### New state vars

```python
unit_status_auto_refresh:      bool = False  # enable auto-refresh
unit_status_auto_refresh_secs: int  = 30     # 0 = on-change only, N = every N seconds
```

Both are persisted to `state/current.yaml` and restored on `on_load`.

### New module-level tracking vars

```python
_UNIT_STATE_YAML_MTIME: float = 0.0        # mtime of unit-state.yaml at last read
_UNIT_STATE_LAST_AUTO_REFRESH: float = 0.0  # time.time() of last interval-based refresh
```

### `local_state_watcher` — auto-refresh block

Inserted at the top of the poll loop (before the `.terragrunt-cache` scan).
On every poll (every 8 s normal, 2 s accelerated):

1. Skip if `unit_status_auto_refresh` is False or `show_unit_build_status` is False.
2. Check `unit-state.yaml` mtime.
3. If mtime changed → read YAML, push updates, reset mtime tracker.
4. If `unit_status_auto_refresh_secs > 0` and the interval has elapsed → same.
5. Logs a single line when a mtime-change-triggered update occurs.

Interval of `0` means on-change only. Minimum enforced interval is 5 s (via
`set_unit_status_auto_refresh_secs` clamp) to avoid hammering the reader.

### New event handlers

- `toggle_unit_status_auto_refresh(checked: bool)` — checkbox on_change
- `flip_unit_status_auto_refresh()` — label click
- `set_unit_status_auto_refresh_secs(value: int)` — select on_change; clamps to 0 or ≥ 5

### UI (Appearance menu, under "Show build status")

New row below the Refresh / Validate buttons:
- Checkbox: "Auto-refresh"
- When checked: interval `rx.select` appears (options: 0, 10, 15, 30, 60, 120, 300 s)
  with a trailing "s" label. `0` = on-change only.

### Docs

Updated `docs/framework/gui-build-status.md` with the Auto-refresh section.
