# Fix: YAML breadcrumb using pre.children instead of textContent

## Root cause

Each line in the file viewer is rendered as `<span style="display:block">` (via `_render_hcl_line` →
`_HCL_LINE_STYLE`). `pre.textContent` concatenates all spans without any `\n` separator, so
`textContent.split('\n')` gave one giant string and line index math was completely wrong.

## Fix: `_yaml_breadcrumb_install_js()`

- Uses `pre.children[i].textContent` to read each line individually — correct for block-span structure
- Scroll-based line detection: binary search on `spans[i].offsetTop <= scroller.scrollTop`
- Exposes `window._yamlCrumbUpdateFromMark(markEl)` — walks up from the `<mark>` to its parent
  line span via `previousElementSibling` counting, then calls `getYamlPath(lineIdx)`
- Path format: dot-separated (`.`) as per user requirement

## Fix: search JS calls `window._yamlCrumbUpdateFromMark`

After each search navigation, both `_pre_search_js` and `_config_data_node_search_js` now call:
```javascript
if (window._yamlCrumbUpdateFromMark) window._yamlCrumbUpdateFromMark(marks[idx]);
```
This updates the breadcrumb to the **active match position** immediately on search, not just on scroll.
