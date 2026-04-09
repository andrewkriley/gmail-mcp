"""FastMCP server exposing Gmail read/write operations."""

from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from email.message import EmailMessage
from typing import Any

import anyio
from google.oauth2.credentials import Credentials
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from gmail_mcp.auth import load_credentials
from gmail_mcp.calendar_service import calendar_service
from gmail_mcp.config import CALENDAR_SCOPE, client_secret_path, token_path
from gmail_mcp.gmail_service import gmail_service


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _log(event: str) -> None:
    """Write a timestamped connection event to GMAIL_MCP_LOG if set."""
    import os
    log_path = os.environ.get("GMAIL_MCP_LOG", "").strip()
    if not log_path:
        return
    import datetime
    import os as _os
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"{ts} pid={_os.getpid()} {event}\n"
    try:
        with open(log_path, "a") as f:
            f.write(line)
    except OSError:
        pass


def _creds(ctx: Context) -> Credentials:
    lc = ctx.request_context.lifespan_context
    if not isinstance(lc, dict):
        raise RuntimeError("Server lifespan context is invalid")
    c = lc.get("credentials")
    if c is None:
        raise RuntimeError("Gmail credentials missing; run gmail-mcp-setup or restart after OAuth")
    return c  # type: ignore[return-value]


_FULL_SCOPE = "https://mail.google.com/"


def _svc(ctx: Context):
    return gmail_service(_creds(ctx))


def _require_full_scope(ctx: Context) -> None:
    """Raise a clear error when the stored token lacks the full mail scope (permanent delete)."""
    creds = _creds(ctx)
    granted = set(creds.scopes or [])
    if _FULL_SCOPE not in granted:
        raise PermissionError(
            "This operation requires the 'https://mail.google.com/' OAuth scope (full mode). "
            "Re-authenticate with GMAIL_MCP_SCOPE_MODE=full (or run gmail-mcp-setup --scope full) "
            "and restart the server. In trash mode, use gmail_trash_message / gmail_trash_thread instead."
        )


def _require_calendar_scope(ctx: Context) -> None:
    """Raise a clear error when the stored token lacks the Google Calendar scope."""
    creds = _creds(ctx)
    granted = set(creds.scopes or [])
    if CALENDAR_SCOPE not in granted:
        raise PermissionError(
            "This operation requires the 'https://www.googleapis.com/auth/calendar' OAuth scope. "
            "Re-authenticate with GMAIL_MCP_SCOPE_MODE=google (or run gmail-mcp-setup --scope google) "
            "and restart the server."
        )


def _cal_svc(ctx: Context):
    _require_calendar_scope(ctx)
    return calendar_service(_creds(ctx))


@asynccontextmanager
async def _lifespan(_app: FastMCP):
    """Load OAuth token at startup (opens browser if first run).

    Stdout is redirected to stderr during credential loading because this
    server uses stdio transport (stdout = JSON-RPC channel).  Any print()
    call inside the OAuth library (e.g. the authorization-URL prompt in
    InstalledAppFlow.run_local_server) would otherwise emit a bare line that
    the MCP client tries to parse as JSON and fails with EOF/invalid-JSON.
    """
    import sys

    def _sync_load() -> Credentials:
        old_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            return load_credentials(
                client_secret_file=client_secret_path(),
                token_file=token_path(),
                open_browser=True,
            )
        finally:
            sys.stdout = old_stdout

    _log("connected")
    credentials = await anyio.to_thread.run_sync(_sync_load)
    yield {"credentials": credentials}
    _log("disconnected")


mcp = FastMCP(
    "gmail",
    instructions=(
        "Gmail via Gmail API v1. Two scope modes: trash (gmail.modify + gmail.settings.basic — "
        "full mailbox + basic settings, delete ops use trash) and full (mail.google.com + "
        "gmail.settings.basic — adds permanent delete). Default is full. "
        "Tokens from `gmail-mcp-setup` or server startup; raw send payloads are base64url-encoded RFC 2822."
    ),
    lifespan=_lifespan,
)

_write = ToolAnnotations(destructiveHint=True)
_read = ToolAnnotations(readOnlyHint=True)



@mcp.tool(annotations=_read)
def gmail_get_attachment(ctx: Context, message_id: str, attachment_id: str) -> str:
    """Download a message attachment by message id and attachment id."""
    att = (
        _svc(ctx)
        .users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )
    return _json(att)


