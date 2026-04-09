"""Interactive OAuth setup without starting the MCP server."""

from __future__ import annotations

import argparse
import shlex
import shutil
import sys
from pathlib import Path

from gmail_mcp.auth import load_credentials
from gmail_mcp.config import (
    client_secret_path,
    keychain_delete_client_secret,
    keychain_load_client_secret,
    keychain_save_client_secret,
    state_dir,
    token_path,
)

# Candidate directories where Google Chrome / Firefox save downloads on each OS.
_DOWNLOAD_DIRS = [
    Path.home() / "Downloads",           # macOS & Ubuntu (GNOME default)
    Path.home() / "download",            # some Ubuntu setups
    Path("/tmp"),                         # headless / CI fallback
]


def _find_client_secret_in_downloads() -> Path | None:
    """Return the most-recently-modified client_secret*.json from common download dirs."""
    candidates: list[Path] = []
    for d in _DOWNLOAD_DIRS:
        if d.is_dir():
            candidates.extend(d.glob("client_secret*.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _resolve_client_secret(cli_value: str | None) -> Path:
    """
    Determine the client secret path, with auto-discovery fallback.

    Priority:
      1. Explicit --client-secret CLI argument or positional arg
      2. Configured default path (env / ~/.config/gmail-mcp/client_secret.json)
      3. Auto-discovered client_secret*.json in ~/Downloads (or /tmp on Linux)
    """
    if cli_value:
        return Path(cli_value).expanduser()

    default = client_secret_path()
    if default.is_file():
        return default

    found = _find_client_secret_in_downloads()
    if found:
        dest = state_dir() / "client_secret.json"
        shutil.copy(found, dest)
        print(f"Found credentials: {found.name}\nCopied to {dest}\n")
        return dest

    return default  # let the caller emit the "not found" error


def _mcp_config(executable: str) -> str:
    """Return a ready-to-paste MCP server JSON block."""
    import json

    config = {
        "mcpServers": {
            "gmail": {
                "command": executable,
            }
        }
    }
    return json.dumps(config, indent=2)


def _find_executable() -> str:
    """Return the absolute path of the gmail-mcp binary.

    Prefers the sibling binary next to the running Python interpreter so that
    the printed MCP config points into the venv even when the venv is not
    activated in the calling shell.
    """
    sibling = Path(sys.executable).parent / "gmail-mcp"
    if sibling.is_file():
        return str(sibling)
    path = shutil.which("gmail-mcp")
    return path if path else "gmail-mcp"


def main() -> None:
    p = argparse.ArgumentParser(
        description="Authenticate Gmail MCP with Google OAuth (saves token for the server).",
        epilog=(
            "OAuth scopes: default is mailbox-only (gmail.modify). "
            "Set GMAIL_MCP_SCOPE_MODE=full for filters/forwarding/send-as/watch tools, "
            "or GMAIL_MCP_SCOPES to a comma-separated list of scope URLs.\n\n"
            "Tip: if you just downloaded credentials from Google Cloud Console, run\n"
            "  gmail-mcp-setup\n"
            "without any arguments — it will find the file in ~/Downloads automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "client_secret_positional",
        nargs="?",
        metavar="CLIENT_SECRET",
        help="Path to OAuth client secret JSON (positional shorthand for --client-secret).",
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="Print authorization URL instead of opening a browser (for SSH/headless).",
    )
    p.add_argument(
        "--client-secret",
        type=str,
        default=None,
        dest="client_secret",
        help="Path to OAuth client secret JSON (default: ~/.config/gmail-mcp/client_secret.json).",
    )
    p.add_argument(
        "--token",
        type=str,
        default=None,
        help="Path to store the OAuth token (default: ~/.config/gmail-mcp/token.json).",
    )
    p.add_argument(
        "--print-config",
        action="store_true",
        help="After authenticating, print a ready-to-paste MCP server JSON block and exit.",
    )
    p.add_argument(
        "--keychain",
        action="store_true",
        help="Store the client secret in the macOS Keychain instead of (or in addition to) a file.",
    )
    p.add_argument(
        "--delete-keychain",
        action="store_true",
        help="Remove the client secret from the macOS Keychain and exit.",
    )
    args = p.parse_args()

    # --delete-keychain: remove stored secret and exit
    if args.delete_keychain:
        if keychain_load_client_secret() is None:
            print("No client secret found in Keychain.")
        else:
            keychain_delete_client_secret()
            print("Client secret removed from Keychain.")
        sys.exit(0)

    # Positional arg overrides --client-secret when both are given
    cli_secret = args.client_secret_positional or args.client_secret
    secret = _resolve_client_secret(cli_secret)
    tok = Path(args.token) if args.token else token_path()

    # --keychain: store the secret in Keychain (file still required to read from)
    if args.keychain:
        if not secret.is_file():
            print(
                "Pass the client_secret*.json path to store it in the Keychain:\n"
                "  gmail-mcp-setup --keychain ~/Downloads/client_secret_*.json",
                file=sys.stderr,
            )
            sys.exit(1)
        keychain_save_client_secret(secret.read_text(encoding="utf-8"))
        print(f"Client secret stored in Keychain (service=gmail-mcp).")
        print("You can now delete the JSON file — the server will use the Keychain entry.")

    if not args.keychain and not secret.is_file() and keychain_load_client_secret() is None:
        d = state_dir()
        print(
            f"OAuth client secret not found.\n\n"
            f"Get it from Google Cloud Console:\n"
            f"  https://console.cloud.google.com/apis/credentials\n"
            f"  → Create credentials → OAuth client ID → Desktop app → Download JSON\n\n"
            f"Then either:\n"
            f"  • Save the file to:  {d / 'client_secret.json'}\n"
            f"  • Store in Keychain:  gmail-mcp-setup --keychain ~/Downloads/client_secret_*.json\n"
            f"  • Or pass it directly:  gmail-mcp-setup ~/Downloads/client_secret_*.json",
            file=sys.stderr,
        )
        sys.exit(1)

    load_credentials(client_secret_file=secret if secret.is_file() else None, token_file=tok, open_browser=not args.no_browser)
    print(f"Authentication complete. Token saved to {tok}.")

    if args.print_config:
        exe = _find_executable()
        print(f"\nAdd this to your MCP host config (Claude Desktop / Cursor / etc.):\n")
        print(_mcp_config(exe))
    else:
        print(f"\nStart the MCP server with:  gmail-mcp")
        print(f"Or run setup with config output:  gmail-mcp-setup --print-config")
