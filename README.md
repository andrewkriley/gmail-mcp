# gmail-mcp

An [MCP](https://modelcontextprotocol.io/) server that exposes Gmail through the official Gmail API v1 with OAuth 2.0. It includes tools for messages, threads, labels, drafts, filters, send-as aliases, forwarding, and mailbox watch.

## Prerequisites

1. A Google Cloud project with **Gmail API** enabled.
2. OAuth **Desktop app** credentials (download the client JSON).
3. If the app is in testing, add your Google account under **OAuth consent screen → Test users**.

The server requests the `https://mail.google.com/` scope so clients can send, read, and manage mail and settings (same breadth as the Gmail web client for that account).

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

## Security

This server can read, send, and delete mail and change account settings. Run it only in environments you trust, protect `token.json`, and use a dedicated Google Cloud OAuth client per machine or team.
