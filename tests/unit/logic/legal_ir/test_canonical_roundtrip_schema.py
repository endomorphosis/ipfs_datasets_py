from __future__ import annotations

import copy
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_DESIGN_GATE_CID,
    CANONICAL_PARITY_POLICY_CID,
    IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
    REPLACEMENT_GATE_CID,
    REPLACEMENT_REPORT_CID,
    SELECTABLE_ARM_IDS,
    SELECTION_BASIS,
    SOURCE_WITHHELD_DECOMPILER_CONFIG,
    SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
    SOURCE_WITHHELD_RENDERING_SPEC_CID,
    SRT014_GATE_CID,
    SRT014_REMEDIATION_MANIFEST_CID,
    SRT014_REPORT_CID,
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CanonicalDiagnostic,
    CanonicalError,
    CanonicalErrorCode,
    CanonicalRoundTripIR,
    CanonicalRule,
    CompilerRequest,
    CompilerResult,
    ComponentTrace,
    DecompilerRequest,
    DecompilerResult,
    DiagnosticSeverity,
    OperationStatus,
    SourceMapEntry,
    UnsupportedDisposition,
    UnsupportedSemantic,
    load_canonical_ir_schema,
    load_parity_policy,
)
from ipfs_datasets_py.utils.cid_utils import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)


ROOT = Path(__file__).resolve().parents[4]
GATE_PATH = (
    ROOT
    / "workspace/benchmarks/semantic-roundtrip-compositions"
    / "replacement_selection_gate.json"
)
POLICY_PATH = (
    ROOT / "docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json"
)
SCHEMA_RELATIVE = (
    "ipfs_datasets_py/logic/legal_ir/schemas/"
    "canonical_roundtrip_ir.schema.json"
)


def _rule() -> CanonicalRule:
    return CanonicalRule(
        modality="O",
        actor="permit_holder",
        action="file",
        object="notice",
        conditions=("work_begins",),
        exceptions=(),
        temporal=("within_10_days",),
    )


def _vocabulary() -> CanonicalAtomVocabulary:
    return CanonicalAtomVocabulary(
        actors=("permit_holder",),
        actions=("file",),
        objects=("notice",),
        qualifiers=("within_10_days", "work_begins"),
    )


def _compiler_request() -> CompilerRequest:
    return CompilerRequest(
        source_text="The permit holder must file notice within ten days.",
        request_id="case-1",
        atom_vocabulary=_vocabulary(),
        config={"document_type": "general"},
    )


def test_authorized_gate_and_exact_tie_lineage_are_bound() -> None:
    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    payload = dict(gate)
    supplied = payload.pop("gate_cid")
    payload.pop("gate_cid_codec")
    payload.pop("gate_cid_scope")

    assert cid_for_dag_json(payload) == supplied == CANONICAL_DESIGN_GATE_CID
    assert gate["launch_authorized"] is True
    assert gate["status"] == "authorized"
    assert gate["replacement_selection_outcome"] == "exact_tie"
    assert tuple(gate["selectable_arm_ids"]) == SELECTABLE_ARM_IDS
    assert (
        gate["implementation_representative_arm_id"]
        == IMPLEMENTATION_REPRESENTATIVE_ARM_ID
    )
    assert gate["selection_basis"] == SELECTION_BASIS
    assert gate["srt014_report_cid"] == SRT014_REPORT_CID
    assert gate["srt014_gate_cid"] == SRT014_GATE_CID
    assert gate["remediation_manifest_cid"] == SRT014_REMEDIATION_MANIFEST_CID
    assert gate["replacement_report_cid"] == REPLACEMENT_REPORT_CID
    assert gate["replacement_gate_cid"] == REPLACEMENT_GATE_CID


def test_parity_policy_is_canonical_and_binds_both_runs() -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    payload = dict(policy)
    supplied = payload.pop("policy_cid")

    assert cid_for_dag_json(payload) == supplied == CANONICAL_PARITY_POLICY_CID
    assert validate_cid(supplied, codecs=("dag-json",)) == supplied
    assert policy["frozen_before_parity_run"] is True
    assert policy["frozen_from_report_cid"] == REPLACEMENT_REPORT_CID
    assert policy["frozen_from_report_cids"] == [
        SRT014_REPORT_CID,
        REPLACEMENT_REPORT_CID,
    ]
    assert policy["metric"] == "end_to_end_loss"
    assert policy["loss_direction"] == "lower_is_better"
    assert policy["comparison"] == "canonical_minus_selected"
    assert (
        policy["aggregation_order"]
        == "repeats_within_case_then_unweighted_macro_average_across_cases"
    )
    assert policy["bootstrap_method"] == (
        "seeded_percentile_case_cluster_bootstrap"
    )
    assert policy["resampling_unit"] == (
        "case_after_within_case_repeat_aggregation"
    )
    assert policy["confidence_level"] == 0.95
    assert policy["bootstrap_samples"] == 10_000
    assert policy["bootstrap_seed"] == 17_291
    assert policy["noninferiority_margin"] == 0.03
    assert policy["selection"]["outcome"] == "exact_tie"
    assert policy["selection"]["representative_semantically_superior"] is False
    assert load_parity_policy().to_dict() == policy


