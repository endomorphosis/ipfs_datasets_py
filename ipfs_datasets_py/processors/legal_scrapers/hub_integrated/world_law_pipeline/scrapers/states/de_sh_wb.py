"""Schleswig-Holstein (DE-SH) state law from Wayback captures of the old juris portal -> iso:DE-SH.

Live: www.gesetze-rechtsprechung.sh.juris.de is unreachable from the box (robots.txt fetch fails, 2026-10-18 PT)
=> disallow-all for live crawling; the current portal is a JS shell anyway. Archive-only.
Discovery: Wayback CDX prefix listing of www.gesetze-rechtsprechung.sh.juris.de/jportal/ filtered to
quelle=jlink pages (collapse timestamp:4 = one row per URL per year), via the shared pipeline/archive module
(lane states; deferrals honoured; truncated listings are retried, never cached as complete).
Only "Gesamtausgabe" pages (whole consolidated norm, docLayoutText) are staged. doc_id sh_juris:<norm key>.
"""
from __future__ import annotations
import json, logging, os, re, sys, time
from urllib.parse import urlsplit, parse_qs
from bs4 import BeautifulSoup

from common import check_guards as _cg  # noqa: E402
from arch_common import clean, archived_rec

POLICY = "archived_robots_disallowed"
BASIS = ("robots.txt unreachable (connection failure on www.gesetze-rechtsprechung.sh.juris.de from the box, "
         "2026-10-18) => disallow-all; archived copies only")
HOST = "www.gesetze-rechtsprechung.sh.juris.de"
PREFIXES = ["aiz=true&max=true", "max=true"]
log = logging.getLogger("de_sh_wb")
BLOCK = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div", "table", "pre", "dt", "dd"]


