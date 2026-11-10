"""Timor-Leste judges (public names + titles only) from the official courts portal www.tribunais.tl:
'Juizes' page (Tribunal de Recurso bench) and the four Tribunal Judicial de Primeira Instância pages (administrator judge).
robots.txt allows (only /wp-admin/ disallowed). Polite 2s delay. Appends to data/tl/tl_judges.jsonl, dedupe by judge_id.
Court rows already exist (tl-court-of-appeal, tl-district-court-*) and are not modified (pages also carry addresses/phones)."""
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/tl/tl_judges.jsonl"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
B = "https://www.tribunais.tl/"
def get(p):
    time.sleep(2); b = urllib.request.urlopen(urllib.request.Request(B + p, headers=UA), timeout=60).read()
    t = b.decode("utf-8", "replace"); i = t.find("You are here")
    x = html.unescape(re.sub(r"<[^>]+>", "\n", t[i:])); return b, [l.strip() for l in x.splitlines() if l.strip()]
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
now = datetime.datetime.now(datetime.UTC).isoformat()
old = {json.loads(l)["judge_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
rows = []
def add(court, name, title, pt, url, raw, note):
    jid = f"{court}-{slug(name)}"
    if jid in old or any(r["judge_id"] == jid for r in rows): return
    rows.append({"judge_id": jid, "court_id": court, "name": name, "title": title, "position_type": pt, "term_start": None, "term_end": None,
        "status": "sitting", "jurisdiction": "TL", "roster_url": B + "juizes/", "source_url": url, "source_kind": "official",
        "site_policy": "robots_allowed|tribunais.tl termos-de-uso", "retrieved_at": now, "needs_review": False,
        "extraction": note, "license": "Tribunais de Timor-Leste official website (facts)", "source_sha256": hashlib.sha256(raw).hexdigest(),
        "language": "pt"})
raw, L = get("juizes/")
for l in L[L.index("Juizes") + 1:]:
    if l == "Go to Top": break
    m = re.match(r"(Dra?\.)\s+(.+?)(?:\s+[–-]\s+(Presidente))?$", l)
    if not m: continue
    pres = bool(m.group(3))
    add("tl-court-of-appeal", m.group(2).strip(), "Presidente do Tribunal de Recurso" if pres else "Juiz(a) do Tribunal de Recurso",
        "chief" if pres else "appellate", B + "juizes/", raw, "official 'Juizes' page, Tribunal de Recurso bench list")
for d in ["dili", "baucau", "suai", "oecusse"]:
    raw, L = get(f"tribunal-distrital-de-{d}/")
    for l in L:
        m = re.match(r"Juiz[a]?\s+Administra\w*\s*:\s*Dra?\.\s*(.+)$", l)
        if m:
            fem = l.startswith("Juiza")
            add(f"tl-district-court-{d}", m.group(1).strip(), "Juíza Administradora" if fem else "Juiz Administrador", "administrator",
                f"{B}tribunal-distrital-de-{d}/", raw, "official Tribunal Judicial de Primeira Instância page (administrator judge)")
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows)); [print(r["court_id"], r["name"], r["title"]) for r in rows]
