# 20260413120842 — Fix: wave/region/env/package/role filters not persisted

## Root cause

`_save_current_config()` only included `providers` in its snapshot dict — the five
filter groups (`wave_filters`, `region_filters`, `env_filters`, `package_filters`,
`selected_roles`) were never written to `state/current.yaml`.

Additionally, none of the filter toggle/solo/show/hide event handlers called
`_save_current_config()`, so even if the save dict had included them the state would
never have been written on user interaction.

On load, `on_load` restored only `provider_filters` from state; all other filters
reinitialised to all-visible defaults on every page load.

## Fix

### `_save_current_config`
Added the five filter groups to the snapshot dict:
```python
"wave_filters":    {k: v for k, v in self.wave_filters.items()},
"region_filters":  {k: v for k, v in self.region_filters.items()},
"env_filters":     {k: v for k, v in self.env_filters.items()},
"package_filters": {k: v for k, v in self.package_filters.items()},
"selected_roles":  list(self.selected_roles),
```

### Filter event handlers
Added `self._save_current_config()` to all 24 filter mutation handlers:
`toggle_wave`, `solo_wave`, `show_all_waves`, `hide_all_waves`, `toggle_all_waves`,
`toggle_region`, `solo_region`, `show_all_regions`, `hide_all_regions`, `toggle_all_regions`,
`toggle_env`, `solo_env`, `show_all_envs`, `hide_all_envs`, `toggle_all_envs`,
`toggle_package`, `solo_package`, `show_all_packages`, `hide_all_packages`, `toggle_all_packages`,
`toggle_role`, `clear_role_filter`, `toggle_all_roles`, `solo_role`.

### `on_load` — saved filter restore
After initialising filters from cache (lines after `_build_initial_wave_filters()`),
merge saved state using a "known keys only, new keys default to True" pattern:

```python
_sv_wave = saved_menu.get("wave_filters", {})
if _sv_wave:
    self.wave_filters = {k: _sv_wave.get(k, True) for k in self.wave_filters}
# … same for region_filters, env_filters, package_filters …
_sv_roles = saved_menu.get("selected_roles", [])
if _sv_roles:
    self.selected_roles = [r for r in _sv_roles if r in self.available_roles]
```

This ensures newly-added waves/regions/envs/packages that were not present when state
was saved default to visible, while previously hidden entries stay hidden.

## Behaviour after fix

| Action | Before | After |
|---|---|---|
| Hide a wave, reload | Wave reappears (all visible) | Wave stays hidden ✓ |
| Solo a package, reload | All packages visible again | Solo state restored ✓ |
| Hide a region, reload | Region reappears | Region stays hidden ✓ |
| Set role filter, reload | Roles cleared | Role filter restored ✓ |
| Add a new wave to config, reload | n/a (didn't persist) | New wave visible by default ✓ |
