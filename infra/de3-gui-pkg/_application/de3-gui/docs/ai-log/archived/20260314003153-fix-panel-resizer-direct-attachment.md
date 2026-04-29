# Fix panel resizer mousedown via direct element attachment

## What changed

**`homelab_gui/homelab_gui.py`** — `_RESIZER_JS`:
- Added `window._resizerDbg` object (`clientX`, `targetId`, `startX`) to capture drag start info for diagnostics
- Extracted drag start logic into `_beginResize(e, sourceId)` helper
- Added `_bindResizerElement()` that attaches `mousedown` directly to `#panel-resizer` (guarded by `resizer._resizerBound` flag)
- Kept document-level delegation as fallback for cases where the DOM element is replaced post-bind; added `if (isResizing) return` guard to prevent double-firing
- Result: direct element attachment eliminates the `e.target !== resizer` check that was returning early in Playwright's synthetic event dispatch

**`tests/browser_test.py`** — `check_panel_resize_works`:
- Added `page.evaluate("JSON.stringify(window._resizerDbg || null)")` after `page.mouse.down()` to print diagnostic info showing `clientX`, `targetId`, and `startX`

## Why

The `panel_resize_works:200` test was failing with `initial=960px new=1720px expected≈1160px`. The `1720 = contW - 200` result indicated `startX ≈ 0`, meaning the document-level `mousedown` delegation's `e.target !== resizer` check was allowing the handler to run but `e.clientX` was 0 (or the target check was bypassed by a stale `isResizing` state). Direct attachment to the element removes the target-check uncertainty entirely.

After the fix, `_resizerDbg` reports `{"clientX":962,"targetId":"direct","startX":962}` and resize correctly produces `1160px`.
