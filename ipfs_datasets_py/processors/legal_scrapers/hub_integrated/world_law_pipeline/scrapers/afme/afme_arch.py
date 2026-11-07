#!~/.ipfs_datasets/world_law/.venv_afme/bin/python
"""afme archive fetcher: Common Crawl first, then Wayback through the box-wide breaker (1 Wayback worker).

Input: out/afme_config/<CC>.json (same format as afme_live.py; docs[].url are the targets), or --urls-file
with lines "place_id<TAB>url[<TAB>doc_id]".
Done list: out/afme/done/arch_<CC>.tsv (url, status ok|miss|skip_challenge, utc, note).
Places/URLs deferred by the Wayback breaker, a 429/5xx cool-down or a transient error are logged to
out/afme/done/arch_<CC>.deferred.tsv and are NOT marked done.
Output: out/afme/raw/<CC>/<place_key>.<cc>_arch_<UTC>.jsonl ; afme_stage.py validates and stages.
Single process, sequential: at most one Wayback request in flight from this lane (the limiter enforces 1 box-wide).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, sys
import afme_common as C          # sets ARCHIVE_LANE=afme before the archive module is imported
from archive import ArchiveFetcher, ArchiveDeferred, ArchiveTransient, ArchiveError, provenance_fields, ratelimit
from schema import place_key, validate_record

WAYBACK_WORKERS = 1


def targets(cc, urls_file):
    if urls_file:
        out = {}
        for line in open(urls_file, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and not line.startswith("#"):
                out.setdefault(p[0], []).append({"url": p[1], **({"doc_id": p[2]} if len(p) > 2 and p[2] else {})})
        cfg = C.load_config(cc) if (C.CONFIG / f"{cc}.json").exists() else {"cc": cc}
        cfg["places"] = [{"place_id": k, "docs": v} for k, v in out.items()]
        return cfg
    return C.load_config(cc)


def mark_deferred(cc, url, why):
    with C.done_path("arch", cc).with_suffix(".deferred.tsv").open("a", encoding="utf-8") as f:
        f.write(f"{url}\tdeferred\t{C.utc_iso()}\t{why[:300]}\n")


def fetch_one(fx, url):
    """-> (doc|None, status, note). status: ok|miss|deferred|skip_challenge."""
    cc_def = None
    try:
        caps = fx.list_captures(url, sources=("commoncrawl",))
        if caps:
            doc = fx.fetch_best(caps, max_tries=3)
            if doc is not None:
                return doc, "ok", "commoncrawl"
        if getattr(caps, "truncated", False):
            cc_def = "cc_listing_truncated"
    except ArchiveDeferred as e:
        cc_def = f"cc_deferred {e.families} retry_in={e.retry_in:.0f}s"
    except ArchiveTransient as e:
        cc_def = f"cc_transient {e}"
    except ArchiveError as e:
        C.log(f"cc error {url}: {e}")
    # Wayback, only through the breaker
    if not ratelimit.wayback_available():
        return None, "deferred", f"wayback_breaker_open {cc_def or ''}"
    try:
        caps = fx.list_captures(url, sources=("wayback",))
        if caps:
            doc = fx.fetch_best(caps, max_tries=3)
            if doc is not None:
                return doc, "ok", "wayback"
        if getattr(caps, "truncated", False):
            return None, "deferred", "wb_listing_truncated"
        if fx.last_wb_deferred:
            return None, "deferred", "wayback_breaker_or_throttle"
    except ratelimit.WaybackDown as e:
        return None, "deferred", f"wayback_down {e}"
    except ArchiveDeferred as e:
        return None, "deferred", f"wb_deferred {e.families} retry_in={e.retry_in:.0f}s"
    except ArchiveTransient as e:
        return None, "deferred", f"wb_transient {e}"
    except ArchiveError as e:
        return None, "miss", f"wb_error {e}"
    if cc_def:
        return None, "deferred", cc_def
    return None, "miss", "no_capture"


def run(cc, urls_file=None, max_urls=None, cc_crawls=4, dry=False):
    C.cap_address_space()
    cc = cc.upper()
    cfg = targets(cc, urls_file); cfg["cc"] = cc
    fx = ArchiveFetcher(cc_crawls=cc_crawls, user_agent=C.UA)
    done = C.load_done("arch", cc)
    n = 0
    for place in cfg["places"]:
        pk = place_key(place["place_id"])
        rows = []
        for d in place.get("docs", []):
            if d["url"] in done:
                continue
            if max_urls is not None and n >= max_urls:
                break
            C.disk_check(); C.mem_check()
            n += 1
            doc, st, note = fetch_one(fx, d["url"])
            if st == "ok":
                ch = C.is_challenge(200, {}, doc.body)
                if ch:
                    st, note, doc = "skip_challenge", ch, None
            if st == "deferred":
                C.log(f"{cc} {pk} DEFERRED {d['url']}: {note}")
                if not dry:
                    mark_deferred(cc, d["url"], note)
                continue
            if st != "ok":
                C.log(f"{cc} {pk} {st} {d['url']}: {note}")
                if not dry:
                    C.mark_done("arch", cc, d["url"], st, note)
                continue
            is_pdf = (doc.content_type or "").lower().find("pdf") >= 0 or doc.body[:5] == b"%PDF-"
            rec = {"place_id": place["place_id"], "country_code": cc,
                   "doc_id": d.get("doc_id") or d["url"].split("://", 1)[-1],
                   "source_platform": cfg.get("source_platform", f"{cc.lower()}_archive"),
                   "source_url": d["url"], "doc_type": d.get("doc_type", cfg.get("doc_type", "ordinance")),
                   "language": d.get("language", cfg.get("language", "en")),
                   "consolidated": bool(cfg.get("consolidated", False)),
                   "content_format": "pdf_text" if is_pdf else "html",
                   "retrieved_at": C.utc_iso(), "source_official": cfg.get("source_official", True),
                   **provenance_fields(doc)}
            rec["source_policy"] = f"{note}_archive_fallback"     # e.g. commoncrawl_archive_fallback
            rec["extra_metadata"]["archive"]["source_policy"] = rec["source_policy"]
            if is_pdf:
                from afme_live import pdf_text
                rec["text"] = pdf_text(doc.body)
                if not rec["text"].strip():
                    rec["content_complete"] = False
            else:
                rec["html"] = doc.text()
            for k in ("title_native", "number", "adopted_date", "published_date"):
                if d.get(k):
                    rec[k] = d[k]
            rec.setdefault("title_native", d.get("title_native") or rec["doc_id"])
            for k in ("place_name", "admin_level", "qid"):
                if place.get(k):
                    rec[k] = place[k]
            errs = validate_record(rec)
            if errs:
                C.log(f"{cc} {pk} invalid {d['url']}: {errs}")
                continue
            rows.append(rec)
            C.log(f"{cc} {pk} ok {d['url']} via {note}")
        if rows and not dry:
            p = C.write_raw(cc, pk, f"{cc.lower()}_arch_", rows)
            for r in rows:
                C.mark_done("arch", cc, r["source_url"], "ok", p.name)
        if max_urls is not None and n >= max_urls:
            break
    C.log(f"{cc} arch done: {n} URLs, breaker={ratelimit.breaker_status().get('state', ratelimit.breaker_status())}, RSS {C.rss_mb():.0f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cc")
    ap.add_argument("--urls-file")
    ap.add_argument("--max-urls", type=int)
    ap.add_argument("--cc-crawls", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(a.cc, a.urls_file, a.max_urls, a.cc_crawls, a.dry_run)
