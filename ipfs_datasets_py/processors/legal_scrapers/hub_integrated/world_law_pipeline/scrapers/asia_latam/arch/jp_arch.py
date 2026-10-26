#!/usr/bin/env python3
"""Japan 例規集 bodies that are network-blocked from the box, from web archives -> staging/asia_latam/JP/.

  jp_arch.py [--hosts g-reiki,d1law] [--max-fetch N] [--rediscover] [--cc]

Scope (staging/asia_latam/_blocked_jp.csv): www1.g-reiki.net bodies with reason=unreachable (Gyosei Reiki-Base,
TLS dropped from the box) and en3/en5-jg.d1-law.com bodies with reason=robots_unreachable (server closes the
connection; coordinator-listed for the archive). Asahikawa/Towada (robots_disallow live) from the archive only, tagged archived_robots_disallowed; g-reiki tagged noarchive_meta.
houmu.h-chosonkai.gr.jp is not handled yet (archived data/<n>/<n>/ paths do not map to choson_no).
Discovery: Wayback prefix listings per host (collapse=urlkey) + CC listings when cached (--cc). Fetch: newest Wayback
capture first via the timestamp-redirect of the id_ replay, validated, else the listed capture (CC first when present).
doc_id = the vendor's document id (same as the live jp_reiki.py scraper) so merges by doc_id line up.
"""
from __future__ import annotations

import argparse, csv, hashlib, html as htmlmod, json, logging, os, re, sys, time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arch_common import wb_deferred, WBDeferred, listing_failed  # noqa: E402,F401
from archive.ratelimit import wayback_available  # noqa: E402,F401
from arch_common import STAGE, STOP, ArchiveError, ArchiveFetcher, CheckedFetcher, Capture, State, provenance_fields  # noqa: E402

JOB = "JP_reiki_archive"
log = logging.getLogger(JOB)

# --- copied (not imported, to avoid side effects) from jp/jp_reiki.py --------------------------------------------
ERA = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}
Z2H = str.maketrans("０１２３４５６７８９", "0123456789")


def jdate(s):
    if not s:
        return None
    s = s.translate(Z2H).replace("元年", "1年")
    m = re.search(r"(明治|大正|昭和|平成|令和)\s*(\d+)年(?:\s*(\d+)月(?:\s*(\d+)日)?)?", s)
    if not m:
        m2 = re.search(r"((?:18|19|20)\d\d)年(?:(\d+)月(?:(\d+)日)?)?", s)
        if not m2:
            return None
        y, mo, d = int(m2.group(1)), m2.group(2), m2.group(3)
    else:
        y, mo, d = ERA[m.group(1)] + int(m.group(2)), m.group(3), m.group(4)
    if mo and d:
        return f"{y:04d}-{int(mo):02d}-{int(d):02d}"
    if mo:
        return f"{y:04d}-{int(mo):02d}"
    return f"{y:04d}"


def doc_type_for(number, title=""):
    if re.search(r"条例", number or "") or (not number and (title or "").endswith("条例")):
        return "ordinance"
    if "告示" in (number or "") or "公告" in (number or ""):
        return "decision"
    return "regulation"


BLOCK_TAGS = ["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "dt", "dd", "ul", "ol", "blockquote", "pre"]


def html_to_text(soup):
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for t in soup.find_all(BLOCK_TAGS):
        t.insert_after("\n")
    txt = soup.get_text("")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"[ \t\u3000]*\n[ \t\u3000\n]*", "\n", txt)
    return txt.strip()
# ------------------------------------------------------------------------------------------------------------------

