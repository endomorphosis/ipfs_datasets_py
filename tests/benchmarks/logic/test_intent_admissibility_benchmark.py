"""Offline deterministic Intent admissibility benchmark + leakage guards (LIG-019).

``IntentAdmissibilityBenchmark@1`` evaluates the composite gate on held-out
source families.  The gate is never trained; development partitions exist only
to exercise the partition fence.  Metrics cover allow / reject / abstain, and
promotion requires zero leakage and zero false allows.
"""

from __future__ import annotations

import copy
import hashlib
import json
import socket
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import pytest

from ipfs_datasets_py.logic.admissibility.gate import (
    ADMISSIBILITY_DECISION_INTERFACE,
    ADMISSIBILITY_GATE_INTERFACE,
    AdmissibilityDecision,
    IntentAdmissibilityGate,
    evaluate_admissibility,
    store_snapshot_digest,
)
from ipfs_datasets_py.logic.admissibility.profiles import get_profile
from ipfs_datasets_py.logic.admissibility.reasons import (
    AdmissibilityReasonCode,
    AdmissibilityStatus,
)
from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore


REPO_ROOT = Path(__file__).resolve().parents[3]
PARENT_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "logic" / "admissibility"
BENCHMARK_ROOT = PARENT_FIXTURE_ROOT / "benchmark"
INTENT_FORMAL_ROOT = (
    REPO_ROOT / "tests" / "fixtures" / "intent_ir" / "admissibility"
)

BENCHMARK_INTERFACE: Final = "IntentAdmissibilityBenchmark@1"
BENCHMARK_SCHEMA_VERSION: Final = "intent-admissibility-benchmark/v1"
SPLITS_INTERFACE: Final = "IntentAdmissibilityBenchmarkSplits@1"
REPORT_INTERFACE: Final = "IntentAdmissibilityBenchmarkReport@1"
REPORT_SCHEMA_VERSION: Final = "intent-admissibility-benchmark-report/v1"

EVALUATION_PARTITIONS: Final = frozenset({"test", "held_out_domain"})
DEVELOPMENT_PARTITIONS: Final = frozenset({"train", "validation"})
ALL_PARTITIONS: Final = frozenset(
    {"train", "validation", "test", "held_out_domain"}
)
STATUSES: Final = ("allow", "reject", "abstain")


class AdmissibilityBenchmarkError(ValueError):
    """Malformed or incomplete benchmark fixtures / observations."""


class AdmissibilityBenchmarkIntegrityError(AdmissibilityBenchmarkError):
    """Raised when splits or evaluation observations leak across partitions."""


# ---------------------------------------------------------------------------
# Fixture loaders
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _benchmark_manifest() -> dict[str, Any]:
    return _load_json(BENCHMARK_ROOT / "manifest.json")


def _splits() -> dict[str, Any]:
    return _load_json(BENCHMARK_ROOT / "splits.json")


def _expected_report() -> dict[str, Any]:
    return _load_json(BENCHMARK_ROOT / "expected_report.json")


def _recipe_case(case_id: str) -> dict[str, Any]:
    return _load_json(PARENT_FIXTURE_ROOT / "cases" / case_id / "case.json")


def _recipe_lineage(case_id: str) -> dict[str, Any]:
    return _load_json(PARENT_FIXTURE_ROOT / "cases" / case_id / "lineage.json")


def _recipe_expected(case_id: str) -> dict[str, Any]:
    return _load_json(
        PARENT_FIXTURE_ROOT / "cases" / case_id / "expected_decision.json"
    )


# ---------------------------------------------------------------------------
# Corpus reconstruction (offline, same recipe pattern as LIG-016)
# ---------------------------------------------------------------------------


