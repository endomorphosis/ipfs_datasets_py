#!/bin/sh
# 2026-11-01 ~11:50 PST: resume Loire FR-42 délibérations top-up after the 10:20 reboot. Runs us_pdf_list.py directly on the already-built
# fr_raa_cd_fr-42.json (3,372 URLs; index not re-crawled). us_pdf_list skips source_urls already in staging/counties + processed/counties/FR
# (doc_ids are ~urlhash of the URL, so URL skip = doc_id skip). Cher/Meurthe-et-Moselle/Haute-Loire NOT redone. Robots RFC 9309, crawl_delay from cfg.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh
g; echo "$(date) start Loire resume"
$PY -u us_pdf_list.py fr_raa_cd_fr-42.json >> /workspace/world_law/staging/counties/_logs/fr_raa_cd_FR-42.log 2>&1
echo "$(date) done rc=$?"