HOSTS = {
    "g-reiki": dict(queries=[("www1.g-reiki.net/", ["original:.*reiki_honbun.*"])], vendor="gyosei",
                    platform="jp_reiki_gyosei", groups=(1, 2), policy="noarchive_meta",
                    doc_rx=re.compile(r"(?i)^https?://www1\.g-reiki\.net(?::\d+)?/(.+?)/reiki_honbun/([A-Za-z0-9_]+)\.html?$")),
    # robots-disallowed live sites; archived copies allowed (Benjamin via coordinator 2026-10-10), never fetched live
    "asahikawa": dict(queries=[("www1.city.asahikawa.hokkaido.jp/files/soumu_soumu/d1w_reiki/", None)], vendor="d1w",
                      platform="jp_reiki_d1w", groups=(1, 2), reason="robots_disallow",
                      doc_rx=re.compile(r"(?i)^https?://www1\.city\.asahikawa\.hokkaido\.jp(?::\d+)?/(files/soumu_soumu)/d1w_reiki/([A-Za-z0-9]+)/\2_j\.html?$")),
    "towada": dict(queries=[("www.city.towada.lg.jp/reiki_int/", ["original:.*reiki_honbun.*"])], vendor="gyosei",
                   platform="jp_reiki_gyosei", groups=(1, 2), reason="robots_disallow",
                   doc_rx=re.compile(r"(?i)^https?://www\.city\.towada\.lg\.jp(?::\d+)?/(reiki_int)/reiki_honbun/([A-Za-z0-9_]+)\.html?$")),
    "d1law": dict(queries=[("en3-jg.d1-law.com/", ["original:.*d1w_reiki/.*_j\\.html.*"]), ("en5-jg.d1-law.com/", None)],
                  vendor="d1w", platform="jp_reiki_d1law", groups=(2, 3), policy="robots_unreachable",
                  doc_rx=re.compile(r"(?i)^https?://(en[35]-jg\.d1-law\.com)(?::\d+)?/(.+?)/d1w_reiki/([A-Za-z0-9]+)/\3_j\.html?$")),
}


def seeds():
    """base key -> seed row (from _blocked_jp.csv; only network-level reasons)."""
    out = {}
    for r in csv.DictReader(open(STAGE / "_blocked_jp.csv", encoding="utf-8")):
        u = r["url"]
        if "g-reiki.net" in r["host"] and r["reason"] == "unreachable":
            m = re.match(r"https?://www1\.g-reiki\.net/(.+?)/(?:reiki_menu\.html|reiki_[a-z]+/|index\.html|$)", u)
            if m:
                out[("g-reiki", m.group(1).lower())] = r
        elif r["host"] in ("en3-jg.d1-law.com", "en5-jg.d1-law.com") and r["reason"] == "robots_unreachable":
            m = re.match(r"https?://([^/]+)/(.+?)/d1w_reiki/", u)
            if m:
                out[("d1law", m.group(2).lower())] = r
        elif r["host"] == "www1.city.asahikawa.hokkaido.jp" and r["reason"] == "robots_disallow":
            out[("asahikawa", "files/soumu_soumu")] = r
        elif r["host"] == "www.city.towada.lg.jp" and r["reason"] == "robots_disallow":
            out[("towada", "reiki_int")] = r
    return out


def jis_pref(jis):
    return f"JP-{str(jis)[:2]}" if jis and len(str(jis)) >= 2 else None


