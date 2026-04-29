# 2026-04-09 — Fix merged-mode path reconstruction for new engine layout

## Problem

After fixing infra scanning, the merged-mode view and file-viewer provider selector
were still broken because they reconstructed full provider-inclusive paths from merged
paths using the old formula — inserting provider at position 1, missing `_stack`.

## Root cause

Old merged→full reconstruction:
  `<pkg>/<env>/...`  +  `proxmox`  →  `<pkg>/proxmox/<env>/...`

New merged→full reconstruction:
  `<pkg>/<env>/...`  +  `proxmox`  →  `<pkg>/_stack/proxmox/<env>/...`

Five functions used the old formula:

1. **`_merged_full_paths()`** — reconstructs full paths for region/env/wave keep-set
   lookups in `merged_visible_nodes`. Region/env/wave filters were silently broken.

2. **`file_viewer_provider_options`** (computed var) — builds `full_path` for each
   provider option in the file viewer's Provider dropdown.

3. **`file_viewer_provider_full_path`** (computed var) — builds the path shown in
   the Provider dropdown button label.

4. **`_read_hcl_file_for_merged()`** — reconstructs the full path to read the HCL
   file for a merged-mode node. File content would never load in merged mode.

5. **`_get_hcl_providers_for_merged()`** — scanned `infra/<pkg>/` for provider dirs
   instead of `infra/<pkg>/_stack/`. All children of a package dir start with `_`,
   so the scan always returned an empty list → provider dropdown never populated.

## Fixes

All five functions updated to insert `_stack` between `parts[0]` (pkg) and provider:

- `_merged_full_paths`: `[parts[0], "_stack", p] + parts[1:]`
- `file_viewer_provider_options`: `[parts[0], "_stack", p] + parts[1:]`
- `file_viewer_provider_full_path`: `[parts[0], "_stack", self.file_viewer_provider] + parts[1:]`
- `_read_hcl_file_for_merged`: `[parts[0], "_stack", provider] + parts[1:]`
- `_get_hcl_providers_for_merged`: now scans `infra/<pkg>/_stack/` not `infra/<pkg>/`

Updated docstrings and comments to show new path examples.

## Files changed
- `homelab_gui/homelab_gui.py`
