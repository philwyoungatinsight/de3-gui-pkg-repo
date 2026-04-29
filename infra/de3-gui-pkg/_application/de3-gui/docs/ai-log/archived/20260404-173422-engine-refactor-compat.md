# 20260404-173422 — Compatibility with engine repo package-subdir refactor

## What changed in the engine repo

### `cc2fc91` — package config files moved to subdirectories
Each package now lives in its own subdirectory under `terragrunt_lab_stack/`:
- `maas-pkg/terragrunt_lab_stack_maas-pkg.yaml`
- `maas-pkg/terragrunt_lab_stack_maas-pkg_secrets.sops.yaml`
- etc.

The base file `terragrunt_lab_stack.yaml` and its secrets remain at the root.

### `a0e7c41` — wave names renamed
- Dropped `.pwy-homelab` site suffix from all on-prem wave names
- Renamed `cloud.storage.multi` → `cloud.storage`
- Renamed `vm.proxmox.pwy-homelab.mesh-central` → `vm.mesh-central`
- Removed `util.noop`
- Added `hw.storage`, `hw.power`, `hw.servers` waves
- Wave structure is still a list of `{name, description, ...}` dicts — GUI already handled this correctly

## Bugs fixed in GUI

### Bug 1: `_STACK_CONFIG_KEY` wrong → waves not loaded
`_find_stack_configs()` uses `rglob` + `sorted()`. After the package subdir move,
`aws-pkg/terragrunt_lab_stack_aws-pkg.yaml` sorted **before** the root-level
`terragrunt_lab_stack.yaml` (because `'a' < 't'`). The first file's key became the
primary key (`terragrunt_lab_stack_aws-pkg` instead of `terragrunt_lab_stack`).
`_STACK_CONFIG.get("terragrunt_lab_stack_aws-pkg")` has no `waves` → wave panel
showed nothing, wave numbers missing from tree nodes.

**Fix**: sort key `(0 if f.name == "terragrunt_lab_stack.yaml" else 1, str(f))` ensures
the base file always comes first regardless of subdirectory nesting.

### Bug 2: Package secrets not found
`_scan_packages()` looked for secrets only at `_secrets_base / _sname` (root).
Package secrets moved to `_secrets_base / pkg_name / _sname`.

**Fix**: try root-level path first; if not found, try `_secrets_base / pkg_name / _sname`.
Default secrets (`terragrunt_lab_stack_secrets.sops.yaml`) remain at root → found on
first try. Package secrets are found via the subdirectory fallback.
