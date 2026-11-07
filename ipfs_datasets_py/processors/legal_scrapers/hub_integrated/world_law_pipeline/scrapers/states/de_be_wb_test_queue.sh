#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25: DE-BE (Wayback) --review --limit 20 test, gated on states-lane RAM (resumes from _work/de_be_wb/cdx_parts).
# 2026-10-28 06:20 PDT: r1 (5 rows) superseded: jlink permalink trailer + "| zur Einzelansicht" chrome in text, heading-only rows; fixed in de_be_wb.py (bak_20261028_boiler).
# 2026-10-28 09:15 PDT: r2 (6 rows) superseded: "zum Seitenanfang" nav line, "Nichtamtliches Inhaltsverzeichnis" TOC block, and
#   duplicate whole-norm Gesamtausgabe rows (doc.part=X of P1 and P6 = same norm); fixed in de_be_wb.py (bak_20261028_gesamt):
#   strip both, Gesamtausgabe -> one row per norm root (doc_id be_juris:<root>, map in _work/de_be_wb/gesamt_seen.tsv).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
export ARCHIVE_LANE=states STATES_MAX_DEFERS=10000
L=${WORLD_LAW_ROOT}/staging/states/_logs
pgrep -f "arch_states.py de_be_wb" >/dev/null && { echo "de_be_wb already running"; exit 0; }
echo "=== $(date) r3 retest (TOC + zum Seitenanfang strip; Gesamtausgabe one row per norm)" >> $L/test_de_be_wb.out
ramgate_run 110 $L/test_de_be_wb.out ${WORLD_LAW_ROOT}/pipeline/venv/bin/python -u arch_states.py de_be_wb --review --limit 20
echo "$(date) DEBE_TEST_END rc=$?"
