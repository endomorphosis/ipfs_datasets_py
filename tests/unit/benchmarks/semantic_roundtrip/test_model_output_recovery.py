from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.utils.cid_utils import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)

from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ContractError,
    FailureReason,
    RealizerRequest,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LeanstralMalformedResponseError,
)
from benchmarks.semantic_roundtrip.constructors.symai import SyMAICompletion
from benchmarks.semantic_roundtrip.model_output_recovery import (
    BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE,
    DIRECT_ROUTE_ID,
    FROZEN_SRT021_REMEDIATION_EVIDENCE,
    LEANSTRAL_TOKENIZER_IDENTITY,
    PREREGISTERED_RESEARCH_RECOVERY_POLICY,
    PREREGISTERED_SRT023_POLICY,
    PROMOTION_RECOVERY_POLICY,
    SRT014_REPORT_CID,
    SRT021_MANIFEST_CID,
    SRT021_MANIFEST_GATE_CID,
    SRT021_MANIFEST_RELATIVE_PATH,
    SYMAI_POLARITY_CONTRACT_INTERFACE,
    TYPED_REJECTION_REASONS,
    ArmReliabilityMetrics,
    BoundedModelOutputRecovery,
    ModelCallReceipt,
    ModelOutputRecoveryReceipt,
    ModelRejectionReason,
    RecoveryPolicy,
    RecoveryPolicyKind,
    RecoveryRole,
    RecoveryRoute,
    RecoverySchemaPath,
    SyMAIPolarityContract,
    arm_reliability_metrics,
    classify_model_rejection,
    load_srt021_remediation_evidence,
)
from benchmarks.semantic_roundtrip_capabilities import (
    LEANSTRAL_BACKEND,
    LEANSTRAL_BACKEND_OWNER,
    LEANSTRAL_CAPACITY,
    LEANSTRAL_PROVIDER,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


VOCABULARY = AllowedAtomVocabulary(
    actors=("administrator", "controller", "processor"),
    actions=("delete", "disclose", "retain"),
    objects=("records",),
    qualifiers=("after_30_days", "unless_required_by_law"),
)
IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
            temporal=("after_30_days",),
        ),
        CanonicalRule(
            modality="P",
            actor="administrator",
            action="disclose",
            object="records",
        ),
        CanonicalRule(
            modality="F",
            actor="processor",
            action="retain",
            object="records",
            exceptions=("unless_required_by_law",),
        ),
    )
)


def constructor_request(
    source: str = "A bounded public source sentence.",
) -> ConstructorRequest:
    return ConstructorRequest(source, VOCABULARY, {"public_label": "case-a"})


def realizer_request(
    marker: str = "PRIVATE_MARKER_MUST_NOT_BE_SERIALIZED",
) -> RealizerRequest:
    return RealizerRequest(IR, VOCABULARY, {"display_marker": marker})


def realization(
    overrides: dict[int, dict[str, object]] | None = None,
) -> dict[str, object]:
    text = {
        "F": "The processor must not retain records unless required by law.",
        "O": "The controller must delete records after 30 days.",
        "P": "The administrator may disclose records.",
    }
    rows: list[dict[str, object]] = []
    for index, rule in enumerate(IR.rules):
        row: dict[str, object] = {
            "index": index,
            "modality": rule.modality,
            "polarity": {
                "O": "obligation",
                "P": "permission",
                "F": "prohibition",
            }[rule.modality],
            "text": text[rule.modality],
        }
        row.update((overrides or {}).get(index, {}))
        rows.append(row)
    return {"rules": rows}


ROUTE_METADATA = {
    "resolved_provider_name": LEANSTRAL_PROVIDER,
    "resolved_model_name": LEANSTRAL_MODEL,
    "service_endpoint": LEANSTRAL_ENDPOINT,
    "routing_backend": LEANSTRAL_BACKEND,
    "attempts": 1,
    "retries": 0,
    "cache_enabled": False,
    "cache_hit": False,
}


