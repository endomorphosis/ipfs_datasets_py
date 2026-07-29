"""Contracts for the provider-neutral symbolic protocol IR."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.protocol import (
    PROTOCOL_IR_INTERFACE,
    AdversaryAccess,
    AdversaryCapability,
    AdversaryKind,
    AdversaryKnowledge,
    ChannelSecurity,
    CorrespondenceKind,
    EquationalTheory,
    EventPhase,
    FreshName,
    FreshNameKind,
    FunctionKind,
    KeyKind,
    ProtocolAdversary,
    ProtocolChannel,
    ProtocolClaim,
    ProtocolClaimKind,
    ProtocolEvent,
    ProtocolFunction,
    ProtocolIR,
    ProtocolKey,
    ProtocolMessage,
    ProtocolRole,
    ProtocolSort,
    ProtocolTerm,
    ProtocolValidationError,
    ProtocolVariable,
    RewriteFact,
    SortKind,
    TrustAssumption,
)

SOURCE_ID = "source:handshake"
SPAN_ID = "span:protocol"


def _source() -> SourceRef:
    return SourceRef(
        ref_id=SOURCE_ID,
        source_uri="file:///protocols/handshake.protocol.json",
        source_id="handshake.protocol.json",
        source_revision="git:0123456789abcdef",
        content_sha256="a" * 64,
    )


def _span() -> SourceSpan:
    return SourceSpan(
        span_id=SPAN_ID,
        source_ref_id=SOURCE_ID,
        start_byte=0,
        end_byte=1024,
        start_line=1,
        start_column=1,
        end_line=40,
        end_column=2,
    )


def _mapped() -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (SOURCE_ID,), "span_ids": (SPAN_ID,)}


def _document(
    *,
    observations: dict[str, object] | None = None,
) -> ProtocolIR:
    sorts = (
        ProtocolSort("sort:agent", "Agent", SortKind.AGENT, **_mapped()),
        ProtocolSort("sort:key", "Key", SortKind.KEY, **_mapped()),
        ProtocolSort("sort:message", "Message", SortKind.MESSAGE, **_mapped()),
        ProtocolSort("sort:nonce", "Nonce", SortKind.NONCE, **_mapped()),
    )
    variables = (
        ProtocolVariable(
            "variable:initiator-peer",
            "peer",
            "sort:agent",
            role_id="role:initiator",
            **_mapped(),
        ),
        ProtocolVariable(
            "variable:responder-peer",
            "peer",
            "sort:agent",
            role_id="role:responder",
            **_mapped(),
        ),
    )
    roles = (
        ProtocolRole(
            "role:initiator",
            "Initiator",
            parameter_ids=("variable:initiator-peer",),
            **_mapped(),
        ),
        ProtocolRole(
            "role:responder",
            "Responder",
            parameter_ids=("variable:responder-peer",),
            **_mapped(),
        ),
    )
    nonce = FreshName(
        "name:challenge",
        "challenge",
        "sort:nonce",
        "role:initiator",
        FreshNameKind.NONCE,
        **_mapped(),
    )
    keys = (
        ProtocolKey(
            "key:initiator-private",
            "initiator_private",
            "sort:key",
            KeyKind.PRIVATE,
            ("role:initiator",),
            peer_key_id="key:initiator-public",
            **_mapped(),
        ),
        ProtocolKey(
            "key:initiator-public",
            "initiator_public",
            "sort:key",
            KeyKind.PUBLIC,
            ("role:initiator",),
            peer_key_id="key:initiator-private",
            **_mapped(),
        ),
        ProtocolKey(
            "key:session",
            "session_key",
            "sort:key",
            KeyKind.SYMMETRIC,
            ("role:initiator", "role:responder"),
            **_mapped(),
        ),
    )
    functions = (
        ProtocolFunction(
            "function:encrypt",
            "encrypt",
            ("sort:nonce", "sort:key"),
            "sort:message",
            FunctionKind.CONSTRUCTOR,
            EquationalTheory.SYMMETRIC_ENCRYPTION,
            **_mapped(),
        ),
        ProtocolFunction(
            "function:decrypt",
            "decrypt",
            ("sort:message", "sort:key"),
            "sort:nonce",
            FunctionKind.DESTRUCTOR,
            EquationalTheory.SYMMETRIC_ENCRYPTION,
            **_mapped(),
        ),
    )
    nonce_term = ProtocolTerm.symbol("name:challenge", "sort:nonce")
    session_key = ProtocolTerm.symbol("key:session", "sort:key")
    ciphertext = ProtocolTerm.application(
        "function:encrypt", (nonce_term, session_key), "sort:message"
    )
    plaintext = ProtocolTerm.application(
        "function:decrypt", (ciphertext, session_key), "sort:nonce"
    )
    assumption = TrustAssumption(
        "assumption:session-key",
        "The long-term mechanism delivers the session key only to both roles.",
        trusted_role_ids=("role:initiator", "role:responder"),
        trusted_key_ids=("key:session",),
        **_mapped(),
    )
    channel = ProtocolChannel(
        "channel:network",
        "network",
        ChannelSecurity.PUBLIC,
        AdversaryAccess.CONTROL,
        **_mapped(),
    )
    message = ProtocolMessage(
        "message:challenge",
        "encrypted challenge",
        ciphertext,
        "role:initiator",
        ("role:responder",),
        "channel:network",
        **_mapped(),
    )
    begin = ProtocolEvent(
        "event:begin",
        "BeginChallenge",
        "role:initiator",
        (nonce_term,),
        EventPhase.BEGIN,
        **_mapped(),
    )
    accept = ProtocolEvent(
        "event:accept",
        "AcceptChallenge",
        "role:responder",
        (nonce_term,),
        EventPhase.ACCEPT,
        **_mapped(),
    )
    claims = (
        ProtocolClaim(
            "claim:secrecy",
            ProtocolClaimKind.SECRECY,
            "The challenge remains secret.",
            secret_terms=(nonce_term,),
            assumption_ids=("assumption:session-key",),
            **_mapped(),
        ),
        ProtocolClaim(
            "claim:reachable",
            ProtocolClaimKind.REACHABILITY,
            "The responder can accept.",
            reachable_event_ids=("event:accept",),
            **_mapped(),
        ),
        ProtocolClaim(
            "claim:authentication",
            ProtocolClaimKind.AUTHENTICATION,
            "Every accept authenticates an initiator run.",
            antecedent_event_ids=("event:accept",),
            consequent_event_ids=("event:begin",),
            correspondence=CorrespondenceKind.INJECTIVE,
            assumption_ids=("assumption:session-key",),
            **_mapped(),
        ),
        ProtocolClaim(
            "claim:correspondence",
            ProtocolClaimKind.CORRESPONDENCE,
            "Accept events correspond to begin events.",
            antecedent_event_ids=("event:accept",),
            consequent_event_ids=("event:begin",),
            **_mapped(),
        ),
        ProtocolClaim(
            "claim:equivalence",
            ProtocolClaimKind.EQUIVALENCE,
            "The two opaque observations are indistinguishable.",
            left_terms=(
                ProtocolTerm(sort="sort:message", literal="left-observation"),
            ),
            right_terms=(
                ProtocolTerm(sort="sort:message", literal="right-observation"),
            ),
            **_mapped(),
        ),
    )
    adversary = ProtocolAdversary(
        "adversary:network",
        AdversaryKind.DOLEV_YAO,
        tuple(AdversaryCapability),
        knowledge=(
            AdversaryKnowledge(
                "knowledge:public-key",
                ProtocolTerm.symbol("key:initiator-public", "sort:key"),
                **_mapped(),
            ),
        ),
        **_mapped(),
    )
    return ProtocolIR(
        sources=(_source(),),
        spans=(_span(),),
        sorts=sorts,
        variables=variables,
        roles=roles,
        fresh_names=(nonce,),
        keys=keys,
        functions=functions,
        trust_assumptions=(assumption,),
        channels=(channel,),
        messages=(message,),
        adversary=adversary,
        rewrite_facts=(
            RewriteFact(
                "fact:decrypt-encrypt",
                plaintext,
                nonce_term,
                EquationalTheory.SYMMETRIC_ENCRYPTION,
                **_mapped(),
            ),
        ),
        events=(begin, accept),
        claims=claims,
        equational_theories=(
            EquationalTheory.FREE,
            EquationalTheory.SYMMETRIC_ENCRYPTION,
        ),
        metadata={"protocol": "challenge-response", "version": 1},
        observations=observations or {},
    )


def test_complete_model_covers_the_protocol_semantic_vocabulary() -> None:
    document = _document()

    assert document.interface == PROTOCOL_IR_INTERFACE
    assert document.roles
    assert document.fresh_names
    assert document.keys
    assert document.messages
    assert document.channels
    assert document.adversary.knowledge
    assert document.rewrite_facts
    assert document.events
    assert {claim.kind for claim in document.claims} == set(ProtocolClaimKind)
    assert document.channels[0].adversary_access is AdversaryAccess.CONTROL
    assert document.trust_assumptions[0].trusted_key_ids == ("key:session",)
    authentication = next(
        claim
        for claim in document.claims
        if claim.kind is ProtocolClaimKind.AUTHENTICATION
    )
    assert authentication.correspondence is CorrespondenceKind.INJECTIVE


def test_model_is_deeply_immutable_and_round_trips_losslessly() -> None:
    document = _document()
    encoded = document.to_json()
    restored = ProtocolIR.from_json(encoded)

    assert restored == document
    assert restored.document_id == document.document_id
    assert restored.to_dict() == document.to_dict()
    assert restored.semantic_bytes() == document.semantic_bytes()
    with pytest.raises(TypeError):
        document.metadata["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        document.roles[0].name = "Changed"  # type: ignore[misc]


def test_identity_is_order_independent_and_excludes_observations() -> None:
    first = _document(
        observations={
            "started_at": "2026-07-29T00:00:00Z",
            "duration_ms": 4,
            "host": "runner-a",
        }
    )
    second = replace(
        _document(
            observations={
                "started_at": "2030-01-01T00:00:00Z",
                "duration_ms": 900,
                "host": "runner-b",
            }
        ),
        sorts=tuple(reversed(first.sorts)),
        roles=tuple(reversed(first.roles)),
        claims=tuple(reversed(first.claims)),
    )

    assert first.document_id == second.document_id
    assert first.semantic_dict() == second.semantic_dict()
    assert first.to_dict()["observations"] != second.to_dict()["observations"]
    assert "runner-a" not in first.semantic_bytes().decode()


@pytest.mark.parametrize(
    ("factory", "error"),
    [
        (
            lambda: ProtocolSort("sort:x", "X", SortKind.DATA),
            "must be source mapped",
        ),
        (
            lambda: ProtocolFunction(
                "function:x",
                "x",
                (),
                "sort:message",
                FunctionKind.CONSTRUCTOR,
                "exclusive_or",
                **_mapped(),
            ),
            "must be one of",
        ),
        (
            lambda: ProtocolChannel(
                "channel:bad",
                "bad",
                ChannelSecurity.SECURE,
                AdversaryAccess.CONTROL,
                **_mapped(),
            ),
            "secure channel must deny",
        ),
        (
            lambda: ProtocolAdversary(
                "adversary:passive",
                AdversaryKind.PASSIVE,
                (AdversaryCapability.INJECT,),
                **_mapped(),
            ),
            "passive adversary cannot",
        ),
    ],
)
def test_source_and_threat_model_assumptions_fail_closed(
    factory: object, error: str
) -> None:
    with pytest.raises(ProtocolValidationError, match=error):
        factory()  # type: ignore[operator]


def test_unsupported_or_disabled_equational_theories_fail_closed() -> None:
    unsupported = _document().to_dict()
    unsupported["document_id"] = ""
    unsupported["equational_theories"] = ["free", "exclusive_or"]
    with pytest.raises(ProtocolValidationError, match="must be one of"):
        ProtocolIR.from_dict(unsupported)


def test_disabled_theory_rejection_occurs_during_construction() -> None:
    document = _document()
    with pytest.raises(ProtocolValidationError, match="disabled equational theory"):
        replace(
            document,
            equational_theories=(EquationalTheory.FREE,),
            document_id="",
        )


def test_channel_access_cannot_exceed_the_declared_adversary() -> None:
    passive_public = _document().to_dict()
    passive_public["document_id"] = ""
    passive_public["adversary"].update(
        {
            "kind": "passive",
            "capabilities": ["compose", "decompose", "intercept"],
        }
    )
    passive_public["channels"][0]["adversary_access"] = "observe"
    assert ProtocolIR.from_dict(passive_public).adversary.kind is AdversaryKind.PASSIVE

    missing_capability = _document().to_dict()
    missing_capability["document_id"] = ""
    missing_capability["adversary"]["capabilities"].remove("intercept")
    with pytest.raises(ProtocolValidationError, match="requires capabilities"):
        ProtocolIR.from_dict(missing_capability)

    absent_adversary = _document().to_dict()
    absent_adversary["document_id"] = ""
    absent_adversary["adversary"].update(
        {
            "kind": "none",
            "capabilities": [],
            "knowledge": [],
            "compromised_role_ids": [],
            "compromised_key_ids": [],
        }
    )
    with pytest.raises(ProtocolValidationError, match="absent adversary"):
        ProtocolIR.from_dict(absent_adversary)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["messages"][0]["payload"].update(
            {"sort": "sort:nonce"}
        ),
        lambda data: data["messages"][0]["payload"]["arguments"][0].update(
            {"symbol_id": "name:unknown"}
        ),
        lambda data: data["messages"][0]["payload"].update({"arguments": []}),
        lambda data: data["roles"][0].update(
            {"parameter_ids": ["variable:responder-peer"]}
        ),
        lambda data: data["claims"][0].update(
            {"reachable_event_ids": ["event:accept"]}
        ),
    ],
)
def test_types_scopes_and_claim_shapes_are_checked(mutate: object) -> None:
    data = _document().to_dict()
    data["document_id"] = ""
    mutate(data)  # type: ignore[operator]

    with pytest.raises(ProtocolValidationError):
        ProtocolIR.from_dict(data)


def test_each_claim_kind_requires_its_own_operands() -> None:
    nonce = ProtocolTerm.symbol("name:challenge", "sort:nonce")
    mapped = _mapped()

    with pytest.raises(ProtocolValidationError, match="secrecy claim"):
        ProtocolClaim(
            "claim:bad-secret",
            ProtocolClaimKind.SECRECY,
            "Incorrectly event-shaped secrecy.",
            reachable_event_ids=("event:accept",),
            **mapped,
        )
    with pytest.raises(ProtocolValidationError, match="correspondence claim"):
        ProtocolClaim(
            "claim:half-correspondence",
            ProtocolClaimKind.CORRESPONDENCE,
            "Missing the required event.",
            antecedent_event_ids=("event:accept",),
            **mapped,
        )
    with pytest.raises(ProtocolValidationError, match="equivalence claim"):
        ProtocolClaim(
            "claim:ill-typed-equivalence",
            ProtocolClaimKind.EQUIVALENCE,
            "Observations use different sorts.",
            left_terms=(nonce,),
            right_terms=(ProtocolTerm(sort="sort:message", literal="message"),),
            **mapped,
        )


def test_dangling_source_and_semantic_references_are_rejected() -> None:
    data = _document().to_dict()
    data["document_id"] = ""
    data["messages"][0]["channel_id"] = "channel:missing"
    with pytest.raises(ProtocolValidationError, match="unknown ids"):
        ProtocolIR.from_dict(data)

    data = _document().to_dict()
    data["document_id"] = ""
    data["events"][0]["source_ref_ids"] = ["source:missing"]
    with pytest.raises(ProtocolValidationError, match="unknown ids"):
        ProtocolIR.from_dict(data)


def test_asymmetric_key_pairs_must_be_reciprocal_and_typed() -> None:
    data = _document().to_dict()
    data["document_id"] = ""
    data["keys"][0]["peer_key_id"] = "key:session"

    with pytest.raises(ProtocolValidationError, match="must be reciprocal"):
        ProtocolIR.from_dict(data)


def test_unknown_fields_and_stale_identity_are_rejected() -> None:
    data = _document().to_dict()
    data["unexpected"] = True
    with pytest.raises(ProtocolValidationError, match="unknown protocol document"):
        ProtocolIR.from_dict(data)

    document = _document()
    with pytest.raises(ProtocolValidationError, match="document_id does not match"):
        replace(document, metadata={"protocol": "changed"})
