#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import stat
import sys
from pathlib import Path
from zipfile import ZipFile


EXECUTABLE_PATTERNS = (
    "**/Camoufox.app/Contents/MacOS/camoufox",
    "**/Camoufox.app/Contents/MacOS/Camoufox",
    "**/camoufox-bin",
    "**/camoufox.exe",
)

MACH_O_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


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


def looks_executable(path: Path) -> bool:
    if not path.is_file():
        return False

    try:
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        return False

    if header.startswith(b"#!"):
        return True
    if header[:4] == b"\x7fELF":
        return True
    if header[:4] in MACH_O_MAGICS:
        return True
    return False


def restore_executable_bits(extract_dir: Path) -> None:
    for path in extract_dir.rglob("*"):
        if not looks_executable(path):
            continue
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


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

    with ZipFile(artifact) as archive:
        archive.extractall(extract_dir)

    # Python's ZipFile extraction does not preserve Unix executable bits.
    restore_executable_bits(extract_dir)

    executable = resolve_executable(extract_dir)
    print(executable)

    if args.github_output:
        write_output(Path(args.github_output), executable)

    return 0


if __name__ == "__main__":
    sys.exit(main())
