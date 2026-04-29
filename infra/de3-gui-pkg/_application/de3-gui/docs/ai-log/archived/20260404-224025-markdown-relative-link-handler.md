# 20260404-224025 — Handle relative links in rendered markdown file viewer

## Problem

Clicking a relative link in a README rendered by `rx.markdown()` (e.g.
`../common/README.md`) caused the browser to try to navigate the main page to a
bogus URL like `http://localhost:3000/../common/README.md`.

## Solution

Three pieces work together:

### 1. `_markdown_link_interceptor_js()`

Document-level click handler (installed once, uses event delegation):

- **Relative paths**: prevented from navigating; resolved against the current file's
  directory (read from `#hcl-file-path-src`) using `new URL(href, 'file://' + dir).pathname`;
  sent to Reflex via the React native-setter trick on `#markdown-link-input`.
- **`http://`/`https://` links**: prevented from navigating the main frame; opened in
  a new tab via `window.open(href, '_blank')`.
- **`#anchor` and `mailto:`/other schemes**: left to default browser behaviour.

Installed in `install_resizer` (runs once post-hydration; event delegation means no
re-install needed when markdown content changes).

### 2. Hidden DOM helpers in the file viewer

```python
rx.span(AppState.hcl_file_path, id="hcl-file-path-src", display="none")
rx.input(id="markdown-link-input", on_change=AppState.open_markdown_link, display="none")
```

`hcl-file-path-src` is kept in sync with `hcl_file_path` by Reflex's reactive
rendering — no extra state var or call_script needed.

`markdown-link-input` is an uncontrolled hidden input whose `on_change` fires
`open_markdown_link` when the JS interceptor triggers it with a resolved path (using
`Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set` + dispatching
an `input` event — the standard React controlled-input bypass technique).

### 3. `open_markdown_link(self, path: str)` handler

Resolves the path (`Path(path).resolve()`), checks `p.is_file()`, and calls
`open_abs_file_in_viewer` if the file exists. Non-existent paths are silently ignored.
