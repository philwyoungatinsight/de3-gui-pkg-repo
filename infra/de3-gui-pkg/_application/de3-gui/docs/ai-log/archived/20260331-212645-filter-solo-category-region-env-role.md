# Filter checkboxes: double-double-click solo for Category, Region, Env, Role

## Summary

Extended the double-double-click solo/invert pattern to all remaining infra filter
dropdowns: Category, Region, Env, and Role. Previously only Provider and Wave had
this behaviour.

---

## Changes — `homelab_gui/homelab_gui.py`

### New event handlers

| Handler | Filter dict/list | Logic |
|---|---|---|
| `solo_category(name)` | `category_filters` dict | Mirrors `solo_provider` |
| `solo_region(name)` | `region_filters` dict | Mirrors `solo_provider` |
| `solo_env(name)` | `env_filters` dict | Mirrors `solo_provider` |
| `solo_role(tag)` | `selected_roles` list | List-aware: soloed = `selected_roles == [tag]`; invert = all others + `"_none"` |

All dict-based solos follow the same pattern as `solo_wave` / `solo_provider`:
- First double-click: set only this key `True`, all others `False`.
- Second double-click (already soloed): invert — set only this key `False`, all others `True`.

`solo_role` is list-based because `selected_roles` is a list (empty = no filter = show all):
- First double-click: `selected_roles = [tag]`.
- Second double-click: `selected_roles = [all available roles except tag] + ["_none"]`.

### UI components updated

Each component wrapped in `rx.tooltip` and given `on_double_click`:
- `_category_toggle_item` → `on_double_click=AppState.solo_category(item["name"])`
- `_region_toggle_item` → `on_double_click=AppState.solo_region(item["name"])`
- `_env_toggle_item` → `on_double_click=AppState.solo_env(item["name"])`
- `_role_toggle_item` → `on_double_click=AppState.solo_role(item["tag"])`

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331-212645-filter-solo-category-region-env-role.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
