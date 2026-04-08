"""Build Gmail API client from credentials."""

from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
