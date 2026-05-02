#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import shutil
import stat
import sys
from pathlib import Path


EXECUTABLE_PATTERNS = (
    "**/Camoufox.app/Contents/MacOS/camoufox",
    "**/Camoufox.app/Contents/MacOS/Camoufox",
    "**/camoufox-bin",
    "**/camoufox.exe",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract a built Camoufox artifact and locate its executable."
    )
    parser.add_argument(
        "--artifact",
        required=True,
        help="Path to an artifact zip, or a directory containing exactly one artifact zip.",
    )
    parser.add_argument(
        "--extract-dir",
        required=True,
        help="Directory where the artifact contents should be extracted.",
    )
    parser.add_argument(
        "--github-output",
        default=None,
        help="Optional path to the GITHUB_OUTPUT file for step outputs.",
    )
    return parser.parse_args()


def resolve_artifact(path: Path) -> Path:
    if path.is_file():
        return path

    artifacts = sorted(path.glob("*.zip"))
    if len(artifacts) != 1:
        raise SystemExit(
            f"Expected exactly one zip artifact in {path}, found {len(artifacts)}: {artifacts}"
        )
    return artifacts[0]


def resolve_executable(extract_dir: Path) -> Path:
    for pattern in EXECUTABLE_PATTERNS:
        matches = sorted(extract_dir.glob(pattern))
        if matches:
            executable = matches[0]
            if executable.suffix != ".exe":
                executable.chmod(
                    executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                )
            return executable
    raise SystemExit(f"Could not find a Camoufox executable under {extract_dir}")


def extract_artifact(artifact: Path, extract_dir: Path) -> None:
    if sys.platform == "darwin":
        command = ["ditto", "-x", "-k", str(artifact), str(extract_dir)]
    else:
        command = ["unzip", "-q", str(artifact), "-d", str(extract_dir)]
    subprocess.run(command, check=True, env=os.environ.copy())


def write_output(path: Path, executable_path: Path) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"executable_path={executable_path}\n")


def main() -> int:
    args = parse_args()
    artifact = resolve_artifact(Path(args.artifact).resolve())
    extract_dir = Path(args.extract_dir).resolve()

    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    extract_artifact(artifact, extract_dir)

    executable = resolve_executable(extract_dir)
    print(executable)

    if args.github_output:
        write_output(Path(args.github_output), executable)

    return 0


if __name__ == "__main__":
    sys.exit(main())
