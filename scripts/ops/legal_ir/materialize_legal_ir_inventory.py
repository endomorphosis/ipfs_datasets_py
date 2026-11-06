"""Materialize one source-bound USC/Constitution inventory in its native task.

This helper creates inventory artifacts only. Independent task validation and
native proposal/merge admission retain all completion authority. It performs no
retrieval, download, model, compiler, training, board or status mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[3]
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
SOURCE_ID = "national-archives-retained-20260923"


def contract_owner(root):
    path = root / "scripts/ops/legal_ir/legal_ir_supervisor_contract.py"
    spec = importlib.util.spec_from_file_location("legal_ir_inventory_contract", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def raw(value):
    return (json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False,
                       allow_nan=False) + "\n").encode()


def zipped_array(label, content):
    """One deterministic ordinary JSON member; no filesystem extraction."""
    if not 0 < len(content) <= MAX_ARTIFACT_BYTES:
        raise ValueError("uncompressed JSON exceeds native artifact bound")
    member = zipfile.ZipInfo(label + ".json", date_time=(1980, 1, 1, 0, 0, 0))
    member.create_system = 3
    member.external_attr = (stat.S_IFREG | 0o600) << 16
    member.compress_type = zipfile.ZIP_DEFLATED
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(member, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def uscode_artifacts(root, contract, plan, task_id, source_parquet):
    shards = [row for row in plan["shards"] if row["task_id"] == task_id]
    contract.require(len(shards) == 1, "one exact planned USC shard required")
    shard = shards[0]
    contract.require(all(type(shard.get(key)) is int for key in ("start", "end", "count"))
                     and 0 <= shard["start"] < shard["end"]
                     and shard["count"] == shard["end"] - shard["start"], "invalid shard bounds")
    rows = contract.usc_rows(str(shard["title"]), source_parquet=source_parquet)
    rows = rows[shard["start"]:shard["end"]]
    contract.require(len(rows) == shard["count"], "pinned shard row count differs")
    sections, spans, entities, identities = [], [], [], set()
    for row in rows:
        index, cid, text = row["source_row_index"], row["ipfs_cid"], row["text"]
        contract.require(type(index) is int and index >= 0 and (text is None or type(text) is str),
                         "exact source row identity/plaintext required")
        identity = cid if isinstance(cid, str) and cid else ("parquet-row", index)
        contract.require(identity not in identities, "duplicate pinned source identity")
        identities.add(identity)
        title, section = str(shard["title"]), row["section_number"]
        digest = contract.sha(text.encode()) if text is not None else None
        base = {"source_row_index": index, "title": title, "section_number": section,
                "ipfs_cid": cid, "text": text, "source_text_sha256": digest,
                "admitted": False, "formalized": False}
        if text is None or not text.strip() or not isinstance(cid, str) or not cid:
            reason = ("pinned source plaintext is missing" if text is None else
                      "pinned source plaintext is empty" if not text.strip() else
                      "pinned source CID is missing; absolute row identity retained")
            sections.append({**base, "status": "abstain", "reason": reason, "span_ids": []})
            continue
        unit = f"usc:us:{title}:{section or 'unknown'}:row:{index}"
        # This is a full-section inventory, not sentence parsing or a claim
        # of logical compilation. Every original source byte is retained.
        span_id = f"usc:us:{title}:row:{index}:span:1"
        ids = [span_id]
        spans.append({"id": span_id, "text": text, "status": "uncompiled",
                      "source_ipfs_cid": cid, "source_text_sha256": digest,
                      "source_row_index": index, "byte_start": 0,
                      "byte_end": len(text.encode()), "admitted": False, "formalized": False})
        sections.append({**base, "status": "spans", "span_ids": ids})
        entities.append({"id": unit, "type": "section", "label": f"{title} U.S.C. § {section}",
                         "span_ids": ids, "source_ipfs_cid": cid,
                         "source_text_sha256": digest, "source_row_index": index,
                         "admitted": False, "formalized": False})
    return ({"sections": sections, "spans": spans, "entities": entities},
            {**{key: shard[key] for key in ("title", "start", "end", "count")},
             "span_granularity": "section"},
            {"repository": "justicedao/ipfs_uscode", "revision": contract.REVISION})


def constitution_artifacts(root, contract, task_id):
    text = (root / contract.CONSTITUTION).read_bytes()
    contract.require(contract.sha(text) == contract.CONSTITUTION_SHA256, "retained Constitution input differs")
    source = {"source_id": SOURCE_ID, "sha256": contract.CONSTITUTION_SHA256, "text": text.decode()}
    inventory = contract.owner(root, "constitution_inventory").inventory_constitution(source["text"])
    unit = contract.selector(task_id)
    spans = [{**row, "source_id": SOURCE_ID, "source_text_sha256": contract.CONSTITUTION_SHA256,
              "admitted": False, "formalized": False, "roundtrip_ok": False}
             for row in contract.constitution_spans(inventory, task_id)]
    contract.require(spans, "planned Constitution unit has no source inventory")
    return ({"source": source, "spans": spans},
            {"unit_id": unit, "repeal_treated_as_obligation": False},
            {"source_id": SOURCE_ID, "sha256": contract.CONSTITUTION_SHA256})


def materialize(root, task_id, *, source_parquet=None):
    root = Path(root)
    if not root.is_absolute() or root != root.resolve(strict=True) or not root.is_dir():
        raise ValueError("canonical existing task workspace required")
    contract = contract_owner(root)
    family = contract.kind(task_id)
    contract.require(family in {"uscode", "constitution"}, "only USC/Constitution inventories are materialized")
    plan = json.loads((root / contract.PLAN).read_bytes())
    contract.require(sum(task["task_id"] == task_id for task in plan["tasks"]) == 1,
                     "one exact planned task required")
    task_dir = root / contract.directory(task_id)
    for candidate in (task_dir, *task_dir.parents):
        if candidate == root:
            break
        contract.require(not candidate.is_symlink(), "task output aliases refused")
    artifacts, evidence, source = (uscode_artifacts(root, contract, plan, task_id, source_parquet)
                                   if family == "uscode" else constitution_artifacts(root, contract, task_id))
    names = {label: label + (".zip" if family == "uscode" else ".json") for label in artifacts}
    outputs = {names[label]: zipped_array(label, raw(value)) if family == "uscode" else raw(value)
               for label, value in artifacts.items()}
    receipt = {"schema": contract.SCHEMA, "task_id": task_id, "task_kind": family,
               "status": "inventory", "authority": {"admitted": False, "formalized": False},
               "source": source, "evidence": evidence,
               "artifacts": [{"kind": label,
                              "path": (contract.directory(task_id) / names[label]).as_posix(),
                              "sha256": contract.sha(outputs[names[label]])} for label in sorted(artifacts)]}
    if family == "constitution":
        receipt["authority"]["roundtrip_ok"] = False
    outputs["receipt.json"] = raw(receipt)
    # Check every existing destination before creating anything. Identical
    # bytes are a no-op; a conflicting prior artifact requires separate repair.
    for name, content in outputs.items():
        contract.require(0 < len(content) <= MAX_ARTIFACT_BYTES, "artifact exceeds native size bound")
        path = task_dir / name
        contract.require(not path.is_symlink(), "task output aliases refused")
        if path.exists():
            info = path.lstat()
            contract.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                             and path.read_bytes() == content, "existing inventory artifact conflicts")
    task_dir.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        path = task_dir / name
        if path.exists():
            continue
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    return {"task_id": task_id, "task_kind": family, "artifact_count": len(artifacts),
            "materialized": True, "completion_authority": False, "provider_calls": 0,
            "admitted": False, "formalized": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--corpus-parquet", type=Path)
    args = parser.parse_args(argv)
    try:
        result = materialize(args.root, args.task, source_parquet=args.corpus_parquet)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("LegalIR inventory refused: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
