"""ECSC rule sets from official gazetted PDFs on cms.eccourts.org (Saint Lucia copies), rule-level:
 - Eastern Caribbean Supreme Court (Bail) Rules, 2023 (SLU S.I. 2023 No. 128; also gazetted ANU, AXA, BVI, GDA, SKB, MNI, SVG)
 - Eastern Caribbean Supreme Court (Non-Contentious Probate and Administration of Estates) Rules, 2017 (SLU S.I. 2017 No. 104;
   counterparts gazetted ANU, AXA, BVI 2017, SKB 2017, DOM 2019, GDA 2021)
Rule titles from the 'Arrangement of Rules', text from the body up to the Schedule. Appends to data/lc/lc_rules.jsonl (dedupe by rule_id).
Saint Lucia text is used; member-state copies can differ in local references -> needs_review."""
import json, re, os, hashlib, datetime, subprocess, time, urllib.request
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/lc"; OUT = f"{ROOT}/data/lc/lc_rules.jsonl"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
now = datetime.datetime.now(datetime.UTC).isoformat()
U = "https://cms.eccourts.org/wp-content/uploads/"
SETS = [dict(id="ecsc-bail-2023", name="Eastern Caribbean Supreme Court (Bail) Rules, 2023", eff="2023-10-09",
             url=U + "2023/10/SLU-S.I.-128-of-2023-Eastern-Caribbean-Supreme-Court-Bail-Rules-2023.pdf",
             applies=["LC", "AG", "AI", "VG", "GD", "KN", "MS", "VC"], gaz="Saint Lucia S.I. 2023 No. 128"),
        dict(id="ecsc-ncp-2017", name="Eastern Caribbean Supreme Court (Non-Contentious Probate and Administration of Estates) Rules, 2017",
             eff=None, url=U + "2021/11/SLU-S.I.-104-of-2017-NON-CONTENTIOUS-PROBATE-RULES-2017.pdf",
             applies=["LC", "AG", "AI", "VG", "KN", "DM", "GD"], gaz="Saint Lucia S.I. 2017 No. 104")]
P = (".", ";", ":", ",", "—")
def fetch(url):
    p = f"{RAW}/{url.rsplit('/', 1)[1]}"
    if not os.path.exists(p):
        time.sleep(2); open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read())
    return p, hashlib.sha256(open(p, "rb").read()).hexdigest()
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
rows = []
for S in SETS:
    p, sha = fetch(S["url"])
    L = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.splitlines()
    a0 = next(i for i, l in enumerate(L) if "ARRANGEMENT OF RULES" in l)
    a1 = next(i for i, l in enumerate(L) if i > a0 and re.fullmatch(r"\s*SCHEDULES?\s*", l))
    toc = []
    for i in range(a0, a1):
        m = re.match(r"\s{0,8}(\d{1,3})\.\s*(\S.*)", L[i])
        if m and int(m.group(1)) == len(toc) + 1: toc.append([int(m.group(1)), m.group(2).strip()])
        elif toc and L[i].strip() and not re.search(r"^\s*\d+\s*$|Rules$|^Rule$", L[i].strip()) and L[i].startswith("    "):
            toc[-1][1] += " " + L[i].strip()
    b0 = next(i for i, l in enumerate(L) if i > a1 and "In exercise of the powers" in l)
    b1 = next(i for i, l in enumerate(L) if i > b0 and re.fullmatch(r"\s*SCHEDULES?\s*", l))
    starts, k = [], 0
    for i in range(b0, b1):
        if k < len(toc) and re.match(rf"\s{{0,12}}{toc[k][0]}\.\s*(—|–|\(|[A-Z“\"a-z])", L[i]): starts.append(i); k += 1
    assert k == len(toc), (S["id"], k, len(toc))
    junk = re.compile(r"^\s*\d{1,4}\s*$|^\s*Eastern Caribbean Supreme Court \(|^\s*and Administration of Estates\) Rules\s*$")
    for j, (n, title) in enumerate(toc):
        e = starts[j + 1] if j + 1 < len(starts) else b1
        body = [l.rstrip() for l in L[starts[j]:e] if not junk.search(l)]
        nb = [i for i, x in enumerate(body) if x.strip()]
        if j + 1 < len(toc):
            nt = re.sub(r"\W+", "", toc[j + 1][1]).lower()
            for t in (3, 2, 1):
                if len(nb) > t and nt.startswith(re.sub(r"\W+", "", " ".join(body[x] for x in nb[-t:])).lower()):
                    body = body[:nb[-t - 1] + 1]; nb = nb[:-t]; break
        tail = 0
        while tail < len(nb) and not body[nb[-1 - tail]].rstrip().endswith(P): tail += 1
        if 0 < tail <= 4 and tail < len(nb): body = body[:nb[-1 - tail] + 1]
        rid = f"{S['id']}:r{n}"
        if rid in old: continue
        rows.append({"rule_id": rid, "rule_set_id": S["id"], "court_id": "lc-supreme-court", "jurisdiction": "ECSC", "applies_to": S["applies"],
            "rule_set": S["name"], "rule_number": f"Rule {n}", "title": re.sub(r"\s+", " ", title), "text": re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip(),
            "effective_date": S["eff"], "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": S["url"],
            "index_url": "https://www.eccourts.org/rules", "source_kind": "official", "site_policy": "no_robots_txt", "retrieved_at": now,
            "granularity": "rule", "license": f"Official gazetted text ({S['gaz']}) published on eccourts.org; no licence stated", "language": "en",
            "version_note": f"Text from the {S['gaz']} copy; separately gazetted counterparts in other member states may differ in local references",
            "needs_review": True})
    print(S["id"], "toc", len(toc), "new", sum(1 for r in rows if r["rule_set_id"] == S["id"]))
if os.environ.get("DRY"):
    for r in rows[:2] + rows[-2:]: print(r["rule_id"], r["title"], repr(r["text"][:150]), repr(r["text"][-120:]))
else:
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
