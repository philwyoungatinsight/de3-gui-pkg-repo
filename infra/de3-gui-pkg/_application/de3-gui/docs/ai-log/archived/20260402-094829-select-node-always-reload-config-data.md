# 2026-04-02 — select_node: always reload config_data content from disk

## Problem

`select_node` in `config_data` mode had an `if not self.hcl_content` guard, so it
only read the stack config file the first time. Subsequent node clicks (or watcher
reloads that didn't update `hcl_content`) left the viewer showing stale content —
e.g. a `_browser_url` edited on disk still showed the old hardcoded IP.

## Fix

Removed the `if not self.hcl_content` guard in `select_node`. Now always calls
`_read_stack_config_file()` and updates `hcl_content`/`hcl_file_path` on every
node select while in `config_data` mode.

**File:** `homelab_gui/homelab_gui.py` — `select_node()`
