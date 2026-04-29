# HCL Source Link Feature and Unit Test

## Changes

### HCL source link in file viewer
- `source = "..."` lines in the file viewer are now rendered as clickable links
- `hcl_parsed_lines` computed var splits each line with a regex (`_SOURCE_RE`) to identify source lines
- Source lines rendered with `prefix` + clickable link + `suffix` inline spans
- Introduced `_HCL_FONT`, `_HCL_LINE_STYLE` (block), `_HCL_INLINE_STYLE` (inline) style dicts
  to fix rendering where inline sub-spans had accidentally been given `display:block`

### `open_source_link` handler
- Clicking a source link calls `open_source_link(source_val)`
- Strips all `${...}` interpolation prefixes (not just `${get_terragrunt_dir()}`)
- Replaces `//` separator with `/`
- Resolution order:
  1. Try `_STACK_DIR/_modules/<sub_path>` (for `${include.root.locals.modules_dir}/...`)
  2. Fall back to path relative to the currently viewed file's directory
- Skips remote sources (`git::`, `https://`, etc.)
- Loads the first `.tf` / `.hcl` file found in the resolved directory

### Unit test: `test-source-link`
- New Playwright check `check_file_viewer_source_link(page, args)` in `tests/browser_test.py`
  - Clicks the named tree node, waits for `id="hcl-source-link"`, clicks it
  - Asserts the expected module name appears in the file viewer content
- Registered in `CHECK_MAP` as `"file_viewer_source_link"`
- New task file `tests/unit-tests/test-source-link.yml`
- Added `test-source-link` entry to `tests/playbooks/unit-tests.yml`