def _constraint_from_intent(
    intent_raw: dict[str, Any],
    *,
    domain: str,
    role: str,
    variant: str | None = None,
) -> FormalizationArtifact:
    payload = copy.deepcopy(intent_raw)
    payload["domain"] = domain
    metadata = dict(payload.get("metadata") or {})
    metadata["gate_role"] = role
    metadata["constraint_family"] = domain
    if variant:
        metadata["constraint_variant"] = variant
    payload["metadata"] = metadata
    for formula in payload.get("formulas", []):
        expression = formula.get("expression")
        if isinstance(expression, dict):
            expression = dict(expression)
            expression["role"] = role
            if role in {"grant", "permission", "support"}:
                expression["norm_type"] = "permission"
                expression["polarity"] = "positive"
            else:
                expression["norm_type"] = "prohibition"
                expression["polarity"] = "negative"
            if variant:
                expression["variant"] = variant
            formula["expression"] = expression
    return FormalizationArtifact.from_dict(payload)


def _load_intent_formal(
    source_case_id: str,
) -> tuple[dict[str, Any], FormalizationArtifact]:
    path = INTENT_FORMAL_ROOT / "formal_artifacts" / f"{source_case_id}.json"
    raw = _load_json(path)
    return raw, FormalizationArtifact.from_dict(raw)


def _build_corpus(
    case_id: str,
) -> tuple[ProofCorpusStore, ArtifactEnvelope, dict[str, Any]]:
    case = _recipe_case(case_id)
    lineage = _recipe_lineage(case_id)
    intent_raw, intent = _load_intent_formal(case["source_formal_case_id"])
    env_profile = case.get("envelope_profile_id", "legal-strict")

    store = ProofCorpusStore()
    intent_env = store.put(
        ArtifactEnvelope.from_intent_artifact(intent, profile=env_profile)
    )
    for c in case.get("constraints") or []:
        art = _constraint_from_intent(
            intent_raw,
            domain=c["domain"],
            role=c["role"],
            variant=c.get("variant"),
        )
        store.put(
            ArtifactEnvelope.build(
                art,
                profile=c.get("profile", "legal-strict"),
                family=c["family"],
                producer_id=f"test-{c['family']}-constraint",
            )
        )

    if store_snapshot_digest(store) != lineage["store_snapshot_digest"]:
        raise AdmissibilityBenchmarkError(
            f"store snapshot mismatch for {case_id}: "
            f"{store_snapshot_digest(store)} != {lineage['store_snapshot_digest']}"
        )
    if intent_env.content_cid != lineage["intent_content_cid"]:
        raise AdmissibilityBenchmarkError(
            f"intent content CID mismatch for {case_id}"
        )
    return store, intent_env, lineage


# ---------------------------------------------------------------------------
# Leakage guards
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeakageFinding:
    rule: str
    detail: str
    case_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "detail": self.detail,
            "case_ids": list(self.case_ids),
        }


def _source_family_partition_fence(
    cases: Sequence[Mapping[str, Any]],
    splits: Mapping[str, Any],
) -> list[LeakageFinding]:
    """Require each source family to live entirely in one partition."""

    findings: list[LeakageFinding] = []
    by_family: dict[str, set[str]] = defaultdict(set)
    family_members: dict[str, list[str]] = defaultdict(list)

    for case in cases:
        family = str(case["source_family_id"])
        partition = str(case["partition"])
        by_family[family].add(partition)
        family_members[family].append(str(case["case_id"]))

    declared = splits.get("source_families") or {}
    for family_id, meta in declared.items():
        expected_members = set(meta.get("member_case_ids") or [])
        observed = set(family_members.get(family_id, []))
        if expected_members != observed:
            findings.append(
                LeakageFinding(
                    rule="source_family_membership",
                    detail=(
                        f"{family_id}: declared members {sorted(expected_members)} "
                        f"!= observed {sorted(observed)}"
                    ),
                    case_ids=tuple(sorted(expected_members | observed)),
                )
            )

    for family, partitions in sorted(by_family.items()):
        if len(partitions) > 1:
            findings.append(
                LeakageFinding(
                    rule="entire_source_family_in_single_partition",
                    detail=(
                        f"{family} spans partitions {sorted(partitions)}; "
                        "held-out sources must never train the gate"
                    ),
                    case_ids=tuple(sorted(family_members[family])),
                )
            )
    return findings


