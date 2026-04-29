# 20260413144309 — Build status Tier 1: local .terragrunt-cache watcher

## Problem

The previous build status system used two sources:
1. `gsutil ls -r` to find `default.tfstate` files in GCS — presence only, no content check
2. `run.log` "Unit queue" lines — only populated after a `./run` wave run

This meant:
- Applying a single unit from the GUI context menu or shell never updated the status dots
- A destroyed unit (empty state) and a never-built unit both showed grey
- Status was "file exists", not "resources exist"

## What changed (Tier 1)

### New: `local_state_watcher` background task

A process-level singleton loop (`@rx.event(background=True)`) that runs for the lifetime
of the server process. Every 8 s (normal) or 2 s (accelerated):

1. Runs `find <infra_dir> -path "*/.terragrunt-cache/*/terraform.tfstate" [-newer <marker>]`
2. For each found path, strips `.terragrunt-cache/...` to recover the unit path relative to `infra/`
3. Reads and parses the local state JSON; checks `resources` array length
4. Merges `{unit_path: "ok" | "destroyed"}` into `unit_build_statuses` — does not replace the whole dict

A `/tmp/homelab_gui_state_check.marker` file is touched after each scan so subsequent
runs only process newly-changed files (`-newer` flag).

First run (no marker): full baseline scan of all existing local caches.

### Acceleration on apply_unit / apply_recursive

Both methods now set `_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL = time.time() + 60.0`
immediately when called, switching the watcher to 2 s poll intervals. Status dots
update within seconds of an apply completing.

### New "destroyed" status (purple dot)

`resources == []` in the local state file → status `"destroyed"` (purple dot, tooltip
"Destroyed — state is empty"). Previously indistinguishable from "never built" (grey).

### Module-level globals added

```python
_LOCAL_STATE_WATCHER_RUNNING: bool         # process singleton guard
_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL: float  # fast-poll deadline
_LOCAL_STATE_WATCHER_FOCUS_PATHS: list[str]   # unit paths targeted by last apply
```

### State var added

`local_state_watcher_active: bool` — True while the loop is alive (for future UI use).

### on_load

`AppState.local_state_watcher` added to the scripts list. The singleton guard makes
this safe to dispatch on every page load; it returns immediately if already running.

## Status values after Tier 1

| Value | Colour | Meaning |
|---|---|---|
| `"ok"` | Green | Resources exist in local state |
| `"destroyed"` | Purple | State file exists but resources = [] |
| `"fail"` | Red | In run.log queue, no GCS state (from bulk refresh) |
| `"none"` | Grey | No evidence anywhere |

GCS bulk refresh (`do_refresh_unit_build_statuses`) still runs on demand and on wave
completion — Tier 1 supplements it with real-time local data; it does not replace it.
