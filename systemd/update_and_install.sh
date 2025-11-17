#!/usr/bin/env bash
set -euo pipefail

# Update script for ipfs_datasets_py deployed at /var/lib/ipfsdatasets/app
# This script will:
#  - fetch the latest main from the remote
#  - reset the local copy to origin/main
#  - install (or upgrade) dependencies into the venv at /var/lib/ipfsdatasets/.venv
# Usage:
#   update_and_install.sh [--dry-run]

APP_DIR="/var/lib/ipfsdatasets/app"
VENV_PY="$HOME/.venv/bin/python"
VENV_BIN="/var/lib/ipfsdatasets/.venv/bin"
LOG_DIR="/var/log/ipfsdatasets"
LOG_FILE="$LOG_DIR/update_and_install.log"

DRY_RUN=0
if [ "${1-}" = "--dry-run" ] || [ "${DRY_RUN_ENV-}" = "1" ]; then
  DRY_RUN=1
fi

mkdir -p "$LOG_DIR"
chown ipfsdatasets:ipfsdatasets "$LOG_DIR" || true

echo "[update_and_install] Starting at $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "$LOG_FILE"

if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: app dir does not exist: $APP_DIR" | tee -a "$LOG_FILE"
  exit 1
fi

cd "$APP_DIR"
echo "[update_and_install] Fetching latest from origin/main" | tee -a "$LOG_FILE"

# Helper: run command as deploy user if script is executed as root, otherwise run directly.
run_as_deploy() {
  if [ "$(id -u)" -eq 0 ]; then
    # Use su to switch user when running as root (avoids requiring sudoers entry)
    # Ensure commands run from the deployed app directory so git operations work
    # Use a login shell for the user but cd into APP_DIR first to preserve working dir
    su -s /bin/bash - ipfsdatasets -c "cd \"$APP_DIR\" && $*"
  else
    bash -lc "$*"
  fi
}

# If the app directory doesn't contain a git repository, try to provision one
if [ ! -d "$APP_DIR/.git" ]; then
  echo "[update_and_install] .git not found in $APP_DIR; attempting to provision .git" | tee -a "$LOG_FILE"
  if [ -d "/home/barberb/ipfs_datasets_py/.git" ]; then
    echo "[update_and_install] Copying .git from /home/barberb/ipfs_datasets_py" | tee -a "$LOG_FILE"
    run_as_deploy "rsync -a /home/barberb/ipfs_datasets_py/.git $APP_DIR/.git" >> "$LOG_FILE" 2>&1 || true
  else
    echo "[update_and_install] No local .git available; initializing and adding GitHub origin" | tee -a "$LOG_FILE"
    run_as_deploy "git init && git remote add origin https://github.com/endomorphosis/ipfs_datasets_py.git" >> "$LOG_FILE" 2>&1 || true
  fi
fi

# If we still don't have a git repo, try to fetch from GitHub origin (shallow)
if [ ! -d "$APP_DIR/.git" ]; then
  echo "[update_and_install] Attempting to initialize and fetch from GitHub origin" | tee -a "$LOG_FILE"
  run_as_deploy "git init" >> "$LOG_FILE" 2>&1 || true
  run_as_deploy "git remote add origin https://github.com/endomorphosis/ipfs_datasets_py.git" >> "$LOG_FILE" 2>&1 || true
  run_as_deploy "git fetch --depth=1 origin main" >> "$LOG_FILE" 2>&1 || true
  run_as_deploy "git reset --hard origin/main" >> "$LOG_FILE" 2>&1 || true
fi

run_as_deploy "git fetch --all" >> "$LOG_FILE" 2>&1 || { echo "git fetch failed" | tee -a "$LOG_FILE"; }

echo "[update_and_install] Resetting to origin/main" | tee -a "$LOG_FILE"
run_as_deploy "git reset --hard origin/main" >> "$LOG_FILE" 2>&1 || { echo "git reset failed" | tee -a "$LOG_FILE"; exit 1; }
run_as_deploy "git clean -fd" >> "$LOG_FILE" 2>&1 || true

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[update_and_install] Dry-run mode: skipping pip install steps" | tee -a "$LOG_FILE"
  echo "[update_and_install] Completed (dry-run) at $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "$LOG_FILE"
  exit 0
fi

echo "[update_and_install] Updating venv tools (pip/setuptools/wheel)" | tee -a "$LOG_FILE"
run_as_deploy "$VENV_BIN/pip install --upgrade pip setuptools wheel" >> "$LOG_FILE" 2>&1 || { echo "pip upgrade failed" | tee -a "$LOG_FILE"; exit 1; }

echo "[update_and_install] Installing project and extras (all) into venv" | tee -a "$LOG_FILE"
run_as_deploy "$VENV_BIN/pip install -e \"$APP_DIR\"[all]" >> "$LOG_FILE" 2>&1 || { echo "pip install -e .[all] failed" | tee -a "$LOG_FILE"; exit 1; }

echo "[update_and_install] Completed at $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "$LOG_FILE"
exit 0