class RecordingClient:
    endpoint = LEANSTRAL_ENDPOINT
    model = LEANSTRAL_MODEL

    def __init__(
        self,
        responses: list[object],
        *,
        symai: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.responses = responses
        self.symai = symai
        self.metadata = metadata or ROUTE_METADATA
        self.calls: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> Any:
        self.calls.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        if self.symai:
            return SyMAICompletion(value, self.metadata)  # type: ignore[arg-type]
        return value


def readdress_receipt(value: dict[str, object]) -> dict[str, object]:
    """Deep-copy and recompute one call or recovery receipt CID."""

    addressed = json.loads(json.dumps(value))
    body = dict(addressed)
    del body["receipt_cid"]
    addressed["receipt_cid"] = cid_for_dag_json(body)
    return addressed


def test_interfaces_bind_the_exact_model_envelope_and_route_identity() -> None:
    direct = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()]), route=RecoveryRoute.DIRECT
    )
    symai = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()], symai=True),
        route=RecoveryRoute.SYMAI,
    )

    assert direct.interface == BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE
    assert SyMAIPolarityContract.interface == SYMAI_POLARITY_CONTRACT_INTERFACE
    for wrapper in (direct, symai):
        assert LEANSTRAL_ENDPOINT in wrapper.identity
        assert LEANSTRAL_BACKEND in wrapper.identity
        assert LEANSTRAL_MODEL in wrapper.identity
        assert LEANSTRAL_TOKENIZER_IDENTITY in wrapper.identity
        assert f"slots={LEANSTRAL_CAPACITY}" in wrapper.identity
        assert "cache=disabled" in wrapper.identity
    assert DIRECT_ROUTE_ID in direct.identity
    assert "symai_router" in symai.identity

    result = direct.recover_l1(constructor_request())
    identity = result.receipt.to_dict()["identity"]
    assert identity == {
        "provider": LEANSTRAL_PROVIDER,
        "endpoint": LEANSTRAL_ENDPOINT,
        "backend": LEANSTRAL_BACKEND,
        "backend_owner": LEANSTRAL_BACKEND_OWNER,
        "model": LEANSTRAL_MODEL,
        "tokenizer": LEANSTRAL_TOKENIZER_IDENTITY,
        "route": "direct",
        "route_id": DIRECT_ROUTE_ID,
        "direct_and_symai_are_independent_models": False,
        "physical_model_slots": 1,
        "execution": "globally_serialized_one_slot",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("endpoint", "http://127.0.0.1:9999/v1"),
        ("model", "substitute-model"),
        ("backend", "transformers"),
        ("tokenizer", "substitute-tokenizer"),
        ("parallel_slots", 2),
        ("cache_enabled", True),
    ],
)
def test_identity_cache_or_capacity_drift_is_rejected_before_a_call(
    field: str, value: object
) -> None:
    client = SimpleNamespace(
        endpoint=LEANSTRAL_ENDPOINT,
        model=LEANSTRAL_MODEL,
        complete_json=lambda **_: IR.to_dict(),
    )
    setattr(client, field, value)

    with pytest.raises(ContractError, match="frozen|cache"):
        BoundedModelOutputRecovery(client, route="direct")  # type: ignore[arg-type]


def test_role_specific_bounded_schemas_and_explicit_polarity_instructions() -> None:
    client = RecordingClient([IR.to_dict(), realization(), IR.to_dict()])
    recovery = BoundedModelOutputRecovery(client, route="direct")

    l1 = recovery.recover_l1(constructor_request())
    t1 = recovery.recover_t1(realizer_request())
    l2 = recovery.recover_l2(
        constructor_request(t1.text or ""), expected_ir=IR
    )

    assert l1.status is ComponentStatus.SUCCESS
    assert t1.status is ComponentStatus.SUCCESS
    assert l2.status is ComponentStatus.SUCCESS
    assert l1.canonical_ir == IR
    assert l2.canonical_ir == IR
    assert t1.text == (
        "The processor must not retain records unless required by law. "
        "The controller must delete records after 30 days. "
        "The administrator may disclose records."
    )

    assert [call["schema_name"] for call in client.calls] == [
        "srt023_replacement_l1_canonical_ir_v1",
        "srt023_replacement_t1_realization_v1",
        "srt023_replacement_l2_canonical_ir_v1",
    ]
    for index in (0, 2):
        canonical_rules = client.calls[index]["schema"]["properties"]["rules"]
        assert canonical_rules["minItems"] == 1
        assert canonical_rules["maxItems"] == 16
    for call in client.calls:
        system = str(call["system"])
        assert "O means obligation" in system
        assert "P means permission" in system
        assert "F means prohibition" in system
        assert "'may not'" in system
    t1_schema = client.calls[1]["schema"]
    rules = t1_schema["properties"]["rules"]  # type: ignore[index]
    assert rules["minItems"] == rules["maxItems"] == len(IR.rules)
    properties = rules["items"]["properties"]
    assert properties["modality"]["enum"] == ["O", "P", "F"]
    assert properties["polarity"]["enum"] == [
        "obligation",
        "permission",
        "prohibition",
    ]


def test_t1_is_source_withheld_and_results_are_never_reused() -> None:
    marker = "PRIVATE_SOURCE_RECOVERY_SENTINEL"
    client = RecordingClient([realization(), realization()])
    recovery = BoundedModelOutputRecovery(client, route="direct")
    request = realizer_request(marker)

    first = recovery.recover_t1(request)
    second = recovery.recover_t1(request)

    assert first.status is second.status is ComponentStatus.SUCCESS
    assert len(client.calls) == 2
    assert marker not in str(client.calls)
    assert "CANONICAL_IR_JSON" in str(client.calls[0]["prompt"])
    for result in (first, second):
        receipt = result.receipt.to_dict()
        assert receipt["boundary"] == {
            "source_withheld": True,
            "source_recovery_allowed": False,
            "fallback_allowed": False,
            "route_substitution_allowed": False,
            "cross_call_result_reuse_allowed": False,
        }
        assert receipt["cache"] == {
            "prompt_cache_enabled": False,
            "response_cache_enabled": False,
            "cache_hit": False,
        }
        assert receipt["calls"][0]["cache"]["result_reused"] is False


@pytest.mark.parametrize(
    ("first", "rejection"),
    [
        ({"rules": []}, "blank_output"),
        ({"rules": [{"bad": "shape"}]}, "malformed_output"),
        (
            realization(
                {
                    0: {
                        "text": "The processor may not retain records.",
                    }
                }
            ),
            "polarity_ambiguous",
        ),
    ],
)
def test_rejected_t1_gets_only_the_preregistered_bounded_retry(
    first: object, rejection: str
) -> None:
    client = RecordingClient([first, realization()])
    recovery = BoundedModelOutputRecovery(client, route="direct")

    result = recovery.recover_t1(realizer_request())

    assert result.status is ComponentStatus.SUCCESS
    assert len(client.calls) == 2
    receipt = result.receipt
    assert receipt.retries == 1
    assert [call.outcome for call in receipt.calls] == [
        "rejected",
        "accepted",
    ]
    assert receipt.calls[0].rejection == rejection
    assert receipt.calls[1].attempt_kind == "preregistered_retry"
    assert rejection in str(client.calls[1]["prompt"])
    assert "PRIVATE_MARKER" not in str(client.calls[1])


