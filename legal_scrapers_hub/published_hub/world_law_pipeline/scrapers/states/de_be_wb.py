"""Berlin (DE-BE) state law from Wayback captures (2019/2020) of the old gesetze.berlin.de juris jportal -> iso:DE-BE.

Coordinator decision 2026-10-18: go ahead after SH; tag each row with the archive copy date, mark it as a possibly
outdated 2019-era version, in_force unknown (None); consolidated=True (the portal served the consolidated text as of
the capture date). Live gesetze.berlin.de does not answer from the box (robots.txt connect timeout, 2026-10-24)
=> disallow-all; the current portal is a JS shell. Discovery: Wayback CDX urlkey listing of
gesetze.berlin.de/jportal/portal/page/bsbeprod.psml filtered to doc.part=G pages (whole norm; S = single section),
then the newest captures per URL. doc_id be_juris:<doc.id>.
"""
from __future__ import annotations
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, logging, os, re, sys, time
from urllib.parse import urlsplit, parse_qs
from bs4 import BeautifulSoup

from common import check_guards as _cg  # noqa: E402
from arch_common import clean, archived_rec

POLICY = "archived_robots_disallowed"
BASIS = ("robots.txt unreachable (connect timeout on gesetze.berlin.de from the box, 2026-10-24) => disallow-all; "
         "archived copies only (2019/2020 Wayback captures of the retired jportal)")
HOST = "gesetze.berlin.de"
PREFIXES = ["aiz=true&max=true", "max=true"]
log = logging.getLogger("de_be_wb")
BLOCK = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div", "table", "pre", "dt", "dd"]


