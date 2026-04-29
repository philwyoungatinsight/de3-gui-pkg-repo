# 20260407-103219 — File viewer: path bar wraps long filenames + copy button

## Problem

Long file paths in the path bar were clipped (`text-overflow: ellipsis;
white-space: nowrap`), making the full path invisible.

## Fix

### Path bar layout (`bottom_left_panel`)

Changed from a plain `rx.box(rx.text(...))` to `rx.hstack(rx.text(...), rx.button(...))`:

- `rx.text`: removed `overflow`, `text_overflow`, `white_space` constraints;
  added `word_break="break-all"` and `flex="1"` so the path wraps across as
  many lines as needed.
- `rx.button`: clipboard icon (`rx.icon("clipboard", size=12)`) on the right;
  calls `AppState.copy_file_path_to_clipboard`; `align="start"` keeps the icon
  pinned to the top of the row when the path wraps.

### New handler

```python
def copy_file_path_to_clipboard(self):
    """Copy the currently viewed file path to the system clipboard."""
    if not self.hcl_file_path:
        return
    return rx.set_clipboard(self.hcl_file_path)
```
