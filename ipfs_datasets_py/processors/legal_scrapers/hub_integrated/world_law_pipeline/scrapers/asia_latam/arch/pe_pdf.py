#!/usr/bin/env python3
"""Peru gob.pe: backfill full text of staged docs whose PDF (cdn.www.gob.pe, CDN-blocked from the box) was missing.

  pe_pdf.py [--max-fetch N] [--cc-crawls 3] [--loop SECS]

Input: finished files staging/asia_latam/PE/*.jsonl (+ processed/asia_latam/PE/*.jsonl), records with
content_complete=false and pdf_urls (read-only; never modified). For each, list archive captures of the PDF
(Common Crawl exact URL in the newest --cc-crawls crawls, then Wayback prefix uploads/document/file/<id>/), fetch the
best (CC first, then Wayback) through pipeline/archive.ArchiveFetcher, pdftotext it, and emit an updated record with the
SAME place_id/doc_id in a NEW batch file <place_key>.archivepdf<UTC>pNNNN.jsonl (merge by doc_id: newest file wins).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702

import argparse, glob, json, logging, re, sys, time
from collections import defaultdict
from urllib.parse import unquote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arch_common import wb_deferred, WBDeferred  # noqa: E402,F401
from arch_common import STAGE, STOP, ArchiveError, ArchiveFetcher, CheckedFetcher, Capture, State, pdf_text, provenance_fields  # noqa: E402

JOB = "PE_gobpe_pdf"
log = logging.getLogger(JOB)
FID = re.compile(r"cdn\.www\.gob\.pe/(uploads/document/file/(\d+)/)([^?#]+)")


def inputs():
    files = glob_jsonl(str(STAGE / "PE" / "*.jsonl")) + glob_jsonl((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/asia_latam/PE/*.jsonl"))
    seen = set()
    for f in files:
        if ".archivepdf" in f:
            continue
        try:
            fh = open_text(f)
        except FileNotFoundError:  # moved to processed/ (or gzipped) meanwhile
            f2 = locate(f)
            if not f2:
                continue
            fh = open_text(f2)
        with fh:
            for line in fh:
                if '"content_complete": false' not in line or "cdn.www.gob.pe" not in line:
                    continue
                r = json.loads(line)
                k = f"{r['place_id']}|{r['doc_id']}"
                if k in seen or not r.get("pdf_urls"):
                    continue
                seen.add(k)
                yield k, r


class Job:
    def __init__(self, a):
        self.a = a
        self.st = State(JOB, "PE", batch_prefix="archivepdf", chunk=a.chunk)
        self.fx = CheckedFetcher(cc_crawls=max(a.cc_crawls, 1))

    def listing(self, pfx):
        """Wayback (and optionally CC) captures under cdn.www.gob.pe/uploads/document/file/<pfx>; cached by the fetcher."""
        caps = []
        url = "cdn.www.gob.pe/uploads/document/file/" + pfx
        if self.a.cc_crawls > 0:
            caps += self.fx.cc_captures(url, "prefix", crawls=self.fx.cc_crawls()[: self.a.cc_crawls])
        try:
            caps += self.fx.wb_captures(url, "prefix", collapse="urlkey", max_rows=200000,
                                        filters=["original:.*\\.(pdf|PDF).*"])
        except ArchiveError as e:
            log.info("wb cdx failed %s: %s", url, e)
            self.st.stats["wb_cdx_failed"] += 1
        self.st.stats["listings"] += 1
        idx = {}
        for c in caps:
            if c.status not in (200, None):
                continue
            m = FID.search(c.original_url)
            if m:
                idx.setdefault((m.group(2), unquote(m.group(3)).lower()), []).append(c)
        return idx

    def captures(self, url, idx):
        m = FID.search(url)
        if not m:
            return []
        return idx.get((m.group(2), unquote(m.group(3)).lower()), [])

    def one(self, key, r, idx):
        parts, provs, complete, reasons = [], [], True, []
        got = 0
        for u in r["pdf_urls"][: self.a.max_pdfs]:
            caps = self.captures(u, idx)
            if caps:
                self.st.stats["pdf_with_captures"] += 1
            try:
                doc = self.fx.fetch_best(caps, max_tries=3) if caps else None
            except ArchiveError as e:
                log.info("fetch error %s: %s", u, e)
                doc = None
            if doc is None or doc.body[:5] != b"%PDF-":
                self.st.stats["pdf_not_archived"] += 1
                complete = False
                reasons.append("pdf_not_archived:" + u.split("?")[0].rsplit("/", 1)[-1])
                continue
            t = pdf_text(doc.body)
            if len(t) < 50:
                self.st.stats["pdf_no_text_layer"] += 1
                complete = False
                reasons.append("pdf_no_text_layer")
                continue
            got += 1
            parts.append(t)
            provs.append(doc)
            complete = complete and doc.content_complete
            if not doc.content_complete:
                reasons.append(doc.incomplete_reason or "truncated")
        if not got:
            return None, "no_archived_pdf"
        out = {k: v for k, v in r.items() if k not in ("html", "html_title", "text", "content_sha256")}
        head = "\n".join(x for x in (r.get("title_native"), r.get("summary")) if x)
        out["text"] = (head + "\n\n" if head else "") + "\n\n".join(parts)
        out["content_format"] = "pdf_text"
        out["text_source"] = "archived_pdf"
        out["page_url"] = r["source_url"]
        out.update(provenance_fields(provs[0]))
        out["source_url"] = provs[0].original_url
        out["content_complete"] = complete
        out["extra_metadata"]["archive"]["content_complete"] = complete
        if len(provs) > 1:
            out["extra_metadata"]["archive_all"] = [p.provenance() for p in provs]
        if reasons:
            out["incomplete_reason"] = ";".join(reasons)[:300]
        out["retrieved_at"] = provs[0].fetched_at
        return out, "ok"

    def run(self):
        n = 0
        todo = [(k, r) for k, r in inputs() if k not in self.st.done]
        # group docs by listing prefix: 4-digit id prefix when >=2 docs share it, else the doc's own file dir
        groups = defaultdict(list)
        for k, r in todo:
            ids = [FID.search(u).group(2) for u in r["pdf_urls"][: self.a.max_pdfs] if FID.search(u)]
            if not ids:
                self.st.mark(k, "no_cdn_pdf_url")
                continue
            groups[ids[0][:4]].append((k, r))
        plan = []
        for p4, items in groups.items():
            if len(items) >= 2:
                plan.append((p4, items))
            else:
                k, r = items[0]
                plan.append((FID.search(r["pdf_urls"][0]).group(2) + "/", items))
        plan.sort(key=lambda x: -len(x[1]))
        self.st.stats["inputs_pending"] = len(todo)
        self.st.stats["listing_plan"] = len(plan)
        self.st.save(self.fx)
        log.info("pending incomplete docs: %d in %d listings (done before: %d)", len(todo), len(plan), len(self.st.done))
        for pfx, items in plan:
            if STOP["flag"] or (self.a.max_fetch and n >= self.a.max_fetch):
                break
            idx = self.listing(pfx)
            for k, r in items:
                extra = []  # other pdfs of the doc outside this prefix
                for u in r["pdf_urls"][1: self.a.max_pdfs]:
                    m = FID.search(u)
                    if m and not m.group(2).startswith(pfx.rstrip("/")) and self.a.extra_pdf_listing:
                        extra.append(m.group(2) + "/")
                for e in extra:
                    idx.update(self.listing(e))
                n += 1
                try:
                    rec, why = self.one(k, r, idx)
                except Exception as e:
                    log.exception("failed %s", k)
                    rec, why = None, f"error:{type(e).__name__}"
                if rec is None:
                    self.st.stats[why] += 1
                    self.st.mark(k, why)
                else:
                    self.st.add(k, rec)
                self.st.maybe_flush(self.a.flush_secs)
            self.st.save(self.fx)
            log.info("listing %s: docs=%d done=%d staged=%d %s", pfx, len(items), n, self.st.stats["staged"],
                     dict(self.fx.stats))
        self.st.flush()
        self.st.save(self.fx, final=not STOP["flag"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--cc-crawls", type=int, default=0)
    ap.add_argument("--max-pdfs", type=int, default=4)
    ap.add_argument("--chunk", type=int, default=100)
    ap.add_argument("--flush-secs", type=int, default=600)
    ap.add_argument("--extra-pdf-listing", action="store_true")
    ap.add_argument("--loop", type=int, default=0, help="re-scan for new incomplete docs every N s")
    a = ap.parse_args()
    while True:
        Job(a).run()
        if not a.loop or STOP["flag"]:
            break
        for _ in range(a.loop):
            if STOP["flag"]:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())
