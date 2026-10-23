#!/usr/bin/env python3
"""Peru: municipal ordinances (and decretos de alcaldía) from gob.pe 'Normas y documentos legales'
(https://www.gob.pe/institucion/<slug>/normas-legales/<id>-<slug>).

Polite & robots-conformant (RFC 9309 matcher, identifying UA, >=1 s/host):
 * gob.pe robots.txt disallows '?sheet=' (listing pagination), so listings are NOT paginated. Norma URLs come from
   the sitemaps advertised in robots.txt (fetch_sitemaps.py -> _sitemaps/*.normas.txt).
 * Per institution: /normas-legales/tipos (type facets + institution name) and the FIRST page of each ordinance-like
   type list (allowed) -> exact ids + slug 'signatures' (digits->N) of that institution's ordinances. Sitemap URLs are
   then fetched only when the id is known, the slug names an ordinance/decree, or the slug matches a learned signature.
   Every fetched page is verified (document type read from the page) before staging.
Mapping: institution name (+slug vs official site) -> district place_id (pe_places.PEResolver); provincial
municipalities -> capital district (match flagged). Resumable: staging/asia_latam/_state/pe/<slug>.json.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, collections, csv, glob, hashlib, json, logging, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup
HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, str(HERE.parent / "es")); sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import schema as S  # noqa: E402
from es_bop import Fetcher, Blocked, pdf_text  # noqa: E402  (RFC 9309 robots + crawl-delay + manual redirects)
from pe_places import PEResolver  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
OUT, UNM, QUAR, STATE = STAGE / "PE", STAGE / "_unmatched" / "PE", STAGE / "_quarantine" / "PE", STAGE / "_state" / "pe"
B = "https://www.gob.pe"
log = logging.getLogger("pe_gobpe")
TYPE_KEEP = re.compile(r"ordenanza|decreto[- ]de[- ]alcald", re.I)
SLUG_HINT = re.compile(r"ordenanza|decreto-de-alcaldia|(^|-)om(-|$)|(^|-)ord(-|$)|(^|-)da(-|$)", re.I)
PDF_OK = {"on": True, "n403": 0}
MESES = {m: i + 1 for i, m in enumerate("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sig(tail):
    return re.sub(r"\d+", "N", tail.lower())


class LazyURLs:
    """Per-institution URL lists from _sitemaps/by_slug/<slug>.tsv (split once from the sitemaps) so the 5.4M URLs
    are not held in memory (the box is shared)."""
    def __init__(self):
        self.d = HERE / "_sitemaps" / "by_slug"
        self.n = json.loads((self.d / "_index.json").read_text())

    def __iter__(self):
        return iter(self.n)

    def __len__(self):
        return len(self.n)

    def __getitem__(self, slug):
        return self.get(slug, [])

    def values(self):
        return [[None] * c for c in self.n.values()]

    def get(self, slug, default=None):
        p = self.d / f"{slug}.tsv"
        if not p.exists():
            return default
        out = []
        for l in open(p):
            nid, tail = l.rstrip("\n").split("\t", 1)
            out.append((nid, tail, "https://www.gob.pe/institucion/%s/normas-legales/%s%s" % (slug, nid, ("-" + tail) if tail else "")))
        return out


def load_urls():
    return LazyURLs()


def st_load(slug):
    p = STATE / f"{slug}.json"
    return json.loads(p.read_text()) if p.exists() else {"slug": slug, "done": {}}


def st_save(slug, st):
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / f"{slug}.json"; t = p.with_suffix(".tmp"); t.write_text(json.dumps(st, ensure_ascii=False)); os.replace(t, p)


def write_atomic(d, name, rows, pk=None):
    d.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)?\.jsonl", name):
        raise RuntimeError(f"bad staging filename {name!r}")
    final = d / name
    if final.exists():
        raise RuntimeError(f"refusing to overwrite {final}")
    tmp = final.with_name("." + final.name + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush(); os.fsync(fh.fileno())
    if pk:
        v = S.validate_file(tmp, expect_place_key=pk)
        if not v["ok"]:
            raise RuntimeError(f"validate_file {final.name}: {v['errors'][:3]}")
    os.rename(tmp, final)


def parse_date(s):
    m = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", s or "")
    if m and m.group(2).lower() in MESES:
        return f"{int(m.group(3)):04d}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


def institution(f, slug):
    r = f.get(f"{B}/institucion/{slug}/normas-legales/tipos")
    if r.status_code != 200:
        return None, []
    soup = BeautifulSoup(r.content, "lxml")
    h1 = soup.select_one("h1 a[href]") or soup.find("h1")
    name = h1.get_text(" ", strip=True) if h1 else ""
    types = sorted(set(re.findall(r'href="(/institucion/%s/normas-legales/tipos/(\d+)-([^"?]+))"' % re.escape(slug), r.text)))
    return name, [{"url": B + t[0], "id": t[1], "slug": t[2]} for t in types]


def parse_norma(html, url):
    soup = BeautifulSoup(html, "lxml")
    h2 = soup.select_one(".institution-document__header h2") or soup.find("h2")
    title = h2.get_text(" ", strip=True) if h2 else ""
    ps = [p.get_text(" ", strip=True) for p in soup.select(".institution-document__header p")]
    desc_el = soup.select_one(".description.rule-content > div") or soup.select_one(".description")
    desc = desc_el.get_text(" ", strip=True) if desc_el else ""
    pdfs = list(dict.fromkeys(a["href"] for a in soup.select(".institution-document__files a[href]") if "/uploads/document/file/" in a["href"]))
    typ = re.split(r"\s+N\.?\s*[°º]", title)[0].strip() if title else ""
    main = soup.select_one("article") or soup.select_one(".institution-document") or soup.body
    return {"title": title, "number_line": ps[0] if ps else None, "date": parse_date(" ".join(ps)), "description": desc,
            "pdfs": pdfs, "type": typ, "html": str(main) if main else None}


def run(a):
    f, res = Fetcher(min_interval=a.interval), PEResolver()
    urls = load_urls()
    slugs = sorted(urls, key=lambda s: (not re.match(r"(muni|md|mp|mun)", s), -urls.n[s]))
    if a.slugs:
        slugs = [s for s in a.slugs.split(",")]
    log.info("sitemap norma URLs: %d institutions, %d urls", len(urls), sum(urls.n.values()))
    unm_csv = STAGE / "_unmatched_pe.csv"
    for slug in slugs:
        rf = STATE / "_RESTART"
        if rf.exists():                       # graceful restart point: between institutions, nothing buffered
            rf.unlink(); log.info("_RESTART seen -> exit 75 (supervisor relaunches with current code)"); sys.exit(75)
        st = st_load(slug)
        if st.get("status") in ("done", "not_municipal", "blocked") and not a.max_docs:
            continue
        try:
            if "name" not in st:
                name, types = institution(f, slug)
                st.update(name=name, types=[t["slug"] for t in types])
                place = res.resolve(name or "", slug) if name else {"match": "no_name"}
                st["place"] = place
                if place.get("match") == "not_municipal" or not name:
                    st["status"] = "not_municipal"; st_save(slug, st); continue
                ids, sigs = set(), collections.Counter()
                for t in types:
                    if TYPE_KEEP.search(t["slug"]):
                        r = f.get(t["url"])
                        for nid, tail in re.findall(r'href="/institucion/%s/normas-legales/(\d+)-?([^"/?]*)"' % re.escape(slug), r.text):
                            ids.add(nid); sigs[sig(tail)] += 1
                st.update(type_ids=sorted(ids), sigs=dict(sigs), status="listed")
                st_save(slug, st)
                log.info("%s | %s | %s | %s | types=%s ord-like=%d sigs=%s", slug, name, place.get("match"), place.get("place_name"),
                         len(types), len(ids), dict(sigs.most_common(4)))
            place = st["place"]
            if not any(TYPE_KEEP.search(t) for t in st.get("types", [])):
                st["status"] = "done"; st["reason"] = "no ordinance-like type"; st_save(slug, st); continue
            ids, sigs = set(st.get("type_ids", [])), set(st.get("sigs", {}))
            cand = [(nid, tail, u) for nid, tail, u in urls.get(slug, [])
                    if nid not in st["done"] and (nid in ids or SLUG_HINT.search(tail) or (sig(tail) in sigs and sig(tail) not in ("", "N")))]
            cand.sort(key=lambda x: -int(x[0]))                     # newest ids first
            pk = S.place_key(place["place_id"], None, "PE") if place.get("place_id") else None
            buf, n_new, fetched = [], 0, 0
            sst = st.setdefault("sig_stats", {})
            for nid, tail, u in cand:
                if a.max_docs and n_new >= a.max_docs:
                    break
                sg = sig(tail)
                known = nid in ids or bool(SLUG_HINT.search(tail))
                if not known:
                    fz, hz = sst.get(sg, [0, 0])
                    if fz >= 40 and hz / fz < 0.08:          # signature proved unproductive for this institution
                        continue
                try:
                    r = f.get(u); fetched += 1
                    if r.status_code != 200:
                        st["done"][nid] = f"http {r.status_code}"; continue
                    d = parse_norma(r.text, u)
                    hit = bool(TYPE_KEEP.search(d["type"] or d["title"]))
                    if not known:
                        z = sst.setdefault(sg, [0, 0]); z[0] += 1; z[1] += int(hit)
                    if not hit:
                        st["done"][nid] = "skip:" + (d["type"] or "?")[:40]; continue
                    text, fmt, src = None, "html", u
                    for pu in (d["pdfs"][:3] if PDF_OK["on"] else []):
                        rp = f.get(pu)
                        if rp.status_code == 403:
                            PDF_OK["n403"] += 1
                            if PDF_OK["n403"] >= 5:
                                PDF_OK["on"] = False
                                log.warning("cdn.www.gob.pe answers 403 (CDN forbid) -> PDF download disabled for this run; staging page metadata/summary only")
                            continue
                        PDF_OK["n403"] = 0
                        if rp.status_code == 200 and rp.content[:4] == b"%PDF":
                            t = pdf_text(rp.content)
                            if len(t) > 200:
                                text, fmt, src = t, "pdf_text", pu; break
                    text_source = "pdf" if text else "page_description"
                    if not text:
                        text = "\n".join(x for x in (d["title"], d["number_line"], d["description"]) if x)
                    dt = "ordinance" if re.search(r"ordenanza", d["type"] or d["title"], re.I) else "regulation"
                    rec = {"place_id": place.get("place_id"), "country_code": "PE", "doc_id": f"gobpe-{nid}", "source_platform": "pe_gobpe_normas",
                           "source_url": u, "doc_type": dt, "language": "es", "html_title": d["title"], "title_native": d["title"],
                           "number": d["number_line"], "published_date": d["date"], "consolidated": False, "content_format": fmt,
                           "text": text, "html": d["html"], "retrieved_at": now_utc(), "place_name": place.get("place_name"), "qid": place.get("qid"),
                           "admin_level": "municipality", "platform": "pe_gobpe_normas", "platform_place_id": slug,
                           "issuer_name": st.get("name"), "norma_type": d["type"], "summary": d["description"] or None,
                           "pdf_urls": d["pdfs"] or None, "text_source": text_source, "content_complete": text_source == "pdf", "match": place.get("match"),
                           "municipality_kind": place.get("municipality_kind"), "province_name": place.get("province_name"),
                           "department_name": place.get("department_name"), "source_policy": "robots_allowed_rfc9309",
                           "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
                    rec = {k: v for k, v in rec.items() if v is not None or k == "place_id"}
                    buf.append(rec); st["done"][nid] = 1; n_new += 1
                except Blocked as e:
                    st["done"][nid] = "robots"; log.info("robots skip %s %s", u, e)
                except Exception as e:  # noqa: BLE001
                    st.setdefault("doc_errors", {})[nid] = f"{type(e).__name__}: {e}"[:200]
                if len(buf) >= a.batch:
                    flush(st, slug, pk, buf, unm_csv); buf = []
                if fetched % 50 == 0:
                    st_save(slug, st)
            flush(st, slug, pk, buf, unm_csv)
            st["status"] = "partial" if a.max_docs else "done"; st["candidates"] = len(cand); st["finished"] = now_utc()
            st_save(slug, st)
            log.info("%s done: candidates=%d new_docs=%d total=%d match=%s", slug, len(cand), n_new, st.get("n_docs", 0), place.get("match"))
        except Blocked as e:
            st.update(status="blocked", reason=str(e)); st_save(slug, st); log.info("%s blocked %s", slug, e)
        except Exception as e:  # noqa: BLE001
            st.update(status="error", reason=f"{type(e).__name__}: {e}"[:300]); st_save(slug, st); log.exception("%s failed", slug)


def safe_token(slug):
    """Filename-safe batch token: percent-decode, ASCII-fold (ñ->n), keep [A-Za-z0-9_-] only."""
    import unicodedata, urllib.parse
    t = unicodedata.normalize("NFKD", urllib.parse.unquote(slug)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9_-]+", "-", t).strip("-")
    return t or ("h" + hashlib.sha1(slug.encode()).hexdigest()[:10])


def flush(st, slug, pk, rows, unm_csv):
    if not rows:
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    st["batch"] = st.get("batch", 0) + 1
    name = f"{safe_token(slug)}-p{st['batch']:04d}-{ts}"
    if pk:
        good = [r for r in rows if not S.validate_record(r)]
        bad = [r for r in rows if S.validate_record(r)]
        if bad:
            QUAR.mkdir(parents=True, exist_ok=True)
            with open(QUAR / f"{pk}.{name}.jsonl", "a") as q:
                for r in bad:
                    q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
        if good:
            write_atomic(OUT, f"{pk}.gobpe-{name}.jsonl", good, pk)
            st["n_docs"] = st.get("n_docs", 0) + len(good)
    else:
        write_atomic(UNM, f"{name}.jsonl", rows)
        with open(unm_csv, "a", newline="") as fh:
            w = csv.writer(fh)
            for r in rows:
                w.writerow([slug, st.get("name"), r["doc_id"], st["place"].get("match"), r["source_url"]])
        st["n_unmatched"] = st.get("n_unmatched", 0) + len(rows)
    st_save(slug, st)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs", default="")
    ap.add_argument("--max-docs", type=int, default=0)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--interval", type=float, default=1.0)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(ap.parse_args())
