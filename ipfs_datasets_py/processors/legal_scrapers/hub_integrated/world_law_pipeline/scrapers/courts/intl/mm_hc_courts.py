"""Myanmar: High Courts of the Regions and States (official sites <region>.hc.gov.mm, linked from unionsupremecourt.gov.mm):
 - 'တရားရုံးလိပ်စာများ' (/locations, paginated): court name + street address in Burmese, plus the court's own Google Maps embed
   (lat/lon taken from the embed's !3d/!2d parameters) -> courthouse rows (High Court, district, township, SAZ and special courts).
 - 'တရားသူကြီးများ' (/judges): judges of the High Court (name + title only; biographies not stored) -> judge rows, needs_review.
robots.txt on every HC host: 'User-agent: * / Disallow:' (allowed). Polite 2 s delay. Dedupe by ids; re-runs add 0. yangon.hc.gov.mm
was unreachable on 2026-11-01 (logged, skipped)."""
import json, re, os, html, hashlib, datetime, time, requests, sys
ROOT = "/workspace/world_courts"; D = f"{ROOT}/data/mm"
UA = {"User-Agent": "Mozilla/5.0 (WorldCourtsResearchBot/1.0; public court directory research; polite crawl)"}
now = datetime.datetime.now(datetime.UTC).isoformat()
HCS = {"ayeyarwady": ("MM-07", "Ayeyarwady Region"), "bago": ("MM-02", "Bago Region"), "chin": ("MM-14", "Chin State"), "kachin": ("MM-11", "Kachin State"),
       "kayah": ("MM-12", "Kayah State"), "kayin": ("MM-13", "Kayin State"), "magway": ("MM-03", "Magway Region"), "mandalay": ("MM-04", "Mandalay Region"),
       "mon": ("MM-15", "Mon State"), "rakhine": ("MM-16", "Rakhine State"), "sagaing": ("MM-01", "Sagaing Region"), "shan": ("MM-17", "Shan State"),
       "tanintharyi": ("MM-05", "Tanintharyi Region"), "yangon": ("MM-06", "Yangon Region")}
POL = "robots_allowed|{h}: High Court of {r} official website; no licence stated"
S = requests.Session()
def get(u):
    for i in range(2):
        try:
            r = S.get(u, headers=UA, timeout=45); time.sleep(2); r.raise_for_status(); return r
        except Exception as e:
            last = e; time.sleep(4)
    raise last
def clean(s): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\u200b", "").replace("\u200c", "")).strip()
def compact(s): return re.sub(r"[\s\u200b\u200c]+", "", s)
def level(n):
    n = compact(n)
    if "တရားလွှတ်တော်" in n: return "appellate", "mm-high-courts-region-state"
    if "ကိုယ်ပိုင်အုပ်ချုပ်ခွင့်ရ" in n: return "trial_general", "mm-sad-courts"
    if "ခရိုင်တရားရုံး" in n: return "trial_general", "mm-district-courts"
    if "မြို့နယ်တရားရုံး" in n: return "trial_limited", "mm-township-courts"
    if "လူငယ်" in n or "ကလေး" in n: return "juvenile", "mm-district-courts"
    return "trial", None