@mcp.tool(annotations=_write)
def gmail_send_message(
    ctx: Context,
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Compose and send an email (plain text, optional HTML part)."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    body: dict[str, Any] = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    sent = _svc(ctx).users().messages().send(userId="me", body=body).execute()
    return _json(sent)


@mcp.tool(annotations=_write)
def gmail_send_raw(ctx: Context, raw_base64url: str, thread_id: str | None = None) -> str:
    """Send a message from an RFC 2822 payload already base64url-encoded (advanced)."""
    body: dict[str, Any] = {"raw": raw_base64url}
    if thread_id:
        body["threadId"] = thread_id
    sent = _svc(ctx).users().messages().send(userId="me", body=body).execute()
    return _json(sent)


@mcp.tool(annotations=_write)
def gmail_modify_message(
    ctx: Context,
    message_id: str,
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> str:
    """Add/remove labels on a message (e.g. INBOX, UNREAD, STARRED or custom label ids)."""
    body: dict[str, Any] = {}
    if add_label_ids:
        body["addLabelIds"] = add_label_ids
    if remove_label_ids:
        body["removeLabelIds"] = remove_label_ids
    out = _svc(ctx).users().messages().modify(userId="me", id=message_id, body=body).execute()
    return _json(out)


@mcp.tool(annotations=_write)
def gmail_trash_message(ctx: Context, message_id: str) -> str:
    """Move a message to trash."""
    return _json(_svc(ctx).users().messages().trash(userId="me", id=message_id).execute())


@mcp.tool(annotations=_write)
def gmail_untrash_message(ctx: Context, message_id: str) -> str:
    """Restore a message from trash."""
    return _json(_svc(ctx).users().messages().untrash(userId="me", id=message_id).execute())


@mcp.tool(annotations=_write)
def gmail_delete_message(ctx: Context, message_id: str) -> str:
    """Permanently delete a message. Requires full mail scope (https://mail.google.com/)."""
    _require_full_scope(ctx)
    _svc(ctx).users().messages().delete(userId="me", id=message_id).execute()
    return _json({"ok": True, "id": message_id})


@mcp.tool(annotations=_write)
def gmail_batch_modify_messages(
    ctx: Context,
    message_ids: list[str],
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> str:
    """Batch add/remove labels on multiple messages."""
    body: dict[str, Any] = {"ids": message_ids}
    if add_label_ids:
        body["addLabelIds"] = add_label_ids
    if remove_label_ids:
        body["removeLabelIds"] = remove_label_ids
    _svc(ctx).users().messages().batchModify(userId="me", body=body).execute()
    return _json({"ok": True, "count": len(message_ids)})


@mcp.tool(annotations=_write)
def gmail_batch_delete_messages(ctx: Context, message_ids: list[str]) -> str:
    """Permanently delete multiple messages. `message_ids` is a required list of Gmail message ID strings, e.g. ["18abc", "18def"]. Requires full mail scope (https://mail.google.com/)."""
    _require_full_scope(ctx)
    _svc(ctx).users().messages().batchDelete(userId="me", body={"ids": message_ids}).execute()
    return _json({"ok": True, "count": len(message_ids)})


@mcp.tool(annotations=_read)
def gmail_get_label(ctx: Context, label_id: str) -> str:
    """Get metadata for one label by id."""
    return _json(_svc(ctx).users().labels().get(userId="me", id=label_id).execute())


@mcp.tool(annotations=_write)
def gmail_create_label(
    ctx: Context,
    name: str,
    message_list_visibility: str | None = None,
    label_list_visibility: str | None = None,
) -> str:
    """Create a user label. visibility values: show|hide."""
    body: dict[str, Any] = {"name": name, "type": "user"}
    if message_list_visibility:
        body["messageListVisibility"] = message_list_visibility
    if label_list_visibility:
        body["labelListVisibility"] = label_list_visibility
    return _json(_svc(ctx).users().labels().create(userId="me", body=body).execute())


@mcp.tool(annotations=_write)
def gmail_update_label(
    ctx: Context,
    label_id: str,
    name: str | None = None,
    message_list_visibility: str | None = None,
    label_list_visibility: str | None = None,
) -> str:
    """Patch a label (partial update)."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if message_list_visibility is not None:
        body["messageListVisibility"] = message_list_visibility
    if label_list_visibility is not None:
        body["labelListVisibility"] = label_list_visibility
    return _json(_svc(ctx).users().labels().patch(userId="me", id=label_id, body=body).execute())


@mcp.tool(annotations=_write)
def gmail_delete_label(ctx: Context, label_id: str) -> str:
    """Delete a user label by id."""
    _svc(ctx).users().labels().delete(userId="me", id=label_id).execute()
    return _json({"ok": True, "id": label_id})


@mcp.tool(annotations=_read)
def gmail_list_threads(
    ctx: Context,
    query: str | None = None,
    label_ids: list[str] | None = None,
    max_results: int = 50,
    page_token: str | None = None,
    include_spam_trash: bool = False,
) -> str:
    """List conversation threads."""
    svc = _svc(ctx)
    kwargs: dict[str, Any] = {
        "userId": "me",
        "maxResults": min(max(1, max_results), 500),
        "includeSpamTrash": include_spam_trash,
    }
    if query:
        kwargs["q"] = query
    if label_ids:
        kwargs["labelIds"] = label_ids
    if page_token:
        kwargs["pageToken"] = page_token
    return _json(svc.users().threads().list(**kwargs).execute())


@mcp.tool(annotations=_write)
def gmail_modify_thread(
    ctx: Context,
    thread_id: str,
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> str:
    """Add/remove labels on all messages in a thread."""
    body: dict[str, Any] = {}
    if add_label_ids:
        body["addLabelIds"] = add_label_ids
    if remove_label_ids:
        body["removeLabelIds"] = remove_label_ids
    return _json(_svc(ctx).users().threads().modify(userId="me", id=thread_id, body=body).execute())


@mcp.tool(annotations=_write)
def gmail_trash_thread(ctx: Context, thread_id: str) -> str:
    """Move a thread to trash."""
    return _json(_svc(ctx).users().threads().trash(userId="me", id=thread_id).execute())


@mcp.tool(annotations=_write)
def gmail_untrash_thread(ctx: Context, thread_id: str) -> str:
    """Restore a thread from trash."""
    return _json(_svc(ctx).users().threads().untrash(userId="me", id=thread_id).execute())


@mcp.tool(annotations=_write)
def gmail_delete_thread(ctx: Context, thread_id: str) -> str:
    """Permanently delete a thread. Requires full mail scope (https://mail.google.com/)."""
    _require_full_scope(ctx)
    _svc(ctx).users().threads().delete(userId="me", id=thread_id).execute()
    return _json({"ok": True, "id": thread_id})


@mcp.tool(annotations=_read)
def gmail_get_draft(ctx: Context, draft_id: str, message_format: str = "full") -> str:
    """Get a draft by id."""
    return _json(_svc(ctx).users().drafts().get(userId="me", id=draft_id, format=message_format).execute())


@mcp.tool(annotations=_write)
def gmail_create_draft(
    ctx: Context,
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Create a draft (same shape as send_message)."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    message: dict[str, Any] = {"raw": raw}
    if thread_id:
        message["threadId"] = thread_id
    return _json(_svc(ctx).users().drafts().create(userId="me", body={"message": message}).execute())


@mcp.tool(annotations=_write)
def gmail_update_draft(
    ctx: Context,
    draft_id: str,
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Replace a draft's message content."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    message: dict[str, Any] = {"raw": raw}
    if thread_id:
        message["threadId"] = thread_id
    return _json(
        _svc(ctx).users().drafts().update(userId="me", id=draft_id, body={"message": message}).execute()
    )


@mcp.tool(annotations=_write)
def gmail_send_draft(ctx: Context, draft_id: str) -> str:
    """Send an existing draft."""
    return _json(_svc(ctx).users().drafts().send(userId="me", body={"id": draft_id}).execute())


@mcp.tool(annotations=_write)
def gmail_delete_draft(ctx: Context, draft_id: str) -> str:
    """Delete a draft."""
    _svc(ctx).users().drafts().delete(userId="me", id=draft_id).execute()
    return _json({"ok": True, "id": draft_id})


@mcp.tool(annotations=_read)
def gmail_list_filters(ctx: Context) -> str:
    """List inbox filters."""
    return _json(_svc(ctx).users().settings().filters().list(userId="me").execute())


@mcp.tool(annotations=_read)
def gmail_get_filter(ctx: Context, filter_id: str) -> str:
    """Get a single filter by id."""
    return _json(_svc(ctx).users().settings().filters().get(userId="me", id=filter_id).execute())


@mcp.tool(annotations=_write)
def gmail_create_filter(ctx: Context, filter_json: str) -> str:
    """Create a filter. `filter_json` is a JSON object matching the Gmail API Filter resource (criteria + action)."""
    body = json.loads(filter_json)
    return _json(_svc(ctx).users().settings().filters().create(userId="me", body=body).execute())


@mcp.tool(annotations=_write)
def gmail_delete_filter(ctx: Context, filter_id: str) -> str:
    """Delete a filter by id."""
    _svc(ctx).users().settings().filters().delete(userId="me", id=filter_id).execute()
    return _json({"ok": True, "id": filter_id})


@mcp.tool(annotations=_read)
def gmail_list_forwarding_addresses(ctx: Context) -> str:
    """List forwarding addresses."""
    return _json(_svc(ctx).users().settings().forwardingAddresses().list(userId="me").execute())


@mcp.tool(annotations=_write)
def gmail_create_forwarding_address(ctx: Context, forwarding_email: str) -> str:
    """Request verification for a forwarding email address."""
    return _json(
        _svc(ctx)
        .users()
        .settings()
        .forwardingAddresses()
        .create(userId="me", body={"forwardingEmail": forwarding_email})
        .execute()
    )


@mcp.tool(annotations=_write)
def gmail_delete_forwarding_address(ctx: Context, forwarding_email: str) -> str:
    """Delete a forwarding address."""
    _svc(ctx).users().settings().forwardingAddresses().delete(userId="me", forwardingEmail=forwarding_email).execute()
    return _json({"ok": True, "forwardingEmail": forwarding_email})


@mcp.tool(annotations=_read)
def gmail_get_auto_forwarding(ctx: Context) -> str:
    """Get auto-forwarding settings."""
    return _json(_svc(ctx).users().settings().getAutoForwarding(userId="me").execute())


@mcp.tool(annotations=_write)
def gmail_update_auto_forwarding(ctx: Context, settings_json: str) -> str:
    """Update auto-forwarding. `settings_json` matches Gmail API AutoForwarding resource."""
    body = json.loads(settings_json)
    return _json(_svc(ctx).users().settings().updateAutoForwarding(userId="me", body=body).execute())


@mcp.tool(annotations=_read)
def gmail_list_send_as(ctx: Context) -> str:
    """List send-as aliases / From addresses."""
    return _json(_svc(ctx).users().settings().sendAs().list(userId="me").execute())


@mcp.tool(annotations=_read)
def gmail_get_send_as(ctx: Context, send_as_email: str) -> str:
    """Get one send-as configuration."""
    return _json(_svc(ctx).users().settings().sendAs().get(userId="me", sendAsEmail=send_as_email).execute())


@mcp.tool(annotations=_write)
def gmail_patch_send_as(ctx: Context, send_as_email: str, patch_json: str) -> str:
    """Patch send-as settings (JSON object with fields to update)."""
    body = json.loads(patch_json)
    return _json(
        _svc(ctx).users().settings().sendAs().patch(userId="me", sendAsEmail=send_as_email, body=body).execute()
    )


@mcp.tool(annotations=_write)
def gmail_verify_send_as(ctx: Context, send_as_email: str) -> str:
    """Send verification for a send-as address."""
    return _json(_svc(ctx).users().settings().sendAs().verify(userId="me", sendAsEmail=send_as_email).execute())


@mcp.tool(annotations=_write)
def gmail_watch_mailbox(ctx: Context, request_json: str) -> str:
    """Set up push notifications (Pub/Sub). `request_json` is a WatchRequest object."""
    body = json.loads(request_json)
    return _json(_svc(ctx).users().watch(userId="me", body=body).execute())


@mcp.tool(annotations=_write)
def gmail_stop_watch(ctx: Context) -> str:
    """Stop receiving push notifications for the mailbox."""
    _svc(ctx).users().stop(userId="me").execute()
    return _json({"ok": True})


# ── Google Calendar tools (require GMAIL_MCP_SCOPE_MODE=google) ───────────────

@mcp.tool(annotations=_write)
def gcal_create_calendar(ctx: Context, summary: str, description: str | None = None, time_zone: str | None = None) -> str:
    """Create a new Google Calendar. Returns the created calendar resource."""
    body: dict[str, Any] = {"summary": summary}
    if description:
        body["description"] = description
    if time_zone:
        body["timeZone"] = time_zone
    return _json(_cal_svc(ctx).calendars().insert(body=body).execute())


@mcp.tool(annotations=_write)
def gcal_update_calendar(
    ctx: Context,
    calendar_id: str,
    summary: str | None = None,
    description: str | None = None,
    time_zone: str | None = None,
) -> str:
    """Update metadata on a calendar (summary, description, time zone). Use 'primary' for your main calendar."""
    body: dict[str, Any] = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if time_zone is not None:
        body["timeZone"] = time_zone
    return _json(_cal_svc(ctx).calendars().patch(calendarId=calendar_id, body=body).execute())


@mcp.tool(annotations=_write)
def gcal_delete_calendar(ctx: Context, calendar_id: str) -> str:
    """Permanently delete a calendar and all its events. Cannot be undone."""
    _cal_svc(ctx).calendars().delete(calendarId=calendar_id).execute()
    return _json({"ok": True, "calendarId": calendar_id})


@mcp.tool(annotations=_write)
def gcal_clear_calendar(ctx: Context, calendar_id: str) -> str:
    """Remove all events from a calendar without deleting the calendar itself. Only works on primary-type calendars."""
    _cal_svc(ctx).calendars().clear(calendarId=calendar_id).execute()
    return _json({"ok": True, "calendarId": calendar_id})


@mcp.tool(annotations=_write)
def gcal_update_calendar_list_entry(
    ctx: Context,
    calendar_id: str,
    color_id: str | None = None,
    background_color: str | None = None,
    foreground_color: str | None = None,
    hidden: bool | None = None,
    selected: bool | None = None,
    default_reminders: str | None = None,
) -> str:
    """Update your personal view of a subscribed calendar (color, visibility, reminders).
    color_id: one of Google's palette IDs (e.g. '1'–'11'). background_color/foreground_color: hex CSS colors.
    default_reminders: JSON array of reminder objects, e.g. '[{"method":"popup","minutes":10}]'."""
    body: dict[str, Any] = {}
    if color_id is not None:
        body["colorId"] = color_id
    if background_color is not None:
        body["backgroundColor"] = background_color
    if foreground_color is not None:
        body["foregroundColor"] = foreground_color
    if hidden is not None:
        body["hidden"] = hidden
    if selected is not None:
        body["selected"] = selected
    if default_reminders is not None:
        body["defaultReminders"] = json.loads(default_reminders)
    return _json(_cal_svc(ctx).calendarList().patch(calendarId=calendar_id, body=body).execute())


@mcp.tool(annotations=_write)
def gcal_remove_calendar(ctx: Context, calendar_id: str) -> str:
    """Unsubscribe from / remove a calendar from your calendar list. Does not delete the calendar itself."""
    _cal_svc(ctx).calendarList().delete(calendarId=calendar_id).execute()
    return _json({"ok": True, "calendarId": calendar_id})


@mcp.tool(annotations=_read)
def gcal_list_acl(ctx: Context, calendar_id: str) -> str:
    """List all access control rules for a calendar (who has access and at what role)."""
    return _json(_cal_svc(ctx).acl().list(calendarId=calendar_id).execute())


@mcp.tool(annotations=_write)
def gcal_create_acl(ctx: Context, calendar_id: str, role: str, scope_type: str, scope_value: str | None = None) -> str:
    """Share a calendar by adding an ACL rule.
    role: 'reader' | 'writer' | 'owner'.
    scope_type: 'user' | 'group' | 'domain' | 'default'.
    scope_value: email address (user/group), domain name, or omit for 'default'."""
    scope: dict[str, Any] = {"type": scope_type}
    if scope_value:
        scope["value"] = scope_value
    body = {"role": role, "scope": scope}
    return _json(_cal_svc(ctx).acl().insert(calendarId=calendar_id, body=body).execute())


@mcp.tool(annotations=_write)
def gcal_update_acl(ctx: Context, calendar_id: str, rule_id: str, role: str) -> str:
    """Change the role on an existing ACL rule. role: 'reader' | 'writer' | 'owner'."""
    return _json(_cal_svc(ctx).acl().update(calendarId=calendar_id, ruleId=rule_id, body={"role": role}).execute())


@mcp.tool(annotations=_write)
def gcal_delete_acl(ctx: Context, calendar_id: str, rule_id: str) -> str:
    """Revoke access by deleting an ACL rule."""
    _cal_svc(ctx).acl().delete(calendarId=calendar_id, ruleId=rule_id).execute()
    return _json({"ok": True, "calendarId": calendar_id, "ruleId": rule_id})


@mcp.tool(annotations=_write)
def gcal_move_event(ctx: Context, calendar_id: str, event_id: str, destination_calendar_id: str) -> str:
    """Move an event from one calendar to another. Returns the updated event."""
    return _json(
        _cal_svc(ctx).events().move(
            calendarId=calendar_id, eventId=event_id, destination=destination_calendar_id
        ).execute()
    )


@mcp.tool(annotations=_write)
def gcal_quick_add(ctx: Context, calendar_id: str, text: str, send_notifications: bool = False) -> str:
    """Create an event from a natural-language string (e.g. 'Lunch with Sam on Tuesday at noon').
    calendar_id: target calendar, use 'primary' for your main calendar."""
    return _json(
        _cal_svc(ctx).events().quickAdd(
            calendarId=calendar_id, text=text, sendNotifications=send_notifications
        ).execute()
    )


def main() -> None:
    mcp.run(transport="stdio")
