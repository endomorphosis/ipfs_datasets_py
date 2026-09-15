#!/usr/bin/env python3
"""Best-effort remaining EU gazettes: HR SI RO HU PT GR BG CY HU."""
from __future__ import annotations
import json, logging, re, sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

log = logging.getLogger("remain")

SPECS = {
    "hr": {
        "country": "Croatia", "lang": "hr", "source_type": "narodne_novine",
        "license": "Narodne novine official gazette (nn.hr / ehrm.nn.hr). Official texts; reuse per NN terms.",
        "seeds": [
            "https://narodne-novine.nn.hr/",
            "https://narodne-novine.nn.hr/clanci/sluzbeni/index.html",
            "https://ehrm.nn.hr/",
            "https://www.nn.hr/",
        ],
        "list_urls": [f"https://narodne-novine.nn.hr/clanci/sluzbeni/{y}/index.html" for y in range(2020, 2027)],
        "link_re": r"href=\"([^\"]+/clanci/sluzbeni/[^\"]+\.html)\"",
    },
    "si": {
        "country": "Slovenia", "lang": "sl", "source_type": "pisrs",
        "license": "PISRS / Uradni list RS official consolidations. https://www.pisrs.si/",
        "seeds": ["https://www.pisrs.si/", "https://www.uradni-list.si/", "https://www.pisrs.si/Pis.web/pregledPredpisov"],
        "list_urls": ["https://www.pisrs.si/Pis.web/pregledPredpisov?type=zakon"],
        "link_re": r"href=\"([^\"]*(?:Pis\.web|uradni-list)[^\"]+)\"",
    },
    "ro": {
        "country": "Romania", "lang": "ro", "source_type": "legislatie_just",
        "license": "legislatie.just.ro official portal of the Ministry of Justice.",
        "seeds": ["https://legislatie.just.ro/", "http://legislatie.just.ro/Public/Home/Index"],
        "list_urls": ["https://legislatie.just.ro/Public/Home/Index"],
        "link_re": r"href=\"([^\"]*DetaliiDocument[^\"]+)\"",
    },
    "hu": {
        "country": "Hungary", "lang": "hu", "source_type": "njt",
        "license": "Nemzeti Jogszabálytár (njt.jog.gov.hu) official ELI. https://njt.jog.gov.hu/eli/urisemak",
        "seeds": ["https://njt.jog.gov.hu/", "https://njt.jog.gov.hu/eli/urisemak"],
        "list_urls": [f"https://njt.jog.gov.hu/eli/TV/{y}" for y in range(1989, 2027)],
        "link_re": r"href=\"(https://njt\.jog\.gov\.hu/eli/TV/\d+/\d+)\"",
    },
    "pt": {
        "country": "Portugal", "lang": "pt", "source_type": "dre",
        "license": "Diário da República (dre.pt / diariodarepublica.pt). Official gazette; check dre.pt legal notice for reuse.",
        "seeds": ["https://diariodarepublica.pt/", "https://dre.pt/", "https://data.dre.pt/"],
        "list_urls": ["https://diariodarepublica.pt/dr/legislacao-consolidada"],
        "link_re": r"href=\"([^\"]*eli[^\"]+)\"",
    },
    "gr": {
        "country": "Greece", "lang": "el", "source_type": "et_gr",
        "license": "National Printing Office (Εθνικό Τυπογραφείο) et.gr official gazette.",
        "seeds": ["https://www.et.gr/", "https://search.et.gr/"],
        "list_urls": ["https://www.et.gr/"],
        "link_re": r"href=\"([^\"]+)\"",
    },
    "bg": {
        "country": "Bulgaria", "lang": "bg", "source_type": "dv_parliament",
        "license": "State Gazette of the Republic of Bulgaria (dv.parliament.bg). Official; open-data slice if published.",
        "seeds": ["https://dv.parliament.bg/", "https://dv.parliament.bg/DVWeb/index.faces"],
        "list_urls": ["https://dv.parliament.bg/"],
        "link_re": r"href=\"([^\"]+)\"",
    },
    "cy": {
        "country": "Cyprus", "lang": "el", "source_type": "legislation_gov_cy",
        "license": "Official Cyprus gazette / legislation.gov.cy if available. cylaw.org is unofficial and is NOT used.",
        "seeds": ["https://www.legislation.gov.cy/", "https://www.cylaw.org/", "http://www.mof.gov.cy/mof/gpo/gpo.nsf/index_gr/index_gr"],
        "list_urls": ["https://www.legislation.gov.cy/"],
        "link_re": r"href=\"([^\"]+)\"",
    },
}

