#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${TYPEFLO_SIGN_IDENTITY:-}" ]; then
  TYPEFLO_SIGN_IDENTITY="$(security find-identity -v -p codesigning | sed -n 's/.*"\(Apple Development[^"]*\)".*/\1/p' | head -1 || true)"
fi
if [ -n "$TYPEFLO_SIGN_IDENTITY" ]; then
  printf 'Signing with: %s\n' "$TYPEFLO_SIGN_IDENTITY"
else
  printf 'No Apple Development certificate found; using an ad-hoc signature. macOS will forget Accessibility permission on every rebuild.\n'
fi

uv sync --group build --quiet
uv run --no-sync python scripts/make-icon.py
iconutil -c icns build/Typeflo.iconset -o src/dictate/resources/Typeflo.icns
uv run --no-sync pyinstaller --noconfirm Typeflo.spec
sign_app() {
  if [ -n "$TYPEFLO_SIGN_IDENTITY" ]; then
    codesign --force --deep --timestamp=none --options runtime \
      --entitlements scripts/entitlements.plist -s "$TYPEFLO_SIGN_IDENTITY" dist/Typeflo.app
  fi
  codesign --verify --deep --strict dist/Typeflo.app
}
sign_app

if [ "${1:-install}" = "install" ]; then
  osascript -e 'tell application "Typeflo" to quit' >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    pgrep -f "Typeflo.app/Contents/MacOS/Typeflo" >/dev/null || break
    sleep 0.5
  done
  pkill -f "Typeflo.app/Contents/MacOS/Typeflo" 2>/dev/null || true
  rm -rf /Applications/Typeflo.app
  cp -R dist/Typeflo.app /Applications/Typeflo.app
  open /Applications/Typeflo.app
  printf 'Installed and launched /Applications/Typeflo.app\n'
else
  printf 'Built %s/dist/Typeflo.app\n' "$PWD"
fi
