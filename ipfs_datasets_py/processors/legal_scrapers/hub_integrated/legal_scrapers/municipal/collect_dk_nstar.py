#!/usr/bin/env python3
"""Denmark municipal waste regulations (affaldsregulativer) from NSTAR, Energistyrelsen's national regulation database (nstar.ens.dk).

Kommunerne skal offentliggøre vedtagne affaldsregulativer ved indrapportering til NSTAR (BEK nr. 938 af 2022 § 3, stk. 4): a regulation
is valid only once published there, so NSTAR holds every kommune's current household and business waste regulation. The public status
page (PublicMunicipalityStatusPage.aspx) lists, per type, each kommune with its approval date and a 'PDF' button. The button is an
ASP.NET postback that returns the published regulation as a born-digital PDF; this is a read-only download (the same as a click).
nstar.ens.dk has no robots.txt (404). Requests are spaced; one session.

Streaming: each PDF is converted with pdftotext at once; only the text, page count, sha256 and size are kept (gzip JSONL shard), and the
PDF is deleted. Kommunekoder (3-digit) come from Danmarks Statistik's StatBank API (api.statbank.dk, table FOLK1A region codes; open data).

usage: collect_dk_nstar.py [OUTDIR]       (default: dk_build)
"""
import gzip, hashlib, html, json, os, re, subprocess, sys, tempfile, time
import requests

BASE = "https://nstar.ens.dk/PublicMunicipalityStatusPage.aspx"
UA = "legal-corpora research collector (municipal regulations dataset; read-only, spaced requests)"
SLEEP = 1.5
TYPES = {"PrivateRb": "husholdning", "BusinessRb": "erhverv"}

def hidden(page):
    return {m.group(1): html.unescape(m.group(2)) for m in re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page)}

def rows(page):
    out = []
    for m in re.finditer(r'name="(ctl00\$DefaultContent\$(modelId\d+)\$DocumentId)"[^>]*value="(\d+)"(.*?)(?=name="ctl00\$DefaultContent\$modelId\d+\$DocumentId"|</div>\s*</div>\s*</div>\s*</div>)', page, re.S):
        blk = m.group(4)
        title = re.search(r'documentInfoStyleMarker"[^>]*Title="([^"]*)"', blk, re.S)
        kom = re.search(r'_MunicipalityL">([^<]*)<', blk); dt = re.search(r'_RegulationApprovedL">([^<]*)<', blk)
        btn = re.search(r'name="(ctl00\$DefaultContent\$' + m.group(2) + r'\$ShowPdf)"', blk)
        info = html.unescape(title.group(1)) if title else ""
        out.append(dict(model=m.group(2), document_id=m.group(3), kommune=html.unescape(kom.group(1)).strip() if kom else None,
                        approved=dt.group(1).strip() if dt else None, pdf_button=btn.group(1) if btn else None,
                        paradigm_id=(re.search(r"Paradigmets database id:\s*(\d+)", info) or [None, None])[1],
                        status_note=re.sub(r"\s+", " ", info).strip() or None))
    return out

def norm_kommune(n):
    n = re.sub(r"\s+(Kommune|Regionskommune)$", "", (n or "").strip(), flags=re.I).strip().lower()
    return {"københavns": "københavn", "bornholms": "bornholm", "høje-tåstrup": "høje-taastrup", "vesthimmerland": "vesthimmerlands"}.get(n, n)

def kommunekoder(s):
    # Danmarks Statistik StatBank API (open): region variable of FOLK1A; kommune codes are 101-860 (081-085 are regions)
    r = s.get("https://api.statbank.dk/v1/tableinfo/FOLK1A", params={"lang": "da", "format": "JSON"}, timeout=60); r.raise_for_status()
    vals = [v for v in r.json()["variables"] if v["id"] == "OMRÅDE"][0]["values"]
    kommunekoder.raw = vals  # ordered: each region (08x) followed by its kommuner
    return {norm_kommune(v["text"]): v["id"] for v in vals if re.fullmatch(r"\d{3}", v["id"]) and int(v["id"]) >= 101}

def main(out="dk_build"):
    os.makedirs(out, exist_ok=True)
    s = requests.Session(); s.headers["User-Agent"] = UA
    kk = kommunekoder(s); json.dump(dict(codes=kk, statbank_folk1a_omraade=kommunekoder.raw), open(f"{out}/kommunekoder.json", "w"), ensure_ascii=False)
    shard = f"{out}/nstar_texts.jsonl.gz"
    done = set()
    if os.path.exists(shard):
        for l in gzip.open(shard, "rt"): r = json.loads(l); done.add((r["type"], r["document_id"])) if not r.get("error") else None
    w = gzip.open(shard, "at")
    for rb, typ in TYPES.items():
        p = s.get(BASE, timeout=60); time.sleep(SLEEP)
        if rb != "PrivateRb":
            f = hidden(p.text); f["__EVENTTARGET"] = "ctl00$MenuSideContent$" + rb; f["__EVENTARGUMENT"] = ""; f["ctl00$MenuSideContent$Type"] = rb
            p = s.post(BASE, data=f, timeout=60); time.sleep(SLEEP)
        page = p.text; rs = rows(page)
        print(typ, len(rs), "rows", flush=True)
        json.dump(rs, open(f"{out}/status_{typ}.json", "w"), ensure_ascii=False)
        for r in rs:
            if not r["pdf_button"] or (typ, r["document_id"]) in done: continue
            f = hidden(page); f["ctl00$MenuSideContent$Type"] = rb; f[r["pdf_button"]] = "PDF"
            rec = dict(type=typ, **{k: v for k, v in r.items() if k != "pdf_button"}, kommunekode=kk.get(norm_kommune(r["kommune"])), source_page=BASE,
                       retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            try:
                d = s.post(BASE, data=f, timeout=180)
                if d.status_code != 200 or "pdf" not in (d.headers.get("content-type") or ""): raise RuntimeError(f"HTTP {d.status_code} {d.headers.get('content-type')}")
                cd = d.headers.get("content-disposition") or ""; fn = re.search(r'filename="?([^";]+)', cd)
                with tempfile.NamedTemporaryFile(suffix=".pdf", dir=out) as tf:
                    tf.write(d.content); tf.flush()
                    info = subprocess.run(["pdfinfo", tf.name], capture_output=True, text=True).stdout
                    txt = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", tf.name, "-"], capture_output=True, text=True).stdout
                rec.update(filename=fn.group(1).strip() if fn else None, pdf_bytes=len(d.content), pdf_sha256=hashlib.sha256(d.content).hexdigest(),
                           pages=int((re.search(r"Pages:\s+(\d+)", info) or [0, 0])[1]), producer=(re.search(r"Producer:\s+(.*)", info) or [None, None])[1], text=txt)
            except Exception as e:
                rec["error"] = f"{type(e).__name__}: {e}"[:300]
            w.write(json.dumps(rec, ensure_ascii=False) + "\n"); w.flush()
            print(typ, r["kommune"], rec.get("pages"), rec.get("error") or "", flush=True)
            time.sleep(SLEEP)
    w.close()

if __name__ == "__main__":
    main(*(sys.argv[1:2]))
