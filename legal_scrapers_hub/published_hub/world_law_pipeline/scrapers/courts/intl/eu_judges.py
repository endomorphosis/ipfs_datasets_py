"""Judges (needs_review=true): CJEU Court of Justice + General Court members from curia.europa.eu (official 'The Members' pages; name, office, appointment date from the biography text),
and Ireland's 198 judges imported (provenance) from endomorphosis/ipfs_ireland_courts -> data/eu/eu_judges.jsonl, data/ie/ie_judges.jsonl"""
import sys, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import cached
from bs4 import BeautifulSoup
import pandas as pd
def curia(url, key, court, court_label):
    b, u, pol = cached(url, key, delay=2.0)
    s = BeautifulSoup(b.decode("utf-8", "replace"), "html.parser"); out = []; now = NOW()
    for h in s.find_all("h3"):
        box = h.parent
        if "curia-cv-item-details" not in (box.get("class") or []): continue
        name = h.get_text(" ", strip=True); role = h.find_next_sibling().get_text(" ", strip=True) if h.find_next_sibling() else "Judge"
        text = box.get_text(" ", strip=True).replace("\xa0", " ")
        m = re.search(r"appointed as (?:a |an |the )?(?:Member|Judge|Advocate General)[^.]*? (?:at|of) the (Court of Justice|General Court)[^.]*? on (\d{1,2} \w+ \d{4})", text) or re.search(r"(?:appointed|Appointed)[^.]*? on (\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4})", text)
        ts = None
        if m:
            try: ts = datetime.datetime.strptime(m.group(m.lastindex), "%d %B %Y").date().isoformat()
            except Exception: pass
        ptype = "chief" if role in ("President",) else "presiding" if "President" in role else "advocate_general" if "Advocate General" in role else "associate"
        out.append(dict(judge_id=f"eu-{court}-{slug(name)}", court_id=f"eu-cjeu-{court}", name=name, title=role if role != "Judge" else f"Judge of the {court_label}", position_type=ptype, term_start=ts, term_end=None, status="sitting",
                        roster_name=f"{court_label} - The Members", roster_url=u, source_url=u, site_policy=pol, retrieved_at=now, needs_review=True, extraction="curia-cv-item-details h3 + role sibling; appointment date regex on biography", license="CC-BY-4.0 (EU reuse, Decision 2011/833/EU)"))
    return out
def main():
    j = curia("https://curia.europa.eu/jcms/jcms/Jo2_7026/en/", "intl_jud_curia_cj.html", "court-of-justice", "Court of Justice")
    j += curia("https://curia.europa.eu/site/jcms/d2_5097/en/general-court", "intl_jud_curia_gc.html", "general-court", "General Court")
    seen = set(); jj = []
    for r in j:
        if r["judge_id"] in seen: continue
        seen.add(r["judge_id"]); jj.append(r)
    wjl(f"{ROOT}/data/eu/eu_judges.jsonl", jj); print("EU judges", len(jj), collections_count(jj))
    ie = []; d = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_ie/data/judges-00000.parquet")
    for r in d.itertuples():
        ie.append(dict(judge_id=r.judge_id, court_id=r.court_id, name=r.full_name, title=r.title if isinstance(r.title, str) else None, position_type=r.role, division=r.chamber_or_division if isinstance(r.chamber_or_division, str) else None,
                       term_start=str(r.appointed_date) if r.appointed_date is not None and str(r.appointed_date) != "NaT" else None, term_end=None, status=r.status, roster_url=r.source_url, source_url=r.official_bio_url if isinstance(r.official_bio_url, str) else r.source_url,
                       site_policy="upstream_dataset", retrieved_at=str(r.source_retrieved_at), needs_review=True, extraction="import:endomorphosis/ipfs_ireland_courts", upstream="endomorphosis/ipfs_ireland_courts", license="courts-ie-psi-reuse"))
    os.makedirs(f"{ROOT}/data/ie", exist_ok=True); wjl(f"{ROOT}/data/ie/ie_judges.jsonl", ie); print("IE judges", len(ie))
def collections_count(rows):
    import collections; return dict(collections.Counter(r["court_id"] for r in rows))
if __name__ == "__main__": main()
