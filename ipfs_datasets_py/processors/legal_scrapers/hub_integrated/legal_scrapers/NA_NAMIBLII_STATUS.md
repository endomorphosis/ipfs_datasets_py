# NA NamibLII archive pack status (resume-safe)
Owner direction 2026-10-23 9:23 AM PT: build from Wayback + Common Crawl archived copies. No live namiblii.org doc pages (Cloudflare 403 challenge seen 09:2x PT).
Note: an earlier work dir + this status file were deleted by something else around 09:27 PT; recreated. Script backups are in the bot store na_namiblii_backup/.
Hub baseline: endomorphosis/ipfs_namibia_laws @ cffa06694596ba6439d555b05d311c94e3b97f8a = 530 laws / 5,791 articles; 0 namiblii.org rows in Hub. Copy: na_namiblii_work/hub_base/.
## Wayback CDX inventory (/akn/na/ prefix, status 200, collapse urlkey) — na_namiblii_work/wb_inventory.json
| category | archived works | with archived source.pdf |
|---|---|---|
| Acts (/akn/na/act/YYYY/..) | 981 | 444 |
| Subsidiary (gn 790, p 301, ord 102, genn 40, reg 1) | 1,234 | 424 |
| Government Gazettes (/akn/na/officialGazette/) | 4,373 | 0 |
| total | 6,588 | |
Missing vs live: live lists not enumerable (doc pages challenged); live subsidiary listing said 476 docs; the ~821 figure in the brief could not be checked. Wayback has more than the live listing showed (it includes repealed and historical instruments).
Common Crawl: fallback for Wayback misses, run inside fetch.py (index lookups + ranged WARC only).
## Runner
na_namiblii_work/runner.sh (nohup) -> fetch.py (checkpoint results.jsonl, raw/*.json) -> build.py -> regate_all.py -> handoffs/20261023_africa_me_READY_NA_namiblii.txt
Progress: wc -l na_namiblii_work/results.jsonl ; tail na_namiblii_work/fetch.log. Resume: re-run nohup na_namiblii_work/runner.sh (skips done keys).
## Log
- 2026-10-23 09:30:17 PDT runner: started (pid 9979)
- 2026-10-27 22:20:08 PDT runner: started (pid 28628)
## Recovery 2026-10-27 22:2x PDT (after box snapshot restore ~20:49 PDT)
- Survived (all present, snapshot-stale): na_namiblii_work/{runner.sh,fetch.py,build.py,wb_inventory.json,wb_akn.txt,results.jsonl (3,301 records, all Wayback; fetch.log last entry 2026-10-26 18:53 before restart),raw/ (1,348 files),hub_base/}; NA_NAMIBLII_STATUS.md; common_crawl_helper.py; africa_me_b2/hub_pins.json (no NA pin in it); scripts identical to bot-store na_namiblii_backup/.
- Lost / absent: ready_africa_me_na_namiblii_20261023/ (never built - expected, build runs after fetch); no runner process was alive. Results after the snapshot point (if any) are unrecoverable.
- Hub head re-verified 2026-10-27: endomorphosis/ipfs_namibia_laws @ cffa06694596ba6439d555b05d311c94e3b97f8a = 530 laws / 5,791 articles (unchanged; floor). Fresh read-only snapshot in na_namiblii_work/hub_base_head_20261027/ (parquet sha256 identical to hub_base/).
- Changes: fetch.py disk gate lowered 30G -> 22G per owner rule (backup fetch.py.bak_pre_22g); results.jsonl backed up to results.jsonl.bak_20261027. Mem gate 4.5G unchanged (fetch.py pauses/rechecks per request).
- Runner restarted 22:20 PDT (pid 28628) resuming at 3,301/6,588. NOT uploading; Chief of Staff owns upload.
- 2026-10-27 22:24 PDT: runner alive but PAUSED on disk gate (free 21.8G < 22G; shared box, other jobs growing disk). Still 3,301/6,588; will auto-resume when >=22G free and MemAvailable>=4.5G. I do not delete anything to free space.
- 2026-10-28 00:02:01 PDT runner: fetch done: 6588 records
- 2026-10-28 00:02:06 PDT runner: BUILT 1636 28171 new 1106 22380 skipped 0
- 2026-10-28 00:02:14 PDT runner: regate rc=1 -> na_namiblii_work/regate_na.json
- 2026-10-28 00:02:14 PDT runner: DONE; handoff written
