# Depth Slider Control — All Three Views

## Overview
Added a "Depth" control (popover with a Radix slider) that limits the visible
depth across all three views: Tree (reflex), Nested Networks (Cytoscape), and
Tree2 (React Flow).

## Semantics

| Slider value | Meaning | Visible depths |
|---|---|---|
| 0 | "All" | Every node, tree fully expanded |
| 1 | "1" | Depth 0 only (root categories) |
| 2 | "2" | Depth 0 and 1 |
| k | "k" | Depth 0 … k |
| `_MAX_DEPTH` | deepest | All nodes (equivalent to "All") |

Default is **1** (matches the original tree behaviour: depth-0 expanded →
depth-0 and depth-1 nodes visible).

## Changes in `homelab_gui/homelab_gui.py`

### Module-level constants
- `_MAX_DEPTH: int` — computed from `_ALL_NODES_CACHE` max depth after
  `_init_reactflow_cache()` (fallback 4 for synthetic data).
- `_build_reactflow_elements()` — added `"depth"` key to each RF node's `data`
  dict so the depth filter can inspect it.

### `AppState` state vars added
```python
panel_show_depth: bool = True
depth_limit: int = 1   # 0=All, k=show depth 0..k
```

### `AppState` computed vars added
- `max_depth() -> int` — returns `_MAX_DEPTH`.
- `depth_button_label() -> str` — "All" when `depth_limit==0`, else str(k).

### Updated computed vars
- `cytoscape_elements` — adds `if lim > 0 and elem.depth > lim: skip`.
- `reactflow_nodes` — adds `lim == 0 or node.depth <= lim`.
- `reactflow_edges` — recomputes `visible_ids` including depth filter.

### Event handlers added
- `set_depth_limit(value)` — accepts `int` or `list[int]` (Radix slider).
  - Updates `depth_limit`.
  - Recomputes `expanded_paths` and `merged_expanded_paths` for tree views:
    - `depth_limit==0` → expand all paths.
    - `depth_limit==k` → expand paths where `depth < k` (shows depth 0..k).

- `toggle_panel_depth(checked)` / `flip_panel_depth()` — appearance control.

### `_save_current_config` / `on_load`
- Persists `depth_limit` and `panel_show_depth` to `state/current.yaml`.
- `on_load` restores both; recomputes `expanded_paths` from the restored depth.

### UI
- `_panel_depth_slider()` — `rx.popover` containing:
  - Header row: "Depth" label + current value ("All" or number) in blue.
  - `rx.slider(min=0, max=AppState.max_depth, on_value_commit=...)`.
  - Footer: "All" / `max_depth` range labels.
  - Uses `on_value_commit` (fires on drag-end) to avoid spamming state updates.
- `left_panel()` — adds `rx.cond(AppState.panel_show_depth, _panel_depth_slider(), rx.box())`.
- `appearance_menu()` — adds "Depth" checkbox row.
