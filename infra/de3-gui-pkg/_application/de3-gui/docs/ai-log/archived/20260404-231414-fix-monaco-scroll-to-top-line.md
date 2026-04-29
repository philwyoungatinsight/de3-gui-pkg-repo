# 20260404-231414 — Fix Monaco scroll: setScrollPosition instead of revealLineAtTop

## Problem

`revealLineAtTop` does not exist in the Monaco editor API — caused a
`TypeError: ... revealLineAtTop is not a function` runtime exception.

## Fix

Use `getTopForLineNumber(ln)` to get the pixel offset of the target line,
then `setScrollPosition({scrollTop: px}, 1)` to pin it to the top:

```javascript
var e = monaco.editor.getEditors()[0];
e.setScrollPosition({scrollTop: e.getTopForLineNumber(ln)}, 1);
```

This is the correct Monaco idiom for "scroll line N to the top of the viewport".