class Job:
    def __init__(self, a):
        self.a = a
        self.st = State(JOB, "JP", batch_prefix="archive", chunk=a.chunk)
        self.fx = CheckedFetcher(cc_crawls=a.cc_crawls)
        self.seeds = seeds()

    def discover(self):
        cand = defaultdict(list)  # (host, base, did) -> caps
        stats = {}
        for h in self.a.hosts:
            spec = HOSTS[h]
            for url, flt in spec["queries"]:
                caps = []
                if self.a.cc:
                    caps += self.fx.cc_captures(url, "prefix")
                ncc = len(caps)
                try:
                    caps += self.fx.wb_captures(url, "prefix", collapse="urlkey", filters=flt, max_rows=1500000)
                except ArchiveError as e:
                    log.warning("wayback listing failed %s: %s", url, e)
                    listing_failed(e, url)
                stats[url] = {"cc": ncc, "wb": len(caps) - ncc}
                for c in caps:
                    if c.status not in (200, None):
                        continue
                    m = spec["doc_rx"].match(c.original_url)
                    if not m:
                        continue
                    base, did = m.group(spec["groups"][0]), m.group(spec["groups"][1])
                    if (h, base.lower()) not in self.seeds:
                        continue
                    cand[(h, base.lower(), did)].append(c)
        # place by place (smallest first, so many places complete early; one file per place when it completes)
        per = defaultdict(list)
        for (h, base, did), caps in cand.items():
            caps.sort(key=lambda c: (c.source == "commoncrawl", c.timestamp), reverse=True)
            per[(h, base)].append({"key": f"{h}|{base}|{did}", "host": h, "base": base, "did": did,
                                   "caps": [c.to_dict() for c in caps[:4]]})
        order = []
        for k in sorted(per, key=lambda k: (len(per[k]), k)):
            order += sorted(per[k], key=lambda r: r["did"])
        tmp = self.st.dir / "candidates.jsonl.tmp"
        with tmp.open("w") as f:
            for r in order:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, self.st.dir / "candidates.jsonl")
        stats["candidates"] = len(order)
        stats["places_with_captures"] = len(per)
        stats["places_in_scope"] = sum(1 for k in self.seeds if k[0] in self.a.hosts)
        stats["per_place"] = {f"{k[0]}|{k[1]}": len(v) for k, v in per.items()}
        (self.st.dir / "discovery.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
        log.info("candidates=%d places=%d/%d", len(order), len(per), stats["places_in_scope"])
        return order

    def valid(self, doc, h):
        b = doc.body[:200000]
        if HOSTS[h]["vendor"] == "gyosei":
            return b'id="primary"' in b or b"class=\"eline\"" in b
        return b"<body" in b.lower() and len(b) > 500

    def fetch(self, r):
        caps = [Capture(**c) for c in r["caps"]]
        wb = [c for c in caps if c.source == "wayback"]
        cc = [c for c in caps if c.source == "commoncrawl"]
        if cc:  # CC first
            try:
                d = self.fx.fetch_best(cc, max_tries=2, validator=lambda d: self.valid(d, r["host"]))
                if d:
                    return d
            except ArchiveError:
                pass
        if wb and not self.a.no_newest:
            # newest Wayback capture: an id_ replay at a future timestamp redirects to the nearest (= newest) one
            probe = Capture("wayback", "wayback", "20261010000000", wb[0].original_url, 200, wb[0].mime)
            if not wayback_available():   # breaker open: skip the newest-capture probe (fetch_best drops Wayback too)
                self.fx.last_wb_deferred = len(wb)
                return None
            try:
                d = self.fx.fetch_capture(probe)
                if d is not None and self.valid(d, r["host"]) and d.archive_timestamp > "2000":
                    return d
            except ArchiveError:
                pass
        try:
            return self.fx.fetch_best(wb, max_tries=2, validator=lambda d: self.valid(d, r["host"])) if wb else None
        except ArchiveError as e:
            if wb_deferred(self.fx, None, e):
                self.fx.last_wb_deferred = max(1, getattr(self.fx, "last_wb_deferred", 0))
            return None

    def build(self, r, doc):
        from bs4 import BeautifulSoup
        seed = self.seeds[(r["host"], r["base"])]
        raw = doc.text()
        soup = BeautifulSoup(raw, "lxml")
        title = number = date_raw = None
        if HOSTS[r["host"]]["vendor"] == "gyosei":
            main = soup.find(id="primary") or soup.body or soup
            t = main.find("p", class_=re.compile("title")) if main else None
            title = (t.get_text(" ", strip=True).lstrip("○◎") if t else None) or (soup.title.get_text(strip=True) if soup.title else None)
            d = main.find("p", class_="date") if main else None
            n = main.find("p", class_="number") if main else None
            date_raw = d.get_text(" ", strip=True) if d else None
            number = n.get_text(" ", strip=True) if n else None
            platform = HOSTS[r["host"]]["platform"]
        else:
            for t in soup(["script", "style"]):
                t.decompose()
            main = soup.body or soup
            title = soup.title.get_text(strip=True) if soup.title else None
            txt0 = main.get_text("\n", strip=True)[:600]
            m = re.search(r"((?:明治|大正|昭和|平成|令和)\S{1,4}年\S{1,3}月\S{1,3}日)\s*\n?\s*(\S*第\S+号)?", txt0)
            if m:
                date_raw, number = m.group(1), m.group(2)
            if not title:
                title = next((l for l in txt0.split("\n") if len(l) > 3), None)
            platform = HOSTS[r["host"]]["platform"]
        html = str(main)
        text = html_to_text(BeautifulSoup(html, "lxml"))
        if len(text) < 30:
            return None, "too_short"
        title = (title or r["did"]).strip()
        rec = {
            "place_id": seed["place_id"], "country_code": "JP", "doc_id": r["did"], "source_platform": platform,
            "source_url": doc.original_url, "doc_type": doc_type_for(number, title), "language": "ja",
            "html_title": title, "title_native": title, "consolidated": True, "content_format": "html",
            "html": html, "text": text, "retrieved_at": doc.fetched_at, "in_force": None,
            "place_name": seed["name"], "qid": seed["place_id"].split(":", 1)[1] if seed["place_id"].startswith("wd:") else None,
            "admin_level": "adm1" if seed["place_id"].startswith("iso:") else "municipality",
            "iso_3166_2": jis_pref(seed.get("jis_code")), "platform": platform, "platform_place_id": seed["url"],
            "jis_code": seed.get("jis_code"), "vendor": HOSTS[r["host"]]["vendor"], "prefecture": seed.get("pref"),
            "seed_url": seed["url"], "seed_id": seed.get("seed_id"),
            "content_sha256": hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest(),
            "source_policy": HOSTS[r["host"]].get("policy") or ("archived_robots_disallowed"
                             if HOSTS[r["host"]].get("reason") == "robots_disallow" else "network_unreachable_archive_fallback"),
        }
        if number and number not in ("種別なし",):
            rec["number"] = number
        ad = jdate(date_raw)
        if ad:
            rec["adopted_date"] = ad
        rec.update(provenance_fields(doc))
        return {k: v for k, v in rec.items() if v is not None or k == "in_force"}, "ok"

    def run(self):
        cp = self.st.dir / "candidates.jsonl"
        cands = self.discover() if (self.a.rediscover or not cp.exists()) else [json.loads(l) for l in cp.open()]
        self.st.stats["candidates"] = len(cands)
        self.st.save(self.fx)
        if self.a.discover_only:
            return
        n = 0
        for r in cands:
            if STOP["flag"] or (self.a.max_fetch and n >= self.a.max_fetch):
                break
            if r["key"] in self.st.done or r["host"] not in self.a.hosts:
                continue
            place = (r["host"], r["base"])
            if place != getattr(self, "_place", None):
                if any(w.buf for w in self.st.writers.values()):
                    self.st.flush()  # previous place complete -> one immutable file
                self._place = place
            n += 1
            if r["key"] in self.st.deferred:
                continue
            self.fx.last_wb_deferred = 0
            doc = self.fetch(r)
            if wb_deferred(self.fx, doc):
                self.st.defer(r["key"]); continue
            if doc is None:
                self.st.stats["no_good_capture"] += 1
                self.st.mark(r["key"], "no_good_capture")
                continue
            try:
                rec, why = self.build(r, doc)
            except Exception as e:
                log.exception("build failed %s", r["key"])
                rec, why = None, f"build_error:{type(e).__name__}"
            if rec is None:
                self.st.stats[why] += 1
                self.st.mark(r["key"], why)
                continue
            self.st.add(r["key"], rec)
            self.st.maybe_flush(self.a.flush_secs)
            if n % 50 == 0:
                self.st.save(self.fx)
                log.info("progress fetched=%d staged=%d %s", n, self.st.stats["staged"], dict(self.fx.stats))
        self.st.flush()
        self.st.save(self.fx, final=not STOP["flag"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", type=lambda s: s.split(","), default=["g-reiki", "d1law", "asahikawa", "towada"])
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--cc", action="store_true", help="include CC listings (slow while index.commoncrawl.org 504s)")
    ap.add_argument("--cc-crawls", type=int, default=4)
    ap.add_argument("--chunk", type=int, default=250)
    ap.add_argument("--flush-secs", type=int, default=900)
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--no-newest", action="store_true")
    a = ap.parse_args()
    # g-reiki carries <meta ROBOTS NOARCHIVE>: allowed ONLY in this archive job (Benjamin via coordinator
    # 2026-10-10), every doc tagged source_policy=noarchive_meta. Live g-reiki crawling stays off.
    unknown = [h for h in a.hosts if h not in HOSTS]
    if unknown:
        raise SystemExit(f"unknown hosts {unknown}")
    Job(a).run()


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())
