"""RU municipal NPA from Gosweb municipal sites (<name>.gosuslugi.ru, uniform 'Документы' section). Live, robots-respecting,
direct connection only (no proxy/VPN). Usage: ru_gosweb.py --hosts-file F (jsonl: host, place_id, place_name) [--per-place N] [--stage]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, re, json, html as H, time, os, subprocess, tempfile, zipfile, argparse, hashlib
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import validate_record, validate_file, place_key
from rfc9309 import Robots
UA = "Mozilla/5.0 (compatible; WorldLawMunicipalResearch/1.0)"
DELAY = 2.0
S = requests.Session(); S.headers["User-Agent"] = UA
def get(url, rb, **kw):
    if not rb.can_fetch(UA, url): return None
    time.sleep(max(DELAY, rb.crawl_delay(UA) or 0))
    try: return S.get(url, timeout=(10, 60), **kw)
    except Exception: return None
def to_text(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h); h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    t = H.unescape(re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ")
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())
def extract(content, ext):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f." + ext); open(p, "wb").write(content)
        if ext == "pdf":
            return subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, timeout=120).stdout, "pdf_text"
        if ext == "docx":
            x = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8", "replace")
            x = re.sub(r"</w:p>", "\n", x); return H.unescape(re.sub(r"<[^>]+>", "", x)), "docx_text"
        if ext in ("doc", "rtf", "odt"):
            subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text (encoded):UTF8", "--outdir", d, p], capture_output=True, timeout=180)
            q = os.path.join(d, "f.txt"); return (open(q, encoding="utf-8", errors="replace").read() if os.path.exists(q) else ""), "docx_text"
    return "", None
RU_MON = None
EXCLUDE = re.compile(r"проект|\bплан\b|план[ау]? |схем[аы]|карт[аы]|карт-план|отч[её]т|информаци|извещени|объявлени|сообщени|протокол|заключени", re.I)
TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", ["a","b","v","g","d","e","e","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","kh","ts","ch","sh","shch","","y","","e","yu","ya"]))
def translit(t): return "".join(TR.get(c, c) for c in t.lower())
STOP = {"urban","rural","okrug","district","settlement","municipal","city","town","of","the","formation","resort","posyolok","selo","sp","municipality","village","raion","rayon"}
def norm(w): return re.sub(r"[^a-z]", "", w.lower().replace("yo","e").replace("kh","h").replace("y","i").replace("j","i"))
def name_ok(site_title, place_name):
    tt = norm(translit(site_title))
    keys = [norm(w) for w in re.split(r"[\s\-]+", place_name or "") if norm(w) and w.lower() not in STOP]
    return bool(keys) and all(k[:max(4, len(k) - 3)] in tt for k in keys[:1])
def parse_title(t):
    kind = re.search(r"(Решени[ея]|Постановлени[ея]|Распоряжени[ея]|Устав|Приказ|Положени[ея]|Правил[аo])", t, re.I)
    d = re.search(r"от\s+(\d{2})\.(\d{2})\.(\d{4})", t); n = re.search(r"№\s*([0-9A-Za-zА-Яа-я\-/]+)", t)
    return ((kind.group(1)[:5].capitalize() if kind else None), f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None, n.group(1) if n else None)
def scrape_host(host, place_id, name, per_place, now, verify_name=False):
    base = f"https://{host}"
    rr = S.get(base + "/robots.txt", timeout=(10, 30))
    if rr.status_code == 200: rb, pol = Robots(rr.text), "robots_allowed_rfc9309"
    elif 400 <= rr.status_code < 500: rb, pol = Robots(allow_all=True), "robots_404_allow_rfc9309"
    else: return [], "robots_unreachable"
    if verify_name:
        hp = get(base + "/", rb)
        if not hp or hp.status_code != 200: return [], "home_unreachable"
        tm = re.search(r"<title>(.*?)</title>", hp.text, re.S); hm = re.search(r'<a[^>]*navbar-brand[^>]*>(.*?)</a>|class="gw-header[^"]*title[^"]*"[^>]*>(.*?)<', hp.text, re.S)
        st = " ".join(x for x in [tm.group(1) if tm else "", hm.group(0) if hm else ""])
        st = re.sub(r"<[^>]+>", " ", H.unescape(st))
        if not name_ok(st, name): return [], "name_mismatch: " + re.sub(r"\s+", " ", st)[:120]
    r = get(base + "/ofitsialno/dokumenty/", rb)
    if not r or r.status_code != 200: return [], f"no_docs_section {r.status_code if r else None}"
    ITEM = r'href="(/ofitsialno/dokumenty/[^"?#]+?_\d+\.html)"'
    SUB = r'href="(/ofitsialno/dokumenty/[^"?#.]+/)"'
    pri = lambda u: 0 if re.search(r"resh|sovet|duma|dep|npa", u, re.I) else 1 if re.search(r"post|pago", u, re.I) else 2
    items, seen, queue = list(re.findall(ITEM, r.text)), {"/ofitsialno/dokumenty/"}, sorted(set(re.findall(SUB, r.text)), key=pri)
    pages = 0
    while queue and pages < 8 and len(items) < per_place * 15:
        sub = queue.pop(0)
        if sub in seen: continue
        seen.add(sub); rs = get(base + sub, rb); pages += 1
        if not rs or rs.status_code != 200: continue
        items += re.findall(ITEM, rs.text)
        queue = sorted(set(queue) | (set(re.findall(SUB, rs.text)) - seen), key=pri)
    items = [(u, "") for u in sorted(set(items), key=lambda u: -int(re.search(r"_(\d+)\.html$", u).group(1)))]
    items = list(dict.fromkeys(items)); recs = []
    for u, t in items:
        if len(recs) >= per_place: break
        rd = get(base + u, rb)
        if not rd or rd.status_code != 200: continue
        m = re.search(r'gw-document-page__title">(.*?)</h1>', rd.text, re.S)
        title = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip() if m else t
        files = list(dict.fromkeys(re.findall(r'href="(/netcat_files/[^"]+\.(?:pdf|docx|doc|rtf|odt))"', rd.text, re.I)))
        text, fmt, furl = "", None, None
        for f in files[:2]:
            rf = get(base + f, rb)
            if not rf or rf.status_code != 200 or len(rf.content) > 30_000_000: continue
            try: text, fmt = extract(rf.content, f.rsplit(".", 1)[1].lower())
            except Exception: text = ""
            if len(text.strip()) >= 200: furl = base + f; break
        if len(text.strip()) < 200: continue
        kind, dt, num = parse_title(title)
        if not kind or kind not in ("Решен", "Поста", "Устав") or EXCLUDE.search(title): continue
        pub = re.search(r"Опубликовано\s*</[^>]+>\s*<[^>]+>\s*(\d{2})\.(\d{2})\.(\d{4})", rd.text)
        did = re.search(r"_(\d+)\.html$", u).group(1)
        rec = {"place_id": place_id, "country_code": "RU", "doc_id": f"gosweb:{host}:{did}", "source_platform": "ru_gosweb",
               "source_url": base + u, "doc_type": {"Решение": "decision", "Постановление": "regulation", "Распоряжение": "decision",
               "Устав": "statute", "Приказ": "decision", "Положение": "regulation", "Правила": "regulation"}.get({"Решен":"Решение","Поста":"Постановление","Распо":"Распоряжение","Устав":"Устав","Прика":"Приказ","Полож":"Положение","Прави":"Правила"}.get(kind), "decision"), "language": "ru", "title_native": title[:1000],
               "number": num, "adopted_date": dt, "published_date": f"{pub.group(3)}-{pub.group(2)}-{pub.group(1)}" if pub else None,
               "in_force": None, "consolidated": False, "content_format": fmt, "text": text, "retrieved_at": now,
               "source_policy": pol, "source_official": True, "file_url": furl, "place_name": name,
               "qid": place_id[3:] if place_id.startswith("wd:") else None, "admin_level": "municipality", "platform": "ru_gosweb",
               "platform_place_id": host}
        if not validate_record(rec): recs.append(rec)
    return recs, "ok"
def stage(recs, cc, pid):
    d = f"/workspace/world_law/staging/sasia_ru/{cc}"; os.makedirs(d, exist_ok=True)
    final = f"{d}/{place_key(pid)}.full.gosweb{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}p0001.jsonl"
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    chk = f"{d}/.{os.path.basename(final)}.check.jsonl"; os.link(tmp, chk)
    try: res = validate_file(chk, expect_place_key=place_key(pid))
    finally: os.unlink(chk)
    if not res["ok"]:
        os.makedirs((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_rejects"), exist_ok=True)
        os.replace(tmp, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_rejects/") + os.path.basename(final)); return None
    os.rename(tmp, final); return final
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--hosts-file", required=True); ap.add_argument("--per-place", type=int, default=3)
    ap.add_argument("--stage", action="store_true"); ap.add_argument("--max-places", type=int, default=20); a = ap.parse_args()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); n_ok = 0
    for line in open(a.hosts_file):
        if n_ok >= a.max_places: break
        h = json.loads(line)
        try: recs, st = scrape_host(h["host"], h["place_id"], h.get("place_name"), a.per_place, now, verify_name=h.get("verify", True))
        except Exception as e: recs, st = [], f"error {type(e).__name__}"
        out = stage(recs, "RU", h["place_id"]) if (a.stage and recs) else None
        print(json.dumps({"host": h["host"], "place_id": h["place_id"], "docs": len(recs), "status": st, "staged": out}, ensure_ascii=False), flush=True)
        if recs: n_ok += 1
