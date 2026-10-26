#!/usr/bin/env python3
"""Council / municipality websites that are network-blocked from the box (connect timeout, TLS failure, HTTP 403/202
firewall), from web archives: AU QLD local laws (_state/au_qld_ll) and ZA municipal by-laws (_state/za_bylaws).

  sites_arch.py [--targets au,za] [--max-fetch N] [--rediscover]

Only places whose live-crawler state is status=blocked (robots_unreachable: ConnectTimeout/SSLError = network-level)
or status=error with 'home page HTTP 403/202' are in scope; robots *disallow* is never in scope.
Discovery per site: Wayback (and CC when cached) domain listing restricted to PDF/Word documents whose URL matches the
live crawler's document regex (local law / by-law), minus its exclusion regex (draft, agenda, ...). Each document is
fetched from the archive (CC first, then Wayback), converted with pdftotext, staged per place with the same doc_id
scheme as the live crawler (<bot>-sha1(url)[:16]).
"""
from __future__ import annotations

import argparse, hashlib, json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from arch_common import wb_deferred, WBDeferred, listing_failed  # noqa: E402,F401
from arch_common import STAGE, STOP, ArchiveError, ArchiveFetcher, CheckedFetcher, Capture, State, pdf_text, provenance_fields  # noqa: E402

JOB = "SITES_archive"
log = logging.getLogger(JOB)
TARGETS = {
    "au": dict(bot="au_qld_ll", cc="AU", platform="au_council_site", lang="en",
               doc=re.compile(r"(?i)local[\s\-_%20]*laws?|subordinate|\bS?LL[\s\-_]*\d"),
               excl=re.compile(r"(?i)proposed|draft|consultation|submission|agenda|minutes|public[\s\-_]*notice|gazette[\s\-_]*notice|form\b|application")),
    "za": dict(bot="za_bylaws", cc="ZA", platform="za_municipal_site", lang="en",
               doc=re.compile(r"(?i)by[\s\-_%20]*laws?|bylaws?|verordening"),
               excl=re.compile(r"(?i)draft|proposed|comment|consultation|notice[\s\-_]*of|invitation|agenda|minutes|tender|vacanc|application[\s\-_]*form")),
}


def blocked_places(t):
    sp = TARGETS[t]
    if t == "au":
        from au.qld_local_laws import places
    else:
        from za.za_bylaws import places
    P = {p["qid"]: p for p in places()}
    out = []
    for f in sorted((STAGE / "_state" / sp["bot"]).glob("Q*.json")):
        d = json.loads(f.read_text())
        reason = str(d.get("reason") or "")
        net = d.get("status") == "blocked" and re.search(r"robots_unreachable: (ConnectTimeout|ConnectionError|SSLError|ReadTimeout)", reason)
        fw = d.get("status") == "error" and re.search(r"home page HTTP (403|202)", reason)
        if (net or fw) and d["qid"] in P and P[d["qid"]].get("site"):
            p = dict(P[d["qid"]]); p["block_reason"] = reason
            out.append(p)
    return out


def host_of(site):
    site = site.split(",")[0].strip()
    h = urlparse(site if "://" in site else "http://" + site).hostname or ""
    return h[4:] if h.startswith("www.") else h


