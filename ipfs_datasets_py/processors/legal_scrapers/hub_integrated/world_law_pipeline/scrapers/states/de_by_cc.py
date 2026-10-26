"""Bavaria (DE-BY) state law from Common Crawl WARC records of www.gesetze-bayern.de -> iso:DE-BY.

Live: www.gesetze-bayern.de resets TLS from the box (2026-10-17 PT) => robots unreachable => disallow-all for live
crawling; archive-only. Discovery: CC index prefix listings of www.gesetze-bayern.de/Content/Document/ over the newest
N crawls (shared pipeline/archive, cc_index limiter); fetch: WARC byte ranges from data.commoncrawl.org (cc_data
limiter/breaker). Only the "Gesamtansicht" pages /Content/Document/<Norm>/true (whole consolidated norm) are staged;
norms with only per-article captures are listed in _work/de_by_cc/article_only.tsv (not staged).
doc_id by_gesetze_bayern:<Norm>.
"""
from __future__ import annotations
import json, os, re, time
from urllib.parse import unquote
from bs4 import BeautifulSoup

from archive.core import Capture
from common import check_guards as _cg  # noqa: E402
from arch_common import clean, archived_rec

POLICY = "archived_robots_disallowed"
BASIS = "robots.txt unreachable (TLS reset/EOF on www.gesetze-bayern.de from the box, 2026-10-17) => disallow-all; archived copies only"
RX = re.compile(r"^https?://(?:www\.)?gesetze-bayern\.de/Content/Document/([^/?#]+?)(?:-(\w+))?(/true)?/?(?:\?.*)?$", re.I)
BLOCK = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div", "table", "pre", "dt", "dd"]
N_CRAWLS = int(os.environ.get("BY_CC_CRAWLS", "12"))


