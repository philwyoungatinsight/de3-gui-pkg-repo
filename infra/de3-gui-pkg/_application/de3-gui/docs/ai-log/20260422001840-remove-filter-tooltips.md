# 2026-04-22 — Remove filter item tooltips

## What changed
Removed `rx.tooltip()` wrappers from the five filter-item toggle functions in the infra-panel filter dropdowns (packages, providers, regions, envs, roles). Each function was returning `rx.tooltip(rx.hstack(...), content="Click to toggle…")` — now returns `rx.hstack(...)` directly.

## Why
Hovering over checkbox items in the filter dropdowns triggered Radix tooltip popups that made the UI feel clunky and slow. The tooltips added no essential information not already understood by users.

## Functions changed
- `provider_toggle_item` (line 12643)
- `_package_toggle_item` (line 13138)
- `_region_toggle_item` (line 13166)
- `_role_toggle_item` (line 13194)
- `_env_toggle_item` (line 13336)

## Not changed
Button-level `title=` attributes on the main dropdown trigger buttons ("Packages ▾", "Providers ▾", etc.) were left intact — those are not causing the sluggishness.
