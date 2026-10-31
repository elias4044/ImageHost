"""NudeNet inference shared by the HTTP service and local process. AGPL-3.0-or-later."""

import hashlib
import io
import math
import warnings
from pathlib import Path

from PIL import Image

MODEL = "nudenet-3.4.2-320n"
MODEL_SHA256 = "c15d8273adad2d0a92f014cc69ab2d6c311a06777a55545f2c4eb46f51911f0f"
LABELS = (
    "FEMALE_GENITALIA_COVERED",
    "FACE_FEMALE",
    "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "ANUS_EXPOSED",
    "FEET_EXPOSED",
    "BELLY_COVERED",
    "FEET_COVERED",
    "ARMPITS_COVERED",
    "ARMPITS_EXPOSED",
    "FACE_MALE",
    "BELLY_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_COVERED",
    "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
)
Image.MAX_IMAGE_PIXELS = 25_000_000


def loadDetector():
    import nudenet
    from nudenet import NudeDetector

    modelPath = Path(nudenet.__file__).parent / "320n.onnx"
    if hashlib.sha256(modelPath.read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("Local model integrity check failed")
    return NudeDetector(providers=["CPUExecutionProvider"])


def detectionScores(detections):
    if not isinstance(detections, list):
        raise ValueError("Invalid detector result")
    scores = dict.fromkeys(LABELS, 0.0)
    for detection in detections:
        label, score = detection["class"], detection["score"]
        if (
            label not in scores
            or type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise ValueError("Invalid detection")
        scores[label] = max(scores[label], float(score))
    return scores


def prepareImage(content):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(content)) as image:
            if image.format != "WEBP" or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Expected a static WebP")
            image.load()
            # Bound NudeNet's square padding for very wide images.
            image.thumbnail((1280, 1280))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def scanResult(imageId, content, scores):
    return {
        "image_id": imageId,
        "sha256": hashlib.sha256(content).hexdigest(),
        "model": MODEL,
        "scores": scores,
    }
