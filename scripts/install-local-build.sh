#!/usr/bin/env bash
# Install a custom Rotunda build into the local channel.
#
# Usage:
#   ./install-local-build.sh [artifact.zip] [version-build]
#
# If no artifact is given, uses the latest zip in dist/.
# If no version-build is given, extracts it from the zip filename.
#
# Installs to ~/.cache/rotunda/browsers/local/<version-build>/
# and sets active_version in config.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

CACHE_DIR="${HOME}/Library/Caches/rotunda"
# Fall back to XDG if not on macOS
if [[ ! -d "${HOME}/Library/Caches" ]]; then
    CACHE_DIR="${XDG_CACHE_HOME:-${HOME}/.cache}/rotunda"
fi

BROWSERS_DIR="${CACHE_DIR}/browsers"
CONFIG_FILE="${CACHE_DIR}/config.json"

# --- Resolve artifact zip ---

ARTIFACT="${1:-}"
if [[ -z "$ARTIFACT" ]]; then
    ARTIFACT="$(ls -t "$REPO_ROOT"/dist/rotunda-*-mac.arm64.zip 2>/dev/null | head -1)"
    if [[ -z "$ARTIFACT" ]]; then
        echo "No artifact found in dist/. Pass the zip path as an argument."
        exit 1
    fi
    echo "Using latest artifact: $ARTIFACT"
fi

if [[ ! -f "$ARTIFACT" ]]; then
    echo "Artifact not found: $ARTIFACT"
    exit 1
fi

# --- Resolve version-build string ---

VERSION_BUILD="${2:-}"
if [[ -z "$VERSION_BUILD" ]]; then
    # Extract from filename: rotunda-<version>-<build>-mac.arm64.zip
    BASENAME="$(basename "$ARTIFACT")"
    # Strip prefix "rotunda-" and suffix "-mac.arm64.zip" (or similar)
    VERSION_BUILD="${BASENAME#rotunda-}"
    VERSION_BUILD="${VERSION_BUILD%-mac.*}"
    VERSION_BUILD="${VERSION_BUILD%-linux.*}"
    VERSION_BUILD="${VERSION_BUILD%-win.*}"
fi

echo "Version: $VERSION_BUILD"

# --- Extract version and build parts ---

# version-build format: "146.0.1-ruben.brotli-fix.1"
# version = everything up to the first hyphen-followed-by-non-digit
# For simplicity, split on first hyphen after the semver
VERSION="$(echo "$VERSION_BUILD" | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+')"
BUILD="${VERSION_BUILD#${VERSION}-}"

INSTALL_DIR="${BROWSERS_DIR}/local/${VERSION_BUILD}"

echo "Installing to: $INSTALL_DIR"

# --- Install ---

if [[ -d "$INSTALL_DIR" ]]; then
    echo "Removing existing installation..."
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"

# Unzip to temp dir first to handle nested structure
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

unzip -q "$ARTIFACT" -d "$TMP_DIR"

# Handle macOS structure: the zip may contain Rotunda.app directly or nested
if [[ -d "$TMP_DIR/Rotunda.app" ]]; then
    mv "$TMP_DIR/Rotunda.app" "$INSTALL_DIR/Rotunda.app"
elif [[ -d "$TMP_DIR/Rotunda/Rotunda.app" ]]; then
    mv "$TMP_DIR/Rotunda/Rotunda.app" "$INSTALL_DIR/Rotunda.app"
else
    # Linux/Windows: move everything
    mv "$TMP_DIR"/* "$INSTALL_DIR/"
fi

# Fix permissions (cp/unzip can strip executable bits)
chmod -R 755 "$INSTALL_DIR"

# Write version.json
cat > "$INSTALL_DIR/version.json" <<VEOF
{
  "version": "$VERSION",
  "build": "$BUILD",
  "prerelease": false,
  "local_build": true
}
VEOF

# --- Set active version ---

RELATIVE_PATH="browsers/local/${VERSION_BUILD}"

# Write config.json (preserve channel if set)
if [[ -f "$CONFIG_FILE" ]]; then
    # Use python for safe JSON manipulation
    python3 -c "
import json, sys
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
cfg['active_version'] = '$RELATIVE_PATH'
with open('$CONFIG_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
"
else
    mkdir -p "$(dirname "$CONFIG_FILE")"
    echo "{\"active_version\": \"$RELATIVE_PATH\"}" > "$CONFIG_FILE"
fi

echo ""
echo "Installed: $INSTALL_DIR"
echo "Active:    $RELATIVE_PATH"

# Verify
PLIST="$INSTALL_DIR/Rotunda.app/Contents/Info.plist"
if [[ -f "$PLIST" ]]; then
    BUNDLE_VERSION="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$PLIST" 2>/dev/null || echo "unknown")"
    echo "Bundle:    $BUNDLE_VERSION"
fi

echo ""
echo "Done. Run 'rotunda list' to see installed versions."
