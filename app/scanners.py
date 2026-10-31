import hashlib
import json
import math
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

import httpx


class ScanUnavailable(Exception):
    pass


class ContentBlocked(Exception):
    pass


BLOCKED_LABELS = (
    "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "BUTTOCKS_EXPOSED",
)


def antivirus(settings, content):
    with socket.create_connection((settings.clamavHost, settings.clamavPort), timeout=30) as stream:
        stream.sendall(b"zINSTREAM\0")
        for offset in range(0, len(content), 65536):
            chunk = content[offset : offset + 65536]
            stream.sendall(struct.pack("!I", len(chunk)) + chunk)
        stream.sendall(struct.pack("!I", 0))
        reply = b""
        while not reply.endswith(b"\0") and len(reply) < 4096:
            chunk = stream.recv(1024)
            if not chunk:
                break
            reply += chunk
    if reply.endswith(b" FOUND\0"):
        raise ContentBlocked("malware")
    if reply != b"stream: OK\0":
        raise ScanUnavailable("antivirus_response")


def probability(value):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ScanUnavailable("invalid_nsfw_score")
    return value


def specialistScan(settings, client, original, imageId, digest):
    try:
        response = client.post(
            settings.safetyUrl,
            headers={"Authorization": f"Bearer {settings.safetyToken}", "Idempotency-Key": imageId},
            data={"image_id": imageId, "sha256": digest},
            files={"file": ("upload.bin", original, "application/octet-stream")},
        )
        response.raise_for_status()
        result = response.json()
        if result.get("image_id") != imageId or result.get("sha256") != digest:
            raise ScanUnavailable("specialist_identity")
        if result.get("decision") == "block":
            raise ContentBlocked("specialist_policy")
        if result.get("decision") != "allow":
            raise ScanUnavailable("specialist_review")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
        raise ScanUnavailable("specialist_unavailable") from error


def localNsfw(settings, normalized, imageId):
    try:
        process = subprocess.run(
            [sys.executable, "-m", "moderation.classify", imageId],
            input=normalized,
            capture_output=True,
            timeout=45,
            check=False,
            cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "MAX_UPLOAD_MB": str(math.ceil(settings.maxUploadBytes / 1024**2))},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise ScanUnavailable("nsfw_local_timeout") from error
    except OSError as error:
        raise ScanUnavailable("nsfw_local_unavailable") from error
    if process.returncode != 0:
        raise ScanUnavailable("nsfw_local_failed")
    try:
        return json.loads(process.stdout)
    except ValueError as error:
        raise ScanUnavailable("nsfw_response") from error


def httpNsfw(settings, client, normalized, imageId):
    try:
        response = client.post(
            settings.nsfwUrl,
            content=normalized,
            headers={
                "Authorization": f"Bearer {settings.nsfwToken}",
                "Content-Type": "image/webp",
                "X-Image-ID": imageId,
                "X-Content-SHA256": hashlib.sha256(normalized).hexdigest(),
            },
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as error:
        code = "nsfw_auth_failed" if error.response.status_code == 401 else "nsfw_service_unavailable"
        raise ScanUnavailable(code) from error
    except (httpx.HTTPError, ValueError) as error:
        raise ScanUnavailable("nsfw_service_unavailable") from error


def validateNsfw(settings, result, normalized, imageId):
    try:
        if (
            result.get("image_id") != imageId
            or result.get("sha256") != hashlib.sha256(normalized).hexdigest()
            or result.get("model") != "nudenet-3.4.2-320n"
        ):
            raise ScanUnavailable("nsfw_response")
        scores = [probability(result["scores"][label]) for label in BLOCKED_LABELS]
        if max(scores) >= settings.nsfwThreshold:
            raise ContentBlocked("nsfw_policy")
    except (KeyError, TypeError, AttributeError) as error:
        raise ScanUnavailable("nsfw_response") from error


def scanImage(settings, original, normalized, imageId, digest):
    configured = settings.scannerConfig()
    for name in settings.requiredScanners():
        if not configured[name]:
            raise ScanUnavailable(f"{name}_not_configured")
    if settings.antivirusEnabled:
        try:
            antivirus(settings, original)
            antivirus(settings, normalized)
        except OSError as error:
            raise ScanUnavailable("antivirus_unavailable") from error
    with httpx.Client(timeout=45, follow_redirects=False, trust_env=False) as client:
        if "specialist" in settings.requiredScanners():
            specialistScan(settings, client, original, imageId, digest)
        result = (
            localNsfw(settings, normalized, imageId)
            if settings.nsfwBackend == "local"
            else httpNsfw(settings, client, normalized, imageId)
        )
    validateNsfw(settings, result, normalized, imageId)
