import hashlib
import io
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from moderation.server import MODEL, createApp, detectionScores

TOKEN = "test-local-scanner-secret-at-least-32-characters"
IMAGE_ID = "a" * 32


def webp():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, "WEBP")
    return buffer.getvalue()


def headers(content):
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "image/webp",
        "X-Image-ID": IMAGE_ID,
        "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
    }


@pytest.fixture
def localScanner():
    detector = Mock()
    detector.detect.return_value = []
    with TestClient(createApp(lambda: detector, token=TOKEN)) as client:
        yield client, detector


def test_local_scanner_auth_identity_and_clean_result(localScanner):
    client, detector = localScanner
    content = webp()
    assert client.get("/health/ready").json() == {"ready": True, "model": MODEL}
    assert (
        client.post(
            "/scan", content=content, headers={**headers(content), "Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    response = client.post("/scan", content=content, headers=headers(content))
    assert response.status_code == 200
    assert response.json()["image_id"] == IMAGE_ID
    assert response.json()["sha256"] == hashlib.sha256(content).hexdigest()
    assert response.json()["scores"]["ANUS_EXPOSED"] == 0
    decoded = Image.open(io.BytesIO(detector.detect.call_args.args[0]))
    assert decoded.size == (32, 32)


def test_local_scanner_rejects_tampered_or_invalid_bytes(localScanner):
    client, _ = localScanner
    content = webp()
    assert client.post("/scan", content=content, headers=headers(b"different")).status_code == 422
    assert client.post("/scan", content=b"invalid", headers=headers(b"invalid")).status_code == 415


def test_local_scanner_errors_never_return_clean_scores(localScanner):
    client, detector = localScanner
    detector.detect.side_effect = RuntimeError("Model failed")
    content = webp()
    assert client.post("/scan", content=content, headers=headers(content)).status_code == 503


def test_local_scanner_exposed_nudity_and_max_score(localScanner):
    client, detector = localScanner
    detector.detect.return_value = [
        {"class": "ANUS_EXPOSED", "score": 0.7},
        {"class": "ANUS_EXPOSED", "score": 0.9},
    ]
    content = webp()
    assert (
        client.post("/scan", content=content, headers=headers(content)).json()["scores"]["ANUS_EXPOSED"]
        == 0.9
    )


def test_local_scanner_bounds_streamed_request_size():
    detector = Mock()
    detector.detect.return_value = []
    with TestClient(createApp(lambda: detector, token=TOKEN, maxUploadBytes=8)) as client:
        content = webp()
        assert (
            client.post(
                "/scan", content=iter([content[:8], content[8:]]), headers=headers(content)
            ).status_code
            == 413
        )


@pytest.mark.parametrize(
    "detections",
    [
        None,
        {},
        [{"class": "unknown", "score": 0.1}],
        [{"class": "ANUS_EXPOSED", "score": float("nan")}],
        [{"class": "ANUS_EXPOSED", "score": True}],
    ],
)
def test_invalid_detections_fail_closed(detections):
    with pytest.raises(ValueError):
        detectionScores(detections)


def test_scanner_requires_strong_shared_token():
    with pytest.raises(ValueError):
        createApp(token="weak")
