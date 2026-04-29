# 20260404-230713 — File viewer: show line numbers option

## Feature

Added an "Show line numbers" toggle to the Appearance menu (File Viewer section).
When enabled, each line in the read-only file viewer is prefixed with a
right-aligned, dim, non-selectable line number separated from the code by a
thin vertical rule.

## Changes

### `homelab_gui/homelab_gui.py`

**New state var** (`AppState`):
```python
file_viewer_show_line_numbers: bool = False
```

**New handlers**:
```python
def toggle_file_viewer_show_line_numbers(self, checked: bool): ...
def flip_file_viewer_show_line_numbers(self): ...
```
Both call `_save_current_config()`.

**Persistence** — added to `_save_current_config` dict and restored in
`_restore_saved_config`.

**`hcl_parsed_lines` computed var** — each line dict now includes:
```python
"line_num": str(i + 1)
```

**`_HCL_LINE_NUM_STYLE`** — new module-level style dict for the line number
`<span>`: `display:inline-block`, `width:4ch`, right-aligned, dim colour,
right border, `userSelect:none`.

**`_render_hcl_line`** — prepends a conditional `rx.el.span(line["line_num"])`
(styled with `_HCL_LINE_NUM_STYLE`) or an empty span based on
`AppState.file_viewer_show_line_numbers`. Applied to both the source-link
branch and the plain-text branch.

**Appearance menu** — added a second item under "File Viewer":
```python
_appearance_menu_item(
    "Show line numbers",
    AppState.file_viewer_show_line_numbers,
    AppState.toggle_file_viewer_show_line_numbers,
    AppState.flip_file_viewer_show_line_numbers,
)
```
