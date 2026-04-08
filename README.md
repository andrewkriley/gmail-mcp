# gmail-mcp

An [MCP](https://modelcontextprotocol.io/) server that exposes Gmail through the official Gmail API v1 with OAuth 2.0. It includes tools for messages, threads, labels, drafts, filters, send-as aliases, forwarding, and mailbox watch.

## Prerequisites

1. A Google Cloud project with **Gmail API** enabled.
2. OAuth **Desktop app** credentials (download the client JSON).
3. If the app is in testing, add your Google account under **OAuth consent screen → Test users**.

### OAuth scopes

By default the server requests **`https://www.googleapis.com/auth/gmail.modify`**: read all mail, send, change labels, trash/delete messages, manage drafts and user-created labels—**not** account settings (filters, forwarding, send-as) or **watch** (Pub/Sub).

| Mode | How | Scopes |
|------|-----|--------|
| **Mailbox (default)** | _(unset)_ or `GMAIL_MCP_SCOPE_MODE=mailbox` | `gmail.modify` |
| **Full / admin tools** | `GMAIL_MCP_SCOPE_MODE=full` | `https://mail.google.com/` |
| **Custom** | `GMAIL_MCP_SCOPES` = comma-separated URLs | _(your list)_ |

Add the scope URLs you use to the OAuth consent screen in Google Cloud. If you change scope mode, run `gmail-mcp-setup` again (or delete `token.json`) so Google re-consents.

**Stricter read-only:** you can set e.g. `GMAIL_MCP_SCOPES=https://www.googleapis.com/auth/gmail.readonly`—then only list/get tools work; send/modify/delete will return API errors.

## Install

```bash
pip install -e .
```

Or install from the built wheel in `dist/`.

## Authenticate (setup)

Put your Desktop client secret JSON at `~/.config/gmail-mcp/client_secret.json`, or set `GMAIL_MCP_CLIENT_SECRET` to its path.

Run the setup helper (opens a browser by default):

```bash
gmail-mcp-setup
```

For headless/SSH, use:

```bash
gmail-mcp-setup --no-browser
```

The refresh token is stored at `~/.config/gmail-mcp/token.json` unless you pass `--token` or set `GMAIL_MCP_TOKEN`.

**First connection:** If you skip `gmail-mcp-setup`, starting the MCP server will run the same OAuth flow during startup (browser opens once).

## Run the server

Stdio transport (typical for MCP hosts):

```bash
gmail-mcp
```

Or:

```bash
python -m gmail_mcp
```

## Cursor / Claude Desktop

Add a server entry that runs the command above, for example:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "gmail-mcp",
      "env": {}
    }
  }
}
```

Use the full path to `gmail-mcp` if it is not on `PATH`.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `GMAIL_MCP_STATE_DIR` | Directory for default `client_secret.json` / `token.json` (default: `~/.config/gmail-mcp`) |
| `GMAIL_MCP_CLIENT_SECRET` | Path to OAuth client secret JSON |
| `GMAIL_MCP_TOKEN` | Path to the saved OAuth token JSON |
| `GMAIL_MCP_SCOPE_MODE` | `mailbox` (default) or `full` for settings + watch tools |
| `GMAIL_MCP_SCOPES` | Comma-separated OAuth scope URLs (overrides `SCOPE_MODE` when set) |

## Security

With the default scope, the token can still **read, send, and delete mail** and manage labels. With `SCOPE_MODE=full`, it can also change **filters, forwarding, send-as**, and enable **push watch**. Run only in environments you trust, protect `token.json`, and use a dedicated OAuth client where possible.
