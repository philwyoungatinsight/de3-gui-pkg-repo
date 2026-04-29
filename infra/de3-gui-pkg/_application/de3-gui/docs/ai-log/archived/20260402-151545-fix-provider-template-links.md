# 2026-04-02 — Fix: provider template links in Packages view

## Problem

Clicking provider template pills (e.g., `proxmox.tpl`) in the Packages view did
nothing. The file viewer did not open the template file.

## Root Cause

`PackageInfo.provider_templates` was typed as `list[PackageFileLink]` where
`PackageFileLink(rx.Base)` has `label: str` and `path: str` fields.

In the rendered card, `provider_templates` was iterated via an inner
`rx.foreach` nested inside the outer `rx.foreach(AppState.packages_data, ...)`.
The `on_click` handler used `lnk.path` (a nested `rx.Base` field access on the
inner foreach item) as an event argument.

When the inner iterable is a **field of an outer foreach item** (not a top-level
AppState var), Reflex 0.8.27 does not correctly pass `lnk.path` as an event arg
— even though the generated JSX looked syntactically correct. The click dispatched
but `abs_path` arrived as an empty string, so the file viewer showed nothing.

## Fix

Changed `provider_templates` from `list[PackageFileLink]` to `list[str]`
(absolute paths only). The filename label is derived at render time via
`path.split("/")[-1]` (Reflex StringVar operation that compiles to
`path.split("/")?.at?.(-1)`).

Added a new dedicated component function `_pkg_template_pill(path: str)` that
receives the path string directly as the foreach item var (no nested field
access), and passes it straight to `open_abs_file_in_viewer(path)`.

Changed `_pkg_card` to call `_pkg_template_pill` instead of `_pkg_file_link_pill`
for the provider templates section.

## Files changed

- `homelab_gui/homelab_gui.py`:
  - `PackageInfo.provider_templates`: `list[PackageFileLink]` → `list[str]`
  - `_scan_packages()`: accumulate `str(tpl)` directly (no dict wrapping)
  - `PackageInfo(...)` constructor: pass `p["provider_templates"]` as-is
  - `_pkg_card`: `rx.foreach(pkg.provider_templates, _pkg_file_link_pill)` →
    `rx.foreach(pkg.provider_templates, _pkg_template_pill)`
  - Added `_pkg_template_pill(path: str)` component function

## Note

`_pkg_file_link_pill` is still used for `tg_scripts_sub_dirs` and
`wave_test_playbooks` — those are top-level `AppState` vars iterated in their own
`rx.foreach`, so the nested field access works there. Only `provider_templates`
(inner field of outer foreach item) required this change.
