"""Full-coverage adapters (states lane). Each adapter:
  key, cc, place, platform        identifiers
  discover(sess) -> [item]        item = {"doc_id", "url", **meta}; doc_id is final (dedupe before fetching)
  fetch(sess, item) -> (rec|None, reason)
  min_chars                        QC floor for text length
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import hashlib, json, re, time
from datetime import datetime, timezone
from lxml import etree, html as LH

from common import utcnow, pdf_has_text, queue_scanned_pdf
from sources import _text, PLACES as _P0, OntarioELaws as _ON, ManitobaCCSM as _MB

PLACES = dict(_P0)
PLACES.update({
    "AU-TAS": dict(place_id="iso:AU-TAS", country_code="AU", place_name="Tasmania", qid="Q34366", iso_3166_2="AU-TAS", admin_level="adm1"),
    "AU-VIC": dict(place_id="iso:AU-VIC", country_code="AU", place_name="Victoria", qid="Q36687", iso_3166_2="AU-VIC", admin_level="adm1"),
    "AU-NT": dict(place_id="iso:AU-NT", country_code="AU", place_name="Northern Territory", qid="Q3235", iso_3166_2="AU-NT", admin_level="adm1"),
    "AU-ACT": dict(place_id="iso:AU-ACT", country_code="AU", place_name="Australian Capital Territory", qid="Q3258", iso_3166_2="AU-ACT", admin_level="adm1"),
    "CA-NB": dict(place_id="iso:CA-NB", country_code="CA", place_name="New Brunswick", qid="Q1965", iso_3166_2="CA-NB", admin_level="adm1"),
    "CA-NL": dict(place_id="iso:CA-NL", country_code="CA", place_name="Newfoundland and Labrador", qid="Q2003", iso_3166_2="CA-NL", admin_level="adm1"),
    "CA-PE": dict(place_id="iso:CA-PE", country_code="CA", place_name="Prince Edward Island", qid="Q1979", iso_3166_2="CA-PE", admin_level="adm1"),
    "CA-NS": dict(place_id="iso:CA-NS", country_code="CA", place_name="Nova Scotia", qid="Q1952", iso_3166_2="CA-NS", admin_level="adm1"),
    "CA-SK": dict(place_id="iso:CA-SK", country_code="CA", place_name="Saskatchewan", qid="Q1989", iso_3166_2="CA-SK", admin_level="adm1"),
    "CA-NT": dict(place_id="iso:CA-NT", country_code="CA", place_name="Northwest Territories", qid="Q2007", iso_3166_2="CA-NT", admin_level="adm1"),
})
BOILER = ("Skip to main content", "Unknown Page", "Just a moment", "JavaScript is required", "enable JavaScript",
          "Page not found", "Access denied", "Accessibility Disclaimer Copyright Privacy")


def base(place, **kw):
    r = dict(PLACES[place]); r.update(retrieved_at=utcnow(), source_official=True, **kw)
    return r


def _ids_from_cdx(path, rx, prefix):
    out = set()
    for line in open(path, encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        u = line.split()[-1]
        p = re.sub(r"^https?://(www\.)?ontario\.ca(:\d+)?", "", u).split("?")[0].split("#")[0].rstrip("/")
        if p.startswith(prefix):
            i = p[len(prefix):]
            if rx.match(i):
                out.add(i)
    return sorted(out)


# ------------------------------------------------------------------ Ontario
class OntarioFull:
    key, cc, place, platform, min_chars = "ca_on_elaws", "CA", "CA-ON", "ca_on_elaws", 150
    DATA = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data")
    ST_RX = re.compile(r"^(?:\d{2}[a-z]\d{2,3}[a-z]?|pr\d{5})$")      # consolidated statutes + private acts
    RG_RX = re.compile(r"^\d{6}$")                                      # consolidated regs (900194, 050123)

    def discover(self, sess):
        items = [{"doc_id": f"on_statute:{i}", "url": f"https://www.ontario.ca/laws/statute/{i}", "kind": "statute"}
                 for i in _ids_from_cdx(f"{self.DATA}/on_statute_cdx_full.txt", self.ST_RX, "/laws/statute/")]
        try:
            items += [{"doc_id": f"on_regulation:{i}", "url": f"https://www.ontario.ca/laws/regulation/{i}", "kind": "regulation"}
                      for i in _ids_from_cdx(f"{self.DATA}/on_regulation_cdx_full.txt", self.RG_RX, "/laws/regulation/")]
        except FileNotFoundError:
            pass
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        doc = LH.fromstring(r.content)
        title = (doc.findtext(".//title") or "").strip().strip('"').strip()
        body = doc.xpath('//div[starts-with(@class,"WordSection")]')
        legacy = False
        if body:
            text = "\n\n".join(t for t in (_text(b) for b in body) if t)
        else:   # older e-Laws template: <p class="...-e"> paragraphs (English), no WordSection wrapper
            ps = doc.xpath('//p[substring(@class, string-length(@class) - 1) = "-e"]')
            if not ps:
                return None, "no_body"
            text = "\n".join(t for t in (re.sub(r"\s+", " ", p.text_content()).strip() for p in ps) if t)
            legacy = True
            mm = re.match(r"^(.*?),?\s*(\d{4})\s*-\s*Chap\.\s*(Pr\d+)", title)
            if mm:
                title = f"{mm.group(1)}, {mm.group(2)}, S.O. {mm.group(2)}, c. {mm.group(3)}"
        head = text[:2500]
        if re.search(r"Note: This (?:Act|Regulation) (?:was|is|has been) (?:repealed|revoked)", head):
            return None, "repealed_or_revoked"
        consolidated = "Consolidation Period" in head
        if it["kind"] == "statute":
            if not consolidated and not it["doc_id"].startswith("on_statute:pr") and not legacy:
                return None, "source_law"
            m = re.match(r"^(.*?),\s*((?:R\.S\.O\.|S\.O\.)\s*\d{4},\s*c\.\s*[\w.]+)", title)
            name, number = (m.group(1), m.group(2)) if m else (title, None)
            if legacy and name and re.search(r", \d{4}$", name) is None and number and "Pr" in number:
                pass
            dt = "statute"
        else:
            if not consolidated:
                return None, "source_law"
            m = re.match(r"^((?:R\.R\.O\.\s*\d{4},\s*Reg\.\s*[\w.]+)|(?:O\.\s*Reg\.\s*[\w.]+/\d{2,4}))\s*[:\-–]\s*(.+)$", title)
            number, name = (m.group(1), m.group(2).strip()) if m else (None, title)
            if name and name.isupper():
                name = _smart_title(name)
            dt = "regulation"
        yr = re.search(r"\b(1[89]\d\d|20\d\d)\b", number or "") or (re.search(r"/(\d{2})$", number or "") if number else None)
        year = yr.group(1) if yr else None
        if year and len(year) == 2:
            year = ("19" if int(year) > 50 else "20") + year
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type=dt,
                    language="en", title_native=name, number=number, adopted_date=year, in_force=True if consolidated else None,
                    consolidated=consolidated, content_format="html", text=text, source_policy=pol,
                    source_org="King's Printer for Ontario (e-Laws)",
                    license_note="Government of Ontario legal materials (statutes, regulations) - reproduction permitted (ontario.ca/page/copyright-information)",
                    platform="ca_on_elaws", platform_place_id="ON",
                    elaws_kind=("private_act" if it["doc_id"].startswith("on_statute:pr") else "consolidated"), elaws_legacy_template=legacy), "ok"


# ------------------------------------------------------------------ Manitoba
class ManitobaFull:
    key, cc, place, platform, min_chars = "ca_mb_ccsm", "CA", "CA-MB", "ca_mb_ccsm", 80

    def discover(self, sess):
        items, seen = [], set()
        r, _ = sess.get("https://web2.gov.mb.ca/laws/statutes/index_ccsm.php")
        for h in re.findall(r'href="ccsm/([a-z0-9\-]+)\.php', r.text):
            if h not in seen:
                seen.add(h); items.append({"doc_id": f"mb_ccsm:{h}", "kind": "statute",
                                           "url": f"https://web2.gov.mb.ca/laws/statutes/ccsm/{h}.php?lang=en"})
        r, _ = sess.get("https://web2.gov.mb.ca/laws/regs/index.php")
        for h in re.findall(r'href="(?:\.\./regs/)?current/([0-9a-z\-]+)\.php', r.text):
            if h not in seen:
                seen.add(h); items.append({"doc_id": f"mb_reg:{h}", "kind": "regulation",
                                           "url": f"https://web2.gov.mb.ca/laws/regs/current/{h}.php?lang=en"})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        if it["kind"] == "statute":
            rec = _MB().parse(it["url"], r)
        else:
            rec = _MB().parse(it["url"].replace("/regs/current/", "/statutes/ccsm/"), r)  # same page template
            if rec:
                rec["source_url"] = it["url"]; rec["doc_id"] = it["doc_id"]; rec["doc_type"] = "regulation"
                t = (LH.fromstring(r.content).findtext(".//title") or "").strip()
                m = re.match(r"^(.*?),\s*(M\.R\.\s*[\w/\-]+)$", t)
                rec["title_native"], rec["number"] = (m.group(1), m.group(2)) if m else (t, None)
        if not rec:
            return None, "no_body"
        if re.search(r"^\s*(?:This (?:Act|regulation) (?:has been|was) (?:repealed|revoked))", rec["text"][:600], re.I):
            return None, "repealed_or_revoked"
        rec["source_policy"] = pol
        return rec, "ok"


# ------------------------------------------------------------------ PCO "EnAct" platform (QLD, TAS)
class PCOFull:
    BLOCK = {"txt", "heading", "shorttitle", "longtitle", "block", "li", "row", "entry", "p", "def", "hdg", "note",
             "TXT", "HEADING", "SHORTTITLE", "LONGTITLE", "BLOCK", "LI", "ROW", "ENTRY", "P", "DEF", "HDG", "NOTE", "HEADER",
             "TEXT", "HEADNOTE", "TITLE", "ENACTINGWORDS", "DEFINITION", "PARAGRAPH", "SUBPARAGRAPH", "HOWAFFECTED", "ASSENTDATE"}
    min_chars = 150

    def _q(self, sess, expr, start, count):
        import urllib.parse as U
        q = {"ds": self.DS, "start": start, "count": count, "subset": "browse", "expression": expr}
        if self.SORT:
            q.update(sortField=self.SORT, sortDirection="asc")
        r, _ = sess.get(f"{self.HOST}/projectdata?{U.urlencode(q)}")
        if r.status_code != 200:
            raise RuntimeError(f"projectdata {r.status_code}: {r.text[:200]}")
        return json.loads(r.content)

    def discover(self, sess):
        pit = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        items, seen = [], set()
        for kind, expr in self.EXPRS:
            start, total = 1, None
            while total is None or start <= total:
                d = self._q(sess, expr.format(pit=pit), start, 200)
                total = d["totalCount"]["__value__"]
                for row in d["data"]:
                    v = {k: (x.get("__value__") if isinstance(x, dict) else x) for k, x in row.items()}
                    lid = v["id"]
                    if lid in seen:
                        continue
                    seen.add(lid)
                    items.append({"doc_id": f"{self.PFX}:{lid}", "url": f"{self.HOST}/view/xml/inforce/current/{lid}",
                                  "kind": kind, "meta": v})
                start += 200
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        root = etree.fromstring(r.content, parser=etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, recover=True))
        if root is None:
            return None, "bad_xml"
        for c in list(root.iter(etree.Comment)):
            c.getparent().remove(c)
        for e in root.iter():
            if isinstance(e.tag, str) and e.tag in self.BLOCK:
                e.tail = "\n" + (e.tail or "")
        txt = " ".join(root.itertext())
        txt = re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", txt)).strip()
        m = it["meta"]; lid = m["id"]
        dt = "statute" if it["kind"] == "act" else "regulation"
        yr, no = m.get("year"), m.get("no")
        number = (f"{'Act' if dt == 'statute' else self.SL_LABEL} No. {int(no)} of {yr}" if (no or "").isdigit() and yr else lid)
        d10 = lambda k: (m.get(k) or "")[:10] or None
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type=dt,
                    language="en", title_native=m.get("title") or m.get("title_v"), number=number,
                    adopted_date=d10("assent.date") or yr, published_date=d10("publication.date"),
                    effective_date=d10("first.valid.date"), in_force=True, consolidated=True, content_format="xml",
                    text=txt, source_policy=pol, source_org=self.ORG, license_note=self.LICENSE, platform=self.platform,
                    platform_place_id=self.place.split("-")[1], version_series_id=m.get("version.series.id"),
                    version_desc_id=m.get("version.desc.id"), html_view_url=it["url"].replace("/view/xml/", "/view/html/"),
                    instrument_type=m.get("type")), "ok"


class QLDFull(PCOFull):
    key, cc, place, platform = "au_qld_leg", "AU", "AU-QLD", "au_qld_legislation"
    HOST, DS, SORT, PFX, SL_LABEL = "https://www.legislation.qld.gov.au", "OQPC-BrowseDataSource", "sort.title", "qld", "SL"
    EXPRS = [("act", "Repealed=N AND PrintType=act.reprint AND PitValid=@pointInTime({pit})"),
             ("sl", "Repealed=N AND PrintType=reprint AND PitValid=@pointInTime({pit})")]
    ORG = "Queensland Parliamentary Counsel (OQPC)"
    LICENSE = "CC BY 4.0 (legislation.qld.gov.au/copyright)"


class TASFull(PCOFull):
    key, cc, place, platform = "au_tas_leg", "AU", "AU-TAS", "au_tas_legislation"
    HOST, DS, SORT, PFX, SL_LABEL = "https://www.legislation.tas.gov.au", "EnAct-BrowseDataSource", None, "tas", "SR"
    EXPRS = [("act", "PrintType=act.reprint AND Repealed<>Y AND Amending<>pure AND PitValid=@pointInTime({pit})"),
             ("sl", "PrintType=reprint AND Repealed<>Y AND Amending<>pure AND PitValid=@pointInTime({pit})")]
    ORG = "Office of Parliamentary Counsel, Tasmania"
    LICENSE = ("CC BY 4.0 (legislation.tas.gov.au/copyrightanddisclaimer); attribution: Sourced from the Tasmanian Legislation "
               "website at <retrieved_at date>. For the latest information on Tasmanian Government legislation please go to www.legislation.tas.gov.au")


ADAPTERS = {c.key: c for c in (OntarioFull, ManitobaFull, QLDFull, TASFull)}


# ------------------------------------------------------------------ Northern Territory (PDF text layer)
class NTFull:
    key, cc, place, platform, min_chars = "au_nt_leg", "AU", "AU-NT", "au_nt_legislation", 150
    HOST = "https://legislation.nt.gov.au"
    LISTS = [("act", "/en/LegislationPortal/Acts/By-Title?status=inforce"), ("sl", "/en/LegislationPortal/Subordinate-Legislation/By-Title?status=inforce")]

    def discover(self, sess):
        items, seen = [], set()
        for kind, path in self.LISTS:
            r, _ = sess.get(self.HOST + path)
            for slug in re.findall(r'href="/(?:en/)?Legislation/([A-Za-z0-9\-_.()%]+)"', r.text):
                if slug in seen:
                    continue
                seen.add(slug)
                items.append({"doc_id": f"nt:{slug.lower()}", "url": f"{self.HOST}/en/Legislation/{slug}", "kind": kind})
        return items

    @staticmethod
    def _field(t, label):
        m = re.search(r"<label>\s*" + re.escape(label) + r"\s*</label>\s*<span>(.*?)</span>", t, re.S)
        return LH.fromstring("<x>" + m.group(1) + "</x>").text_content().strip() if m and m.group(1).strip() else None

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        t = r.text
        status = self._field(t, "Status:")
        if not status or "in force" not in status.lower():
            return None, f"status:{(status or 'none')[:20]}"
        m = re.search(r'href="(https://legislation\.nt\.gov\.au/api/sitecore/[A-Za-z]+/PDF\?id=\d+)"', t)
        if not m:
            return None, "no_pdf_link"
        doc = LH.fromstring(r.content)
        h = re.sub(r"\s+", " ", " ".join(doc.xpath('//*[contains(@class,"legislation-title") or self::h1 or self::h2]//text()'))).strip()
        mt = re.search(r"Details\s+(.+?)\s+(?:Act No|Subordinate Legislation No|SL No|Number)\s*:", re.sub(r"\s+", " ", doc.text_content()))
        title_up = (mt.group(1).strip() if mt else h) or it["url"].rsplit("/", 1)[-1].replace("-", " ")
        pdf_url = m.group(1)
        pr, pol2 = sess.get(pdf_url)
        if pr.status_code != 200 or not pr.content.startswith(b"%PDF"):
            return None, f"pdf_http_{pr.status_code}"
        ok, txt = pdf_has_text(pr.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, pdf_url, pol2)
            return None, "scanned_pdf_queued"
        txt = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", txt.replace("\f", "\n"))).strip()
        title = title_up.title() if title_up.isupper() else title_up
        title = re.sub(r"\b(Of|And|The|For|To|In|On|By|Under|With)\b", lambda x: x.group(1).lower(), title)
        title = title[0].upper() + title[1:]
        yr = re.search(r"(\d{4})\s*$", title)
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=pdf_url, doc_type="statute" if it["kind"] == "act" else "regulation",
                    language="en", title_native=title, number=self._field(t, "Act No:") or self._field(t, "Reprint:"),
                    adopted_date=(yr.group(1) if yr else None), in_force=True, consolidated=True, content_format="pdf_text",
                    text=txt, source_policy=pol, source_org="Northern Territory Government (NT Legislation)",
                    license_note="NT copyright policy (legislation.nt.gov.au/en/Footer/Terms-of-Use): legislation may be reproduced if not presented as official, without NT arms, accurately",
                    platform=self.platform, platform_place_id="NT", detail_url=it["url"], title_upper=title_up,
                    reprint=self._field(t, "Reprint:"), agency=self._field(t, "Agency:")), "ok"


ADAPTERS[NTFull.key] = NTFull


# ------------------------------------------------------------------ block-aware HTML -> text
_BLK = {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table", "section", "article", "blockquote", "pre", "dd", "dt", "ul", "ol"}


def btext(node):
    """Text with a newline after every block element (lxml node is modified in place)."""
    for bad in node.xpath(".//script|.//style|.//noscript|.//button"):
        bad.drop_tree()
    for el in node.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.split("}")[-1].lower()
        if tag in _BLK:
            el.tail = "\n" + (el.tail or "")
        elif tag == "br":
            el.tail = "\n" + (el.tail or "")
        elif tag in ("td", "th"):
            el.tail = "\t" + (el.tail or "")
    lines = [re.sub(r"[ \t\r\f\v\u00a0]+", " ", ln).strip() for ln in node.text_content().split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln); blank = False
        elif not blank and out:
            out.append(""); blank = True
    return "\n".join(out).strip()


# ------------------------------------------------------------------ New Brunswick (laws.gnb.ca, Irosoft Cyberlex)
class NBFull:
    key, cc, place, platform, min_chars = "ca_nb_laws", "CA", "CA-NB", "ca_nb_laws_gnb", 80
    HOST = "https://laws.gnb.ca"
    LICENSE = ("New Brunswick King's Printer copyright notice: anyone may reproduce the Acts and regulations at no charge and without "
               "permission for non-commercial use (incl. research) provided due diligence ensures accuracy; commercial reproduction "
               "licensed on conditions; not an official version")

    def discover(self, sess):
        items, seen = [], set()
        for corpus, pfx, kind in (("statutes", "cs", "statute"), ("regs", "cr", "regulation")):
            r, _ = sess.get(f"{self.HOST}/en/chapters?corpus={corpus}&selection=all")
            for ref in re.findall(r'href="/en/document/' + pfx + r'/([^"]+)"', r.text):
                if ref in seen:
                    continue
                seen.add(ref)
                did = re.sub(r"[^a-z0-9.\-]+", "_", requests_unquote(ref).lower()).strip("_")
                items.append({"doc_id": f"nb_{pfx}:{did}", "url": f"{self.HOST}/en/document/{pfx}/{ref}", "kind": kind,
                              "number": requests_unquote(ref)})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        doc = LH.fromstring(r.content.decode("utf-8", "replace"))
        m = doc.xpath('//*[@id="mainContent-document"]')
        if not m:
            return None, "no_body"
        cls = m[0].get("class") or ""
        title = " ".join(" ".join(m[0].xpath('.//*[contains(@class,"long-title-document")][1]//text()')).split())
        num = " ".join(" ".join(m[0].xpath('.//*[contains(@class,"id-document")][1]//text()')).split()) or it["number"]
        full = " ".join(doc.text_content().split())
        cur = re.search(r"Current to (\d{1,2} \w+ \d{4})", full)
        for lab in m[0].xpath('.//span[contains(concat(" ", normalize-space(@class), " "), " label ")]'):
            lab.tail = " " + (lab.tail or "")
        text = btext(m[0])
        if re.search(r"^\s*(?:Repealed|Abrogé)\b", text[:400]) or "repealed" in cls.split():
            return None, "repealed_or_revoked"
        if not title:
            title = text.split("\n", 1)[0]
        yr = re.search(r"\b(1[89]\d\d|20\d\d)\b", num) or re.search(r"^(\d{2})-", num)
        year = yr.group(1) if yr else None
        if year and len(year) == 2:
            year = ("19" if int(year) > 30 else "20") + year
        num = re.sub(r"^(?:CHAPTER|REGULATION)\s+", "", num, flags=re.I).strip()
        if it["kind"] == "regulation" and num.lower().startswith("rule"):
            num_disp = "Rules of Court, " + num.replace("-", " ").title()
            title = f"{num_disp} - {title.title() if title.isupper() else title}"
        elif it["kind"] == "regulation":
            num_disp = f"N.B. Reg. {num}" if re.match(r"^\d{2,4}-\d+$", num) else num
            mc = re.search(r"may be cited as (?:the )?(.+?)(?:\.\s|\.$|\n)", text[:3000])
            if mc and len(mc.group(1)) < 250:
                title = mc.group(1).strip()
            elif title.upper() in ("NEW BRUNSWICK", "") or title == text.split("\n", 1)[0] and title.isupper() and "RULE" not in title:
                mu = re.search(r"under the\s+(.+?)\n", text[:800])
                title = f"Regulation {num}" + (f" under the {mu.group(1).strip()}" if mu else "")
            if title.isupper():
                title = title.title()
        else:
            num_disp = f"S.N.B. {num}" if re.match(r"^\d{4}, c\.", num) else num
            ma = re.search(r"Assented to \w+ \d{1,2}, (\d{4})", text[:1500])
            if ma and not year:
                year = ma.group(1)
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type=it["kind"],
                    language="en", title_native=title, number=num_disp, adopted_date=year, in_force=True, consolidated=True,
                    content_format="html", text=text, source_policy=pol, source_org="King's Printer for New Brunswick (laws.gnb.ca)",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="NB", current_to=(cur.group(1) if cur else None),
                    gnb_chapter=it["number"]), "ok"


def requests_unquote(s):
    from urllib.parse import unquote
    return unquote(s)


ADAPTERS[NBFull.key] = NBFull


# ------------------------------------------------------------------ Newfoundland and Labrador (assembly.nl.ca)  -- TERMS HOLD
# House of Assembly copyright statement permits excerpt/cite for research etc.; commercial use needs Speaker's approval.
# Adapter is built and tested into _review only; do NOT promote until the user decides on the terms question.
def _smart_title(s):
    s = s.title() if s.isupper() else s
    s = re.sub(r"\b(Of|And|Or|The|For|To|In|On|By|Under|With|An|A|If|At|From|Into)\b", lambda x: x.group(1).lower(), s)
    s = re.sub(r"\b([IVXLivxl]+)(?=\b|\.)", lambda x: x.group(1).upper() if re.fullmatch(r"(?i)[ivxl]{1,6}", x.group(1)) and x.group(1).lower() not in ("i",) or x.group(1) == "Ii" else x.group(1), s)
    s = re.sub(r"(['’])S\b", r"\1s", s)
    return s[:1].upper() + s[1:]


class NLFull:
    key, cc, place, platform, min_chars = "ca_nl_assembly", "CA", "CA-NL", "ca_nl_assembly", 100
    HOST = "https://www.assembly.nl.ca"
    TERMS_HOLD = True
    LICENSE = ("House of Assembly of Newfoundland and Labrador copyright statement (assembly.nl.ca/inc/CopyrightStatementHOA.pdf): "
               "permission to excerpt and cite for education, research, review etc.; commercial use requires the Speaker's written approval")

    def discover(self, sess):
        items, seen = [], set()
        r, _ = sess.get(f"{self.HOST}/Legislation/sr/titleindex.htm")
        for h in re.findall(r'href="/Legislation/sr/statutes/([a-z0-9\-]+)\.htm"', r.text, re.I):
            if h.lower() not in seen:
                seen.add(h.lower()); items.append({"doc_id": f"nl_stat:{h.lower()}", "kind": "statute", "url": f"{self.HOST}/Legislation/sr/statutes/{h}.htm"})
        r, _ = sess.get(f"{self.HOST}/Legislation/sr/")
        for h in re.findall(r'href="/Legislation/sr/regulations/(rc\d+)\.htm"', r.text, re.I):
            if h.lower() not in seen:
                seen.add(h.lower()); items.append({"doc_id": f"nl_reg:{h.lower()}", "kind": "regulation", "url": f"{self.HOST}/Legislation/sr/regulations/{h}.htm"})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        doc = LH.fromstring(r.content)
        t = " ".join((doc.findtext(".//title") or "").split())
        secs = doc.xpath('//div[starts-with(@class,"Section")]') or doc.xpath("//body")
        text = "\n\n".join(x for x in (btext(s) for s in secs) if x)
        text = re.sub(r"^.*?How current is this (?:regulation|Act)\?\s*", "", text, count=1, flags=re.S | re.I)
        text = re.sub(r"\n?Back to Top\n?", "\n", text)
        text = re.sub(r"\s*©[^\n]{0,40}(?:Queen|King)['’]s Printer\s*$", "", text).strip()
        text = re.sub(r"^This is an official version\..{0,400}?(?:Main Site|Table of (?:Public )?(?:Statutes|Regulations))\s*", "", text, count=1, flags=re.S)
        if re.search(r"\b(?:Repealed|Revoked)\b", t, re.I):
            return None, "repealed_or_revoked"
        m = re.match(r"^(.*?)\s+-\s+(.+)$", t)
        cite, name = (m.group(1), m.group(2)) if m else (None, t)
        name = _smart_title(name.strip())
        cite = re.sub(r"^(SNL|RSNL)(\d{4}) CHAPTER ", r"\1 \2 c ", cite or "") or None
        yr = re.search(r"(\d{4})", cite or "") or re.search(r"/(\d{2})$", cite or "")
        year = yr.group(1) if yr else None
        if year and len(year) == 2:
            year = ("19" if int(year) > 30 else "20") + year
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type=it["kind"],
                    language="en", title_native=name, number=cite, adopted_date=year, in_force=True, consolidated=True,
                    content_format="html", text=text, source_policy=pol, source_org="House of Assembly of Newfoundland and Labrador / King's Printer",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="NL"), "ok"


ADAPTERS[NLFull.key] = NLFull


def _pdf_left_column(data: bytes):
    """English column of a two-column EN|FR PDF: pdftotext -layout cropped to the left half of each page (no OCR)."""
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf") as t:
        t.write(data); t.flush()
        info = subprocess.run(["pdfinfo", t.name], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", info)
        if not m:
            return None
        w, h = float(m.group(1)), float(m.group(2))
        out = subprocess.run(["pdftotext", "-layout", "-r", "72", "-x", "0", "-y", "0", "-W", str(int(w / 2)), "-H", str(int(h) + 1), t.name, "-"],
                             capture_output=True, timeout=180).stdout
    return out.decode("utf-8", "replace")


# ------------------------------------------------------------------ Northwest Territories (justice.gov.nt.ca consolidation PDFs)
class NWTFull:
    key, cc, place, platform, min_chars = "ca_nt_justice", "CA", "CA-NT", "ca_nt_justice", 150
    LIST = "https://www.justice.gov.nt.ca/en/legislation/"
    LICENSE = ("GNWT consolidation copyright notice: may be used for a non-commercial purpose without seeking permission, provided it is "
               "accurately reproduced and acknowledges the Government of the Northwest Territories as its source; reproduction permitted "
               "in whole or in part by any means. Consolidations are not an official statement of the law. Source: Government of the Northwest Territories")

    def discover(self, sess):
        r, _ = sess.get(self.LIST)
        doc = LH.fromstring(r.content)
        items = []
        for li in doc.xpath('//li[contains(@class,"gn-filebrowse-file")]'):
            a = li.xpath('./a[@href]')
            if not a:
                continue
            href = a[0].get("href")
            m = re.search(r"/en/files/legislation/([a-z0-9\-]+)/([a-z0-9\-]+)\.(a|r\d+)\.pdf$", href)
            if not m:
                continue
            folder = li.xpath('ancestor::li[contains(@class,"gn-filebrowse-folder")][1]')
            act = " ".join(folder[0].xpath('./a[contains(@class,"gn-filebrowse-node-label")]')[0].text_content().split()) if folder else None
            dept = folder[0].xpath('./div/div[@data-attribute-name="department"]/text()') if folder else []
            date = li.xpath('.//div[@data-attribute-name="date"]/text()')
            items.append({"doc_id": f"nwt:{m.group(2)}.{m.group(3)}", "url": href, "kind": "statute" if m.group(3) == "a" else "regulation",
                          "title": " ".join(a[0].text_content().split()), "parent_act": act,
                          "department": (dept[0].strip() if dept else None), "file_date": (date[0].strip() if date else None)})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            return None, f"http_{r.status_code}"
        ok, txt = pdf_has_text(r.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, it["url"], pol)
            return None, "scanned_pdf_queued"
        bilingual = bool(re.search(r"\bLOI (?:SUR|CONCERNANT|D['’])|\bRÈGLEMENT\b", txt[:4000]))
        if bilingual:
            left = _pdf_left_column(r.content)
            if left and len("".join(left.split())) > 0.25 * len("".join(txt.split())):
                txt = left
            else:
                bilingual = None   # crop failed; keep full two-column text
        txt = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", txt.replace("\f", "\n"))).strip()
        head = txt[:3000]
        cite = None
        mc = re.search(r"\b(R\.S\.N\.W\.T\. \d{4},\s*c\.\s*[\w\-.]+|S\.?N\.?W\.?T\.? \d{4},\s*c\.\s*[\w\-.]+|S\.N\.W\.T\. \d{4},\s*c\.\s*[\w\-.]+|R-\d{3}-\d{4}|R\.R\.N\.W\.T\. \d{4},\s*c\.\s*[\w\-.]+)", head)
        if mc:
            cite = re.sub(r"\s+", " ", mc.group(1))
        mr = re.search(r"\b(R-\d{3}-\d{2,4})\b", head[:1500]) if it["kind"] == "regulation" else None
        if mr:
            cite = mr.group(1)
        yr = re.search(r"(\d{4})", cite or "") or re.search(r"-(\d{2})$", cite or "")
        if yr and len(yr.group(1)) == 2:
            yr = re.match(r"(.*)", ("19" if int(yr.group(1)) > 30 else "20") + yr.group(1))
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type=it["kind"],
                    language="en", title_native=it["title"], number=cite, adopted_date=(yr.group(1) if yr else None), in_force=True,
                    consolidated=True, content_format="pdf_text", text=txt, source_policy=pol,
                    source_org="Government of the Northwest Territories, Department of Justice", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="NT", parent_act=it["parent_act"], administering_department=it["department"],
                    file_modified_date=it["file_date"], bilingual_source_english_column_only=bilingual), "ok"


ADAPTERS[NWTFull.key] = NWTFull


# ------------------------------------------------------------------ Australian Capital Territory (legislation.act.gov.au; Crawl-delay 10)
class ACTFull:
    """Discovery: Wayback CDX URL lists (the browse endpoint /results is robots-disallowed). Live fetch only of allowed
    paths: /a/<id>/, /sl/<id>/ (item pages) and /DownloadFile/... (current authorised PDF). Never /View/, /html/, /results."""
    key, cc, place, platform, min_chars = "au_act_leg", "AU", "AU-ACT", "au_act_legislation_register", 150
    HOST = "https://www.legislation.act.gov.au"
    DATA = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data")
    LICENSE = ("CC BY 4.0 (ACT Government / JACS copyright policy, act.gov.au/copyright); source: ACT Legislation Register, "
               "Parliamentary Counsel's Office; text extracted from the authorised PDF, not itself an authorised version")

    def discover(self, sess):
        items, seen = [], set()
        for kind, fn in (("a", "act_a_cdx.txt"), ("sl", "act_sl_cdx.txt")):
            try:
                lines = open(f"{self.DATA}/{fn}", encoding="utf-8").read().split("\n")
            except FileNotFoundError:
                continue
            for line in lines:
                if not line.strip() or line.startswith("#"):
                    continue
                u = line.split()[-1]
                m = re.search(r"legislation\.act\.gov\.au(?::\d+)?/" + kind + r"/(\d{4}-\d{1,4})(?:[/?#]|$)", u, re.I)
                if m and (kind, m.group(1)) not in seen:
                    seen.add((kind, m.group(1)))
                    items.append({"doc_id": f"act_{kind}:{m.group(1)}", "kind": kind, "id": m.group(1), "url": f"{self.HOST}/{kind}/{m.group(1)}/"})
        items.sort(key=lambda x: (x["kind"], x["id"]))
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        t = r.text
        status = re.search(r"<dt>Status</dt>\s*<dd[^>]*>\s*([^<]+?)\s*</dd>", t)
        status = status.group(1) if status else None
        if not status or status.lower() != "in force":
            return None, f"status:{(status or 'none')[:24].lower()}"
        h2 = re.search(r'<article class="wrap"[^>]*>.*?<h2>(.*?)</h2>', t, re.S)
        title = " ".join(LH.fromstring("<x>" + h2.group(1) + "</x>").text_content().split()) if h2 else None
        num = re.search(r"<dt>Number</dt>\s*<dd[^>]*>\s*([^<]+?)\s*</dd>", t)
        num = num.group(1) if num else None
        k, i = it["kind"], it["id"]
        pdf = re.search(r'href="(/DownloadFile/' + k + "/" + re.escape(i) + r'/current/PDF/[^"]+\.PDF)"', t, re.I)
        if not pdf:
            return None, "no_current_pdf"
        pdf_url = self.HOST + pdf.group(1)
        eff = re.search(r"Current version.*?<td[^>]*>\s*(\d{1,2} \w+ \d{4})", t, re.S)
        pr, pol2 = sess.get(pdf_url)
        if pr.status_code != 200 or not pr.content.startswith(b"%PDF"):
            return None, f"pdf_http_{pr.status_code}"
        ok, txt = pdf_has_text(pr.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, pdf_url, pol2)
            return None, "scanned_pdf_queued"
        txt = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", txt.replace("\f", "\n"))).strip()
        yr = re.search(r"(\d{4})", i)
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=pdf_url,
                    doc_type=("statute" if k == "a" else "regulation"), language="en", title_native=title, number=num,
                    adopted_date=(yr.group(1) if yr else None), in_force=True, consolidated=True, content_format="pdf_text",
                    text=txt, source_policy=pol, source_org="ACT Parliamentary Counsel's Office (ACT Legislation Register)",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="ACT", detail_url=it["url"],
                    current_version_effective=(eff.group(1) if eff else None)), "ok"


ADAPTERS[ACTFull.key] = ACTFull


# ================================================================== ARCHIVE-ONLY sources (robots-disallowed / challenged hosts)
# Never any live request to these hosts. URL lists come from Wayback CDX (data/archive/<x>.txt, via cdx_list.py);
# bodies come from the shared archive module (box-wide limiter, ARCHIVE_LANE=states). Records carry
# source_policy=archived_robots_disallowed, robots_basis and the archive provenance (archive_timestamp = copy date).
import sys as _sys
_sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
_FX = None


def _fx():
    global _FX
    if _FX is None:
        import os
        os.environ.setdefault("ARCHIVE_LANE", "states")
        from archive import ArchiveFetcher
        _FX = ArchiveFetcher(lane="states", cc_crawls=0, use_cc=False, cc_max_wait=30)
    return _FX


def _wait_wayback():
    """Breaker open: defer the item (runner requeues it for the next probe) instead of sleeping on it."""
    from archive import ratelimit
    if not ratelimit.wayback_available():
        from deferq import ItemDeferred, breaker_not_before
        raise ItemDeferred("wayback breaker open (box-wide)", breaker_not_before())


class ArchiveBase:
    key = cc = place = platform = None
    min_chars = 150
    DISC = None                 # data/archive/<x>.txt  ("<timestamp> <original_url>" lines)
    URL_RX = None               # compiled regex on the normalised URL (no scheme/port/query unless KEEP_QUERY); group "id"
    KEEP_QUERY = False
    ROBOTS_BASIS = ""
    LICENSE = ""
    SOURCE_ORG = ""
    MAX_CAPS = 3

    def norm(self, u):
        u = re.sub(r"^https?://", "", u.strip())
        u = re.sub(r"^([^/]+):\d+", r"\1", u)
        if not self.KEEP_QUERY:
            u = u.split("?")[0]
        return u.split("#")[0].rstrip("/")

    def doc_id(self, m):
        return f"{self.key.split('_archive')[0]}:{m.group('id').lower()}"

    def discover(self, sess):
        by = {}
        path = f"/workspace/world_law/pipeline/scrapers/states/{self.DISC}"
        try:
            lines = open(path, encoding="utf-8").read().split("\n")
        except FileNotFoundError:
            return []
        for line in lines:
            parts = line.split(" ", 1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            ts, u = parts[0], parts[1].strip()
            m = self.URL_RX.search(self.norm(u))
            if not m:
                continue
            did = self.doc_id(m)
            by.setdefault(did, {"doc_id": did, "caps": [], "m": m.groupdict()})["caps"].append((ts, u))
        items = []
        for did, it in by.items():
            it["caps"] = sorted(set(it["caps"]), reverse=True)[: self.MAX_CAPS]
            it["url"] = it["caps"][0][1]
            items.append(it)
        items.sort(key=lambda x: x["doc_id"])
        return items

    def valid(self, doc):
        return True

    def parse(self, doc, it):
        raise NotImplementedError

    def fetch(self, sess, it):
        from archive import Capture, provenance_fields
        _wait_wayback()
        caps = [Capture(source="wayback", crawl_id="wayback", timestamp=ts, original_url=u, status=200) for ts, u in it["caps"]]
        from deferq import fetch_best_or_defer, reset_incomplete, incomplete_not_before, ItemDeferred
        reset_incomplete(_fx())
        # round 3: None = true miss; timeouts / breaker / throttle raise ArchiveDeferred -> run_full requeues the item
        doc = fetch_best_or_defer(_fx(), caps, validator=self.valid, max_tries=len(caps), policy="newest")
        if doc is None:
            return None, "no_good_capture"
        out = self.parse(doc, it)
        inc_nb = incomplete_not_before(_fx())        # doc.incomplete (main doc or the VIC text file): another source failed
        if inc_nb and (isinstance(out, str) or not doc.content_complete or len((out.get("text") or "").strip()) < self.min_chars):
            raise ItemDeferred(f"incomplete archive fetch ({out if isinstance(out, str) else 'short/partial text'})", inc_nb)
        if isinstance(out, str):
            return None, out
        prov = provenance_fields(doc, "archived_robots_disallowed", self.ROBOTS_BASIS)
        em = prov.pop("extra_metadata")
        rec = base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=doc.original_url,
                   language=out.pop("language", "en"), source_org=self.SOURCE_ORG, license_note=self.LICENSE,
                   platform=self.platform, archive_copy_date=doc.archive_timestamp[:10], **prov, **out)
        rec["source_policy"] = "archived_robots_disallowed"
        if inc_nb:
            em["archive_incomplete"] = True          # full text, but another archive source failed for this item
        rec["extra_metadata"] = em
        return rec, "ok"


def _doc_html(doc):
    return LH.fromstring(doc.text())


def _main_text(root, xpaths):
    for xp in xpaths:
        n = root.xpath(xp)
        if n:
            return "\n\n".join(t for t in (btext(x) for x in n) if t)
    return None


def _pdf_text(body):
    ok, txt = pdf_has_text(body)
    return (re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", txt.replace("\f", "\n"))).strip() if ok else None)


_DROP = ".//script|.//style|.//noscript|.//nav|.//header|.//footer|.//*[@id='header' or @id='footer' or @role='navigation']"


def _generic_html(doc, xpaths):
    root = _doc_html(doc)
    for bad in root.xpath(_DROP):
        bad.drop_tree()
    title = " ".join((root.findtext(".//title") or "").split())
    h1 = root.xpath("//h1")
    h1 = " ".join(h1[0].text_content().split()) if h1 else ""
    text = _main_text(root, xpaths) or _main_text(root, ["//main", "//article", "//body"])
    return title, h1, text


def _docx_text(body):
    import io, zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
        x = etree.fromstring(z.read("word/document.xml"))
    except Exception:
        return None
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras = ["".join(t.text or "" for t in p.iter("{%s}t" % ns["w"])) for p in x.iter("{%s}p" % ns["w"])]
    return "\n".join(p for p in paras if p.strip()) or None


class _ArchHTML(ArchiveBase):
    XPATHS = []
    TITLE_STRIP = r"\s*[|\-–]\s*(?:NSW Legislation|LégisQuébec|BC Laws).*$"

    def valid(self, doc):
        return doc.http_status == 200 and b"<html" in doc.body[:5000].lower()

    def parse(self, doc, it):
        title, h1, text = _generic_html(doc, self.XPATHS)
        if not text:
            return "no_body"
        t = re.sub(self.TITLE_STRIP, "", h1 or title).strip() or title
        kind = (it.get("m") or {}).get("kind") or ""
        return dict(title_native=t, doc_type=self.doc_type(kind, it), text=text, content_format="html",
                    in_force=None, consolidated=True, in_force_at_capture=self.IN_FORCE_AT_CAPTURE)

    IN_FORCE_AT_CAPTURE = None

    def doc_type(self, kind, it):
        return "regulation" if kind.lower() in ("sl", "rc", "r", "regs", "subordinate", "statutory-rules") else "statute"


class _ArchPDF(ArchiveBase):
    def valid(self, doc):
        return doc.http_status == 200 and doc.body[:5] == b"%PDF-"

    def parse(self, doc, it):
        txt = _pdf_text(doc.body)
        if not txt:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, doc.original_url, "archived_robots_disallowed")
            return "scanned_pdf_queued"
        first = next((l.strip() for l in txt.split("\n") if l.strip()), "")
        kind = (it.get("m") or {}).get("kind") or ""
        name = re.sub(r"\.pdf$", "", (it.get("m") or {}).get("id") or "", flags=re.I)
        return dict(title_native=self.title_from(txt) or first[:200], doc_type=("regulation" if kind.lower() in ("regs", "subordinate") else "statute"),
                    text=txt, content_format="pdf_text", in_force=None, consolidated=True, archive_file_name=name)

    def title_from(self, txt):
        head = [l.strip() for l in txt[:1500].split("\n") if l.strip()]
        for l in head[:15]:
            if re.search(r"\b(ACT|REGULATION|Act|Regulation|CODE|Code|ORDER|Order)\b", l) and len(l) < 200:
                return _smart_title(l)
        return None


class NSWArchive(_ArchHTML):
    key, cc, place, platform = "au_nsw_archive", "AU", "AU-NSW", "au_nsw_legislation"
    DISC = "data/archive/nsw.txt"
    URL_RX = re.compile(r"legislation\.nsw\.gov\.au/view/html/inforce/current/(?P<id>(?P<kind>act|sl|epi)-\d{4}-\d+[a-z]?)$", re.I)
    XPATHS = ['//div[@id="frag-col"]', '//div[@id="fragview"]', '//div[contains(@class,"frag")]']
    IN_FORCE_AT_CAPTURE = True
    ROBOTS_BASIS = "legislation.nsw.gov.au answers robots.txt with a 403 challenge => disallow-all for live crawling"
    LICENSE = "CC BY 4.0 (NSW Parliamentary Counsel's Office, legislation.nsw.gov.au copyright notice)"
    SOURCE_ORG = "NSW Parliamentary Counsel's Office (archived copy)"

    # The /view/html/inforce/current/<id> page is only a JS frame (toolbar + title, ~220 chars); the provisions are
    # loaded later by XHR and are not in the capture. The frame links the static whole-instrument page
    # (/view/whole/html/inforce/<date>/<id>) and an XML rendition, so those are taken from the archive instead.
    FRAME_RX = re.compile(r"Results: match \d+ of \d+ provisions|Return to search results")
    MIN_TEXT = 800
    # 2026-10-19: the whole-instrument page starts with the viewer toolbar ("View whole EPI / Parent Act / Legislative
    # history / Search EPI / Results: match 0 of 0 provisions / Previous Hit / ... / First / Last") before the title.
    CHROME_RX = re.compile(r"View whole|Parent Act|Legislative history|Results: match \d+ of \d+|Previous Hit|Return to search results|hits in page")

    def strip_chrome(self, text, title):
        head = text[:1500]
        if not self.CHROME_RX.search(head):
            return text
        if title:
            i = head.find(title)
            if i > 0 and self.CHROME_RX.search(head[:i]):
                return text[i:].strip()
        m = list(re.finditer(r"(?m)^(?:First\s*\n\s*Last|Last)\s*$", head))
        if m and self.CHROME_RX.search(head[:m[-1].start()]):
            return text[m[-1].end():].strip()
        return text

    def parse(self, doc, it):
        from urllib.parse import urljoin
        from lxml import etree
        root = _doc_html(doc)
        h1 = root.xpath("//h1")
        title = " ".join((h1[0].text_content() if h1 else (root.findtext(".//title") or "")).split())
        title = re.sub(self.TITLE_STRIP, "", title).strip()
        hrefs = [urljoin(doc.original_url, a.get("href")) for a in root.xpath("//a[@href]")]
        whole = [u for u in hrefs if re.search(r"/view/whole/html/inforce/[^/]+/(act|sl|epi)-", u)]
        xml = [u for u in hrefs if re.search(r"/view/xml/inforce/[^/]+/(act|sl|epi)-", u)]
        kind = (it.get("m") or {}).get("kind") or ""
        from deferq import fetch_newest_or_defer, ArchiveTransient
        # 2026-10-20: about half the frames link a dated whole page that Wayback never captured; the undated
        # /view/whole/html/inforce/current/<id> page often is captured (e.g. act-1993-030) -> last-resort fallback.
        cur = []
        mid = re.search(r"/((?:act|sl|epi)-\d{4}-\d+[a-z]?)$", doc.original_url.split("?")[0].rstrip("/"), re.I)
        if mid:
            cu = f"https://legislation.nsw.gov.au/view/whole/html/inforce/current/{mid.group(1).lower()}"
            if cu not in whole[:1]:
                cur = [(cu, "html")]
        for u, fmt in [(x, "html") for x in whole[:1]] + [(x, "xml") for x in xml[:1]] + cur:
            try:
                f = fetch_newest_or_defer(_fx(), u)
            except ArchiveTransient:
                raise
            except Exception:
                f = None
            if not f or f.http_status != 200 or not f.body:
                continue
            if fmt == "html":
                t2, h2, text = _generic_html(f, ['//div[@id="frag-col"]', '//div[@id="fragview"]', '//div[contains(@class,"frag")]', "//main", "//body"])
            else:
                try:
                    x = etree.fromstring(f.body, etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True))
                    text = "\n".join(l for l in (" ".join(t.split()) for t in x.itertext()) if l) if x is not None else ""
                except Exception:
                    text = ""
            text = self.strip_chrome((text or "").strip(), title or (h2 if fmt == "html" else ""))
            if len(text) < self.MIN_TEXT or (self.FRAME_RX.search(text[:600]) and len(text) < 3000):
                continue
            date_m = re.search(r"/inforce/([^/]+)/", u)
            return dict(title_native=title or (h2 if fmt == "html" else ""), doc_type=self.doc_type(kind, it), text=text,
                        content_format=fmt, in_force=None, consolidated=True, in_force_at_capture=True,
                        text_page_archive_url=f.archive_url, text_page_archive_timestamp=f.archive_timestamp,
                        version_date=(date_m.group(1) if date_m and date_m.group(1) != "current" else None))
        return "frame_only_no_archived_text"


class QCArchive(_ArchHTML):
    key, cc, place, platform = "ca_qc_archive", "CA", "CA-QC", "ca_qc_legisquebec"
    DISC = "data/archive/qc.txt"
    URL_RX = re.compile(r"www\.legisquebec\.gouv\.qc\.ca/en/document/(?P<kind>cs|rc)/(?P<id>[^/]+)$", re.I)
    XPATHS = ['//div[@id="mainContent-document"]', '//div[contains(@class,"WebDocument")]', '//div[@id="content"]']
    IN_FORCE_AT_CAPTURE = True
    ROBOTS_BASIS = "www.legisquebec.gouv.qc.ca serves a bot challenge => disallow-all for live crawling"
    LICENSE = "Québec legislation: reproduction permitted (Éditeur officiel du Québec, LégisQuébec terms); archived English version"
    SOURCE_ORG = "Éditeur officiel du Québec / LégisQuébec (archived copy)"

    def doc_id(self, m):
        from urllib.parse import unquote
        return f"qc_{m.group('kind').lower()}:{re.sub(r'[^a-z0-9.\-]+', '_', unquote(m.group('id')).lower()).strip('_')}"


class BCArchive(_ArchHTML):
    key, cc, place, platform = "ca_bc_archive", "CA", "CA-BC", "ca_bc_bclaws"
    DISC = "data/archive/bc.txt"
    URL_RX = re.compile(r"www\.bclaws\.gov\.bc\.ca/civix/document/id/complete/statreg/(?P<id>[0-9a-z_]+)$", re.I)
    XPATHS = ['//div[@id="contentsscroll"]', '//div[@id="act:currency"]/..', "//body"]
    ROBOTS_BASIS = "www.bclaws.gov.bc.ca robots.txt allows only Googlebot/Bingbot => disallowed for our UA"
    LICENSE = "King's Printer Licence - British Columbia (open licence for BC laws; bclaws.gov.bc.ca)"
    SOURCE_ORG = "King's Printer for British Columbia (archived copy)"

    def doc_type(self, kind, it):
        return "regulation" if re.match(r"^\d+_\d{4}$", (it.get("m") or {}).get("id", "")) else "statute"


class YTArchive(_ArchPDF):
    key, cc, place, platform = "ca_yt_archive", "CA", "CA-YT", "ca_yt_laws"
    DISC = "data/archive/yt.txt"
    URL_RX = re.compile(r"laws\.yukon\.ca/cms/images/LEGISLATION/(?P<kind>PRINCIPAL|SUBORDINATE)/(?P<id>[^?]+\.pdf)$", re.I)
    ROBOTS_BASIS = "laws.yukon.ca serves a bot challenge => disallow-all for live crawling"
    LICENSE = "Yukon legislation (Government of Yukon); archived consolidation PDF, not an official copy"
    SOURCE_ORG = "Government of Yukon (archived copy)"

    def doc_id(self, m):
        return f"yt:{m.group('kind').lower()[0]}:{re.sub(r'[^a-z0-9.\-]+', '_', m.group('id').lower())}"


class ABArchive(_ArchPDF):
    key, cc, place, platform = "ca_ab_archive", "CA", "CA-AB", "ca_ab_kings_printer"
    DISC = "data/archive/ab.txt"
    URL_RX = re.compile(r"kings-printer\.alberta\.ca/documents/(?P<kind>Acts|Regs)/(?P<id>[^?/]+\.pdf)$", re.I)
    ROBOTS_BASIS = "kings-printer.alberta.ca robots.txt Disallow: / for all agents"
    LICENSE = "Alberta King's Printer; archived consolidation PDF, not an official copy"
    SOURCE_ORG = "Alberta King's Printer (archived copy)"

    def doc_id(self, m):
        return f"ab_{m.group('kind').lower()}:{re.sub(r'[^a-z0-9.\-]+', '_', m.group('id').lower())}"


class SAArchive(_ArchHTML):
    key, cc, place, platform = "au_sa_archive", "AU", "AU-SA", "au_sa_legislation"
    DISC = "data/archive/sa.txt"
    KEEP_QUERY = True
    URL_RX = re.compile(r"www\.legislation\.sa\.gov\.au/lz\?path=(?:%2F|/)C(?:%2F|/)(?P<kind>A|R)(?:%2F|/)(?P<id>[^&/%]+(?:%20[^&/%]+)*)$", re.I)
    IN_FORCE_AT_CAPTURE = True
    XPATHS = ['//div[@id="content"]', "//main"]
    ROBOTS_BASIS = "www.legislation.sa.gov.au serves a bot challenge => disallow-all for live crawling"
    LICENSE = "Government of South Australia legislation (legislation.sa.gov.au copyright); archived copy"
    SOURCE_ORG = "Attorney-General's Department SA (archived copy)"

    def doc_id(self, m):
        from urllib.parse import unquote
        return f"sa_{m.group('kind').lower()}:{re.sub(r'[^a-z0-9.\-]+', '_', unquote(m.group('id')).lower()).strip('_')}"


class VICArchive(_ArchHTML):
    """Version pages on www.legislation.vic.gov.au hold metadata; the text is in the authorised PDF/DOCX on
    content.legislation.vic.gov.au (both robots-disallowed), so the file is also taken from the archive."""
    key, cc, place, platform = "au_vic_archive", "AU", "AU-VIC", "au_vic_legislation"
    DISC = "data/archive/vic.txt"
    URL_RX = re.compile(r"www\.legislation\.vic\.gov\.au/in-force/(?P<kind>acts|statutory-rules)/(?P<id>[a-z0-9\-]+)/(?P<ver>\d{3})$", re.I)
    IN_FORCE_AT_CAPTURE = True
    ROBOTS_BASIS = "content.legislation.vic.gov.au robots.txt Disallow: / (text files); coordinator decision 2026-10-17: archive copies only"
    LICENSE = "State of Victoria (Office of the Chief Parliamentary Counsel); site terms restrict reproduction - archived copy, see README"
    SOURCE_ORG = "Office of the Chief Parliamentary Counsel Victoria (archived copy)"

    def doc_id(self, m):
        return f"vic_{m.group('kind').lower()[0]}:{m.group('id').lower()}"

    def parse(self, doc, it):
        root = _doc_html(doc)
        h1 = root.xpath("//h1")
        title = " ".join(h1[0].text_content().split()) if h1 else " ".join((root.findtext(".//title") or "").split())
        links = [a.get("href") for a in root.xpath("//a[@href]") if re.search(r"content\.legislation\.vic\.gov\.au/.+\.(pdf|docx)$", a.get("href") or "", re.I)]
        links.sort(key=lambda u: 0 if u.lower().endswith(".docx") else 1)
        for u in links[:2]:
            from deferq import fetch_newest_or_defer, ArchiveTransient
            try:
                f = fetch_newest_or_defer(_fx(), u)     # None = true miss; throttle/timeout/breaker raise -> item requeued
            except ArchiveTransient:
                raise
            except Exception:
                f = None
            if not f or f.http_status != 200:
                continue
            txt = _docx_text(f.body) if u.lower().endswith(".docx") else _pdf_text(f.body)
            if txt:
                return dict(title_native=title, doc_type=self.doc_type((it.get("m") or {}).get("kind", ""), it), text=txt,
                            content_format=("docx_text" if u.lower().endswith(".docx") else "pdf_text"), in_force=None,
                            consolidated=True, in_force_at_capture=True, version=(it.get("m") or {}).get("ver"),
                            text_file_archive_url=f.archive_url, text_file_archive_timestamp=f.archive_timestamp)
        return "no_archived_text_file"


for _c in (NSWArchive, QCArchive, BCArchive, YTArchive, ABArchive, SAArchive, VICArchive):
    ADAPTERS[_c.key] = _c
PLACES.update({
    "AU-NSW": dict(place_id="iso:AU-NSW", country_code="AU", place_name="New South Wales", qid="Q3224", iso_3166_2="AU-NSW", admin_level="adm1"),
    "AU-SA": dict(place_id="iso:AU-SA", country_code="AU", place_name="South Australia", qid="Q35715", iso_3166_2="AU-SA", admin_level="adm1"),
    "CA-QC": dict(place_id="iso:CA-QC", country_code="CA", place_name="Quebec", qid="Q176", iso_3166_2="CA-QC", admin_level="adm1"),
    "CA-BC": dict(place_id="iso:CA-BC", country_code="CA", place_name="British Columbia", qid="Q1973", iso_3166_2="CA-BC", admin_level="adm1"),
    "CA-AB": dict(place_id="iso:CA-AB", country_code="CA", place_name="Alberta", qid="Q1951", iso_3166_2="CA-AB", admin_level="adm1"),
    "CA-YT": dict(place_id="iso:CA-YT", country_code="CA", place_name="Yukon", qid="Q2009", iso_3166_2="CA-YT", admin_level="adm1"),
})


# ================================================================== Switzerland: cantons via LexFind (lexfind.ch)
# LexFind is run for the Swiss State Chancellors' Conference (SSK) by Sitrox; robots.txt allows all; Swiss legislative
# texts are not protected by copyright (Art. 5 para. 1 let. a URG/LDA). Listing: /api/frontend/v1/<lang>/entities/<id>/systematics
# (active_only=true + tols_for_systematics[]); text: /tol/<tol_id>/<lang> = newest version (PDF copy of the official SGS text).
CH_CANTONS = {  # abbr: (place name, qid, languages)
    "ZH": ("Zürich", "Q11943", ["de"]), "BE": ("Bern", "Q11911", ["de", "fr"]), "LU": ("Luzern", "Q12121", ["de"]),
    "UR": ("Uri", "Q12404", ["de"]), "SZ": ("Schwyz", "Q12433", ["de"]), "OW": ("Obwalden", "Q12573", ["de"]),
    "NW": ("Nidwalden", "Q12592", ["de"]), "GL": ("Glarus", "Q11922", ["de"]), "ZG": ("Zug", "Q11933", ["de"]),
    "FR": ("Fribourg", "Q12640", ["fr", "de"]), "SO": ("Solothurn", "Q11929", ["de"]), "BS": ("Basel-Stadt", "Q12172", ["de"]),
    "BL": ("Basel-Landschaft", "Q12146", ["de"]), "SH": ("Schaffhausen", "Q12697", ["de"]),
    "AR": ("Appenzell Ausserrhoden", "Q12079", ["de"]), "AI": ("Appenzell Innerrhoden", "Q12094", ["de"]),
    "SG": ("St. Gallen", "Q12746", ["de"]), "GR": ("Graubünden", "Q11925", ["de", "it", "rm"]), "AG": ("Aargau", "Q11972", ["de"]),
    "TG": ("Thurgau", "Q12713", ["de"]), "TI": ("Ticino", "Q12724", ["it"]), "VD": ("Vaud", "Q12771", ["fr"]),
    "VS": ("Valais", "Q834", ["fr", "de"]), "NE": ("Neuchâtel", "Q12738", ["fr"]), "GE": ("Genève", "Q11917", ["fr"]),
    "JU": ("Jura", "Q12755", ["fr"]),
}
for _a, (_n, _q, _l) in CH_CANTONS.items():
    PLACES[f"CH-{_a}"] = dict(place_id=f"iso:CH-{_a}", country_code="CH", place_name=_n, qid=_q, iso_3166_2=f"CH-{_a}", admin_level="adm1")

CH_CAT_TYPE = {1: "statute", 2: "statute", 3: "statute", 4: "statute", 8: "statute", 6: "regulation", 7: "regulation", 5: "decision"}
CH_CAT_NAME = {1: "Staatsvertrag", 2: "Interkantonale Vereinbarung", 3: "Verfassung", 4: "Gesetz", 8: "Verordnung des Parlaments (Dekret)",
               6: "Verordnung", 7: "Reglement", 5: "Anderes"}


_CH_SW = {"de": " der die und das nicht mit wird von für ist auf ", "fr": " le la les des et du une est pour par dans ",
          "it": " il della delle che per una sono degli nel con dal ", "rm": " da la il dal ed per u ina ils las cun tenor "}


def _ch_lang(txt):
    w = re.findall(r"[a-zäöüàèéìòù]+", txt[:6000].lower())
    if len(w) < 50:
        return None
    sc = {lg: sum(1 for x in w if f" {x} " in sw) for lg, sw in _CH_SW.items()}
    best = max(sc, key=sc.get)
    return best if sc[best] >= 1.5 * max(v for k, v in sc.items() if k != best) else None


_CH_DATE = re.compile(r"^(?:vom|du|del|dals|dal|da|dils|dalla)\s+(\d{1,2}\.\s*\d{1,2}\.\s*\d{4}|\d{1,2}\.?\s+\w+\s+\d{4})(?:.*?\((?:Stand|état|stato|versiun|stadi)(?: (?:au|al|ils|dals))?\s+([\d.]+)\))?", re.I)


_CH_MON = {m: i + 1 for ms in (
    "januar februar märz april mai juni juli august september oktober november dezember",
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
    "schaner favrer mars avrigl matg zercladur fanadur avust settember october november december")
    for i, m in enumerate(ms.split())}
_CH_MON.update({"jänner": 1, "fevrier": 2, "decembre": 12, "aout": 8})


def _ch_iso(d):
    if not d:
        return None
    d = d.strip().lower().replace("1er", "1").replace("1°", "1")
    m = re.match(r"^(\d{1,2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{4})$", d)
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.match(r"^(\d{1,2})\.?\s+(?:da\s+|d')?([a-zäöüéèûàì]+)\s+(\d{4})$", d)
        if not m or m.group(2) not in _CH_MON:
            m2 = re.search(r"(1[6-9]\d\d|20\d\d)", d)
            return m2.group(1) if m2 else None
        dd, mm, yy = int(m.group(1)), _CH_MON[m.group(2)], m.group(3)
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return yy
    return f"{yy}-{mm:02d}-{dd:02d}"


_CH_DATE2 = re.compile(r"^\(?(?:vom|du|del|dals|dal|da)\s+(\d{1,2}(?:er|°)?[.\-/ ]\s*(?:\d{1,2}[.\-/]\s*|(?:da\s+|d')?[a-zäöüéèûàì]+\s+)\d{4})", re.I)


def _ch_dates(txt):
    """(adopted ISO, stand ISO) from the header lines of a cantonal SGS text."""
    ad = st = None
    for l in txt.split("\n")[:45]:
        m = _CH_DATE2.match(l.strip())
        if m:
            ad = _ch_iso(m.group(1))
            ms = re.search(r"\((?:Stand|état|etat|stato|versiun)\s+(?:au|al|dals|dils|am)?\s*([\d.\-]+\d)", l, re.I)
            st = _ch_iso(ms.group(1)) if ms else None
            break
    return ad, st


def _ch_title(txt, fallback, sysnr):
    lines = [l for l in txt.split("\n")[:40]]
    out, adopted, stand = [], None, None
    for l in lines:
        if not l or (sysnr and l.replace(" ", "") == sysnr.replace(" ", "")) or re.match(r"^[\d.\s]+$", l):
            if out and not l:
                continue
            continue
        m = _CH_DATE2.match(l)
        if m:
            adopted, stand = m.group(1), None
            break
        out.append(l)
        if len(out) > 6:
            return fallback, None, None
    if not out or not adopted:
        return fallback, None, None
    t = " ".join(out)
    t = re.sub(r"(\w)- (\w)", r"\1\2", t)
    t = re.sub(r"(?<=[)a-zàèéìòùäöü])\s?\d{1,2}\)?$", "", t).strip()
    return (t if 8 <= len(t) <= 400 else fallback), adopted, stand


class LexFindCH:
    """One run per canton: key ch_lexfind_<abbr>."""
    cc, platform, min_chars = "CH", "ch_lexfind", 80
    HOST = "https://www.lexfind.ch"
    LICENSE = ("Swiss official legislative texts are not protected by copyright (Art. 5 para. 1 lit. a URG/LDA); "
               "copy via LexFind (Schweizerische Staatsschreiberkonferenz / ZRI), original: cantonal systematic collection")

    def __init__(self, abbr):
        self.abbr = abbr
        self.key = f"ch_lexfind_{abbr.lower()}"
        self.place = f"CH-{abbr}"
        self.langs = CH_CANTONS[abbr][2]

    def _json(self, sess, url, params=None):
        if params:
            from urllib.parse import urlencode
            url = url + "?" + urlencode(params)
        r, _ = sess.get(url)
        if r.status_code != 200:
            raise RuntimeError(f"lexfind {r.status_code} {url}")
        return r.json()

    def discover(self, sess):
        lang0 = self.langs[0]
        ents = self._json(sess, f"{self.HOST}/api/frontend/v1/{lang0}/entities")
        eid = next(e["id"] for e in ents if e["abbreviation"] == self.abbr)
        base_url = f"{self.HOST}/api/frontend/v1/{lang0}/entities/{eid}/systematics"
        sysd = self._json(sess, base_url, params=[("active_only", "true")])
        ids = [k for k in sysd if k]
        tols = {}
        for i in range(0, len(ids), 120):
            p = [("active_only", "true")] + [("tols_for_systematics[]", k) for k in ids[i:i + 120]]
            d = self._json(sess, base_url, params=p)
            for sid, node in d.items():
                for t in (node.get("tols") or []) if isinstance(node, dict) else []:
                    if t.get("is_active") and t.get("category_id") != 9:   # 9 = Gemeindeerlass (municipal lane)
                        tols[t["id"]] = t
        items = []
        for tid, t in sorted(tols.items()):
            for lg in self.langs:
                items.append({"doc_id": f"ch_{self.abbr.lower()}:{tid}:{lg}", "url": f"{self.HOST}/tol/{tid}/{lg}", "lang": lg,
                              "tol_id": tid, "title": t.get("title"), "sysnr": t.get("systematic_number"), "cat": t.get("category_id"),
                              "primary": lg == self.langs[0]})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code == 404:
            return None, "no_such_language" if not it["primary"] else "http_404"
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        ct = (r.headers.get("Content-Type") or "").lower()
        if r.content[:5] == b"%PDF-":
            ok, txt = pdf_has_text(r.content)
            if not ok:
                queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, it["url"], pol)
                return None, "scanned_pdf_queued"
            txt = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", txt.replace("\f", "\n"))).strip()
            fmt = "pdf_text"
        elif "html" in ct:
            root = LH.fromstring(r.content)
            txt = btext(root.xpath("//body")[0] if root.xpath("//body") else root)
            fmt = "html"
        else:
            return None, f"unsupported:{ct[:30]}"
        txt = "\n".join(re.sub(r"\s{3,}", "  ", l.strip()) for l in txt.split("\n"))
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        lg = _ch_lang(txt)
        if lg and lg != it["lang"]:
            return None, f"lang_mismatch_{lg}"
        title = it["title"]   # LexFind listing title (clean) for the primary language
        if not it["primary"]:
            title, _a, _s = _ch_title(txt, it["title"], it.get("sysnr"))
        adopted, stand = _ch_dates(txt)
        if not it["primary"] and title == it["title"]:
            title = next((l for l in txt.split("\n")[:12] if len(l) > 8 and not re.match(r"^[\d.\s]+$", l)), title)
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"],
                    doc_type=CH_CAT_TYPE.get(it["cat"], "other"), language=it["lang"], title_native=title,
                    number=(f"{self.abbr} {it['sysnr']}" if it.get("sysnr") else None), adopted_date=adopted, in_force=True,
                    consolidated=True, content_format=fmt, text=txt, source_policy=pol,
                    source_org="LexFind (Schweizerische Staatsschreiberkonferenz); text from the cantonal systematic collection",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id=self.abbr,
                    lexfind_tol_id=it["tol_id"], stand=stand, systematic_number=it.get("sysnr"), lexfind_category_id=it["cat"],
                    lexfind_category=CH_CAT_NAME.get(it["cat"])), "ok"


for _a in CH_CANTONS:
    ADAPTERS[f"ch_lexfind_{_a.lower()}"] = (lambda a: (lambda: LexFindCH(a)))(_a)


# ================================================================== Italy: regions / autonomous provinces
IT_REGIONS = {  # iso suffix: (name, qid)
    "65": ("Abruzzo", "Q1284"), "77": ("Basilicata", "Q1452"), "78": ("Calabria", "Q1458"), "72": ("Campania", "Q1438"),
    "45": ("Emilia-Romagna", "Q1263"), "36": ("Friuli-Venezia Giulia", "Q1250"), "62": ("Lazio", "Q1282"),
    "42": ("Liguria", "Q1256"), "25": ("Lombardia", "Q1210"), "57": ("Marche", "Q1279"), "67": ("Molise", "Q1443"),
    "21": ("Piemonte", "Q1216"), "75": ("Puglia", "Q1447"), "88": ("Sardegna", "Q1462"), "82": ("Sicilia", "Q1460"),
    "52": ("Toscana", "Q1273"), "32": ("Trentino-Alto Adige/Südtirol", "Q1237"), "55": ("Umbria", "Q1280"),
    "23": ("Valle d'Aosta/Vallée d'Aoste", "Q1222"), "34": ("Veneto", "Q1243"),
    "BZ": ("Provincia autonoma di Bolzano/Bozen", None), "TN": ("Provincia autonoma di Trento", None),
}
for _c, (_n, _q) in IT_REGIONS.items():
    PLACES[f"IT-{_c}"] = dict(place_id=f"iso:IT-{_c}", country_code="IT", place_name=_n, qid=_q, iso_3166_2=f"IT-{_c}",
                              admin_level=("adm2_autonomous_province" if _c in ("BZ", "TN") else "adm1"))

IT_MON = {m: i + 1 for i, m in enumerate("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split())}


class ToscanaRN:
    """Raccolta Normativa della Regione Toscana (Consiglio regionale). Discovery: URNs from the CC BY 3.0 bulk AKN datasets
    (scarica-i-dati, legislatures I-X = 1970-2020); text: current (vigente) full-text page per act."""
    key, cc, place, platform, min_chars = "it_tos_raccolta", "IT", "IT-52", "it_tos_raccoltanormativa", 80
    HOST = "https://raccoltanormativa.consiglio.regione.toscana.it"
    DATA = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data/it_tos/urns.tsv")
    LICENSE = ("Raccolta Normativa Regione Toscana: datasets released under CC BY 3.0 (scarica-i-dati); site terms: 'I documenti "
               "sono liberamente utilizzabili a condizione che ne sia citata la fonte'. Source: Consiglio regionale della Toscana. "
               "Not the legally binding text (BURT is)")
    KIND = {"legge": "statute", "regolamento.giunta": "regulation", "regolamento.consiglio": "regulation"}

    def discover(self, sess):
        items, seen = [], set()
        import os as _os
        files = [self.DATA] + ([str(self.DATA).replace("urns.tsv", "urns_post2020.tsv")]
                               if _os.path.exists(str(self.DATA).replace("urns.tsv", "urns_post2020.tsv")) else [])
        for line in (l for f in files for l in open(f, encoding="utf-8")):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            tipo, date, num = parts[:3]
            if (tipo, date, num) in seen:
                continue
            seen.add((tipo, date, num))
            urn = f"urn:nir:regione.toscana:{tipo}:{date};{num}"
            items.append({"doc_id": f"it_tos:{tipo}:{date}:{num.replace('/', '')}", "urn": urn, "tipo": tipo, "date": date, "num": num,
                          "url": f"{self.HOST}/articolo?urndoc={urn}&pr=idx,0;artic,1;articparziale,0"})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        if len(r.content) < 500:
            # 2026-10-19: the site answers HTTP 200 with a 59-byte "1 caricamento del documento fallito: verificare il
            # percorso" for URNs it cannot resolve (and, at 2026-10-19 07:11Z, transiently for 109 URNs that load
            # fine since). Recorded as load_failed (retry with run_full.py --retry-status load_failed).
            return None, "load_failed"
        doc = LH.fromstring(r.content.decode("utf-8", "replace"))
        tipo_box = doc.xpath('//*[@id="NIR_tes_tipo"]')
        cls = tipo_box[0].get("class", "") if tipo_box else ""
        tipodoc = " ".join(" ".join(doc.xpath('//*[contains(@class,"NIR_Tipodocumento")]//text()')).split())
        if "abrog" in (cls + " " + tipodoc).lower():
            return None, "repealed_or_revoked"
        head = doc.xpath('//*[@id="doc_tes_intestazione"]')
        body = doc.xpath('//*[@id="doc_cor_contenuto"]')
        if not head or not body:
            return None, "no_body"
        intest = " ".join(" ".join(head[0].xpath('.//*[contains(@class,"intestazione")]//text()')).split())
        title = " ".join(" ".join(head[0].xpath('.//*[contains(@class,"titoloDoc")]//text()')).split())
        pub = " ".join(" ".join(head[0].xpath('.//*[contains(@class,"pubblicazione")]//text()')).split())
        text = "\n".join(x for x in (intest, title, pub) if x) + "\n\n" + btext(body[0])
        title = re.sub(r"\s+([.,;])", r"\1", title).rstrip(" .") or intest
        pm = re.search(r"del (\d{1,2}) (\w+) (\d{4})", pub)
        pubd = f"{pm.group(3)}-{IT_MON.get(pm.group(2).lower(), 0):02d}-{int(pm.group(1)):02d}" if pm and pm.group(2).lower() in IT_MON else None
        kind = self.KIND[it["tipo"]]
        number = (f"l.r. {it['num']}/{it['date'][:4]}" if it["tipo"] == "legge" else
                  f"d.p.g.r. {it['num']}/{it['date'][:4]}" if it["tipo"] == "regolamento.giunta" else f"reg. cons. {it['num']}/{it['date'][:4]}")
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"].split("&pr=")[0],
                    doc_type=kind, language="it", title_native=title, number=number, adopted_date=it["date"], published_date=pubd,
                    in_force=True, consolidated=("vigente" in tipodoc.lower() or "coordinat" in tipodoc.lower()),
                    content_format="html", text=text, source_policy=pol, source_org="Consiglio regionale della Toscana - Raccolta Normativa",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="toscana", urn_nir=it["urn"],
                    text_version_label=tipodoc or None, header=intest), "ok"


ADAPTERS[ToscanaRN.key] = ToscanaRN


# ------------------------------------------------------------------ NormeInRete (NIR) XML -> text (regional bulk datasets)
_NIR_BLOCK = {"articolo", "comma", "rubrica", "p", "el", "en", "ep", "capo", "titolo", "sezione", "libro", "parte",
              "intestazione", "titoloDoc", "emanante", "formulainiziale", "formulafinale", "preambolo", "visto", "considerato",
              "conclusione", "dataeluogo", "sottoscrizioni", "sottoscrivente", "annesso", "corpo", "alinea", "coda", "h:p", "div",
              "tr", "table", "virgolette", "li", "br"}


def nir_text(root):
    """Plain text of a NIR document body (skips <meta>, <ndr> footnote refs)."""
    out = []

    def local(t):
        return t.split("}")[-1] if isinstance(t, str) else ""

    def walk(e):
        tg = local(e.tag)
        if tg in ("meta", "ndr", "redazionale", "descrittori", "inlinemeta"):
            if e.tail:
                out.append(" ".join(e.tail.split(" ")))
            return
        blk = tg in _NIR_BLOCK or tg == "p"
        if blk:
            out.append("\x00")
        if tg == "numDoc" and not (e.text or "").strip().lower().startswith("n"):
            out.append("n. ")
        if e.text:
            out.append(e.text)
        for c in e:
            walk(c)
        if blk:
            out.append("\x00")
        elif tg in ("tipoDoc", "dataDoc", "numDoc", "num"):
            out.append(" ")
        if e.tail:
            out.append(e.tail)
    walk(root)
    t = " ".join("".join(out).split(" "))
    t = re.sub(r"[ \t\r\n]+", " ", t)
    t = "\n".join(l.strip() for l in t.split("\x00"))
    t = re.sub(r"\s+,\s*n\.\s*n\.\s*", ", n. ", t)
    t = re.sub(r"\bn\.\s*n\.\s+", "n. ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


class EmiliaRomagnaDemetra:
    """Demetra (Assemblea legislativa Emilia-Romagna) weekly bulk datasets, CC BY 4.0: testi vigenti of LR / RR / RI per
    legislature, NIR XML (data/it_er/<leg>_<tipo>_xml.zip, refreshed by data/it_er/dl.sh). No per-document crawling."""
    key, cc, place, platform, min_chars = "it_er_demetra", "IT", "IT-45", "it_er_demetra", 80
    DIR = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data/it_er")
    LICENSE = ("Demetra - Assemblea legislativa della Regione Emilia-Romagna: datasets of current texts of regional laws and "
               "regulations released under CC BY 4.0 (link-utili/scarica-i-dati). Not the legally binding text (BURERT is)")
    TIPO = {"LR": ("statute", "legge"), "RR": ("regulation", "regolamento"), "RI": ("regulation", "regolamento.interno")}

    def discover(self, sess):
        import zipfile, glob
        items = []
        for zp in sorted(glob.glob(f"{self.DIR}/*_xml.zip")):
            try:
                z = zipfile.ZipFile(zp)
            except Exception:
                continue
            for n in z.namelist():
                m = re.match(r"^(\d+)_(LR|RR|RI)_(\d{4})_(\d+)\.xml$", n.split("/")[-1])
                if m:
                    items.append({"doc_id": f"it_er:{m.group(2)}:{m.group(3)}:{m.group(4)}", "zip": zp, "member": n, "leg": m.group(1),
                                  "tipo": m.group(2), "year": m.group(3), "num": m.group(4),
                                  "url": f"file://{zp}#{n}"})
        return items

    def fetch(self, sess, it):
        import zipfile
        from datetime import date
        raw = zipfile.ZipFile(it["zip"]).read(it["member"])
        root = etree.fromstring(raw, parser=etree.XMLParser(recover=True, huge_tree=True))
        if root is None:
            return None, "xml_error"
        tipo_nir = root.get("tipo") or ""
        def first(xp):
            r = root.xpath(xp)
            return r[0] if r else None
        dd = first('//*[local-name()="dataDoc"]')
        tit = first('//*[local-name()="titoloDoc"]')
        title = " ".join("".join(t for t in tit.itertext()).split()) if tit is not None else ""
        title = re.sub(r"\s*\(\d+\)\s*$", "", title).strip()
        if title.isupper():
            title = title.capitalize()
        norm = dd.get("norm") if dd is not None else None
        adopted = f"{norm[:4]}-{norm[4:6]}-{norm[6:8]}" if norm and re.match(r"^\d{8}$", norm) else it["year"]
        pub = first('//*[local-name()="pubblicazione"]')
        pn = pub.get("norm") if pub is not None else None
        pubd = f"{pn[:4]}-{pn[4:6]}-{pn[6:8]}" if pn and re.match(r"^\d{8}$", pn) else None
        orig = first('//*[local-name()="originale"]')
        urn = orig.get("{http://www.w3.org/1999/xlink}href") if orig is not None else None
        notes = " ".join(" ".join(n.itertext()) for n in root.xpath('//*[local-name()="redazionale"]//*[local-name()="nota"]'))[:20000]
        body = [e for e in root if isinstance(e.tag, str)]
        text = nir_text(body[0] if len(body) == 1 else root)
        if any("abrog" in (a.get("status") or "").lower() for a in root.xpath('//*[local-name()="articolato"]')):
            return None, "repealed_or_revoked"
        if re.search(r"(?i)\b(legge|regolamento)\s+(?:interamente\s+)?abrogat[oa]\b", notes[:3000]) or re.search(r"(?i)^\s*abrogat[ao]\b", notes):
            return None, "repealed_or_revoked"
        kind, nirt = self.TIPO[it["tipo"]]
        number = f"{'L.R.' if it['tipo'] == 'LR' else 'R.R.' if it['tipo'] == 'RR' else 'Reg. int.'} {it['num']}/{it['year']}"
        src = (f"https://demetra.regione.emilia-romagna.it/al/articolo?urn=er:assemblealegislativa:{nirt}:{it['year']};{it['num']}"
               if it["tipo"] in ("LR", "RR") else "https://demetra.regione.emilia-romagna.it/al/link-utili/scarica-i-dati/")
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=src, doc_type=kind, language="it",
                    title_native=title or number, number=number, adopted_date=adopted, published_date=pubd, in_force=True,
                    consolidated=(tipo_nir == "vigente"), content_format="xml", text=text, source_policy="open_data_bulk_cc_by_4",
                    source_org="Assemblea legislativa della Regione Emilia-Romagna - Demetra", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="emilia-romagna", urn_nir=urn, legislatura=it["leg"],
                    nir_tipo=tipo_nir, bulk_file=it["zip"].split("/")[-1] + "#" + it["member"]), "ok"


ADAPTERS[EmiliaRomagnaDemetra.key] = EmiliaRomagnaDemetra


def xml_fix_entities(raw: bytes) -> bytes:
    """Replace HTML named entities (&egrave; ...) that plain XML parsers drop; keep the 5 XML ones."""
    from html.entities import name2codepoint
    keep = {"amp", "lt", "gt", "quot", "apos"}
    def rep(m):
        n = m.group(1).decode()
        return m.group(0) if n in keep or n not in name2codepoint else f"&#{name2codepoint[n]};".encode()
    raw = re.sub(rb"<!DOCTYPE[^\[>]*(\[[^\]]*\])?>", b"", raw, count=1)
    return re.sub(rb"&([A-Za-z][A-Za-z0-9]*);", rep, raw)


def _it_clean_title(t):
    t = " ".join(t.split())
    t = re.sub(r"\s*\(\s*(?:B\.?\s?U\.?|BURL)\b[^)]*\)\s*$", "", t)
    t = re.sub(r"(?:\s*\(\d+\))+\s*$", "", t)
    t = re.sub(r"\s*\(\s*(?:B\.?\s?U\.?|BURL)\b[^)]*\)\s*$", "", t)
    t = re.sub(r"(?:\s*\(\d+\))+\s*\.?\s*$", "", t).strip()
    t = t.strip().rstrip(". ").strip()
    if len(t) > 2 and t[0] in "\"“«" and t[-1] in "\"”»":
        t = t[1:-1].strip()
    return t


class LombardiaCRL:
    """Consiglio regionale della Lombardia: law list from the CC0 open dataset 'CRL - Leggi Regionali della Lombardia'
    (dati.lombardia.it abjw-hhay, Socrata API), current text as NIR XML from normelombardia (xmain_xml.aspx)."""
    key, cc, place, platform, min_chars = "it_lom_crl", "IT", "IT-25", "it_lom_normelombardia", 80
    API = "https://www.dati.lombardia.it/resource/abjw-hhay.json"
    LICENSE = ("Law list: CC0 1.0 open dataset 'CRL - Leggi Regionali della Lombardia' (Consiglio Regionale della Lombardia, "
               "dati.lombardia.it); texts: normelombardia (OpenLeggiLombardia), Consiglio regionale della Lombardia; not the official BURL text")

    def discover(self, sess):
        import json as _j
        from urllib.parse import urlencode
        items, off = [], 0
        while True:
            q = urlencode({"$limit": 1000, "$offset": off, "$order": "ids"})
            r, _ = sess.get(f"{self.API}?{q}")
            rows = _j.loads(r.content)
            for x in rows:
                st = (x.get("stato_legge") or "").strip().lower()
                if st != "vigente":
                    continue
                ids = x["ids"]
                items.append({"doc_id": f"it_lom:{ids}", "ids": ids, "title": x.get("titolo"), "estremi": x.get("estremi"),
                              "data": (x.get("data_legge") or "")[:10], "num": x.get("numero_legge"), "burl": x.get("numero_burl"),
                              "data_burl": (x.get("data_burl") or "")[:10], "mod": (x.get("data_ultima_modifica") or "")[:10],
                              "url": f"https://normelombardia.consiglio.regione.lombardia.it/normelombardia/accessibile/xmain_xml.aspx?view=showdoc&iddoc={ids}"})
            if len(rows) < 1000:
                break
            off += 1000
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        if b"<NIR" not in r.content[:3000]:
            return None, "no_xml"
        root = etree.fromstring(xml_fix_entities(r.content), parser=etree.XMLParser(recover=True, huge_tree=True))
        if root is None:
            return None, "xml_error"
        art = root.xpath('//*[local-name()="articolato"]')
        if not art or len("".join(art[0].itertext()).strip()) < 20:
            return None, "no_article_text"   # metadata-only entry (e.g. amending law already merged into the amended text)
        text = nir_text(root)
        amended = bool(root.xpath('//*[local-name()="nota"][contains(@*[local-name()="class"],"Passiva")]'))
        urn = root.xpath('string(//*[local-name()="urn"][1])').strip() or None
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform,
                    source_url=it["url"].replace("xmain_xml.aspx", "main.aspx"),
                    doc_type=("regulation" if it["ids"].startswith("rr") else "statute"), language="it",
                    title_native=_it_clean_title(it["title"] or it["estremi"] or ""),
                    number=f"{'r.r.' if it['ids'].startswith('rr') else 'l.r.'} {it['num']}/{it['data'][:4]}",
                    adopted_date=it["data"] or None, published_date=it["data_burl"] or None, in_force=True, consolidated=amended,
                    content_format="xml", text=text, source_policy=pol, source_org="Consiglio regionale della Lombardia",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="lombardia", urn_nir=urn,
                    burl_number=it["burl"], last_modified=it["mod"] or None, crl_ids=it["ids"]), "ok"


ADAPTERS[LombardiaCRL.key] = LombardiaCRL


class CalabriaCRC:
    """Consiglio regionale della Calabria, Banca dati della Legislazione (bdf): per-legislature law lists (open data on
    dati.gov.it, CC BY 4.0: /bdf/api/CTG?Legislatura=N) + plain-text current version (/bdf/api/BDF?numero=&anno=&tipo=TXT).
    robots.txt: 'Request-rate: 1/30' -> one request per 30 s (PoliteSession honours it)."""
    key, cc, place, platform, min_chars = "it_cal_crc", "IT", "IT-78", "it_cal_bdf", 80
    HOST = "https://www.consiglioregionale.calabria.it"
    LICENSE = ("Consiglio regionale della Calabria - Banca dati della legislazione regionale; law lists published as open data "
               "under CC BY 4.0 (dati.gov.it); legislative texts are excluded from copyright (L. 633/1941 art. 5). Not the official BURC text")

    def discover(self, sess):
        items, seen = [], set()
        for leg in range(1, 14):
            r, _ = sess.get(f"{self.HOST}/bdf/api/CTG?Legislatura={leg}")
            if r.status_code != 200 or b"<LEGGI" not in r.content[:2000]:
                continue
            root = etree.fromstring(r.content, parser=etree.XMLParser(recover=True))
            for L in root.iter("LEGGE"):
                g = lambda t: (L.findtext(t) or "").strip()
                if g("TESTO").lower() != "vigente":
                    continue
                num, data = g("NUMERO"), g("DATA")
                key = (g("TIPO"), data[:4], num)
                if key in seen or not num or not data:
                    continue
                seen.add(key)
                items.append({"doc_id": f"it_cal:{g('TIPO')}:{data[:4]}:{num}", "num": num, "data": data[:10], "pub": g("DATAPUB")[:10],
                              "tipo": g("TIPO"), "title": " ".join(g("TITOLO").split()), "leg": leg,
                              "url": f"{self.HOST}/bdf/api/BDF?numero={num}&anno={data[:4]}&tipo=TXT",
                              "page": f"{self.HOST}/bdf/api/BDF?numero={num}&anno={data[:4]}"})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        raw = r.content
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:
            txt = raw.decode("cp1252", "replace")
        txt = "\n".join(" ".join(l.split()) for l in txt.replace("\r", "").split("\n"))
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        if re.match(r"(?is)^.{0,400}\b(?:legge|regolamento)\s+abrogat", txt):
            return None, "repealed_or_revoked"
        kind = "regulation" if it["tipo"].lower().startswith("reg") else "statute"
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["page"], doc_type=kind, language="it",
                    title_native=_it_clean_title(it["title"]) or f"Legge regionale n. {it['num']}/{it['data'][:4]}",
                    number=f"{'r.r.' if kind == 'regulation' else 'l.r.'} {it['num']}/{it['data'][:4]}", adopted_date=it["data"],
                    published_date=it["pub"] or None, in_force=True, consolidated=True, content_format="html", text=txt,
                    source_policy=pol, source_org="Consiglio regionale della Calabria", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="calabria", legislatura=it["leg"], text_url=it["url"], source_text_format="text/plain"), "ok"


ADAPTERS[CalabriaCRC.key] = CalabriaCRC


class LazioCRL:
    """Consiglio regionale del Lazio, banca dati leggi regionali, testo coordinato (sv=vigente). Discovery: per-year
    result lists (?vw=leggiregionali&sv=vigente&annoLegge=Y&pg=N); text: ?vw=leggiregionalidettaglio&id=..&sv=vigente."""
    key, cc, place, platform, min_chars = "it_laz_crl", "IT", "IT-62", "it_laz_consiglio", 80
    HOST = "https://www.consiglio.regione.lazio.it"
    LICENSE = ("Consiglio regionale del Lazio, testo coordinato (not legally binding; BUR is). Site content under CC BY-NC-SA 2.0 IT; "
               "the statute text itself is excluded from copyright (L. 633/1941 art. 5)")

    @staticmethod
    def _dec(b):
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", b.decode("cp1252", "replace"))

    def discover(self, sess):
        import datetime as _dt
        items, seen = [], set()
        for y in range(1970, _dt.date.today().year + 1):
            pg = 1
            while pg < 200:
                r, _ = sess.get(f"{self.HOST}/?vw=leggiregionali&sv=vigente&annoLegge={y}&pg={pg}")
                s = self._dec(r.content)
                found = 0
                for m in re.finditer(r"href='\?vw=leggiregionalidettaglio&amp;id=(\d+)&amp;sv=vigente' title=\"([^\"]*)\"", s):
                    i = m.group(1)
                    if i in seen:
                        continue
                    seen.add(i); found += 1
                    items.append({"doc_id": f"it_laz:{i}", "id": i, "year": y, "title": m.group(2),
                                  "url": f"{self.HOST}/?vw=leggiregionalidettaglio&id={i}&sv=vigente"})
                if not found or f"annoLegge={y}&amp;pg={pg + 1}'" not in s:
                    break
                pg += 1
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        doc = LH.fromstring(self._dec(r.content))
        box = doc.xpath('//*[@id="contenuto_legge"]')
        full = " ".join(doc.text_content().split())
        if not box or not "".join(box[0].xpath("./p//text()")).strip():   # older laws: a plain table (tr1 'L.R. ...', tr2 title, tr3 body, tr4 disclaimer)
            tb = [t for t in doc.xpath('//table') if t.xpath('.//tr') and
                  re.match(r"L\.R\.\s", " ".join(t.xpath('.//tr')[0].text_content().split()))]
            if not tb:
                return None, "no_body"
            trs = tb[0].xpath('.//tr')
            bl = [btext(tr).strip() for tr in trs[2:] if not " ".join(tr.text_content().split()).startswith("Il testo non ha valore legale")]
            body = "\n\n".join(b for b in bl if b)
            if len(body) < 40:
                return None, "no_body"
            return self._rec(it, pol, full, re.sub(r"\n{3,}", "\n\n", body))
        mh = re.search(r"legge num\. (\d+\w*) del (\d{1,2}) (\w+) (\d{4})", full)
        mb = re.search(r"Data BUR: (\d{2})/(\d{2})/(\d{4})", full)
        mbn = re.search(r"Numero BUR: (.+?)Data BUR", full)
        ps = box[0].xpath("./p")
        start = 0
        for k, p in enumerate(ps):   # body starts at the 2nd standalone 'Art. 1' heading (the 1st block is the SOMMARIO)
            if " ".join(p.text_content().split()) == "Art. 1":
                start = k; break
        if start == 0 and ps and " ".join(ps[0].text_content().split()) == "SOMMARIO":
            start = next((k for k, p in enumerate(ps) if k > 0 and not re.match(r"^Art\. \d+\w*\s*\(", " ".join(p.text_content().split()))
                          and " ".join(p.text_content().split())), 0)
        lines = []
        for p in ps[start:]:
            if "firma_legge" in (p.get("id"), p.get("class")):
                continue
            t = " ".join(p.text_content().split())
            if t:
                lines.append(t)
        if not lines:
            return None, "no_body"
        body = re.sub(r"(?m)^(Art\. \d+\w*(?: \w+)?)\n(\()", r"\1 \2", "\n".join(lines))
        return self._rec(it, pol, full, body)

    LAZ_ABR = re.compile(r"(?m)^\(\d+\w?\)\s*Legge (?:regionale )?(?:\S+ )?abrogata\b|\A.{0,400}?\bed\s+abrogata dal", re.S)

    def _rec(self, it, pol, full, body):
        if self.LAZ_ABR.search(body):
            return None, "repealed_or_revoked"
        mh = re.search(r"legge num\. (\d+\w*) del (\d{1,2}) (\w+) (\d{4})", full)
        mb = re.search(r"Data BUR: (\d{2})/(\d{2})/(\d{4})", full)
        mbn = re.search(r"Numero BUR: (.+?)Data BUR", full)
        date = (f"{mh.group(4)}-{IT_MON.get(mh.group(3).lower(), 0):02d}-{int(mh.group(2)):02d}"
                if mh and mh.group(3).lower() in IT_MON else str(it["year"]))
        num = mh.group(1) if mh else None
        head = f"Legge regionale {mh.group(2)} {mh.group(3)} {mh.group(4)}, n. {num}" if mh else ""
        text = (head + "\n" + it["title"] + "\n\n" + body).strip()
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type="statute",
                    language="it", title_native=_it_clean_title(it["title"]) or head, number=(f"l.r. {num}/{mh.group(4)}" if mh else None),
                    adopted_date=date, published_date=(f"{mb.group(3)}-{mb.group(2)}-{mb.group(1)}" if mb else None), in_force=True,
                    consolidated=True, content_format="html", text=text, source_policy=pol, source_org="Consiglio regionale del Lazio",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="lazio", lazio_id=it["id"],
                    bur_number=(mbn.group(1).strip() if mbn else None)), "ok"


ADAPTERS[LazioCRL.key] = LazioCRL


class FVGLexview:
    """Friuli Venezia Giulia - Lexview (Consiglio regionale / Insiel): testo vigente per law at
    /fontinormative/xml/xmlLex.aspx?anno=Y&legge=N. The chronological index is an ASP.NET postback tree, so discovery
    enumerates (year, number) candidates; after 6 consecutive misses in a year the rest of that year is skipped
    without requests (marked skip_beyond_end; clear done.tsv lines to re-probe a year)."""
    key, cc, place, platform, min_chars = "it_fvg_lexview", "IT", "IT-36", "it_fvg_lexview", 80
    HOST = "https://lexview-int.regione.fvg.it"
    MAXN = 90
    LICENSE = ("Friuli Venezia Giulia Lexview: reproduced from the BUR text, not official; statute text excluded from copyright "
               "(L. 633/1941 art. 5)")

    def __init__(self):
        self.miss = {}

    def discover(self, sess):
        import datetime as _dt
        return [{"doc_id": f"it_fvg:lr:{y}:{n}", "year": y, "n": n,
                 "url": f"{self.HOST}/fontinormative/xml/xmlLex.aspx?anno={y}&legge={n}"}
                for y in range(1964, _dt.date.today().year + 1) for n in range(1, self.MAXN + 1)]

    def fetch(self, sess, it):
        y = it["year"]
        if self.miss.get(y, 0) >= 6:
            return None, "skip_beyond_end"
        r, pol = sess.get(it["url"])
        if r.status_code != 200 or "/Errore/" in r.url:
            self.miss[y] = self.miss.get(y, 0) + 1
            return None, "not_found"
        doc = LH.fromstring(r.content)
        box = doc.xpath('//*[@id="testoint"]')
        nir = doc.xpath('//*[@id="testoint"]//div[contains(@class,"NIR")]')
        if not box or not nir:
            self.miss[y] = self.miss.get(y, 0) + 1
            return None, "not_found"
        self.miss[y] = 0
        head = " ".join(" ".join(box[0].xpath('.//div[@class="intestazione"]//div[@class="h3"]//text()')).split())
        head = re.sub(r"\s+([,.;])", r"\1", head)
        stato = " ".join(" ".join(box[0].xpath('.//*[@id="PageBody_lbTestoMulti" or @id="PageBody_lbTesto"]//text()')).split())
        src = " ".join(" ".join(box[0].xpath('.//div[contains(@class,"sottotitoloDoc")]//text()')).split())
        if re.search(r"(?i)abrogat", stato) or (not re.search(r"(?i)vigente", stato) and re.search(r"(?i)\babrogat[ao]\b", src[:300])):
            return None, "repealed_or_revoked"
        mh = re.match(r"(?i)(Legge regionale|Legge costituzionale|Regolamento)\s+(\d{1,2})\s+(\w+)\s+(\d{4}),\s*n\.\s*(\S+?)\s+(.*)$", head)
        title = mh.group(6) if mh else head
        date = (f"{mh.group(4)}-{IT_MON.get(mh.group(3).lower(), 0):02d}-{int(mh.group(2)):02d}"
                if mh and mh.group(3).lower() in IT_MON else str(y))
        body = btext(nir[0])
        if len(body) < 40:
            return None, "no_article_text"
        mnote = re.search(r"(?s)Note riguardanti modifiche apportate all.intera legge:(.{0,1500}?)(?:\n\s*Art\.|$)", body)
        if mnote and re.search(r"(?i)\d?\s*Legge abrogata\b", mnote.group(1)):
            return None, "repealed_or_revoked"
        mv = re.search(r"Data di entrata in vigore:\s*(\d{2})/(\d{2})/(\d{4})", src)
        text = head + "\n" + (stato + "\n" if stato else "") + "\n" + body
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type="statute",
                    language="it", title_native=_it_clean_title(title) or head, number=f"l.r. {it['n']}/{y}", adopted_date=date,
                    effective_date=(f"{mv.group(3)}-{mv.group(2)}-{mv.group(1)}" if mv else None), in_force=True,
                    consolidated=bool(re.search(r"(?i)vigente", stato)), content_format="html", text=text, source_policy=pol,
                    source_org="Consiglio regionale / Regione Friuli Venezia Giulia - Lexview", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="fvg", text_status=stato or None, bur_source=src[:300] or None), "ok"


ADAPTERS[FVGLexview.key] = FVGLexview


class MarcheCRM:
    """Consiglio regionale delle Marche - banca dati leggi e regolamenti regionali, testo vigente (arc=vig).
    Discovery: cronologico.php?arc=vig&anno=Y (entries flagged 'Abr.' are skipped); text: dettaglio.php?arc=vig&idl=N."""
    key, cc, place, platform, min_chars = "it_mar_crm", "IT", "IT-57", "it_mar_consiglio", 80
    BASE = "https://www.consiglio.marche.it/banche_dati_e_documentazione/leggi"
    LICENSE = ("Consiglio regionale delle Marche, testo vigente (not official; BUR is). Site 'Note legali' allow download for personal, "
               "non-commercial use 'salvo diversa indicazione'; the statute text itself is excluded from copyright (L. 633/1941 art. 5)")

    def discover(self, sess):
        import datetime as _dt
        out, seen = [], set()
        for y in range(1970, _dt.date.today().year + 1):
            r, _ = sess.get(f"{self.BASE}/cronologico.php?arc=vig&anno={y}")
            if r.status_code != 200:
                continue
            s = r.content.decode("cp1252", "replace")
            for m in re.finditer(r'<a href="dettaglio\.php\?arc=vig&(?:amp;)?idl=(\d+)"[^>]*>([^<]*)</a>(.{0,200}?)<br', s, re.S):
                i = m.group(1)
                if i in seen:
                    continue
                seen.add(i)
                out.append({"doc_id": f"it_mar:{i}", "idl": i, "year": y, "atto": " ".join(m.group(2).split()),
                            "abr": "Abr." in m.group(3), "url": f"{self.BASE}/dettaglio.php?arc=vig&idl={i}"})
        return out

    def fetch(self, sess, it):
        if it.get("abr"):
            return None, "repealed_or_revoked"
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        doc = LH.fromstring(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", r.content.decode("cp1252", "replace")))
        a = doc.xpath('//div[@id="atto"]')
        if not a:
            return None, "no_article_text"
        a = a[0]
        meta = {}
        for tr in a.xpath('./table//tr'):
            tds = tr.xpath('./td')
            if len(tds) == 2:
                meta[" ".join(tds[0].text_content().split()).rstrip(":")] = " ".join(tds[1].text_content().split())
        stato = meta.get("Stato", "")
        if re.search(r"(?i)abrogat", stato):
            return None, "repealed_or_revoked"
        # body = everything after the Sommario block
        kids = list(a)
        start = 0
        for k, x in enumerate(kids):
            if x.tag == "h2" and "Sommario" in x.text_content():
                start = k + 3
                break
        if start == 0:
            start = 1
        parts = []
        for x in kids[start:]:
            if x.tag in ("br", "hr"):
                continue
            t = btext(x).strip()
            if t:
                t = re.sub(r"^(Art\.\s*\S+?)\s*\(", r"\1\n(", t) if x.tag == "div" else t
                parts.append(t)
        body = "\n\n".join(parts)
        if len(body) < 40:
            return None, "no_article_text"
        atto = meta.get("Atto") or it["atto"]
        mh = re.match(r"(?i)(LEGGE STATUTARIA|LEGGE REGIONALE|REGOLAMENTO REGIONALE|REGOLAMENTO INTERNO|DELIBERAZIONE LEGISLATIVA)?\s*(\d{1,2})º?\s+(\w+)\s+(\d{4}),\s*n\.\s*(\S+)", atto)
        date = (f"{mh.group(4)}-{IT_MON[mh.group(3).lower()]:02d}-{int(mh.group(2)):02d}"
                if mh and mh.group(3).lower() in IT_MON else str(it["year"]))
        kind = (mh.group(1) or "").upper() if mh else ""
        isreg = kind.startswith("REGOLAMENTO")
        num = (f"{'r.r.' if isreg else ('l.statutaria' if 'STATUTARIA' in kind else 'l.r.')} {mh.group(5)}/{mh.group(4)}" if mh else atto)
        title = _it_clean_title(meta.get("Titolo", "")) or atto
        text = f"{atto}\n{title}\n{meta.get('Pubblicazione', '')}\n\n{body}"
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"],
                    doc_type="regulation" if isreg else "statute", language="it", title_native=title, number=num,
                    adopted_date=date, in_force=True, consolidated=True, content_format="html", text=text, source_policy=pol,
                    source_org="Consiglio regionale delle Marche", license_note=self.LICENSE, platform=self.platform,
                    platform_place_id="marche", publication=meta.get("Pubblicazione") or None, stato=stato or None,
                    materia=meta.get("Materia") or None, tema=meta.get("Tema") or None), "ok"


ADAPTERS[MarcheCRM.key] = MarcheCRM


class SardegnaBDG:
    """Regione autonoma della Sardegna - Banca dati giuridica (leggiregionali.regione.sardegna.it). Discovery: JSON
    /regional-laws/front-office/search?page=N&size=20 (2.6k leggi regionali); text: /front-office/<id>/files/pdf, a born-digital
    PDF rendered from the coordinated AKN/XML text (amended passages in [..] with footnotes)."""
    key, cc, place, platform, min_chars = "it_sar_bdg", "IT", "IT-88", "it_sar_bancadatigiuridica", 80
    API = "https://leggiregionali.regione.sardegna.it/regional-laws/front-office"
    LICENSE = ("Regione Sardegna, Banca dati giuridica (testo coordinato, not official; BURAS is); statute text excluded from "
               "copyright (L. 633/1941 art. 5)")

    def discover(self, sess):
        out, seen, page = [], set(), 0
        while True:
            r, _ = sess.get(f"{self.API}/search?page={page}&size=20&sort=date,asc")
            if r.status_code != 200:
                break
            d = r.json()
            for x in d.get("content") or []:
                if x["id"] in seen:
                    continue
                seen.add(x["id"])
                dt = x.get("date") or []
                out.append({"doc_id": f"it_sar:{x['id']}", "id": x["id"], "number": x.get("number"),
                            "date": "-".join(f"{v:02d}" if k else str(v) for k, v in enumerate(dt)) if dt else None,
                            "title": x.get("title") or "", "fileType": x.get("fileType"),
                            "url": f"{self.API}/{x['id']}/files/pdf"})
            if d.get("last", True):
                break
            page += 1
        return out

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            return None, f"http_{r.status_code}"
        ok, txt = pdf_has_text(r.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, it["url"], pol)
            return None, "scanned_pdf_queued"
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n[ \t]+", "\n", txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        if re.search(r"(?i)\bLegge (?:regionale )?abrogata\b", txt[:2500]):
            return None, "repealed_or_revoked"
        y = (it.get("date") or "")[:4]
        title = _it_clean_title(it["title"]) or txt.split("\n", 1)[0]
        mp = re.search(r"Pubblicata nel Bollettino Ufficiale[^\n]*(?:\n[^\n]{0,80})?", txt[:2000])
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform,
                    source_url=it["url"],
                    doc_type="statute", language="it", title_native=title, number=f"l.r. {it['number']}/{y}",
                    adopted_date=it.get("date") or None, in_force=None, consolidated=True,
                    content_format="pdf_text", text=txt, source_policy=pol, source_org="Regione autonoma della Sardegna",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="sardegna",
                    publication=" ".join(mp.group(0).split()) if mp else None, source_file_type=it.get("fileType")), "ok"


ADAPTERS[SardegnaBDG.key] = SardegnaBDG


class TrentoCP:
    """Provincia autonoma di Trento - Codice provinciale (Consiglio provinciale): testi coordinati. Discovery: the site's own
    search endpoint (SearchControl/CodiceProvinciale_response.aspx, tipo=dati, 50/page; read-only POST used by the public
    search page); per act: DetailControl/CodiceProvinciale_response.aspx tipoContenuto=info (status) + ultimotesto (HTML text).
    The robots-disallowed /doc/clex_*.pdf files are never requested. State acts and recepted regional acts are skipped."""
    key, cc, place, platform, min_chars = "it_tn_codprov", "IT", "IT-TN", "it_tn_codiceprovinciale", 80
    HOST = "https://www.consiglio.provincia.tn.it"
    LICENSE = ("Consiglio della Provincia autonoma di Trento, Codice provinciale (testi coordinati, not official; the BUR is); "
               "statute text excluded from copyright (L. 633/1941 art. 5)")
    KEEP = {"legge provinciale": "statute", "decreto del presidente della provincia": "regulation",
            "decreto del presidente della giunta provinciale": "regulation", "deliberazione del consiglio provinciale": "regulation",
            "deliberazione dell'ufficio di presidenza del consiglio": "regulation", "deliberazione della giunta provinciale": "regulation"}

    def _schema_markers(self, sess):
        r, _ = sess.get(f"{self.HOST}/leggi-e-archivi/codice-provinciale/Pages/ricerca-codice-provinciale.aspx")
        s = r.text
        i = s.find("setFiltroSchema(")
        d, _ = json.JSONDecoder().raw_decode(s[i + len("setFiltroSchema("):])
        return json.dumps([k.replace("F_", "M_") for k, v in d.items() if v.get("marker")])

    def discover(self, sess):
        sm = self._schema_markers(sess)
        url = f"{self.HOST}/_layouts/15/SearchControl/CodiceProvinciale_response.aspx"
        out, seen, start = [], set(), 0
        while True:
            r, _ = sess.post(url, data={"oFiltroSelected": json.dumps({"filtri": {}, "ordine": "ord1", "tipo": "AVANZATA"}),
                                        "oSchemaMarker": sm, "offset": "50", "startRow": str(start), "tipo": "dati", "tipoMarker": ""})
            if r.status_code != 200:
                break
            try:
                d = r.json()
            except ValueError:
                break
            c = d.get("contenuto") or ""
            n = 0
            for m in re.finditer(r"at_id=(\d+)\"[^>]*>.*?<div class='h3'>(.*?)</div>(?:<p class='testo-item'>(.*?)</p>)?", c, re.S):
                n += 1
                uid = m.group(1)
                if uid in seen:
                    continue
                seen.add(uid)
                h3 = LH.fromstring(f"<div>{m.group(2)}</div>").text_content().strip()
                ti = LH.fromstring(f"<div>{m.group(3) or ''}</div>").text_content().strip()
                out.append({"doc_id": f"it_tn:{uid}", "uid": uid, "atto": " ".join(h3.split()), "title": " ".join(ti.split()),
                            "url": f"{self.HOST}/leggi-e-archivi/codice-provinciale/Pages/legge.aspx?uid={uid}"})
            if n == 0 or int(d.get("restituiti") or 0) < 50:
                break
            start += n
        return out

    def fetch(self, sess, it):
        atto = it["atto"]
        mk = re.match(r"(?i)(.+?)\s+(\d{1,2})\s+(\w+)\s+(\d{4}),\s*n\.\s*(\S+)", atto)
        kind = (mk.group(1).strip().lower() if mk else atto.lower())
        dt = self.KEEP.get(kind)
        if not dt:
            return None, "out_of_scope_type"
        u = f"{self.HOST}/_layouts/15/DetailControl/CodiceProvinciale_response.aspx"
        r, pol = sess.post(u, data={"id": it["uid"], "tipoContenuto": "info"})
        if r.status_code != 200 or "Stato corrente" not in r.text:
            return None, f"http_{r.status_code}"
        info = " ".join(" ".join(LH.fromstring("<div>" + r.content.decode("utf-8", "replace") + "</div>").itertext()).split())
        ms = re.search(r"Stato corrente (.+?)(?= Pubblicazione| Materia| Data | Note|$)", info)
        stato = ms.group(1).strip().lower() if ms else ""
        if stato.startswith(("abrog", "a termine", "annullat", "decadut", "esaurit", "illegittim")):
            return None, "repealed_or_revoked"
        r, pol = sess.post(u, data={"id": it["uid"], "tipoContenuto": "ultimotesto"})
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        doc = LH.fromstring("<div>" + r.content.decode("utf-8", "replace") + "</div>")
        ws = doc.xpath('.//div[contains(@class,"WordSection")]')
        if not ws:
            return None, "no_body"
        agg = " ".join(" ".join(doc.xpath('.//div[contains(@class,"alert-head")]//text()')).split())
        body = "\n\n".join(t for t in (btext(w).strip() for w in ws) if t)
        body = re.sub(r"[ \t]*\n(?!\n)[ \t]*", " ", re.sub(r"\n{3,}", "\n\n", body))
        body = re.sub(r"(?<!\n)\n\n(?!\n)", "\n", body) if body.count("\n\n") > 3 * max(1, body.count(". ")) else body
        if len(body) < 40:
            return None, "no_body"
        body = re.sub(r"\n[ \t]+", "\n", body)
        if re.search(r"(?i)\b(?:Legge|Regolamento|Decreto) abrogat[oa]\b", body[:3000]) and len(body) < 3000:
            return None, "repealed_or_revoked"
        date = (f"{mk.group(4)}-{IT_MON[mk.group(3).lower()]:02d}-{int(mk.group(2)):02d}" if mk and mk.group(3).lower() in IT_MON else None)
        num = mk.group(5).rstrip(",") if mk else None
        abbr = {"statute": "l.p."}.get(dt, "d.p.p." if "presidente" in kind else "delib.")
        mb = re.search(r"Pubblicazione sul BUR (n\.o \S+ del \d{2}-\d{2}-\d{4})", info)
        text = (agg + "\n\n" if agg else "") + body
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type=dt,
                    language="it", title_native=_it_clean_title(it["title"]) or atto, number=(f"{abbr} {num}/{mk.group(4)}" if mk else atto),
                    adopted_date=date or "", in_force=(stato == "vigente") or None, consolidated=True, content_format="html",
                    text=text, source_policy=pol, source_org="Consiglio della Provincia autonoma di Trento", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="trento", act_type_native=kind, stato=stato or None,
                    testo_aggiornato=agg or None, bur=(mb.group(1) if mb else None)), "ok"


ADAPTERS[TrentoCP.key] = TrentoCP


class PugliaBussola:
    """Consiglio regionale della Puglia - Bussola Normativa (banca dati leggi e regolamenti regionali, testo vigente).
    Discovery: the public 'Ricerca semplice' form per year (ASP.NET postback incl. result pages); text:
    LeggeNavscroll.aspx?id=N (span#ContentPlaceHolder1_lblTesto), following the row marked VIGENTE in the Vigenze tab."""
    key, cc, place, platform, min_chars = "it_pug_bussola", "IT", "IT-75", "it_pug_bussolanormativa", 80
    B = "https://bussolanormativa.consiglio.puglia.it/public/Leges"
    LICENSE = ("Consiglio regionale della Puglia, Bussola Normativa (not official; the BURP is); statute text excluded from "
               "copyright (L. 633/1941 art. 5)")

    @staticmethod
    def _form(doc):
        return {i.get("name"): i.get("value", "") for i in doc.xpath('//input[@type="hidden"]') if i.get("name")}

    def _rows(self, html, kind):
        out = []
        for m in re.finditer(r'<th scope="row" class="w-6">(\d{4})</th>\s*<td class="w-8">(\w+)</td>.*?href="LeggeNavscroll\.aspx\?id=(\d+)">(.*?)</a>', html, re.S):
            out.append({"year": int(m.group(1)), "num": m.group(2), "id": m.group(3),
                        "title": " ".join(LH.fromstring(f"<p>{m.group(4)}</p>").text_content().split()), "kind": kind})
        return out

    def discover(self, sess):
        import datetime as _dt
        url = f"{self.B}/RicercaSemplice.aspx"
        out, seen = [], set()
        for y in range(1970, _dt.date.today().year + 1):
            for kind, box in (("L", "Leggi"), ("R", "Regolamenti")):
                r, _ = sess.get(url)
                form = self._form(LH.fromstring(r.content))
                form.update({f"ctl00$ContentPlaceHolder1${box}": kind, "ctl00$ContentPlaceHolder1$cmbAnno": str(y),
                             "ctl00$ContentPlaceHolder1$btnInvia": "Avvia la Ricerca"})
                r, _ = sess.post(url, data=form)
                page, res_url = 1, r.url
                while True:
                    html = r.content.decode("utf-8", "replace")
                    for x in self._rows(html, kind):
                        if x["id"] not in seen:
                            seen.add(x["id"]); out.append(x)
                    page += 1
                    if f"ctl00$ContentPlaceHolder1$Link{page}" not in html.replace("&#39;", "'"):
                        break
                    f2 = self._form(LH.fromstring(r.content))
                    f2.update({"__EVENTTARGET": f"ctl00$ContentPlaceHolder1$Link{page}", "__EVENTARGUMENT": ""})
                    r, _ = sess.post(res_url, data=f2)
                    if page > 60:
                        break
        for x in out:
            x["doc_id"] = f"it_pug:{x['kind']}:{x['year']}:{x['num']}"
            x["url"] = f"{self.B}/LeggeNavscroll.aspx?id={x['id']}"
        return out

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        html = r.content.decode("utf-8", "replace")
        doc = LH.fromstring(html)
        sp = lambda i: " ".join(" ".join(doc.xpath(f'//*[@id="ContentPlaceHolder1_{i}"]//text()')).split())
        if sp("lblAbrogato").lower().startswith("s"):
            return None, "repealed_or_revoked"
        vig = doc.xpath('//table[@id="ContentPlaceHolder1_tVigenze"]//tr[th/a[translate(normalize-space(.),"vigente","VIGENTE")="VIGENTE"]]/th/a/@href')
        cur_url = it["url"]
        if vig:
            mid = re.search(r"id=(\d+)", vig[0])
            if mid and mid.group(1) != it["id"]:
                cur_url = f"{self.B}/LeggeNavscroll.aspx?id={mid.group(1)}"
                r, pol = sess.get(cur_url)
                doc = LH.fromstring(r.content.decode("utf-8", "replace"))
        box = doc.xpath('//*[@id="ContentPlaceHolder1_lblTesto"]/ancestor::td[1]') or doc.xpath('//*[@id="ContentPlaceHolder1_lblTesto"]')
        if not box:   # (the span's HTML is malformed; lxml closes it early, so take the enclosing cell)
            return None, "no_body"
        for el in box[0].iter():
            if not isinstance(el.tag, str):
                continue
            if el.text:
                el.text = re.sub(r"\s+", " ", el.text)
            if el.tail:
                el.tail = re.sub(r"\s+", " ", el.tail)
            if el.tag == "a" and "articolo" in (el.get("class") or ""):
                el.tail = "\n" + (el.tail or "").lstrip()
                el.text = "\n" + (el.text or "")
        body = btext(box[0])
        body = re.sub(r"\n[ \t]+", "\n", re.sub(r"[ \t]+\n", "\n", body))
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if len(body) < 40:
            return None, "no_body"
        d = sp("lblData")
        md = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
        isreg = it["kind"] == "R"
        burp = doc.xpath('//a[@id="ContentPlaceHolder1_lblBURPLink"]/@href')
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=cur_url,
                    doc_type="regulation" if isreg else "statute", language="it", title_native=_it_clean_title(it["title"]),
                    number=f"{'r.r.' if isreg else 'l.r.'} {it['num']}/{it['year']}",
                    adopted_date=(f"{md.group(3)}-{md.group(2)}-{md.group(1)}" if md else str(it["year"])), in_force=True,
                    consolidated=True, content_format="html", text=body, source_policy=pol,
                    source_org="Consiglio regionale della Puglia", license_note=self.LICENSE, platform=self.platform,
                    platform_place_id="puglia", burp_url=(burp[0] if burp else None), materia=sp("lblMateria") or None,
                    vigenze=len(doc.xpath('//table[@id="ContentPlaceHolder1_tVigenze"]//tr')) or None), "ok"