def test_empty_l1_and_l2_rejections_retain_role_specific_typed_failures() -> None:
    no_retry = RecoveryPolicy("srt-023-no-retry-negative-control", 0)
    l1 = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}]),
        route="direct",
        policy=no_retry,
    ).recover_l1(constructor_request())
    l2 = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}]),
        route="direct",
        policy=no_retry,
    ).recover_l2(constructor_request(), expected_ir=IR)

    assert l1.failure_reason is FailureReason.EMPTY_L1
    assert l2.failure_reason is FailureReason.EMPTY_L2
    assert l1.receipt.terminal_rejection == "empty_output"
    assert l2.receipt.terminal_rejection == "empty_output"
    assert l1.receipt.calls[0].failure_reason is FailureReason.EMPTY_L1
    assert l2.receipt.calls[0].failure_reason is FailureReason.EMPTY_L2


def test_exhausted_retry_retains_both_rejections_and_terminal_typed_failure() -> None:
    client = RecordingClient([{"rules": []}, {"rules": []}])
    recovery = BoundedModelOutputRecovery(client, route="direct")

    result = recovery.recover_l1(constructor_request())

    assert result.status is ComponentStatus.FAILED
    assert result.failure_reason is FailureReason.RETRY_EXHAUSTED
    assert len(client.calls) == 2
    receipt = result.receipt.to_dict()
    assert receipt["call_count"] == 2
    assert receipt["rejection_count"] == 2
    assert receipt["retry_count"] == 1
    assert receipt["terminal_failure"] == "retry_exhausted"
    assert receipt["terminal_rejection"] == "empty_output"
    assert [call["failure_reason"] for call in receipt["calls"]] == [
        "empty_l1",
        "empty_l1",
    ]


def test_malformed_provider_output_is_recorded_and_can_use_only_one_retry() -> None:
    client = RecordingClient(
        [
            LeanstralMalformedResponseError("bad provider envelope"),
            IR.to_dict(),
        ]
    )
    recovery = BoundedModelOutputRecovery(client, route="direct")

    result = recovery.recover_l1(constructor_request())

    assert result.status is ComponentStatus.SUCCESS
    assert [call.outcome for call in result.receipt.calls] == [
        "call_failed",
        "accepted",
    ]
    assert result.receipt.calls[0].rejection == "malformed_output"
    assert result.receipt.calls[0].failure_reason is FailureReason.INVALID_OUTPUT


def test_symai_route_receipts_are_retained_and_route_drift_never_falls_back() -> None:
    accepted_client = RecordingClient([realization()], symai=True)
    accepted = BoundedModelOutputRecovery(
        accepted_client, route="symai"
    ).recover_t1(realizer_request())

    assert accepted.status is ComponentStatus.SUCCESS
    call = accepted.receipt.to_dict()["calls"][0]
    route = call["symai_route_receipt"]["routing"]
    assert route["route"] == "symai_router"
    assert route["resolved_endpoint"] == LEANSTRAL_ENDPOINT
    assert route["resolved_model"] == LEANSTRAL_MODEL
    assert route["resolved_backend"] == LEANSTRAL_BACKEND
    assert route["shared_capacity"] == 1

    drift_client = RecordingClient(
        [IR.to_dict()],
        symai=True,
        metadata={**ROUTE_METADATA, "resolved_model_name": "other-model"},
    )
    failed = BoundedModelOutputRecovery(
        drift_client, route="symai"
    ).recover_l1(constructor_request())

    assert failed.failure_reason is FailureReason.CAPABILITY_UNAVAILABLE
    assert len(drift_client.calls) == 1
    assert failed.receipt.calls[0].outcome == "call_failed"
    assert failed.receipt.calls[0].rejection == "route_contract_failure"
    assert failed.receipt.retries == 0


def test_l2_polarity_mismatch_is_rejected_instead_of_silently_accepted() -> None:
    inverted = IR.to_dict()
    inverted["rules"][0]["modality"] = "O"
    client = RecordingClient([inverted, inverted])
    recovery = BoundedModelOutputRecovery(client, route="direct")

    result = recovery.recover_l2(
        constructor_request("Reconstructed bounded text."),
        expected_ir=IR,
    )

    assert result.failure_reason is FailureReason.RETRY_EXHAUSTED
    assert result.receipt.terminal_rejection == "polarity_ambiguous"
    assert all(
        call.rejection == "polarity_ambiguous"
        for call in result.receipt.calls
    )


def test_policy_is_bounded_and_cannot_add_an_unregistered_retry_class() -> None:
    assert PREREGISTERED_SRT023_POLICY.max_retries == 1
    with pytest.raises(ContractError, match="at most one"):
        RecoveryPolicy("srt-023-unbounded", 2)
    with pytest.raises(ContractError, match="preregistration"):
        RecoveryPolicy(
            "srt-023-route-substitution",
            1,
            ("route_contract_failure",),
        )
    with pytest.raises(ContractError, match="replacement experiment"):
        RecoveryPolicy("production-run", 1)


