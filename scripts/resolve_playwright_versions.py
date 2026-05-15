#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PYPI_PACKAGE_URL = "https://pypi.org/pypi/{package}/json"
STABLE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve recent stable Playwright release lines from PyPI. "
            "For each major.minor line, the newest patch release is selected."
        )
    )
    parser.add_argument(
        "--package",
        default="playwright",
        help="PyPI package name to inspect.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of recent major.minor release lines to return.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20,
        help="PyPI request timeout in seconds.",
    )
    parser.add_argument(
        "--github-output",
        default=None,
        help="Optional path to GITHUB_OUTPUT.",
    )
    parser.add_argument(
        "--output-name",
        default="versions",
        help="GITHUB_OUTPUT key to write.",
    )
    return parser.parse_args()


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
) -> list[str]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    stable_versions: list[tuple[tuple[int, int, int], str]] = []
    for version, files in releases.items():
        parsed = _stable_version_tuple(version)
        if parsed is None or not _has_installable_file(files):
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


def main() -> int:
    args = parse_args()
    metadata = fetch_pypi_metadata(args.package, timeout=args.timeout)
    versions = select_recent_minor_versions(metadata["releases"], limit=args.limit)
    if not versions:
        raise SystemExit(f"No stable releases found for {args.package}.")

    output = json.dumps(versions, separators=(",", ":"))
    print(output)

    if args.github_output:
        write_github_output(Path(args.github_output), args.output_name, output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
