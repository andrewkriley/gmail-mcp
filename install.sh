#!/usr/bin/env bash
# gmail-mcp installer — macOS & Ubuntu
# Creates a self-contained .venv inside the repo directory.
# Usage:
#   bash install.sh                    # auto-detect (uv preferred, then pip)
#   bash install.sh --no-setup         # install only, skip OAuth setup
#   bash install.sh --headless         # OAuth via printed URL (no browser)
#   bash install.sh --claude-desktop   # write MCP config to Claude Desktop
#   bash install.sh --claude-code      # write MCP config to Claude Code (~/.claude.json)
#   bash install.sh --no-client        # skip client config prompt
#   bash install.sh --fresh            # wipe credentials & MCP config, then reinstall from scratch
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
RUN_SETUP=1
HEADLESS=0
INSTALL_CLAUDE_DESKTOP=0
INSTALL_CLAUDE_CODE=0
FRESH=0
# -1 = prompt interactively, 0 = skip, 1 = already set via flags
CLIENT_MODE=-1

for arg in "$@"; do
  case "$arg" in
    --no-setup)        RUN_SETUP=0 ;;
    --headless)        HEADLESS=1 ;;
    --claude-desktop)  INSTALL_CLAUDE_DESKTOP=1; CLIENT_MODE=1 ;;
    --claude-code)     INSTALL_CLAUDE_CODE=1;    CLIENT_MODE=1 ;;
    --no-client)       CLIENT_MODE=0 ;;
    --fresh)           FRESH=1 ;;
    -h|--help)
      sed -n '2,11p' "$0" | sed 's/^# //'
      exit 0
      ;;
  esac
done

# ── helpers ──────────────────────────────────────────────────────────────────

info()  { printf '\033[1;34m[gmail-mcp]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[gmail-mcp]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[gmail-mcp]\033[0m %s\n' "$*" >&2; }
die()   { printf '\033[1;31m[gmail-mcp]\033[0m %s\n' "$*" >&2; exit 1; }

# ── OS detection ──────────────────────────────────────────────────────────────

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM=macos ;;
  Linux)  PLATFORM=linux ;;
  *)      die "Unsupported OS: $OS" ;;
esac

info "Platform: $PLATFORM"
if [[ "$PLATFORM" == "linux" ]]; then
  warn "SECURITY: On Linux, OAuth credentials are stored as plaintext files"
  warn "         (~/.config/gmail-mcp/). Permissions are set to 600/700, but"
  warn "         consider an encrypted secrets manager for production/shared systems."
fi

# ── Python check ─────────────────────────────────────────────────────────────

py_meets_min() {
  local py="$1"
  command -v "$py" &>/dev/null || return 1
  local maj min
  maj=$("$py" -c 'import sys; print(sys.version_info[0])' 2>/dev/null) || return 1
  min=$("$py" -c 'import sys; print(sys.version_info[1])' 2>/dev/null) || return 1
  [[ "$maj" -gt 3 || ("$maj" -eq 3 && "$min" -ge 11) ]]
}

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if py_meets_min "$candidate"; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  # Check if any python3 exists but is too old
  if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    if [[ "$PLATFORM" == "linux" ]]; then
      die "Python 3.11+ required (found $PY_VERSION). Install with: sudo apt install python3.11"
    else
      die "Python 3.11+ required (found $PY_VERSION). Install via: brew install python@3.12"
    fi
  fi
  if [[ "$PLATFORM" == "linux" ]]; then
    die "Python 3 not found. Install with: sudo apt install python3.11"
  else
    die "Python 3 not found. Install via: brew install python@3.12"
  fi
fi

PY_VERSION=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
info "Python $PY_VERSION ($PYTHON) ✓"

# ── Create venv & install ─────────────────────────────────────────────────────

if command -v uv &>/dev/null; then
  info "Creating venv with uv…"
  uv venv "$VENV_DIR" --python "$PYTHON" --quiet
  info "Installing with uv pip…"
  uv pip install --python "$VENV_DIR/bin/python" -e "$REPO_DIR" --quiet
  INSTALLER=uv
else
  info "Creating venv…"
  "$PYTHON" -m venv "$VENV_DIR"
  info "Installing with pip…"
  "$VENV_DIR/bin/pip" install --quiet -e "$REPO_DIR"
  INSTALLER=pip
fi

GMAIL_MCP_BIN="$VENV_DIR/bin/gmail-mcp"
GMAIL_MCP_SETUP_BIN="$VENV_DIR/bin/gmail-mcp-setup"

