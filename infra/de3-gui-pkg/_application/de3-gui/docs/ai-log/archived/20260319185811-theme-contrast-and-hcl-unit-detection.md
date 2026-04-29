# Theme contrast fixes, non-standard HCL unit file support, and scan bug fix

## What changed

Three separate improvements in one session:

1. **Dark/VSCode theme contrast** — hard-coded light-mode colours replaced with
   CSS variables so tree text, selection highlights, and filter controls are
   readable in all three themes (light / dark / vscode).

2. **Non-standard unit HCL filenames** — infra scan and file-reader now
   recognise any `*.hcl` file as a unit file, not just `terragrunt.hcl`.

3. **Critical scan bug fix** — `_find_unit_hcl` was defined too late in the
   file (line ~4080) but called at module-load time (line ~1514).  A silenced
   `except Exception: pass` swallowed the resulting `NameError`, causing the
   infra scan to always return 0 nodes.

## Files modified

- `homelab_gui/homelab_gui.py`

---

## 1. Theme contrast

### Problem
Tree node text colours (`#111`, `#444`), expand/collapse arrows (`#888`),
selection backgrounds (`#e0e7ff` / `#f0f5ff`), provider pills (`#f3f4f6`),
and filter-panel hover states (`#f3f4f6`) were all hard-coded for light mode.
In dark/vscode themes the text was invisible or very low contrast.

### Fix
Added two new CSS variables to `_GUI_THEME_CSS` for all three themes:

| variable | light | dark | vscode |
|---|---|---|---|
| `--gui-tree-select-bg` | `#e0e7ff` | `#1e3a5c` | `#094771` |
| `--gui-tree-hover-bg` | `#f0f5ff` | `#1a2a3a` | `#2a2d2e` |

Replaced hard-coded colours in:
- `tree_node_component` — text, arrows, selection/hover bg
- `modules_node_component` — text, arrows, selection/hover bg
- `unit_templates_node_component` — text, arrows, selection/hover bg
- Provider pills background → `var(--gui-hover-soft)`
- Provider tab bar background → `var(--gui-panel-bg)`
- Filter toggle item hovers (4×) → `var(--gui-hover)`
- Param block base background → `var(--gui-content-bg)`

---

## 2. Non-standard HCL unit filenames

### Problem
Detection and reading of unit files was hard-coded to `terragrunt.hcl`.
Directories containing files like `unit.hcl` or similar were not recognised
as having a unit file.

### Fix
Added `_find_unit_hcl(dir_path) -> Path | None`:
- Checks for `terragrunt.hcl` first (backward-compatible)
- Falls back to the first non-hidden `*.hcl` file in the directory
- Hidden files (e.g. `.terraform.lock.hcl`) are excluded via `not f.name.startswith(".")`

Used in three places:
- `_scan_infra` — `has_terragrunt` flag
- `_read_hcl_file` — file content for the bottom-left viewer
- `_get_hcl_providers_for_merged` — provider detection in merged mode

---

## 3. Scan bug fix

### Problem
`_find_unit_hcl` was defined at line ~4080 but `_scan_infra` (called by
`_init_nodes_cache()` at module-load time, line ~1514) referenced it before
that definition was reached.  Python raised `NameError: name '_find_unit_hcl'
is not defined`, which was silently swallowed by `except Exception: pass` in
`_init_nodes_cache`.  Result: infra scan always returned 0 nodes, making the
entire tree empty on every startup.

Confirmed via: import showed "0 nodes"; standalone re-run after full import
showed 108 nodes (the `NameError` was gone because the full module was loaded).

### Fix
Moved `_find_unit_hcl` to just before `_scan_infra` (line ~1410) so it is
defined before any module-level call can reach it.  Removed the now-duplicate
definition that remained at the old location.

### Verification
```
python3 -c "import homelab_gui.homelab_gui"
# [homelab_gui] Infra scan done — 108 nodes   ✓
```
