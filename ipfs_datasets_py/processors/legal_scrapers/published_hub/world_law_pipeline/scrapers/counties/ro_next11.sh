#!/bin/sh
# 2026-10-24 ro_next11: deep re-crawls of two judete whose earlier runs hit the 60-page cap (all 41 judete + Bucharest already attempted).
#  Hunedoara (Q191071): Joomla year pages 916-hotarari-2026 / 830-hotarari-2025 / 744-hotarari-2024 list 213/336/390 HCJH PDFs (earlier run: 42 ok). Order 2026,2025,2024; 700 cap.
#  Harghita (Q190702): one WP post per decision (hotararea-nr-N-dd-mm-yyyy), 1071 posts for 2024-2026 in wp-sitemap; 780 newest seeded (earlier run: 65 ok). Many scans -> raw, no OCR.
# Uses new optional entry key "seeds" (extra depth-0 URLs) in ro_council_build.py (backup: ro_council_build.py.bak_20261024_ro_next11); follow_re "(?!)" = no link following.
# robots.txt: cjhunedoara.ro Joomla default (Disallow admin dirs only), judetulharghita.ro / hargitamegye.ro WP default. SSL_CERT_FILE as ro_next9/10. MAXU 700.
# Not included: Mureș (robots Crawl-Delay 20, pipeline uses 2 s), Maramureș/Neamț year lists JS-rendered, Arad list = draft projects only; blocked list as ro_next10.
cd /workspace/world_law/pipeline/scrapers/counties
L=/workspace/world_law/staging/counties/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
export SSL_CERT_FILE=/workspace/world_law/pipeline/scrapers/counties/_cabundle/ro_bundle.pem
df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
echo "$(date) start"; $PY -u ro_council_build.py ro_next11_entries.json ro_cj_hcj 700; echo "$(date) done"
