# 20260407-140708 — Fix: config-data search shows "Not found" on node click

## Problem

Clicking a node in the infra tree while in config_data mode showed a "Not found"
badge even though the path existed in the file. Clicking the prev/next arrows
immediately found it correctly.

Root cause: both `select_node` and `click_node` set `self.hcl_content` and then
immediately ran the search JS in the same event (or same `yield`). Reflex batches
state updates and `call_script` in the same WebSocket message, so React had not yet
re-rendered the new content when the JS searched for matches → 0 results →
`file_search_match_count = 0` → "Not found" badge.

`set_file_viewer_mode` already solved this with the `post_mode_switch_search`
deferred-event pattern: it returns `AppState.post_mode_switch_search` so the search
runs in a separate WebSocket round-trip after React has committed the new content.

## Fix

Both `select_node` (non-generator) and `click_node` (generator) now defer the
search the same way:

```python
# select_node
if self.hcl_content:
    return AppState.post_mode_switch_search  # was: return self._search_script(...)

# click_node
if self.hcl_content:
    yield AppState.post_mode_switch_search   # was: yield self._search_script(...)
```

`post_mode_switch_search` already constructs the correct search JS from
`self.selected_node_path` and `self._selected_node_provider`, both of which are
set before the deferred event fires.
