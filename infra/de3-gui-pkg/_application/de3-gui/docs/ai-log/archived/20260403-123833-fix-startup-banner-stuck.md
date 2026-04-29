# 20260403-123833 — Fix startup banner stuck on "Refreshing inventory…"

## Problem

`startup_status_banner` showed "Refreshing inventory…" indefinitely after a page reload
(or any load that hit the double-fire guard in `on_load`).

Root cause: the early-return path in `on_load` (double-fire guard, ~line 4282) only
returned `AppState.install_resizer`. It never started `AppState.signal_inventory_ready`,
so `inventory_refresh_counter` stayed at `0` and `app_status_message` never cleared.

## Fix

Changed the early-return to return both tasks:

```python
# before
return AppState.install_resizer

# after
return [AppState.install_resizer, AppState.signal_inventory_ready]
```

`signal_inventory_ready` polls `_INVENTORY_REFRESH_COMPLETE`. On a page reload this global
is already `True` (set during the first load), so the background task exits immediately and
bumps `inventory_refresh_counter` to 1, clearing the banner.
