# GUI Background Tasks

All continuously-running background coroutines in the `homelab_gui.py` Reflex application.
See also: `docs/background-jobs.md` for the cross-package central index.

---

## Overview

The GUI has five background tasks. They are all `@rx.event(background=True)` async methods
on `AppState`, started from `on_load`:

| Task | Lifetime | Per instance | Poll interval |
|------|----------|--------------|---------------|
| `local_state_watcher` | Process (singleton) | One per server process | 8 s / 2 s accelerated |
| `sync_unit_status_from_gcs` | One-shot | One per page load | — |
| `sync_wave_status_from_gcs` | One-shot | One per page load | — |
| `config_file_watcher` | Session (per client) | One per connected browser tab | 2 s |
| `signal_inventory_ready` | One-shot | One per page load | 1 s (max 120 s) |

---

## `local_state_watcher`

**Method**: `AppState.local_state_watcher` in `homelab_gui.py:8794`
**Trigger**: `on_load` event; guarded by `_LOCAL_STATE_WATCHER_RUNNING` process-global so
only one instance runs per server process lifetime.

### What it does

Detects apply/destroy activity and updates `unit_build_statuses` for each affected unit.
Uses a four-tier detection strategy (highest priority first):

**Tier 0 — exit-status YAMLs** (primary, no network calls)

