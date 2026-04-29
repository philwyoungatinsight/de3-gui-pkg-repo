# ai-log: Markdown rendering in file viewer

**Date:** 2026-04-01  
**Branch:** feat/gui

## What changed

Added markdown rendering support to the bottom-left file viewer panel.

### New state var
- `file_viewer_render_markdown: bool = True` — controls whether `.md` files are rendered as formatted markdown (default on).

### New computed var
- `hcl_is_markdown: bool` — True when `file_viewer_render_markdown` is True and `hcl_file_path` ends with `.md`.

### New event handlers
- `toggle_file_viewer_render_markdown(checked: bool)` — checkbox handler.
- `flip_file_viewer_render_markdown()` — label-click handler.

### Persistence
- `_save_current_config()` now writes `file_viewer_render_markdown`.
- `on_load()` now restores `file_viewer_render_markdown` (default `True`).

### Appearance menu
- Added a new **"File Viewer"** section between "Terminal" and "Nested Networks" with a single checkbox: **"Render markdown files"** (default on).

### File viewer rendering
- The read-only rendering branch (non-editor, non-ANSI) now has an additional `rx.cond`:
  - If `hcl_is_markdown` → `rx.markdown(AppState.hcl_content)` inside a scrollable box.
  - Otherwise → existing `rx.el.pre(rx.foreach(...))` syntax-highlighted view.
- Code blocks inside markdown use monospace pre/code with a themed background.

## Files modified
- `homelab_gui/homelab_gui.py`
