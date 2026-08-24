#!/usr/bin/env bash
# Orchestrator installer
#
# curl -fsSL https://raw.githubusercontent.com/cornellev/orchestrator/main/install.sh | bash
# curl -fsSL https://raw.githubusercontent.com/cornellev/orchestrator/main/install.sh | bash -s -- server
# curl -fsSL https://raw.githubusercontent.com/cornellev/orchestrator/main/install.sh | bash -s -- client:js
#
# Environment:
#   ORCHESTRATOR_REPO    Git clone URL (default: https://github.com/cornellev/orchestrator.git)
#   ORCHESTRATOR_BRANCH  Git branch (default: main)
#   ORCHESTRATOR_DIR     Install directory (default: ./orchestrator)
#
# Targets:
#   server              Python server only (default for curl install)
#   client              All clients (python, js, rust)
#   client:python       Python client
#   client:js           JavaScript/Node client
#   client:rust         Rust workspace
#   all                 Server + all clients (default when run from a local checkout)
#
# Options:
#   --dir PATH          Install directory (same as ORCHESTRATOR_DIR)
#   --branch BRANCH     Git branch (same as ORCHESTRATOR_BRANCH)
#   --venv PATH         Python virtualenv directory (default: <install-dir>/.venv)
#   --no-venv           Install Python packages with pip --user
#   --skip-rust         Skip Rust client when installing client/all
#   --skip-node         Skip Node client when installing client/all
#   --no-clone          Use the current directory; do not clone or update
#   -h, --help          Show help

set -euo pipefail

REPO_URL="${ORCHESTRATOR_REPO:-https://github.com/cornellev/orchestrator.git}"
BRANCH="${ORCHESTRATOR_BRANCH:-main}"
INSTALL_DIR="${ORCHESTRATOR_DIR:-./orchestrator}"
TARGET=""
USE_VENV=1
VENV_DIR=""
SKIP_RUST=0
SKIP_NODE=0
NO_CLONE=0
LOCAL_CHECKOUT=0

if [[ -t 1 ]] && [[ "${NO_COLOR:-}" == "" ]] && [[ "${TERM:-}" != "dumb" ]]; then
	BOLD=$'\033[1m'
	DIM=$'\033[2m'
	RESET=$'\033[0m'
	RED=$'\033[31m'
	GREEN=$'\033[32m'
	YELLOW=$'\033[33m'
	CYAN=$'\033[36m'
else
	BOLD=""; DIM=""; RESET=""; RED=""; GREEN=""; YELLOW=""; CYAN=""
fi

