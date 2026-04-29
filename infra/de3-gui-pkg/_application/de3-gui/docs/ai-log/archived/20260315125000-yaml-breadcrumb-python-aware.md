# YAML breadcrumb: Python-parsed paths via data-yaml-path attribute

## Root cause of wrong paths

Client-side YAML parsing from DOM text was unreliable:
- Indentation counts from `textContent` are wrong when marks (`<mark data-fs>`) are injected
  (mark elements add wrapper nodes that change character offsets)
- Regex key extraction misses many YAML syntax variants
- No awareness of multiline values, anchors, etc.

## New approach: server-side YAML parsing

### `_build_yaml_line_paths(content: str) -> list[str]`
New module-level function using `yaml.compose()` (PyYAML's node tree with line marks):

- Walks the node tree depth-first
- For each mapping key at line L inside a mapping at path P: `result[L] = P` (show the
  PARENT path — so searching for `cat-1/gcp/us-central1/dev` shows `..providers.gcp.config_params`)
- For the value node at line L with path P.key: `result[L] = P.key`
- Forward-fills blank/comment/continuation lines from the previous event
- Returns all-empty on parse error (HCL files, invalid YAML)

### `hcl_parsed_lines` — `yaml_path` added to each line dict
The existing `@rx.var` now calls `_build_yaml_line_paths(self.hcl_content)` and adds
`yaml_path` to each line dict alongside `text`, `is_source`, etc.

### `_render_hcl_line` — `data-yaml-path` attribute on each span
Both the source-line and normal-line spans now include `data_yaml_path=line["yaml_path"]`,
rendered as `data-yaml-path="..."` in the DOM.

### `_yaml_breadcrumb_install_js()` — no more client-side parsing
Simplified to just read `span.dataset.yamlPath`:
- `pathFromSpan(span)` → `span.dataset.yamlPath || ''`
- `window._yamlCrumbUpdateFromMark(mark)` → walks up to line span, reads its `dataset.yamlPath`
- Scroll listener: binary-searches spans by `offsetTop`, reads `dataset.yamlPath`

Zero JS YAML parsing. Paths are always correct because they come from PyYAML.
