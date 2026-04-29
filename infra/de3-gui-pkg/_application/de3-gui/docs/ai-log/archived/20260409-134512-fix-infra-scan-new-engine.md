# 2026-04-09 — Fix infra scanning for new engine layout

## Problem

After the initial engine-refactor update (commit 724ffbe), the GUI showed no infra
nodes and no waves.  The root cause was that `_init_nodes_cache` and related
functions assumed the old engine path structure but the new engine puts all
deployable units under `infra/<pkg>/_stack/<provider>/...`.

## Root causes identified

1. **`_init_nodes_cache`** iterated `infra/<pkg>/` dirs and called `_scan_infra` on
   each package dir.  Package dirs contain ONLY `_`-prefixed children (`_config`,
   `_modules`, `_stack`), so `_scan_infra`'s `not d.name.startswith("_")` filter
   returned empty lists for every package → 0 nodes.

2. **`_scan_infra`** extracted provider from `current_parts[1]` (position of
   provider in old paths `cat/<provider>/...`).  New paths are
   `<pkg>/_stack/<provider>/...` so provider is at `current_parts[2]`.

3. **`_infer_type`** extracted provider from `parts[1]` for the same reason.

4. **`_build_merged_nodes`** stripped provider at `parts[1]` with
   `merged_parts = [parts[0]] + parts[2:]`.  New paths need to strip both `_stack`
   (parts[1]) AND provider (parts[2]): `merged_parts = [parts[0]] + parts[3:]`.

5. **Several event handlers** used `parts[1]` to extract the provider for display,
   config-file lookup, and copy-paste validation.

## Fixes in `homelab_gui/homelab_gui.py`

### `_init_nodes_cache`
- New loop: for each `infra/<pkg>/` with a `_stack/` subdir, create a synthetic
  depth-0 package node, then call `_scan_infra(provider_dir, depth=1,
  parts=[pkg_dir.name, "_stack"])` for each provider dir under `_stack/`.
- Added `traceback.print_exc()` on exception for better debugging.

### `_scan_infra`
- Provider extraction: `current_parts[1]` → `current_parts[2]`

### `_infer_type`
- Provider extraction: `parts[1]` → `parts[2]`
- Depth offsets unchanged (depth 1 = provider, 2 = env — same as before since
  we start scanning at depth=1 from provider dirs).

### `_build_merged_nodes`
- `merged_parts = [parts[0]] + parts[2:]` → `[parts[0]] + parts[3:]`

### Display / event handler fixes (all `parts[1]` → `parts[2]` for provider)
- `_get_unit_params_flat` display format string (line ~1797)
- `_selected_node_provider` fallback
- `navigate_to_source` merged-tree path and provider extraction
- `paste_unit` provider mismatch check
- `confirm_paste` provider extraction

## Verification

After fixes, importing the module shows:
- 7 providers loaded
- 180 config_params entries
- 21 waves
- 246 total nodes, 132 unit nodes, 157 nodes with wave assignments
- Correct type inference: depth-0 = category, depth-1 = provider, depth-2 = environment, etc.

## Files changed
- `homelab_gui/homelab_gui.py`
