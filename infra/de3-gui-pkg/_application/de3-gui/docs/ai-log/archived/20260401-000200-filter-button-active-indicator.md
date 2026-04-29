# ai-log: Filter button active indicator

**Date:** 2026-04-01  
**Branch:** feat/gui

## What changed

Filter dropdown buttons in the infra tree controls bar now turn orange when
a filter is active (i.e. one or more items hidden).

### New computed vars
- `category_filter_active: bool` — any `category_filters` value is False
- `provider_filter_active: bool` — any `provider_filters` value is False
- `region_filter_active: bool` — any `region_filters` value is False
- `env_filter_active: bool` — any `env_filters` value is False
- (`role_filter_active` already existed)

### Updated buttons
Each filter button now uses `color_scheme=rx.cond(<active_var>, "orange", "gray")`:
- **Categories ▾** — orange when any category hidden
- **Providers ▾** — orange when any provider hidden
- **Regions ▾** — orange when any region hidden
- **Envs ▾** — orange when any env hidden
- **Roles ▾** / **Roles (N) ▾** — orange when any role selected; also now uses
  the existing `roles_button_label` dynamic var (showing count when filtered)

## Files modified
- `homelab_gui/homelab_gui.py`
