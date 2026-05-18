#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "click>=8.1",
# ]
# ///

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import click


PYPI_PACKAGE_URL = "https://pypi.org/pypi/{package}/json"
STABLE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
DEFAULT_MINIMUM_VERSION = "1.51.0"


def _stable_version_tuple(version: str) -> tuple[int, int, int] | None:
    match = STABLE_VERSION_RE.match(version)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _has_installable_file(files: list[dict[str, Any]]) -> bool:
    return any(not file.get("yanked", False) for file in files)


def select_recent_minor_versions(
    releases: dict[str, list[dict[str, Any]]],
    *,
    limit: int,
    minimum_version: str,
) -> list[str]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    minimum = _stable_version_tuple(minimum_version)
    if minimum is None:
        raise ValueError(f"minimum_version must be a stable x.y.z version: {minimum_version}")

    stable_versions: list[tuple[tuple[int, int, int], str]] = []
    for version, files in releases.items():
        parsed = _stable_version_tuple(version)
        if parsed is None or parsed < minimum or not _has_installable_file(files):
            continue
        stable_versions.append((parsed, version))

    latest_by_minor: dict[tuple[int, int], tuple[tuple[int, int, int], str]] = {}
    for parsed, version in sorted(stable_versions, key=lambda item: item[0]):
        latest_by_minor[(parsed[0], parsed[1])] = (parsed, version)

    recent = sorted(latest_by_minor.values(), key=lambda item: item[0])[-limit:]
    return [version for _, version in recent]


def fetch_pypi_metadata(package: str, *, timeout: float) -> dict[str, Any]:
    quoted_package = urllib.parse.quote(package, safe="")
    request = urllib.request.Request(
        PYPI_PACKAGE_URL.format(package=quoted_package),
        headers={"User-Agent": "rotunda-ci"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def write_github_output(path: Path, name: str, value: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


@click.command()
@click.option(
    "--package",
    "package_name",
    default="playwright",
    show_default=True,
    help="PyPI package name to inspect.",
)
@click.option(
    "--limit",
    default=10,
    show_default=True,
    type=click.IntRange(min=1),
    help="Number of recent major.minor release lines to return.",
)
@click.option(
    "--timeout",
    default=20.0,
    show_default=True,
    type=float,
    help="PyPI request timeout in seconds.",
)
@click.option(
    "--minimum-version",
    default=DEFAULT_MINIMUM_VERSION,
    show_default=True,
    help="Oldest stable Playwright version Rotunda supports.",
)
@click.option(
    "--github-output",
    type=click.Path(path_type=Path),
    help="Optional path to GITHUB_OUTPUT.",
)
@click.option(
    "--output-name",
    default="versions",
    show_default=True,
    help="GITHUB_OUTPUT key to write.",
)
def main(
    package_name: str,
    limit: int,
    timeout: float,
    minimum_version: str,
    github_output: Path | None,
    output_name: str,
) -> None:
    """Resolve recent stable Playwright release lines from PyPI."""
    metadata = fetch_pypi_metadata(package_name, timeout=timeout)
    try:
        versions = select_recent_minor_versions(
            metadata["releases"],
            limit=limit,
            minimum_version=minimum_version,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not versions:
        raise click.ClickException(f"No stable releases found for {package_name}.")

    output = json.dumps(versions, separators=(",", ":"))
    click.echo(output)

    if github_output:
        write_github_output(github_output, output_name, output)


if __name__ == "__main__":
    main()
