# Add Ansible-based GUI test framework

## Changes

### New: `tests/` directory

Full Ansible test suite added under `scripts/install-de-gui/tests/`:

- `Makefile` / `run` — entry points
- `ansible.cfg`, `inventory/hosts.yml` — localhost Ansible config
- `playbooks/unit-tests.yml`, `integration-tests.yml`, `performance-tests.yml`
- `unit-tests/test-tree-open-node.yml`, `unit-tests/test-api-endpoints.yml`
- `gui-states/tree-default.yml`, `gui-states/tree-proxmox-pve1-selected.yml`
- `roles/gui-test/` — reusable role with `main.yml`, `assert.yml`, `screenshot.yml`

### New: test API endpoints in `homelab_gui/homelab_gui.py`

- `POST /api/test/set-state` — writes `.test_state.yml` for `on_load` to consume
- `POST /api/test/clear-state` — removes `.test_state.yml`
- `_apply_test_state()` helper called at end of `on_load`; reads and deletes the file,
  applying `viz_framework`, `left_view`, `tree_mode`, `selected_node`,
  `active_provider_tab`, and provider visibility; auto-expands ancestors

### Modified: `run` (`--test`)

Updated `_test()` to invoke `tests/run --unit` when `ansible-playbook` is available,
falling back to browser smoke test when not.

### Modified: `.gitignore`

Added `.test_state.yml`.

## GUI state YAML format

```yaml
gui_state:
  viz_framework: reflex
  left_view: tree
  tree_mode: separated
  selected_node: "cat-hmc/proxmox/pwy-homelab/pve-nodes/pve-1"
  active_provider_tab: ""
  providers:
    - provider-name: proxmox
      show: true
```

## Debugging notes

- System Ansible 2.10 is incompatible with pip Jinja2 3.x (`environmentfilter` removed).
  Fix: `pip install ansible-core>=2.14`.
- `selectattr('id', 'equalto', ...)` fails on edge elements (no `id` key).
  Fix: replaced with `ansible.builtin.shell` + Python heredoc.
- Python multiline in `cmd: >-` collapses to one line.
  Fix: use `ansible.builtin.shell` with `<< 'PYEOF'` heredoc.
