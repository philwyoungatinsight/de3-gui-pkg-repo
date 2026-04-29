# ai-log: Packages panel section tooltips

**Date:** 2026-04-01  
**Branch:** feat/gui

## What changed

Added `rx.tooltip` to three section labels in the packages panel (`_pkg_card`):

- **Providers:** — "Terraform providers used by the modules in this package"
- **TG Scripts** — "Scripts called by the Terragrunt units in this package"
- **Wave Scripts** — "Scripts available to be called by the wave(s) in this package"

## Files modified
- `homelab_gui/homelab_gui.py`
