# Infra filter checkboxes: double-double-click solo (mirrors wave checkboxes)

## Summary

Added `solo_provider` event handler and `on_double_click` binding to the infra
provider filter checkboxes, giving them the same double-double-click solo/invert
behaviour as the wave filter checkboxes.

---

## Changes — `homelab_gui/homelab_gui.py`

### New `solo_provider(self, provider: str)` handler
Mirrors `solo_wave` exactly:
- **First double-click**: check only this provider, uncheck all others.
- **Second double-click** (already soloed): invert — uncheck only this provider,
  check all others.

Detection of "already soloed": `provider_filters[provider] is True` AND all other
keys are `False`.

### `provider_toggle_item` — updated
- Wrapped the `rx.hstack` in `rx.tooltip` with the same help text pattern as wave
  checkboxes: `"Click to toggle · Double-double-click: show only this provider (again to invert)"`.
- Added `on_double_click=AppState.solo_provider(p["provider-name"])` to the hstack.

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331-210951-infra-filter-solo-provider.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