def _development_source_fence(
    cases: Sequence[Mapping[str, Any]],
    *,
    retrieved_by_case: Mapping[str, Sequence[str]] | None = None,
) -> list[LeakageFinding]:
    """Block eval cases from sharing sources or retrieving development rows."""

    findings: list[LeakageFinding] = []
    development = [
        c for c in cases if c["partition"] in DEVELOPMENT_PARTITIONS
    ]
    evaluation = [
        c for c in cases if c["partition"] in EVALUATION_PARTITIONS
    ]
    dev_digests = {c["intent_source_digest"] for c in development}
    dev_case_ids = {c["case_id"] for c in development}
    dev_families = {c["source_family_id"] for c in development}

    for case in evaluation:
        if case["intent_source_digest"] in dev_digests:
            findings.append(
                LeakageFinding(
                    rule="evaluation_must_not_share_intent_source_digest_with_development",
                    detail=(
                        f"{case['case_id']} shares intent_source_digest with development"
                    ),
                    case_ids=(case["case_id"],),
                )
            )
        if case["source_family_id"] in dev_families:
            findings.append(
                LeakageFinding(
                    rule="held_out_sources_never_train_the_gate",
                    detail=(
                        f"{case['case_id']} source family "
                        f"{case['source_family_id']} appears in development"
                    ),
                    case_ids=(case["case_id"],),
                )
            )

    if retrieved_by_case:
        for case_id, retrieved in retrieved_by_case.items():
            leaked = sorted(set(retrieved) & dev_case_ids)
            if leaked:
                findings.append(
                    LeakageFinding(
                        rule="evaluation_must_not_retrieve_development_case_ids",
                        detail=(
                            f"{case_id} retrieved development case(s) {leaked}"
                        ),
                        case_ids=(case_id, *leaked),
                    )
                )
    return findings


def validate_leakage_safe_splits(
    cases: Sequence[Mapping[str, Any]],
    splits: Mapping[str, Any],
    *,
    retrieved_by_case: Mapping[str, Sequence[str]] | None = None,
) -> list[LeakageFinding]:
    findings = _source_family_partition_fence(cases, splits)
    findings.extend(
        _development_source_fence(cases, retrieved_by_case=retrieved_by_case)
    )
    return findings


def require_leakage_safe(
    cases: Sequence[Mapping[str, Any]],
    splits: Mapping[str, Any],
    *,
    retrieved_by_case: Mapping[str, Sequence[str]] | None = None,
) -> None:
    findings = validate_leakage_safe_splits(
        cases, splits, retrieved_by_case=retrieved_by_case
    )
    if findings:
        detail = "; ".join(f"{item.rule}: {item.detail}" for item in findings)
        raise AdmissibilityBenchmarkIntegrityError(
            f"split leakage detected ({len(findings)}): {detail}"
        )


# ---------------------------------------------------------------------------
# Benchmark runner + metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseObservation:
    case_id: str
    partition: str
    expected_status: str
    observed_status: str
    expected_reason_codes: tuple[str, ...]
    observed_reason_codes: tuple[str, ...]
    profile_id: str
    decision: dict[str, Any]
    store_snapshot_digest: str
    intent_cid: str
    intent_artifact_cid: str
    retrieved_case_ids: tuple[str, ...] = ()

    @property
    def status_match(self) -> bool:
        return self.expected_status == self.observed_status

    @property
    def reasons_match(self) -> bool:
        return set(self.expected_reason_codes) == set(
            self.observed_reason_codes
        )


def _precision_recall(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    label: str,
) -> tuple[float, float]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
    precision = 1.0 if (tp + fp) == 0 else tp / (tp + fp)
    recall = 1.0 if (tp + fn) == 0 else tp / (tp + fn)
    return precision, recall