def de_date(s):
    m = re.search(r"(\d\d)\.(\d\d)\.(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def norm_key(url):
    qs = {k.lower(): v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    k = qs.get("query") or qs.get("docid") or ""
    k = re.sub(r"\s+", " ", k.replace("+", " ")).strip()
    return k, qs.get("max", "").lower() == "true"


class Adapter:
    key = "de_sh_wb"
    tag = "sh_juris-wb"
    platform = "sh_juris"

    def eligible(self, r):
        return None

    def validator(self, doc):
        return b"docLayoutText" in doc.body and b"Gesamtausgabe" in doc.body[:60000]

    def _stopping(self):
        m = sys.modules.get("__main__")
        return bool(getattr(m, "STOP", False))

    def _listing(self, d):
        """Checkpointed listing (2026-10-19 03:xx PT). The 00:11 full run died after 40 fixed attempts while the
        Wayback breaker was open (RuntimeError). Now: no attempt cap; every ArchiveTransient/ArchiveDeferred
        (incl. breaker open, slot busy) sleeps until deferq.not_before_for(e) (the exception's not_before, host
        cool-down or the breaker's next probe) in short STOP-aware slices, then resumes. Progress is persisted in
        <workdir>/listing_partial.json (the urlkey index + per-URL exact captures already listed), so a restart
        resumes instead of re-listing from scratch."""
        from deferq import listing_state, not_before_for
        from archive.core import ArchiveTransient, Capture
        pp = d / "listing_partial.json"
        st = json.loads(pp.read_text()) if pp.exists() else {"idx": None, "per_url": {}, "listing": "ok"}

        def save():
            _cg()
            tmp = pp.with_suffix(".tmp"); tmp.write_text(json.dumps(st)); os.replace(tmp, pp)

        def wait(nb, why):
            nb = max(nb, time.time() + 5)
            log.info("DE-SH listing deferred (%s); sleeping until %s", str(why)[:160],
                     time.strftime("%H:%M:%S", time.localtime(nb)))
            while time.time() < nb and not self._stopping():
                time.sleep(min(5.0, max(0.1, nb - time.time())))
            if self._stopping():
                raise SystemExit("stopped during DE-SH listing (progress saved in listing_partial.json)")

        while True:
            try:
                if st["idx"] is None:
                    # 2026-10-19: urlkey listing over the whole bsshoprod.psml prefix finds 16 jlink URLs (the old
                    # per-prefix timestamp:4 listing found 2); then the newest 3 captures per URL (exact match).
                    idx = self.fx.wb_captures(f"{HOST}/jportal/portal/page/bsshoprod.psml", "prefix",
                                              collapse="urlkey", page_size=5000,
                                              filters=["original:.*quelle=jlink.*"])
                    s0, nb0 = listing_state(idx)
                    if s0 == "retry":
                        wait(nb0, "index listing truncated"); continue
                    if s0 == "final":
                        st["listing"] = "final"
                    st["idx"] = [c.to_dict() for c in idx]
                    save()
                    log.info("DE-SH listing: %d distinct jlink URLs", len(idx))
                for c0 in st["idx"]:
                    u = c0["original_url"]
                    if u in st["per_url"]:
                        continue
                    part = self.fx.wb_captures(u, "exact", limit=-3)
                    s1, nb1 = listing_state(part)
                    if s1 == "retry":
                        wait(nb1, f"exact listing truncated {u[:80]}"); break
                    st["per_url"][u] = [c.to_dict() for c in part] or [c0]
                    save()
                else:
                    caps = [Capture(**c) for u in st["per_url"] for c in st["per_url"][u]]
                    return caps, st["listing"]
            except ArchiveTransient as e:          # incl. ArchiveDeferred / ArchiveBreakerOpen / ArchiveBusy
                wait(not_before_for(e, ["wayback"]), f"{type(e).__name__}: {e}")

    def candidates(self, d):
        cp = d / "candidates.jsonl"
        if not cp.exists():
            caps, st = self._listing(d)
            full, other = {}, {}
            for c in caps:
                if c.status not in (None, 200):
                    continue
                k, mx = norm_key(c.original_url)
                if not k:
                    continue
                (full if mx else other).setdefault(k, []).append(c.to_dict())
            (d / "discovery.json").write_text(json.dumps({"listing": st, "rows": len(caps), "max_keys": len(full),
                                                          "other_keys": len(other)}, indent=1))
            _cg()
            with open(cp.with_suffix(".tmp"), "w") as f:
                for k in sorted(set(full) | set(other)):
                    a = sorted(full.get(k, []), key=lambda c: c["timestamp"], reverse=True)[:3]
                    b = sorted(other.get(k, []), key=lambda c: c["timestamp"], reverse=True)[:2]
                    f.write(json.dumps({"key": k, "caps": a + b, "has_max": bool(a)}) + "\n")
            os.replace(cp.with_suffix(".tmp"), cp)
        for line in cp.open():
            yield json.loads(line)

    def build(self, r, doc):
        s = BeautifulSoup(doc.text(), "lxml")
        pt = s.title.get_text(" ", strip=True) if s.title else ""
        c = s.select_one(".docLayoutText")
        if c is None or "Gesamtausgabe" not in pt + c.get_text(" ", strip=True)[:300]:
            return None, "not_gesamtausgabe"
        tt = s.select_one(".docLayoutTitel")
        title = tt.get_text(" ", strip=True) if tt else ""
        for t in c.select("script, style, noscript, button, form, nav, .docLayoutNachObenAiz"):
            t.decompose()
        for br in c.find_all("br"):
            br.replace_with("\n")
        for t in c.find_all(BLOCK):
            t.append("\n")
        raw = c.get_text("").replace("\xa0", " ")
        text = clean(re.sub(r"[ \t]{2,}", " ", re.sub(r"(?m)^[ \t]+|[ \t]+$", "", raw))).strip()
        if title and not text.startswith(title[:40]):
            text = title + "\n\n" + text
        if len(text) < 300:
            return None, "too_short"
        parts = [p.strip() for p in pt.split("|")]
        abbr = parts[0].replace("Gesetze-Rechtsprechung Schleswig-Holstein", "").strip() if parts else ""
        kind_s = parts[1] if len(parts) > 1 else ""
        title = title or (parts[3] if len(parts) > 3 else r["key"])
        head = text[:2000]
        g = re.search(r"Gültigkeit vom (\d\d\.\d\d\.\d{4})(?: bis (\d\d\.\d\d\.\d{4}))?", head)
        low = title.lower().split("(")[0]
        if re.search(r"verordnung|satzung", low):
            kind, dt = "Verordnung", "regulation"
        elif re.search(r"gesetz|verfassung|staatsvertrag|abkommen|vertrag\b", low):
            kind, dt = "Gesetz", "statute"
        elif re.search(r"erlass|bekanntmachung|richtlinie|vorschrift", low):
            kind, dt = "Verwaltungsvorschrift", "regulation"
        else:
            kind, dt = None, "regulation"
        rec = {
            "place_id": "iso:DE-SH", "country_code": "DE", "doc_id": f"{self.platform}:{r['key']}",
            "source_platform": self.platform, "source_url": doc.original_url, "doc_type": dt, "language": "de",
            "title_native": title[:1000], "consolidated": True, "content_format": "html", "text": text,
            "retrieved_at": doc.fetched_at, "in_force": None, "place_name": "Schleswig-Holstein", "qid": "Q1194",
            "iso_3166_2": "DE-SH", "admin_level": "adm1", "platform": self.platform, "platform_place_id": "SH",
            "source_official": True,
            "source_org": "Land Schleswig-Holstein - Gesetze-Rechtsprechung Schleswig-Holstein (juris portal)",
            "license_note": "Official Schleswig-Holstein law text = amtliches Werk (§ 5 Abs. 1 UrhG); archived copy via Internet Archive Wayback Machine",
        }
        if abbr:
            rec["number"] = abbr
        if g and de_date(g.group(1)):
            rec["effective_date"] = de_date(g.group(1))
        extra = dict(norm_key=r["key"], norm_abbrev=abbr or None, norm_kind=kind, portal_kind=kind_s or None,
                     valid_from=de_date(g.group(1)) if g else None,
                     valid_to=de_date(g.group(2)) if g and g.group(2) else None, page_title=pt[:500])
        rec.update(archived_rec(doc, POLICY, BASIS, **extra))
        return rec, "ok"
