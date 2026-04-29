# Fix on_load double-fire, panel resizer JS, and Continue button status panel

## Summary

Three related fixes to the GUI test infrastructure and app behavior:

### 1. Reflex on_load double-fire fix (`homelab_gui.py`)

**Problem**: Reflex 0.8.27 fires `on_load` twice per page load due to a WebSocket
reconnect. The second call was resetting test state back to config defaults, causing
`test-tree-open-node` to fail (pve-1 selection lost before checks ran).

**Root cause**: Reflex runs multiple worker processes — a module-level Python variable
couldn't coordinate between them.

**Fix**: Use a file-based marker (`/tmp/.homelab-gui-test-applied`) written by
`_apply_test_state()` with the current timestamp. `on_load()` reads this file; if it
is less than 10 seconds old and no new `.test_state.yml` exists, the second call skips
re-initialization and returns `AppState.install_resizer` directly.

`make clean` now deletes this marker file to prevent stale state across test runs.

### 2. Panel resizer JS injection (`homelab_gui.py`)

**Problem**: `rx.script(src="/resizer.js")` does not execute — React Helmet injects
scripts via `innerHTML`, which browsers refuse to execute per the HTML spec.
The `_panelResizerReady` sentinel was never set, so drag-to-resize didn't work.

**Fix**: `on_load()` returns `AppState.install_resizer` at the end of both code paths
(normal init and the skip path). `install_resizer()` returns `rx.call_script(_RESIZER_JS)`,
executing the resizer JavaScript through the Reflex WebSocket (guaranteed post-hydration).

### 3. Continue button → persistent two-line status panel (`tests/browser_test.py`)

**Problem**: The green "✓ Continuing…" flash disappeared too quickly after clicking.
User couldn't see what the button did or what test was running.

**Fix**: Redesigned the floating panel to show two lines:
- **next-step**: what will happen on click (e.g., "▶ Click to run 3 check(s)")
- **status**: current activity (e.g., "✓ node_visible:pve-1\n✗ node_selected:pve-1")

The panel updates live as each check runs (amber while running, green on pass, red on
fail) and stays visible until just before `context.close()`. A `_btn_update()` Python
helper and `window._pwUpdateBtn()` JS function handle updates without re-injecting.

### 4. Post-continue pause (`config/testing.yaml`, `browser_test.py`)

Added `post_continue_pause_secs: 3` to `testing.yaml`. After clicking Continue, the
script sleeps this many seconds before running checks so the user can see the live
browser state. Wired through `browser_assert.yml` via `--post-continue-pause` flag.

## Tests passing

All unit tests now pass:
- `test-api-endpoints` — API health checks
- `test-tree-open-node` — tree state, node selection, right panel
- `test-resize-panel` — panel drag-to-resize (`panel_resize_works:200`)
