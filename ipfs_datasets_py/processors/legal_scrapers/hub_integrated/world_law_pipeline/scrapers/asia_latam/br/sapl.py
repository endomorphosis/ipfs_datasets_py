#!/usr/bin/env python3
"""Brazil: SAPL (Interlegis) câmara municipal systems -> normas jurídicas (municipal laws, decrees, resolutions).

Hosts come from sapl_discover.py (_sapl_hosts.jsonl: sapl.<slug>.<uf>.leg.br seeded from Wikidata P1585 IBGE codes,
robots allow + /api/ answering JSON). Per host: /api/norma/tiponormajuridica/, then /api/norma/normajuridica/?o=-id
(newest first, page_size 100), then the texto_integral PDF per norma (pdftotext). Every request goes through the
es_bop Fetcher: RFC 9309 robots per host, Crawl-delay honoured (most SAPL hosts declare 60 s), identifying UA,
redirect hops re-checked. Hosts are processed in slices (SLICE docs) round-robin by a worker pool, so many hosts
progress in parallel while each host only ever sees one request per crawl-delay.
Place: wd:<QID> of the municipality (IBGE code via Wikidata P1585). Resumable: _state/br_sapl/<host>.json.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, hashlib, json, logging, os, queue, re, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, str(HERE.parent / "es")); sys.path.insert(0, str(HERE.parent))
import schema as S  # noqa: E402
from es_bop import Fetcher, Blocked, pdf_text  # noqa: E402
sys.path.insert(0, str(HERE.parent / "common")); import scanned_pdfs as SCANQ  # noqa: E402,E702  scanned-PDF queue (World Law OCR)

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
OUT, QUAR, STATE = STAGE / "BR", STAGE / "_quarantine" / "BR", STAGE / "_state" / "br_sapl"
log = logging.getLogger("br_sapl")
UF = {"11":"RO","12":"AC","13":"AM","14":"RR","15":"PA","16":"AP","17":"TO","21":"MA","22":"PI","23":"CE","24":"RN","25":"PB","26":"PE","27":"AL","28":"SE","29":"BA","31":"MG","32":"ES","33":"RJ","35":"SP","41":"PR","42":"SC","43":"RS","50":"MS","51":"MT","52":"GO","53":"DF"}


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def https(u):
    return re.sub(r"^http://", "https://", u) if u else u


def st_load(h):
    p = STATE / f"{h}.json"
    return json.loads(p.read_text()) if p.exists() else {"host": h, "done": {}, "listed": False}


def st_save(h, st):
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / f"{h}.json"; t = STATE / f".{h}.json.tmp"; t.write_text(json.dumps(st, ensure_ascii=False)); os.replace(t, p)


def write_atomic(name, rows, pk):
    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / name; tmp = OUT / ("." + name + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush(); os.fsync(fh.fileno())
    v = S.validate_file(tmp, expect_place_key=pk)
    if not v["ok"]:
        raise RuntimeError(f"validate_file {name}: {v['errors'][:3]}")
    os.rename(tmp, final)


def flush(st, rows):
    if not rows:
        return
    pk = S.place_key(st["place_id"], None, "BR")
    good = [r for r in rows if not S.validate_record(r)]
    bad = [r for r in rows if S.validate_record(r)]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    st["batch"] = st.get("batch", 0) + 1
    name = f"sapl-{st['host'].split('.')[1]}-{st['host'].split('.')[2]}-p{st['batch']:04d}-{ts}"
    if bad:
        QUAR.mkdir(parents=True, exist_ok=True)
        with open(QUAR / f"{pk}.{name}.jsonl", "a") as q:
            for r in bad:
                q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
    if good:
        write_atomic(f"{pk}.{name}.jsonl", good, pk)
        st["n_docs"] = st.get("n_docs", 0) + len(good)


def scanq_push(recs):
    """Append no-text-layer PDFs (rows already staged by flush) to the lane scanned-PDF queue; never fatal."""
    if recs:
        try:
            SCANQ.append(recs)
        except Exception as e:  # noqa: BLE001
            log.warning("scanned-PDF queue append failed (%d rows): %s", len(recs), e)
    return []


SKIP_TIPO = re.compile(r"portaria|^ato\b|ato da (mesa|presid)|requerimento|indica[cç][aã]o|mo[cç][aã]o", re.I)


def doc_type(tipo):
    t = (tipo or "").lower()
    return "ordinance" if re.search(r"\blei|emenda|c[oó]digo|lei org", t) else "regulation"


class Host:
    def __init__(self, rec, a):
        self.rec, self.a, self.h = rec, a, rec["host"]
        self.f, self.next_t = None, {}                 # Fetcher (session + robots) only exists during a slice
        self.st = None                      # loaded per slice and dropped afterwards (memory: box is shared)
        self.finished = False

    def load(self):
        self.st = st_load(self.h)
        self.st.update(place_id=f"wd:{self.rec['qid']}", ibge=self.rec["ibge"], name=self.rec["name"])
        self.migrate()

    def api(self, path):
        r = self.f.get(f"https://{self.h}{path}")
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            raise IOError(f"{path}: HTTP {r.status_code} {r.headers.get('content-type')}")
        return r.json()

    def list_all(self):
        st = self.st
        if "tipos" not in st:
            tipos, url = {}, "/api/norma/tiponormajuridica/?page_size=100"
            while url:
                j = self.api(url)
                for t in j.get("results", []):
                    tipos[str(t["id"])] = t.get("descricao") or t.get("__str__")
                nxt = j.get("pagination", {}).get("next_page")
                url = f"/api/norma/tiponormajuridica/?page_size=100&page={nxt}" if nxt else None
            st["tipos"] = tipos; st_save(self.h, st)
        page = st.get("list_page", 1)
        ip = STATE / f"{self.h}.items.jsonl"
        if page == 1 and ip.exists():
            ip.unlink()                                   # our own scratch file (listing restarts from page 1)
        while True:
            j = self.api(f"/api/norma/normajuridica/?o=-id&page_size=100&page={page}")
            with ip.open("a") as fh:
                for n in j.get("results", []):
                    fh.write(json.dumps({k: n.get(k) for k in ("id", "__str__", "texto_integral", "numero", "ano", "data", "data_publicacao",
                                                     "veiculo_publicacao", "ementa", "indexacao", "tipo", "esfera_federacao",
                                                     "data_vigencia", "observacao", "link_detail_backend")}, ensure_ascii=False) + "\n")
            pg = j.get("pagination", {})
            st["total_entries"] = pg.get("total_entries")
            if not pg.get("next_page"):
                break
            page = pg["next_page"]; st["list_page"] = page
            st_save(self.h, st)                           # page N is on disk -> resume at N+1
        st["listed"] = True; st["n_items"] = sum(1 for _ in ip.open()); st_save(self.h, st)
        log.info("%s listed %d normas (%s tipos)", self.h, st["n_items"], len(st["tipos"]))

    def migrate(self):
        st = self.st
        if "items" in st:                                 # legacy state (items inline) -> migrate to disk once
            ip = STATE / f"{self.h}.items.jsonl"; t = STATE / f".{self.h}.items.tmp"
            with t.open("w") as fh:
                for it in st["items"]:
                    fh.write(json.dumps(it, ensure_ascii=False) + "\n")
            os.replace(t, ip); st["n_items"] = len(st.pop("items")); st_save(self.h, st)

    def items(self):
        p = STATE / f"{self.h}.items.jsonl"
        if p.exists():
            with p.open() as fh:
                for l in fh:
                    yield json.loads(l)

    def slice(self):
        self.f = Fetcher(min_interval=self.a.interval)
        self.f.s.headers["Accept-Language"] = "pt-BR,pt;q=0.9,en;q=0.5"
        self.f.next = self.next_t                      # keep per-host crawl-delay timing across slices
        self.load()
        try:
            return self._slice()
        finally:
            self.st = None
            self.next_t = self.f.next
            self.f.s.close(); self.f = None               # memory: no idle sessions/robots for ~850 hosts

    def _slice(self):
        """Process up to SLICE docs; returns True when the host is finished."""
        st = self.st
        if st.get("status") in ("done", "blocked"):
            return True
        try:
            if not st.get("listed"):
                self.list_all()
            buf, n, scan_buf = [], 0, []
            for it in self.items():
                nid = str(it["id"])
                if nid in st["done"]:
                    continue
                if n >= self.a.slice:
                    break
                tipo = st["tipos"].get(str(it.get("tipo")), "")
                if SKIP_TIPO.search(tipo or ""):
                    st["done"][nid] = "skip:" + tipo[:30]; continue
                n += 1
                text, fmt, src, ts = None, "html", f"https://{self.h}/norma/{nid}", "ementa"
                pu = https(it.get("texto_integral"))
                scanned = False
                if pu and self.a.pdf:
                    try:
                        r = self.f.get(pu)
                        if r.status_code == 200 and r.content[:4] == b"%PDF":
                            t = pdf_text(r.content)
                            if len(t) > 100:
                                text, fmt, ts = t, "pdf_text", "pdf"
                            else:
                                scanned = True   # PDF fetched but no usable text layer -> scanned-PDF queue
                    except Blocked as e:
                        st.setdefault("pdf_blocked", 0); st["pdf_blocked"] += 1
                    except Exception as e:  # noqa: BLE001
                        st.setdefault("doc_errors", {})[nid] = f"{type(e).__name__}: {e}"[:160]
                title = it.get("__str__") or ""
                if not text:
                    text = "\n".join(x for x in (title, it.get("ementa"), it.get("indexacao")) if x)
                ufc = UF.get(st["ibge"][:2])
                rec = {"place_id": st["place_id"], "country_code": "BR", "doc_id": f"sapl-{nid}", "source_platform": "br_sapl",
                       "source_url": src, "doc_type": doc_type(tipo), "language": "pt", "html_title": title, "title_native": title,
                       "number": f"{it.get('numero')}/{it.get('ano')}" if it.get("numero") else None,
                       "adopted_date": it.get("data"), "published_date": it.get("data_publicacao"),
                       "effective_date": it.get("data_vigencia"), "consolidated": False, "content_format": fmt, "text": text,
                       "retrieved_at": now_utc(), "place_name": st["name"], "qid": self.rec["qid"], "admin_level": "municipality",
                       "iso_3166_2": f"BR-{ufc}" if ufc else None, "state_code": ufc, "platform": "br_sapl", "platform_place_id": self.h,
                       "ibge_code": st["ibge"], "norma_type": tipo, "summary": it.get("ementa") or None, "pdf_urls": [pu] if pu else None,
                       "publication_vehicle": it.get("veiculo_publicacao") or None, "text_source": ts,
                       "content_complete": ts == "pdf", "source_policy": "robots_allowed_rfc9309",
                       "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
                rec = {k: v for k, v in rec.items() if v not in (None, "") or k == "place_id"}
                for k in ("adopted_date", "published_date", "effective_date"):
                    if k in rec and not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", str(rec[k])):
                        rec.pop(k)
                if scanned and rec.get("place_id"):
                    scan_buf.append(SCANQ.record(rec["doc_id"], S.place_key(rec["place_id"], None, "BR"), "BR", pu, rec["source_policy"]))
                buf.append(rec); st["done"][nid] = 1
                if len(buf) >= self.a.batch:
                    flush(st, buf); buf = []; st_save(self.h, st); scan_buf = scanq_push(scan_buf)
            flush(st, buf); st_save(self.h, st); scan_buf = scanq_push(scan_buf)
            if all(str(it["id"]) in st["done"] for it in self.items()):
                st["status"] = "done"; st["finished"] = now_utc(); st_save(self.h, st)
                log.info("%s done: %d docs", self.h, st.get("n_docs", 0))
                return True
            return False
        except Blocked as e:
            st.update(status="blocked", reason=str(e)); st_save(self.h, st); log.info("%s blocked %s", self.h, e); return True
        except Exception as e:  # noqa: BLE001
            st["errors"] = st.get("errors", 0) + 1; st["last_error"] = f"{type(e).__name__}: {e}"[:300]; st_save(self.h, st)
            log.warning("%s error #%d: %s", self.h, st["errors"], st["last_error"])
            if st["errors"] >= 6:
                st["status"] = "blocked"; st["reason"] = "repeated errors: " + st["last_error"]; st_save(self.h, st); return True
            time.sleep(120)
            return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--slice", type=int, default=25)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--hosts", default="")
    ap.add_argument("--no-pdf", dest="pdf", action="store_false")
    ap.add_argument("--max-hosts", type=int, default=0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    q, seen = queue.Queue(), set()

    def feed():
        recs = []
        for l in open(HERE / "_sapl_hosts.jsonl"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("api_status") == 200 and r.get("count") and r["host"] not in seen:
                if a.hosts and r["host"] not in set(a.hosts.split(",")):
                    continue
                seen.add(r["host"]); recs.append(r)
        recs.sort(key=lambda r: r.get("count") or 0)
        for r in recs:
            q.put(Host(r, a))
        if recs:
            log.info("queued %d new SAPL hosts (normas %d); hosts total %d", len(recs), sum(r.get("count") or 0 for r in recs), len(seen))
    feed()

    def worker():
        while True:
            try:
                h = q.get(timeout=60)
            except queue.Empty:
                continue
            if not h.slice():
                q.put(h)
    th = [threading.Thread(target=worker, daemon=True) for _ in range(a.workers)]
    for t in th:
        t.start()
    while True:                       # re-read the discovery output (it may still be growing)
        time.sleep(1200)
        feed()
    log.info("all hosts finished")


if __name__ == "__main__":
    main()
