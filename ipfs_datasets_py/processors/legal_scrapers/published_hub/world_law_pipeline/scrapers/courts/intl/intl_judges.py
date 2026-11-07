"""Judges for GB/CA/AU -> data/<cc>/<cc>_judges.jsonl. E&W (ipfs_uk_courts, judiciary.uk list pages) and Federal Court of Canada (ipfs_canada_courts) are imported with provenance
(no re-scrape); UK Supreme Court (supremecourt.uk), Supreme Court of Canada (scc-csc.ca) and High Court of Australia (hcourt.gov.au) are collected from the official rosters.
Only official name/title/role/appointment date; needs_review=true as in the US judge files."""
import sys, glob
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW, html_text, cached
import pandas as pd
MAP = [("Circuit Judges", "gb-ew-crown-court"), ("District Judges (Magistrates", "gb-ew-magistrates-court"), ("District Judges", "gb-ew-county-court"), ("First-tier", "gb-ew-tribunals-first-tier"),
       ("Employment Tribunals", "gb-ew-employment-tribunal"), ("Upper Tribunal", "gb-ew-tribunals-upper"), ("Court of Appeal", "gb-ew-court-of-appeal"), ("High Court", "gb-ew-high-court"),
       ("Heads of Division", "gb-ew-court-of-appeal")]
def gb_court(n):
    for k, v in MAP:
        if k in n: return v
    return None
