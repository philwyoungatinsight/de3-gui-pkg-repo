# 20260404-225524 — Monaco editor opens at the same line as the read-only view

## Problem

Opening the embedded Monaco editor always started at line 1, regardless of
where the user was scrolled in the read-only file viewer.

## Fix

Split `enter_file_edit_mode` into two steps using a JS callback:

### Step 1 — `enter_file_edit_mode`

Seeds `file_editor_draft` and `file_editor_save_error` as before, but now
does NOT immediately set `file_editor_active = True`. Instead it returns:

```python
rx.call_script(_read_pre_top_line_js(), callback=AppState.open_editor_at_line)
```

`_read_pre_top_line_js()` walks up from `#file-viewer-pre` to its scroll
container and returns the 1-based index of the first span whose bottom edge
is below `scrollTop`. The pre element is still in the DOM at this point.

### Step 2 — `open_editor_at_line(self, line: int)` (callback)

Sets `file_editor_active = True` (triggering the React re-render that mounts
Monaco), then returns:

```python
rx.call_script(_monaco_reveal_line_js(line_num))
```

`_monaco_reveal_line_js(line)` polls every 60ms until `monaco.editor.getEditors()`
is non-empty (Monaco has mounted), then calls `editor.revealLine(line, 1)`
(ScrollType.Immediate). This tolerates the async Monaco initialization delay.