CP, JP = f"{D}/mm_courthouses.jsonl", f"{D}/mm_judges.jsonl"
oldc = {json.loads(l)["court_id"] for l in open(CP)}; oldj = {json.loads(l)["judge_id"] for l in open(JP)}
newc, newj, log = [], [], []
for slug, (iso, rname) in HCS.items():
    host = f"https://{slug}.hc.gov.mm"; pol = POL.format(h=f"{slug}.hc.gov.mm", r=rname)
    try: get(host + "/robots.txt")
    except Exception as e: log.append(f"{slug}: unreachable ({str(e)[:80]})"); continue
    hc_id = f"mm-hc-{slug}"; seen_titles = set(); pg = 1; items = []
    while pg < 60:
        try: r = get(f"{host}/locations?page={pg}")
        except Exception as e: log.append(f"{slug} locations p{pg}: {str(e)[:60]}"); break
        blocks = re.findall(r'<li[^>]*>((?:(?!</li>).)*?views-field-title(?:(?!</li>).)*?)</li>', r.text, re.S)
        got = 0
        for b in blocks:
            t = clean(re.search(r'views-field-title[^>]*>(.*?)</div>', b, re.S).group(1))
            body = re.search(r'views-field-body.*?field-content[^>]*>(.*?)</div>', b, re.S)
            addr = clean(body.group(1)) if body else None
            m = re.search(r"!2d(-?\d+\.\d+)!3d(-?\d+\.\d+)", b)
            if not t or t in seen_titles: continue
            seen_titles.add(t); got += 1; items.append((t, addr, (float(m.group(2)), float(m.group(1))) if m else None, r.url, hashlib.sha256(r.content).hexdigest()))
        if not got: break
        pg += 1
    for t, addr, geo, url, sha in items:
        lv, parent = level(t)
        ct = compact(t); is_hc = (ct.endswith("တရားလွှတ်တော်") and "ခရိုင်" not in ct) or bool(re.match(r"^[^၊]*(တိုင်းဒေသကြီး|ပြည်နယ်)တရားလွှတ်တော်၊", ct))
        cid = hc_id if is_hc else f"mm-hc-{slug}-{hashlib.sha1(t.encode()).hexdigest()[:10]}"
        if cid in oldc or any(x["court_id"] == cid for x in newc): continue
        newc.append({"court_id": cid, "record_type": "courthouse", "name": t, "name_local": t, "level": lv, "court_system": "national",
            "country_code": "MM", "subdivision": iso, "jurisdiction": rname, "parent_court_id": parent if is_hc or parent != "mm-high-courts-region-state" else parent,
            "address": {"street": addr, "city": None, "postcode": None, "region": rname, "country": "MM"},
            "geo": {"lat": geo[0], "lon": geo[1]} if geo else {"lat": None, "lon": None}, "geo_source": "court's own Google Maps embed on the official locations page" if geo else None,
            "phone": None, "website": host if is_hc else None, "wikidata": None, "place_ids": [], "source_url": url, "source_kind": "official",
            "site_policy": pol, "retrieved_at": now, "license": f"High Court of {rname} official website; facts, no licence stated", "source_sha256": sha,
            "language": "my", "high_court_region": rname, "needs_review": True, "record_note": "name/address in Burmese as published; level inferred from the court name"})
    try:
        r = get(f"{host}/judges"); sha = hashlib.sha256(r.content).hexdigest()
        for h3 in re.findall(r'<div class="judge_text[^"]*">\s*<h3>(.*?)</h3>', r.text, re.S):
            full = clean(h3); m = re.search(r"(တရားသူကြီးချုပ်|တရားသူကြီး)\s*(.+)$", full)
            if not m: continue
            tl, name = m.group(1), m.group(2).strip()
            chief = tl == "တရားသူကြီးချုပ်"
            jid = f"mm-hc-{slug}-{hashlib.sha1(name.encode()).hexdigest()[:10]}"
            if jid in oldj or any(x["judge_id"] == jid for x in newj): continue
            newj.append({"judge_id": jid, "court_id": hc_id, "court_name": f"High Court of {rname}", "name": re.sub(r"^(ဦး|ဒေါ်|ဒေါက်တာ)\s*", "", name), "name_local": name,
                "name_as_listed": full, "title": f"Chief Justice of the High Court of {rname}" if chief else f"Judge of the High Court of {rname}", "title_local": tl,
                "position_type": "chief" if chief else "judge", "term_start": None, "term_end": None, "status": "sitting", "jurisdiction": "MM",
                "roster_url": f"{host}/judges", "source_url": f"{host}/judges", "source_kind": "official", "site_policy": pol, "retrieved_at": now,
                "needs_review": True, "extraction": "official High Court 'judges' page headings (title + name; honorific ဦး/ဒေါ် kept in name_local)",
                "license": "official public roster; no licence stated", "source_sha256": sha, "language": "my"})
    except Exception as e: log.append(f"{slug} judges: {str(e)[:60]}")
    print(slug, "locations", len(items), "judges_total_new", len(newj), flush=True)
# make sure each judge's HC court row exists (some HC location lists have no separate High Court entry)
hcids = {x["court_id"] for x in newc} | oldc
miss = sorted({j["court_id"] for j in newj} - hcids)
for cid in miss:
    slug = cid.split("-", 2)[2]; iso, rname = HCS[slug]; host = f"https://{slug}.hc.gov.mm"
    newc.append({"court_id": cid, "record_type": "courthouse", "name": f"High Court of {rname}", "name_local": None, "level": "appellate", "court_system": "national",
        "country_code": "MM", "subdivision": iso, "jurisdiction": rname, "parent_court_id": "mm-high-courts-region-state",
        "address": {"street": None, "city": None, "postcode": None, "region": rname, "country": "MM"}, "geo": {"lat": None, "lon": None}, "geo_source": None,
        "phone": None, "website": host, "wikidata": None, "place_ids": [], "source_url": host + "/judges", "source_kind": "official",
        "site_policy": POL.format(h=f"{slug}.hc.gov.mm", r=rname), "retrieved_at": now, "license": f"High Court of {rname} official website; facts, no licence stated",
        "source_sha256": None, "language": "en", "high_court_region": rname, "needs_review": True,
        "record_note": "High Court row created from the official site (its locations list has no separate High Court entry); address not published there"})
print("courts new", len(newc), "judges new", len(newj), "missing_hc_rows", miss); print("\n".join(log))
if not os.environ.get("DRY"):
    with open(CP, "a") as f:
        for x in newc: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(JP, "a") as f:
        for x in newj: f.write(json.dumps(x, ensure_ascii=False) + "\n")
else:
    json.dump({"c": newc, "j": newj}, open("/tmp/mm/dry.json", "w"), ensure_ascii=False)
