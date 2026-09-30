#!/usr/bin/env python3
"""Append complete legacy logic receipts to the Hub without rerunning inference.

Original JSON bytes are preserved in deterministic gzip files. Publication is
append-only, compare-and-swap, and verified at the exact resulting commit.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = "justicedao/uscode-autoformal-span-cache"
PREFIX = "autoformal/uscode/reports/v1"
SCHEMA = "uscode-full-logic-report/v1"
MAX_BYTES = 128 * 1024 * 1024
MAX_GZIP_BYTES = MAX_BYTES + 1024 * 1024
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _snapshot(path, bound=MAX_BYTES):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path:
        raise ValueError("report inputs must be unaliased regular files")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= bound:
            raise ValueError("report input exceeds its regular-file byte bound")
        raw = stream.read(bound + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) != before.st_size or _identity(before) != _identity(after)
            or _identity(before) != _identity(path.stat(follow_symlinks=False))):
        raise ValueError("report input changed during capture")
    return raw


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate report JSON key")
        result[key] = value
    return result


def _load(raw):
    def invalid(_):
        raise ValueError("nonfinite report JSON number")
    return json.loads(raw, object_pairs_hook=_object, parse_constant=invalid)


def _descriptor(raw, kind, path, remote):
    return {"kind": kind, "path": str(path), "path_in_repo": remote,
            "bytes": len(raw), "sha256": _sha(raw),
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def _write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.resolve(strict=True) != path.parent.absolute():
        raise ValueError("report output directory must not be aliased")
    try:
        with path.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        if _snapshot(path, max(MAX_GZIP_BYTES, len(raw))) != raw:
            raise ValueError("immutable report artifact has conflicting bytes")


def _document(target):
    document = target.get("document")
    if not isinstance(document, dict):
        return None, {"status": "unavailable", "reason": target.get("reason")}
    # The plain and recursively compressed capture formats have the same
    # lossless document contract. This helper loads no model or parser.
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_logic_artifacts import unpack_document
    if ROOT / "ipfs_datasets_py" not in Path(sys.modules[unpack_document.__module__].__file__).resolve().parents:
        raise ValueError("logic artifact decoder imported from a different checkout")
    document = unpack_document(document)
    compact = _json(document)
    spaced = json.dumps(document, sort_keys=True, allow_nan=False).encode()
    profiles = {"canonical_compact": compact, "json_default_spaced": spaced}
    matched = next((name for name, raw in profiles.items()
        if target.get("document_sha256") == _sha(raw) and target.get("document_bytes") == len(raw)), None)
    return document, {"status": "verified" if matched else "recorded_identity_mismatch_or_absent",
        "matching_serialization_profile": matched,
        "recorded_sha256": target.get("document_sha256"), "recorded_bytes": target.get("document_bytes"),
        "observed_compact_sha256": _sha(compact), "observed_compact_bytes": len(compact)}


def _summary(receipt):
    if not isinstance(receipt, dict) or receipt.get("schema_version") != "legacy-span-cuda-diagnostic/v1":
        raise ValueError("expected a complete legacy CUDA diagnostic receipt")
    if any(receipt.get(key) is not False for key in ("admitted", "formalized", "training_executed")):
        raise ValueError("report must remain unadmitted, unformalized inference evidence")
    rows = receipt.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError("report must contain one to 4096 complete span observations")
    if receipt.get("requested_span_count") != len(rows):
        raise ValueError("requested span count differs from retained rows")
    counts = {"span_count": len(rows), "sample_count": 0, "source_bridge_document_count": 0,
              "compiler_rule_count": 0, "raw_decoder_vector_count": 0,
              "projected_decoder_vector_count": 0, "guided_formula_count": 0}
    spans, documents, seen, families, views = [], [], set(), set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("span observation must be an object")
        span_id, text = row.get("source_span_id"), row.get("text")
        if not isinstance(span_id, str) or not span_id or span_id in seen or not isinstance(text, str) or not text:
            raise ValueError("report source spans must have unique IDs and complete text")
        seen.add(span_id)
        text_sha = _sha(text.encode())
        if row.get("source_sha256") != text_sha:
            raise ValueError("report source text hash differs")
        if any(row.get(key) is not False for key in ("admitted", "formalized")):
            raise ValueError("span report cannot grant admission")
        if isinstance(row.get("lake"), dict) and row["lake"].get("admitted") is not False:
            raise ValueError("span report cannot carry Lake admission")
        compiler = row.get("compiler") or {}
        if not isinstance(compiler, dict) or any(compiler.get(key, False) is not False for key in ("admitted", "formalized")):
            raise ValueError("compiler report cannot grant admission")
        constitution = row.get("constitution_source") is True or any(
            "constitution" in str(row.get(key, "")).lower()
            for key in ("legal_id", "source_span_id", "source_path", "corpus", "dataset_id", "source_url"))
        if constitution and (compiler.get("roundtrip_ok") or compiler.get("roundtrip")):
            raise ValueError("Constitution cannot be marked roundtrip_ok")
        rules = compiler.get("rules")
        if rules is None:
            rules = [compiler["rule"]] if isinstance(compiler.get("rule"), dict) else []
        if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
            raise ValueError("compiler rules must be complete objects")
        counts["compiler_rule_count"] += len(rules)
        counts["sample_count"] += int(bool(row.get("sample_id")))
        for field, count in (("raw_decoder", "raw_decoder_vector_count"),
                             ("safety_projected_decoder", "projected_decoder_vector_count")):
            decoder = row.get(field)
            if isinstance(decoder, dict) and isinstance(decoder.get("embedding"), list):
                counts[count] += 1
        guided = row.get("guided_compiler_observation") or {}
        counts["guided_formula_count"] += len(guided.get("model_formal_outputs", [])) if isinstance(guided, dict) else 0
        target = row.get("logic_target_observation")
        if isinstance(target, dict):
            document, verification = _document(target)
            documents.append({"source_span_id": span_id, **verification})
            if document is not None:
                counts["source_bridge_document_count"] += 1
                document_views = document.get("views", {})
                if isinstance(document_views, dict):
                    views.update(document_views)
                    for view in document_views.values():
                        if isinstance(view, dict):
                            family = view.get("logic_family") or (view.get("metadata") or {}).get("logic_family")
                            if isinstance(family, str) and family:
                                families.add(family)
        spans.append({"source_span_id": span_id, "source_sha256": text_sha,
                      "legal_id": row.get("legal_id"), "sample_id": row.get("sample_id")})
    if receipt.get("sample_count") != counts["sample_count"]:
        raise ValueError("valid sample count differs from retained observations")
    counts["source_bridge_document_unavailable_count"] = sum(item["status"] == "unavailable" for item in documents)
    counts["source_bridge_document_identity_verified_count"] = sum(item["status"] == "verified" for item in documents)
    counts["source_bridge_document_identity_unverified_count"] = sum(
        item["status"] == "recorded_identity_mismatch_or_absent" for item in documents)
    return {"counts": counts, "source_spans": spans, "actual_logic_families": sorted(families),
            "source_document_verification": documents,
            "file_integrity_verified": True, "training_qualification_granted": False,
            "actual_view_names": sorted(views), "checkpoint": receipt.get("checkpoint"),
            "producer_source": receipt.get("producer_source"), "logic_tree": receipt.get("logic_tree"),
            "bridges": receipt.get("bridges"), "timings": receipt.get("timings"),
            "mode": receipt.get("mode"), "campaign": receipt.get("campaign")}


def prepare_report(receipt_path, output_dir):
    """Validate one bounded receipt and preserve its exact bytes in gzip."""
    raw = _snapshot(receipt_path)
    summary = _summary(_load(raw))
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=6) as stream:
        for offset in range(0, len(raw), 1024 * 1024):
            stream.write(raw[offset:offset + 1024 * 1024])
    compressed = buffer.getvalue()
    if len(compressed) > MAX_GZIP_BYTES:
        raise ValueError("compressed report exceeds byte bound")
    root = Path(output_dir).absolute()
    report_name = _sha(compressed) + ".json.gz"
    report_path = root / report_name
    report = _descriptor(compressed, "report", report_path, f"{PREFIX}/reports/{report_name}")
    manifest = {"schema": SCHEMA, "repository_id": REPOSITORY,
        "receipt_schema": "legacy-span-cuda-diagnostic/v1", "compression": "gzip",
        "original": {"sha256": _sha(raw), "bytes": len(raw)},
        "report": {key: value for key, value in report.items() if key not in {"path", "kind"}},
        **summary, "admitted": False, "formalized": False, "training_executed": False,
        "enqueued": False, "wrote_compiler": False}
    manifest_raw = _json(manifest)
    manifest_name = _sha(manifest_raw) + ".json"
    manifest_path = root / manifest_name
    _write(report_path, compressed)
    _write(manifest_path, manifest_raw)
    return {"manifest": _descriptor(manifest_raw, "manifest", manifest_path, f"{PREFIX}/manifests/{manifest_name}"),
            "report": report, "summary": summary, "original": manifest["original"]}


def _field(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _remote(api, descriptors, commit, *, complete):
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise ValueError("Hub must supply an immutable full commit")
    if _field(api.repo_info(repo_id=REPOSITORY, repo_type="dataset", revision=commit), "sha") != commit:
        raise ValueError("Hub resolved a different immutable commit")
    expected = {item["path_in_repo"]: item for item in descriptors}
    seen = set()
    for item in api.get_paths_info(repo_id=REPOSITORY, repo_type="dataset", revision=commit, paths=list(expected)):
        path = _field(item, "path", _field(item, "rfilename"))
        if path not in expected or path in seen:
            raise ValueError("unexpected remote report artifact")
        wanted, lfs = expected[path], _field(item, "lfs")
        digest = _field(lfs, "sha256") if lfs else None
        if ((_field(item, "size") != wanted["bytes"])
                or (digest or _field(item, "blob_id")) != (wanted["sha256"] if digest else wanted["git_blob_sha1"])):
            raise ValueError("immutable remote report hash or size differs")
        seen.add(path)
    if complete and len(seen) != len(expected):
        raise ValueError("immutable commit is missing a report artifact")
    return seen


def publish_report(prepared, *, upload=False, api=None):
    """CAS append the two exact files and verify their immutable remote hashes."""
    files = []
    for kind in ("report", "manifest"):
        item = prepared[kind]
        raw = _snapshot(item["path"], MAX_GZIP_BYTES)
        actual = _descriptor(raw, kind, item["path"], item["path_in_repo"])
        if actual != item:
            raise ValueError("prepared report artifact changed before publication")
        expected_remote = f"{PREFIX}/{'reports' if kind == 'report' else 'manifests'}/{item['sha256']}{'.json.gz' if kind == 'report' else '.json'}"
        if item["path_in_repo"] != expected_remote:
            raise ValueError("report publication escaped its immutable namespace")
        files.append((item, raw))
    result = {"schema": "uscode-full-logic-report-publication/v1", "repository_id": REPOSITORY,
        "manifest": prepared["manifest"], "report": prepared["report"], "original": prepared["original"],
        "uploaded": False, "dry_run": not upload, "admitted": False, "formalized": False,
        "training_executed": False, "enqueued": False, "wrote_compiler": False}
    if not upload:
        return result
    from huggingface_hub import HfApi, CommitOperationAdd
    api = api or HfApi()
    descriptors = [item for item, _ in files]
    publication_path = Path(prepared["manifest"]["path"] + ".publication.json")
    if publication_path.exists():
        saved = _load(_snapshot(publication_path, 1024 * 1024))
        if any(saved.get(key) != result[key] for key in result if key not in {"uploaded", "dry_run"}) or saved.get("uploaded") is not True or saved.get("dry_run") is not False:
            raise ValueError("retained report publication differs")
        _remote(api, descriptors, saved["commit_sha"], complete=True)
        return saved
    parent = _field(api.repo_info(repo_id=REPOSITORY, repo_type="dataset"), "sha")
    present = _remote(api, descriptors, parent, complete=False)
    operations = [CommitOperationAdd(path_in_repo=item["path_in_repo"], path_or_fileobj=raw)
                  for item, raw in files if item["path_in_repo"] not in present]
    commit = parent
    if operations:
        commit = _field(api.create_commit(repo_id=REPOSITORY, repo_type="dataset", parent_commit=parent,
            operations=operations, commit_message="Append complete lossless legacy formal-logic reports"), "oid")
    _remote(api, descriptors, commit, complete=True)
    result.update(uploaded=True, commit_sha=commit, parent_commit=parent)
    _write(publication_path, _json(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args(argv)
    for path in args.receipt:
        prepared = prepare_report(path, args.output_dir)
        result = publish_report(prepared, upload=args.upload)
        print(json.dumps({**result, "summary": prepared["summary"]}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