ADAPTERS[PugliaBussola.key] = PugliaBussola


# ================================================================== ARGENTINA - provinces
# In-force selection comes from the Ministry of Justice's open dataset "Base SAIJ de Normativa Provincial"
# (datos.jus.gob.ar, CC BY 4.0; metadata only, downloaded once to data/ar_saij/). SAIJ's own web texts are NOT used:
# its Reglamento de uso (Res. MJyDH 1427/2011) limits downloads to personal use and forbids obtaining contents by other
# means (blocked by terms). Texts come from each province's own official digest.
PLACES.update({
    "AR-B": dict(place_id="iso:AR-B", country_code="AR", place_name="Buenos Aires Province", qid="Q44754", iso_3166_2="AR-B",
                 admin_level="adm1"),
})
AR_SAIJ_CSV = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data/ar_saij/base-saij-normativa-provincial.csv")


def _ar_saij_inforce(prov, tipos):
    import csv
    out = []
    with open(AR_SAIJ_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["provincia_nombre"] == prov and r["tipo_norma"] in tipos and r["estado_vigencia"] == "Vigente, de alcance general":
                out.append(r)
    return out


class ARBuenosAiresNormas:
    """Provincia de Buenos Aires - Sistema de Información Normativa y Documental "Malvinas Argentinas" (normas.gba.gob.ar,
    robots allow all). For each law / decree-law that SAIJ's open dataset lists as 'Vigente, de alcance general':
    search by number -> law page (/ar-b/<tipo>/<year>/<n>/<id>) -> "Ver texto actualizado" (/documentos/<x>.html)."""
    key, cc, place, platform, min_chars = "ar_b_normas", "AR", "AR-B", "ar_b_normas_gba", 80
    HOST = "https://normas.gba.gob.ar"
    TIPOS = {"Ley": ("Law", "ley", "statute"), "Decreto Ley": ("DecreeLaw", "dley", "statute")}
    LICENSE = ("Provincia de Buenos Aires, normas.gba.gob.ar (texto actualizado; not the official Boletín Oficial). No reuse "
               "restriction found on the site; in-force status from 'Base SAIJ de Normativa Provincial' (Ministerio de Justicia, "
               "datos.jus.gob.ar, CC BY 4.0). Official legislative texts.")

    def discover(self, sess):
        items, seen = [], set()
        for r in _ar_saij_inforce("Buenos Aires", self.TIPOS):
            raw, short, _ = self.TIPOS[r["tipo_norma"]]
            n = r["numero_norma"].strip()
            if not n.isdigit() or (short, n) in seen:
                continue
            seen.add((short, n))
            q = f"{self.HOST}/resultados?q%5Bterms%5D%5Braw_type%5D={raw}&q%5Bterms%5D%5Bnumber%5D={n}"
            items.append({"doc_id": f"ar_b:{short}:{n}", "url": q, "n": n, "tipo": r["tipo_norma"], "saij": r})
        return items

    @staticmethod
    def _doc(r):
        return LH.document_fromstring(r.content.decode("utf-8", "replace"))

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        links = sorted({a.get("href") for a in self._doc(r).xpath("//a[@href]")
                        if re.match(r"^/ar-b/[a-z\-]+/\d{4}/%s/\d+$" % it["n"], a.get("href") or "")})
        if not links:
            return None, "not_found"
        page = self.HOST + links[0]
        r, pol = sess.get(page)
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        d = self._doc(r)
        for b in d.xpath("//script|//style|//nav|//header|//footer"):
            b.drop_tree()
        info = re.sub(r"[ \t\r]+", " ", d.xpath("//body")[0].text_content())
        def fld(lbl, nxt):
            m = re.search(lbl + r"\s*:?\s*(.*?)\s*(?:" + nxt + ")", info, re.S)
            return " ".join(m.group(1).split()) if m else ""
        resumen = fld("Resumen", "Observaciones|Documentos")
        obs = fld("Observaciones", "Documentos")
        if re.search(r"(?i)\bderogad[ao]\b|\babrogad[ao]\b", obs[:300]):
            return None, "repealed_or_revoked"
        upd = [a.get("href") for a in d.xpath("//a[@href]") if "texto actualizado" in " ".join(a.text_content().split()).lower()]
        orig = [a.get("href") for a in d.xpath("//a[@href]") if "texto original" in " ".join(a.text_content().split()).lower()]
        text, fmt, src = None, "html", page
        if upd:
            src = self.HOST + upd[0] if upd[0].startswith("/") else upd[0]
            r2, _ = sess.get(src)
            if r2.status_code == 200:
                t = self._doc(r2)
                for b in t.xpath("//script|//style"):
                    b.drop_tree()
                text = btext(t.xpath("//body")[0]) if t.xpath("//body") else None
        if not text and orig and orig[0].lower().endswith(".pdf"):
            src = self.HOST + orig[0] if orig[0].startswith("/") else orig[0]
            r2, _ = sess.get(src)
            ok, txt = pdf_has_text(r2.content) if r2.status_code == 200 else (False, "")
            if not ok:
                queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, src, pol)
                return None, "scanned_pdf_queued"
            text, fmt = txt, "pdf_text"
        if not text or len(text.strip()) < 40:
            return None, "no_body"
        _, _, dtype = self.TIPOS[it["tipo"]]
        s = it["saij"]
        mprom = re.search(r"Fecha de promulgaci\S+\s*:?\s*(\d{2})/(\d{2})/(\d{4})", info)
        mpub = re.search(r"Fecha de publicaci\S+\s*:?\s*(\d{2})/(\d{2})/(\d{4})", info)
        title = (s.get("titulo_resumido") or "").strip() or resumen[:300] or f"{it['tipo']} {it['n']}"
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=page, doc_type=dtype,
                    language="es", title_native=_smart_title(title) if title.isupper() else title,
                    number=f"{it['tipo']} {it['n']}", adopted_date=(f"{mprom.group(3)}-{mprom.group(2)}-{mprom.group(1)}" if mprom else (s.get("fecha") or None)),
                    publication_date=(f"{mpub.group(3)}-{mpub.group(2)}-{mpub.group(1)}" if mpub else (s.get("fecha_publicacion") or None)),
                    in_force=True, consolidated=bool(upd and fmt == "html"), content_format=fmt, text=text, source_policy=pol,
                    source_org="Provincia de Buenos Aires - Sistema de Información Normativa y Documental Malvinas Argentinas",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="ar-b", text_file_url=src,
                    summary=resumen[:2000] or None, saij_status=s.get("estado_vigencia"), saij_id=(s.get("texto_actualizado") or "").split("/")[-1] or None), "ok"


