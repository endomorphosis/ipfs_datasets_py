"""MX: Consejo de la Judicatura Federal - Dirección General de Archivo y Documentación 'Formatos' (archival forms used by federal
jurisdictional bodies: transfer inventories, destruction/depuración acts, loan voucher, etc.) via Wayback Machine id_ snapshots
(www.cjf.gob.mx unreachable from box). Index: archived transparencia/Uarchivo.htm (2025-07-18). Files only if archived."""
import json, re, html, datetime, hashlib, os, time, requests, urllib.parse
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
IDX = "https://www.cjf.gob.mx/transparencia/uarchivo.htm"; ITS = "20250718192002"
OUT = f"{ROOT}/data/mx/mx_forms.jsonl"; FD = f"{ROOT}/forms/mx"; os.makedirs(FD, exist_ok=True); now = datetime.datetime.now(datetime.UTC).isoformat()
def avail(url):
    q = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
    for k in range(4):
        try: c = requests.get(q, timeout=60, headers={"User-Agent": UA}).json()["archived_snapshots"].get("closest"); time.sleep(2); return c and c["timestamp"]
        except Exception: time.sleep(15 * (k + 1))
t = requests.get(f"https://web.archive.org/web/{ITS}id_/{IDX}", headers={"User-Agent": UA}, timeout=120).text
seg = t[t.find(">Formatos<"):]
links = []
for m in re.finditer(r'<a[^>]+href="(//www\.cjf\.gob\.mx/transparencia/resources/unidad/formatos/[^"]+)"[^>]*>(.*?)</a>', seg, re.S):
    links.append(("https:" + m.group(1), re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", m.group(2)))).strip()))
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; shas = {r["pdf_sha256"] for r in old}; srcs = {r["source_url"] for r in old}
MAG = {b"%PDF": "pdf", b"\xd0\xcf\x11\xe0": "doc", b"PK\x03\x04": None}; n = 0; miss = []
for src, label in links:
    if src in srcs: continue
    ts = avail(src)
    if not ts: miss.append(src.rsplit("/", 1)[1]); continue
    r = requests.get(f"https://web.archive.org/web/{ts}id_/{src}", headers={"User-Agent": UA}, timeout=120); time.sleep(3)
    ext = src.rsplit(".", 1)[1].lower()
    if r.status_code != 200 or not any(r.content.startswith(k) for k in MAG): miss.append(src.rsplit("/", 1)[1]); continue
    sha = hashlib.sha256(r.content).hexdigest()
    if sha in shas: continue
    open(f"{FD}/{sha}.{ext}", "wb").write(r.content)
    fname = src.rsplit("/", 1)[1]; title = label if len(label) > 25 else f"{label} ({fname.rsplit('.',1)[0].replace('_', ' ')})"
    row = {"form_id": f"mx-cjf-{sha[:16]}", "court_id": None, "jurisdiction": "MX", "form_number": None, "title": title,
           "category": "cjf-archivo-formatos", "language": "es", "revision_date": None, "file_format": ext, "pdf_path": f"forms/mx/{sha}.{ext}",
           "pdf_sha256": sha, "file_bytes": len(r.content), "source_url": src, "index_url": IDX,
           "license": "Official CJF document (Mexico: official texts not subject to copyright, LFDA art. 14 VIII)",
           "site_policy": f"archived_copy(wayback:{ts[:8]});origin_unreachable", "retrieved_at": now}
    open(OUT, "a").write(json.dumps(row, ensure_ascii=False) + "\n"); shas.add(sha); srcs.add(src); n += 1
print("links", len(links), "added", n, "missing", miss)
