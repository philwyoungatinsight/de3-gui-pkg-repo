# 2026-04-02 — Investigation: provider template links in packages view

## Background

Investigated why clicking provider template pill links (e.g., `proxmox.tpl`) in the
Packages view did not appear to open the template files in the file viewer.

## Findings

**No bug found — the feature is correctly implemented.**

Investigation steps:
1. Confirmed `_scan_packages()` populates `provider_templates` correctly:
   - `default-pkg` → 6 templates (aws/azure/gcp/maas/null/proxmox `.tpl`)
   - `unifi-pkg` → 1 template (`unifi.tpl`)
2. Confirmed `_pkg_file_link_pill(lnk: PackageFileLink)` wires
   `on_click=AppState.open_abs_file_in_viewer(lnk.path)` correctly.
3. Read the compiled `.web/app/routes/_index.jsx` and confirmed the generated
   JavaScript correctly captures `lnk_rx_state_?.["path"]` per nested-foreach
   closure, dispatching it as `abs_path` to `open_abs_file_in_viewer`.
4. Confirmed `open_abs_file_in_viewer` reads the file, sets `hcl_content`,
   `hcl_file_path`, and switches `file_viewer_mode` to `"unit_file"` for `.tpl` files.
5. Confirmed `isTrue()` in generated JS returns `true` for non-empty path strings.

The nested `rx.foreach` pattern (outer `AppState.packages_data` → inner
`pkg.provider_templates`) compiles to valid React `Array.prototype.map.call`
with independent closures — no variable collision.

## Note on packages with templates

Only `default-pkg` and `unifi-pkg` (module-derived packages) have provider
templates. Config-derived packages (`default`, `buckets-pkg`) do not have
corresponding `_providers/<name>/` directories and show no "Provider Templates"
section.
