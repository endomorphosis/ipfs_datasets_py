#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec python3 -P "$repo_root/scripts/ops/open_us_law_reindex/status.py" --repo-root "$repo_root" --json "$@"
