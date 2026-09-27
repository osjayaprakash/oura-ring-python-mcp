# Installing oura-ring-mcp

This guide takes you from nothing to asking Claude "how did I sleep last night?". It takes
about 10 minutes.

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

## 2. Get an Oura access token

1. Sign in at <https://cloud.ouraring.com/personal-access-tokens> with your Oura account.
2. Create a new personal access token and copy it. Treat it like a password: it can read
   all of your Oura data.

If you have your own Oura OAuth2 application, an access token from it works too; the
server sends whatever `OURA_ACCESS_TOKEN` holds as a bearer token.

## 3. Download and install

```bash
git clone https://github.com/osjayaprakash/oura-ring-mcp.git
cd oura-ring-mcp
uv sync
```

Note the full path of this folder; you'll need it below:

```bash
pwd
```

## 4. Check your token

Before connecting a client, confirm the server can read data:

```bash
OURA_ACCESS_TOKEN='your-token' uv run pytest -m live -q
```

`1 passed` means it works. If it fails, the error message tells you what to fix; see
[Troubleshooting](#troubleshooting).

On Windows (PowerShell), set the variable first:

```powershell
$env:OURA_ACCESS_TOKEN = "your-token"
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
         "args": ["--directory", "/Users/you/oura-ring-mcp", "run", "oura-ring-mcp"],
         "env": {
           "OURA_ACCESS_TOKEN": "your-token"
         }
       }
     }
   }
   ```

   On Windows, double every backslash in paths, for example
   `"C:\\Users\\you\\oura-ring-mcp"`.

4. Quit Claude Desktop completely and reopen it. The `oura` tools should appear in the
   tools menu.

### Claude Code

```bash
claude mcp add oura \
  -e OURA_ACCESS_TOKEN=your-token \
  -- uv --directory /Users/you/oura-ring-mcp run oura-ring-mcp
```

This adds the server to the current project only. Add `--scope user` after `add` to make
it available in every project. Check it with `claude mcp list`.

### Other MCP clients

Run this command with `OURA_ACCESS_TOKEN` set; it speaks MCP over stdio:

```bash
uv --directory /path/to/oura-ring-mcp run oura-ring-mcp
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
2. In the client config, change `run oura-ring-mcp` to `run --extra langfuse oura-ring-mcp`.
3. Add `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the server's `env`, plus
   `LANGFUSE_BASE_URL` if you don't use Langfuse Cloud.

By default, traces hold only tool names, timings and error class names.
`LANGFUSE_CAPTURE_DATA=true` also sends your Oura data; only turn it on with a Langfuse
instance you trust, such as a self-hosted one.

## Troubleshooting

| Message | What to do |
|---|---|
| `Missing required environment variable(s): OURA_ACCESS_TOKEN` | The client isn't passing the token. Check the `env` block (Claude Desktop) or `-e` flag (Claude Code). |
| `Oura rejected the access token…` | The token is wrong, expired or revoked. Create a new one (step 2). |
| `Oura denied access to this data…` | Check the Oura membership is active, and that an OAuth token was granted the scope for this data. |
| `Rate limited by Oura…` | Wait for the time shown, then retry. |
| `… is not a date; use YYYY-MM-DD.` | Ask with explicit dates, e.g. "sleep from 2026-09-01 to 2026-09-07". |
| `Date range is longer than 90 days…` | Ask for a shorter range, or several in turn. |
| An empty `items` list | The ring hasn't synced for those days, or that feature isn't available for your ring. Open the Oura app to sync. |
| `Oura returned unexpected data for …` | The API's response format changed. Open an issue with the tool name. |
| Tools don't appear in Claude Desktop | Use the absolute path to `uv`, check the JSON is valid, and fully quit and reopen Claude Desktop. Logs are in `~/Library/Logs/Claude/` (macOS) or `%APPDATA%\Claude\logs\` (Windows). |

## Updating

```bash
cd /path/to/oura-ring-mcp
git pull
uv sync
```

Then restart your MCP client.

## Uninstalling

1. Remove the `oura` entry from `claude_desktop_config.json`, or run
   `claude mcp remove oura`.
2. Delete the `oura-ring-mcp` folder.
3. Revoke the token at <https://cloud.ouraring.com/personal-access-tokens>.

## A note on your token

The client config stores the access token in plain text, readable by anyone who can read
that file. Revoke it from the Oura website if it leaks.
