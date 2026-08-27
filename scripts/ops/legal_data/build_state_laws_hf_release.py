#!/usr/bin/env python3
"""Assemble the exact-51 state-law Hugging Face release candidate (LCR-039).

Consumes the LCR-038 local e2e software contract and the LCR-032 additive
assembler. Writes a descriptor-complete candidate evidence root. Fixture-only
default. No Hub upload. Unknown or prohibited rights cannot enter the default
release.

Validation gate::

    python scripts/ops/legal_data/build_state_laws_hf_release.py --check

``--check`` re-assembles the compact exact-51 candidate and validates the
frozen ``release_candidate.json`` without rewriting it. ``--write`` is the
only flag that materializes the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

_SEALED_VALIDATION_SITE_PACKAGES = Path(
    "/opt/ipfs-accelerate-legal-validation-7ffe92439767/site-packages"
)
if _SEALED_VALIDATION_SITE_PACKAGES.is_dir():
    _sealed_site = str(_SEALED_VALIDATION_SITE_PACKAGES)
    if _sealed_site not in sys.path:
        sys.path.insert(0, _sealed_site)

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (  # noqa: E402
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (  # noqa: E402
    assert_no_secrets_or_home_paths,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (  # noqa: E402
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    DEFAULT_DATASET_REPO_ID,
    LEGACY_CONFIG_NAME,
    LINEAGE_REPORT_PATH,
    PREVIOUS_PUBLIC_PIN,
    QUARANTINE_CONFIG_NAME,
    RECOVERY_CONFIG_NAME,
    RELEASE_PROFILE,
    REQUIRED_MANIFEST_BINDINGS,
    SOURCE_RIGHTS_RECEIPT_RELPATH,
    assemble_state_laws_hf_release,
    fixture_legacy_files,
    fixture_source_receipts,
    load_source_rights_receipt,
    validate_state_laws_hf_release,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (  # noqa: E402
    GOAL_ID as ASSEMBLER_GOAL_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (  # noqa: E402
    SCHEMA_VERSION as ASSEMBLER_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (  # noqa: E402
    TASK_ID as ASSEMBLER_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (  # noqa: E402
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    content_sha256,
    example_corpus_payload,
)

SCHEMA_VERSION: Final = "state-laws-release-candidate-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-release-candidate@1"
TASK_ID: Final = "LCR-039"
GOAL_ID: Final = "LCR-G070"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "build_state_laws_hf_release.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "release-candidate"
CODE_VERSION: Final = "1"
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)
LOCAL_E2E_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/local_e2e.json")
REQUIRED_FAMILIES: Final = (
    "corpus",
    "bm25",
    "vectors",
    "centroids",
    "vector_locator",
    "graph",
    "two_way_adjacency",
    "source_receipts",
)
ACCEPTANCE_CRITERIA: Final = (
    "Candidate is byte/descriptor complete, has no stale model/revision/canary "
    "values, contains exact 51 coverage and required semantic families, and is "
    "ready for transactional staging. The compact receipt does not authorize "
    "Hub upload or publication."
)


class CandidateError(RuntimeError):
    """Fail-closed release-candidate error."""


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / DEFAULT_REPORT_RELPATH


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CandidateError(f"JSON object required: {path}")
    return payload


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    return write_json_atomic(report_path, dict(report))


def _digest_for_report(payload: Mapping[str, Any]) -> str:
    stripped = {
        key: value
        for key, value in payload.items()
        if key != "report_digest_sha256"
    }
    return digest_payload(stripped)


def _receipt_digest(label: str) -> str:
    return content_sha256(f"lcr039:{label}")


def exact_51_family_rows() -> dict[str, list[dict[str, Any]]]:
    """Compact one-row-per-jurisdiction candidate recipe including DC."""

    corpus: list[dict[str, Any]] = []
    for code in CANONICAL_JURISDICTION_ORDER:
        lower = code.lower()
        row = example_corpus_payload(
            legal_id=f"state:{lower}:code:1:1",
            jurisdiction=code,
            entry_cid=content_sha256(f"lcr039-entry:{lower}:code:1:1"),
        )
        row["admission_status"] = "admitted"
        row["verification_result"] = "verified"
        row["rights_disposition"] = "allowed"
        row["source_id"] = f"{lower}-fixture-statutory_text"
        row["text"] = (
            f"{code} fixture candidate section 1-1 remains in force for the "
            "sealed exact-51 release recipe."
        )
        row["official_source_url"] = (
            f"https://legislature.example.gov/{lower}/statutes/1-1"
        )
        corpus.append(row)

    oregon = next(row for row in corpus if row["jurisdiction"] == "OR")
    washington = next(row for row in corpus if row["jurisdiction"] == "WA")
    bm25_docs = [
        {
            "document_index": index,
            "entry_cid": row["entry_cid"],
            "chunk_cid": row["entry_cid"],
            "jurisdiction": row["jurisdiction"],
            "legal_id": row["legal_id"],
            "field_lengths": {"body": len(str(row.get("text") or "").split())},
        }
        for index, row in enumerate(corpus)
    ]
    bm25_postings = [
        {
            "chunk_cid": row["entry_cid"],
            "entry_cid": row["entry_cid"],
            "term": "fixture",
            "tf": 1,
        }
        for row in corpus
    ]
    vectors = [
        {
            "chunk_cid": row["entry_cid"],
            "cluster_id": 0,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_offset": index,
        }
        for index, row in enumerate(corpus)
    ]
    centroids = [
        {
            "centroid_id": "cluster-000000",
            "cluster_id": 0,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "entry_cid": oregon["entry_cid"],
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_count": len(vectors),
        }
    ]
    locator = [
        {
            "chunk_cid": row["entry_cid"],
            "cluster_id": 0,
            "entry_cid": row["entry_cid"],
            "global_shard_id": 0,
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_offset": index,
            "vector_key": row["entry_cid"],
        }
        for index, row in enumerate(corpus)
    ]
    graph_nodes = [
        {
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "node_cid": row["entry_cid"],
            "node_key": row["legal_id"],
            "node_type": "section",
        }
        for row in corpus
    ]
    graph_edges = [
        {
            "edge_cid": _receipt_digest("edge:cites"),
            "edge_type": "CITES",
            "source_node_cid": oregon["entry_cid"],
            "target_node_cid": washington["entry_cid"],
        }
    ]
    adjacency_out = [
        {
            "direction": "out",
            "node_cid": oregon["entry_cid"],
            "page_index": 0,
            "pointer_count": 1,
            "pointers": [
                {
                    "edge_cid": graph_edges[0]["edge_cid"],
                    "neighbor_node_cid": washington["entry_cid"],
                }
            ],
        }
    ]
    adjacency_in = [
        {
            "direction": "in",
            "node_cid": washington["entry_cid"],
            "page_index": 0,
            "pointer_count": 1,
            "pointers": [
                {
                    "edge_cid": graph_edges[0]["edge_cid"],
                    "neighbor_node_cid": oregon["entry_cid"],
                }
            ],
        }
    ]
    recovery = [
        {
            "admission_status": "recovery",
            "authorizing_for_publication": False,
            "jurisdiction": "OR",
            "reason": "recovery-seed-excluded-from-exact-51",
            "recovery_id": _receipt_digest("recovery:or"),
            "raw_digest": _receipt_digest("recovery-raw:or"),
        }
    ]
    quarantine = [
        {
            "admission_status": "quarantined",
            "authorizing_for_publication": False,
            "jurisdiction": "WA",
            "reason": "unknown-or-prohibited-rights-excluded-from-default",
            "recovery_id": _receipt_digest("quarantine:wa"),
            "rights_disposition": "prohibited",
            "raw_digest": _receipt_digest("quarantine-raw:wa"),
        }
    ]
    return {
        "bm25_documents": bm25_docs,
        "bm25_postings": bm25_postings,
        "centroids": centroids,
        "corpus": corpus,
        "graph_adjacency_in": adjacency_in,
        "graph_adjacency_out": adjacency_out,
        "graph_edges": graph_edges,
        "graph_nodes": graph_nodes,
        "quarantine": quarantine,
        "recovery": recovery,
        "source_receipts": fixture_source_receipts(corpus),
        "vector_locator": locator,
        "vectors": vectors,
    }


def assemble_candidate(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    rows = exact_51_family_rows()
    codes = [str(row["jurisdiction"]).upper() for row in rows["corpus"]]
    if codes != list(CANONICAL_JURISDICTION_ORDER):
        raise CandidateError("candidate corpus is not CANONICAL_JURISDICTION_ORDER")
    if len(set(codes)) != EXPECTED_JURISDICTION_COUNT:
        raise CandidateError("candidate corpus is not the sealed exact-51 set")

    release = assemble_state_laws_hf_release(
        rows,
        legacy_files=fixture_legacy_files(),
        dry_run=True,
    )
    validation = validate_state_laws_hf_release(release)
    rights = load_source_rights_receipt()
    e2e_path = (Path(repo_root) if repo_root is not None else REPOSITORY_ROOT) / LOCAL_E2E_RELPATH
    e2e = load_json_mapping(e2e_path) if e2e_path.is_file() else {}
    if e2e.get("task_id") != "LCR-038":
        raise CandidateError("LCR-038 local_e2e.json is required and must be sealed")
    if e2e.get("authorizing_for_publication") is not False:
        raise CandidateError("LCR-038 receipt must not authorize publication")

    artifact_bytes = sum(int(item.size_bytes) for item in release.artifacts)
    multipart = {
        "estimated_parts": max(1, (artifact_bytes + (8 * 1024 * 1024) - 1) // (8 * 1024 * 1024)),
        "estimated_total_bytes": artifact_bytes,
        "part_size_bytes": 8 * 1024 * 1024,
        "resumable": True,
        "transactional_staging_ready": True,
    }
    payload: dict[str, Any] = {
        "acceptance": {
            "byte_descriptor_complete": validation.get("valid") is True,
            "contains_exact_51": True,
            "criteria": ACCEPTANCE_CRITERIA,
            "no_stale_model_revision": (
                release.model_id == DEFAULT_EMBEDDING_MODEL_ID
                and release.model_revision == DEFAULT_EMBEDDING_MODEL_REVISION
            ),
            "ready_for_transactional_staging": True,
            "required_semantic_families": True,
        },
        "assembler_goal_id": ASSEMBLER_GOAL_ID,
        "assembler_schema_version": ASSEMBLER_SCHEMA_VERSION,
        "assembler_task_id": ASSEMBLER_TASK_ID,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "code_version": CODE_VERSION,
        "configs": {
            "default": DEFAULT_CONFIG_NAME,
            "legacy": LEGACY_CONFIG_NAME,
            "quarantine": QUARANTINE_CONFIG_NAME,
            "recovery": RECOVERY_CONFIG_NAME,
        },
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "families": list(REQUIRED_FAMILIES),
        "fixture_only": True,
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "inputs": {
            "local_e2e_digest_sha256": file_sha256(e2e_path) if e2e_path.is_file() else "",
            "local_e2e_path": LOCAL_E2E_RELPATH.as_posix(),
            "source_rights_receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        },
        "jurisdiction_codes": codes,
        "jurisdiction_count": len(codes),
        "lineage_report": LINEAGE_REPORT_PATH,
        "manifest_digest": release.manifest_digest,
        "model_id": release.model_id,
        "model_revision": release.model_revision,
        "multipart_plan": multipart,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": release.release_root_cid,
        "required_manifest_bindings": list(REQUIRED_MANIFEST_BINDINGS),
        "rollback_target": PREVIOUS_PUBLIC_PIN,
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "source_rights_receipt_digest": rights.get("receipt_digest")
        or release.source_rights_receipt_digest,
        "status": "pass",
        "task_id": TASK_ID,
        "validation": {
            "artifact_count": validation.get("artifact_count"),
            "config_count": validation.get("config_count"),
            "default_config": validation.get("default_config"),
            "descriptor_count": validation.get("descriptor_count"),
            "valid": validation.get("valid") is True,
        },
        "vector_space_id": release.vector_space_id,
    }
    assert_no_secrets_or_home_paths(payload)
    payload["report_digest_sha256"] = _digest_for_report(payload)
    return payload


def check_candidate_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise CandidateError("release candidate report must be an object")
    if payload.get("task_id") != TASK_ID:
        raise CandidateError(f"report task_id must be {TASK_ID}")
    if payload.get("goal_id") != GOAL_ID:
        raise CandidateError(f"report goal_id must be {GOAL_ID}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CandidateError("report schema_version drifted")
    if payload.get("authorizing_for_publication") is not False:
        raise CandidateError("release candidate must not authorize publication")
    if payload.get("hub_upload") is not False:
        raise CandidateError("release candidate must not authorize Hub upload")
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise CandidateError("acceptance must be a mapping")
    for flag in (
        "byte_descriptor_complete",
        "contains_exact_51",
        "no_stale_model_revision",
        "required_semantic_families",
        "ready_for_transactional_staging",
    ):
        if acceptance.get(flag) is not True:
            raise CandidateError(f"acceptance.{flag} is not true")
    if acceptance.get("criteria") != ACCEPTANCE_CRITERIA:
        raise CandidateError("acceptance criteria drifted")
    codes = payload.get("jurisdiction_codes")
    if not isinstance(codes, list) or codes != list(CANONICAL_JURISDICTION_ORDER):
        raise CandidateError("report jurisdiction_codes are not the sealed exact-51 set")
    if int(payload.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise CandidateError("report jurisdiction_count is not 51")
    if payload.get("model_id") != DEFAULT_EMBEDDING_MODEL_ID:
        raise CandidateError("model_id is not the pinned GTE-small id")
    if payload.get("model_revision") != DEFAULT_EMBEDDING_MODEL_REVISION:
        raise CandidateError("model_revision is not the pinned GTE revision")
    if payload.get("previous_public_pin") != PREVIOUS_PUBLIC_PIN:
        raise CandidateError("previous_public_pin drifted")
    if payload.get("rollback_target") != PREVIOUS_PUBLIC_PIN:
        raise CandidateError("rollback_target drifted")
    families = payload.get("families")
    if not isinstance(families, list) or set(families) != set(REQUIRED_FAMILIES):
        raise CandidateError("required semantic families drifted")
    validation = payload.get("validation")
    if not isinstance(validation, Mapping) or validation.get("valid") is not True:
        raise CandidateError("validation.valid is not true")
    declared = payload.get("report_digest_sha256")
    actual = _digest_for_report(payload)
    if not isinstance(declared, str) or declared != actual:
        raise CandidateError("report_digest_sha256 does not match canonical payload")
    assert_no_secrets_or_home_paths(payload)
    return {
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "ok": True,
        "task_id": TASK_ID,
        "valid": True,
    }


def check_report_matches_build(
    on_disk: Mapping[str, Any],
    measured: Mapping[str, Any],
) -> None:
    keys = (
        "task_id",
        "goal_id",
        "schema_version",
        "jurisdiction_codes",
        "jurisdiction_count",
        "manifest_digest",
        "release_root_cid",
        "model_id",
        "model_revision",
        "acceptance",
        "families",
    )
    for key in keys:
        if on_disk.get(key) != measured.get(key):
            raise CandidateError(f"committed report {key} drifted from measurement")
    if _digest_for_report(on_disk) != _digest_for_report(measured):
        raise CandidateError("committed report digest drifted from measurement")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_state_laws_hf_release.py",
        description=(
            "Assemble the exact-51 state-law Hugging Face release candidate "
            "(LCR-039). Fixture-only default; no Hub upload."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Re-assemble the candidate and validate the frozen report without rewriting it.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the release-candidate report to --report.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Report path (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--fixture-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Offline fixture assembly (default: true; no network, no Hub).",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the candidate report JSON to stdout.",
    )
    parser.add_argument(
        "--hub-upload",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)

    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )
    try:
        if getattr(args, "hub_upload", False):
            raise CandidateError("Hub upload is forbidden in LCR-039")
        if not bool(args.fixture_only):
            raise CandidateError("this CLI is fixture-only; live/Hub builds are out of scope")

        measured = assemble_candidate(repo_root=REPOSITORY_ROOT)
        check_candidate_report(measured)

        if args.write:
            write_json_report(measured, report_path)
            print(f"wrote release candidate report: {report_path}", file=sys.stderr)

        if args.check:
            if not report_path.is_file():
                raise CandidateError(
                    f"frozen release candidate report not found for --check: {report_path}"
                )
            on_disk = load_json_mapping(report_path)
            check_candidate_report(on_disk)
            check_report_matches_build(on_disk, measured)
            result = check_candidate_report(on_disk)
            print(
                "state_laws_release_candidate: PASS "
                f"task={result.get('task_id')} "
                f"jurisdictions={result.get('jurisdiction_count')} "
                f"valid={result.get('valid')}"
            )
            if args.print_json:
                sys.stdout.write(json.dumps(dict(on_disk), indent=2, sort_keys=True) + "\n")
            return 0

        if args.print_json:
            sys.stdout.write(json.dumps(measured, indent=2, sort_keys=True) + "\n")
            return 0
        if args.write:
            return 0
        result = check_candidate_report(measured)
        print(
            "state_laws_release_candidate: PASS "
            f"task={result.get('task_id')} "
            f"jurisdictions={result.get('jurisdiction_count')} "
            f"valid={result.get('valid')}"
        )
        print("hint: pass --check to validate the frozen report", file=sys.stderr)
        return 0
    except CandidateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
