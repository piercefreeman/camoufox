# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "packaging",
# ]
# ///

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version


PROJECT_SECTION = re.compile(r"^\[project\]\s*$")
SECTION_HEADER = re.compile(r"^\[[^\]]+\]\s*$")
VERSION_LINE = re.compile(r'^version\s*=\s*"[^"]*"\s*$')


def _read_upstream_firefox_version() -> str | None:
    upstream = Path("upstream.sh")
    if not upstream.exists():
        return None

    for line in upstream.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"version=(.+)", line.strip())
        if match:
            return match.group(1)
    return None


def _candidate_versions(raw_version: str) -> list[str]:
    cleaned = raw_version.strip()
    cleaned = cleaned.removeprefix("refs/tags/")
    cleaned = cleaned.removeprefix("rotunda-")
    cleaned = cleaned.removeprefix("v")

    candidates = [cleaned]

    firefox_version = _read_upstream_firefox_version()
    if firefox_version and not cleaned.startswith(firefox_version):
        candidates.append(f"{firefox_version}-{cleaned}")

    return candidates


def normalize_python_version(raw_version: str) -> str:
    for candidate in _candidate_versions(raw_version):
        try:
            return str(Version(candidate))
        except InvalidVersion:
            continue

    attempted = ", ".join(_candidate_versions(raw_version))
    raise ValueError(f"Could not derive a PEP 440 version from {raw_version!r}; tried {attempted}.")


def update_pyproject_version(pyproject_path: Path, python_version: str) -> None:
    lines = pyproject_path.read_text(encoding="utf-8").splitlines()
    in_project = False
    updated = False

    for idx, line in enumerate(lines):
        if PROJECT_SECTION.match(line):
            in_project = True
            continue

        if in_project and SECTION_HEADER.match(line):
            break

        if in_project and VERSION_LINE.match(line):
            lines[idx] = f'version = "{python_version}"'
            updated = True
            break

    if not updated:
        raise ValueError(f"Could not find [project] version in {pyproject_path}.")

    pyproject_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_github_output(python_version: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return

    with Path(github_output).open("a", encoding="utf-8") as output:
        output.write(f"python_version={python_version}\n")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: update-python-version.py <tag-or-release-version>", file=sys.stderr)
        return 2

    python_version = normalize_python_version(sys.argv[1])
    update_pyproject_version(Path("pyproject.toml"), python_version)
    write_github_output(python_version)
    print(f"Updated Python package version to {python_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
