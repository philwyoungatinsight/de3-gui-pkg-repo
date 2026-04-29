# Browser panel: "Embedded" becomes an independent checkbox

## What changed

**`homelab_gui/homelab_gui.py`**:

- `_detect_chrome_profiles()`: first entry changed from `{"id":"embedded","label":"Embedded"}` to `{"id":"none","label":"None"}` (no external browser)
- State vars: removed `browser_profile: str = "embedded"` default; new default is `"none"`. Added `browser_embedded: bool = True`.
- `browser_profile_label` fallback changed from `"Embedded"` to `"None"`
- State save/restore: persists `browser_embedded` alongside `browser_profile`; load default changed from `"embedded"` to `"none"` with `browser_embedded=True`
- New `toggle_browser_embedded(value)` event handler
- `dispatch_action` for `url` type: if `browser_embedded` → loads in iframe; if `browser_profile != "none"` → also launches in external browser (Chrome profile / default / pycharm)
- `_browser_profile_selector()`: replaced single dropdown with `rx.hstack(checkbox("Embedded") + dropdown)`
- Nav-bar "open app" dropdown: filter changed from `!= "embedded"` to `!= "none"`

## Behaviour

| Embedded ✓ | Profile | Result |
|---|---|---|
| ✓ | None | Panel iframe only (previous default) |
| ✓ | Chrome X | Panel iframe + Chrome profile X |
| ✗ | Chrome X | Chrome profile X only |
| ✗ | Default | System default browser only |
