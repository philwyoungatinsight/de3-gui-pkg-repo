# 20260405-093700 — Wave status: "running" state and ⟳ icon

## Problem

While a pre/run/test component of a wave was executing, the icon showed
**✗** (red, failure) because the log file existed but had no done/fail marker
yet.  The user saw the failure icon for the entire duration of the test
(~15 s), then it switched to ✓ on the next 3-second poll.

## Fix

### `_wave_status` (nested fn in `refresh_wave_log_statuses`)

Added a `run_log_mtime: float | None` parameter.  When a log has no done/fail
marker, the function now checks the age of `run.log` in the same directory:

- **age < 300 s** → `"running"` (the wave is still executing)
- **age ≥ 300 s** → `"fail"` (crashed / timed out without writing a marker)

The 300-second threshold is a local constant `_RUNNING_THRESHOLD_SECS`.

`run_log_mtime` is computed once per directory with `run_log.stat().st_mtime`
and passed to all three `_wave_status` calls (main/precheck/test-playbook).

### `_wave_status_icon`

Added a middle `rx.cond` branch for `"running"`:

```
"none"    → – (dim dash)
"running" → ⟳ (amber, non-clickable, title="In progress…")
"ok"      → ✓ (green button, opens log)
"fail"    → ✗ (red button, opens log)
```

The ⟳ symbol is U+27F3 (CLOCKWISE GAPPED CIRCLE ARROW), rendered at 16 px
in `var(--amber-9)`.  It transitions to ✓ or ✗ on the next 3-second poll
after the script writes its done/fail marker.
