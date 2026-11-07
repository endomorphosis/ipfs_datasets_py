#!/bin/bash
# deferq_compact_loop.sh (2026-10-31): until every lane process started before the deferq.py auto-compaction fix
# (2026-10-31 12:09 PDT) has exited, compact any states-lane deferred.tsv > 20 MB every 2 h (newest line per key;
# deferq_compact.py takes the <path>.lock flock and re-reads bytes appended during the scan). Exits by itself.
cd /workspace/world_law/pipeline/scrapers/states
S=/workspace/world_law/staging/states
FIX=$(date -d '2026-10-31 12:09:18' +%s)
old_alive() {
  for p in $(pgrep -f 'run_full.py|arch_states.py'); do
    [ "$(readlink /proc/$p/cwd 2>/dev/null)" = "$PWD" ] || continue
    st=$(( $(date +%s) - $(ps -o etimes= -p $p) ))
    [ "$st" -lt "$FIX" ] && return 0
  done
  return 1
}
while old_alive; do
  sleep 7200
  avail=$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)
  [ "${avail:-0}" -lt 11 ] && echo "$(date '+%F %T') disk ${avail}G < 11G: skip" && continue
  for f in $S/_state/*.deferred.tsv $S/_work/*/deferred.tsv; do
    [ -f "$f" ] && [ $(stat -c %s "$f") -gt 20000000 ] && ../../venv/bin/python deferq_compact.py "$f"
  done
done
echo "$(date '+%F %T') no pre-fix lane process left; exiting"
