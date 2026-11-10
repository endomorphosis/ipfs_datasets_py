"""MY: judges of the Court of Appeal and High Courts from kehakiman.gov.my (Malay pages 'Hakim Mahkamah Rayuan' / 'Hakim Mahkamah Tinggi',
paginated ?page=N; robots.txt only disallows Drupal core/profile dirs). Plus the President of the Court of Appeal and the two Chief Judges
from the court overview pages. Names (honorifics YA/Tan Sri/Datuk/Dato' stripped) + official title (incl. station) only; appointment history NOT stored.
3 s delay between requests."""
import json, re, html, datetime, hashlib, os, time, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"; B = "https://www.kehakiman.gov.my/ms/mengenai-kami/mahkamah/"
OUT = f"{ROOT}/data/my/my_judges.jsonl"; now = datetime.datetime.now(datetime.UTC).isoformat()
def toks(t):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=re.S)
    return [y for y in (re.sub(r"\s+", " ", html.unescape(z)).strip() for z in re.sub(r"<[^>]+>", "\n", t).split("\n")) if y]
HON = re.compile(r"^(?:YAA|YA)?\s*(?:(?:Tan Sri|Puan Sri|Datuk Seri|Puan|Tuan|Dato['’] Sri|Dato['’] Seri|Datuk|Dato['’]|Dr\.?)\s+)*", re.I)
def clean(n): return HON.sub("", n.replace("’", "'")).strip()
def get(u):
    r = requests.get(u, headers={"User-Agent": UA}, timeout=60); time.sleep(3); return r
recs = []  # (name, title, court_id, url, sha)
for path, cid, label in [("mahkamah-rayuan/hakim-mahkamah-rayuan", "my-court-of-appeal", "Hakim Mahkamah Rayuan"),
                         ("mahkamah-tinggi/hakim-mahkamah-tinggi", "my-high-court", "Hakim Mahkamah Tinggi")]:
    seen = set()
    for p in range(0, 30):
        u = B + path + (f"?page={p}" if p else ""); r = get(u)
        if r.status_code != 200: break
        x = toks(r.text); new = 0
        for i, y in enumerate(x):
            if y.startswith("YA ") and i + 1 < len(x) and x[i + 1].startswith(label):
                n = clean(y)
                if n in seen: continue
                seen.add(n); new += 1; recs.append((n, x[i + 1], cid, B + path, hashlib.sha256(r.content).hexdigest()))
        if not new: break
for path, cid, role in [("mahkamah-rayuan", "my-court-of-appeal", "Presiden Mahkamah Rayuan"), ("mahkamah-tinggi", "my-high-court", "Hakim Besar Malaya"),
                        ("mahkamah-tinggi", "my-high-court", "Hakim Besar Sabah Dan Sarawak")]:
    r = get(B + path); x = toks(r.text)
    for i, y in enumerate(x[:-1]):
        if x[i + 1] == role and re.match(r"^(Tan Sri|Datuk|Dato)", y): recs.append((clean(y), role, cid, B + path, hashlib.sha256(r.content).hexdigest())); break
        # layout 2 (CoA page, 2026): role / 'Yang Amat Arif' / name
        if y == role and i + 2 < len(x) and x[i + 1].startswith("Yang Amat") and re.match(r"^(Tan Sri|Datuk|Dato)", x[i + 2]):
            recs.append((clean(x[i + 2]), role, cid, B + path, hashlib.sha256(r.content).hexdigest())); break
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; have = {slug(o["name"]) for o in old}; n = 0
with open(OUT, "a") as f:
    for name, title, cid, url, sha in recs:
        if slug(name) in have: continue
        f.write(json.dumps({"judge_id": f"{cid}-{slug(name)}", "court_id": cid, "name": name, "title": title,
            "position_type": "chief" if title.startswith(("Presiden", "Hakim Besar")) else "associate", "term_start": None, "term_end": None,
            "status": "sitting", "roster_url": url, "source_url": url, "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": False,
            "extraction": "kehakiman.gov.my judges list (names/official titles only; honorifics stripped)", "license": "Pejabat Ketua Pendaftar Mahkamah Persekutuan Malaysia website (facts)",
            "source_sha256": sha}, ensure_ascii=False) + "\n"); n += 1; have.add(slug(name))
print("parsed", len(recs), "added", n)