def test_all_wrappers_share_one_serialized_physical_slot() -> None:
    class BlockingClient:
        endpoint = LEANSTRAL_ENDPOINT
        model = LEANSTRAL_MODEL

        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.release = threading.Event()
            self.first_entered = threading.Event()
            self.active = 0
            self.max_active = 0
            self.call_count = 0

        def complete_json(self, **_: object) -> dict[str, object]:
            with self.lock:
                self.call_count += 1
                call_number = self.call_count
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            if call_number == 1:
                self.first_entered.set()
                assert self.release.wait(timeout=2)
            with self.lock:
                self.active -= 1
            return IR.to_dict()

    client = BlockingClient()
    first = BoundedModelOutputRecovery(client, route="direct")
    second = BoundedModelOutputRecovery(client, route="direct")
    results: list[object] = []

    threads = [
        threading.Thread(
            target=lambda wrapper=wrapper: results.append(
                wrapper.recover_l1(constructor_request())
            )
        )
        for wrapper in (first, second)
    ]
    threads[0].start()
    assert client.first_entered.wait(timeout=2)
    threads[1].start()
    client.release.set()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert client.call_count == 2
    assert client.max_active == 1
    assert all(
        result.status is ComponentStatus.SUCCESS  # type: ignore[union-attr]
        for result in results
    )


def test_frozen_srt021_evidence_binds_exact_report_gate_and_coordinates() -> None:
    evidence = load_srt021_remediation_evidence(REPO_ROOT)

    assert evidence is not None
    assert evidence == FROZEN_SRT021_REMEDIATION_EVIDENCE
    assert evidence.manifest_cid == SRT021_MANIFEST_CID
    assert evidence.manifest_gate_cid == SRT021_MANIFEST_GATE_CID
    assert evidence.report_cid == SRT014_REPORT_CID
    assert validate_cid(evidence.manifest_cid, codecs=("dag-json",))
    assert validate_cid(evidence.manifest_gate_cid, codecs=("dag-json",))
    assert validate_cid(evidence.report_cid, codecs=("dag-json",))

    serialized = evidence.to_dict()
    evidence_cid = serialized.pop("evidence_cid")
    assert evidence_cid == cid_for_dag_json(serialized)
    assert evidence.remediation_targets == (
        "blank_t1",
        "empty_l1",
        "empty_l2",
        "polarity_ambiguous",
        "route_contract_failure",
    )
    coordinates = evidence.to_dict()["coordinates"]
    model = [
        coordinate
        for coordinate in coordinates
        if str(coordinate["arm_id"]).startswith("model__")
    ]
    modal_spacy = [
        coordinate
        for coordinate in coordinates
        if str(coordinate["arm_id"]).startswith("modal_spacy__")
    ]
    assert len(model) == 5
    assert {
        (
            coordinate["case_id"],
            coordinate["repeat_index"],
            coordinate["gate_id"],
        )
        for coordinate in model
    } == {
        ("legal_doc_1", repeat, "polarity_preservation")
        for repeat in range(5)
    }
    assert len(modal_spacy) == 4
    assert {
        coordinate["case_id"] for coordinate in modal_spacy
    } == {
        "construction_contract",
        "corp_policy_1",
        "exec_order_1",
        "legal_doc_1",
    }
    assert {
        coordinate["repeat_index"] for coordinate in modal_spacy
    } == {0}

    policy = PREREGISTERED_SRT023_POLICY.to_dict()
    policy_cid = policy.pop("policy_cid")
    assert policy["remediation_evidence"] == evidence.to_dict()
    assert policy_cid == cid_for_dag_json(policy)


def test_request_prompt_call_and_recovery_cids_are_content_sensitive() -> None:
    first_source = "The controller shall delete records."
    second_source = "The controller may disclose records."
    client = RecordingClient([IR.to_dict(), IR.to_dict()])
    recovery = BoundedModelOutputRecovery(client, route="direct")

    first = recovery.recover_l1(constructor_request(first_source))
    second = recovery.recover_l1(constructor_request(second_source))

    first_receipt = first.receipt.to_dict()
    second_receipt = second.receipt.to_dict()
    assert first_receipt["request_cid"] == cid_for_dag_json(
        {
            "role": "l1",
            "source_text": first_source,
            "allowed_atom_vocabulary": VOCABULARY.to_dict(),
        }
    )
    assert second_receipt["request_cid"] == cid_for_dag_json(
        {
            "role": "l1",
            "source_text": second_source,
            "allowed_atom_vocabulary": VOCABULARY.to_dict(),
        }
    )
    first_call = first_receipt["calls"][0]
    second_call = second_receipt["calls"][0]
    assert first_call["prompt_cid"] == cid_for_bytes(
        str(client.calls[0]["prompt"]).encode("utf-8")
    )
    assert second_call["prompt_cid"] == cid_for_bytes(
        str(client.calls[1]["prompt"]).encode("utf-8")
    )
    assert validate_cid(
        first_receipt["request_cid"], codecs=("dag-json",)
    )
    assert validate_cid(first_call["prompt_cid"], codecs=("raw",))

    for serialized in (first_receipt, second_receipt):
        call = dict(serialized["calls"][0])
        call_cid = call.pop("receipt_cid")
        assert call_cid == cid_for_dag_json(call)
        assert ModelCallReceipt.from_dict(
            serialized["calls"][0]
        ).receipt_cid == call_cid
        receipt = dict(serialized)
        receipt_cid = receipt.pop("receipt_cid")
        assert receipt_cid == cid_for_dag_json(receipt)
        assert (
            ModelOutputRecoveryReceipt.validate_dict(serialized)
            == receipt_cid
        )

    assert first_receipt["request_cid"] != second_receipt["request_cid"]
    assert first_call["prompt_cid"] != second_call["prompt_cid"]
    assert first_call["receipt_cid"] != second_call["receipt_cid"]
    assert first_receipt["receipt_cid"] != second_receipt["receipt_cid"]


