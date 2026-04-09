"""Build Google Calendar API client from credentials."""

from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def calendar_service(creds: Credentials):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
