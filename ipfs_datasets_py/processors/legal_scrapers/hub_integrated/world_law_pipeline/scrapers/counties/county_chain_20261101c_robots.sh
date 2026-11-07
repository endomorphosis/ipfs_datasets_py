#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-01 ~12:40 PST: ROBOTS RECRAWL chain (Benjamin 12:14 PST: robots.txt no longer honoured for legal texts; polite delays, honest UA,
#  never bypass WAF/Cloudflare/captcha, no proxies/VPNs). Starts after county_chain_20261101b.sh (PID 71551) exits (detached waiter).
#  Sources: configs whose URLs were skipped live / sent to archive-only because robots.txt Disallow (inventory _reports/robots_skipped_20261101.json).
#  Per site: robots_recrawl_prep.py drops already staged/processed URLs, spreadsheets, Code Publishing/eCode360 -> 3-URL test via us_pdf_list
#  (RESPECT_ROBOTS=0); full run only if the test staged >=1 OK row. robots_unreachable sites (WAF / TLS / 403) are NOT included: not bypassed.
#  Rows keep source_policy "robots_disallowed;robots_ignored_live_20261101" (schema.py HOLD policy still holds robots_disallowed rows from publishing).
D=${WORLD_LAW_ROOT}/pipeline/scrapers/counties; L=${WORLD_LAW_ROOT}/staging/counties/_logs
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
. $D/county_chain_guard.sh   # GUARD_MIN_MIB=20480
export RESPECT_ROBOTS=0
cd $D
echo "$(date) robots chain start pid $$ free $(free_mib) MiB"
SITES="de_by_kreisrecht_landkreis_cham_archive de_by_kreisrecht_landkreis_eichstätt_archive de_by_kreisrecht_landkreis_garmisch_partenkirchen_archive
 de_by_kreisrecht_landkreis_landsberg_am_lech_archive de_by_kreisrecht_landkreis_miesbach_archive de_by_kreisrecht_landkreis_neuburg_schrobenhausen_archive
 de_by_kreisrecht_landkreis_rhön_grabfeld_archive de_by_kreisrecht_landkreis_weißenburg_gunzenhausen_archive de_by_kreisrecht_landkreis_würzburg_archive
 de_by_kreisrecht_landkreis_ansbach_archive de_by_kreisrecht_landkreis_aschaffenburg de_by_kreisrecht_landkreis_amberg_sulzbach de_by_kreisrecht_landkreis_lindau_bodensee
 de_nds_landkreis_cuxhaven_retry de_nds_landkreis_ammerland_retry fr_raa_cd_fr-44_archive fr_raa_cd_fr-72_delib_archive harris_tx_retry"
for s in $SITES; do
  g
  n=$($PY $D/robots_recrawl_prep.py $D/$s.json 2>>$L/robots20261101c_prep.log) || { echo "$(date) $s prep failed"; continue; }
  [ "${n:-0}" -gt 0 ] || { echo "$(date) $s nothing pending"; continue; }
  echo "$(date) $s pending $n -> test"
  $PY -u $D/us_pdf_list.py $D/${s}_robotslive_test.json > $L/robots20261101c_${s}_test.log 2>&1
  ok=$(grep -c '^OK ' $L/robots20261101c_${s}_test.log)
  if [ "$ok" -lt 1 ]; then echo "$(date) $s test 0 OK -> skipped (see log)"; continue; fi
  g; echo "$(date) $s test ok=$ok -> full ($n)"
  $PY -u $D/us_pdf_list.py $D/${s}_robotslive.json > $L/robots20261101c_${s}.log 2>&1
  echo "$(date) $s done: $(tail -1 $L/robots20261101c_${s}.log)"
done
echo "$(date) robots chain complete"
