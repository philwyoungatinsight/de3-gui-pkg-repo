# Cytoscape.js Native Reflex Component

## Problem
The previous Cytoscape.js integration used `rx.el.iframe` loading a static
`assets/cytoscape_viewer.html` that fetched data from `/api/infra-graph` via
CDN scripts (unpkg.com). It never rendered correctly — likely due to CDN
availability, path resolution, or CORS issues inside the iframe.

## Solution
Replaced the iframe approach with a proper `NoSSRComponent` wrapper around
`react-cytoscapejs`, following the same pattern as Reflex's built-in
`DataTable` (which wraps `gridjs-react`).

### Key implementation details

**Component class** (`_CytoscapeGraph` in `homelab_gui/homelab_gui.py`):
```python
class _CytoscapeGraph(NoSSRComponent):
    library: str = "react-cytoscapejs@2.0.0"
    lib_dependencies: list[str] = ["cytoscape@3.29.2"]
    tag: str = "CytoscapeComponent"
    is_default: bool = True
    _rename_props: ClassVar[dict] = {"cyStyle": "style"}

    elements:   Var[list]
    stylesheet: Var[list]
    layout:     Var[dict]
    cy_style:   Var[dict]
```

**Why `cy_style` instead of `style`:**  Reflex reserves `style` for its own
CSS-style system and intercepts it in `_post_init`. Using `cy_style` (Python)
+ `_rename_props = {"cyStyle": "style"}` (camelCase, post-Reflex conversion)
passes the correct `style` prop to the React component without conflict.

**Synthetic data:** `_SYNTHETIC_ELEMENTS` and `_CYTOSCAPE_STYLESHEET` provide
a hardcoded graph (Proxmox nodes, Unifi, k3s workers) so the view works
immediately without a live infra directory. Wire up live data from AppState
once the widget is confirmed working.

**npm packages** added automatically by Reflex to `.web/package.json`:
- `react-cytoscapejs@2.0.0`
- `cytoscape@3.29.2`

## Files Changed
- `homelab_gui/homelab_gui.py`
  - Added imports: `NoSSRComponent`, `Var`, `ClassVar`
  - Added `_CytoscapeGraph` component class
  - Added `_SYNTHETIC_ELEMENTS` and `_CYTOSCAPE_STYLESHEET` constants
  - Replaced `cytoscape_view()` iframe with `_CytoscapeGraph.create(...)`
  - Removed `_build_mxgraph_cells()`, `mxgraph_view()`, mxgraph API route
  - Removed mxgraph from `VIZ_FRAMEWORKS`
  - Consolidated view selector: single dropdown "Tree" / "Nested Networks"
  - Added `set_view_mode()` event handler + `view_mode` computed var
