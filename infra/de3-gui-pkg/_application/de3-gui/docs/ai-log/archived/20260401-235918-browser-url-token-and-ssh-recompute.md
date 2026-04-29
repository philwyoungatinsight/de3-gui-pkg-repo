# 2026-04-01 — `{ansible_host}` token in `_browser_url`; SSH button recompute fix

## Changes

### 1. `{ansible_host}` token support in `_browser_url` config param

**File:** `homelab_gui/homelab_gui.py` — `_get_browser_url_for_node()`

`_browser_url` values in stack config `config_params` now support Python `.format()` tokens
resolved from the Ansible inventory. Example:

```yaml
# stack config config_params
cat-hmc/proxmox/pwy-homelab/pve-nodes/pve-1/vms/utils/mesh-central:
  _browser_url: "https://{ansible_host}"
```

Resolution uses the same exact-then-prefix inventory lookup as `_get_ssh_command`.
Supported tokens: any inventory var (`ansible_host`, `ansible_port`, `proxmox_api_port`,
etc.). If a token is missing, the raw template string is returned unchanged.

**Why:** the hardcoded `_browser_url: https://10.0.10.155` for mesh-central was wrong
(inventory `ansible_host` is `10.0.10.156`). Using `{ansible_host}` keeps it in sync
with the live inventory.

### 2. SSH button now appears after inventory refresh (action panel)

**Root cause:** `selected_node_browser_actions` is a `@rx.var` that calls
`_load_inventory_hosts()`, which reads a module-level global cache (`_INVENTORY_HOSTS_CACHE`).
Reflex does not track module-level globals as dependencies. If the cache was empty when the
var was first computed (e.g., first-ever startup before the inventory file existed), Reflex
would never recompute it — so SSH buttons would remain absent even after the inventory loaded.

**Fix (3 parts):**

1. Added `_INVENTORY_REFRESH_COMPLETE: bool` flag set to `True` in `_run_inventory_refresh`'s
   `finally` block (and in all early-return paths) once the script has finished.

2. Added `inventory_refresh_counter: int = 0` to `AppState`. Accessing it inside
   `selected_node_browser_actions` registers it as a tracked Reflex dependency.

3. Added `signal_inventory_ready` (`@rx.event(background=True)`) — polls
   `_INVENTORY_REFRESH_COMPLETE` up to 120 s, then does `async with self: self.inventory_refresh_counter += 1`.
   This forces `selected_node_browser_actions` to recompute with the now-populated cache.
   Dispatched from `on_load` alongside the existing `config_file_watcher` event.

**Files changed:** `homelab_gui/homelab_gui.py`

## Stack config change required (user action)

To use `{ansible_host}` in `_browser_url`, update your stack YAML:

```yaml
# Before
cat-hmc/proxmox/pwy-homelab/pve-nodes/pve-1/vms/utils/mesh-central:
  _browser_url: "https://10.0.10.155"

# After
cat-hmc/proxmox/pwy-homelab/pve-nodes/pve-1/vms/utils/mesh-central:
  _browser_url: "https://{ansible_host}"
```
