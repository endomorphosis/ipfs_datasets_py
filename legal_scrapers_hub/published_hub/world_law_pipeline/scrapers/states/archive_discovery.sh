#!/bin/bash
# Wayback URL discovery for archive-only sources (CC has no 200 captures for these robots-blocked/challenged hosts).
# Resumable: cdx_list.py caches finished parts in data/cdx_parts/.
cd /workspace/world_law/pipeline/scrapers/states
V=/workspace/world_law/pipeline/venv/bin/python
D=data/archive
mkdir -p $D
$V cdx_list.py $D/nsw.txt legislation.nsw.gov.au/view/html/inforce/current/ act- sl- epi-
$V cdx_list.py $D/qc.txt www.legisquebec.gouv.qc.ca/en/document/ cs/ rc/
$V cdx_list.py $D/bc.txt www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/ 0 1 2 3 4 5 6 7 8 9
$V cdx_list.py $D/yt.txt laws.yukon.ca/cms/images/LEGISLATION/ PRINCIPAL/ SUBORDINATE/
$V cdx_list.py $D/ab.txt kings-printer.alberta.ca/documents/ Acts/ Regs/
$V cdx_list.py $D/sa.txt www.legislation.sa.gov.au/lz ""
$V cdx_list.py $D/vic.txt www.legislation.vic.gov.au/in-force/ acts/ statutory-rules/
