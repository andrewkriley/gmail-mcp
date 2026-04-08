"""Paths and environment for Gmail OAuth credentials."""

from __future__ import annotations

import os
from pathlib import Path

# Default XDG-style config directory
_DEFAULT_STATE_DIR = Path.home() / ".config" / "gmail-mcp"


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
