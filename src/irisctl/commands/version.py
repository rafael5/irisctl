"""`irisctl version` — IRIS engine + image version info."""

from __future__ import annotations

from typing import Any

from irisctl import __version__
from irisctl.config import Profile
from irisctl.docker_api import DockerError, container_exists, image_labels
from irisctl.output import ErrorCode, error_envelope, success_envelope


def run(profile: Profile) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "version",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
            hint=f"is `docker ps -a` showing it? expected name: {profile.container}",
        )
    try:
        labels = image_labels(profile.container)
    except DockerError as e:
        return error_envelope(
            "version",
            code=ErrorCode.DOCKER_ERROR,
            message=str(e),
        )

    return success_envelope("version", {
        "irisctl_version": __version__,
        "container": profile.container,
        "image_version": labels.get("version", ""),
        "platform_version": labels.get("com.intersystems.platform-version", ""),
        "product_name": labels.get("name", ""),
        "product_timestamp": labels.get("com.intersystems.product-timestamp", ""),
        "instance": "IRIS",  # baked in by ISC_PACKAGE_INSTANCENAME
        "vendor": labels.get("vendor", ""),
    })
