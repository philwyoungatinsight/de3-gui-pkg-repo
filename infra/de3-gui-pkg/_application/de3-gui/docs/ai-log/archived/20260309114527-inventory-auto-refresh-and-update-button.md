# Ansible Inventory Auto-Refresh and Update Button

## Changes

### Inventory auto-refresh on startup
- Added `ansible_inventory_refresh` section to `config/de-gui.yaml`:
  ```yaml
  ansible_inventory_refresh:
    enabled: true
    script: "../../../../k8s-recipes/scripts/update-ansible-inventory.sh"
  ```
- `_run_inventory_refresh(background=True/False)` reads the config and runs the script
  - In background mode: `threading.Thread(daemon=True)` runs the script in its own directory
  - Busts `_INVENTORY_HOSTS_CACHE` on completion so fresh IPs are used
- `_INVENTORY_REFRESH_DONE` module-level flag ensures the refresh runs exactly once per process
  (Reflex 0.8.27 fires `on_load` twice per page load)
- `on_load()` calls `_run_inventory_refresh(background=True)` when flag is False, then sets flag

### "Update Inventory" ad-hoc button
- `update_inventory` event handler:
  - Runs `_run_inventory_refresh(background=False)` (blocking, waits for script to finish)
  - Reloads inventory file into the file viewer if `explorer_root == "ansible_inventory"`
    or if the inventory file is currently displayed
- Button added to `ansible_inventory_view()`:
  ```
  ↺ Update Inventory   (color_scheme=blue, variant=soft)
  ```
  with tooltip "Run the configured inventory-refresh script and reload the file viewer"
