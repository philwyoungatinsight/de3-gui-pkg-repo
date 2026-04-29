# 2026-04-09 — Engine refactor: update GUI to match new engine layout

## What changed

The engine repo (`pwy-home-lab`) was massively refactored. This session updated
the GUI to be compatible with the new structure.

## Summary of GUI changes

### `README.refactor.md` (new file)
Full written plan documenting old vs new engine layout, the 5 implementation
phases, what stays the same, and risk areas.

### Phase 1 — Simple path fixes

**`homelab_gui/homelab_gui.py`**
- `_STACK_DIR` default: `$HOME/git/pwy-home-lab/deploy/tasks/phase-0/terragrunt/lab_stack`
  → `$HOME/git/pwy-home-lab` (engine repo root is now flat, no nested subpath)

**`config/de-gui.yaml`**
- `ansible_inventory_path`:
  `../../../../k8s-recipes/config/tmp/dynamic/ansible/terragrunt_lab_stack/hosts.yml`
  → `ansible/terragrunt_lab_stack/hosts.yml` (engine now writes inventory here)
- `ansible_inventory_refresh.script`:
  `scripts/common/generate-ansible-inventory/run`
  → `framework/generate-ansible-inventory/run`
- `unit_params.identity_params`: `[provider, region, env]`
  → `[_provider, _region, _env]` (new engine prefixes all reserved params with `_`)
- Updated `stack_config_path` comment to reflect new auto-detection logic

### Phase 2 — Config discovery and loading rewrite

**`_find_stack_configs()`** — complete rewrite
- Old: searched for `terragrunt_lab_stack*.yaml` files under
  `{git_root}/deploy/config/files/platform-config/terragrunt/terragrunt_lab_stack/`
- New: returns `config/framework.yaml` (first) + all
  `infra/*/_config/*.yaml` files (excluding secrets), sorted alphabetically

**`_load_stack_config()`** — complete rewrite
- Old: merged `providers.<provider>.config_params` from `terragrunt_lab_stack*.yaml`
- New: adapter pattern that synthesises the same `providers.<provider>.config_params`
  structure from the new per-package format:
  1. Loads `config/framework.yaml` for global settings
  2. Loads `config/waves_ordering.yaml` for canonical wave order + `skip_on_clean`
  3. Loads each `infra/<pkg>/_config/<pkg>.yaml`; for each `config_params` entry:
     - Resolves `_provider` via ancestor-path inheritance (`_resolve_provider_inheritance()`)
     - Places entry under `providers[provider].config_params[path]`
     - Copies `_region`→`region` and `_env`→`env` for backward-compat
  4. Merges wave details from package `waves:` sections with ordering from
     `waves_ordering.yaml`
  5. Sets `_STACK_CONFIG_KEY = "lab_stack"` (was `"terragrunt_lab_stack_default"`)

**New helper: `_resolve_provider_inheritance(path, config_params)`**
- Walks ancestor paths (shortest→full) to find the most-specific `_provider` value
- Replicates root.hcl ancestor-merge semantics in Python

**`_find_config_file_for_node()`** — rewritten
- Searches package config files for the longest-prefix `config_params` key
- Was: searched `providers.<provider>.config_params` in stack config files

**`_find_source_config_file()`** — rewritten
- Same pattern: searches `<pkg>.config_params` in package configs

**`_find_sops_secrets_file()` / `_find_sops_secrets_files()`**
- Old: found a single `terragrunt_lab_stack_secrets.sops.yaml`
- New: `_find_sops_secrets_files()` returns all `infra/*/_config/*_secrets.sops.yaml`
- `_load_sops_secrets()` merges all per-package secrets; synthesises legacy
  `"terragrunt_lab_stack_secrets"` key so `_get_resolved_secret_params` /
  `_get_provider_level_secrets` still work

**`_get_watched_mtimes()`** — updated to watch `config/waves_ordering.yaml` and
all per-package secrets files

### Phase 3 — Package/module/script scanning

**`_scan_packages()`** — complete rewrite
- Old: scanned `_STACK_DIR/_modules/<provider>/<pkg>/<module>/`,
  `scripts/tg-scripts/<pkg>/`, `scripts/wave-scripts/<pkg>/`
- New: scans `infra/<pkg>/` for each package directory:
  - Config: `_config/<pkg>.yaml`; Secrets: `_config/<pkg>_secrets.sops.yaml`
  - Modules: `_modules/<module>/` (no provider subdir)
  - Provider templates: `_providers/*.tpl`
  - TG scripts: `_tg_scripts/<role>/`
  - Wave scripts: `_wave_scripts/test-ansible-playbooks/<cat>/<wave>/run`
  - `providers_str` derived from `providers:` key in package config YAML
- External repos now scan `infra/<pkg>/_modules/` inside ext repo (same layout)

**`_init_modules_cache()`** — complete rewrite
- Old: scanned `_STACK_DIR/_modules/<provider>/<pkg>/<module>/` (3 levels)
- New: scans `infra/<pkg>/_modules/<module>/` across all packages (2 levels)
- Creates synthetic package node (depth 0, path=`<pkg>`), then calls
  `_scan_dir_tree` at depth=1 for each module, producing paths `<pkg>/<module>`

**`_populate_module_tree_paths()`** — updated
- Depth check: 2→1 (modules now at depth 1 not 2)
- Package name extraction: `mtp_parts[1]`→`mtp_parts[0]` (no provider prefix)

**`_read_module_file()`** — updated
- Old: `_STACK_DIR / "_modules" / node_path`
- New: parses `<pkg>/<module>` from `node_path` →
  `_STACK_DIR / "infra" / pkg / "_modules" / mod_name`

**`open_source_link()`** — updated
- Old: tried `_STACK_DIR / "_modules" / sub_path`
- New: searches `infra/<pkg>/_modules/<sub_path>` across all packages

### Phase 4 — Wave write-back

**`toggle_wave_skip_on_clean()`** — updated target file
- Old: wrote to `terragrunt_lab_stack.yaml` under `waves:` key
- New: writes to `config/waves_ordering.yaml` under `waves_ordering:` key
- Handles both bare-string entries and dict entries; promotes str→dict to add
  `skip_on_clean`; demotes back to bare string when flag is cleared

**`_move_wave()`** — updated target file
- Same: writes reordering to `config/waves_ordering.yaml`

### Phase 5 — UI text and comments

- External packages dialog: updated description from
  `_modules/<provider>/<package>/` → `infra/<pkg>/_modules/<module>/`
- Modules-not-found UI text: `"_modules/ not found"` →
  `"No modules found in infra/*/ _modules/"`
- `de-gui.yaml` comment for `stack_config_path` updated to reflect new config
  auto-detection path

## Files changed
- `README.refactor.md` (new)
- `homelab_gui/homelab_gui.py`
- `config/de-gui.yaml`
