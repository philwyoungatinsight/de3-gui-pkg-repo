# Packages panel: full metadata display

## Summary

Expanded the Packages panel to show all package components as documented in
`README.package-system.md`: provider templates, TG script sub-dirs with READMEs,
wave test playbooks, and the secrets YAML link.

---

## Changes — `homelab_gui/homelab_gui.py`

### New `PackageFileLink` class
`rx.Base` with `label: str` and `path: str` fields. Used for all new link lists
in `PackageInfo`. `path=""` means non-clickable (display only).

### `PackageInfo` — new fields
| Field | Type | Content |
|---|---|---|
| `secrets_yaml_path` | `str` | `terragrunt_lab_stack[_<pkg>]_secrets.sops.yaml` abs path |
| `provider_templates` | `list[PackageFileLink]` | `_providers/<pkg>/*.tpl` files |
| `tg_scripts_sub_dirs` | `list[PackageFileLink]` | Provider sub-dirs inside `tg-scripts/<pkg>/`; path = sub-dir `README.md` |
| `wave_scripts_env_path` | `str` | `wave-scripts/<pkg>/pkg_env.sh` |
| `wave_test_playbooks` | `list[PackageFileLink]` | `run` scripts under `test-ansible-playbooks/`; label = `category/wave` |

### `_scan_packages()` — updated
- Computes `_secrets_base` (same git-root logic as `_find_stack_configs`) to locate secrets YAMLs.
- Iterates tg-scripts package dir for sub-directories; attaches their `README.md` paths.
- Iterates wave-scripts package dir for `pkg_env.sh` and recursively for `test-ansible-playbooks/*/run` scripts.
- Globs `_providers/<pkg>/*.tpl` for provider template files.
- `_entry()` dict and `PackageInfo(...)` constructor updated for all new fields.

### New `_pkg_file_link_pill(lnk: PackageFileLink)` component
Renders a clickable outline button when `lnk.path` is set, or a styled non-clickable
text pill otherwise.

### New `_pkg_section_label(text)` helper
One-liner for section headings inside cards.

### `_pkg_card()` — redesigned
Card now has six sections (conditionally shown):
1. **Header**: name | config YAML | secrets (orange ghost button)
2. **Providers**: (unchanged)
3. **Provider Templates**: row of `.tpl` file pills
4. **Modules**: (unchanged, existing table)
5. **TG Scripts**: Files row (pkg_env.sh, README.md) + Dirs row (provider sub-dirs)
6. **Wave Scripts**: Files row (pkg_env.sh, README.md) + Tests row (test playbook run scripts)

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331205012-packages-panel-full-metadata.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
