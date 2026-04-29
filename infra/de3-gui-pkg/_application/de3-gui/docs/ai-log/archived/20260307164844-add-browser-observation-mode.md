# Add browser observation mode (timer and interactive)

## Problem

When `headless: false`, the browser opened and closed immediately.
`browser_test.py` ran all Playwright checks and exited before the user could
see anything. The `ansible.builtin.pause` in `main.yml` fired *after* the
browser was already closed, so the prompt was meaningless.

## Root cause

Observation must happen *inside* `browser_test.py`, before `context.close()`.
The Ansible-level pause cannot keep a browser alive that Python has already shut down.

## Changes

### Modified: `config/testing.yaml`

Added two new `ui_testing` parameters:

```yaml
observation_mode: "interactive"   # none | timer | interactive
observation_timeout_secs: 60
```

- `none` — close immediately after checks (default; always used in headless mode)
- `timer` — sleep `observation_timeout_secs` seconds, then close
- `interactive` — inject a floating "▶ Continue test" button into the page AND
  listen for Enter on stdin; whichever comes first advances the test.
  `observation_timeout_secs` is the maximum wait (0 = indefinite).

### Modified: `tests/browser_test.py`

Added two observation pause points inside `run()`:

1. **After page hydration, before checks** — lets the user see that the GUI
   state was applied correctly before assertions run.
2. **After all checks pass** — lets the user confirm the DOM looks right.

Added helpers:

- `observe(page, mode, timeout_secs, prompt)` — dispatcher
- `_wait_for_click_or_page_click(page, timeout_secs)` — for interactive mode:
  - Injects a `<button id="pw-observe-btn">` overlay via `page.evaluate()`
  - Polls for `btn.dataset.clicked == 'true'` (set by `onclick`)
  - Simultaneously polls stdin with `select.select(..., timeout=0)` (non-blocking)
  - Advances on the first of: button click, Enter keypress, or timeout

Added CLI args:
- `--observation-mode none|timer|interactive`
- `--observation-timeout SECS`

Observation is suppressed automatically when `--headless true`.

### Modified: `tests/roles/gui-test/tasks/main.yml`

- Extract `_ui_observation_mode` and `_ui_observation_timeout` from `testing.yaml`
- Fixed the `ansible.builtin.pause` condition:
  - **Before**: fired whenever `not headless` (even when browser_checks were present,
    meaning the browser was already closed)
  - **After**: only fires when `not headless AND browser_checks | length == 0`
    (screenshot-only path, where the browser is launched fire-and-forget)

### Modified: `tests/roles/gui-test/tasks/browser_assert.yml`

Passes `--observation-mode` and `--observation-timeout` to `browser_test.py`.

### Modified: `tests/roles/gui-test/defaults/main.yml`

Added defaults:
```yaml
_ui_observation_mode: "none"
_ui_observation_timeout: 60
```
