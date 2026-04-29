# 20260404 — Fix "inherited from" links in Unit Params panel

## Problem

Clicking an "inherited from" link in the Unit Params panel (top-right) did not open
the source config file. This was broken specifically in merged-tree mode.

### Root cause

`navigate_to_source` called `click_node(stripped_path)` where `stripped_path` was the
merged (provider-stripped) node path (e.g. `cat-hmc/pwy-homelab`). Problems:

1. **Wrong search target**: the YAML config_params key is provider-inclusive
   (e.g. `cat-hmc/proxmox/pwy-homelab`). Searching for the stripped path produced no
   match or landed on the wrong line.
2. **Wrong file**: after the engine repo refactor, config_params may live in a
   per-package YAML file (e.g. `aws-pkg/terragrunt_lab_stack_aws-pkg.yaml`), not the
   base `terragrunt_lab_stack.yaml`. The old code always showed the base file.

## Fix

### New helper: `_find_source_config_file(provider, config_key) -> Path | None`

Iterates over all stack config files (`_find_stack_configs()`), parses each, and
returns the first file whose `providers[provider].config_params` contains `config_key`.
Falls back to the primary config file if no match is found.

### Rewritten: `navigate_to_source(full_path)`

`full_path` is always provider-inclusive (e.g. `cat-hmc/proxmox/pwy-homelab`).

New behaviour:
1. Selects the ancestor node in the tree (strips provider segment in merged mode, as
   before — this only updates `selected_node_path`, does NOT call `click_node`).
2. Extracts `provider = parts[1]` from the full_path.
3. Calls `_find_source_config_file(provider, full_path)` to find the right YAML.
4. Loads that file, sets `file_viewer_mode = "config_data"`, and searches using the
   **full provider-inclusive path** via `_config_data_node_search_js`.
