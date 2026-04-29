# File viewer mode switch: post-render search via follow-up event

## Problem

Switching between `unit_file` ↔ `config_data` in the file viewer did not scroll
to the selected node or run the correct search. Root cause: `set_file_viewer_mode`
changed `hcl_content` AND returned a search script in the same WebSocket message.
React hadn't committed the new file content to the DOM when the JS ran, so the
search executed against the old file (unit HCL when switching to config YAML, or
vice versa) and found nothing.

## Fix

Split into two events (same pattern as `install_resizer`):

### `set_file_viewer_mode(mode)`
Updates all state: `file_viewer_mode`, `hcl_content`, `hcl_file_path`,
`config_data_search_query`. Does **not** return a search script.
Returns `AppState.post_mode_switch_search` as a follow-up event.

### `post_mode_switch_search()`  ← public name required (Reflex ignores `_` methods)
Runs as a separate WebSocket event, after React has committed the new content
to DOM. Dispatches the appropriate search:
- `config_data` mode + selected node → `_config_data_node_search_js` (same as clicking the node)
- `unit_file` mode → `_search_reapply_script` (re-highlights existing query)

## Note on Reflex event handler naming
Returning `AppState._post_mode_switch_search` (underscore prefix) raised:
```
TypeError: Your handler AppState.set_file_viewer_mode must only return/yield:
None, Events or other EventHandlers … Returned events of types <class 'function'>
```
Reflex does not expose `_`-prefixed methods as event handlers. Renamed to
`post_mode_switch_search` (no underscore).
