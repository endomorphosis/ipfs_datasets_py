#!/bin/bash
# Run de_build.py one Land at a time with a MemAvailable watchdog (kill at <=3584 MB). Offline: reads raw cache only.
set -u
PY=/workspace/venv/bin/python; B=/workspace/legal-corpora/de_subnational
for L in "$@"; do
  m=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo); echo "$(date +%T) START $L MemAvail=${m}MB"
  [ "$m" -le 3584 ] && { echo "MEMGUARD STOP before $L"; exit 3; }
  $PY /workspace/scripts/de_build.py $B/build_parts/$L $L & pid=$!
  minm=99999
  while kill -0 $pid 2>/dev/null; do
    m=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo); [ $m -lt $minm ] && minm=$m
    if [ "$m" -le 3584 ]; then echo "MEMGUARD KILL $L at ${m}MB"; kill $pid; exit 3; fi
    sleep 2
  done
  wait $pid; rc=$?; echo "$(date +%T) END $L rc=$rc minMemAvail=${minm}MB"; [ $rc -ne 0 ] && exit $rc
done
echo ALL DONE
