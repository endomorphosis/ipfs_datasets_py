#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-01 PST: Loire FR-42 waiter. Every 45 min probe https://webdelib-citoyens.loire.fr/ once (honest UA, no proxy).
# 200 + real content -> resume pdf_list_fetch.py on entries/fr_raa_cd_fr-42.json under guard, then exit. Block page (403/WAF/captcha) -> log, exit. Give up after 24 h.
# 19:27 PST: if the resume stops on 25 consecutive doc errors (homepage up, showFile.jsp down), go back to waiting.
# 19:21 PST: follow redirects (/ -> /webdelib/ frameset, ~400 B); real content = 200 + <title> + <frameset|body>.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python; L=${WORLD_LAW_ROOT}/staging/counties/_logs; W=$L/fr42_loire_waiter.log
UA="WorldLawBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; public-law research crawler; polite)"
URL=https://webdelib-citoyens.loire.fr/; end=$(( $(date +%s) + 86400 ))
echo "$(date) waiter start pid=$$" >> $W
while [ $(date +%s) -lt $end ]; do
  b=/tmp/fr42_probe_$$.html; code=$(curl -sL --max-redirs 5 --noproxy '*' -A "$UA" -m 60 -o $b -w '%{http_code}' "$URL"); sz=$(stat -c %s $b 2>/dev/null || echo 0)
  if grep -qiE 'captcha|cf-chl|challenge-platform|access denied|request rejected|incapsula|datadome|web application firewall|are you a robot' $b 2>/dev/null || [ "$code" = 403 ]; then
    echo "$(date) probe BLOCK code=$code size=$sz -> exit (no bypass)" >> $W; head -c 400 $b >> $W; echo >> $W; rm -f $b; exit 3; fi
  if [ "$code" = 200 ] && [ "$sz" -ge 300 ] && grep -qiE '<(frameset|body)' $b && grep -qi '<title>' $b; then
    echo "$(date) probe OK code=200 size=$sz -> resume" >> $W; rm -f $b
    guard_run loire_fr42 $PY -u pdf_list_fetch.py entries/fr_raa_cd_fr-42.json >> $L/loire_fr42.log 2>&1; rc=$?
    echo "$(date) resume ended rc=$rc; $(grep SUMMARY $L/loire_fr42.log | tail -1)" >> $W
    [ $rc -eq 99 ] && { echo "$(date) guard stop -> exit" >> $W; exit 99; }
    if tail -3 $L/loire_fr42.log | grep -q "consecutive errors"; then echo "$(date) homepage up but documents still failing -> keep waiting" >> $W; sleep 2700; continue; fi
    echo "$(date) done -> exit" >> $W; exit $rc; fi
  echo "$(date) probe down code=$code size=$sz; next in 45 min" >> $W; rm -f $b; sleep 2700
done
echo "$(date) 24 h elapsed -> give up" >> $W
