"""Conformance tests for the selected source-withheld canonical decompiler."""

from __future__ import annotations

import builtins
import inspect
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_decompiler as module
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_PARITY_POLICY_CID,
    SELECTED_REALIZER_ADAPTER_RAW_CID,
    SELECTED_REALIZER_INTERFACE,
    SOURCE_WITHHELD_DECOMPILER_CONFIG,
    SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
    SOURCE_WITHHELD_RENDERING_SPEC_CID,
    CanonicalContractError,
    CanonicalErrorCode,
    CanonicalRoundTripIR,
    CanonicalRule,
    CanonicalStructuredTextDecompiler,
    DecompilerRequest,
    DecompilerResult,
    OperationStatus,
)
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
    CANONICAL_DECOMPILER_ATTRIBUTION_INTERFACE,
    CANONICAL_DECOMPILER_ATTRIBUTION_SCHEMA,
    CANONICAL_DECOMPILER_COMPONENT_ID,
    SourceWithheldCanonicalDecompiler,
    decompile_rule,
    frozen_decompiler_config,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_dag_json


ROOT = Path(__file__).resolve().parents[4]
PILOT_CASES = json.loads(
    (
        ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
    ).read_text(encoding="utf-8")
)


def _rule() -> CanonicalRule:
    return CanonicalRule(
        modality="O",
        actor="company_a",
        action="file",
        object="annual_report",
        conditions=("public_interest", "required_by_law"),
        exceptions=("emergency",),
        temporal=("after_approval", "within_10_days"),
    )


def _request(*rules: CanonicalRule) -> DecompilerRequest:
    return DecompilerRequest(
        canonical_ir=CanonicalRoundTripIR(tuple(rules)),
        request_id="decompiler-conformance",
    )


def test_all_frozen_t1_outputs_match_selected_benchmark_adapter() -> None:
    from benchmarks.semantic_roundtrip import (
        AllowedAtomVocabulary,
        CanonicalRuleIR,
        ComponentStatus,
        RealizerRequest,
    )
    from benchmarks.semantic_roundtrip.realizers.source_withheld_paraphrase import (
        SourceWithheldCanonicalParaphraser as BenchmarkParaphraser,
        frozen_replacement_config as benchmark_config,
    )

    decompiler = SourceWithheldCanonicalDecompiler()
    benchmark = BenchmarkParaphraser()

    for case in PILOT_CASES:
        production_ir = CanonicalRoundTripIR.from_dict(case["gold_ir"])
        result = decompiler.decompile(
            DecompilerRequest(
                canonical_ir=production_ir,
                request_id=str(case["id"]),
            )
        )

        vocabulary = AllowedAtomVocabulary.from_dict(case["allowed_atoms"])
        benchmark_ir = CanonicalRuleIR.from_dict(case["gold_ir"], vocabulary)
        expected = benchmark.realize(
            RealizerRequest(
                canonical_ir=benchmark_ir,
                allowed_atom_vocabulary=vocabulary,
                config=benchmark_config(),
            )
        )

        assert expected.status is ComponentStatus.SUCCESS, case["id"]
        assert result.status is OperationStatus.SUCCESS, case["id"]
        assert result.text == expected.text, case["id"]
        assert result.text_cid == cid_for_bytes(
            expected.text.encode("utf-8")
        ), case["id"]


def test_frozen_grammar_preserves_polarity_roles_and_every_facet() -> None:
    request = _request(
        _rule(),
        CanonicalRule(
            modality="P",
            actor="court",
            action="review",
            object="notice",
        ),
        CanonicalRule(
            modality="F",
            actor="agency",
            action="inspect",
            object="records",
        ),
    )

    result = SourceWithheldCanonicalDecompiler().decompile(request)

    assert result.status is OperationStatus.SUCCESS
    assert result.text == (
        "Agency must not inspect records. "
        "Company a must file annual report after approval and within 10 days "
        "if public interest and required by law unless emergency. "
        "Court may review notice."
    )
    assert "Agency must inspect" not in result.text
    assert " shall " not in result.text
    assert decompile_rule(
        CanonicalRule(
            modality="P",
            actor="court",
            action="review",
            object="",
            temporal=("after_approval",),
        )
    ) == "Court may review after approval."


def test_success_has_raw_text_cid_and_deterministic_component_trace() -> None:
    request = _request(_rule())
    decompiler = SourceWithheldCanonicalDecompiler()

    result = decompiler.decompile(request)

    assert result.status is OperationStatus.SUCCESS
    assert result.error is None
    assert result.text is not None
    assert result.text_cid == cid_for_bytes(result.text.encode("utf-8"))
    assert len(result.component_trace) == 1
    trace = result.component_trace[0]
    assert trace.component_id == CANONICAL_DECOMPILER_COMPONENT_ID
    assert trace.component_interface == SELECTED_REALIZER_INTERFACE
    assert trace.input_cid == request.canonical_ir.ir_cid
    assert trace.input_codec == "dag-json"
    assert trace.output_cid == result.text_cid
    assert trace.output_codec == "raw"
    assert trace.config_cid == SOURCE_WITHHELD_DECOMPILER_CONFIG_CID
    assert trace.deterministic is True
    assert trace.model_receipt_cid is None
    assert DecompilerResult.from_dict(result.to_dict()) == result


