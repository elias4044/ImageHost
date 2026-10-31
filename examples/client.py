"""Upload from a server application and wait for a definitive screening result."""

import os
import sys
import time
from pathlib import Path

import httpx


def uploadAndWait(path: Path, public=True):
    origin = os.environ["IMAGEHOST_URL"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['IMAGEHOST_KEY']}"}
    with httpx.Client(base_url=origin, headers=headers, timeout=60, follow_redirects=False) as client:
        with path.open("rb") as content:
            response = client.post(
                "/api/v1/images", files={"file": (path.name, content)}, data={"public": str(public).lower()}
            )
        response.raise_for_status()
        image = response.json()
        deadline = time.monotonic() + 120
        delay = 2
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/images/{image['id']}")
            if response.status_code == 429:
                time.sleep(min(60, int(response.headers.get("Retry-After", "60"))))
                continue
            response.raise_for_status()
            image = response.json()
            if image["state"] == "ready":
                return image
            if image["state"] in ("blocked", "expired"):
                raise RuntimeError(f"Image was not approved: {image['state']}")
            time.sleep(delay)
            delay = min(10, delay + 1)
        raise TimeoutError(f"Image {image['id']} remains private in state {image['state']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python examples/client.py /path/to/image.png")
    print(uploadAndWait(Path(sys.argv[1])))
