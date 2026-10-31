import hashlib
import json
import subprocess
from unittest.mock import Mock, patch

import pytest

from app.config import Settings
from app.scanners import BLOCKED_LABELS, ContentBlocked, ScanUnavailable, scanImage


def result(score=0):
    return {
        "image_id": "a" * 32,
        "sha256": hashlib.sha256(b"normalized").hexdigest(),
        "model": "nudenet-3.4.2-320n",
        "scores": dict.fromkeys(BLOCKED_LABELS, score),
    }


def test_native_nsfw_only_has_no_external_service_requirement():
    settings = Settings(nsfwBackend="local", antivirusEnabled=False, safetyUrl="", safetyToken="")
    assert settings.requiredScanners() == ["nsfw"]
    process = Mock(returncode=0, stdout=json.dumps(result()).encode())
    with (
        patch("app.config.find_spec", return_value=object()),
        patch("app.scanners.subprocess.run", return_value=process) as run,
        patch("app.scanners.antivirus") as av,
        patch("httpx.Client.post") as post,
    ):
        scanImage(settings, b"original", b"normalized", "a" * 32, "digest")
        assert run.call_args.kwargs["input"] == b"normalized"
        assert run.call_args.kwargs["timeout"] == 45
        av.assert_not_called()
        post.assert_not_called()


@pytest.mark.parametrize("score", [0.5, 0.9])
def test_local_nsfw_rejection_is_not_approval(score):
    settings = Settings(nsfwBackend="local", antivirusEnabled=False, safetyUrl="", safetyToken="")
    process = Mock(returncode=0, stdout=json.dumps(result(score)).encode())
    with (
        patch("app.config.find_spec", return_value=object()),
        patch("app.scanners.subprocess.run", return_value=process),
        pytest.raises(ContentBlocked),
    ):
        scanImage(settings, b"original", b"normalized", "a" * 32, "digest")


@pytest.mark.parametrize(
    "mode,reason",
    [("timeout", "nsfw_local_timeout"), ("exit", "nsfw_local_failed"), ("malformed", "nsfw_response")],
)
def test_native_scanner_failures_keep_quarantine(mode, reason):
    settings = Settings(nsfwBackend="local", antivirusEnabled=False, safetyUrl="", safetyToken="")
    process = Mock(returncode=1 if mode == "exit" else 0, stdout=b"invalid json")
    with (
        patch("app.config.find_spec", return_value=object()),
        patch(
            "app.scanners.subprocess.run",
            return_value=process,
            side_effect=subprocess.TimeoutExpired("scanner", 45) if mode == "timeout" else None,
        ),
        pytest.raises(ScanUnavailable, match=reason),
    ):
        scanImage(settings, b"original", b"normalized", "a" * 32, "digest")


def test_enabled_optional_checks_still_fail_closed():
    settings = Settings(
        nsfwBackend="local", antivirusEnabled=True, clamavHost="", safetyUrl="", safetyToken=""
    )
    with (
        patch("app.config.find_spec", return_value=object()),
        pytest.raises(ScanUnavailable, match="antivirus_not_configured"),
    ):
        scanImage(settings, b"original", b"normalized", "a" * 32, "digest")
    settings.antivirusEnabled = False
    settings.safetyUrl = "https://safety.example/scan"
    assert "specialist" in settings.requiredScanners()
    with (
        patch("app.config.find_spec", return_value=object()),
        pytest.raises(ScanUnavailable, match="specialist_not_configured"),
    ):
        scanImage(settings, b"original", b"normalized", "a" * 32, "digest")
