"""Sweden pilot — checkpointed disk-first fetch (curl, hard-capped).

Collectors per kommun produce doc specs {url, title, kind}:
- 1980 Västerås: PDF links from the författningssamling index
  (discovery_state.json), substantive subset sampled.
- 0380 Uppsala: the 8 styrdokument doc-pages linked from the
  författningssamling index (HTML pages; PDF extracted at build time
  if the page offers one).
- 1280 Malmö: PDF links from the författningssamling category pages.
- 1880 Örebro: KFS-class PDF links (föreskrift/reglemente/taxa/
  ordning in title) from the category document pages.
Downloads land in pdfs/<code>/ (PDF) or pages/<code>/ (HTML);
fetch_manifest.json is rewritten after every file.
"""
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

OUT = Path(__file__).resolve().parent
SCRATCH = OUT / "scratch"
MANIFEST = OUT / "fetch_manifest.json"
UA = "world-municipal-law-pilot/1.0 (research; polite harvest)"
RETRIEVED = "2026-10-14"

REG = {json.loads(ln)["jurisdiction_id"]: json.loads(ln)["jurisdiction_name"]
       for ln in (OUT / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines()}


def curl(url, dest=None, max_time=120):
    cmd = ["curl", "-sS", "-L", "--max-time", str(max_time), "-A", UA,
           "-w", "\n%{http_code}", url]
    if dest:
        cmd = ["curl", "-sS", "-L", "--max-time", str(max_time), "-A", UA,
               "-w", "%{http_code}", "-o", str(dest), url]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=max_time + 20)
        if dest:
            code = int(p.stdout.decode().strip() or 0)
            body = dest.read_bytes() if dest.exists() else b""
            return {"status": code, "body": body, "bytes": len(body),
                    "seconds": round(time.monotonic() - t0, 1)}
        out = p.stdout
        body, _, tail = out.rpartition(b"\n")
        return {"status": int(tail.decode().strip() or 0), "body": body,
                "bytes": len(body), "seconds": round(time.monotonic() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "body": b"", "bytes": 0,
                "seconds": round(time.monotonic() - t0, 1),
                "error": f"{type(e).__name__}: {e}"}


def soup_links(html_text, base):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        out.append((urljoin(base, a["href"]), " ".join(a.get_text().split())))
    return out


def clean_title(t):
    t = re.sub(r"\s*(pdf|docx?)\s*,?\s*[\d.,]+\s*(kB|MB|KB)?\.?\s*$", "", t, flags=re.I)
    return t.strip(" .")


def collect_vasteras():
    disc = json.loads((OUT / "discovery_state.json").read_text())
    docs = disc["kommuner"]["1980"]["found_index"][0]["doc_links"]
    want = ["Lokala ordningsföreskrifter för Västerås",
            "Lokala föreskrifter för att skydda människors hälsa och miljön",
            "Lokala ordningsföreskrifter torghandel",
            "Reglemente för kommunstyrelsen",
            "Reglemente för arbetsmarknadsnämnden",
            "Taxa för prövning och tillsyn enligt alkohollagen"]
    picked = []
    for d in docs:
        title = clean_title(d["text"])
        if any(title.startswith(w) for w in want):
            picked.append({"url": d["url"], "title": title, "kind": "pdf"})
    return picked


UPPSALA_INDEX = "https://www.uppsala.se/kommun-och-politik/dokumentsamlingar/lokala-foreskrifter/"


def collect_uppsala():
    html = (SCRATCH / "index_0380.html").read_text(encoding="utf-8", errors="replace")
    picked = []
    for href, txt in soup_links(html, UPPSALA_INDEX):
        if "/publikasjoner/" in href or "/publikationer/styrdokument/" in href:
            picked.append({"url": href, "title": txt, "kind": "html_page"})
    return picked


MALMO_CATS = [
    "https://malmo.se/Om-Malmo-stad/Demokrati-och-politik/Sa-styrs-Malmo/Forfattningssamling.html",
    "https://malmo.se/Om-Malmo-stad/Demokrati-och-politik/Sa-styrs-Malmo/Forfattningssamling/Bestammelser-som-riktar-sig-till-dig-som-medborgare.html",
    "https://malmo.se/Om-Malmo-stad/Demokrati-och-politik/Sa-styrs-Malmo/Forfattningssamling/Taxor-och-avgifter.html",
    "https://malmo.se/Om-Malmo-stad/Demokrati-och-politik/Sa-styrs-Malmo/Forfattningssamling/Kommunala-reglementen.html",
]


def collect_malmo(manifest):
    pdfs = []
    for cat in MALMO_CATS:
        r = curl(cat, max_time=60)
        manifest.setdefault("index_fetches", []).append(
            {"url": cat, "status": r["status"], "bytes": r["bytes"]})
        if r["status"] != 200:
            continue
        for href, txt in soup_links(r["body"].decode("utf-8", "replace"), cat):
            if href.lower().split("?")[0].endswith(".pdf") or "/download/" in href:
                pdfs.append({"url": href, "title": clean_title(txt) or
                             unquote(href.split("/")[-1]), "kind": "pdf"})
        time.sleep(1.5)
    seen, out = set(), []
    for p in pdfs:
        if p["url"] not in seen:
            seen.add(p["url"])
            out.append(p)
    return out[:5]


OREBRO_CATS = [
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/kommun--politik---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/bygga-bo--trafik---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/miljo--klimat---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/barn--utbildning---dokument.html",
]
KFS_WORDS = ("föreskrift", "foreskrift", "reglemente", "taxa", "ordning")


def collect_orebro(manifest):
    pdfs = []
    for cat in OREBRO_CATS:
        r = curl(cat, max_time=60)
        manifest.setdefault("index_fetches", []).append(
            {"url": cat, "status": r["status"], "bytes": r["bytes"]})
        if r["status"] != 200:
            continue
        for href, txt in soup_links(r["body"].decode("utf-8", "replace"), cat):
            title = clean_title(txt)
            if ("/download/" in href or href.lower().split("?")[0].endswith(".pdf")) \
                    and any(w in title.lower() for w in KFS_WORDS):
                pdfs.append({"url": href, "title": title, "kind": "pdf"})
        time.sleep(1.5)
    seen, out = set(), []
    for p in pdfs:
        if p["url"] not in seen:
            seen.add(p["url"])
            out.append(p)
    return out[:5]


COLLECTORS = {"1980": collect_vasteras, "0380": collect_uppsala,
              "1280": collect_malmo, "1880": collect_orebro}


def main():
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() \
        else {"retrieved": RETRIEVED, "kommuner": {}}
    for code, collector in COLLECTORS.items():
        entry = manifest["kommuner"].setdefault(code, {"name": REG[code], "files": []})
        if not entry.get("specs"):
            if code in ("1280", "1880"):
                specs = collector(manifest)
            else:
                specs = collector()
            entry["specs"] = specs
            MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
            print(f"[{code}] collected {len(specs)} doc specs", flush=True)
        done = {f["url"] for f in entry["files"] if f.get("status") == "ok"}
        for spec in entry["specs"]:
            if spec["url"] in done:
                continue
            sub = "pdfs" if spec["kind"] == "pdf" else "pages"
            d = OUT / sub / code
            d.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-z0-9]+", "-",
                          unquote(spec["url"]).split("/")[-1].lower()).strip("-")
            if spec["kind"] == "pdf" and not slug.endswith(".pdf"):
                slug += ".pdf"
            if spec["kind"] == "html_page":
                slug = (slug or "page") + ".html"
            dest = d / slug
            r = curl(spec["url"], dest=dest, max_time=180)
            ok = r["status"] == 200 and r["bytes"] > 500
            if spec["kind"] == "pdf" and ok and not r["body"][:5] == b"%PDF-":
                ok = False
                r["error"] = "not a PDF payload"
            rec = {"url": spec["url"], "title": spec["title"], "kind": spec["kind"],
                   "path": str(dest.relative_to(OUT)), "status": "ok" if ok else "failed",
                   "http": r["status"], "bytes": r["bytes"], "seconds": r["seconds"]}
            if r.get("error"):
                rec["error"] = r["error"]
            entry["files"] = [f for f in entry["files"] if f["url"] != spec["url"]] + [rec]
            MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
            print(f"[{code}] {rec['status']} {rec['bytes']}B {spec['title'][:60]}", flush=True)
            time.sleep(2)
    print("fetch done")


if __name__ == "__main__":
    main()
