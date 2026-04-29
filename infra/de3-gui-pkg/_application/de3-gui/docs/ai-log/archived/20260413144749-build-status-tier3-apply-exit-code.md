# 20260413144749 — Build status Tier 3: apply exit code capture

## Problem

Tiers 1 and 2 know whether resources exist in state, but cannot tell whether the
most recent apply *succeeded* or *partially failed*. A partial failure (3 of 5
resources created then error) looks identical to "ok" — state is non-empty.

There is no "terminal done" callback in the embedded terminal, so the GUI cannot
directly observe when a command exits.

## What changed (Tier 3)

### `apply_unit` — exit code file

The shell command is now wrapped to capture the exit code:
```bash
source set_env.sh && terragrunt apply -- -auto-approve; echo $? > /tmp/homelab_gui_apply_<safe_path>.exit
```

The safe path uses `+` as path separator (never appears in unit paths), making the
filename reversible: `pwy-home-lab-pkg+_stack+maas+...+ms01-01.exit`.

`apply_recursive` is NOT wrapped — individual unit states are picked up by Tier 1
as each unit completes within the recursive run. The exit code for the whole subtree
would not map cleanly to individual unit statuses.

### `local_state_watcher` — exit file scan (Tier 3 extension)

Each loop iteration now also does:
1. `glob.glob("/tmp/homelab_gui_apply_*.exit")` — check for new exit files
2. Read content, parse as int (exit code)
3. Recover unit path by reversing the `+` → `/` encoding
4. If exit code != 0: set status to `"fail"` (definitive failure)
5. If exit code == 0: log confirmation; Tier 1 tfstate read already has the correct status
6. Remove the exit file unconditionally after reading (one-shot)

This runs on every watcher loop iteration (every 2–8 s), so exit files are consumed
within one poll interval after the apply finishes.

## Status accuracy after all three tiers

| Scenario | Status | Source |
|---|---|---|
| Apply succeeded, resources > 0 | `"ok"` | Tier 1 (local tfstate) + Tier 3 (exit 0 logged) |
| Apply failed partway, resources > 0 | `"fail"` | Tier 3 (exit != 0 overrides Tier 1 ok) |
| Apply failed before any resources | `"fail"` | Tier 3 (exit != 0) or Tier 2 (no GCS state) |
| Destroy succeeded | `"destroyed"` | Tier 1 (resources == []) |
| Never applied | `"none"` | Tier 1 + 2 (no state anywhere) |
| Recursive apply in progress | Real-time updates per unit | Tier 1 as each unit writes tfstate |
