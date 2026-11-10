"""Panama: Órgano Judicial official forms for 'Procesos y solicitudes cuyo trámite no requiere la intervención de un abogado'
(www.organojudicial.gob.pa). robots.txt: 'Disallow:' (allow all). Polite 2s delay. Only the downloadable form files (FORMA-*/RUE-* .xls/.xlsx/.ods/.pdf)
are taken; information trípticos/brochures (incl. Guna-language versions) skipped. Files saved as forms/pa/<sha256>.<ext>,
rows appended to data/pa/pa_forms.jsonl (dedupe by source_url and sha256). Titles derived from the official file names."""
import json, re, os, html, hashlib, datetime, time, urllib.request, urllib.parse
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/pa/pa_forms.jsonl"; FD = f"{ROOT}/forms/pa"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
IDX = "https://www.organojudicial.gob.pa/compromiso-no-1-del-segundo-plan-de-accion-nacional-de-gobierno-abierto-2015-2017"
def get(u):
    time.sleep(2); return urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(u, safe=":/?&=%"), headers=UA), timeout=120).read()
os.makedirs(FD, exist_ok=True)
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
seen_u = {r["source_url"] for r in old}; seen_s = {r["pdf_sha256"] for r in old}
t = get(IDX).decode("utf-8", "replace")
links = []
for h in re.findall(r'href="([^"]+)"', t):
    h = html.unescape(h); fn = h.rsplit("/", 1)[-1]
    if re.search(r"\.(xlsx?|ods|pdf|docx?)$", fn, re.I) and re.match(r"(forma|rue-\d)", fn, re.I) and h not in links: links.append(h)
now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []
for u in links:
    if u in seen_u: continue
    try: b = get(u)
    except Exception as ex: print("fail", u, ex); continue
    fn = urllib.parse.unquote(u.rsplit("/", 1)[-1]); stem, ext = fn.rsplit(".", 1); ext = ext.lower()
    sha = hashlib.sha256(b).hexdigest()
    if sha in seen_s: print("dup", fn); continue
    seen_s.add(sha); p = f"forms/pa/{sha}.{ext}"; open(f"{ROOT}/{p}", "wb").write(b)
    m = re.match(r"(?i)forma[- ](?:configurada-)?((?:[A-Z]+-)+\d+)?-?(.*)", stem) or re.match(r"(?i)(rue-\d+)-(.*)", stem)
    code = m.group(1).upper() if m and m.group(1) else None
    rest = (m.group(2) if m else stem)
    rest = re.sub(r"(?i)-?(intranet|modificada)$", "", rest).replace("-", " ").strip()
    title = rest[:1].upper() + rest[1:].lower() if rest.isupper() else rest[:1].upper() + rest[1:]
    if stem.lower() == "forma-sucesion-laboral": code, title = None, "Sucesión laboral"
    cat = "family" if re.search(r"(?i)pensi|matrimonio|menor|salida del pa", title) else "consumer" if "onsumidor" in title else \
          "criminal" if re.search(r"(?i)h[áa]beas corpus", title) else "general"
    rows.append({"form_id": f"pa-{sha[:16]}", "court_id": None, "jurisdiction": "PA", "form_number": code, "title": title, "category": cat,
        "language": "es", "file_format": ext, "pdf_path": p, "pdf_sha256": sha, "file_bytes": len(b), "source_url": u, "source_filename": fn,
        "index_url": IDX, "source_kind": "official", "site_policy": "robots_allowed",
        "license": "Órgano Judicial de Panamá official form; no licence stated", "retrieved_at": now,
        "record_note": "form for proceedings that do not require a lawyer (Órgano Judicial access-to-justice page)"})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("links", len(links), "added", len(rows)); [print(" ", r["form_number"], "|", r["title"], r["file_format"]) for r in rows]
