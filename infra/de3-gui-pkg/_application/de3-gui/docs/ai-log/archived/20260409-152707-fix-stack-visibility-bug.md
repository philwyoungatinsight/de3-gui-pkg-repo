# 2026-04-09 — Fix `_stack` ancestor path bug causing empty infra tree

## Problem

After all the engine-compatibility fixes applied earlier in this session, the GUI
still showed nothing in the infra (left panel tree) when running. Depth-0 package
nodes were technically visible but depth-1 provider nodes and all deeper nodes were
invisible.

## Root cause

Node paths in the new engine include `_stack` as an intermediate path component:

    pwy-home-lab-pkg/_stack/proxmox          (depth 1)
    pwy-home-lab-pkg/_stack/proxmox/pwy-homelab  (depth 2)
    ...

The `visible_nodes` computed var checks ancestor visibility by iterating `parts[:-1]`
and verifying each prefix is in `expanded_paths`. For depth-1 node
`pwy-home-lab-pkg/_stack/proxmox`, the check evaluates:

1. `"pwy-home-lab-pkg"` → in expanded_paths ✓
2. `"pwy-home-lab-pkg/_stack"` → NOT in expanded_paths ✗ → visible=False

`"pwy-home-lab-pkg/_stack"` is never a real node (it has no corresponding dir entry
in the tree), so it is never added to `expanded_paths`. Every depth-1+ node failed
this check and was hidden.

## Fix

Skip the `_stack` segment in the `expanded_paths` ancestor check in `visible_nodes`
(the `merged_visible_nodes` var is unaffected — merged paths strip `_stack` already):

```python
for part in parts[:-1]:
    check = f"{check}/{part}" if check else part
    if part == "_stack":
        # "_stack" is a virtual path segment with no node of its own;
        # skip the expanded_paths check for this intermediate segment.
        continue
    if check not in self.expanded_paths:
        visible = False
        break
```

## Verification (logic trace)

With `depth_limit=0` (all paths in `expanded_paths`):
- Depth-1 `pwy-home-lab-pkg/_stack/proxmox`: checks `pwy-home-lab-pkg` ✓, skips `_stack` → visible ✓
- Depth-2 `pwy-home-lab-pkg/_stack/proxmox/pwy-homelab`: checks `pwy-home-lab-pkg` ✓,
  skips `_stack`, checks `pwy-home-lab-pkg/_stack/proxmox` ✓ → visible ✓

With `depth_limit=1` (only depth-0 paths in `expanded_paths`):
- Depth-1 visible (parent package in expanded_paths) ✓
- Depth-2 hidden until depth-1 node is clicked ✓

Expand/collapse via node click still works: clicking a provider node adds
`pwy-home-lab-pkg/_stack/proxmox` to `expanded_paths`, which the next level's
ancestor check finds correctly.

## Files changed
- `homelab_gui/homelab_gui.py`