ADAPTERS[ARBuenosAiresNormas.key] = ARBuenosAiresNormas


# ---------------------------------------------------------------- AR-C  Ciudad Autónoma de Buenos Aires
PLACES.update({
    "AR-C": dict(place_id="iso:AR-C", country_code="AR", place_name="Ciudad Autónoma de Buenos Aires", qid="Q1486",
                 iso_3166_2="AR-C", admin_level="adm1"),
})


class ARCabaBoletin:
    """CABA - Boletín Oficial, Servicio de Información Normativa (boletinoficial.buenosaires.gob.ar/normativaba; robots
    allow all). For each law SAIJ's open dataset lists as 'Vigente, de alcance general': search form (POST, session
    token) by type LEY + number -> /normativaba/norma/<id> -> 'Texto actualizado' PDF (boletinoficialpdf..., updated
    consolidated text) when it has a text layer, else the inline 'Texto original' HTML."""
    key, cc, place, platform, min_chars = "ar_c_boletin", "AR", "AR-C", "ar_c_boletin_normativa", 80
    HOST = "https://boletinoficial.buenosaires.gob.ar"
    TIPOS = {"Ley": ("22", "ley", "statute"), "Texto Ordenado Ley": ("22", "ley", "statute")}
    LICENSE = ("Gobierno de la Ciudad Autónoma de Buenos Aires - Boletín Oficial / Servicio de Información Normativa "
               "(buenosaires.gob.ar content under CC BY 2.5 AR). 'Texto actualizado' is published for information only. "
               "In-force status from 'Base SAIJ de Normativa Provincial' (Ministerio de Justicia, datos.jus.gob.ar, CC BY 4.0). "
               "Official legislative texts.")

    def __init__(self):
        self._tok = None

    def discover(self, sess):
        items, seen = [], set()
        for r in _ar_saij_inforce("Ciudad Autónoma de Buenos Aires", self.TIPOS):
            n = r["numero_norma"].strip()
            if not n.isdigit() or int(n) == 0 or n in seen:   # "0" = unnumbered (e.g. constitution): a 0 search lists everything
                continue
            seen.add(n)
            items.append({"doc_id": f"ar_c:ley:{n}", "url": f"{self.HOST}/normativaba/resultados#ley={n}", "n": n,
                          "tipo": r["tipo_norma"], "saij": r})
        return items

    def _token(self, sess, force=False):
        if self._tok is None or force:
            r, _ = sess.get(self.HOST + "/normativaba")
            v = LH.document_fromstring(r.content.decode("utf-8", "replace")).xpath('//input[@name="buscador[_token]"]/@value')
            self._tok = v[0] if v else ""
        return self._tok

    def _search(self, sess, n):
        for attempt in range(2):
            r, pol = sess.post(self.HOST + "/normativaba/resultados",
                               data={"buscador[id_tipo_norma]": "22", "buscador[numero]": n,
                                     "buscador[_token]": self._token(sess, force=attempt > 0)})
            if r.status_code == 200:
                d = LH.document_fromstring(r.content.decode("utf-8", "replace"))
                hits = [(a.get("href"), " ".join(a.text_content().split())) for a in d.xpath('//a[starts-with(@href,"/normativaba/norma/")]')]
                if hits or b"buscador_normativa" not in r.content[:200000] or attempt:
                    return hits, r.status_code
        return [], r.status_code

    def fetch(self, sess, it):
        n, s = it["n"], it["saij"]
        hits, st = self._search(sess, n)
        if st != 200:
            return None, f"http_{st}"
        yr = (s.get("fecha") or "")[:4]
        hits = [h for h in hits if re.match(r"^LEY %s(\s|$)" % n, h[1])]
        if len(hits) > 1 and yr:
            hits = [h for h in hits if yr in h[1]] or hits
        if not hits:
            return None, "not_found"
        page = self.HOST + hits[0][0]
        r, pol = sess.get(page)
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        d = LH.document_fromstring(r.content.decode("utf-8", "replace"))
        for b in d.xpath("//script|//style"):
            b.drop_tree()
        det = d.xpath('//*[@id="detalle_normativa"]')
        info = " ".join((det[0] if det else d).text_content().split())
        def fld(lbl, nxt):
            m = re.search(lbl + r"\s*:\s*(.*?)\s*(?:" + nxt + r")\s*:", info)
            return m.group(1).strip() if m else ""
        sintesis = fld("Síntesis", "Publicación")
        def dmy(lbl):
            m = re.search(lbl + r"\s*:\s*(\d{2})/(\d{2})/(\d{4})", info)
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
        text, fmt, src, cons = None, "html", page, False
        pdfs = d.xpath('//*[@id="collapseFour"]//a[contains(@href,"imagen.php")]/@href')
        if pdfs:
            src = pdfs[0]
            r2, _ = sess.get(src)
            k = r2.content.find(b"%PDF", 0, 4096) if r2.status_code == 200 else -1   # PHP notices may precede the PDF
            ok, txt = pdf_has_text(r2.content[k:]) if k >= 0 else (False, "")
            if ok and len(txt.strip()) > 200:
                text, fmt, cons = txt, "pdf_text", True
        if not text:
            src = page
            orig = d.xpath('//*[@id="collapseFive"]')
            text = btext(orig[0]) if orig else None
        if not text or len(text.strip()) < 40:
            if pdfs:
                queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, pdfs[0], pol)
                return None, "scanned_pdf_queued"
            return None, "no_body"
        title = (s.get("titulo_resumido") or "").strip() or sintesis[:300] or f"Ley {n}"
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=page, doc_type="statute",
                    language="es", title_native=_smart_title(title) if title.isupper() else title, number=f"Ley {n}",
                    adopted_date=dmy("Sanción") or (s.get("fecha") or None),
                    publication_date=dmy("Publicación") or (s.get("fecha_publicacion") or None),
                    in_force=True, consolidated=cons, content_format=fmt, text=text, source_policy=pol,
                    source_org="Gobierno de la Ciudad Autónoma de Buenos Aires - Boletín Oficial (Servicio de Información Normativa)",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="ar-c", text_file_url=src,
                    summary=sintesis[:2000] or None, saij_status=s.get("estado_vigencia")), "ok"


