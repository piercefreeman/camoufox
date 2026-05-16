#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "click>=8.1",
# ]
# ///

from __future__ import annotations

import os
import subprocess
import shutil
import stat
import sys
from pathlib import Path

import click


EXECUTABLE_PATTERNS = (
    "**/Rotunda.app/Contents/MacOS/rotunda",
    "**/Rotunda.app/Contents/MacOS/Rotunda",
    "**/rotunda-bin",
    "**/rotunda.exe",
)


def resolve_artifact(path: Path) -> Path:
    if path.is_file():
        return path

    artifacts = sorted(path.glob("*.zip"))
    if len(artifacts) != 1:
        raise click.ClickException(
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
    raise click.ClickException(f"Could not find a Rotunda executable under {extract_dir}")


def extract_artifact(artifact: Path, extract_dir: Path) -> None:
    if sys.platform == "darwin":
        command = ["ditto", "-x", "-k", str(artifact), str(extract_dir)]
    else:
        command = ["unzip", "-q", str(artifact), "-d", str(extract_dir)]
    subprocess.run(command, check=True, env=os.environ.copy())


def write_output(path: Path, executable_path: Path) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"executable_path={executable_path}\n")


@click.command()
@click.option(
    "--artifact",
    required=True,
    type=click.Path(path_type=Path),
    help="Path to an artifact zip, or a directory containing exactly one artifact zip.",
)
@click.option(
    "--extract-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory where the artifact contents should be extracted.",
)
@click.option(
    "--github-output",
    type=click.Path(path_type=Path),
    help="Optional path to the GITHUB_OUTPUT file for step outputs.",
)
def main(artifact: Path, extract_dir: Path, github_output: Path | None) -> None:
    """Extract a built Rotunda artifact and locate its executable."""
    artifact = resolve_artifact(artifact.resolve())
    extract_dir = extract_dir.resolve()

    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    extract_artifact(artifact, extract_dir)

    executable = resolve_executable(extract_dir)
    click.echo(executable)

    if github_output:
        write_output(github_output, executable)


if __name__ == "__main__":
    main()
