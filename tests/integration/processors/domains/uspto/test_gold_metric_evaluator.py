"""PATLAW-123: executable, receipt-bound gold-corpus metric evaluator.

Acceptance coverage:

* Intentionally degraded outputs fail their corresponding metric.
* Thresholds are versioned and compared to observed values.
* Receipts bind corpus / parser / ruleset / model / config identities.
* Missing labels or unmeasurable cases produce explicit unknown /
  not_applicable counts rather than passes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.evaluation import (
    DEFAULT_CORPUS_ID,
    EVALUATION_SCHEMA_VERSION,
    GATE_CITATION_RECALL,
    GATE_EVIDENCE_PRECISION,
    GATE_FALSE_NEGATIVE_BUDGET,
    GATE_PROVENANCE_COMPLETENESS,
    GATE_REQUIREMENT_RECALL,
    GATES_SCHEMA,
    METRIC_CONTRADICTION,
    METRIC_DEADLINE,
    METRIC_DETERMINISM,
    METRIC_DOCUMENT_CLASSIFICATION,
    METRIC_E2E_COMPLETENESS,
    METRIC_OBLIGATION,
    METRIC_PRIVACY,
    METRIC_SEMANTIC_FIELD,
    METRIC_SPAN,
    OBSERVED_METRICS_SCHEMA,
    OBSERVED_METRICS_SCHEMA_VERSION,
    REQUIRED_GATE_IDS,
    REQUIRED_RECEIPT_METRIC_IDS,
    EvaluationIdentity,
    MetricStatus,
    MetricThresholdError,
    USPTOGoldEvaluator,
    assert_thresholds,
    content_digest,
    default_gold_root,
    digest_uri,
    load_gold_case,
    load_gold_corpus,
    load_metric_gates,
    normalize_citation,
    observed_metrics_document,
    perfect_output_from_case,
    sha256_hex,
)

# test_...py → uspto → domains → processors → integration → tests
FIXTURE_ROOT = Path(__file__).resolve().parents[4] / "fixtures" / "uspto"
GOLD_ROOT = FIXTURE_ROOT / "gold"
GATES_PATH = GOLD_ROOT / "metrics" / "metric_gates.json"
OBSERVED_SCHEMA_PATH = GOLD_ROOT / "metrics" / "observed_metrics.schema.json"

# Case with rich requirement + citation + deadline truth for degradation tests.
RICH_CASE_ID = "gold-scanned-office-action"
# Case with empty requirements/citations/dates (unmeasurable core gates).
EMPTY_LABELS_CASE_ID = "gold-unknown-low-readability"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def thresholds():
    return load_metric_gates(GATES_PATH)


@pytest.fixture(scope="module")
def rich_case():
    return load_gold_case(RICH_CASE_ID, gold_root=GOLD_ROOT)


@pytest.fixture(scope="module")
def empty_case():
    return load_gold_case(EMPTY_LABELS_CASE_ID, gold_root=GOLD_ROOT)


@pytest.fixture
def bound_identity(thresholds) -> EvaluationIdentity:
    return EvaluationIdentity(
        corpus_id=DEFAULT_CORPUS_ID,
        corpus_digest=digest_uri(content_digest({"corpus": DEFAULT_CORPUS_ID})),
        parser_id="uspto.parser.test",
        parser_digest=digest_uri(content_digest({"parser": "test-v1"})),
        ruleset_id="uspto.ruleset.test",
        ruleset_digest=digest_uri(content_digest({"ruleset": "test-v1"})),
        model_id="uspto.model.test",
        model_digest=digest_uri(content_digest({"model": "none"})),
        config_id="uspto.config.test",
        config_digest=digest_uri(content_digest({"config": "offline"})),
        thresholds_version=thresholds.thresholds_version,
        thresholds_digest=thresholds.thresholds_digest,
    )


def _degrade_drop_requirements(output: dict[str, Any]) -> dict[str, Any]:
    degraded = copy.deepcopy(output)
    degraded["requirements"] = []
    degraded["obligations"] = []
    return degraded


def _degrade_drop_citations(output: dict[str, Any]) -> dict[str, Any]:
    degraded = copy.deepcopy(output)
    degraded["citations"] = []
    for req in degraded.get("requirements") or []:
        req["legal_citations"] = []
    return degraded


def _degrade_wrong_evidence(output: dict[str, Any]) -> dict[str, Any]:
    degraded = copy.deepcopy(output)
    for req in degraded.get("requirements") or []:
        req["source_span_id"] = "span:intentionally-wrong"
    degraded["evidence_links"] = [
        {"item_id": r.get("requirement_id"), "span_id": "span:intentionally-wrong"}
        for r in degraded.get("requirements") or []
        if r.get("requirement_id")
    ]
    return degraded


def _degrade_incomplete_provenance(output: dict[str, Any]) -> dict[str, Any]:
    degraded = copy.deepcopy(output)
    stripped = []
    for item in degraded.get("provenance") or []:
        broken = dict(item)
        broken.pop("source_receipt_id", None)
        broken.pop("span_id", None)
        stripped.append(broken)
    degraded["provenance"] = stripped
    return degraded


def _degrade_classification(output: dict[str, Any]) -> dict[str, Any]:
    degraded = copy.deepcopy(output)
    degraded["classification"] = "confidential_application"
    degraded["document_classification"] = {
        "predicted": "confidential_application",
        "privacy_class": "public_synthetic",
    }
    degraded["privacy"] = {
        "classification": "confidential_application",
        "privacy_class": "public_synthetic",
        "leaked_private": False,
        "public_sink_allowed": False,
    }
    return degraded


def _degrade_deadline(output: dict[str, Any]) -> dict[str, Any]:
    degraded = copy.deepcopy(output)
    degraded["dates"] = []
    degraded["deadlines"] = []
    return degraded


def _degrade_determinism(output: dict[str, Any]) -> dict[str, Any]:
    degraded = copy.deepcopy(output)
    degraded["determinism"] = {
        "run_digest": "aaa",
        "repeat_digest": "bbb",
    }
    return degraded


def _degrade_e2e(output: dict[str, Any]) -> dict[str, Any]:
    degraded = copy.deepcopy(output)
    e2e = dict(degraded.get("end_to_end") or {})
    expected = list(e2e.get("stages_expected") or [])
    e2e["stages_completed"] = expected[: max(0, len(expected) - 2)]
    degraded["end_to_end"] = e2e
    return degraded


def _metric_by_id(metrics, metric_id: str):
    for m in metrics:
        if m.metric_id == metric_id:
            return m
    raise AssertionError(f"missing metric {metric_id}")


# ---------------------------------------------------------------------------
# Schema / fixture wiring
# ---------------------------------------------------------------------------


def test_observed_metrics_schema_fixture_exists_and_is_valid_json() -> None:
    assert OBSERVED_SCHEMA_PATH.is_file()
    schema = json.loads(OBSERVED_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["properties"]["schema"]["const"] == OBSERVED_METRICS_SCHEMA
    assert schema["properties"]["schema_version"]["const"] == OBSERVED_METRICS_SCHEMA_VERSION
    statuses = schema["$defs"]["metricStatus"]["enum"]
    assert set(statuses) == {"pass", "fail", "unknown", "not_applicable"}
    # Explicit unknown/not_applicable are first-class — not aliases of pass.
    assert "pass" in statuses and "unknown" in statuses and "not_applicable" in statuses


def test_default_gold_root_points_at_reviewed_corpus() -> None:
    root = default_gold_root()
    assert root.is_dir()
    assert (root / "metrics" / "metric_gates.json").is_file()
    assert (root / "cases").is_dir()


def test_metric_gates_are_versioned_and_digested(thresholds) -> None:
    assert thresholds.schema == GATES_SCHEMA
    assert thresholds.schema_version == 1
    assert thresholds.thresholds_version == f"{GATES_SCHEMA}@1"
    assert thresholds.thresholds_digest.startswith("sha256:")
    assert len(thresholds.thresholds_digest) == len("sha256:") + 64
    # Digest binds the on-disk gates file bytes.
    raw = GATES_PATH.read_bytes()
    assert thresholds.thresholds_digest == digest_uri(sha256_hex(raw))
    assert REQUIRED_GATE_IDS <= set(thresholds.gates)


# ---------------------------------------------------------------------------
# Perfect outputs pass thresholds
# ---------------------------------------------------------------------------


def test_perfect_output_passes_release_gates(rich_case, thresholds, bound_identity) -> None:
    output = perfect_output_from_case(rich_case)
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds,
        gold_root=GOLD_ROOT,
        identity=bound_identity,
        fail_loudly=True,
    )
    case_eval = evaluator.evaluate_case(rich_case, output)
    for gate_id in REQUIRED_GATE_IDS:
        metric = _metric_by_id(case_eval.metrics, gate_id)
        assert metric.status is MetricStatus.PASS, (gate_id, metric.to_dict())
        assert metric.threshold_version == thresholds.thresholds_version
        assert metric.value is not None

    receipt = evaluator.evaluate_corpus(
        {rich_case.case_id: output},
        identity=bound_identity,
        receipt_id="receipt:perfect-rich",
        evaluated_at_utc="2026-08-03T12:00:00Z",
    )
    assert receipt.passed is True
    assert receipt.fail_count == 0
    assert receipt.schema_version == EVALUATION_SCHEMA_VERSION
    assert receipt.observed_metrics_schema == OBSERVED_METRICS_SCHEMA


def test_perfect_corpus_subset_passes(thresholds, bound_identity) -> None:
    """Evaluate several labeled cases with ideal outputs."""
    case_ids = [
        "gold-scanned-office-action",
        "gold-rotated-scan-page",
        "gold-forms-and-tables",
        "gold-filing-receipts",
        "gold-amendments-current-claims",
    ]
    outputs = {}
    for cid in case_ids:
        case = load_gold_case(cid, gold_root=GOLD_ROOT)
        outputs[cid] = perfect_output_from_case(case)

    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds,
        gold_root=GOLD_ROOT,
        identity=bound_identity,
        fail_loudly=True,
    )
    receipt = evaluator.evaluate_corpus(
        outputs,
        identity=bound_identity,
        receipt_id="receipt:perfect-subset",
    )
    assert receipt.passed is True
    for gate_id in REQUIRED_GATE_IDS:
        assert receipt.metric(gate_id).status is MetricStatus.PASS


# ---------------------------------------------------------------------------
# Intentionally degraded outputs fail corresponding metrics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "degrader,metric_id",
    [
        (_degrade_drop_requirements, GATE_REQUIREMENT_RECALL),
        (_degrade_drop_requirements, GATE_FALSE_NEGATIVE_BUDGET),
        (_degrade_drop_requirements, METRIC_OBLIGATION),
        (_degrade_drop_citations, GATE_CITATION_RECALL),
        (_degrade_wrong_evidence, GATE_EVIDENCE_PRECISION),
        (_degrade_incomplete_provenance, GATE_PROVENANCE_COMPLETENESS),
        (_degrade_classification, METRIC_DOCUMENT_CLASSIFICATION),
        (_degrade_classification, METRIC_PRIVACY),
        (_degrade_deadline, METRIC_DEADLINE),
        (_degrade_determinism, METRIC_DETERMINISM),
        (_degrade_e2e, METRIC_E2E_COMPLETENESS),
    ],
)
def test_degraded_output_fails_corresponding_metric(
    rich_case, thresholds, degrader, metric_id
) -> None:
    baseline = perfect_output_from_case(rich_case)
    # Sanity: baseline must pass the target metric first.
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    baseline_eval = evaluator.evaluate_case(rich_case, baseline)
    baseline_metric = _metric_by_id(baseline_eval.metrics, metric_id)
    assert baseline_metric.status is MetricStatus.PASS, baseline_metric.to_dict()

    degraded = degrader(baseline)
    degraded_eval = evaluator.evaluate_case(rich_case, degraded)
    failed = _metric_by_id(degraded_eval.metrics, metric_id)
    assert failed.status is MetricStatus.FAIL, (
        f"{metric_id} expected FAIL, got {failed.status.value}: {failed.to_dict()}"
    )
    # Thresholds remain versioned on the observation.
    assert failed.threshold_version == thresholds.thresholds_version
    if failed.threshold is not None and failed.value is not None:
        assert failed.operator in {">=", "<=", ">", "<", "=="}


def test_drop_requirement_fails_assert_thresholds(rich_case, thresholds) -> None:
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    degraded = _degrade_drop_requirements(perfect_output_from_case(rich_case))
    metrics = evaluator.evaluate_case(rich_case, degraded).metrics
    with pytest.raises(MetricThresholdError) as excinfo:
        assert_thresholds(metrics, required_ids=REQUIRED_GATE_IDS)
    assert GATE_REQUIREMENT_RECALL in str(excinfo.value)


def test_degraded_corpus_receipt_does_not_pass(
    rich_case, thresholds, bound_identity
) -> None:
    output = _degrade_drop_citations(perfect_output_from_case(rich_case))
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds,
        gold_root=GOLD_ROOT,
        identity=bound_identity,
        fail_loudly=False,
    )
    receipt = evaluator.evaluate_corpus(
        {rich_case.case_id: output},
        identity=bound_identity,
        receipt_id="receipt:degraded-cite",
    )
    assert receipt.passed is False
    assert receipt.fail_count >= 1
    assert receipt.metric(GATE_CITATION_RECALL).status is MetricStatus.FAIL


# ---------------------------------------------------------------------------
# Unknown / not_applicable (never automatic passes)
# ---------------------------------------------------------------------------


def test_empty_labels_produce_not_applicable_not_pass(empty_case, thresholds) -> None:
    """Cases with no requirement/citation/date labels must not invent gate passes."""
    output = perfect_output_from_case(empty_case)
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metrics = evaluator.evaluate_case(empty_case, output).metrics

    req = _metric_by_id(metrics, GATE_REQUIREMENT_RECALL)
    assert req.status is MetricStatus.NOT_APPLICABLE
    assert req.not_applicable_count >= 1
    assert req.passed is None  # not True
    assert req.value is None

    cite = _metric_by_id(metrics, GATE_CITATION_RECALL)
    assert cite.status is MetricStatus.NOT_APPLICABLE
    assert cite.not_applicable_count >= 1

    fn = _metric_by_id(metrics, GATE_FALSE_NEGATIVE_BUDGET)
    assert fn.status is MetricStatus.NOT_APPLICABLE

    deadline = _metric_by_id(metrics, METRIC_DEADLINE)
    assert deadline.status is MetricStatus.NOT_APPLICABLE

    contradiction = _metric_by_id(metrics, METRIC_CONTRADICTION)
    assert contradiction.status is MetricStatus.NOT_APPLICABLE
    assert contradiction.not_applicable_count >= 1


def test_missing_determinism_block_is_unknown(rich_case, thresholds) -> None:
    output = perfect_output_from_case(rich_case)
    output.pop("determinism", None)
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metric = _metric_by_id(
        evaluator.evaluate_case(rich_case, output).metrics, METRIC_DETERMINISM
    )
    assert metric.status is MetricStatus.UNKNOWN
    assert metric.unknown_count >= 1
    assert metric.passed is None


def test_missing_classification_is_unknown(rich_case, thresholds) -> None:
    output = perfect_output_from_case(rich_case)
    output.pop("classification", None)
    output.pop("document_classification", None)
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metric = _metric_by_id(
        evaluator.evaluate_case(rich_case, output).metrics,
        METRIC_DOCUMENT_CLASSIFICATION,
    )
    assert metric.status is MetricStatus.UNKNOWN
    assert metric.unknown_count >= 1


def test_contradiction_predictions_without_labels_are_unknown(
    empty_case, thresholds
) -> None:
    output = perfect_output_from_case(empty_case)
    output["contradictions"] = [{"contradiction_id": "ctr:invented", "note": "unlabeled"}]
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metric = _metric_by_id(
        evaluator.evaluate_case(empty_case, output).metrics, METRIC_CONTRADICTION
    )
    assert metric.status is MetricStatus.UNKNOWN
    assert metric.unknown_count >= 1


def test_empty_label_case_does_not_pass_corpus_receipt(
    empty_case, thresholds, bound_identity
) -> None:
    """Overall receipt must not pass when required gates are not_applicable."""
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds,
        gold_root=GOLD_ROOT,
        identity=bound_identity,
        fail_loudly=False,
    )
    receipt = evaluator.evaluate_corpus(
        {empty_case.case_id: perfect_output_from_case(empty_case)},
        identity=bound_identity,
        receipt_id="receipt:empty-labels",
    )
    assert receipt.passed is False
    assert receipt.not_applicable_count >= 1
    # Required gates are N/A, not pass.
    assert receipt.metric(GATE_REQUIREMENT_RECALL).status is MetricStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Receipt identity binding
# ---------------------------------------------------------------------------


def test_receipt_binds_corpus_parser_ruleset_model_config(
    rich_case, thresholds, bound_identity
) -> None:
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds,
        gold_root=GOLD_ROOT,
        identity=bound_identity,
        fail_loudly=True,
    )
    output = perfect_output_from_case(rich_case)
    receipt = evaluator.evaluate_corpus(
        {rich_case.case_id: output},
        identity=bound_identity,
        receipt_id="receipt:identity-bind",
        evaluated_at_utc="2026-08-03T15:00:00Z",
        metadata={"task_id": "PATLAW-123"},
    )

    identity = receipt.identity
    assert identity.corpus_id == bound_identity.corpus_id
    assert identity.corpus_digest == bound_identity.corpus_digest
    assert identity.parser_id == bound_identity.parser_id
    assert identity.parser_digest == bound_identity.parser_digest
    assert identity.ruleset_id == bound_identity.ruleset_id
    assert identity.ruleset_digest == bound_identity.ruleset_digest
    assert identity.model_id == bound_identity.model_id
    assert identity.model_digest == bound_identity.model_digest
    assert identity.config_id == bound_identity.config_id
    assert identity.config_digest == bound_identity.config_digest
    assert identity.thresholds_version == thresholds.thresholds_version
    assert identity.thresholds_digest == thresholds.thresholds_digest

    # Digests are content-addressed sha256 URIs.
    for field in (
        identity.corpus_digest,
        identity.parser_digest,
        identity.ruleset_digest,
        identity.model_digest,
        identity.config_digest,
        identity.thresholds_digest,
        receipt.receipt_digest,
        receipt.annotations_digest,
        receipt.outputs_digest,
    ):
        assert field.startswith("sha256:")
        assert len(field) == 7 + 64

    # Receipt digest is self-consistent with body (excluding receipt_digest).
    body = receipt.to_dict()
    from ipfs_datasets_py.processors.domains.uspto.evaluation import build_receipt_digest

    assert receipt.receipt_digest == build_receipt_digest(body)
    assert receipt.metadata["task_id"] == "PATLAW-123"


def test_different_identities_produce_different_receipt_digests(
    rich_case, thresholds
) -> None:
    output = perfect_output_from_case(rich_case)
    base = dict(
        corpus_id=DEFAULT_CORPUS_ID,
        corpus_digest=digest_uri(content_digest({"c": 1})),
        parser_id="parser-a",
        parser_digest=digest_uri(content_digest({"p": "a"})),
        ruleset_id="rules-a",
        ruleset_digest=digest_uri(content_digest({"r": "a"})),
        model_id="model-a",
        model_digest=digest_uri(content_digest({"m": "a"})),
        config_id="config-a",
        config_digest=digest_uri(content_digest({"cfg": "a"})),
        thresholds_version=thresholds.thresholds_version,
        thresholds_digest=thresholds.thresholds_digest,
    )
    id_a = EvaluationIdentity(**base)
    id_b = EvaluationIdentity(
        **{
            **base,
            "parser_id": "parser-b",
            "parser_digest": digest_uri(content_digest({"p": "b"})),
        }
    )
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=True
    )
    r_a = evaluator.evaluate_corpus(
        {rich_case.case_id: output}, identity=id_a, receipt_id="receipt:a"
    )
    r_b = evaluator.evaluate_corpus(
        {rich_case.case_id: output}, identity=id_b, receipt_id="receipt:b"
    )
    assert r_a.receipt_digest != r_b.receipt_digest
    assert r_a.identity.parser_digest != r_b.identity.parser_digest


def test_thresholds_version_compared_on_every_gate_metric(
    rich_case, thresholds
) -> None:
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metrics = evaluator.evaluate_case(
        rich_case, perfect_output_from_case(rich_case)
    ).metrics
    for gate_id in REQUIRED_GATE_IDS:
        m = _metric_by_id(metrics, gate_id)
        assert m.threshold_version == thresholds.thresholds_version
        gate = thresholds.gate(gate_id)
        assert m.operator == gate.operator
        assert m.threshold == gate.threshold
        assert m.value is not None
        # Observed value is compared (status already encodes the comparison).
        assert m.status in {MetricStatus.PASS, MetricStatus.FAIL}


# ---------------------------------------------------------------------------
# Observed metrics document + extended families
# ---------------------------------------------------------------------------


def test_observed_metrics_document_matches_schema_constants(
    rich_case, thresholds
) -> None:
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metrics = evaluator.evaluate_case(
        rich_case, perfect_output_from_case(rich_case)
    ).metrics
    doc = observed_metrics_document(
        metrics, thresholds=thresholds, case_ids=[rich_case.case_id]
    )
    assert doc["schema"] == OBSERVED_METRICS_SCHEMA
    assert doc["schema_version"] == OBSERVED_METRICS_SCHEMA_VERSION
    assert doc["thresholds_version"] == thresholds.thresholds_version
    assert doc["thresholds_digest"] == thresholds.thresholds_digest
    assert doc["case_ids"] == [rich_case.case_id]
    assert isinstance(doc["metrics"], list) and doc["metrics"]
    summary = doc["summary"]
    assert summary["pass_count"] + summary["fail_count"] >= 1
    assert summary["unknown_count"] >= 0
    assert summary["not_applicable_count"] >= 0

    # Round-trip each metric through the ObservedMetric shape fields.
    required_fields = {
        "metric_id",
        "family",
        "status",
        "value",
        "operator",
        "threshold",
        "threshold_version",
        "true_positives",
        "false_positives",
        "false_negatives",
        "unknown_count",
        "not_applicable_count",
        "numerator",
        "denominator",
        "details",
    }
    for item in doc["metrics"]:
        assert required_fields <= set(item)
        assert item["status"] in {"pass", "fail", "unknown", "not_applicable"}


def test_extended_metric_families_are_emitted(rich_case, thresholds) -> None:
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metrics = evaluator.evaluate_case(
        rich_case, perfect_output_from_case(rich_case)
    ).metrics
    ids = {m.metric_id for m in metrics}
    assert REQUIRED_RECEIPT_METRIC_IDS <= ids
    for mid in (
        METRIC_DOCUMENT_CLASSIFICATION,
        METRIC_SPAN,
        METRIC_SEMANTIC_FIELD,
        METRIC_OBLIGATION,
        METRIC_CONTRADICTION,
        METRIC_DEADLINE,
        METRIC_PRIVACY,
        METRIC_DETERMINISM,
        METRIC_E2E_COMPLETENESS,
    ):
        assert mid in ids


def test_span_and_semantic_field_metrics_pass_on_perfect(
    rich_case, thresholds
) -> None:
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metrics = evaluator.evaluate_case(
        rich_case, perfect_output_from_case(rich_case)
    ).metrics
    assert _metric_by_id(metrics, METRIC_SPAN).status is MetricStatus.PASS
    assert _metric_by_id(metrics, METRIC_SEMANTIC_FIELD).status is MetricStatus.PASS


def test_span_metric_fails_when_spans_dropped(rich_case, thresholds) -> None:
    output = perfect_output_from_case(rich_case)
    output["spans"] = []
    for req in output.get("requirements") or []:
        req["source_span_id"] = "span:missing"
    for cite in output.get("citations") or []:
        cite["source_span_id"] = "span:missing"
    for prov in output.get("provenance") or []:
        prov["span_id"] = "span:missing"
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds, gold_root=GOLD_ROOT, fail_loudly=False
    )
    metric = _metric_by_id(
        evaluator.evaluate_case(rich_case, output).metrics, METRIC_SPAN
    )
    assert metric.status is MetricStatus.FAIL


def test_normalize_citation_is_stable() -> None:
    assert normalize_citation("35 U.S.C. 112(a)") == normalize_citation(
        "35  usc  112(a)"
    )


def test_load_gold_corpus_offline() -> None:
    corpus = load_gold_corpus(gold_root=GOLD_ROOT)
    assert len(corpus) >= 8
    ids = {c.case_id for c in corpus}
    assert RICH_CASE_ID in ids
    assert EMPTY_LABELS_CASE_ID in ids


def test_fail_loudly_raises_on_corpus_regression(
    rich_case, thresholds, bound_identity
) -> None:
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds,
        gold_root=GOLD_ROOT,
        identity=bound_identity,
        fail_loudly=True,
    )
    degraded = _degrade_drop_requirements(perfect_output_from_case(rich_case))
    with pytest.raises(MetricThresholdError):
        evaluator.evaluate_corpus(
            {rich_case.case_id: degraded},
            identity=bound_identity,
            receipt_id="receipt:loud-fail",
        )
