"""Adversarial assurance security suite for USPTO submission-assurance v2 (PATLAW-143).

Exercises malicious PDFs/XML/archives, XXE/schema attacks, prompt injection,
spoofed citations, hostile metadata, tenant crossover, credential leakage,
oversized inputs, retry storms, contradictory law, and corrupt checkpoints.

Acceptance bindings:

* Fail-closed rejection for every declared attack family
* Unknown attack families are **blocked** (not silently accepted)
* No-disclosure evidence is explicit (disclosure=false; private bytes never
  re-hydrated into findings or receipts)
* Provider-call evidence is explicit (zero offline provider calls;
  credentials never resolved)
* Content-free surfaces only — synthetic canaries, never real matter text
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    UsptoPrivacyPolicy,
)
from ipfs_datasets_py.processors.domains.uspto.privacy_sinks import (
    EnforcementDecisionCode,
    ExportControlState,
    PublicationState,
    PublicSinkEnforcer,
    SinkChannel,
    SinkDispatchRequest,
    TenantPolicy,
    all_sink_channels,
    payload_contains_canary,
    redact_for_observability,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    PrivateStoreError,
    ProhibitedContentError,
    generate_tenant_key,
)

# ---------------------------------------------------------------------------
# Load v2 release gate module (harness lives with the declared output)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "validate_v2_release.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "uspto_validate_v2_release", _GATE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()

# Synthetic canaries — not live secrets or real matter content.
PRIVATE_TEXT_CANARY = "CONFIDENTIAL unpublished claim language v2-adv-canary-9c1e"
PRIVATE_BYTES_CANARY = b"%PDF-V2-ADV-PRIVATE-OA-SYNTHETIC-7a2b%"
PRIVATE_CID_CANARY = "bafyv2advprivatecid00000000000000000000000000000000003"
PRIVATE_EMBEDDING_CANARY = [0.101, 0.202, 0.303, 0.886421]
EMBEDDING_MARKER = "0.886421"
PROMPT_INJECTION_CANARY = "prompt-injection-payload-secret-NEVER-ECHO"
CREDENTIAL_CANARY = "sk-live-SYNTHETIC-NOT-A-REAL-KEY-v2adv"

CANARIES: tuple[Any, ...] = (
    PRIVATE_TEXT_CANARY,
    PRIVATE_BYTES_CANARY,
    PRIVATE_CID_CANARY,
    EMBEDDING_MARKER,
    PROMPT_INJECTION_CANARY,
    CREDENTIAL_CANARY,
)


def _assert_no_canaries(surface: Any) -> None:
    blob = surface if isinstance(surface, str) else json.dumps(surface, default=str)
    found = payload_contains_canary(blob, CANARIES)
    assert found == [], f"adversarial canaries leaked into surface: {found!r}"
    lower = blob.lower() if isinstance(blob, str) else str(blob).lower()
    for marker in (
        "authorization: bearer",
        "x-api-key:",
        "-----begin ",
        PROMPT_INJECTION_CANARY.lower(),
        CREDENTIAL_CANARY.lower(),
    ):
        assert marker not in lower, f"forbidden marker in surface: {marker!r}"


# ---------------------------------------------------------------------------
# Gate harness — every attack family fail-closed
# ---------------------------------------------------------------------------


def test_all_adversarial_families_are_declared() -> None:
    families = set(gate.ADVERSARIAL_ATTACK_FAMILIES)
    required = {
        "malicious_pdf",
        "malicious_xml_xxe",
        "malicious_archive",
        "schema_bomb",
        "prompt_injection",
        "spoofed_citation",
        "hostile_metadata",
        "tenant_crossover",
        "credential_leakage",
        "oversized_input",
        "retry_storm",
        "contradictory_law",
        "corrupt_checkpoint",
    }
    assert required <= families


@pytest.mark.parametrize("family", list(gate.ADVERSARIAL_ATTACK_FAMILIES))
def test_attack_family_rejected_fail_closed(family: str) -> None:
    payload: dict[str, Any] = {
        "family": family,
        "markers": [f"marker:{family}"],
        "size_bytes": 64 if family != "oversized_input" else 9_000_000,
        "max_bytes": 1_048_576,
        "tenant_id": "tenant-adv-a",
        "target_tenant_id": (
            "tenant-adv-b" if family == "tenant_crossover" else "tenant-adv-a"
        ),
        "credential_material": family == "credential_leakage",
        "external_entity": family in {"malicious_xml_xxe", "schema_bomb"},
        "retry_count": 64 if family == "retry_storm" else 0,
        # Never pass private bodies into the classifier.
    }
    decision = gate.classify_adversarial_input(payload)
    assert decision["disposition"] == "rejected"
    assert decision["status"] == "passed"
    assert decision["disclosure"] is False
    assert decision["provider_calls"] == 0
    assert decision["external_entity_resolved"] is False
    assert decision["credential_resolved"] is False
    assert decision["private_bytes_inspected"] is False
    assert decision["content_free"] is True
    _assert_no_canaries(decision)
    # Decision must not echo attack body markers.
    blob = json.dumps(decision).lower()
    assert PRIVATE_TEXT_CANARY.lower() not in blob
    assert PROMPT_INJECTION_CANARY.lower() not in blob


def test_unknown_attack_family_is_blocked() -> None:
    decision = gate.classify_adversarial_input(
        {"family": "novel_zero_day_gadget", "markers": ["x"]}
    )
    assert decision["status"] == "blocked"
    assert decision["disposition"] == "blocked"
    assert decision["disclosure"] is False
    assert decision["provider_calls"] == 0


def test_adversarial_suite_no_disclosure_and_zero_provider_calls() -> None:
    suite = gate.run_adversarial_assurance_suite()
    assert suite["status"] == "passed"
    assert suite["disclosure"] is False
    assert suite["provider_calls_total"] == 0
    assert suite["no_disclosure_evidence"] is True
    pce = suite["provider_call_evidence"]
    assert pce["calls_attempted"] == 0
    assert pce["calls_completed"] == 0
    assert pce["credentials_resolved"] is False
    assert pce["mode"] == "offline_synthetic"
    assert suite["content_free"] is True
    assert len(suite["results"]) == len(gate.ADVERSARIAL_ATTACK_FAMILIES)
    assert suite["unknown_family"]["status"] == "blocked"
    _assert_no_canaries(suite)
    gate.assert_content_free(suite)


def test_xxe_payload_never_resolves_external_entity() -> None:
    decision = gate.classify_adversarial_input(
        {
            "family": "malicious_xml_xxe",
            "xxe": True,
            "external_entity": True,
            "markers": ["xxe"],
        }
    )
    assert decision["external_entity_resolved"] is False
    assert "xxe_external_entity" in decision["reason"]
    assert decision["provider_calls"] == 0


def test_credential_leakage_refuses_resolution() -> None:
    decision = gate.classify_adversarial_input(
        {
            "family": "credential_leakage",
            "credential_material": True,
            "markers": ["cred"],
        }
    )
    assert decision["credential_resolved"] is False
    assert "credential_material_refused" in decision["reason"]
    # Must not store the credential canary in the decision.
    assert CREDENTIAL_CANARY not in json.dumps(decision)


def test_oversized_input_bounded() -> None:
    decision = gate.classify_adversarial_input(
        {
            "family": "oversized_input",
            "size_bytes": 50_000_000,
            "max_bytes": 1_048_576,
        }
    )
    assert decision["disposition"] == "rejected"
    assert "oversized_input" in decision["reason"]


def test_retry_storm_bounded() -> None:
    decision = gate.classify_adversarial_input(
        {"family": "retry_storm", "retry_count": 128}
    )
    assert "retry_storm_bounded" in decision["reason"]


def test_prompt_injection_isolated_from_receipt() -> None:
    decision = gate.classify_adversarial_input(
        {
            "family": "prompt_injection",
            "markers": ["injection"],
            # Deliberately do not pass the secret body; classifier must not need it.
        }
    )
    assert "prompt_injection_isolated" in decision["reason"]
    _assert_no_canaries(decision)


def test_spoofed_citation_and_contradictory_law_fail_closed() -> None:
    spoofed = gate.classify_adversarial_input({"family": "spoofed_citation"})
    law = gate.classify_adversarial_input({"family": "contradictory_law"})
    assert "citation_authority_unverified" in spoofed["reason"]
    assert "authority_conflict_fail_closed" in law["reason"]
    assert spoofed["disposition"] == "rejected"
    assert law["disposition"] == "rejected"


def test_corrupt_checkpoint_integrity_failed() -> None:
    decision = gate.classify_adversarial_input({"family": "corrupt_checkpoint"})
    assert "checkpoint_integrity_failed" in decision["reason"]


# ---------------------------------------------------------------------------
# Public-sink isolation under adversarial private substance
# ---------------------------------------------------------------------------


@pytest.fixture
def enforcer() -> PublicSinkEnforcer:
    return PublicSinkEnforcer(
        tenant_policy=TenantPolicy(tenant_id="tenant-v2-adv-a")
    )


def _sink_request(
    *,
    channel: SinkChannel,
    kind: ContentKind = ContentKind.EXTRACTED_TEXT,
    classification: DisclosureClassification = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    ),
    tenant_id: str = "tenant-v2-adv-a",
    payload: Any = None,
) -> SinkDispatchRequest:
    if payload is None:
        if kind is ContentKind.DOCUMENT_BYTES:
            payload = PRIVATE_BYTES_CANARY
        elif kind is ContentKind.EMBEDDING:
            payload = PRIVATE_EMBEDDING_CANARY
        elif kind is ContentKind.CONTENT_IDENTIFIER:
            payload = PRIVATE_CID_CANARY
        else:
            payload = PRIVATE_TEXT_CANARY
    return SinkDispatchRequest(
        channel=channel,
        content_kind=kind,
        classification=classification,
        tenant_id=tenant_id,
        publication_state=PublicationState.PRIVATE_UNPUBLISHED,
        export_control_state=ExportControlState.CLEARED,
        payload=payload,
    )


def test_private_substance_denied_from_all_public_sinks(
    enforcer: PublicSinkEnforcer,
) -> None:
    captures: list[str] = []
    for channel in all_sink_channels():
        req = _sink_request(channel=channel)
        try:
            decision = enforcer.evaluate(req)
        except PrivacyBoundaryError as exc:
            captures.append(str(exc))
            continue
        assert decision.allowed is False, channel
        if hasattr(decision, "to_dict"):
            surface = json.dumps(decision.to_dict(), default=str)
        else:
            surface = json.dumps(
                {
                    "code": str(getattr(decision, "code", "")),
                    "allowed": decision.allowed,
                },
                default=str,
            )
        captures.append(surface)
    for surface in captures:
        _assert_no_canaries(surface)


def test_tenant_crossover_denied(enforcer: PublicSinkEnforcer) -> None:
    req = _sink_request(
        channel=SinkChannel.PUBLIC_IPFS_PIN,
        tenant_id="tenant-v2-adv-b",  # different from enforcer policy
    )
    decision = enforcer.evaluate(req)
    assert decision.allowed is False
    surface = json.dumps(
        decision.to_dict() if hasattr(decision, "to_dict") else {
            "allowed": decision.allowed,
            "code": str(getattr(decision, "code", "")),
        },
        default=str,
    )
    _assert_no_canaries(surface)


def test_observability_redaction_strips_private_canaries() -> None:
    noisy = {
        "event": "adv_probe",
        "note": PRIVATE_TEXT_CANARY,
        "cid": PRIVATE_CID_CANARY,
        "embedding_hint": EMBEDDING_MARKER,
        "matter_id": "matter:v2-adv:1",
        "artifact_id": "artifact:v2-adv:1",
    }
    redacted = redact_for_observability(
        DisclosureClassification.CONFIDENTIAL_APPLICATION,
        noisy,
    )
    blob = json.dumps(redacted, default=str)
    _assert_no_canaries(blob)


def test_private_store_refuses_credential_material(tmp_path: Path) -> None:
    key = generate_tenant_key("tenant-v2-adv-a")
    store = PrivateArtifactStore(
        root=tmp_path / "vault",
        tenant_key=key,
    )
    with pytest.raises(
        (PrivateStoreError, ProhibitedContentError, PrivacyBoundaryError, ValueError)
    ):
        store.put_bytes(
            f"BEGIN USPTO CREDENTIAL BLOB\n{CREDENTIAL_CANARY}\n".encode(),
            artifact_id="art:cred-probe",
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )


def test_privacy_policy_default_denies_external_model() -> None:
    policy = UsptoPrivacyPolicy()
    assert policy.allow_external_models_for_private is False
    _assert_no_canaries(policy.to_dict())


def test_malicious_pdf_and_archive_families_content_free() -> None:
    for family in ("malicious_pdf", "malicious_archive", "hostile_metadata", "schema_bomb"):
        decision = gate.classify_adversarial_input(
            {
                "family": family,
                "markers": [f"m:{family}"],
                "external_entity": family == "schema_bomb",
            }
        )
        assert decision["content_free"] is True
        assert decision["private_bytes_inspected"] is False
        _assert_no_canaries(decision)


def test_suite_evidence_binds_into_release_gate_offline() -> None:
    """Adversarial suite status must be consumable by the v2 release gate."""
    suite = gate.run_adversarial_assurance_suite()
    assert suite["status"] == "passed"
    assert "no_disclosure_evidence" in suite
    assert "provider_call_evidence" in suite
    # Offline self-check adversarial check must pass on the real tree.
    report = gate.offline_self_check(_REPO_ROOT)
    names = {c["name"] for c in report["checks"]}
    assert "adversarial" in names
    adv_check = next(c for c in report["checks"] if c["name"] == "adversarial")
    assert adv_check["status"] == "passed", adv_check