def test_attribution_receipt_binds_only_public_canonical_inputs_and_t1() -> None:
    request = _request(_rule())
    result, receipt = (
        SourceWithheldCanonicalDecompiler().decompile_with_receipt(request)
    )

    assert result.status is OperationStatus.SUCCESS
    assert receipt is not None
    assert receipt["interface"] == CANONICAL_DECOMPILER_ATTRIBUTION_INTERFACE
    assert receipt["schema_version"] == CANONICAL_DECOMPILER_ATTRIBUTION_SCHEMA
    assert receipt["realizer_identity"] == SELECTED_REALIZER_INTERFACE
    assert receipt["selected_adapter_raw_cid"] == (
        SELECTED_REALIZER_ADAPTER_RAW_CID
    )
    assert receipt["rendering_spec_cid"] == (
        SOURCE_WITHHELD_RENDERING_SPEC_CID
    )
    assert receipt["deterministic"] is True
    assert receipt["source_withheld"] is True
    assert receipt["input_attribution"] == {
        "public_request_cid": request.request_cid,
        "canonical_ir_cid": request.canonical_ir.ir_cid,
        "policy_cid": CANONICAL_PARITY_POLICY_CID,
        "frozen_config_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
    }
    assert receipt["output_attribution"] == {
        "text_cid": result.text_cid,
        "character_count": len(result.text),
    }
    body = dict(receipt)
    receipt_cid = body.pop("receipt_cid")
    assert receipt_cid == cid_for_dag_json(body)
    serialized = json.dumps(receipt, sort_keys=True)
    assert "source_text" not in serialized
    assert "source_map" not in serialized


def test_only_exact_frozen_config_and_policy_are_accepted() -> None:
    request = _request(_rule())
    drifted = dict(SOURCE_WITHHELD_DECOMPILER_CONFIG)
    drifted["obligation_surface"] = "shall"
    object.__setattr__(request, "config", MappingProxyType(drifted))

    result = SourceWithheldCanonicalDecompiler().decompile(request)

    assert result.status is OperationStatus.FAILED
    assert result.error is not None
    assert result.error.code is CanonicalErrorCode.POLICY_MISMATCH
    assert result.error.details["drifted_field"] == "config_cid"
    assert result.text is None
    assert result.component_trace == ()

    policy_drift = _request(_rule())
    object.__setattr__(
        policy_drift,
        "policy_cid",
        SOURCE_WITHHELD_RENDERING_SPEC_CID,
    )
    result = SourceWithheldCanonicalDecompiler().decompile(policy_drift)
    assert result.status is OperationStatus.FAILED
    assert result.error is not None
    assert result.error.code is CanonicalErrorCode.POLICY_MISMATCH
    assert result.error.details["drifted_field"] == "policy_cid"

    detached = frozen_decompiler_config()
    detached["obligation_surface"] = "shall"
    assert dict(SOURCE_WITHHELD_DECOMPILER_CONFIG)[
        "obligation_surface"
    ] == "must"


def test_invalid_requests_and_component_errors_are_typed_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decompiler = SourceWithheldCanonicalDecompiler()

    invalid = decompiler.decompile(  # type: ignore[arg-type]
        {"canonical_ir": _request(_rule()).canonical_ir.to_dict()}
    )
    assert invalid.status is OperationStatus.FAILED
    assert invalid.error is not None
    assert invalid.error.code is CanonicalErrorCode.INVALID_REQUEST
    assert invalid.text is None

    def fail_component(rule: CanonicalRule) -> str:
        raise RuntimeError("synthetic component failure")

    monkeypatch.setattr(module, "decompile_rule", fail_component)
    failed = decompiler.decompile(_request(_rule()))
    assert failed.status is OperationStatus.FAILED
    assert failed.error is not None
    assert failed.error.code is CanonicalErrorCode.COMPONENT_FAILED
    assert failed.error.details["exception_type"] == "RuntimeError"
    assert failed.text is None
    assert failed.component_trace == ()

    with pytest.raises(CanonicalContractError, match="CanonicalRule"):
        decompile_rule({"modality": "O"})  # type: ignore[arg-type]


def test_decompiler_is_stateless_source_withheld_and_model_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        CanonicalRule(
            modality="F",
            actor="agency",
            action="publish",
            object="records",
            conditions=("public_interest",),
        )
    )

    def forbidden_open(*args: object, **kwargs: object) -> object:
        raise AssertionError("decompiler attempted a source-bearing lookup")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    decompiler = SourceWithheldCanonicalDecompiler()
    first = decompiler.decompile(request)
    second = decompiler.decompile(request)

    assert first == second
    assert first.text == "Agency must not publish records if public interest."
    assert decompiler.identity == SELECTED_REALIZER_INTERFACE
    assert decompiler.deterministic is True
    assert decompiler.uses_model is False
    assert isinstance(decompiler, CanonicalStructuredTextDecompiler)
    with pytest.raises(AttributeError):
        decompiler.source_text = "unavailable"  # type: ignore[attr-defined]


def test_production_module_has_no_benchmark_dependency() -> None:
    source = inspect.getsource(module)

    assert "from benchmarks" not in source
    assert "import benchmarks" not in source