ADAPTERS[ARCabaBoletin.key] = ARCabaBoletin


# ---------------------------------------------------------------- AR-S  Santa Fe
PLACES.update({
    "AR-S": dict(place_id="iso:AR-S", country_code="AR", place_name="Santa Fe Province", qid="Q44823",
                 iso_3166_2="AR-S", admin_level="adm1"),
})


class ARSantaFeSIN:
    """Provincia de Santa Fe - Sistema de Información de Normativa (www.santafe.gov.ar/normativa; robots.txt 404 = allow).
    For each law SAIJ's open dataset lists as 'Vigente, de alcance general': POST src/busqueda.php (type Leyes + number)
    -> item.php (metadata, relations; 'Es derogada por' => skipped) -> 'Texto completo' PDF (getFile.php; original
    sanctioned text, text layer only, scanned PDFs queued, no OCR)."""
    key, cc, place, platform, min_chars = "ar_s_normativa", "AR", "AR-S", "ar_s_sin_santafe", 80
    HOST = "https://www.santafe.gov.ar/normativa/"
    TIPOS = {"Ley": None}
    LICENSE = ("Provincia de Santa Fe - Sistema de Información de Normativa (santafe.gov.ar/normativa); original sanctioned "
               "text (PDF), not consolidated. No reuse restriction found on the site; in-force status from 'Base SAIJ de "
               "Normativa Provincial' (Ministerio de Justicia, datos.jus.gob.ar, CC BY 4.0). Official legislative texts.")

    def discover(self, sess):
        items, seen = [], set()
        for r in _ar_saij_inforce("Santa Fe", self.TIPOS):
            n = r["numero_norma"].strip()
            if not n.isdigit() or int(n) == 0 or n in seen:   # "0" = unnumbered (e.g. constitution): a 0 search lists everything
                continue
            seen.add(n)
            items.append({"doc_id": f"ar_s:ley:{n}", "url": f"{self.HOST}index.php#ley={n}", "n": n, "saij": r})
        return items

    def fetch(self, sess, it):
        n, s = it["n"], it["saij"]
        r, pol = sess.post(self.HOST + "src/busqueda.php?organismo=&tbusqueda=",
                           data={"tipoNorma": "1", "numNorma": n, "anio": "", "numExpediente": "", "frase": "alguna",
                                 "action": "buscar", "pagina": "1", "ordenarPor": "2", "ordenBusqueda": "ASC", "iniciador": ""})
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        d = LH.document_fromstring(r.content.decode("utf-8", "replace") or "<html/>")
        rows = []
        for tr in d.xpath("//tr[.//a[contains(@href,'item.php')]]"):
            cells = [" ".join(td.text_content().split()) for td in tr.xpath("./td")]
            if cells and cells[0] == n:
                rows.append((tr.xpath(".//a[contains(@href,'item.php')]/@href")[0], cells))
        if len(rows) > 1 and s.get("fecha"):
            yr = s["fecha"][:4]
            rows = [x for x in rows if yr in x[1][-2] or yr in " ".join(x[1])] or rows
        if not rows:
            return None, "not_found"
        page = self.HOST + rows[0][0]
        r, pol = sess.get(page)
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        d = LH.document_fromstring(r.content.decode("utf-8", "replace"))
        for b in d.xpath("//script|//style"):
            b.drop_tree()
        info = " ".join(d.text_content().split())
        if re.search(r"Es derogada por\s*:", info):
            return None, "repealed_or_revoked"
        desc = re.search(r"Descripci\S+\s*:\s*(.*?)\s*(?:Jurisdicci\S+\s*:|Texto completo|$)", info)
        desc = desc.group(1).strip() if desc else ""
        fecha = re.search(r"Fecha\s*:\s*(\d{2})-(\d{2})-(\d{4})", info)
        pub = re.search(r"Publicada en (?:el )?B\.?\s?O\.? el (\d{2})[-/](\d{2})[-/](\d{4})", info)
        files = d.xpath("//a[contains(@href,'getFile.php')]/@href")
        if not files:
            return None, "no_text_file"
        src = self.HOST + files[0]
        r2, _ = sess.get(src)
        if r2.status_code != 200 or r2.content[:4] != b"%PDF":
            return None, f"file_http_{r2.status_code}"
        ok, txt = pdf_has_text(r2.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, src, pol)
            return None, "scanned_pdf_queued"
        title = (s.get("titulo_resumido") or "").strip() or re.split(r"\.\s+Promulgada", desc)[0][:300] or f"Ley {n}"
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=page, doc_type="statute",
                    language="es", title_native=_smart_title(title) if title.isupper() else title, number=f"Ley {n}",
                    adopted_date=(f"{fecha.group(3)}-{fecha.group(2)}-{fecha.group(1)}" if fecha else (s.get("fecha") or None)),
                    publication_date=(f"{pub.group(3)}-{pub.group(2)}-{pub.group(1)}" if pub else (s.get("fecha_publicacion") or None)),
                    in_force=True, consolidated=False, content_format="pdf_text", text=txt, source_policy=pol,
                    source_org="Provincia de Santa Fe - Sistema de Información de Normativa",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="ar-s", text_file_url=src,
                    summary=desc[:2000] or None, saij_status=s.get("estado_vigencia")), "ok"


