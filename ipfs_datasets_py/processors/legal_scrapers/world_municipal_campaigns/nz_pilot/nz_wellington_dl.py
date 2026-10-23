"""Wellington City (047) — download operative bylaw PDFs from Wayback
snapshots enumerated via CDX (the availability API had no snapshot of
the index page, but CDX domain search found the bylaw PDFs under
/-/media/your-council/plans-policies-and-bylaws/bylaws/files/).
Writes pdfs/047/ + fetch_manifest.json entry (source="wayback").
"""
import hashlib
import json
import sys
import time
from pathlib import Path

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))
from nz_pilot_build import PoliteSession  # noqa: E402
from nz_fetch import stream_download, slugify, load_manifest, save_manifest  # noqa: E402

BASE = "https://wellington.govt.nz/-/media/your-council/plans-policies-and-bylaws/bylaws/files/"
DOCS = [
    ("animal-bylaw-2024.pdf", "20250331210634", "Animal Bylaw 2024"),
    ("alcohol-fees-bylaw-2024.pdf", "20250404023842", "Alcohol Fees Bylaw 2024"),
    ("public-places/public-places-bylaw-2022.pdf", "20240612182418", "Public Places Bylaw 2022"),
    ("public-health-bylaw-2019-06-28.pdf", "20220320052838", "Public Health Bylaw 2019"),
]


def main():
    manifest = load_manifest()
    entry = {"name": "Wellington City",
             "index_url": "https://wellington.govt.nz/your-council/plans-policies-and-bylaws/bylaws",
             "robots": {"status": "documented-allow",
                        "basis": "2026-10-12 documented check (nz_pilot_build.py header): "
                                 "Allow /, Disallow /search/ etc. Live host ReadTimeout "
                                 "from this egress in all three workers; PDFs taken from "
                                 "Wayback CDX-enumerated snapshots of the same public URLs",
                        "seconds": None},
             "discovered": len(DOCS), "files": []}
    manifest["councils"]["047"] = entry
    save_manifest(manifest)
    sess = PoliteSession()
    cdir = OUT / "pdfs" / "047"
    cdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    files = []
    for i, (rel, ts, link_text) in enumerate(DOCS, start=1):
        url = BASE + rel
        wb_url = f"https://web.archive.org/web/{ts}id_/{url}"
        final_path = cdir / slugify(url, i)
        rec = {"url": url, "link_text": link_text,
               "path": str(final_path.relative_to(OUT)),
               "status": "failed", "source": None, "size": 0, "sha256": "",
               "seconds": 0.0, "attempts": 0, "errors": [],
               "wayback_url": wb_url, "wayback_timestamp": ts}
        t1 = time.monotonic()
        part = final_path.with_suffix(".pdf.part")
        for attempt in range(1, 5):
            rec["attempts"] = attempt
            try:
                stream_download(sess, wb_url, part)
                break
            except Exception as exc:  # noqa: BLE001
                rec["errors"].append(f"wayback#{attempt}: {type(exc).__name__}: {str(exc)[:120]}")
                print(f"    WB DL FAIL #{attempt} {type(exc).__name__} {rel}", flush=True)
                time.sleep(45 * attempt)  # archive.org 429s: back off properly
        if part.exists() and part.stat().st_size > 0 and part.open("rb").read(4) == b"%PDF":
            part.rename(final_path)
            data = final_path.read_bytes()
            rec.update(status="ok", source="wayback", size=len(data),
                       sha256=hashlib.sha256(data).hexdigest())
            print(f"    WB DL OK {len(data)}B {rel}", flush=True)
        else:
            rec["errors"].append("wayback: no usable PDF bytes")
            part.unlink(missing_ok=True)
        rec["seconds"] = round(time.monotonic() - t1, 1)
        files.append(rec)
        entry["files"] = files
        save_manifest(manifest)
    entry["wall_seconds"] = round(time.monotonic() - t0, 1)
    save_manifest(manifest)
    ok = sum(1 for f in files if f["status"] == "ok")
    print(f"[047] done: {ok}/{len(DOCS)} PDFs via wayback CDX, wall {entry['wall_seconds']}s")


if __name__ == "__main__":
    main()
