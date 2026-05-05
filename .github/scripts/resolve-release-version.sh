#!/usr/bin/env bash

set -euo pipefail

source upstream.sh

if [[ "${GITHUB_EVENT_NAME:-}" == "pull_request" ]]; then
  release_version="0.0.1"
else
  raw_tag="${GITHUB_EVENT_RELEASE_TAG_NAME:-${GITHUB_REF_NAME:-}}"
  if [[ -z "$raw_tag" ]]; then
    echo "Unable to resolve release version: no tag name is available." >&2
    exit 1
  fi

  release_version="${raw_tag#refs/tags/}"
  release_version="${release_version#rotunda-}"
  release_version="${release_version#v}"
  release_version="${release_version#${version}-}"
fi

if [[ ! "$release_version" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]]; then
  echo "Invalid Rotunda release version derived from tag: $release_version" >&2
  exit 1
fi

echo "Rotunda release version: $release_version"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  echo "ROTUNDA_RELEASE=$release_version" >> "$GITHUB_ENV"
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "release=$release_version" >> "$GITHUB_OUTPUT"
fi
