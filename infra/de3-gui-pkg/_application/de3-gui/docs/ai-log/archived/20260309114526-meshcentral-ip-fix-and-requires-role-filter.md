# MeshCentral IP Fix and requires_role Action Filter

## Changes

### MeshCentral UI wrong IP fix
- "MeshCentral UI" context menu button was opening `https://10.0.10.115/` (stale stack config IP)
  instead of `https://10.0.10.193/` (correct live IP from Ansible inventory)
- Root cause: `_get_node_actions` used `_get_resolved_params` (stack config) for `ansible_host`
- Fix: after stack param resolution, overlay `ansible_host` from Ansible inventory
  - Direct hostname match in inventory hosts dict
  - Prefix match fallback for partial node name matches
- Ansible inventory is now the authoritative source for live host IPs

### `requires_role` action filter in provider-actions.yaml
- Added `requires_role` field to action definitions in `config/provider-actions.yaml`
- `_get_node_roles(node_path)` helper collects `additional_tags` from all ancestor `config_params`
  and returns the union as a set of role strings (e.g. `role_mesh_central`)
- `_get_node_actions` skips actions where `requires_role` is set but not present in the node's roles
- `mesh_central_ui` action updated:
  - Removed fragile `node_path_contains: "mesh-central"` filter
  - Replaced with `requires_role: role_mesh_central`
- Added `requires_role` documentation to the YAML comments block
