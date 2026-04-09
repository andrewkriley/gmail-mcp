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
    "https://www.googleapis.com/auth/gmail.readonly":       "Read all resources and their metadata — no write operations.",
    "https://www.googleapis.com/auth/gmail.send":           "Send messages only; no read or modify access.",
    "https://www.googleapis.com/auth/gmail.compose":        "Create, read, update, and delete drafts; send messages.",
    "https://www.googleapis.com/auth/gmail.insert":         "Insert and import messages.",
    "https://www.googleapis.com/auth/gmail.labels":         "Create, read, update, and delete labels only.",
    "https://www.googleapis.com/auth/gmail.metadata":       "Read resources metadata including labels, history, profile; no message body.",
    "https://www.googleapis.com/auth/gmail.modify":         "All read/write except permanent delete and settings (used in trash mode).",
    "https://www.googleapis.com/auth/gmail.settings.basic": "Manage basic settings: filters, vacation responder, signature, IMAP/POP.",
    "https://mail.google.com/":                             "Full account access including permanent delete (used in full mode).",
}


# Each entry: (label, set_of_granting_scope_substrings, capabilities_when_missing)
# A feature is available if ANY of the granting scopes (or the full-access scope) is present.
_SCOPE_FEATURES: list[tuple[str, set[str], list[str]]] = [
    (
        "Read messages / threads / labels",
        {"gmail.readonly", "gmail.modify", "gmail.compose", "mail.google.com"},
        ["list messages", "get messages", "list threads", "get thread", "list labels"],
    ),
    (
        "Send & modify / trash (trash mode)",
        {"gmail.modify", "mail.google.com"},
        ["send message", "trash messages", "modify labels", "create/update drafts"],
    ),
    (
        "Basic settings (trash + full mode)",
        {"gmail.settings.basic", "mail.google.com"},
        ["manage filters", "vacation responder", "signature", "IMAP/POP settings"],
    ),
    (
        "Permanent delete (full mode only)",
        {"mail.google.com"},
        ["permanently delete messages", "batch delete messages", "permanently delete threads"],
    ),
]


def validate_access(token_file: Path | None = None) -> int:
    """
    Load the saved OAuth token, probe the Gmail API, and print a scope report.

    Returns 0 on success, 1 on any failure.
    """
    from gmail_mcp.gmail_service import gmail_service

    tok = token_file or token_path()

    # Load credentials without triggering a new OAuth flow.
    try:
        creds = load_credentials(token_file=tok, open_browser=False)
    except FileNotFoundError as exc:
        print(f"\033[1;31m[validate]\033[0m Credentials not found: {exc}", file=sys.stderr)
        print("Run  gmail-mcp-setup  first to authenticate.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\033[1;31m[validate]\033[0m Failed to load credentials: {exc}", file=sys.stderr)
        return 1

    granted: set[str] = set(creds.scopes or [])
    full_scope = "https://mail.google.com/"

    # ── Probe the API ─────────────────────────────────────────────────────────
    print("\n\033[1;34m[validate]\033[0m Testing Gmail API connectivity…")
    try:
        svc = gmail_service(creds)
        profile = svc.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "<unknown>")
        messages_total = profile.get("messagesTotal", "?")
        print(f"\033[1;32m[validate]\033[0m Connected  ✓  ({email}, {messages_total} messages)")
    except Exception as exc:
        print(f"\033[1;31m[validate]\033[0m API call failed: {exc}", file=sys.stderr)
        return 1

    # ── Scope report ─────────────────────────────────────────────────────────
    print("\n\033[1;34m[validate]\033[0m Granted OAuth scopes:")
    if granted:
        for s in sorted(granted):
            print(f"  • {s}")
    else:
        print("  (none reported — token may be opaque)")

    def _has_any_scope(granted: set[str], fragments: set[str]) -> bool:
        """True if any granted scope URL contains any of the given fragments."""
        return any(frag in g for frag in fragments for g in granted)

    print("\n\033[1;34m[validate]\033[0m Feature availability:")
    for label, granting_scopes, capabilities in _SCOPE_FEATURES:
        has_scope = _has_any_scope(granted, granting_scopes)
        status = "\033[1;32mavailable\033[0m" if has_scope else "\033[1;33munavailable\033[0m"
        print(f"  {status}  {label}")
        if not has_scope:
            # Only print capabilities for unavailable features so the output stays concise.
            for cap in capabilities:
                print(f"             – {cap}")

    # ── Re-auth hint if needed ────────────────────────────────────────────────
    missing_full = full_scope not in granted
    if missing_full:
        print(
            "\n\033[1;33m[validate]\033[0m Account-settings tools require full scope.\n"
            "  Run:  gmail-mcp-setup\n"
            "  Then restart your MCP client."
        )
    else:
        print("\n\033[1;32m[validate]\033[0m All scopes look good.")

    return 0


def _print_scopes() -> None:
    print("Available Gmail OAuth scope URLs:\n")
    for url, desc in GMAIL_SCOPES.items():
        print(f"  {url}")
        print(f"    {desc}")
    print(
        "\nPre-defined modes:\n"
        "  full     →  mail.google.com (complete access) [default]\n"
        "  mailbox  →  gmail.modify (read/write messages, no account settings)\n"
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
            "  full   mail.google.com + gmail.settings.basic — complete access including\n"
            "         permanent delete and basic settings (default).\n"
            "  trash  gmail.modify + gmail.settings.basic — full mailbox read/write, send,\n"
            "         labels, drafts, basic settings; delete operations use trash only.\n"
            "  custom Specify exact scope URLs with --scopes (run --list-scopes to see options).\n\n"
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
        choices=["trash", "full", "custom"],
        default="full",
        metavar="MODE",
        help=(
            "OAuth scope mode: full (default, mail.google.com + settings.basic), "
            "trash (gmail.modify + settings.basic, no permanent delete), "
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
    p.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Test the saved OAuth token against the Gmail API and print a scope/feature "
            "availability report. Exits 0 on success, 1 on failure."
        ),
    )
    args = p.parse_args()

    # --list-scopes: print available scope URLs and exit
    if args.list_scopes:
        _print_scopes()
        sys.exit(0)

    # --validate: probe the API and report scope coverage, then exit
    if args.validate:
        tok = Path(args.token) if args.token else None
        sys.exit(validate_access(token_file=tok))

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
    elif args.scope in ("full", "trash"):
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