def setup_all():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    for cc in SPECS:
        ensure_dirs(cc)


def harvest(cc: str, spec: dict):
    UA = DEFAULT_UA + f" source={spec['seeds'][0]}"
    notes = []
    discovered = 0
    ok = skip = fail = 0
    done = existing_ids(cc)
    links = []
    # probe seeds
    for seed in spec["seeds"]:
        try:
            r = http_get(seed, ua=UA, sleep=0.4, timeout=(15, 40))
            (ROOT / cc / "raw" / re.sub(r"[^a-z0-9]+","_", seed)[:80]).write_bytes(r.content[:20000] if r.content else b"")
            notes.append(f"seed {seed} -> HTTP {r.status_code} bytes={len(r.content or b'')}")
        except Exception as exc:
            notes.append(f"seed {seed} ERROR {exc}")
    for url in spec.get("list_urls") or []:
        try:
            r = http_get(url, ua=UA, sleep=0.4, timeout=(15, 40))
        except Exception as exc:
            notes.append(f"list {url} ERROR {exc}")
            continue
        if r.status_code != 200:
            notes.append(f"list {url} HTTP {r.status_code}")
            continue
        found = re.findall(spec["link_re"], r.text)
        for href in found:
            if href.startswith("/"):
                from urllib.parse import urljoin
                href = urljoin(url, href)
            if href.startswith("http"):
                links.append(href)
        notes.append(f"list {url} HTTP {r.status_code} links={len(found)}")
    # unique
    seen=set(); uniq=[]
    for l in links:
        if l in seen: continue
        seen.add(l); uniq.append(l)
    # cap per country to avoid storms on HTML-only sites
    MAX = 400
    if len(uniq) > MAX:
        notes.append(f"capped fetch {MAX} of {len(uniq)} discovered links (HTML-only source; polite slice)")
        uniq = uniq[:MAX]
    discovered = len(seen)
    for href in uniq:
        ident = re.sub(r"^https?://", "", href)
        rid = slug_id(cc, ident)
        if rid in done:
            skip += 1; continue
        try:
            r = http_get(href, ua=UA, sleep=0.55, timeout=(15, 50))
        except Exception as exc:
            fail += 1
            log_failure(cc, {"identifier": ident, "source_url": href, "status": "failed", "reason": repr(exc)})
            continue
        if r.status_code != 200 or not r.content:
            fail += 1
            log_failure(cc, {"identifier": ident, "source_url": href, "status": "failed", "reason": f"http_{r.status_code}"})
            continue
        text = html_to_text(r.text)
        if len(text) < 80:
            fail += 1
            log_failure(cc, {"identifier": ident, "source_url": href, "status": "failed", "reason": "empty_or_chrome"})
            continue
        m = re.search(r"<title>([^<]+)</title>", r.text, re.I)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ident
        rec = base_record(cc=cc, country=spec["country"], language=spec["lang"], ident=ident, title=title, text=text,
                          source_url=href, source_type=spec["source_type"], license_text=spec["license"],
                          collector=f"{cc}-gazette-html", eli=href if "/eli/" in href else None,
                          date=None, official_identifier=ident, document_type="statute",
                          law_status="unknown", is_current=None)
        write_instrument(cc, rec); ok += 1
        done.add(rid)
    coverage = "shard"
    if discovered and ok + skip + fail >= min(discovered, MAX) and ok:
        coverage = "catalog-backed incomplete"
    if not uniq:
        notes.append("No bulk/open-data catalog found; official seeds probed. Blocker: no machine-readable full catalog without HTML SPA/login.")
    write_summary(cc, country=spec["country"], source=spec["seeds"][0],
                  source_urls=spec["seeds"], license_text=spec["license"],
                  discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                  coverage=coverage, notes="\n".join(notes), last_run=utcnow())
    log.info("%s disc=%s ok=%s fail=%s", cc, discovered, ok, fail)


def main():
    setup_all()
    targets = sys.argv[1:] or list(SPECS)
    for cc in targets:
        if cc not in SPECS:
            continue
        try:
            harvest(cc, SPECS[cc])
        except Exception:
            log.exception("country %s failed", cc)
            write_summary(cc, country=SPECS[cc]["country"], source=SPECS[cc]["seeds"][0],
                          source_urls=SPECS[cc]["seeds"], license_text=SPECS[cc]["license"],
                          discovered=0, fetched=0, skipped=0, failed=1,
                          coverage="catalog-backed incomplete",
                          notes=traceback.format_exc()[-1500:], last_run=utcnow())

if __name__ == "__main__":
    main()