ADAPTERS[ARSantaFeSIN.key] = ARSantaFeSIN


# ================================================================== SOUTH AFRICA - provinces
# Official legislature/government sites only (coordinator decision 2026-10-18: no LawLibrary - its terms prohibit
# scraping/bulk download). Official texts of a legislative nature carry no copyright (Copyright Act 98 of 1978, s 12(8)(a)).
PLACES.update({
    "ZA-WC": dict(place_id="iso:ZA-WC", country_code="ZA", place_name="Western Cape", qid="Q127167", iso_3166_2="ZA-WC",
                  admin_level="adm1"),
})


class ZAWesternCapeWCPP:
    """Western Cape Provincial Parliament - Legislation list (www.wcpp.gov.za/?q=legislation, 33 pages; robots allow,
    Crawl-delay 10 honoured by PoliteSession). Acts only (rows whose name is an Act, not a Bill); text = PDF text layer,
    scanned PDFs queued (no OCR). As-passed texts, not consolidated; in_force unknown."""
    key, cc, place, platform, min_chars = "za_wc_wcpp", "ZA", "ZA-WC", "za_wc_wcpp", 200
    HOST = "https://www.wcpp.gov.za"
    LICENSE = ("Western Cape Provincial Parliament (wcpp.gov.za). Official text of a legislative nature: no copyright "
               "(South African Copyright Act 98 of 1978, s 12(8)(a)). As passed/published, not consolidated.")

    def discover(self, sess):
        items, seen, page, last = [], set(), 0, 0
        while page <= max(last, 0) and page < 80:
            r, _ = sess.get(f"{self.HOST}/?q=legislation" + (f"&page={page}" if page else ""))
            if r.status_code != 200:
                break
            d = LH.document_fromstring(r.content.decode("utf-8", "replace"))
            for a in d.xpath('//ul[contains(@class,"pager")]//a/@href'):
                m = re.search(r"page=(\d+)", a)
                if m:
                    last = max(last, int(m.group(1)))
            for tr in d.xpath("//table//tr[td]"):
                tds = [" ".join(td.text_content().split()) for td in tr.xpath("./td")]
                hrefs = tr.xpath(".//a/@href")
                if len(tds) < 2 or not hrefs:
                    continue
                num, name = tds[0], tds[1]
                if re.search(r"(?i)\bbill\b", name + " " + num) or not re.search(r"(?i)\bact\b", name) or re.match(r"(?i)^B\s?\d", num):
                    continue
                url = hrefs[0] if hrefs[0].startswith("http") else self.HOST + hrefs[0]
                if url in seen:
                    continue
                seen.add(url)
                m = re.search(r"(?i)act\s*(?:\[?\s*no\.?\s*)?(\d+)\s*(?:of|-)\s*(\d{4})", name) or re.match(r"^\s*(\d+)\s*-\s*(\d{4})", num)
                key = f"{m.group(2)}-{int(m.group(1))}" if m else hashlib.md5(url.encode()).hexdigest()[:10]
                items.append({"doc_id": f"za_wc:act:{key}", "url": url, "name": name, "num": num,
                              "year": tds[2] if len(tds) > 2 else "", "actno": m.groups() if m else None})
            page += 1
        # one doc per act number: keep the first (newest-listed) row
        out, ids = [], set()
        for it in items:
            if it["doc_id"] not in ids:
                ids.add(it["doc_id"]); out.append(it)
        return out

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        if r.content[:4] != b"%PDF":
            return None, "not_pdf"
        ok, txt = pdf_has_text(r.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, it["url"], pol)
            return None, "scanned_pdf_queued"
        no = it.get("actno")
        if not no:                                      # list column holds only the act no.; the year is in the title page
            my = re.search(r"(?i)\bACT\b[^\n]{0,80}?\b((?:19|20)\d\d)\b", " ".join(txt[:1500].split()))
            mn = re.match(r"^\s*(?:Act\s*)?(\d+)\b", it.get("num") or "")
            if my and mn:
                no = (mn.group(1), my.group(1))
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type="statute",
                    language="en", title_native=it["name"][:1000], number=(f"Act {int(no[0])} of {no[1]}" if no else it["num"] or None),
                    in_force=None, consolidated=False, content_format="pdf_text", text=txt, source_policy=pol,
                    source_org="Western Cape Provincial Parliament", license_note=self.LICENSE, platform=self.platform,
                    platform_place_id="wc", text_file_url=it["url"], listed_year=it.get("year") or None), "ok"