def sha(s): import hashlib; return hashlib.sha1(s.encode()).hexdigest()[:12]
def build():
    gb = []; now = NOW()
    j = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_uk/data/judges-00000.parquet")
    for r in j.itertuples():
        ex = dict(r.external_ids); cn = ex.get("court_name", "")
        gb.append(dict(judge_id=r.judge_id, court_id=gb_court(cn), name=r.full_name, title=r.title, position_type=r.role, division=r.chamber_or_division if isinstance(r.chamber_or_division, str) else None,
                       term_start=str(r.appointed_date) if r.appointed_date is not None else None, term_end=str(r.term_end_date) if r.term_end_date is not None else None, status=r.status,
                       roster_name=cn, roster_url=r.source_url, source_url=r.source_url, site_policy="archive:commoncrawl", retrieved_at=r.source_retrieved_at.isoformat(), needs_review=True,
                       extraction="import:endomorphosis/ipfs_uk_courts", upstream="endomorphosis/ipfs_uk_courts", license="OGL-3.0"))
    # UKSC
    b, _, _ = cached("https://www.supremecourt.uk/justices/lord-reed", "intl_jud_uksc_reed.html")
    base = b.decode("utf-8", "replace")
    slugs = ["lord-reed"] + [s.rsplit("/", 1)[-1] for s in sorted(set(re.findall(r'href="(/justices/[^"]+)"', base)))]
    NAMES = {"lord-reed": "Lord Reed", "lord-sales": "Lord Sales", "lord-lloyd-jones": "Lord Lloyd-Jones", "lord-briggs": "Lord Briggs", "lord-hamblen": "Lord Hamblen", "lord-leggatt": "Lord Leggatt",
             "lord-burrows": "Lord Burrows", "lord-stephens": "Lord Stephens", "lady-rose": "Lady Rose", "lady-simler": "Lady Simler", "lord-doherty": "Lord Doherty", "lord-snowden": "Lord Snowden"}
    for s in slugs:
        u = f"https://www.supremecourt.uk/justices/{s}"
        bb, _, pol = cached(u, f"intl_jud_uksc_{s}.html")
        if not bb or s not in NAMES: print("uksc skip", s); continue
        t = html_text(bb.decode("utf-8", "replace")); nm = NAMES[s]
        m = re.search(r"appointed (?:as )?(?:a )?Justice[^.]*? on (\d{1,2} \w+ \d{4})", t)
        ts = None
        if m:
            try: ts = datetime.datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
            except Exception: pass
        title = "President" if s == "lord-reed" else "Deputy President" if s == "lord-sales" else "Justice of the Supreme Court"
        gb.append(dict(judge_id=f"gb-uksc-{s}", court_id="gb-uksc", name=nm, title=title, position_type="chief" if s == "lord-reed" else "associate", term_start=ts, term_end=None, status="sitting", roster_url="https://www.supremecourt.uk/justices",
                       source_url=u, site_policy=pol, retrieved_at=now, needs_review=True, extraction="slug->name (official /justices/<slug> pages) + appointment_regex", license="OGL-3.0"))
    wjl(f"{ROOT}/data/gb/gb_judges.jsonl", gb); print("GB judges", len(gb))
    # Canada
    ca = []
    jc = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_ca/data/judges-00000.parquet")
    for r in jc.itertuples():
        ca.append(dict(judge_id=r.judge_id, court_id="ca-fc", name=r.full_name, title=r.title, position_type=r.role, term_start=str(r.appointed_date) if r.appointed_date is not None else None, term_end=None, status=r.status,
                       roster_url=r.source_url, source_url=r.official_bio_url if isinstance(r.official_bio_url, str) else r.source_url, site_policy="archive:commoncrawl", retrieved_at=r.source_retrieved_at.isoformat(), needs_review=True,
                       extraction="import:endomorphosis/ipfs_canada_courts", upstream="endomorphosis/ipfs_canada_courts", license="gc-non-commercial"))
    SCC = [("The Right Honourable Richard Wagner, P.C.", "Chief Justice of Canada", "chief", "2012-10-05"), ("The Honourable Andromache Karakatsanis", "Puisne Judge", "associate", "2011-10-21"),
           ("The Honourable Suzanne Côté", "Puisne Judge", "associate", "2014-12-01"), ("The Honourable Malcolm Rowe", "Puisne Judge", "associate", "2016-10-28"),
           ("The Honourable Nicholas Kasirer", "Puisne Judge", "associate", "2019-09-16"), ("The Honourable Mahmud Jamal", "Puisne Judge", "associate", "2021-07-01"),
           ("The Honourable Michelle O'Bonsawin", "Puisne Judge", "associate", "2022-09-01"), ("The Honourable Mary T. Moreau", "Puisne Judge", "associate", "2023-11-06"),
           ("The Honourable Glenn D. Joyal", "Puisne Judge", "associate", "2026-07-15")]
    for n, t, p, d in SCC:
        ca.append(dict(judge_id=f"ca-scc-{slug(n.replace('The Right Honourable','').replace('The Honourable',''))}", court_id="ca-scc", name=n, title=t, position_type=p, term_start=d, term_end=None, status="sitting",
                       roster_url="https://www.scc-csc.ca/about-apropos/judges-juges/list-liste/", source_url="https://www.scc-csc.ca/about-apropos/judges-juges/list-liste/", site_policy="robots_unknown:box_tls_blocked;fetched_via_webfetch",
                       retrieved_at=now, needs_review=True, extraction="roster_table", license="Crown copyright (Canada)"))
    wjl(f"{ROOT}/data/ca/ca_judges.jsonl", ca); print("CA judges", len(ca))
    HCA = ["The Hon Chief Justice Stephen Gageler AC", "The Hon Justice Michelle Gordon AC", "The Hon Justice James Edelman AC", "The Hon Justice Simon Steward AC", "The Hon Justice Jacqueline Gleeson", "The Hon Justice Jayne Jagot", "The Hon Justice Robert Beech-Jones"]
    au = []
    for n in HCA:
        nm = re.sub(r"^The Hon (Chief Justice|Justice) ", "", n); chief = "Chief Justice" in n
        au.append(dict(judge_id=f"au-hca-{slug(nm)}", court_id="au-hca", name=nm, title="Chief Justice" if chief else "Justice", position_type="chief" if chief else "associate", term_start=None, term_end=None, status="sitting",
                       roster_url="https://www.hcourt.gov.au/justices/current-justices", source_url="https://www.hcourt.gov.au/justices/current-justices", site_policy="robots_unknown:fetched_via_webfetch", retrieved_at=now,
                       needs_review=True, extraction="roster_list", license="CC-BY-4.0 (HCA)"))
    wjl(f"{ROOT}/data/au/au_judges.jsonl", au); print("AU judges", len(au))
if __name__ == "__main__": build()
