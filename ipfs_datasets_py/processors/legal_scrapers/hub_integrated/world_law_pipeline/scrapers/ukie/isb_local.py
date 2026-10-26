#!/usr/bin/env python3
"""Phase 3b: Irish Statute Book (irishstatutebook.ie, Office of the Attorney General) local statutory instruments.

Walks the SI year indexes /eli/<y>/si/ (honest UA, >=2 s/host; the site has no robots.txt -> allow),
keeps instruments whose title names one Irish local authority area and is local-government in nature
(local electoral areas / municipal districts, boundary alterations, council bye-laws/regulations confirmed by SI,
SDZ planning schemes, local speed limits, etc.), fetches /eli/<y>/si/<n>/made/en/print and stages the text under
the current local authority (Tipperary N/S Riding -> Tipperary CC; Limerick/Waterford city or county -> merged
2014 councils; 'County Dublin' pre-1994 -> unmatched: ambiguous between Fingal / South Dublin / DLR).
doc_id = ie_si:<year>/<number>. Records with no text (scanned only) go to the OCR list with the PDF URL.
Resumable: per-SI items in the state db (source 'isb'), per-year 'year:isb:<y>' done keys."""
import argparse, html, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.util import LANE, STAGE, STATE_DIR, PoliteSession, State, StopRun, append_jsonl, get_logger, guard, utcnow  # noqa: E402,E501
from places import Places, place_codes  # noqa: E402
from archive.staging import StagedWriter  # noqa: E402

BASE = "https://www.irishstatutebook.ie"
log = get_logger("ukie_isb")
OCR_LIST = STATE_DIR / "needs_ocr" / "notext_urls.jsonl"
UNMATCHED = STATE_DIR / "unmatched_isb.jsonl"
LICENSE = ("Oireachtas (Open Data) PSI Licence incorporating CC BY 4.0, "
           "https://www.irishstatutebook.ie/eli/open-data.html")
# area name in titles -> current local authority (place_id)
AREA = [
    (r"Dún Laoghaire[- ]Rathdown|Dun Laoghaire[- ]Rathdown", "wd:Q5320425"),
    (r"South Dublin", "wd:Q7567084"), (r"Fingal", "wd:Q5450180"),
    (r"(?:City|County Borough) of Dublin|Dublin City|Dublin Corporation", "wd:Q4810766"),
    (r"(?:City|County Borough) of Cork|Cork City|Cork Corporation", "wd:Q5170762"),
    (r"County (?:of )?Cork|Cork County", "wd:Q5170774"),
    (r"(?:City|County Borough) of Galway|Galway City", "wd:Q5519477"),
    (r"County (?:of )?Galway|Galway County", "wd:Q5519483"),
    (r"Limerick", "wd:Q16886590"), (r"Waterford", "wd:Q16886769"), (r"Tipperary", "wd:Q7808890"),
    (r"Carlow", "wd:Q5042852"), (r"Cavan", "wd:Q2974524"), (r"Clare", "wd:Q5126146"), (r"Donegal", "wd:Q3782781"),
    (r"Kerry", "wd:Q6394503"), (r"Kildare", "wd:Q6406724"), (r"Kilkenny", "wd:Q6407034"),
    (r"Laois|Leix|Queen'?s County", "wd:Q6487885"), (r"Leitrim", "wd:Q6520435"), (r"Longford", "wd:Q6673830"),
    (r"Louth", "wd:Q6689844"), (r"Mayo", "wd:Q6797511"), (r"\bMeath\b", "wd:Q6804297"),
    (r"Monaghan", "wd:Q4319098"), (r"Offaly|King'?s County", "wd:Q7079017"), (r"Roscommon", "wd:Q7367572"),
    (r"Sligo", "wd:Q7540498"), (r"Westmeath", "wd:Q7989085"), (r"Wexford", "wd:Q7990249"), (r"Wicklow", "wd:Q7998430"),
]
AREA = [(re.compile(r"\b(?:" + a + r")\b", re.I), p) for a, p in AREA]
COUNTY_DUBLIN = re.compile(r"County (?:of )?Dublin|Dublin County", re.I)
LOCALISH = re.compile(r"Electoral Area|Municipal District|Electoral Divisions?|Boundar|Bye-?Laws?|"
                      r"County Council|City Council|Borough Council|Town Council|Corporation|County Borough|"
                      r"Local Government|Planning Scheme|Strategic Development Zone|Speed Limit|Casual Trading|"
                      r"Control of Dogs|Burial Ground|Urban District|Town Commissioners|Vocational Education|"
                      r"Housing Authorit|Fire Brigade|Water Supply|Sanitary Authorit|Library|Harbour", re.I)
NONLA = re.compile(r"Registration Board|University|Hospital|Institute of Technology|Garda|Prison|"
                   r"Port Company|Harbour Company|Education and Training Board|Credit Union|Courts?\b|Dáil|Seanad|"
                   r"Constituenc|European Parliament|Fisheries|Milk|Agricultur|Livestock|Pigs|Bacon", re.I)
TITLE_RE = re.compile(r'<a href="/(\d{4})/en/si/(\d{4})\.html">([^<]+)')


