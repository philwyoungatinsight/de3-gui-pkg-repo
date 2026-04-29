# 2026-04-02 — config_file_watcher: refresh file viewer on YAML change

## Problem

`config_file_watcher` reloads `_STACK_CONFIG` and updates the node tree when the stack
config YAML changes on disk, but never refreshed `hcl_content` / `hcl_file_path`. The file
viewer in `config_data` mode kept showing the stale file content until the user manually
reloaded (e.g. switched mode and back).

## Fix

In `config_file_watcher`, inside the `async with self` block, when `yaml_changed` is True
and `self.file_viewer_mode == "config_data"`, re-read the stack config file via
`_read_stack_config_file()` and update `self.hcl_content` / `self.hcl_file_path`.

**File:** `homelab_gui/homelab_gui.py`
