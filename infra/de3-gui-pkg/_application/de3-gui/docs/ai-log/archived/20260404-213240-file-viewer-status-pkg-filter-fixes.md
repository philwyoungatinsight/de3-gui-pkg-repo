# 20260404-213240 — File viewer status msg + package filter fixes

## Changes

### 1. `packages_with_visibility` — include all `_PACKAGES_CACHE` names

Previously only collected package names from infra nodes that had a non-empty
`node["package"]` field. Packages that exist in the registry (`_PACKAGES_CACHE`)
but have no infra nodes referencing them (e.g. `demo-buckets-example`) were
invisible in the filter dropdown.

Fix: after iterating `self.all_nodes`, also iterates `_PACKAGES_CACHE` and appends
any names not already in `seen`.

### 2. `package_filters` initialization — all 3 sites updated

All three `package_filters = {"_none": True, **{...}}` sites (in `on_load`,
`rescan`, and `update_inventory_and_dag`) now also merge in `_PACKAGES_CACHE`
package names:

```python
self.package_filters = {"_none": True, **{
    n["package"]: True for n in flat if n.get("package")
}, **{pi.name: True for pi in _PACKAGES_CACHE if pi.name}}
```

This ensures packages from the registry are always toggleable, even if no infra
node currently references them.

### 3. File viewer empty-state UI — use `file_viewer_status_msg`

Replaced the hardcoded nested `rx.cond` tree:
```python
rx.cond(selected_node_path == "",
    rx.text("Select a node ..."),
    rx.cond(has_unit_params, rx.text("No unit file..."), rx.vstack(...))
)
```

With a single `rx.text(AppState.file_viewer_status_msg, ...)`.

`file_viewer_status_msg` is set by event handlers:
- `"Select a node to view its file"` — default (no node selected)
- `""` — cleared whenever a file is successfully loaded
- `"No unit file found for: {path}"` — when unit_file mode finds no content
- `"No config data found for: {path}"` — when config_data mode finds no match

### 4. `file_viewer_status_msg` cleared in all file-loading paths

Added `self.file_viewer_status_msg = ""` to:
- `navigate_to_source` (when content found)
- `open_wave_definition`
- `show_inventory`
- `click_modules_node` (also clears search queries; sets msg on empty content)
- `navigate_to_module` (also clears search queries; sets msg on empty content)

These paths were previously not touching `file_viewer_status_msg` and could
leave a stale error message visible after navigating away from a node with no file.
