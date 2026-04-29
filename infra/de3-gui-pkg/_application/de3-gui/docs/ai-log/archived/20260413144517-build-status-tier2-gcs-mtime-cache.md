# 20260413144517 — Build status Tier 2: GCS mtime cache + resource count

## Problem

The previous GCS scan used `gsutil ls -r` which returns only file paths (no timestamps).
Every bulk refresh re-used "file exists" as the status, not actual resource count, and
re-processed every file on every scan regardless of whether it had changed.

## What changed (Tier 2)

### `do_refresh_unit_build_statuses` rewritten

**`gsutil ls -l -r`** (was `gsutil ls -r`): the `-l` flag adds file size and mtime to each
output line in the format `<size>  <mtime>  <gcs_uri>`.

**mtime cache** (`gcs_state_mtimes: dict[str, str]`): after each scan the mtime string for
every `default.tfstate` path is saved in state. On the next scan, if a file's mtime matches
the cached value the previous status is carried forward and the file is NOT downloaded.

**Content-based status** (was presence-based): for files whose mtime changed (or first scan),
the state file is downloaded with `gsutil cat` and parsed as JSON. `resources` array length
determines the status:
- `resources` non-empty → `"ok"` (resources exist)
- `resources` empty → `"destroyed"` (clean destroy or pristine init)

**Merge with existing statuses**: the final dict starts from `prev_statuses` (which may
contain Tier 1 local-cache entries) and is overwritten by GCS-authoritative values.
GCS wins when it has data; local cache values survive for units not yet visible in GCS.

### New state var

`gcs_state_mtimes: dict[str, str]` — persists mtime strings between refreshes so that
only changed files are downloaded.

## Performance characteristics

- First bulk refresh: `gsutil ls -l -r` per package prefix (fast, one network round-trip
  per package), then `gsutil cat` for every state file (one per unit — same cost as before).
- Subsequent bulk refreshes: `gsutil ls -l -r` (cheap), then `gsutil cat` only for files
  whose mtime changed. On a stable lab with no recent applies: zero downloads.
- Accelerated Tier 1 local watcher runs in parallel and updates dots before GCS sees the change.
