"""One-shot local scanner over stdin/stdout, without an HTTP service. AGPL-3.0-or-later."""

import json
import os
import re
import sys

from moderation.inference import detectionScores, loadDetector, prepareImage, scanResult


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[a-f0-9]{32}", sys.argv[1]):
        raise SystemExit("Expected an image identifier")
    limit = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024**2
    content = sys.stdin.buffer.read(limit + 1)
    if not content or len(content) > limit:
        raise SystemExit("Invalid scanner input size")
    prepared = prepareImage(content)
    detector = loadDetector()
    scores = detectionScores(detector.detect(prepared))
    print(json.dumps(scanResult(sys.argv[1], content, scores)))


if __name__ == "__main__":
    main()
