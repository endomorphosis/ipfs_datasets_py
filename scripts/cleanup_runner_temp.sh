#!/usr/bin/env bash
# Cleanup script for GitHub Actions self-hosted runner _work/_temp
# Removes old docker-actions-toolkit-* directories to prevent accumulation.
# Usage:
#   ./cleanup_runner_temp.sh [--path PATH] [--hours N] [--max-delete N] [--dry-run]

set -euo pipefail

WORKDIR_DEFAULT="/home/barberb/actions-runner-ipfs_datasets_py/_work/_temp"
HOURS_DEFAULT=24
MAX_DELETE_DEFAULT=100
DRY_RUN=0

print_usage() {
  cat <<EOF
Usage: $0 [--path PATH] [--hours N] [--max-delete N] [--dry-run]

Options:
  --path PATH       Path to runner _temp directory (default: $WORKDIR_DEFAULT)
  --hours N         Only remove dirs older than N hours (default: $HOURS_DEFAULT)
  --max-delete N    Maximum number of directories to remove in one run (default: $MAX_DELETE_DEFAULT)
  --dry-run         Show what would be deleted but don't delete
  --help            Show this help
EOF
}

PATH_DIR="$WORKDIR_DEFAULT"
HOURS="$HOURS_DEFAULT"
MAX_DELETE="$MAX_DELETE_DEFAULT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path)
      PATH_DIR="$2"; shift 2;;
    --hours)
      HOURS="$2"; shift 2;;
    --max-delete)
      MAX_DELETE="$2"; shift 2;;
    --dry-run)
      DRY_RUN=1; shift;;
    --help)
      print_usage; exit 0;;
    *)
      echo "Unknown arg: $1" >&2; print_usage; exit 2;;
  esac
done

if [ ! -d "$PATH_DIR" ]; then
  echo "Path does not exist: $PATH_DIR" >&2
  exit 1
fi

echo "[cleanup_runner_temp] Path: $PATH_DIR  Older than: ${HOURS}h  Max delete: $MAX_DELETE  Dry-run: $DRY_RUN"

# Convert hours to minutes for find -mmin
MINUTES=$((HOURS * 60))

# Find matching directories one level deep
mapfile -t CANDIDATES < <(find "$PATH_DIR" -maxdepth 1 -type d -name 'docker-actions-toolkit-*' -mmin +"$MINUTES" -printf '%T@ %p\n' | sort -n | awk '{print $2}')

COUNT=${#CANDIDATES[@]}
echo "Found $COUNT candidate(s) to remove."

if [ "$COUNT" -eq 0 ]; then
  exit 0
fi

TO_DELETE=${CANDIDATES[@]:0:$MAX_DELETE}

echo "Listing to-delete (up to $MAX_DELETE):"
for d in ${TO_DELETE}; do
  echo "  $d"
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry-run: no files will be deleted."
  exit 0
fi

echo "Removing directories..."
for d in ${TO_DELETE}; do
  if [ -d "$d" ]; then
    rm -rf -- "$d" && echo "Removed: $d" || echo "Failed to remove: $d" >&2
  fi
done

echo "Done."
