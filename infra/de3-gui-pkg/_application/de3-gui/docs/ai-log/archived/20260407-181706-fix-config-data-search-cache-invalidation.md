# 20260407-181706 — Fix: config-data "Not found" badge — cache not invalidated after React re-render

## Problem

Clicking a node in config_data mode showed "Not found" even though the text existed in
the file. The previous fix (deferring search to `post_mode_switch_search`) did not resolve
it.

Root cause: `_config_data_node_search_js` guards mark rebuilding behind:

```js
if(pre.dataset.searchQ !== ql) { /* rebuild marks */ }
```

After React re-renders with new `hcl_content`, all `<mark data-fs>` elements are destroyed
(the DOM children are replaced). However `pre.dataset.searchQ` is an attribute on the `pre`
element itself, which React does not recreate — so it retains the old cache key from the
previous file.

If the next node's search query happens to be the same string (e.g. navigating between two
nodes with a path segment like `kubeconfig`), `ql === pre.dataset.searchQ` → rebuild is
skipped → `querySelectorAll('mark[data-fs]')` returns 0 → function returns `undefined` →
`set_file_search_match_count` sets count to 0 → "Not found" badge.

The arrow buttons (`file_search_next`/`prev`) use `_pre_search_js` which has a different
cache-key format (`qn + '\x00' + caseflag`) — it never matches `ql` stored by
`_config_data_node_search_js`, so it always rebuilds and finds matches correctly.

## Fix

Removed the cache guard in `_config_data_node_search_js`. Marks are now always rebuilt
unconditionally. The function is only called once per node navigation (not on every
keystroke), so there is no performance concern:

```js
// Before:
if(pre.dataset.searchQ !== ql) {
  pre.dataset.searchQ = ql;
  /* rebuild marks */
}

// After:
pre.dataset.searchQ = '';   // clear cache key to prevent stale state
/* rebuild marks unconditionally */
```

The deferred-search fix (`post_mode_switch_search`) from the previous session remains in
place — it ensures React has committed the new content before the JS runs.
