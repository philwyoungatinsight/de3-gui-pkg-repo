# 20260403-023140 — Terminal backend: add macOS support (iTerm2, Terminal.app) + platform filtering

## Changes

### `_detect_terminal_backends()` — platform-aware detection
- Terminals split into three groups:
  - `_LINUX_TERMINALS`: gnome-terminal, xterm, konsole, tilix (probed via `shutil.which`, Linux only)
  - `_CROSS_PLATFORM_TERMINALS`: alacritty, kitty, wezterm (probed via `shutil.which` on all platforms)
  - `_MACOS_TERMINALS`: iTerm2 (checks `/Applications/iTerm.app`), Terminal.app (always present on macOS)
- `sys.platform == "darwin"` check ensures Linux-only terminals are never offered on macOS and
  macOS-native terminals are never offered on Linux.

### `_launch_native_terminal()` — new macOS backends
- **iTerm2**: `osascript` AppleScript — creates new window, writes `cd <cwd> && <cmd>` to session
- **Terminal.app**: `osascript` AppleScript — `do script "cd <cwd> && <cmd>"` in new window
- **WezTerm**: `wezterm start --cwd <cwd> -- bash --login [-c <cmd>]`
- Fixed xterm branch: removed duplicate args assignment (was setting args twice)
