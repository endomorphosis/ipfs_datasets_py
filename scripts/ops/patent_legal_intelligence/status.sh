#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATLAW_REPO_ROOT="$(cd "${PATLAW_REPO_ROOT:-$SCRIPT_DIR/../../..}" && pwd)"
exec python3 "$SCRIPT_DIR/status.py" --repo-root "$PATLAW_REPO_ROOT" "$@"
