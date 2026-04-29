# 2026-04-09 — Comprehensive engine compatibility fixes

## Context

Full cross-codebase audit of GUI against the new engine layout found 10 issues
(5 critical, 3 medium, 2 low) beyond the infra scanning and merged-path fixes
already applied earlier this session.

## Fixes

### 1. SOPS secrets format (CRITICAL)

**`_load_sops_secrets()`** — new engine has no `providers:` wrapper in secrets YAML.
New format: `<pkg>_secrets: { config_params: { <path>: {params} } }`.

Fixed: detect `config_params` at top level, resolve provider via
`_resolve_provider_inheritance`, merge into `merged_providers` structure the
same way public config is loaded. Legacy `providers:` fallback retained.

### 2. Config write-back to wrong file (CRITICAL)

`confirm_paste`, `confirm_recursive_paste`, delete-unit cleanup, and
`save_param_edit` all wrote config_params into `framework.yaml` using a synthetic
`lab_stack.providers.*` key that doesn't exist in the new engine. Written data was
never read back by `_load_stack_config`.

Fixed with three new helpers:
- `_pkg_config_yaml_for_path(node_path)` — returns `infra/<pkg>/_config/<pkg>.yaml`
- `_write_pkg_config_param(node_path, params)` — writes under `<pkg>.config_params[path]`
- `_delete_pkg_config_param(node_path)` — removes key from owning package YAML

All four write-back functions updated to use these helpers.

### 3. `open_source_link` missed `framework/_modules/` (CRITICAL)

Null-provider units use `source = ".../modules_dir}/null_resource__run-script"` which
resolves to `framework/_modules/null_resource__run-script`. Not in any `infra/<pkg>/`.

Fixed: now tries `framework/_modules/<sub_path>` first, then infra packages.

### 4. `_init_modules_cache` missed `framework/_modules/` (CRITICAL)

Same modules absent from the Modules panel entirely.

Fixed: after scanning `infra/<pkg>/_modules/`, also scans `framework/_modules/` and
adds entries under a synthetic `framework` package node.

Result: `framework/null_resource__run-script` and `framework/null_resource__ssh-script`
now visible in the Modules panel.

### 5. `_scan_packages` providers_str always empty (CRITICAL)

Code read `pkg_cfg.get("providers")` but no package config has a `providers:` key.

Fixed: derive `providers_str` from `_stack/` subdirectory names directly.

### 6. Cytoscape region filter used provider name as region (MEDIUM)

`cytoscape_elements` filtered by `parts[2]` (provider) as the region key,
instead of looking up the actual region from `_PATH_TO_REGION_CACHE`.

Fixed: `region_name = _PATH_TO_REGION_CACHE.get(data["id"], "")`.

### 7. TG scripts only one level deep (MEDIUM)

Structure is `_tg_scripts/<group>/<role>/` but code iterated only one level,
showing group dirs (`proxmox`) rather than individual roles.

Fixed: iterate two levels; emit group entry if it has a README, plus individual
`group/role` entries for each role subdir. Example: now shows `proxmox`,
`proxmox/configure`, `proxmox/install`, `proxmox/wait-for-api`.

### 8. Wave scripts missed `common/` subdirectory (MEDIUM)

Code only scanned `_wave_scripts/test-ansible-playbooks/`. The `unifi-pkg` and
`maas-pkg` packages have scripts under `_wave_scripts/common/`.

Fixed: rglob all `run` files under `_wave_scripts/` regardless of subdir.

### 9 & 10. `pkg_env.sh` (LOW)

`tg_scripts_env_path` and `wave_scripts_env_path` looked for `pkg_env.sh` which
no longer exists. Removed those lookups (they just returned `""` anyway).

## Files changed
- `homelab_gui/homelab_gui.py`
