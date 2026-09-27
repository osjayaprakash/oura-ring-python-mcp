# Installing oura-ring-python-mcp

This guide takes you from nothing to asking Claude "how did I sleep last night?". It takes
about 15 minutes, most of it creating the Oura application.

## 1. Prerequisites

- **An Oura Ring** synced with the Oura app. Gen3 and Oura Ring 4 need an active Oura
  membership for the API to return data.
- **[uv](https://docs.astral.sh/uv/)**, which installs Python 3.11+ and the dependencies
  for you:

  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # or, with Homebrew
  brew install uv
  ```

  ```powershell
  # Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

- **An MCP client**, such as Claude Desktop or Claude Code.

## 2. Create an Oura API application

Oura has deprecated personal access tokens, so this server signs in with OAuth2 using an
application you register. Only you will use it, so the details can be simple.

1. Open Oura's developer portal from <https://cloud.ouraring.com/oauth/applications>
   (new applications are created in the new portal it links to) and sign in with your
   Oura account.
2. Create an application. For the website and privacy/terms URLs, your GitHub profile
   or this repository's URL is fine.
3. Add this **redirect URI** exactly as written:

   ```
   http://localhost:47651/callback
   ```

4. Allow the scopes `email`, `personal`, `daily`, `heartrate`, `workout`, `session`,
   `spo2` and `stress`. (Oura's docs don't list `stress`, but daily resilience needs it.)
5. Save, then note the **client ID** and **client secret**. Treat the secret like a
   password.

## 3. Download and install

```bash
git clone https://github.com/osjayaprakash/oura-ring-python-mcp.git
cd oura-ring-python-mcp
uv sync
```

Note the full path of this folder; you'll need it below:

```bash
pwd
```

## 4. Sign in to Oura

```bash
OURA_CLIENT_ID='your-client-id' \
OURA_CLIENT_SECRET='your-client-secret' \
uv run oura-ring-python-mcp auth
```

Your browser opens Oura's sign-in page. Sign in and allow access; the page then says
"Oura sign-in received", and the command prints where it saved the tokens
(`~/.config/oura-ring-mcp/tokens.json`, readable only by you).

You only do this once: the server renews the access token by itself. Each renewal
replaces the saved refresh token (Oura's are single-use), so don't copy the token file
between machines and use both copies; sign in on each machine instead.

Signing in over SSH, in Docker, or with a redirect URI that isn't on `localhost`? Add
`--paste`: after allowing access, copy the address the browser ended up on (it may show
a "can't connect" page; that's fine) and paste it into the terminal.

Then confirm the server can read your data:

```bash
OURA_CLIENT_ID='your-client-id' OURA_CLIENT_SECRET='your-client-secret' \
uv run pytest -m live -q
```

`1 passed` means it works. If it fails, the error message tells you what to fix; see
[Troubleshooting](#troubleshooting).

On Windows (PowerShell), set the variables first:

```powershell
$env:OURA_CLIENT_ID = "your-client-id"
$env:OURA_CLIENT_SECRET = "your-client-secret"
uv run oura-ring-python-mcp auth
uv run pytest -m live -q
```

## 5. Connect your client

### Claude Desktop

1. Find the full path to `uv`. Claude Desktop doesn't always see your shell's `PATH`, so
   use the absolute path:

   ```bash
   which uv        # macOS / Linux, e.g. /Users/you/.local/bin/uv
   where uv        # Windows
   ```

2. Open the config file (*Settings* → *Developer* → *Edit Config*), or open it directly:

   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

3. Add the server under `mcpServers`, keeping any servers already there:

   ```json
   {
     "mcpServers": {
       "oura": {
         "command": "/Users/you/.local/bin/uv",
         "args": ["--directory", "/Users/you/oura-ring-python-mcp", "run", "oura-ring-python-mcp"],
         "env": {
           "OURA_CLIENT_ID": "your-client-id",
           "OURA_CLIENT_SECRET": "your-client-secret"
         }
       }
     }
   }
   ```

   On Windows, double every backslash in paths, for example
   `"C:\\Users\\you\\oura-ring-python-mcp"`.

4. Quit Claude Desktop completely and reopen it. The `oura` tools should appear in the
   tools menu.

### Claude Code

```bash
claude mcp add oura \
  -e OURA_CLIENT_ID=your-client-id \
  -e OURA_CLIENT_SECRET=your-client-secret \
  -- uv --directory /Users/you/oura-ring-python-mcp run oura-ring-python-mcp
```

This adds the server to the current project only. Add `--scope user` after `add` to make
it available in every project. Check it with `claude mcp list`.

### Other MCP clients

Run this command with `OURA_CLIENT_ID` and `OURA_CLIENT_SECRET` set; it speaks MCP over
stdio:

```bash
uv --directory /path/to/oura-ring-python-mcp run oura-ring-python-mcp
```

## 6. Try it

Ask Claude:

- "How did I sleep last night?"
- "What's my readiness trend over the last two weeks?"
- "How many steps did I average this month?"
- "What was my resting heart rate overnight?"

Oura assigns sleep to the day you wake up, so last night's sleep is under today's date.
Data appears only after the ring has synced with the Oura app.

## Optional: Langfuse tracing

To send a trace of each tool call to [Langfuse](https://langfuse.com):

1. Install the extra: `uv sync --extra langfuse`.
2. In the client config, change `run oura-ring-python-mcp` to `run --extra langfuse oura-ring-python-mcp`.
3. Add `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the server's `env`, plus
   `LANGFUSE_BASE_URL` if you don't use Langfuse Cloud.

By default, traces hold only tool names, timings and error class names.
`LANGFUSE_CAPTURE_DATA=true` also sends your Oura data; only turn it on with a Langfuse
instance you trust, such as a self-hosted one.

## Troubleshooting

| Message | What to do |
|---|---|
| `Missing required environment variable(s): OURA_CLIENT_ID …` | The client isn't passing the credentials. Check the `env` block (Claude Desktop) or `-e` flags (Claude Code). |
| `Not signed in to Oura (no …tokens.json). Run \`oura-ring-python-mcp auth\` first.` | Do step 4 with the same `OURA_TOKEN_FILE` (if you set one) as the client config. |
| The Oura page says the redirect URI is invalid | The application's redirect URIs must include `http://localhost:47651/callback` exactly (or whatever `OURA_REDIRECT_URI` is). |
| `Cannot listen on http://localhost:47651/callback …` | Something else uses port 47651. Stop it, or add another redirect URI to the application with a free port and set `OURA_REDIRECT_URI` to it, or use `auth --paste`. |
| `Oura did not authorize access: access_denied.` | You clicked deny on Oura's page. Run `auth` again and allow access. |
| `Oura sign-in is missing or no longer valid (invalid_grant)…` | The saved refresh token was revoked, already used by another copy of the token file, or expired. Run `oura-ring-python-mcp auth` again. |
| `Oura sign-in is missing or no longer valid (invalid_client)…` | The client ID or secret is wrong. Copy them again from the developer portal. |
| `The Oura sign-in doesn't include the \`stress\` scope…` (or another scope) | Allow that scope for the application in the developer portal, then run `oura-ring-python-mcp auth` again and allow it on Oura's page. |
| `Oura rejected the access token…` | Run `oura-ring-python-mcp auth` again. |
| "Today" is a day behind or ahead, or last night's sleep is missing | The server's time zone differs from yours (Docker defaults to UTC). Set `OURA_TIMEZONE`, e.g. `Europe/London`. |
| `Could not save refreshed Oura tokens …` in the client's logs | The token folder isn't writable (disk full, permissions, a read-only Docker mount). Fix it before the server restarts, or you'll need to run `auth` again. |
| `Oura denied access to this data…` | Check the Oura membership is active, and that you allowed that scope when signing in (run `auth` again to change). |
| `Rate limited by Oura…` | Wait for the time shown, then retry. |
| `… is not a date; use YYYY-MM-DD.` | Ask with explicit dates, e.g. "sleep from 2026-09-01 to 2026-09-07". |
| `Date range is longer than 90 days…` | Ask for a shorter range, or several in turn. |
| An empty `items` list | The ring hasn't synced for those days, or that feature isn't available for your ring. Open the Oura app to sync. |
| `Oura returned unexpected data for …` | The API's response format changed. Open an issue with the tool name. |
| Tools don't appear in Claude Desktop | Use the absolute path to `uv`, check the JSON is valid, and fully quit and reopen Claude Desktop. Logs are in `~/Library/Logs/Claude/` (macOS) or `%APPDATA%\Claude\logs\` (Windows). |

## Updating

```bash
cd /path/to/oura-ring-python-mcp
git pull
uv sync
```

Then restart your MCP client.

## Uninstalling

1. Remove the `oura` entry from `claude_desktop_config.json`, or run
   `claude mcp remove oura`.
2. Delete the `oura-ring-python-mcp` folder and `~/.config/oura-ring-mcp/`.
3. Revoke the application's access in your Oura account settings, or delete the
   application in the developer portal.

## A note on your secrets

The client config stores the client secret in plain text, readable by anyone who can
read that file, and the token file holds a refresh token that grants access to your Oura
data. The token file is created readable only by you; keep it that way, and revoke the
application's access if either leaks.
