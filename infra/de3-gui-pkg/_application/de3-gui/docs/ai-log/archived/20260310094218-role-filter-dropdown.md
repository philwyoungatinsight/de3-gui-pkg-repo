# Role Filter Dropdown

## Feature
Added a multi-select role filter to the left panel (below the search box), driven by
the Ansible inventory file's `additional_tags` field.

## Behaviour
- Dropdown shows all roles sorted alphabetically, with "All Roles" at the top (default).
- Selecting one or more roles shows only nodes whose inventory hostname matches a role,
  plus all ancestors up to the category root (same logic as the search filter).
- Multiple roles are OR-combined: paths to any selected role are shown.
- Applied in all three views: tree (separated + merged), Nested Networks (Cytoscape),
  and Tree2 (ReactFlow).

## Implementation

### State vars added
```python
available_roles: list[str] = []     # sorted role tags from inventory
node_name_roles: dict = {}          # {hostname: [role_tags]}
selected_roles: list[str] = []      # active role filters; empty = All Roles
```

### `_build_role_maps()`
Module-level helper that reads the Ansible inventory YAML and returns
`(sorted_role_tags, {hostname: [roles]})`.

Key fix: uses `for hostname, hvars in hosts.items()` (the inventory YAML key is
the hostname, e.g. `image-maker`) rather than `hvars.get("node_name")` (which is
the Proxmox hypervisor name, e.g. `pve`). The hostname is what matches infra node
names.

### `on_load`
Calls `_build_role_maps()` to populate `available_roles` and `node_name_roles`.

### `update_inventory_and_dag`
Rebuilds role maps after inventory refresh.

### `visible_nodes` and `merged_visible_nodes`
Both use a shared `_keep_paths_for(nodes, match_fn)` helper + lambda:
```python
lambda n: any(r in nm_roles.get(n.get("name", ""), []) for r in sel_roles)
```
`filtering = bool(search or sel_roles)` gates the normal expand/collapse logic.

### `cytoscape_elements`, `reactflow_nodes`, `reactflow_edges`
Added `role_keep` set pre-computation and element filtering to extend role filter
support to the Cytoscape (Nested Networks) and ReactFlow (Tree2) views.

### UI: `_panel_roles()` and `_role_toggle_item()`
Role filter dropdown placed after the search box in `infra_controls`. Multi-select
via checkboxes; clicking "All Roles" clears `selected_roles`.
