# Extract GUI to Standalone Repo

## Summary
Restructured `pwy-home-lab-GUI` so its root contains only the GUI application
code (previously nested at `deploy/tasks/phase-0/terragrunt/lab_stack/scripts/install-de-gui/`).
All infrastructure code that was also in the repo has been removed. External
directories (infra, stack config) are now located via the `_STACK_DIR` env var.

## Changes

### Repo structure
- Moved all `install-de-gui/` content to repo root via `git mv`.
- Deleted `deploy/` directory and all k8s-recipes, Makefile, set_env.sh,
  .sops.yaml, .aider.chat.history.md from root.
- Root `Makefile`, `.gitignore`, `.claude/settings.local.json` replaced with
  the install-de-gui versions.

### `homelab_gui/homelab_gui.py`
- Added `import os`.
- Added `_STACK_DIR = Path(os.environ.get("_STACK_DIR", str(Path.home() / "git/pwy-home-lab/deploy/tasks/phase-0/terragrunt/lab_stack")))`.
- Updated `_infra_path()`: uses `_STACK_DIR / "infra"` by default; `config.infra_path` is now an optional override resolved relative to `_STACK_DIR` (was `_CONFIG_DIR`).
- Updated `_find_stack_config()`: runs `git rev-parse --show-toplevel` from `_STACK_DIR` (not `_CONFIG_DIR`), so it finds the git root of the infra repo (`pwy-home-lab`) where `terragrunt_lab_stack.yaml` lives.

### `config/config.yaml`
- Removed `infra_path` entry (now driven by `_STACK_DIR`).
- Kept `vm_ip`.
- Added comments documenting the optional `infra_path` and `stack_config_path` overrides.

### `run`
- Added `export _STACK_DIR="${_STACK_DIR:-$HOME/git/pwy-home-lab/deploy/tasks/phase-0/terragrunt/lab_stack}"` near the top so the Reflex process inherits it.

### `set_env.sh` (new, replaces old complex set_env.sh)
- Simple script: exports `_STACK_DIR` with the default path.
- Accepts an optional positional argument to override the path.
- Warns if `_STACK_DIR` does not exist.

## Path resolution (new)
| Variable | Path |
|---|---|
| `_CONFIG_DIR` | repo root (`homelab_gui/../`) |
| `CONFIG_DIR` | `<repo>/config/` |
| `_STACK_DIR` | `$HOME/git/pwy-home-lab/deploy/tasks/phase-0/terragrunt/lab_stack` (default) |
| infra | `$_STACK_DIR/infra` |
| stack config | `$(git -C $_STACK_DIR rev-parse --show-toplevel)/deploy/k8s-recipes/config/files/platform-config/terragrunt/terragrunt_lab_stack/terragrunt_lab_stack.yaml` |
