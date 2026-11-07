#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-01 ~00:40 PDT de_by_topup1: TOP-UP of the 13 Bavarian Landkreise whose live Kreisrecht/Amtsblatt crawl was capped at max_urls=400 (Oct 21-23):
#   Straubing-Bogen (824 found), Passau (687), Günzburg (608), Bayreuth (570), Kronach (563), Neu-Ulm (527), Landshut (526), Deggendorf (525), Kelheim (524),
#   Altötting (478), Freising (451), Oberallgäu (421), Wunsiedel (421) -> ~1,900 not-yet-staged PDFs expected. Same index URLs/QIDs as pass 1 (de_by_topup1_entries.json).
#   de_kreisrecht_topup_build.py = de_kreisrecht_build.py + drops already staged/processed de_by_kreisrecht source_urls BEFORE the cap; logs _logs/de_by_kreisrecht_<slug>_topup.log.
#   Robots RFC 9309 per host (index + PDFs), 2 s. Not included: Neuburg-Schrobenhausen (PDFs robots-disallowed), Würzburg (archive-only).
#   Test 2026-11-01 00:10 PDT (_logs/de_by_topup1_test.log): Straubing-Bogen 2/2 OK, Passau 2/2 OK. max_urls 2000 here (= no cap).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
. ${WORLD_LAW_ROOT}/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480)
g; echo "$(date) start live"
$PY -u de_kreisrecht_topup_build.py de_by_topup1_entries.json by_kreisrecht 2000
echo "$(date) done"
