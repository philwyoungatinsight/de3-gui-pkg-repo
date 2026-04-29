# Add Context Menu and Fix Test Shell Quoting

## Changes

### homelab_gui/homelab_gui.py
- Changed cross-process test-state marker file from `/tmp/.homelab-gui-test-applied`
  to `$HOME/.homelab-gui-test-applied` so different users on the same host do not
  collide.
- Added `_PROVIDER_ACTIONS_CACHE`, `_load_provider_actions()`, `_get_resolved_params()`,
  and `_get_node_actions()` to resolve context menu actions from `provider-actions.yaml`
  using merged stack config params for a given node path.
- Added `ctx_menu_path` and `ctx_menu_rows` state vars to `AppState`.
- Added `open_context_menu(path)` event handler that populates `ctx_menu_rows` from
  `_get_node_actions()`, inserting group labels and separators.
- Added `dispatch_action(action_type, value)` event handler that calls
  `rx.call_script` for `url` (window.open) and `clipboard` (navigator.clipboard.writeText)
  actions, and `click_node` for `expand_collapse`.
- Added `_ctx_menu_row` component using `rx.match` to render separator / group-label /
  item rows.
- Updated `tree_node_component` to wrap tree rows in `rx.context_menu.root` with
  `on_context_menu=AppState.open_context_menu(node["path"])` and
  `rx.foreach(AppState.ctx_menu_rows, _ctx_menu_row)` in the content.

### config/provider-actions.yaml (new)
Declarative action definitions keyed by group, action_type, and param templates.
Actions defined:
- `ssh_pve` — SSH to PVE host (proxmox/pve-node, clipboard)
- `ssh_vm` — SSH to VM (proxmox/vm, clipboard)
- `proxmox_ui` — Proxmox web UI (proxmox/pve-node, url)
- `maas_ui` — MaaS admin UI (maas/environment, url)
- `maas_ui_machine` — MaaS machine detail (maas/machine, url)
- `amt_ui` — AMT web console (maas/machine, url)
- `tg_apply`, `tg_show_inputs`, `tg_show_outputs`, `tg_destroy` — Terragrunt unit
  commands (requires_terragrunt, clipboard)
- `edit_hcl` — Open terragrunt.hcl in $EDITOR (requires_terragrunt, clipboard)
- `expand_collapse` — Toggle tree node expansion (expand_collapse)

### tests/browser_test.py
Added `_right_click_node`, `check_context_menu_visible`, `check_context_menu_url`,
`check_context_menu_clipboard` functions and registered them in `CHECK_MAP`.

### tests/roles/gui-test/tasks/browser_assert.yml
Fixed `_bt_check_args` set_fact — replaced broken `regex_replace` backreference approach
with Jinja2 for-loop using `quote` filter so check values containing spaces (e.g.
`context_menu_clipboard:ssh_pve:ssh root@10.4.10.227`) are passed as single arguments
to argparse:
```yaml
_bt_check_args: "{% for c in browser_checks %}--check {{ c | quote }} {% endfor %}"
```

### tests/gui-states/context-menu-pve1.yml (new)
GUI state fixture: proxmox tree with pve-1 selected.

### tests/unit-tests/test-context-menu.yml (new)
Browser test for context menu on pve-1:
- `context_menu_visible:ssh_pve`
- `context_menu_visible:proxmox_ui`
- `context_menu_url:proxmox_ui:https://10.4.10.227:8006`
- `context_menu_clipboard:ssh_pve:ssh root@10.4.10.227`

Note: `tg_apply` is not checked for pve-1 — it is a container directory with no
`terragrunt.hcl`. Unit group actions only appear for leaf nodes with a `terragrunt.hcl`.

### tests/playbooks/unit-tests.yml
Added `test-context-menu` task.

### tests/.gitignore
Changed `screenshots/*.png` to `screenshots/*` + `!screenshots/.gitkeep` to ignore
all generated screenshot files while tracking the directory via `.gitkeep`.

### tests/screenshots/.gitkeep (new)
Empty file to track the screenshots directory in git.

### run
Changed marker file cleanup from `/tmp/.homelab-gui-test-applied` to
`${HOME}/.homelab-gui-test-applied`.

## Test Results
All tests pass: `make test` green, including the new `test-context-menu` suite.
