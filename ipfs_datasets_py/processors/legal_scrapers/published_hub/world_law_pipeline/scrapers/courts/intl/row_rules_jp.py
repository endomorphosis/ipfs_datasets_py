"""Japan procedural codes and Supreme Court rules from the official e-Gov Laws API v2 (laws.e-gov.go.jp, open data) -> data/jp/jp_rules.jsonl + crosswalk. One row per article (Japanese, current revision)."""
import sys, json, hashlib, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
RAWD = f"{ROOT}/rules/raw/jp"; os.makedirs(RAWD, exist_ok=True)
SETS = [  # title, id, courts-tier keys
 ("民事訴訟法", "jp-ccp", "civil"), ("民事訴訟規則", "jp-rcp", "civil"), ("刑事訴訟法", "jp-ccrp", "criminal"), ("刑事訴訟規則", "jp-rcrp", "criminal"), ("裁判所法", "jp-courts-act", "all"),
 ("家事事件手続法", "jp-family-act", "family"), ("家事事件手続規則", "jp-family-rules", "family"), ("人事訴訟法", "jp-personal-status-act", "family"), ("行政事件訴訟法", "jp-admin-act", "civil"),
 ("民事執行法", "jp-civil-execution-act", "civil"), ("民事保全法", "jp-civil-provisional-act", "civil"), ("少年法", "jp-juvenile-act", "family"), ("破産法", "jp-bankruptcy-act", "civil")]
def api(path, delay=1.0):
    time.sleep(delay); return get(f"https://laws.e-gov.go.jp/api/2/{path}", delay=0, timeout=120)
def text_of(n):
    if isinstance(n, str): return n
    if n is None: return ""
    t = n.get("tag"); ch = "".join(text_of(c) for c in n.get("children", []))
    if t in ("Paragraph", "Item", "Subitem1", "Subitem2", "Subitem3", "ParagraphSentence", "ArticleCaption", "ParagraphNum", "ItemTitle", "Sentence") and t not in ("Sentence",): return ch + " "
    return ch
def articles(n, out):
    if isinstance(n, dict):
        if n.get("tag") == "Article": out.append(n)
        else:
            for c in n.get("children", []): articles(c, out)
def find(n, tag):
    if isinstance(n, dict):
        if n.get("tag") == tag: return n
        for c in n.get("children", []):
            r = find(c, tag)
            if r: return r
def build():
    rows = []; xw = []
    for title, sid, grp in SETS:
        fn = f"{RAWD}/{sid}.json"
        if not os.path.exists(fn):
            r = json.loads(api("laws?law_title=" + urllib.parse.quote(title) + "&limit=20")); cand = [l for l in r["laws"] if l["revision_info"]["law_title"] == title and l["revision_info"]["current_revision_status"] in ("CurrentEnforced", "PreviousEnforced")]
            if not cand: print("NOT FOUND", title); continue
            lid = cand[0]["law_info"]["law_id"]; open(fn, "w").write(api(f"law_data/{lid}?law_full_text_format=json", 1.0))
        raw = open(fn, "rb").read(); d = json.loads(raw); sh = hashlib.sha256(raw).hexdigest(); li = d["law_info"]; ri = d["revision_info"]
        arts = []; articles(d["law_full_text"], arts); name = f"{title} ({li['law_num']})"
        url = f"https://laws.e-gov.go.jp/law/{li['law_id']}"; n = 0
        for a in arts:
            num = a["attr"].get("Num", ""); cap = find(a, "ArticleCaption"); tt = find(a, "ArticleTitle")
            body = re.sub(r"\s+", " ", "".join(text_of(c) for c in a["children"] if c.get("tag") not in ("ArticleCaption", "ArticleTitle"))).strip()
            if len(body) < 3: continue
            rows.append(dict(rule_id=f"{sid}:{num}", rule_set_id=sid, court_id=None, jurisdiction="JP", rule_set=name, rule_number=f"第{num.replace('_','の')}条" if num else num, title=(text_of(cap).strip(" （）()") if cap else None) or None,
                             text=body[:12000], effective_date=ri.get("amendment_enforcement_date"), pdf_path=None, pdf_sha256=None, source_sha256=sh, source_url=url, site_policy="open_data_api", retrieved_at=NOW(),
                             license="Government of Japan (e-Gov Laws) open data; Government of Japan Standard Terms of Use v2.0 (CC-BY 4.0 compatible)", language="ja")); n += 1
        print(sid, title, n, ri.get("amendment_enforcement_date"), flush=True)
        tiers = {"civil": ["jp-supreme-court", "jp-high", "jp-district", "jp-summary"], "criminal": ["jp-supreme-court", "jp-high", "jp-district", "jp-summary"], "family": ["jp-supreme-court", "jp-high", "jp-family"], "all": ["jp-supreme-court", "jp-high", "jp-district", "jp-family", "jp-summary"]}[grp]
        for c in tiers: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="JP", basis="rule set applies to this court tier (per rule set scope)", source_url=url, linked_rows="new"))
    os.makedirs(f"{ROOT}/data/jp", exist_ok=True); wjl(f"{ROOT}/data/jp/jp_rules.jsonl", rows); wjl(f"{ROOT}/data/jp/jp_rules_crosswalk.jsonl", xw); print("JP rules", len(rows))
if __name__ == "__main__": build()
