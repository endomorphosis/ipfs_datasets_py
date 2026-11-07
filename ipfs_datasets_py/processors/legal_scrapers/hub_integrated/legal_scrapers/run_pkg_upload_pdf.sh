#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
set -e
PY=/workspace/hf-venv/bin/python
WP=${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/world_package.py
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}
df -h / | awk 'NR==2{print "disk_free",$4}'
for spec in \
  "sv|PDF deepen via Asamblea/Diario; IntegratedPDFProcessor pdfplumber+OCR; honest Art. splits. Quarantined 1847 garbage scans. Not legal advice." \
  "tn|PDF reprocess (ipfs_datasets_py); PNG junk quarantined; honest fasl/Article splits where present. Not legal advice." \
  "et|Negarit/MoJ PDFs; pdfplumber reextract; honest Article/አንቀጽ line-start splits. Not legal advice." \
  "jm|MOJ Jamaica official PDFs only; sample/HR junk quarantined; honest Section/PART splits. Not legal advice." \
  "fj|laws.gov.fj PDFs; honest N.— / Section splits via IntegratedPDFProcessor pipeline. Not legal advice."
do
  cc="${spec%%|*}"
  notes="${spec#*|}"
  echo "=== package-upload $cc ==="
  $PY "$WP" package-upload "$cc" "$notes"
done
echo ALL_UPLOADS_DONE
