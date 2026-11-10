#!/usr/bin/env python3
"""Mexico: state official gazettes (periódicos oficiales) that do not connect from the box (TLS EOF / connection
refused / HTTP 403), from web archives -> municipal reglamentos / bandos in staging/asia_latam/MX/.

  mx_gaz_arch.py [--states tamaulipas,...] [--max-fetch N] [--rediscover] [--no-cc]

Same machinery as mx_arch.py (arch_common.CheckedFetcher: shared pipeline/archive limiter + box-wide Wayback breaker,
ARCHIVE_LANE=asia_latam; Common Crawl first, then Wayback). Discovery: CC + Wayback prefix listing per gazette host,
PDF/DOC(X) only. Per document: text from the archived copy; kept only if the head names a municipal reglamento /
bando / código municipal (mx/mx_gazettes TARGET/EXCL criteria) issued by a municipio of that state (INEGI via
Wikidata P3801 -> wd:Q). Records carry archive provenance (archive_source, archive_timestamp = copy date, archive_url,
original_url), source_policy network_blocked_archive_fallback. Exit 75 when Wayback deferrals happened.
"""
from __future__ import annotations

import argparse, hashlib, json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "mx"))
from arch_common import wb_deferred  # noqa: E402
from arch_common import STAGE, STOP, ArchiveError, CheckedFetcher, Capture, State, append_csv, pdf_text, provenance_fields  # noqa: E402
from common_docx import docx_text  # noqa: E402
from mx_arch import Places, STATES  # noqa: E402
from mx_gazettes import TARGET, EXCL  # noqa: E402

JOB = "MX_gazettes_archive"
log = logging.getLogger(JOB)
# key -> (INEGI state code, host). Hosts that failed live from the box on 2026-11-02 (see report).
GAZ = {"tamaulipas": ("28", "po.tamaulipas.gob.mx"), "michoacan": ("16", "periodicooficial.michoacan.gob.mx"),
       "zacatecas": ("32", "periodico.zacatecas.gob.mx"), "quintanaroo": ("23", "po.segob.qroo.gob.mx"),
       "oaxaca": ("20", "periodicooficial.oaxaca.gob.mx"), "tlaxcala": ("29", "periodico.tlaxcala.gob.mx"),
       "coahuila": ("05", "periodico.sfpcoahuila.gob.mx"), "edomex": ("15", "legislacion.edomex.gob.mx"),
       "veracruz": ("30", "editoraveracruz.gob.mx"), "guerrero": ("12", "periodicooficial.guerrero.gob.mx"),
       "sinaloa": ("25", "iipo.sinaloa.gob.mx"), "sonora": ("26", "boletinoficial.sonora.gob.mx"),
       # Baja California: listing (periodicooficial.ebajacalifornia.gob.mx) is live, but every PDF is served by the CDN
       # host below, which fails TLS from the box (2026-11-02) -> archived copies only
       "bajacalifornia": ("02", "wsextbc.ebajacalifornia.gob.mx")}
DOC_EXT = re.compile(r"(?i)\.(pdf|docx?)(?:$|[?&#])")   # also in the query (CDN ...&nombreArchivo=X.pdf&...)
MUNI_RX = re.compile(r"(?i)\b(?:municipio|ayuntamiento(?: constitucional)?|h\. ayuntamiento)\s+(?:de|del)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\. ]{2,50}?)(?=[,\.;:\n]|\s+(?:del estado|estado|en|para|que|y)\b)")


