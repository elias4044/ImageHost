import hashlib
import io
import socket
from unittest.mock import patch

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.images import normalizeImage
from app.scanners import BLOCKED_LABELS, ContentBlocked, ScanUnavailable, antivirus, scanImage


class FakeSocket:
    def __init__(self, reply):
        self.reply = iter(reply)
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def sendall(self, chunk):
        self.sent += chunk

    def recv(self, size):
        return next(self.reply, b"")


@pytest.mark.parametrize(
    "reply,expected",
    [
        ([b"stream: ", b"OK\0"], None),
        ([b"stream: Eicar FOUND\0"], ContentBlocked),
        ([b"stream: ERROR\0"], ScanUnavailable),
        ([b"stream: OK"], ScanUnavailable),
        ([b""], ScanUnavailable),
    ],
)
def test_clamav_stream_protocol(reply, expected):
    stream = FakeSocket(reply)
    with patch("app.scanners.socket.create_connection", return_value=stream):
        if expected:
            with pytest.raises(expected):
                antivirus(Settings(), b"test")
        else:
            antivirus(Settings(), b"test")
    assert stream.sent == b"zINSTREAM\0\0\0\0\x04test\0\0\0\0"


def test_clamav_connection_error_fails_closed():
    settings = Settings(
        nsfwBackend="http",
        antivirusEnabled=True,
        nsfwToken="local-scanner-test-token-32-characters",
        safetyUrl="https://safety.example",
        safetyToken="secret",
    )
    with (
        patch("app.scanners.socket.create_connection", side_effect=socket.timeout),
        pytest.raises(ScanUnavailable),
    ):
        scanImage(settings, b"original", b"normalized", "id", "digest")


@pytest.mark.parametrize(
    "variant",
    [
        "clean",
        "bad_identity",
        "missing_score",
        "redirect",
        "nsfw_error",
        "exposed",
        "bad_json",
        "nsfw_identity",
    ],
)
def test_full_provider_contract(variant):
    settings = Settings(
        nsfwBackend="http",
        antivirusEnabled=True,
        nsfwToken="local-scanner-test-token-32-characters",
        safetyUrl="https://safety.example/scan",
        safetyToken="secret",
    )
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "safety.example":
            assert request.headers["authorization"] == "Bearer secret"
            assert request.headers["idempotency-key"] == "id"
            assert b"original" in request.content
            if variant == "redirect":
                return httpx.Response(302, headers={"Location": "https://other.example"})
            return httpx.Response(
                200,
                json={
                    "image_id": "other" if variant == "bad_identity" else "id",
                    "sha256": "digest",
                    "decision": "allow",
                },
            )
        assert request.content == b"normalized"
        assert request.url.host == "nsfw"
        assert request.headers["authorization"] == "Bearer local-scanner-test-token-32-characters"
        if variant == "bad_json":
            return httpx.Response(200, content=b"not json")
        scores = dict.fromkeys(BLOCKED_LABELS, 0.01)
        scores["FEMALE_BREAST_EXPOSED"] = 0.9 if variant == "exposed" else 0.01
        if variant == "missing_score":
            del scores["ANUS_EXPOSED"]
        return httpx.Response(
            503 if variant == "nsfw_error" else 200,
            json={
                "image_id": "different" if variant == "nsfw_identity" else "id",
                "sha256": hashlib.sha256(b"normalized").hexdigest(),
                "model": "nudenet-3.4.2-320n",
                "scores": scores,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with patch("app.scanners.antivirus") as av, patch("app.scanners.httpx.Client", return_value=client):
        if variant == "clean":
            scanImage(settings, b"original", b"normalized", "id", "digest")
            assert len(calls) == 2
            assert av.call_count == 2
        else:
            with pytest.raises(ContentBlocked if variant == "exposed" else ScanUnavailable):
                scanImage(settings, b"original", b"normalized", "id", "digest")


def test_palette_transparency_preserved_and_metadata_removed():
    source = Image.new("P", (12, 12), 0)
    source.info["transparency"] = 0
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    content, width, height, _ = normalizeImage(buffer.getvalue())
    decoded = Image.open(io.BytesIO(content)).convert("RGBA")
    assert width == height == 12
    assert decoded.getpixel((0, 0))[3] == 0
    assert not decoded.getexif()