Scans `$_DYNAMIC_DIR/unit-status/exit-*.yaml`. These files are written by
`utilities/tg-scripts/write-exit-status/run` (called from `root.hcl`'s `after_hook`)
exactly once per apply/destroy, then consumed (deleted) by this watcher on first read.

Each file:
```yaml
unit_path: infra/maas-pkg/_stack/maas/pwy-homelab/machines/ms01-01/commission
status: ok        # or: fail
finished_at: 2026-04-16T13:05:00Z
```

**Tier 0b — MaaS intermediate-status YAMLs** (live phase during long MaaS operations)

Scans `$_DYNAMIC_DIR/unit-status/maas-*.yaml`. These files are written by the four MaaS
polling scripts (commission-and-wait.sh, wait-for-ready.sh, wait-for-deployed.sh) every
poll iteration (~10–30 s). Unlike Tier 0 files, these are NOT consumed — they are re-read
every watcher cycle until the apply completes, at which point `write-exit-status/run`
deletes them.

Each file:
```yaml
unit_path: infra/maas-pkg/_stack/maas/pwy-homelab/machines/ms01-01/commission
phase: commissioning    # or: ready / deploying
message: "Waiting for MaaS commissioning (elapsed: 4m12s, timeout: 2400s)"
machine_id: abc123
started_at: 2026-04-16T13:00:00Z
updated_at: 2026-04-16T13:04:12Z
```

The GUI writes `maas_phase` and `maas_message` into the unit's `unit-state.yaml` and
shows them in the hover popup. `last_apply_at` is also advanced so the Auto-select
button tracks the active node every 30 s.

See `infra/maas-pkg/_docs/background-processes.md` for the MaaS script reference
(file schema, env vars, stuck-detection, recovery).

Units already resolved by Tier 0 (exit-status YAML consumed) are skipped in Tier 0b —
no double-processing.

**Tier 3 — `$_GUI_DIR/homelab_gui_apply_*.exit`** (for GUI-initiated applies)

Reads exit files written by `apply_unit()` in the GUI itself. Covers the window between
apply start and when the Tier 0 YAML arrives — definitive failure signal when exit ≠ 0.

### Accelerated polling

Normal poll interval is 8 s. When `apply_unit()` or `apply_recursive()` fires, the
watcher is accelerated to 2 s for 60 s via `_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL`:

```python
_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL = time.time() + 60
```

This ensures the GUI reacts quickly to apply completion without burning CPU during
idle periods.

### `unit-state.yaml` schema (v2)

The watcher writes and reads `unit-state.yaml` per unit (in `$_DYNAMIC_DIR/unit-state/`):

```yaml
schema_version: 2
unit_path: infra/maas-pkg/_stack/maas/pwy-homelab/machines/ms01-01/commission
status: ok                    # ok | fail | unknown | destroyed | (empty)
details: ""                   # one-line detail string (e.g. from Tier 1 GCS read)
maas_phase: commissioning     # commissioning | ready | deploying | (empty)
maas_message: "..."           # live status message from MaaS polling script
last_apply_at: 2026-04-16T13:05:00Z
last_validated_at: 2026-04-16T13:05:00Z
last_apply_exit_code: 0
```

The hover popup `_ORDER` shows: `status`, `maas_phase`, `maas_message`, `details`,
`last_apply_at`, `last_validated_at`, `last_apply_exit_code`.

---

## `sync_unit_status_from_gcs`

**Method**: `AppState.sync_unit_status_from_gcs`
**Trigger**: `on_load` event; one-shot per page load.

### What it does

Pulls unit build statuses written by `write-exit-status/run` to the GCS
`unit_status/<unit_path>/<ts>.json` prefix. On first call (empty cursor) fetches all
objects; subsequent calls filter by timestamp to fetch only newer entries.

Merges results into `unit_build_statuses` and writes to `unit-state.yaml` so dots are
populated from prior sessions without waiting for a manual "Validate (GCS)" scan. Uses
`unit_status_sync_after` as a cursor (ISO timestamp stored in Reflex state).

---

## `sync_wave_status_from_gcs`

**Method**: `AppState.sync_wave_status_from_gcs`
**Trigger**: `on_load` event; one-shot per page load.

### What it does

Pulls wave phase statuses written by the wave runner to GCS `wave_status/<wave>/<ts>.json`.
Takes the newest object per wave name and stores results in `gcs_wave_statuses` (Reflex
state var). `refresh_wave_log_statuses()` merges these into the waves panel for any wave
not already present in the current session's `run.log` — recovering wave history from
before this session.

Uses `wave_status_sync_after` as a cursor (ISO timestamp stored in Reflex state).

---

## `config_file_watcher`

**Method**: `AppState.config_file_watcher` in `homelab_gui.py:7641`
**Trigger**: `on_load` event; one instance per connected browser client (not a singleton).

### What it does

Polls mtimes of all stack config YAMLs (`infra/**/_config/*.yaml`) and the SOPS secrets
file (`infra/default-pkg/_config/secrets.sops.yaml`) every 2 s.

When any YAML changes:
- Calls `_load_stack_config()` and `_init_path_param_maps()` to reload in-memory config
- Rebuilds `all_nodes`, `merged_nodes_base`, `region_filters`, `env_filters`, `wave_filters`
- If the file viewer is showing config data, refreshes `hcl_content`

When only the SOPS secrets file changes:
- Sets `_SOPS_SECRETS_LOADED = False` to force lazy re-decrypt on next access
- Bumps `wave_filters` to trigger a repaint (without re-scanning all nodes)

### Why per-client

The Reflex state is per-session, so `all_nodes` and filter state belong to each session.
Each browser tab gets its own watcher that writes to that tab's state snapshot.

---

## `signal_inventory_ready`

**Method**: `AppState.signal_inventory_ready` in `homelab_gui.py:7620`
**Trigger**: `on_load` event; one-shot per page load.

### What it does

The inventory cache (`infra/<pkg>/_config/ansible-inventory/hosts.yml` and related files)
may be populated lazily in the background after the GUI starts. This task:

1. Polls `_INVENTORY_REFRESH_COMPLETE` every 1 s (up to 120 s)
2. When the flag is set (background inventory thread finished), increments
   `inventory_refresh_counter`
3. `selected_node_browser_actions` depends on `inventory_refresh_counter` via Reflex's
   reactive graph, so it recomputes — making SSH buttons appear even if the inventory
   cache was empty at initial page load
4. Exits after signalling (not a persistent loop)

### Interaction with other tasks

- `signal_inventory_ready` is entirely independent of `local_state_watcher`
- It does not read or write `unit-state.yaml`
- It does not affect `unit_build_statuses`
- The background inventory thread that sets `_INVENTORY_REFRESH_COMPLETE` is started
  at import time (process startup) and runs once; it is not a recurring task

---

## Shared Infrastructure

### `_DYNAMIC_DIR`

Set by `set_env.sh` to `<repo-root>/config/tmp/dynamic/`. All status files and runtime
state go here. Paths derived from it:
- `$_DYNAMIC_DIR/unit-status/` — Tier 0 and Tier 0b status YAMLs
- `$_DYNAMIC_DIR/unit-state/<unit-rel-full>.yaml` — persistent unit state written by watcher
- `$_DYNAMIC_DIR/kubeconfig/` — per-cluster kubeconfig files (unrelated to GUI tasks)

The watcher resolves `_DYNAMIC_DIR` from `os.environ["_DYNAMIC_DIR"]`, falling back to
`<git-root>/config/tmp/dynamic/` if the env var is not set (for dev runs without `set_env.sh`).

### Global singletons and flags

| Global | Purpose |
|--------|---------|
| `_LOCAL_STATE_WATCHER_RUNNING` | Ensures only one `local_state_watcher` per process |
| `_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL` | Unix timestamp; watcher polls at 2 s until this time |
| `_INVENTORY_REFRESH_COMPLETE` | Set by background inventory thread; polled by `signal_inventory_ready` |
| `_SOPS_SECRETS_LOADED` | False → force lazy re-decrypt of SOPS secrets on next access |
| `_UNIT_STATE_YAML_MTIME` | Last observed mtime of `unit-state.yaml`; used by auto-refresh |
| `_UNIT_STATE_LAST_AUTO_REFRESH` | Unix timestamp of last auto-refresh from `unit-state.yaml` |
