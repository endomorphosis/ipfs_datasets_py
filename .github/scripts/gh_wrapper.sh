#!/bin/bash
#
# GitHub CLI Wrapper with API Call Counting
#
# This script wraps the `gh` CLI command to automatically count API calls.
# Use this in GitHub Actions workflows instead of calling `gh` directly.
#
# Usage:
#   Instead of:  gh pr list
#   Use:         .github/scripts/gh_wrapper.sh pr list
#
# The wrapper will:
# - Count the API call
# - Run the actual gh command
# - Save metrics to the workflow temp directory
# - Gracefully handle counter failures
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COUNTER_SCRIPT="${SCRIPT_DIR}/github_api_counter.py"

# Check if Python counter is available
if [ ! -f "$COUNTER_SCRIPT" ]; then
    # Fallback: just run gh directly without counting
    exec gh "$@"
fi

# Try to run gh command through the counter, but fallback to direct gh if counter fails
if ! python3 "$COUNTER_SCRIPT" --command gh "$@"; then
    # Counter failed, run gh directly to ensure the command still executes
    exec gh "$@"
fi
