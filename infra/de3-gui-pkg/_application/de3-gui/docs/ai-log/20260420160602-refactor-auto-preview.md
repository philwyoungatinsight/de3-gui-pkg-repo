# GUI — Refactor Panel Auto-Preview

**Date:** 2026-04-20  
**File:** `homelab_gui/homelab_gui.py`, `infra/de3-gui-pkg/_config/de3-gui-pkg.yaml`

## Summary

Added auto-preview to the refactor panel: when the user sets a destination (by clicking a
node in the infra tree, or by typing and pausing), Preview runs automatically without
requiring a manual button click. The feature is controlled by two config parameters and
uses a JS `setTimeout` debounce for the typing path.

## Changes

- **`homelab_gui/homelab_gui.py`**
  - Added `_REFACTOR_AUTO_PREVIEW` and `_REFACTOR_AUTO_PREVIEW_DELAY_MS` module-level
    constants read from config (defaults: `true` / `2000 ms`).
  - `click_node`: when refactor panel is open and op is not delete, after setting
    `refactor_dst_path`, returns `AppState.run_refactor_preview` if auto-preview is on.
  - `set_refactor_dst_path`: when auto-preview is on, returns `rx.call_script` that
    clears any pending `setTimeout` and schedules a new one to click the hidden trigger
    button after `_REFACTOR_AUTO_PREVIEW_DELAY_MS` ms.
  - `set_refactor_operation`: clears the debounce timer when switching to delete (no
    destination, no preview needed).
  - `close_float_refactor`: clears the debounce timer on panel close.
  - `_refactor_panel`: added hidden `rx.button` with `id="refactor-auto-preview-trigger"`
    that fires `AppState.run_refactor_preview` when clicked by JS.

- **`infra/de3-gui-pkg/_config/de3-gui-pkg.yaml`**
  - Added `refactor_auto_preview: true` and `refactor_auto_preview_delay_ms: 2000` under
    `config:`.

## Notes

- The debounce uses `window._refactorAutoPreviewTimer` as the global timer handle, cleared
  on every keystroke before rescheduling — standard debounce pattern.
- Click-from-tree triggers immediately (returns the event spec directly from `click_node`,
  no JS involved); typing path uses the JS hidden-button trick (same pattern as wave poll).
- Setting `refactor_auto_preview: false` in config disables all auto-preview behaviour.
