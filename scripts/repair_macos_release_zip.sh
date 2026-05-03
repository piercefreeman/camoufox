#!/usr/bin/env bash

set -euo pipefail

# This script repairs macOS release zips before they are uploaded.
#
# Root cause:
# - The build pipeline publishes dist/*.zip directly as both workflow artifacts
#   and GitHub release assets.
# - Older upstream Camoufox macOS zips stored helper binaries like
#   Contents/MacOS/camoufox, pingsender, and plugin-container with executable
#   mode bits intact.
# - The regressed 146.0.1 macOS zips stored those same Mach-O binaries as
#   non-executable files, which broke helper subprocess launch after download.
#
# Why fix the zip here:
# - End users can download the release zip directly, so the archive itself must
#   be correct.
# - Python's ZipFile.extractall() also drops Unix exec bits even for a good zip,
#   but that is a separate extraction problem. CI now uses native extractors.
# - This script fixes the source artifact so both release downloads and workflow
#   artifacts carry the right permissions from the start.
#
# Implementation notes:
# - We unpack the zip, find Mach-O files inside Camoufox.app, and chmod them
#   executable.
# - We then rebuild the archive with plain zip. We intentionally avoid a ditto
#   re-pack here because it introduced __MACOSX / AppleDouble sidecar entries
#   during testing.

if [[ "$#" -eq 0 ]]; then
  echo "Usage: $0 <archive.zip> [archive.zip ...]" >&2
  exit 64
fi

for archive in "$@"; do
  if [[ ! -f "$archive" ]]; then
    echo "Archive not found: $archive" >&2
    exit 1
  fi

  temp_dir="$(mktemp -d)"
  archive_dir="$(cd "$(dirname "$archive")" && pwd)"
  archive_name="$(basename "$archive")"

  unzip -q "$archive" -d "$temp_dir"

  app_path="$(find "$temp_dir" -type d -name 'Camoufox.app' -print -quit)"
  if [[ -z "$app_path" ]]; then
    echo "Camoufox.app not found in $archive" >&2
    rm -rf "$temp_dir"
    exit 1
  fi

  # Only touch Mach-O payloads. Resource files inside the app bundle should
  # keep their normal non-executable permissions.
  while IFS= read -r -d '' file_path; do
    if file -b "$file_path" | grep -q 'Mach-O'; then
      chmod 755 "$file_path"
    fi
  done < <(find "$app_path" -type f -print0)

  rm -f "$archive"
  (
    cd "$temp_dir"
    # Preserve symlinks and Unix mode bits in the rebuilt archive.
    zip -qry -y "$archive_dir/$archive_name" .
  )

  zipinfo -l "$archive_dir/$archive_name" | grep 'Camoufox.app/Contents/MacOS/' >/dev/null
  rm -rf "$temp_dir"
done
