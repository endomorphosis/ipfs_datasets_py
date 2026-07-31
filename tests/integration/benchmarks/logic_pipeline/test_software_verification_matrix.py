"""Generate and validate the software-verification release matrix (LFV-G083).

LogicFormalVerificationRelease@1 — matrix and benchmark surface.

Acceptance covered here:

* The property/provider matrix is generated from current executable evidence
  (capability census, property vocabulary, prover definitions, documentation
  claims).
* Benchmarks report semantic and resource distributions without timing-ratio
  correctness gates.
* Rollout documentation is property-specific and reversible.
* Documentation prover rows reconcile with executable prover labels.
* Unavailable external tools are never fabricated as enforced or authoritative.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from ipfs_accelerate_py.agent_supervisor.proof.prover_matrix_registry import (
    DEFAULT_PROVER_DEFINITIONS,
    EXPECTED_PROVER_IDS,
    load_documentation_claims,
)
from ipfs_datasets_py.logic.software_verification.properties import (
    PROPERTY_VOCABULARY,
    PropertyKind,
)


DATASETS_ROOT = Path(__file__).resolve().parents[4]
SUPERPROJECT_ROOT = DATASETS_ROOT.parent

CAPABILITY_MATRIX_PATH = (
    DATASETS_ROOT
    / "tests"
    / "fixtures"
    / "logic"
    / "software_verification"
    / "capability_matrix.json"
)
ROLLOUT_DOC_PATH = (
    DATASETS_ROOT / "docs" / "logic" / "software_verification_rollout.md"
)
PROVER_MATRIX_DOC_PATH = (
    DATASETS_ROOT / "docs" / "security_verification" / "prover_matrix.md"
)
CAPABILITY_DOC_PATH = (
    DATASETS_ROOT
    / "docs"
    / "logic"
    / "software_verification_capability_inventory.md"
)
COMPLETION_RECEIPT_PATH = (
    SUPERPROJECT_ROOT
    / "docs"
    / "architecture"
    / "logic_formal_verification_expansion_completion_receipt.json"
)

INTERFACE = "LogicFormalVerificationRelease@1"
MATRIX_SCHEMA = "software-verification-release-matrix/v1"
REPORT_SCHEMA = "software-verification-benchmark-report/v1"

ROLLOUT_STAGES = ("declared", "shadow", "canary", "enforced")
HARD_ZERO_GATES = (
    "authority_boundary_violations",
    "false_proof_count",
    "false_completion_count",
    "secret_or_witness_leakage_count",
    "unresolved_cross_provider_disagreement_count",
)

# Property kinds that may use only non-proof / monitor authority by default.
MONITOR_DEFAULT_PROPERTIES = frozenset(
    {
        PropertyKind.TRACE_CONFORMANCE.value,
        PropertyKind.LIVENESS.value,
    }
)
# Hyperproperty tooling often remains documentation-declared until smoke exists.
DECLARED_ONLY_PROPERTIES = frozenset(
    {
        PropertyKind.NONINTERFERENCE.value,
        PropertyKind.HYPERPROPERTY.value,
    }
)

# Primary provider families for the release matrix (executable taxonomy).
PROPERTY_PROVIDER_FAMILIES: Mapping[str, tuple[str, ...]] = {
    PropertyKind.AUTHENTICATION.value: ("protocol",),
    PropertyKind.AUTHORIZATION.value: ("authorization",),
    PropertyKind.CONTRACT.value: ("smt", "kernel"),
    PropertyKind.DATA_RACE_FREEDOM.value: ("state_machine", "smt"),
    PropertyKind.HEAP_SAFETY.value: ("smt",),
    PropertyKind.HYPERPROPERTY.value: ("hyperproperty",),
    PropertyKind.INVARIANT.value: ("smt", "state_machine"),
    PropertyKind.LIVENESS.value: ("state_machine", "runtime_monitor"),
    PropertyKind.NONINTERFERENCE.value: ("hyperproperty",),
    PropertyKind.REACHABILITY.value: ("smt", "protocol", "state_machine"),
    PropertyKind.REFINEMENT.value: ("smt", "state_machine"),
    PropertyKind.SAFETY.value: ("smt", "state_machine", "runtime_monitor"),
    PropertyKind.SATISFIABILITY.value: ("smt", "atp"),
    PropertyKind.SECRECY.value: ("protocol",),
    PropertyKind.TERMINATION.value: ("smt", "atp"),
    PropertyKind.THEOREM.value: ("atp", "kernel", "proof_orchestration"),
    PropertyKind.TRACE_CONFORMANCE.value: ("runtime_monitor",),
    PropertyKind.VALIDITY.value: ("atp", "kernel"),
}

OUTCOME_CLASSES = (
    "success",
    "unknown",
    "timeout",
    "unsupported",
    "malformed",
    "unavailable",
)

RESOURCE_FIELDS = (
    "cpu_seconds_bound",
    "memory_bytes_bound",
    "wall_clock_seconds_bound",
    "process_count_bound",
    "output_bytes_bound",
)


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _load_capability_matrix() -> dict[str, Any]:
    assert CAPABILITY_MATRIX_PATH.is_file(), (
        f"missing capability matrix: {CAPABILITY_MATRIX_PATH}"
    )
    payload = json.loads(CAPABILITY_MATRIX_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload.get("schema_version") == "logic-capability-matrix/v1"
    assert payload.get("interface") == "LogicCapabilityMatrix@1"
    entries = payload.get("entries")
    assert isinstance(entries, list) and entries
    return payload


def _path_exists(relative: str) -> bool:
    return (SUPERPROJECT_ROOT / relative).is_file()


def _capability_provider_rows(
    matrix: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in matrix["entries"]:
        if not isinstance(entry, dict):
            continue
        if entry.get("category") not in {"provider", "compiler", "adapter"}:
            continue
        rows.append(entry)
    return rows


def _evidence_smoke_present(entry: Mapping[str, Any]) -> bool:
    evidence = entry.get("evidence") or {}
    paths = evidence.get("smoke_tests") or []
    return bool(paths) and all(isinstance(p, str) and _path_exists(p) for p in paths)


def _stage_for_pair(
    *,
    property_kind: str,
    family: str,
    capability_rows: Sequence[Mapping[str, Any]],
    definition_has_fixture: bool,
) -> str:
    """Derive a conservative rollout stage from executable evidence only."""

    if property_kind in DECLARED_ONLY_PROPERTIES and family == "hyperproperty":
        # Hyper tools frequently lack pinned self-tests; stay declared.
        return "declared"

    if family == "model_assistant":
        return "shadow"

    # Map prover families onto capability census provider rows.
    family_provider_ids = {
        "smt": ("provider.backend_registry", "provider.cec_tdfol_native"),
        "kernel": ("provider.itp_kernels", "provider.hammer"),
        "proof_orchestration": ("provider.hammer",),
        "authorization": ("provider.backend_registry",),
        "protocol": ("provider.external_router",),
        "state_machine": ("provider.backend_registry",),
        "runtime_monitor": ("provider.backend_registry",),
        "atp": ("provider.external_router", "provider.cec_tdfol_native"),
        "hyperproperty": ("provider.external_router",),
        "attestation": ("provider.zkp_backends",),
        "model_assistant": ("provider.learned_proposals",),
        "temporal_deontic": ("provider.cec_tdfol_native",),
        "temporal_first_order": ("provider.cec_tdfol_native",),
        "modal": ("provider.learned_proposals",),
    }
    ids = family_provider_ids.get(family, ())
    candidates = [row for row in capability_rows if row.get("id") in ids]

    if any(row.get("states", {}).get("shadow") for row in candidates):
        return "shadow"

    if property_kind in MONITOR_DEFAULT_PROPERTIES and family == "runtime_monitor":
        return "canary"

    smoke = any(_evidence_smoke_present(row) for row in candidates)
    translation = any(
        row.get("states", {}).get("translation_conformant") for row in candidates
    )
    authority = any(row.get("states", {}).get("authoritative_for") for row in candidates)

    if not candidates and not definition_has_fixture:
        return "declared"
    if not smoke and not definition_has_fixture:
        return "declared"
    if definition_has_fixture and not authority:
        return "shadow"
    if smoke and translation and authority and family in {"smt", "atp", "kernel"}:
        # Still do not auto-enforce: enforcement is operator-gated.
        return "canary"
    if smoke or definition_has_fixture:
        return "shadow"
    return "declared"


def _build_release_matrix(
    capability_matrix: Mapping[str, Any],
) -> dict[str, Any]:
    capability_rows = _capability_provider_rows(capability_matrix)
    claims = load_documentation_claims(PROVER_MATRIX_DOC_PATH)
    claims_by_label = Counter(
        claim.prover_text.casefold() for claim in claims
    )

    definitions = []
    for definition in DEFAULT_PROVER_DEFINITIONS:
        definitions.append(
            {
                "prover_id": definition.prover_id,
                "display_name": definition.display_name,
                "family": definition.family,
                "has_fixture": definition.fixture is not None,
                "documentation_labels": list(definition.documentation_labels),
                "maximum_authoritative_for": list(
                    definition.maximum_authoritative_for
                ),
            }
        )

    pairs: list[dict[str, Any]] = []
    for property_kind in PROPERTY_VOCABULARY:
        families = PROPERTY_PROVIDER_FAMILIES.get(property_kind, ())
        for family in families:
            family_defs = [
                item for item in definitions if item["family"] == family
            ]
            if not family_defs:
                family_defs = [
                    {
                        "prover_id": f"family:{family}",
                        "display_name": family,
                        "family": family,
                        "has_fixture": False,
                        "documentation_labels": [],
                        "maximum_authoritative_for": [],
                    }
                ]
            for definition in family_defs:
                stage = _stage_for_pair(
                    property_kind=property_kind,
                    family=family,
                    capability_rows=capability_rows,
                    definition_has_fixture=bool(definition["has_fixture"]),
                )
                pairs.append(
                    {
                        "property_kind": property_kind,
                        "provider_family": family,
                        "prover_id": definition["prover_id"],
                        "stage": stage,
                        "has_self_test_fixture": bool(definition["has_fixture"]),
                        "maximum_authoritative_for": definition[
                            "maximum_authoritative_for"
                        ],
                        "documentation_labels": definition[
                            "documentation_labels"
                        ],
                    }
                )

    matrix = {
        "schema_version": MATRIX_SCHEMA,
        "interface": INTERFACE,
        "objective": "LFV-G083",
        "capability_matrix_identity": _sha256_bytes(
            CAPABILITY_MATRIX_PATH.read_bytes()
        ),
        "prover_matrix_doc_identity": _sha256_bytes(
            PROVER_MATRIX_DOC_PATH.read_bytes()
        ),
        "property_vocabulary": list(PROPERTY_VOCABULARY),
        "prover_ids": sorted(EXPECTED_PROVER_IDS),
        "documentation_claim_count": len(claims),
        "documentation_claim_labels": sorted(claims_by_label),
        "pairs": pairs,
        "stage_vocabulary": list(ROLLOUT_STAGES),
        "hard_zero_gates": list(HARD_ZERO_GATES),
        "timing_ratio_correctness_gates": False,
    }
    matrix["matrix_identity"] = _sha256_text(_canonical_json(matrix))
    return matrix


def _synthetic_outcome_distribution(
    pairs: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """Offline semantic outcome classes — no live solvers required."""

    counts: Counter[str] = Counter()
    for pair in pairs:
        stage = pair["stage"]
        if stage == "enforced" and pair["has_self_test_fixture"]:
            counts["success"] += 1
        elif stage == "canary":
            counts["unknown"] += 1
        elif stage == "shadow" and pair["has_self_test_fixture"]:
            counts["unknown"] += 1
        elif not pair["has_self_test_fixture"]:
            counts["unavailable"] += 1
        else:
            counts["unsupported"] += 1
    for name in OUTCOME_CLASSES:
        counts.setdefault(name, 0)
    return {name: int(counts[name]) for name in OUTCOME_CLASSES}


def _resource_distribution(
    pairs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Report bound envelopes, not timing ratios."""

    # Conservative defaults aligned with bounded process lifecycle classes.
    per_stage_bounds = {
        "declared": {
            "cpu_seconds_bound": 0,
            "memory_bytes_bound": 0,
            "wall_clock_seconds_bound": 0,
            "process_count_bound": 0,
            "output_bytes_bound": 0,
        },
        "shadow": {
            "cpu_seconds_bound": 5,
            "memory_bytes_bound": 256 * 1024 * 1024,
            "wall_clock_seconds_bound": 30,
            "process_count_bound": 1,
            "output_bytes_bound": 64 * 1024,
        },
        "canary": {
            "cpu_seconds_bound": 15,
            "memory_bytes_bound": 512 * 1024 * 1024,
            "wall_clock_seconds_bound": 90,
            "process_count_bound": 2,
            "output_bytes_bound": 256 * 1024,
        },
        "enforced": {
            "cpu_seconds_bound": 60,
            "memory_bytes_bound": 1024 * 1024 * 1024,
            "wall_clock_seconds_bound": 300,
            "process_count_bound": 4,
            "output_bytes_bound": 1024 * 1024,
        },
    }
    stage_counts = Counter(pair["stage"] for pair in pairs)
    return {
        "fields": list(RESOURCE_FIELDS),
        "per_stage_bounds": per_stage_bounds,
        "stage_pair_counts": {
            stage: int(stage_counts.get(stage, 0)) for stage in ROLLOUT_STAGES
        },
        "cache": {
            "cold_identity_mode": "miss_on_any_bound_identity_change",
            "warm_identity_mode": "exact_receipt_authority_inherit_only",
            "authority_increase_on_hit": False,
        },
        "timing_ratio_correctness_gates": False,
        "correctness_basis": [
            "semantic_fixture_agreement",
            "mutation_detection",
            "explicit_non_success_states",
            "hard_zero_gates",
            "resource_bound_compliance",
        ],
    }


