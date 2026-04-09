"""Paths and environment for Gmail OAuth credentials."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KEYCHAIN_SERVICE = "gmail-mcp"
_KEYCHAIN_CLIENT_SECRET = "client_secret"
_KEYCHAIN_TOKEN = "token"


def _keyring_available() -> bool:
    try:
        import keyring  # noqa: F401
        return True
    except ImportError:
        return False


def use_keychain_token() -> bool:
    """Return True when OAuth token should be stored/read from the system keychain.

    Enabled by default on macOS. Opt out by setting GMAIL_MCP_NO_KEYCHAIN=1.
    """
    if os.environ.get("GMAIL_MCP_NO_KEYCHAIN", "").strip() == "1":
        return False
    return sys.platform == "darwin" and _keyring_available()


def keychain_save_client_secret(json_text: str) -> None:
    import keyring
    keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_CLIENT_SECRET, json_text)


def keychain_load_client_secret() -> str | None:
    try:
        import keyring
        return keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_CLIENT_SECRET)
    except Exception:
        return None


def keychain_delete_client_secret() -> None:
    import keyring
    keyring.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_CLIENT_SECRET)


def keychain_save_token(json_text: str) -> None:
    import keyring
    keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_TOKEN, json_text)


def keychain_load_token() -> str | None:
    try:
        import keyring
        return keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_TOKEN)
    except Exception:
        return None


def keychain_delete_token() -> None:
    import keyring
    keyring.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_TOKEN)

# Default XDG-style config directory
_DEFAULT_STATE_DIR = Path.home() / ".config" / "gmail-mcp"

# OAuth scope sets (Gmail API)
_SCOPE_MAILBOX = ["https://www.googleapis.com/auth/gmail.modify"]
_SCOPE_FULL = ["https://mail.google.com/"]


def oauth_scopes() -> list[str]:
    """
    Scopes requested at OAuth time.

    - Default (mailbox): gmail.modify — read/write messages, labels, threads, drafts,
      send; does not include account settings (filters, forwarding, send-as) or watch.
    - GMAIL_MCP_SCOPE_MODE=full: https://mail.google.com/ — same breadth as before
      (all tools).

    Override with comma-separated GMAIL_MCP_SCOPES (non-empty) to set exact URLs.
    """
    raw = os.environ.get("GMAIL_MCP_SCOPES", "").strip()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]

    mode = os.environ.get("GMAIL_MCP_SCOPE_MODE", "mailbox").strip().lower()
    if mode in ("full", "admin", "all"):
        return list(_SCOPE_FULL)
    if mode == "mailbox":
        return list(_SCOPE_MAILBOX)
    raise ValueError(
        f"Invalid GMAIL_MCP_SCOPE_MODE={mode!r}. Use 'mailbox' (default) or 'full'."
    )


def state_dir() -> Path:
    base = os.environ.get("GMAIL_MCP_STATE_DIR", "").strip()
    path = Path(base) if base else _DEFAULT_STATE_DIR
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def client_secret_path() -> Path:
    override = os.environ.get("GMAIL_MCP_CLIENT_SECRET", "").strip()
    if override:
        return Path(override).expanduser()
    return state_dir() / "client_secret.json"


def token_path() -> Path:
    override = os.environ.get("GMAIL_MCP_TOKEN", "").strip()
    if override:
        return Path(override).expanduser()
    return state_dir() / "token.json"
