"""India Code State Acts (indiacode.nic.in DSpace) from web archives -> iso:IN-<state>.

Live: www.indiacode.nic.in and indiacode.nic.in answer 403 (Akamai "Access Denied") even for /robots.txt
(2026-10-17 PT) => robots unreachable => disallow-all for live crawling; archive-only (Wayback; CC index 504s).
Candidates: national lane IN_state discovery (1,063 handle pages). Handles < 3000 are Central Acts (collection
123456789/1362; national lane / HF has 849 central acts) -> skipped. Each act landing page gives Act ID, number,
enactment date, Short/Long Title, Ministry/Department, Type: STATE and Location: <State>; full text is the English
PDF /bitstream/123456789/<handle>/<seq>/<file>.pdf (looked up by Wayback prefix query per handle).
Text-layer PDF -> content_format pdf_text; image-only PDF -> queued for OCR (_scanned_pdfs_manifest.jsonl) + metadata
row content_complete=false; PDF not archived -> metadata row content_complete=false.
doc_id: in_indiacode_state:<handle> (national spec platform in_indiacode_state; national staged 0 of these).
"""
from __future__ import annotations
import hashlib, re
from urllib.parse import urljoin, unquote

from archive.core import ArchiveError, ArchiveTransient, Capture
from deferq import fetch_best_or_defer, listing_state, ItemDeferred  # noqa: E402
from arch_common import html_extract, pdf_text, has_text, clean, queue_scanned_pdf_archived, archived_rec
from places import in_state  # noqa: E402  (national lane ISO 3166-2:IN table, read-only)

POLICY = "archived_robots_disallowed"
BASIS = "robots.txt 403 (Akamai Access Denied) on www.indiacode.nic.in and indiacode.nic.in, 2026-10-17 => disallow-all; archived copies only"
LABELS = ["Act ID", "Act Number", "Enactment Date", "Act Year", "Short Title", "Hindi Title", "Long Title", "Ministry",
          "Department", "Enforcement Date", "Notification", "Type", "Location"]
STATE_NAMES = {"IN-AN": "Andaman and Nicobar Islands", "IN-DH": "Dadra and Nagar Haveli and Daman and Diu"}


def fields(text):
    lines = [l.strip() for l in text.split("\n")]
    out = {}
    i0 = next((i for i, l in enumerate(lines) if l == "Actdetails"), 0)
    for i in range(i0, len(lines) - 1):
        l = lines[i]
        if l.endswith(":") and l[:-1] in LABELS and l[:-1] not in out:
            v = lines[i + 1]
            if not (v.endswith(":") and v[:-1] in LABELS):
                out[l[:-1]] = v
    return out


