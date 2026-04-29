# Fix Playwright diagnostics and add page scraping

## Problem

`make test` showed "Browser opened at..." but no browser appeared.
Three root causes:

1. **No diagnostic output** — no way to know if `browser_test.py` was even running,
   let alone whether Playwright connected to the page.
2. **`browser_assert.yml` silently swallowed errors** — missing `failed_when` meant
   a non-zero exit from `browser_test.py` could go unnoticed in some flows.
3. **Variable scoping not verified** — `browser_checks` is passed via `include_role vars:`;
   if it evaluated to `[]` (the role default) due to a scoping issue, `browser_assert.yml`
   would be silently skipped and `screenshot.yml` + the ansible pause would run instead,
   with no browser window if Chrome wasn't on PATH.

## Changes

### Modified: `tests/browser_test.py`

Added `_page_summary(page, screenshot_path)` — called immediately after Reflex hydration,
before any checks run. Always executes regardless of headless/observation mode.

Outputs:
```
  --- Page Summary ---
  Title   : Home Lab GUI
  URL     : http://localhost:8080/
  Content : cat-hmc cat-1 cat-2 proxmox maas pve-1 pve-2 ...
  Screenshot: tests/screenshots/auto-1234567890.png
  --------------------
```

- Dumps page title, URL, and up to 800 chars of `document.body.innerText`
- Always saves a screenshot (auto-named by timestamp if `--screenshot` not given)
- On check failure: saves a second `fail-<timestamp>.png` of the broken state

Added verbose startup logging:
```
[browser_test] Playwright launching Chromium (headless=false, observation=interactive)
[browser_test] Target URL: http://localhost:8080
[browser_test] Navigating to http://localhost:8080 ...
[browser_test] Waiting for Reflex to hydrate (looking for 'cat-' nodes)...
[browser_test] Page ready.
[browser_test] Running 3 check(s)...
  OK   node_visible:pve-1
  OK   node_selected:pve-1
  OK   right_panel_has:proxmox
[browser_test] All checks passed.
```

### Modified: `tests/roles/gui-test/tasks/browser_assert.yml`

- Added `failed_when: _bt_result.rc != 0` — errors now fail the play loudly
- Added "Browser test command" debug task that prints the exact `python3 browser_test.py`
  invocation before it runs — makes it obvious what command is being executed
- Added separate "Playwright stderr" task that shows stderr when non-empty
- Passes `--observation-mode` and `--observation-timeout` to `browser_test.py`

### Modified: `tests/roles/gui-test/tasks/main.yml`

- Added "Browser checks configured" debug task immediately before `browser_assert.yml`
  include — prints the `browser_checks` list and its length, making any variable
  scoping failure immediately visible:
  ```
  browser_checks (3 items): ['node_visible:pve-1', 'node_selected:pve-1', 'right_panel_has:proxmox']
  ```
- Renamed tasks for clarity: "Run Playwright browser assertions" and
  "Take screenshot (no browser_checks path)"
