# SSH to host context menu + configurable identity params

**Date:** 2026-03-09

---

## 1. "SSH to host" in the right-click context menu

**Files:** `homelab_gui/homelab_gui.py`

### Inventory loading
- Added `_flatten_inventory_group(node, out)` — recursively walks an Ansible inventory
  group dict, collecting all `hosts:` entries into a flat `{hostname: vars}` dict.
- Added `_load_inventory_hosts()` — loads and caches the inventory on first call
  (module-level `_INVENTORY_HOSTS_CACHE`). Calls `_read_inventory_file()` for the
  path configured in `de-gui.yaml`.

### Host matching
`_get_ssh_command(node_path)` implements a three-stage match:
1. **Exact** — last path segment matches an inventory hostname (e.g. `pve-1` → `pve-1`).
2. **Prefix** — inventory hostname starts with the node name
   (e.g. `test-ubuntu-vm-1` → `test-ubuntu-vm-1-pve`, `test-ubuntu-vm-1-pve-2`).
   If exactly one prefix match, use it.
3. **Disambiguation** — when multiple prefix matches exist, cross-reference the
   `node_name` var in each host's inventory vars against the tree path segments
   (e.g. path contains `pve-1`, inventory host has `node_name: pve` which maps to pve-1).
   Falls back to first match if still ambiguous.

### SSH command construction
Uses inventory vars (when present):
- `ansible_host` — required; skipped if absent
- `ansible_user` — `user@host` form
- `ansible_ssh_common_args` — prepended after `ssh` (covers bastion/ProxyJump etc.)
- `ansible_port` — added as `-p PORT` if not 22
- `ansible_ssh_private_key_file` — added as `-i FILE`

Example output: `ssh -o ProxyJump=bastion ubuntu@10.0.10.156`

### Context menu injection
- Refactored the injection block in `open_context_menu` to build an `injected` list.
- "Open local shell" added first (if node has terragrunt.hcl).
- "SSH to host" added second (if inventory match found), `action_type: clipboard`
  so the command is copied to clipboard on click.
- Both appear under the "Shell" group header.

---

## 2. Identity params made configurable

**Files:** `config/de-gui.yaml`, `homelab_gui/homelab_gui.py`

Previously `provider`, `env`, `region` were hardcoded in `_SPECIAL_KEY_ORDER` and
`_SPECIAL_KEY_COLORS`. These are now driven by config.

### de-gui.yaml
Added `unit_params.identity_params` list (order matters — determines display order
and colour assignment):
```yaml
unit_params:
  identity_params:
    - provider
    - env
    - region
```

### homelab_gui.py
- Added `_IDENTITY_COLOR_PALETTE` (7 colours, wraps if list is longer).
- Added `_load_identity_params()` — reads `unit_params.identity_params` from
  `de-gui.yaml`, falls back to `[provider, env, region]` if absent.
- `_SPECIAL_KEY_ORDER` and `_SPECIAL_KEY_COLORS` are now built by calling
  `_load_identity_params()` at module load time.
- Adding, removing, or reordering identity params requires only a config edit.
