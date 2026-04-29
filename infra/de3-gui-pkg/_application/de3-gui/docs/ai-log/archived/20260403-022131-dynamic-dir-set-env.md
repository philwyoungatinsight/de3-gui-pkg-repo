# 20260403-022131 — Add _DYNAMIC_DIR to set_env.sh

## Problem
Kube Shell failed because `$_DYNAMIC_DIR` was unset after sourcing `set_env.sh`.
`set_env.sh` only exported `_STACK_DIR`; `_DYNAMIC_DIR` was never defined.

## Fix

`set_env.sh` now derives and exports `_DYNAMIC_DIR` from `_STACK_DIR`:

```bash
export _DYNAMIC_DIR="${_DYNAMIC_DIR:-$(cd "$_STACK_DIR/../../../../k8s-recipes/config/tmp/dynamic" 2>/dev/null && pwd)}"
```

Derivation rationale: the existing `ansible_inventory_path` in `config/de-gui.yaml`
is `../../../../k8s-recipes/config/tmp/dynamic/ansible/terragrunt_lab_stack/hosts.yml`
(relative to `_STACK_DIR`), confirming that the dynamic dir is at
`$_STACK_DIR/../../../../k8s-recipes/config/tmp/dynamic`.

Resolves to: `$HOME/git/pwy-home-lab/deploy/k8s-recipes/config/tmp/dynamic`

A WARNING is printed if the path doesn't exist (directory not yet created).
Can be pre-set in the environment to override.