class Job:
    def __init__(self, a):
        self.a = a
        self.fx = CheckedFetcher(cc_crawls=4)
        self.states = {t: State(f"{JOB}_{t}", TARGETS[t]["cc"], batch_prefix="archive", chunk=100) for t in a.targets}

    def discover(self, t):
        sp, st = TARGETS[t], self.states[t]
        cand, per = [], {}
        for p in blocked_places(t):
            host = host_of(p["site"])
            caps = []
            if self.a.cc:
                caps += self.fx.cc_captures(host, "domain", filters=["mime:application/pdf"])
            try:
                caps += self.fx.wb_captures(host, "domain", collapse="urlkey", max_rows=200000,
                                            filters=["mimetype:application/(pdf|msword|vnd.openxmlformats.*)"])
            except ArchiveError as e:
                log.warning("listing failed %s: %s", host, e)
                listing_failed(e, host)
                per[p["qid"]] = {"host": host, "error": str(e)[:100]}
                continue
            docs = {}
            for c in caps:
                if c.status not in (200, None):
                    continue
                path = unquote(urlparse(c.original_url).path)
                if not sp["doc"].search(path) or sp["excl"].search(path):
                    continue
                k = re.sub(r"^www\d?\.", "", (urlparse(c.original_url).hostname or "").lower()) + path.lower()
                docs.setdefault(k, []).append(c)
            per[p["qid"]] = {"host": host, "name": p["name"], "captures": len(caps), "docs": len(docs),
                             "block_reason": p["block_reason"]}
            log.info("%s %s %s: captures=%d law docs=%d", t, p["qid"], host, len(caps), len(docs))
            for k, cs in docs.items():
                cs.sort(key=lambda c: (c.source == "commoncrawl", c.timestamp), reverse=True)
                cand.append({"key": p["qid"] + "|" + k, "place": p, "caps": [c.to_dict() for c in cs[:4]]})
        with (st.dir / "candidates.jsonl.tmp").open("w") as f:
            for r in cand:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(st.dir / "candidates.jsonl.tmp", st.dir / "candidates.jsonl")
        (st.dir / "discovery.json").write_text(json.dumps(per, indent=1, ensure_ascii=False))
        return cand

    def build(self, t, r, doc):
        sp, p = TARGETS[t], r["place"]
        if doc.body[:5] == b"%PDF-":
            text, fmt = pdf_text(doc.body), "pdf_text"
        elif doc.body[:2] == b"PK":
            from common_docx import docx_text  # optional
            text, fmt = docx_text(doc.body), "docx_text"
        else:
            return None, "not_pdf"
        if len(text) < 200:
            return None, "no_text"
        title = Path(unquote(urlparse(doc.original_url).path)).stem.replace("_", " ").replace("-", " ").strip()
        u = doc.original_url
        rec = {"place_id": p["place_id"], "country_code": sp["cc"], "doc_id": f"{sp['bot']}-" + hashlib.sha1(u.encode()).hexdigest()[:16],
               "source_platform": sp["platform"], "source_url": u, "doc_type": "ordinance", "language": sp["lang"],
               "html_title": title, "title_native": title, "consolidated": False, "content_format": fmt, "text": text,
               "retrieved_at": doc.fetched_at, "place_name": p["name"], "qid": p["qid"], "admin_level": "municipality",
               "iso_3166_2": p.get("iso_3166_2"), "platform": sp["platform"], "platform_place_id": p["site"],
               "text_source": fmt, "source_policy": "network_blocked_archive_fallback", "block_reason": p["block_reason"],
               "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
        rec.update(provenance_fields(doc))
        return {k: v for k, v in rec.items() if v not in (None, "")}, "ok"

    def run(self):
        for t in self.a.targets:
            st = self.states[t]
            cp = st.dir / "candidates.jsonl"
            cands = self.discover(t) if (self.a.rediscover or not cp.exists()) else [json.loads(l) for l in cp.open()]
            st.stats["candidates"] = len(cands)
            st.save(self.fx)
            n = 0
            for r in cands:
                if STOP["flag"] or (self.a.max_fetch and n >= self.a.max_fetch):
                    break
                if r["key"] in st.done:
                    continue
                n += 1
                if r["key"] in st.deferred:
                    continue
                exc = None
                try:
                    doc = self.fx.fetch_best([Capture(**c) for c in r["caps"]], max_tries=3)
                except ArchiveError as e:
                    doc, exc = None, e
                if wb_deferred(self.fx, doc, exc):
                    st.defer(r["key"]); continue
                if doc is None:
                    st.stats["no_good_capture"] += 1; st.mark(r["key"], "no_good_capture"); continue
                try:
                    rec, why = self.build(t, r, doc)
                except Exception as e:
                    log.exception("build %s", r["key"]); rec, why = None, f"error:{type(e).__name__}"
                if rec is None:
                    st.stats[why] += 1; st.mark(r["key"], why); continue
                st.add(r["key"], rec)
                st.maybe_flush(900)
                if n % 20 == 0:
                    st.save(self.fx)
            st.flush()
            st.save(self.fx, final=not STOP["flag"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=lambda s: s.split(","), default=["au", "za"])
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--cc", action="store_true")
    Job(ap.parse_args()).run()


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())
