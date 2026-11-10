"""Costa Rica: Poder Judicial official forms from the Phoca Download categories on pj.poder-judicial.go.cr
('Formularios', 'Formularios Importantes', 'Formularios Importantes v2'). robots.txt allows these paths (Crawl-delay 3 respected).
Files saved once as forms/cr/<sha256>.<ext>; rows appended to data/cr/cr_forms.jsonl (dedupe by source_url and sha256).
Note: the same Phoca area also hosts 'Sentencias CIDH' (court decisions) - out of scope, not fetched."""
import json, re, os, html, hashlib, datetime, time, urllib.request
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/cr/cr_forms.jsonl"; FD = f"{ROOT}/forms/cr"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
B = "https://pj.poder-judicial.go.cr"
CATS = ["2-formularios", "3-formularios-importantes", "23-formularios-importantes-v2"]
FAM = re.compile(r"pensi|alimentari|exoneraci|rebajo|salida del pa|apremio|salvaguardia|beneficio", re.I)
def get(u):
    time.sleep(3.5); r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120); return r.read(), r.headers
os.makedirs(FD, exist_ok=True)
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
seen_u = {r["source_url"] for r in old}; seen_s = {r["pdf_sha256"] for r in old}
now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []
for c in CATS:
    idx = f"{B}/index.php/component/phocadownload/category/{c}?Itemid=409"
    t = get(idx)[0].decode("utf-8", "replace")
    for m in re.finditer(r'<div class="pd-title">(.*?)</div>.*?<a class="" href="([^"]+download=[^"]+)"\s*>(.*?)</a>', t, flags=re.S):
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split()); u = B + html.unescape(m.group(2))
        fn = html.unescape(m.group(3)).strip()
        if u in seen_u: continue
        try: b, h = get(u)
        except Exception as ex: print("fail", u, ex); continue
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "bin"
        if b[:4] == b"%PDF": ext = "pdf"
        elif b[:4] == b"\xd0\xcf\x11\xe0": ext = "doc"
        elif b[:2] == b"PK": ext = "docx" if ext not in ("xlsx", "odt") else ext
        else: print("skip non-doc", u, b[:20]); continue
        sha = hashlib.sha256(b).hexdigest(); seen_u.add(u)
        if sha in seen_s: print("dup", title); continue
        seen_s.add(sha); p = f"forms/cr/{sha}.{ext}"; open(f"{ROOT}/{p}", "wb").write(b)
        rows.append({"form_id": f"cr-{sha[:16]}", "court_id": None, "jurisdiction": "CR", "form_number": None, "title": title,
            "category": "family" if FAM.search(title) else "general", "language": "es", "file_format": ext, "pdf_path": p, "pdf_sha256": sha,
            "file_bytes": len(b), "source_url": u, "source_filename": fn, "index_url": idx, "source_kind": "official",
            "site_policy": "robots_allowed (crawl-delay 3 respected)", "license": "Poder Judicial de Costa Rica official form; no licence stated",
            "retrieved_at": now})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows)); [print(" ", r["title"], r["file_format"], r["file_bytes"]) for r in rows]
