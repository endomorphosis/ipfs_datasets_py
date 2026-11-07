#!/usr/bin/env bash
# France: DILA LEGI open-data dumps (Licence Ouverte 2.0) from echanges.dila.gouv.fr/OPENDATA/LEGI/
# (robots.txt 404 => allowed). Resumable: wget -c; collect_legi resumes via index.jsonl.
set -u
B=https://echanges.dila.gouv.fr/OPENDATA/LEGI
W=/workspace/world_law/staging/national/_work/FR; D=$W/dumps; mkdir -p $D
N=/workspace/world_law/pipeline/scrapers/national; PY=/workspace/world_law/pipeline/venv/bin/python
export IPFS_DATASETS_LEGAL_CORPORA_ROOT=$W HF_TOKEN_PATH=/dev/null HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
UA="legal-corpora-collector/1.0 (research archive; polite)"
echo "=== $(date '+%F %T %Z') start"
GLOBAL=$(curl -s --max-time 60 $B/ | grep -o 'Freemium_legi_global_[0-9-]*\.tar\.gz' | sort -u | tail -1)
GTS=$(echo $GLOBAL | grep -o '[0-9]\{8\}-[0-9]\{6\}')
wget -q -c --limit-rate=4m -U "$UA" -O $D/$GLOBAL $B/$GLOBAL || { echo "global download failed"; exit 1; }
curl -s --max-time 60 $B/ | grep -o 'LEGI_[0-9]\{8\}-[0-9]\{6\}\.tar\.gz' | sort -u | while read f; do
  ts=$(echo $f | grep -o '[0-9]\{8\}-[0-9]\{6\}'); [[ "$ts" > "$GTS" ]] || continue
  [ -s $D/$f.done ] && continue
  wget -q -c --limit-rate=4m -U "$UA" -O $D/$f $B/$f && echo ok > $D/$f.done; sleep 1
done
echo "=== $(date '+%F %T %Z') downloads done"
if [ ! -f $W/.global_done ]; then
  $PY $N/shared/collect_legi.py $D/$GLOBAL && touch $W/.global_done
fi
INCR=$(ls $D/LEGI_*.tar.gz | sort)
if [ ! -f $W/.incr_done ]; then
  $PY $N/shared/collect_legi.py --overlay $INCR && touch $W/.incr_done
fi
$PY $N/emit_staged.py FR
echo "=== $(date '+%F %T %Z') FINISHED"
