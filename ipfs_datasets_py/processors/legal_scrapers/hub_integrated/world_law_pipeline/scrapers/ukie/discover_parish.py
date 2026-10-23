#!/usr/bin/env python3
"""Phase 2 site discovery for GB town/parish/community councils.

Sources (no crawling of third-party lists without robots check):
  1. Wikidata (qlever mirror): P856 of the parish item, P856 of its legislative body (P194) and of any
     item that is P1001-'applies to jurisdiction' / P2541-'operating area' the parish and is a council.
  2. place candidate source_url (already in state).
Classifies each URL: council_site (domain/path says council / pc / tc / gov.uk parish domain), principal_site
(the domain of a GB principal council -> rejected: those docs belong to phase 1), community_site (village
website: kept as a fallback, crawled with a lower page budget), or rejected (social media, hosting landing pages).
Writes _state/parish_sites.csv and updates places.site / places.note in the state db (never deletes)."""
import csv, json, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).parent))
from common.util import STATE_DIR, UA, State, guard  # noqa: E402
from councils import site_key  # noqa: E402

QLEVER = "https://qlever.dev/api/wikidata"
PREFIX = ("PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX wd: <http://www.wikidata.org/entity/> "
          "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> ")
CACHE = STATE_DIR / "cache"
SOCIAL = re.compile(r"facebook\.|twitter\.|x\.com|instagram\.|wikipedia\.|youtube\.|linkedin\.|google\.|nextdoor\.", re.I)
COUNCILISH = re.compile(r"council|parish|\bpc\b|-pc\.|pc\.(?:gov|org|co)|towncouncil|\btc\b|-tc\.|tc\.(?:gov|org)|"
                        r"cyngor|cymuned|communitycouncil|-cc\.|\.gov\.uk$", re.I)


def qlever(query, out):
    if out.exists() and out.stat().st_size > 50:
        return out
    tmp = out.with_suffix(".tmp")
    subprocess.run(["curl", "-sS", "-m", "600", "--retry", "3", "--retry-delay", "20", "-A", UA,
                    "-H", "Accept: text/tab-separated-values", "--data-urlencode", f"query={query}", QLEVER,
                    "-o", str(tmp)], check=True)
    tmp.replace(out)
    time.sleep(2)
    return out


def tsv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        next(f, None)
        for l in f:
            p = [x.strip() for x in l.rstrip("\n").split("\t")]
            rows.append([re.sub(r"^<http://www\.wikidata\.org/entity/(Q\d+)>$", r"\1", x).strip("<>\"") for x in p])
    return rows


def main():
    st = State()
    rows = st.c.execute("SELECT place_id, name, tier, site FROM places WHERE phase=2").fetchall()
    principal = {site_key(urlparse(s).hostname or "") for (s,) in
                 st.c.execute("SELECT site FROM places WHERE phase=1 AND site!=''")}
    principal |= {site_key(h) for h in ("gov.uk", "gov.wales", "llyw.cymru", "nidirect.gov.uk")}
    qids = [r[0].split(":")[1] for r in rows]
    found = {}
    for i in range(0, len(qids), 1500):
        guard()
        vals = " ".join(f"wd:{q}" for q in qids[i:i + 1500])
        q = (PREFIX + f"SELECT ?p ?src ?url WHERE {{ VALUES ?p {{ {vals} }} "
             "{ ?p wdt:P856 ?url . BIND(\"P856\" AS ?src) } UNION "
             "{ ?p wdt:P194 ?b . ?b wdt:P856 ?url . BIND(\"P194.P856\" AS ?src) } UNION "
             "{ ?b wdt:P1001 ?p . ?b wdt:P856 ?url . ?b rdfs:label ?bl . FILTER(LANG(?bl)=\"en\" && "
             "CONTAINS(LCASE(?bl), \"council\")) BIND(\"P1001.P856\" AS ?src) } }")
        for p, src, url in (r[:3] for r in tsv(qlever(q, CACHE / f"wd_parish_sites_{i // 1500}.tsv")) if len(r) >= 3):
            found.setdefault("wd:" + p, []).append((src, url))
    out = []
    stats = {}
    for pid, name, tier, cur in rows:
        cands = found.get(pid, []) + ([("candidate", cur)] if cur else [])
        best, cls = "", "none"
        ranked = []
        for src, u in cands:
            u = u.strip()
            if not u.startswith("http"):
                continue
            h = (urlparse(u).hostname or "").lower()
            if SOCIAL.search(h):
                c = "rejected_social"
            elif site_key(h) in principal:
                c = "principal_site"
            elif COUNCILISH.search(h) or COUNCILISH.search(urlparse(u).path) or src.startswith("P194") or src.startswith("P1001"):
                c = "council_site"
            else:
                c = "community_site"
            ranked.append(({"council_site": 0, "community_site": 1}.get(c, 9), src != "P194.P856", u, c, src))
        ranked.sort()
        if ranked and ranked[0][0] < 9:
            _, _, best, cls, src = ranked[0]
        elif ranked:
            cls = ranked[0][3]
        stats[cls] = stats.get(cls, 0) + 1
        out.append({"place_id": pid, "name": name, "tier": tier, "site": best, "class": cls,
                    "candidates": json.dumps([(c[4], c[2], c[3]) for c in ranked])})
        if best and best != cur:
            st.c.execute("UPDATE places SET site=? WHERE place_id=?", (best, pid))
        st.c.execute("UPDATE places SET mode=? WHERE place_id=?", (cls, pid))
    st.c.commit()
    with open(STATE_DIR / "parish_sites.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)
    print(json.dumps(stats))
    print("DISCOVER_PARISH_DONE")


if __name__ == "__main__":
    main()
