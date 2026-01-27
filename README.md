# Umami MCP Server

MCP server that exposes Umami Cloud analytics via tools.

## Tools

- `get_websites` - List all your websites
- `get_stats` - Get visitor statistics
- `get_pageviews` - View page traffic over time
- `get_metrics` - See browsers, countries, devices, and more
- `get_active` - Current active visitors

## Requirements

- Python 3.13+
- `uv`

## Configure

Umami Cloud API base URL: `https://api.umami.is/v1`

Environment variables:

- `UMAMI_API_KEY` - Umami Cloud API key (required for Umami Cloud)
- `UMAMI_USERNAME` - Umami username (self-hosted only)
- `UMAMI_PASSWORD` - Umami password (self-hosted only)
- `UMAMI_API_BASE` (optional) - defaults to `https://api.umami.is/v1`

Auth rules:

- Umami Cloud: only `UMAMI_API_KEY` is supported.
- Self-hosted: you can use `UMAMI_API_KEY` or `UMAMI_USERNAME` + `UMAMI_PASSWORD`.
- You must configure at least one of these: `UMAMI_API_KEY` OR (`UMAMI_USERNAME` and `UMAMI_PASSWORD`).
- For self-hosted username/password auth, set `UMAMI_API_BASE` to your instance API root (e.g. `https://your-umami.example/api`).

All tool parameters that represent times accept ISO datetimes. If a datetime is missing a timezone, it is treated as UTC.

## Run locally

```bash
uvx run umami-mcp-server
```

## OpenCode MCP config

Example `~/.config/opencode/opencode.json` (replace the API key and adjust the path if your clone lives elsewhere):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "theme": "system",
  "mcp": {
    "umami": {
      "type": "local",
      "command": [
        "uvx",
        "umami-mcp-server"
      ],
      "environment": {
        "UMAMI_API_KEY": "YOUR_UMAMI_CLOUD_API_KEY",
        "UMAMI_API_BASE": "https://api.umami.is/v1"
      },
      "enabled": true,
    }
  }
}
```

Self-hosted example:

```json
{
  "mcp": {
    "umami": {
      "type": "local",
      "command": ["uvx", "umami-mcp-server"],
      "environment": {
        "UMAMI_USERNAME": "YOUR_USERNAME",
        "UMAMI_PASSWORD": "YOUR_PASSWORD",
        "UMAMI_API_BASE": "https://your-umami.example"
      }
    },
    "enabled": true,

  }
}
```
