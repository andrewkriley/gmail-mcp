# gmail-mcp

An [MCP](https://modelcontextprotocol.io/) server that exposes Gmail through the official Gmail API v1 with OAuth 2.0. It includes tools for messages, threads, labels, drafts, filters, send-as aliases, forwarding, and mailbox watch.

## Quickstart

**1. Download your OAuth credentials** from [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
> APIs & Services → Credentials → Create credentials → OAuth client ID → Desktop app → Download JSON

Leave the downloaded file in `~/Downloads` (name stays `client_secret*.json`) **or** move it to `~/.config/gmail-mcp/client_secret.json`.

**2. Run the installer:**

```bash
bash install.sh
```

The script finds the credentials automatically, runs the OAuth flow, and prints the JSON block to paste into your MCP host config.

**3. Paste the printed JSON** into your MCP host config (Claude Desktop / Cursor) and restart it.

---

## Prerequisites

- A Google Cloud project with **Gmail API** enabled.
- If the OAuth app is in **Testing** mode, add your Google account under **OAuth consent screen → Test users**.

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

Run the setup helper. It automatically searches `~/Downloads` for a `client_secret*.json` file (the default name Google gives downloaded credentials), copies it to `~/.config/gmail-mcp/`, and opens a browser for consent:

```bash
gmail-mcp-setup
```

You can also pass the file directly (positional or flag):

```bash
gmail-mcp-setup ~/Downloads/client_secret_*.json
gmail-mcp-setup --client-secret ~/Downloads/client_secret_*.json
```

For headless / SSH environments:

```bash
gmail-mcp-setup --no-browser
```

### Print MCP config after setup

```bash
gmail-mcp-setup --print-config
```

Output (example):

```json
{
  "mcpServers": {
    "gmail": {
      "command": "/home/user/.local/bin/gmail-mcp"
    }
  }
}
```

The token is saved at `~/.config/gmail-mcp/token.json`. If you skip `gmail-mcp-setup`, the MCP server runs the same OAuth flow on first startup.

---

## Cursor / Claude Desktop

Add the server entry to your MCP host config. Run `gmail-mcp-setup --print-config` to get the exact block, or use the template below:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "gmail-mcp"
    }
  }
}
```

Use the full path to `gmail-mcp` if it is not on `PATH` (the `--print-config` flag always outputs the full path).

---

## OAuth scopes

By default the server requests **`gmail.modify`**: read all mail, send, change labels, trash/delete messages, manage drafts and user-created labels — but **not** account settings (filters, forwarding, send-as) or watch (Pub/Sub).

| Mode | How | Scopes |
|------|-----|--------|
| **Mailbox (default)** | _(unset)_ or `GMAIL_MCP_SCOPE_MODE=mailbox` | `gmail.modify` |
| **Full / admin tools** | `GMAIL_MCP_SCOPE_MODE=full` | `https://mail.google.com/` |
| **Custom** | `GMAIL_MCP_SCOPES` = comma-separated URLs | _(your list)_ |

If you change the scope mode, run `gmail-mcp-setup` again (or delete `token.json`) so Google re-consents.

**Read-only:** set `GMAIL_MCP_SCOPES=https://www.googleapis.com/auth/gmail.readonly` — only list/get tools will work.

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `GMAIL_MCP_STATE_DIR` | Directory for `client_secret.json` / `token.json` (default: `~/.config/gmail-mcp`) |
| `GMAIL_MCP_CLIENT_SECRET` | Path to OAuth client secret JSON |
| `GMAIL_MCP_TOKEN` | Path to the saved OAuth token JSON |
| `GMAIL_MCP_SCOPE_MODE` | `mailbox` (default) or `full` for settings + watch tools |
| `GMAIL_MCP_SCOPES` | Comma-separated OAuth scope URLs (overrides `SCOPE_MODE` when set) |

---

## Security

With the default scope, the token can **read, send, and delete mail** and manage labels. With `SCOPE_MODE=full`, it can also change **filters, forwarding, send-as**, and enable **push watch**. Run only in environments you trust, protect `token.json`, and use a dedicated OAuth client where possible.
