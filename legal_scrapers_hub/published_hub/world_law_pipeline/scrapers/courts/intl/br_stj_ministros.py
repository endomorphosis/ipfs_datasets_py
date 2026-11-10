"""BR: active ministers of the Superior Tribunal de Justiça from stj.jus.br/web/verMinistrosSTJ?parametro=1 ('Ministros em Atividade', linked from
the official Composição page; robots.txt does not disallow /web/). Full official name + title (Ministro/Ministra; Presidente / Vice-Presidente noted);
birthplace (UF naturalidade) and curriculum NOT stored."""
import json, re, html, datetime, hashlib, os, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
URL = "https://www.stj.jus.br/web/verMinistrosSTJ?parametro=1"; OUT = f"{ROOT}/data/br/br_judges.jsonl"; CID = "br-national-supreme-stj"
now = datetime.datetime.now(datetime.UTC).isoformat()
r = requests.get(URL, headers={"User-Agent": UA}, timeout=60); r.raise_for_status(); sha = hashlib.sha256(r.content).hexdigest()
t = r.content.decode("cp1252", errors="replace"); t = t[t.find("ordem alfab"):] if "ordem alfab" in t else t
recs = {}
for a in re.findall(r'<span class="clsMinistrosNome"><a href="verCurriculoMinistro\?[^"]*">(.*?)</a>', t, re.S):
    txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", a))).strip()
    name, _, role = txt.partition(" - "); recs.setdefault(name.strip(), role.strip())
def slug(s):
    import unicodedata; s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode(); return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; have = {slug(o["name"]) for o in old}; n = 0
with open(OUT, "a") as f:
    for name, role in recs.items():
        if slug(name) in have: continue
        title = "Ministro(a), Superior Tribunal de Justiça" + (f" ({role})" if role.startswith(("Presidente", "Vice-Presidente")) else "")
        f.write(json.dumps({"judge_id": f"br-stj-{slug(name)}", "court_id": CID, "name": name, "title": title,
            "position_type": "chief" if role == "Presidente" else "associate", "term_start": None, "term_end": None, "status": "sitting",
            "roster_url": URL, "source_url": URL, "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": False,
            "extraction": "STJ 'Ministros em Atividade' list (names/titles only)", "license": "Superior Tribunal de Justiça website (facts)",
            "source_sha256": sha}, ensure_ascii=False) + "\n"); n += 1; have.add(slug(name))
print("parsed", len(recs), "added", n)