def test_frozen_manifest_and_receipts_reject_readdressed_tampering() -> None:
    manifest_path = REPO_ROOT / SRT021_MANIFEST_RELATIVE_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered_manifest = json.loads(json.dumps(manifest))
    model_arm = (
        "model__not_applicable__always_on__symai__leanstral_symai"
    )
    samples = tampered_manifest["remediation"]["arms"][model_arm][
        "sample_coordinate_keys_by_gate"
    ]["polarity_preservation"]
    samples[0] = (
        "legal_doc_1|9|"
        "model__not_applicable__always_on__symai__leanstral_symai"
    )
    manifest_body = dict(tampered_manifest)
    del manifest_body["manifest_cid"]
    tampered_manifest["manifest_cid"] = cid_for_dag_json(manifest_body)

    with pytest.raises(ContractError, match="CID|frozen"):
        load_srt021_remediation_evidence(manifest=tampered_manifest)
    with pytest.raises(ContractError, match="frozen gate"):
        load_srt021_remediation_evidence(
            manifest=manifest,
            manifest_gate_cid=cid_for_dag_json({"forged": "gate"}),
        )

    result = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()]), route="direct"
    ).recover_l1(constructor_request())
    tampered_receipt = json.loads(json.dumps(result.receipt.to_dict()))
    tampered_receipt["boundary"]["fallback_allowed"] = True
    receipt_body = dict(tampered_receipt)
    del receipt_body["receipt_cid"]
    tampered_receipt["receipt_cid"] = cid_for_dag_json(receipt_body)
    with pytest.raises(ContractError, match="malformed|contradictory|CID"):
        ModelOutputRecoveryReceipt.validate_dict(tampered_receipt)

    tampered_evidence = json.loads(json.dumps(result.receipt.to_dict()))
    tampered_evidence["remediation_evidence"]["coordinates"][0][
        "case_id"
    ] = "forged_case"
    evidence_body = dict(tampered_evidence["remediation_evidence"])
    del evidence_body["evidence_cid"]
    tampered_evidence["remediation_evidence"][
        "evidence_cid"
    ] = cid_for_dag_json(evidence_body)
    receipt_body = dict(tampered_evidence)
    del receipt_body["receipt_cid"]
    tampered_evidence["receipt_cid"] = cid_for_dag_json(receipt_body)
    with pytest.raises(ContractError, match="frozen remediation lineage"):
        ModelOutputRecoveryReceipt.validate_dict(tampered_evidence)


def test_model_output_recovery_has_no_legacy_sha_fields() -> None:
    source = (
        REPO_ROOT
        / "benchmarks/semantic_roundtrip/model_output_recovery.py"
    ).read_text(encoding="utf-8")
    result = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()]), route="direct"
    ).recover_l1(constructor_request())
    serialized = json.dumps(result.receipt.to_dict(), sort_keys=True)

    assert "sha256" not in source.lower()
    assert "hashlib" not in source.lower()
    assert "sha256" not in serialized.lower()
    assert "hashlib" not in serialized.lower()


def test_readdressed_accepted_then_accepted_transition_is_rejected() -> None:
    result = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}, IR.to_dict()]),
        route="direct",
    ).recover_l1(constructor_request())
    receipt = json.loads(json.dumps(result.receipt.to_dict()))
    first_call = receipt["calls"][0]
    first_call.update(
        {
            "outcome": "accepted",
            "rejection": None,
            "rejection_reason": None,
            "failure_reason": None,
            "detail": None,
        }
    )
    receipt["calls"][0] = readdress_receipt(first_call)
    receipt = readdress_receipt(receipt)

    with pytest.raises(ContractError, match="transition"):
        ModelOutputRecoveryReceipt.validate_dict(receipt)


@pytest.mark.parametrize(
    ("rejection", "failure_reason"),
    [
        ("call_timeout", "timeout"),
        (
            "route_contract_failure",
            "post_schedule_capability_unavailable",
        ),
        ("call_exception", "exception"),
    ],
)
def test_readdressed_nonretryable_then_accepted_transition_is_rejected(
    rejection: str, failure_reason: str
) -> None:
    from benchmarks.semantic_roundtrip.model_output_recovery import (
        classify_model_rejection,
    )

    result = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}, IR.to_dict()]),
        route="direct",
    ).recover_l1(constructor_request())
    receipt = json.loads(json.dumps(result.receipt.to_dict()))
    first_call = receipt["calls"][0]
    mapped = classify_model_rejection(rejection)
    assert mapped is not None
    first_call.update(
        {
            "outcome": "call_failed",
            "rejection": rejection,
            "rejection_reason": mapped.value,
            "failure_reason": failure_reason,
            "detail": "forged nonretryable call",
        }
    )
    receipt["calls"][0] = readdress_receipt(first_call)
    receipt = readdress_receipt(receipt)

    with pytest.raises(ContractError, match="policy-permitted"):
        ModelOutputRecoveryReceipt.validate_dict(receipt)


