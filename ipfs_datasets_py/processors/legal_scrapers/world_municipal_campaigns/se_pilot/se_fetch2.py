"""Sweden pilot — fetch pass 2: Umeå (2480) + Gotland (0980).

Both expose a /styrdokument index with direct document links
(discovery addendum). KFS-class titles preferred; appends into the
shared fetch_manifest.json, same record shape as se_fetch.py.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote

from se_fetch import curl, soup_links, clean_title, OUT, MANIFEST, REG

INDEX = {"2480": "https://www.umea.se/styrdokument",
         "0980": "https://gotland.se/styrdokument"}
KFS_WORDS = ("föreskrift", "foreskrift", "reglemente", "taxa", "ordning",
             "arbetsordning", "stadga")
LIMIT = {"2480": 5, "0980": 4}


def main():
    manifest = json.loads(MANIFEST.read_text())
    manifest.setdefault("index_fetches", [])
    for code, idx in INDEX.items():
        entry = manifest["kommuner"].setdefault(code, {"name": REG[code], "files": []})
        if not entry.get("specs"):
            r = curl(idx, max_time=90)
            manifest["index_fetches"].append(
                {"url": idx, "status": r["status"], "bytes": r["bytes"]})
            (OUT / "scratch" / f"index_{code}.html").write_bytes(r["body"])
            specs, seen = [], set()
            for href, txt in soup_links(r["body"].decode("utf-8", "replace"), idx):
                title = clean_title(txt)
                if ("/download/" in href or href.lower().split("?")[0].endswith(".pdf")) \
                        and href not in seen:
                    seen.add(href)
                    specs.append({"url": href, "title": title or unquote(href.split("/")[-1]),
                                  "kind": "pdf"})
            kfs = [s for s in specs if any(w in s["title"].lower() for w in KFS_WORDS)]
            entry["specs"] = (kfs or specs)[:LIMIT[code]]
            entry["index_doc_links_total"] = len(specs)
            entry["index_kfs_links"] = len(kfs)
            MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
            print(f"[{code}] index docs={len(specs)} kfs={len(kfs)} picked={len(entry['specs'])}", flush=True)
        done = {f["url"] for f in entry["files"] if f.get("status") == "ok"}
        for spec in entry["specs"]:
            if spec["url"] in done:
                continue
            d = OUT / "pdfs" / code
            d.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-z0-9]+", "-", unquote(spec["url"]).split("/")[-1].lower()).strip("-")
            if not slug.endswith(".pdf"):
                slug += ".pdf"
            dest = d / slug
            r = curl(spec["url"], dest=dest, max_time=180)
            ok = r["status"] == 200 and r["bytes"] > 500 and r["body"][:5] == b"%PDF-"
            rec = {"url": spec["url"], "title": spec["title"], "kind": "pdf",
                   "path": str(dest.relative_to(OUT)), "status": "ok" if ok else "failed",
                   "http": r["status"], "bytes": r["bytes"], "seconds": r["seconds"]}
            entry["files"] = [f for f in entry["files"] if f["url"] != spec["url"]] + [rec]
            MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
            print(f"[{code}] {rec['status']} {rec['bytes']}B {spec['title'][:60]}", flush=True)
            time.sleep(2)
    print("fetch2 done")


if __name__ == "__main__":
    main()
