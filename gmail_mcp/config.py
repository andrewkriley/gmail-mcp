"""Paths and environment for Gmail OAuth credentials."""

from __future__ import annotations

import os
from pathlib import Path

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
