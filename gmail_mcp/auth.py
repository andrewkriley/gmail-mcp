"""Google OAuth 2.0 for Gmail API (installed-app flow)."""

from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gmail_mcp.config import client_secret_path, keychain_load_client_secret, oauth_scopes, token_path

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
    elif secret.is_file():
        client_config = json.loads(secret.read_text(encoding="utf-8"))
    else:
        raise FileNotFoundError(
            f"OAuth client secret not found in Keychain or at {secret}. "
            "Run `gmail-mcp-setup --keychain <path>` to store it in the Keychain, "
            "or save the JSON file from Google Cloud Console at that path."
        )

    creds: Credentials | None = None
    if tok.is_file():
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
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text(creds.to_json(), encoding="utf-8")
