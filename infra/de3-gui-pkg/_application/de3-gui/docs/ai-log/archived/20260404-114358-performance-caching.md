# 20260404-114358 — Performance: caching + debounced config writes

## Problem
Clicking tree nodes was slow. Each click blocked on:
1. `_load_config()` — YAML-parsed `de-gui.yaml` on every call (called inside `_read_hcl_file`)
2. `_read_hcl_file()` — full directory scan + file read on every click, no cache
3. `_save_current_config()` — synchronous read+write of `current.yaml` on every click

## Fixes

### 1. `_load_config()` — mtime cache
Added `_config_cache: dict` + `_config_mtime: float` module globals.
`_load_config()` now checks `config_file.stat().st_mtime` before parsing YAML.
Only re-reads when the file actually changes. Eliminates YAML parse on every click.

### 2. `_read_hcl_file()` — two-level mtime cache
- `_hcl_path_cache: dict[str, str]` — maps `node_path → abs_path` (or `""` for not-found).
  Avoids calling `_find_unit_hcl()` (directory scan) on every click.
  Cleared in `_init_nodes_cache()` so rescans pick up new/moved files.
  On `FileNotFoundError` the entry is evicted so the next call re-probes.
- `_hcl_content_cache: dict[str, dict]` — maps `abs_path → {mtime, content}`.
  Avoids re-reading the file when mtime is unchanged.
  After the first click on a node, subsequent clicks only cost one `stat()` call.

### 3. `_save_current_config()` — debounced background write
- Added `import threading as _threading` at top-level imports.
- Added `_state_write_lock` (threading.Lock) shared by all `current.yaml` writers.
- Added `_save_timer` (threading.Timer | None) for debouncing.
- `_do_write_menu(menu_data)` — background function that merges menu_data into
  `current.yaml` under `current.menu`, preserving unmanaged keys (providers, etc.).
- `_schedule_config_write(menu_data)` — cancels pending timer, schedules new one 800 ms out.
- `_save_current_config()` now builds a menu_data snapshot dict and calls
  `_schedule_config_write()` — returns instantly instead of blocking on file I/O.
- Result: rapid node clicks produce at most one disk write per 800 ms instead of one per click.
- `_save_ext_package_repos()` now uses the same `_state_write_lock` to prevent races.

### 4. Tree highlight fix (previous commit)
`click_node` already `yield`s immediately after setting `selected_node_path` +
`expanded_paths`, so the tree highlight appears before any file I/O.
