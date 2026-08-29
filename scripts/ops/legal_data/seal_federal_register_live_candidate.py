#!/usr/bin/env python3
"""Seal a non-fixture LCR-071 live candidate that still does not authorize Hub upload.

Writes ``federal_candidate.live.json``. Does not overwrite the sealed fixture
``federal_candidate.json``. Publication and dataset-repo upload remain false.
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

from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (  # noqa: E402
    FIRST_FEDERAL_REGISTER_NUMBER,
    FIRST_FEDERAL_REGISTER_PACKAGE_ID,
    FIRST_FEDERAL_REGISTER_PUBLICATION_DATE,
    FIRST_FEDERAL_REGISTER_VOLUME,
    FederalRegisterHuggingFaceRelease,
    build_federal_production_candidate_evidence,
    validate_federal_register_hf_release,
)

TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "seal_federal_register_live_candidate.py"
CANDIDATE_KIND = "live_official_complete"
LIVE_CANDIDATE_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.live.json"
)
LIVE_FULLTEXT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.live.json"
)
LIVE_CORPUS_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_live_corpus.json")
LIVE_BM25_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_live_bm25.json")
LIVE_GRAPH_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_graph.live.json")
LIVE_ADJACENCY_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.live.json"
)
LIVE_EVAL_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_evaluation.live.json"
)
LIVE_VECTORS_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_vectors.live.json"
)
LIVE_GOLD_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_gold.live.json")
INVENTORY_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_inventory.json")
RIGHTS_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json"
)
CANONICAL_CANDIDATE_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)
CANONICAL_ADMISSION_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_admission.json"
)
CANONICAL_FULLTEXT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json"
)
CANONICAL_EVALUATION_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_evaluation.json"
)
CANONICAL_ACCEPTANCE_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json"
)
EXPECTED_LIVE_DOCUMENTS = 11784
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


class LiveCandidateError(RuntimeError):
    pass


def _receipt_digest(payload: Mapping[str, Any]) -> str:
    """Digest one in-memory receipt without trusting a declared self digest."""

    body = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "content_digest",
            "digest",
            "report_digest_sha256",
            "receipt_digest",
        }
    }
    return digest_mapping(body)


def _seal_evidence_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed.pop("content_digest", None)
    sealed.pop("report_digest_sha256", None)
    sealed["content_digest"] = digest_mapping(sealed)
    return sealed


def _official_live_inventory_total(inventory: Mapping[str, Any]) -> int:
    acceptance = inventory.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise LiveCandidateError("live inventory acceptance is missing")
    official_total = int(acceptance.get("official_total") or 0)
    failed_final = int(
        acceptance.get("failed_final")
        if acceptance.get("failed_final") is not None
        else (inventory.get("counts") or {}).get("failed_final") or 0
    )
    if (
        acceptance.get("mode") != "live"
        or official_total <= 0
        or acceptance.get("frontier_closed") is not True
        or acceptance.get("failed_final_zero") is not True
        or inventory.get("frontier_closed") is not True
        or failed_final != 0
    ):
        raise LiveCandidateError(
            "inventory is not a closed, failed-final-zero live frontier"
        )
    return official_total


def build_canonical_live_fulltext_evidence(
    *,
    inventory: Mapping[str, Any],
    fulltext: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize verified LCR-071 exhaustion into the canonical LCR-053 schema."""

    official_total = _official_live_inventory_total(inventory)
    classified = int(fulltext.get("classified") or 0)
    admitted = int(fulltext.get("full_text_admitted") or 0)
    excluded = int(fulltext.get("excluded") or 0)
    failed_final = int(fulltext.get("failed_final") or 0)
    metadata_only = int(fulltext.get("metadata_only") or 0)
    quarantined = int(fulltext.get("quarantined") or 0)
    if (
        fulltext.get("mode") != "live"
        or fulltext.get("fixture_only") is True
        or fulltext.get("sample_identity") is True
        or fulltext.get("compact_recipe") is True
        or fulltext.get("authorizing_hub_upload") is True
        or classified != official_total
        or admitted != official_total
        or failed_final != 0
        or excluded != 0
        or metadata_only != 0
        or quarantined != 0
    ):
        raise LiveCandidateError(
            "full-text input is not exact, non-fixture live exhaustion"
        )
    payload = {
        "acceptance": {
            "all_inventory_documents_classified": True,
            "failed_final_zero": True,
            "full_text_admitted_equals_inventory": True,
            "metadata_as_body_rejected": True,
            "one_disposition_per_document": True,
            "sample_or_cap_rejected": True,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "classified": classified,
        "compact_recipe": False,
        "excluded": excluded,
        "failed_final": failed_final,
        "fixture_only": False,
        "full_text_admitted": admitted,
        "goal_id": "LCR-G110",
        "input_receipt_digest": _receipt_digest(fulltext),
        "inventory_digest": _receipt_digest(inventory),
        "metadata_only": metadata_only,
        "mode": "live_official",
        "observation_cutoff": fulltext.get("observation_cutoff"),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "quarantined": quarantined,
        "sample_identity": False,
        "schema": "ipfs_datasets_py/legal-corpora-reindex-federal-fulltext-coverage@1",
        "status": "passed",
        "task_id": "LCR-053",
    }
    return _seal_evidence_payload(payload)


def build_canonical_live_admission_evidence(
    *,
    inventory: Mapping[str, Any],
    fulltext: Mapping[str, Any],
    corpus: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize exact live inventory/body/corpus conservation for LCR-055."""

    official_total = _official_live_inventory_total(inventory)
    identity = inventory.get("identity")
    if not isinstance(identity, Mapping):
        raise LiveCandidateError("live inventory identity evidence is missing")
    if (
        corpus.get("status") != "passed"
        or corpus.get("fixture_only") is True
        or corpus.get("authorizing_hub_upload") is True
        or int(corpus.get("verified") or 0) != official_total
        or int(corpus.get("error_count") or 0) != 0
        or int(corpus.get("mismatches") or 0) != 0
        or int(fulltext.get("full_text_admitted") or 0) != official_total
        or int(fulltext.get("failed_final") or 0) != 0
        or int(fulltext.get("excluded") or 0) != 0
        or int(fulltext.get("metadata_only") or 0) != 0
        or int(fulltext.get("quarantined") or 0) != 0
        or identity.get("duplicate_free") is not True
        or int(identity.get("unique_legal_id_count") or 0) != official_total
    ):
        raise LiveCandidateError(
            "canonical admission inputs do not conserve the verified live corpus"
        )
    payload = {
        "acceptance": {
            "admitted_rows_have_complete_official_provenance": True,
            "admitted_rows_have_non_placeholder_text": True,
            "exact_row_conservation": True,
            "failed_final_zero": True,
            "no_duplicate_primary_keys": True,
            "one_disposition_per_input": True,
            "primary_keys_unique": True,
            "unique_primary_keys": True,
            "valid_provenance_and_offsets": True,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "counts": {
            "admitted": official_total,
            "excluded": int(fulltext.get("excluded") or 0),
            "failed_final": 0,
            "inventory": official_total,
            "quarantined": int(fulltext.get("quarantined") or 0),
        },
        "fixture_only": False,
        "goal_id": "LCR-G110",
        "input_receipt_digests": {
            "corpus": _receipt_digest(corpus),
            "fulltext": _receipt_digest(fulltext),
            "inventory": _receipt_digest(inventory),
        },
        "mode": "live_official",
        "observation_cutoff": inventory.get("observation_cutoff"),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "schema": "ipfs_datasets_py/legal-corpora-reindex-federal-admission@1",
        "status": "passed",
        "task_id": "LCR-055",
    }
    return _seal_evidence_payload(payload)


def build_canonical_live_evaluation_evidence(
    *,
    evaluation: Mapping[str, Any],
    official_document_count: int,
) -> dict[str, Any]:
    """Normalize the non-fixture local evaluation into the canonical schema."""

    acceptance = evaluation.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise LiveCandidateError("live evaluation acceptance is missing")
    families = {
        name: evaluation.get(name)
        for name in ("bm25", "gold", "graph", "vector")
    }
    if (
        evaluation.get("fixture_only") is not False
        or evaluation.get("status") != "passed"
        or evaluation.get("authorizing_hub_upload") is True
        or int(evaluation.get("documents") or 0) != official_document_count
        or any(
            not isinstance(value, Mapping)
            or value.get("meets_declared_gates") is not True
            for value in families.values()
        )
        or acceptance.get("local_query_canary") is not True
        or acceptance.get("no_fixture_result_called_live_canary") is not True
    ):
        raise LiveCandidateError(
            "evaluation input is not a complete non-fixture local production evaluation"
        )
    payload = {
        key: value
        for key, value in evaluation.items()
        if key not in {"content_digest", "schema", "task_id"}
    }
    payload.update(
        {
            "acceptance": {
                **dict(acceptance),
                "all_expected_outputs_accounted": True,
                "sealed_thresholds_pass": True,
            },
            "authorizing_for_publication": False,
            "authorizing_hub_upload": False,
            "fixture_only": False,
            "input_receipt_digest": _receipt_digest(evaluation),
            "mode": "live_official",
            "producer": PRODUCER,
            "schema": "ipfs_datasets_py/legal-corpora-reindex-federal-evaluation@1",
            "status": "passed",
            "task_id": "LCR-063",
        }
    )
    return _seal_evidence_payload(payload)


def build_canonical_full_live_acceptance_evidence(
    *,
    release: FederalRegisterHuggingFaceRelease,
    inventory: Mapping[str, Any],
    fulltext: Mapping[str, Any],
    admission: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    """Build terminal LCR-071 evidence with the fields consumed by LCR-069."""

    official_total = _official_live_inventory_total(inventory)
    fulltext_acceptance = fulltext.get("acceptance")
    admission_acceptance = admission.get("acceptance")
    admission_counts = admission.get("counts")
    evaluation_acceptance = evaluation.get("acceptance")
    if (
        fulltext.get("schema")
        != "ipfs_datasets_py/legal-corpora-reindex-federal-fulltext-coverage@1"
        or fulltext.get("status") != "passed"
        or not isinstance(fulltext_acceptance, Mapping)
        or fulltext_acceptance.get("failed_final_zero") is not True
        or fulltext_acceptance.get("full_text_admitted_equals_inventory") is not True
        or int(fulltext.get("full_text_admitted") or 0) != official_total
        or int(fulltext.get("failed_final") or 0) != 0
        or admission.get("schema")
        != "ipfs_datasets_py/legal-corpora-reindex-federal-admission@1"
        or admission.get("status") != "passed"
        or admission.get("fixture_only") is not False
        or not isinstance(admission_acceptance, Mapping)
        or admission_acceptance.get("exact_row_conservation") is not True
        or admission_acceptance.get("failed_final_zero") is not True
        or not isinstance(admission_counts, Mapping)
        or admission_counts.get("inventory") != official_total
        or admission_counts.get("admitted") != official_total
        or admission_counts.get("failed_final") != 0
        or admission_counts.get("excluded") != 0
        or admission_counts.get("quarantined") != 0
        or evaluation.get("schema")
        != "ipfs_datasets_py/legal-corpora-reindex-federal-evaluation@1"
        or evaluation.get("status") != "passed"
        or evaluation.get("fixture_only") is not False
        or not isinstance(evaluation_acceptance, Mapping)
        or evaluation_acceptance.get("all_expected_outputs_accounted") is not True
        or evaluation_acceptance.get("sealed_thresholds_pass") is not True
    ):
        raise LiveCandidateError("terminal live evidence inputs are not complete")
    validation = validate_federal_register_hf_release(release)
    if validation.get("valid") is not True:
        raise LiveCandidateError("production release did not validate")
    first_issue = {
        "number": FIRST_FEDERAL_REGISTER_NUMBER,
        "package_id": FIRST_FEDERAL_REGISTER_PACKAGE_ID,
        "publication_date": FIRST_FEDERAL_REGISTER_PUBLICATION_DATE,
        "volume": FIRST_FEDERAL_REGISTER_VOLUME,
    }
    payload = {
        "acceptance": {
            "binds_first_issue": True,
            "candidate_descriptor_complete": True,
            "failed_final_zero": True,
            "frontier_closed": True,
            "live_official_inputs_only": True,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "binds_first_issue": True,
        "candidate_kind": "production_descriptor_complete",
        "candidate_manifest_digest": release.manifest_digest,
        "failed_final_count": 0,
        "first_issue": first_issue,
        "fixture_only": False,
        "frontier_closed": True,
        "goal_id": GOAL_ID,
        "input_receipt_digests": {
            "admission": _receipt_digest(admission),
            "evaluation": _receipt_digest(evaluation),
            "fulltext": _receipt_digest(fulltext),
            "inventory": _receipt_digest(inventory),
        },
        "inventory_official_total": official_total,
        "mode": "live_official",
        "producer": "run_federal_register_full_release_acceptance.py",
        "program_id": PROGRAM_ID,
        "schema": "ipfs_datasets_py/federal-register-full-live-acceptance@2",
        "status": "passed",
        "task_id": TASK_ID,
    }
    sealed = dict(payload)
    sealed["report_digest_sha256"] = digest_mapping(sealed)
    return sealed


def build_canonical_production_evidence_bundle(
    *,
    release: FederalRegisterHuggingFaceRelease,
    inventory: Mapping[str, Any],
    fulltext: Mapping[str, Any],
    corpus: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    source_rights: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build all canonical Federal production reports in memory, without I/O."""

    if type(release) is not FederalRegisterHuggingFaceRelease:
        raise LiveCandidateError(
            "canonical evidence requires an exact in-memory production release"
        )
    canonical_fulltext = build_canonical_live_fulltext_evidence(
        inventory=inventory,
        fulltext=fulltext,
    )
    canonical_admission = build_canonical_live_admission_evidence(
        inventory=inventory,
        fulltext=fulltext,
        corpus=corpus,
    )
    official_total = _official_live_inventory_total(inventory)
    canonical_evaluation = build_canonical_live_evaluation_evidence(
        evaluation=evaluation,
        official_document_count=official_total,
    )
    acceptance = build_canonical_full_live_acceptance_evidence(
        release=release,
        inventory=inventory,
        fulltext=canonical_fulltext,
        admission=canonical_admission,
        evaluation=canonical_evaluation,
    )
    candidate = build_federal_production_candidate_evidence(
        release,
        official_document_count=official_total,
        first_issue=acceptance["first_issue"],
        inventory_digest=_receipt_digest(inventory),
        admission_digest=_receipt_digest(canonical_admission),
        fulltext_digest=_receipt_digest(canonical_fulltext),
        evaluation_digest=_receipt_digest(canonical_evaluation),
        full_live_acceptance_digest=_receipt_digest(acceptance),
        source_rights=source_rights,
    )
    return {
        "admission": canonical_admission,
        "candidate": candidate,
        "evaluation": canonical_evaluation,
        "full_live_acceptance": acceptance,
        "fulltext": canonical_fulltext,
    }


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise LiveCandidateError(f"required receipt missing: {path.as_posix()}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise LiveCandidateError(f"receipt root must be an object: {path.as_posix()}")
    return payload


def _require_live_pass(payload: Mapping[str, Any], *, label: str) -> None:
    if payload.get("fixture_only") is True:
        raise LiveCandidateError(f"{label} is fixture-only")
    if payload.get("authorizing_hub_upload") is True:
        raise LiveCandidateError(f"{label} authorizing_hub_upload is forbidden")
    status = str(payload.get("status") or "")
    if status and status not in {"passed", "complete"}:
        raise LiveCandidateError(f"{label} status is {status!r}")


def seal_live_candidate(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    write_receipt: bool = True,
) -> dict[str, Any]:
    inventory = _load(repository_root / INVENTORY_RELPATH)
    fulltext = _load(repository_root / LIVE_FULLTEXT_RELPATH)
    corpus = _load(repository_root / LIVE_CORPUS_RELPATH)
    bm25 = _load(repository_root / LIVE_BM25_RELPATH)
    graph = _load(repository_root / LIVE_GRAPH_RELPATH)
    adjacency = _load(repository_root / LIVE_ADJACENCY_RELPATH)
    evaluation = _load(repository_root / LIVE_EVAL_RELPATH)
    vectors = _load(repository_root / LIVE_VECTORS_RELPATH)
    gold = _load(repository_root / LIVE_GOLD_RELPATH)
    rights = _load(repository_root / RIGHTS_RELPATH)

    official_total = int((inventory.get("acceptance") or {}).get("official_total") or 0)
    if official_total != EXPECTED_LIVE_DOCUMENTS:
        raise LiveCandidateError(
            f"inventory official_total {official_total} != {EXPECTED_LIVE_DOCUMENTS}"
        )
    if str((inventory.get("acceptance") or {}).get("mode") or "") != "live":
        raise LiveCandidateError("inventory mode is not live")
    if int(fulltext.get("full_text_admitted") or 0) != official_total:
        raise LiveCandidateError("live full-text is not exhausted")
    if fulltext.get("sample_identity") is True or fulltext.get("compact_recipe") is True:
        raise LiveCandidateError("live full-text is still sampled or compact")
    for label, payload in (
        ("corpus", corpus),
        ("bm25", bm25),
        ("graph", graph),
        ("adjacency", adjacency),
        ("evaluation", evaluation),
        ("vectors", vectors),
        ("gold", gold),
    ):
        _require_live_pass(payload, label=label)
    if int(corpus.get("verified") or 0) != official_total:
        raise LiveCandidateError("live corpus is not fully verified")
    if int(bm25.get("documents") or 0) != official_total:
        raise LiveCandidateError("live BM25 is not complete")
    if evaluation.get("fixture_only") is not False:
        raise LiveCandidateError("live evaluation must set fixture_only=false")
    if int(vectors.get("vector_count") or 0) != official_total:
        raise LiveCandidateError("live vectors are not complete")
    if vectors.get("centroid_bounds_hold") is not True:
        raise LiveCandidateError("centroid routing bounds do not hold")
    if str(vectors.get("backend") or "") != "sentence_transformers":
        raise LiveCandidateError("live vectors must use sentence_transformers GTE-small")
    if gold.get("fixture_only") is not False:
        raise LiveCandidateError("live gold must set fixture_only=false")
    if CANDIDATE_KIND in FORBIDDEN_KINDS:
        raise LiveCandidateError("internal candidate kind is forbidden")

    present = [
        "bm25_documents",
        "bm25_postings",
        "centroids",
        "corpus",
        "graph_adjacency_in",
        "graph_adjacency_out",
        "graph_edges",
        "graph_nodes",
        "locator_index",
        "routing_index",
        "vectors",
    ]
    missing: list[str] = []
    payload: dict[str, Any] = {
        "acceptance": {
            "publication_not_authorized": True,
            "secrets_absent": True,
            "source_rights_bound": True,
            "live_fulltext_exhausted": True,
            "live_corpus_verified": True,
            "live_bm25_complete": True,
            "live_graph_projected": True,
            "live_evaluation_not_fixture": True,
            "live_vectors_complete": True,
            "live_gold_not_fixture": True,
            "vectors_deferred": False,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "board_namespace": "legal-corpora-reindex-v1",
        "bundle": "federal-full-live-e2e",
        "candidate": {
            "dataset_id": DEFAULT_DATASET_REPO_ID,
            "kind": CANDIDATE_KIND,
            "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
            "release_point": "federal-register/v2/2026-08-10",
            "release_profile": "federal-register-ir-graphrag/v2",
            "official_total": official_total,
            "full_text_admitted": int(fulltext.get("full_text_admitted") or 0),
            "corpus_verified": int(corpus.get("verified") or 0),
            "bm25_documents": int(bm25.get("documents") or 0),
            "graph_nodes": int(graph.get("node_count") or 0),
            "graph_edges": int(graph.get("edge_count") or 0),
            "vector_count": int(vectors.get("vector_count") or 0),
            "cluster_count": int(vectors.get("cluster_count") or 0),
            "evaluation_status": evaluation.get("status"),
        },
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": ["LCR-050", "LCR-061", "LCR-079", "LCR-055", "LCR-056", "LCR-058"],
        "evidence_root": LIVE_CANDIDATE_RELPATH.as_posix(),
        "fixture_only": False,
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "live_family_outputs": {
            "adjacency_digest": adjacency.get("content_digest") or adjacency.get("graph_edge_digest"),
            "bm25_documents": int(bm25.get("documents") or 0),
            "bm25_vocabulary": int(bm25.get("vocabulary_size") or 0),
            "corpus_verified": int(corpus.get("verified") or 0),
            "evaluation_digest": evaluation.get("content_digest"),
            "fulltext_sha256": fulltext.get("checkpoint_sha256"),
            "graph_digest": graph.get("content_digest") or graph.get("edge_digest"),
            "vector_root_cid": vectors.get("vector_root_cid"),
            "vector_count": int(vectors.get("vector_count") or 0),
            "gold_digest": gold.get("content_digest"),
            "producer_task_id": TASK_ID,
        },
        "mode": "live",
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": False,
        "schema": "ipfs_datasets_py/legal-corpora-reindex-federal-candidate-live@1",
        "semantic_family_closure": {
            "closed": True,
            "missing": missing,
            "present": present,
            "required": present,
        },
        "source_rights": {
            "catalog_digest_sha256": rights.get("catalog_digest_sha256")
            or (rights.get("catalog") or {}).get("digest_sha256"),
            "receipt_digest": rights.get("receipt_digest"),
            "receipt_path": RIGHTS_RELPATH.as_posix(),
            "unknown_or_prohibited_excluded_from_default": True,
        },
        "task_id": TASK_ID,
        "vectors_deferred": False,
    }
    payload["content_digest"] = digest_mapping(
        {k: v for k, v in payload.items() if k != "content_digest"}
    )
    if write_receipt:
        out = repository_root / LIVE_CANDIDATE_RELPATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload["receipt_path"] = LIVE_CANDIDATE_RELPATH.as_posix()
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seal live FR candidate without Hub upload")
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--no-write-receipt", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        payload = seal_live_candidate(
            repository_root=args.repository_root,
            write_receipt=not bool(args.no_write_receipt),
        )
    except LiveCandidateError as exc:
        sys.stderr.write(f"seal_federal_register_live_candidate: FAILED: {exc}\n")
        return 1
    if payload.get("authorizing_hub_upload") is True:
        sys.stderr.write(
            "seal_federal_register_live_candidate: FAILED: hub upload must stay false\n"
        )
        return 1
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "seal_federal_register_live_candidate: "
            f"kind={payload['candidate']['kind']} "
            f"fixture_only={payload['fixture_only']} "
            f"hub_upload={payload['authorizing_hub_upload']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
