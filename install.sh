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
#   ORCHESTRATOR_BIN_DIR Directory for the orch command (default: ~/.local/bin)
#
# Targets:
#   server              Python server only (default for curl install)
#   client              All clients (python, js, rust)
#   client:python       Python client
#   client:js           JavaScript/Node client
#   client:rust         Rust workspace
#   all                 Server + all clients (default when run from a local checkout)
#   command             Install the `orch` launcher only (existing checkout)
#
# Options:
#   --dir PATH          Install directory (same as ORCHESTRATOR_DIR)
#   --branch BRANCH     Git branch (same as ORCHESTRATOR_BRANCH)
#   --venv PATH         Python virtualenv directory (default: <install-dir>/.venv)
#   --bin-dir PATH      Directory for the `orch` command (default: ~/.local/bin)
#   --no-venv           Install Python packages with pip --user
#   --no-command        Do not install the `orch` launcher
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
BIN_DIR="${ORCHESTRATOR_BIN_DIR:-}"
SKIP_RUST=0
SKIP_NODE=0
NO_CLONE=0
NO_COMMAND=0
LOCAL_CHECKOUT=0
COMMAND_INSTALLED=0
PATH_HINT=""

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
  command             Install the orch launcher only (existing checkout)

Environment:
  ORCHESTRATOR_REPO, ORCHESTRATOR_BRANCH, ORCHESTRATOR_DIR, ORCHESTRATOR_BIN_DIR

Options:
  --dir PATH, --branch BRANCH, --venv PATH, --bin-dir PATH
  --no-venv, --no-command, --skip-rust, --skip-node, --no-clone, -h, --help
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
			server|client|client:python|client:js|client:rust|all|command)
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
			--bin-dir)
				[[ $# -ge 2 ]] || die "--bin-dir requires a path"
				BIN_DIR="$2"
				shift
				;;
			--no-venv)
				USE_VENV=0
				;;
			--no-command)
				NO_COMMAND=1
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

	if [[ -z "$BIN_DIR" ]]; then
		BIN_DIR="${HOME}/.local/bin"
	fi

	if [[ "$TARGET" == "command" ]]; then
		NO_COMMAND=0
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

want_orch_command() {
	[[ "$NO_COMMAND" -eq 0 ]] || return 1
	case "$TARGET" in
		server|all|command) return 0 ;;
		*) return 1 ;;
	esac
}

check_prerequisites() {
	if [[ "$TARGET" == "command" ]]; then
		return
	fi

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
	if [[ "$TARGET" == "command" ]]; then
		[[ -f "${INSTALL_DIR}/main.py" ]] || die "command requires an existing Orchestrator checkout. Run ./install.sh command from the repo, or pass --dir PATH"
		ok "Using checkout at ${INSTALL_DIR}"
		return
	fi

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

canonicalize_paths() {
	INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"

	if [[ "$USE_VENV" -eq 1 ]]; then
		local parent base
		parent="$(dirname "$VENV_DIR")"
		base="$(basename "$VENV_DIR")"
		mkdir -p "$parent"
		parent="$(cd "$parent" && pwd)"
		VENV_DIR="${parent}/${base}"
	fi
}

append_path_snippet() {
	local rc="$1"
	local snippet="$2"
	local marker="# added by Orchestrator installer"

	if [[ -f "$rc" ]] && grep -Fqs "$marker" "$rc"; then
		return 0
	fi
	printf '\n%s\n%s\n' "$marker" "$snippet" >> "$rc"
	ok "Added ${BIN_DIR} to PATH in ${rc}"
}

ensure_bin_on_path() {
	if [[ ":${PATH}:" == *":${BIN_DIR}:"* ]]; then
		return 0
	fi

	local snippet
	if [[ "$BIN_DIR" == "${HOME}/.local/bin" ]]; then
		snippet='export PATH="$HOME/.local/bin:$PATH"'
	else
		snippet="export PATH=\"${BIN_DIR}:\$PATH\""
	fi

	local shell_name
	shell_name="$(basename "${SHELL:-/bin/sh}")"
	case "$shell_name" in
		zsh)
			append_path_snippet "${HOME}/.zshrc" "$snippet"
			append_path_snippet "${HOME}/.zprofile" "$snippet"
			;;
		bash)
			append_path_snippet "${HOME}/.bashrc" "$snippet"
			append_path_snippet "${HOME}/.bash_profile" "$snippet"
			;;
		fish)
			local fish_config="${HOME}/.config/fish/config.fish"
			local marker="# added by Orchestrator installer"
			mkdir -p "$(dirname "$fish_config")"
			if [[ -f "$fish_config" ]] && grep -Fqs "$marker" "$fish_config"; then
				:
			else
				printf '\n%s\nfish_add_path %s\n' "$marker" "$BIN_DIR" >> "$fish_config"
				ok "Added ${BIN_DIR} to PATH in ${fish_config}"
			fi
			;;
		*)
			warn "Add ${BIN_DIR} to your PATH to use the orch command"
			;;
	esac

	PATH_HINT="export PATH=\"${BIN_DIR}:\$PATH\""
}

