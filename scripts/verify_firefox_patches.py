#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "click>=8.1",
#   "rich>=13.9",
# ]
# ///

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import click
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

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
console = Console()


@dataclass(frozen=True)
class BuildMetadata:
    version: str
    release: str


@dataclass(frozen=True)
class VerifierOptions:
    cache_dir: Path
    tarball: Path | None
    workspace: Path | None
    keep_workdir: bool
    skip_syntax: bool
    jobs: int


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
    def __init__(self, metadata: BuildMetadata, options: VerifierOptions):
        self.metadata = metadata
        self.options = options
        self.patch_bin = shutil.which("gpatch") or shutil.which("patch") or "patch"
        self.patch_paths = active_patch_paths()
        self.patch_entries_by_path = collect_patch_entries(self.patch_paths)
        self.cache_dir = options.cache_dir
        self.tarball_path = self._resolve_tarball_path()
        self.tar_index = TarIndex(self.tarball_path)
        self.workdir = self._prepare_workdir()
        self.stub_dir = self.workdir / "__generated_stubs__"
        self.wrapper_dir = self.workdir / "__verify_wrappers__"
        self.workspace_paths: set[str] = set()
        self.workspace_paths_by_basename: dict[str, list[str]] = defaultdict(list)
        self.extracted_paths: set[str] = set()
        self.include_cache: dict[str, list[tuple[bool, str]]] = {}
        self.include_resolution_cache: dict[tuple[str, str, bool], str | None] = {}

    @staticmethod
    def progress() -> Progress:
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        )

    def _resolve_tarball_path(self) -> Path:
        if self.options.tarball is not None:
            console.print(f"[cyan]Using explicit tarball:[/cyan] {self.options.tarball}")
            return self.options.tarball

        local_tarball = REPO_ROOT / f"firefox-{self.metadata.version}.source.tar.xz"
        if local_tarball.exists():
            console.print(f"[cyan]Using local tarball:[/cyan] {local_tarball}")
            return local_tarball

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached_tarball = self.cache_dir / f"firefox-{self.metadata.version}.source.tar.xz"
        if cached_tarball.exists():
            console.print(f"[cyan]Using cached tarball:[/cyan] {cached_tarball}")
            return cached_tarball

        url = FIREFOX_TARBALL_URL.format(version=self.metadata.version)
        temp_tarball = cached_tarball.with_suffix(".tmp")
        console.print(f"[cyan]Downloading[/cyan] {url}")
        with urllib.request.urlopen(url) as response, temp_tarball.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        temp_tarball.replace(cached_tarball)
        console.print(f"[green]Cached tarball at[/green] {cached_tarball}")
        return cached_tarball

    def _prepare_workdir(self) -> Path:
        if self.options.workspace is not None:
            self.options.workspace.mkdir(parents=True, exist_ok=True)
            console.print(f"[cyan]Using workspace:[/cyan] {self.options.workspace}")
            return self.options.workspace

        workdir = Path(tempfile.mkdtemp(prefix="camoufox-patch-verify-"))
        console.print(f"[cyan]Created temp workspace:[/cyan] {workdir}")
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

        console.print(f"[bold cyan]Extracting[/bold cyan] {len(upstream_paths)} upstream files")
        self.extract_paths(upstream_paths)

        console.print("[bold cyan]Copying additions and helper files[/bold cyan]")
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
        console.print(f"[bold cyan]Applying[/bold cyan] {len(self.patch_paths)} patches")
        console.print(f"[cyan]Using patch binary:[/cyan] {self.patch_bin}")
        failures: list[tuple[str, str]] = []
        with self.progress() as progress:
            task_id = progress.add_task("Applying patch set", total=len(self.patch_paths))
            for patch_path in self.patch_paths:
                patch_name = repo_relative(patch_path)
                progress.update(task_id, description=f"Applying {patch_name}")
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
                    failures.append((patch_name, combined))
                progress.advance(task_id)

        if failures:
            for patch_name, output in failures:
                console.rule(f"[red]Patch failed[/red]: {patch_name}")
                if output:
                    console.print(output, markup=False)
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
        cached = self.include_cache.get(relative_path)
        if cached is not None:
            return cached

        includes: list[tuple[bool, str]] = []
        file_path = self.workspace_file(relative_path)
        for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = INCLUDE_RE.match(line)
            if match is None:
                continue
            delimiter, include_path = match.groups()
            includes.append((delimiter == '"', include_path))
        self.include_cache[relative_path] = includes
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
        cache_key = (current_file, include_path, quoted)
        if cache_key in self.include_resolution_cache:
            return self.include_resolution_cache[cache_key]

        current_parent = PurePosixPath(current_file).parent

        if quoted:
            relative_candidate = normalize_posix(current_parent.joinpath(include_path).as_posix())
            if self.ensure_candidate(relative_candidate):
                self.include_resolution_cache[cache_key] = relative_candidate
                return relative_candidate

            exact_candidate = normalize_posix(include_path)
            if self.ensure_candidate(exact_candidate):
                self.include_resolution_cache[cache_key] = exact_candidate
                return exact_candidate

            basename = PurePosixPath(include_path).name
            candidates = list(self.workspace_paths_by_basename.get(basename, []))
            candidates.extend(self.tar_index.basename_candidates(basename))
            chosen = choose_best_candidate(sorted(set(candidates)), current_file)
            if chosen is not None and self.ensure_candidate(chosen):
                self.include_resolution_cache[cache_key] = chosen
                return chosen
            self.include_resolution_cache[cache_key] = None
            return None

        if "/" not in include_path:
            self.include_resolution_cache[cache_key] = None
            return None

        exact_candidate = normalize_posix(include_path)
        if self.ensure_candidate(exact_candidate):
            self.include_resolution_cache[cache_key] = exact_candidate
            return exact_candidate
        self.include_resolution_cache[cache_key] = None
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
        console.print(f"[bold cyan]Preparing syntax checks[/bold cyan] for {len(targets)} files")
        immediate_results: list[SyntaxResult] = []
        prepared_targets: list[PreparedTarget] = []

        with self.progress() as progress:
            task_id = progress.add_task("Preparing syntax targets", total=len(targets))
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
                    progress.advance(task_id)
                    continue
                prepared_targets.append(prepared)
                progress.advance(task_id)

        max_workers = max(1, min(self.options.jobs, len(prepared_targets) or 1))
        console.print(
            f"[bold cyan]Running syntax checks[/bold cyan] on {len(prepared_targets)} prepared targets "
            f"with {max_workers} parallel jobs"
        )
        compiled_results: list[SyntaxResult] = []
        with self.progress() as progress:
            task_id = progress.add_task("Compiling syntax targets", total=len(prepared_targets))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(self.run_compiler, prepared) for prepared in prepared_targets]
                for future in as_completed(futures):
                    compiled_results.append(future.result())
                    progress.advance(task_id)

        return immediate_results + compiled_results

    def cleanup(self) -> None:
        if self.options.keep_workdir or self.options.workspace is not None:
            console.print(f"[yellow]Workspace preserved at[/yellow] {self.workdir}")
            return
        shutil.rmtree(self.workdir, ignore_errors=True)

    def run(self) -> int:
        try:
            self.prepare_source_tree()
            self.apply_patches()
            console.print("[green]Patch application passed[/green]")

            if self.options.skip_syntax:
                console.print("[yellow]Skipping syntax checks[/yellow]")
                return 0

            syntax_results = self.run_syntax_checks()
            passed = [result for result in syntax_results if result.status == "passed"]
            skipped = [result for result in syntax_results if result.status == "skipped"]
            failed = [result for result in syntax_results if result.status == "failed"]

            summary = Table(title="Syntax Summary")
            summary.add_column("Status", style="bold")
            summary.add_column("Count", justify="right")
            summary.add_row("[green]Passed[/green]", str(len(passed)))
            summary.add_row("[yellow]Skipped[/yellow]", str(len(skipped)))
            summary.add_row("[red]Failed[/red]", str(len(failed)))
            console.print(summary)
            if skipped:
                console.rule("[yellow]Skipped syntax targets[/yellow]")
                for result in skipped:
                    console.print(f"- {result.display_path}: {result.reason}")
            if failed:
                console.rule("[red]Failed syntax targets[/red]")
                for result in failed:
                    console.print(f"- {result.display_path}")
                    if result.reason:
                        console.print(f"  {result.reason}")
                    if result.output:
                        console.print(textwrap.indent(result.output, "  "), markup=False)
                return 1

            console.print("[green]Syntax checks passed[/green]")
            return 0
        finally:
            self.cleanup()


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--cache-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path.home() / ".cache" / "camoufox" / "firefox-source",
    show_default=True,
    help="Directory for cached Firefox source tarballs.",
)
@click.option(
    "--tarball",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Use an existing Firefox source tarball instead of downloading one.",
)
@click.option(
    "--workspace",
    type=click.Path(path_type=Path, file_okay=False),
    help="Reuse or create a specific workspace directory instead of a temp dir.",
)
@click.option(
    "--keep-workdir",
    is_flag=True,
    help="Keep the temporary workspace after the run for debugging.",
)
@click.option(
    "--skip-syntax",
    is_flag=True,
    help="Only verify extraction and patch application.",
)
@click.option(
    "--jobs",
    type=click.IntRange(min=1),
    default=max(1, min(os.cpu_count() or 1, 8)),
    show_default=True,
    help="Maximum parallel syntax check jobs.",
)
def main(
    cache_dir: Path,
    tarball: Path | None,
    workspace: Path | None,
    keep_workdir: bool,
    skip_syntax: bool,
    jobs: int,
) -> None:
    metadata = parse_upstream_metadata()
    console.rule("[bold blue]Firefox Patch Verification[/bold blue]")
    console.print(
        f"Verifying Firefox [bold]{metadata.version}[/bold] with "
        f"Camoufox release [bold]{metadata.release}[/bold]"
    )
    options = VerifierOptions(
        cache_dir=cache_dir,
        tarball=tarball,
        workspace=workspace,
        keep_workdir=keep_workdir,
        skip_syntax=skip_syntax,
        jobs=jobs,
    )
    verifier = PatchVerifier(metadata=metadata, options=options)
    raise SystemExit(verifier.run())


if __name__ == "__main__":
    main()
