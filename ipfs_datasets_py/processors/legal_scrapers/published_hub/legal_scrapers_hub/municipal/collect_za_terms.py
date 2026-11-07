"""Record each source host's stated terms (terms of use / disclaimer / copyright page) for the README and row licence field.
For every host that yielded documents (munisites/*.docs.jsonl) plus openbylaws.org.za: look for a terms / disclaimer /
copyright / legal link on the (cached) home page, fetch up to 2 such pages politely, keep the sentences that mention
copyright / reproduction / permission / rights. Writes <STATE>/terms/terms.json {host: {url, summary, sentences}}."""
import os, sys, re, json, glob, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import za_common as zc
from bs4 import BeautifulSoup
import warnings; warnings.filterwarnings("ignore")
STATE = os.environ.get("ZA_STATE", "za_build_state")
os.makedirs(os.path.join(STATE, "terms"), exist_ok=True)
fn = os.path.join(STATE, "terms", "terms.json")
out = json.load(open(fn)) if os.path.exists(fn) else {}
hosts = set()
for f in glob.glob(os.path.join(STATE, "munisites", "*.docs.jsonl")):
    for l in open(f):
        try:
            d = json.loads(l)
            if d.get("status") == 200: hosts.add(urllib.parse.urlsplit(d.get("final_url") or d["url"]).netloc)
        except Exception: pass
P = zc.Polite()
TL = re.compile(r"terms|disclaimer|copyright|legal notice|conditions of use|website policy|legal", re.I)
KEEP = re.compile(r"copyright|reproduc|permission|rights reserved|intellectual property|may not be|may be used|license|licence|ai-train|content-signal", re.I)
fixed = {"openbylaws.org.za": "https://openbylaws.org.za/terms-of-use/"}
for h in sorted(hosts | {"openbylaws.org.za"}):
    if h in out: continue
    cands = [fixed[h]] if h in fixed else []
    r = P.get(f"https://{h}/")
    if r and r["status"] == 200:
        s = BeautifulSoup(r["body"], "html.parser")
        for a in s.find_all("a", href=True):
            t = a.get_text(" ", strip=True)
            if TL.search(t + " " + a["href"]) and len(t) < 60:
                u = urllib.parse.urljoin(r["url"], a["href"])
                if urllib.parse.urlsplit(u).netloc.endswith(h.replace("www.", "")) and u not in cands: cands.append(u)
    rec = dict(url=None, sentences=[], checked=zc.now_utc())
    for u in cands[:2]:
        x = P.get(u)
        if not x or x["status"] != 200 or "html" not in x["ctype"]: continue
        txt = BeautifulSoup(x["body"], "html.parser").get_text(" ", strip=True)
        sents = [z.strip() for z in re.split(r"(?<=[\.\!\?])\s+", txt) if KEEP.search(z) and 20 < len(z) < 400]
        if sents and not rec["url"]: rec["url"] = u
        rec["sentences"] += sents[:8]
    rb = P.robots_raw.get(f"https://{h}", "")
    sig = re.findall(r"(?im)^content-signal:\s*(.+)$", rb or "")
    if sig: rec["content_signal"] = sorted(set(sig))
    rec["summary"] = ((f"{rec['url']}: " + " ".join(rec["sentences"][:3]))[:600] if rec["sentences"] else
                      f"no terms-of-use / copyright statement found on {h} (checked {rec['checked'][:10]})")
    if sig: rec["summary"] += f" robots.txt Content-Signal: {'; '.join(sorted(set(sig)))}."
    out[h] = rec
    json.dump(out, open(fn, "w"), indent=1, ensure_ascii=False)
    print(h, rec["url"], len(rec["sentences"]), flush=True)
print("DONE", flush=True)
