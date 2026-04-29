# ai-log: Fix Reflex proxy objects written to stack YAML on copy/paste

**Date:** 2026-04-01  
**Branch:** feat/gui

## Problem

Copying a unit and pasting it produced a corrupted config block in the stack YAML.
List values (`additional_tags`, `boot_order`) were serialized as:

```yaml
additional_tags: !!python/object/apply:reflex.istate.proxy._unwrap_for_pickle
- - role_pxe_test
boot_order: !!python/object/apply:reflex.istate.proxy._unwrap_for_pickle
- - net0
  - virtio0
```

instead of plain YAML lists.

## Root cause

Config block values read from Reflex state vars (`self.clipboard_config_block`,
`item["config_block"]`) are wrapped in Reflex proxy objects. `dict(proxy_dict)`
does a shallow copy: scalars are unwrapped, but nested lists/dicts remain as
proxy objects. When PyYAML serialises these proxies it uses their `__reduce__`
method, producing the `!!python/object/apply:reflex.istate.proxy._unwrap_for_pickle`
tag instead of a plain list/dict.

## Fix

Added `_deep_plain(obj)` helper that recursively converts proxy-wrapped values
to plain Python by iterating via `dict(obj).items()` and `list(obj)`.  Applied
at both paste sites:

- Single paste (`confirm_paste`): `cfg_ref[new_node_path] = _deep_plain(self.clipboard_config_block)`
- Recursive paste (`confirm_recursive_paste`): `cfg_ref[new_node_path] = _deep_plain(item["config_block"])`

Also repaired the already-corrupted `pxe-test-vm-2` entry in
`terragrunt_lab_stack.yaml`.

## Files modified
- `homelab_gui/homelab_gui.py`
- `deploy/config/files/platform-config/terragrunt/terragrunt_lab_stack/terragrunt_lab_stack.yaml` (pwy-home-lab repo)
