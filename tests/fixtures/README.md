# Umami v3 contract fixtures

These fixtures contain only synthetic, sanitized data. They never contain authentication
responses, tokens, passwords, API keys, headers, email addresses, real domains, or real user
data.

## `self_hosted_v3`

Captured on **2026-08-05** from a disposable environment running:

- Umami **3.1.0**, image `umamisoftware/umami:3.1.0` (manifest digest
  `sha256:81119aa498f910fe1bf590c0974dfd00afd3f3563dd55528bb3bd002f06f3dfb`);
- PostgreSQL 15 (`postgres:15-alpine`);
- telemetry disabled and Umami exposed only on localhost.

The initial password was changed before creating a synthetic website. Five synthetic
pageviews and two synthetic custom events were submitted. The captured HTTP 200 responses
used these requests (the common range was `1768435200000..1768521600000`, timezone `UTC`):

| Fixture | Request |
|---|---|
| `websites.json` | `GET /api/websites` |
| `stats.json` | `GET /api/websites/{websiteId}/stats?startAt=...&endAt=...` |
| `pageviews.json` | `GET /api/websites/{websiteId}/pageviews?startAt=...&endAt=...&unit=hour&timezone=UTC` |
| `pageviews_compare.json` | Same request with `compare=prev` |
| `metrics.json` | `GET /api/websites/{websiteId}/metrics?startAt=...&endAt=...&type=path` |
| `metrics_expanded.json` | `GET /api/websites/{websiteId}/metrics/expanded?startAt=...&endAt=...&type=path` |
| `active.json` | `GET /api/websites/{websiteId}/active` after one current synthetic pageview |

Sanitization replaced the website and user UUIDs, username, domain, and website
creation/update timestamps. Shapes, keys, nulls, booleans, analytical values, and
number-versus-string
representations were preserved. In particular, Umami 3.1.0 returned `pageviews` and
`totaltime` as strings in expanded metrics. The environment and its volume were destroyed
with `docker compose down --volumes --remove-orphans` after capture.

## `cloud_current`

Cloud API access is not available to this project's free account. These are **contract-derived
fixtures**, not responses captured from an Umami Cloud account. They were assembled on
**2026-08-05** from the current public contract and upstream v3 implementation:

- <https://docs.umami.is/docs/api/websites>
- <https://docs.umami.is/docs/api/website-stats>
- <https://docs.umami.is/docs/api/api-client>
- <https://github.com/umami-software/umami>

The fixtures include synthetic additive fields to verify the required `extra="allow"`
behavior. Live Cloud compatibility is covered only by the optional `live` test when explicit
credentials are supplied.

## Refresh procedure

Fixture generation is manual and is not part of normal CI. Pin an exact Umami 3.x image,
use a disposable PostgreSQL volume, create only synthetic data, capture the seven read-only
responses above, sanitize unstable identifiers without changing types or shapes, inspect for
secrets, then remove containers and volumes.
