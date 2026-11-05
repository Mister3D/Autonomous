#!/bin/bash
# Minimal XFCE: bottom panel only, no desktop icons.
set -euo pipefail

export DISPLAY="${DISPLAY:-:1}"

# Wait for xfconf / panel
for _ in $(seq 1 50); do
  if xfconf-query -c xfce4-panel -p /panels >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

# Single workspace — no multi-desktop
xfconf-query -c xfwm4 -p /general/workspace_count -n -t int -s 1 2>/dev/null \
  || xfconf-query -c xfwm4 -p /general/workspace_count -s 1
xfconf-query -c xfwm4 -p /general/workspace_names -n -a -t string -s "Desktop" 2>/dev/null || true
xfconf-query -c xfwm4 -p /general/scroll_workspaces -n -t bool -s false 2>/dev/null || true
xfconf-query -c xfwm4 -p /general/wrap_workspaces -n -t bool -s false 2>/dev/null || true

# Keep only panel 1. Drop bottom dock / panel 2+.
xfconf-query -c xfce4-panel -p /panels -n -a -t int -s 1 2>/dev/null \
  || xfconf-query -c xfce4-panel -p /panels -a -t int -s 1

# Panel at the bottom (p=8), thin, locked
xfconf-query -c xfce4-panel -p /panels/panel-1/position -n -t string -s "p=8;x=0;y=0" 2>/dev/null \
  || xfconf-query -c xfce4-panel -p /panels/panel-1/position -s "p=8;x=0;y=0" 2>/dev/null || true
xfconf-query -c xfce4-panel -p /panels/panel-1/size -n -t uint -s 28 2>/dev/null || true
xfconf-query -c xfce4-panel -p /panels/panel-1/length -n -t uint -s 100 2>/dev/null || true
xfconf-query -c xfce4-panel -p /panels/panel-1/position-locked -n -t bool -s true 2>/dev/null || true
xfconf-query -c xfce4-panel -p /panels/panel-1/autohide-behavior -n -t uint -s 0 2>/dev/null || true

# Plugin set without pager / window-menu dock clutter
xfconf-query -c xfce4-panel -p /panels/panel-1/plugin-ids -n -a \
  -t int -s 1 -t int -s 2 -t int -s 3 -t int -s 4 -t int -s 5 2>/dev/null || true

xfconf-query -c xfce4-panel -p /plugins/plugin-1 -n -t string -s applicationsmenu 2>/dev/null || true
xfconf-query -c xfce4-panel -p /plugins/plugin-2 -n -t string -s tasklist 2>/dev/null || true
xfconf-query -c xfce4-panel -p /plugins/plugin-3 -n -t string -s separator 2>/dev/null || true
xfconf-query -c xfce4-panel -p /plugins/plugin-4 -n -t string -s systray 2>/dev/null || true
xfconf-query -c xfce4-panel -p /plugins/plugin-5 -n -t string -s clock 2>/dev/null || true

# Hide leftover plugins that often live on a second bar
for id in 6 7 8 9 10 11 12 13 14 15 16 20 21 22; do
  xfconf-query -c xfce4-panel -p /plugins/plugin-$id -r 2>/dev/null || true
done

# Desktop: no icons at all (home / trash / removable / filesystem)
xfconf-query -c xfce4-desktop -p /desktop-icons/style -n -t int -s 0 2>/dev/null \
  || xfconf-query -c xfce4-desktop -p /desktop-icons/style -s 0 2>/dev/null || true
xfconf-query -c xfce4-desktop -p /desktop-icons/file-icons/show-filesystem -n -t bool -s false 2>/dev/null || true
xfconf-query -c xfce4-desktop -p /desktop-icons/file-icons/show-home -n -t bool -s false 2>/dev/null || true
xfconf-query -c xfce4-desktop -p /desktop-icons/file-icons/show-trash -n -t bool -s false 2>/dev/null || true
xfconf-query -c xfce4-desktop -p /desktop-icons/file-icons/show-removable -n -t bool -s false 2>/dev/null || true

# Clear Desktop folder shortcuts (Chrome .desktop, workspace symlink, etc.)
if [ -d "$HOME/Desktop" ]; then
  find "$HOME/Desktop" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
fi

# Reload panel so changes stick without full logout
if command -v xfce4-panel >/dev/null 2>&1; then
  xfce4-panel -r 2>/dev/null || true
fi

echo "XFCE minimized (1 workspace, bottom panel, no desktop icons)"
