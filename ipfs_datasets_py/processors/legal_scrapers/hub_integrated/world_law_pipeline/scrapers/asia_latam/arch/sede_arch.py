#!/usr/bin/env python3
"""Spain esPublico Gestiona sedes (*.sedelectronica.es, 1,534 hosts whose live robots.txt disallows the
"Ordenanzas y reglamentos" board) from web archives ONLY -> staging/asia_latam/ES/, source_policy=archived_robots_disallowed
(Benjamin via coordinator 2026-10-10). Nothing is ever fetched live.

  sede_arch.py [--max-hosts N] [--rediscover] [--per-host]

Discovery (2 Wayback domain listings, cached): every archived capture of the ordinances board
(/board/97521486-f59b-11de-b600-00237da12c6a...) and every archived /preview-document/<uuid>/ on *.sedelectronica.es.
Hosts with an archived board go first, ordered by population. Per host: the newest archived board snapshots are parsed
(same parser as the live es_sede.py) -> listed ordinances; each listed doc whose preview-document is archived is
fetched from the archive (PDF -> pdftotext). doc_id = preview uuid (same as es_sede.py).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse, csv, hashlib, json, logging, os, re, sys, time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arch_common import wb_deferred, WBDeferred, listing_failed  # noqa: E402,F401
from arch_common import STAGE, STOP, ArchiveError, CheckedFetcher, Capture, State, pdf_text, provenance_fields, html_soup_text  # noqa
from sede_parse import parse_sede_documents  # noqa: E402

JOB = "ES_sede_archive"
log = logging.getLogger(JOB)
BOARD_ID = "97521486-f59b-11de-b600-00237da12c6a"
CAND = (_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv")
UUID = re.compile(r"/preview-document/([0-9a-fA-F-]{36})")


def seeds():
    pop = {}
    for r in csv.DictReader(open(CAND, encoding="utf-8")):
        if r.get("country_code") == "ES" and r.get("qid"):
            try:
                pop[r["qid"]] = float(r.get("population") or 0)
            except ValueError:
                pass
    out = {}
    for r in csv.DictReader(open(STAGE / "_blocked_es.csv", encoding="utf-8")):
        if r["host"].endswith(".sedelectronica.es") and r["reason"] == "robots_disallow" and r["place_id"]:
            q = r["place_id"].split(":", 1)[-1]
            out[r["host"].lower()] = dict(r, qid=q, population=pop.get(q, 0))
    return out


def jdate(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


class Job:
    def __init__(self, a):
        self.a = a
        self.st = State(JOB, "ES", batch_prefix="archive", chunk=100)
        self.fx = CheckedFetcher(cc_crawls=4)
        self.seeds = seeds()

    def discover(self):
        boards, prev = defaultdict(list), defaultdict(dict)
        q = [("board", [f"original:.*/board/{BOARD_ID}.*"]), ("preview", ["original:.*/preview-document/.*"])]
        stats = {}
        for kind, flt in q:
            caps = []
            if not self.a.per_host:
                try:
                    caps = self.fx.wb_captures("sedelectronica.es", "domain", collapse="urlkey" if kind == "preview" else "timestamp:6",
                                               filters=flt, max_rows=2_000_000)
                except ArchiveError as e:
                    log.warning("domain listing %s failed: %s -> per-host listings", kind, e)
                    if listing_failed(e, "domain:" + kind):
                        break   # host cooling down: per-host listings would be deferred too
                    self.a.per_host = True
            stats[kind] = len(caps)
            for c in caps:
                h = re.sub(r"^https?://", "", c.original_url).split("/")[0].split(":")[0].lower()
                if h not in self.seeds:
                    continue
                if kind == "board":
                    boards[h].append(c.to_dict())
                else:
                    m = UUID.search(c.original_url)
                    if m:
                        prev[h].setdefault(m.group(1).lower(), []).append(c.to_dict())
        order = sorted(self.seeds, key=lambda h: (h not in boards, -self.seeds[h]["population"], h))
        if self.a.per_host:  # fallback: one prefix listing per host, biggest first
            for i, h in enumerate(order[: self.a.max_hosts or len(order)]):
                if STOP["flag"]:
                    break
                try:
                    caps = self.fx.wb_captures(h + "/", "prefix", collapse="urlkey",
                                               filters=[f"original:.*(board/{BOARD_ID}|preview-document).*"])
                except ArchiveError as e:
                    listing_failed(e, h)
                    continue
                for c in caps:
                    m = UUID.search(c.original_url)
                    if m:
                        prev[h].setdefault(m.group(1).lower(), []).append(c.to_dict())
                    elif BOARD_ID in c.original_url:
                        boards[h].append(c.to_dict())
            order = sorted(self.seeds, key=lambda h: (h not in boards, -self.seeds[h]["population"], h))
        stats.update(hosts=len(self.seeds), hosts_with_board=len(boards), hosts_with_previews=len(prev),
                     previews=sum(len(v) for v in prev.values()))
        plan = [{"host": h, "boards": boards.get(h, []), "previews": prev.get(h, {})} for h in order if h in boards or h in prev]
        with (self.st.dir / "plan.jsonl.tmp").open("w") as f:
            for r in plan:
                f.write(json.dumps(r) + "\n")
        os.replace(self.st.dir / "plan.jsonl.tmp", self.st.dir / "plan.jsonl")
        (self.st.dir / "discovery.json").write_text(json.dumps(stats, indent=1))
        log.info("discovery %s", stats)
        return plan

    def host(self, p):
        h, seed = p["host"], self.seeds[p["host"]]
        listed, bflags = {}, set()
        bcaps = sorted((Capture(**c) for c in p["boards"]), key=lambda c: c.timestamp, reverse=True)[:4]
        for c in bcaps:  # newest board snapshots: titles + preview links
            try:
                d = self.fx.fetch_capture(c)
            except ArchiveError:
                continue
            bflags |= set(getattr(d, "robots_flags", []) or [])
            for x in parse_sede_documents(d.text(), c.original_url):
                m = UUID.search(x["url"])
                if m:
                    listed.setdefault(m.group(1).lower(), x)
        self.st.stats["board_docs_listed"] += len(listed)
        for uid, x in listed.items():
            if STOP["flag"]:
                return
            key = f"{h}|{uid}"
            if key in self.st.done:
                continue
            caps = p["previews"].get(uid)
            if not caps:
                self.st.stats["preview_not_archived"] += 1; self.st.mark(key, "preview_not_archived"); continue
            if key in self.st.deferred:
                continue
            exc = None
            try:
                doc = self.fx.fetch_best([Capture(**c) for c in caps], max_tries=2)
            except ArchiveError as e:
                doc, exc = None, e
            if wb_deferred(self.fx, doc, exc):
                self.st.defer(key); continue
            if doc is None:
                self.st.stats["no_good_capture"] += 1; self.st.mark(key, "no_good_capture"); continue
            if doc.body[:5] == b"%PDF-":
                text, cf = pdf_text(doc.body), "pdf_text"
            else:
                text, cf = html_soup_text(doc.text()), "html"
            if len(text or "") < 100:
                self.st.stats["no_text"] += 1; self.st.mark(key, "no_text"); continue
            title = x.get("title") or x.get("label") or uid
            rec = {"place_id": seed["place_id"], "country_code": "ES", "doc_id": uid, "source_platform": "es_sedelectronica",
                   "source_url": doc.original_url, "page_url": f"https://{h}/board/{BOARD_ID}/",
                   "doc_type": "ordinance" if "ordenanza" in title.lower() else "regulation", "language": "es",
                   "html_title": title[:600], "title_native": title[:600], "number": x.get("expediente") or None,
                   "published_date": jdate(x.get("published")), "in_force": None, "consolidated": False,
                   "content_format": cf, "text": text, "retrieved_at": doc.fetched_at, "place_name": seed["name"],
                   "qid": seed["qid"], "admin_level": "municipality", "platform": "es_sedelectronica",
                   "platform_place_id": h, "ine_code": seed.get("ine"), "board_label": x.get("label"),
                   "procedure": x.get("procedure"), "source_policy": "archived_robots_disallowed",
                   "block_reason": "robots_disallow (live): " + (seed.get("detail") or "")[:150],
                   "content_sha256": hashlib.sha256(doc.body).hexdigest()}
            rec.update(provenance_fields(doc))
            if bflags:
                rec["robots_meta"] = sorted(set(rec.get("robots_meta") or []) | bflags)
            self.st.add(key, {k: v for k, v in rec.items() if v is not None or k == "in_force"})
        self.st.mark(f"{h}|host", f"listed={len(listed)}")

    def run(self):
        cp = self.st.dir / "plan.jsonl"
        plan = self.discover() if (self.a.rediscover or not cp.exists()) else [json.loads(l) for l in cp.open()]
        self.st.stats["hosts_planned"] = len(plan)
        self.st.save(self.fx)
        for i, p in enumerate(plan):
            if STOP["flag"] or (self.a.max_hosts and i >= self.a.max_hosts):
                break
            if f"{p['host']}|host" in self.st.done:
                continue
            self.host(p)
            self.st.flush()  # one file per host/place
            self.st.save(self.fx)
            log.info("host %d/%d %s staged=%d", i + 1, len(plan), p["host"], self.st.stats["staged"])
        self.st.flush()
        self.st.save(self.fx, final=not STOP["flag"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hosts", type=int, default=0)
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--per-host", action="store_true", help="skip the domain listings; one prefix listing per host")
    Job(ap.parse_args()).run()


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())
