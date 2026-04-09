# gmail-mcp

An [MCP](https://modelcontextprotocol.io/) server that exposes Gmail write operations, settings management, and advanced mailbox tools through the official Gmail API v1 with OAuth 2.0.

> **Designed to complement the Anthropic Gmail connector** — see [Using with Anthropic's Gmail integration](#using-with-anthropics-gmail-integration) below.

---

## What this server provides

This server covers the operations that Anthropic's built-in Gmail connector does not:

| Category | Tools |
|----------|-------|
| **Send** | `gmail_send_message`, `gmail_send_raw`, `gmail_send_draft` |
| **Mutations** | `gmail_modify_message/thread`, `gmail_trash_*`, `gmail_untrash_*`, `gmail_delete_*` |
| **Batch ops** | `gmail_batch_modify_messages`, `gmail_batch_delete_messages` |
| **Drafts** | `gmail_create_draft`, `gmail_get_draft`, `gmail_update_draft`, `gmail_delete_draft` |
| **Labels** | `gmail_get_label`, `gmail_create_label`, `gmail_update_label`, `gmail_delete_label` |
| **Threads** | `gmail_list_threads` |
| **Attachments** | `gmail_get_attachment` |
| **Filters** | `gmail_list_filters`, `gmail_get_filter`, `gmail_create_filter`, `gmail_delete_filter` |
| **Forwarding** | `gmail_list_forwarding_addresses`, `gmail_create_forwarding_address`, `gmail_delete_forwarding_address` |
| **Auto-forward** | `gmail_get_auto_forwarding`, `gmail_update_auto_forwarding` |
| **Send-as** | `gmail_list_send_as`, `gmail_get_send_as`, `gmail_patch_send_as`, `gmail_verify_send_as` |
| **Push watch** | `gmail_watch_mailbox`, `gmail_stop_watch` |

---

## Using with Anthropic's Gmail integration

Claude Code and Claude Desktop include a built-in Gmail connector (via claude.ai integrations). When both are active, they complement each other:

- **Anthropic connector** handles: searching messages, reading messages/threads, listing labels/drafts, creating drafts, and getting your profile.
- **This server** handles: everything write-related, settings management, filters, forwarding, and send-as.

If both are configured, prefer Anthropic's tools for read/search operations and use this server's tools for mutations and settings. Having both avoids tool ambiguity — this server intentionally does **not** duplicate the read/list tools that Anthropic already covers well (e.g. `gmail_list_messages` was removed in favour of Anthropic's `gmail_search_messages`, which has proper Gmail search syntax support).

---

## Prerequisites

Before installing, you need a Google Cloud project. This is a one-time setup.

### Step 1 — Create a Google Cloud project

Go to [console.cloud.google.com](https://console.cloud.google.com/) and select or create a project.

### Step 2 — Enable the Gmail API

Go to **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.

### Step 3 — Configure the OAuth consent screen

Go to **APIs & Services → OAuth consent screen**:
- User Type: **External** → Create
- Fill in App name and support email → Save and Continue (scopes and test users screens can be left as-is for now)
- Back on the consent screen page, click **Publish App** → Confirm, OR go to **Test users** and add your Google account (required if you leave the app in Testing mode)

### Step 4 — Create OAuth credentials

Go to **APIs & Services → Credentials**:
- Create Credentials → **OAuth client ID**
- Application type: **Desktop app** → Create
- Download JSON (the download button on the right of the new credential)

Leave the downloaded file in `~/Downloads` (Google names it `client_secret*.json`) **or** move it to `~/.config/gmail-mcp/client_secret.json`.

---

## Install

```bash
# If you've already cloned the repo:
bash install.sh

# Or run directly without cloning:
curl -fsSL https://raw.githubusercontent.com/andrewkriley/gmail-mcp/main/install.sh | bash
```

The installer:
- Creates a `.venv` inside the repo directory (uses `uv` if available, otherwise `pip`)
- Finds your `client_secret*.json` automatically
- Runs the OAuth browser flow
- Auto-detects Claude Desktop and Claude Code and writes the MCP config

### Installer flags

```bash
bash install.sh --no-setup        # install only, skip OAuth
bash install.sh --headless        # OAuth via printed URL (no browser)
bash install.sh --claude-desktop  # force config into Claude Desktop
bash install.sh --claude-code     # force config into Claude Code
bash install.sh --no-client       # skip client config entirely
bash install.sh --change-scope    # change OAuth scope interactively after setup
bash install.sh --fresh           # wipe all credentials and MCP config, then reinstall
```

---

## Manual install

### With uv (recommended)

```bash
uv tool install -e .
```

### With pipx

```bash
pipx install -e .
```

### With pip

```bash
pip install -e .
```

---

## Authenticate

Run the setup helper. It searches `~/Downloads` for a `client_secret*.json`, copies it to `~/.config/gmail-mcp/`, and opens a browser for consent:

```bash
gmail-mcp-setup
```

Pass the file explicitly if needed:

```bash
gmail-mcp-setup ~/Downloads/client_secret_*.json
gmail-mcp-setup --client-secret ~/Downloads/client_secret_*.json
```

For headless / SSH environments:

```bash
gmail-mcp-setup --no-browser
```

### Print MCP config

```bash
gmail-mcp-setup --print-config
```

Output example:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "/Users/you/gmail-mcp/.venv/bin/gmail-mcp"
    }
  }
}
```

---

## Client config

Add the server entry to your MCP host config. Run `gmail-mcp-setup --print-config` to get the exact block (always includes the full path), or use:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "/full/path/to/gmail-mcp/.venv/bin/gmail-mcp"
    }
  }
}
```

**Claude Code** config is at `~/.claude.json`. **Claude Desktop** config is at `~/Library/Application Support/Claude/claude_desktop_config.json`.

Restart your MCP client after any config change. In Claude Code, exit and re-run `claude`.

---

## OAuth scopes

| Mode | Env var | Scopes granted |
|------|---------|----------------|
| **full** (default) | `GMAIL_MCP_SCOPE_MODE=full` | `https://mail.google.com/` + `gmail.settings.basic` — complete access including permanent delete |
| **trash** | `GMAIL_MCP_SCOPE_MODE=trash` | `gmail.modify` + `gmail.settings.basic` — full mailbox read/write; delete moves to trash only |
| **custom** | `GMAIL_MCP_SCOPES=url1,url2` | Exact URLs you specify (overrides `SCOPE_MODE`) |

Default is `full`. If you need to restrict permanent deletes, use `trash` mode.

To change scope, re-run setup (or delete `token.json`) so Google re-consents:

```bash
gmail-mcp-setup --scope trash
# or
GMAIL_MCP_SCOPE_MODE=trash gmail-mcp-setup
```

---

## Scope troubleshooting

**"Insufficient Permission" or 403 errors on settings tools (filters, forwarding, send-as)**

The stored token was issued without `gmail.settings.basic`. Re-authenticate:

```bash
rm ~/.config/gmail-mcp/token.json
gmail-mcp-setup
```

**"This operation requires the 'https://mail.google.com/' OAuth scope"**

You're in `trash` scope mode but called a permanent-delete tool. Either switch to `full` mode or use `gmail_trash_message` / `gmail_trash_thread` instead:

```bash
gmail-mcp-setup --scope full
```

**Scope change not taking effect**

The old token is still cached. Delete it and re-authenticate:

```bash
# macOS (keychain)
gmail-mcp-setup --delete-keychain-token

# All platforms (file fallback)
rm ~/.config/gmail-mcp/token.json

gmail-mcp-setup
```

Then restart your MCP client.

**OAuth consent shows "App not verified" warning**

This is expected for personal-use apps in Testing mode. Click **Advanced → Go to [App name] (unsafe)** to proceed. To remove the warning, publish the app in the OAuth consent screen (only appropriate if you trust all users who will connect).

**Token expires / refresh fails**

Delete `token.json` (and keychain entry on macOS) and re-run `gmail-mcp-setup`. The refresh token can be invalidated if you revoke access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions) or if the OAuth app is in Testing mode and the 7-day refresh limit is hit — re-publishing the app resolves the 7-day limit.

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `GMAIL_MCP_STATE_DIR` | Directory for `client_secret.json` / `token.json` (default: `~/.config/gmail-mcp`) |
| `GMAIL_MCP_CLIENT_SECRET` | Path to OAuth client secret JSON |
| `GMAIL_MCP_TOKEN` | Path to the saved OAuth token JSON |
| `GMAIL_MCP_SCOPE_MODE` | `full` (default) or `trash` |
| `GMAIL_MCP_SCOPES` | Comma-separated OAuth scope URLs (overrides `SCOPE_MODE`) |
| `GMAIL_MCP_NO_KEYCHAIN` | Set to `1` to disable macOS keychain storage and use plaintext files instead |
| `GMAIL_MCP_LOG` | Path to a log file for connection events (optional) |

---

## Security

The default `full` scope token can **read, send, permanently delete mail**, manage labels, and change account settings. Protect `~/.config/gmail-mcp/token.json` (permissions are set to `600` automatically). On macOS, credentials are stored in the system keychain by default. Use a dedicated OAuth client ID rather than a shared one where possible.
