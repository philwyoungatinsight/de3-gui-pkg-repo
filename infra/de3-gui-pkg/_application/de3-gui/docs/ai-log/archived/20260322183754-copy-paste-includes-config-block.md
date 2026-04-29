# Copy/Paste: Include Stack Config Block

## Summary
Extended unit copy/paste so that the exact `config_params` block from the stack YAML
is also copied and written under the new path on paste.

## Changes

### New state vars
- `clipboard_config_block: dict` — exact config_params dict for the copied unit (empty if none)
- `clipboard_config_provider: str` — which provider key the block lives under

### `copy_unit` update
- After reading the HCL file, searches all providers in `_STACK_CONFIG` for an exact-match
  `config_params` entry keyed by the unit's path
- Stores the block and provider name; both remain empty if no exact-match entry exists
  (inherited ancestor entries are not included — only the unit's own block)

### `confirm_paste` update
- After writing the HCL file, if `clipboard_config_block` is non-empty:
  - Loads the stack YAML via `_find_stack_config()`
  - Inserts the block under the new node path (`target_path/unit_name`)
  - Writes the YAML back and reloads `_STACK_CONFIG` via `_load_stack_config()`
- Success message now says "Pasted: ... + config block" when a config block was written

## Files Modified
- `homelab_gui/homelab_gui.py`
