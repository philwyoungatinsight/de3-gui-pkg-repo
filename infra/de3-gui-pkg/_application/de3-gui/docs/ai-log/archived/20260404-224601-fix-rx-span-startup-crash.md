# 20260404-224601 — Fix startup crash: rx.span → rx.box

`rx.span` is not a valid component in Reflex 0.8.27
(`AttributeError: No reflex attribute span`).

The hidden `hcl-file-path-src` element added for the markdown link
interceptor was changed from `rx.span(...)` to `rx.box(...)`, which
renders as a `<div>` but works identically for the purpose of exposing
`hcl_file_path` to JavaScript.
