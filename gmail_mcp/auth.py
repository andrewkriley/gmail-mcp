"""Google OAuth 2.0 for Gmail API (installed-app flow)."""

from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gmail_mcp.config import (
    client_secret_path,
    keychain_delete_token,
    keychain_load_client_secret,
    keychain_load_token,
    keychain_save_client_secret,
    keychain_save_token,
    oauth_scopes,
    token_path,
    use_keychain_token,
)

_FULL_MAIL_SCOPE = "https://mail.google.com/"


def _granted_covers_requested(granted: set[str], required: list[str]) -> bool:
    """True if stored token can satisfy the OAuth scopes we need for this run."""
    if _FULL_MAIL_SCOPE in granted:
        return True
    return not (set(required) - granted)


def load_credentials(
    *,
    client_secret_file: Path | None = None,
    token_file: Path | None = None,
    open_browser: bool = True,
) -> Credentials:
    """
    Load saved OAuth token or run the installed-app consent flow.

    If no valid token exists, opens the system browser (unless open_browser=False,
    in which case a URL is printed for manual visit — useful over SSH).
    """
    secret = client_secret_file or client_secret_path()
    tok = token_file or token_path()
    scopes = oauth_scopes()

    # Resolve the client secret: keychain takes priority over the file.
    keychain_json = keychain_load_client_secret()
    if keychain_json:
        client_config = json.loads(keychain_json)
        # macOS: delete any leftover plaintext file — keychain is the source of truth.
        if use_keychain_token() and secret.is_file():
            secret.unlink(missing_ok=True)
    elif secret.is_file():
        raw = secret.read_text(encoding="utf-8")
        client_config = json.loads(raw)
        # macOS: auto-migrate to keychain on first use and remove the plaintext file.
        if use_keychain_token():
            keychain_save_client_secret(raw)
            secret.unlink(missing_ok=True)
    else:
        raise FileNotFoundError(
            f"OAuth client secret not found in Keychain or at {secret}. "
            "Run `gmail-mcp-setup --keychain <path>` to store it in the Keychain, "
            "or save the JSON file from Google Cloud Console at that path."
        )

    creds: Credentials | None = None

    # On macOS, prefer keychain over file; fall back to file for migration.
    if use_keychain_token():
        keychain_json = keychain_load_token()
        if keychain_json:
            creds = Credentials.from_authorized_user_info(json.loads(keychain_json), scopes)
        elif tok.is_file():
            # Migrate existing file token into keychain on first run.
            creds = Credentials.from_authorized_user_file(str(tok), scopes)
    elif tok.is_file():
        creds = Credentials.from_authorized_user_file(str(tok), scopes)

    granted = set(creds.scopes or []) if creds else set()
    if creds and creds.valid and _granted_covers_requested(granted, scopes):
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, tok)
        granted = set(creds.scopes or [])
        if creds.valid and _granted_covers_requested(granted, scopes):
            return creds
        creds = None

    flow = InstalledAppFlow.from_client_config(client_config, scopes)
    if open_browser:
        creds = flow.run_local_server(port=0, open_browser=True)
    else:
        creds = flow.run_console()

    _save_token(creds, tok)
    return creds


def _save_token(creds: Credentials, tok: Path) -> None:
    token_json = creds.to_json()
    if use_keychain_token():
        keychain_save_token(token_json)
        # Remove the plaintext file if it exists to avoid stale copies.
        if tok.is_file():
            tok.unlink(missing_ok=True)
    else:
        tok.parent.mkdir(parents=True, exist_ok=True)
        tok.write_text(token_json, encoding="utf-8")
        tok.chmod(0o600)
