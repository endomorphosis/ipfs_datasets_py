from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest

from ipfs_datasets_py.logic.legal_ir.canonical_compiler import (
    MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID,
    TYPED_DEONTIC_COMPILER_CONFIG,
    TYPED_DEONTIC_COMPILER_CONFIG_CID,
    CanonicalCompiler,
    TypedDeonticCanonicalCompiler,
    compiler_configuration,
    project_legal_norms,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
    IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID,
    SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID,
    SELECTED_CONSTRUCTOR_INTERFACE,
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CanonicalStructuredTextCompiler,
    CompilerRequest,
    CompilerResult,
    OperationStatus,
    UnsupportedDisposition,
)
from ipfs_datasets_py.utils.cid_utils import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)


ROOT = Path(__file__).resolve().parents[4]


@dataclass
class _Norm:
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.data)


def _vocabulary(
    *,
    actors: tuple[str, ...] = ("agency", "company_a"),
    actions: tuple[str, ...] = ("file", "submit", "withdraw"),
    objects: tuple[str, ...] = ("backup_report", "notice"),
    qualifiers: tuple[str, ...] = (
        "emergency",
        "natural_disaster",
        "within_10_days",
    ),
) -> CanonicalAtomVocabulary:
    return CanonicalAtomVocabulary(
        actors=actors,
        actions=actions,
        objects=objects,
        qualifiers=qualifiers,
    )


def _request(
    source_text: str = (
        "Company A shall submit backup report within 10 days unless emergency."
    ),
    *,
    vocabulary: CanonicalAtomVocabulary | None = None,
    allow_explicit_partial: bool = False,
    config: dict[str, object] | None = None,
) -> CompilerRequest:
    return CompilerRequest(
        source_text=source_text,
        request_id="compiler-test",
        atom_vocabulary=vocabulary or _vocabulary(),
        allow_explicit_partial=allow_explicit_partial,
        config={} if config is None else config,
    )


def test_projection_matches_reviewed_typed_deontic_semantics() -> None:
    norms = [
        _Norm(
            {
                "modality": "permission",
                "norm_type": "permission",
                "actor": "the agency",
                "action": "withdraw the filing",
                "action_verb": "withdraws",
                "action_object": "",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": "must not cross the boundary",
            }
        ),
        _Norm(
            {
                "modality": "obligation",
                "norm_type": "obligation",
                "actor": "Company A",
                "action": "submit backup report",
                "action_verb": "submit",
                "action_object": "backup report",
                "conditions": [{"text": "natural disaster"}],
                "exceptions": [{"text": "emergency"}],
                "temporal_constraints": [{"text": "within 10 days"}],
            }
        ),
    ]

    projected = project_legal_norms(norms, _vocabulary())

    assert projected.to_dict() == {
        "rules": [
            {
                "modality": "O",
                "actor": "company_a",
                "action": "submit",
                "object": "backup_report",
                "conditions": ["natural_disaster"],
                "exceptions": ["emergency"],
                "temporal": ["within_10_days"],
            },
            {
                "modality": "P",
                "actor": "agency",
                "action": "withdraw",
                "object": "",
                "conditions": [],
                "exceptions": [],
                "temporal": [],
            },
        ]
    }
    assert "must not cross the boundary" not in repr(projected)


def test_projection_rejects_unrepresented_semantic_facets() -> None:
    norm = _Norm(
        {
            "modality": "obligation",
            "norm_type": "obligation",
            "actor": "Company A",
            "action": "submit backup report",
            "action_verb": "submit",
            "action_object": "backup report",
            "conditions": [],
            "exceptions": [],
            "temporal_constraints": [],
            "mental_state": "knowingly",
        }
    )

    with pytest.raises(
        CanonicalContractError,
        match="unsupported semantics",
    ):
        project_legal_norms((norm,), _vocabulary())


def test_projection_rejects_unmapped_qualifier_values() -> None:
    norm = _Norm(
        {
            "modality": "obligation",
            "norm_type": "obligation",
            "actor": "Company A",
            "action": "submit backup report",
            "action_verb": "submit",
            "action_object": "backup report",
            "conditions": [{"text": "after a secret tribunal finding"}],
            "exceptions": [],
            "temporal_constraints": [],
        }
    )

    with pytest.raises(
        CanonicalContractError,
        match="unsupported semantics",
    ):
        project_legal_norms((norm,), _vocabulary())


