# 20260403-021754 — Fix Kube Shell cwd and set_env.sh absolute path

## Problem
Kube Shell failed:
```
fatal: not a git repository (or any of the parent directories): .git
bash: /set_env.sh: No such file or directory
```

Two root causes:
1. `cwd` was `Path.home()` — not inside any git repo, so `git rev-parse --show-toplevel` failed
2. Even if cwd were the infra repo, `set_env.sh` lives in the GUI repo, so the wrong path would be found

## Fix

### `_build_kube_shell_cmd` — use `_APP_DIR.parent / "set_env.sh"` (absolute path)
No longer uses `$(git rev-parse --show-toplevel)/set_env.sh`. Instead uses the
Python-computed absolute path `str(_APP_DIR.parent / "set_env.sh")` which is always
correct regardless of the terminal's cwd.

### `selected_node_browser_actions` — use `shell_dir` as cwd (was `Path.home()`)
`shell_dir` is the node's infra directory (computed earlier in the same var).

### `open_context_menu` — use `shell_dir` (or infra path) as cwd (was `Path.home()`)
Falls back to `_infra_path(_load_config()) / path` when `shell_dir` is empty
(i.e. node has no HCL file).
