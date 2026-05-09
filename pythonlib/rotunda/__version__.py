from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version


def installed_library_version() -> str:
    try:
        return package_version("rotunda")
    except PackageNotFoundError:
        return "0+unknown"
