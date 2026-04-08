"""Interactive OAuth setup without starting the MCP server."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gmail_mcp.auth import load_credentials
from gmail_mcp.config import client_secret_path, state_dir, token_path


def main() -> None:
    p = argparse.ArgumentParser(
        description="Authenticate Gmail MCP with Google OAuth (saves token for the server).",
        epilog=(
            "OAuth scopes: default is mailbox-only (gmail.modify). "
            "Set GMAIL_MCP_SCOPE_MODE=full for filters/forwarding/send-as/watch tools, "
            "or GMAIL_MCP_SCOPES to a comma-separated list of scope URLs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="Print authorization URL instead of opening a browser (for SSH).",
    )
    p.add_argument(
        "--client-secret",
        type=str,
        default=None,
        help="Path to OAuth client secret JSON (default: ~/.config/gmail-mcp/client_secret.json).",
    )
    p.add_argument(
        "--token",
        type=str,
        default=None,
        help="Path to store the OAuth token (default: ~/.config/gmail-mcp/token.json).",
    )
    args = p.parse_args()

    secret = Path(args.client_secret) if args.client_secret else client_secret_path()
    tok = Path(args.token) if args.token else token_path()

    if not secret.is_file():
        d = state_dir()
        print(
            f"Missing OAuth client secret at {secret}.\n"
            f"1. In Google Cloud Console, enable Gmail API and create OAuth credentials (Desktop app).\n"
            f"2. Download the JSON and save it to:\n   {d / 'client_secret.json'}\n"
            f"   Or pass --client-secret /path/to/client_secret.json",
            file=sys.stderr,
        )
        sys.exit(1)

    load_credentials(client_secret_file=secret, token_file=tok, open_browser=not args.no_browser)
    print(f"Saved token to {tok}. You can start the MCP server with: gmail-mcp")
