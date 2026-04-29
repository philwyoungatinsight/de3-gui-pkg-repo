# Four-Panel Layout — File Viewer + Embedded Browser

## Overview

The 2-panel layout (left viz / right unit-params) was extended to a 4-panel
layout:

```
┌─ navbar (56px, fixed) ────────────────────────────────────────────┐
├──────────────────────────────────────────────────────────────────-┤
│  left-column              │  right-column                         │
│  ┌─ top-left-panel ─────┐ │ ┌─ top-right-panel ─────────────────┐│
│  │  tree / graph view   │ │ │  unit params                      ││
│  └──────────────────────┘ │ └───────────────────────────────────┘│
│  [panel-h-resizer bar]    │                                       │
│  ┌─ bottom-left-panel ──┐ │ ┌─ bottom-right-panel ──────────────┐│
│  │  terragrunt.hcl      │ │ │  embedded browser (iframe)        ││
│  │  file viewer         │ │ │  + URL action buttons in header   ││
│  └──────────────────────┘ │ └───────────────────────────────────┘│
│              [panel-resizer (vertical)]                           │
```

Column widths share the existing `left_panel_width_pct` state var.
Row heights share the new `top_row_height_pct` state var (default 60 %).

## Changes

### `homelab_gui/homelab_gui.py`

**`_RESIZER_JS`** — changed `getElementById('left-panel')` →
`getElementById('left-column')` (both occurrences) so the vertical resizer
targets the new column wrapper rather than the old panel element.

**`_HRESIZER_JS`** — new constant; horizontal drag-to-resize JS that mirrors
the vertical resizer pattern:
- `mousedown` on `#panel-h-resizer` records start Y + top panel height.
- `mousemove` clamps new height between 100 px and (column height − 100 px),
  sets `top-left-panel.style.height` and `top-right-panel.style.height` in sync.
- `mouseup` clicks `#hresize-complete-trigger` → `on_hresize_complete()`.

**New state vars:**
```python
top_row_height_pct: int = 60   # % of panel area for top row
hcl_content:        str = ""   # content of selected node's terragrunt.hcl
browser_url:        str = ""   # URL loaded in bottom-right iframe
```

**New computed vars:**
- `top_row_height_style() -> str` — `f"{top_row_height_pct}%"`.
- `selected_node_url_actions() -> list[dict]` — calls `_get_node_actions()` and
  filters to `action_type == "url"`; drives bottom-right header buttons.

**`select_node(path)`** — now also resets `browser_url = ""` and sets
`hcl_content = _read_hcl_file(path)`.

**New event handlers:**
- `open_browser_url(url)` — sets `browser_url`.
- `save_row_height(pct)` — clamps and persists `top_row_height_pct`.
- `on_hresize_complete()` — reads actual top-panel height % via `rx.call_script`
  callback into `save_row_height`.

**`install_resizer()`** — now runs `_RESIZER_JS + _HRESIZER_JS` in one call.

**Persistence** — `_save_current_config` / `on_load` persist/restore
`top_row_height_pct`.

**`_read_hcl_file(node_path)`** — new module-level helper; reads
`infra/{node_path}/terragrunt.hcl`, returns text or `""`.

**`left_panel()`** — refactored to flex-column layout; removed `id`,
`border_right`, fixed `width` (those live on the column wrapper in `index()`).
Content box uses `flex="1"` instead of `height="calc(...)"`.

**`right_panel()` → `top_right_panel()`** — renamed; same flex-column refactor.

**`h_panel_resizer()`** — 5 px horizontal drag bar (`id="panel-h-resizer"`).

**`bottom_left_panel()`** — flex-column panel:
- Header shows "File Viewer" + current HCL file path.
- Content: `rx.scroll_area` wrapping `rx.el.pre` with monospace styling when
  `hcl_content != ""`; placeholder text otherwise.

**`_url_action_button(action)`** — renders a soft blue button wired to
`AppState.open_browser_url(action["value"])`.

**`bottom_right_panel()`** — flex-column panel:
- Header: "Browser" label + current URL + `rx.foreach` of URL action buttons
  from `AppState.selected_node_url_actions`.
- Content: `rx.el.iframe(src=AppState.browser_url)` when a URL is set;
  placeholder text otherwise.

**`index()`** — rewritten with nested flex layout; left column wraps
`top-left-panel + h-resizer + bottom-left-panel`, right column wraps
`top-right-panel + bottom-right-panel`. Added `#hresize-complete-trigger` div.

## How it works

1. User selects a node → `select_node()` fires → HCL file loaded into
   `hcl_content`, `browser_url` reset.
2. Bottom-left panel renders the HCL file content.
3. Bottom-right header shows URL action buttons sourced from
   `provider-actions.yaml` (e.g. "Proxmox UI", "MaaS Admin UI").
4. Clicking a button → `open_browser_url(url)` → `browser_url` set →
   `<iframe>` renders the URL inside the panel.
5. Dragging `#panel-h-resizer` adjusts top/bottom row heights; final value
   saved to `state/current.yaml` on mouseup.
