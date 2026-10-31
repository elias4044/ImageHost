# Dokploy deployment

## Requirements

- A Docker host with at least 4 GiB RAM recommended for NudeNet and the app;
  allow at least 6 GiB when enabling optional ClamAV.
- A domain and HTTPS through Dokploy's reverse proxy.
- A random NSFW_TOKEN for the private Docker scanner. No specialist provider
  is required for NSFW-only use. NudeNet needs no external account or subscription.
- Disk capacity for the image quota, SQLite metadata, signatures, temporary
  multipart files and backups. The default object quota is 10 GiB.

## Configure

1. Create a Docker Compose application in Dokploy, connected to this repository.
2. Select `compose.yaml` as the Compose path. Use Compose rather than Swarm
   stack mode because this file builds the application locally.
3. Add every value from `.env.example` in the environment editor, replacing
   BASE_URL with `https://images.your-domain.example`, generating NSFW_TOKEN with
   Python's `secrets.token_urlsafe(48)`, and generating an admin
   password hash as described in the README. Do not put secrets in source.
   Dokploy's environment editor expects the literal hash without shell quotes.
   A Docker Compose `.env` file needs single quotes around a hash so dollar
   signs are preserved. Verify the deployed value without printing it in logs.
4. Deploy. Under Domains, route your hostname to service `imagehost`, port
   `8000`, and enable HTTPS. Do not route or publish ClamAV port 3310 or the
   NudeNet service on port 8080.
5. Check the effective Compose configuration in Dokploy's Preview Compose.
   Imagehost and ClamAV must retain their shared `scanners` network. Imagehost
   and NudeNet must retain the internal `moderation` network. Only imagehost
   needs the proxy network. Do not use compose.local.yaml on the public server.
6. Sign in, open Content safety, confirm configuration, create an application
   key and upload an innocuous test image. Confirm a ready verdict, successful
   delivery, API ownership, deletion and scanner-outage quarantine before use.

Dokploy's [Compose domain documentation](https://docs.dokploy.com/docs/core/docker-compose/domains)
describes its service routing and automatic network changes.

## Proxy and runtime

Run exactly one imagehost container with one Uvicorn worker. SQLite and the
embedded worker are intentionally single-instance. Never scale replicas or
mount the same volume into a second live instance. Planned upgrades should stop
the old instance before starting the new one. Use local disk, not network storage.

The Docker stack sets NSFW_BACKEND=http; the default native Python startup uses
NSFW_BACKEND=local and requirements-local.txt. Malware scanning is off by default.
To enable it in Docker, set ANTIVIRUS_ENABLED=true and start Compose with
`--profile antivirus`. Specialist screening runs only when its URL and token
are deliberately configured. Disabled optional checks never block an upload.

Set the reverse proxy body limit to MAX_UPLOAD_MB plus 64 KiB and a sensible
upload timeout. Add perimeter connection and request limits. Request handling
normalizes images in a thread pool; the container's CPU/memory limits bound
resource use. Do not expose the app directly to the internet without a proxy.

Proxy headers are disabled by default. IP-based login and public-delivery
limits will therefore apply to the proxy peer (shared across clients), which
is conservative but may constrain traffic. Per-API-key limits are unaffected.
If enabling trusted proxy support, explicitly restrict trusted proxy IPs at
Uvicorn and at the network edge; never trust arbitrary X-Forwarded-For input.
Use an external IP allowlist or identity-aware proxy for the admin interface
if stronger administrator access controls are needed. No MFA is bundled.

Health check `/health/live` verifies the web process, not provider readiness.
The NudeNet container separately verifies its model loads and completes a
harmless warmup inference before becoming healthy. Compose waits for it before
starting the hosting service. No GPU is needed. It uses up to 1 GiB RAM and two
CPU cores under the supplied container limits.
The dashboard distinguishes configured scanners from actual image verdicts.
ClamAV's initial signature download can take several minutes. Failed scans
remain private; use Retry after setup completes if attempts were exhausted.
The server waits up to 100 seconds for an in-flight scan during shutdown;
Compose gives it 110 seconds. Forced termination leaves recoverable jobs.

## Persistent state and backups

- `imagehost_data`: SQLite database, WAL files, originals in quarantine, and
  rebuilt images, owned by UID/GID 10001. New Docker named volumes inherit the
  image's /data ownership. Existing bind mounts must grant that UID access.
- `clamav_signatures`: virus definition database, maintained by ClamAV.

Use Dokploy volume backups or a volume-aware backup job. For a consistent simple
backup, stop imagehost, back up its entire data volume, then restart it. Copying
only imagehost.db while the app runs can miss committed WAL data. Backups contain
sensitive quarantine bytes and credential hashes: encrypt and restrict them,
apply retention, and test restoration into an isolated instance. Do not leave
a restored instance connected to real clients until checks complete.

Rotate the admin password by replacing its Argon2id hash and restarting. Existing
sessions invalidate automatically. Existing API keys are separate and must be
revoked individually. Losing the admin password does not require data deletion.

## Upgrades

Back up first. Build and test a new release, stop the old instance, then deploy
the new image against the volume. The initial schema uses SQLite user_version 1;
future incompatible schema changes require an explicit migration. Do not assume
older versions can read a future schema. Pin the ClamAV stable tag to a verified
digest for reproducible production deployments, and schedule signature and
dependency updates. The Python runtime dependencies are pinned in requirements.lock.

## Incident handling

Delete an image to stop subsequent origin delivery. Existing browser copies or
third-party caches cannot be recalled. Revoke a compromised application key;
public images do not become private when a key is revoked. Review audit events
and handle provider reporting/evidence workflows according to your procedures.
Do not download suspicious files into issue trackers or send them to contributors.