ok()   { printf ' %s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf ' %s!%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf ' %s✗%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }
step() { printf '\n%s▸%s %s%s%s\n' "$CYAN" "$RESET" "$BOLD" "$*" "$RESET"; }
info() { printf '   %s\n' "$*"; }

usage() {
	cat <<'EOF'
Orchestrator installer

Quick install:
  curl -fsSL https://raw.githubusercontent.com/cornellev/orchestrator/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/cornellev/orchestrator/main/install.sh | bash -s -- server
  curl -fsSL https://raw.githubusercontent.com/cornellev/orchestrator/main/install.sh | bash -s -- client:js

Targets:
  server              Python server only (default for curl install)
  client              All clients (python, js, rust)
  client:python       Python client
  client:js           JavaScript/Node client
  client:rust         Rust workspace
  all                 Server + all clients (default when run from a local checkout)

Environment:
  ORCHESTRATOR_REPO, ORCHESTRATOR_BRANCH, ORCHESTRATOR_DIR

Options:
  --dir PATH, --branch BRANCH, --venv PATH, --no-venv
  --skip-rust, --skip-node, --no-clone, -h, --help
EOF
}

have() { command -v "$1" >/dev/null 2>&1; }

detect_local_checkout() {
	local script="${BASH_SOURCE[0]:-}"
	[[ -n "$script" && "$script" != "-" && -f "$script" ]] || return 1
	local dir
	dir="$(cd "$(dirname "$script")" && pwd)"
	[[ -f "${dir}/main.py" && -f "${dir}/requirements.txt" ]] || return 1
	INSTALL_DIR="$dir"
	LOCAL_CHECKOUT=1
	return 0
}

parse_args() {
	while [[ $# -gt 0 ]]; do
		case "$1" in
			server|client|client:python|client:js|client:rust|all)
				TARGET="$1"
				;;
			--dir)
				[[ $# -ge 2 ]] || die "--dir requires a path"
				INSTALL_DIR="$2"
				shift
				;;
			--branch)
				[[ $# -ge 2 ]] || die "--branch requires a name"
				BRANCH="$2"
				shift
				;;
			--venv)
				[[ $# -ge 2 ]] || die "--venv requires a path"
				VENV_DIR="$2"
				USE_VENV=1
				shift
				;;
			--no-venv)
				USE_VENV=0
				;;
			--skip-rust)
				SKIP_RUST=1
				;;
			--skip-node)
				SKIP_NODE=1
				;;
			--no-clone)
				NO_CLONE=1
				LOCAL_CHECKOUT=1
				;;
			-h|--help)
				usage
				exit 0
				;;
			*)
				die "unknown argument: $1 (try --help)"
				;;
		esac
		shift
	done

	if [[ -z "$TARGET" ]]; then
		if [[ "$LOCAL_CHECKOUT" -eq 1 ]]; then
			TARGET="all"
		else
			TARGET="server"
		fi
	fi

	if [[ -z "$VENV_DIR" ]]; then
		VENV_DIR="${INSTALL_DIR}/.venv"
	fi
}

want_server() {
	case "$TARGET" in
		server|all|client:python) return 0 ;;
		client) return 0 ;;
		*) return 1 ;;
	esac
}

want_client_python() {
	case "$TARGET" in
		client|client:python|all) return 0 ;;
		*) return 1 ;;
	esac
}

want_client_js() {
	case "$TARGET" in
		client|client:js|all) return 0 ;;
		*) return 1 ;;
	esac
}

want_client_rust() {
	case "$TARGET" in
		client|client:rust|all) return 0 ;;
		*) return 1 ;;
	esac
}

check_prerequisites() {
	step "Checking prerequisites"

	if [[ "$LOCAL_CHECKOUT" -eq 0 && "$NO_CLONE" -eq 0 ]]; then
		have git || die "git is required. Install it, then re-run this script."
		ok "git $(git --version | awk '{print $3}')"
	fi

	if want_server || want_client_python; then
		have python3 || die "python3 is required for ${TARGET}. Install Python 3.9+, then re-run."
		ok "python3 $(python3 --version | awk '{print $2}')"
	fi

	if want_client_js && [[ "$SKIP_NODE" -eq 0 ]]; then
		have npm || die "npm is required for the JavaScript client. Install Node.js, then re-run."
		ok "npm v$(npm -v 2>/dev/null)"
	fi

	if want_client_rust && [[ "$SKIP_RUST" -eq 0 ]]; then
		have cargo || die "cargo is required for the Rust client (Rust 1.88+). Install from https://rustup.rs"
		ok "cargo $(cargo --version | awk '{print $2}')"
	fi
}

ensure_checkout() {
	if [[ "$LOCAL_CHECKOUT" -eq 1 || "$NO_CLONE" -eq 1 ]]; then
		[[ -f "${INSTALL_DIR}/main.py" ]] || die "not an Orchestrator checkout: ${INSTALL_DIR}"
		ok "Using checkout at ${INSTALL_DIR}"
		return
	fi

	step "Cloning repository"
	info "$REPO_URL (${BRANCH})"
	info "→ ${INSTALL_DIR}"

	if [[ -d "${INSTALL_DIR}/.git" ]]; then
		warn "Existing checkout found — updating instead of cloning"
		(
			cd "$INSTALL_DIR"
			git fetch --quiet origin "$BRANCH"
			git checkout --quiet "$BRANCH"
			git pull --ff-only --quiet origin "$BRANCH"
		) || die "failed to update existing clone at ${INSTALL_DIR}"
		ok "Updated existing checkout"
	elif [[ -e "$INSTALL_DIR" ]]; then
		die "path exists and is not an Orchestrator clone: ${INSTALL_DIR}"
	else
		mkdir -p "$(dirname "$INSTALL_DIR")"
		git clone --branch "$BRANCH" --depth 1 --quiet "$REPO_URL" "$INSTALL_DIR" \
			|| die "git clone failed"
		ok "Cloned into ${INSTALL_DIR}"
	fi
}

