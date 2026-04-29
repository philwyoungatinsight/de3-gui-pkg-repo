# 20260413154050 — Context menu: "Status" and "Debug" groups

## What changed

Reorganised the right-click context menu extra_actions to reduce clutter in the
"Build" group and give each logical category its own header.

### Before

All of these lived under **Build**:
- Apply unit / Apply (recursive)
- Copy unit and config block / (recursive)
- Show inputs
- Show outputs
- Remove state lock file…
- Remove state lock files (recursive)…
- Refresh build status (recursive)  *(when show_unit_build_status)*

### After

| Group | Items |
|---|---|
| **Build** | Apply unit, Apply (recursive), Copy unit, Copy (recursive) |
| **Status** | Show inputs, Show outputs, Refresh build status (recursive) |
| **Debug** | Remove state lock file…, Remove state lock files (recursive)… |
| **Destroy** | (unchanged) |
| **Edit** | (unchanged) |

"Status" and "Debug" added to `group_labels` dict so they display with proper
capitalised labels in the menu header.
