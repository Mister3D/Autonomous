#!/bin/sh
# Autonomous installer.
#
#   curl -fsSL https://raw.githubusercontent.com/Mister3D/Autonomous/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- --yes --no-desk
#
# Re-running is safe: it updates the checkout and keeps your data (and any .env).
set -eu

REPO_URL="${AUTONOMOUS_REPO_URL:-https://github.com/Mister3D/Autonomous}"
VERSION="${AUTONOMOUS_VERSION:-main}"
PREFIX="${AUTONOMOUS_PREFIX:-$HOME/autonomous}"
DATA_HOME="${AUTONOMOUS_HOME:-}"
PORT="${AUTONOMOUS_PORT:-8787}"
ASSUME_YES=0
NO_DESK=0
NO_SERVICE=0
PKG=""
SUDO=""
OS_ID=""
ARCH=""

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
	cat <<USAGE
Usage: install.sh [options]

  --yes            answer yes to every question (non-interactive)
  --prefix DIR     install directory (default: \$HOME/autonomous)
  --home DIR       data directory, AUTONOMOUS_HOME (default: PREFIX/data)
  --version REF    git branch or tag to install (default: main)
  --port N         port for the systemd service (default: 8787)
  --no-desk        do not offer to build the desktop Docker image
  --no-service     do not offer to install a systemd service
  -h, --help       show this help

Environment: AUTONOMOUS_REPO_URL (default $REPO_URL),
AUTONOMOUS_PASSWORD (login password for non-interactive installs).
USAGE
}

# Ask a yes/no question on the terminal, even when piped from curl.
confirm() {
	if [ "$ASSUME_YES" = 1 ]; then
		return 0
	fi
	if ! [ -r /dev/tty ]; then
		warn "no terminal to ask: '$1' -> no (use --yes)"
		return 1
	fi
	printf '%s [y/N] ' "$1" >/dev/tty
	read -r answer </dev/tty || answer=""
	case "$answer" in
	[yY] | [yY][eE][sS]) return 0 ;;
	*) return 1 ;;
	esac
}

parse_args() {
	while [ $# -gt 0 ]; do
		case "$1" in
		--yes | -y) ASSUME_YES=1 ;;
		--prefix) [ $# -ge 2 ] || die "--prefix needs a value"; PREFIX="$2"; shift ;;
		--prefix=*) PREFIX="${1#*=}" ;;
		--home) [ $# -ge 2 ] || die "--home needs a value"; DATA_HOME="$2"; shift ;;
		--home=*) DATA_HOME="${1#*=}" ;;
		--version) [ $# -ge 2 ] || die "--version needs a value"; VERSION="$2"; shift ;;
		--version=*) VERSION="${1#*=}" ;;
		--port) [ $# -ge 2 ] || die "--port needs a value"; PORT="$2"; shift ;;
		--port=*) PORT="${1#*=}" ;;
		--no-desk) NO_DESK=1 ;;
		--no-service) NO_SERVICE=1 ;;
		-h | --help) usage; exit 0 ;;
		*) die "unknown option: $1 (see --help)" ;;
		esac
		shift
	done
	case "$PORT" in
	'' | *[!0-9]*) die "--port must be a number" ;;
	esac
	[ -n "$DATA_HOME" ] || DATA_HOME="$PREFIX/data"
}

detect_os() {
	ARCH="$(uname -m)"
	[ "$(uname -s)" = Linux ] || die "only Linux is supported by this installer"
	if [ -r /etc/os-release ]; then
		# shellcheck disable=SC1091
		OS_ID="$(. /etc/os-release && printf '%s %s' "${ID:-}" "${ID_LIKE:-}")"
	fi
	if have apt-get; then
		PKG=apt
	elif have dnf; then
		PKG=dnf
		warn "dnf support is best effort"
	else
		warn "no apt-get or dnf: missing packages must be installed by hand"
	fi
	if [ "$(id -u)" != 0 ]; then
		if have sudo; then SUDO=sudo; else warn "not root and no sudo: package installs will fail"; fi
	fi
	info "System: ${OS_ID:-unknown} ($ARCH), package manager: ${PKG:-none}"
}

APT_UPDATED=0
pkg_install() {
	case "$PKG" in
	apt)
		if [ "$APT_UPDATED" = 0 ]; then
			$SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -q
			APT_UPDATED=1
		fi
		$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$@"
		;;
	dnf) $SUDO dnf install -y "$@" ;;
	*) die "cannot install $* automatically; install it and re-run" ;;
	esac
}

