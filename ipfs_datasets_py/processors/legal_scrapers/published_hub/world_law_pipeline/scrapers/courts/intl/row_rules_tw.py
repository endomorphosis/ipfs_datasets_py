"""Taiwan procedural statutes from the Ministry of Justice National Laws & Regulations Database open data (law.moj.gov.tw/api/Ch/Law/JSON), one row per article (zh).
-> data/tw/tw_rules.jsonl + crosswalk"""
import sys, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
P = f"{ROOT}/rules/raw/tw/ChLaw.json"
SETS = {"法院組織法": ("tw-courts-organization-act", ["tw-constitutional-court", "tw-supreme-court", "tw-high-court", "tw-district-court"]), "民事訴訟法": ("tw-civil-procedure-code", ["tw-supreme-court", "tw-high-court", "tw-district-court", "tw-ip-commercial-court"]),
        "刑事訴訟法": ("tw-criminal-procedure-code", ["tw-supreme-court", "tw-high-court", "tw-district-court"]), "行政訴訟法": ("tw-administrative-procedure-act", ["tw-supreme-administrative-court", "tw-high-administrative-court"]),
        "家事事件法": ("tw-family-proceedings-act", ["tw-supreme-court", "tw-high-court", "tw-district-court"]), "少年事件處理法": ("tw-juvenile-act", ["tw-district-court", "tw-juvenile-family-court"]),
        "智慧財產案件審理法": ("tw-ip-case-adjudication-act", ["tw-ip-commercial-court"]), "憲法訴訟法": ("tw-constitutional-court-procedure-act", ["tw-constitutional-court"]), "強制執行法": ("tw-compulsory-enforcement-act", ["tw-district-court"]),
        "非訟事件法": ("tw-non-contentious-matters-act", ["tw-district-court", "tw-high-court"]), "商業事件審理法": ("tw-commercial-case-adjudication-act", ["tw-ip-commercial-court"]), "民事訴訟費用法": ("tw-civil-litigation-fees-act", ["tw-district-court", "tw-high-court", "tw-supreme-court"]),
        "刑事訴訟法施行法": ("tw-criminal-procedure-code-enforcement-act", ["tw-supreme-court", "tw-high-court", "tw-district-court"]), "破產法": ("tw-bankruptcy-act", ["tw-district-court"]), "消費者債務清理條例": ("tw-consumer-debt-clearance-act", ["tw-district-court"])}
def d8(s): return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if s and len(s) == 8 else None
def main():
    raw = open(P, "rb").read(); sh = hashlib.sha256(raw).hexdigest(); L = json.loads(raw.decode("utf-8-sig"))["Laws"]; rows = []; xw = []
    for l in L:
        if l["LawName"] not in SETS: continue
        sid, courts = SETS[l["LawName"]]; name = l["LawName"] + (f" ({l['EngLawName']})" if l.get("EngLawName") else ""); n = 0
        for a in l["LawArticles"]:
            if not a.get("ArticleNo") or a.get("ArticleType") != "A": continue
            no = a["ArticleNo"].strip()
            rows.append(dict(rule_id=f"{sid}:{no}", rule_set_id=sid, court_id=None, jurisdiction="TW", rule_set=name, rule_number=f"第 {no} 條" if True else no, title=None, text=re.sub(r"\s+", " ", a["ArticleContent"]).strip()[:12000], effective_date=d8(l.get("LawModifiedDate")), pdf_path=None, pdf_sha256=None, source_sha256=sh,
                             source_url=l["LawURL"], site_policy="open_data_dump", retrieved_at=NOW(), license="Government Website Open Data License v1.0 (Taiwan MOJ)", language="zh")); n += 1
        print(sid, n, flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="TW", basis="statute governing procedure in this court tier", source_url=l["LawURL"], linked_rows="new"))
    os.makedirs(f"{ROOT}/data/tw", exist_ok=True); wjl(f"{ROOT}/data/tw/tw_rules.jsonl", rows); wjl(f"{ROOT}/data/tw/tw_rules_crosswalk.jsonl", xw); print("TW rules", len(rows))
if __name__ == "__main__": main()
