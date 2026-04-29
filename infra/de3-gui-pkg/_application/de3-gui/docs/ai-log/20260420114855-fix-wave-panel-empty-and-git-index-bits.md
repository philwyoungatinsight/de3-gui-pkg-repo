# Fix Wave Panel Empty + Add git Index Bits Utility

## Summary

The GUI wave panel was showing no waves because `_find_stack_configs()` returned an empty list when `framework.yaml` did not exist, causing `_load_stack_config()` to exit early. Also, `waves_ordering.yaml` was being looked up at a stale `config/` root path instead of the actual `infra/default-pkg/_config/` location. Separately, a new human-only utility script was added to detect and clear `skip-worktree`/`assume-unchanged` git index bits, which can cause tracked files to silently disappear from disk without git noticing.

## Changes

- **`homelab_gui/homelab_gui.py`** — `_find_stack_configs()`: removed hard requirement for `framework.yaml` to exist; now scans `infra/*/_config/*.yaml` whenever the `infra/` directory is present, including `framework.yaml` only if it exists. `_load_stack_config()`: corrected `waves_ordering_path` from `config/waves_ordering.yaml` (root-level, never existed) to `infra/default-pkg/_config/waves_ordering.yaml`.
- **`infra/default-pkg/_framework/_human-only-scripts/fix-git-index-bits/run`** — new utility: scans `git ls-files -v` for `S` (skip-worktree) and `h` (assume-unchanged) flags, labels missing files, prompts user, then clears bits and restores missing files from HEAD.

## Root Cause

The GUI code was written expecting a unified `framework.yaml` at `infra/default-pkg/_config/framework.yaml` as a sentinel to trigger the infra scan. The actual repo layout splits framework config across `framework_*.yaml` fragments with no single `framework.yaml`, so the sentinel check always failed and the scan never ran. The `waves_ordering.yaml` path was a separate leftover from an older repo layout (`config/` at the root).

## Notes

The `skip-worktree` git index bit is the most likely explanation for the `run` script being tracked in HEAD but absent from disk while `git status` reported clean. Once set (often by sparse-checkout operations), the bit persists even after sparse checkout is disabled and survives `git pull`.
