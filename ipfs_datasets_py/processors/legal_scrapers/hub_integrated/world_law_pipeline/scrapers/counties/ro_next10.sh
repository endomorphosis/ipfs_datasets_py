#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-23 ro_next10: Covasna (new judet, Q188959; covasna.info.ro 2024-2026 month pages, RO-language HCJ PDFs only) +
# Satu Mare 2026 deep crawl (Q165459; previous run hit the 60-page cap -> 17 docs; per-decision pages, 200-page cap, slug keeps old cfg/log).
# Uses new optional entry keys in ro_council_build.py: slug, follow_re, max_pages (backup: ro_council_build.py.bak_20261023_ro_next10). MAXU 700.
# robots.txt: covasna.info.ro "Allow: /", cjsm.ro "Disallow:" (empty). SSL_CERT_FILE as ro_next9 (verification ON).
# Not included: Vrancea (HCJ published as .doc only; pipeline is PDF-only), Bistrița-Năsăud/Iași/cjcovasna.ro (TLS handshake fails),
# Brașov (503), Suceava (JS browser challenge), Tulcea (SharePoint JS), Galați (robots.txt unreachable: TLS EOF), Timiș (JS list),
# Bucharest pmb.ro (Angular SPA), Brăila (custom Domino lister), Alba/Argeș/Gorj (archive-only).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
L=${WORLD_LAW_ROOT}/staging/counties/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
export SSL_CERT_FILE=${WORLD_LAW_ROOT}/pipeline/scrapers/counties/_cabundle/ro_bundle.pem
df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
echo "$(date) start"; $PY -u ro_council_build.py ro_next10_entries.json ro_cj_hcj 700; echo "$(date) done"
