#!/bin/sh
# Download a pinned python-build-standalone (arm64 macOS), check its sha256, strip it, and put it in desktop/python/
# (electron-builder copies that folder to Resources/python). Run it on the Mac before `npm run dist:mac`.
# --dry-run prints the URL, hash and target folder and downloads nothing.
set -eu

TAG=20261021
VERSION=3.12.15
FILE="cpython-${VERSION}+${TAG}-aarch64-apple-darwin-install_only_stripped.tar.gz"
SHA256=7b8d00b751db21cea87dc551a8f8165147c5fbc5251d5537d7e5497dde00a219  # from the release's SHA256SUMS
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${TAG}/$(printf '%s' "$FILE" | sed 's/+/%2B/')"
HERE=$(cd "$(dirname "$0")/.." && pwd)
DEST="$HERE/python"

if [ "${1:-}" = "--dry-run" ]; then
  echo "url:    $URL"
  echo "sha256: $SHA256"
  echo "target: $DEST"
  exit 0
fi

# shasum ships with macOS; sha256sum with Linux
sum() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fL --retry 3 -o "$TMP/py.tar.gz" "$URL"
GOT=$(sum "$TMP/py.tar.gz" | cut -d' ' -f1)
if [ "$GOT" != "$SHA256" ]; then
  echo "sha256 mismatch: expected $SHA256, got $GOT" >&2
  exit 1
fi
tar -xzf "$TMP/py.tar.gz" -C "$TMP"  # unpacks to python/
rm -rf "$DEST"
mv "$TMP/python" "$DEST"
# not needed to run `tokscope serve`: headers, docs, tests, caches, ensurepip, tkinter and idle
rm -rf "$DEST/include" "$DEST/share" "$DEST/lib/pkgconfig"
find "$DEST/lib" -type d \( -name test -o -name tests -o -name idle_test -o -name __pycache__ -o -name ensurepip -o -name idlelib -o -name turtledemo -o -name tkinter \) -prune -exec rm -rf {} +
echo "python $VERSION ready in $DEST"
