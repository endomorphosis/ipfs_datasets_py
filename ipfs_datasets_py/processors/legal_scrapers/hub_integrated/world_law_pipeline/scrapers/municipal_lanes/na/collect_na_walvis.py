#!/usr/bin/env python3
"""Collect Walvis Bay municipal regulations (Local Authorities Act 1992) from walvisbaycc.org.na."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import os, sys, json, time, hashlib, re, subprocess
from datetime import datetime, timezone
from urllib.parse import urlsplit, urljoin, unquote
from html.parser import HTMLParser
from pathlib import Path
from html import unescape

STAGE = Path("/dev/shm/muni_africa/na")
os.environ["LEGAL_CORPORA_ROOT"] = str(STAGE / "root")
sys.path.insert(0, _ipfs_os.path.dirname(_ipfs_os.path.abspath(__file__)))
import robots_guard as rg
import requests

RAW = STAGE / "raw" / "walvis"
LOG = STAGE / "logs" / "walvis_requests.jsonl"
PRIOR_LOGS = [
  "/dev/shm/muni_africa/next_probe/probe3_requests.jsonl",
  str(LOG),
]
RECORDS = STAGE / "records.jsonl"
EXCL = STAGE / "listing_exclusions.jsonl"
FLOOR = 5.0
HOST = "walvisbaycc.org.na"
CHAL = re.compile(
    r"<title[^>]*>\s*(?:Just a moment|Attention Required|Access denied|Please wait|One more step|DDoS protection|Request Rejected)|"
    r"_cf_chl_opt|cf-browser-verification|/cdn-cgi/challenge-platform|cf-turnstile|checking your browser|"
    r"Checking if the site connection is secure|Enable JavaScript and cookies to continue|/cdn-cgi/challenge|"
    r"sgcaptcha|ddos-guard|__ddg|_Incapsula_Resource|incapsula|px-captcha|perimeterx|datadome|awswaf|"
    r"The requested URL was rejected", re.I)
DOC_RE = re.compile(r"\.(?:pdf)(?:$|\?)", re.I)

RAW.mkdir(parents=True, exist_ok=True)
(STAGE/"logs").mkdir(parents=True, exist_ok=True)
(STAGE/"ocr").mkdir(parents=True, exist_ok=True)

def fam(h): return re.sub(r"^www\.", "", (h or "").lower())
def now(): return time.time()
def iso(t=None):
  t = t or now()
  return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")

def last_send(f):
  best = 0.0
  for p in PRIOR_LOGS:
    if not os.path.exists(p): continue
    for l in open(p):
      try: r = json.loads(l)
      except Exception: continue
      if fam(urlsplit(r.get("url","")).hostname) != f: continue
      v = r.get("sent_at")
      if isinstance(v, str):
        try: best = max(best, datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
        except Exception: pass
  return best

CD = {}; STOP = {}; SENDS = {}
class Stop(Exception): pass

def mem_gib():
  with open("/proc/meminfo") as f:
    for line in f:
      if line.startswith("MemAvailable:"):
        return int(line.split()[1])/1024/1024
  return 99.0

def mem_guard():
  if mem_gib() >= 3.0: return
  t0 = time.time()
  while time.time() - t0 < 15:
    time.sleep(2)
    if mem_gib() >= 3.0: return
  raise Stop(f"MemAvailable {mem_gib():.2f} < 3 GiB for 15s")

def pace(url):
  mem_guard()
  f = fam(urlsplit(url).hostname)
  if STOP.get(f): raise Stop(STOP[f])
  need = max(FLOOR, CD.get(f, 0.0))
  t0 = last_send(f)
  wait = t0 + need - now()
  if wait > 0: time.sleep(wait + 0.05)
  t = now()
  SENDS[f] = SENDS.get(f, 0) + 1
  open("/dev/shm/muni_africa/status_na_b1.txt","w").write(
    f"status=COLLECTING sends={dict(SENDS)} mem={mem_gib():.2f} t={time.strftime('%H:%M:%S')}\n")
  return t, (t - t0 if t0 else None), need

def log(row):
  open(LOG, "a").write(json.dumps(row, ensure_ascii=False) + "\n")
  print(json.dumps(row, ensure_ascii=False)[:380], flush=True)

def chk(r, body):
  sig = []
  if r.status_code in (403,429,503): sig.append(f"http_{r.status_code}")
  if r.headers.get("cf-mitigated"): sig.append("cf-mitigated")
  if any(k.lower().startswith("cf-chl") for k in r.headers): sig.append("cf-chl")
  txt = body[:200000].decode("utf-8","replace") if body else ""
  if "<html" in txt[:4000].lower() or "<!doctype" in txt[:400].lower():
    m = CHAL.search(txt)
    if m: sig.append("challenge:"+m.group(0)[:40])
  return sig

def robots_fetch(robots_url):
  t, gap, need = pace(robots_url)
  url = robots_url; hops=[]; r=None; body=b""
  try:
    for _ in range(4):
      r = requests.get(url, timeout=(15,30), allow_redirects=False, verify=rg.ca_verify_for(url),
                       headers={"User-Agent": rg.ROBOTS_UA, "Accept":"text/plain,*/*"}, stream=True)
      body = r.raw.read(rg.MAX_ROBOTS_BYTES, decode_content=True); r.close()
      hops.append(r.status_code)
      loc = r.headers.get("Location")
      if r.status_code in (301,302,303,307,308) and loc:
        nxt = urljoin(url, loc)
        if fam(urlsplit(nxt).hostname) != fam(urlsplit(robots_url).hostname): break
        url = nxt; continue
      break
    sig = chk(r, body)
    log({"sent_at": iso(t), "url": robots_url, "kind":"robots_txt", "status": r.status_code, "hops": hops,
         "gap_s": round(gap,2) if gap else None, "required_gap_s": need, "signals": sig})
    if sig:
      STOP[fam(urlsplit(robots_url).hostname)] = f"challenge robots {sig}"
      return 0, "", "challenge"
    try: txt = body.decode("utf-8-sig")
    except: txt = body.decode("latin-1","replace")
    return r.status_code, txt, ""
  except Stop: raise
  except Exception as e:
    log({"sent_at": iso(t), "url": robots_url, "kind":"robots_txt", "error": f"{type(e).__name__}: {e}"[:300]})
    return 0, "", str(e)[:300]

rg._robots_fetcher = robots_fetch

class Links(HTMLParser):
  def __init__(self, base):
    super().__init__(); self.base=base; self.links=[]; self._h=None; self._t=[]
  def handle_starttag(self, tag, attrs):
    ad=dict(attrs)
    if tag=="a" and "href" in ad: self._h=ad["href"]; self._t=[]
  def handle_data(self, d):
    if self._h is not None: self._t.append(d)
  def handle_endtag(self, tag):
    if tag=="a" and self._h is not None:
      self.links.append((urljoin(self.base,self._h), " ".join(self._t).strip())); self._h=None; self._t=[]

def get(url, kind="page"):
  cur = url
  for _ in range(6):
    d = rg.check(cur)
    f = fam(urlsplit(cur).hostname)
    if d.crawl_delay: CD[f] = max(CD.get(f,0.0), float(d.crawl_delay))
    if not d.allowed:
      log({"url": cur, "kind": kind, "skipped": "robots "+d.reason}); return None
    if f != HOST:
      log({"url": cur, "kind": kind, "skipped": "off-host"}); return None
    t, gap, need = pace(cur)
    try:
      r = requests.get(cur, timeout=(20,120), allow_redirects=False, verify=rg.ca_verify_for(cur), stream=True,
                       headers={"User-Agent": rg.ROBOTS_UA, "Accept":"text/html,application/xhtml+xml,application/pdf,*/*"})
      body = b""
      for ch in r.iter_content(65536):
        body += ch
        if len(body) > 25_000_000: break
      r.close()
    except Exception as e:
      log({"sent_at": iso(t), "url": cur, "kind": kind, "error": f"{type(e).__name__}: {e}"[:300]}); return None
    sig = chk(r, body)
    row = {"sent_at": iso(t), "url": cur, "kind": kind, "status": r.status_code, "ctype": r.headers.get("Content-Type"),
           "bytes": len(body), "gap_s": round(gap,2) if gap else None, "required_gap_s": need, "signals": sig, "robots": d.reason}
    loc = r.headers.get("Location")
    if r.status_code in (301,302,303,307,308) and loc:
      nxt = urljoin(cur, loc); row["redirect_to"] = nxt; log(row)
      if fam(urlsplit(nxt).hostname) != HOST:
        log({"url": nxt, "kind": kind, "skipped": "off-host redirect"}); return None
      cur = nxt; continue
    log(row)
    if sig:
      STOP[f] = f"HARD STOP {sig}"; raise Stop(STOP[f])
    return {"url": cur, "status": r.status_code, "ctype": r.headers.get("Content-Type") or "", "body": body}
  return None

def classify(url, text):
  name = unquote(urlsplit(url).path.rsplit("/",1)[-1]).lower()
  blob = (name + " " + (text or "")).lower()
  # Exclude policies, drafts, forms, maps, checklists, reports
  if re.search(r'(policy|draft|form|checklist|consent|map|tourism.?forum|corruption|application)', blob):
    return False, "policy_draft_or_form", "Policy/draft/form/map/report — excluded"
  # Include regulations under Local Authorities Act
  if re.search(r'regulat', blob) and re.search(r'(waste|hazardous|early.?child|public.?amenit|local.?authorit)', blob):
    return True, "regulation", "Municipal regulation under Local Authorities Act 1992"
  if re.search(r'regulat', name):
    # other regulations on this page
    return True, "regulation", "Municipal regulation (filename)"
  return False, "other", "Not a Local Authorities Act regulation"

def extract_pdfs(html, base):
  try:
    p = Links(base); p.feed(html[:3_000_000]); links = p.links
  except Exception:
    links = []
  out=[]; seen=set()
  for href, text in links:
    if fam(urlsplit(href).hostname) not in ("", HOST):
      continue
    if DOC_RE.search(href) or DOC_RE.search(text or ""):
      if href not in seen:
        seen.add(href); out.append({"url": href, "text": unescape(text or "")})
  for m in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
    u = urljoin(base, m.group(1))
    if fam(urlsplit(u).hostname) == HOST and u not in seen:
      seen.add(u); out.append({"url": u, "text": ""})
  return out

def pdf_n_pages(path):
  try:
    out = subprocess.check_output(["pdfinfo", str(path)], stderr=subprocess.DEVNULL).decode()
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else 0
  except Exception:
    return 0

def page_chars(path, page):
  try:
    t = subprocess.check_output(["pdftotext", "-f", str(page), "-l", str(page), "-enc", "UTF-8", str(path), "-"],
                                stderr=subprocess.DEVNULL).decode("utf-8","replace")
    return len(re.sub(r"\s+","", t)), t
  except Exception:
    return 0, ""

def ocr_page(path, page, dpi=250):
  stem = f"{path.stem}_p{page}"
  prefix = STAGE / "ocr" / stem
  for oldp in (STAGE/"ocr").glob(f"{stem}*.png"):
    try: oldp.unlink()
    except: pass
  subprocess.check_call(["pdftoppm", "-f", str(page), "-l", str(page), "-png", "-r", str(dpi), "-singlefile", str(path), str(prefix)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  cand = STAGE / "ocr" / f"{stem}.png"
  if not cand.exists():
    cands=sorted((STAGE/"ocr").glob(f"{stem}*.png"))
    if not cands: raise FileNotFoundError(f"no png for {path} p{page}")
    cand = cands[0]
  outbase = STAGE / "ocr" / stem
  err = subprocess.run(["tesseract", str(cand), str(outbase), "-l", "eng", "--psm", "6", "tsv", "txt"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        env={**os.environ, "OMP_THREAD_LIMIT":"1"})
  if err.returncode != 0:
    raise RuntimeError(err.stderr[:200])
  lines = open(outbase.with_suffix(".tsv"), encoding="utf-8", errors="replace").read().splitlines()
  confs=[]; words=[]
  for i, line in enumerate(lines):
    if i==0: continue
    parts = line.split("\t")
    if len(parts) < 12: continue
    try: conf = float(parts[10])
    except: continue
    w = parts[11]
    if conf >= 0 and w.strip():
      confs.append(conf); words.append((w, conf))
  mean = sum(confs)/len(confs) if confs else 0.0
  text = " ".join(("[illegible]" if c < 50 else w) for w,c in words)
  try: cand.unlink()
  except: pass
  return mean, text

def extract_text(path):
  n = pdf_n_pages(path)
  page_meta=[]; parts=[]; used_ocr=False
  for p in range(1, max(n,1)+1):
    chars, t = page_chars(path, p)
    if chars >= 40:
      parts.append(t); page_meta.append({"page":p,"backend":"pdftotext","chars":chars})
    else:
      used_ocr=True
      mean, ot = ocr_page(path, p)
      parts.append(ot)
      page_meta.append({"page":p,"backend":"ocr_eng","chars":len(ot),"mean_conf":mean})
  text = "\n\n".join(parts)
  if used_ocr:
    all_conf = [100.0 if pm["backend"]=="pdftotext" else (pm.get("mean_conf") or 0) for pm in page_meta]
    doc_conf = sum(all_conf)/len(all_conf)
    degraded = doc_conf < 80.0
    backend = "mixed_pdftotext_ocr_eng" if any(pm["backend"]=="pdftotext" for pm in page_meta) else "ocr_eng"
  else:
    doc_conf = 100.0; degraded = False; backend = "pdftotext"
  if degraded and "[illegible]" not in text:
    text += "\n\n[illegible]"
  return text, backend, doc_conf, degraded, page_meta, n

def main():
  if EXCL.exists(): EXCL.unlink()
  if RECORDS.exists(): RECORDS.unlink()
  rg.set_country("na")
  listing_url = "https://www.walvisbaycc.org.na/?page_id=1235"
  res = get(listing_url, "listing")
  if not res or res["status"] != 200:
    raise SystemExit(f"listing failed: {res}")
  html = res["body"].decode("utf-8","replace")
  (RAW/"listing_policies.html").write_bytes(res["body"])
  pdfs = extract_pdfs(html, res["url"])
  print("FOUND", len(pdfs), flush=True)
  selected=[]; excluded=[]
  for item in pdfs:
    ok, kind, reason = classify(item["url"], item.get("text"))
    if ok:
      selected.append({**item, "kind": kind, "reason": reason})
    else:
      excluded.append(item)
      open(EXCL,"a").write(json.dumps({"url":item["url"],"text":item.get("text"),"kind":kind,"reason":reason}, ensure_ascii=False)+"\n")
  seen=set(); uniq=[]
  for s in selected:
    if s["url"] in seen: continue
    seen.add(s["url"]); uniq.append(s)
  selected=uniq
  print("SELECTED", len(selected), "EXCLUDED", len(excluded), flush=True)
  for s in selected:
    print(" +", s["url"].rsplit("/",1)[-1][:90], flush=True)

  for s in selected:
    mem_guard()
    r = get(s["url"], "doc")
    if not r or r["status"] != 200:
      open(EXCL,"a").write(json.dumps({"url":s["url"],"reason":"fetch_failed"}, ensure_ascii=False)+"\n")
      continue
    if not r["body"].startswith(b"%PDF"):
      open(EXCL,"a").write(json.dumps({"url":s["url"],"reason":"not_pdf"}, ensure_ascii=False)+"\n")
      continue
    fname = unquote(urlsplit(s["url"]).path.rsplit("/",1)[-1])
    safe = re.sub(r'[^A-Za-z0-9._\-]+','_', fname)[:120]
    path = RAW / safe
    path.write_bytes(r["body"])
    sha = hashlib.sha256(r["body"]).hexdigest()
    text, backend, conf, degraded, page_meta, nPages = extract_text(path)
    # maker hint: must look like regulation
    if not re.search(r'(?i)regulat', text[:3000]+fname):
      open(EXCL,"a").write(json.dumps({"url":s["url"],"reason":"content_not_regulation","sha":sha}, ensure_ascii=False)+"\n")
      print("DROP not regulation content", safe, flush=True)
      continue
    rec = {
      "source_url": s["url"], "source_page": listing_url, "listing_title": s.get("text") or fname,
      "instrument_kind": s["kind"], "classify_reason": s["reason"],
      "local_path": str(path), "pdf_bytes": len(r["body"]), "pdf_sha256": sha,
      "pages": nPages, "text": text, "text_backend": backend,
      "ocr_mean_conf": conf, "ocr_degraded": degraded, "ocr_pages": page_meta,
      "retrieved_at": iso(),
    }
    open(RECORDS,"a").write(json.dumps(rec, ensure_ascii=False)+"\n")
    print(f"REC {safe} pages={nPages} backend={backend} conf={conf:.1f} deg={degraded}", flush=True)
    for p in (STAGE/"ocr").glob("*.png"):
      try: p.unlink()
      except: pass

  print("DONE sends", dict(SENDS), "records", sum(1 for _ in open(RECORDS)) if RECORDS.exists() else 0, flush=True)
  open("/dev/shm/muni_africa/status_na_b1.txt","w").write(
    f"status=COLLECTED sends={dict(SENDS)} mem={mem_gib():.2f} t={time.strftime('%H:%M:%S')}\n")

if __name__ == "__main__":
  main()
