#!/usr/bin/env bash
# One-shot operator loop: discover (optional) → refresh public → print next private steps.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export PYTHONPATH="${PYTHONPATH:-$ROOT}"
ENV_FILE="${HOME}/.config/ipfs_datasets_py/uspto.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi
CLI=(python3 "$ROOT/scripts/ops/uspto/portfolio_cli.py")
INVENTOR="${PATLAW_INVENTOR_NAME:-Benjamin Barber}"

if [[ "${1:-}" == "discover" || "${1:-}" == "all" ]]; then
  "${CLI[@]}" discover --inventor-name "$INVENTOR"
fi
if [[ "${1:-refresh}" == "refresh" || "${1:-}" == "all" || -z "${1:-}" ]]; then
  if [[ "${PATLAW_WITH_DOCUMENTS:-0}" == "1" ]]; then
    "${CLI[@]}" refresh --with-documents
  else
    "${CLI[@]}" refresh
  fi
fi
if [[ "${1:-}" == "inbox" || "${1:-}" == "all" ]]; then
  "${CLI[@]}" inbox-import --authorizing-user "operator:${USER:-local}"
fi
"${CLI[@]}" dashboard
echo
echo "Private next steps:"
echo "  Drop Patent Center downloads into private_inbox/<APP>/ (optional READY marker)"
echo "  ${CLI[*]} watch-inbox --duration-seconds 600 --authorizing-user operator:\$USER"
echo "  ${CLI[*]} attended-export --application-number <APP> --authorizing-user operator:\$USER"
echo "Docs: docs/operations/USPTO_PORTFOLIO_AUTOMATION.md"
