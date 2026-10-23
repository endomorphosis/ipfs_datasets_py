"""Austria RIS Landesrecht (ris.bka.gv.at) from web archives -> iso:AT-1 .. iso:AT-9.

Live: ris.bka.gv.at / www.ris.bka.gv.at / data.bka.gv.at reset TLS from the box (2026-10-17 PT, as in the national
lane's checks) => robots unreachable => disallow-all for live crawling; archive-only (Wayback, CC when available).
Candidates: national lane AT discovery (8,899 keys); this adapter takes only Landesrecht:
GeltendeFassung.wxe?Abfrage=Lr<Land>&Gesetzesnummer=N (whole consolidated Land law, doc_type statute) and
Dokument.wxe?Abfrage=Lr<Land>&Dokumentnummer=L.. (single provision, doc_type code_section). Bundesrecht (NOR...) is the
national lane's. doc_id at_ris:<key> as in the national lane (its 17 staged Landesrecht keys are skipped).
"""
from __future__ import annotations
import re

from bs4 import BeautifulSoup

from arch_common import clean, archived_rec

POLICY = "archived_robots_disallowed"
BASIS = ("robots.txt unreachable (TLS reset/EOF on ris.bka.gv.at, www.ris.bka.gv.at, data.bka.gv.at; national lane "
         "2026-10-10, re-checked 2026-10-17) => disallow-all; archived copies only")
LAND = {"lrbgld": ("AT-1", "Burgenland"), "lrk": ("AT-2", "Kärnten"), "lrno": ("AT-3", "Niederösterreich"),
        "lroo": ("AT-4", "Oberösterreich"), "lrsbg": ("AT-5", "Salzburg"), "lrstmk": ("AT-6", "Steiermark"),
        "lrt": ("AT-7", "Tirol"), "lrvbg": ("AT-8", "Vorarlberg"), "lrw": ("AT-9", "Wien")}
DOCPREFIX = {"lbg": "lrbgld", "lkt": "lrk", "lno": "lrno", "loo": "lroo", "lsb": "lrsbg", "lst": "lrstmk",
             "lti": "lrt", "lvb": "lrvbg", "lwi": "lrw"}
QID = {"AT-1": "Q43210", "AT-2": "Q37985", "AT-3": "Q42497", "AT-4": "Q41967", "AT-5": "Q43325", "AT-6": "Q41358",
       "AT-7": "Q42880", "AT-8": "Q38981", "AT-9": "Q1741"}
BLOCK = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div", "table", "pre"]


def land_of(key):
    k = key.lower()
    if "&gesetzesnummer=" in k:
        return k.split("&", 1)[0]
    return DOCPREFIX.get(k[:3])


def ris_text(node):
    for t in node.select(".sr-only, script, style, noscript, button, .hidden-print-btn"):
        t.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    for t in node.find_all(BLOCK):
        t.append("\n")
    for t in node.find_all("td"):
        t.append(" ")
    t = clean(node.get_text(""))
    t = re.sub(r"(?m)^(\d+[a-z]?\.|[a-z]{1,2}\)|[a-z]{1,2}\.|\u2013|-)\n+(?=\S)", r"\1 ", t)   # list markers -> same line
    return re.sub(r"(?m)^\((\d+[a-z]?)\)(?=\S)", r"(\1) ", t)


class Adapter:
    key = "at_ris"
    nat_target = "AT"
    tag = "at_ris_landesrecht-archive"
    platform = "at_ris"

    def eligible(self, r):
        return None if land_of(r["key"]) in LAND else "not_landesrecht"

    def validator(self, doc):
        return b"documentContent" in doc.body[:3_000_000]

    def build(self, r, doc):
        key = r["key"]
        land = land_of(key)
        code, lname = LAND[land]
        soup = BeautifulSoup(doc.text(), "lxml")
        pt = (soup.title.get_text(" ", strip=True) if soup.title else "")
        blocks = soup.select("div.documentContent")
        if not blocks:
            return None, "no_document_content"
        parts = [ris_text(b) for b in blocks]
        parts = [p for p in parts if p]
        text = "\n\n".join(parts)
        whole = "&gesetzesnummer=" in key
        # "RIS - Wiener Naturschutzgesetz - Landesrecht konsolidiert Wien, Fassung vom 07.10.2026"
        m = re.match(r"^RIS\s*-\s*(.+?)\s*-\s*Landesrecht\b(.*)$", pt)
        title = (m.group(1) if m else pt).strip()
        fassung = re.search(r"Fassung vom (\d\d)\.(\d\d)\.(\d{4})", pt)
        if len(text) < 80 or not title:
            return None, "too_short"
        head = parts[0] if parts else ""
        lang_t = re.search(r"Langtitel\n(.+?)(?:\n(?:Änderung|Präambel|Text|Stammfassung)\b|$)", head, re.S)
        amend = re.findall(r"LGBl\. ?Nr\. ?\d+/\d{4}", head)
        gnr = re.search(r"gesetzesnummer=(\d+)", key)
        dnr = None if whole else key.upper()
        rec = {
            "place_id": f"iso:{code}", "country_code": "AT", "doc_id": f"{self.platform}:{key}",
            "source_platform": self.platform, "source_url": doc.original_url,
            "doc_type": "statute" if whole else "code_section", "language": "de", "title_native": title[:1000],
            "consolidated": True, "content_format": "html", "text": text, "retrieved_at": doc.fetched_at,
            "in_force": True if whole else None,
            "place_name": lname, "qid": QID.get(code), "iso_3166_2": code, "admin_level": "adm1",
            "platform": "at_ris", "platform_place_id": land, "source_official": True,
            "source_org": "Rechtsinformationssystem des Bundes (RIS), Bundeskanzleramt Österreich - Landesrecht konsolidiert " + lname,
            "license_note": "RIS Open Government Data, CC BY 4.0 (data.gv.at / ris.bka.gv.at); archived copy via web archive",
        }
        stf = re.search(r"StF:\s*(LGBl\.?\s?Nr\.?\s?\d+/\d{4})", head)
        if stf:
            rec["number"] = re.sub(r"\s+", " ", stf.group(1))
        elif amend and not whole:
            rec["number"] = amend[0]
        extra = dict(ris_abfrage=land, gesetzesnummer=gnr.group(1) if gnr else None, dokumentnummer=dnr,
                     fassung_vom=(f"{fassung.group(3)}-{fassung.group(2)}-{fassung.group(1)}" if fassung else None),
                     langtitel=clean(lang_t.group(1))[:2000] if lang_t else None, lgbl_citations=amend[:200] or None,
                     n_provisions=len(blocks), page_title=pt)
        rec.update(archived_rec(doc, POLICY, BASIS, **extra))
        return rec, "ok"
