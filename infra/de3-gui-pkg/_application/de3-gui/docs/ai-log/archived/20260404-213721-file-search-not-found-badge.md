# 20260404-213721 — File viewer "Not found" badge

## What changed

### New computed var: `file_search_not_found`

```python
@rx.var
def file_search_not_found(self) -> bool:
    """True when there is a non-empty search query, content to search, but zero matches."""
    if self.file_viewer_mode == "config_data":
        query = self.config_data_search_query
    else:
        query = self.unit_file_search_query
    return bool(query.strip()) and bool(self.hcl_content) and self.file_search_match_count == 0
```

Reads the mode-appropriate search query. Returns True only when all three
conditions hold: query has text, content is present, and `file_search_match_count == 0`.

### "Not found" badge in the search bar

Added a `rx.badge("Not found", color_scheme="red", variant="soft")` in the search
bar `rx.hstack`, placed between the search input and the case-sensitive button.
Shown only when `file_search_not_found` is True.
