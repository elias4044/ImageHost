# Moderation providers and safety contract

## Publication gate

Every upload follows this pipeline:

1. Bound request size, authenticate, validate the decoded image, reject animation
   and excessive pixels, re-encode into metadata-free WebP, reserve storage.
2. Store original and rebuilt files in private storage; record a pending job.
3. If ANTIVIRUS_ENABLED=true, scan both files with ClamAV using INSTREAM.
   Anything except an exact clean response prevents publication.
4. If SAFETY_URL and SAFETY_TOKEN are configured, submit the original bytes
   to that optional specialist endpoint. An explicit allow verdict is required.
5. Run the rebuilt image through NudeNet locally. Reject if a detected
   exposed breast, female/male genitalia, anus or buttocks has a confidence at
   or above NSFW_THRESHOLD (default 0.5).
6. Only after NSFW screening and all enabled optional checks pass, delete the
   original and set state to ready.

The serving routes check the database state on every request. Storage is never
mounted as a static web directory. No quarantine thumbnail or manual release
endpoint exists. SVG, GIF, video and animated PNG/WebP are not supported.

Scan errors retry after 60, 120, 240, 480 and 960 seconds, with at most five scan
attempts. The final backoff is recorded but there is no sixth automatic attempt.
The admin can requeue a scan_error inside the first 24 hours. Quarantine expires
after 24 hours, including errors whose attempts are exhausted. A definitive
block deletes the stored files. Scan state and reason remain as metadata.

## Local NudeNet scanner

Native Python startup defaults to NSFW_BACKEND=local. Install
`requirements-local.txt`; no scanner URL, token, Docker service or external
provider is needed. The worker sends rebuilt bytes to a separate local Python
process over stdin, validates the result, and enforces a 45-second timeout.
The image is never written to a temporary file for inference. NSFW screening
cannot be disabled. Failures keep the image quarantined.

Docker Compose explicitly selects NSFW_BACKEND=http and builds the private
scanner described below. Set NSFW_BACKEND=http yourself only when you intend
to run a separate scanner service.

Compose builds the scanner from `moderation/Dockerfile`. It runs NudeNet 3.4.2's
bundled 320n ONNX model on the CPU. Model weights ship in the Python package and
are checked against a pinned SHA-256 digest and loaded during image build and startup. No image or model download is sent
to an external service at runtime. Installation still downloads public packages.

Set NSFW_TOKEN to a random secret of at least 32 characters, shared by the app
and the scanner. Compose connects them over an internal network with no published
scanner port and no outbound internet route for that container. NSFW_URL defaults
to `http://nsfw:8080/scan`; do not expose this endpoint to the public internet.
When running services directly rather than Compose, use an appropriate local URL.

The application posts normalized bytes with a bearer token, image identifier
and SHA-256 digest. The scanner checks the digest and decoded image, runs the
model, and returns the maximum confidence per class, bound to that image and
model version. Missing scores, wrong image identifiers/digests, unsupported
model versions, invalid confidence values, failed inference and HTTP errors
prevent approval. An empty detection list becomes zero scores only after real
inference completes; no scanner-error fallback returns clean scores.

Blocked classes: FEMALE_BREAST_EXPOSED, FEMALE_GENITALIA_EXPOSED,
MALE_GENITALIA_EXPOSED, ANUS_EXPOSED and BUTTOCKS_EXPOSED. Scores are detector
confidences, not a calibrated probability that an entire image is safe. NudeNet
filters low-confidence detections internally, so the supported NSFW_THRESHOLD
range is 0.25 inclusive to 1 exclusive. Default: 0.5.

This is exposed-nudity detection, not a full substitute for sexual-activity,
fetish, suggestiveness, violence or illegal-content classification. It can miss
content and reject harmless images. It cannot determine a person's age or
whether an image is illegal. Specialist screening is an optional additional check.

For malware scanning, set ANTIVIRUS_ENABLED=true and run a reachable ClamAV
daemon. With Compose, enable the antivirus profile as well. Disabled optional
checks are marked Optional / off in the dashboard, not as setup errors.

Source: [NudeNet](https://github.com/notAI-tech/NudeNet).
The pinned package bundles an AGPL license despite its MIT package metadata;
the separate scanner's source and license are included under `moderation/`.

## Optional specialist adapter

Leave SAFETY_URL and SAFETY_TOKEN empty for NSFW-only screening. Neither is
required by default. If you need this additional check, a production provider
implementation is not bundled. Choose an authorized
specialist provider appropriate to your use case, obtain access, and implement
this contract in an adapter service you control. Known-hash matching services
usually require enrollment; do not substitute a generic NSFW model or a stub
that always approves. SHA-256 is an integrity binding here, not a perceptual
hash or an illegal-content detection algorithm.

Set SAFETY_URL to the HTTPS endpoint and SAFETY_TOKEN to a strong shared secret.
Do not point it at an untrusted URL. The application sends:

```http
POST /scan
Authorization: Bearer <SAFETY_TOKEN>
Idempotency-Key: <image_id>
Content-Type: multipart/form-data

file=<original image bytes, filename upload.bin>
image_id=<32-character identifier>
sha256=<SHA-256 hex digest of the original bytes>
```

The adapter must authenticate the request, recompute the digest, inspect the
original decoded image with the provider, handle all necessary frames (only
static images are accepted upstream), and return this JSON only after receiving
a definitive provider result:

```json
{
  "image_id": "same identifier from request",
  "sha256": "same verified digest from request",
  "decision": "allow"
}
```

Allowed decisions:

- `allow`: all required specialist checks completed and cleared the image.
- `block`: a definitive provider policy rejection; bytes are removed locally.
- `review`: undecided, unsupported, pending review or unknown; remain private.

The adapter must never translate provider outages, pending decisions, unsupported
media or enrollment failures into allow. If it uses asynchronous providers,
persist the job and return review until a definitive verdict is available;
the same image_id is reused on retry. Return a non-2xx response on service error.
Only HTTP 2xx with exact matching image_id and sha256 and decision allow clears
this stage. TLS verification is enabled, redirects and environment proxies are
disabled, and the timeout is 45 seconds. Do not log file bytes or credentials.

Maintain your provider-specific abuse handling, human review, preservation,
reporting and appeal procedures outside this generic contract. The service
does not determine jurisdiction or claim legal compliance.

ClamAV protocol source: [ClamD protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).
