#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# usage: afme_slot.sh x <cmd...> : flock-serialised wait until fewer than 3 afme crawl python processes run, then run cmd with an RSS guard. Rebuilt 2026-10-18.
cd ${WORLD_LAW_ROOT}/out; shift
cnt(){ pgrep -f "^[^ ]*python[^ ]* (-W ignore )?afme_(cc|ccidx|live|au_live|pdfgaz|lus_[a-z]+|cv_boe|aus_gaz|arch10|live10|arch11|live11)\.py" | wc -l; }
exec 9>afme/.slot.lock; flock 9
while [ "$(cnt)" -ge 3 ]; do sleep 30; done
"$@" & p=$!; sleep 15; setsid nohup ./afme_rss_guard.sh $p >/dev/null 2>&1 &
flock -u 9; wait $p
