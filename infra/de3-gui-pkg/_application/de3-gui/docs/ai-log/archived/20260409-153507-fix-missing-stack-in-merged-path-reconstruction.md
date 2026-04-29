# 2026-04-09 — Fix missing `_stack` in merged-mode path reconstruction (4 sites)

## Context

After the main `_stack` ancestor visibility fix, a comprehensive code audit found
four more functions that reconstructed provider-inclusive paths from merged paths
using the old formula `[parts[0], provider] + parts[1:]` instead of the correct
`[parts[0], "_stack", provider] + parts[1:]`.

## Bugs fixed

### 1. `_get_unit_params_flat` (line ~1829) — Unit Params panel

In merged mode, `lookup_path` was built without `_stack`. The config_params keys
in YAML are full paths (e.g. `pwy-home-lab-pkg/_stack/proxmox/pwy-homelab/...`),
so the lookup always failed and the Unit Params panel showed no params in merged mode.

### 2. `_get_browser_url_for_node` (line ~8435) — Browser URL resolution

Same pattern: merged mode lookup_path missing `_stack`. Browser URL params (e.g.
`_browser_url`) were never found for nodes in merged mode.

### 3. `select_node` — config_data mode full_path reconstruction (line ~6044)

When the right panel is in `config_data` mode and `tree_mode == "merged"`,
full_path was built as `<pkg>/<provider>/<rest>` instead of
`<pkg>/_stack/<provider>/<rest>`. Config data file lookup always failed.

### 4. `select_node` — config_data mode provider fallback (line ~6051)

In separated mode when provider was not yet set, it fell back to `_segs[1]`
(which is `"_stack"`) instead of `_segs[2]` (the actual provider name).

### 5. `open_param_edit_dialog` (line ~7406) — param-edit inherited detection

In merged mode, the `lookup` path used for determining if a param is inherited
vs. directly defined was missing `_stack`.

### 6. `confirm_edit_param` (line ~7443) — param-edit write key

In merged mode with inherited param, the `write_key` (used to create an
override at the exact node path) was missing `_stack`, so the write went to
the wrong config_params key.

## Pattern

All six instances followed the same wrong formula and were corrected to:

```python
# Old (wrong):
"/".join([parts[0], provider] + parts[1:])

# New (correct):
"/".join([parts[0], "_stack", provider] + parts[1:])
```

## Files changed
- `homelab_gui/homelab_gui.py`
