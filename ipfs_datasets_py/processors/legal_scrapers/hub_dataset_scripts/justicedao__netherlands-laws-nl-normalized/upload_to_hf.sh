#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <namespace/dataset-name>"
  exit 1
fi

REPO_ID="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat <<EOF
cd "$SCRIPT_DIR"
git init
git lfs install
git remote add origin "https://huggingface.co/datasets/$REPO_ID"
git add .
git commit -m "Add normalized Netherlands laws dataset"
git branch -M main
git push origin main
EOF
