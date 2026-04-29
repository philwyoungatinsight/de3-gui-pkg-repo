# Package System: Stack Config Path and Key Rename

## Summary
Updated the GUI to support the new `pwy-home-lab` package system layout, where the
stack YAML moved from `terragrunt_lab_stack/terragrunt_lab_stack.yaml` to
`terragrunt_lab_stack/default/terragrunt_lab_stack_default.yaml` and the top-level
YAML key was renamed from `terragrunt_lab_stack:` to `terragrunt_lab_stack_default:`.

## Background (pwy-home-lab changes)
- Stack YAML moved: `terragrunt_lab_stack/terragrunt_lab_stack.yaml` →
  `terragrunt_lab_stack/default/terragrunt_lab_stack_default.yaml`
- Top-level YAML key renamed: `terragrunt_lab_stack:` → `terragrunt_lab_stack_default:`
- `common_config.hcl` glob changed: `*/*.yaml` → `**/*.yaml` (picks up nested packages)
- Module source paths changed: `native/` → `default/` (purely cosmetic in GUI — basename
  unchanged; only affects "Show full module name" display)

## Changes

### `_find_stack_config()` — auto-detection updated for package system
- Now uses `rglob("terragrunt_lab_stack*.yaml")` under the `terragrunt_lab_stack/` directory,
  skipping any file with `"secrets"` in its name — works for any package name, not just `"default"`
- Falls back to flat legacy path `terragrunt_lab_stack/terragrunt_lab_stack.yaml` (backward compat)

### `_STACK_CONFIG_KEY` — dynamic key detection
- New module-level `_STACK_CONFIG_KEY: str` (default `"terragrunt_lab_stack_default"`)
- `_load_stack_config()` detects the actual top-level key after loading by scanning for any
  key starting with `terragrunt_lab_stack` (excluding `secrets`) — works for any package name
- All 15 call sites changed from the hardcoded string to `_STACK_CONFIG_KEY` (12 reads, 3 write-backs)
- `"terragrunt_lab_stack_secrets"` key (in secrets loading) intentionally left unchanged

### `config/de-gui.yaml` comment updated
- `stack_config_path` example updated to show new file path (`deploy/config/...` not `deploy/k8s-recipes/...`)

### `_find_stack_config()` base path updated
- Config files moved from `deploy/k8s-recipes/config/...` to `deploy/config/...`
- Updated hardcoded base path accordingly

### `@rx.background` → `@rx.event(background=True)`
- `rx.background` does not exist in Reflex 0.8.27; correct decorator is `rx.event(background=True)`
- Applied to `config_file_watcher` (formerly `_config_file_watcher`)

### `_config_file_watcher` renamed to `config_file_watcher`
- Background task handlers cannot have underscore-prefixed names in Reflex 0.8.27
  (`ValueError: Event handlers cannot be private`)
- Renamed method and its call site in `on_load`

## Files Modified
- `homelab_gui/homelab_gui.py`
- `config/de-gui.yaml`
- `docs/ai-log/20260326100000-package-system-stack-config-key-rename.md` (this file)
