# oura-ring-mcp

<!-- mcp-name: io.github.osjayaprakash/oura-ring-mcp -->

[![CI](https://github.com/osjayaprakash/oura-ring-mcp/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/osjayaprakash/oura-ring-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/oura-ring-mcp)](https://pypi.org/project/oura-ring-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/oura-ring-mcp)](https://pypi.org/project/oura-ring-mcp/)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-2496ED?logo=docker&logoColor=white)](https://github.com/osjayaprakash/oura-ring-mcp/pkgs/container/oura-ring-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/osjayaprakash/oura-ring-mcp/blob/master/LICENSE)

An MCP server that gives Claude (or any MCP client) read-only access to your Oura Ring
data: sleep, readiness, activity, stress, SpO2, resilience, workouts, sessions and heart
rate. It talks to the [Oura API v2](https://cloud.ouraring.com/v2/docs) with its own small
async client (`oura_ring_mcp.core`).

## Tools

| Tool | Returns |
|---|---|
| `get_personal_info` | Age, weight, height, biological sex, email |
| `get_daily_sleep` | Daily sleep score and contributors |
| `get_sleep_periods` | Each night's sleep and naps: stages, efficiency, heart rate, HRV |
| `get_daily_readiness` | Daily readiness score, contributors, temperature deviation |
| `get_daily_activity` | Daily activity score, steps, calories, time per activity level |
| `get_daily_stress` | Daily time in high stress and in recovery |
| `get_daily_spo2` | Nightly average SpO2 and breathing disturbance index |
| `get_daily_resilience` | Daily resilience level and contributors |
| `get_workouts` | Workouts with type, intensity, calories, distance |
| `get_sessions` | Meditation, breathing and rest sessions |
| `get_heart_rate` | Heart rate samples with min, max and average bpm |

Daily tools take optional `start_date` and `end_date` (`YYYY-MM-DD`, both inclusive).
Without them they cover the 7 days ending today; ranges are limited to 90 days. Each
result echoes the range it covers, so the model always knows what "today" meant.

`get_heart_rate` takes optional `start_datetime` and `end_datetime` (ISO 8601). Without
them it covers the last 24 hours; windows are limited to 7 days.

Per-interval series (5-minute activity classes, MET, sleep phases, in-sleep heart rate
and HRV curves) are left out of results to keep them small; the scores, totals and
averages are kept.

## Setup

For a step-by-step guide, including getting a token and troubleshooting, see the
[installation guide](https://oura-ring-mcp.readthedocs.io/en/latest/install/).
Full documentation is at <https://oura-ring-mcp.readthedocs.io>.

You need an Oura access token. Create a personal access token at
<https://cloud.ouraring.com/personal-access-tokens>, or use the access token of an Oura
OAuth2 application you've authorised. Gen3 and Oura Ring 4 users need an active Oura
membership for the API to return data.

```bash
git clone https://github.com/osjayaprakash/oura-ring-mcp.git && cd oura-ring-mcp
uv sync
```

| Variable | Required | Meaning |
|---|---|---|
| `OURA_ACCESS_TOKEN` | yes | Oura personal access token (or OAuth2 access token) |

### Run from PyPI

No clone needed; [uv](https://docs.astral.sh/uv/) fetches and runs the published package:

```bash
uvx oura-ring-mcp
```

In a client config, use `"command": "uvx", "args": ["oura-ring-mcp"]`.

### Run with Docker

The server speaks MCP over stdio, so keep `-i`:

```bash
docker run -i --rm -e OURA_ACCESS_TOKEN ghcr.io/osjayaprakash/oura-ring-mcp:latest
```

In a client config, use `"command": "docker"` with those arguments, and pass the
variable through the client's `env` block.

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "oura": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/oura-ring-mcp", "run", "oura-ring-mcp"],
      "env": {
        "OURA_ACCESS_TOKEN": "your-token"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add oura \
  -e OURA_ACCESS_TOKEN=your-token \
  -- uv --directory /absolute/path/to/oura-ring-mcp run oura-ring-mcp
```

## Langfuse tracing (optional)

Each tool call becomes a Langfuse trace, with a child span for each Oura API call.
Install the extra and set the keys:

```bash
uv sync --extra langfuse
```

In the server command, use `run --extra langfuse oura-ring-mcp` instead of
`run oura-ring-mcp`.

| Variable | Meaning |
|---|---|
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Tracing is on only when both are set |
| `LANGFUSE_BASE_URL` | Langfuse URL for self-hosted or regional instances (default: Langfuse Cloud) |
| `LANGFUSE_CAPTURE_DATA` | `true` to include tool inputs, outputs and error messages. Default `false` |

**Privacy:** sleep, heart rate and activity data are health data. By default, traces hold
only tool names, timings and error class names. Setting `LANGFUSE_CAPTURE_DATA=true`
sends your data to your Langfuse instance; only do that with an instance you trust, such
as a self-hosted one.

## Development

```bash
uv sync
uv run pytest            # offline suite
uv run pytest -m live    # hits the real API; needs OURA_ACCESS_TOKEN
uv run ruff check src tests && uv run ruff format --check src tests
```

## Releasing

Bump `version` in `pyproject.toml` and both versions in `server.json` (a test checks they
match), commit, then push a tag:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The tag publishes to PyPI (`pypi.yml`, needs the `PYPI_API_TOKEN` secret), to
`ghcr.io/osjayaprakash/oura-ring-mcp` (`docker.yml`), and then to the
[MCP Registry](https://registry.modelcontextprotocol.io) (`mcp-registry.yml`).

## License

[MIT](https://github.com/osjayaprakash/oura-ring-mcp/blob/master/LICENSE)
