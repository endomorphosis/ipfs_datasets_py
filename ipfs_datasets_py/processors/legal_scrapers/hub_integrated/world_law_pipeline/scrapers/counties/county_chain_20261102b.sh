#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-02 04:40 PST: Bavarian top-up 3 (entries built by de_by_topup3_build.py + de_by_topup3_postfilter.py + de_by_topup3_normalize.py):
# Landkreise that were robots-blocked/archive-only or got tiny yields before the 2026-11-01 "ignore robots" decision.
# Phase 1: live pdf_list_fetch.py (2 s/host) per Landkreis under guard_run (10 GB disk / 1.5 GB RAM floors); each county's
#   live 404/410 URLs are written to de_by_kreisrecht_<Q>_topup3_404_archive.json.
# Phase 2: archive_retry.py (ArchiveFetcher with deferral) rounds over: Ebersberg (TLS reset live), Regensburg (WAF "Security
#   Check" 503 live -> no bypass), Fürth (403 live -> no bypass), plus the phase-1 404 lists. Runs in parallel with chain 20261102a (FR-31).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python; L=${WORLD_LAW_ROOT}/staging/counties/_logs; C=$L/county_chain_20261102b.log
echo "$(date) chain b start pid=$$" >> $C
for q in Q10507 Q10523 Q10477 Q10436 Q10518 Q10458 Q10465 Q10453 Q10454 Q10493 Q10491 Q10424; do f=entries/de_by_wd_$q.json; [ -f "$f" ] || continue
  guard_run "de_by_wd_$q" $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/de_by_fetch_topup3_$q.log 2>&1; rc=$?
  echo "$(date) [b] $f rc=$rc" >> $C; [ $rc -eq 99 ] && { echo "$(date) [b] guard stop" >> $C; exit 99; }
  $PY - "$q" >> $C 2>&1 <<'P'
import json, re, sys
q = sys.argv[1]; E = json.load(open(f"entries/de_by_wd_{q}.json"))
bad = re.findall(r"^ERR (\S+) (?:404|410)$", open(f"${WORLD_LAW_ROOT}/staging/counties/_logs/de_by_fetch_topup3_{q}.log").read(), re.M)
full = {i["url"] for i in E["items"]}; urls = [u for u in dict.fromkeys(bad)]
urls = [next((f for f in full if f.startswith(u)), u) for u in urls]  # log lines truncate URLs at 120 chars
if urls:
    json.dump(dict(country_code="DE", place_id=E["place_id"], qid=q, place_name=E["place_name"], iso_3166_2="DE-BY", admin_level="landkreis",
                   language="de", doc_type="ordinance", platform="de_by_kreisrecht", source_org=E["source_org"], archive_policy="archived_live_404",
                   max_bytes=52428800, urls=urls, titles={i["url"]: i["title"] for i in E["items"] if i["url"] in urls}),
              open(f"de_by_kreisrecht_{q}_topup3_404_archive.json", "w"), ensure_ascii=False, indent=1)
print(q, "live 404/410 ->archive list", len(urls))
P
done
echo "$(date) [b] phase 1 done; phase 2 archive rounds" >> $C
for round in 1 2 3 4; do
  for cfg in de_by_kreisrecht_landkreis_ebersberg_archive.json de_by_kreisrecht_landkreis_regensburg_archive.json de_by_kreisrecht_landkreis_fürth_archive.json de_by_kreisrecht_Q*_topup3_404_archive.json; do
    [ -f "$cfg" ] || continue; n=$(basename $cfg .json)
    guard_run "arch_$n" bash -c 'ARCHIVE_RETRY_STOPFILE=$GUARD_STOPFILE exec timeout 3300 '"$PY"' -u archive_retry.py '"$cfg"' 50' 2>&1 \
      | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|GUARD|Traceback|[A-Za-z]*Error)' >> $L/de_by_archive_topup3.log
    rc=${PIPESTATUS[0]}; echo "$(date) [b] archive round $round $cfg rc=$rc" >> $C; [ $rc -eq 99 ] && { echo "$(date) [b] guard stop" >> $C; exit 99; }
  done
  [ $round -lt 4 ] && sleep 900
done
echo "$(date) chain b done" >> $C
