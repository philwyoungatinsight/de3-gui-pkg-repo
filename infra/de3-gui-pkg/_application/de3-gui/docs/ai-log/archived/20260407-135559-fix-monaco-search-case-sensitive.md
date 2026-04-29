# 20260407-135559 — Fix: TypeError on file search in Monaco editor mode

## Problem

Opening a file and searching raised:

```
TypeError: _monaco_search_js() got an unexpected keyword argument 'case_sensitive'
```

All four call sites passed `case_sensitive=self.file_search_case_sensitive` as a
keyword argument, but the function signature had no such parameter.

## Fix

Added `case_sensitive: bool = False` to `_monaco_search_js` and wired it through
to the `model.findMatches()` call (4th argument, previously hardcoded `false`).
