#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts/ui-smoke
uv run --no-sync typeflo --config artifacts/ui-config.toml --smoke-ui artifacts/ui-smoke