def test_packaged_schema_matches_contract_and_embedded_policy() -> None:
    schema = load_canonical_ir_schema()
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    assert schema["x-interface"] == "CanonicalRoundTripIR@1"
    assert schema["x-schema-version"] == (
        "ipfs-datasets.canonical-roundtrip-ir.v1"
    )
    assert schema["x-canonical-cid"] == {
        "base": "base32",
        "codec": "dag-json",
        "hash": "sha2-256",
        "scope": "entire_semantic_ir_object",
        "version": 1,
    }
    assert schema["x-parity-policy"] == policy

    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(CanonicalRoundTripIR((_rule(),)).to_dict(), schema)

    invalid = CanonicalRoundTripIR((_rule(),)).to_dict()
    invalid["rules"][0]["modality"] = "holding"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)


def test_ir_preserves_measured_payload_shape_and_cid() -> None:
    ir = CanonicalRoundTripIR((_rule(),))

    assert set(ir.to_dict()) == {"rules"}
    assert set(ir.to_dict()["rules"][0]) == {
        "modality",
        "actor",
        "action",
        "object",
        "conditions",
        "exceptions",
        "temporal",
    }
    assert ir.ir_cid == cid_for_dag_json(ir.to_dict())
    assert CanonicalRoundTripIR.from_dict(ir.to_dict()) == ir

    # Values are open vocabulary, but the measured v1 realizer only supports
    # the three deontic operators.
    open_rule = CanonicalRule("P", "novel_actor", "novel_action", "")
    assert open_rule.actor == "novel_actor"
    with pytest.raises(CanonicalContractError, match="O, P, or F"):
        CanonicalRule("holding", "court", "decide")


def test_compiler_request_wire_round_trip_binds_body_and_vocabulary() -> None:
    request = _compiler_request()
    wire = request.to_dict()

    assert CompilerRequest.from_dict(wire) == request
    assert wire["source_cid"] == cid_for_bytes(
        request.source_text.encode("utf-8")
    )
    assert wire["request_cid"] == cid_for_dag_json(request.identity_payload())
    assert isinstance(request.config, MappingProxyType)
    assert isinstance(request.atom_vocabulary.actors, tuple)

    tampered = copy.deepcopy(wire)
    tampered["source_text"] += " Changed."
    with pytest.raises(CanonicalContractError, match="source_cid"):
        CompilerRequest.from_dict(tampered)

    tampered = copy.deepcopy(wire)
    tampered["atom_vocabulary"]["actors"].append("hidden_oracle_actor")
    with pytest.raises(CanonicalContractError, match="request_cid"):
        CompilerRequest.from_dict(tampered)


@pytest.mark.parametrize(
    "forbidden",
    [
        "source_cid",
        "source_map",
        "native_record",
        "native_payload",
        "parse_tree",
    ],
)
def test_decompiler_rejects_every_source_or_native_side_channel(
    forbidden: str,
) -> None:
    ir = CanonicalRoundTripIR((_rule(),))
    config = dict(SOURCE_WITHHELD_DECOMPILER_CONFIG)
    config["nested"] = {forbidden: "secret"}
    with pytest.raises(CanonicalContractError):
        DecompilerRequest(ir, "decompile-1", config=config)


def test_decompiler_accepts_only_measured_source_withheld_profile() -> None:
    from benchmarks.semantic_roundtrip.realizers.source_withheld_paraphrase import (
        FROZEN_REPLACEMENT_CONFIG,
        FROZEN_REPLACEMENT_CONFIG_CID,
        SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID,
    )

    ir = CanonicalRoundTripIR((_rule(),))
    request = DecompilerRequest(ir, "decompile-1")
    wire = request.to_dict()

    assert dict(SOURCE_WITHHELD_DECOMPILER_CONFIG) == dict(
        FROZEN_REPLACEMENT_CONFIG
    )
    assert SOURCE_WITHHELD_DECOMPILER_CONFIG_CID == (
        FROZEN_REPLACEMENT_CONFIG_CID
    )
    assert SOURCE_WITHHELD_RENDERING_SPEC_CID == (
        SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID
    )
    assert cid_for_dag_json(dict(request.config)) == (
        SOURCE_WITHHELD_DECOMPILER_CONFIG_CID
    )
    assert wire["rendering_spec_cid"] == SOURCE_WITHHELD_RENDERING_SPEC_CID
    assert set(wire) == {
        "interface",
        "request_id",
        "canonical_ir",
        "canonical_ir_cid",
        "policy_cid",
        "source_withheld",
        "config",
        "config_cid",
        "rendering_spec_cid",
        "request_cid",
        "request_cid_codec",
        "request_cid_scope",
    }
    assert not {
        "source_text",
        "source_map",
        "source_path",
        "source_cid",
        "native_record",
    } & set(wire)
    assert DecompilerRequest.from_dict(wire) == request

    drifted = dict(SOURCE_WITHHELD_DECOMPILER_CONFIG)
    drifted["notes"] = "could carry the original source"
    with pytest.raises(CanonicalContractError, match="measured source-withheld"):
        DecompilerRequest(ir, "decompile-1", config=drifted)

    tampered = copy.deepcopy(wire)
    tampered["canonical_ir"]["rules"][0]["actor"] = "another_actor"
    with pytest.raises(CanonicalContractError, match="canonical_ir_cid"):
        DecompilerRequest.from_dict(tampered)


