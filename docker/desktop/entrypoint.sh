#!/bin/bash
set -euo pipefail

export USER="${USER:-autonomous}"
export HOME="${HOME:-/home/autonomous}"
export DISPLAY="${DISPLAY:-:1}"
export BOT_CHROME_PORT="${BOT_CHROME_PORT:-9222}"
# Persist Chrome profile on the host bind-mount (cookies / clearance survive recreate).
export BOT_CHROME_USER_DATA_DIR="${BOT_CHROME_USER_DATA_DIR:-$HOME/shared/.autonomous-chrome}"
# FR defaults — anti-bot services compare timezone/lang to IP geo (FR).
export TZ="${TZ:-Europe/Paris}"
export LANG="${LANG:-fr_FR.UTF-8}"
export LANGUAGE="${LANGUAGE:-fr_FR:fr:en_US:en}"
export LC_ALL="${LC_ALL:-$LANG}"
export UNMASKED_VENDOR_WEBGL="${UNMASKED_VENDOR_WEBGL:-Google Inc. (Intel)}"
export UNMASKED_RENDERER_WEBGL="${UNMASKED_RENDERER_WEBGL:-ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)}"

mkdir -p "$HOME/.vnc" "$HOME/Downloads" "$HOME/workspace" "$HOME/shared" "$HOME/Desktop" "$HOME/.config/autostart"
mkdir -p "$BOT_CHROME_USER_DATA_DIR"
# Keep Desktop empty (no folder icons / shortcuts cluttering the VNC view).
find "$HOME/Desktop" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
# Binaries are already +x in the image; non-root cannot chmod /usr/local/bin.
chmod +x "$HOME/.vnc/xstartup" 2>/dev/null || true
# Ensure Chrome autostart desktop entry exists (idempotent for old volumes).
if [ ! -f "$HOME/.config/autostart/chrome.desktop" ]; then
  cat >"$HOME/.config/autostart/chrome.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Google Chrome
Exec=/usr/local/bin/bot-chrome
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
fi

# Pre-start WebGL CDP spoof watcher (attaches when Chrome opens port 9222)
if ! pgrep -f "webgl-spoof-cdp.py" >/dev/null 2>&1; then
  nohup python3 /usr/local/bin/webgl-spoof-cdp.py --port "$BOT_CHROME_PORT" \
    >>"$HOME/.chrome-webgl-spoof.log" 2>&1 &
fi

# Clean stale locks
vncserver -kill "$DISPLAY" >/dev/null 2>&1 || true
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null || true

# VNC only on localhost inside the container; noVNC/websockify is the public face.
# SecurityTypes=None is acceptable: RFB is not published outside the container netns.
vncserver "$DISPLAY" \
  -geometry "${VNC_GEOMETRY:-1920x1200}" \
  -depth 24 \
  -localhost yes \
  -SecurityTypes None \
  -rfbport "${VNC_PORT:-5901}" \
  -xstartup "$HOME/.vnc/xstartup"

/opt/websockify/run \
  --web /opt/novnc \
  "0.0.0.0:${NOVNC_PORT:-6080}" \
  "127.0.0.1:${VNC_PORT:-5901}" &

echo "Autonomous desktop ready (VNC ${VNC_PORT:-5901}, noVNC ${NOVNC_PORT:-6080})"
exec tail -F "$HOME/.vnc"/*.log 2>/dev/null || exec sleep infinity
