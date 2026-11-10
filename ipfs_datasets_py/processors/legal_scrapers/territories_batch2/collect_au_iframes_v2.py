#!/usr/bin/env python3
"""Fetch 5 AU Register EPUB HTML full-text iframes (10.5s robots delay).
Stages CX/CC/HM upload_ready packages. No overwrite of existing files.
"""
from __future__ import annotations
import json, pathlib, sys, time

sys.path.insert(0, "/workspace/staging/territories_batch2_20261105")
from batch2_common_v3 import (  # noqa: E402
    ROOT,
    Polite,
    UA,
    copy_sanitized_script,
    guard,
    install_guard,
    mem_available_gib,
    peak_rss_mb,
    write_json_x,
    write_text_x,
)

install_guard()
guard("au_start")

from bs4 import BeautifulSoup
import pyarrow as pa
import pyarrow.parquet as pq
from urllib.robotparser import RobotFileParser

terms = json.load((ROOT / "AU_terms_review.json").open())
client = Polite(["www.legislation.gov.au"], min_delay=10.5)
# Prefer already-fetched robots if present
robots_raw = terms.get("robots", {}).get("raw_path")
if robots_raw and pathlib.Path(robots_raw).exists():
    rp = RobotFileParser()
    rp.parse(pathlib.Path(robots_raw).read_text().splitlines())
    client.policies["www.legislation.gov.au"] = rp
    client.delay["www.legislation.gov.au"] = max(
        10.5, float(rp.crawl_delay(UA) or rp.crawl_delay("*") or 0)
    )
else:
    client.setup("https://www.legislation.gov.au/")
    client.delay["www.legislation.gov.au"] = max(
        10.5, client.delay.get("www.legislation.gov.au", 10.5)
    )

rows = {}
events = []
for old in json.load((ROOT / "AU_collection_events.json").open()):
    guard(f"au_{old['code']}")
    soup = BeautifulSoup(pathlib.Path(old["response"]["raw_path"]).read_bytes(), "html.parser")
    iframe = soup.find("iframe", id="epubFrame")
    if not iframe or not iframe.get("src"):
        events.append({"code": old["code"], "title": old["title"], "error": "no_iframe"})
        continue
    url = iframe["src"]
    body, meta = client.get(url)
    event = {"code": old["code"], "title": old["title"], "response": meta}
    events.append(event)
    if meta["status"] != 200 or meta.get("challenge"):
        event["error"] = "bad_status_or_challenge"
        break
    doc = BeautifulSoup(body, "html.parser")
    for n in doc(["script", "style"]):
        n.extract()
    text = (doc.body or doc).get_text("\n", strip=True)
    if len(text) < 1000:
        event["error"] = "body_too_short"
        event["text_len"] = len(text)
        continue
    identifier = old["response"]["requested_url"].split("/")[3]
    code = old["code"]
    rows.setdefault(code, []).append(
        {
            "id": f"{code}-{identifier}",
            "official_identifier": identifier,
            "title": old["title"],
            "text": text,
            "source_url": meta["requested_url"],
            "source_sha256": meta["sha256"],
            "jurisdiction_code": code,
            "parent_country": "AU",
            "language": "en",
            "source_type": "official_Federal_Register_EPUB_HTML",
            "retrieved_at": meta["observed_local"],
            "license": "CC-BY-4.0, Federal Register of Legislation attribution; exceptions as official terms",
            "normalization": (
                "Based on content from the Federal Register of Legislation at "
                + meta["requested_url"]
                + " on retrieval date; HTML markup removed, text order retained. "
                "https://creativecommons.org/licenses/by/4.0/"
            ),
            "coverage": "Foundation act / Applied Laws Ordinance seed set, not all applied WA/ACT laws",
        }
    )
    print("AU_HTML", code, identifier, len(text), f"rss={peak_rss_mb():.1f}", flush=True)

write_json_x(ROOT / "AU_iframe_collection_events_v2.json", events)

REPO = {
    "CX": "endomorphosis/ipfs_christmasisland_laws",
    "CC": "endomorphosis/ipfs_cocoskeelingislands_laws",
    "HM": "endomorphosis/ipfs_heardislandandmcdonaldislands_laws",
}

for code, data in rows.items():
    ready = ROOT / code / "upload_ready"
    if (ready / "data" / "laws.parquet").exists():
        print("AU_SKIP_EXISTS", code, flush=True)
        continue
    (ready / "data").mkdir(parents=True, exist_ok=True)
    p = ready / "data" / "laws.parquet"
    pq.write_table(pa.Table.from_pylist(data), str(p), compression="zstd")
    n = pq.read_metadata(str(p)).num_rows
    min_text = min(len(r["text"].strip()) for r in data)
    write_json_x(
        ready / "validation.json",
        {
            "laws_rows": n,
            "articles_rows": 0,
            "articles_file_created": False,
            "min_law_text_chars": min_text,
            "source": "Official full-text document iframe linked visibly by Register page",
            "scope": "Foundation acts and applied-laws ordinances only",
            "robots_crawl_delay_seconds": client.delay["www.legislation.gov.au"],
            "license": "CC-BY-4.0; see AU_terms_review.json",
            "target_hf_repo": REPO[code],
            "peak_rss_mb": peak_rss_mb(),
            "datasets_streaming_validation": "Pending central verifier",
            "push": "NOT_PUSHED",
        },
    )
    write_json_x(
        ready / "manifest_upload_ready.json",
        {
            "dataset": REPO[code],
            "jurisdiction_code": code,
            "parent_country": "AU",
            "package_path": str(ready),
            "laws_rows": n,
            "articles_rows": 0,
            "created_local": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "push": "HOLD_PENDING_BENJAMIN_GO",
        },
    )
    write_text_x(
        ready / "README.md",
        f"""---
license: cc-by-4.0
language: en
configs:
- config_name: laws
  data_files: data/laws.parquet
---
# Australian external territory ({code}): official foundation laws

Based on content from the Federal Register of Legislation, https://www.legislation.gov.au/ .
Source URLs and retrieval times accompany each record. Licensed CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/), with exceptions in official terms.
Changes: HTML markup removed, source text order retained; no speculative article splitting.

Complete for the documented small foundation-act/applied-laws-ordinance seed list only.
NOT all territory ordinances or all applied Western Australian/ACT legislation.
No empty articles.parquet created. Official text prevails; not legal advice.
No Hugging Face upload performed (CoS HOLD). Target: {REPO[code]}.
""",
    )
    for src in [pathlib.Path(__file__), ROOT / "batch2_common_v3.py"]:
        copy_sanitized_script(src, ready / "scrapers_and_normalizers" / src.name)
    print("AU_READY", code, n, "min_text", min_text, flush=True)

print(
    "AU_IFRAMES_DONE",
    "codes",
    sorted(rows),
    "peak_rss_mb",
    peak_rss_mb(),
    "mem_gib",
    f"{mem_available_gib():.3f}",
    flush=True,
)
