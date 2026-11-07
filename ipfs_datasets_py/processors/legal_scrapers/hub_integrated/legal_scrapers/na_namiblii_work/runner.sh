#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
# nohup runner: fetch.py waits for >=30G disk / >=4.5G mem before every request (recheck 3 min); resumes from results.jsonl.
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}; W=na_namiblii_work; PY=/workspace/hf-venv/bin/python; ST=NA_NAMIBLII_STATUS.md
note(){ echo "- $(date '+%F %T %Z') runner: $*" >> $ST; }
note "started (pid $$)"
until [ -f $W/FETCH_DONE ]; do
  $PY $W/fetch.py >> $W/fetch.log 2>&1; rc=$?
  [ $rc = 3 ] && { note "STOPPED: archive.org blocking (see $W/BLOCKED)"; exit 3; }
  [ -f $W/FETCH_DONE ] || { note "fetch exited rc=$rc; restart in 300s"; sleep 300; }
done
note "fetch done: $(wc -l < $W/results.jsonl) records"
$PY $W/build.py > $W/build.log 2>&1 || { note "build FAILED (see $W/build.log)"; exit 1; }
note "$(tail -1 $W/build.log)"
$PY africa_me_b2/regate_all.py ready_africa_me_na_namiblii_20261023 $W/regate_na.json $W/hub_override.json > $W/regate.log 2>&1; note "regate rc=$? -> $W/regate_na.json"
P=ready_africa_me_na_namiblii_20261023/na
{ echo "READY NA namiblii archive pack (built $(date '+%F %T %Z'); NOT uploaded)"; echo "path: ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/$P"
  echo "hub: endomorphosis/ipfs_namibia_laws @ cffa06694596ba6439d555b05d311c94e3b97f8a  L/A 530/5791"
  $PY -c "import json;m=json.load(open('$P/MANIFEST.json'));print('pack L/A',m['rows'],'delta',m['new'])"
  sha256sum $P/data/*.parquet $P/README.md $P/MANIFEST.json
  echo "gates ($W/regate_na.json):"; head -c 4000 $W/regate_na.json 2>/dev/null; echo
  echo "terms: NamibLII s4 prohibits scraping/bulk download; s5 requires following robots.txt; robots disallows /gazettes/, /akn/na/officialGazette/ etc., Crawl-delay 5; Content-Signal ai-train=no, ai-input=no; licence CC BY-NC 4.0 (unconfirmed live); rows from Wayback/CC archive copies only; owner directed 2026-10-23."
} > handoffs/20261023_africa_me_READY_NA_namiblii.txt
note "DONE; handoff written"
