"""PK: sitting judges of the Sindh, Peshawar and Balochistan High Courts from each court's official 'sitting judges' page (live, robots checked:
SHC disallows only /causelist/, BHC disallows only asset dirs, PHC robots.txt returns an HTML redirect (no valid robots => treated as absent)).
Names and official titles only; DOB/appointment/retirement dates are NOT stored (SHC retirement date used only to skip anyone already past it).
HTML comments (commented-out former judges) are stripped before parsing."""
import json, re, html, datetime, hashlib, os, time, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
OUT = f"{ROOT}/data/pk/pk_judges.jsonl"; now = datetime.datetime.now(datetime.UTC); today = now.date()
SRC = {"shc": ("https://sindhhighcourt.gov.pk/sitting_judges.php", "osm:node/5107524358", "Sindh High Court", "robots_allowed"),
       "phc": ("https://www.peshawarhighcourt.gov.pk/app/site/35/c/Sitting_Judges.html", "pk-wd-q7171378", "Peshawar High Court", "robots_invalid(html_redirect):treated_absent"),
       "bhc": ("https://bhc.gov.pk/judges/hon-judges", "osm:way/436809661", "High Court of Balochistan", "robots_allowed")}
def toks(t):
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S); t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=re.S)
    return [x for x in (re.sub(r"\s+", " ", html.unescape(y)).strip() for y in re.sub(r"<[^>]+>", "\n", t).split("\n")) if x]
DT = re.compile(r"^\d{2}-\d{2}-\d{4}$"); HON = re.compile(r"^(?:\d+-\s*)?(?:Mr\.|Mrs\.|Ms\.|Miss)?\s*Justice\b\s*(.*)$")
def clean(n): return re.sub(r"\s+", " ", re.sub(r"^(?:Mr\.|Mrs\.|Ms\.|Miss)\s+", "", n.strip())).strip(" .,")
def parse(k, T):
    out = []
    if k == "shc":
        s = T.index("Date of Retirement") + 1; i = s
        while i < len(T):
            m = HON.match(T[i]); role = "Chief Justice" if i > 0 and "Chief Justice" in T[i - 1] else None
            if not m: i += 1; continue
            nm = [m.group(1)]; j = i + 1
            while j < len(T) and not DT.match(T[j]) and not HON.match(T[j]):
                if "Senior Puisne" in T[j]: role = "Senior Puisne Judge"
                elif "Chief Justice" not in T[j]: nm.append(T[j])
                j += 1
            ds = [x for x in T[j:j + 3] if DT.match(x)]
            if len(ds) < 2: break  # end of table
            ret = datetime.datetime.strptime(ds[-1], "%d-%m-%Y").date() if len(ds) == 3 else None
            if any("Transferred" in x for x in nm): i = j + len(ds); continue  # transferred away (listed elsewhere)
            if not (ret and ret < today): out.append((clean(" ".join(nm)), role))
            i = j + len(ds)
    elif k == "phc":
        for i, x in enumerate(T):
            m = HON.match(x)
            if not m or not (x[0].isdigit() or (i and "Chief Justice" in T[i - 1])): continue
            n = m.group(1); role = "Chief Justice" if not x[0].isdigit() else None
            if "(Senior Puisne Judge)" in n: role = "Senior Puisne Judge"; n = n.replace("(Senior Puisne Judge)", "")
            out.append((clean(n), role))
    else:
        for i, x in enumerate(T):
            m = HON.match(x)
            if m and i and T[i - 1].startswith("The Honorable"):
                out.append((clean(m.group(1)), "Chief Justice" if "Chief Justice" in T[i - 1] else None))
    return out
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
have = {slug(x["name"]) for x in old}; ids = {x["judge_id"] for x in old}
for k, (url, cid, cname, pol) in SRC.items():
    r = requests.get(url, headers={"User-Agent": UA}, timeout=60); time.sleep(3); r.raise_for_status()
    sha = hashlib.sha256(r.content).hexdigest(); recs = parse(k, toks(r.text)); n = dup = 0
    with open(OUT, "a") as f:
        for name, role in recs:
            jid = f"pk-{slug(cname)}-{slug(name)}"
            if slug(name) in have or jid in ids: dup += 1; continue
            f.write(json.dumps({"judge_id": jid, "court_id": cid, "name": name, "title": f"{role or 'Judge'}, {cname}",
                "position_type": "chief" if role == "Chief Justice" else "associate", "term_start": None, "term_end": None, "status": "sitting",
                "roster_url": url, "source_url": url, "site_policy": pol, "retrieved_at": now.isoformat(), "needs_review": False,
                "extraction": f"{cname} official sitting-judges page (names and titles only)", "license": f"{cname} website (facts)", "source_sha256": sha},
                ensure_ascii=False) + "\n"); n += 1; have.add(slug(name)); ids.add(jid)
    print(k, "parsed", len(recs), "added", n, "dup_skipped", dup, [x[0] for x in recs][:3])
