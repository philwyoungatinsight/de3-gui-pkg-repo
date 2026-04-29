# 20260403-163013 — Restore performance: mtime cache for _read_stack_config_file

## Problem
commit fe3eb43 removed the `if not self.hcl_content` guard in `select_node`
(config_data mode) to fix stale file viewer content. This made every node click call
`_read_stack_config_file()` unconditionally, which:
1. Calls `_find_stack_config()` → `_find_stack_configs()` → `subprocess.run(git rev-parse)`
   on every click
2. Reads the full YAML from disk on every click

## Fix: mtime-based cache in `_read_stack_config_file()`

Added `_stack_config_file_cache` module-level dict tracking:
- `path` — resolved `Path` (cached after first successful find; avoids repeated git subprocess calls)
- `mtime` — mtime of last disk read
- `content` / `str_path` — cached return values

On each call:
- If `path` is None → find it once via `_find_stack_config()` and cache it
- If `path.exists()` is False → clear path cache so it re-probes next call
- If `path.stat().st_mtime == cached mtime` → return cached content (no disk I/O)
- Otherwise → read from disk and update cache

The existing `config_file_watcher` (2s mtime polling) triggers `_load_stack_config()`
when the file changes. `_read_stack_config_file` will detect the new mtime on the next
node click and re-read automatically — no explicit cache invalidation needed.
