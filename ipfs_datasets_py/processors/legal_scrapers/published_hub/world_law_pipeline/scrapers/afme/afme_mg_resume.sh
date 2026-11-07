#!/usr/bin/env bash
# MG-only resume: live cnlegis with bounded backoff; on live host failure, CC then Wayback
# via afme_arch (1 Wayback worker / breaker). Does not re-run SN/ML. Stages via afme_stage.py.
set -u
export ARCHIVE_LANE=afme AFME_AS_LIMIT_MB=1200 PYTHONUNBUFFERED=1
PY=/workspace/world_law/.venv_afme/bin/python
OUT=/workspace/world_law/out
LOG=/workspace/world_law/staging/afme/_logs/mg_resume_$(date -u +%Y%m%dT%H%M%SZ).log
NOHUP_META=/workspace/world_law/out/afme/mg_resume.nohup
mkdir -p "$(dirname "$LOG")"
cd "$OUT"
ulimit -v 1228800
echo "log $LOG" | tee "$NOHUP_META"
echo "== MG resume start $(date -u +%FT%TZ)" | tee -a "$LOG" | tee -a "$NOHUP_META"
mem_mb=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 2048 ]; then echo "mem guard: MemAvailable ${mem_mb} MB, stop" | tee -a "$LOG"; exit 4; fi
if ! $PY -c 'import afme_common as C; C.disk_check()'; then
  echo "disk guard: stop after confirm/retry" | tee -a "$LOG"; exit 3
fi
echo "== MG live $(date -u +%FT%TZ)" | tee -a "$LOG" | tee -a "$NOHUP_META"
set +e
$PY -u afme_mg_cnlegis.py >>"$LOG" 2>&1
live_rc=$?
set -e
echo "MG live exit $live_rc" | tee -a "$LOG" | tee -a "$NOHUP_META"

# Archive fallback when live host stayed unreachable (exit 2) or crashed (nonzero).
# CC first, then Wayback through breaker (afme_arch). Tagging: *_archive_fallback source_policy.
if [ "$live_rc" -ne 0 ]; then
  TODO=afme/done/arch_todo_MG.tsv
  mkdir -p afme/done
  # Seed with cnlegis root + search entry (POST JSON body is not in archives; still try captures).
  # Preserve any existing todo lines. Fragment live keys (#texte-ID) are not useful for archives.
  {
    echo -e "iso:MG\thttps://www.cnlegis.gov.mg/"
    echo -e "iso:MG\thttps://www.cnlegis.gov.mg/page_find_direct_mots_texte/"
    [ -s "$TODO" ] && cat "$TODO"
  } | awk -F'\t' 'NF>=2 && !seen[$2]++' > "$TODO.tmp" && mv "$TODO.tmp" "$TODO"
  echo "== MG archive (CC then Wayback) $(date -u +%FT%TZ) todo=$(wc -l < "$TODO") lines" | tee -a "$LOG" | tee -a "$NOHUP_META"
  set +e
  $PY -u afme_arch.py MG --urls-file "$TODO" >>"$LOG" 2>&1
  arch_rc=$?
  set -e
  echo "MG arch exit $arch_rc" | tee -a "$LOG" | tee -a "$NOHUP_META"
fi

echo "== MG stage $(date -u +%FT%TZ)" | tee -a "$LOG" | tee -a "$NOHUP_META"
set +e
$PY -u afme_stage.py MG >>"$LOG" 2>&1
stage_rc=$?
set -e
echo "MG stage exit $stage_rc" | tee -a "$LOG" | tee -a "$NOHUP_META"
echo "== MG resume done $(date -u +%FT%TZ)" | tee -a "$LOG" | tee -a "$NOHUP_META"
exit 0
