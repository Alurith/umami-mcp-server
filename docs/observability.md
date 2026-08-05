# Observability

Umami MCP Server emits application-level OpenTelemetry traces and metrics for requests to
Umami. MCP request spans are supplied by MCP SDK; this project adds one logical client span
for each analytics operation and a child span for login when required.

## Installation and activation

The base package depends only on `opentelemetry-api`. Without an OpenTelemetry SDK and an
exporter, all instrumentation is no-op and the server works normally over stdio.

The `otel` extra installs OpenTelemetry SDK, distro, and the OTLP exporters. The library does
not install global providers or choose an exporter. Run the distro's auto-configuration
command from an environment containing the extra:

```bash
OTEL_SERVICE_NAME=umami-mcp-server \
OTEL_TRACES_EXPORTER=otlp \
OTEL_METRICS_EXPORTER=otlp \
OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.internal:4317 \
uvx --from 'umami-mcp-server[otel]' opentelemetry-instrument umami-mcp-server
```

For a persistent installation, install `umami-mcp-server[otel]` in a virtual environment and
invoke that environment's `opentelemetry-instrument` executable.

Use this command as the MCP stdio command in place of `umami-mcp-server`. No HTTP MCP
transport is enabled.

The three OpenTelemetry layers have separate responsibilities:

- **API:** the mandatory, no-op-safe instrumentation used by the application;
- **SDK:** providers, sampling, aggregation, and processing, installed by the `otel` extra;
- **exporter:** sends completed telemetry to a backend, selected through standard
  OpenTelemetry configuration.

## Trace model

The expected hierarchy is:

```text
MCP tools/call <tool-name>
└── umami.request <METHOD> <normalized-endpoint>
    └── umami.auth.login                 # only when login or refresh is required
```

One analytics call creates one `umami.request` span even if login, token refresh, rate-limit
handling, or retries cause multiple HTTP sends. HTTPX automatic instrumentation is not used.

Only the W3C `traceparent` and `tracestate` fields are propagated to Umami. Baggage received
from an MCP client is deliberately not forwarded.

Span names contain only the HTTP method and one of these normalized endpoints:

```text
/websites
/websites/{websiteId}/stats
/websites/{websiteId}/pageviews
/websites/{websiteId}/metrics
/websites/{websiteId}/metrics/expanded
/websites/{websiteId}/active
/auth/login
```

## Metrics

| Instrument | Type | Unit | Meaning |
|---|---|---:|---|
| `umami.client.request.duration` | Histogram | `s` | Logical analytics duration, including required login and retries |
| `umami.client.request.errors` | Counter | `1` | Analytics operations ending with an error |
| `umami.client.retries` | Counter | `1` | Additional analytics HTTP sends |
| `umami.client.rate_limits` | Counter | `1` | Every observed Umami `429` response |
| `umami.client.token.refreshes` | Counter | `1` | Refreshes that actually perform a new login |

Metric labels are selected from the same bounded allowlist used for spans. Retry causes are
limited to `authentication_refresh`, `timeout`, `network`, `rate_limit`, and `server_error`.
Outcomes are limited to `success` and `error`.

## Attribute and redaction policy

Only these application attributes are emitted:

```text
http.request.method
http.response.status_code
umami.endpoint
umami.auth.mode
umami.retry.count
umami.outcome
umami.retry.cause
error.type
```

Error categories are controlled values such as `authentication`, `rate_limit`, `timeout`,
`network`, `upstream`, and `invalid_response`. Raw exceptions are not recorded as span
events or status descriptions.

Telemetry never includes:

- API keys, bearer tokens, usernames, passwords, or exporter credentials;
- HTTP headers, request bodies, response bodies, full URLs, or query strings;
- website IDs or other concrete UUIDs;
- search terms, filters, dates, or timezones supplied to tools;
- MCP or Umami payloads;
- raw HTTPX or Pydantic exception messages.

## Standard configuration

Common standard OpenTelemetry variables include:

```text
OTEL_SERVICE_NAME=umami-mcp-server
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.example:4317
```

Exporter authentication may be configured with variables such as
`OTEL_EXPORTER_OTLP_HEADERS`. **Exporter headers and credentials are operational secrets.**
Never paste them into issues, logs, shared MCP configurations, or troubleshooting output.
Consult the OpenTelemetry documentation for TLS, certificate, sampling, batching, and
signal-specific endpoint variables.

Disable all SDK telemetry explicitly with:

```text
OTEL_SDK_DISABLED=true
```

Alternatively, run the base `umami-mcp-server` command without SDK auto-configuration to
retain no-op instrumentation.

## Troubleshooting

1. Confirm the `otel` extra is installed in the same environment as the server. Dependency
   executables are not exposed by a plain `uv tool install`; use the `uvx --from` command
   above or a virtual environment.
2. Confirm the MCP command invokes `opentelemetry-instrument`, not only
   `umami-mcp-server`.
3. Check collector reachability and that its OTLP protocol and port match the client.
4. Check that `OTEL_SDK_DISABLED` is not set to `true`.
5. Confirm both trace and metric exporters are enabled when both signals are expected.
6. Inspect collector health and sanitized exporter diagnostics, never complete environment
   dumps, authorization headers, or MCP configuration files containing credentials.

The server does not contact a collector unless an externally configured SDK/exporter does
so; exporter failures do not change Umami request behavior.
