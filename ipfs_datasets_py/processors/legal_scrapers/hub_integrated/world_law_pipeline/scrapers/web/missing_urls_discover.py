#!/usr/bin/env python3
"""Official-website discovery for non-US places with no known URL (ipfs_missing_places_20261020.csv, kind nonUS*).
Free sources only: Wikidata P856 (SPARQL, batched, >=2 s between queries), Wikipedia infobox 'website'/'site web'/
'sitio web' (MediaWiki API, 1 req/s), and domain-pattern guesses checked by DNS then one robots-respecting GET of '/'.
Accepts only government TLDs or clearly municipal hosts. Appends one JSON line per place to
staging/web/_discovery/missing_urls_20261020.jsonl (resumable: places already there are skipped).
Africa & Middle East (afme) places/hosts are marked skip_afme; GB/IE skipped."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, socket, sys, time, unicodedata, urllib.parse, glob
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rfc9309 import Robots

CSV = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/ipfs_missing_places_20261020.csv"))
OUTF = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/_discovery/missing_urls_20261020.jsonl"))
UA = ("WorldLawMunicipalBot/0.2 (+https://github.com/endomorphosis/ipfs_datasets_py; research crawler collecting "
      "public municipal law; respects robots.txt and Crawl-delay; 1 request per host every >=2s)")
S = requests.Session(); S.headers["User-Agent"] = UA
VALID_HIST = {"YU", "SU", "AN"}  # historic codes: not ISO 3166-1 current
GOV_SUFFIX = {"BF": ["gov.bf"], "MR": ["gov.mr"], "LR": ["gov.lr"], "UY": ["gub.uy"], "CF": ["gouv.cf"], "CG": ["gouv.cg"],
              "SS": ["gov.ss"], "ZW": ["gov.zw"], "GA": ["gouv.ga"], "UG": ["go.ug"], "KM": ["gouv.km"], "TD": ["gouv.td"],
              "YE": ["gov.ye"], "ZM": ["gov.zm"], "TL": ["gov.tl"], "NR": ["gov.nr"], "AI": ["gov.ai"], "SR": ["gov.sr"],
              "GY": ["gov.gy"], "WS": ["gov.ws"], "BB": ["gov.bb"], "BW": ["gov.bw"], "LS": ["gov.ls"], "DM": ["gov.dm"],
              "SB": ["gov.sb"], "TC": ["gov.tc"], "TV": ["gov.tv"], "SL": ["gov.sl"], "KW": ["gov.kw"], "GD": ["gov.gd"],
              "AW": ["gov.aw"], "VU": ["gov.vu"], "IM": ["gov.im"], "VC": ["gov.vc"], "CW": ["gov.cw"], "ER": ["gov.er"],
              "TJ": ["tj"], "MW": ["gov.mw"], "SZ": ["gov.sz"], "MS": ["gov.ms"], "GW": ["gov.gw"], "SO": ["gov.so"],
              "KI": ["gov.ki"], "VG": ["gov.vg"], "KY": ["gov.ky"], "MH": ["gov.mh"], "SX": ["gov.sx"], "ST": ["gov.st"]}
GOV_RE = re.compile(r"(^|\.)(gov|gouv|gob|gub|go|govt|government|admin|mil)\.[a-z]{2}$|\.gov$|(^|\.)gov\.[a-z]{2}\.[a-z]{2}$")
MUNI_RE = re.compile(r"mairie|commune|municipal|municipio|intendencia|council|city|town|ville|concejo|prefecture|"
                     r"prefeitura|county|baladiya|baladia|wilaya|provincia|departement")
NONOFF_RE = re.compile(r"wikipedia|wikimedia|facebook|twitter|instagram|youtube|blogspot|wordpress\.com|wixsite|"
                       r"globaldatalab|geonames|tripadvisor|google\.|linkedin|citypopulation|mapcarta|weebly|over-blog")

def fold(s):
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())

def slug_variants(name):
    n = re.sub(r"\((.*?)\)", "", name or "")
    n = re.sub(r"\b(District|Department|Departement|Département|Region|Région|County|Commune|Prefecture|Préfecture|"
               r"Province|Municipality|Municipio|Sub-?prefecture|Sous-préfecture|Moughataa|Governorate|Town|City|"
               r"Council|Parish|State|of|de|du|la|le)\b", "", n, flags=re.I)
    base = fold(n)
    return [base] if 3 <= len(base) <= 30 else []

def afme_cover():
    pids, hosts = set(), set()
    for f in glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/*_cfg.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for p in d.get("places", []):
            pids.add(p.get("place_id"))
            h = p.get("host") or urllib.parse.urlsplit(p.get("site") or "").netloc
            if h:
                hosts.add(h.lower().removeprefix("www."))
    for root in ((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/afme"), (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/afme"), (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme")):
        for f in glob.glob(root + "/*/*.jsonl"):
            m = re.match(r"(wd_Q\d+)", Path(f).name)
            if m:
                pids.add(m.group(1).replace("_", ":", 1))
    return pids, hosts

CCTLD = {"GB": "uk"}
def host_ok(url, name, cc):
    h = urllib.parse.urlsplit(url).netloc.lower().split(":")[0].removeprefix("www.")
    if not h or NONOFF_RE.search(h):
        return None, h
    tld = h.rsplit(".", 1)[-1]
    own = tld == CCTLD.get(cc, cc.lower())
    fn = fold(re.sub(r"\b(District|Department|Region|County|Province|Prefecture|Commune|Municipality)\b", "", name or ""))[:6]
    named = len(fn) >= 4 and fn in fold(h)
    if GOV_RE.search(h) and own:
        return ("high" if named else "medium"), h
    if own and (named or MUNI_RE.search(h)):
        return "medium", h
    if tld in ("org", "com", "net", "info") and named and MUNI_RE.search(h):
        return "low", h
    return None, h

def sparql(qids):
    q = ("SELECT ?item ?site ?en ?fr ?es ?pt WHERE { VALUES ?item {" + " ".join("wd:" + x for x in qids) + "} "
         "OPTIONAL {?item wdt:P856 ?site} "
         "OPTIONAL {?en schema:about ?item; schema:isPartOf <https://en.wikipedia.org/>} "
         "OPTIONAL {?fr schema:about ?item; schema:isPartOf <https://fr.wikipedia.org/>} "
         "OPTIONAL {?es schema:about ?item; schema:isPartOf <https://es.wikipedia.org/>} "
         "OPTIONAL {?pt schema:about ?item; schema:isPartOf <https://pt.wikipedia.org/>} }")
    for att in range(4):
        r = S.post("https://query.wikidata.org/sparql", data={"query": q, "format": "json"}, timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(int(r.headers.get("Retry-After", 30)) + 5); continue
        r.raise_for_status()
        out = {}
        for b in r.json()["results"]["bindings"]:
            qid = b["item"]["value"].rsplit("/", 1)[1]
            o = out.setdefault(qid, {"sites": set(), "wiki": {}})
            if "site" in b: o["sites"].add(b["site"]["value"])
            for lg in ("en", "fr", "es", "pt"):
                if lg in b: o["wiki"][lg] = b[lg]["value"]
        return out
    raise RuntimeError("sparql failed")

INFOBOX_RE = re.compile(r"\|\s*(website|site ?web|site internet|sitio ?web|sitio oficial|site oficial|página oficial)\s*=\s*((?:\{\{[^}]*\}\}|[^\n|])*)", re.I)
def wiki_sites(wiki):
    found = []
    for lg, url in wiki.items():
        title = urllib.parse.unquote(url.rsplit("/wiki/", 1)[1])
        time.sleep(1.0)
        try:
            r = S.get(f"https://{lg}.wikipedia.org/w/api.php", params={"action": "query", "prop": "revisions", "rvprop": "content",
                      "rvslots": "main", "titles": title, "format": "json", "formatversion": 2}, timeout=30)
            txt = r.json()["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"][:20000]
        except Exception:
            continue
        for _, v in INFOBOX_RE.findall(txt):
            v = re.sub(r"\{\{\s*(url|official website|site officiel|lien web)\s*\|\s*", "", v.strip(), flags=re.I)
            m = re.search(r"https?://[^\s\]}|]+|(?:www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+\.[a-z]{2,}", v, re.I)
            if m:
                u = m.group(0)
                found.append((u if u.startswith("http") else "http://" + u, f"wikipedia_{lg}_infobox"))
    return found

_robots = {}
def live_check(url, name):
    """DNS + robots (RFC 9309: 5xx/unreachable => no fetch) + one GET of '/'. Returns (ok, final_url, note)."""
    p = urllib.parse.urlsplit(url); host = p.netloc.split(":")[0]
    try:
        socket.getaddrinfo(host, 443)
    except Exception:
        return False, None, "dns_fail"
    for scheme in ("https", "http"):
        try:
            r = S.get(f"{scheme}://{host}/robots.txt", timeout=(5, 15))
            rb = "allow" if 400 <= r.status_code < 500 else ("deny" if r.status_code >= 500 else Robots(r.text))
        except Exception as e:
            rb = "unreachable"; continue
        if rb == "deny":
            return False, f"{scheme}://{host}/", "robots_5xx"
        if isinstance(rb, Robots) and not rb.can_fetch("WorldLawMunicipalBot", f"{scheme}://{host}/"):
            return True, f"{scheme}://{host}/", "robots_disallow_root(no_live_check)"
        time.sleep(2)
        try:
            r = S.get(f"{scheme}://{host}/", timeout=(5, 20))
            body = r.text[:200000]
        except Exception:
            continue
        if r.status_code < 400:
            hit = fold(name)[:6] in fold(body) if len(fold(name)) >= 4 else False
            return True, r.url, f"http_{r.status_code}" + ("_name_on_page" if hit else "")
        return False, r.url, f"http_{r.status_code}"
    return False, None, "unreachable"

def main():
    done = set()
    if OUTF.exists():
        done = {json.loads(l)["place_id"] for l in OUTF.open() if l.strip()}
    rows = [r for r in csv.DictReader(CSV.open(encoding="utf-8")) if r["kind"].startswith("nonUS") and r["qid"]]
    apids, ahosts = afme_cover()
    todo = [r for r in rows if "wd:" + r["qid"] not in done]
    print(f"rows={len(rows)} done={len(done)} todo={len(todo)} afme_pids={len(apids)} afme_hosts={len(ahosts)}", flush=True)
    fo = OUTF.open("a", encoding="utf-8")
    def emit(rec):
        fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
    for i in range(0, len(todo), 120):
        chunk = todo[i:i + 120]
        wd = sparql([r["qid"] for r in chunk]); time.sleep(3)
        for r in chunk:
            pid, cc, name = "wd:" + r["qid"], r["country_code"], r["name"]
            rec = {"place_id": pid, "qid": r["qid"], "country_code": cc, "name": name, "admin_level": r["admin_level"],
                   "population": r["population"], "url": None, "confidence": None, "source": None, "candidates": [],
                   "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            if cc in ("GB", "IE"):
                rec["status"] = "skip_gb_ie"; emit(rec); continue
            if cc in VALID_HIST:
                rec["status"] = "skip_historic_cc"; emit(rec); continue
            if pid in apids:
                rec["status"] = "skip_afme_place"; emit(rec); continue
            w = wd.get(r["qid"], {"sites": set(), "wiki": {}})
            cands = [(u, "wikidata_P856") for u in sorted(w["sites"])]
            if not cands:
                cands += wiki_sites(w["wiki"])
            if not cands:
                for s in slug_variants(name):
                    for suf in GOV_SUFFIX.get(cc, []):
                        cands.append((f"https://{s}.{suf}/", "domain_guess"))
                        cands.append((f"https://www.{s}.{suf}/", "domain_guess"))
            best = None
            for u, src in cands:
                conf, h = host_ok(u, name, cc)
                c = {"url": u, "source": src, "host": h, "official": conf}
                if conf and h in ahosts:
                    c["note"] = "afme_host"; rec["candidates"].append(c); rec["status"] = "skip_afme_host"; best = "afme"; break
                if not conf or conf == "low":
                    c["note"] = "rejected_not_official" if not conf else "low_unverified_nongov"; rec["candidates"].append(c); continue
                if src == "domain_guess":
                    ok, fu, note = live_check(u, name); c["live"] = note
                    if not ok or "name_on_page" not in note:
                        rec["candidates"].append(c); continue
                    conf = "medium"; u = fu or u
                else:
                    ok, fu, note = live_check(u, name); c["live"] = note
                    if not ok and note == "dns_fail":
                        rec["candidates"].append(c); continue
                rec["candidates"].append(c)
                if best is None:
                    best = (u, conf, src)
                    if src != "domain_guess":
                        break
            if best == "afme":
                pass
            elif best:
                rec["url"], rec["confidence"], rec["source"] = best; rec["status"] = "found"
            else:
                rec["status"] = "not_found"
            emit(rec)
        print(f"{min(i+120,len(todo))}/{len(todo)}", flush=True)
    print("DISCOVERY_DONE", flush=True)

if __name__ == "__main__":
    main()