[[ -x "$GMAIL_MCP_BIN" ]] || die "gmail-mcp binary not found after install: $GMAIL_MCP_BIN"
ok "Installed via $INSTALLER into $VENV_DIR ✓"

# ── Fresh install: wipe credentials & MCP config entries ─────────────────────

_purge_credentials() {
  info "Purging existing credentials and MCP config entries…"

  # Remove OAuth token from Keychain (ignore error if not present)
  "$GMAIL_MCP_SETUP_BIN" --delete-keychain-token 2>/dev/null || true

  # Remove client secret from Keychain (ignore error if not present)
  "$GMAIL_MCP_SETUP_BIN" --delete-keychain 2>/dev/null || true

  # Remove plaintext credential files
  local state_dir="$HOME/.config/gmail-mcp"
  rm -f "$state_dir/token.json" "$state_dir/client_secret.json"

  # Remove the gmail entry from any installed MCP client configs
  local desktop_cfg="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  local code_cfg="$HOME/.claude.json"
  for cfg in "$desktop_cfg" "$code_cfg"; do
    if [[ -f "$cfg" ]]; then
      "$PYTHON" - "$cfg" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    data = json.loads(open(path).read())
    removed = data.get("mcpServers", {}).pop("gmail", None)
    if removed is not None:
        open(path, "w").write(json.dumps(data, indent=2) + "\n")
        print(f"Removed gmail MCP entry from {path}")
except Exception as e:
    print(f"Warning: could not update {path}: {e}", file=sys.stderr)
PYEOF
    fi
  done

  ok "Credentials purged ✓"
}

if [[ "$FRESH" -eq 1 ]]; then
  _purge_credentials
fi

# ── OAuth setup ───────────────────────────────────────────────────────────────

# Locate a client_secret*.json in the same places setup_cli.py looks.
_find_client_secret() {
  local cfg="$HOME/.config/gmail-mcp/client_secret.json"
  [[ -f "$cfg" ]] && { echo "$cfg"; return; }
  for dir in "$HOME/Downloads" "$HOME/download" "/tmp"; do
    local found
    found=$(find "$dir" -maxdepth 1 -name 'client_secret*.json' 2>/dev/null \
            | xargs ls -t 2>/dev/null | head -1)
    [[ -n "$found" ]] && { echo "$found"; return; }
  done
}

# ── Client config selection ───────────────────────────────────────────────────

_prompt_client_selection() {
  # Only prompt when stdin is a terminal
  if [[ ! -t 0 ]]; then
    return
  fi
  echo ""
  echo "Configure MCP client automatically?"
  echo "  1) Claude Desktop"
  echo "  2) Claude Code  (~/.claude.json)"
  echo "  3) Both"
  echo "  4) Skip  (I'll edit the config manually)"
  printf "Choice [1-4]: "
  local choice
  read -r choice
  case "$choice" in
    1) INSTALL_CLAUDE_DESKTOP=1 ;;
    2) INSTALL_CLAUDE_CODE=1 ;;
    3) INSTALL_CLAUDE_DESKTOP=1; INSTALL_CLAUDE_CODE=1 ;;
    *) ;;  # skip
  esac
}

_build_setup_flags() {
  local flags=()
  [[ "$HEADLESS" -eq 1 ]]              && flags+=(--no-browser)
  [[ "$INSTALL_CLAUDE_DESKTOP" -eq 1 ]] && flags+=(--install-claude-desktop)
  [[ "$INSTALL_CLAUDE_CODE" -eq 1 ]]    && flags+=(--install-claude-code)
  # Print config only when neither auto-install target was chosen
  if [[ "$INSTALL_CLAUDE_DESKTOP" -eq 0 && "$INSTALL_CLAUDE_CODE" -eq 0 ]]; then
    flags+=(--print-config)
  fi
  echo "${flags[@]+"${flags[@]}"}"
}

# ── Scope detection & change ──────────────────────────────────────────────────

# Read the current Gmail scope from an installed MCP config file.
# Returns one of: "mailbox", "full", or "custom: <URL1>,<URL2>,..."
_detect_current_scope() {
  local code_cfg="$HOME/.claude.json"
  local desktop_cfg="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  for cfg_path in "$code_cfg" "$desktop_cfg"; do
    if [[ -f "$cfg_path" ]]; then
      local result
      result=$("$PYTHON" -c "
import json, sys
try:
    data = json.loads(open(sys.argv[1]).read())
    env = data.get('mcpServers', {}).get('gmail', {}).get('env', {})
    if 'GMAIL_MCP_SCOPES' in env:
        print('custom: ' + env['GMAIL_MCP_SCOPES'])
    elif 'GMAIL_MCP_SCOPE_MODE' in env:
        print(env['GMAIL_MCP_SCOPE_MODE'])
    else:
        print('mailbox')
except Exception:
    pass
" "$cfg_path" 2>/dev/null)
      [[ -n "$result" ]] && { echo "$result"; return; }
    fi
  done
  echo "mailbox"
}

_print_scope_description() {
  case "$1" in
    mailbox) echo "mailbox  — gmail.modify (read/write messages, labels, drafts, send; no account settings)" ;;
    full)    echo "full     — mail.google.com (complete access including filters, forwarding, settings)" ;;
    custom:*) echo "custom   — ${1#custom: }" ;;
    *)       echo "$1" ;;
  esac
}

