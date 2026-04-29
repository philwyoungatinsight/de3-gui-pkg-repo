# Rename "category" → "package" in GUI

## Summary

The old `cat-hmc` / `cat-N` category grouping layer above packages was removed from the
infra directory structure. The GUI retained stale "Categories" terminology — the
depth-0 nodes are now packages (`proxmox-pkg`, `maas-pkg`, etc.), not categories.

## Changes

All occurrences of the "category" concept replaced with "package":

- `type: "category"` → `type: "package"` for depth-0 tree nodes in `_infer_type()` and the synthetic node builder
- State var: `category_filters` → `package_filters`
- Computed vars: `categories_with_visibility` → `packages_with_visibility`, removed duplicate `category_filter_active` (kept `package_filter_active` which already existed)
- Event handlers: `toggle_category` → `toggle_package`, `solo_category` → `solo_package`, `show_all_categories` → `show_all_packages`, `hide_all_categories` → `hide_all_packages`, `toggle_all_categories` → `toggle_all_packages`
- UI components: `_category_toggle_item` → `_package_toggle_item`, `_panel_categories` → `_panel_packages`
- Visible UI text: "Categories ▾" button → "Packages ▾", dropdown title "Categories" → "Packages", tooltips updated
- CSS comment updated
- Internal docstring/comment references updated
