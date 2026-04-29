# UI/UX Improvements: Dark Mode, Filters, Waves, Shell Button

## Summary
Multiple UI/UX improvements across the homelab GUI in a single session.

## Changes

### Dark Mode Contrast
- Made dark mode "medium" (less extreme backgrounds): `--gui-panel-bg: #2d2d2d`, `--gui-content-bg: #222222`
- Fixed unit_params panel value text contrast in dark mode: added `--gui-param-value: #e2e8f0`
- Fixed override green colors for dark mode: `--gui-param-override-1/2/3` use lighter greens (`#4ade80`, `#86efac`, `#bbf7d0`)
- Fixed override block backgrounds: `--gui-param-block-bg-1/2/3` use dark green shades
- Fixed additional_tags green contrast in dark mode via same CSS vars

### Shell Button Fixes
- Fixed shell button opening wrong directory: `hcl_file_path` was overwritten when entering config_data viewer mode
- Added `unit_hcl_path` state var set before mode-branching in `select_node`
- Evolved to computing shell_dir directly via `_read_hcl_file(self.selected_node_path)` in `selected_node_browser_actions` computed var (same pattern as context menu)
- Made Shell button always visible even for nodes without unit files (falls back to infra dir path)

### File Viewer Cleanup
- Removed rel/abs buttons from file viewer header
- Terminal panel header now shows only relative path after `infra/` via `shell_cwd_display` computed var

### Appearance Menu Fix
- Fixed "Show merged" option doing nothing: `_panel_merge_btn()` was always rendered; wrapped in `rx.cond(AppState.panel_show_merged, ...)` so it only shows when merged mode is active

### Waves Filter
- Added Waves filter dropdown to Explorer toolbar (after Roles, before vertical bar)
- Reads wave values from `_wave` key in `config_params` in stack config yaml
- Extended `_build_path_param_maps()` from 2-tuple to 3-tuple returning `(path_to_region, path_to_env, path_to_wave)`
- Added `wave_filters: dict` state var + `has_waves`/`available_waves` computed vars
- Added `toggle_wave_filter`/`set_all_wave_filters` event handlers
- Added `_panel_waves()` UI component matching style of `_panel_envs()`

### Filter Ancestor Pruning Fix
- Fixed Explorer showing all categories/providers/regions even when filters hide their children
- Root cause: per-node filter checks passed for ancestor nodes (no assigned value)
- Fix: compute keep-sets using `_keep_paths_for` when any filter value is hidden; ancestors are included in keep-set only if they have visible descendants
- Applied to region, env, and wave filters in both `visible_nodes` (separated mode) and `merged_visible_nodes` (merged mode)

## Files Modified
- `homelab_gui/homelab_gui.py`
