"""Check the running local model using an innocuous generated image."""

import hashlib
import io
import json
import os
import urllib.request

from PIL import Image


def main():
    image = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(image, "WEBP")
    content = image.getvalue()
    request = urllib.request.Request(
        "http://localhost:8080/scan",
        data=content,
        headers={
            "Authorization": "Bearer " + os.environ["NSFW_TOKEN"],
            "Content-Type": "image/webp",
            "X-Image-ID": "a" * 32,
            "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)
    assert result["model"] == "nudenet-3.4.2-320n"
    assert len(result["scores"]) == 18
    assert result["sha256"] == hashlib.sha256(content).hexdigest()
    print("Local model inference passed")


if __name__ == "__main__":
    main()
