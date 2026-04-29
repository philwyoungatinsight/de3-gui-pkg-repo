# 20260403-165411 — Package panel: expand/collapse + external repo management

## What changed

### Expand/collapse package cards
- `packages_expanded_names: list[str]` state var tracks which packages are expanded.
- `toggle_package_expanded(name: str)` handler adds/removes names from the list.
- `_pkg_card(pkg)` now returns `rx.cond(is_expanded, expanded_card, collapsed_row)` where
  `is_expanded = AppState.packages_expanded_names.contains(pkg.name)`.
- **Collapsed row**: compact single-line view — chevron (▶/▼), 📦 icon, name, providers (dim),
  source-repo badge (cyan, if ext); click anywhere on the row to expand.
- **Expanded card**: same as the previous full card plus a ▼ chevron and source-repo badge in the
  header; clicking the header row collapses it.
- Default state: all packages collapsed.

### External package repos
- `PackageInfo.source_repo: str` field — empty for built-in packages; holds the repo name for
  packages discovered from a cloned ext repo.
- `_EXT_PACKAGES_DIR = _STACK_DIR / "_ext_packages"` — clone target parent directory.
- `_load_ext_package_repos()` / `_save_ext_package_repos()` — persist `[{name, url}]` under
  `current.ext_package_repos` in `state/current.yaml`.
- `_scan_packages()` now also scans `_ext_packages/<name>/_modules/` for each registered ext repo,
  using the cloned repo's own `scripts/tg-scripts/`, `scripts/wave-scripts/`, and `_providers/`
  directories for scripts and templates (not `_STACK_DIR`'s). No secrets YAML for ext packages.
- `PackageInfo` construction passes `source_repo=p.get("source_repo", "")`.

### State vars added
| Var | Type | Purpose |
|-----|------|---------|
| `packages_expanded_names` | `list[str]` | Names of currently expanded packages |
| `ext_package_repos` | `list[dict]` | `[{name, url}]` loaded from state |
| `add_pkg_repo_dialog_open` | `bool` | Dialog visibility |
| `add_pkg_repo_url` | `str` | URL input |
| `add_pkg_repo_name` | `str` | Name input |
| `add_pkg_repo_status` | `str` | `""` / `"cloning…"` / `"error: …"` / `"done"` |

### Handlers added
- `toggle_package_expanded(name)` — add/remove from `packages_expanded_names`
- `open_add_pkg_repo_dialog()` / `close_add_pkg_repo_dialog()` — dialog open/close
- `set_add_pkg_repo_url(v)` / `set_add_pkg_repo_name(v)` — controlled inputs
- `clone_pkg_repo()` — `@rx.event(background=True)`: validates inputs, runs
  `git clone --depth=1 <url> _ext_packages/<name>/`, saves to state, calls `_init_modules_cache()`,
  updates `self.packages_data`
- `remove_pkg_repo(name)` — deletes clone dir via `shutil.rmtree`, saves updated repos list,
  rescans packages

### `on_load` change
`self.ext_package_repos = _load_ext_package_repos()` added after `self.packages_data = _PACKAGES_CACHE`.

### UI additions
- `_add_pkg_repo_dialog()` — Radix dialog with Name + URL inputs, Clone button, status message
- `_ext_repo_chip(repo)` — inline chip per ext repo with ✕ remove button and tooltip
- `packages_view()` now wraps content in `rx.fragment(_add_pkg_repo_dialog(), rx.scroll_area(...))`:
  - Header row: "PACKAGES" label + "+ Repo" button
  - Ext repos row (shown only when repos exist): "Ext repos: chip1 chip2…"
  - Package list via `rx.foreach(AppState.packages_data, _pkg_card)`
