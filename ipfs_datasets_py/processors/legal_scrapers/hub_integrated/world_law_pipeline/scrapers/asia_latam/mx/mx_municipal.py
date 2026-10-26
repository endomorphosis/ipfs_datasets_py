#!/usr/bin/env python3
"""Mexico: municipal reglamentos / bandos from official municipal government websites (ordenjuridico.gob.mx is
unreachable). Generic crawler: common/council_sites.py (RFC 9309 robots per host, identifying UA, >=interval s/host).
Places: candidate-list MX municipalities (wd:Q..., INEGI code via Wikidata P3801) + the 16 CDMX alcaldias (P3801 09xxx).
Site: Wikidata P856 first, else candidate-list source_url (web archives skipped). Priority: population desc.
Unreachable/robots-unreachable sites -> appended to _archive_queue_asia_latam.csv (candidate_network_block) for the
archive worker; robots-disallowed -> excluded_robots (never archived)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, csv, logging, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common")); sys.path.insert(0, str(HERE.parent))
from council_sites import CouncilCrawler, STAGE, regdom  # noqa: E402

STRONG = re.compile(r"reglament|normativ|marco[\s\-_]*(jur[ií]dico|normativo|legal)|bando|gaceta[\s\-_]*municipal|"
                    r"ordenamientos|leyes[\s\-_]*y[\s\-_]*reglamentos|normateca", re.I)
TOPIC = re.compile(r"transparencia|cabildo|ayuntamiento|gobierno|legislaci|marco|documentos|publicaciones|gaceta", re.I)
DOC = re.compile(r"reglament|bando|c[oó]digo[\s_\-]+municipal|ordenamiento|ordenanza", re.I)
EXCL = re.compile(r"proyecto|iniciativa|consulta|convocatoria|licitaci|acta[\s_\-]+de|minuta|formato|solicitud|"
                  r"aviso[\s_\-]+de[\s_\-]+privacidad|orden[\s_\-]+del[\s_\-]+d[ií]a|informe|tabulador|"
                  # federal / state law (and their reglamentos) published on municipal sites is not municipal law
                  r"\bley(es)?\b|federal|federaci[oó]n|constituci[oó]n|estatal|del[\s_\-]+estado[\s_\-]+de|nacional|^acuerdo", re.I)
SEEDS = ["/reglamentos", "/normatividad", "/marco-normativo", "/marco-juridico", "/reglamentacion", "/gaceta-municipal",
         "/normatividad-municipal", "/transparencia/marco-normativo", "/reglamentos-municipales", "/gaceta"]
INEGI_ISO = dict(zip([f"{i:02d}" for i in range(1, 33)],
                     "AGU BCN BCS CAM COA COL CHP CHH CMX DUR GUA GRO HID JAL MEX MIC MOR NAY NLE OAX PUE QUE ROO SLP SIN SON TAB "
                     "TAM TLA VER YUC ZAC".split()))
SKIP_SITE = re.compile(r"webarchive|archive\.org|wikipedia|facebook\.com|twitter\.com|ordenjuridico", re.I)
AQ = STAGE / "_archive_queue_asia_latam.csv"
# Site sanity: the official-site host must contain a distinctive word of the municipio name (seed lists had e.g.
# Culiacan -> badiraguato.gob.mx). Explicit fixes / known-good exceptions below.
SITE_FIX = {"Q2485095": "https://www.culiacan.gob.mx/"}
SITE_OK = {"Q14906254", "Q2279198", "Q2994111", "Q1709166", "Q2065515", "Q958153"}  # aao, cancun, villahermosa, opb, ldm, dh
STOPW = {"de", "del", "la", "las", "los", "el", "y", "san", "santa", "santo", "municipio", "heroica", "ciudad", "villa", "general"}


def _ascii(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def site_ok(q, name, site):
    if q in SITE_OK or q in SITE_FIX:
        return True
    host = _ascii(urlparse(site).hostname or "").replace("-", "")
    words = [w for w in re.split(r"[^a-z0-9]+", _ascii(name)) if len(w) >= 4 and w not in STOPW]
    return any(w in host for w in words) or _ascii(name).replace(" ", "") in host
_aq_lock = threading.Lock()


def popf(x):
    try:
        return float(x)
    except ValueError:
        return 0.0


def places():
    wd = {}
    for r in csv.DictReader(open(HERE / "wd_P3801_sites.csv")):
        q = r["item"].rsplit("/", 1)[1]
        e = wd.setdefault(q, {"code": r["code"], "sites": [], "label": r["label"]})
        if r["site"] and r["site"] not in e["sites"]:
            e["sites"].append(r["site"])
    out, seen = [], set()
    for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))):
        if r["country_code"] != "MX" or r["admin_level"] != "municipality":
            continue
        q = r["qid"]; w = wd.get(q, {})
        nm = r["place_name"].replace(" Municipality", "")
        sites = [s for s in w.get("sites", []) if not SKIP_SITE.search(s)]
        if r["source_url"] and not SKIP_SITE.search(r["source_url"]):
            sites.append(r["source_url"])
        sites = [SITE_FIX[q]] if q in SITE_FIX else [s for s in sites if site_ok(q, nm, s)]
        code = w.get("code", "")
        out.append({"qid": q, "place_id": r["place_id"], "name": r["place_name"].replace(" Municipality", ""),
                    "site": sites[0] if sites else None, "iso_3166_2": f"MX-{INEGI_ISO[code[:2]]}" if code[:2] in INEGI_ISO else None,
                    "inegi": code, "pop": popf(r["population"])})
        seen.add(q)
    for q, w in wd.items():                       # CDMX alcaldias (not in the candidate list)
        if w["code"].startswith("09") and q not in seen:
            sites = [s for s in w["sites"] if not SKIP_SITE.search(s) and site_ok(q, w["label"] or "", s)]
            out.append({"qid": q, "place_id": f"wd:{q}", "name": w["label"] or q, "site": sites[0] if sites else None,
                        "iso_3166_2": "MX-CMX", "inegi": w["code"], "pop": 1e6})
    out.sort(key=lambda p: -p["pop"])
    return out


def queue_archive(p, st):
    reason = (st.get("reason") or "")[:200].replace("\n", " ")
    robots = "robots_disallow" in reason or "disallow" in reason.lower()
    row = ["MX", f"mx_municipal:{p['name']}", urlparse(p["site"]).netloc, p["place_id"], reason,
           "excluded_robots" if robots else "candidate_network_block", "official municipal site; reglamentos"]
    with _aq_lock:
        have = {l.split(",")[2] + "|" + l.split(",")[3] for l in open(AQ, encoding="utf8") if l.startswith("MX,mx_municipal")}
        if row[2] + "|" + row[3] in have:
            return
        with open(AQ, "a", newline="", encoding="utf8") as fh:
            csv.writer(fh).writerow(row)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--top", type=int, default=150, help="largest N municipios (+ CDMX alcaldias)")
    ap.add_argument("--only", default="")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--retry-failed", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = CouncilCrawler("mx_municipal", "MX", TOPIC, DOC, EXCL, SEEDS, doc_type="regulation", lang="es",
                       platform="mx_municipal_site", strong_re=STRONG, max_pages=60, max_docs=400)
    c.accept_lang = "es-MX,es;q=0.9"
    _disc = c.discover

    def discover_same_site(f, home):          # only documents hosted on the municipio's own registrable domain
        docs, pages = _disc(f, home)
        dom = regdom(urlparse(home).hostname)
        return {u: l for u, l in docs.items() if regdom(urlparse(u).hostname) == dom}, pages
    c.discover = discover_same_site
    P = places()
    if a.only:
        P = [p for p in P if p["qid"] in a.only.split(",") or a.only.lower() in p["name"].lower()]
    else:
        P = P[: a.top]
    logging.info("MX places: %d (with site %d)", len(P), sum(1 for p in P if p["site"]))

    def one(p):
        st = c.run_place(p, a)
        if st.get("status") == "blocked" and p["site"]:
            queue_archive(p, st)
        return st
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, P))
    logging.info("finished: %s", {s: sum(1 for r in res if r.get("status") == s) for s in ("done", "blocked", "no_site", "error")})
