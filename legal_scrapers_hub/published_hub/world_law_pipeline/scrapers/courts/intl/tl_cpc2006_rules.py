"""TL: Código de Processo Civil de Timor-Leste (approved by Decreto-Lei n.º 1/2006, de 21 de Fevereiro), article-level rows from the
official Jornal da República, Série I, N.º 4 (2006) PDF on mj.gov.tl (robots.txt Drupal default, /jornal/public/docs not disallowed).
Two-column layout: rebuilt from pdftotext -bbox-layout blocks (left column then right column per page; running headers dropped)."""
import json, os, re, hashlib, datetime, subprocess, requests
from xml.etree import ElementTree as ET
ROOT = "/workspace/world_courts"
SRC = "https://mj.gov.tl/jornal/public/docs/2006/serie_1/serie1_no4.pdf"
IDX = "https://www.mj.gov.tl/jornal/?q=node%2F1372"
RAW = f"{ROOT}/rules/raw/tl/cpc2006_jr.pdf"; OUT = f"{ROOT}/data/tl/tl_rules.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat()
if not os.path.exists(RAW):
    r = requests.get(SRC, headers={"User-Agent": "WorldCourtsResearchBot/1.0"}, timeout=180); r.raise_for_status(); open(RAW, "wb").write(r.content)
sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
x = subprocess.run(["pdftotext", "-bbox-layout", RAW, "-"], capture_output=True, text=True).stdout
x = re.sub(r"<!DOCTYPE[^>]*>", "", x).replace('xmlns="http://www.w3.org/1999/xhtml"', "")
root = ET.fromstring(x); L = []
for pg in root.iter("page"):
    W = float(pg.get("width")); bl = []
    for b in pg.iter("block"):
        x0, x1, y0, y1 = (float(b.get(k)) for k in ("xMin", "xMax", "yMin", "yMax"))
        lines = [" ".join(w.text or "" for w in ln.iter("word")) for ln in b.iter("line")]
        t = " ".join(lines)
        if y1 < 46 or y0 > 800 or re.match(r"^(Página \d+|Série I.*|Jornal da República.*|.*-Feira, \d+ de Fevereiro de 2006.*)$", t.strip()): continue
        bl.append((0 if (x0 + x1) / 2 < W / 2 else 1, y0, lines))
    for c, y, lines in sorted(bl, key=lambda z: (z[0], z[1])): L.extend(lines)
# the code starts at the second "Artigo 1.º" (the first five belong to the approving decree)
art = re.compile(r"^Artigo (\d+)\.?\s?[ºo°]\.?$")
starts = [i for i, l in enumerate(L) if (m := art.match(l.strip())) and m.group(1) == "1"]
L = L[starts[1]:] if len(starts) > 1 else L
heads = {"LIVRO": None, "TÍTULO": None, "CAPÍTULO": None, "SECÇÃO": None, "SUBSECÇÃO": None}
order = list(heads)
rows = []; cur = None; pending = None
def flush():
    if cur:
        txt = re.sub(r"\s+", " ", " ".join(cur["lines"])).strip(); txt = re.sub(r"(?<=[a-zà-ú])- (?=[a-zà-ú])", "", txt)
        cur["text"] = txt; rows.append(cur)
for i, l in enumerate(L):
    s = l.strip()
    if not s: continue
    m = re.fullmatch(r"(LIVRO|TÍTULO|CAPÍTULO|SECÇÃO|SUBSECÇÃO) ([IVXLC]+|ÚNICO|ÚNICA)", s)
    if m:
        k = m.group(1); heads[k] = f"{k.title()} {m.group(2)}"; pending = k
        for kk in order[order.index(k) + 1:]: heads[kk] = None
        continue
    if pending:  # heading title line
        heads[pending] += f" – {s}"; pending = None; continue
    m = art.match(s)
    if m:
        flush(); cur = {"n": int(m.group(1)), "part": " / ".join(v for v in heads.values() if v), "lines": [], "title": None}; continue
    if cur is not None:
        if cur["title"] is None and not cur["lines"]: cur["title"] = s
        else: cur["lines"].append(s)
flush()
out, seen = [], set()
for a in rows:
    rid = f"tl-cpc-2006:art{a['n']}"
    if rid in seen or not a["text"]: continue
    seen.add(rid)
    out.append({"rule_id": rid, "rule_set_id": "tl-cpc-2006", "court_id": None, "jurisdiction": "TL",
        "rule_set": "Código de Processo Civil (Decreto-Lei n.º 1/2006, de 21 de Fevereiro)", "rule_number": f"Artigo {a['n']}.º", "title": a["title"],
        "part": a["part"] or None, "text": a["text"], "effective_date": "2006-02-22", "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha,
        "source_url": SRC, "index_url": IDX, "site_policy": "robots_allowed", "retrieved_at": now,
        "license": "Decree-Law of the Democratic Republic of Timor-Leste; official text in the Jornal da República (Ministério da Justiça), no licence stated",
        "language": "pt", "version_note": "original 2006 text as published in Jornal da República Série I N.º 4; later amendments not consolidated", "needs_review": True})
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [x for x in out if x["rule_id"] not in old]
with open(OUT, "a") as f:
    for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("parsed", len(out), "added", len(new))
