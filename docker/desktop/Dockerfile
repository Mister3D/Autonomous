# Autonomous desktop: minimal XFCE + TigerVNC + noVNC + Chrome (WebGL spoof)
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    DISPLAY=:1 \
    VNC_PORT=5901 \
    NOVNC_PORT=6080 \
    HOME=/home/autonomous \
    USER=autonomous \
    BOT_CHROME_PORT=9222 \
    UNMASKED_VENDOR_WEBGL="Google Inc. (Intel)" \
    UNMASKED_RENDERER_WEBGL="ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg locales sudo \
    xfce4 xfce4-terminal dbus-x11 x11-xserver-utils \
    tigervnc-standalone-server tigervnc-common \
    python3 python3-numpy python3-websockets \
    fonts-liberation fonts-dejavu fonts-dejavu-core \
    fonts-noto-core fonts-noto-color-emoji fonts-noto-mono fonts-noto-ui-core \
    fonts-roboto fonts-open-sans fonts-lato fonts-freefont-ttf \
    fonts-crosextra-carlito fonts-crosextra-caladea fonts-droid-fallback \
    fonts-inconsolata fonts-opensymbol fonts-cantarell fontconfig \
    procps net-tools psmisc \
    nano vim-tiny less \
    && sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
    && sed -i 's/^# *fr_FR.UTF-8 UTF-8/fr_FR.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && curl -fsSL https://github.com/novnc/noVNC/archive/refs/tags/v1.5.0.tar.gz \
       | tar -xz -C /opt \
    && mv /opt/noVNC-1.5.0 /opt/novnc \
    && curl -fsSL https://github.com/novnc/websockify/archive/refs/tags/v0.12.0.tar.gz \
       | tar -xz -C /opt \
    && mv /opt/websockify-0.12.0 /opt/websockify \
    && ln -sf /opt/websockify /opt/novnc/utils/websockify \
    && wget -qO /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -f /tmp/chrome.deb \
    && (test -s /etc/machine-id || echo "0123456789abcdef0123456789abcdef" >/etc/machine-id) \
    && useradd -m -u 1000 -s /bin/bash autonomous \
    && echo "autonomous ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/autonomous \
    && mkdir -p /home/autonomous/.vnc /home/autonomous/Downloads /home/autonomous/workspace \
                 /home/autonomous/Desktop /home/autonomous/.config/autostart \
                 /usr/local/share/autonomous \
                 /etc/opt/chrome/policies/managed \
    && chown -R autonomous:autonomous /home/autonomous \
    && rm -rf /var/lib/apt/lists/*

# Keep real Chrome binary; wrap via bot-chrome
RUN if [ -e /usr/bin/google-chrome-stable ]; then \
      mv /usr/bin/google-chrome-stable /usr/bin/google-chrome-stable.real; \
    fi \
 && ln -sf /usr/local/bin/bot-chrome /usr/bin/google-chrome-stable \
 && ln -sf /usr/local/bin/bot-chrome /usr/bin/google-chrome

COPY xstartup /home/autonomous/.vnc/xstartup
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY minimize-xfce.sh /usr/local/bin/minimize-xfce.sh
COPY bot-chrome /usr/local/bin/bot-chrome
COPY maximize-window.py /usr/local/bin/maximize-window.py
COPY webgl-spoof-cdp.py /usr/local/bin/webgl-spoof-cdp.py
COPY webgl-spoof.js /usr/local/share/autonomous/webgl-spoof.js
COPY chrome-policy.json /etc/opt/chrome/policies/managed/autonomous.json
COPY google-chrome.desktop /usr/share/applications/google-chrome.desktop
COPY chrome-autostart.desktop /home/autonomous/.config/autostart/chrome.desktop

RUN chmod +x /home/autonomous/.vnc/xstartup \
             /usr/local/bin/entrypoint.sh \
             /usr/local/bin/minimize-xfce.sh \
             /usr/local/bin/bot-chrome \
             /usr/local/bin/maximize-window.py \
             /usr/local/bin/webgl-spoof-cdp.py \
 && ln -sf /usr/local/share/autonomous/webgl-spoof.js /usr/local/bin/webgl-spoof.js \
 && chown -R autonomous:autonomous /home/autonomous

USER autonomous
WORKDIR /home/autonomous

EXPOSE 5901 6080

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS http://127.0.0.1:6080/ || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
