"""VN: TANDTC (toaan.gov.vn) 'Biểu mẫu tố tụng' procedural forms (civil forms = annex of Nghị quyết 01/2017/NQ-HĐTP; administrative = NQ 02/2017;
criminal = NQ 05/2017) via Wayback Machine id_ snapshots only. toaan.gov.vn unreachable from box; vbpl.vn NOT used (WAF).
Wayback CDX API was offline, so only listing pages / files findable via the availability API are used."""
import json, re, html, datetime, hashlib, os, sys, time, requests, urllib.parse
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
OUT = f"{ROOT}/data/vn/vn_forms.jsonl"; FD = f"{ROOT}/forms/vn"; os.makedirs(FD, exist_ok=True)
now = datetime.datetime.now(datetime.UTC).isoformat(); B = "https://www.toaan.gov.vn/webcenter/portal/tatc/"
def avail(url):
    # fallback when availability API is down: follow raw redirect and read timestamp from final URL
    for y in ("2020", "2018", "2023"):
        try:
            try: r = requests.head(f"https://web.archive.org/web/{y}id_/{url}", timeout=60, allow_redirects=True, headers={"User-Agent": UA})
            except requests.exceptions.SSLError: r = _curl(f"https://web.archive.org/web/{y}id_/{url}", head=True)
            time.sleep(3)
            m = re.search(r"/web/(\d{14})id_/", r.url)
            if r.status_code == 200 and m: return m.group(1)
        except Exception as e: print("raw err", str(e)[:60])
    return avail_api(url)
def avail_api(url):
    q = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
    for k in range(4):
        try: c = requests.get(q, timeout=60, headers={"User-Agent": UA}).json()["archived_snapshots"].get("closest"); time.sleep(3); return c and c["timestamp"]
        except Exception as e: print("avail err", url[-30:], str(e)[:60]); time.sleep(20 * (k + 1))
class _R:  # minimal response wrapper for the curl fallback
    def __init__(s, code, content, url): s.status_code, s.content, s.url = code, content, url; s.text = content.decode("utf-8", "replace")
def _curl(u, head=False):
    # python-requests hits TLS EOF errors on web.archive.org from this box while curl works; same request, same UA
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile() as f:
        cmd = ["curl", "-s", "-L", "-m", "120", "-A", UA, "-o", f.name, "-w", "%{http_code} %{url_effective}", u]
        if head: cmd[1:1] = ["-I"]
        o = subprocess.run(cmd, capture_output=True, text=True).stdout.split(" ", 1); time.sleep(3)
        return _R(int(o[0] or 0), open(f.name, "rb").read(), o[1] if len(o) > 1 else u)
def get(url, ts):
    try: r = requests.get(f"https://web.archive.org/web/{ts}id_/{url}", timeout=120, headers={"User-Agent": UA})
    except requests.exceptions.SSLError: r = _curl(f"https://web.archive.org/web/{ts}id_/{url}")
    time.sleep(3); return r
LV = {"45": "to-tung-dan-su", "46": "to-tung-hinh-su", "47": "to-tung-hanh-chinh"}
NQ = {"45": "NQ 01/2017/NQ-HĐTP (civil procedure forms)", "46": "NQ 05/2017/NQ-HĐTP (criminal procedure forms)", "47": "NQ 02/2017/NQ-HĐTP (administrative procedure forms)"}
lists = [(f"{B}bieu-mau-to-tung?linhVuc={lv}", lv) for lv in LV] + [(f"{B}bieu-mau-to-tung?selectedPage={p}&docType=BieuMau&linhVuc={lv}", lv) for lv in LV for p in range(8)]
CACHE = "/tmp/vn_forms_docs.json"; docs = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
for u, lv in ([] if docs else lists):
    ts = avail(u)
    if not ts: continue
    t = get(u, ts).text
    for m in re.finditer(r'chi-tiet-bieu-mau\?dDocName=(\w+)"[^>]*>(.*?)</a>', t, re.S):
        docs.setdefault(m.group(1), (re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", m.group(2)))).strip(), lv, u, ts))
json.dump(docs, open(CACHE, "w"), ensure_ascii=False); print("listed docs", len(docs))
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; shas = {r["pdf_sha256"] for r in old}; srcs = {r["source_url"] for r in old}
EXT = {b"%PDF": "pdf", b"\xd0\xcf\x11\xe0": "doc", b"PK\x03\x04": "docx"}; n = 0; miss = []
for did, (title, lv, lu, lts) in docs.items():
    src = f"https://www.toaan.gov.vn/webcenter/ShowProperty?nodeId=/UCMServer/{did}"
    if src in srcs: continue
    ts = avail(src)
    if not ts: miss.append(did); print("no snapshot", did); continue
    r = get(src, ts); ext = next((e for k, e in EXT.items() if r.content.startswith(k)), None)
    if r.status_code != 200 or not ext: miss.append(did); continue
    sha = hashlib.sha256(r.content).hexdigest()
    if sha in shas: continue
    open(f"{FD}/{sha}.{ext}", "wb").write(r.content)
    fn = re.match(r"^M[ẫâ]u(?: số)?\s*([0-9]+[a-zđ]?\s*-?\s*[A-Z]{2})", title)
    row = {"form_id": f"vn-{sha[:16]}", "court_id": None, "jurisdiction": "VN", "form_number": fn.group(1).replace(" ", "") if fn else None,
           "title": title, "category": LV[lv], "language": "vi", "revision_date": None, "file_format": ext, "pdf_path": f"forms/vn/{sha}.{ext}",
           "pdf_sha256": sha, "file_bytes": len(r.content), "source_url": src, "index_url": lu, "legal_basis": NQ[lv],
           "license": "Official court form (Vietnam: legal normative documents & official forms not protected by copyright, Law on IP art. 15)",
           "site_policy": f"archived_copy(wayback:{ts[:8]});origin_unreachable", "retrieved_at": now}
    open(OUT, "a").write(json.dumps(row, ensure_ascii=False) + "\n"); shas.add(sha); srcs.add(src); n += 1
print("added", n, "not_archived", len(miss))