ADAPTERS[ZAWesternCapeWCPP.key] = ZAWesternCapeWCPP


# ---------------------------------------------------------------- AR-R  Río Negro
PLACES.update({
    "AR-R": dict(place_id="iso:AR-R", country_code="AR", place_name="Río Negro Province", qid="Q44802",
                 iso_3166_2="AR-R", admin_level="adm1"),
})


class ARRioNegroDigesto:
    """Legislatura de Río Negro - Digesto Jurídico (web.legisrn.gov.ar; robots allow all). In-force set = the Digesto's
    own base 'Digesto' (vigente, alcance general) for type Ley Provincial, listed through the public page's JSON listing
    (/apiv1/digesto/norma?base_datos=D&tipo=L, 100/page). Text: 'Texto Consolidado' PDF when available, else the
    'Texto Promulgado' PDF of the legislative antecedent (consolidated=False). Text layer only; scans queued."""
    key, cc, place, platform, min_chars = "ar_r_digesto", "AR", "AR-R", "ar_r_digesto_legisrn", 80
    HOST = "https://web.legisrn.gov.ar"
    LICENSE = ("Legislatura de la Provincia de Río Negro - Digesto Jurídico (web.legisrn.gov.ar). No reuse restriction found "
               "on the site; in-force status = membership of the official Digesto (vigente, alcance general). Official legislative texts.")

    def discover(self, sess):
        items, page, pages = [], 1, 1
        while page <= pages and page < 100:
            r, _ = sess.get(f"{self.HOST}/apiv1/digesto/norma?base_datos=D&tipo=L&page={page}")
            if r.status_code != 200:
                raise RuntimeError(f"rn listing page {page}: http {r.status_code}")   # never run on a partial listing
            pages = int(r.headers.get("X-Pagination-Page-Count") or 1)
            for x in r.json():
                if x.get("base_datos") != "Digesto":
                    continue
                items.append({"doc_id": f"ar_r:{x['asiento']}", "url": f"{self.HOST}/digesto/normas/ver?id={x['asiento']}",
                              "titulo": x.get("titulo") or "", "tema": x.get("tema_gral") or ""})
            page += 1
        return items

    def _pdf(self, sess, it, href, pol):
        src = self.HOST + href if href.startswith("/") else href
        r, _ = sess.get(src)
        if r.status_code != 200 or r.content[:4] != b"%PDF":
            return None, src
        ok, txt = pdf_has_text(r.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, src, pol)
            return "", src
        return txt, src

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        d = LH.document_fromstring(r.content.decode("utf-8", "replace"))
        for b in d.xpath("//script|//style"):
            b.drop_tree()
        info = " ".join(d.text_content().split())
        blk = d.xpath('//h4[contains(.,"Documentos:")]/following-sibling::*[1]')
        hrefs = [a.get("href") or "" for a in (blk[0].xpath(".//a") if blk else [])]
        cons = [h for h in hrefs if "/digesto/normas/documento" in h]
        orig = [h for h in hrefs if "/legislativa/legislacion/ver" in h]
        text, src, consolidated = None, it["url"], False
        if cons:
            text, src = self._pdf(sess, it, cons[0], pol)
            consolidated = bool(text)
        if not text and orig:
            r2, _ = sess.get(self.HOST + orig[0] if orig[0].startswith("/") else orig[0])
            if r2.status_code == 200:
                d2 = LH.document_fromstring(r2.content.decode("utf-8", "replace"))
                docs = [a.get("href") for a in d2.xpath('//a[contains(@href,"/legislativa/legislacion/documento")]')]
                if docs:
                    text, src = self._pdf(sess, it, docs[0], pol)
        if text == "":
            return None, "scanned_pdf_queued"
        if not text or len(text.strip()) < 40:
            return None, "no_body"
        num = re.search(r"N[ºo°]\s*(\d+)", it["titulo"])
        letra = re.search(r"Ley Provincial\s+([A-Z])\s+N", it["titulo"])
        sanc = re.search(r"Sancionada el (\d{2})-(\d{2})-(\d{4})", info)
        prom = re.search(r"Promulgada el (\d{2})-(\d{2})-(\d{4})", info)
        pend = "afectado por otras Normas desde su última consolidación" in info
        title = it["tema"].strip() or it["titulo"]
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type="statute",
                    language="es", title_native=title[:1000],
                    number=(f"Ley {letra.group(1)} Nº {num.group(1)}" if letra and num else (f"Ley {num.group(1)}" if num else it["titulo"])),
                    adopted_date=(f"{sanc.group(3)}-{sanc.group(2)}-{sanc.group(1)}" if sanc else None),
                    publication_date=None, in_force=True, consolidated=consolidated, content_format="pdf_text", text=text,
                    source_policy=pol, source_org="Legislatura de la Provincia de Río Negro - Digesto Jurídico",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="ar-r", text_file_url=src,
                    summary=it["tema"][:2000] or None, promulgation_date=(f"{prom.group(3)}-{prom.group(2)}-{prom.group(1)}" if prom else None),
                    unconsolidated_amendments_pending=pend or None), "ok"


