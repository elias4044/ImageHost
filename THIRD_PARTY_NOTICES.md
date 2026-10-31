# Third-party notices

ImageHost hosting application code is MIT licensed. The standalone moderation
service is licensed under AGPL-3.0-or-later (moderation/LICENSE). Dependencies retain their own
licenses; consult installed package metadata and upstream sources.

IBM Plex Sans by IBM is bundled locally under the SIL Open Font License 1.1.
The complete upstream license is at app/static/fonts/OFL.txt. Source:
[IBM/Plex](https://github.com/IBM/plex). Font files were fetched through Google Fonts.
No font requests are made to Google by the running dashboard.

The dashboard mark and chart renderer are original code for this project.
No stock photographs or sample customer assets are bundled.

ClamAV is a separate GPL-licensed container service. Its image and signature
distribution retain their respective terms.

NudeNet 3.4.2 and its bundled 320n ONNX model run in a separate private service.
The published wheel includes both an AGPL LICENSE and an MIT LICENSE.md while
its package metadata says MIT. This project conservatively preserves the AGPL
license for the scanner rather than claiming the dependency is MIT-only.
Its source is [notAI-tech/NudeNet](https://github.com/notAI-tech/NudeNet).
The pinned package, source files, model and upstream licenses remain installed
inside the scanner image; this repository includes the wrapper source, build
instructions and AGPL license under moderation/. The MIT hosting license does
not replace those notices. Preserve source availability when distributing or
modifying the scanner.

Any specialist screening system has its own terms, separate from these licenses.