def test_readdressed_one_call_terminal_failure_must_match_call() -> None:
    result = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}]),
        route="direct",
        policy=RecoveryPolicy("srt-023-no-retry-negative-control", 0),
    ).recover_l1(constructor_request())
    receipt = json.loads(json.dumps(result.receipt.to_dict()))
    assert receipt["terminal_failure"] == "empty_l1"
    receipt["terminal_failure"] = "invalid_output"
    receipt = readdress_receipt(receipt)

    with pytest.raises(ContractError, match="one-call failure"):
        ModelOutputRecoveryReceipt.validate_dict(receipt)


def test_readdressed_two_call_terminal_failure_must_be_retry_exhausted() -> None:
    result = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}, {"rules": []}]),
        route="direct",
    ).recover_l1(constructor_request())
    receipt = json.loads(json.dumps(result.receipt.to_dict()))
    assert receipt["terminal_failure"] == "retry_exhausted"
    receipt["terminal_failure"] = "empty_l1"
    receipt = readdress_receipt(receipt)

    with pytest.raises(ContractError, match="exhausted retry"):
        ModelOutputRecoveryReceipt.validate_dict(receipt)


def test_readdressed_direct_call_cannot_claim_a_symai_receipt() -> None:
    direct = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()]), route="direct"
    ).recover_l1(constructor_request())
    symai = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()], symai=True), route="symai"
    ).recover_l1(constructor_request())
    direct_receipt = json.loads(json.dumps(direct.receipt.to_dict()))
    direct_call = direct_receipt["calls"][0]
    direct_call["symai_route_receipt"] = symai.receipt.to_dict()["calls"][0][
        "symai_route_receipt"
    ]
    direct_call = readdress_receipt(direct_call)

    with pytest.raises(ContractError, match="direct model call"):
        ModelCallReceipt.from_dict(direct_call)
    direct_receipt["calls"][0] = direct_call
    direct_receipt = readdress_receipt(direct_receipt)
    with pytest.raises(ContractError, match="direct model call"):
        ModelOutputRecoveryReceipt.validate_dict(direct_receipt)


@pytest.mark.parametrize("call_index", [0, 1])
def test_readdressed_symai_rejected_or_accepted_call_needs_route_receipt(
    call_index: int,
) -> None:
    result = BoundedModelOutputRecovery(
        RecordingClient(
            [{"rules": []}, IR.to_dict()],
            symai=True,
        ),
        route="symai",
    ).recover_l1(constructor_request())
    receipt = json.loads(json.dumps(result.receipt.to_dict()))
    call = receipt["calls"][call_index]
    assert call["outcome"] in {"rejected", "accepted"}
    call["symai_route_receipt"] = None
    call = readdress_receipt(call)

    with pytest.raises(ContractError, match="needs a route receipt"):
        ModelCallReceipt.from_dict(call)
    receipt["calls"][call_index] = call
    receipt = readdress_receipt(receipt)
    with pytest.raises(ContractError, match="needs a route receipt"):
        ModelOutputRecoveryReceipt.validate_dict(receipt)


@pytest.mark.parametrize(
    ("section", "field", "forged"),
    [
        ("routing", "resolved_provider", "forged-provider"),
        ("routing", "resolved_endpoint", "http://127.0.0.1:9999/v1"),
        ("routing", "resolved_model", "forged-model"),
        ("routing", "resolved_backend", "forged-backend"),
        ("model_settings", "temperature", 1),
        ("model_settings", "temperature", False),
        ("model_settings", "seed", 2),
        ("retry", "attempts", 2),
        ("retry", "attempts", True),
        ("cache", "enabled", True),
        ("cache", "enabled", 0),
    ],
)
def test_readdressed_symai_route_identity_or_settings_drift_is_rejected(
    section: str, field: str, forged: object
) -> None:
    result = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()], symai=True), route="symai"
    ).recover_l1(constructor_request())
    receipt = json.loads(json.dumps(result.receipt.to_dict()))
    call = receipt["calls"][0]
    call["symai_route_receipt"][section][field] = forged
    call = readdress_receipt(call)

    with pytest.raises(ContractError, match="pinned route identity"):
        ModelCallReceipt.from_dict(call)
    receipt["calls"][0] = call
    receipt = readdress_receipt(receipt)
    with pytest.raises(ContractError, match="pinned route identity"):
        ModelOutputRecoveryReceipt.validate_dict(receipt)


