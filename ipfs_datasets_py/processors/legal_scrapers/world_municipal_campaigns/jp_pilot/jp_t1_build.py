"""Japan tranche 1 — FULL-corpus builder (supersedes the pilot samples).

Same adapters as the pilot (jp_build.py: Gyosei Reiki-Base + Daiichi Hoki
d1-law), but processes the ENTIRE enumerated corpus per municipality
instead of the deterministic 16-ordinance sample.

Resumability: per municipality, parsed rows are appended doc-by-doc to
staging/<code>_rows.jsonl and the done-set to staging/<code>_done.json
(atomic replace after every doc). A killed run resumes from the first
unprocessed doc; page fetches additionally hit the pilot's scratch cache
(scratch/<code>/honbun/). Finalize (dedupe doc_ids, doc_order, gates,
parquet write) happens once all docs are processed, or immediately when
the staging is already complete.

Endpoints: the pilot's five + any added by the tenant census in
tranche1_endpoints.json ({code: base_url}), which overrides/extends
jp_build.MUNICIPALITIES.
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jp_build as B  # noqa: E402  (pilot adapters, Fetcher, parsers)

from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402

OUT = B.OUT
DATA = B.DATA
SCRATCH = B.SCRATCH
STAGING = OUT / "staging"
RETRIEVED = "2026-10-14"
JP = B.JP
REGISTRY = B.REGISTRY

ENDPOINTS = dict(B.MUNICIPALITIES)
_ep_file = OUT / "tranche1_endpoints.json"
if _ep_file.exists():
    ENDPOINTS.update(json.loads(_ep_file.read_text(encoding="utf-8")))
ENDPOINTS.pop("01202", None)  # Hakodate: pilot-documented retired tenant


class FastFetcher(B.Fetcher):
    """Pilot Fetcher with keep-alive session pooling (the egress proxy
    makes per-request connection setup the dominant cost), a 30 s
    timeout, and a robots.txt read WITH a timeout — the pilot's
    RobotFileParser.read() uses urllib with no timeout and hangs
    indefinitely when the proxy stalls a connection (observed: whole
    builders silently frozen). Robots posture preserved: explicit
    Disallow rules honored; 401/403 on robots.txt => disallow-all
    (the pilot's g-reiki behavior); unreachable/other => allow, as
    with rp.read()."""

    def __init__(self):
        super().__init__()
        self.session = requests.Session()

    def robots_allows(self, url):
        from urllib.parse import urlparse
        import urllib.robotparser as robotparser
        parts = urlparse(url)
        key = (parts.scheme, parts.netloc)
        if key not in self._robots_ok:
            rp = robotparser.RobotFileParser()
            rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
            # RobotFileParser.can_fetch returns False for EVERYTHING
            # until last_checked is set (read() sets it before fetching);
            # mirror read(): stamp it, then parse only a readable 200.
            rp.last_checked = int(time.time())
            # Posture (pilot parity, jp_build.Fetcher line ~95:
            # "unreadable robots: proceed politely"): a robots.txt that
            # cannot be READ — network failure through this proxy, or a
            # non-200 the proxy may have synthesized (en3-jg's robots
            # path is dropped by the egress proxy while its content
            # pages serve 200) — does not block; a readable robots.txt
            # is parsed and honored. Hosts that genuinely block us
            # (g-reiki.net) refuse the content fetches themselves,
            # which surface as per-doc failures. Notes are printed so
            # the posture is auditable in the build logs.
            for attempt in range(2):
                try:
                    r = self.session.get(rp.url, headers=B.HEADERS,
                                         timeout=15)
                    if r.status_code == 200:
                        rp.parse(r.text.splitlines())
                    else:
                        print(f"robots unreadable ({r.status_code}) for "
                              f"{parts.netloc} — proceeding politely",
                              flush=True)
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 1:
                        print(f"robots unreadable ({type(e).__name__}) "
                              f"for {parts.netloc} — proceeding politely",
                              flush=True)
                    else:
                        time.sleep(3)
            self._robots_ok[key] = rp
        return self._robots_ok[key].can_fetch(B.UA, url)

    def get(self, url, cache_path=None, timeout=75, attempts=3):
        if cache_path is not None and Path(cache_path).exists():
            return Path(cache_path).read_bytes()
        if not self.robots_allows(url):
            raise PermissionError(f"robots.txt disallows {url}")
        last = None
        for i in range(attempts):
            try:
                r = self.session.get(url, headers=B.HEADERS, timeout=timeout)
                r.raise_for_status()
                raw = r.content
                if cache_path is not None:
                    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(cache_path).write_bytes(raw)
                return raw
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"fetch failed {url}: {last}")


def load_done(code):
    p = STAGING / f"{code}_done.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"docs": [], "failed": [], "corpus_docs": None, "chapters": None}


def save_done(code, done):
    STAGING.mkdir(parents=True, exist_ok=True)
    tmp = STAGING / f"{code}_done.json.tmp"
    tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STAGING / f"{code}_done.json")


def build_municipality(fx, code, base):
    reg = REGISTRY[code]
    name = reg["name"]
    fam = B.family_of(base, code)
    if fam == "d1law":
        chapters, docs = B.enumerate_d1law(fx, code, base)
        parse = B.parse_d1law
    else:
        chapters, docs = B.enumerate_corpus(fx, code, base)
        parse = B.parse_honbun
    done = load_done(code)
    done["corpus_docs"] = len(docs)
    done["chapters"] = len(chapters)
    # failures from earlier runs are retried, not skipped forever
    if done["failed"]:
        done.setdefault("fail_log", []).extend(done["failed"])
        done["failed"] = []
        save_done(code, done)
    done_ids = {d["honbun_id"] for d in done["docs"]}
    todo = [d for d in docs if d["honbun_id"] not in done_ids]
    print(f"{code} {name}: corpus {len(docs)} docs / {len(chapters)} chapters; "
          f"done {len(done_ids)}, todo {len(todo)}", flush=True)
    rows_path = STAGING / f"{code}_rows.jsonl"
    STAGING.mkdir(parents=True, exist_ok=True)
    rf = rows_path.open("a", encoding="utf-8")

    def process(d):
        cache_file = SCRATCH / code / "honbun" / f"{d['honbun_id']}.html"
        was_cached = cache_file.exists()
        try:
            raw = fx.get(d["url"], cache_file)
            meta, units = parse(B.decode(raw))
        except Exception as e:  # noqa: BLE001
            done["failed"].append({"honbun_id": d["honbun_id"],
                                   "name": d["name"],
                                   "error": f"{type(e).__name__}: {e}"})
            save_done(code, done)
            print(f"{code} FAIL {d['honbun_id']} {d['name']}: {e}", flush=True)
            return False
        title = meta["title"] or d["name"]
        path = f"{d['chapter_title']} / {title}"
        n_rows = 0
        for u in units:
            row = make_row(
                jurisdiction_id=code, jurisdiction_name=name, country="JP",
                doc_id=f"{d['honbun_id']}-{u['key']}",
                regeling_id=d["honbun_id"], regeling_work_id=d["honbun_id"],
                title=title, structural_path=path, node_label=u["label"],
                body_html=u["html"], source_url=d["url"],
                date_effective=meta["promulgated_iso"], retrieved=RETRIEVED,
            )
            rf.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_rows += 1
        rf.flush()
        done["docs"].append({"honbun_id": d["honbun_id"], "name": title,
                             "chapter": d["chapter_title"],
                             "units": len(units), "rows": n_rows,
                             "promulgated": meta["promulgated_iso"]})
        save_done(code, done)
        if not was_cached:
            time.sleep(0.5)
        return True

    for i, d in enumerate(todo):
        process(d)
        if (i + 1) % 25 == 0 or i + 1 == len(todo):
            print(f"{code}: {len(done['docs'])}/{len(docs)} docs processed",
                  flush=True)
    # one retry pass over this run's failures (proxy flakiness is common)
    if done["failed"]:
        retry_ids = {f["honbun_id"] for f in done["failed"]}
        done["failed"] = []
        save_done(code, done)
        retry = [d for d in docs if d["honbun_id"] in retry_ids]
        print(f"{code}: retrying {len(retry)} failed docs", flush=True)
        for d in retry:
            process(d)
    rf.close()
    return finalize_municipality(code, name, base, fam, done)


def finalize_municipality(code, name, base, fam, done):
    rows_path = STAGING / f"{code}_rows.jsonl"
    rows = [json.loads(l) for l in rows_path.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    rows = drop_empty_rows(finalize_rows(rows))
    table = rows_to_table(rows)
    errs = validate_table(table, jurisdiction_id=code, jurisdiction_name=name,
                          country="JP")
    report = validation_report(table, jurisdiction_id=code,
                               jurisdiction_name=name, country="JP")
    dest = DATA / JP.file_name(code)
    write_html_parquet(dest, table)
    write_validation_report(DATA / f"{code}_validation.json", report)
    back = read_html_parquet(dest)
    errs2 = validate_table(back, jurisdiction_id=code, jurisdiction_name=name,
                           country="JP")
    complete = (len(done["docs"]) + len(done["failed"])) >= (done["corpus_docs"] or 0)
    res = {"name": name, "base": base, "family": fam,
           "corpus_docs": done["corpus_docs"], "chapters": done["chapters"],
           "sampled_docs": len(done["docs"]) + len(done["failed"]),
           "docs_built": len(done["docs"]),
           "failed_docs": done["failed"],
           "docs": done["docs"], "rows": table.num_rows,
           "full": complete and not done["failed"],
           "valid": not errs and not errs2, "errors": errs + errs2}
    print(f"{code} {name}: rows {table.num_rows} valid={res['valid']} "
          f"full={res['full']} failed={len(done['failed'])} "
          f"errs={errs + errs2}", flush=True)
    return res


def main():
    codes = sys.argv[1:]
    if not codes:
        print("usage: jp_t1_build.py <JIS code> [more codes...]")
        return 1
    manifest_path = OUT / "tranche1_manifest.json"
    manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists() else {"municipalities": {}})
    fx = FastFetcher()
    for code in codes:
        code = JP.normalize(code)
        if code not in ENDPOINTS:
            print(code, "no endpoint known — skipped", flush=True)
            continue
        try:
            res = build_municipality(fx, code, ENDPOINTS[code])
            manifest["municipalities"][code] = res
        except Exception as e:  # noqa: BLE001
            manifest["municipalities"][code] = {"error": f"{type(e).__name__}: {e}"}
            print(code, "BUILD FAILED", e, flush=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print("tranche1 manifest updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
