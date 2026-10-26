#!/usr/bin/env python3
"""Spain BORM (Región de Murcia) backfill from web archives for the days the live es_bop.py BORM walker cannot reach
(Radware CAPTCHA challenges; never solved or circumvented): days older than the live cursor, plus the live job's
CAPTCHA-skipped error_days. Coordinator decision 2026-10-17 22:12 PT.

  borm_arch.py [--max-fetch N] [--rediscover] [--cc] [--min-id 0] [--max-id 0] [--floor 2010-01-01]

Discovery: Wayback CDX (+ Common Crawl index with --cc) listings of www.borm.es/services/anuncio/<id>/{txt,pdf} (and
borm.es without www), anuncio ids in [--min-id, --max-id] (~2010-01 .. 2011-09-19; BORM ids are sequential, 456997 =
2011-09-20). The archives hold no day sumarios for this period, so items are found per anuncio, not per day.
Per anuncio: newest good capture (txt preferred over pdf) through pipeline/archive's ArchiveFetcher (box-wide limiter +
Wayback breaker, lane asia_latam), NPE header (A-DDMMYY-NNNNN -> date + anuncio number), Sección IV Administración Local,
issuer, title; kept only with the live es_bop.py criteria (TARGET_RE / EXCLUDE_RE) and when the issuer resolves to a
Murcia municipality (es_places.Resolver, prov 30).
No double fetching with the live job: only publication dates < the live BORM cursor (read-only from _state/es_bop/borm.json
at every item) and doc_ids not in its done set; doc_id = BORM-<year>-<number>, the live job's own id scheme.
Records: es_bop.base_record + archive provenance (archive_source/crawl_id/timestamp/url, original_url), source_policy
captcha_blocked_archive_fallback. Staged via arch_common.State (StagedWriter, batch prefix 'archive').
Exit 75 when items were deferred because the Wayback breaker was open (breaker_loop.sh reruns from checkpoint).
"""
from __future__ import annotations

import argparse, json, logging, os, re, sys, time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "es"))
from arch_common import wb_deferred  # noqa: E402
from arch_common import STAGE, STOP, ArchiveError, CheckedFetcher, Capture, State, append_csv, pdf_text, provenance_fields  # noqa: E402
from es_places import Resolver  # noqa: E402
import es_bop as E  # noqa: E402  (TARGET_RE, EXCLUDE_RE, base_record: identical criteria/record shape to the live job)

JOB = "ES_borm_archive"
log = logging.getLogger(JOB)
LIVE_STATE = STAGE / "_state" / "es_bop" / "borm.json"
ID_RE = re.compile(r"borm\.es(?::\d+)?/services/anuncio/(\d+)/(txt|pdf)\b", re.I)
NPE_RE = re.compile(r"NPE:\s*A-(\d{2})(\d{2})(\d{2})-(\d{3,6})")
SEC_RE = re.compile(r"IV\.\s*Administraci[oó]n\s+Local", re.I)
NEXT_SEC_RE = re.compile(r"^\s*(?:I|II|III|V|VI)\.\s+[A-ZÁÉÍÓÚ][a-záéíóú]", re.M)
POLICY = "captcha_blocked_archive_fallback"


def live_view():
    """(cursor date, done doc_ids) of the running live BORM walker; read-only."""
    try:
        st = json.loads(LIVE_STATE.read_text())
        return (date.fromisoformat(st.get("cursor") or "2011-09-20"), set(st.get("done") or {}),
                {d for d, why in (st.get("error_days") or {}).items() if "captcha" in str(why)})
    except Exception:  # noqa: BLE001  (mid-rename etc.)
        return None, set(), set()


