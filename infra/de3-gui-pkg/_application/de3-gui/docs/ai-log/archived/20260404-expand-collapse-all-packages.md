# 20260404 — Packages panel: expand/collapse all button

## What changed

Added a single toggle button to the packages panel header that expands or collapses
all package cards at once.

### New computed var

`packages_all_expanded: bool` — `True` when `packages_data` is non-empty and
`len(packages_expanded_names) >= len(packages_data)`.

### New event handlers

- `expand_all_packages()` — sets `packages_expanded_names` to all package names.
- `collapse_all_packages()` — clears `packages_expanded_names`.

### UI

In `packages_view()`, inserted a `rx.cond(AppState.packages_all_expanded, ...)` button
between the `rx.spacer()` and the `+ Repo` button in the top bar:

- When all expanded → shows "⊟ Collapse all" (ghost variant, calls `collapse_all_packages`)
- Otherwise → shows "⊞ Expand all" (ghost variant, calls `expand_all_packages`)
