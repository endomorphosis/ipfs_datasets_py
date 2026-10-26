#!/usr/bin/env python3
"""Indonesia BPK (peraturan.bpk.go.id) kabupaten/kota regulations from web archives -> staging/asia_latam/ID/.

  id_bpk.py [--max-fetch N] [--rediscover] [--cc-crawls 8] [--no-pdf]

The live site is network-blocked from the box, so every page comes from Common Crawl (first) or Wayback via
pipeline/archive.ArchiveFetcher (box-wide limiter). Discovery = CC + Wayback prefix listings of /Details/ (the same
Wayback query the national lane runs, so it is served from the shared CDX cache) and /Download/ (PDF index).
Province-level acts (pergub/perda-prov) are left to the national lane (ID_bpk_regional); national acts to ID_national.
Each Details page gives structured metadata (Judul, T.E.U., Nomor, Tanggal Penetapan/Pengundangan/Berlaku, Status) and a
/Download/<id>/<file>.pdf link; when that PDF is archived its text is appended (content_format=pdf_text), otherwise the
metadata page is staged with content_complete=false, incomplete_reason=landing_page_only:pdf_not_archived.
Place: T.E.U./Lokasi/title/slug -> Kemendagri code (Wikidata P2588) -> wd:Q from global_municipalities_candidate.csv.
Unmatched docs -> staging/asia_latam/_unmatched_id.csv.
"""
from __future__ import annotations

import argparse, json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arch_common import wb_deferred, WBDeferred, listing_failed  # noqa: E402,F401
from arch_common import (STAGE, STOP, ArchiveError, ArchiveFetcher, CheckedFetcher, Capture, State, append_csv, clean_text,  # noqa: E402
                    html_soup_text, is_pdf, pdf_text, provenance_fields)
from id_places import IdPlaces, extract_kind_name  # noqa: E402

JOB = "ID_bpk_kabkota"
log = logging.getLogger(JOB)
INC = re.compile(r"(?i)peraturan\.bpk\.go\.id(?::\d+)?/Details/(\d+)/((?:perda|perbup|perwali|kepbup|kepwal|perdes|qanun|"
                 r"perkab|perkot|perdasus|perdais)[\w-]*)$")
EXC = re.compile(r"(?i)/Details/\d+/[a-z]+-prov\b")
DL = re.compile(r"(?i)/(?:Download|Read)/(\d+)/")
UNMATCHED = STAGE / "_unmatched_id.csv"
MONTHS = {m: i + 1 for i, m in enumerate("januari februari maret april mei juni juli agustus september oktober november "
                                          "desember".split())}
MONTHS.update({"agustus": 8, "nopember": 11, "pebruari": 2})
FIELDS = ["Judul", "T.E.U.", "Nomor", "Bentuk", "Bentuk Singkat", "Tahun", "Tempat Penetapan", "Tanggal Penetapan",
          "Tanggal Pengundangan", "Tanggal Berlaku", "Sumber", "Subjek", "Status", "Bahasa", "Lokasi", "Bidang"]


def id_date(s):
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+((?:19|20)\d\d)", s or "")
    if not m:
        return None
    mo = MONTHS.get(m.group(2).lower())
    if not mo:
        return None
    return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(1)):02d}"


def parse_meta(text):
    """BPK Details page text (one label per line, value on the next lines) -> dict."""
    k = text.find("\nMETADATA")
    lines = (text[k:] if k >= 0 else text).split("\n")
    meta, i = {}, 0
    labels = set(FIELDS)
    while i < len(lines):
        l = lines[i].strip()
        if l in labels and l not in meta and i + 1 < len(lines):
            j, vals = i + 1, []
            while j < len(lines) and lines[j].strip() not in labels and len(vals) < 4:
                v = lines[j].strip()
                if v in ("UJI MATERI", "FILE-FILE", "Bidang") or v.startswith("Halaman ini"):
                    break
                vals.append(v)
                j += 1
                if l not in ("Subjek", "Bidang"):
                    break
            meta[l] = " ; ".join(vals)
            i = j
        else:
            i += 1
    return meta


