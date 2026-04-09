#!/usr/bin/env bash
# gmail-mcp installer — macOS & Ubuntu
# Creates a self-contained .venv inside the repo directory.
# Usage:
#   bash install.sh              # auto-detect (uv preferred, then pip)
#   bash install.sh --no-setup   # install only, skip OAuth setup
#   bash install.sh --headless   # OAuth via printed URL (no browser)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
RUN_SETUP=1
HEADLESS=0

for arg in "$@"; do
  case "$arg" in
    --no-setup)  RUN_SETUP=0 ;;
    --headless)  HEADLESS=1 ;;
    -h|--help)
      sed -n '2,7p' "$0" | sed 's/^# //'
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
    info "Running OAuth setup…"
    if [[ "$HEADLESS" -eq 1 ]]; then
      "$GMAIL_MCP_SETUP_BIN" --no-browser --print-config
    else
      "$GMAIL_MCP_SETUP_BIN" --print-config
    fi
  fi
else
  ok "Skipped OAuth setup (--no-setup). Run the following when ready:"
  echo "  $GMAIL_MCP_SETUP_BIN --print-config"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
ok "Installation complete."
info "Binary: $GMAIL_MCP_BIN"
info "To activate the venv manually: source $VENV_DIR/bin/activate"