def de_date(s):
    m = re.search(r"(\d\d)\.(\d\d)\.(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


class Adapter:
    key = "de_by_cc"
    tag = "by_gesetze_bayern-cc"
    platform = "by_gesetze_bayern"

    def eligible(self, r):
        return None

    def validator(self, doc):
        return b'id="content"' in doc.body or b"id='content'" in doc.body

    def candidates(self, d):
        cp = d / "candidates.jsonl"
        if not cp.exists():
            full, arts = {}, {}
            todo, ok, failed = list(self.fx.cc_crawls()[:N_CRAWLS]), [], []
            for rnd in range(3):                   # the CC index 502/504s a lot: retry failed crawls twice, 5 min apart
                if rnd:
                    if not todo:
                        break
                    # every remaining crawl failed/deferred: sleep until the CC index cool-down ends (min 60 s)
                    from deferq import not_before_for
                    time.sleep(max(60.0, not_before_for(None, ["cc_index"]) - time.time()))
                failed = []
                for cr in todo:
                    before = self.fx.stats.get("cc_query_failed", 0)
                    caps = self.fx.cc_captures("www.gesetze-bayern.de/Content/Document/", "prefix", crawls=[cr])
                    # any retryable .truncated gap (deferred/timeout/breaker mid-listing) = crawl not complete -> retried
                    if self.fx.stats.get("cc_query_failed", 0) > before or (getattr(caps, "truncated", False)
                                                                             and not getattr(caps, "complete_except_permanent", False)):
                        failed.append(cr); continue
                    ok.append(cr)
                    self._collect(caps, full, arts)
                todo = failed
            (d / "discovery.json").write_text(json.dumps({"crawls_ok": ok, "crawls_failed": failed}, indent=1))
            _cg()  # disk floor: pause (common.check_guards) before every write
            with open(cp.with_suffix(".tmp"), "w") as f:

                for n in sorted(full):
                    caps = sorted(full[n], key=lambda c: c["timestamp"], reverse=True)[:3]
                    f.write(json.dumps({"key": n, "newest": caps[0]["timestamp"], "caps": caps}) + "\n")
            os.replace(cp.with_suffix(".tmp"), cp)
            _cg()  # disk floor: pause (common.check_guards) before every write
            with open(d / "article_only.tsv", "w") as f:
                for n in sorted(set(arts) - set(full)):
                    f.write(f"{n}\t{len(arts[n])}\n")
        merged = {}                                   # "%20BayX" / "BayX" -> one norm
        for line in cp.open():
            r = json.loads(line)
            k = unquote(r["key"]).strip()
            if k in merged:
                merged[k]["caps"] = sorted(merged[k]["caps"] + r["caps"], key=lambda c: c["timestamp"], reverse=True)[:3]
            else:
                r["key"] = k; merged[k] = r
        for k in sorted(merged):
            yield merged[k]

    @staticmethod
    def _collect(caps, full, arts):
        for c in caps:
            if c.status != 200:
                continue
            m = RX.match(c.original_url)
            if not m:
                continue
            n = m.group(1)
            if m.group(3) and not m.group(2):
                full.setdefault(n, []).append(c.to_dict())
            elif m.group(2):
                arts.setdefault(n, set()).add(m.group(2))

    def build(self, r, doc):
        s = BeautifulSoup(doc.text(), "lxml")
        pt = s.title.get_text(" ", strip=True) if s.title else ""
        c = s.select_one("#content")
        if c is None:
            return None, "no_content"
        for t in c.select("script, style, noscript, button, form, nav"):
            t.decompose()
        for sn in c.select(".satznr"):               # sentence numbers: "1Die" -> "1 Die"
            sn.replace_with(" " + sn.get_text(strip=True) + " ")
        for br in c.find_all("br"):
            br.replace_with("\n")
        for t in c.find_all(BLOCK):
            t.append("\n")
        raw = c.get_text("").replace("\xa0", " ")
        raw = clean(re.sub(r"[ \t]{2,}", " ", re.sub(r"(?m)^[ \t]+|[ \t]+$", "", raw)))
        head = raw[:1500]
        gilt = re.search(r"Text gilt ab:\s*(\d\d\.\d\d\.\d{4})", head)
        fass = re.search(r"Fassung:\s*(\d\d\.\d\d\.\d{4})", head)
        k = raw.find("Nächstes Dokument")
        text = raw[raw.find("\n", k) + 1:] if 0 <= k < 1500 else raw
        text = re.sub(r"(?m)^(\(\d+[a-z]?\)|\d+[a-z]?)\n(?=\S)", r"\1 ", text)
        text = re.sub(r"(?m)^(\(\d+[a-z]?\)) (\d+[a-z]?)\n(?=\S)", r"\1 \2 ", text).strip()
        if len(text) < 300:
            return None, "too_short"
        t0 = re.sub(r"\s*-\s*Bürgerservice\s*$", "", pt)
        t0 = re.sub(r"^[^:]{1,40}:\s*", "", t0)                         # "AGGVG: ..."
        bayrs = re.search(r"BayRS\s+([\d-]+-[A-Z]+)", t0)
        title = re.sub(r"\s*BayRS\s+[\d-]+-[A-Z]+.*$", "", t0).strip() or r["key"]
        low = title.lower()
        head_l = low.split("(")[0]
        if r["key"].startswith("BayVV_"):
            kind = "Verwaltungsvorschrift"
        elif re.match(r"^(?:bayerisches\s+)?[\w-]*gesetz\b", head_l):
            kind = "Gesetz"
        elif re.search(r"staatsvertrag|abkommen|vertrag\b|übereinkunft|vereinbarung", head_l):
            kind = "Staatsvertrag/Vereinbarung"
        elif re.search(r"gesetz\b|gesetzes\b|^gesetz|verfassung", head_l) and not re.search(r"verordnung", head_l):
            kind = "Gesetz"
        elif re.search(r"verordnung", head_l):
            kind = "Verordnung"
        elif re.search(r"bekanntmachung", head_l):
            kind = "Bekanntmachung"
        else:
            kind = None
        doc_type = "statute" if kind in ("Gesetz", "Staatsvertrag/Vereinbarung") else "regulation"
        rec = {
            "place_id": "iso:DE-BY", "country_code": "DE", "doc_id": f"{self.platform}:{r['key']}",
            "source_platform": self.platform, "source_url": doc.original_url, "doc_type": doc_type, "language": "de",
            "title_native": title[:1000], "consolidated": True, "content_format": "html", "text": text,
            "retrieved_at": doc.fetched_at, "in_force": None, "place_name": "Bayern", "qid": "Q980",
            "iso_3166_2": "DE-BY", "admin_level": "adm1", "platform": self.platform, "platform_place_id": "BY",
            "source_official": True,
            "source_org": "Bayerische Staatskanzlei - BAYERN.RECHT (gesetze-bayern.de, Bürgerservice)",
            "license_note": "Official Bavarian law text = amtliches Werk (§ 5 Abs. 1 UrhG); archived copy via Common Crawl",
        }
        if bayrs:
            rec["number"] = "BayRS " + bayrs.group(1)
        if de_date(fass.group(1) if fass else None):
            rec["adopted_date"] = de_date(fass.group(1))
        if de_date(gilt.group(1) if gilt else None):
            rec["effective_date"] = de_date(gilt.group(1))
        vz = re.search(r"Vollzitat nach RedR:\s*([^\n]+)", text[:3000])
        extra = dict(norm_abbrev=r["key"], norm_kind=kind, text_gilt_ab=rec.get("effective_date"), fassung=rec.get("adopted_date"),
                     vollzitat=vz.group(1)[:1000] if vz else None, page_title=pt[:500])
        rec.update(archived_rec(doc, POLICY, BASIS, **extra))
        return rec, "ok"
