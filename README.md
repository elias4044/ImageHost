# ImageHost

Host images locally through an API. Open source & free. Written in Python.

## What is included

- Dashboard: upload, image search, state filters, deletion, usage,
  scanner configuration, audit events, application keys, and scan retries.
- Versioned REST API with machine-readable OpenAPI at `/openapi.json` and
  readable reference at `/docs`.
- Static JPEG, PNG and WebP ingestion; compressed WebP delivery with metadata
  removed and configurable quality and maximum dimensions. Animated images and
  images over 25 megapixels are rejected.
- Required local NudeNet screening, optional ClamAV malware scanning, and an
  optional HTTPS specialist adapter for operators who need additional checks.
- Durable queue, five automatic attempts with exponential backoff, 24-hour
  quarantine expiry, and no manual approval bypass.
- Argon2id admin authentication, hashed bearer keys and sessions, per-key
  permissions and ownership, key expiry/revocation, CSRF protection, rate limits,
  storage quota, security headers, and a non-root application container.
- SQLite WAL and local object storage in one persistent volume. One process,
  one replica, one server. No external database, Redis or frontend build needed.

## Quick start locally on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-local.txt
.\.venv\Scripts\python -m app.password
```

Copy `.env.example` to `.env` if you do not already have one. Store the generated
hash in ADMIN_PASSWORD_HASH, retain its single quotes, and set
BASE_URL=http://localhost:8000. Native startup defaults to NSFW_BACKEND=local
and ANTIVIRUS_ENABLED=false. Leave SAFETY_URL and SAFETY_TOKEN empty for NSFW-only
screening. NSFW_TOKEN is not needed in local mode.

```powershell
.\.venv\Scripts\python -m uvicorn app.main:createApp --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open [the dashboard](http://localhost:8000). Upload an image, then refresh the
library after screening. No additional scanner process or Docker setup is needed.
The app starts a bounded, one-shot local inference process for each queued image.

## Quick start with Docker

1. Clone this repository and copy `.env.example` to `.env`.
2. Generate an admin password hash:

   ```sh
   docker run --rm -it python:3.14-slim sh -c \
     'pip install argon2-cffi==25.1.0 >/dev/null && python -c "from getpass import getpass; from argon2 import PasswordHasher; p=getpass(\"Password (16+ characters): \"); assert len(p)>=16; print(PasswordHasher().hash(p))"'
   ```

   Alternatively, after installing the Python dependencies, run
   `python -m app.password` for password confirmation.

3. Put the generated hash in `ADMIN_PASSWORD_HASH`, retaining the single quotes
   in the `.env` file. Set `BASE_URL`. Local use may use `http://localhost:8000`;
   production requires an HTTPS origin with no path.
4. Generate the private scanner's shared secret with
   `python -c "import secrets; print(secrets.token_urlsafe(48))"` and save it as
   NSFW_TOKEN. This is a local service credential, not an external API account.
   No specialist provider is needed for NSFW-only hosting. Leave SAFETY_URL and
   SAFETY_TOKEN empty unless you deliberately enable that optional check.
5. Start a local instance:

   ```sh
   docker compose -f compose.yaml -f compose.local.yaml up -d --build
   ```

6. Open [the local dashboard](http://localhost:8000), sign in, and create an
   application key. Uploads cannot be delivered until NSFW screening and any
   enabled optional checks approve.

To additionally scan for malware, set ANTIVIRUS_ENABLED=true and add
`--profile antivirus` to the Compose command. ClamAV remains optional.
The main Compose file exposes no host ports. The local override binds only to
loopback. Use Dokploy's HTTPS routing for server deployments.

## Deploy on Dokploy

See the complete [Dokploy deployment guide](docs/deployment.md), including
environment variables, TLS routing, persistent volumes, backups and upgrades.

## Use the API

```sh
export IMAGEHOST_URL='https://images.example.com'
export IMAGEHOST_KEY='ih_your_server_side_key'

curl "$IMAGEHOST_URL/api/v1/images" \
  -H "Authorization: Bearer $IMAGEHOST_KEY" \
  -F 'file=@photo.jpg' -F 'public=true'

curl "$IMAGEHOST_URL/api/v1/images/IMAGE_ID" \
  -H "Authorization: Bearer $IMAGEHOST_KEY"
```

Upload returns `202` with `state: pending`. Poll metadata with backoff until
`ready`, then use `url` for approved public images. `scan_error` is not approval.
Private images use authenticated `/api/v1/images/IMAGE_ID/content` after approval.
See [API notes](docs/api.md) and the runnable [Python client](examples/client.py).

## Develop and verify

Python 3.14 is used by the container and CI.

```sh
python -m venv .venv
# Activate the virtual environment using your shell's standard activation command.
python -m pip install -r requirements-local.txt -r requirements-dev.txt
python -m app.password
# Save the generated hash as ADMIN_PASSWORD_HASH in the project's .env file.
# Local startup reads .env automatically; existing process environment values take precedence.
python -m uvicorn app.main:createApp --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
python -m pytest
ruff check app moderation tests scripts examples
ruff format --check app moderation tests scripts examples
```

On Windows PowerShell, you can use the virtual environment without activating it:

```powershell
.\.venv\Scripts\python -m pip install -r requirements-local.txt
.\.venv\Scripts\python -m app.password
.\.venv\Scripts\python -m uvicorn app.main:createApp --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Put the generated hash in `.env` as `ADMIN_PASSWORD_HASH='the-full-generated-hash'`.
Do not put your plain password in this setting. Set `BASE_URL=http://localhost:8000`
and open that exact origin in your browser so sign-in's origin check matches.
This starts the dashboard, API and native NSFW scanning. Docker Compose instead
uses NSFW_BACKEND=http to run inference in the private scanner container.

Tests substitute scanner responses; they never use illegal material. They cover
quarantine, ownership, scopes, revocation, private delivery, rejection, retries,
expiry, deletion races, quotas, body limits, authentication and adapter decisions.
CI also builds the Docker image and boots the Compose stack for smoke checks.
The locked dependencies include transitive runtime packages; update the lock
alongside `requirements.txt`, then rerun tests and container verification.

## Image compression

New uploads are compressed to WebP at quality 80 using the encoder's highest
compression effort. Images larger than 2560 pixels on either edge are resized
proportionally; smaller images are never enlarged. Transparency is preserved,
camera orientation is applied, and embedded metadata is removed.

Configure these values in `.env` and restart the app (or redeploy with Compose):

```dotenv
IMAGE_QUALITY=80
IMAGE_MAX_DIMENSION=2560
```

IMAGE_QUALITY accepts 1-100; lower values trade detail for smaller files.
IMAGE_MAX_DIMENSION=0 keeps the original dimensions. The default 2560-pixel
limit reduces storage for large photographs; choose a larger limit for detailed
artwork or documents. WebP encoding does not guarantee every small or already
optimized source becomes smaller.

The compressed image goes through the normal scan gate before delivery. The
original is retained only during quarantine and deleted after approval. Storage
usage reflects the actual stored bytes. Existing hosted images are not rewritten;
these settings apply to new uploads. `/api/v1/system` exposes active compression
settings for administrators.

## Operating limits

- This release supports one admin and per-application keys, not multi-user
  accounts, SSO, replication, shared galleries or S3 storage.
- Replacing a key creates a new ownership namespace. Uploads owned by revoked
  or expired keys remain manageable by the admin. Public URLs remain public
  until the image is deleted. There is no anonymous upload endpoint.
- Public delivery is deliberately uncached for prompt removal at the origin.
  Metrics count responses started; thumbnails also count as image requests.
  There is no range support or image transformation API.
- No fetch-from-URL upload endpoint is provided; send file bytes directly.
- Original files are passed to ClamAV and the specialist provider; rebuilt
  images are passed to ClamAV and NudeNet on your own server. Only the specialist
  adapter receives original bytes outside the local stack, if you host it externally.
  Consider that provider's data handling before enabling uploads.
- NudeNet detects exposed body parts, not all sexual activity, suggestive content,
  violence or illegal material. It is not equivalent to a broad NSFW classifier.
- Rejected bytes are removed immediately; this is not an evidence preservation
  or reporting workflow. Adapt that workflow with qualified advice before
  using it where preservation or reporting obligations apply.
- Quarantine files are private to the service, but not encrypted by the app.
  Use encrypted server disks, protect backups and restrict host access.
- Configure proxy request-size limits, timeouts, connection limits and perimeter
  abuse controls. Built-in rate limits do not replace network DoS protection.

## Contributing and licensing

The hosting application is MIT licensed. The separate `moderation/` service is
AGPL-3.0-or-later to preserve NudeNet's bundled license. See [CONTRIBUTING.md](CONTRIBUTING.md),
[SECURITY.md](SECURITY.md), and [third-party notices](THIRD_PARTY_NOTICES.md).
The locally hosted IBM Plex Sans font retains its SIL Open Font License.
NudeNet runs locally without a paid API. The optional specialist adapter requires
access to a suitable authorized screening system; no provider or paid service
is selected or bundled for that check.
