# ai-log: Fix "Show full module name" toggle having no effect

**Date:** 2026-04-01  
**Branch:** feat/gui

## Problem

Toggling "Show full module name" in the Appearance menu showed no visual
difference in the module pill on tree nodes.

## Root cause

`_extract_module_path` uses a greedy regex `[^"]*\}/` that matches up to the
**last** `}/` in the HCL source string. Terragrunt unit HCL files use two
interpolations:

```hcl
source = "${include.root.locals.modules_dir}/aws/${include.root.locals.p_package}/aws_s3_bucket"
```

The greedy match stops at `p_package}/`, extracting only `aws_s3_bucket`. So
`module_source == module_source_short` (both are just the bare module name),
and toggling the full-name option had no visible effect.

## Fix

`module_tree_path` is already populated by `_populate_module_tree_paths()` with
the resolved full path (e.g. `aws/demo-cloud-buckets/aws_s3_bucket`).

Changed both the pill label and the hover-card text to use `module_tree_path`
instead of `module_source` when showing the full path:

- **Pill label**: `show_full_module_name=True` now shows `node["module_tree_path"]`
  (was `node["module_source"]`, same as the short name)
- **Hover card**: full path text now shows `node["module_tree_path"]`
  (was `node["module_source"]`, also just the bare name)

## Files modified
- `homelab_gui/homelab_gui.py`
