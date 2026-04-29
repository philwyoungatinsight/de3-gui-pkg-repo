# ai-log: Role filter reads from stack config instead of Ansible inventory only

**Date:** 2026-04-01  
**Branch:** feat/gui

## Problem

The Roles filter dropdown only showed roles for nodes that had already been
Ansible-provisioned (present in `hosts.yml`). Nodes like `pxe-test-vm-1` that
have `additional_tags: [role_pxe_test]` in the stack config YAML but are not
yet in the Ansible inventory were invisible to the filter.

## Root cause

`_build_role_maps()` read exclusively from `_load_inventory_hosts()` (the
generated Ansible inventory `hosts.yml`). It ignored the `additional_tags`
already present in the stack config's `config_params` — which is the authoritative
source for all nodes whether deployed or not.

## Fix

### New cache
- `_PATH_TO_ROLES_CACHE: dict[str, list[str]]` — full infra path → accumulated role tags.

### Extended `_build_path_param_maps()`
- Now returns a 4th element: `path_to_roles`.
- Collects `additional_tags` entries starting with `role_` from all matching
  `config_params` prefixes, using **union semantics** (all ancestor tags accumulated,
  consistent with `_get_node_roles()`).

### Updated `_init_path_param_maps()`
- Unpacks and sets `_PATH_TO_ROLES_CACHE`.

### Rewritten `_build_role_maps()`
- Primary source: `_PATH_TO_ROLES_CACHE` (stack config, covers all nodes).
- Supplement: Ansible inventory (for hosts in inventory but not in stack config),
  matched by last path-segment name.
- Returns `{full_node_path: [role_tags]}` instead of `{hostname: [role_tags]}`.

### Updated all 5 role lookup sites
Changed from name/label lookup to full-path lookup:
- `cytoscape_elements`: `nm_roles.get(node_id, [])` (was `nm_roles.get(label, [])`)
- `reactflow_nodes`: `nm_roles.get(n["id"], [])` (was `nm_roles.get(label, [])`)
- `reactflow_edges`: same as reactflow_nodes
- `visible_nodes` `_role_match`: `_nm.get(n["path"], [])` (was `n.get("name", "")`)
- `visible_merged_nodes` `_m_role_match`: same as visible_nodes

## Result

All 8 role tags now appear in the filter, including `role_pxe_test` for
`pxe-test-vm-1` which was previously missing.

## Files modified
- `homelab_gui/homelab_gui.py`