class Adapter:
    key = "in_state"
    nat_target = "IN_state"
    tag = "in_indiacode_state-archive"
    platform = "in_indiacode_state"

    def eligible(self, r):
        try:
            return "central_handle" if int(r["key"]) < 3000 else None
        except ValueError:
            return "bad_key"

    def find_pdfs(self, handle, links, base):
        hrefs = []
        for h in links:
            if h and re.search(r"/bitstream/123456789/%s/\d+/[^\"' ]+\.pdf" % handle, h, re.I):
                u = urljoin(base, h.strip())
                if u not in hrefs:
                    hrefs.append(u)
        eng = [u for u in hrefs if not re.search(r"hindi|_hin\b|hin\.pdf", u, re.I)] or hrefs
        return eng, hrefs

    def fetch_pdf(self, handle, eng):
        """Newest good archived copy of the English PDF. One Wayback prefix CDX query per handle."""
        caps = self.fx.wb_captures(f"indiacode.nic.in/bitstream/123456789/{handle}/", "prefix", collapse="urlkey")
        st, nb = listing_state(caps)
        if st == "retry":                              # truncated listing: requeue the item, don't miss the PDF
            raise ItemDeferred(f"pdf listing truncated ({getattr(caps, 'truncated_reason', '')})", nb)
        want = {re.sub(r"^https?://(www\.)?", "", unquote(u)).lower() for u in eng}
        mine = [c for c in caps if re.sub(r"^https?://(www\.)?", "", unquote(c.original_url)).split("?")[0].lower() in want]
        if not mine:
            mine = [c for c in caps if c.original_url.lower().endswith(".pdf") and not re.search(r"hindi", c.original_url, re.I)]
        if not mine:
            return None
        pdoc = fetch_best_or_defer(self.fx, mine, max_tries=3)   # raises ItemDeferred on throttle -> requeued
        # None = true miss (round 3); throttle/timeout/breaker raise ArchiveDeferred -> item requeued
        return pdoc

    def build(self, r, doc):
        title, page_title, text, links = html_extract(doc.text(), ["#content"], None)
        f = fields(text)
        typ = (f.get("Type") or "").upper()
        if typ and typ != "STATE":
            return None, "not_state:" + typ[:20]
        loc = f.get("Location") or ""
        pl = in_state(loc)
        if not pl:
            return None, "no_place:" + loc[:40]
        code, name = pl
        name = STATE_NAMES.get(code, name)
        handle = r["key"]
        short = (f.get("Short Title") or re.sub(r"^India Code:\s*", "", page_title) or title).strip()
        head = "\n".join(f"{k}: {f[k]}" for k in LABELS if f.get(k) and k != "Hindi Title")
        eng, allpdf = self.find_pdfs(handle, links, doc.original_url)
        body, fmt, complete, reason, pdoc, queued = short + "\n\n" + head, "html", False, None, None, False
        if eng:
            pdoc = self.fetch_pdf(handle, eng)
            if pdoc is not None and pdoc.body[:5] == b"%PDF-":
                pt = pdf_text(pdoc.body)
                if has_text(pt):
                    body, fmt = short + "\n\n" + head + "\n\n" + pt, "pdf_text"
                    complete = doc.content_complete and pdoc.content_complete
                    reason = pdoc.incomplete_reason
                else:
                    queued = queue_scanned_pdf_archived(f"{self.platform}:{handle}", f"iso:{code}", "IN", pdoc.original_url,
                                                        pdoc.archive_url, POLICY, pdoc.archive_timestamp,
                                                        hashlib.sha256(pdoc.body).hexdigest(), pdoc.archive_source,
                                                        pdoc.archive_crawl_id, pdoc.content_type or "application/pdf")
                    reason = "scanned_pdf_no_text_layer:queued_for_ocr"
            else:
                reason = "landing_page_only:pdf_not_archived"
        else:
            reason = "landing_page_only:no_pdf_link"
        ed = f.get("Enactment Date") or ""
        rec = {
            "place_id": f"iso:{code}", "country_code": "IN", "doc_id": f"{self.platform}:{handle}",
            "source_platform": self.platform, "source_url": doc.original_url, "doc_type": "statute", "language": "en",
            "title_native": short[:1000], "consolidated": True, "content_format": fmt, "text": clean(body),
            "retrieved_at": doc.fetched_at, "place_name": name, "iso_3166_2": code, "admin_level": "adm1",
            "platform": self.platform, "platform_place_id": code, "source_official": True,
            "source_org": "India Code (Legislative Department, Ministry of Law and Justice); content provided by the State Government",
            "license_note": "Official State Act text as published on India Code (Government of India / State Government); archived "
                            "copy via Wayback. Site terms not reviewable live (403); government legislation text",
        }
        if f.get("Act Number") and f.get("Act Year"):
            rec["number"] = f"Act No. {f['Act Number']} of {f['Act Year']}"
        if re.fullmatch(r"\d{4}-\d\d-\d\d", ed):
            rec["adopted_date"] = ed
        elif re.fullmatch(r"(18|19|20)\d\d", f.get("Act Year", "")):
            rec["adopted_date"] = f["Act Year"]
        m = re.match(r"(\d\d)-(\d\d)-(\d{4})$", f.get("Enforcement Date") or "")
        if m:
            rec["effective_date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        extra = dict(act_id=f.get("Act ID"), long_title=f.get("Long Title"), hindi_title=f.get("Hindi Title"),
                     ministry=f.get("Ministry"), department=f.get("Department"), indiacode_type=f.get("Type"),
                     indiacode_location=loc, handle=f"123456789/{handle}", pdf_urls=allpdf,
                     incomplete_reason=reason, ocr_queued=queued or None,
                     pdf_archive=(pdoc.provenance() if pdoc is not None else None))
        rec.update(archived_rec(doc, POLICY, BASIS, **extra))
        rec["content_complete"] = bool(complete)
        rec["extra_metadata"]["archive"]["content_complete"] = bool(complete)
        return rec, "ok"