install_command() {
	step "Installing orch command"

	mkdir -p "$BIN_DIR"
	BIN_DIR="$(cd "$BIN_DIR" && pwd)"

	if [[ -f "${INSTALL_DIR}/bin/orch" ]]; then
		chmod +x "${INSTALL_DIR}/bin/orch"
	fi

	local dest="${BIN_DIR}/orch"
	{
		printf '%s\n' '#!/usr/bin/env bash'
		printf '%s\n' '# Generated by Orchestrator installer — start the server from any directory.'
		printf '%s\n' 'set -euo pipefail'
		printf 'ORCH_HOME=%q\n' "$INSTALL_DIR"
		if [[ "$USE_VENV" -eq 1 ]]; then
			printf 'ORCH_VENV=%q\n' "$VENV_DIR"
		else
			printf '%s\n' 'ORCH_VENV=""'
		fi
		cat <<'BODY'
if [[ ! -f "${ORCH_HOME}/main.py" ]]; then
	printf 'orch: Orchestrator not found at %s\n' "$ORCH_HOME" >&2
	printf 'orch: re-run ./install.sh command from the checkout\n' >&2
	exit 1
fi
if [[ -n "$ORCH_VENV" && -x "${ORCH_VENV}/bin/python" ]]; then
	PYTHON="${ORCH_VENV}/bin/python"
elif [[ -x "${ORCH_HOME}/.venv/bin/python" ]]; then
	PYTHON="${ORCH_HOME}/.venv/bin/python"
else
	PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
	printf 'orch: python3 not found. Run ./install.sh server first.\n' >&2
	exit 1
fi
cd "$ORCH_HOME"
exec "$PYTHON" "${ORCH_HOME}/main.py" "$@"
BODY
	} > "$dest"
	chmod +x "$dest"
	COMMAND_INSTALLED=1
	ok "Installed ${dest}"

	if have orch; then
		local resolved
		resolved="$(command -v orch)"
		if [[ "$resolved" != "$dest" ]]; then
			warn "another orch is on PATH: ${resolved} (this install is ${dest})"
		fi
	fi

	ensure_bin_on_path
}

run_install() {
	if [[ "$TARGET" != "command" ]]; then
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
	fi

	if want_orch_command; then
		install_command
	fi
}

print_orch_hint() {
	[[ "$COMMAND_INSTALLED" -eq 1 ]] || return 0
	info "Start the server from anywhere:"
	info "  orch"
	if [[ -n "$PATH_HINT" ]]; then
		info "If orch is not found, restart your shell or run:"
		info "  ${PATH_HINT}"
	fi
}

print_done() {
	printf '\n'
	printf ' %s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$GREEN" "$RESET"
	printf ' %s%sInstallation complete%s\n' "$GREEN" "$BOLD" "$RESET"
	printf '\n'

	case "$TARGET" in
		server)
			print_orch_hint
			if [[ "$COMMAND_INSTALLED" -eq 0 ]]; then
				info "cd ${INSTALL_DIR}"
				info "source ${VENV_DIR}/bin/activate"
				info "python main.py"
			fi
			;;
		command)
			print_orch_hint
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
			print_orch_hint
			if [[ "$COMMAND_INSTALLED" -eq 0 ]]; then
				info "Server: cd ${INSTALL_DIR} && source ${VENV_DIR}/bin/activate && python main.py"
			fi
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
	canonicalize_paths
	run_install
	print_done
}

main "$@"