# version_ge "3.13.1" "3.11" -> true
version_ge() {
	[ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" = "$2" ]
}

need() {
	# need <what> <check-cmd> <install-function>
	what="$1"; check="$2"; installer="$3"
	if eval "$check"; then
		info "ok: $what"
		return 0
	fi
	if confirm "$what is missing. Install it now?"; then
		"$installer"
		eval "$check" || die "$what is still missing after install"
		info "installed: $what"
	else
		die "$what is required"
	fi
}

check_python() {
	have python3 || return 1
	v="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
	version_ge "$v" 3.11 || { warn "python3 $v < 3.11"; return 1; }
	python3 -c 'import venv, ensurepip' >/dev/null 2>&1
}
install_python() {
	case "$PKG" in
	apt) pkg_install python3 python3-venv python3-pip ;;
	*) pkg_install python3 python3-pip ;;
	esac
}

check_git() { have git; }
install_git() { pkg_install git; }

check_curl() { have curl; }
install_curl() { pkg_install curl ca-certificates; }

# Pi needs Node >= 22.19; the frontend needs >= 20.
check_node() {
	have node && have npm || return 1
	v="$(node -p 'process.versions.node')"
	version_ge "$v" 22.19 || { warn "node $v < 22.19"; return 1; }
}
install_node() {
	case "$PKG" in
	apt)
		pkg_install ca-certificates curl gnupg
		curl -fsSL https://deb.nodesource.com/setup_24.x | $SUDO bash -
		pkg_install nodejs
		;;
	dnf) pkg_install nodejs npm ;;
	*) die "install Node.js >= 22.19 by hand" ;;
	esac
}

check_docker() { have docker && docker info >/dev/null 2>&1; }
install_docker() {
	if ! have docker; then
		info "Installing Docker with https://get.docker.com"
		tmp="$(mktemp)"
		curl -fsSL https://get.docker.com -o "$tmp"
		$SUDO sh "$tmp"
		rm -f "$tmp"
	fi
	if have systemctl; then
		$SUDO systemctl enable --now docker || true
	fi
}

pi_path() {
	PATH="$HOME/.local/bin:$HOME/.pi/agent/bin:$PATH"
	export PATH
}
check_pi() { pi_path; have pi; }
install_pi() {
	# Same package the Pi extensions import (autonomous/pi_extensions/*.ts).
	if have npm; then
		npm install -g --ignore-scripts @earendil-works/pi-coding-agent \
			|| $SUDO npm install -g --ignore-scripts @earendil-works/pi-coding-agent
	else
		curl -fsSL https://pi.dev/install.sh | sh
	fi
	pi_path
}

check_prereqs() {
	need curl check_curl install_curl
	need git check_git install_git
	need "python3 >= 3.11 with venv" check_python install_python
	need "node >= 22.19 and npm" check_node install_node
	need pi check_pi install_pi
	if check_docker; then
		info "ok: docker"
	elif confirm "Docker (with a running daemon) is missing. It is needed for the bots' desktops. Install it now via get.docker.com?"; then
		install_docker
		check_docker || warn "docker installed but the daemon is not reachable (restart your session or start dockerd)"
	else
		warn "continuing without Docker: desktops will not work"
	fi
	if have cargo || [ -x "$HOME/.cargo/bin/cargo" ]; then
		info "ok: cargo (the companion will be built when Autonomous starts)"
	else
		info "optional: Rust is not installed; the companion download page will explain how to add it"
		info "          (curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh)"
	fi
}

fetch_source() {
	if [ -d "$PREFIX/.git" ]; then
		info "Updating $PREFIX"
		git -C "$PREFIX" fetch --tags origin
		if git -C "$PREFIX" diff --quiet && git -C "$PREFIX" diff --cached --quiet; then
			git -C "$PREFIX" checkout -q "$VERSION"
			git -C "$PREFIX" merge -q --ff-only "origin/$VERSION" 2>/dev/null || true
		else
			warn "$PREFIX has local changes: not updating the checkout"
		fi
	elif [ -e "$PREFIX" ] && [ -n "$(ls -A "$PREFIX" 2>/dev/null)" ]; then
		die "$PREFIX exists and is not a git checkout"
	else
		info "Cloning $REPO_URL ($VERSION) into $PREFIX"
		git clone -q --branch "$VERSION" "$REPO_URL" "$PREFIX"
	fi
}

install_app() {
	cd "$PREFIX"
	if [ ! -x .venv/bin/python ]; then
		info "Creating virtualenv"
		python3 -m venv .venv
	fi
	info "Building the web interface"
	(cd frontend && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent)
	info "Installing the Python package"
	.venv/bin/pip install -q --upgrade pip
	# Editable: the app reads repo files at runtime (Pi extensions, companion sources).
	.venv/bin/pip install -q -e .
}

setup_env() {
	cd "$PREFIX"
	# Configuration is done in the web UI (setup page). An existing .env is kept
	# and still loaded by the service as an advanced override; none is created.
	[ -f .env ] && info "Keeping existing .env (advanced overrides)"
	mkdir -p "$DATA_HOME"
	chmod 700 "$DATA_HOME"
}

