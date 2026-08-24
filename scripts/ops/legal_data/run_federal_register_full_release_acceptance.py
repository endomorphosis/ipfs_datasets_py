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
SCHEMA = "ipfs_datasets_py/federal-register-full-live-acceptance@1"
CANDIDATE_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_candidate.json")
LIVE_CANDIDATE_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.live.json"
)
INVENTORY_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_inventory.json")
FULLTEXT_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json")
LIVE_FULLTEXT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.live.json"
)
LIVE_FULLTEXT_CHECKPOINT = Path(
    "/var/tmp/lcr-071-fr-fulltext/federal_fulltext_live_checkpoint.json"
)
EVALUATION_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_evaluation.json")
LIVE_EVALUATION_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_evaluation.live.json"
)
ADJACENCY_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.json"
)
LIVE_ADJACENCY_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.live.json"
)
LIVE_VECTORS_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_vectors.live.json"
)
LIVE_GOLD_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_gold.live.json")
ACCEPTANCE_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json"
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


def _load_preferred(
    repository_root: Path, preferred: Path, fallback: Path
) -> tuple[dict[str, Any], str]:
    preferred_path = repository_root / preferred
    if preferred_path.is_file():
        return _load(preferred_path), preferred_path.as_posix()
    fallback_path = repository_root / fallback
    return _load(fallback_path), fallback_path.as_posix()


def inspect_production_readiness(
    *,
    require_live_official: bool,
    require_production_candidate: bool,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    candidate, candidate_source = _load_preferred(
        repository_root, LIVE_CANDIDATE_RELPATH, CANDIDATE_RELPATH
    )
    inventory = _load(repository_root / INVENTORY_RELPATH)
    fulltext = _load(repository_root / FULLTEXT_RELPATH)
    evaluation, evaluation_source = _load_preferred(
        repository_root, LIVE_EVALUATION_RELPATH, EVALUATION_RELPATH
    )
    adjacency, adjacency_source = _load_preferred(
        repository_root, LIVE_ADJACENCY_RELPATH, ADJACENCY_RELPATH
    )

    reasons: list[str] = []
    candidate_kind = str((candidate.get("candidate") or {}).get("kind") or "")
    if candidate.get("authorizing_for_publication") is True:
        reasons.append("candidate authorizing_for_publication must remain false until live e2e")
    if candidate.get("authorizing_hub_upload") is True:
        reasons.append("candidate authorizing_hub_upload is forbidden")
    if require_production_candidate and candidate_kind in FORBIDDEN_KINDS:
        reasons.append(f"candidate kind {candidate_kind!r} cannot satisfy production")
    if require_production_candidate and candidate.get("fixture_only") is True:
        reasons.append("candidate is fixture-only")
    if require_live_official and str(inventory.get("acceptance", {}).get("mode") or "") != "live":
        reasons.append("inventory mode is not live")
    fixture = fulltext.get("fixture") if isinstance(fulltext.get("fixture"), Mapping) else {}
    inventory_documents = int(fixture.get("inventory_documents") or 0)
    official_total = int((inventory.get("acceptance") or {}).get("official_total") or 0)
    live_fulltext: Mapping[str, Any] | None = None
    live_fulltext_source = ""
    for candidate_path in (
        repository_root / LIVE_FULLTEXT_RELPATH,
        LIVE_FULLTEXT_CHECKPOINT,
    ):
        if candidate_path.is_file():
            live_fulltext = _load(candidate_path)
            live_fulltext_source = str(candidate_path)
            break
    live_classified = int((live_fulltext or {}).get("classified") or 0)
    live_admitted = int((live_fulltext or {}).get("full_text_admitted") or 0)
    live_failed = int((live_fulltext or {}).get("failed_final") or 0)
    live_complete = bool(
        live_fulltext
        and live_fulltext.get("sample_identity") is not True
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
        if live_fulltext is not None:
            if live_fulltext.get("sample_identity") is True:
                reasons.append(
                    "live full-text coverage is still the identity sample, not 11784 exhaustion"
                )
            if official_total and live_classified and live_classified < official_total:
                reasons.append(
                    f"live full-text classified {live_classified} against inventory {official_total}"
                )
            if live_fulltext.get("compact_recipe") is True:
                reasons.append("live full-text coverage is still a compact recipe")
        elif require_live_official:
            reasons.append("live full-text coverage receipt is missing")
    if evaluation.get("fixture_only") is True:
        reasons.append("evaluation receipt is fixture-only")
    if adjacency.get("fixture_only") is True:
        reasons.append("adjacency receipt is fixture-only")
    vectors_path = repository_root / LIVE_VECTORS_RELPATH
    gold_path = repository_root / LIVE_GOLD_RELPATH
    vectors: Mapping[str, Any] | None = None
    gold: Mapping[str, Any] | None = None
    vectors_source = ""
    gold_source = ""
    if vectors_path.is_file():
        vectors = _load(vectors_path)
        vectors_source = vectors_path.as_posix()
        if vectors.get("fixture_only") is True:
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
        gold_source = gold_path.as_posix()
        if gold.get("fixture_only") is True:
            reasons.append("gold receipt is fixture-only")
    elif require_live_official:
        reasons.append("live gold receipt is missing")
    if require_live_official:
        if str(evaluation.get("status") or "") not in {"passed", ""}:
            reasons.append(f"evaluation status is {evaluation.get('status')!r}")
        vector_eval = evaluation.get("vector") if isinstance(evaluation.get("vector"), Mapping) else {}
        gold_eval = evaluation.get("gold") if isinstance(evaluation.get("gold"), Mapping) else {}
        if LIVE_EVALUATION_RELPATH.as_posix() in evaluation_source:
            if vector_eval.get("meets_declared_gates") is not True:
                reasons.append("live vector evaluation does not meet declared gates")
            if gold_eval.get("meets_declared_gates") is not True:
                reasons.append("live gold evaluation does not meet declared gates")
    if require_live_official and reasons:
        raise AcceptanceError("; ".join(reasons))
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "mode": "live_official" if require_live_official else "inspect",
        "status": "passed" if not reasons else "blocked",
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "reasons": reasons,
        "candidate_kind": candidate_kind,
        "candidate_source": candidate_source,
        "evaluation_source": evaluation_source,
        "adjacency_source": adjacency_source,
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
    receipt_path = REPOSITORY_ROOT / ACCEPTANCE_RELPATH
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
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