ADAPTERS[ARRioNegroDigesto.key] = ARRioNegroDigesto


# ---------------------------------------------------------------- AR-U  Chubut
PLACES.update({
    "AR-U": dict(place_id="iso:AR-U", country_code="AR", place_name="Chubut Province", qid="Q45007",
                 iso_3166_2="AR-U", admin_level="adm1"),
})


class ARChubutDigesto:
    """Legislatura del Chubut - Digesto Jurídico público (digesto.legislaturadelchubut.gob.ar; robots allow /api/public).
    The public site's JSON listing /api/public/documentos (100/page) carries each norm's full text (textoCompleto).
    In-force set: tipo LEY_PROVINCIAL with estadoConsolidacion VIGENTE; base 'Digesto' = consolidated, 'Pendiente de
    Consolidación' = in force but not yet consolidated. Anexos are not staged separately."""
    key, cc, place, platform, min_chars = "ar_u_digesto", "AR", "AR-U", "ar_u_digesto_chubut", 80
    HOST = "https://digesto.legislaturadelchubut.gob.ar"
    LICENSE = ("Legislatura de la Provincia del Chubut - Digesto Jurídico (digesto.legislaturadelchubut.gob.ar). No reuse "
               "restriction found on the site; in-force status from the Digesto's own consolidation state. Official legislative texts.")

    def discover(self, sess):
        items, page, last = [], 0, 0
        while page <= last and page < 1000:
            r, _ = sess.get(f"{self.HOST}/api/public/documentos?page={page}&size=100")
            if r.status_code != 200:
                raise RuntimeError(f"chubut listing page {page}: http {r.status_code}")   # never run on a partial listing
            m = re.search(r"page=(\d+)&size=\d+>;\s*rel=\"last\"", r.headers.get("Link", ""))
            last = int(m.group(1)) if m else last
            for x in r.json():
                if x.get("tipo") != "LEY_PROVINCIAL" or x.get("estadoConsolidacion") != "VIGENTE" or x.get("caduca"):
                    continue
                if not (x.get("textoCompleto") or "").strip():
                    continue
                rama = (x.get("rama") or {}).get("id") if isinstance(x.get("rama"), dict) else None
                items.append({"doc_id": f"ar_u:{x['id']}", "url": f"{self.HOST}/public/rama/{rama}/ley/{x.get('numero')}" if rama else f"{self.HOST}/public",
                              "x": {k: x.get(k) for k in ("id", "numero", "numeroAnterior", "numeroCompleto", "sancionFecha",
                                                          "promulgacionFecha", "publicacionFecha", "publicacionBo", "publicacionBoUrl",
                                                          "resumen", "base", "textoCompleto", "observaciones")}})
            page += 1
        return items

    def fetch(self, sess, it):
        x = it["x"]
        text = re.sub(r"\n{3,}", "\n\n", (x.get("textoCompleto") or "").replace("\r", "")).strip()
        if len(text) < 40:
            return None, "no_body"
        title = " ".join(((x.get("resumen") or "").strip() or x.get("numeroCompleto") or f"Ley {x.get('numero')}").split())
        x = dict(x, numeroCompleto=" ".join((x.get("numeroCompleto") or "").split()) or None)
        pol = sess.allowed(it["url"])[1]
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type="statute",
                    language="es", title_native=title[:1000], number=x.get("numeroCompleto") or None,
                    adopted_date=x.get("sancionFecha") or None, publication_date=x.get("publicacionFecha") or None,
                    in_force=True, consolidated=(x.get("base") == "Digesto"), content_format="html", text=text,
                    source_policy=pol, source_org="Legislatura de la Provincia del Chubut - Digesto Jurídico",
                    license_note=self.LICENSE, platform=self.platform, platform_place_id="ar-u",
                    text_file_url=f"{self.HOST}/api/public/documentos (id {x['id']})", summary=(x.get("resumen") or "")[:2000] or None,
                    previous_number=x.get("numeroAnterior") or None, digesto_base=x.get("base") or None,
                    boletin_oficial_url=x.get("publicacionBoUrl") or None), "ok"


ADAPTERS[ARChubutDigesto.key] = ARChubutDigesto


PLACES.update({
    "ZA-EC": dict(place_id="iso:ZA-EC", country_code="ZA", place_name="Eastern Cape", qid="Q130840", iso_3166_2="ZA-EC",
                  admin_level="adm1"),
})


class ZAEasternCapeECPL:
    """Eastern Cape Provincial Legislature - Acts library (www.eclegislature.gov.za/acts/provincial is a JS app; its data
    is the public JSON list api.eclegislature.gov.za/v1/documents/list, category 'provincial_acts'; PDFs on
    docs.eclegislature.gov.za; robots 404 = allow). The list holds the newest 1000 documents only. Text layer only."""
    key, cc, place, platform, min_chars = "za_ec_ecpl", "ZA", "ZA-EC", "za_ec_ecpl", 200
    LIST = "https://api.eclegislature.gov.za/v1/documents/list"
    LICENSE = ("Eastern Cape Provincial Legislature (eclegislature.gov.za). Official text of a legislative nature: no copyright "
               "(South African Copyright Act 98 of 1978, s 12(8)(a)). As passed/published, not consolidated.")

    def discover(self, sess):
        r, _ = sess.get(self.LIST)
        if r.status_code != 200:
            raise RuntimeError(f"ec list http {r.status_code}")
        out = []
        for x in r.json().get("data", []):
            if (x.get("category") == "provincial_acts" or x.get("dir_name") == "provincial_acts") and x.get("doc_url"):
                out.append({"doc_id": f"za_ec:{x['id']}", "url": x["doc_url"], "title": re.sub(r"\.pdf$", "", x.get("title") or "", flags=re.I),
                            "date_added": x.get("date_added")})
        return out

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200 or r.content[:4] != b"%PDF":
            return None, f"http_{r.status_code}"
        ok, txt = pdf_has_text(r.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, it["url"], pol)
            return None, "scanned_pdf_queued"
        flat = " ".join(txt[:3000].split())
        if not re.search(r"(?i)PROVINCE OF (?:THE )?EASTERN CAPE|PROVINSIE|EASTERN CAPE\)", flat[:800]):
            return None, "not_provincial_act"            # e.g. national Government Gazette copies filed under provincial_acts
        m = re.search(r"(?i)\bAct\s+(?:No\.?\s*)?(\d+)\s+of\s+((?:19|20)\d\d)", flat)
        title = re.sub(r"^[\d_ -]+", "", it["title"]).replace("_", " ").replace("-", " ").strip() or it["title"]
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type="statute",
                    language="en", title_native=title[:1000], number=(f"Act {m.group(1)} of {m.group(2)}" if m else None),
                    in_force=None, consolidated=False, content_format="pdf_text", text=txt, source_policy=pol,
                    source_org="Eastern Cape Provincial Legislature", license_note=self.LICENSE, platform=self.platform,
                    platform_place_id="ec", text_file_url=it["url"], listed_date=it.get("date_added")), "ok"


ADAPTERS[ZAEasternCapeECPL.key] = ZAEasternCapeECPL


PLACES.update({
    "AR-H": dict(place_id="iso:AR-H", country_code="AR", place_name="Chaco Province", qid="Q44757",
                 iso_3166_2="AR-H", admin_level="adm1"),
})


class ARChacoDigesto:
    """Legislatura del Chaco - Digesto Jurídico (digesto.legislaturachaco.gob.ar; robots.txt 404 = allow).
    The public search grid (POST /Documentos/Documento/GetDocumentosBusquedaPublica, Kendo JSON) returns each norm's
    digested text in 'Texto'. DocumentoTipoId=1 (Ley) with VerNoVigentes unset = in-force laws only (NoVigente False).
    Identifiers are the Digesto's renumbered ones (e.g. L.2283.A, 'Antes Ley 7540')."""
    key, cc, place, platform, min_chars = "ar_h_digesto", "AR", "AR-H", "ar_h_digesto_chaco", 80
    HOST = "https://digesto.legislaturachaco.gob.ar"
    LICENSE = ("Legislatura de la Provincia del Chaco - Digesto Jurídico (digesto.legislaturachaco.gob.ar). No reuse "
               "restriction found on the site; in-force status from the Digesto's vigencia flag. Official legislative texts.")

    def _page(self, sess, page, size=100):
        d = {"sort": "Identificador-asc", "page": str(page), "pageSize": str(size), "group": "", "filter": "", "Titulo": "",
             "Numero": "", "Anio": "", "Texto": "", "RamaId": "", "DocumentoTipoId": "1", "VerNoVigentes": ""}
        r, _ = sess.post(f"{self.HOST}/Documentos/Documento/GetDocumentosBusquedaPublica", data=d)
        if r.status_code != 200:
            raise RuntimeError(f"chaco listing page {page}: http {r.status_code}")   # never run on a partial listing
        return r.json()

    def discover(self, sess):
        items, seen, page, total = [], set(), 1, None
        while page < 200:
            j = self._page(sess, page)
            total = j.get("Total") if total is None else total
            data = j.get("Data") or []
            if not data:
                break
            for x in data:
                if x.get("NoVigente") or not x.get("Publicada") or x.get("DocumentoTipoId") != 1 or x["Id"] in seen:
                    continue
                if not (x.get("Texto") or "").strip():
                    continue
                seen.add(x["Id"])
                items.append({"doc_id": f"ar_h:{x['Id']}", "url": f"{self.HOST}/Documentos/Documento/GetTipoDeDocumentoBuscadoPublico/{x['Id']}",
                              "x": {k: x.get(k) for k in ("Id", "Identificador", "Titulo", "Sintesis", "Texto", "Anio", "Nro",
                                                          "NombreDocumentoFisico", "Observacion", "FechaVerificacion")}})
            page += 1
        if total and len(seen) < 0.95 * total:
            raise RuntimeError(f"chaco listing short: {len(seen)} of {total}")
        return items

    def fetch(self, sess, it):
        x = it["x"]
        text = re.sub(r"\n{3,}", "\n\n", (x.get("Texto") or "").replace("\r", "")).strip()
        if len(text) < 40:
            return None, "no_body"
        ident = " ".join((x.get("Identificador") or "").split()) or None
        title = " ".join((x.get("Titulo") or "").split()) or (f"Ley {ident}" if ident else "Ley")
        m = re.search(r"\(\s*Antes\s+Ley\s+N?[º°]?\s*([\d.]+)\s*\)", text[:600], re.I)
        ver = None
        mv = re.match(r"/Date\((\d+)\)/", x.get("FechaVerificacion") or "")
        if mv:
            ver = datetime.fromtimestamp(int(mv.group(1)) / 1000, timezone.utc).strftime("%Y-%m-%d")
        pol = sess.allowed(it["url"])[1]
        return base(self.place, doc_id=it["doc_id"], source_url=it["url"], source_platform=self.platform, doc_type="statute",
                    language="es", title_native=title[:1000], number=ident, in_force=True, consolidated=True,
                    content_format="html", text=text, source_policy=pol,
                    source_org="Legislatura de la Provincia del Chaco - Digesto Jurídico", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="ar-h",
                    text_file_url=f"{self.HOST}/Documentos/Documento/GetDocumentosBusquedaPublica (Id {x['Id']})",
                    summary=(" ".join((x.get("Sintesis") or "").split()))[:2000] or None,
                    previous_number=m.group(1) if m else None, digesto_year=x.get("Anio") or None,
                    digesto_verified_date=ver, pdf_name=x.get("NombreDocumentoFisico") or None), "ok"


ADAPTERS[ARChacoDigesto.key] = ARChacoDigesto


PLACES.update({
    "AR-J": dict(place_id="iso:AR-J", country_code="AR", place_name="San Juan Province", qid="Q44805",
                 iso_3166_2="AR-J", admin_level="adm1"),
})


def _docx_plain(data: bytes) -> str:
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        x = etree.fromstring(z.read("word/document.xml"))
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paras = ["".join(t.text or "" for t in p.iter(W + "t")) for p in x.iter(W + "p")]
    return "\n".join(p for p in paras if p.strip())


class ARSanJuanDigesto:
    """Digesto de San Juan (digestosanjuan.gob.ar, Cámara de Diputados). The public search
    /buscador/legislativo/vigentes/<b64 json> (25/page, search_after on 'sort') lists the in-force laws (2,107).
    Texts live on minio.legsanjuan.gob.ar; its robots.txt answers 403 (MinIO AccessDenied XML, no challenge).
    Coordinator decision 2026-10-18: follow RFC 9309 (4xx robots.txt => allow) for that host only while its content
    pages serve normally to our UA; any 403/challenge on content raises PermissionError and stops the run.
    Text preference: Digesto text PDF (link_texto_pdf; consolidated unless estado_Consolidacion is "A consolidar") >
    texto_original .docx. link_ta_pdf is the "Tabla de Antecedentes" only (kept as antecedents_table_url)."""
    key, cc, place, platform, min_chars = "ar_j_digesto", "AR", "AR-J", "ar_j_digesto_sanjuan", 80
    HOST = "https://digestosanjuan.gob.ar"
    LICENSE = ("Cámara de Diputados de San Juan - Digesto Provincial (digestosanjuan.gob.ar). No reuse restriction found. "
               "Text files from minio.legsanjuan.gob.ar, whose robots.txt answers HTTP 403; collected under RFC 9309 "
               "(4xx robots.txt => allow) per coordinator decision 2026-10-18, content pages served normally to our UA.")
    SORT = [{"nueva": "desc", "numero": "desc"}]   # no "fecha": null fechas yield Long.MIN sort keys the server cannot take back

    def discover(self, sess):
        import base64
        items, seen, desde, total = [], set(), None, None
        for _ in range(400):
            q = json.dumps({"texto": "", "filtros": [], "sort": self.SORT, "desde": desde}, separators=(",", ":"))
            r, _ = sess.get(f"{self.HOST}/buscador/legislativo/vigentes/" + base64.b64encode(q.encode()).decode())
            if r.status_code != 200:
                raise RuntimeError(f"san juan listing: http {r.status_code}")   # never run on a partial listing
            j = r.json(); hits = j["hits"]["hits"]; total = j["hits"]["total"] if total is None else total
            if not hits:
                break
            for h in hits:
                x = h.get("_source") or {}
                if x.get("id") in seen:
                    continue
                seen.add(x.get("id"))
                if x.get("estado_Vigencia") != "Vigente":
                    continue
                items.append({"doc_id": f"ar_j:{x.get('digesto_id') or x['id']}",
                              "url": f"{self.HOST}/detalle_ley/{x['id']}", "x": x})
            desde = hits[-1].get("sort")
            # missing sort values come back as Long.MIN_VALUE rounded through a double; send the exact long back
            desde = [(-9223372036854775808 if isinstance(v, (int, float)) and v <= -9.2e18 else v) for v in (desde or [])] or None
            if len(seen) >= total:
                break
        if total and len(seen) < 0.95 * total:
            raise RuntimeError(f"san juan listing short: {len(seen)} of {total}")
        return items

    def fetch(self, sess, it):
        x = it["x"]
        # link_texto_pdf = Digesto text (normasconsolidaciones/); link_ta_pdf is only the "Tabla de Antecedentes" (history
        # table), kept as metadata; texto_original .docx = text as drafted/sanctioned
        cons_state = (x.get("estado_Consolidacion") or "").strip()
        cands = [("link_texto_pdf", cons_state.lower() not in ("a consolidar", "")), ("texto_original", False)]
        txt, used, cons, scanned = None, None, False, None
        for fld, is_ta in cands:
            u = (x.get(fld) or "").strip()
            if not u.startswith("http"):
                continue
            r, pol = sess.get(u)          # PermissionError on 403/challenge => run stops (host blocks our UA)
            if r.status_code != 200:
                continue
            if u.lower().endswith(".pdf") or r.content[:4] == b"%PDF":
                ok, t = pdf_has_text(r.content)
                if not ok:
                    scanned = scanned or u
                    continue
                txt, used, cons, fmt = t, u, is_ta, "pdf_text"
            elif r.content[:2] == b"PK":
                try:
                    t = _docx_plain(r.content)
                except Exception:
                    continue
                if len(t) < 80:
                    continue
                txt, used, cons, fmt = t, u, False, "docx_text"
            else:
                continue
            break
        if not txt:
            if scanned:
                queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, scanned, sess.allowed(scanned)[1])
                return None, "scanned_pdf_queued"
            return None, "no_text_file"
        tn = x.get("tipo_Norma") or ""
        nom = x.get("nomenclatura") or x.get("asiento") or f"Ley {x.get('numero')}"
        title = " ".join(((x.get("tema_General") or "").strip() or nom).split())
        d = lambda k: (x.get(k) or "")[:10] or None
        return base(self.place, doc_id=it["doc_id"], source_url=it["url"], source_platform=self.platform, doc_type="statute",
                    language="es", title_native=title[:1000], number=x.get("asiento") or nom, adopted_date=d("fecha_Sancion"),
                    publication_date=d("fecha_Publicacion"), in_force=True, consolidated=cons, content_format=fmt,
                    text=re.sub(r"\n{3,}", "\n\n", txt).strip(), source_policy=sess.allowed(used)[1],
                    source_org="Cámara de Diputados de San Juan - Digesto Provincial", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="ar-j", text_file_url=used,
                    robots_basis="minio.legsanjuan.gob.ar robots.txt HTTP 403 -> RFC 9309 4xx=allow (coordinator 2026-10-18)",
                    nomenclatura=nom, consolidation_state=x.get("estado_Consolidacion") or None,
                    tipo_norma=str(tn)[:200] or None, scanned_original_url=x.get("texto_escaneado") or None,
                    antecedents_table_url=x.get("link_ta_pdf") or None), "ok"


ADAPTERS[ARSanJuanDigesto.key] = ARSanJuanDigesto


PLACES.update({
    "AR-F": dict(place_id="iso:AR-F", country_code="AR", place_name="La Rioja Province", qid="Q44796",
                 iso_3166_2="AR-F", admin_level="adm1"),
})


class ARLaRiojaLegislatura:
    """Legislatura de La Rioja - Consulta de Leyes (legislaturalarioja.gob.ar/consulta-de-leyes, WordPress; robots allow
    except wp internals). In-force selection: SAIJ open CSV 'Vigente, de alcance general' (CC BY 4.0) intersected with the
    site's 'leyes' post type (wp-json/wp/v2/leyes, slug ley-<n>; the site is still uploading laws). Law page -> embedded
    PDF (original sanctioned text, not consolidated; text layer only, scanned PDFs queued, no OCR)."""
    key, cc, place, platform, min_chars = "ar_f_legislatura", "AR", "AR-F", "ar_f_legislatura_larioja", 80
    HOST = "https://legislaturalarioja.gob.ar/consulta-de-leyes"
    TIPOS = {"Ley": None}
    LICENSE = ("Legislatura de la Provincia de La Rioja - Consulta de Leyes (legislaturalarioja.gob.ar); original sanctioned "
               "text (PDF), not consolidated. No reuse restriction found on the site; in-force status from 'Base SAIJ de "
               "Normativa Provincial' (Ministerio de Justicia, datos.jus.gob.ar, CC BY 4.0). Official legislative texts.")

    def discover(self, sess):
        site, page, pages = {}, 1, 1
        while page <= pages and page < 500:
            r, _ = sess.get(f"{self.HOST}/wp-json/wp/v2/leyes?per_page=100&page={page}&_fields=id,slug,link,date")
            if r.status_code != 200:
                raise RuntimeError(f"la rioja listing page {page}: http {r.status_code}")   # never run on a partial listing
            pages = int(r.headers.get("X-WP-TotalPages", pages))
            for x in r.json():
                m = re.fullmatch(r"ley-(\d+)", x.get("slug") or "")
                if m:
                    site.setdefault(str(int(m.group(1))), x)
            page += 1
        items, seen = [], set()
        for r in _ar_saij_inforce("La Rioja", self.TIPOS):
            n = r["numero_norma"].strip()
            if not n.isdigit() or int(n) == 0 or n in seen:
                continue
            seen.add(n)
            x = site.get(str(int(n)))
            if not x:
                continue
            items.append({"doc_id": f"ar_f:ley:{n}", "url": x["link"], "n": n, "wp_id": x["id"], "saij": r})
        self.not_on_site = len(seen) - len(items)
        return items

    def fetch(self, sess, it):
        n, s = it["n"], it["saij"]
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        d = LH.document_fromstring(r.content.decode("utf-8", "replace"))
        pdfs = [u for u in d.xpath("//iframe[contains(@class,'pdf')]/@src|//a[contains(@href,'.pdf')]/@href")
                if "/wp-content/uploads/" in u and re.search(rf"L0*{n}\b|ley[-_ ]?0*{n}\b", u, re.I)]
        pdfs = pdfs or [u for u in d.xpath("//iframe[contains(@class,'pdf')]/@src") if u.lower().endswith(".pdf")]
        if not pdfs:
            return None, "no_text_file"
        src = pdfs[0]
        r2, _ = sess.get(src)
        if r2.status_code != 200 or b"%PDF" not in r2.content[:1024]:
            return None, f"file_http_{r2.status_code}"
        ok, txt = pdf_has_text(r2.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, src, pol)
            return None, "scanned_pdf_queued"
        title = (s.get("titulo_resumido") or "").strip() or (s.get("titulo_sumario") or "").strip()[:300] or f"Ley {n}"
        return base(self.place, doc_id=it["doc_id"], source_platform=self.platform, source_url=it["url"], doc_type="statute",
                    language="es", title_native=_smart_title(title) if title.isupper() else title, number=f"Ley {n}",
                    adopted_date=s.get("fecha") or None, publication_date=s.get("fecha_publicacion") or None,
                    in_force=True, consolidated=False, content_format="pdf_text", text=txt, source_policy=pol,
                    source_org="Legislatura de la Provincia de La Rioja", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="ar-f", text_file_url=src,
                    summary=(s.get("titulo_sumario") or "")[:2000] or None, saij_status=s.get("estado_vigencia")), "ok"