class Job:
    def __init__(self, a):
        self.a = a
        self.st = State(JOB, "ID", batch_prefix="archive", chunk=a.chunk)
        self.fx = CheckedFetcher(cc_crawls=a.cc_crawls)
        self.P = IdPlaces()
        self.dl = {}  # download id -> [capture dicts]

    # ------------------------------------------------------------ discovery
    def discover(self):
        cand = {}
        stats = {}
        for url, flt in (("peraturan.bpk.go.id/Details/", ["mimetype:text/html"]),):
            caps = []
            if not self.a.no_cc:
                caps += self.fx.cc_captures(url, "prefix")
            ncc = len(caps)
            try:
                caps += self.fx.wb_captures(url, "prefix", collapse="timestamp:4", filters=flt, max_rows=600000)
            except ArchiveError as e:
                log.warning("wayback listing failed: %s", e)
                listing_failed(e, "details")
            stats["details_captures_cc"], stats["details_captures_wb"] = ncc, len(caps) - ncc
            log.info("discover %s cc=%d wb=%d", url, ncc, len(caps) - ncc)
            for c in caps:
                if c.status not in (200, None):
                    continue
                m = INC.search(c.original_url)
                if not m or EXC.search(c.original_url):
                    continue
                cand.setdefault(m.group(1), []).append(c)
        out = []
        for k, caps in cand.items():
            caps.sort(key=lambda c: (c.timestamp, c.source == "commoncrawl"), reverse=True)
            cc = [c for c in caps if c.source == "commoncrawl"][:3]
            wb = [c for c in caps if c.source == "wayback"][:3]
            out.append({"key": k, "newest": caps[0].timestamp, "caps": [c.to_dict() for c in cc + wb]})
        out.sort(key=lambda r: r["newest"], reverse=True)
        tmp = self.st.dir / "candidates.jsonl.tmp"
        with tmp.open("w") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, self.st.dir / "candidates.jsonl")
        stats["candidates"] = len(out)
        stats["candidates_cc"] = sum(1 for r in out if any(c["source"] == "commoncrawl" for c in r["caps"]))
        (self.st.dir / "discovery.json").write_text(json.dumps(stats, indent=1))
        log.info("candidates=%d", len(out))
        return out

    def pdf_index(self):
        p = self.st.dir / "pdf_index.jsonl"
        if p.exists() and not self.a.rediscover:
            for l in p.open():
                r = json.loads(l)
                self.dl[r["id"]] = r["caps"]
            return
        caps = []
        if not self.a.no_cc:
            caps += self.fx.cc_captures("peraturan.bpk.go.id/Download/", "prefix")
        try:
            caps += self.fx.wb_captures("peraturan.bpk.go.id/Download/", "prefix", collapse="urlkey", max_rows=2000000)
        except ArchiveError as e:
            log.warning("wayback download listing failed: %s", e)
            listing_failed(e, "downloads")
        for c in caps:
            if c.status not in (200, None):
                continue
            m = DL.search(c.original_url)
            if m:
                self.dl.setdefault(m.group(1), []).append(c.to_dict())
        tmp = p.with_suffix(".tmp")
        with tmp.open("w") as f:
            for k, v in self.dl.items():
                v.sort(key=lambda c: (c["source"] == "commoncrawl", c["timestamp"]), reverse=True)
                self.dl[k] = v[:4]
                f.write(json.dumps({"id": k, "caps": v[:4]}) + "\n")
        os.replace(tmp, p)
        log.info("pdf index: %d download ids (%d captures)", len(self.dl), len(caps))

    # ------------------------------------------------------------ per doc
    def follow_pdf(self, links, base):
        """All archived PDFs linked from the Details page (main act + lampiran), in page order, max --max-pdfs."""
        seen, docs, texts = [], [], []
        for href in links:
            m = DL.search(href or "")
            if not m or m.group(1) in seen:
                continue
            seen.append(m.group(1))
            caps = self.dl.get(m.group(1))
            if not caps and self.a.pdf_lookup:
                try:
                    caps = [c.to_dict() for c in self.fx.wb_captures(urljoin(base, href), "exact", limit=-3)]
                except ArchiveError as e:
                    if wb_deferred(self.fx, None, e):
                        raise WBDeferred(str(e))
                    caps = []
            if not caps or len(docs) >= self.a.max_pdfs:
                continue
            try:
                pdoc = self.fx.fetch_best([Capture(**c) for c in caps], max_tries=3)
            except ArchiveError as e:
                pdoc = None
                if wb_deferred(self.fx, None, e):
                    raise WBDeferred(str(e))
            if pdoc is None and wb_deferred(self.fx, None):
                raise WBDeferred("pdf wayback-only")
            if pdoc is not None and pdoc.body[:5] == b"%PDF-":
                t = pdf_text(pdoc.body)
                if len(t) > 200:
                    docs.append(pdoc)
                    texts.append(t)
                else:
                    self.st.stats["pdf_no_text"] += 1
        return docs, texts, seen

    def build(self, r, doc):
        if is_pdf(doc):
            return None, "details_is_pdf"
        soup, page_title, text, links = html_soup_text(doc.text())
        del soup
        meta = parse_meta(text)
        title = meta.get("Judul") or page_title
        kind, name, how = extract_kind_name(doc.original_url, text, title)
        teu = meta.get("T.E.U.", "")
        if re.search(r"\bProvinsi\b", teu) and not re.search(r"\b(Kabupaten|Kota)\b", teu):
            return None, "province_level"
        if not kind:
            return None, "unmatched:no_place_text"
        row, code, why = self.P.resolve(kind, name)
        if row is None and how != "slug":  # second chance: slug
            k2, n2, _ = extract_kind_name(doc.original_url, "", "")
            if k2:
                row, code, why2 = self.P.resolve(k2, n2)
                why = why if row is None else None
        if row is None:
            append_csv(UNMATCHED, ["doc_key", "url", "kind", "name", "how", "teu", "reason", "logged_at"],
                       [r["key"], doc.original_url, kind, name, how, teu, why, time.strftime("%Y-%m-%d %H:%M")])
            return None, "unmatched:" + (why or "?").split(":")[0]
        # body: metadata block (+ archived PDF full text)
        head = "\n".join(f"{k}: {meta[k]}" for k in FIELDS if meta.get(k))
        pdocs, ptxts, seen = [], [], []
        if not self.a.no_pdf:
            pdocs, ptxts, seen = self.follow_pdf(links, doc.original_url)
        missing = len(seen) - len(pdocs)
        if ptxts:
            body, fmt = (title + "\n\n" + head + "\n\n" + "\n\n".join(ptxts)), "pdf_text"
            self.st.stats["with_pdf_text"] += 1
            for p in pdocs:
                self.st.stats["pdf_src_" + p.archive_source] += 1
            complete = doc.content_complete and all(p.content_complete for p in pdocs) and missing == 0
            reason = ";".join(filter(None, [p.incomplete_reason for p in pdocs] +
                                     ([f"pdf_not_archived:{missing}_of_{len(seen)}"] if missing else []))) or None
        else:
            body, fmt = (title + "\n\n" + head), "html"
            complete, reason = False, ("landing_page_only:pdf_not_archived" if seen else "landing_page_only:no_pdf_link")
            self.st.stats["landing_only"] += 1
        pdoc = pdocs[0] if pdocs else None
        if len(body) < 120:
            return None, "too_short"
        status = (meta.get("Status") or "").lower()
        rec = {
            "place_id": row["place_id"], "country_code": "ID", "doc_id": f"id_bpk:{r['key']}",
            "source_platform": "id_bpk_jdih", "source_url": doc.original_url, "doc_type": "regulation",
            "language": "id", "title_native": title[:1000] or r["key"], "consolidated": False,
            "content_format": fmt, "text": clean_text(body), "retrieved_at": doc.fetched_at,
            "place_name": row["place_name"], "qid": row["qid"], "admin_level": row["admin_level"] or "municipality",
            "platform": "id_bpk_jdih", "platform_place_id": code,
            "kemendagri_code": code, "regional_kind": kind, "place_match": how,
            "bentuk": meta.get("Bentuk"), "teu": teu or None,
        }
        if meta.get("Nomor"):
            rec["number"] = meta["Nomor"] + (f"/{meta['Tahun']}" if meta.get("Tahun") else "")
        for k, f in (("adopted_date", "Tanggal Penetapan"), ("published_date", "Tanggal Pengundangan"),
                     ("effective_date", "Tanggal Berlaku")):
            d = id_date(meta.get(f))
            if d:
                rec[k] = d
        if "adopted_date" not in rec and re.fullmatch(r"(19|20)\d\d", meta.get("Tahun", "")):
            rec["adopted_date"] = meta["Tahun"]
        if status:
            rec["in_force"] = True if status.startswith("berlaku") else (False if ("tidak" in status or "cabut" in status)
                                                                         else None)
        rec.update(provenance_fields(doc))  # Details page capture = the doc's archive provenance
        rec["content_complete"] = complete
        rec["extra_metadata"]["archive"]["content_complete"] = complete
        if reason:
            rec["incomplete_reason"] = reason
        if pdocs:
            pp = [p.provenance() for p in pdocs]
            rec["pdf_archive"] = pp
            rec["extra_metadata"]["pdf_archive"] = pp
        return rec, "ok"

    def run(self):
        cp = self.st.dir / "candidates.jsonl"
        cands = self.discover() if (self.a.rediscover or not cp.exists()) else [json.loads(l) for l in cp.open()]
        if not self.a.no_pdf:
            self.pdf_index()
        self.st.stats["candidates"] = len(cands)
        self.st.save(self.fx, pdf_index_ids=len(self.dl))
        if self.a.discover_only:
            return
        n = 0
        for r in cands:
            if STOP["flag"] or (self.a.max_fetch and n >= self.a.max_fetch):
                break
            if r["key"] in self.st.done:
                continue
            if self.a.shard and int(r["key"]) % self.a.shard[1] != self.a.shard[0]:
                continue
            n += 1
            if r["key"] in self.st.deferred:
                continue
            exc = None
            try:
                doc = self.fx.fetch_best([Capture(**c) for c in r["caps"]], max_tries=3)
            except ArchiveError as e:
                doc, exc = None, e
                log.info("fetch error %s: %s", r["key"], e)
            if wb_deferred(self.fx, doc, exc):
                self.st.defer(r["key"]); continue
            if doc is None:
                self.st.stats["no_good_capture"] += 1
                self.st.mark(r["key"], "no_good_capture")
                continue
            self.st.stats["details_src_" + doc.archive_source] += 1
            try:
                rec, why = self.build(r, doc)
            except WBDeferred:          # an attached PDF was only on Wayback while the breaker is open
                self.st.defer(r["key"], "wayback_breaker_pdf"); continue
            except Exception as e:  # keep going
                log.exception("build failed %s", r["key"])
                rec, why = None, f"build_error:{type(e).__name__}"
            if rec is None:
                self.st.stats[why] += 1
                self.st.mark(r["key"], why)
                continue
            self.st.add(r["key"], rec)
            self.st.maybe_flush(self.a.flush_secs)
            if n % 25 == 0:
                self.st.save(self.fx, pdf_index_ids=len(self.dl))
                log.info("progress fetched=%d staged=%d %s", n, self.st.stats["staged"], dict(self.fx.stats))
        self.st.flush()
        self.st.save(self.fx, final=not STOP["flag"], pdf_index_ids=len(self.dl))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--cc-crawls", type=int, default=8)
    ap.add_argument("--chunk", type=int, default=200)
    ap.add_argument("--flush-secs", type=int, default=900)
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--no-cc", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--max-pdfs", type=int, default=4)
    ap.add_argument("--pdf-lookup", action="store_true", help="Wayback exact lookup for PDFs missing from the index")
    ap.add_argument("--shard", type=lambda s: tuple(int(x) for x in s.split("/")), default=None, help="i/n")
    Job(ap.parse_args()).run()


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())