def test_symai_call_failure_allows_only_an_absent_route_receipt() -> None:
    drift_client = RecordingClient(
        [IR.to_dict()],
        symai=True,
        metadata={**ROUTE_METADATA, "resolved_model_name": "other-model"},
    )
    failed = BoundedModelOutputRecovery(
        drift_client, route="symai"
    ).recover_l1(constructor_request())
    failed_receipt = json.loads(json.dumps(failed.receipt.to_dict()))
    failed_call = failed_receipt["calls"][0]
    assert failed_call["outcome"] == "call_failed"
    assert failed_call["symai_route_receipt"] is None
    assert ModelCallReceipt.from_dict(failed_call).receipt_cid == (
        failed_call["receipt_cid"]
    )
    assert ModelOutputRecoveryReceipt.validate_dict(failed_receipt) == (
        failed_receipt["receipt_cid"]
    )

    valid_symai = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()], symai=True), route="symai"
    ).recover_l1(constructor_request())
    forged_call = json.loads(json.dumps(failed_call))
    forged_call["symai_route_receipt"] = valid_symai.receipt.to_dict()[
        "calls"
    ][0]["symai_route_receipt"]
    forged_call = readdress_receipt(forged_call)
    with pytest.raises(ContractError, match="failed SyMAI call"):
        ModelCallReceipt.from_dict(forged_call)
    forged_receipt = json.loads(json.dumps(failed_receipt))
    forged_receipt["calls"][0] = forged_call
    forged_receipt = readdress_receipt(forged_receipt)
    with pytest.raises(ContractError, match="failed SyMAI call"):
        ModelOutputRecoveryReceipt.validate_dict(forged_receipt)


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("schema_name", "srt023_replacement_l2_canonical_ir_v1"),
        ("max_tokens", 256),
    ],
)
def test_readdressed_call_role_schema_or_token_drift_is_rejected(
    field: str, forged: object
) -> None:
    result = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()], symai=True), route="symai"
    ).recover_l1(constructor_request())
    receipt = json.loads(json.dumps(result.receipt.to_dict()))
    call = receipt["calls"][0]
    call[field] = forged
    if field == "schema_name":
        call["symai_route_receipt"]["role"] = forged
    else:
        call["symai_route_receipt"]["model_settings"]["max_tokens"] = forged
    call = readdress_receipt(call)

    with pytest.raises(ContractError, match="schema or token"):
        ModelCallReceipt.from_dict(call)
    receipt["calls"][0] = call
    receipt = readdress_receipt(receipt)
    with pytest.raises(ContractError, match="schema or token"):
        ModelOutputRecoveryReceipt.validate_dict(receipt)


@pytest.mark.parametrize(
    ("detailed", "taxonomy"),
    [
        ("blank_output", ModelRejectionReason.BLANK),
        ("empty_output", ModelRejectionReason.EMPTY_RULES),
        ("malformed_output", ModelRejectionReason.SCHEMA),
        ("polarity_ambiguous", ModelRejectionReason.POLARITY),
        ("call_timeout", ModelRejectionReason.TIMEOUT),
        ("route_contract_failure", ModelRejectionReason.OTHER),
        ("call_exception", ModelRejectionReason.OTHER),
        ("blank", ModelRejectionReason.BLANK),
        ("schema", ModelRejectionReason.SCHEMA),
        ("polarity", ModelRejectionReason.POLARITY),
        ("empty_rules", ModelRejectionReason.EMPTY_RULES),
        ("timeout", ModelRejectionReason.TIMEOUT),
        ("other", ModelRejectionReason.OTHER),
        ("unmapped_provider_glitch", ModelRejectionReason.OTHER),
    ],
)
def test_rejection_taxonomy_maps_every_detailed_label(
    detailed: str, taxonomy: ModelRejectionReason
) -> None:
    assert classify_model_rejection(detailed) is taxonomy
    assert taxonomy.value in TYPED_REJECTION_REASONS
    assert TYPED_REJECTION_REASONS == {
        "blank",
        "schema",
        "polarity",
        "empty_rules",
        "timeout",
        "other",
    }


def test_every_failed_model_call_records_typed_rejection_reason() -> None:
    cases = [
        ({"rules": []}, "empty_rules", FailureReason.EMPTY_L1),
        (
            {"rules": [{"modality": "O"}]},
            "schema",
            FailureReason.INVALID_OUTPUT,
        ),
    ]
    for payload, reason, failure in cases:
        result = BoundedModelOutputRecovery(
            RecordingClient([payload]),
            route="direct",
            policy=RecoveryPolicy("srt-023-no-retry-taxonomy", 0),
        ).recover_l1(constructor_request())
        call = result.receipt.calls[0]
        assert call.outcome == "rejected"
        assert call.rejection_reason == reason
        assert call.failure_reason is failure
        assert result.receipt.terminal_rejection_reason == reason
        assert result.receipt.to_dict()["terminal_rejection_reason"] == reason

    polarity = IR.to_dict()
    polarity["rules"][0]["modality"] = "P"
    polarity_result = BoundedModelOutputRecovery(
        RecordingClient([polarity]),
        route="direct",
        policy=RecoveryPolicy("srt-023-no-retry-polarity", 0),
    ).recover_l2(constructor_request("text"), expected_ir=IR)
    assert polarity_result.receipt.calls[0].rejection_reason == "polarity"

    timeout = BoundedModelOutputRecovery(
        RecordingClient([TimeoutError("late")]),
        route="direct",
        policy=RecoveryPolicy("srt-023-no-retry-timeout", 0),
    ).recover_l1(constructor_request())
    assert timeout.receipt.calls[0].rejection_reason == "timeout"
    assert timeout.receipt.calls[0].rejection == "call_timeout"

    blank = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}]),
        route="direct",
        policy=RecoveryPolicy("srt-023-no-retry-blank", 0),
    ).recover_t1(realizer_request())
    assert blank.receipt.calls[0].rejection_reason == "blank"


