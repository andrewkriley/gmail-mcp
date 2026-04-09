"""Interactive OAuth setup without starting the MCP server."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from gmail_mcp.auth import load_credentials
from gmail_mcp.config import (
    client_secret_path,
    keychain_delete_client_secret,
    keychain_delete_token,
    keychain_load_client_secret,
    keychain_load_token,
    keychain_save_client_secret,
    state_dir,
    token_path,
    use_keychain_token,
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
        dest.chmod(0o600)
        print(f"Found credentials: {found.name}\nCopied to {dest}\n")
        return dest

    return default  # let the caller emit the "not found" error


# Available Gmail OAuth scopes with descriptions
GMAIL_SCOPES = {
    "https://www.googleapis.com/auth/gmail.readonly":    "Read all resources and their metadata — no write operations.",
    "https://www.googleapis.com/auth/gmail.send":        "Send messages only; no read or modify access.",
    "https://www.googleapis.com/auth/gmail.compose":     "Create, read, update, and delete drafts; send messages.",
    "https://www.googleapis.com/auth/gmail.insert":      "Insert and import messages.",
    "https://www.googleapis.com/auth/gmail.labels":      "Create, read, update, and delete labels only.",
    "https://www.googleapis.com/auth/gmail.metadata":    "Read resources metadata including labels, history, profile; no message body.",
    "https://www.googleapis.com/auth/gmail.modify":      "All read/write except settings (default mailbox mode).",
    "https://mail.google.com/":                          "Full account access including settings, filters, forwarding (full mode).",
}


def _print_scopes() -> None:
    print("Available Gmail OAuth scope URLs:\n")
    for url, desc in GMAIL_SCOPES.items():
        print(f"  {url}")
        print(f"    {desc}")
    print(
        "\nPre-defined modes:\n"
        "  mailbox  →  gmail.modify (read/write messages, no account settings)\n"
        "  full     →  mail.google.com (complete access)\n"
        "  custom   →  specify exact scopes with --scopes URL1,URL2,...\n"
    )


def _mcp_config(executable: str, env: dict[str, str] | None = None) -> str:
    """Return a ready-to-paste MCP server JSON block."""
    import json

    server: dict = {"command": executable}
    if env:
        server["env"] = env
    config = {"mcpServers": {"gmail": server}}
    return json.dumps(config, indent=2)


def _claude_desktop_config_path() -> Path:
    import platform
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    # Linux / Windows fallback (Claude Desktop uses XDG on Linux)
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "Claude" / "claude_desktop_config.json"


def _claude_code_config_path() -> Path:
    return Path.home() / ".claude.json"


def _install_mcp_config(
    config_path: Path,
    executable: str,
    client_label: str,
    env: dict[str, str] | None = None,
) -> None:
    """Merge the gmail MCP server entry into a JSON config file."""
    import json

    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if config_path.is_file():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"Warning: {config_path} contains invalid JSON — it will be overwritten.", file=sys.stderr)

    existing.setdefault("mcpServers", {})
    server: dict = {"command": executable}
    if env:
        server["env"] = env
    existing["mcpServers"]["gmail"] = server

    config_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print(f"gmail MCP server added to {client_label} config: {config_path}")


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
            "OAuth scope modes:\n"
            "  mailbox  gmail.modify — read/write messages, labels, threads, drafts, send;\n"
            "           does NOT include account settings (filters, forwarding, send-as) or watch.\n"
            "  full     mail.google.com — complete access including account settings.\n"
            "  custom   Specify exact scope URLs with --scopes (run --list-scopes to see options).\n\n"
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
    p.add_argument(
        "--delete-keychain-token",
        action="store_true",
        help="Remove the OAuth token from the macOS Keychain and exit.",
    )
    p.add_argument(
        "--install-claude-desktop",
        action="store_true",
        help="Write the MCP server config into the Claude Desktop config file.",
    )
    p.add_argument(
        "--install-claude-code",
        action="store_true",
        help="Write the MCP server config into the Claude Code global config (~/.claude.json).",
    )
    p.add_argument(
        "--scope",
        choices=["mailbox", "full", "custom"],
        default=None,
        metavar="MODE",
        help=(
            "OAuth scope mode: mailbox (default, gmail.modify), full (mail.google.com), "
            "or custom (specify URLs with --scopes). Run --list-scopes to see available scope URLs."
        ),
    )
    p.add_argument(
        "--scopes",
        type=str,
        default=None,
        metavar="URL1,URL2,...",
        help="Comma-separated Gmail API scope URLs for --scope custom.",
    )
    p.add_argument(
        "--list-scopes",
        action="store_true",
        help="Print available Gmail OAuth scope URLs and exit.",
    )
    args = p.parse_args()

    # --list-scopes: print available scope URLs and exit
    if args.list_scopes:
        _print_scopes()
        sys.exit(0)

    # --delete-keychain: remove stored secret and exit
    if args.delete_keychain:
        if keychain_load_client_secret() is None:
            print("No client secret found in Keychain.")
        else:
            keychain_delete_client_secret()
            print("Client secret removed from Keychain.")
        sys.exit(0)

    # --delete-keychain-token: remove stored OAuth token and exit
    if args.delete_keychain_token:
        if keychain_load_token() is None:
            print("No OAuth token found in Keychain.")
        else:
            keychain_delete_token()
            print("OAuth token removed from Keychain.")
        sys.exit(0)

    # Resolve and validate --scope / --scopes, then expose as env vars so
    # oauth_scopes() (called inside load_credentials) picks up the right set.
    scope_env: dict[str, str] = {}
    if args.scope == "custom":
        if not args.scopes:
            p.error("--scope custom requires --scopes URL1,URL2,... (run --list-scopes to see options)")
        scope_env["GMAIL_MCP_SCOPES"] = args.scopes
        os.environ["GMAIL_MCP_SCOPES"] = args.scopes
    elif args.scope in ("full", "mailbox"):
        scope_env["GMAIL_MCP_SCOPE_MODE"] = args.scope
        os.environ["GMAIL_MCP_SCOPE_MODE"] = args.scope
    elif args.scopes:
        # --scopes without --scope custom: treat as custom implicitly
        scope_env["GMAIL_MCP_SCOPES"] = args.scopes
        os.environ["GMAIL_MCP_SCOPES"] = args.scopes

    # Positional arg overrides --client-secret when both are given
    cli_secret = args.client_secret_positional or args.client_secret
    secret = _resolve_client_secret(cli_secret)
    tok = Path(args.token) if args.token else token_path()

    # --keychain: store the secret in Keychain and delete the plaintext file(s)
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
        # Delete every plaintext copy — keychain is now the sole source of truth.
        deleted: list[Path] = []
        for candidate in {secret, client_secret_path()}:
            if candidate.is_file():
                candidate.unlink()
                deleted.append(candidate)
        for p in deleted:
            print(f"Deleted credential file: {p}")

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
    if use_keychain_token():
        print("Authentication complete. Token and client secret stored in macOS Keychain (service=gmail-mcp).")
        print("Credential JSON files have been deleted — the server reads exclusively from the Keychain.")
    else:
        print(f"Authentication complete. Token saved to {tok}.")
        print(
            "\n\033[1;33mSECURITY WARNING\033[0m: OAuth credentials are stored as plaintext files on disk.\n"
            f"  Token:         {tok}\n"
            f"  Client secret: {client_secret_path()}\n"
            "File permissions are set to 600 (owner read/write only), but these files\n"
            "contain sensitive tokens. Consider restricting access further or using\n"
            "an encrypted secrets manager for any shared or production environment.",
            file=sys.stderr,
        )

    exe = _find_executable()

    env_for_config = scope_env or None
    if args.install_claude_desktop:
        _install_mcp_config(_claude_desktop_config_path(), exe, "Claude Desktop", env=env_for_config)
    if args.install_claude_code:
        _install_mcp_config(_claude_code_config_path(), exe, "Claude Code", env=env_for_config)

    if args.print_config:
        print(f"\nAdd this to your MCP host config (Claude Desktop / Cursor / etc.):\n")
        print(_mcp_config(exe, env=env_for_config))
    elif not args.install_claude_desktop and not args.install_claude_code:
        print(f"\nStart the MCP server with:  gmail-mcp")
        print(f"Or run setup with config output:  gmail-mcp-setup --print-config")
