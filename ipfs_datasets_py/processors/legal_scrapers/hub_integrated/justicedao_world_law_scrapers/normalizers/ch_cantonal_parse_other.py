#!/usr/bin/env python3
"""Parse raw files of non-LexWork official cantonal portals (VD, GE, TI: HTML; ZH, JU: PDF) -> law/article rows."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json, sys, glob, os, time, re, subprocess
sys.path.insert(0, "/workspace/scripts")
from ch_cantonal_common import *
BASE = "{_CORPORA}/ch_cantonal"
SUF = r"(?:\s?(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies)\b|[a-z]\b)?"

def split_vd(h):
    body = h[h.find("<akomaNtoso"):] if "<akomaNtoso" in h else h
    pieces = re.split(r'(?=<div class="akn-article-container")', body)
    head = pieces[0]; arts = []
    cut = re.compile(r'<div class="akn-(?:chapter|section|subsection|title|part|book|chapter-container|section-container|title-container|attachments|annexes|conclusions|hcontainer)\b')
    for p in pieces[1:]:
        m = cut.search(p, 10); seg = p[:m.start()] if m else p
        lab = re.search(r'position="([^"]+)"', p); pos = strip(lab.group(1)) if lab else ""
        nm = re.search(r'class="akn-num[^"]*"[^>]*>(.*?)</td>', seg, re.S)
        label = strip(nm.group(1)) if nm else pos.split(",")[-1].strip()
        if not re.match(r"(?:Art|§)", label): label = pos.split(",")[-1].strip() or label
        hd = re.search(r'class="akn-heading[^"]*">(.*?)</div>', seg, re.S); heading = strip(hd.group(1)) if hd else ""
        arts.append((label, heading, strip(seg), {"position": pos}))
    return strip(head), arts

def split_ge(h):
    h = re.sub(r"<p\s+class=\"?article\"?(?:\s[^>]*)?>", "<p class=article>", h, flags=re.I)
    pieces = re.split(r"(?=<p class=article>)", h, flags=re.I); arts = []
    cut = re.compile(r"<p class=(?:chapitre|section|titre|Tvigueur|Ttetevigueur|Tteteintit|Tadopt|Ttexte|Tmodifi|sous-?section)\b", re.I)
    for p in pieces[1:]:
        m = cut.search(p, 10); seg = p[:m.start()] if m else p
        first = strip(re.match(r"<p class=article>(.*?)</p>", seg, re.S | re.I).group(1)) if re.match(r"<p class=article>(.*?)</p>", seg, re.S | re.I) else ""
        mm = re.match(r"(Art\.\s*\d+[A-Za-z]?" + SUF + r")\s*(.*)", first, re.S)
        label, heading = (re.sub(r"\s+", " ", mm.group(1)), mm.group(2).strip()) if mm else (first[:20], "")
        arts.append((label, heading, strip(seg), {}))
    return strip(pieces[0]), arts

def split_ti(h):
    i = h.find("<body"); body = h[i:] if i >= 0 else h
    text = strip(body); head, arts, full = split_pdf_text(text)
    out = []; prev_head = ""
    lines_head = head.split("\n")
    if lines_head and 0 < len(lines_head[-1]) < 120 and not lines_head[-1].rstrip().endswith((".", ";", ":")): prev_head = lines_head[-1]
    for k, (l, _, t, ex) in enumerate(arts):
        tl = t.split("\n"); nxt = ""
        if k + 1 < len(arts):
            while tl and not tl[-1].strip(): tl.pop()
            if tl and len(tl) > 1 and 0 < len(tl[-1]) < 120 and not tl[-1].rstrip().endswith((".", ";", ":")):
                nxt = tl.pop()
        out.append((l, re.sub(r"\s*\[\d+\]$", "", prev_head).strip(), "\n".join(tl).strip(), {})); prev_head = nxt
    return head, out

ART_LINE = re.compile(r"^(?:(?P<sym>Artt\.|Art\.|Art|Articles|Article|Articoli|Articolo|§§|§)\s*(?P<n>\d+)\s*(?P<suf>[a-z]\b|bis\b|ter\b|quater\b|quinquies\b|sexies\b)?(?P<rng>\s*(?:[-–]|à)\s*\d+\s*(?:[a-z]\b|bis\b|ter\b)?)?|(?P<prem>Article premier))")
def split_pdf_text(txt):
    lines = txt.replace("\f", "\n").split("\n"); starts = []; last = 0
    for i, ln in enumerate(lines):
        m = ART_LINE.match(ln.strip())
        if not m: continue
        rest = ln.strip()[m.end():]
        if rest.startswith((",", " ,")) or re.match(r"\s*(?:al\.|alinéa|Abs\.|lit\.|Ziff\.|ff\.|des |der |und |und$|bis |de la |du |et |LAO\b|CC\b|CO\b|StG\b|FAG\b)", rest): continue
        rng = ""
        if m.group("prem"): b, suf, sym = 1, "", "Art."
        else:
            b, suf, sym = int(m.group("n")), (m.group("suf") or "").lower(), ("§" if m.group("sym").startswith("§") else "Art.")
            rng = re.sub(r"\s+", "", m.group("rng") or "").replace("à", "–")
        if starts and not (last <= b <= last + 25):
            # footnote number glued to the article number (e.g. "Art. 356" = Art. 35 + fn 6)
            ds = str(b); fix = [int(ds[:k]) for k in range(len(ds) - 1, 0, -1) if last < int(ds[:k]) <= last + 3]
            if not fix: continue
            b, suf, rng = fix[0], "", ""
        if not starts:
            if b > 3: continue
        if starts and b == last and not suf: continue
        lab = f"{sym} {b}{(' ' + suf) if suf in ('bis','ter','quater','quinquies','sexies') else suf}{rng}"
        starts.append((i, lab)); last = int(re.search(r"(\d+)", rng).group(1)) if rng and int(re.search(r"(\d+)", rng).group(1)) > b else b
    arts = []
    for k, (i, label) in enumerate(starts):
        j = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        t = re.sub(r"\n{3,}", "\n\n", "\n".join(lines[i:j])).strip()
        arts.append((label, "", t, {}))
    head = "\n".join(lines[: starts[0][0]]).strip() if starts else ""
    return head, arts, re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
def pdftext(path):
    r = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=300)
    return r.stdout.decode("utf-8", errors="replace")

def parse(c, path):
    d = json.load(gzip.open(path)); m = d["meta"]; url = d.get("url", "")
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(path)))
    if c == "VD":
        sn = m["code"]; title = re.sub(r"\s*\(([^()]*;\s*)?BLV [^)]*\)\s*$", "", m["libelle"]).strip()
        head, arts = split_vd(d["html"]); full = strip(d["html"][d["html"].find("<akomaNtoso"):]); date = (d.get("version") or {}).get("dateAdoption") or ""
        meta = {"publisher": "Canton de Vaud, Base législative vaudoise (BLV)", "date_entry_in_force": m.get("dateMiseEnVigueur") or "",
                "version_in_force_since": (d.get("version") or {}).get("versionDateMiseEnVigueur") or "", "html_id": (d.get("version") or {}).get("htmlId")}
        st, backend = "cantonal_vd_blv", "vd_akn_html_article_v1"
    elif c == "GE":
        mm = re.search(r"rsg_([a-z])(\d+)_(\d+)(?:p(\d+))?\.htm", m["href"]); sn = f"{mm.group(1).upper()} {mm.group(2)} {mm.group(3)}" + (f".{mm.group(4)}" if mm.group(4) else "")
        h = d["html"]; tm = re.search(r"<title>(.*?)</title>", h, re.S); title = strip(tm.group(1)) if tm else m.get("label", "")
        title = re.sub(r"^rsGE\s+[^:]+:\s*", "", title); head, arts = split_ge(h); full = strip(h); date = ""
        meta = {"publisher": "République et canton de Genève, Recueil systématique genevois (rsGE, silgeneve.ch)"}
        st, backend = "cantonal_ge_silgeneve", "ge_html_article_v1"
    elif c == "TI":
        sn = m["sn"]; title = m["title"]; head, arts = split_ti(d["html"]); i = d["html"].find("<body"); full = strip(d["html"][i:]); date = ""
        meta = {"publisher": "Repubblica e Cantone Ticino, Raccolta delle leggi (RL)", "rl_num": m["num"], "volume": m.get("volume")}
        st, backend = "cantonal_ti_rleggi", "ti_html_article_v1"
    elif c in ("ZH", "JU"):
        pdf = path.replace(".json.gz", ".pdf"); txt = pdftext(pdf); head, arts, full = split_pdf_text(txt)
        if c == "ZH":
            sn = m["referenceNumber"]; title = m["enactmentTitle"]; date = m.get("enactmentDate", "")
            meta = {"publisher": "Kanton Zürich, Zürcher Gesetzessammlung (ZH-Lex LS)", "pdf_url": d.get("pdf_url"), "text_from_pdf": True}
            st, backend = "cantonal_zh_zhlex", "pdf_text_article_v1"
        else:
            sn = m["sn"] or m["id"]; title = m["title"]; date = ""
            meta = {"publisher": "République et Canton du Jura, Recueil systématique jurassien (RSJU)", "pdf_url": d.get("pdf_url"), "text_from_pdf": True, "rsju_id": m["id"]}
            st, backend = "cantonal_ju_rsju", "pdf_text_article_v1"
    arts = [a for a in arts if a[0]]
    law = make_law(c, sn, title, full, url, st, date, retrieved, len(arts), path, meta)
    return law, make_articles(c, sn, url, date, arts, backend), [a[0] for a in arts]
if __name__ == "__main__":
    for c in sys.argv[1].split(","):
        files = sorted(glob.glob(f"{BASE}/raw/{c}/*.json.gz")); nl = na = npass = 0; checks = {}; seen = set()
        with gzip.open(f"{BASE}/parsed/{c}_laws.jsonl.gz", "wt") as fl, gzip.open(f"{BASE}/parsed/{c}_articles.jsonl.gz", "wt") as fa:
            for p in files:
                try: law, arts, labels = parse(c, p)
                except Exception as e: checks[p] = {"error": repr(e)}; continue
                if law["id"] in seen: checks[p] = {"error": "duplicate_law_id " + law["id"]}; continue
                seen.add(law["id"]); fl.write(json.dumps(law, ensure_ascii=False) + "\n"); nl += 1
                for a in arts: fa.write(json.dumps(a, ensure_ascii=False) + "\n")
                na += len(arts); ck = numbering_check(labels); checks[law["id"]] = ck; npass += bool(ck["pass"])
        json.dump(checks, open(f"{BASE}/parsed/{c}_numbering.json", "w"))
        print(c, "laws", nl, "articles", na, "numbering_pass", npass, flush=True)
