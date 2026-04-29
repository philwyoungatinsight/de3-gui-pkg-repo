# Wave Run/Destroy Buttons, Popup Drag, Hover Cards, Wave Numbers

## Summary
Fixed show_inputs/show_outputs dispatch routing, added per-wave run/destroy buttons in a
draggable floating wave popup, added hover card tooltips on wave names, added a wave number
column in the popup, and added "Show wave numbers" in Appearance → Folder View to append
`(N)` after node names in the infra tree.

## Changes

### Fix show_inputs / show_outputs dispatch routing
- `dispatch_action`: added two missing `elif` branches for `"show_inputs"` and `"show_outputs"`
  so context menu actions actually call those handlers and open the terminal

### Wave run/destroy buttons in floating popup (Option A)
- New state vars: `wave_run_dialog_open`, `wave_run_pending_name`, `wave_run_pending_mode`,
  `wave_popup_open`, `wave_popup_left`, `wave_popup_top`
- `begin_wave_run(name, mode)`: apply → opens terminal immediately; destroy → opens
  confirmation dialog first
- `_open_wave_terminal(name, mode)`: builds command from `_STACK_DIR / "run"` script:
  - apply: `run -a -w {name} --skip-test`
  - destroy: `run --clean -w {name}`
- Confirmation dialog (`wave_run_dialog_open`) warns before destroy
- Run/destroy buttons use `size="3"` (Radix) with explicit gaps:
  `rx.box(width="72px")` before ▶, `rx.box(width="36px")` between ▶ and ✕

### Draggable floating wave popup
- Replaced dropdown/popover with a `position="fixed"` panel (`id="wave-popup-panel"`)
- `_WAVE_POPUP_INIT_JS` constant: attaches drag listeners once (guarded by
  `window._waveDragListenersAttached`), right-aligns 340px panel to `left-column` right edge
- JS manipulates panel position directly during drag (no server roundtrips)
- On mouseup: hidden `rx.el.div(id="wave-popup-drag-trigger")` fires
  `on_wave_popup_drag_end` which persists `window._wavePanelX/Y` via two scalar callbacks
- Public handler names (no underscore): `save_wave_popup_x`, `save_wave_popup_y`,
  `on_wave_popup_drag_end`, `toggle_wave_popup`, `close_wave_popup`

### Wave hover card tooltips
- `_wave_hover_card(item, trigger)`: `rx.hover_card.root/trigger/content` showing wave
  config attributes: name, description, pre_ansible_playbook, test_ansible_playbook,
  test_action, update_inventory (each shown only when non-empty)
- `waves_with_visibility` enriched to carry all wave config attributes + `wave_num`
- `waves_folder_rows` passes through `wave_attrs` dict with all fields

### Wave number column in popup
- `waves_with_visibility`: iterates `cfg_waves` list with `enumerate(..., 1)` to assign
  `"wave_num"` in config-file declaration order
- `_wave_toggle_item`: leftmost `rx.text(item["wave_num"], ...)` in monospace 11px dim text,
  22px wide right-aligned; non-config waves get `wave_num = ""`

### "Show wave numbers" in Appearance → Folder View
- New state var: `show_wave_numbers: bool = False`
- `_init_path_param_maps`: stamps `node["wave_num_str"]` on every node after building
  `_PATH_TO_WAVE_CACHE`; `wave_name_to_num` maps wave name → 1-based index string
- Node creation sites (`_scan_infra`, `_scan_dir_tree`): added `"wave_num_str": ""` default
- `tree_node_component`: renders `rx.text("(", node["wave_num_str"], ")")` in 11px grey
  monospace after node name when `show_wave_numbers` is True and `wave_num_str != ""`
- Persisted in `_save_current_config` / `on_load`
- Checkbox in Appearance → Folder View section (below "Show full module name")

## Bugs Fixed

### EventFnArgMismatchError (x2) — Reflex underscore/scalar callback rules
1. Tried returning JS object `{x, y}` from `rx.call_script` with a dict callback.
   Reflex can only pass a single scalar through a callback. Fixed by two separate calls.
2. Methods `_set_wave_popup_x/_y` (underscore prefix) not registered as Reflex events.
   Callback lookup returns `None` → crash. Fixed by renaming to `save_wave_popup_x/y`.
   AGENTS.md updated with permanent rules to prevent recurrence.

### TypeError on Reflex var string concatenation
- `"(" + node["wave_num_str"] + ")"` fails at compile time: `node["wave_num_str"]` is a
  Reflex `ObjectItemOperation`, not a Python str.
- Fixed: `rx.text("(", node["wave_num_str"], ")")` — pass as separate children.
  AGENTS.md updated with this rule too.

## Files Modified
- `homelab_gui/homelab_gui.py`
- `AGENTS.md`
