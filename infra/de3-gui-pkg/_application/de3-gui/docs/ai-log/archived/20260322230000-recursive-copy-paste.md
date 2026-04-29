# 20260322230000 — Recursive copy/paste feature

## Summary

Implemented recursive copy/paste for folder subtrees in the context menu. Users can now right-click any folder node to copy its entire subtree of terragrunt units, then paste that subtree under any compatible folder (same provider) with a custom destination folder name.

## Changes made

All changes are in `homelab_gui/homelab_gui.py`.

### 1. New state vars (after existing paste/delete vars, ~line 2044)

Five new `AppState` fields:
- `recursive_clipboard_root: str` — folder path that was recursively copied
- `recursive_clipboard_items: list[dict]` — list of unit dicts with path, relative_path, hcl_filename, hcl_content, config_block, config_provider
- `recursive_paste_dialog_open: bool` — controls the new dialog
- `recursive_paste_pending_target: str` — target folder for pending paste
- `recursive_paste_pending_prefix: str` — editable destination folder name (defaults to source folder's last component)

### 2. New module-level helper `_collect_subtree_units` (~line 4849)

Placed immediately before `_read_hcl_file_for_merged`. Walks `_ALL_NODES_CACHE` for nodes whose path starts with `folder_path + "/"` and have `has_terragrunt=True`. For each: reads HCL file, looks up config block in `_STACK_CONFIG`, computes relative_path, and returns a list of dicts.

### 3. New handler methods in `AppState` (after `copy_unit`, ~line 4063)

- `copy_recursive(path)` — calls `_collect_subtree_units`, stores results in `recursive_clipboard_root` / `recursive_clipboard_items`, sets clipboard message
- `begin_recursive_paste(target_path)` — opens dialog, sets pending target/prefix
- `set_recursive_paste_prefix(name)` — updates editable prefix
- `recursive_paste_prefix_keydown(key)` — Enter key triggers confirm
- `cancel_recursive_paste()` — closes dialog
- `confirm_recursive_paste()` — full paste logic: provider validation, conflict check, filesystem pass (mkdir + write_text per unit), single-cycle YAML read/write for config blocks, cache refresh (same pattern as `confirm_paste`), success message

### 4. Context menu additions in `open_context_menu` (~line 4579)

- For folder nodes (`not has_terragrunt`): added "Copy subtree (recursive)" item before apply/delete recursive items
- For folder nodes when `recursive_clipboard_root` is set: added "Paste subtree '…' here (N units)" item after single-unit paste item

### 5. `dispatch_action` additions (~line 4714)

Two new branches after `begin_delete_recursive`:
- `copy_recursive` → `self.copy_recursive(value)`
- `begin_recursive_paste` → `self.begin_recursive_paste(value)`

### 6. New dialog in `index()` (~line 8506)

Added "Paste subtree" dialog before the existing delete dialog. Shows Into/Source paths, an editable input for the destination folder name (Enter = confirm), Cancel and Paste buttons. Paste button disabled when prefix is empty.

## Key design decisions

- Provider mismatch check uses `path.split("/")[1]` (index 1 = provider segment) on both source root and target path — same approach as `confirm_paste`
- Conflict check collects ALL conflicts before aborting, reporting up to 3 paths in the error message
- YAML is read once and written once for the entire subtree (not once per unit) to avoid race conditions
- Units with no config block are silently skipped (counted and appended to success message)
- Cache refresh replicates the exact same pattern used in `confirm_paste` (rebuild merged nodes, category/region/env/wave filters, expanded_paths)
