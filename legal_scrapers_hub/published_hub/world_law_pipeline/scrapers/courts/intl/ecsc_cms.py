"""ECSC (Eastern Caribbean Supreme Court, seat Castries, Saint Lucia): judicial officers + Civil Procedure Rules
(CPR 2000 and CPR Revised Edition 2023, part-level text) via the public WordPress REST API at cms.eccourts.org,
which backs the www.eccourts.org Vue front end (robots.txt on www allows all; cms has no robots.txt).
Rows are written once under data/lc/ (court seat); rules carry applies_to for all member states/territories."""
import json, re, sys, os, html, hashlib, datetime, time, urllib.request
ROOT = "/workspace/world_courts"
API = "https://cms.eccourts.org/wp-json/wp/v2/pages"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
MEMBERS = ["AG", "DM", "GD", "KN", "LC", "VC", "AI", "MS", "VG"]
now = datetime.datetime.now(datetime.UTC).isoformat()
def get(url):
    time.sleep(1.0)
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
def text(h):
    h = re.sub(r"<(script|style).*?</\1>", " ", h, flags=re.S)
    h = re.sub(r"</(p|li|h\d|tr|div)>|<br\s*/?>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", l).strip() for l in t.split("\n") if l.strip())
def rjl(p): return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
def append(p, rows):
    with open(p, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
dry = "--dry" in sys.argv
# ---- rules
RS = {18422: ("ecsc-cpr-2000", "Eastern Caribbean Supreme Court Civil Procedure Rules 2000", "2000-12-31"),
      101443: ("ecsc-cpr-2023", "Eastern Caribbean Supreme Court Civil Procedure Rules (Revised Edition) 2023", None)}
OUT = f"{ROOT}/data/lc/lc_rules.jsonl"; old = {r["rule_id"] for r in rjl(OUT)}; rules = []
for pid, (rsid, rsname, eff) in RS.items():
    idx = json.loads(get(f"{API}/{pid}?_fields=link"))["link"]
    pages = json.loads(get(f"{API}?parent={pid}&per_page=100&_fields=id,title,link,content,modified"))
    for p in pages:
        title = html.unescape(p["title"]["rendered"]).strip()
        m = re.match(r"Part\s+(\d+\s*:?\s*[A-Z]?)\s*[–-]?\s*(.*)", title)
        num = re.sub(r"\s*:\s*|\s+", "", m.group(1)) if m else str(p["id"])
        ttl = (m.group(2) if m else title).strip(" –-")
        raw = p["content"]["rendered"]; txt = text(raw)
        rid = f"{rsid}:part{num.lower()}"
        if rid in old or len(txt) < 40: continue
        sha = hashlib.sha256(raw.encode()).hexdigest()
        rules.append({"rule_id": rid, "rule_set_id": rsid, "court_id": "lc-supreme-court", "jurisdiction": "ECSC",
            "applies_to": MEMBERS, "rule_set": rsname, "rule_number": f"Part {num}", "title": ttl, "text": txt,
            "effective_date": eff, "pdf_path": None, "pdf_sha256": None, "source_sha256": sha, "source_url": p["link"],
            "index_url": idx, "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now,
            "source_modified": p["modified"], "granularity": "part",
            "license": "Official ECSC rules text published on eccourts.org; no licence stated", "language": "en"})
# ---- judges (names and official titles only)
JOUT = f"{ROOT}/data/lc/lc_judges.jsonl"; jold = {r["judge_id"] for r in rjl(JOUT)}; judges = []
def jrow(name, title, court, ptype, url, sha, review, how):
    jid = f"{court}-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return {"judge_id": jid, "court_id": court, "name": name, "title": title, "position_type": ptype, "term_start": None,
        "term_end": None, "status": "sitting", "jurisdiction": "ECSC", "roster_url": "https://www.eccourts.org/judicial-officers",
        "source_url": url, "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": review,
        "extraction": how, "license": "Eastern Caribbean Supreme Court website (facts)", "source_sha256": sha}
cj = json.loads(get(f"{API}/42950?_fields=content,link")); cjt = text(cj["content"]["rendered"])
mcj = re.search(r"Hon\. Justice ([A-Z][\w.\- ]+?)\s*\n?\s*Chief Justice", cjt)
cjname = re.sub(r"\s+", " ", mcj.group(1)).strip() if mcj else None
if cjname:
    judges.append(jrow(cjname, "Chief Justice", "lc-supreme-court", "chief", cj["link"], hashlib.sha256(cj["content"]["rendered"].encode()).hexdigest(), False, "official 'Meet the Chief Justice' page"))
kids = json.loads(get(f"{API}?parent=1322&per_page=100&_fields=id,title,link,content"))
for p in kids:
    t = html.unescape(p["title"]["rendered"]); raw = p["content"]["rendered"]; sha = hashlib.sha256(raw.encode()).hexdigest()
    if p["id"] == 42650:
        for nm in re.findall(r"Master Hon\. ([^\n]+)", text(raw)):
            judges.append(jrow(nm.strip(), "Master", "lc-high-court", "master", p["link"], sha, False, "official 'Masters' page under Judicial Officers"))
        continue
    m = re.search(r"Hon\. (?:Justice )?(.+)", t)
    if not m: continue
    nm = re.sub(r",\s*KC$", "", m.group(1)).strip()
    if cjname and nm.replace("-", " ").split()[-1] in cjname.replace("-", " "): continue
    bio = text(raw)
    if re.search(r"(appointed|elevated)[^.]{0,80}Justice of Appeal", bio) and not re.search(r"retire", bio):
        judges.append(jrow(nm, "Justice of Appeal", "lc-court-of-appeal", "appellate", p["link"], sha, False, "official judicial-officer page; title from bio statement of appointment"))
    else:
        judges.append(jrow(nm, "Judicial Officer (Eastern Caribbean Supreme Court)", "lc-court-of-appeal", None, p["link"], sha, True, "listed under official Judicial Officers section; current post not stated explicitly in bio"))
judges = [j for j in judges if j["judge_id"] not in jold]
if not dry:
    append(OUT, rules); append(JOUT, judges)
print("rules", len(rules), "judges", len(judges))
for j in judges: print(" ", j["name"], "|", j["title"], "|", j["needs_review"])
