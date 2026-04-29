# YAML breadcrumb: show path only on text selection, matches filename bar style

## What changed

### Behaviour
- Breadcrumb bar is **empty by default** — no path shown until user selects text
  or search navigation fires
- When user selects text inside the file viewer (mouseup), the breadcrumb shows
  the YAML path of the selected line
- When search navigation runs (`_config_data_node_search_js` / `_pre_search_js`),
  `window._yamlCrumbUpdateFromMark(mark)` sets the path for the active match
- **Path stays pinned** — it does NOT clear on `selectionchange` with empty
  selection. This prevents flicker when node clicks inject `<mark>` elements
  (DOM mutation fires selectionchange before the path is set)
- Path is replaced only by: a new text selection, or a new search navigation call

### `_yaml_breadcrumb_install_js()`

Replaced scroll-listener approach with a single `mouseup` listener:

- No `selectionchange` handler (caused flicker on mark injection)
- `mouseup` handler: reads `window.getSelection()`, checks selection is inside
  `#file-viewer-pre`, walks up from `range.startContainer` to find the line span,
  reads its `dataset.yamlPath`. Only updates if path is non-null (i.e. selection
  is inside pre). Never clears.
- `window._yamlCrumbUpdateFromMark(mark)` — sets breadcrumb from a search mark,
  used by all search JS functions after scrolling to a match
- No injected `::selection` style — browser default selection colour

### Breadcrumb UI element
Style matches the filename bar exactly:
- `font_size="11px"`, `font_family="monospace"`, `color="var(--gui-text-muted)"`
- `background="var(--gui-panel-bg)"`, `padding_x="12px"`, `padding_y="4px"`
- `border_bottom="1px solid var(--gui-border)"`
- `display` toggled via `rx.cond(hcl_content != "")` — hidden when no file loaded

## Why scroll-based was wrong
- `span.offsetTop` vs `scroller.scrollTop` used inconsistent coordinate spaces
- Scroll-based path is ambiguous (which line = "current"?) and changes constantly
- Selection/search-navigation based is unambiguous: shows exactly where the user
  is focused
