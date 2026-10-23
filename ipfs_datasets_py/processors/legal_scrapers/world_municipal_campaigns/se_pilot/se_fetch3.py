"""Sweden pilot — fetch pass 3: Uppsala repair.

se_fetch.py slugified html_page URLs by their last path segment; the
Uppsala URLs end in '/', so all 8 pages overwrote one 'page.html'.
This pass re-downloads each page under a correct slug, extracts the
canonical PDF link (/contentassets/<hash>/<file>.pdf) that every
Uppsala styrdokument page carries, downloads that PDF, and replaces
Uppsala's manifest files with the PDF records.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

from se_fetch import curl, OUT, MANIFEST, REG

CODE = "0380"
BASE = "https://www.uppsala.se"


def page_slug(url):
    seg = [s for s in url.split("/") if s][-1]
    return re.sub(r"[^a-z0-9]+", "-", seg.lower()).strip("-")


def main():
    manifest = json.loads(MANIFEST.read_text())
    entry = manifest["kommuner"][CODE]
    specs = entry["specs"]
    pdir = OUT / "pages" / CODE
    ddir = OUT / "pdfs" / CODE
    pdir.mkdir(parents=True, exist_ok=True)
    ddir.mkdir(parents=True, exist_ok=True)
    bogus = pdir / "page.html"
    if bogus.exists():
        bogus.unlink()
    files = []
    for spec in specs:
        slug = page_slug(spec["url"])
        page_dest = pdir / f"{slug}.html"
        r = curl(spec["url"], dest=page_dest, max_time=120)
        rec_page = {"url": spec["url"], "title": spec["title"], "kind": "html_page",
                    "path": str(page_dest.relative_to(OUT)),
                    "status": "ok" if r["status"] == 200 else "failed",
                    "http": r["status"], "bytes": r["bytes"], "seconds": r["seconds"]}
        files.append(rec_page)
        print(f"[0380] page {rec_page['status']} {slug}", flush=True)
        if r["status"] != 200:
            continue
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r["body"].decode("utf-8", "replace"), "html.parser")
        pdf_url = None
        for a in soup.find_all("a", href=True):
            if "/contentassets/" in a["href"] and a["href"].lower().endswith(".pdf"):
                pdf_url = urljoin(BASE, a["href"])
                break
        if not pdf_url:
            print(f"[0380] no contentassets PDF on {slug}", flush=True)
            continue
        pdf_dest = ddir / f"{slug}.pdf"
        r2 = curl(pdf_url, dest=pdf_dest, max_time=180)
        ok = r2["status"] == 200 and r2["bytes"] > 500 and r2["body"][:5] == b"%PDF-"
        files.append({"url": pdf_url, "title": spec["title"], "kind": "pdf",
                      "via_page": spec["url"],
                      "path": str(pdf_dest.relative_to(OUT)),
                      "status": "ok" if ok else "failed", "http": r2["status"],
                      "bytes": r2["bytes"], "seconds": r2["seconds"]})
        print(f"[0380] pdf {'ok' if ok else 'FAIL'} {r2['bytes']}B {slug}", flush=True)
        MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
        time.sleep(2)
    entry["files"] = files
    MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print("uppsala repair done")


if __name__ == "__main__":
    main()
