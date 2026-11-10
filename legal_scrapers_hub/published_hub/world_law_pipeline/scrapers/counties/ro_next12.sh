#!/bin/sh
# 2026-10-24 ro_next12: Gorj (Q190406, RO-GJ), the only uncovered judet with a crawlable live site. Earlier lists had it "archive-only", but
#  www.cjgorj.ro robots.txt now has two "User-agent: *" groups (Allow: / and Disallow: /); RFC 9309 merges them and the equal-length Allow wins ->
#  pipeline robots() = robots_allowed_rfc9309. One page (hotararile-autoritatii-deliberative) lists every adopted HCJ PDF; 765 for 2024-2026
#  ("/Sedinte Consiliu/<dd.mm.yyyy> - Adoptate/", annexes and registers excluded). follow_re "(?!)", max_pages 1. MAXU 800.
#  Test batch (ro_next12_test.log, slug județul_gorj_test): 5 ok / 1 fail (site href malformed -> 403), 5/5 rows validate.
# Still not covered (checked 2026-10-24): Alba (judetul-alba.ro Cloudflare 403, Wayback CDX has no 2024+ HCJ pages), Argeș (cjarges.ro Cloudflare challenge,
#  Wayback has only 2021-2022 decision pages), Suceava (JS browser check), Tulcea (SharePoint JS), Vrancea (.doc only), Bistrița-Năsăud/Iași/Brașov
#  (connection fails), Bucharest (SPA).
cd /workspace/world_law/pipeline/scrapers/counties
L=/workspace/world_law/staging/counties/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
export SSL_CERT_FILE=/workspace/world_law/pipeline/scrapers/counties/_cabundle/ro_bundle.pem
df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
echo "$(date) start"; $PY -u ro_council_build.py ro_next12_entries.json ro_cj_hcj 800; echo "$(date) done"
