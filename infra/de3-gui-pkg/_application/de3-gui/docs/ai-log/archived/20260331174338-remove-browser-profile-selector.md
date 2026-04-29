# Remove defunct browser profile selector

## Summary

The global browser profile selector dropdown (far right of the bottom-right panel
header) was made redundant by the per-button browser-picker dropdowns added in the
previous session. Removed it and all supporting dead code.

Context menu URL items were also still using `dispatch_action` with the global profile,
so they were updated to use a browser-picker sub-menu before the selector was removed.

---

## Changes — `homelab_gui/homelab_gui.py`

### Context menu URL items: browser sub-menu
`_ctx_menu_row` now renders URL-type items as `rx.context_menu.sub` with a
`rx.context_menu.sub_trigger` (the action label) and a `rx.context_menu.sub_content`
listing all chrome profiles. Each profile item calls
`AppState.dispatch_url_with_profile(row["value"], p["id"])`.

### Removed dead code
- `_browser_profile_selector()` component function
- `_profile_menu_item()` component function
- `browser_profile_label` computed var
- `has_node_browser_actions` computed var
- `selected_node_url_actions` computed var (was already unused in the UI)
- `set_browser_profile` event handler
- `_browser_profile_selector()` call in `bottom_right_panel` header
- Thin separator between action buttons and profile selector

The `browser_profile` state var is retained (it persists to `state/current.yaml`) but
is no longer referenced by any UI dispatch path.

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331174338-remove-browser-profile-selector.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