read_password() {
	if [ -n "${AUTONOMOUS_PASSWORD:-}" ]; then
		PASSWORD="$AUTONOMOUS_PASSWORD"
		return 0
	fi
	if [ -r /dev/tty ] && [ "$ASSUME_YES" = 0 ]; then
		while :; do
			printf 'Choose a login password: ' >/dev/tty
			stty -echo </dev/tty 2>/dev/null || true
			read -r PASSWORD </dev/tty || PASSWORD=""
			stty echo </dev/tty 2>/dev/null || true
			printf '\n' >/dev/tty
			[ ${#PASSWORD} -ge 8 ] && return 0
			printf 'At least 8 characters, please.\n' >/dev/tty
		done
	fi
	# Non-interactive: generate one and store it next to the data (mode 600).
	PASSWORD="$(od -An -N18 -tx1 /dev/urandom | tr -d ' \n')"
	umask 077
	printf '%s\n' "$PASSWORD" >"$DATA_HOME/initial-password"
	GENERATED_PASSWORD_FILE="$DATA_HOME/initial-password"
	GENERATED_PASSWORD="$PASSWORD"
}

init_app() {
	if [ -f "$DATA_HOME/password.hash" ]; then
		info "Already initialised ($DATA_HOME)"
		return 0
	fi
	PASSWORD=""
	GENERATED_PASSWORD_FILE=""
	GENERATED_PASSWORD=""
	read_password
	info "Initialising $DATA_HOME"
	init_args=(init --password "$PASSWORD")
	# Generated password → force change on first web login and drop plaintext ASAP.
	if [ -n "${GENERATED_PASSWORD_FILE:-}" ]; then
		init_args+=(--must-change-password)
	fi
	AUTONOMOUS_HOME="$DATA_HOME" "$PREFIX/.venv/bin/autonomous" "${init_args[@]}" >/dev/null
	PASSWORD=""
}

build_desk() {
	[ "$NO_DESK" = 0 ] || return 0
	check_docker || { warn "skipping the desktop image: Docker is not available"; return 0; }
	if confirm "Build the desktop image now (autonomous-desktop:latest, several GB, ~10 min)?"; then
		docker build -t autonomous-desktop:latest "$PREFIX/docker/desktop"
	fi
}

install_service() {
	[ "$NO_SERVICE" = 0 ] || return 0
	have systemctl && [ -d /run/systemd/system ] || { info "no systemd: skipping the service"; return 0; }
	confirm "Install a systemd service (autonomous.service, port $PORT)?" || return 0
	unit=/etc/systemd/system/autonomous.service
	tmp="$(mktemp)"
	cat >"$tmp" <<UNIT
[Unit]
Description=Autonomous bot hub
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$PREFIX
Environment=AUTONOMOUS_HOME=$DATA_HOME
Environment=PATH=$HOME/.local/bin:$HOME/.pi/agent/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=-$PREFIX/.env
ExecStart=$PREFIX/.venv/bin/autonomous serve --host 127.0.0.1 --port $PORT
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
	$SUDO install -m 644 "$tmp" "$unit"
	rm -f "$tmp"
	$SUDO systemctl daemon-reload
	$SUDO systemctl enable --now autonomous.service
	SERVICE_INSTALLED=1
}

next_steps() {
	cat <<EOT

Autonomous is installed in $PREFIX (data: $DATA_HOME).

Next steps:
EOT
	if [ "${SERVICE_INSTALLED:-0}" = 1 ]; then
		echo "  1. Open http://127.0.0.1:$PORT/ and log in  (service: systemctl status autonomous)"
	else
		echo "  1. Start it:  cd $PREFIX && AUTONOMOUS_HOME=$DATA_HOME .venv/bin/autonomous serve --port $PORT"
		echo "     then open http://127.0.0.1:$PORT/"
	fi
	if [ -n "${GENERATED_PASSWORD:-}" ]; then
		echo "  2. Temporary login password (you will be forced to change it on first login):"
		echo "       $GENERATED_PASSWORD"
		echo "     Also written to: $GENERATED_PASSWORD_FILE (removed after first login)"
	elif [ -n "${GENERATED_PASSWORD_FILE:-}" ] && [ -r "$GENERATED_PASSWORD_FILE" ]; then
		echo "  2. Temporary login password (you will be forced to change it on first login):"
		echo "       $(cat "$GENERATED_PASSWORD_FILE")"
		echo "     Also written to: $GENERATED_PASSWORD_FILE (removed after first login)"
	fi
	echo "  Then follow the setup page: it lists what is left (LLM, desktop image, optional"
	echo "  grounding and companion) with Configure links and Install/Build buttons."
}

main() {
	parse_args "$@"
	detect_os
	check_prereqs
	fetch_source
	install_app
	setup_env
	init_app
	build_desk
	install_service
	next_steps
}

main "$@"
