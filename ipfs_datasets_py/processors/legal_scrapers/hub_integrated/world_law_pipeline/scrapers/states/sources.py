"""Source adapters for the states lane test batch. Each adapter: discover(sess, limit) -> [url], parse(url, resp) -> record|None.

ca_on_elaws  Ontario e-Laws        www.ontario.ca/laws/statute/<id>          robots: /laws allowed, Crawl-delay 1
             discovery: Wayback CDX url list (shared pipeline/archive, ARCHIVE_LANE=states; URLs only, content fetched live)
             licence: Ontario legal materials (statutes, regulations) exempt from King's Printer licence requirement
ca_mb_ccsm   Manitoba C.C.S.M.     web2.gov.mb.ca/laws/statutes/ccsm/<id>.php robots: 404 -> allow (RFC 9309)
             discovery: index_ccsm.php; licence: OpenMB Information and Data Use Licence
au_qld_leg   Queensland legislation www.legislation.qld.gov.au/view/xml/...   robots: /view/xml allowed (/view/pdf disallowed)
             discovery: sitemap.xml + feed?id=crawler (both listed in robots.txt); licence: CC BY 4.0
"""
from __future__ import annotations
import html as H, re
from lxml import etree, html as LH

from common import utcnow

PLACES = {
    "CA-ON": dict(place_id="iso:CA-ON", country_code="CA", place_name="Ontario", qid="Q1904", iso_3166_2="CA-ON", admin_level="adm1"),
    "CA-MB": dict(place_id="iso:CA-MB", country_code="CA", place_name="Manitoba", qid="Q1948", iso_3166_2="CA-MB", admin_level="adm1"),
    "AU-QLD": dict(place_id="iso:AU-QLD", country_code="AU", place_name="Queensland", qid="Q36074", iso_3166_2="AU-QLD", admin_level="adm1"),
}


def _text(node):
    for bad in node.xpath(".//script|.//style|.//noscript"):
        bad.getparent().remove(bad)
    t = node.text_content()
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def _base(place, **kw):
    r = dict(place); r.update(retrieved_at=utcnow(), source_official=True, **kw)
    return r


# ---------------------------------------------------------------- Ontario
class OntarioELaws:
    key, place, platform = "ca_on_elaws", "CA-ON", "ca_on_elaws"
    ID_RX = re.compile(r"^/laws/statute/([0-9a-z]+)$")

    def discover(self, sess, limit, cdx_file=None):
        ids = []
        if cdx_file:
            for line in open(cdx_file, encoding="utf-8"):
                u = line.split()[-1] if line.strip() and not line.startswith("#") else ""
                p = re.sub(r"^https?://(www\.)?ontario\.ca(:\d+)?", "", u).split("?")[0].split("#")[0].rstrip("/")
                m = self.ID_RX.match(p)
                if m and m.group(1) not in ids:
                    ids.append(m.group(1))
        else:
            import os
            os.environ.setdefault("ARCHIVE_LANE", "states")
            from archive import ArchiveFetcher
            fx = ArchiveFetcher(cc_crawls=0, lane="states")
            for c in fx.wb_captures("www.ontario.ca/laws/statute/", "prefix", collapse="urlkey"):
                p = re.sub(r"^https?://(www\.)?ontario\.ca(:\d+)?", "", c.url).split("?")[0].rstrip("/")
                m = self.ID_RX.match(p)
                if m and m.group(1) not in ids:
                    ids.append(m.group(1))
        ids = sorted(ids); step = max(1, len(ids) // max(1, limit))   # spread sample across the whole id range
        return [f"https://www.ontario.ca/laws/statute/{i}" for i in ids[::step][:limit]]

    def parse(self, url, resp):
        doc = LH.fromstring(resp.content)
        title = (doc.findtext(".//title") or "").strip().strip('"').strip()
        body = doc.xpath('//div[starts-with(@class,"WordSection")]')   # source-law pages have 2+ (explanatory note + act)
        if not body:
            return None
        text = "\n\n".join(t for t in (_text(b) for b in body) if t)
        repealed = bool(re.search(r"Note: This Act (?:was|is) repealed", text[:2000]))
        consolidated = repealed or "Consolidation Period" in text[:3000]   # repealed acts: final consolidation; Pr/source law: as enacted
        m = re.match(r"^(.*?),\s*((?:R\.S\.O\.|S\.O\.)\s*\d{4},\s*c\.\s*[\w.]+)", title)
        name, number = (m.group(1), m.group(2)) if m else (title, None)
        sid = url.rstrip("/").rsplit("/", 1)[-1]
        yr = re.search(r"\b(1[89]\d\d|20\d\d)\b", number or "")
        return _base(PLACES[self.place], doc_id=f"on_statute:{sid}", source_platform=self.platform, source_url=url,
                     doc_type="statute", language="en", title_native=name, number=number,
                     adopted_date=yr.group(1) if yr else None, in_force=(False if repealed else None), consolidated=consolidated, content_format="html",
                     text=text, source_org="King's Printer for Ontario (e-Laws)",
                     license_note="Government of Ontario legal materials (statutes) - reproduction permitted (ontario.ca/page/copyright-information)",
                     platform="ca_on_elaws", platform_place_id="ON",
                     elaws_kind=("repealed" if repealed else "source_law" if not consolidated else "consolidated"), n_wordsections=len(body))


# ---------------------------------------------------------------- Manitoba
class ManitobaCCSM:
    key, place, platform = "ca_mb_ccsm", "CA-MB", "ca_mb_ccsm"
    INDEX = "https://web2.gov.mb.ca/laws/statutes/index_ccsm.php"

    def discover(self, sess, limit):
        r, _ = sess.get(self.INDEX)
        hrefs = re.findall(r'href="ccsm/([a-z0-9\-]+)\.php', r.text)
        seen = []
        for h in hrefs:
            if h not in seen:
                seen.append(h)
        self.pdf_links = sorted(set(re.findall(r'href="(ccsm/pdf/[^"]+\.pdf)"', r.text)))
        step = max(1, len(seen) // max(1, limit))
        return [f"https://web2.gov.mb.ca/laws/statutes/ccsm/{h}.php?lang=en" for h in seen[::step][:limit]]

    def parse(self, url, resp):
        doc = LH.fromstring(resp.content)
        main = doc.xpath('//*[@id="mainContent"]')
        if not main:
            return None
        number = (doc.findtext(".//title") or "").strip()          # e.g. "C.C.S.M. c. A1.5"
        t = doc.xpath('//*[@id="title_en"]')
        title = _text(t[0]) if t else None
        if not title:
            h = main[0].xpath(".//p[contains(@class,'title')]|.//h1|.//h2")
            title = _text(h[0]) if h else number
        if title and number and title.endswith(number):
            title = title[: -len(number)].rstrip(" ,")
        fr = main[0].xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," regcol-f ")]')
        for e in fr:
            e.getparent().remove(e)
        text = re.sub(r"^\s*bilingual version \(HTML\)\s*(?:version bilingue \(HTML\)\s*)?", "", _text(main[0]))
        text = re.sub(r"\s*Accessibility\s+Disclaimer\s+Copyright\s+Privacy\s+Contact Us\s*$", "", text)
        sid = re.search(r"/ccsm/([a-z0-9\-]+)\.php", url).group(1)
        return _base(PLACES[self.place], doc_id=f"mb_ccsm:{sid}", source_platform=self.platform, source_url=url,
                     doc_type="statute", language="en", title_native=title, number=number or None, in_force=True,
                     consolidated=True, content_format="html", text=text,
                     source_org="Manitoba King's Printer (C.C.S.M., unofficial consolidation)",
                     license_note="OpenMB Information and Data Use Licence (manitoba.ca/legal/copyright.html)",
                     platform="ca_mb_ccsm", platform_place_id="MB", bilingual_source=bool(fr), french_columns_dropped=len(fr))


