# 20260404 — config_data mode: find node in package-specific YAML files

## Problem

Clicking a node in the folder view while in `config_data` mode searched only in
whatever config file was currently loaded (usually the base
`terragrunt_lab_stack.yaml`). Nodes whose `config_params` live in a package-specific
file (e.g. `aws-pkg/terragrunt_lab_stack_aws-pkg.yaml`) were never found.

## Fix

### New helper: `_find_config_file_for_node(provider, node_path) -> Path | None`

Iterates over all stack config files (`_find_stack_configs()`), parses each, and
returns the file whose `providers[provider].config_params` has the **longest prefix**
that matches `node_path` (exact match or prefix `+ "/"`). Falls back to the primary
config file. Handles the multi-file config layout introduced in the engine repo refactor.

### Updated config_data branch in `click_node`

Instead of the previous `if toggling_mode or not hcl_content: load base file` guard,
the branch now:
1. Extracts `provider` via `_selected_node_provider`.
2. Reconstructs the full provider-inclusive path (merged mode strips the provider
   segment from `path`; re-inserts it for the lookup).
3. Calls `_find_config_file_for_node(provider, full_path)`.
4. Loads the returned file into `hcl_content` / `hcl_file_path`.
5. Searches with `_config_data_node_search_js(path, provider, ...)`.

This also covers the mode-toggle case (previously needed a separate reload guard).
