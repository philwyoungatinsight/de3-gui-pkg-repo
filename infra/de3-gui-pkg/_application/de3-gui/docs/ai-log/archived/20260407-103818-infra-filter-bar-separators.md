# 20260407-103818 — Infra filter bar: separators between all controls

## Change

Added `_divider` vertical bar separators between every filter control in the
infra panel filter bar.

Before:
```
Packages ▾  Categories ▾  Providers ▾  [Regions ▾]  |  Envs ▾  Roles ▾  |  Search…
```

After:
```
Packages ▾  |  Categories ▾  |  Providers ▾  |  [Regions ▾]  |  Envs ▾  |  Roles ▾  |  Search…
```

One `_divider` added: after Packages, after Categories, after Providers, and
between Envs and Roles (the existing divider between Regions and Envs and the
one before Search were already there).