# ---------------------------------------------------------------- Queensland
BLOCK_TAGS = {"txt", "heading", "shorttitle", "longtitle", "block", "li", "row", "entry", "p", "def", "hdg", "note"}


class QueenslandLegislation:
    key, place, platform = "au_qld_leg", "AU-QLD", "au_qld_legislation"
    RX = re.compile(r"/view/(?:whole/)?html/inforce/[^/]+/((?:act|sl)-\d{4}-[0-9a-z]+)")

    def discover(self, sess, limit):
        ids = []
        for u in ("https://www.legislation.qld.gov.au/sitemap.xml", "https://www.legislation.qld.gov.au/feed?id=crawler"):
            r, _ = sess.get(u)
            for m in self.RX.finditer(r.text):
                if m.group(1) not in ids:
                    ids.append(m.group(1))
        return [f"https://www.legislation.qld.gov.au/view/xml/inforce/current/{i}" for i in ids[:limit]]

    def parse(self, url, resp):
        root = etree.fromstring(resp.content, parser=etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, recover=True))
        if root is None:
            return None
        a = root.attrib
        title = a.get("title") or (root.findtext(".//shorttitle") or "").strip()
        for c in root.iter(etree.Comment):
            c.getparent().remove(c)
        for e in root.iter():
            if isinstance(e.tag, str) and e.tag in BLOCK_TAGS:
                e.tail = "\n" + (e.tail or "")
        txt = " ".join(root.itertext())
        txt = re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", txt)).strip()
        lid = a.get("id") or url.rsplit("/", 1)[-1]
        kind = a.get("type", "")
        dt = "regulation" if kind.startswith("sl") or lid.startswith("sl-") else "statute"
        no = a.get("no")
        yr = a.get("year.assent") or (re.search(r"-(\d{4})-", lid).group(1) if re.search(r"-(\d{4})-", lid) else None)
        number = (f"Act No. {int(no)} of {yr}" if dt == "statute" else f"SL No. {int(no)} of {yr}") if (no and no.isdigit() and yr) else lid
        inf = a.get("in.force")
        return _base(PLACES[self.place], doc_id=f"qld:{lid}", source_platform=self.platform, source_url=url,
                     doc_type=dt, language="en", title_native=title, number=number,
                     adopted_date=(a.get("assent.date") or a.get("notification.date") or "")[:10] or yr,
                     published_date=(a.get("publication.date") or "")[:10] or None,
                     effective_date=(a.get("first.valid.date") or "")[:10] or None,
                     in_force=(True if inf in ("allinforce", "partinforce") else None), consolidated=True,
                     content_format="xml", text=txt, source_org="Queensland Parliamentary Counsel (OQPC)",
                     license_note="CC BY 4.0 (legislation.qld.gov.au/copyright)", platform="au_qld_legislation",
                     platform_place_id="QLD", version_series_id=a.get("version.series.id"),
                     html_view_url=url.replace("/view/xml/", "/view/html/"))


ADAPTERS = {c.key: c for c in (OntarioELaws, ManitobaCCSM, QueenslandLegislation)}
