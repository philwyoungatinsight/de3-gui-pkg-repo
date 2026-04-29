# YAML breadcrumb: unit test + scroll coordinate-space fix

## What changed

### New: `tests/test_yaml_breadcrumb.py`

13 unit tests covering `_build_yaml_line_paths`:

- Flat YAML: root key has empty path; nested keys show parent
- Multi-level nesting: deep keys show correct ancestor path
- Realistic `terragrunt_lab_stack` structure:
  - `"cat-1/gcp/us-central1/dev"` key line → `terragrunt_lab_stack.providers.gcp.config_params`
  - Value lines inside that key → `terragrunt_lab_stack.providers.gcp.config_params.cat-1/gcp/us-central1/dev`
  - aws/proxmox entries show their respective parent paths
  - Scalar key inside `gcp:` (not `config_params`) shows `terragrunt_lab_stack.providers.gcp`
- Blank lines inherit the previous path (forward-fill)
- HCL content (invalid YAML) returns all-empty
- Empty string returns single-element empty list

All 13 tests pass. The Python logic in `_build_yaml_line_paths` is correct.

### Bug fix: `_yaml_breadcrumb_install_js` — wrong coordinate space

**Root cause**: `updateFromScroll()` used `span.offsetTop <= scroller.scrollTop` in the
binary search. `span.offsetTop` is relative to the span's `offsetParent` (often `document.body`
or a distant ancestor), while `scroller.scrollTop` is local to the scroller div — completely
different coordinate systems, so the binary search found wrong lines.

**Fix**: Use `span.getBoundingClientRect().top <= scroller.getBoundingClientRect().top` — both
values are always viewport-relative, so the comparison is correct regardless of DOM structure.

The search-based breadcrumb update (`window._yamlCrumbUpdateFromMark`) was not affected by
this bug (it reads `dataset.yamlPath` directly from the span identified by DOM traversal).
