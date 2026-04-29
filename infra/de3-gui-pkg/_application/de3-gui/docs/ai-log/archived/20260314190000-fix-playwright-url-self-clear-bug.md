# Fix: open_playwright_url immediately clearing playwright_url

## What changed

**`homelab_gui/homelab_gui.py`**:
- Fixed `open_playwright_url` event handler: a stray `self.playwright_url = ""` line immediately cleared the URL that was just set (copy-paste error)

**`tests/test_playwright_browser.py`**:
- Fixed test [5] button selector: changed `has-text('Open')` (substring) to `get_by_role("button", name="Open", exact=True)` so the nav bar "Open in ▾" button is not accidentally clicked
- Fixed `wait_for_function` check from `.includes(action_label)` to `=== action_label` for same reason

## Root cause

`open_playwright_url` had three lines setting state:
```python
self.playwright_url = url   # set correctly
self.browser_url = ""
self.playwright_url = ""    # BUG: immediately clears it
```
The last line was a copy-paste error from `open_browser_url`/`open_shell`. The result was that `playwright_url` was always empty after the event, so the `rx.cond(playwright_url != "", ...)` never rendered the `/pb` iframe.

## Test status

All 5 tests now pass:
1. GET /pb page — OK
2. WS /ws/pb frames — OK
3. GUI iframe inject (JS direct) — OK
4. GUI state injection (test-state API) — OK
5. GUI button click (full Reflex state flow) — OK
