# Copy/Paste, Apply, Module Name, Taint, Param Edit, Inputs/Outputs

## Summary
Large feature session: fixed copy/paste for units without a config block, fixed apply
requiring manual "yes", removed VSCode theme, added "Show Full Module Name" with hover
card, removed unnecessary UnitParams filter buttons, added taint (single + recursive)
with confirmation, implemented inline param editing via the unit_params panel, fixed
wave ordering in the filter popup, and added Show Inputs / Show Outputs to the context
menu.

## Changes

### Copy/paste with no config block
- `copy_unit`: removed early return when config block is missing; sets clipboard message
  to `"Copied: {name} (no config block)"` instead
- `confirm_paste`: skips the YAML write when `clipboard_config_block` is empty; appends
  `" (no config block)"` to the paste confirmation message

### Apply unit fix
- `apply_unit` was running `terragrunt apply --non-interactive --` which still prompts.
  Fixed to `terragrunt apply -- -auto-approve` (passes `-auto-approve` to tofu/terraform
  via the `--` separator).

### VSCode theme removal
- Deleted `html.vscode { ... }` CSS block
- Removed VSCode button from `appearance_menu()`
- `_apply_color_mode_js`: removed "vscode" from `classList.remove(...)` call
- `file_editor_monaco_theme`: removed `"vscode": "vs-dark"` mapping
- `on_load`: remaps saved "vscode" → "dark" so old state files don't break

### Show Full Module Name (Appearance → Folder view)
- New state var: `show_full_module_name: bool = False`
- New checkbox in Appearance → Folder view section
- `_extract_module_path(hcl_content)`: regex extracts path after `}/` in terragrunt
  `source = "...modules_dir}/a/b/c"` attributes
- `_init_nodes_cache`: post-processes every `has_terragrunt` node, reads the HCL file,
  sets `node["module_source"]` (full path e.g. `aws/native/aws_s3_bucket`) and
  `node["module_source_short"]` (basename, e.g. `aws_s3_bucket`)
- Tree node shows: if `show_full_module_name` → `module_source`, else `module_source_short`
- Module pill wrapped in `rx.hover_card`:
  - Trigger: the pill label
  - Content: full `module_source` in monospace + "Open in Modules ↗" link
  - `navigate_to_module(module_path)`: switches explorer to "modules", expands tree to
    the module node, sets `selected_node_path`, reads the module HCL

### Remove Hide identity / Hide _provider buttons
- Removed "Hide identity" and "Hide _provider*" toggle buttons from UnitParams panel header

### Taint unit (single + recursive)
- State vars: `taint_dialog_open`, `taint_pending_path`, `taint_pending_mode`
- `begin_taint(path, mode)` → sets pending vars, opens dialog
- `cancel_taint()` → closes dialog
- `confirm_taint()` → reads `taint_pending_mode`, builds command, opens action terminal:
  - Single: `terragrunt state list | xargs -r -I{} terragrunt run -- taint {}`
  - Recursive: `terragrunt run --all -- state list | xargs -r -I{} terragrunt run -- taint {}`
  - Both prefixed with `source $(git rev-parse --show-toplevel)/set_env.sh &&`
- Context menu: "Taint unit…" and "Taint unit (recursive)…" for `has_tg` nodes
- Confirmation dialog with title/description that switches on mode

### Taint command fix
- Initial implementation used `terragrunt taint {}` which fails in terragrunt v0.99+:
  `ERROR unknown command: "taint". Use 'terragrunt run -- taint ...'`
- Fixed to `terragrunt run -- taint {}` for single; recursive unchanged in structure

### Inline param editing via unit_params panel
- `_get_unit_params_flat` `param` rows: fixed `source_path` from hardcoded `""` to the
  actual `source_path` loop variable, so the edit handler can locate the config entry
- State vars: `param_edit_dialog_open`, `param_edit_provider`, `param_edit_config_key`,
  `param_edit_param_key`, `param_edit_draft`, `param_edit_is_inherited`, `param_edit_error`
- `begin_edit_param(provider, config_key, param_key, current_value)`:
  - Determines if the param is inherited (`config_key != current_node_path`)
  - Sets `param_edit_is_inherited` accordingly
  - Opens the edit dialog
- `confirm_edit_param()`:
  - Inherited params → writes override at the exact current node path (not the ancestor)
  - Merged mode: reconstructs write key as `parts[0]/provider/parts[1:]`
  - YAML write: `yaml.safe_load` → `setdefault` chain → `yaml.dump`
  - Calls `_load_stack_config()` + `_init_path_param_maps()` to refresh in-memory caches
  - Then reloads unit params display
- `_param_kv_row`: clickable row with hover highlight + `on_click=AppState.begin_edit_param(...)`

### Wave ordering fix
- Filter popup was iterating `wave_visibility.keys()` from `_PATH_TO_WAVE_CACHE`
  (dict → no guaranteed order) which caused waves to appear in a different order than
  the config file
- `waves_with_visibility`: now iterates `_STACK_CONFIG["terragrunt_lab_stack"]["waves"]`
  list (declaration order) as the primary source, then appends any unseen names
- `waves_folder_rows`: changed from `sorted(wave_visibility.keys())` → plain iteration
  to preserve the insertion order from `waves_with_visibility`

### Show Inputs / Show Outputs context menu items
- `show_inputs(path)`: opens action terminal with
  `terragrunt render --all --json | jq '.inputs'`
- `show_outputs(path)`: opens action terminal with
  `terragrunt output -json | jq .`
- Both set `shell_cwd` to the unit directory and prefix with `set_env.sh` source
- Context menu: two new items after "Taint unit (recursive)…", gated to `has_tg` nodes

## Files Modified
- `homelab_gui/homelab_gui.py`
