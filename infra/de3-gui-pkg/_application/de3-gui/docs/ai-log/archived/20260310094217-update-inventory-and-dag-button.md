# Update Inventory (and DAG) Button + Script Path Fix

## Changes

### Renamed "Update Inventory" → "Update Inventory (and DAG)"
- Button now calls `update_inventory_and_dag` instead of `update_inventory`
- Mimics a full app restart: re-scans infra dir, rebuilds all node caches, refreshes inventory

### New `update_inventory_and_dag` event handler
- Generator-style handler (uses `yield`) so Reflex pushes the "running" state to the browser
  before blocking on the inventory script
- Calls `_init_nodes_cache()`, `_init_reactflow_cache()`, `_init_modules_cache()` to rebuild
  all module-level caches from disk
- Calls `_run_inventory_refresh(background=False)` and raises if it returns an error string
- Reloads all DAG state vars from the refreshed caches (mirrors `on_load` logic):
  `all_nodes`, `merged_nodes_base`, `category_filters`, `region_filters`,
  `expanded_paths`, `merged_expanded_paths`, `modules_nodes`, `unit_templates_nodes`, etc.
- Reloads the file viewer if it is currently showing the inventory file

### Button status feedback (yellow/red/blue)
- Added state vars:
  - `dag_refresh_status: str = "idle"`  — `"idle"` | `"running"` | `"error"`
  - `dag_refresh_error: str = ""`
- Button `color_scheme` driven by `rx.cond`:
  - `"yellow"` while running
  - `"red"` on error
  - `"blue"` (normal) when idle
- Button label changes to `"↺ Updating…"` while running; disabled to prevent double-clicks
- Error text rendered below the button (red, 11px) when status is `"error"`

### Fixed inventory refresh script path + added `args` support
- `config/de-gui.yaml`: corrected `ansible_inventory_refresh.script` from the non-existent
  `../../../../k8s-recipes/scripts/update-ansible-inventory.sh` to
  `scripts/generate_ansible_inventory/run` (relative to `_STACK_DIR`)
- Added `args: ["-b"]` so the run script receives the build flag
- `_run_inventory_refresh`: reads optional `args` list (or space-separated string) from config
  and appends to the subprocess command
- `_run_inventory_refresh` return type changed from `None` to `Optional[str]`:
  returns `None` on success, an error string on failure (only meaningful in blocking mode)
