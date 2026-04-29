# 20260413154306 — Context menu: expand Edit group, move Remove unit out of Destroy

## What changed

### Edit group now contains: Rename + Copy + Remove unit

Edit moved up to second position (just below Build). Items added to Edit:
- Copy unit and config block
- Copy unit and config block (recursive)
- Remove unit and config block…
- Remove unit and config block… (recursive)

### Destroy group now contains: Destroy + Taint only

Remove unit items removed from Destroy — they now live in Edit.

### Final menu order

| Group | Items |
|---|---|
| **Build** | Apply unit, Apply (recursive) |
| **Edit** | Rename…, Copy unit, Copy (recursive), Remove unit…, Remove unit (recursive)… |
| **Status** | Show inputs, Show outputs, Refresh build status (recursive) |
| **Debug** | Remove state lock file…, Remove state lock files (recursive)… |
| **Destroy** | Destroy unit, Destroy (recursive), Taint unit…, Taint (recursive)… |
| **Clipboard** | Paste (when clipboard has a unit) |
| **Shell** | Open local shell, SSH to host, etc. |
