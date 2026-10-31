# Contributing

Start with a small issue describing the behavior you want to change. Never
attach suspicious or illegal content, production secrets, session cookies,
database snapshots or private customer images to issues or pull requests.

Use Python 3.14, the locked dependencies and the checks in README.md. Keep
functions readable, use descriptive camelCase names and PascalCase types, and
keep authored comments and documentation ASCII. The dashboard has no build
step and no CDN dependencies. Include mobile and desktop verification for UI
changes. All counters must come from real persisted data.

Changes to authorization, ingestion, scanning, storage or delivery need regression
tests demonstrating the publication gate. Never introduce a development bypass
that can reach production configuration. Mock provider responses in tests;
use harmless generated images and synthetic metadata.

Document API contract changes and configuration defaults. Schema changes need
an explicit, tested migration with backup and recovery instructions. Reproduce
bugs with the minimum necessary metadata. Report suspected vulnerabilities
privately using SECURITY.md.

Contributions are licensed under the project's MIT license. Keep dependency and
font notices intact. Do not add images, fonts or code whose redistribution
license is unknown.
