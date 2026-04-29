# 20260404-214133 — Clear YAML breadcrumb when a new file is loaded

## Problem

The YAML breadcrumb bar (the third bar in the file viewer, below the filename bar)
shows the YAML key path at the currently selected/scrolled position. It is set by
JavaScript on text selection or search-navigation, and intentionally does NOT clear
on empty selection (to avoid flicker when search-mark DOM mutations fire
`selectionchange`).

As a result, when clicking a node in the folder tree (loading a different file),
the breadcrumb retained the YAML path from the previous file — showing something
like `terragrunt_lab_stack.waves` even when viewing a completely different file.

## What the breadcrumb shows

The breadcrumb is driven by `data-yamlPath` attributes set on each `<span>` line
in the `#file-viewer-pre` element. It shows the **YAML key path** of the line the
user's cursor/selection is on, e.g. `terragrunt_lab_stack.providers.proxmox.config_params`.
It is only visible in `config_data` mode (hidden via `display: none` otherwise).

It is NOT a file path — that is the second bar (`hcl_file_path`).

## Fix

Added `_CLEAR_CRUMB_JS` module-level constant:
```python
_CLEAR_CRUMB_JS = "var _c=document.getElementById('yaml-breadcrumb');if(_c)_c.textContent='';"
```

Prepended to the JS string at all file-loading search call sites:

- `_search_reapply_script()` — covers `click_modules_node`, `navigate_to_module`,
  `open_wave_definition`, `show_inventory`, and the no-query path
- `select_node` config_data and unit_file branches
- `post_mode_switch_search` config_data branch
- `click_node` config_data and unit_file branches
- `navigate_to_source`

Search navigation calls (prev/next/keydown) are intentionally NOT touched —
those update the breadcrumb via `window._yamlCrumbUpdateFromMark`, which is
the desired behaviour.
