# Fix: Appearance menu checkbox double-fire

## Problem

Clicking a checkbox in the Appearance menu (e.g. "Age") immediately reverted to its
previous state. Root cause: a single click propagated to both `on_change` on the
`rx.checkbox` (sends new bool value → toggle) AND `on_click` on the parent `rx.hstack`
(flip) — toggling the state twice and ending back where it started.

## Fix

In `_appearance_menu_item`, removed `on_click` from the row `rx.hstack` and moved
`on_row_click` (the flip handler) to the label `rx.text` only.

- Clicking the **checkbox**: fires `on_change(new_bool)` once → correct
- Clicking the **label text**: fires `on_row_click()` (flip) once → correct
- No overlap, no double-firing

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331165313-appearance-menu-double-fire-fix.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