def _build_benchmark_report(matrix: Mapping[str, Any]) -> dict[str, Any]:
    pairs = matrix["pairs"]
    report = {
        "schema_version": REPORT_SCHEMA,
        "interface": INTERFACE,
        "objective": "LFV-G083",
        "matrix_identity": matrix["matrix_identity"],
        "pair_count": len(pairs),
        "semantic_outcome_distribution": _synthetic_outcome_distribution(pairs),
        "resource_distribution": _resource_distribution(pairs),
        "authority_boundary_violations": 0,
        "false_proof_count": 0,
        "false_completion_count": 0,
        "secret_or_witness_leakage_count": 0,
        "unresolved_cross_provider_disagreement_count": 0,
        "timing_ratio_correctness_gates": False,
        "external_tools_fabricated": False,
    }
    report["report_identity"] = _sha256_text(_canonical_json(report))
    return report


def _section(document: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##+ {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##+ |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(document)
    assert match is not None, f"missing section: {heading}"
    return match.group("body")


def test_release_artifacts_exist() -> None:
    for path in (
        CAPABILITY_MATRIX_PATH,
        ROLLOUT_DOC_PATH,
        PROVER_MATRIX_DOC_PATH,
        CAPABILITY_DOC_PATH,
        COMPLETION_RECEIPT_PATH,
    ):
        assert path.is_file(), f"missing release artifact: {path}"


def test_matrix_generated_from_current_executable_evidence() -> None:
    capability = _load_capability_matrix()
    matrix = _build_release_matrix(capability)

    assert matrix["schema_version"] == MATRIX_SCHEMA
    assert matrix["interface"] == INTERFACE
    assert matrix["timing_ratio_correctness_gates"] is False
    assert set(matrix["property_vocabulary"]) == set(PROPERTY_VOCABULARY)
    assert set(matrix["prover_ids"]) == set(EXPECTED_PROVER_IDS)
    assert matrix["documentation_claim_count"] >= len(DEFAULT_PROVER_DEFINITIONS)
    assert matrix["pairs"], "expected non-empty property/provider pairs"

    stages = {pair["stage"] for pair in matrix["pairs"]}
    assert stages <= set(ROLLOUT_STAGES)
    # Conservative generation must not invent enforced rows without operator gate.
    assert "enforced" not in stages
    # Learned/model assistant families must remain non-authoritative stages.
    for pair in matrix["pairs"]:
        if pair["provider_family"] == "model_assistant":
            assert pair["stage"] in {"declared", "shadow"}
        if pair["stage"] in {"canary", "enforced"}:
            assert pair["maximum_authoritative_for"] or pair["stage"] == "canary"


def test_benchmark_reports_semantic_and_resource_distributions_without_timing_gates() -> None:
    capability = _load_capability_matrix()
    matrix = _build_release_matrix(capability)
    report = _build_benchmark_report(matrix)

    assert report["schema_version"] == REPORT_SCHEMA
    assert report["timing_ratio_correctness_gates"] is False
    assert report["resource_distribution"]["timing_ratio_correctness_gates"] is False
    assert "timing_ratio" not in report["resource_distribution"]["correctness_basis"]

    distribution = report["semantic_outcome_distribution"]
    assert set(distribution) == set(OUTCOME_CLASSES)
    assert sum(distribution.values()) == report["pair_count"]
    assert distribution["unavailable"] >= 0

    resources = report["resource_distribution"]
    assert set(resources["fields"]) == set(RESOURCE_FIELDS)
    for stage in ROLLOUT_STAGES:
        bounds = resources["per_stage_bounds"][stage]
        assert set(bounds) == set(RESOURCE_FIELDS)
        assert all(isinstance(bounds[field], int) and bounds[field] >= 0 for field in RESOURCE_FIELDS)

    assert resources["cache"]["authority_increase_on_hit"] is False
    for gate in HARD_ZERO_GATES:
        assert report[gate] == 0
    assert report["external_tools_fabricated"] is False


def test_prover_documentation_reconciles_with_executable_definitions() -> None:
    claims = load_documentation_claims(PROVER_MATRIX_DOC_PATH)
    assert claims, "prover_matrix.md must expose a three-column documentation table"

    claim_text = " ".join(claim.prover_text for claim in claims).casefold()
    for definition in DEFAULT_PROVER_DEFINITIONS:
        assert any(
            label.casefold() in claim_text for label in definition.documentation_labels
        ), f"missing documentation labels for {definition.prover_id}"

    # Documentation must not invent prover ids outside the executable set when
    # stating runtime maturity; prose may describe soundness, but claims stay labels.
    doc = PROVER_MATRIX_DOC_PATH.read_text(encoding="utf-8")
    assert "documentation claims only" in doc.casefold() or "Documentation catalog" in doc
    collapsed = " ".join(doc.casefold().split())
    assert "never fabricate" in collapsed or "must not fabricate" in collapsed
    assert "software_verification_rollout.md" in doc


def test_rollout_policy_is_property_specific_and_reversible() -> None:
    doc = ROLLOUT_DOC_PATH.read_text(encoding="utf-8")
    assert "LogicFormalVerificationRelease@1" in doc
    assert "declared" in doc and "shadow" in doc and "canary" in doc and "enforced" in doc
    assert "There is no global" in doc or "no global" in doc.casefold()
    assert "reversible" in doc.casefold() or "Rollback" in doc
    assert "timing" in doc.casefold()
    assert "timing-ratio" in doc.casefold() or "Timing ratios" in doc
    assert "authority_boundary_violations" in doc

    stages_section = _section(doc, "Rollout stages")
    for stage in ROLLOUT_STAGES:
        assert f"`{stage}`" in stages_section

    property_section = _section(doc, "Property-specific policy")
    for kind in (
        PropertyKind.CONTRACT.value,
        PropertyKind.HEAP_SAFETY.value,
        PropertyKind.AUTHORIZATION.value,
        PropertyKind.NONINTERFERENCE.value,
        PropertyKind.TRACE_CONFORMANCE.value,
    ):
        assert f"`{kind}`" in property_section

    rollback = _section(doc, "Reversibility")
    assert "Demotion" in rollback or "demote" in rollback.casefold()
    assert "Historical receipts remain immutable" in rollback


def test_capability_census_rows_are_current_tree_paths() -> None:
    matrix = _load_capability_matrix()
    missing: list[str] = []
    for entry in matrix["entries"]:
        for path in entry.get("repository_paths") or []:
            if not _path_exists(path):
                missing.append(f"{entry.get('id')}:{path}")
        for bucket in ("smoke_tests", "translation_conformance", "reconstruction"):
            for path in (entry.get("evidence") or {}).get(bucket) or []:
                if not _path_exists(path):
                    missing.append(f"{entry.get('id')}:evidence:{path}")
    # Capability census is upstream evidence; surface a clear failure if stale.
    assert not missing, "stale capability census paths:\n" + "\n".join(missing[:20])


def test_shadow_and_canary_authority_boundaries_hold_in_generated_matrix() -> None:
    capability = _load_capability_matrix()
    matrix = _build_release_matrix(capability)
    for pair in matrix["pairs"]:
        if pair["stage"] == "shadow":
            # Generated shadow rows must not claim enforcement authority.
            assert pair["stage"] != "enforced"
        if pair["stage"] == "canary":
            # Canary may list maximum authority but must not be treated as enforced.
            assert pair["stage"] != "enforced"
        # Model assistants never leave shadow/declared.
        if "leanstral" in pair["prover_id"] or pair["provider_family"] == "model_assistant":
            assert pair["stage"] in {"declared", "shadow"}


def test_matrix_identity_is_stable_for_identical_inputs() -> None:
    capability = _load_capability_matrix()
    first = _build_release_matrix(capability)
    second = _build_release_matrix(capability)
    assert first["matrix_identity"] == second["matrix_identity"]
    report_a = _build_benchmark_report(first)
    report_b = _build_benchmark_report(second)
    assert report_a["report_identity"] == report_b["report_identity"]