def test_compiler_success_has_cid_bound_ir_source_map_and_lineage() -> None:
    request = _request()
    compiler = TypedDeonticCanonicalCompiler()

    result = compiler.compile(request)

    assert result.status is OperationStatus.SUCCESS
    assert result.unsupported_semantics == ()
    assert result.canonical_ir is not None
    assert result.canonical_ir.to_dict() == {
        "rules": [
            {
                "modality": "O",
                "actor": "company_a",
                "action": "submit",
                "object": "backup_report",
                "conditions": [],
                "exceptions": ["emergency"],
                "temporal": ["within_10_days"],
            }
        ]
    }
    assert CompilerResult.from_dict(result.to_dict()) == result
    validate_cid(result.canonical_ir.ir_cid, codecs=("dag-json",))
    validate_cid(result.result_cid, codecs=("dag-json",))

    receipt = result.source_map_receipt()
    assert receipt is not None
    receipt_payload = dict(receipt)
    receipt_cid = receipt_payload.pop("receipt_cid")
    assert receipt_cid == cid_for_dag_json(receipt_payload)
    assert len(receipt["entries"]) == 7
    assert {
        entry["field_path"].rsplit("/", 1)[-1]
        for entry in receipt["entries"]
    } == {
        "modality",
        "actor",
        "action",
        "object",
        "conditions",
        "exceptions",
        "temporal",
    }
    assert all(
        entry["source_cid"] == request.source_cid
        and 0 <= entry["start"] < entry["end"] <= len(request.source_text)
        and entry["attribution"] == "coarse:typed_deontic_record_span"
        for entry in receipt["entries"]
    )

    assert len(result.component_trace) == 1
    trace = result.component_trace[0]
    assert trace.component_id == IMPLEMENTATION_REPRESENTATIVE_ARM_ID
    assert trace.component_interface == SELECTED_CONSTRUCTOR_INTERFACE
    assert trace.input_cid == request.request_cid
    assert trace.output_cid == result.canonical_ir.ir_cid
    assert trace.config_cid == TYPED_DEONTIC_COMPILER_CONFIG_CID
    assert trace.deterministic is True
    assert trace.model_receipt_cid is None

    provenance = dict(result.provenance)
    assert provenance["constructor_adapter_raw_cid"] == (
        SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID
    )
    # Residual LIG-003 hygiene: current on-disk adapter bytes pin (may differ
    # from the historical selection identity above after deliberate updates).
    assert provenance["measured_adapter_raw_cid"] == (
        MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID
    )
    assert provenance["implementation_representative_arm_identity_cid"] == (
        IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID
    )
    assert provenance["compiler_config_cid"] == (
        TYPED_DEONTIC_COMPILER_CONFIG_CID
    )
    assert provenance["fallback_used"] is False
    assert provenance["learned_stages"] == ()
    assert provenance["model_call_count"] == 0
    provenance_cid = provenance.pop("provenance_cid")
    assert provenance_cid == cid_for_dag_json(
        {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in provenance.items()
        }
    )


def test_frozen_cases_reproduce_benchmark_adapter_l1_exactly() -> None:
    # The benchmark package and its five-case vocabularies are an oracle only
    # in this conformance test.  The production module has no such dependency.
    from benchmarks.semantic_roundtrip import (
        AllowedAtomVocabulary,
        ConstructorRequest,
    )
    from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
        TypedDeonticCanonicalConstructor,
    )

    fixture_path = (
        ROOT
        / "tests"
        / "fixtures"
        / "semantic_roundtrip"
        / "pilot_cases.json"
    )
    adapter_path = (
        ROOT
        / "benchmarks"
        / "semantic_roundtrip"
        / "constructors"
        / "typed_deontic.py"
    )
    assert cid_for_bytes(fixture_path.read_bytes()) == (
        "bafkreidngtg5cojnhkmwj4coijqpoixao25hxfwdzxjpywlusrqhk3hrm4"
    )
    # Residual LIG-003 CID hygiene: pin the *current* measured adapter module
    # bytes.  This is a deliberate golden update after the adapter grew under
    # EVAL-005 (selective-repair surface) while pure construct L1 stayed
    # equivalent.  Distinct from SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID, which
    # remains the historical replacement-gate selection identity.
    # Do not weaken this exact-CID integrity check.
    assert cid_for_bytes(adapter_path.read_bytes()) == (
        MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID
    )
    assert MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID != (
        SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID
    )
    validate_cid(
        MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID,
        codecs=("raw",),
    )
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert tuple(case["id"] for case in cases) == (
        "exception_with_window",
        "legal_doc_1",
        "exec_order_1",
        "corp_policy_1",
        "construction_contract",
    )
    oracle = TypedDeonticCanonicalConstructor()
    compiler = TypedDeonticCanonicalCompiler()

    for case in cases:
        oracle_vocabulary = AllowedAtomVocabulary.from_dict(
            case["allowed_atoms"]
        )
        vocabulary = CanonicalAtomVocabulary.from_dict(case["allowed_atoms"])
        expected = oracle.construct(
            ConstructorRequest(case["source_text"], oracle_vocabulary, {})
        )
        actual = compiler.compile(
            CompilerRequest(
                source_text=case["source_text"],
                request_id=f"frozen-{case['id']}",
                atom_vocabulary=vocabulary,
                # Some frozen documents contain meaning outside the seven
                # canonical fields or public case vocabulary.  The measured
                # adapter omits it; v1 reproduces that exact L1 only through
                # this explicit, visible partial disposition.
                allow_explicit_partial=True,
            )
        )

        assert actual.status is OperationStatus.SUCCESS, case["id"]
        assert actual.canonical_ir is not None
        assert expected.canonical_ir is not None
        # Golden L1 remains stable under the deliberate adapter-byte hygiene
        # update (pure construct semantics unchanged after EVAL-005 surface).
        assert actual.canonical_ir.to_dict() == (
            expected.canonical_ir.to_dict()
        ), case["id"]
        assert actual.canonical_ir.ir_cid == cid_for_dag_json(
            actual.canonical_ir.to_dict()
        )


