# Security policy

Only the latest release is supported until a versioned support policy exists.
This is an initial implementation; no independent security audit is claimed.

Do not disclose exploitable vulnerabilities in public issues. Before publishing
this repository, maintainers should enable GitHub private vulnerability reporting
and add their monitored security contact. Use that private reporting channel;
if it is unavailable, request a private contact without publishing exploit details.

Include affected version, endpoint, preconditions, expected and observed
behavior, and a harmless reproduction. Do not include illegal content, real
customer images, provider credentials or production tokens. Maintainers should
acknowledge reports and coordinate a fix before public disclosure.

Security invariants:

- No original/quarantined/blocked/expired file can be delivered or previewed.
- Publication requires NSFW approval and approval from each enabled optional check.
- Missing required configuration and ambiguous/provider error results fail closed.
- An API key cannot access another key's images or administer the service.
- Credentials are never retrievable from storage as plaintext.
- Deletion cannot be reversed by a concurrent scan result.
- Uploaded bytes never determine filesystem paths or executable content.

Threat and deployment boundaries are documented in README.md and docs/deployment.md.
The host, TLS proxy, provider endpoints and server administrator are trusted.
There is no guarantee that probabilistic moderation catches all prohibited
material. Provider enrollment, policy coverage, incident reporting and legal
obligations are operator responsibilities.