class Job:
    def __init__(self, a):
        self.a = a
        self.st = State(JOB, "ES", batch_prefix="archive", chunk=100)
        self.fx = CheckedFetcher(cc_crawls=6)
        self.res = Resolver()
        self._lv_t, self._lv = 0, (None, set(), set())

    def live(self):
        if time.time() - self._lv_t > 120:
            v = live_view()
            if v[0] is not None:
                self._lv = v
            self._lv_t = time.time()
        return self._lv

    def discover(self):
        caps, failed = [], []
        lo, hi = self.a.min_id, self.a.max_id
        for host in ("www.borm.es", "borm.es"):
            try:
                caps += self.fx.wb_captures(f"{host}/services/anuncio/", "prefix", collapse="urlkey", max_rows=500000)
            except ArchiveError as e:
                log.warning("wayback listing %s failed: %s", host, e); failed.append(f"wb:{host}")
            if self.a.cc:
                try:
                    caps += self.fx.cc_captures(f"{host}/services/anuncio/", "prefix")
                except ArchiveError as e:
                    log.warning("cc listing %s failed: %s", host, e)
        import arch_common as _ac0
        if _ac0.DISC["incomplete"]:   # a CC listing came back truncated (.truncated, deferred mid-listing)
            failed += ["cc:" + x for x in _ac0.DISC["incomplete"]]
            _ac0.DISC["incomplete"].clear()   # handled here: old candidates are kept, not set aside
            m = _ac0.WORK / "ES_borm_archive" / _ac0.DISC_MARK
            if m.exists():
                os.replace(m, m.with_name(_ac0.DISC_MARK + ".handled"))
        if failed:   # incomplete listing (breaker open / Wayback errors): keep old candidates, exit 75 -> rerun later
            import arch_common as _ac
            _ac.DEFERRED["n"] += 1
            log.warning("discovery incomplete (%s) -> deferred, candidates not rewritten", ",".join(failed))
            return None
        by = {}
        for c in caps:
            m = ID_RE.search(c.original_url)
            if not m or c.status not in (200, None):
                continue
            i = int(m.group(1))
            if (lo and i < lo) or (hi and i > hi):
                continue
            by.setdefault(i, {"txt": [], "pdf": []})[m.group(2).lower()].append(c.to_dict())
        cands = [{"key": f"borm:{i}", "id": i, "caps": v["txt"] + v["pdf"]} for i, v in sorted(by.items(), reverse=True)]
        tmp = self.st.dir / "candidates.jsonl.tmp"
        with tmp.open("w") as f:
            for r in cands:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, self.st.dir / "candidates.jsonl")
        (self.st.dir / "discovery.json").write_text(json.dumps({"captures": len(caps), "anuncios": len(cands),
                                                              "with_txt": sum(1 for v in by.values() if v["txt"]),
                                                              "id_range": [lo, hi], "complete": True, "cc": bool(self.a.cc), "at": time.strftime("%F %T")}, indent=1))
        log.info("discovery: %d captures -> %d anuncios in id range %d..%d", len(caps), len(cands), lo, hi)
        return cands

    def parse(self, doc):
        body = doc.body or b""
        if body[:5] == b"%PDF-":
            text, fmt = pdf_text(body), "pdf_text"
        else:
            ct = (doc.content_type or "").lower()
            if "html" in ct and re.search(rb"captcha|perfdrive|shieldsquare", body[:3000], re.I):
                return None, "captcha_page"
            text, fmt = E.html_text(body.decode("utf-8", "replace")) if "html" in ct else body.decode("utf-8", "replace"), "html"
        text = re.sub(r"\r\n?", "\n", text or "").strip()
        if len(text) < 100:
            return None, "no_text"
        return (text, fmt), "ok"

    def build(self, r, doc, cursor, live_done, err_days=frozenset()):
        p, why = self.parse(doc)
        if not p:
            return None, why
        text, fmt = p
        m = NPE_RE.search(text)
        if not m:
            return None, "no_npe"
        dd, mm, yy, num = m.groups()
        try:
            pub = date(2000 + int(yy), int(mm), int(dd))
        except ValueError:
            return None, "bad_npe_date"
        if pub < date.fromisoformat(self.a.floor):
            return None, "before_floor"
        if cursor and pub >= cursor and pub.isoformat() not in err_days:
            return None, "live_range"
        doc_id = f"BORM-{pub.year}-{int(num)}"
        if doc_id in live_done:
            return None, "live_done"
        sm = SEC_RE.search(text)
        if not sm:
            return None, "not_local"
        after = text[sm.end():]
        lines = [l.strip() for l in after.split("\n") if l.strip()]
        lines = [l for l in lines if not re.match(r"(?i)^(n[uú]mero\s+\d+|p[aá]gina\s+\d+|NPE:|www\.borm\.es|BORM\b|boletín oficial)", l)
                 and not re.match(r"(?i)^(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo),", l)]
        if len(lines) < 2:
            return None, "no_header"
        issuer = re.sub(r"\s{2,}.*$", "", lines[0]).strip()
        t_i = next((k for k, l in enumerate(lines[1:6], 1) if re.match(rf"^{int(num)}\b", l)), 1)
        title = re.sub(rf"^{int(num)}\s*", "", " ".join(lines[t_i:t_i + 4]))
        title = re.sub(r"-\s+(?=[a-záéíóúñ])", "", title)
        title = re.split(r"(?<=\.)\s+(?=[A-ZÁÉÍÓÚ])", title, maxsplit=1)[0].strip()[:600]
        if not E.TARGET_RE.search(title) or E.EXCLUDE_RE.search(title):
            return None, "not_target"
        place = self.res.resolve(issuer, "30") or {}
        if not place.get("place_id"):
            append_csv(STAGE / "_unmatched_es_bop_archive.csv", ["gazette", "issuer", "province", "url", "why", "at"],
                       ["borm_arch", issuer, "30", doc.original_url, place.get("match", "no_match"), time.strftime("%Y-%m-%d %H:%M")])
            return None, "unmatched"
        nxt = NEXT_SEC_RE.search(after)
        body_t = after[: nxt.start()] if nxt else after
        ex = {"issuer_name": issuer, "province_code": "30", "gazette": "borm", "borm_id": str(r["id"]),
              "html_url": f"https://www.borm.es/#/home/anuncio/{pub:%d-%m-%Y}/{int(num)}", "npe": m.group(0)[5:].strip(),
              "source_format": "txt" if fmt == "html" else "pdf"}
        rec = E.base_record("borm", place, doc_id, doc.original_url, title, body_t.strip(), fmt, pub.isoformat(), ex)
        rec["source_policy"] = POLICY
        rec["block_reason"] = "live www.borm.es serves a Radware CAPTCHA for this period (never circumvented)"
        rec.update(provenance_fields(doc))
        return rec, "ok"

    def run(self):
        cp = self.st.dir / "candidates.jsonl"
        dj = self.st.dir / "discovery.json"
        done_disc = cp.exists() and dj.exists() and json.loads(dj.read_text()).get("complete") and \
            json.loads(dj.read_text()).get("id_range") == [self.a.min_id, self.a.max_id]
        cands = self.discover() if (self.a.rediscover or not done_disc) else [json.loads(l) for l in cp.open()]
        if cands is None:
            self.st.save(self.fx); return
        self.st.stats["candidates"] = len(cands)
        self.st.save(self.fx)
        n = 0
        for r in cands:
            if STOP["flag"] or (self.a.max_fetch and n >= self.a.max_fetch):
                break
            if r["key"] in self.st.done or r["key"] in self.st.deferred:
                continue
            cursor, live_done, err_days = self.live()
            n += 1
            exc = None
            try:
                doc = self.fx.fetch_best([Capture(**c) for c in r["caps"]], max_tries=2, policy="newest")
            except ArchiveError as e:
                doc, exc = None, e
            if wb_deferred(self.fx, doc, exc):
                self.st.defer(r["key"]); continue
            if doc is None:
                self.st.stats["no_good_capture"] += 1; self.st.mark(r["key"], "no_good_capture"); continue
            try:
                rec, why = self.build(r, doc, cursor, live_done, err_days)
            except Exception as e:  # noqa: BLE001
                log.exception("build %s", r["key"]); rec, why = None, f"error:{type(e).__name__}"
            # live_range = dated on/after the live cursor and not a CAPTCHA-skipped day: the live walker (newest first)
            # has already covered it -> marked like any other terminal outcome below (no refetch on reruns)
            if not rec:
                self.st.stats[why] += 1; self.st.mark(r["key"], why); continue
            self.st.add(r["key"], rec)
            log.info("staged-pending %s %s %s", rec["doc_id"], rec.get("place_name"), rec["title_native"][:80])
            self.st.maybe_flush(1800)
            if n % 10 == 0:
                self.st.save(self.fx)
                log.info("progress %d/%d %s", n, len(cands), dict(self.st.stats))
        self.st.flush()
        self.st.save(self.fx, final=not STOP["flag"] and not self.st.deferred)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--cc", action="store_true")
    ap.add_argument("--min-id", type=int, default=0, help="0 = no bound (ids are not chronological; the NPE date decides)")
    ap.add_argument("--max-id", type=int, default=0)
    ap.add_argument("--floor", default="2010-01-01")
    Job(ap.parse_args()).run()


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())
