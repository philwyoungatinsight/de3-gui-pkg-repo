# GUI — Refactor Menu Update

**Date:** 2026-04-20  
**File:** `homelab_gui/homelab_gui.py`

## What changed

- Renamed context-menu group label "Edit" → "Refactor"
- Changed "Rename…" menu item to "Rename" (no ellipsis)
- Replaced single "Refactor (move / copy)…" + two "Remove unit…" items with three direct-action items: **Move**, **Copy**, **Delete**
- Added three new `dispatch_action` routes: `begin_refactor_move`, `begin_refactor_copy`, `begin_refactor_delete`
- `begin_refactor` now accepts an `operation` parameter (default `"move"`) and pre-sets `refactor_operation` on open
- `run_refactor_preview` short-circuits for `op == "delete"` with a clear message
- `run_refactor_execute` delegates to `confirm_delete` (existing recursive-delete backend) when `op == "delete"`
- Updated `float_refactor_panel` title to "Refactor (units and config recursively)"
- Added **Delete** button (red) to the operation toggle in `_refactor_panel`
- Destination input is hidden via `rx.cond` when Delete is selected
- Execute button disabled logic updated: enabled without destination when Delete is selected
- Added `title=` tooltips to all controls in `_refactor_panel`
