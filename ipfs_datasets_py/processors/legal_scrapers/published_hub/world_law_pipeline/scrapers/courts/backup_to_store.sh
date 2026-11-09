#!/bin/bash
# code + small checkpoints/state only (no big data, no forms) -> persistent store. Uses rsync if present, else cp -ru.
set -e; TX="tar xf - -m --no-same-permissions --no-overwrite-dir"
S=/cursor/stores/store-0b063521-6018-4678-a901-018ed0a65ecf/world_courts_backup
W=/workspace/world_courts
mkdir -p $S/scrapers_courts $S/rules_out $S/data_state $S/forms_offload_state $S/state
if command -v rsync >/dev/null; then
  rsync -a --exclude '__pycache__' --exclude '*.log' $W/scrapers/courts/ $S/scrapers_courts/
  rsync -a $W/rules/out/ $S/rules_out/
  rsync -a --exclude backups --exclude forms_index.parquet --exclude '*.lock' $W/forms_offload/ $S/forms_offload_state/
  rsync -a $W/state/ $S/state/
else
  (cd $W/scrapers/courts && find . -type f ! -name '*.log' ! -path '*__pycache__*' -print0 | tar cf - --exclude='*.log' --exclude=__pycache__ . | $TX -C $S/scrapers_courts)
  cp -ru $W/rules/out/. $S/rules_out/
  cp -ru $W/forms_offload/state.json $S/forms_offload_state/
  cp -ru $W/state/. $S/state/
fi
(cd $W/data && find . -type f \( -name '*blockers*' -o -name '*inbox*' \) -size -50M | tar cf - -T - | $TX -C $S/data_state)
cp $W/publish/.upload_state.json $W/backup_to_store.sh $S/
date > $S/LAST_BACKUP