def test_compiler_result_has_cid_bound_source_map_and_terminal_invariants() -> None:
    request = _compiler_request()
    rule = _rule()
    ir = CanonicalRoundTripIR((rule,))
    source_map = SourceMapEntry(
        rule_cid=rule.rule_cid,
        field_path="/rules/0/actor",
        source_cid=request.source_cid,
        start=4,
        end=17,
    )
    trace = ComponentTrace(
        component_id="typed_deontic",
        component_interface="TypedDeonticCanonicalConstructor@1",
        input_cid=request.request_cid,
        input_codec="dag-json",
        output_cid=ir.ir_cid,
        output_codec="dag-json",
        config_cid=cid_for_dag_json({"mode": "measured"}),
        deterministic=True,
    )
    result = CompilerResult(
        status=OperationStatus.SUCCESS,
        request_cid=request.request_cid,
        canonical_ir=ir,
        source_map=(source_map,),
        provenance={"arm_id": IMPLEMENTATION_REPRESENTATIVE_ARM_ID},
        diagnostics=(
            CanonicalDiagnostic(
                "compiler.measured_path",
                "The measured deterministic path was used.",
                DiagnosticSeverity.INFO,
            ),
        ),
        component_trace=(trace,),
    )

    receipt = result.source_map_receipt()
    assert receipt is not None
    receipt_body = dict(receipt)
    receipt_cid = receipt_body.pop("receipt_cid")
    assert receipt_cid == cid_for_dag_json(receipt_body)
    assert result.to_dict()["result_cid"] == result.result_cid
    assert CompilerResult.from_dict(result.to_dict()) == result
    assert isinstance(result.provenance, MappingProxyType)

    unsupported = UnsupportedSemantic(
        code="caselaw.holding",
        message="Holding force is outside v1.",
        disposition=UnsupportedDisposition.ABSTAIN,
        source_cid=request.source_cid,
        start=0,
        end=3,
    )
    with pytest.raises(CanonicalContractError, match="abstain-required"):
        CompilerResult(
            status=OperationStatus.SUCCESS,
            request_cid=request.request_cid,
            canonical_ir=ir,
            unsupported_semantics=(unsupported,),
        )

    error = CanonicalError(
        CanonicalErrorCode.UNSUPPORTED_SEMANTICS,
        "The compiler abstained.",
    )
    abstained = CompilerResult(
        status=OperationStatus.ABSTAINED,
        request_cid=request.request_cid,
        unsupported_semantics=(unsupported,),
        error=error,
    )
    assert abstained.canonical_ir is None
    assert abstained.result_cid == cid_for_dag_json(abstained.identity_payload())
    assert CompilerResult.from_dict(abstained.to_dict()) == abstained


def test_decompiler_result_supports_raw_text_attribution() -> None:
    ir = CanonicalRoundTripIR((_rule(),))
    request = DecompilerRequest(ir, "decompile-1")
    text = "The permit holder must file notice."
    text_cid = cid_for_bytes(text.encode("utf-8"))
    trace = ComponentTrace(
        component_id="source_withheld_paraphrase",
        component_interface="SourceWithheldCanonicalParaphraser@1",
        input_cid=ir.ir_cid,
        input_codec="dag-json",
        output_cid=text_cid,
        output_codec="raw",
        config_cid=SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
        deterministic=True,
    )
    result = DecompilerResult(
        status=OperationStatus.SUCCESS,
        request_cid=request.request_cid,
        text=text,
        text_cid=text_cid,
        component_trace=(trace,),
    )

    assert result.to_dict()["source_withheld"] is True
    assert result.to_dict()["result_cid"] == result.result_cid
    assert DecompilerResult.from_dict(result.to_dict()) == result
    with pytest.raises(CanonicalContractError, match="text_cid"):
        DecompilerResult(
            status=OperationStatus.SUCCESS,
            request_cid=request.request_cid,
            text=text + " Changed.",
            text_cid=text_cid,
        )


def test_schema_is_declared_in_all_distribution_manifests() -> None:
    setup_text = (ROOT / "setup.py").read_text(encoding="utf-8")
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    manifest_text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert '"logic/legal_ir/schemas/*.json"' in setup_text
    assert '"logic/legal_ir/schemas/*.json"' in pyproject_text
    assert (
        "recursive-include ipfs_datasets_py/logic/legal_ir/schemas *.json"
        in manifest_text
    )
    assert (ROOT / SCHEMA_RELATIVE).is_file()
