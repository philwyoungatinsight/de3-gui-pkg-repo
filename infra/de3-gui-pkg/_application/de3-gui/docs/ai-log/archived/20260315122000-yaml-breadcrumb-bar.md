# File Viewer: YAML breadcrumb bar

## What changed

**`homelab_gui/homelab_gui.py`**:

### New UI element
- Added a `#yaml-breadcrumb` bar below the file path bar, visible whenever `hcl_content != ""`
- Shows the YAML path to the currently visible section as the user scrolls (e.g. `providers › maas › config_params`)
- Uses monospace 11px, muted colour, ellipsis overflow — matches the file path bar style

### New JS helper: `_yaml_breadcrumb_install_js()`
Pure DOM update — no Reflex state / WebSocket round-trips involved.

- Finds the scrollable container (`pre.parentElement`, the `rx.box` with `overflow_y="auto"`)
- Installs a debounced (80 ms) `scroll` listener that computes and sets `#yaml-breadcrumb` text
- Also installs a `MutationObserver` (`childList: true, subtree: false`) on the `<pre>` to re-trigger the update whenever file content is replaced (new node selected, mode switch, etc.) — debounced 150 ms
- Safe to call multiple times: removes old listener/observer first

### YAML path algorithm (in JS)
1. Compute approximate visible line index: `Math.floor(scroller.scrollTop / lineHeight)` where `lineHeight = pre.scrollHeight / lineCount`
2. Walk backwards from that line collecting keys at strictly decreasing indentation levels
3. Key extraction handles: `key:`, `"quoted/key":`, `- key:`, `- "quoted/key":`
4. Joins with ` › ` (U+203A)

### Install
- Called once from `on_load` (after all other scripts)
- The MutationObserver handles subsequent content changes automatically — no need to call from individual handlers

### No new state vars
All updates are direct DOM mutations — the breadcrumb does not go through Reflex state.
