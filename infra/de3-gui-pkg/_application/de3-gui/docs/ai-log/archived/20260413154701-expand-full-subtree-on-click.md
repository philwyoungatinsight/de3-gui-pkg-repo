# 20260413154701 — Expand full subtree on click

## What changed

Clicking a folder node in the tree now expands the entire subtree down to leaf
units in a single click, rather than revealing only immediate children.

### Before

Clicking a folder added only that folder's path to `expanded_paths`. Each level
required a separate click to open.

### After

Clicking a collapsed folder adds its path **and all descendant paths** (from
`all_nodes` / `merged_nodes_base`) to `expanded_paths` in one operation. The
entire hierarchy below the clicked node becomes visible immediately.

Collapsing is unchanged — clicking an already-expanded folder still removes that
node and all its descendants from `expanded_paths`, collapsing the whole subtree.

Applies to both Separated mode (`expanded_paths` / `all_nodes`) and Merged mode
(`merged_expanded_paths` / `merged_nodes_base`).

## Code location

`select_node` in `homelab_gui.py`, expand/collapse block (~line 6212).