def test_unmapped_semantics_abstain_or_are_explicitly_partial() -> None:
    source = (
        "Company A shall submit backup report. "
        "Unknown party must invent widgets."
    )
    strict = TypedDeonticCanonicalCompiler().compile(_request(source))

    assert strict.status is OperationStatus.ABSTAINED
    assert strict.canonical_ir is None
    assert strict.error is not None
    assert strict.error.code.value == "unsupported_semantics"
    assert strict.unsupported_semantics
    assert all(
        item.disposition is UnsupportedDisposition.ABSTAIN
        for item in strict.unsupported_semantics
    )

    partial = TypedDeonticCanonicalCompiler().compile(
        _request(source, allow_explicit_partial=True)
    )
    assert partial.status is OperationStatus.SUCCESS
    assert partial.canonical_ir is not None
    assert partial.unsupported_semantics
    assert all(
        item.disposition is UnsupportedDisposition.EXPLICIT_PARTIAL
        for item in partial.unsupported_semantics
    )


def test_empty_parser_output_is_typed_and_does_not_fabricate_ir() -> None:
    result = TypedDeonticCanonicalCompiler().compile(
        _request("This paragraph contains no normative rule.")
    )

    assert result.status is OperationStatus.FAILED
    assert result.canonical_ir is None
    assert result.error is not None
    assert result.error.code.value == "empty_output"
    assert not result.source_map
    assert not result.component_trace


@pytest.mark.parametrize(
    "config",
    [
        {"use_ml": True},
        {"repair": "silent"},
        {"fallback": "model"},
        {"document_type": "caselaw"},
    ],
)
def test_unmeasured_or_learned_config_is_rejected_without_fallback(
    config: dict[str, object],
) -> None:
    result = TypedDeonticCanonicalCompiler().compile(
        _request(config=config)
    )

    assert result.status is OperationStatus.FAILED
    assert result.error is not None
    assert result.error.code.value == "invalid_request"
    assert result.provenance["fallback_used"] is False
    assert result.provenance["model_call_count"] == 0


def test_unavailable_component_is_a_retryable_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ipfs_datasets_py.logic.legal_ir.canonical_compiler as module

    def unavailable() -> tuple[type[object], type[object]]:
        raise ImportError("test-only unavailable capability")

    monkeypatch.setattr(module, "_load_deontic_components", unavailable)
    result = TypedDeonticCanonicalCompiler().compile(_request())

    assert result.status is OperationStatus.FAILED
    assert result.error is not None
    assert result.error.code.value == "component_unavailable"
    assert result.error.retryable is True
    assert result.canonical_ir is None


def test_configuration_and_protocol_identity_are_stable() -> None:
    compiler = CanonicalCompiler()

    assert compiler.identity == CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE
    assert isinstance(compiler, CanonicalStructuredTextCompiler)
    assert compiler.configuration_cid == TYPED_DEONTIC_COMPILER_CONFIG_CID
    assert cid_for_dag_json(compiler_configuration()) == (
        TYPED_DEONTIC_COMPILER_CONFIG_CID
    )
    assert isinstance(TYPED_DEONTIC_COMPILER_CONFIG, MappingProxyType)
    assert isinstance(
        TYPED_DEONTIC_COMPILER_CONFIG["converter"],
        MappingProxyType,
    )
    # Measured config still binds shared selection lineage, not the live
    # adapter-byte pin (that pin is residual hygiene beside selection).
    constructor_cfg = TYPED_DEONTIC_COMPILER_CONFIG["constructor"]
    assert isinstance(constructor_cfg, MappingProxyType)
    assert constructor_cfg["adapter_raw_cid"] == (
        SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID
    )
    with pytest.raises(TypeError):
        TYPED_DEONTIC_COMPILER_CONFIG["fallback_allowed"] = True
    with pytest.raises(TypeError):
        converter_config = TYPED_DEONTIC_COMPILER_CONFIG["converter"]
        assert isinstance(converter_config, MappingProxyType)
        converter_config["use_ml"] = True
    validate_cid(
        TYPED_DEONTIC_COMPILER_CONFIG_CID,
        codecs=("dag-json",),
    )
    validate_cid(
        MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID,
        codecs=("raw",),
    )
    with pytest.raises(CanonicalContractError, match="CompilerRequest"):
        compiler.compile(object())  # type: ignore[arg-type]
