#!/bin/bash
# 2026-11-05 00:11 PST: VIC 20-row archive test. vic.txt (10,817 URLs) ready since ~Oct 29;
# archive_tests.sh is blocked on missing sa.txt, and archive_tests_sa_vic.sh also waits on SA first.
# Archive-only path (content.legislation.vic.gov.au robots-disallowed); terms tagged on rows.
# Output HELD in _review for eyeball before promote. Single-instance lock.
cd /workspace/world_law/pipeline/scrapers/states
LOCK=/workspace/world_law/staging/states/_state/au_vic_test_queue.lock
exec 8>"$LOCK"
flock -n 8 || { echo "$(date) au_vic_test_queue already locked"; exit 0; }
pgrep -f "run_full.py --source au_vic_archive( |$)" >/dev/null && { echo "$(date) au_vic_archive already running"; exit 0; }
L=/workspace/world_law/staging/states/_logs
zcat -f $L/test_au_vic_archive.out $L/test_au_vic_archive.out.gz 2>/dev/null | grep -q "END" && { echo "$(date) VIC test already ENDed"; exit 0; }
[ -s data/archive/vic.txt ] || { echo "$(date) missing data/archive/vic.txt"; exit 1; }
. ./lane_ramgate.sh
PY=/workspace/world_law/pipeline/venv/bin/python
echo "$(date) VIC 20-row test starting via ramgate"
ramgate_run 150 $L/test_au_vic_archive.out $PY -u run_full.py --source au_vic_archive --test 20
echo "$(date) AUVIC_TEST_END rc=$?"
