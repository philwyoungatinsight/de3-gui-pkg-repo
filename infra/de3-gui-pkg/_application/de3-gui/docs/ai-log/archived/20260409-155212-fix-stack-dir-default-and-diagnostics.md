# 2026-04-09 — Fix _STACK_DIR default in run/set_env.sh + startup diagnostics

## Problem

GUI showed nothing in the infra panel, waves were empty, packages showed only
"none". Root cause: `run` and `set_env.sh` still used the old engine's deep
path as the `_STACK_DIR` default, but the new engine lives directly in the
`pwy-home-lab` repo root.

| Script        | Old (wrong) default                                                      |
|---------------|--------------------------------------------------------------------------|
| `run`         | `$HOME/git/pwy-home-lab/deploy/tasks/phase-0/terragrunt/lab_stack`      |
| `set_env.sh`  | same                                                                     |

The Python code (`homelab_gui.py`) had already been updated to default to
`$HOME/git/pwy-home-lab` during the engine refactor session. The shell scripts
were not updated.

`_find_stack_configs()` looks for `$_STACK_DIR/config/framework.yaml`. With
the wrong `_STACK_DIR`, the file doesn't exist, `_STACK_CONFIG` stays empty,
no waves load. `_init_nodes_cache()` finds no packages under `_STACK_DIR/infra/`,
so the tree is empty.

## Fixes

### `run`
```bash
# Old:
export _STACK_DIR="${_STACK_DIR:-$HOME/git/pwy-home-lab/deploy/tasks/phase-0/terragrunt/lab_stack}"
# New:
export _STACK_DIR="${_STACK_DIR:-$HOME/git/pwy-home-lab}"
```

### `set_env.sh`
Same default updated to `$HOME/git/pwy-home-lab`.

### `CLAUDE.md`
`_STACK_DIR` table entry updated to reflect the new default.

### Startup diagnostic print (`homelab_gui.py`)
Added a print at the start of `_load_stack_config()` showing `_STACK_DIR`,
whether the directory exists, and whether `config/framework.yaml` was found.
Also prints a WARNING if no config files are found so future path issues are
immediately visible in the terminal.

## Files changed
- `run`
- `set_env.sh`
- `CLAUDE.md`
- `homelab_gui/homelab_gui.py`