def place_for(title):
    if NONLA.search(title) or not LOCALISH.search(title):
        return None, "not_local_government"
    if COUNTY_DUBLIN.search(title) and not re.search(r"City|Fingal|South Dublin|Laoghaire", title, re.I):
        return None, "ambiguous:county_dublin"
    hits = []
    for rx, pid in AREA:
        m = rx.search(title)
        if m and pid not in hits:
            hits.append(pid)
            title = title[:m.start()] + " " * (m.end() - m.start()) + title[m.end():]   # Cork City before County Cork
    if not hits:
        return None, "no_area"
    if len(hits) > 1:
        return None, "multi_area:" + ",".join(hits)
    return hits[0], "title_area"


def si_text(raw):
    h = raw[:raw.find("includedFooter")] if "includedFooter" in raw else raw
    h = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S | re.I)
    t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h)).split())
    heads = [m.start() for m in re.finditer(r"S\.I\. No\. \d+/\d{4}", t)]
    if heads:
        t = t[heads[-1]:]
    t = re.sub(r"^(.*?)\s+(?:Amendments Leasuithe\s+)?Download PDF \S+ PDF\s+", r"\1\n\n", t, count=1)
    return t.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="1922-2026")
    ap.add_argument("--limit", type=int, default=0, help="stop after N staged (test)")
    a = ap.parse_args()
    y0, y1 = (int(x) for x in a.years.split("-"))
    ps, st, P, codes = PoliteSession(log, min_interval=2.0), State(), Places(), place_codes()
    w, n = {}, {"staged": 0, "ocr": 0, "unmatched": 0, "not_local": 0, "skipped": 0}

    def flush():
        for x in w.values():
            x.flush()
        w.clear()
    try:
        for y in range(y1, y0 - 1, -1):
            if st.item(f"year:isb:{y}") == "done":
                continue
            guard()
            idx = ps.get(f"{BASE}/eli/{y}/si/").content.decode("utf-8", "replace")
            for yy, num, title in TITLE_RE.findall(idx):
                title = " ".join(html.unescape(title).split()).rstrip(".")
                no = int(num)
                key = f"isb/{yy}/{no}"
                if st.item(key) not in (None, "redo"):
                    n["skipped"] += 1
                    continue
                pid, how = place_for(title)
                if not pid:
                    if how not in ("not_local_government", "no_area"):
                        append_jsonl(UNMATCHED, {"key": key, "title": title, "reason": how, "at": utcnow()})
                        n["unmatched"] += 1
                        st.mark_item(key, "isb", "unmatched", None, {"title": title, "reason": how})
                    else:
                        n["not_local"] += 1
                        st.mark_item(key, "isb", "not_local", None, None)
                    continue
                place = P.get(pid)
                guard()
                url = f"{BASE}/eli/{yy}/si/{no}/made/en/print"
                text = si_text(ps.get(url).content.decode("utf-8", "replace"))
                did = f"ie_si:{yy}/{no}"
                pdf = f"{BASE}/pdf/{yy}/en.si.{yy}.{num}.pdf"
                if len(text) < 300:
                    append_jsonl(OCR_LIST, {"place_id": pid, "place_name": place["place_name"], "source_url": pdf,
                                            "title": title, "doc_key": "doc:" + did, "doc_id": did, "site": BASE + "/",
                                            "place_key": pid.replace(":", "_"), "country_code": "IE",
                                            "local_instrument_kind": "statutory_instrument", "lane": LANE,
                                            "listed_at": utcnow(), "source_policy": None})
                    st.mark_item(key, "isb", "needs_ocr", pid, {"title": title})
                    n["ocr"] += 1
                    continue
                rec = {"place_id": pid, "country_code": "IE", "doc_id": did, "source_platform": "irishstatutebook",
                       "source_url": f"{BASE}/eli/{yy}/si/{no}/made/en/html", "doc_type": "regulation",
                       "language": "en", "title_native": title, "number": f"S.I. No. {no} of {yy}",
                       "adopted_date": None, "published_date": None, "effective_date": None, "in_force": None,
                       "consolidated": False, "content_format": "html", "text": text, "retrieved_at": utcnow(),
                       "place_name": place["place_name"], "qid": place["qid"], "iso_3166_2": place.get("iso_3166_2") or None,
                       "admin_level": place["admin_level"], "platform": "irishstatutebook", "platform_place_id": None,
                       "source_official": True, "source_org": "Office of the Attorney General (eISB)",
                       "license_note": LICENSE, "act_kind": "IE local statutory instrument", "place_match": how,
                       "pdf_url": pdf, "lane": LANE, "place_codes": codes.get(pid) or None}
                if pid not in w:
                    w[pid] = StagedWriter(STAGE, "IE", pid, batch_prefix="ukie-isb", chunk=200)
                err = w[pid].add(rec)
                st.mark_item(key, "isb", "invalid" if err else "staged", pid, {"title": title, "err": err} if err else None)
                n["staged"] += 0 if err else 1
                if a.limit and n["staged"] >= a.limit:
                    raise StopRun("test limit reached")
            flush()
            st.mark_item(f"year:isb:{y}", "isb", "done", None, dict(n))
            log.info("isb year %d: %s", y, n)
    except StopRun as e:
        log.warning("stop: %s", e)
    finally:
        flush()
    print(json.dumps(n))
    print("ISB_DONE")


if __name__ == "__main__":
    main()
