# Fix Cytoscape Nested Networks Layout Overlap

## Problem
The Nested Networks (Cytoscape) view had nodes overlapping each other. The
`cose` layout with low `nodeRepulsion: 8000` caused sibling compound groups and
leaf nodes to crowd together.

## Change

`cytoscape_view()` layout parameters in `homelab_gui/homelab_gui.py`:

| Parameter | Before | After | Reason |
|---|---|---|---|
| `nodeRepulsion` | 8000 | 450000 | Much stronger node separation |
| `nodeOverlap` | — | 40 | 40 px safety margin before overlap is detected |
| `componentSpacing` | — | 120 | Large gap between disconnected components |
| `idealEdgeLength` | 50 | 200 | Longer edges push connected nodes further apart |
| `edgeElasticity` | — | 100 | Softer springs to let repulsion dominate |
| `nestingFactor` | 5 | 1.2 | Standard compound-node multiplier (5 was too high) |
| `gravity` | 1 | 0.25 | Low gravity lets nodes spread out freely |
| `numIter` | 1000 | 2000 | More iterations for better convergence |
| `padding` | 30 | 60 | More whitespace at the graph boundary |

## Result
Sibling compound groups and leaf nodes no longer visually overlap. Parent
containers still visually contain their children (compound-node containment is
enforced by Cytoscape.js, not the layout).
