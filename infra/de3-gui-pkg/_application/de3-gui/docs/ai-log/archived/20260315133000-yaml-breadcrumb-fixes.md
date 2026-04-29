# YAML breadcrumb: block-scalar recursive parsing + unit-file hiding + lazy DOM

## Bug fixes

### 1. Block scalar content lines showed wrong path (`ssh_pwauth`, `qemu-guest-agent`)

**Root cause:** `guest_agent_cloud_init: |` is a YAML block scalar. PyYAML
represents the entire multi-line string as a single `ScalarNode`. The previous
code marked all content lines with `parent_path` (the scalar's own path), but
`packages:`, `runcmd:`, `- qemu-guest-agent`, etc. inside the block are
themselves YAML — so `packages` showed the same path as `ssh_pwauth` instead of
`…guest_agent_cloud_init.packages`.

**Fix:** `_build_yaml_line_paths` now accepts an `offset: int = 0` parameter.
For block scalars (`node.style in ('|', '>')`), it attempts to parse
`node.value` recursively with `yaml.compose()`. If the sub-content is a valid
non-scalar YAML document, it calls `visit(sub_root, parent_path, content_start)`
where `content_start = absolute_line_of_scalar + 1`. This maps sub-content
relative line numbers to absolute file lines. Falls back to flat marking if
sub-content doesn't parse as YAML.

Results for `guest_agent_cloud_init: |`:
- `guest_agent_cloud_init:` line → `…snippets/guest-agent` ✓
- `ssh_pwauth:` → `…snippets/guest-agent.guest_agent_cloud_init` ✓
- `packages:` → `…snippets/guest-agent.guest_agent_cloud_init` ✓
- `- qemu-guest-agent` → `…snippets/guest-agent.guest_agent_cloud_init.packages` ✓
- `runcmd:` → `…snippets/guest-agent.guest_agent_cloud_init` ✓
- `- systemctl …` → `…snippets/guest-agent.guest_agent_cloud_init.runcmd` ✓

### 2. Breadcrumb bar shown in unit-file mode (wrong — unit files are HCL, not YAML)

Changed the `display` condition on `#yaml-breadcrumb` from:
```python
display=rx.cond(AppState.hcl_content != "", "block", "none")
```
to:
```python
display=rx.cond(
    (AppState.hcl_content != "") & (AppState.file_viewer_mode == "config_data"),
    "block", "none",
)
```

### 3. Breadcrumb `window._yamlCrumbUpdateFromMark` never defined when content empty at startup

`_yaml_breadcrumb_install_js` had an early `if(!pre)return;` that prevented
`window._yamlCrumbUpdateFromMark` from being defined when `#file-viewer-pre`
didn't exist yet (hcl_content empty at install time).

**Fix:** removed the early return; all DOM lookups (`getElementById`) now happen
lazily inside each function at call time. `window._yamlCrumbUpdateFromMark` and
`window._yamlCrumbMouseupFn` are always defined after `install_resizer` fires,
regardless of whether the pre element exists.

## Tests added / updated (`tests/test_yaml_breadcrumb.py`)

- Updated the verbatim copy of `_build_yaml_line_paths` with `offset` param and
  block-scalar recursive parsing
- Added 7 new block-scalar tests: key line, ssh_pwauth, packages key, sequence
  item (qemu-guest-agent), runcmd key, runcmd sequence item, sibling after scalar
- Total: 20 tests, all passing
