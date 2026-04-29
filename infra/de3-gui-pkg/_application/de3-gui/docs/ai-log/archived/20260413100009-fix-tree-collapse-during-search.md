# 20260413100009 — Fix: tree folder collapse broken during search

## Root cause

`visible_nodes` (and `merged_visible_nodes`) had a special `if filtering:` branch
that ran when `explorer_search` or role filters were active. Inside that branch,
**`expanded_paths` was completely ignored** — every node that passed the search
filter was shown unconditionally.

Consequence: clicking a folder to collapse it called `click_node`, which removed
the path from `expanded_paths`, but `visible_nodes` still showed all the children
because it never consulted `expanded_paths` in filter mode. The collapse had no
visible effect; the ▼/▶ indicator was also wrong (driven by `search_anc`, not
`expanded_paths`).

## Fix

### `visible_nodes` and `merged_visible_nodes`
Removed the dedicated `if filtering: ... continue` branches from both functions.
The unified expand/collapse logic (respecting `expanded_paths`) now runs for both
filtered and normal modes. The `is_expanded` indicator now always reflects
`expanded_paths`.

### `set_explorer_search`
When a new search term is set, auto-expand all ancestors of matching nodes in
both `expanded_paths` and `merged_expanded_paths`. This ensures search results
remain visible regardless of the current `depth_limit` or prior collapsed state —
without which the visible_nodes fix would hide results whose parents hadn't been
explicitly expanded.

### `on_load`
Added the same ancestor auto-expansion step after `expanded_paths` is initialised
from `depth_limit`, applied when a search term was persisted in `state/current.yaml`.
This handles the initial-load case where a search is restored from state and
`depth_limit > 0`.

## Behaviour after fix

| Situation | Before | After |
|---|---|---|
| No search, click folder | Collapses ✓ | Collapses ✓ |
| Search active, click folder | No visual effect ✗ | Collapses ✓ |
| Search active, ▼/▶ indicator | Driven by `search_anc` (wrong) | Driven by `expanded_paths` (correct) |
| Search on load (from state) | Results visible ✓ | Results visible ✓ |
| depth_limit > 0, new search typed | Results visible (old filtering path) | Results visible (auto-expand) ✓ |
