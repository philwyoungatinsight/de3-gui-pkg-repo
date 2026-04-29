# Add Playwright screenshot browser panel

## What changed

**`homelab_gui/playwright_browser.py`** (new file):
- Shared headless Chromium process via `async_playwright()` (one per server process, lazy init)
- `_screenshot_loop()` task: captures JPEG screenshots at ~10 fps, broadcasts to all connected WebSocket clients via `asyncio.Queue`
- `navigate(url)` coroutine: shared by initial navigation and `navigate` WebSocket messages
- `handle_pb_page()`: serves `GET /pb` — HTML page with `<canvas>` + toolbar (Back, Forward, Reload, URL bar, Go)
- `handle_playwright_ws()`: serves `WS /ws/pb` — streams base64-JPEG frames; accepts JSON control messages: `navigate`, `back`, `forward`, `reload`, `click`, `dblclick`, `right_click`, `scroll`, `key`
- Canvas mouse events normalized to [0..1] coordinates, mapped to absolute pixels (1280×800) on server

**`homelab_gui/homelab_gui.py`**:
- `_detect_chrome_profiles()`: first entry changed from `{"id":"none","label":"None"}` to `{"id":"playwright","label":"Playwright"}`
- State vars: `browser_profile` default changed to `"playwright"`; added `playwright_url: str = ""`
- `on_load` restore: default for `browser_profile` changed from `"none"` to `"playwright"`; `browser_profile_label` fallback changed to `"Playwright"`
- Added `playwright_iframe_url` computed var: generates `/pb?url=<encoded>` URL for the iframe `src`
- Added `open_playwright_url(url)` event handler: sets `playwright_url`, clears `browser_url` and `shell_cwd`
- All event handlers that clear `browser_url` also clear `playwright_url`: `open_shell`, `open_ssh_terminal`, `select_node`, `click_node`, `click_module_node`, and the `terminal_cmd` branch of `dispatch_action`
- `dispatch_action` for `url` type: when `browser_embedded=True` and `browser_profile="playwright"` → `open_playwright_url`; when `browser_embedded=True` and other profile → `open_browser_url`; external browser excludes "playwright" from the profiles list
- Bottom-right panel content: added `rx.cond(playwright_url != "", iframe(playwright_iframe_url), ...)` between terminal and regular browser
- Header info text: also shows `playwright_url` (priority between `shell_cwd` and `browser_url`)
- Nav-bar "open app" dropdown: filter changed from `!= "none"` to `!= "playwright"`
- Registered `GET /pb` and `WS /ws/pb` routes via `app._api`

## Behaviour

| Embedded ✓ | Profile | Result |
|---|---|---|
| ✓ | Playwright | Playwright screenshot canvas in panel (new default) |
| ✓ | Chrome X | Panel iframe with Chrome profile X's URL |
| ✗ | Chrome X | Chrome profile X only (external) |
| ✗ | Default | System default browser only |

The Playwright canvas page (`/pb`) connects over WebSocket (`/ws/pb`) and:
- Renders JPEG screenshots on a `<canvas>` element filling the iframe
- Forwards clicks, double-clicks, right-clicks, scrolls, and key presses back to the Playwright page
- Has a toolbar for manual navigation (URL bar, Back, Forward, Reload)
- Auto-navigates to the `?url=` query parameter on connect
