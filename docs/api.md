# API integration notes

The complete OpenAPI 3 schema is generated from the running routes at
`/openapi.json` (a checked-in snapshot is [openapi.json](openapi.json)). `/docs` provides the human-readable reference without loading
third-party scripts. Authentication uses `Authorization: Bearer ih_...`.

## Image lifecycle

`POST /api/v1/images` accepts multipart fields file and public (default true).
Returns 202 with metadata: id, name, state, public, size (rebuilt bytes), width,
height, created (Unix seconds), reason, url, views, bytes_served. Unknown or
unsupported images return 415. SVG and animation are rejected; images above
25 megapixels or configured upload limits are rejected.

Poll `GET /api/v1/images/{id}` with backoff. Only ready images are deliverable.
No public URL is returned for private images. Use the authenticated content
endpoint for private delivery. Keys must not be embedded in public webpages.
The example client polls for two minutes and returns a timeout rather than
treating pending/error as approved.

List queries: state, search (literal filename substring), limit (1-100), offset.
The response is `{images, total, limit, offset}`. Results sort newest first.
The total follows the active filters and the authenticated key's ownership.
Pagination is offset-based; concurrent uploads/deletes can shift page boundaries.

DELETE removes the metadata row and stored bytes. It returns 204, or 404 if the
image does not exist in the key's namespace. This is not an idempotent-success
delete contract: clients may treat a repeated 404 as already removed.
There is no server-side upload idempotency key; retries of an upload create
separate objects. Do not blindly retry a completed or ambiguous POST.

## Authorization

- images:read: list/read own metadata and approved bytes; own aggregate stats.
- images:write: upload images into this key's namespace.
- images:delete: delete own images.
- Dashboard admin: all namespaces, key administration, audit, retry, system.

Revoking or expiring a key stops its authenticated access. It does not remove
already public images. There is no ownership transfer or key rotation alias in
this release. Use the admin to manage images belonging to an older key.

## Limits, errors and counters

All expected errors use `{error:{code,message}}`; validation errors also name
invalid field paths without echoing submitted values. HTTP 429 supplies
Retry-After: 60. Limits use fixed one-minute windows persisted in SQLite:
120/key/minute, 300/admin/minute, 5 login attempts/peer/minute and 30 global
login attempts/minute, 600 public delivery requests/peer/minute. Key creation
is limited to 10/minute and retry actions to 20/minute. Proxy peer caveats are
in deployment.md. Every application response has an X-Request-ID header.

Stats report current image counts/states and allocated object storage plus a
14-day UTC series of uploads, views and bytes. Upload usage and delivery totals
survive image deletion. Views count responses started, including admin thumbnails;
aborted downloads are not deducted. Quarantine uses original plus rebuilt bytes;
ready storage uses rebuilt bytes. Blocked/expired records use no object quota.
SQLite metadata and rate/audit tables are not part of the object quota; monitor
disk and retention separately. Audit events are retained for 90 days.

No CORS is enabled. Use server-to-server calls for uploads and private delivery;
approved public URLs may be embedded as images on other origins. Responses use
Cache-Control: no-store so subsequent requests consult the publication gate.

## Administrative API

GET/POST `/api/v1/keys`, DELETE `/api/v1/keys/{keyId}`, GET `/api/v1/system`,
GET `/api/v1/audit?limit=25`, POST `/api/v1/images/{id}/retry` require the admin
session cookie. Mutations additionally require an Origin equal to BASE_URL.
Key creation accepts name, scopes and expiresInDays (1-365, default 90).
It returns the plaintext key once. Key listings expose only prefixes and metadata.
Retries only accept scanner-error jobs created within the past 24 hours; they
do not bypass any scanner. Blocked and expired images cannot be reapproved.

NSFW screening is always required. Malware scanning and specialist screening
are optional, but fail closed once enabled. `/api/v1/system` reports the active
`requiredScanners` and `nsfwBackend`. Scan-error reasons distinguish local model
failures, local timeouts, missing dependencies, unreachable HTTP scanner,
scanner authentication failures and optional-service outages.
