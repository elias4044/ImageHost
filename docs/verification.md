# Verification record

Verified locally on 2026-10-31 using Python 3.14.7 and Node 24.19.0.

## Application checks

- 63 pytest tests pass. Adapter tests use synthetic replies, and uploaded images
  are harmless generated fixtures. No illegal material is used.
- Ruff lint and formatting checks pass for app, tests, scripts and example code.
- JavaScript syntax checks pass for the dashboard and chart renderer.
- Compose files and GitHub Actions workflow parse as YAML.
- The pinned runtime dependencies resolve to Linux x86-64 Python 3.14 wheels.
- The real NudeNet 3.4.2 model loaded locally and ran inference on a generated
  white image, returning all 18 class scores. This is a model wiring check,
  not a measurement of detection accuracy.
- A second smoke check passed the real local-model endpoint response through
  the host's scan policy, including image/digest binding. ClamAV and the separate
  specialist result were substituted for this focused check.
- The local Uvicorn service starts and responds to normal dashboard sign-in.

Covered behaviors include authentication and password-change session invalidation,
CSRF, scopes, ownership, key expiry/revocation, public/private delivery gates,
quota and body limits, malformed/animated uploads, metadata removal, transparency,
provider response validation, ClamAV framing, quarantine errors/expiry/retry,
deletion during scanning, restart recovery, orphan cleanup and usage accounting.

One dependency emits a deprecation warning: Starlette's test client currently
warns about its httpx compatibility path. All tests complete successfully; this
does not affect the production server's HTTP client.

## Browser checks

Normal password sign-in was used in a temporary browser, not an authentication
bypass. Overview, images, application keys, safety and API docs were checked
at 1440, 768 and 390 pixels. There was no horizontal overflow or JavaScript
exception on those screens.

The full design inspector reports 0 FAIL and 0 WARN on the overview at all three
widths. Additional measurements on the other screens found no failures. Empty
desktop library/key canvases produce empty-space warnings, accepted because
the working sheet intentionally remains full-height while its real rows remain
compact. No invented images or statistics are used to fill the empty canvas.
The source lint's dialog shadow exception is intentional: it applies only to
a floating modal, as permitted by the design skill.

Browser actions passed: sign-in, key creation, one-time key display and clearing,
key revocation, image upload, filename search, deletion, phone navigation and
sign-out. The upload stayed quarantined without real scanner credentials.

Screenshots and raw reports remain in the ignored .taste-skill directories.
Design decisions and critique are in DESIGN.md.

## Not verified here

- Docker build/runtime and Dokploy deployment: Docker is unavailable locally.
  The CI workflow includes an image build and Compose startup smoke test, but
  that workflow has not been executed on GitHub in this session.
- Live ClamAV and specialist-provider verdicts: no production
  credentials or enrolled specialist service were provided.
- Specialist illegal-content detection is not implemented by a bundled model.
  It is optional and requires a suitable authorized provider only when enabled.
- Production load, backup restoration, infrastructure hardening and independent
  security auditing have not been performed.

The local scanner replacement adds authentication, digest binding, malformed
result, inference failure, request-size and exposed-class policy tests. No paid
moderation API is called by the nudity-screening path. Docker itself remains
unavailable in this environment, so container startup is covered by CI configuration
and still requires execution on a Docker-equipped host.

Local startup now loads the repository's .env file automatically. Regression
checks cover quoted Argon2id hashes, literal dollar signs, and existing process
environment values taking precedence over the file.

The NSFW-only native path was verified end to end using a generated white PNG:
authenticated upload, actual local inference in a child process, ready verdict,
and public WebP delivery. No scanner HTTP calls, ClamAV or specialist provider
were used in that check. New tests cover optional-check selection, local process
timeouts/failures, malformed output and rejection at the NSFW threshold.

Use docs/deployment.md and docs/moderation.md before enabling production use.
