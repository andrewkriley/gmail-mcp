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
from gmail_mcp.config import client_secret_path, token_path
from gmail_mcp.gmail_service import gmail_service


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


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
    """Raise a clear error when the stored token lacks the full mail scope."""
    creds = _creds(ctx)
    granted = set(creds.scopes or [])
    if _FULL_SCOPE not in granted:
        raise PermissionError(
            "This operation requires the 'https://mail.google.com/' OAuth scope. "
            "Re-authenticate with GMAIL_MCP_SCOPE_MODE=full (or run gmail-mcp-setup --scope full) "
            "and restart the server."
        )


@asynccontextmanager
async def _lifespan(_app: FastMCP):
    """Load OAuth token at startup (opens browser if first run)."""

    def _sync_load() -> Credentials:
        return load_credentials(
            client_secret_file=client_secret_path(),
            token_file=token_path(),
            open_browser=True,
        )

    credentials = await anyio.to_thread.run_sync(_sync_load)
    yield {"credentials": credentials}


mcp = FastMCP(
    "gmail",
    instructions=(
        "Gmail via Gmail API v1. Default OAuth scope is gmail.modify (read/write mailbox, labels, "
        "threads, drafts, send). Account settings tools (filters, forwarding, send-as, watch) need "
        "GMAIL_MCP_SCOPE_MODE=full. Tokens from `gmail-mcp-setup` or server startup; raw send payloads "
        "are base64url-encoded RFC 2822."
    ),
    lifespan=_lifespan,
)

_write = ToolAnnotations(destructiveHint=True)
_read = ToolAnnotations(readOnlyHint=True)


@mcp.tool(annotations=_read)
def gmail_get_profile(ctx: Context) -> str:
    """Return the current Gmail user id and email address."""
    prof = _svc(ctx).users().getProfile(userId="me").execute()
    return _json(prof)


@mcp.tool(annotations=_read)
def gmail_list_messages(
    ctx: Context,
    query: str | None = None,
    label_ids: list[str] | None = None,
    max_results: int = 50,
    page_token: str | None = None,
    include_spam_trash: bool = False,
) -> str:
    """List messages. Optional Gmail search `query` (same syntax as Gmail search box)."""
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
    return _json(svc.users().messages().list(**kwargs).execute())


@mcp.tool(annotations=_read)
def gmail_get_message(ctx: Context, message_id: str, message_format: str = "full") -> str:
    """Get a single message by id. message_format: minimal|full|raw|metadata."""
    msg = _svc(ctx).users().messages().get(userId="me", id=message_id, format=message_format).execute()
    return _json(msg)


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
def gmail_list_labels(ctx: Context) -> str:
    """List all labels."""
    return _json(_svc(ctx).users().labels().list(userId="me").execute())


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


@mcp.tool(annotations=_read)
def gmail_get_thread(ctx: Context, thread_id: str, message_format: str = "full") -> str:
    """Get a thread by id."""
    return _json(
        _svc(ctx).users().threads().get(userId="me", id=thread_id, format=message_format).execute()
    )


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
def gmail_list_drafts(ctx: Context, max_results: int = 50, page_token: str | None = None) -> str:
    """List drafts."""
    kwargs: dict[str, Any] = {"userId": "me", "maxResults": min(max(1, max_results), 500)}
    if page_token:
        kwargs["pageToken"] = page_token
    return _json(_svc(ctx).users().drafts().list(**kwargs).execute())


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


def main() -> None:
    mcp.run(transport="stdio")
