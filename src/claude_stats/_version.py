from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

PACKAGE_NAME = "claude-stats"
FALLBACK_VERSION = "0.0.0"


def get_version() -> str:
    installed = _get_installed_version()
    if installed is not None:
        return installed

    dev_version = _get_version_from_pyproject()
    if dev_version is not None:
        return dev_version

    return FALLBACK_VERSION


def _get_installed_version() -> str | None:
    try:
        return _pkg_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return None


def _get_version_from_pyproject() -> str | None:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            with pyproject.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        project_version = data.get("project", {}).get("version")
        if isinstance(project_version, str):
            return project_version
    return None