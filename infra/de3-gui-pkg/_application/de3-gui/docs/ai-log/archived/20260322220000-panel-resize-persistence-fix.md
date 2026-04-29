# Panel Resize Persistence Fix

## Summary
Fixed two bugs that caused panel positions to reset after dragging the resizers.
Also removed diagnostic print statements from `confirm_delete` that were left over
from the ghost-node debugging session.

## Root Causes

### Vertical (left/right) panel resizer
`on_resize_complete` was querying `getElementById('left-panel')` but the DOM id
is `left-column`. The element was never found, so the script returned the fallback
value `50`, and `save_panel_width` always saved 50% regardless of the actual drag
position.

### Horizontal (top/bottom) panel resizer
`on_hresize_complete` divided `top-left-panel.height` by `left-column.height`.
Since `left-column` is a child of `top-left-panel` set to `height: 100%`, the
ratio was always ~1 (100%), so `save_row_height` always saved ~100% instead of
the actual split.

### Race condition between drag JS and React re-renders
After mouseup, the trigger div click fires a Reflex event → server responds with
`rx.call_script` → client executes. Between mouseup and script execution, any
concurrent state update (terminal output, etc.) could cause React to re-render
and reset the DOM width back to the state value. Reading the DOM in the
`rx.call_script` would then read the wrong (reset) value.

## Fixes

### 1. Store drag position in window variables during mousemove
Both drag handlers now set:
- `window._leftPanelWidthPct` — left panel width as % of container (vertical drag)
- `window._topRowHeightPct` — top row height as % of total panel height (horizontal drag)

These are captured at the end of each mousemove, so they hold the precise final
position from the last frame of the drag.

### 2. Read from window variables instead of DOM in completion handlers
- `on_resize_complete` → reads `window._leftPanelWidthPct` (was: DOM query with wrong id)
- `on_hresize_complete` → reads `window._topRowHeightPct` (was: DOM ratio with wrong divisor)

Both fall back to 50/60 if the variable is null (page load before first drag).

### 3. Removed debug prints from `confirm_delete`
Five `print(...)` calls added during the ghost-node debugging session were removed.

## Files Modified
- `homelab_gui/homelab_gui.py`
