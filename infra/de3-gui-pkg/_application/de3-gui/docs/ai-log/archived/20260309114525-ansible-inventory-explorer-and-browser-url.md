# Ansible Inventory Explorer and _browser_url Support

## Changes

### Ansible Inventory explorer root
- Added "Ansible Inventory" option to the Infra/Modules/Unit Templates dropdown (`explorer_root`)
- `ansible_inventory_view()` component reads the configured inventory file and displays it in the file viewer
- Includes an "↺ Update Inventory" button (see inventory auto-refresh log entry)

### `_browser_url` unit param
- Added `_get_browser_url_for_node(node_path)` helper
  - Scans `config_params` for `_browser_url`, returns most-specific (longest key) match
- If a node has `_browser_url`, an "Open" action (`action_type: url`) is injected into `selected_node_browser_actions`
- The browser panel shows this button alongside any other provider actions
- `has_node_browser_actions` boolean var gates the separator rendering

### Stack config updates (deploy/.../terragrunt_lab_stack.yaml)
Added `_browser_url` to:
- `"cat-hmc/proxmox/pwy-homelab/pve-nodes/pve-1/vms/maas-server-1"`:
  `_browser_url: "http://10.0.10.11:5240/MAAS/r/machines"`
- `"cat-hmc/maas/pwy-homelab"`:
  `_browser_url: "http://10.0.10.11:5240/MAAS/r/machines"`