_print_restart_instructions() {
  echo ""
  ok "Scope updated. Restart your MCP client to apply the new OAuth token:"
  echo ""
  if [[ "$INSTALL_CLAUDE_DESKTOP" -eq 1 ]]; then
    echo "  Claude Desktop: quit the app (⌘Q) and reopen it."
  fi
  if [[ "$INSTALL_CLAUDE_CODE" -eq 1 ]]; then
    echo "  Claude Code:    exit and re-run 'claude' in your terminal."
    echo "                  Or in an active session: /mcp  (to verify) then restart."
  fi
  if [[ "$INSTALL_CLAUDE_DESKTOP" -eq 0 && "$INSTALL_CLAUDE_CODE" -eq 0 ]]; then
    echo "  Restart whichever MCP client you configured manually."
  fi
  echo ""
}

_prompt_scope_change() {
  # Only prompt when stdin is a terminal
  [[ ! -t 0 ]] && return

  local current
  current=$(_detect_current_scope)

  echo ""
  echo "Gmail scope currently configured:"
  printf "  \033[1;36m%s\033[0m\n" "$(_print_scope_description "$current")"
  echo ""
  echo "Change Gmail scope?"
  echo "  1) mailbox  — gmail.modify (default; read/write messages, no account settings)"
  echo "  2) full     — mail.google.com (complete access including account settings)"
  echo "  3) Keep current scope"
  printf "Choice [1-3]: "
  local choice
  read -r choice

  local new_scope=""
  case "$choice" in
    1) new_scope="mailbox" ;;
    2) new_scope="full" ;;
    *) return ;;  # keep current
  esac

  # Skip if already set to the chosen scope
  if [[ "$current" == "$new_scope" ]]; then
    info "Scope is already set to '$new_scope' — no change needed."
    return
  fi

  info "Re-running OAuth with scope '$new_scope'…"
  local flags=("--scope" "$new_scope")
  [[ "$HEADLESS" -eq 1 ]]              && flags+=(--no-browser)
  [[ "$INSTALL_CLAUDE_DESKTOP" -eq 1 ]] && flags+=(--install-claude-desktop)
  [[ "$INSTALL_CLAUDE_CODE" -eq 1 ]]    && flags+=(--install-claude-code)
  if [[ "$INSTALL_CLAUDE_DESKTOP" -eq 0 && "$INSTALL_CLAUDE_CODE" -eq 0 ]]; then
    flags+=(--print-config)
  fi
  "$GMAIL_MCP_SETUP_BIN" "${flags[@]}"
  _print_restart_instructions
}

if [[ "$RUN_SETUP" -eq 1 ]]; then
  SECRET=$(_find_client_secret)
  if [[ -z "$SECRET" ]]; then
    warn "OAuth client secret not found — skipping authentication."
    echo ""
    echo "  To complete setup:"
    echo "    1. Go to https://console.cloud.google.com/apis/credentials"
    echo "       → Create credentials → OAuth client ID → Desktop app → Download JSON"
    echo "    2. Place the file in ~/.config/gmail-mcp/client_secret.json"
    echo "       (or leave it in ~/Downloads — the name client_secret*.json is enough)"
    echo "    3. Run: $GMAIL_MCP_SETUP_BIN --print-config"
    echo ""
  else
    info "Found credentials: $SECRET"
    [[ "$CLIENT_MODE" -eq -1 ]] && _prompt_client_selection
    info "Running OAuth setup…"
    # shellcheck disable=SC2046
    "$GMAIL_MCP_SETUP_BIN" $(_build_setup_flags)
    _prompt_scope_change
  fi
else
  ok "Skipped OAuth setup (--no-setup). Run the following when ready:"
  echo "  $GMAIL_MCP_SETUP_BIN --print-config"
  _prompt_scope_change
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
ok "Installation complete."
info "Binary: $GMAIL_MCP_BIN"
info "To activate the venv manually: source $VENV_DIR/bin/activate"
