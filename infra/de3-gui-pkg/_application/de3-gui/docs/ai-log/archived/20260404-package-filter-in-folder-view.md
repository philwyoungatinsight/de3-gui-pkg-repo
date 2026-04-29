# 20260404 — Package filter + package pill in folder view

## What was added

### Package field on infra nodes

- Added `"package": ""` to the node dict in `_scan_infra()`.
- `_populate_module_tree_paths()` now also stamps `node["package"]` when it sets
  `module_tree_path`: extracts `parts[1]` from `<provider>/<package>/<module>`.
  Nodes with no module (folder nodes) keep `"package": ""`.

### Package filter

- New state var: `package_filters: dict = {}` (alongside `category_filters`, etc.)
- Initialised in all three node-cache init sites (on_load, rescan, update_inventory_and_dag)
  as `{"_none": True, **{n["package"]: True for n in flat if n.get("package")}}`.
- New computed vars:
  - `packages_with_visibility`: sorted list of `{name, is_visible}` dicts; includes
    a synthetic `_none` entry for HCL units with no package assigned.
  - `package_filter_active: bool`: True when any package is hidden.
- New event handlers: `toggle_package`, `solo_package`, `toggle_all_packages`.
- `visible_nodes` uses a `package_keep` set (same keep-set pattern as region/env/wave).
  Units with a package value match only if that value is visible; HCL units with no
  package match only if `"_none"` is visible.

### Package pill in tree node row

- A small monospace pill showing `node["package"]` appears to the **left of the type
  badge** in `tree_node_component` (between the name row and the type badge).
- Rendered only when `node["package"] != ""` (i.e. for leaf units with a known module).

### Package filter dropdown in filter bar

- `_pkg_filter_toggle_item(item)`: toggle item component with `(none)` display for `_none`.
- `_panel_packages()`: "Packages ▾" dropdown with All/None button and foreach items.
  Turns orange when `package_filter_active` is True.
- Placed **to the left of Categories** in the filter bar.
