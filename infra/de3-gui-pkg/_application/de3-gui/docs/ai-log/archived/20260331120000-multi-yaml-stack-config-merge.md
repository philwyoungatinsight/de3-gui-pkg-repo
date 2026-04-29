# Multi-YAML Stack Config Merge

## Summary
Fixed unit params not appearing when clicking nodes introduced by the package system.
Also added README for `scripts/lib/` in `pwy-home-lab`.

---

## Root Cause

The package system split stack config across multiple YAML files:
- `terragrunt_lab_stack.yaml` — maas/proxmox/null/unifi providers
- `terragrunt_lab_stack_demo-cloud-buckets.yaml` — aws/azure/gcp providers

`_load_stack_config()` only loaded the first file (alphabetically), so all nodes from
`cat-1/gcp/…`, `cat-2/gcp/…`, `cat-3/aws/…`, `cat-hmc/aws/…`, etc. returned empty
params when clicked.

---

## Changes — homelab_gui/homelab_gui.py

### `_find_stack_configs()` (new) / `_find_stack_config()` (updated)
- Added `_find_stack_configs() -> list[Path]` that returns ALL non-secrets
  `terragrunt_lab_stack*.yaml` files sorted alphabetically.
- `_find_stack_config()` now delegates to `_find_stack_configs()[0]` for callers
  that still need a single primary path.

### `_load_stack_config()` — merge all files
- Loads every file returned by `_find_stack_configs()`.
- Detects the top-level key in each file (`terragrunt_lab_stack*` prefix).
- Deep-merges all `providers` dicts into the primary file's config:
  - `config_params` entries from secondary files are added to the merged dict
  - Non-`config_params` provider keys (auth, project, etc.) from secondary files
    are added only if not already present in the primary file
- Logs the number of files loaded and the merged provider list.

### `_get_watched_mtimes()` — watch all config files
- Now iterates `_find_stack_configs()` instead of just the single primary path,
  so the file watcher picks up changes to any package YAML file.

### `config_file_watcher` — detect changes in any config file
- Changed `yaml_path` (single string) to `yaml_paths` (set of strings) so that
  a change to any package YAML file triggers a config reload.

---

## Changes — pwy-home-lab

### `scripts/lib/README.md` (new)
Documents both lib files:
- `lab_stack_env.sh` — exported variables and sourcing instructions
- `merge-stack-config.py` — modes, deep-merge semantics, why it exists

---

## Verification

After the fix, `_STACK_CONFIG` providers = `['maas', 'null', 'proxmox', 'unifi', 'aws', 'azure', 'gcp']`.
Params confirmed working for all three node types tested:
- `cat-hmc/maas/pwy-homelab/machines/ms01-01` — maas params ✓
- `cat-1/gcp/us-central1/dev/test-bucket` — gcp params incl. `_package` ✓
- `cat-3/aws/us-east-1/dev/test-bucket` — aws params incl. `_package` ✓

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331120000-multi-yaml-stack-config-merge.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
- `~/git/pwy-home-lab/deploy/tasks/phase-0/terragrunt/lab_stack/scripts/lib/README.md` (new)
