#!/usr/bin/env bash

set -euo pipefail

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

  while IFS= read -r -d '' file_path; do
    if file -b "$file_path" | grep -q 'Mach-O'; then
      chmod 755 "$file_path"
    fi
  done < <(find "$app_path" -type f -print0)

  rm -f "$archive"
  (
    cd "$temp_dir"
    zip -qry -y "$archive_dir/$archive_name" .
  )

  zipinfo -l "$archive_dir/$archive_name" | grep 'Camoufox.app/Contents/MacOS/' >/dev/null
  rm -rf "$temp_dir"
done
