#!/bin/sh
# 2026-10-23 ro_next9: new judete not yet staged/processed: Olt, Vâlcea, Prahova, Neamț (adopted HCJ only via pdf_re, MAXU 700).
# These four sites send incomplete TLS chains -> SSL_CERT_FILE=_cabundle/ro_bundle.pem (system+certifi roots + verified public intermediates,
# see _cabundle/README.txt; verification stays ON). robots.txt for all four allows the HCJ paths.
# Not included: Brăila (needs custom Domino lister), Tulcea (SharePoint JS), Alba/Argeș/Gorj (archive-only), Ialomița (archive queue running),
# Bistrița-Năsăud/Covasna/Iași (TLS handshake fails), Brașov (503), Suceava (robots 503) -> archive-only candidates.
cd /workspace/world_law/pipeline/scrapers/counties
L=/workspace/world_law/staging/counties/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
export SSL_CERT_FILE=/workspace/world_law/pipeline/scrapers/counties/_cabundle/ro_bundle.pem
df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
echo "$(date) start"; $PY -u ro_council_build.py ro_next9_entries.json ro_cj_hcj 700; echo "$(date) done"
