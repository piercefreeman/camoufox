#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from _mixin import list_patches


REPO_ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_SH = REPO_ROOT / "upstream.sh"
PATCHES_DIR = REPO_ROOT / "patches"
ADDITIONS_DIR = REPO_ROOT / "additions"
SETTINGS_DIR = REPO_ROOT / "settings"
ASSETS_DIR = REPO_ROOT / "assets"
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIREFOX_TARBALL_URL = (
    "https://archive.mozilla.org/pub/firefox/releases/{version}/source/"
    "firefox-{version}.source.tar.xz"
)

PATCH_PATH_RE = re.compile(r"^(---|\+\+\+) ((?:[ab]/).+|/dev/null)$")
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*([<"])([^">]+)[">]')
MISSING_HEADER_RE = re.compile(r"fatal error: '([^']+)' file not found")

SOURCE_EXTENSIONS = {".cc", ".cpp", ".cxx"}
HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx"}
SCANNABLE_EXTENSIONS = SOURCE_EXTENSIONS | HEADER_EXTENSIONS | {".inc", ".inl"}
SKIPPED_SOURCE_EXTENSIONS = {".m", ".mm"}
GENERATED_HEADER_PATTERNS = (
    re.compile(r"mozilla/dom/.+Binding\.h$"),
    re.compile(r"mozilla/StaticPrefs_.+\.h$"),
)
NONPORTABLE_HEADERS = {
    "windows.h",
}
NONPORTABLE_PREFIXES = (
    "AppKit/",
    "ApplicationServices/",
    "Cocoa/",
    "CoreFoundation/",
    "CoreGraphics/",
    "Foundation/",
    "IOKit/",
    "dbus/",
    "gdk/",
    "gtk/",
    "objc/",
)
COMMON_DEFINES = (
    "MOZILLA_CLIENT",
    "MOZILLA_INTERNAL_API",
    "IMPL_LIBXUL",
    "MOZ_HAS_MOZGLUE",
    "STATIC_EXPORTABLE_JS_API",
    "TRIMMED=1",
    "NDEBUG=1",
)
STUB_HEADERS = {
    "mozilla-config.h": textwrap.dedent(
        """\
        #pragma once
        #define MOZILLA_CLIENT 1
        #define MOZILLA_INTERNAL_API 1
        #define IMPL_LIBXUL 1
        #define MOZ_HAS_MOZGLUE 1
        #define STATIC_EXPORTABLE_JS_API 1
        #define TRIMMED 1
        #define NDEBUG 1
        """
    ),
    "js-confdefs.h": "#pragma once\n",
    "js/src/js-confdefs.h": "#pragma once\n",
}
HELPER_SEEDED_PATHS = {
    "build/vs/pack_vs.py",
    "browser/config/version.txt",
    "browser/config/version_display.txt",
    "lw/camoufox.cfg",
    "lw/chrome.css",
    "lw/local-settings.js",
    "lw/moz.build",
    "lw/mozfetch.sh",
    "lw/policies.json",
    "services/settings/dumps/main/search-config.json",
}


@dataclass(frozen=True)
class BuildMetadata:
    version: str
    release: str


@dataclass(frozen=True)
class PatchEntry:
    old_path: str | None
    new_path: str | None

    @property
    def extract_path(self) -> str | None:
        return self.old_path

    @property
    def target_path(self) -> str | None:
        return self.new_path or self.old_path

    @property
    def is_deleted(self) -> bool:
        return self.new_path is None


@dataclass(frozen=True)
class PreparationFailure:
    target: str
    reason: str
    skip: bool


@dataclass(frozen=True)
class PreparedTarget:
    display_path: str
    compile_path: Path
    command: list[str]


@dataclass(frozen=True)
class SyntaxResult:
    display_path: str
    status: str
    reason: str | None = None
    output: str | None = None


def parse_upstream_metadata(upstream_path: Path = UPSTREAM_SH) -> BuildMetadata:
    values: dict[str, str] = {}
    for line in upstream_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    version = os.environ.get("CAMOUFOX_FIREFOX_VERSION", values["version"])
    release = os.environ.get("CAMOUFOX_RELEASE", values["release"])
    return BuildMetadata(version=version, release=release)


def order_patch_paths(paths: list[Path]) -> list[Path]:
    non_roverfox: list[Path] = []
    roverfox: list[Path] = []
    for patch_path in paths:
        if "roverfox" in patch_path.parts:
            roverfox.append(patch_path)
        else:
            non_roverfox.append(patch_path)
    return non_roverfox + roverfox


def active_patch_paths() -> list[Path]:
    raw_paths = [Path(path) for path in list_patches(str(PATCHES_DIR))]
    return order_patch_paths(raw_paths)


def parse_patch_entries(patch_path: Path) -> list[PatchEntry]:
    entries: list[PatchEntry] = []
    pending_old: str | None = None
    pending_old_seen = False

    for line in patch_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = PATCH_PATH_RE.match(line)
        if not match:
            continue

        marker, raw_path = match.groups()
        parsed_path = None if raw_path == "/dev/null" else raw_path[2:]
        if marker == "---":
            pending_old = parsed_path
            pending_old_seen = True
            continue

        if not pending_old_seen:
            raise ValueError(f"Malformed patch header sequence in {patch_path}")

        entries.append(PatchEntry(old_path=pending_old, new_path=parsed_path))
        pending_old = None
        pending_old_seen = False

    if pending_old_seen:
        raise ValueError(f"Unterminated patch header sequence in {patch_path}")

    return entries


def collect_patch_entries(patch_paths: list[Path]) -> dict[Path, list[PatchEntry]]:
    return {patch_path: parse_patch_entries(patch_path) for patch_path in patch_paths}


def normalize_posix(path: str) -> str:
    return PurePosixPath(path).as_posix()


def common_prefix_len(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    count = 0
    for left_part, right_part in zip(left, right):
        if left_part != right_part:
            break
        count += 1
    return count


def score_candidate(candidate: str, current_file: str) -> tuple[int, int, int, int]:
    candidate_parts = PurePosixPath(candidate).parent.parts
    current_parts = PurePosixPath(current_file).parent.parts
    same_top_level = 0 if candidate_parts[:1] == current_parts[:1] else 1
    shared_prefix = -common_prefix_len(candidate_parts, current_parts)
    depth_distance = abs(len(candidate_parts) - len(current_parts))
    length = len(candidate)
    return (same_top_level, shared_prefix, depth_distance, length)


def choose_best_candidate(candidates: list[str], current_file: str) -> str | None:
    if not candidates:
        return None

    scored = sorted((score_candidate(candidate, current_file), candidate) for candidate in candidates)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def is_generated_header(path: str) -> bool:
    return any(pattern.match(path) for pattern in GENERATED_HEADER_PATTERNS)


def is_nonportable_header(path: str) -> bool:
    return path in NONPORTABLE_HEADERS or path.startswith(NONPORTABLE_PREFIXES)


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


class TarIndex:
    def __init__(self, tarball_path: Path):
        self.tarball_path = tarball_path
        self.raw_members_by_relative_path: dict[str, str] = {}
        self.candidates_by_basename: dict[str, list[str]] = defaultdict(list)
        self._build_index()

    def _build_index(self) -> None:
        result = subprocess.run(
            ["tar", "-tf", str(self.tarball_path)],
            capture_output=True,
            check=True,
            text=True,
        )
        for raw_line in result.stdout.splitlines():
            raw_member = raw_line.strip()
            if not raw_member or raw_member.endswith("/"):
                continue
            relative_path = self._normalize_member(raw_member)
            if relative_path is None:
                continue
            self.raw_members_by_relative_path[relative_path] = raw_member
            self.candidates_by_basename[PurePosixPath(relative_path).name].append(relative_path)

    @staticmethod
    def _normalize_member(raw_member: str) -> str | None:
        parts = [part for part in PurePosixPath(raw_member).parts if part not in ("", ".")]
        if len(parts) < 2:
            return None
        return PurePosixPath(*parts[1:]).as_posix()

    def has(self, relative_path: str) -> bool:
        return relative_path in self.raw_members_by_relative_path

    def basename_candidates(self, basename: str) -> list[str]:
        return self.candidates_by_basename.get(basename, [])

    def extract(self, relative_paths: list[str], destination: Path) -> None:
        raw_members = [self.raw_members_by_relative_path[path] for path in relative_paths]
        for raw_chunk in chunked(raw_members, 200):
            subprocess.run(
                [
                    "tar",
                    "-xJf",
                    str(self.tarball_path),
                    "-C",
                    str(destination),
                    "--strip-components=1",
                    *raw_chunk,
                ],
                check=True,
            )


class PatchVerifier:
    def __init__(self, metadata: BuildMetadata, args: argparse.Namespace):
        self.metadata = metadata
        self.args = args
        self.patch_bin = shutil.which("gpatch") or shutil.which("patch") or "patch"
        self.patch_paths = active_patch_paths()
        self.patch_entries_by_path = collect_patch_entries(self.patch_paths)
        self.cache_dir = args.cache_dir
        self.tarball_path = self._resolve_tarball_path()
        self.tar_index = TarIndex(self.tarball_path)
        self.workdir = self._prepare_workdir()
        self.stub_dir = self.workdir / "__generated_stubs__"
        self.wrapper_dir = self.workdir / "__verify_wrappers__"
        self.workspace_paths: set[str] = set()
        self.workspace_paths_by_basename: dict[str, list[str]] = defaultdict(list)
        self.extracted_paths: set[str] = set()

    def _resolve_tarball_path(self) -> Path:
        if self.args.tarball is not None:
            print(f"Using explicit tarball: {self.args.tarball}")
            return self.args.tarball

        local_tarball = REPO_ROOT / f"firefox-{self.metadata.version}.source.tar.xz"
        if local_tarball.exists():
            print(f"Using local tarball: {local_tarball}")
            return local_tarball

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached_tarball = self.cache_dir / f"firefox-{self.metadata.version}.source.tar.xz"
        if cached_tarball.exists():
            print(f"Using cached tarball: {cached_tarball}")
            return cached_tarball

        url = FIREFOX_TARBALL_URL.format(version=self.metadata.version)
        temp_tarball = cached_tarball.with_suffix(".tmp")
        print(f"Downloading {url}")
        with urllib.request.urlopen(url) as response, temp_tarball.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        temp_tarball.replace(cached_tarball)
        print(f"Cached tarball at {cached_tarball}")
        return cached_tarball

    def _prepare_workdir(self) -> Path:
        if self.args.workspace is not None:
            self.args.workspace.mkdir(parents=True, exist_ok=True)
            print(f"Using workspace: {self.args.workspace}")
            return self.args.workspace

        workdir = Path(tempfile.mkdtemp(prefix="camoufox-patch-verify-"))
        print(f"Created temp workspace: {workdir}")
        return workdir

    def register_workspace_file(self, relative_path: str) -> None:
        normalized = normalize_posix(relative_path)
        if normalized in self.workspace_paths:
            return
        self.workspace_paths.add(normalized)
        self.workspace_paths_by_basename[PurePosixPath(normalized).name].append(normalized)

    def workspace_file(self, relative_path: str) -> Path:
        return self.workdir / PurePosixPath(relative_path)

    def ensure_parent(self, relative_path: str) -> None:
        self.workspace_file(relative_path).parent.mkdir(parents=True, exist_ok=True)

    def extract_paths(self, relative_paths: list[str]) -> None:
        needed = sorted(
            {
                normalize_posix(path)
                for path in relative_paths
                if path not in self.extracted_paths and self.tar_index.has(path)
            }
        )
        if not needed:
            return
        self.tar_index.extract(needed, self.workdir)
        for path in needed:
            self.extracted_paths.add(path)
            self.register_workspace_file(path)

    def copy_file(self, source: Path, relative_destination: str) -> None:
        destination = self.workspace_file(relative_destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        self.register_workspace_file(relative_destination)

    def copy_tree(self, source_root: Path) -> None:
        shutil.copytree(source_root, self.workdir, dirs_exist_ok=True)
        for path in source_root.rglob("*"):
            if path.is_file():
                relative_path = path.relative_to(source_root).as_posix()
                self.register_workspace_file(relative_path)

    def create_stub_headers(self) -> None:
        for relative_path, contents in STUB_HEADERS.items():
            destination = self.stub_dir / PurePosixPath(relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")

    def is_locally_seeded(self, relative_path: str) -> bool:
        normalized = normalize_posix(relative_path)
        if normalized in HELPER_SEEDED_PATHS:
            return True
        return (ADDITIONS_DIR / PurePosixPath(normalized)).is_file()

    def prepare_source_tree(self) -> None:
        upstream_paths = sorted(
            {
                entry.extract_path
                for entries in self.patch_entries_by_path.values()
                for entry in entries
                if entry.extract_path is not None and not self.is_locally_seeded(entry.extract_path)
            }
        )
        missing_paths = [path for path in upstream_paths if not self.tar_index.has(path)]
        if missing_paths:
            raise FileNotFoundError(
                "Firefox tarball is missing patch targets:\n" + "\n".join(missing_paths[:20])
            )

        print(f"Extracting {len(upstream_paths)} upstream files")
        self.extract_paths(upstream_paths)

        print("Copying additions and helper files")
        self.copy_tree(ADDITIONS_DIR)
        self.copy_file(
            ASSETS_DIR / "search-config.json",
            "services/settings/dumps/main/search-config.json",
        )
        self.copy_file(PATCHES_DIR / "librewolf" / "pack_vs.py", "build/vs/pack_vs.py")
        self.copy_file(SETTINGS_DIR / "camoufox.cfg", "lw/camoufox.cfg")
        self.copy_file(
            SETTINGS_DIR / "distribution" / "policies.json",
            "lw/policies.json",
        )
        self.copy_file(
            SETTINGS_DIR / "defaults" / "pref" / "local-settings.js",
            "lw/local-settings.js",
        )
        self.copy_file(SETTINGS_DIR / "chrome.css", "lw/chrome.css")
        self.copy_file(SCRIPTS_DIR / "mozfetch.sh", "lw/mozfetch.sh")
        self.ensure_parent("lw/moz.build")
        self.workspace_file("lw/moz.build").touch()
        self.register_workspace_file("lw/moz.build")

        for relative_path in (
            "browser/config/version.txt",
            "browser/config/version_display.txt",
        ):
            self.ensure_parent(relative_path)
            self.workspace_file(relative_path).write_text(
                f"{self.metadata.version}-{self.metadata.release}\n",
                encoding="utf-8",
            )
            self.register_workspace_file(relative_path)

        new_paths = [
            entry.target_path
            for entries in self.patch_entries_by_path.values()
            for entry in entries
            if entry.target_path is not None
        ]
        for relative_path in new_paths:
            self.workspace_file(relative_path).parent.mkdir(parents=True, exist_ok=True)

        self.create_stub_headers()

    def apply_patches(self) -> None:
        print(f"Applying {len(self.patch_paths)} patches")
        print(f"Using patch binary: {self.patch_bin}")
        failures: list[tuple[str, str]] = []
        for patch_path in self.patch_paths:
            result = subprocess.run(
                [
                    self.patch_bin,
                    "-p1",
                    "--batch",
                    "--forward",
                    "-l",
                    "--binary",
                    "-i",
                    str(patch_path),
                ],
                capture_output=True,
                check=False,
                cwd=self.workdir,
                text=True,
            )
            if result.returncode != 0:
                combined = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
                failures.append((repo_relative(patch_path), combined))

        if failures:
            for patch_name, output in failures:
                print(f"\nPatch failed: {patch_name}")
                if output:
                    print(output)
            raise RuntimeError(f"{len(failures)} patch(es) failed to apply cleanly")

        for entries in self.patch_entries_by_path.values():
            for entry in entries:
                if entry.target_path is None:
                    continue
                path = self.workspace_file(entry.target_path)
                if path.is_file():
                    self.register_workspace_file(entry.target_path)

    def collect_syntax_targets(self) -> list[str]:
        targets: dict[str, None] = {}

        for path in ADDITIONS_DIR.rglob("*"):
            if not path.is_file():
                continue
            relative_path = path.relative_to(ADDITIONS_DIR).as_posix()
            suffix = path.suffix.lower()
            if suffix in SOURCE_EXTENSIONS | HEADER_EXTENSIONS | SKIPPED_SOURCE_EXTENSIONS:
                targets[relative_path] = None

        for entries in self.patch_entries_by_path.values():
            for entry in entries:
                target_path = entry.target_path
                if target_path is None or entry.is_deleted:
                    continue
                suffix = PurePosixPath(target_path).suffix.lower()
                if suffix not in SOURCE_EXTENSIONS | HEADER_EXTENSIONS | SKIPPED_SOURCE_EXTENSIONS:
                    continue
                if self.workspace_file(target_path).is_file():
                    targets[normalize_posix(target_path)] = None

        return sorted(targets)

    def parse_includes(self, relative_path: str) -> list[tuple[bool, str]]:
        includes: list[tuple[bool, str]] = []
        file_path = self.workspace_file(relative_path)
        for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = INCLUDE_RE.match(line)
            if match is None:
                continue
            delimiter, include_path = match.groups()
            includes.append((delimiter == '"', include_path))
        return includes

    def candidate_exists(self, relative_path: str) -> bool:
        return relative_path in self.workspace_paths or self.tar_index.has(relative_path)

    def ensure_candidate(self, relative_path: str) -> bool:
        normalized = normalize_posix(relative_path)
        if normalized in self.workspace_paths:
            return True
        if not self.tar_index.has(normalized):
            return False
        self.extract_paths([normalized])
        return True

    def resolve_include(self, current_file: str, include_path: str, quoted: bool) -> str | None:
        current_parent = PurePosixPath(current_file).parent

        if quoted:
            relative_candidate = normalize_posix(current_parent.joinpath(include_path).as_posix())
            if self.ensure_candidate(relative_candidate):
                return relative_candidate

            exact_candidate = normalize_posix(include_path)
            if self.ensure_candidate(exact_candidate):
                return exact_candidate

            basename = PurePosixPath(include_path).name
            candidates = list(self.workspace_paths_by_basename.get(basename, []))
            candidates.extend(self.tar_index.basename_candidates(basename))
            chosen = choose_best_candidate(sorted(set(candidates)), current_file)
            if chosen is not None and self.ensure_candidate(chosen):
                return chosen
            return None

        if "/" not in include_path:
            return None

        exact_candidate = normalize_posix(include_path)
        if self.ensure_candidate(exact_candidate):
            return exact_candidate
        return None

    def prepare_target(self, target: str) -> PreparedTarget | PreparationFailure:
        suffix = PurePosixPath(target).suffix.lower()
        if suffix in SKIPPED_SOURCE_EXTENSIONS:
            return PreparationFailure(
                target=target,
                reason="Objective-C or Objective-C++ sources are not portable in the Ubuntu fast lane",
                skip=True,
            )

        if not self.workspace_file(target).exists():
            return PreparationFailure(
                target=target,
                reason="syntax target is missing from the prepared workspace",
                skip=False,
            )

        include_dirs: dict[str, None] = {"": None}
        pending = [target]
        visited: set[str] = set()

        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)

            current_suffix = PurePosixPath(current).suffix.lower()
            if current_suffix not in SCANNABLE_EXTENSIONS:
                continue

            include_dirs[str(PurePosixPath(current).parent)] = None
            for quoted, include_path in self.parse_includes(current):
                resolved = self.resolve_include(current, include_path, quoted)
                if resolved is None:
                    if quoted:
                        reason = f"missing quoted include: {include_path}"
                        return PreparationFailure(target=target, reason=reason, skip=is_generated_header(include_path))
                    continue
                include_dirs[str(PurePosixPath(resolved).parent)] = None
                if resolved not in visited:
                    pending.append(resolved)

        command = [
            shutil.which("clang++") or "clang++",
            "-fsyntax-only",
            "-std=gnu++20",
            "-ferror-limit=0",
            "-Wno-unknown-warning-option",
            "-Winvalid-offsetof",
            "-fno-exceptions",
            "-fno-rtti",
            "-fno-sized-deallocation",
            "-fno-aligned-new",
            "-pthread",
            "-include",
            str(self.stub_dir / "mozilla-config.h"),
        ]
        for define in COMMON_DEFINES:
            command.append(f"-D{define}")

        ordered_dirs = [self.workdir, self.stub_dir]
        for relative_dir in include_dirs:
            ordered_dirs.append(self.workdir / PurePosixPath(relative_dir))

        unique_dirs: dict[Path, None] = {}
        for directory in ordered_dirs:
            if directory.exists():
                unique_dirs[directory] = None
        for directory in unique_dirs:
            command.extend(["-I", str(directory)])

        compile_path = self.workspace_file(target)
        if suffix in HEADER_EXTENSIONS:
            wrapper_name = target.replace("/", "__").replace(".", "_") + ".cpp"
            compile_path = self.wrapper_dir / wrapper_name
            compile_path.parent.mkdir(parents=True, exist_ok=True)
            compile_path.write_text(f'#include "{target}"\n', encoding="utf-8")

        command.append(str(compile_path))
        return PreparedTarget(display_path=target, compile_path=compile_path, command=command)

    def run_compiler(self, prepared: PreparedTarget) -> SyntaxResult:
        result = subprocess.run(
            prepared.command,
            capture_output=True,
            check=False,
            cwd=self.workdir,
            text=True,
        )
        if result.returncode == 0:
            return SyntaxResult(display_path=prepared.display_path, status="passed")

        combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        header_match = MISSING_HEADER_RE.search(combined_output)
        if header_match is not None:
            header_name = header_match.group(1)
            if is_generated_header(header_name):
                return SyntaxResult(
                    display_path=prepared.display_path,
                    status="skipped",
                    reason=f"depends on generated Mozilla header {header_name}",
                )
            if is_nonportable_header(header_name):
                return SyntaxResult(
                    display_path=prepared.display_path,
                    status="skipped",
                    reason=f"depends on non-portable system header {header_name}",
                )

        return SyntaxResult(
            display_path=prepared.display_path,
            status="failed",
            output=combined_output,
        )

    def run_syntax_checks(self) -> list[SyntaxResult]:
        targets = self.collect_syntax_targets()
        print(f"Preparing syntax checks for {len(targets)} files")
        immediate_results: list[SyntaxResult] = []
        prepared_targets: list[PreparedTarget] = []

        for target in targets:
            prepared = self.prepare_target(target)
            if isinstance(prepared, PreparationFailure):
                status = "skipped" if prepared.skip else "failed"
                immediate_results.append(
                    SyntaxResult(
                        display_path=prepared.target,
                        status=status,
                        reason=prepared.reason,
                    )
                )
                continue
            prepared_targets.append(prepared)

        max_workers = max(1, min(self.args.jobs, len(prepared_targets) or 1))
        compiled_results: list[SyntaxResult] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for result in executor.map(self.run_compiler, prepared_targets):
                compiled_results.append(result)

        return immediate_results + compiled_results

    def cleanup(self) -> None:
        if self.args.keep_workdir or self.args.workspace is not None:
            print(f"Workspace preserved at {self.workdir}")
            return
        shutil.rmtree(self.workdir, ignore_errors=True)

    def run(self) -> int:
        try:
            self.prepare_source_tree()
            self.apply_patches()
            print("Patch application passed")

            if self.args.skip_syntax:
                print("Skipping syntax checks")
                return 0

            syntax_results = self.run_syntax_checks()
            passed = [result for result in syntax_results if result.status == "passed"]
            skipped = [result for result in syntax_results if result.status == "skipped"]
            failed = [result for result in syntax_results if result.status == "failed"]

            print(
                f"Syntax summary: {len(passed)} passed, {len(skipped)} skipped, {len(failed)} failed"
            )
            if skipped:
                print("\nSkipped syntax targets:")
                for result in skipped:
                    print(f"  - {result.display_path}: {result.reason}")
            if failed:
                print("\nFailed syntax targets:")
                for result in failed:
                    print(f"  - {result.display_path}")
                    if result.reason:
                        print(f"    {result.reason}")
                    if result.output:
                        print(textwrap.indent(result.output, "    "))
                return 1

            return 0
        finally:
            self.cleanup()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the active Firefox patch stack applies to the matching "
            "source tarball and run a lightweight Clang syntax pass over the "
            "prepared source surface."
        )
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "camoufox" / "firefox-source",
        help="Directory for cached Firefox source tarballs",
    )
    parser.add_argument(
        "--tarball",
        type=Path,
        help="Use an existing Firefox source tarball instead of downloading one",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Reuse or create a specific workspace directory instead of a temp dir",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep the temporary workspace after the run for debugging",
    )
    parser.add_argument(
        "--skip-syntax",
        action="store_true",
        help="Only verify extraction and patch application",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, min(os.cpu_count() or 1, 8)),
        help="Maximum parallel syntax check jobs",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    metadata = parse_upstream_metadata()
    print(f"Verifying Firefox {metadata.version} with Camoufox release {metadata.release}")
    verifier = PatchVerifier(metadata=metadata, args=args)
    return verifier.run()


if __name__ == "__main__":
    raise SystemExit(main())
