# Wave Table Pre/Test Status, Host Icon, Tail Button, and Misc

## Summary
Multiple features added across the wave table, node tree, file viewer, and project tooling.

---

## Changes

### Node tree — physical host icon
- Added `is_host: bool` field to node schema in `_scan_infra`
- `_init_nodes_cache()` populates `is_host` using `ansible_inventory.modules_to_include`
  from the stack YAML — mirrors `generate_ansible_inventory.py`'s `unit_is_host` logic:
  1. Check `_is_host` override in exact-path `config_params` entry (true/false forces include/exclude)
  2. Otherwise: `True` if `module_source` contains any string from `modules_to_include`
- Added `_host_icon()` — 14×14 SVG rack-unit server icon (grey chassis, three drive bays, green LED)
- `tree_node_component`: outermost icon `rx.cond` checks `node["is_host"]` first; 📦/📁 fallback unchanged

### Wave table — Pre / Run / Test status columns
- `refresh_wave_log_statuses` now independently scans three log file patterns per wave:
  - `wave-<name>-(apply|destroy).log` → main `status` / `log_path` / timing
  - `wave-<name>-precheck.log` → `pre_status` / `pre_log_path`
  - `wave-<name>-test-playbook.log` → `test_status` / `test_log_path`
  Each type resolved from the newest dir that has that file (independent per type).
- "Status" column replaced by three columns: **Pre** | **Run** | **Test**
- Shared helper `_wave_status_icon(status_key, log_path_key, item, ok_title, fail_title)`
  renders ✓/✗/– with click-to-open-log, used in both list-view and folder-view rows
- All six new fields propagated through `waves_with_visibility`, `waves_folder_rows`, `_empty_ls`, `_empty`

### Wave table — column header tooltips
- All column headers now have `title=` tooltip text explaining their purpose

### Wave table — highlight recent wave
- New state vars: `wave_highlight_recent: bool = True`, `recent_wave_name: str = ""`
- `refresh_wave_log_statuses` sets `recent_wave_name` to the wave whose apply/destroy log
  mtime is newest and within 10 seconds of now (clears to `""` otherwise)
- `is_recent` bool propagated through `waves_with_visibility` and `waves_folder_rows`
- Row background: `--accent-3` when `is_recent`, transparent otherwise; hover uses `--accent-4`
- Appearance menu — new "Wave panel behaviour" section with "Highlight recent wave" toggle
- Saved/restored in `state/current.yaml`

### Wave table — on_load fix for waves tab
- When `object_viewer_mode == "waves"` is restored from saved state in `on_load`,
  `refresh_wave_log_statuses` is called immediately and the 3-second poll is started.
  Previously these only triggered when the user switched tabs, leaving the table blank on reload.

### Wave table — duration / age format
- Days component removed; hours accumulate past 24 (e.g. `51h-04m-05s`)
- Leading zero components replaced with non-breaking spaces (`\u00a0`) for HTML alignment
- Age now includes seconds (same format as duration)
- Format: `{h:>2}h-{m:02d}m-{s:02d}s` — max 11 chars; 7 chars for age (was same)

### Wave table — reorder buttons (up/down arrows)
- New "Order" column at far right of wave table
- ↑ / ↓ buttons per wave row; disabled at boundaries (`is_first` / `is_last`)
- `move_wave_up` / `move_wave_down` swap entries in the stack YAML and reload config
- `_btn_slot` 28px containers used for consistent spacing (matching Apply/Destroy gap)

### File viewer — Tail button
- "Tail" button added to file viewer menu bar (after Download)
- `tail_current_file()` handler: sets `shell_cwd = file directory`, `shell_initial_cmd = "tail -99f <path>"`
- Disabled when no file is loaded

### View selector — Nested Networks moved last
- "Nested Networks" (`cytoscape`) moved to last position in the view-mode dropdown
  (was between Folder and Tree)

### Wave names renamed
- `on_prem.validation.external.storage_systems` → `on_prem.externally_managed.storage_systems`
- `on_prem.validation.external.power_mgmt` → `on_prem.externally_managed.power_mgmt`
  (matches the existing `on_prem.externally_managed.vm_servers` naming pattern)

### Config — wave_logs_dir
- Added `wave_logs_dir: ".run-waves-logs"` to `config/de-gui.yaml`
- `refresh_wave_log_statuses` reads this value; falls back to `.run-waves-logs` if absent

### AGENTS.md → CLAUDE.md
- Renamed `AGENTS.md` to `CLAUDE.md`
- Added mandatory post-session checklist to the top of `CLAUDE.md`:
  ai-log → ai-log-summary → commit

## Files Modified
- `homelab_gui/homelab_gui.py`
- `config/de-gui.yaml`
- `deploy/config/files/platform-config/terragrunt/terragrunt_lab_stack/terragrunt_lab_stack.yaml`
- `AGENTS.md` → `CLAUDE.md` (rename)
- `docs/ai-log/20260330000000-wave-table-host-icon-tail-button-misc.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
