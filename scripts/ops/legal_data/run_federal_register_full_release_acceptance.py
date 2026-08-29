#!/usr/bin/env python3
"""Fail-closed LCR-071 Federal Register full-live production acceptance.

Default ``--check`` inspects the committed candidate/inventory/full-text
receipts and refuses every fixture-only, sampled, capped, metadata-as-body,
or partial-checkpoint path. Live official production cannot be satisfied by
the compact descriptor candidate.

This entrypoint never uploads to Hub.

Examples
--------
Hermetic fail-closed gate::

    python scripts/ops/legal_data/run_federal_register_full_release_acceptance.py \\
        --full --require-live-official --require-production-candidate --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "run_federal_register_full_release_acceptance.py"
SCHEMA = "ipfs_datasets_py/federal-register-full-live-acceptance@2"
CANDIDATE_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_candidate.json")
INVENTORY_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_inventory.json")
FULLTEXT_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json")
EVALUATION_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_evaluation.json")
ADJACENCY_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.json"
)
LIVE_VECTORS_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_vectors.live.json"
)
LIVE_GOLD_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_gold.live.json")
ACCEPTANCE_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json"
)
INPUT_RELPATHS = (
    CANDIDATE_RELPATH,
    INVENTORY_RELPATH,
    FULLTEXT_RELPATH,
    EVALUATION_RELPATH,
    ADJACENCY_RELPATH,
    LIVE_VECTORS_RELPATH,
    LIVE_GOLD_RELPATH,
)
FORBIDDEN_KINDS = frozenset(
    {
        "fixture",
        "fixture_descriptor_complete",
        "compact_recipe",
        "sample",
        "sampled",
        "capped",
        "partial_checkpoint",
        "metadata_as_body",
        "stale_success",
        "failed_final",
    }
)


class AcceptanceError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AcceptanceError(f"required receipt is missing: {path.as_posix()}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"receipt is not strict JSON: {path.as_posix()}") from exc
    if type(payload) is not dict:
        raise AcceptanceError(f"receipt root must be an object: {path.as_posix()}")
    return payload


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _input_file_sha256(repository_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relpath in INPUT_RELPATHS:
        path = repository_root / relpath
        if path.is_symlink() or not path.is_file():
            raise AcceptanceError(
                f"canonical input receipt is missing or unsafe: {relpath.as_posix()}"
            )
        result[relpath.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _report_digest(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("report_digest_sha256", None)
    return hashlib.sha256(_canonical_json_bytes(body)).hexdigest()


def inspect_production_readiness(
    *,
    require_live_official: bool,
    require_production_candidate: bool,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    input_file_sha256 = _input_file_sha256(repository_root)
    candidate = _load(repository_root / CANDIDATE_RELPATH)
    inventory = _load(repository_root / INVENTORY_RELPATH)
    fulltext = _load(repository_root / FULLTEXT_RELPATH)
    evaluation = _load(repository_root / EVALUATION_RELPATH)
    adjacency = _load(repository_root / ADJACENCY_RELPATH)

    reasons: list[str] = []
    candidate_kind = str((candidate.get("candidate") or {}).get("kind") or "")
    if candidate.get("authorizing_for_publication") is True:
        reasons.append("candidate authorizing_for_publication must remain false until live e2e")
    if candidate.get("authorizing_hub_upload") is True:
        reasons.append("candidate authorizing_hub_upload is forbidden")
    if require_production_candidate and candidate_kind in FORBIDDEN_KINDS:
        reasons.append(f"candidate kind {candidate_kind!r} cannot satisfy production")
    if require_production_candidate and candidate.get("fixture_only") is not False:
        reasons.append("candidate is fixture-only")
    if require_live_official and candidate.get("mode") != "live_official":
        reasons.append("canonical candidate mode is not live_official")
    if require_live_official and str(inventory.get("acceptance", {}).get("mode") or "") != "live":
        reasons.append("inventory mode is not live")
    if require_live_official and fulltext.get("fixture_only") is not False:
        reasons.append("canonical full-text coverage is not explicit non-fixture evidence")
    fixture = fulltext.get("fixture") if isinstance(fulltext.get("fixture"), Mapping) else {}
    inventory_documents = int(fixture.get("inventory_documents") or 0)
    official_total = int((inventory.get("acceptance") or {}).get("official_total") or 0)
    live_fulltext: Mapping[str, Any] = fulltext
    live_fulltext_source = FULLTEXT_RELPATH.as_posix()
    live_classified = int((live_fulltext or {}).get("classified") or 0)
    live_admitted = int((live_fulltext or {}).get("full_text_admitted") or 0)
    live_failed = int((live_fulltext or {}).get("failed_final") or 0)
    live_complete = bool(
        live_fulltext.get("sample_identity") is not True
        and live_fulltext.get("compact_recipe") is not True
        and official_total
        and live_classified == official_total
        and live_admitted == official_total
        and live_failed == 0
    )
    if not live_complete:
        if fulltext.get("compact_recipe") is True:
            reasons.append("full-text coverage is a compact recipe, not live exhaustion")
        if (
            require_live_official
            and official_total
            and inventory_documents
            and inventory_documents < official_total
        ):
            reasons.append(
                f"full-text coverage {inventory_documents} is sampled against inventory {official_total}"
            )
        if live_fulltext.get("sample_identity") is True:
            reasons.append(
                "canonical full-text coverage is still the identity sample, not full exhaustion"
            )
        if official_total and live_classified and live_classified < official_total:
            reasons.append(
                f"canonical full-text classified {live_classified} against inventory {official_total}"
            )
        if live_fulltext.get("compact_recipe") is True:
            reasons.append("canonical full-text coverage is still a compact recipe")
    if evaluation.get("fixture_only") is not False:
        reasons.append("evaluation receipt is fixture-only")
    if adjacency.get("fixture_only") is not False:
        reasons.append("adjacency receipt is fixture-only")
    vectors_path = repository_root / LIVE_VECTORS_RELPATH
    gold_path = repository_root / LIVE_GOLD_RELPATH
    vectors: Mapping[str, Any] | None = None
    gold: Mapping[str, Any] | None = None
    vectors_source = ""
    gold_source = ""
    if vectors_path.is_file():
        vectors = _load(vectors_path)
        vectors_source = LIVE_VECTORS_RELPATH.as_posix()
        if vectors.get("fixture_only") is not False:
            reasons.append("vector receipt is fixture-only")
        if require_live_official:
            if int(vectors.get("vector_count") or 0) != official_total:
                reasons.append(
                    f"live vectors {int(vectors.get('vector_count') or 0)} against inventory {official_total}"
                )
            if vectors.get("centroid_bounds_hold") is not True:
                reasons.append("centroid routing bounds do not hold")
            if require_production_candidate and str(vectors.get("backend") or "") != "sentence_transformers":
                reasons.append("production vectors must use sentence_transformers GTE-small")
    elif require_live_official:
        reasons.append("live vector receipt is missing")
    if gold_path.is_file():
        gold = _load(gold_path)
        gold_source = LIVE_GOLD_RELPATH.as_posix()
        if gold.get("fixture_only") is not False:
            reasons.append("gold receipt is fixture-only")
    elif require_live_official:
        reasons.append("live gold receipt is missing")
    if require_live_official:
        if str(evaluation.get("status") or "") not in {"passed", ""}:
            reasons.append(f"evaluation status is {evaluation.get('status')!r}")
        vector_eval = evaluation.get("vector") if isinstance(evaluation.get("vector"), Mapping) else {}
        gold_eval = evaluation.get("gold") if isinstance(evaluation.get("gold"), Mapping) else {}
        if vector_eval.get("meets_declared_gates") is not True:
            reasons.append("canonical vector evaluation does not meet declared gates")
        if gold_eval.get("meets_declared_gates") is not True:
            reasons.append("canonical gold evaluation does not meet declared gates")
    if require_live_official and reasons:
        raise AcceptanceError("; ".join(reasons))
    production_pass = bool(
        require_live_official and require_production_candidate and not reasons
    )
    report = {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "mode": "live_official" if require_live_official else "inspect",
        "status": "passed" if production_pass else "blocked",
        "dirty": False,
        "fixture_only": not production_pass,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "input_file_sha256": input_file_sha256,
        "reasons": reasons,
        "candidate_kind": candidate_kind,
        "candidate_source": CANDIDATE_RELPATH.as_posix(),
        "evaluation_source": EVALUATION_RELPATH.as_posix(),
        "adjacency_source": ADJACENCY_RELPATH.as_posix(),
        "vectors_source": vectors_source,
        "gold_source": gold_source,
        "inventory_mode": (inventory.get("acceptance") or {}).get("mode"),
        "inventory_official_total": official_total,
        "fulltext_compact_recipe": bool(fulltext.get("compact_recipe")),
        "fulltext_inventory_documents": inventory_documents,
        "live_fulltext_source": live_fulltext_source,
        "live_fulltext_classified": live_classified,
        "live_fulltext_admitted": live_admitted,
        "live_fulltext_complete": live_complete,
    }
    report["report_digest_sha256"] = _report_digest(report)
    return report


def check_full_live_acceptance_report(
    payload: Mapping[str, Any],
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Source-attest the exact seven canonical inputs and the @2 receipt."""

    if type(payload) is not dict:
        raise AcceptanceError("full-live acceptance report must be an exact object")
    if (
        payload.get("schema") != SCHEMA
        or payload.get("task_id") != TASK_ID
        or payload.get("mode") != "live_official"
        or payload.get("status") != "passed"
        or payload.get("fixture_only") is not False
        or payload.get("dirty") is not False
        or payload.get("authorizing_for_publication") is not False
        or payload.get("authorizing_hub_upload") is not False
    ):
        raise AcceptanceError(
            "full-live acceptance report is not clean, passed, non-authorizing @2 evidence"
        )
    expected_inputs = _input_file_sha256(repository_root)
    observed_inputs = payload.get("input_file_sha256")
    if type(observed_inputs) is not dict or observed_inputs != expected_inputs:
        raise AcceptanceError(
            "full-live acceptance input_file_sha256 is missing, extra, or stale"
        )
    digest = str(payload.get("report_digest_sha256") or "").strip().casefold()
    if len(digest) != 64 or _report_digest(payload) != digest:
        raise AcceptanceError("full-live acceptance self digest is stale")
    expected = inspect_production_readiness(
        require_live_official=True,
        require_production_candidate=True,
        repository_root=repository_root,
    )
    if _canonical_json_bytes(payload) != _canonical_json_bytes(expected):
        raise AcceptanceError(
            "full-live acceptance report differs from current canonical semantics"
        )
    return {"ok": True, "report_digest_sha256": digest}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed LCR-071 Federal Register full-live acceptance"
    )
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--require-live-official", action="store_true")
    parser.add_argument("--require-production-candidate", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write(
            "run_federal_register_full_release_acceptance: FAILED: --check is required\n"
        )
        return 2
    if args.require_live_official and not args.full:
        sys.stderr.write(
            "run_federal_register_full_release_acceptance: FAILED: "
            "--require-live-official requires --full\n"
        )
        return 2
    try:
        report = inspect_production_readiness(
            require_live_official=bool(args.require_live_official),
            require_production_candidate=bool(args.require_production_candidate),
            repository_root=REPOSITORY_ROOT,
        )
    except AcceptanceError as exc:
        sys.stderr.write(f"run_federal_register_full_release_acceptance: FAILED: {exc}\n")
        return 1
    if report["status"] == "passed":
        check_full_live_acceptance_report(report, repository_root=REPOSITORY_ROOT)
        receipt_path = REPOSITORY_ROOT / ACCEPTANCE_RELPATH
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = receipt_path.with_name(f".{receipt_path.name}.partial")
        temporary.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(receipt_path)
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "run_federal_register_full_release_acceptance: "
            f"{report['status'].upper()} mode={report['mode']} "
            f"candidate_kind={report['candidate_kind']}\n"
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
