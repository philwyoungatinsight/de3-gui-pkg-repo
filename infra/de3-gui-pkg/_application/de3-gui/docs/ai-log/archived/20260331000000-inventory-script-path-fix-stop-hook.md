# Inventory Script Path Fix + Stop Hook

## Summary
Fixed broken inventory refresh script path after `generate-ansible-inventory` was moved in
`pwy-home-lab`. Added a Stop hook to auto-remind Claude of the post-session checklist.

---

## Changes

### config/de-gui.yaml — inventory script path
- `scripts/generate_ansible_inventory/run` → `scripts/common/generate-ansible-inventory/run`
- Matches the new location after the `c59b451` refactor in `pwy-home-lab`
  (`move generate-ansible-inventory to scripts/common/`)

### .claude/settings.local.json + .claude/stop-checklist-hook.sh — Stop hook
- Added a `Stop` hook that runs on every session end
- If uncommitted `.py`/`.yaml`/`.yml`/`.json` files exist (excluding `state/` and `docs/ai-log`),
  injects `additionalContext` reminding Claude to complete the post-session checklist:
  1. Write `docs/ai-log/<datetime>-<slug>.md`
  2. Update `docs/ai-log-summary/README.ai-log-summary.md`
  3. `git commit` everything
- Silent when the repo is clean

### Compatibility check — pwy-home-lab infra changes
Verified GUI handles all recent `pwy-home-lab` changes without further code changes:

| Change | GUI impact |
|--------|-----------|
| Package-aware `source` paths (`${p_package}` in middle) | `_extract_module_path` regex already handles — captures last segment after final `}/` |
| New `all-config` sub-units | Discovered automatically by `_scan_infra` (recursive scan) |
| New `setup-via-ssh` sub-units | Same — appear as child nodes |
| New `cat-1`, `cat-2`, `cat-3` catalogs | Scanned correctly; total node count 114 |
| `generate-ansible-inventory` moved to `scripts/common/` | Fixed via config path update above |
| `_INFRA_DIR` added to `lab_stack_env.sh` | Not used by GUI; no change needed |

## Files Modified
- `config/de-gui.yaml`
- `.claude/settings.local.json`
- `.claude/stop-checklist-hook.sh` (new)
- `docs/ai-log/20260331000000-inventory-script-path-fix-stop-hook.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
