# ai-log: Fix module_tree_path always empty at runtime

**Date:** 2026-04-01  
**Branch:** feat/gui

## Problem

`show_full_module_name` showed nothing (empty string) for all nodes.

## Root cause

`_populate_module_tree_paths()` stamps `module_tree_path` onto the node objects
in `_ALL_NODES_CACHE`. It was called at module level (startup) and in the manual
rescan handler, but NOT in `on_load`.

`on_load` calls `_init_nodes_cache()`, which replaces all objects in
`_ALL_NODES_CACHE` with freshly created nodes whose `module_tree_path` is `""`.
The previously stamped values (from module-level startup) were discarded.
Since `self.all_nodes` is then set from these fresh objects, every node seen by
the UI had `module_tree_path = ""`.

## Fix

Added `_populate_module_tree_paths()` call in `on_load` immediately after
`_init_nodes_cache()`, mirroring the order used in `update_inventory_and_dag`.

Also reverted the defensive `module_tree_path != ""` fallback introduced in the
previous (incorrect) fix attempt — it is no longer needed.

## Files modified
- `homelab_gui/homelab_gui.py`
