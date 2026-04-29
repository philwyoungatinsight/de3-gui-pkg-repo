# Improve Browser Test Gates and Config/State Split

## Changes

### tests/browser_test.py

**Gate 1 (before checks):** Status panel now shows each pending check on its
own line so the user can see exactly what will be verified before clicking
Continue:
```
State applied — checks not yet run.

Will check:
  ○ node_visible:pve-1
  ○ node_selected:pve-1
  ○ right_panel_has:proxmox
```

**Gate 2 (after checks — renamed "Exit test"):** Button label changed from
"Click to close" to "✅ Exit test (N/N passed)" or "❌ Exit test (N FAILED / M)"
to make it clearly a final gate rather than an incidental dismiss.

### config/ and state/ restructuring

All user-editable configuration merged into `config/de-gui.yaml` (single file):
- `config:` — vm_ip, optional path overrides
- `supported:` — canvas views and providers the app supports
- `options:` — default provider visibility
- `testing:` — browser test settings (headless, user, observation mode, etc.)

`config/provider-actions.yaml` kept separate because its shell command templates
(`${{EDITOR:-vim}}`) conflict with Ansible's Jinja2 engine when the file is
loaded via `include_vars`.

Runtime state moved to `state/`:
- `state/current.yaml` — live UI state (written by `_save_current_config`)
- `state/dag.yaml` — DAG structure (populated at runtime)
- `state/.test_state.yml` — gitignored; written/consumed by test API

### homelab_gui/homelab_gui.py
- Added `STATE_DIR = _CONFIG_DIR / "state"` with `mkdir(exist_ok=True)`.
- `_TEST_STATE_FILE` moved from `_CONFIG_DIR / ".test_state.yml"` to
  `STATE_DIR / ".test_state.yml"`.
- `_load_config()` now reads a single `config/de-gui.yaml` instead of globbing
  all `*.yaml` files in `config/`.
- Added `_load_state()` to read `state/current.yaml`.
- `on_load` reads UI state from `_load_state()` instead of from `_load_config()`.
- `_save_current_config` writes to `state/current.yaml`.

### tests/roles/gui-test/tasks/main.yml
- `include_vars` updated to load `de-gui.yaml` instead of `testing.yaml`.

### .gitignore
- Updated `state/.test_state.yml` entry (was `.test_state.yml` at repo root).
