# 20260413152638 — Fix: stale "destroyed" status on app load

## Problem

After a server restart (or hot-reload), units that were correctly applied sometimes
showed a purple "destroyed" dot. The root cause was:

1. `on_load` restores `show_unit_build_status: True` from `current.yaml` but did NOT
   trigger a Tier 2 (GCS) refresh. Only Tier 1 (local `.terragrunt-cache` watcher)
   ran automatically.

2. If old code (pre-4b372270) had set "destroyed" in `unit_build_statuses` by reading
   local `.terragrunt-cache/*/terraform.tfstate` content (which is always empty with a
   GCS backend), those stale entries persisted in Reflex state across hot-reloads.

3. Without a Tier 2 refresh, the stale "destroyed" entries were never overwritten with
   the authoritative GCS status.

## Fix (`on_load`)

When `show_unit_build_status` is `True` on load:

1. **Clear stale caches**: reset both `unit_build_statuses` and `gcs_state_mtimes` to
   empty dicts so the first Tier 2 scan downloads all state files fresh.

2. **Set spinner flag**: set `is_refreshing_build_statuses = True` immediately so the
   UI shows "Updating…" while the scan runs.

3. **Dispatch Tier 2**: append `AppState.do_refresh_unit_build_statuses` to the scripts
   list so a full GCS scan runs on every page load (not just on first toggle-on).

This guarantees that:
- Stale "destroyed" entries from old code are wiped on every server start / page load.
- Dots show correct status within a few seconds of loading (GCS scan time).
- The mtime cache starts fresh so all state files are re-read.

## Behaviour

| Scenario | Before | After |
|---|---|---|
| App starts with `show_unit_build_status: true` | Only Tier 1 runs; stale "destroyed" persists | Tier 2 triggers immediately; fresh GCS status |
| User toggles "Show build status" on | Tier 2 triggered | Same (unchanged) |
| User clicks "⟳ Refresh status" | Tier 2 triggered | Same (unchanged) |
| Multiple page loads | Stale state accumulates | Cache cleared on each load; fresh scan |

## Files changed

- `homelab_gui/homelab_gui.py` — `on_load`: clear caches, set spinner, dispatch Tier 2