def de_date(s):
    m = re.search(r"(\d\d)\.(\d\d)\.(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def norm_key(url):
    import html as _h
    qs = {k.lower().replace("amp;", ""): v[0] for k, v in parse_qs(urlsplit(_h.unescape(url)).query).items()}
    k = (qs.get("doc.id") or "").strip()
    return k, qs.get("doc.part", "").upper() in ("G", "X", "")


# 2026-10-28 18:15 PDT: also the Gesamtausgabe variant ('... wenn Sie auf die Gesamtausgabe verlinken möchten:') - two
# 'rahmen' pages (7-L-2LPlFV BE, GlBerG BE) were staged as heading + permalink only (published 231608Z/203611Z).
_JLINK = re.compile(r"\n*Diesen Link können Sie kopieren und verwenden, wenn Sie [^\n:]{0,80}?verlinken möchten:"
                    r"\s*\n?\s*\S*", re.I)
_EINZEL = re.compile(r"(?m)^\|?\s*zur Einzelansicht\s*$\n?")


_OBEN = re.compile(r"(?m)^\|?\s*zum Seitenanfang\s*$\n?")
# Gesamtausgabe pages: 'Nichtamtliches Inhaltsverzeichnis' + 'Titel' + one TOC line per unit ending in its valid-from date
_TOC = re.compile(r"Nichtamtliches Inhaltsverzeichnis[ \t]*\n+(?:Titel[ \t]*\n+)?(?:[^\n]*\d\d\.\d\d\.\d{4}[ \t]*\n)+\n*")
_GESAMT = re.compile(r"aktuellste verfügbare Fassung der Gesamtausgabe")
# 2026-10-28 15:15 PDT: suffix may contain "-" (pAnlage-G6, pAnlage5-Art...) and IVZ / Protokoll units; before this a
# Gesamtausgabe captured via such a unit kept the unit key as root -> same norm staged twice (7-L-2LPlFV BE).
_ROOT = re.compile(r"^(jlr-.*?BE(?:\d{4})?(?:V\d+)?)(?:[pP]\S*|rahmen|Anlage\S*|ELS|G\d\S*|IVZ|Protokoll\S*|Art\S*)?$")
SEEN = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/states/_work/de_be_wb/gesamt_seen.tsv")


def norm_root(key):
    m = _ROOT.match(key or "")
    return m.group(1) if m else key


def _seen_load():
    d = {}
    if os.path.exists(SEEN):
        for line in open(SEEN):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2:
                d[p[0]] = p[1]
    return d


def strip_portal(text):
    """2026-10-28: drop jportal chrome left inside .docLayoutText: the permalink trailer ('Diesen Link können Sie
    kopieren ...' + jlink URL) and the '| zur Einzelansicht' navigation lines of Gesamtausgabe pages.
    r3 (2026-10-28 09:xx): also 'zum Seitenanfang' nav lines and the 'Nichtamtliches Inhaltsverzeichnis' TOC block."""
    text = _JLINK.sub("\n", text)
    text = _EINZEL.sub("", text)
    text = _OBEN.sub("", text)
    text = _TOC.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# 2026-10-28 21:05 PDT: 'rahmen' (frame) pages often carry only heading + 'Änderungen' amendment list (StrGBErahmen) or
# heading + Gesamtausgabe permalink (7-L-2LPlFVBErahmen, GlBerGBE2006rahmen). Keep a frame page only if, after removing
# heading, TOC, amendment list and portal links, real statute text remains (a § / Art. provision line and >= 400 chars).
_AEND_ITEM = re.compile(r"(?m)^\s*\d+\.\s*\n+\s*[^\n]*(?:geändert|eingefügt|aufgehoben|ersetzt|neu gefasst|berichtigt|"
                        r"Änderung|gestrichen|angefügt)[^\n]*\n?")
_AEND_HEAD = re.compile(r"(?m)^\s*(?:Änderungen|Änderungsübersicht|Fußnoten)\s*$\n?")
_URL = re.compile(r"https?://\S+")
_PROV = re.compile(r"(?m)^\s*(?:§{1,2}\s*\d+\w*|Art(?:ikel|\.)\s*[0-9IVXLC]+\w*|Anlage\b|Nummer\s*\d+|Teil\s+\d|"
                   r"Abschnitt\s+\d|Kapitel\s+\d)")


def frame_substance(body):
    b = _AEND_ITEM.sub("", body)
    b = _AEND_HEAD.sub("", b)
    b = _URL.sub("", b)
    b = re.sub(r"\n{3,}", "\n\n", b).strip()
    return b, bool(_PROV.search(b))


class Adapter:
    key = "de_be_wb"
    tag = "be_juris-wb"
    platform = "be_juris"

    def eligible(self, r):
        return None

    def validator(self, doc):
        return b"docLayoutText" in doc.body

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
            log.info("DE-BE listing deferred (%s); sleeping until %s", str(why)[:160],
                     time.strftime("%H:%M:%S", time.localtime(nb)))
            while time.time() < nb and not self._stopping():
                time.sleep(min(5.0, max(0.1, nb - time.time())))
            if self._stopping():
                raise SystemExit("stopped during DE-BE listing (progress saved in listing_partial.json)")

        while True:
            try:
                if st["idx"] is None:
                    # 2026-10-19: urlkey listing over the whole bsshoprod.psml prefix finds 16 jlink URLs (the old
                    # per-prefix timestamp:4 listing found 2); then the newest 3 captures per URL (exact match).
                    # 2026-10-25: paged CDX listing with the resumeKey + rows persisted per page in
                    # <workdir>/cdx_parts/ (was: one wb_captures() call that lost all pages on every deferral and
                    # looped on page 6 for hours). See _cdx_paged().
                    idx = self._cdx_paged(d)
                    st["idx"] = [c.to_dict() for c in idx]
                    save()
                    log.info("DE-BE listing: %d distinct jlink URLs", len(idx))
                for c0 in st["idx"]:
                    u = c0["original_url"]
                    if u in st["per_url"] or True:   # Berlin: one urlkey capture per URL variant is enough
                        st["per_url"].setdefault(u, [c0])
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

    def _cdx_paged(self, d):
        """Resumable Wayback CDX urlkey listing of the bsbeprod.psml prefix (2026-10-25).

        Same query as fx.wb_captures(url, "prefix", collapse="urlkey", page_size=5000, filters=[doc.id]) and the
        same archive CDX cache keys (so pages already fetched by earlier runs are reused), but each finished page is
        saved to <workdir>/cdx_parts/part_NNNN.json together with the next resumeKey in cdx_parts/state.json. On
        ArchiveDeferred/timeout the exception propagates to _listing() (which sleeps until not_before) and the
        next attempt resumes at the saved resumeKey instead of page 1. After a timeout the page size is halved
        (min 500) for the following pages, since the slow part is the server-side scan. All requests go through
        the shared archive module (ArchiveFetcher._get: box-wide wayback slot, cool-downs, breaker)."""
        from urllib.parse import quote
        from archive import ratelimit
        from archive.core import WB_CDX, Capture, ArchiveError, ArchiveTransient, ArchiveBreakerOpen, ArchiveTimeout
        pd = d / "cdx_parts"
        pd.mkdir(exist_ok=True)
        sp = pd / "state.json"
        cs = json.loads(sp.read_text()) if sp.exists() else {"next": 0, "resume": None, "done": False,
                                                             "page_size": 5000}

        def save_cs():
            _cg()
            tmp = sp.with_suffix(".tmp"); tmp.write_text(json.dumps(cs)); os.replace(tmp, sp)

        base = [("url", f"{HOST}/jportal/portal/page/bsbeprod.psml"), ("matchType", "prefix"), ("output", "json"),
                ("fl", "timestamp,original,mimetype,statuscode,digest,length"), ("filter", "statuscode:200"),
                ("filter", "original:.*doc[.]id=.*"), ("collapse", "urlkey")]
        while not cs["done"]:
            if self._stopping():
                raise SystemExit("stopped during DE-BE listing (progress saved in cdx_parts/)")
            ps = int(cs.get("page_size") or 5000)
            p = base + [("limit", str(ps)), ("showResumeKey", "true")]
            if cs["resume"]:
                p.append(("resumeKey", cs["resume"]))
            q = "&".join(f"{k}={quote(v, safe=':/*,!')}" for k, v in p)
            key = f"WB|{q}"
            data = self.fx.cache.cdx_get(key, self.fx.cdx_ttl)
            if data is None:
                if not ratelimit.wayback_available():
                    raise ArchiveBreakerOpen("wayback breaker open (box-wide); skipped")
                try:
                    r = self.fx._get("wayback", f"{WB_CDX}?{q}", ok_status=(200,))
                except ArchiveTimeout:
                    if ps > 500:
                        cs["page_size"] = max(500, ps // 2); save_cs()
                        log.info("DE-BE cdx page %d timed out at limit=%d; next try limit=%d",
                                 cs["next"], ps, cs["page_size"])
                    raise
                if r.status_code != 200:
                    raise ArchiveError(f"wayback cdx {r.status_code}", status=r.status_code,
                                       permanent=True if r.status_code == 403 else None)
                try:
                    data = r.json() if r.text.strip() else []
                except ValueError:
                    raise ArchiveTransient("wayback cdx non-json", kind="bad_response")
                self.fx.cache.cdx_put(key, data)
            rows = data[1:] if data and data[0] and data[0][0] == "timestamp" else data
            nxt = None
            if len(rows) >= 2 and rows[-2] == [] and len(rows[-1]) == 1:
                nxt = rows[-1][0]; rows = rows[:-2]
            rows = [x[:6] for x in rows if len(x) >= 6]
            _cg()
            pf = pd / f"part_{cs['next']:04d}.json"
            tmp = pf.with_suffix(".tmp"); tmp.write_text(json.dumps(rows)); os.replace(tmp, pf)
            cs["next"] += 1; cs["resume"] = nxt; cs["done"] = not nxt
            save_cs()
            log.info("DE-BE cdx page %d saved: %d rows (limit=%d)%s", cs["next"] - 1, len(rows), ps,
                     "" if nxt else " - listing complete")
        out = []
        for i in range(cs["next"]):
            for ts, orig, mime, stc, dg, ln in json.loads((pd / f"part_{i:04d}.json").read_text()):
                out.append(Capture("wayback", "wayback", ts, orig, int(stc) if str(stc).isdigit() else None,
                                   mime, dg, int(ln) if str(ln).isdigit() else None))
        log.info("DE-BE cdx listing: %d rows from %d saved pages", len(out), cs["next"])
        return out

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
                for k in sorted(set(full)):   # Berlin: whole-norm pages only (doc.part G/X/blank); S/R = single sections
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
        if c is None:
            return None, "no_doc_text"
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
        text = strip_portal(text)
        if title and not text.startswith(title[:40]):
            text = title + "\n\n" + text
        body = text[len(title):].strip() if title and text.startswith(title) else text
        core = re.split(r"\n\s*Fußnoten\b", body)[0].strip()   # 18:15 PDT: heading + footnote only (RiGBE2011pG7)
        if len(body) < 150 or len(core) < 120:
            return None, "heading_only"   # 2026-10-28: section/heading pages ('Fünfter Abschnitt Gemeinsame Vorschriften')
        if len(text) < 300:
            return None, "too_short"
        if r["key"].endswith("rahmen") or re.search(r"(?m)^\s*Änderungen\s*$", body[:400]):
            sub, prov = frame_substance(core)
            if len(sub) < 400 or not prov:
                return None, "frame_no_body"   # 21:05 PDT: heading + amendment list / permalink only
        parts = [p.strip() for p in pt.split("|")]
        # r3 2026-10-28: a doc.part=X capture of ANY unit serves the whole norm (Gesamtausgabe) -> one row per norm:
        # doc_id be_juris:<norm root>, later X captures of other units of the same norm are dropped (persisted map).
        gesamt = bool(_GESAMT.search(text[:600])) or any(p == "Gesamtausgabe" for p in parts)
        root = norm_root(r["key"]) if gesamt else None
        if gesamt:
            seen = _seen_load()
            if seen.get(root, r["key"]) != r["key"]:
                return None, "dup_gesamtausgabe"
        abbr = re.sub(r"^VIS BE\s*", "", parts[0]).strip() if parts else ""
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
            "place_id": "iso:DE-BE", "country_code": "DE", "doc_id": f"{self.platform}:{root or r['key']}",
            "source_platform": self.platform, "source_url": doc.original_url, "doc_type": dt, "language": "de",
            "title_native": title[:1000], "consolidated": True, "content_format": "html", "text": text,
            "retrieved_at": doc.fetched_at, "in_force": None, "place_name": "Berlin", "qid": "Q64",
            "iso_3166_2": "DE-BE", "admin_level": "adm1", "platform": self.platform, "platform_place_id": "BE",
            "source_official": True,
            "source_org": "Land Berlin - Vorschriften- und Informationssystem Berlin (VIS BE, juris jportal; archived copy)",
            "license_note": "Official Berlin law text = amtliches Werk (§ 5 Abs. 1 UrhG); archived 2019/2020 copy via Internet Archive Wayback Machine - possibly outdated",
        }
        if abbr:
            rec["number"] = abbr
        if g and de_date(g.group(1)):
            rec["effective_date"] = de_date(g.group(1))
        extra = dict(norm_key=r["key"], norm_abbrev=abbr or None, norm_kind=kind, portal_kind=kind_s or None,
                     valid_from=de_date(g.group(1)) if g else None,
                     valid_to=de_date(g.group(2)) if g and g.group(2) else None, page_title=pt[:500],
                     possibly_outdated=True, version_note=f"text as served by the retired portal on {doc.archive_timestamp[:10]} (2019/2020 capture); later amendments not reflected",
                     archive_copy_date=doc.archive_timestamp[:10])
        rec.update(archived_rec(doc, POLICY, BASIS, **extra))
        rec["archive_copy_date"] = doc.archive_timestamp[:10]
        rec["in_force"] = None
        if gesamt:
            rec["extra_metadata"]["gesamtausgabe"] = True
            rec["extra_metadata"]["norm_root"] = root
            if root not in _seen_load():
                with open(SEEN, "a") as f:
                    f.write(f"{root}\t{r['key']}\n")
        return rec, "ok"
