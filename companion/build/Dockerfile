# Throwaway builder for the Autonomous companion (Linux + Windows binaries).
# Used by autonomous/services/companion_build.py; nothing is installed on the host.
FROM rust:1-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gcc-mingw-w64-x86-64 pkg-config \
      libgtk-3-dev libxdo-dev libayatana-appindicator3-dev \
 && rm -rf /var/lib/apt/lists/* \
 && rustup target add x86_64-pc-windows-gnu
ENV CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER=x86_64-w64-mingw32-gcc
WORKDIR /src