class Job:
    def __init__(self, a):
        self.a = a
        self.st = State(JOB, "MX", batch_prefix="archive_gaz", chunk=100)
        self.fx = CheckedFetcher(cc_crawls=4)
        self.P = Places()
        self.G = {k: v for k, v in GAZ.items() if not a.states or k in a.states.split(",")}

    def discover(self):
        out = []
        for g, (st, host) in self.G.items():
            caps = []
            if not self.a.no_cc:
                caps += self.fx.cc_captures(host + "/", "prefix")
            try:
                caps += self.fx.wb_captures(host + "/", "prefix", collapse="urlkey", max_rows=200000)
            except Exception as e:  # noqa: BLE001  breaker open / deferred: keep CC hits, rediscover next run
                import arch_common as _ac
                _ac.listing_failed(e, "wb:" + host)
                log.warning("%s: wayback listing deferred (%s) -> CC only this run", g, str(e)[:120])
            cand = {}
            for c in caps:
                if c.status not in (200, None) or not DOC_EXT.search(unquote(c.original_url)):
                    continue
                p = urlparse(c.original_url)
                q = re.sub(r"(?i)&?descargar=[^&]*", "", unquote(p.query)) if not DOC_EXT.search(p.path) else ""
                cand.setdefault(f"{g}:{p.netloc.lower()}{unquote(p.path)}" + (f"?{q}" if q else ""), []).append(c)
            for k, cs in sorted(cand.items()):
                cs.sort(key=lambda c: (c.source == "commoncrawl", c.timestamp), reverse=True)
                # filename hint first: municipal-looking names are fetched before the rest
                hint = 0 if re.search(r"(?i)regla|bando|municip|ayunt", k) else 1
                out.append({"key": k, "g": g, "st": st, "hint": hint, "caps": [c.to_dict() for c in cs[:3]]})
            log.info("%s: %d captures -> %d documents", g, len(caps), len(cand))
        with (self.st.dir / "candidates.jsonl.tmp").open("w") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(self.st.dir / "candidates.jsonl.tmp", self.st.dir / "candidates.jsonl")
        (self.st.dir / "discovery.json").write_text(json.dumps({g: sum(1 for r in out if r["g"] == g) for g in self.G}))
        return out

    def build(self, r, doc):
        if doc.body[:5] == b"%PDF-":
            text, fmt = pdf_text(doc.body), "pdf_text"
        elif doc.body[:2] == b"PK":
            text, fmt = docx_text(doc.body), "docx_text"
        else:
            return None, "unsupported_format"
        if len(text.strip()) < 300:
            from common import scanned_pdfs as SP  # noqa
            return None, "no_text"
        head = text[:6000]
        lines = [l.strip() for l in head.split("\n") if l.strip()]
        title = next((l for l in lines if TARGET.search(l) and not EXCL.search(l)), None)
        if not title:
            return None, "not_target"
        row = code = None
        for m in MUNI_RX.finditer(head):
            row, code = self.P.resolve(r["st"], m.group(1))
            if row:
                break
        if not row:
            append_csv(STAGE / "_unmatched_mx.csv", ["key", "url", "state", "first_muni_mention", "at"],
                       [r["key"], doc.original_url, r["st"], (MUNI_RX.search(head).group(1) if MUNI_RX.search(head) else ""),
                        time.strftime("%Y-%m-%d %H:%M")])
            return None, "unmatched_municipio"
        iso = STATES[r["st"]][0]
        rec = {"place_id": row["place_id"], "country_code": "MX", "doc_id": "mx_gaz_arch:" + r["key"],
               "source_platform": f"mx_gazette_{r['g']}", "source_url": doc.original_url,
               "doc_type": "regulation", "language": "es", "html_title": title[:500], "title_native": title[:500],
               "consolidated": False, "in_force": None, "content_format": fmt, "text": text, "retrieved_at": doc.fetched_at,
               "platform": f"mx_gazette_{r['g']}", "place_name": row["place_name"], "qid": row["qid"],
               "admin_level": row["admin_level"] or "municipality", "iso_3166_2": iso, "inegi_code": code, "gazette": r["g"],
               "source_policy": "network_blocked_archive_fallback", "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
        rec.update(provenance_fields(doc))
        return {k: v for k, v in rec.items() if v not in (None, "") or k == "in_force"}, "ok"

    def run(self):
        cp = self.st.dir / "candidates.jsonl"
        cands = self.discover() if (self.a.rediscover or not cp.exists()) else [json.loads(l) for l in cp.open()]
        cands = [r for r in cands if r["g"] in self.G]
        cands.sort(key=lambda r: r["hint"])
        self.st.stats["candidates"] = len(cands)
        self.st.save(self.fx)
        n = 0
        for r in cands:
            if STOP["flag"] or (self.a.max_fetch and n >= self.a.max_fetch):
                break
            if r["key"] in self.st.done or r["key"] in self.st.deferred:
                continue
            n += 1
            exc = None
            try:
                doc = self.fx.fetch_best([Capture(**c) for c in r["caps"]], max_tries=2)
            except ArchiveError as e:
                doc, exc = None, e
            if wb_deferred(self.fx, doc, exc):
                self.st.defer(r["key"]); continue
            if doc is None:
                self.st.stats["no_good_capture"] += 1; self.st.mark(r["key"], "no_good_capture"); continue
            try:
                rec, why = self.build(r, doc)
            except Exception as e:  # noqa: BLE001
                log.exception("build %s", r["key"]); rec, why = None, f"error:{type(e).__name__}"
            if rec is None:
                self.st.stats[why] += 1; self.st.mark(r["key"], why); continue
            self.st.add(r["key"], rec)
            self.st.maybe_flush(1800)
            if n % 25 == 0:
                self.st.save(self.fx)
        self.st.flush()
        self.st.save(self.fx, final=not STOP["flag"] and not self.a.max_fetch)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", default="")
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--no-cc", action="store_true")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Job(ap.parse_args()).run()


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())
