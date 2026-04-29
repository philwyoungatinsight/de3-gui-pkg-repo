# Fix: "Open" context menu action respects browser profile selector

## What changed

**`homelab_gui/homelab_gui.py`** — `dispatch_action`:
- Previously: `url` action type always called `window.open(..., '_blank')` regardless of the selected browser profile
- Now: checks `self.browser_profile` and routes accordingly:
  - `embedded` → `open_browser_url()` (loads in the embedded iframe panel)
  - `default` → `xdg-open` subprocess
  - `pycharm` → `pycharm` subprocess (falls back to xdg-open)
  - Chrome profile ID → `google-chrome --profile-directory=<id>` subprocess

## Why

The "Open" item injected into the context menu (`_browser_url` action) was ignoring the browser dropdown selector, always opening a new tab instead of using the chosen browser/profile.
