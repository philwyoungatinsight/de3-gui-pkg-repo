# 20260407-115929 — Help menu: Topics + Scripts entries; doc navigation cleanup

## GUI changes

### New handlers (`homelab_gui.py`)

```python
def open_docs_topics(self):
    """Load docs/README.md (topics index) into the file viewer."""
    readme = _STACK_DIR / "docs" / "README.md"
    ...

def open_docs_scripts(self):
    """Load scripts/README.md into the file viewer."""
    readme = _STACK_DIR / "scripts" / "README.md"
    ...
```

### Help menu additions

Two new items added between "Docs (Engine)" and the separator:
- **Topics** → `open_docs_topics` — opens `docs/README.md`
- **Scripts** → `open_docs_scripts` — opens `scripts/README.md`

## Lab stack doc changes (`pwy-home-lab` repo)

### Duplication removed

- `docs/topics/README.bare-metal-onboarding.md` — removed duplicate switch
  port tables (USW-Pro-Max-16, USW-Flex-2.5G-8, MS-01 port layout); replaced
  with a single link to `README.network-planning.md`.
- `docs/topics/README.add-smart-plug-host.md` — removed Appendix A (cabling)
  and Appendix B (BIOS); replaced with a single "Appendix A — Cabling and
  BIOS Setup" section linking to `README.bare-metal-onboarding.md`. Renamed
  Appendix D → C.
- `docs/topics/README.maas-provisioned-proxmox-host-setup.md` — condensed
  "Networking and SSH Access" section (was ~300 words) to a short summary +
  link to `README.network-planning.md`.

### Hardcoded paths fixed

- `README.maas.md` — removed `cd /home/pyoung/git/...`; replaced with
  `source $(git rev-parse --show-toplevel)/set_env.sh` + `cd $_STACK_DIR`.
- `README.troubleshooting.md` — same fix for `cd ~/git/...`.

### Format cleanup

- `README.idempotence-and-tech-debt.md` — replaced spec-template headers
  (`# Goal`, `# General Requirements and Approach`) with a clean prose intro
  and focused sections.

### Navigation links added

- `lab_stack/README.md` — new "Documentation" section linking to
  `docs/README.md`, `scripts/README.md`, `_modules/README._modules.md`,
  `_providers/README.md`.
- `scripts/tg-scripts/README.md` — replaced "See the README in each package
  subdirectory" with explicit per-package hyperlinks.
- `scripts/wave-scripts/README.md` — same.
