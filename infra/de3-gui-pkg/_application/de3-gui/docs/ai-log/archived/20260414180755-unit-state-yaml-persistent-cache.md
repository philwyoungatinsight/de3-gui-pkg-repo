# Unit State YAML — Persistent Status Cache

## What changed

Introduced `~/.run-waves-logs/unit-state.yaml` as a persistent per-unit status cache,
co-located with the wave run logs.  This eliminates the "blank on restart" problem and
makes the "⟳ Refresh" button near-instant (YAML read instead of GCS scan).

### New module-level helpers (`homelab_gui.py`)

- **`_unit_state_path()`** — returns the YAML path, honouring `config.wave_logs_dir`
- **`_read_unit_state()`** — safe reader; returns `{}` on any error
- **`_write_unit_state(updates)`** — atomic writer via `.yaml.tmp` + `os.rename()`; uses
  `_unit_state_lock` (`threading.Lock`) to prevent concurrent write corruption

### YAML schema

```yaml
schema_version: 1
units:
  <unit_path>:
    status: ok | fail | destroyed | unknown
    resources_count: <int>        # from GCS tfstate (set by validate path)
    last_apply_exit_code: <int>   # 0 or 1 (set by exit-file Tier 3)
    last_apply_at: <ISO-8601>     # when local_state_watcher last detected a change
    last_validated_at: <ISO-8601> # when GCS scan last confirmed this status
```

### `on_load` — instant startup status

Replaced the "clear unit_build_statuses" block with a YAML read.  On app restart,
`unit_build_statuses` is populated immediately from the YAML (zero latency, no network).
GCS mtime cache is still cleared so the next validate does a full diff.

### `local_state_watcher` — writes YAML on every detected apply

Both the Tier 1 path (GCS cat after `.terragrunt-cache` change) and the Tier 3 path
(exit-code file) now call `_write_unit_state()` after updating `unit_build_statuses`.
Fields written: `status`, `last_apply_at` (Tier 1 + 3), `last_apply_exit_code` (Tier 3).

### `refresh_unit_build_statuses` / `do_refresh_unit_build_statuses` — fast path

`do_refresh_unit_build_statuses` now **reads the local YAML** instead of hitting GCS.
Completes in milliseconds.  Button label changed from "⟳ Refresh status" to "⟳ Refresh".

### New: `validate_unit_build_statuses` / `do_validate_unit_build_statuses`

Contains the original GCS scan logic (formerly in `do_refresh_unit_build_statuses`).
After the scan, writes `last_validated_at` and `resources_count` to unit-state.yaml.
Exposed in the UI as a new "Validate (GCS)" button next to "⟳ Refresh".

### `do_refresh_subtree_status` — also writes YAML

Subtree GCS scans now persist their results to unit-state.yaml with `last_validated_at`.

### `apply_unit` — per-unit log files

Shell command now:
1. Creates `~/.run-waves-logs/unit-logs/<unit-path>/` directory
2. Timestamps a per-run log file (`YYYYMMDD-HHMMSS.log`)
3. Sets `latest.log` symlink to the current run's file
4. Tees terragrunt output to both terminal and the log file
5. Uses `${PIPESTATUS[0]}` (not `$?`) so the exit code file captures terragrunt's
   return code through the tee pipe

## UI changes

The status section in the explorer Appearance popover now shows two buttons:
- **⟳ Refresh** — reads unit-state.yaml (instant)
- **Validate (GCS)** — runs the full GCS scan and updates the YAML