def test_promotion_default_is_unchanged_and_research_policy_is_separated() -> None:
    assert PROMOTION_RECOVERY_POLICY is PREREGISTERED_SRT023_POLICY
    assert PROMOTION_RECOVERY_POLICY.max_retries == 1
    assert PROMOTION_RECOVERY_POLICY.kind is RecoveryPolicyKind.PROMOTION
    assert PROMOTION_RECOVERY_POLICY.is_promotion_default is True
    assert PROMOTION_RECOVERY_POLICY.is_research is False

    research = PREREGISTERED_RESEARCH_RECOVERY_POLICY
    assert research.kind is RecoveryPolicyKind.RESEARCH
    assert research.max_retries > 1
    assert research.is_research is True
    assert research.is_promotion_default is False
    assert research.policy_cid != PROMOTION_RECOVERY_POLICY.policy_cid

    with pytest.raises(ContractError, match="at most one"):
        RecoveryPolicy("srt-023-replacement-too-many", 2)
    with pytest.raises(ContractError, match="greater than one"):
        RecoveryPolicy(
            "research-recovery-too-small",
            1,
            kind=RecoveryPolicyKind.RESEARCH,
        )
    with pytest.raises(ContractError, match="research-recovery"):
        RecoveryPolicy(
            "srt-023-replacement-as-research",
            3,
            kind=RecoveryPolicyKind.RESEARCH,
        )
    with pytest.raises(ContractError, match="replacement experiment"):
        RecoveryPolicy("production-run", 1)


def test_research_policy_allows_preregistered_budget_greater_than_one() -> None:
    empty = {"rules": []}
    client = RecordingClient([empty, empty, empty, IR.to_dict()])
    recovery = BoundedModelOutputRecovery(
        client,
        route="direct",
        policy=PREREGISTERED_RESEARCH_RECOVERY_POLICY,
    )

    result = recovery.recover_l1(constructor_request())

    assert result.status is ComponentStatus.SUCCESS
    assert len(client.calls) == 4  # initial + 3 research retries
    assert result.receipt.retries == 3
    assert result.receipt.policy.kind is RecoveryPolicyKind.RESEARCH
    assert all(
        call.rejection_reason == "empty_rules"
        for call in result.receipt.calls[:-1]
    )


def test_accept_rate_and_retry_exhausted_rate_are_separate_from_e2e_loss() -> None:
    accepted = BoundedModelOutputRecovery(
        RecordingClient([IR.to_dict()]), route="direct"
    ).recover_l1(constructor_request())
    exhausted = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}, {"rules": []}]), route="direct"
    ).recover_l1(constructor_request())
    one_shot = BoundedModelOutputRecovery(
        RecordingClient([{"rules": []}]),
        route="direct",
        policy=RecoveryPolicy("srt-023-no-retry-metrics", 0),
    ).recover_l1(constructor_request())

    metrics = arm_reliability_metrics(
        "model__not_applicable__always_on__symai__leanstral_symai",
        [accepted, exhausted, one_shot],
    )

    assert isinstance(metrics, ArmReliabilityMetrics)
    assert metrics.recovery_invocations == 3
    assert metrics.accepted_recoveries == 1
    assert metrics.retry_exhausted_recoveries == 1
    assert metrics.accept_rate == pytest.approx(1 / 3)
    assert metrics.retry_exhausted_rate == pytest.approx(1 / 3)
    payload = metrics.to_dict()
    assert payload["accept_rate"] == pytest.approx(1 / 3)
    assert payload["retry_exhausted_rate"] == pytest.approx(1 / 3)
    assert payload["separate_from_end_to_end_loss"] is True
    assert payload["end_to_end_loss"] is None
    assert "empty_rules" in payload["rejection_reason_counts"]
    # Reliability rates must not be confused with a unit end-to-end loss.
    assert payload["accept_rate"] != 1.0 or payload["retry_exhausted_rate"] != 0.0


def test_single_rule_research_schema_path_is_usable_for_hybrid_repair() -> None:
    single = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="controller",
                action="delete",
                object="records",
                temporal=("after_30_days",),
            ),
        )
    )
    schema = SyMAIPolarityContract.single_rule_research_canonical_schema(
        VOCABULARY
    )
    assert schema["properties"]["rules"]["minItems"] == 1
    assert schema["properties"]["rules"]["maxItems"] == 1
    t1_schema = SyMAIPolarityContract.single_rule_research_realization_schema(
        single
    )
    assert t1_schema["properties"]["rules"]["minItems"] == 1
    assert t1_schema["properties"]["rules"]["maxItems"] == 1
    with pytest.raises(ContractError, match="exactly one rule"):
        SyMAIPolarityContract.single_rule_research_realization_schema(IR)

    client = RecordingClient([single.to_dict()])
    recovery = BoundedModelOutputRecovery(
        client,
        route="direct",
        schema_path=RecoverySchemaPath.SINGLE_RULE_RESEARCH,
    )
    result = recovery.recover_l1(constructor_request())
    assert result.status is ComponentStatus.SUCCESS
    assert result.canonical_ir == single
    assert client.calls[0]["schema_name"] == (
        "research_single_rule_l1_canonical_ir_v1"
    )
    assert client.calls[0]["schema"]["properties"]["rules"]["maxItems"] == 1
    assert recovery.schema_path is RecoverySchemaPath.SINGLE_RULE_RESEARCH

    with pytest.raises(ContractError, match="exactly one input rule"):
        BoundedModelOutputRecovery(
            RecordingClient([realization()]),
            route="direct",
            schema_path=RecoverySchemaPath.SINGLE_RULE_RESEARCH,
        ).recover_t1(realizer_request())
