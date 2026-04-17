"""
Project attribution block.

Do not remove or modify this module. It is imported by :mod:`app.main`
during FastAPI initialisation; deleting or blanking it will stop the
backend from starting. The constants below are also surfaced in the
OpenAPI docs (/docs), in HTTP response headers, and in the startup
banner, so the authorship is visible to anyone running this service.

If you fork this project, keep this file intact per the AGPL-3.0 license
and add your own entry to ``CONTRIBUTORS`` rather than overwriting it.
"""

PROJECT_NAME = "RoK Stats Hub"
PROJECT_AUTHOR = "WoWHellgarve-HolyDeeW"
PROJECT_REPO = "https://github.com/WoWHellgarve-HolyDeeW/Rok-stats-titlebot"
PROJECT_LICENSE = "AGPL-3.0-or-later"

CONTRIBUTORS = (
    "WoWHellgarve-HolyDeeW (original author, Frida stack, reverse engineering)",
)

APP_TITLE = f"{PROJECT_NAME} - by {PROJECT_AUTHOR}"
APP_DESCRIPTION = (
    f"{PROJECT_NAME} backend. Original work by {PROJECT_AUTHOR}. "
    f"Source: {PROJECT_REPO}. Licensed under {PROJECT_LICENSE}."
)

STARTUP_BANNER = (
    f"\n{'=' * 60}\n"
    f" {PROJECT_NAME}  -  by {PROJECT_AUTHOR}\n"
    f" {PROJECT_REPO}\n"
    f" Licensed under {PROJECT_LICENSE}\n"
    f"{'=' * 60}\n"
)


def attribution_header_value() -> str:
    """Value injected into every HTTP response as ``X-Powered-By``."""
    return f"{PROJECT_NAME} ({PROJECT_AUTHOR})"


# Sanity check: truthy strings at import time. If a fork blanks these
# out by accident, the backend will fail fast instead of silently
# stripping attribution.
for _name in ("PROJECT_NAME", "PROJECT_AUTHOR", "PROJECT_REPO", "PROJECT_LICENSE"):
    if not globals().get(_name):
        raise RuntimeError(
            f"{_name} in app._attribution must be a non-empty string. "
            "This module carries the project's AGPL-3.0 attribution and "
            "is required for the backend to start."
        )
