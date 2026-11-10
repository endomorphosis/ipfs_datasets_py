#!/bin/bash
# Re-creates the 2026-10-17 cdx_list chain (lost in the box move): ACT a/ and sl/ by year, then the remaining Ontario
# regulation sub-prefixes. cdx_list.py skips parts already cached in data/cdx_parts/ (ACT a/1900-1921 done).
cd /workspace/world_law/pipeline/scrapers/states
V=/workspace/world_law/pipeline/venv/bin/python
Y=$(seq 1900 $(date +%Y))
$V cdx_list.py data/act_a_cdx.txt www.legislation.act.gov.au/a/ $Y
$V cdx_list.py data/act_sl_cdx.txt www.legislation.act.gov.au/sl/ $Y
$V cdx_list.py data/on_regulation_cdx_extra.txt www.ontario.ca/laws/regulation/ 9006 9007 9008 9009 901 902 903 91 92 93 94 95 96 97 98 99