install_python() {
	local label="$1"
	step "Installing ${label} (Python)"
	cd "$INSTALL_DIR"

	if [[ "$USE_VENV" -eq 1 ]]; then
		if [[ ! -d "$VENV_DIR" ]]; then
			info "Creating virtualenv at ${VENV_DIR}"
			python3 -m venv "$VENV_DIR"
		fi
		# shellcheck disable=SC1091
		source "${VENV_DIR}/bin/activate"
	else
		warn "Installing Python packages with pip --user (no virtualenv)"
	fi

	python3 -m pip install --upgrade pip
	python3 -m pip install -r requirements.txt
	ok "Python dependencies installed"
}

install_client_js() {
	if [[ "$SKIP_NODE" -eq 1 ]]; then
		warn "Skipping JavaScript client (--skip-node)"
		return 0
	fi

	step "Installing JavaScript/Node client"
	cd "$INSTALL_DIR"
	if [[ -f package-lock.json ]]; then
		npm ci --no-fund --no-audit
	else
		npm install --no-fund --no-audit
	fi
	ok "Node dependencies installed"
}

install_client_rust() {
	if [[ "$SKIP_RUST" -eq 1 ]]; then
		warn "Skipping Rust client (--skip-rust)"
		return 0
	fi

	step "Building Rust workspace"
	cd "${INSTALL_DIR}/clientrs"
	cargo build --workspace --all-features
	ok "Rust workspace built"
}

run_install() {
	step "Installing Orchestrator (${TARGET})"

	if want_server; then
		install_python "server"
	fi

	if want_client_python && ! want_server; then
		install_python "Python client"
	fi

	if want_client_js; then
		install_client_js
	fi

	if want_client_rust; then
		install_client_rust
	fi
}

print_done() {
	printf '\n'
	printf ' %s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$GREEN" "$RESET"
	printf ' %s%sInstallation complete%s\n' "$GREEN" "$BOLD" "$RESET"
	printf '\n'

	case "$TARGET" in
		server)
			info "cd ${INSTALL_DIR}"
			info "source ${VENV_DIR}/bin/activate"
			info "python main.py"
			;;
		client:python)
			info "cd ${INSTALL_DIR}"
			info "source ${VENV_DIR}/bin/activate"
			info "python client/demo_publish.py"
			;;
		client:js)
			info "cd ${INSTALL_DIR}"
			info "node clientjs/test.js"
			;;
		client:rust)
			info "cd ${INSTALL_DIR}/clientrs"
			info "cargo run -p orchestrator-ws-client --example demo_publish"
			;;
		client)
			info "Python: cd ${INSTALL_DIR} && source ${VENV_DIR}/bin/activate && python client/demo_publish.py"
			info "Node:    cd ${INSTALL_DIR} && node clientjs/test.js"
			info "Rust:    cd ${INSTALL_DIR}/clientrs && cargo run -p orchestrator-ws-client --example demo_publish"
			;;
		all)
			info "Server: cd ${INSTALL_DIR} && source ${VENV_DIR}/bin/activate && python main.py"
			info "Python: python client/demo_publish.py"
			info "Node:    node clientjs/test.js"
			info "Rust:    cd clientrs && cargo run -p orchestrator-ws-client --example demo_publish"
			;;
	esac

	printf '\n'
	printf ' %s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$GREEN" "$RESET"
	printf '\n'
}

main() {
	detect_local_checkout || true
	parse_args "$@"
	check_prerequisites
	ensure_checkout
	run_install
	print_done
}

main "$@"
