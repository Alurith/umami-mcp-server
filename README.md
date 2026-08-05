# Umami MCP Server

MCP server exposing read-only analytics from the current **Umami Cloud API** and
**self-hosted Umami 3.x**.

## Support matrix

| Deployment | Support | API root | Authentication |
|---|---|---|---|
| Umami Cloud (current) | Supported | `https://api.umami.is/v1` | API key |
| Self-hosted Umami 3.x | Supported | `https://host.example/api` | Username/password |
| Self-hosted Umami 2.x | Not supported; any future integration will be separate | — | — |
| Umami 1.x | Not supported | — | — |

The `/v1` suffix belongs to the current **Cloud API URL**. It does not mean that this
server supports version 1 of the self-hosted Umami application.

## Requirements and run command

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)

Run the published package directly:

```bash
uvx umami-mcp-server
```

## Configuration

Environment variables:

- `UMAMI_API_KEY`: Umami Cloud API key.
- `UMAMI_USERNAME`: self-hosted Umami 3.x username.
- `UMAMI_PASSWORD`: self-hosted Umami 3.x password.
- `UMAMI_API_BASE`: optional; defaults to `https://api.umami.is/v1`. For self-hosted
  deployments, set the API root including `/api`.

Choose exactly one authentication mode: a Cloud API key **or** self-hosted username and
password. Cloud API keys use the documented `Authorization: Bearer` scheme; standard
self-hosted Umami 3.x does not support API keys.

Example MCP configuration for Cloud:

```json
{
  "mcp": {
    "umami": {
      "type": "local",
      "command": ["uvx", "umami-mcp-server"],
      "environment": {
        "UMAMI_API_KEY": "YOUR_UMAMI_CLOUD_API_KEY",
        "UMAMI_API_BASE": "https://api.umami.is/v1"
      },
      "enabled": true
    }
  }
}
```

Self-hosted Umami 3.x:

```json
{
  "mcp": {
    "umami": {
      "type": "local",
      "command": ["uvx", "umami-mcp-server"],
      "environment": {
        "UMAMI_USERNAME": "YOUR_USERNAME",
        "UMAMI_PASSWORD": "YOUR_PASSWORD",
        "UMAMI_API_BASE": "https://your-umami.example/api"
      },
      "enabled": true
    }
  }
}
```

## Tools

- `get_websites`: return one page of websites. `page >= 1` and `1 <= page_size <= 100`.
- `get_stats`: summary pageviews, visitors, visits, bounces, total time, and comparison.
- `get_pageviews`: pageview and session time series.
- `get_metrics`: compact or expanded metrics. `1 <= limit <= 500` and
  `0 <= offset <= 10000`.
- `get_active`: current active visitors.

Every `website_id`, segment, and cohort identifier is validated as a UUID before an HTTP
request is sent.

### Time ranges

Datetime parameters accept ISO datetimes. Naive values are interpreted as UTC. The four
range rules are:

| Inputs | Range |
|---|---|
| neither | now minus seven days → now |
| only `end_at` | seven days before `end_at` → `end_at` |
| only `start_at` | `start_at` → now |
| both | explicit range |

The end must be later than the start. Pageview units are `minute`, `hour`, `day`, `month`,
and `year`. Timezones must be valid IANA names such as `UTC` or `Europe/Rome`. Comparisons
are `prev` or `yoy`.

### Metrics and filters

Metric types:

```text
path, fullPath, entry, exit, referrer, domain, title, query,
event, tag, hostname, utmSource, utmMedium, utmCampaign,
utmContent, utmTerm, browser, os, device, screen, language,
country, city, region, distinctId, channel
```

Documented Umami 3 filters:

```text
path, referrer, title, query, browser, os, device, country,
region, city, language, hostname, tag, event, distinctId,
utmSource, utmMedium, utmCampaign, utmContent, utmTerm,
segment, cohort
```

Tool input uses snake_case for `distinct_id` and the UTM filters; the server serializes the
upstream camelCase names automatically.

## Reliability and safe errors

One HTTP client and connection pool is shared for the MCP server lifespan. Login-mode tokens
are shared, concurrent login/refresh is synchronized, and a request can perform at most three
analytics sends and one token refresh. GET requests retry only network failures, timeouts,
rate limits, and transient `500`, `502`, `503`, and `504` responses. `Retry-After` is honored
up to 60 seconds.

Errors are exposed as controlled categories: authentication, rate limit, timeout, network,
upstream failure, and invalid response. Public messages and logs exclude response bodies,
credentials, headers, complete query URLs, and raw HTTP/Pydantic exception values.

## Cache and observability

On the current MCP revision, the static `tools/list` catalog has a public five-minute cache
hint. Tool order and schema content are deterministic, and the catalog contains no Umami
data, website IDs, or credentials. Legacy protocol serialization remains unchanged and does
not include cache fields.

MCP SDK already traces incoming MCP operations. Umami MCP Server adds a child span for each
logical Umami analytics request, a child login span when needed, and metrics for duration,
errors, retries, rate limits, and token refreshes. Only W3C Trace Context is propagated to
Umami; MCP baggage is not forwarded.

The base package uses only the OpenTelemetry API, so instrumentation remains no-op without an
SDK and exporter. Install the optional stack with `umami-mcp-server[otel]`, configure it
externally, or disable it explicitly with `OTEL_SDK_DISABLED=true`. See
[the observability guide](docs/observability.md) for setup, exported names, redaction policy,
and OTLP examples.

## Development

```bash
uv sync --dev
uv run ruff format . --check
uv run ruff check .
uv run pyright
uv run pytest
```

The optional live Cloud contract test requires `UMAMI_LIVE_CLOUD_API_KEY` and
`UMAMI_LIVE_CLOUD_WEBSITE_ID`; `UMAMI_LIVE_CLOUD_API_BASE` may override the default Cloud
root.
