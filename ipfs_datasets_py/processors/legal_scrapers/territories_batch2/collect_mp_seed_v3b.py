#!/usr/bin/env python3
"""Collect CNMI Law Revision Commission seed pages into MP/upload_ready/.
US government work / public domain. Polite >=2.5s, max ~60 requests.
"""
from __future__ import annotations
import json, pathlib, re, sys, time
from urllib.parse import urljoin, urlparse

sys.path.insert(0, "/workspace/staging/territories_batch2_20261105")
from batch2_common_v3 import (  # noqa: E402
    ROOT,
    Polite,
    copy_sanitized_script,
    guard,
    install_guard,
    mem_available_gib,
    peak_rss_mb,
    write_json_x,
    write_text_x,
)

install_guard()
guard("mp_start")

from bs4 import BeautifulSoup
import pyarrow as pa
import pyarrow.parquet as pq

portal = json.load((ROOT / "MP_portal.json").open())
hosts = ["cnmilaw.gov", "www.cnmilaw.gov"]
client = Polite(hosts, min_delay=2.5)
client.setup("https://cnmilaw.gov/")
# after redirects host may be cnmilaw.gov
for h in list(client.policies):
    pass

# Seed from homepage links already in portal text / fresh homepage
body, meta = client.get("https://cnmilaw.gov/")
soup = BeautifulSoup(body, "html.parser")
candidates = []
seen = set()
for a in soup.find_all("a", href=True):
    href = urljoin("https://cnmilaw.gov/", a["href"])
    if urlparse(href).netloc not in ("cnmilaw.gov", "www.cnmilaw.gov"):
        continue
    path = urlparse(href).path.lower()
    title = (a.get_text(" ", strip=True) or "")[:200]
    # Prefer constitution, code titles, court rules
    if any(
        k in path or k in title.lower()
        for k in (
            "constitution",
            "/code",
            "cmc",
            "court-rules",
            "covenant",
            "administrative-code",
            "/title",
        )
    ):
        if href.rstrip("/") not in seen and not href.endswith((".pdf", ".zip")):
            seen.add(href.rstrip("/"))
            candidates.append((href, title or path))

# Cap seeds
candidates = candidates[:40]
print("MP_CANDIDATES", len(candidates), flush=True)

rows = []
events = []
for i, (url, title) in enumerate(candidates):
    if i >= 55:
        break
    guard(f"mp_{i}")
    try:
        b, m = client.get(url)
    except ValueError as e:
        events.append({"url": url, "error": str(e)})
        if "ACCESS_HOLD" in str(e) or "ROBOTS" in str(e):
            break
        continue
    ev = {"url": url, "title": title, "status": m["status"], "challenge": m.get("challenge")}
    events.append(ev)
    if m["status"] != 200 or m.get("challenge"):
        if m["status"] in (403, 429, 503):
            break
        continue
    doc = BeautifulSoup(b, "html.parser")
    for n in doc(["script", "style", "nav", "footer", "header"]):
        n.extract()
    text = (doc.body or doc).get_text("\n", strip=True)
    ev["text_len"] = len(text)
    if len(text) < 100:
        continue
    # Skip pure navigation stubs
    if len(text) < 400 and text.lower().count("http") > 5:
        continue
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", urlparse(url).path.strip("/"))[:80] or f"page-{i}"
    rows.append(
        {
            "id": f"MP-{slug}",
            "title": title or slug,
            "text": text,
            "source_url": m["requested_url"],
            "source_sha256": m["sha256"],
            "jurisdiction_code": "MP",
            "parent_country": "US",
            "language": "en",
            "source_type": "official_CNMI_LRC_HTML",
            "retrieved_at": m["observed_local"],
            "license": "US government work / public domain (CNMI Law Revision Commission official site)",
        }
    )
    print("MP_ROW", slug, len(text), flush=True)

write_json_x(ROOT / "MP_collection_events_v3.json", events)

ready = ROOT / "MP" / "upload_ready"
if rows and not (ready / "data" / "laws.parquet").exists():
    (ready / "data").mkdir(parents=True, exist_ok=True)
    p = ready / "data" / "laws.parquet"
    pq.write_table(pa.Table.from_pylist(rows), str(p), compression="zstd")
    write_json_x(
        ready / "validation.json",
        {
            "laws_rows": len(rows),
            "articles_rows": 0,
            "articles_file_created": False,
            "min_law_text_chars": min(len(r["text"].strip()) for r in rows),
            "license": "US government work / public domain",
            "source": "cnmilaw.gov",
            "target_hf_repo": "endomorphosis/ipfs_northernmarianaislands_laws",
            "scope": "Seed/homepage-linked Constitution/Code/Rules pages; not complete Commonwealth Code",
            "candidates_discovered": len(candidates),
            "peak_rss_mb": peak_rss_mb(),
            "push": "NOT_PUSHED",
        },
    )
    write_json_x(
        ready / "manifest_upload_ready.json",
        {
            "dataset": "endomorphosis/ipfs_northernmarianaislands_laws",
            "jurisdiction_code": "MP",
            "parent_country": "US",
            "package_path": str(ready),
            "laws_rows": len(rows),
            "created_local": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "push": "HOLD_PENDING_BENJAMIN_GO",
        },
    )
    write_text_x(
        ready / "README.md",
        """---
license: other
language: en
configs:
- config_name: laws
  data_files: data/laws.parquet
---
# Northern Mariana Islands (MP) — CNMI LRC seed corpus

Official HTML pages from cnmilaw.gov (CNMI Law Revision Commission).
US government work / public domain. Seed set from homepage-linked Constitution,
Code, and Court Rules pages — not a claim of complete Commonwealth Code coverage.
No Hugging Face upload performed (CoS HOLD).
""",
    )
    for src in [pathlib.Path(__file__), ROOT / "batch2_common_v3.py"]:
        copy_sanitized_script(src, ready / "scrapers_and_normalizers" / src.name)
    print("MP_READY", len(rows), flush=True)
else:
    write_json_x(
        ROOT / "MP" / "probe_only_v3.json",
        {
            "rows": len(rows),
            "events": len(events),
            "note": "No upload_ready package (0 rows or already exists)",
            "peak_rss_mb": peak_rss_mb(),
        },
    )
    print("MP_NO_PACKAGE", len(rows), flush=True)

print("MP_DONE", "rss", peak_rss_mb(), "mem", f"{mem_available_gib():.3f}", flush=True)