ADAPTERS[ARLaRiojaLegislatura.key] = ARLaRiojaLegislatura


# ================================================================== BOSNIA AND HERZEGOVINA - entities / district
# Zakon o autorskom i srodnim pravima BiH ("Sl. glasnik BiH" 63/2010), Art. 8(1)(b): official texts in the fields of
# legislation, administration and judiciary (laws, regulations, decisions, ...) are not protected by copyright
# (Art. 8(2): translations are protected unless published as official texts - we stage the official-language text only).
# Coordinator decision 2026-10-18: proceed on that basis; rows are as-adopted (consolidated=False), in_force unknown.
BA_LICENSE_BASIS = ("Official legislative text: not protected by copyright under Art. 8(1)(b) of the Law on Copyright and "
                    "Related Rights of Bosnia and Herzegovina (Sl. glasnik BiH 63/2010; translations protected unless "
                    "official, Art. 8(2)); the site's own copyright notice covers its compilation/design, not the texts.")
PLACES.update({
    "BA-BIH": dict(place_id="iso:BA-BIH", country_code="BA", place_name="Federation of Bosnia and Herzegovina", qid="Q11198",
                   iso_3166_2="BA-BIH", admin_level="adm1"),
    "BA-SRP": dict(place_id="iso:BA-SRP", country_code="BA", place_name="Republika Srpska", qid="Q11196",
                   iso_3166_2="BA-SRP", admin_level="adm1"),
    "BA-BRC": dict(place_id="iso:BA-BRC", country_code="BA", place_name="Brčko District", qid="Q194483",
                   iso_3166_2="BA-BRC", admin_level="adm1"),
})


def _html_doc(r):
    raw = r.content
    i = raw.find(b"<")
    return LH.document_fromstring(raw[max(i, 0):].decode("utf-8", "replace") or "<html/>")


class BAFBiHVlada:
    """Vlada Federacije BiH (fbihvlada.gov.ba, robots allow all). /bs/zakoni lists yearly 'Hronološki registar zakona
    objavljenih u Službenim novinama FBiH'; each register links per-law pages carrying the full promulgated text
    (div.content-article). As adopted/published (amending acts are separate rows); in-force status not given."""
    key, cc, place, platform, min_chars = "ba_fbih_vlada", "BA", "BA-BIH", "ba_fbih_vlada", 200
    HOST = "https://fbihvlada.gov.ba"
    LICENSE = ("Vlada Federacije BiH, fbihvlada.gov.ba (registers of laws published in Službene novine FBiH; text as "
               "promulgated, not consolidated). " + BA_LICENSE_BASIS)

    def discover(self, sess):
        regs, page = [], 0
        while page < 30:
            r, _ = sess.get(f"{self.HOST}/bs/zakoni?page={page}")
            if r.status_code != 200:
                raise RuntimeError(f"fbih zakoni page {page}: http {r.status_code}")
            new = [u for u in dict.fromkeys(_html_doc(r).xpath("//a[contains(@href,'hronolo') or contains(@href,'hronoco')]/@href"))
                   if u not in regs]
            if not new:
                break
            regs += new; page += 1
        items, seen = [], set()
        for reg in regs:
            url = reg if reg.startswith("http") else self.HOST + reg
            r, _ = sess.get(url)
            if r.status_code != 200:
                raise RuntimeError(f"fbih register {url}: http {r.status_code}")
            d = _html_doc(r)
            c = (d.xpath("//div[contains(@class,'content-article')]") or [d])[0]
            gaz = None
            for e in c.iter():
                if not isinstance(e.tag, str):
                    continue
                if e.tag == "a" and e.get("href"):
                    h = e.get("href")
                    if h.startswith("#") or h.lower().endswith((".pdf", ".doc", ".docx")):
                        continue
                    u = h if h.startswith("http") else self.HOST + "/" + re.sub(r"^(\.\./)+", "", h).lstrip("/")
                    if "fbihvlada.gov.ba/bs/" not in u or u in seen:
                        continue
                    seen.add(u)
                    items.append({"doc_id": "ba_fbih:" + hashlib.sha1(u.encode()).hexdigest()[:16], "url": u,
                                  "title": " ".join(e.text_content().split()), "gazette": gaz, "register": url})
                txt = " ".join(((e.text or "") + " " + (e.tail or "")).split())
                m = re.search(r"broj\s*(\d+\s*/\s*\d{2,4})\s*/?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})?", txt)
                if m:
                    gaz = {"number": m.group(1).replace(" ", ""), "date": m.group(2)}
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        d = _html_doc(r)
        c = d.xpath("//div[contains(@class,'content-article')]")
        if not c:
            return None, "no_body"
        for b in c[0].xpath(".//script|.//style"):
            b.drop_tree()
        text = _text(c[0]) if callable(globals().get("_text")) else c[0].text_content()
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < 200 or not re.search(r"(?i)\bčlan\s+1\b|\bclan\s+1\b|\bčlanak\s+1\b", text):
            return None, "no_law_text"
        h1 = d.xpath("//h1[contains(@class,'title')]")
        title = re.sub(r"^\d+\.\s*", "", " ".join((h1[0].text_content() if h1 else it["title"]).split()))
        if not re.search(r"(?i)zakon|kodeks|budžet", title):
            return None, "not_a_law"
        g = it.get("gazette") or {}
        pub = None
        if g.get("date"):
            dd, mm, yy = g["date"].split(".")[:3]
            yy = ("20" + yy) if len(yy) == 2 else yy
            pub = f"{yy}-{int(mm):02d}-{int(dd):02d}"
        return base(self.place, doc_id=it["doc_id"], source_url=it["url"], source_platform=self.platform, doc_type="statute",
                    language="bs", title_native=title[:1000], number=(f"Sl. novine FBiH {g['number']}" if g.get("number") else None),
                    publication_date=pub, in_force=None, consolidated=False, content_format="html", text=text,
                    source_policy=pol, source_org="Vlada Federacije Bosne i Hercegovine", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="ba-bih", text_version="as_adopted",
                    gazette_number=g.get("number"), register_url=it["register"]), "ok"


ADAPTERS[BAFBiHVlada.key] = BAFBiHVlada


# ================================================================== IRAQ - Kurdistan Region
PLACES.update({
    "IQ-KR": dict(place_id="iso:IQ-KR", country_code="IQ", place_name="Kurdistan Region", qid="Q205047",
                  iso_3166_2="IQ-KR", admin_level="adm1"),
})
_CKB_CHARS = set("ێۆڵڕەڤ")


def _ckb_or_ar(s, default="ar"):
    s = s or ""
    ck = sum(ch in _CKB_CHARS for ch in s) + 5 * sum(s.count(w) for w in ("ياسا", "یاسا", "ژمار", "هةرێم", "هەرێم", " لة ", " بة ", "ڕێم"))
    ar = 5 * sum(s.count(w) for w in ("قانون", "المادة", "الإقليم", "الاقليم", " في ", " من "))
    if not ck and not ar:
        return default
    return "ckb" if ck > ar else "ar"


def _arabic_script_ok(s, min_ratio=0.6):
    """False for PDFs extracted through legacy (non-Unicode) Arabic/Kurdish fonts: mostly Latin-1 mojibake."""
    letters = [ch for ch in s if ch.isalpha()]
    if len(letters) < 100:
        return False
    return sum("\u0600" <= ch <= "\u06ff" or "\u0750" <= ch <= "\u077f" for ch in letters) / len(letters) >= min_ratio


class IQKurdistanParliament:
    """Kurdistan Parliament - Iraq (parliament.krd; robots.txt 404 = allow; no terms page found). Kurdish section
    /business/legislation/<year>/ (1992-) and Arabic section /arabic/business/القوانین/<year>/ (2002-) list the
    laws passed each year as PDFs (/media/<id>/...pdf). Texts as passed (amendments are separate laws); in-force status
    not shown => in_force unknown. Language per record from the text (ckb Sorani vs ar)."""
    key, cc, place, platform, min_chars = "iq_kr_parliament", "IQ", "IQ-KR", "iq_kr_parliament", 200
    HOST = "https://www.parliament.krd"
    INDEXES = [("/business/legislation/", "ckb"), ("/arabic/business/القوانین/", "ar")]
    LICENSE = ("Kurdistan Parliament - Iraq (parliament.krd), laws as passed (PDF). No reuse restriction or terms found on "
               "the site; official legislative texts. Note: Iraqi Copyright Law No. 3 of 1971 (as amended by CPA Order 83) "
               "has no explicit exclusion for official texts; Art. 6 only addresses collections of official documents.")

    def discover(self, sess):
        from urllib.parse import unquote, urljoin
        items, seen = [], set()
        for idx, lang in self.INDEXES:
            r, _ = sess.get(self.HOST + idx)
            if r.status_code != 200:
                raise RuntimeError(f"kurdistan index {idx}: http {r.status_code}")
            years = []
            for h in _html_doc(r).xpath("//a/@href"):
                u = unquote(h)
                if u.startswith(idx) and u.rstrip("/") != idx.rstrip("/") and u.count("/") == idx.count("/") + 1 and u not in years:
                    years.append(u)
            for y in years:
                r, _ = sess.get(self.HOST + y)
                if r.status_code != 200:
                    raise RuntimeError(f"kurdistan year page {y}: http {r.status_code}")
                ym = re.search(r"(\d{4})|([٠-٩]{4})", y)
                yr = (ym.group(1) or ym.group(2).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))) if ym else None
                for a in _html_doc(r).xpath("//a[contains(translate(@href,'PDF','pdf'),'.pdf')]"):
                    u = urljoin(self.HOST + y, a.get("href"))
                    if u in seen or "/media/" not in u:
                        continue
                    seen.add(u)
                    items.append({"doc_id": "iq_kr:" + hashlib.sha1(u.encode()).hexdigest()[:16], "url": u, "page": self.HOST + y,
                                  "title": " ".join(a.text_content().split()), "year": yr, "section_lang": lang})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200 or b"%PDF" not in r.content[:1024]:
            return None, f"file_http_{r.status_code}"
        ok, txt = pdf_has_text(r.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, it["url"], pol)
            return None, "scanned_pdf_queued"
        import unicodedata
        txt = unicodedata.normalize("NFKC", txt).replace("\u202b", "").replace("\u202c", "").replace("\u202a", "")
        if not _arabic_script_ok(txt[:30000]):     # legacy-font PDF: text layer is mojibake -> treat like a scan
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, it["url"], pol)
            return None, "legacy_font_queued"
        lang = _ckb_or_ar(txt[:20000], default=it["section_lang"])
        yr = (it.get("year") or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")) or None
        it = dict(it, year=yr)
        t = it["title"].translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
        m = re.search(r"\((\d+)\)", t) or re.search(r"(?:ژمار\S*|رقم)\s*\(?(\d+)", t)
        num = f"{m.group(1)}/{it['year']}" if m and it.get("year") else None
        return base(self.place, doc_id=it["doc_id"], source_url=it["page"], source_platform=self.platform, doc_type="statute",
                    language=lang, title_native=it["title"][:1000] or None, number=num, adopted_date=it.get("year"),
                    in_force=None, consolidated=False, content_format="pdf_text", text=re.sub(r"\n{3,}", "\n\n", txt).strip(),
                    source_policy=pol, source_org="Kurdistan Parliament - Iraq", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="iq-kr", text_file_url=it["url"], text_version="as_passed",
                    site_section_language=it["section_lang"]), "ok"


ADAPTERS[IQKurdistanParliament.key] = IQKurdistanParliament


def _office_to_text(data: bytes, suffix: str, timeout=180) -> str:
    """Legacy .doc/.rtf -> text via LibreOffice headless (separate profile, temp dir, removed afterwards)."""
    import subprocess, tempfile, shutil, os
    td = tempfile.mkdtemp(prefix="states_lo_")
    try:
        src = os.path.join(td, "in" + suffix)
        open(src, "wb").write(data)
        subprocess.run(["soffice", "--headless", f"-env:UserInstallation=file://{td}/profile", "--convert-to", "txt:Text",
                        "--outdir", td, src], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        out = os.path.join(td, "in.txt")
        return open(out, encoding="utf-8", errors="replace").read() if os.path.exists(out) else ""
    finally:
        shutil.rmtree(td, ignore_errors=True)


class BARSNarodnaSkupstina:
    """Narodna skupština Republike Srpske (narodnaskupstinars.net; robots allow /ci/akti). 'Усвојени закони'
    (/ci/akti/usvojeni-zakoni?page=N) -> law page (Службени гласник number + date) -> attachment (.zip with .doc/.docx/.pdf).
    Text as adopted (amending laws are separate rows); in-force status not given."""
    key, cc, place, platform, min_chars = "ba_srp_nsrs", "BA", "BA-SRP", "ba_srp_nsrs", 200
    HOST = "https://www.narodnaskupstinars.net"
    LICENSE = ("Narodna skupština Republike Srpske, narodnaskupstinars.net (adopted laws; text as adopted, not consolidated). "
               + BA_LICENSE_BASIS)

    def discover(self, sess):
        items, seen, page, empty = [], set(), 0, 0
        while page < 500:
            r, _ = sess.get(f"{self.HOST}/ci/akti/usvojeni-zakoni?page={page}")
            if r.status_code != 200:
                raise RuntimeError(f"nsrs listing page {page}: http {r.status_code}")
            new = 0
            for a in _html_doc(r).xpath("//a[starts-with(@href,'/ci/akti/usvojeni-zakoni/')]"):
                u = self.HOST + a.get("href").split("?")[0]
                if u in seen:
                    continue
                seen.add(u); new += 1
                items.append({"doc_id": "ba_srp:" + a.get("href").rsplit("/", 1)[-1][:120], "url": u,
                              "title": " ".join(a.text_content().split())})
            if not new:
                break
            page += 1
        return items

    def _extract(self, name, data):
        import io, zipfile
        n = name.lower()
        if n.endswith(".zip") or data[:2] == b"PK" and not n.endswith(".docx"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                return "", None
            mem = sorted((m for m in z.namelist() if m.lower().endswith((".docx", ".doc", ".pdf", ".rtf"))),
                         key=lambda m: (not m.lower().endswith(".docx"), not m.lower().endswith(".doc")))
            for m in mem:
                t, fmt = self._extract(m, z.read(m))
                if t:
                    return t, fmt
            return "", None
        if n.endswith(".docx"):
            return _docx_plain(data), "docx_text"
        if n.endswith((".doc", ".rtf")):
            return _office_to_text(data, "." + n.rsplit(".", 1)[-1]), "docx_text"
        if n.endswith(".pdf") or data[:4] == b"%PDF":
            ok, t = pdf_has_text(data)
            return (t, "pdf_text") if ok else ("", "scanned")
        return "", None

    def fetch(self, sess, it):
        r, pol = sess.get(it["url"])
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        d = _html_doc(r)
        for b in d.xpath("//script|//style"):
            b.drop_tree()
        info = " ".join(d.text_content().split())
        g = re.search(r"Службени гласник:\s*([\d/]+)", info)
        dt = re.search(r"Датум:\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", info)
        files = [h for h in d.xpath("//a/@href") if "/sites/default/files/upload/dokumenti/akti/usvojeni_zakoni/" in h]
        if not files:
            return None, "no_text_file"
        src = files[0] if files[0].startswith("http") else self.HOST + files[0]
        r2, _ = sess.get(src)
        if r2.status_code != 200:
            return None, f"file_http_{r2.status_code}"
        from urllib.parse import unquote
        text, fmt = self._extract(unquote(src.rsplit("/", 1)[-1]), r2.content)
        if fmt == "scanned":
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, src, pol)
            return None, "scanned_pdf_queued"
        text = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", (text or "").replace("\r", "").replace("\ufeff", ""))).strip()
        if len(text) < 200:
            return None, "no_body"
        h1 = d.xpath("//h1")
        title = " ".join((h1[0].text_content() if h1 else it["title"]).split()) or it["title"]
        return base(self.place, doc_id=it["doc_id"], source_url=it["url"], source_platform=self.platform, doc_type="statute",
                    language="sr", title_native=title[:1000], number=(f"Сл. гласник РС {g.group(1)}" if g else None),
                    publication_date=(f"{dt.group(3)}-{int(dt.group(2)):02d}-{int(dt.group(1)):02d}" if dt else None),
                    in_force=None, consolidated=False, content_format=fmt, text=text, source_policy=pol,
                    source_org="Narodna skupština Republike Srpske", license_note=self.LICENSE, platform=self.platform,
                    platform_place_id="ba-srp", text_file_url=src, text_version="as_adopted", script="Cyrl",
                    gazette_number=g.group(1) if g else None), "ok"


ADAPTERS[BARSNarodnaSkupstina.key] = BARSNarodnaSkupstina


def _bd_decode(s):
    """skupstinabd.ba file/folder names spell diacritics as 'c--'/'c+' (č), 's--'/'s+' (š), 'z--'/'z+' (ž), 'c-' (ć)."""
    for a, b in (("c--", "č"), ("s--", "š"), ("z--", "ž"), ("d--", "đ"), ("C--", "Č"), ("S--", "Š"), ("Z--", "Ž"),
                 ("c+", "č"), ("s+", "š"), ("z+", "ž"), ("C+", "Č"), ("S+", "Š"), ("Z+", "Ž")):
        s = s.replace(a, b)
    return re.sub(r"c-(?=[a-zčšž])", "ć", s)


def _bd_lang(txt):
    """Cyrillic-majority text => 'sr', else 'bs' (Latin; Brčko publishes in bs/hr/sr and many PDFs carry a bilingual header)."""
    letters = [c for c in txt[:20000] if c.isalpha()]
    cyr = sum("\u0400" <= c <= "\u04ff" for c in letters)
    return "sr" if letters and cyr / len(letters) > 0.5 else "bs"


class BABrckoSkupstina:
    """Skupština Brčko distrikta BiH (skupstinabd.ba, Joomla; robots allow /index.php/sr/zakon.html). The 'Zakoni' page
    lists ~200 district laws; each law page links its PDFs: the original act, amending acts, and where the Assembly
    published one, the 'Prečišćeni tekst' (official consolidated text as of that version). One row per PDF.
    Coordinator decision: consolidated=False on every row (a prečišćeni tekst may predate later amendments);
    text_version tells them apart."""
    key, cc, place, platform, min_chars = "ba_brc_skupstina", "BA", "BA-BRC", "ba_brc_skupstina", 200
    HOST = "https://skupstinabd.ba"
    LICENSE = ("Skupština Brčko distrikta BiH, skupstinabd.ba (law PDFs: original acts, amendments, 'prečišćeni tekst'). "
               + BA_LICENSE_BASIS)

    def discover(self, sess):
        from urllib.parse import quote, unquote
        r, _ = sess.get(f"{self.HOST}/index.php/sr/zakon.html")
        if r.status_code != 200:
            raise RuntimeError(f"brcko zakon list: http {r.status_code}")
        ids = []
        for h in _html_doc(r).xpath("//a/@href"):
            m = re.match(r"zakon\.html\?lang=sr&id=(.+)$", h)
            if m and m.group(1) not in ids:
                ids.append(m.group(1))
        items, seen = [], set()
        for lid in ids:
            page = f"{self.HOST}/index.php/sr/zakon.html?lang=sr&id=" + quote(unquote(lid))
            r, _ = sess.get(page)
            if r.status_code != 200:
                raise RuntimeError(f"brcko law page {lid}: http {r.status_code}")
            law = unquote(lid).strip("/").replace("--", "")
            for f in _html_doc(r).xpath("//a[contains(translate(@href,'PDF','pdf'),'.pdf')]/@href"):
                if "/3-zakon/" not in f or f in seen:
                    continue
                seen.add(f)
                fn = unquote(f.rsplit("/", 1)[-1])
                items.append({"doc_id": "ba_brc:" + hashlib.sha1(f.encode()).hexdigest()[:16], "url": page,
                              "pdf": f.replace(" ", "%20"), "file": fn, "law": law})
        return items

    def fetch(self, sess, it):
        r, pol = sess.get(it["pdf"])
        if r.status_code != 200 or b"%PDF" not in r.content[:1024]:
            return None, f"file_http_{r.status_code}"
        ok, txt = pdf_has_text(r.content)
        if not ok:
            queue_scanned_pdf(it["doc_id"], PLACES[self.place]["place_id"], self.cc, it["pdf"], pol)
            return None, "scanned_pdf_queued"
        fn = re.sub(r"\.pdf$", "", it["file"], flags=re.I).strip()
        dec = _bd_decode(fn)
        prec = bool(re.search(r"(?i)pre[cč]i[sš][cć]?en|пречишћен", dec))
        m = re.match(r"^(?:\d+S|\d{3}\s+)(\d{1,3})-(\d{2})\s+(.*)$", dec)
        g = (int(m.group(1)), m.group(2)) if m and m.group(1).strip("0") else None
        title = re.sub(r"\s+S$", "", (m.group(3) if m else dec)).strip(" ,-") or _bd_decode(it["law"])
        return base(self.place, doc_id=it["doc_id"], source_url=it["url"], source_platform=self.platform, doc_type="statute",
                    language=_bd_lang(txt), title_native=title[:1000],
                    number=fn[:200], in_force=None, consolidated=False, content_format="pdf_text",
                    text=re.sub(r"\n{3,}", "\n\n", txt).strip(), source_policy=pol,
                    source_org="Skupština Brčko distrikta Bosne i Hercegovine", license_note=self.LICENSE,
                    platform=self.platform, platform_place_id="ba-brc", text_file_url=it["pdf"],
                    text_version="precisceni_tekst" if prec else "as_adopted", law_group=_bd_decode(it["law"])[:300],
                    gazette_ref=(f"Sl. glasnik BD {g[0]}/{g[1]}" if g else None), source_file_name=fn), "ok"


ADAPTERS[BABrckoSkupstina.key] = BABrckoSkupstina
