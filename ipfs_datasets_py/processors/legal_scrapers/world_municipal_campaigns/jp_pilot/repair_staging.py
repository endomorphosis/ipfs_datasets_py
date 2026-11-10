"""One-off staging repair after the duplicate-builder race (2026-10-14).

For each staging/<code>: rebuild <code>_rows.jsonl to contain exactly the
rows of the docs in <code>_done.json (first occurrence set per doc, in
done order, count-checked against the done entry's row count). Docs whose
rows are missing/short are removed from done (they will be reprocessed).
"""
import json
from pathlib import Path


# Generated campaign files live outside the installed package; the mapping is
# legal_scrapers/user_data_paths.py (IPFS_DATASETS_LEGAL_WORK_ROOT).
import importlib.util as _udp_util
from pathlib import Path as _udp_Path
_udp_spec = _udp_util.spec_from_file_location(
    "_legal_scrapers_user_data_paths",
    next(p for p in _udp_Path(__file__).resolve().parents if p.name == "legal_scrapers") / "user_data_paths.py",
)
_udp = _udp_util.module_from_spec(_udp_spec)
_udp_spec.loader.exec_module(_udp)
_campaign_data_file = _udp.work_mirror_path
def _campaign_source_path(path):
    return _udp.source_path_for_mirror(path, __file__)


STAGING = _campaign_data_file(__file__).parent.parent / "staging"

for done_path in sorted(STAGING.glob("*_done.json")):
    code = done_path.name.split("_")[0]
    done = json.loads(done_path.read_text(encoding="utf-8"))
    rows_path = STAGING / f"{code}_rows.jsonl"
    raw_lines = rows_path.read_text(encoding="utf-8").splitlines() if rows_path.exists() else []
    by_doc = {}
    bad_lines = 0
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        doc_id = row.get("doc_id", "")
        honbun = doc_id.rsplit("-", 1)[0] if "-" in doc_id else doc_id
        by_doc.setdefault(honbun, []).append(line)
    kept_docs, kept_lines, dropped_docs = [], [], []
    for d in done["docs"]:
        lines = by_doc.get(d["honbun_id"], [])
        if len(lines) >= d["rows"]:
            kept_docs.append(d)
            kept_lines.extend(lines[: d["rows"]])
        else:
            dropped_docs.append((d["honbun_id"], len(lines), d["rows"]))
    done["docs"] = kept_docs
    if dropped_docs:
        done.setdefault("repair_dropped", []).extend(
            [{"honbun_id": h, "found_rows": f, "expected_rows": e}
             for h, f, e in dropped_docs])
    rows_path.write_text("".join(l + "\n" for l in kept_lines), encoding="utf-8")
    tmp = done_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(done_path)
    extra = {h: len(v) for h, v in by_doc.items()
             if h not in {d["honbun_id"] for d in kept_docs}}
    print(f"{code}: kept {len(kept_docs)} docs / {len(kept_lines)} rows; "
          f"dropped-from-done {len(dropped_docs)}; bad_lines {bad_lines}; "
          f"orphan doc rows dropped: {sum(extra.values())} rows in {len(extra)} docs")
print("repair complete")
