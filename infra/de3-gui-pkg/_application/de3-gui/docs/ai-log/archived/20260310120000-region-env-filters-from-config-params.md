# Region and Env Filters: Config-Params Source of Truth

## Problem

Region and Env filters were derived from folder depth:
- depth 2 → region (`parts[2]`)
- depth 3 → env (`parts[3]`)

This broke for `cat-hmc` where `parts[3]` is `pve-nodes`, `machines`, `device` etc. —
structural path segments, not environments. The Envs dropdown was polluted with
`pve-nodes`, `mesh-central`, `network`, `port-profile` etc.

## Root Cause

The infra hierarchy is not uniform. `cat-1/gcp/us-central1/dev/...` has a real env
at depth 3, but `cat-hmc/proxmox/pwy-homelab/pve-nodes/...` does not. The actual
region and env values are defined in `config_params` inside `terragrunt_lab_stack.yaml`
(same data that drives unit_params).

## Fix

### `_build_path_param_maps()` (new module-level function)
Iterates every provider's `config_params` entries in `_STACK_CONFIG`.
For each prefix key, extracts `region` and `env` param values.
Applies inheritance: shorter prefixes first, more-specific prefixes override.
Returns `(path_to_region: dict[str,str], path_to_env: dict[str,str])` keyed by
full provider-inclusive infra path.

### `_PATH_TO_REGION_CACHE` / `_PATH_TO_ENV_CACHE` (new globals)
Module-level dicts populated at import time by `_init_path_param_maps()`.
Called after `_init_nodes_cache()` since it depends on `_ALL_NODES_CACHE`.
Also called from `update_inventory_and_dag` after infra rescan.

### `on_load` + `update_inventory_and_dag`
Both now initialize `region_filters` / `env_filters` from the cache values:
```python
self.region_filters = {v: True for v in set(_PATH_TO_REGION_CACHE.values())}
self.env_filters    = {v: True for v in set(_PATH_TO_ENV_CACHE.values())}
```
(Also fixed `update_inventory_and_dag` which previously never rebuilt `env_filters`.)

### `visible_nodes` and `merged_visible_nodes`
Filter logic replaced depth-based checks with cache lookups:
```python
region_val = _PATH_TO_REGION_CACHE.get(path, "")
if region_val and not self.region_filters.get(region_val, True):
    continue
```
For merged mode, reconstructs full provider-inclusive paths from `providers_str`
before looking up the cache.

### `regions_with_visibility` / `envs_with_visibility`
Now iterate `sorted(set(_PATH_TO_REGION_CACHE.values()))` instead of scanning
`all_nodes` by depth.

### `has_stack_config` (new bool computed var)
`True` when `_STACK_CONFIG` is populated. Used to hide the Regions and Envs
dropdown buttons when no stack config is available (would show nothing anyway).

## Result (real infra)
- Regions: `eastus`, `pwy-homelab`, `us-central1`, `us-east-1`
- Envs: `dev`
- `pve-nodes`, `machines`, `device` etc. no longer appear as fake environments
