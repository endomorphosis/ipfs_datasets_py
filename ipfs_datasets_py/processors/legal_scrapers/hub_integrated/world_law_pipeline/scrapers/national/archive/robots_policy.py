"""Robots status of the official hosts the national archive lane reads ONLY from web archives.

Decision (Benjamin, 2026-10-10 via coordinator): archived copies (Common Crawl / Wayback) are allowed even
for sites whose robots.txt disallows live crawling; live crawling rules are unchanged (no live requests to
these hosts - this lane never makes any). Every document whose original host is listed here carries
    source_policy = "archived_robots_disallowed"
top level, in extra_metadata.archive, and in the _archive_provenance sidecar, plus robots_basis (why).

Basis = the national lane's RFC 9309 robots checks (staging/national/_logs/probe_phase3.jsonl,
robots_recheck_full_runs.txt, _phase3_status.bak.json, robots_guard.py). Under that rule an unreachable
robots.txt (TLS reset / timeout / 5xx) means disallow-all. No live robots.txt was fetched for this list.
"""
import re
from urllib.parse import urlsplit

POLICY = "archived_robots_disallowed"

# host suffix -> basis
DISALLOWED = {
    "flk.npc.gov.cn": "robots.txt Disallow-all (parsed)",
    "wb.flk.npc.gov.cn": "file host of flk.npc.gov.cn (robots Disallow-all); treated as same site",
    "npc.gov.cn": "robots.txt unreachable (TLS reset) => disallow-all",
    "adilet.zan.kz": "robots.txt disallows /api/ (SPA content source) and states an anti-bulk-corpus policy",
    "busquedas.elperuano.pe": "robots.txt unreachable (TLS) => disallow-all",
    "elperuano.pe": "robots.txt unreachable (TLS) => disallow-all",
    "spij.minjus.gob.pe": "archive-only target with elperuano (robots not checked live; treated as disallowed)",
    "kuwaitalyawm.media.gov.kw": "robots.txt unreachable (TLS) => disallow-all",
    "diputados.gob.mx": "robots.txt unreachable (TLS reset) => disallow-all",
    "dof.gob.mx": "robots.txt unreachable (TLS reset) => disallow-all",
    "sidof.segob.gob.mx": "robots.txt unreachable (TLS reset) => disallow-all",
    "parliament.gov.eg": "robots.txt unreachable (TLS) => disallow-all",
    "cc.gov.eg": "robots.txt unreachable (TLS) => disallow-all",
    "peraturan.go.id": "robots.txt unreachable (TLS reset) => disallow-all",
    "pravo.gov.ru": "robots.txt unreachable (connect timeout) => disallow-all",
    "krisdika.go.th": "robots.txt unreachable (TLS) => disallow-all",
    "bdlaws.minlaw.gov.bd": "robots.txt unreachable (connect timeout) => disallow-all",
    "rc.majlis.ir": "robots.txt unreachable (TLS) => disallow-all",
    "ris.bka.gv.at": "robots.txt unreachable (TLS reset) => disallow-all",
    "bka.gv.at": "robots.txt unreachable (TLS reset) => disallow-all",
    "io.gov.mo": "robots.txt unreachable (TLS EOF https / connect timeout http, 2026-10-16) => disallow-all",
}


def policy_for(url: str):
    """(source_policy, robots_basis) for an original URL, or (None, None)."""
    h = (urlsplit(url).hostname or "").lower()
    for suf, basis in sorted(DISALLOWED.items(), key=lambda kv: -len(kv[0])):
        if h == suf or h.endswith("." + suf):
            return POLICY, basis
    return None, None
