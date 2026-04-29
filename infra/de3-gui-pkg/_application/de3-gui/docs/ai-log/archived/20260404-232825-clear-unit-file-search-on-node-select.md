# 20260404-232825 — Clear unit file search query when loading a unit file

## Problem

When selecting an infra node with the file viewer in `unit_file` mode,
`select_node` and `click_node` both set `unit_file_search_query = path`
and immediately ran a search to highlight/scroll to the node path in the HCL.
This caused the search bar to be populated with the node path every time a
unit file was opened, which was surprising and made it hard to start a fresh
search.

## Fix

In both `select_node` (unit_file branch) and `click_node` (unit_file else branch):
- `self.unit_file_search_query = ""` (was `= path`)
- Return/yield `rx.call_script(_CLEAR_CRUMB_JS)` instead of running a search
  (the YAML breadcrumb still needs to be cleared; no search marks exist since
  the file content just re-rendered fresh).