def _corpus_snapshot_pins(
    cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    pins = [
        {
            "case_id": c["case_id"],
            "intent_artifact_cid": c["intent_artifact_cid"],
            "intent_content_cid": c["intent_content_cid"],
            "intent_source_digest": c["intent_source_digest"],
            "profile_id": c["profile_id"],
            "store_snapshot_digest": c["store_snapshot_digest"],
        }
        for c in cases
        if c.get("evaluation") or c["partition"] in EVALUATION_PARTITIONS
    ]
    return sorted(pins, key=lambda item: item["case_id"])


def compute_corpus_snapshot(
    cases: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    pins = _corpus_snapshot_pins(cases)
    digest = _digest(pins)
    hex_part = digest.removeprefix("sha256:")
    cid = "bafkrei" + hex_part[:52]
    return cid, digest


def run_admissibility_benchmark(
    *,
    cases: Sequence[Mapping[str, Any]] | None = None,
    splits: Mapping[str, Any] | None = None,
    retrieved_by_case: Mapping[str, Sequence[str]] | None = None,
    offline: bool = True,
) -> dict[str, Any]:
    """Run the offline gate on evaluation partitions and emit a receipt."""

    manifest = _benchmark_manifest()
    splits = dict(splits if splits is not None else _splits())
    cases = list(cases if cases is not None else manifest["cases"])

    require_leakage_safe(cases, splits, retrieved_by_case=retrieved_by_case)

    evaluation_cases = [
        c
        for c in cases
        if c["partition"] in EVALUATION_PARTITIONS or c.get("evaluation")
    ]
    if not evaluation_cases:
        raise AdmissibilityBenchmarkError("no evaluation cases in benchmark")

    observations: list[CaseObservation] = []
    for case in sorted(evaluation_cases, key=lambda c: c["case_id"]):
        case_id = case["case_id"]
        store, intent_env, lineage = _build_corpus(case_id)
        gate = IntentAdmissibilityGate(store=store)
        decision = gate.evaluate(intent_env.content_cid, case["profile_id"])
        via_helper = evaluate_admissibility(
            store, intent_env.content_cid, case["profile_id"]
        )
        if decision.to_dict() != via_helper.to_dict():
            raise AdmissibilityBenchmarkError(
                f"gate/helper divergence on {case_id}"
            )

        expected = _recipe_expected(case_id)
        observations.append(
            CaseObservation(
                case_id=case_id,
                partition=str(case["partition"]),
                expected_status=str(case["expected_status"]),
                observed_status=decision.status.value,
                expected_reason_codes=tuple(
                    sorted(case["expected_reason_codes"])
                ),
                observed_reason_codes=tuple(sorted(decision.reason_codes)),
                profile_id=decision.profile_id,
                decision=decision.to_dict(),
                store_snapshot_digest=decision.store_snapshot_digest,
                intent_cid=decision.intent_cid,
                intent_artifact_cid=decision.intent_artifact_cid or "",
                retrieved_case_ids=tuple(
                    sorted(retrieved_by_case.get(case_id, ()))
                    if retrieved_by_case
                    else ()
                ),
            )
        )

        # Pin agreement with recipe lineage / expected decision.
        if decision.status.value != expected["status"]:
            raise AdmissibilityBenchmarkError(
                f"{case_id}: status {decision.status.value} != recipe {expected['status']}"
            )
        if set(decision.reason_codes) != set(expected["reason_codes"]):
            raise AdmissibilityBenchmarkError(
                f"{case_id}: reasons {set(decision.reason_codes)} "
                f"!= recipe {set(expected['reason_codes'])}"
            )
        if decision.store_snapshot_digest != lineage["store_snapshot_digest"]:
            raise AdmissibilityBenchmarkError(
                f"{case_id}: store snapshot drift"
            )
        if decision.intent_cid != lineage["intent_content_cid"]:
            raise AdmissibilityBenchmarkError(f"{case_id}: intent CID drift")

    # Determinism: re-run first evaluation case and require identical wire form.
    first = evaluation_cases[0]
    store_a, intent_a, _ = _build_corpus(first["case_id"])
    store_b, intent_b, _ = _build_corpus(first["case_id"])
    d1 = IntentAdmissibilityGate(store=store_a).evaluate(
        intent_a.content_cid, first["profile_id"]
    )
    d2 = IntentAdmissibilityGate(store=store_b).evaluate(
        intent_b.content_cid, first["profile_id"]
    )
    determinism_pass = d1.to_dict() == d2.to_dict()

    y_true = [obs.expected_status for obs in observations]
    y_pred = [obs.observed_status for obs in observations]
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    accuracy = correct / len(observations)

    status_counts = {status: 0 for status in STATUSES}
    status_correct = {status: 0 for status in STATUSES}
    for t, p in zip(y_true, y_pred):
        status_counts[t] = status_counts.get(t, 0) + 1
        if t == p:
            status_correct[t] = status_correct.get(t, 0) + 1

    metrics: dict[str, Any] = {
        "decision_accuracy": accuracy,
        "status_counts": status_counts,
        "status_correct": status_correct,
        "leakage_count": 0,
        "authority_violation_count": 0,
        "false_allow_count": sum(
            1
            for t, p in zip(y_true, y_pred)
            if p == AdmissibilityStatus.ALLOW.value and t != p
        ),
        "determinism_pass": determinism_pass,
        "offline": offline,
    }
    for status in STATUSES:
        precision, recall = _precision_recall(y_true, y_pred, status)
        metrics[f"{status}_precision"] = precision
        metrics[f"{status}_recall"] = recall

    # Authority: an allow without obligations_supported is a violation.
    for obs in observations:
        if obs.observed_status == AdmissibilityStatus.ALLOW.value:
            if (
                AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED.value
                not in obs.observed_reason_codes
            ):
                metrics["authority_violation_count"] += 1
        if not obs.status_match and obs.observed_status == "allow":
            metrics["authority_violation_count"] += 1

    metrics["promotion_eligible"] = (
        metrics["leakage_count"] == 0
        and metrics["authority_violation_count"] == 0
        and metrics["false_allow_count"] == 0
        and metrics["decision_accuracy"] == 1.0
        and metrics["determinism_pass"] is True
        and metrics["offline"] is True
    )

    corpus_cid, corpus_digest = compute_corpus_snapshot(evaluation_cases)
    report = {
        "interface": REPORT_INTERFACE,
        "schema_version": REPORT_SCHEMA_VERSION,
        "corpus_snapshot_cid": corpus_cid,
        "corpus_snapshot_digest": corpus_digest,
        "evaluation_partitions": sorted(EVALUATION_PARTITIONS),
        "evaluation_case_ids": [obs.case_id for obs in observations],
        "case_count": len(observations),
        "metrics": metrics,
        "profiles": manifest["profiles"],
        "gate_interface": ADMISSIBILITY_GATE_INTERFACE,
        "decision_interface": ADMISSIBILITY_DECISION_INTERFACE,
        "observations": [
            {
                "case_id": obs.case_id,
                "partition": obs.partition,
                "expected_status": obs.expected_status,
                "observed_status": obs.observed_status,
                "status_match": obs.status_match,
                "reasons_match": obs.reasons_match,
                "profile_id": obs.profile_id,
                "store_snapshot_digest": obs.store_snapshot_digest,
                "intent_cid": obs.intent_cid,
                "intent_artifact_cid": obs.intent_artifact_cid,
            }
            for obs in observations
        ],
        "report_digest": "",
    }
    report["report_digest"] = _digest(
        {k: v for k, v in report.items() if k != "report_digest"}
    )
    return report


# ---------------------------------------------------------------------------
# Network guard
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed if any benchmark path attempts a real network connection."""

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "LIG-019 admissibility benchmark must not use the network"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *_a, **_k: 1)


# ---------------------------------------------------------------------------
# Fixture contract
# ---------------------------------------------------------------------------


def test_benchmark_manifest_documents_splits_corpus_profiles_and_metrics() -> None:
    manifest = _benchmark_manifest()
    splits = _splits()
    expected = _expected_report()

    assert manifest["interface"] == BENCHMARK_INTERFACE
    assert manifest["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert manifest["gate_interface"] == ADMISSIBILITY_GATE_INTERFACE
    assert manifest["decision_interface"] == ADMISSIBILITY_DECISION_INTERFACE
    assert manifest["offline"] is True
    assert manifest["deterministic"] is True
    assert manifest["network_policy"] == "blocked"
    assert manifest["shadow_default"] is True

    assert splits["interface"] == SPLITS_INTERFACE
    assert set(splits["partitions"]) == ALL_PARTITIONS
    assert set(splits["evaluation_partitions"]) == EVALUATION_PARTITIONS
    assert set(splits["development_partitions"]) == DEVELOPMENT_PARTITIONS

    assert expected["interface"] == REPORT_INTERFACE
    assert expected["schema_version"] == REPORT_SCHEMA_VERSION

    case_ids = [c["case_id"] for c in manifest["cases"]]
    assert case_ids == list(manifest["case_ids"])
    assert len(case_ids) == len(set(case_ids))
    assert set(manifest["evaluation_case_ids"]) <= set(case_ids)

    strata = {c["stratum"] for c in manifest["cases"]}
    assert set(manifest["required_strata"]) <= strata

    for case in manifest["cases"]:
        recipe_path = PARENT_FIXTURE_ROOT / case["recipe_path"]
        assert recipe_path.is_dir(), case["recipe_path"]
        assert case["partition"] in ALL_PARTITIONS
        assert case["expected_status"] in STATUSES
        assert case["source_family_id"]
        assert case["intent_source_digest"].startswith("sha256:")
        assert case["store_snapshot_digest"].startswith("sha256:")
        assert case["intent_content_cid"].startswith("baf")
        assert case["profile_id"] in manifest["profiles"]
        # Assignments agree with splits.json
        assert splits["assignments"][case["case_id"]] == case["partition"]
        # Recipe pins agree with benchmark pins
        lineage = _recipe_lineage(case["case_id"])
        assert case["intent_source_digest"] == lineage["intent_source_digest"]
        assert case["store_snapshot_digest"] == lineage["store_snapshot_digest"]
        assert case["intent_content_cid"] == lineage["intent_content_cid"]
        assert case["intent_artifact_cid"] == lineage["intent_artifact_cid"]
        recipe_expected = _recipe_expected(case["case_id"])
        assert case["expected_status"] == recipe_expected["status"]
        assert set(case["expected_reason_codes"]) == set(
            recipe_expected["reason_codes"]
        )
        # Profile config digest is live and matches get_profile
        profile = get_profile(case["profile_id"])
        assert profile.config_digest() == recipe_expected["config_digest"]

    for metric in manifest["required_metrics"]:
        assert metric in expected["metrics"]

    cid, digest = compute_corpus_snapshot(
        [c for c in manifest["cases"] if c["evaluation"]]
    )
    assert manifest["corpus_snapshot_cid"] == cid == expected["corpus_snapshot_cid"]
    assert (
        manifest["corpus_snapshot_digest"]
        == digest
        == expected["corpus_snapshot_digest"]
    )


def test_splits_are_leakage_safe_by_source_family() -> None:
    manifest = _benchmark_manifest()
    splits = _splits()
    findings = validate_leakage_safe_splits(manifest["cases"], splits)
    assert findings == []
    require_leakage_safe(manifest["cases"], splits)

    # Every source family maps to exactly one partition.
    family_partitions: dict[str, set[str]] = defaultdict(set)
    for case in manifest["cases"]:
        family_partitions[case["source_family_id"]].add(case["partition"])
    for family, partitions in family_partitions.items():
        assert len(partitions) == 1, family

    # Development digests never appear on evaluation cases.
    dev_digests = {
        c["intent_source_digest"]
        for c in manifest["cases"]
        if c["partition"] in DEVELOPMENT_PARTITIONS
    }
    for case in manifest["cases"]:
        if case["partition"] in EVALUATION_PARTITIONS:
            assert case["intent_source_digest"] not in dev_digests


def test_source_family_leakage_is_rejected_before_evaluation() -> None:
    """Cross-partition members of one source family fail closed."""

    manifest = _benchmark_manifest()
    splits = _splits()
    cases = [dict(c) for c in manifest["cases"]]
    # Force a leakage: move one benign-family case into train.
    for case in cases:
        if case["case_id"] == "zkp_required_missing_proof":
            case["partition"] = "train"
            case["evaluation"] = False
            break

    findings = validate_leakage_safe_splits(cases, splits)
    assert any(
        item.rule == "entire_source_family_in_single_partition"
        for item in findings
    )
    with pytest.raises(
        AdmissibilityBenchmarkIntegrityError, match="source.family|leakage"
    ):
        require_leakage_safe(cases, splits)


def test_cross_partition_retrieval_is_rejected() -> None:
    manifest = _benchmark_manifest()
    splits = _splits()
    leaked_retrieval = {"benign_skill": ("legal_hard_reject",)}
    findings = validate_leakage_safe_splits(
        manifest["cases"], splits, retrieved_by_case=leaked_retrieval
    )
    assert any(
        item.rule
        == "evaluation_must_not_retrieve_development_case_ids"
        for item in findings
    )
    with pytest.raises(
        AdmissibilityBenchmarkIntegrityError, match="retrieve|leakage"
    ):
        run_admissibility_benchmark(retrieved_by_case=leaked_retrieval)


# ---------------------------------------------------------------------------
# End-to-end offline evaluation
# ---------------------------------------------------------------------------


def test_held_out_benchmark_matches_pinned_metrics_and_is_deterministic() -> None:
    report = run_admissibility_benchmark()
    expected = _expected_report()

    assert report["interface"] == REPORT_INTERFACE
    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["gate_interface"] == ADMISSIBILITY_GATE_INTERFACE
    assert report["decision_interface"] == ADMISSIBILITY_DECISION_INTERFACE
    assert report["corpus_snapshot_cid"] == expected["corpus_snapshot_cid"]
    assert (
        report["corpus_snapshot_digest"] == expected["corpus_snapshot_digest"]
    )
    assert set(report["evaluation_case_ids"]) == set(
        expected["evaluation_case_ids"]
    )
    assert report["case_count"] == expected["case_count"]

    metrics = report["metrics"]
    expected_metrics = expected["metrics"]
    for key in (
        "decision_accuracy",
        "allow_precision",
        "allow_recall",
        "reject_precision",
        "reject_recall",
        "abstain_precision",
        "abstain_recall",
        "leakage_count",
        "authority_violation_count",
        "false_allow_count",
        "determinism_pass",
        "offline",
        "promotion_eligible",
    ):
        assert metrics[key] == expected_metrics[key], key

    assert metrics["status_counts"] == expected_metrics["status_counts"]
    assert metrics["status_correct"] == expected_metrics["status_correct"]
    assert metrics["decision_accuracy"] == 1.0
    assert metrics["leakage_count"] == 0
    assert metrics["false_allow_count"] == 0
    assert metrics["promotion_eligible"] is True

    # Status coverage on held-out set: allow, reject, and abstain all present.
    assert metrics["status_counts"]["allow"] >= 1
    assert metrics["status_counts"]["reject"] >= 1
    assert metrics["status_counts"]["abstain"] >= 1

    # Every observation matches recipe reasons and status.
    for obs in report["observations"]:
        assert obs["status_match"] is True
        assert obs["reasons_match"] is True
        assert obs["partition"] in EVALUATION_PARTITIONS

    # Double-run yields identical metrics (excluding report_digest identity).
    second = run_admissibility_benchmark()
    assert second["metrics"] == report["metrics"]
    assert second["corpus_snapshot_digest"] == report["corpus_snapshot_digest"]
    assert second["evaluation_case_ids"] == report["evaluation_case_ids"]
    assert [
        {k: v for k, v in obs.items()} for obs in second["observations"]
    ] == [{k: v for k, v in obs.items()} for obs in report["observations"]]


def test_evaluation_never_uses_development_partitions() -> None:
    report = run_admissibility_benchmark()
    development_ids = {
        c["case_id"]
        for c in _benchmark_manifest()["cases"]
        if c["partition"] in DEVELOPMENT_PARTITIONS
    }
    assert development_ids  # fixture has development rows
    assert not (set(report["evaluation_case_ids"]) & development_ids)

    # Development recipes still rebuild offline (sanity, not scored).
    for case_id in sorted(development_ids):
        store, intent_env, lineage = _build_corpus(case_id)
        case = _recipe_case(case_id)
        decision = evaluate_admissibility(
            store, intent_env.content_cid, case["profile_id"]
        )
        expected = _recipe_expected(case_id)
        assert decision.status.value == expected["status"]
        assert decision.store_snapshot_digest == lineage["store_snapshot_digest"]


def test_decision_wire_form_is_closed_and_serializable() -> None:
    report = run_admissibility_benchmark()
    for obs in report["observations"]:
        case_id = obs["case_id"]
        store, intent_env, _ = _build_corpus(case_id)
        case = next(
            c
            for c in _benchmark_manifest()["cases"]
            if c["case_id"] == case_id
        )
        decision = evaluate_admissibility(
            store, intent_env.content_cid, case["profile_id"]
        )
        wire = decision.to_dict()
        assert wire["interface"] == ADMISSIBILITY_DECISION_INTERFACE
        assert wire["status"] in STATUSES
        assert "reasons" in wire
        for reason in wire["reasons"]:
            AdmissibilityReasonCode(reason["code"] if isinstance(reason, dict) else reason)
        # Property surface remains closed and matches the observation.
        for code in decision.reason_codes:
            AdmissibilityReasonCode(code)
        restored = AdmissibilityDecision.from_dict(wire)
        assert restored.to_dict() == wire
        # JSON round-trip is stable
        assert json.loads(json.dumps(wire, sort_keys=True)) == wire


def test_report_digest_is_content_addressed() -> None:
    report = run_admissibility_benchmark()
    body = {k: v for k, v in report.items() if k != "report_digest"}
    assert report["report_digest"] == _digest(body)
    assert report["report_digest"].startswith("sha256:")
    # Mutating a metric changes the digest
    mutated = copy.deepcopy(report)
    mutated["metrics"]["decision_accuracy"] = 0.0
    mutated_body = {k: v for k, v in mutated.items() if k != "report_digest"}
    assert _digest(mutated_body) != report["report_digest"]


def test_benchmark_covers_allow_reject_and_abstain_strata() -> None:
    """Effects contract: metrics for allow/reject/abstain on held-out sources."""

    report = run_admissibility_benchmark()
    by_status = Counter(
        obs["expected_status"] for obs in report["observations"]
    )
    assert by_status["allow"] >= 1
    assert by_status["reject"] >= 1
    assert by_status["abstain"] >= 1

    metrics = report["metrics"]
    assert metrics["allow_recall"] == 1.0
    assert metrics["reject_recall"] == 1.0
    assert metrics["abstain_recall"] == 1.0
    assert metrics["allow_precision"] == 1.0
    assert metrics["reject_precision"] == 1.0
    assert metrics["abstain_precision"] == 1.0
