"""Google OAuth 2.0 for Gmail API (installed-app flow)."""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gmail_mcp.config import client_secret_path, token_path

# Full Gmail access for administration (send, read, modify, settings, filters, etc.)
SCOPES = ["https://mail.google.com/"]


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

    if not secret.is_file():
        raise FileNotFoundError(
            f"OAuth client secret not found at {secret}. "
            "Download JSON credentials from Google Cloud Console (Desktop app) "
            "and save as that path, or set GMAIL_MCP_CLIENT_SECRET."
        )

    creds: Credentials | None = None
    if tok.is_file():
        creds = Credentials.from_authorized_user_file(str(tok), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, tok)
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    if open_browser:
        creds = flow.run_local_server(port=0, open_browser=True)
    else:
        creds = flow.run_console()

    _save_token(creds, tok)
    return creds


def _save_token(creds: Credentials, tok: Path) -> None:
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text(creds.to_json(), encoding="utf-8")
