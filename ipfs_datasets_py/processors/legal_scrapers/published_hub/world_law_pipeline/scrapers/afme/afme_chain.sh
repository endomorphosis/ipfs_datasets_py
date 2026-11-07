#!/usr/bin/env bash
# afme chain runner TEMPLATE: live -> archive fallback -> stage, one country at a time, ONE process at a time.
# Usage: out/afme_chain.sh KE NG GH ...      (each needs out/afme_config/<CC>.json)
# Not started automatically. Stops on disk guard (<20 GiB) or memory guard (>300 MB RSS) exit.
set -u
export ARCHIVE_LANE=afme
PY=/workspace/world_law/.venv_afme/bin/python
OUT=/workspace/world_law/out
LOG=/workspace/world_law/staging/afme/_logs/chain_$(date -u +%Y%m%dT%H%M%SZ).log
mkdir -p "$(dirname "$LOG")"
cd "$OUT"
for CC in "$@"; do
  free_gib=$(df --output=avail -BG /workspace | tail -1 | tr -dc 0-9)
  if [ "$free_gib" -lt 20 ]; then echo "disk guard: ${free_gib} GiB free, stop" | tee -a "$LOG"; exit 3; fi
  [ "$free_gib" -lt 23 ] && echo "WARN disk ${free_gib} GiB free" | tee -a "$LOG"
  echo "== $CC live" | tee -a "$LOG"
  ulimit -v 1228800
  $PY afme_live.py "$CC" >>"$LOG" 2>&1 || { echo "$CC live exit $?" | tee -a "$LOG"; }
  # Archive fallback: feed URLs that missed live, e.g. built from done/live_<CC>.tsv (status miss/skip_challenge):
  #   awk -F'\t' '$2!="ok"' afme/done/live_$CC.tsv | ... > afme/done/arch_todo_$CC.tsv  (place_id<TAB>url)
  if [ -s "afme/done/arch_todo_$CC.tsv" ]; then
    echo "== $CC archive" | tee -a "$LOG"
    $PY afme_arch.py "$CC" --urls-file "afme/done/arch_todo_$CC.tsv" >>"$LOG" 2>&1 || echo "$CC arch exit $?" | tee -a "$LOG"
  fi
  echo "== $CC stage" | tee -a "$LOG"
  $PY afme_stage.py "$CC" >>"$LOG" 2>&1 || echo "$CC stage exit $?" | tee -a "$LOG"
done
