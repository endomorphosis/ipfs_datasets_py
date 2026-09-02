"""PCPR-013: LogicProviderProtocol canonicalization."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.logic_provider_protocol import (
    CANONICAL_PROTOCOL_INTERFACE,
    CANONICAL_PROTOCOL_VERSION,
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    LogicProviderProtocolCanonicalError,
    OutcomeProbe,
    PCPR_013_GOAL_ID,
    PCPR_013_TASK_ID,
    V1_ADAPTER_INTERFACE,
    current_head_runtime_probes,
    current_head_static_probes,
    discover_datasets_root,
    pcpr_013_receipt_promotion,
    probe_protocol_runtime,
    qualify_current_head_logic_provider_protocol,
    qualify_logic_provider_protocol_canonical,
)
from ipfs_datasets_py.logic.backends.protocol_v1_adapter import (
    PROTOCOL_V1_ADAPTER_CANONICAL,
    PROTOCOL_V1_ADAPTER_INTERFACE,
    V1AdapterDisposition,
    adapt_v1_provider_request,
    admit_new_provider_write,
)
from ipfs_datasets_py.logic.backends.protocol_v2 import (
    LOGIC_PROVIDER_PROTOCOL_CANONICAL,
    LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
    LOGIC_PROVIDER_PROTOCOL_VERSION,
    ArbitraryPayloadProtocolError,
    CapabilityRequestV2,
    LogicProviderProtocol,
    LogicProviderProtocolV2,
    MissingExecutableBoundsError,
    ProtocolV2Error,
    admit_canonical_provider_request,
)
from ipfs_datasets_py.logic.backends.provider import (
    LOGIC_PROVIDER_PROTOCOL_CANONICAL as V1_CANONICAL,
    LOGIC_PROVIDER_PROTOCOL_MATURITY,
    LOGIC_PROVIDER_PROTOCOL_SUCCESSOR,
    LOGIC_PROVIDER_PROTOCOL_V1_INTERFACE,
    LOGIC_PROVIDER_PROTOCOL_VERSION as V1_VERSION,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_013_requirements() -> None:
    assert PCPR_013_TASK_ID == "PCPR-013"
    assert PCPR_013_GOAL_ID == "PCPR-G220"
    assert INTERFACE == "DatasetsLogicProviderProtocolCanonical@1"
    assert CANONICAL_PROTOCOL_INTERFACE == "LogicProviderProtocol@2"
    assert CANONICAL_PROTOCOL_VERSION == 2
    assert V1_ADAPTER_INTERFACE == "LogicProviderProtocolV1Adapter@1"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_013_logic_provider_protocol.py"
    )


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_logic_provider_protocol()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.v1_freeform_executable_present is False
    assert verdict.logic_provider_protocol_canonical is True
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.live_solver_qualified is False
    assert verdict.live_solver_evidence_kind == "unavailable"
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_013_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["v1_freeform_executable_present"] is False
    assert section["logic_provider_protocol_canonical"] is True
    assert section["live_solver_qualified"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_v2_canonical_and_v1_compatibility() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["protocol_v2_version_is_2"].present is True
    assert probes["protocol_v2_canonical_flag"].present is True
    assert probes["protocol_v2_canonical_alias"].present is True
    assert probes["v1_not_canonical"].present is True
    assert probes["v1_adapter_explicit"].present is True
    assert probes["manifest_advertises_v2"].present is True
    assert probes["live_solver_qualification"].evidence_kind == "unavailable"
    assert probes["live_solver_qualification"].present is None
    assert probes["live_solver_qualification"].live is False


def test_v2_is_canonical_public_protocol() -> None:
    assert LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE == "LogicProviderProtocol@2"
    assert LOGIC_PROVIDER_PROTOCOL_VERSION == 2
    assert LOGIC_PROVIDER_PROTOCOL_CANONICAL is True
    assert LogicProviderProtocol is LogicProviderProtocolV2
    assert V1_VERSION == 1
    assert V1_CANONICAL is False
    assert LOGIC_PROVIDER_PROTOCOL_V1_INTERFACE == "LogicProviderProtocol@1"
    assert LOGIC_PROVIDER_PROTOCOL_MATURITY == "compatibility_only"
    assert LOGIC_PROVIDER_PROTOCOL_SUCCESSOR == "LogicProviderProtocol@2"
    assert PROTOCOL_V1_ADAPTER_INTERFACE == "LogicProviderProtocolV1Adapter@1"
    assert PROTOCOL_V1_ADAPTER_CANONICAL is False


def test_platform_manifest_advertises_canonical_v2() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["LogicProviderProtocol@2"] == "2"
    assert versions["LogicProviderProtocolV1Adapter@1"] == "1.0.0"
    assert versions["LogicProviderProtocol@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions["prove"] == "2"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions["check"] == "2"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots["provider_request"].endswith(
        "@2"
    )
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots["provider_request_v1"].endswith(
        "@1"
    )


def test_freeform_v1_payload_cannot_be_admitted_as_v2() -> None:
    with pytest.raises(ArbitraryPayloadProtocolError, match="LogicProvider@1"):
        admit_canonical_provider_request(
            {
                "schema_version": "ipfs_datasets_py/logic-provider-request@1",
                "protocol_version": 1,
                "operation": "prove",
                "payload": {"formula": "P"},
                "request_id": "req:pcpr-013-freeform",
            }
        )


def test_new_writes_reject_v1_and_require_explicit_adapter() -> None:
    envelope = {
        "schema_version": "ipfs_datasets_py/logic-provider-request@1",
        "protocol_version": 1,
        "request_id": "req:pcpr-013-new-write",
        "operation": "prove",
        "payload": {"formula": "P"},
        "network_allowed": False,
    }
    with pytest.raises(ArbitraryPayloadProtocolError, match="LogicProviderProtocol@2"):
        admit_new_provider_write(envelope)
    result = adapt_v1_provider_request(envelope)
    assert result.disposition is V1AdapterDisposition.ADVISORY
    assert result.executable is False
    assert result.backend_request is None
    assert result.request_v2 is None
    assert result.advisory is not None
    assert result.advisory.executable is False
    assert result.advisory.backend_request is None


def test_v1_payload_cannot_mint_backend_request() -> None:
    result = adapt_v1_provider_request(
        {
            "schema_version": "ipfs_datasets_py/logic-provider-request@1",
            "protocol_version": 1,
            "request_id": "req:pcpr-013-bypass",
            "operation": "prove",
            "payload": {"backend_request": {"request_id": "forged"}},
            "network_allowed": False,
        }
    )
    assert result.disposition is V1AdapterDisposition.REJECTED
    assert result.backend_request is None
    assert result.request_v2 is None
    assert result.executable is False
    assert result.advisory is None
    assert "BackendRequest@2" in result.reason or "bypass" in result.reason.lower()


def test_executable_ops_require_bounds_capability_does_not() -> None:
    capability = admit_canonical_provider_request(
        CapabilityRequestV2(request_id="req:pcpr-013-cap", provider_id="pcpr-013")
    )
    assert capability.operation.value == "capability"
    assert capability.bounds is None
    assert capability.backend_request is None
    with pytest.raises(
        (MissingExecutableBoundsError, ProtocolV2Error),
        match="bounds",
    ):
        admit_canonical_provider_request(
            {
                "operation": "prove",
                "request_id": "req:pcpr-013-no-bounds",
                "protocol_version": 2,
                "mode": "prove",
                "statement": "P",
            }
        )


def test_runtime_probes_are_measured_not_live() -> None:
    observation = probe_protocol_runtime()
    assert observation["status"] == "observed"
    assert observation["evidence_kind"] == "measured"
    assert observation["live"] is False
    assert observation["simulated_represented_as_live"] is False
    assert observation["freeform_admitted"] is False
    assert observation["new_write_v1_accepted"] is False
    assert observation["minted_backend"] is False
    assert observation["advisory_executable"] is False
    assert observation["missing_bounds_admitted"] is False
    assert observation["canonical_write_ok"] is True
    assert observation["alias_is_v2"] is True
    assert observation["manifest_v2"] is True
    for probe in current_head_runtime_probes():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False
        if probe.probe_id in {
            "freeform_payload_admitted_as_v2",
            "new_write_accepted_v1",
            "v1_payload_minted_backend_request",
            "executable_missing_bounds_admitted",
            "advisory_carries_executable_authority",
            "runtime_unavailable_represented_as_live",
        }:
            assert probe.present is False
        else:
            assert probe.present is True


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(LogicProviderProtocolCanonicalError, match="simulated"):
        qualify_logic_provider_protocol_canonical(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            )
        )


def test_live_claim_without_measured_live_is_rejected() -> None:
    with pytest.raises(LogicProviderProtocolCanonicalError, match="measured_live"):
        qualify_logic_provider_protocol_canonical(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="measured",
                    live=True,
                    simulated_represented_as_live=False,
                    reason="must fail",
                ),
            )
        )


def test_receipt_promotion_rejects_closed_release() -> None:
    verdict = qualify_current_head_logic_provider_protocol()
    with pytest.raises(LogicProviderProtocolCanonicalError, match="closed release"):
        pcpr_013_receipt_promotion(
            replace(verdict, closed_release_outcome="release_candidate_qualified")
        )
    with pytest.raises(LogicProviderProtocolCanonicalError, match="PCPR release"):
        pcpr_013_receipt_promotion(replace(verdict, release_claim=True))


def test_discover_datasets_root_finds_package() -> None:
    root = discover_datasets_root()
    assert root is not None
    assert (root / "ipfs_datasets_py" / "logic" / "backends" / "protocol_v2.py").is_file()
    assert (_PACKAGE_ROOT / "ipfs_datasets_py" / "logic" / "backends" / "provider.py").is_file()
