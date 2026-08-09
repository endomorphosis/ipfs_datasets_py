"""Unit tests for TamarinControlledSource@1 and ProtocolRewritingAdapter@1 (LFP-030).

Acceptance evidence:

* mapping identifies unsupported theory/rule features
* event/fact provenance is preserved
* Tamarin status is decoded as a tool/version/profile-bound symbolic result
* status cannot become proof authority without an independently replayable route
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.parsers.tamarin import (
    CODE_PROVENANCE,
    CODE_RESULT_AUTHORITY,
    CODE_UNSUPPORTED_RULE,
    CODE_UNSUPPORTED_THEORY,
    FactKind,
    FactMultiplicity,
    MultisetFact,
    MultisetRule,
    PROTOCOL_REWRITING_ADAPTER_INTERFACE,
    ProtocolRewritingAdapter,
    ProtocolRewritingDocument,
    Restriction,
    TAMARIN_CONTROLLED_SOURCE_INTERFACE,
    TAMARIN_PROFILE_ID,
    TamarinControlledSource,
    TamarinControlledSourceError,
    TamarinMappingError,
    TamarinProtocolMappings,
    TamarinSymbolicResult,
    TraceLemma,
    UNSUPPORTED_RULE_FEATURES,
    UNSUPPORTED_THEORY_FEATURES,
    interpret_tamarin_results,
    lower_to_tamarin,
    parse_protocol_rewriting,
)
from ipfs_datasets_py.logic.software_verification.protocol import (
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
    ProtocolVariable,
    RewriteFact,
    SortKind,
    TrustAssumption,
)

SOURCE_ID = "source:handshake"
SPAN_ID = "span:tamarin"
TOOL_VERSION = "1.12.0"


def _source() -> SourceRef:
    return SourceRef(
        ref_id=SOURCE_ID,
        source_uri="file:///protocols/handshake.spthy.json",
        source_id="handshake.spthy.json",
        source_revision="git:abcdef0123456789",
        content_sha256="b" * 64,
    )


def _span() -> SourceSpan:
    return SourceSpan(
        span_id=SPAN_ID,
        source_ref_id=SOURCE_ID,
        start_byte=0,
        end_byte=2048,
        start_line=1,
        start_column=1,
        end_line=80,
        end_column=2,
    )


def _mapped() -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (SOURCE_ID,), "span_ids": (SPAN_ID,)}


def _protocol(
    *,
    equational_theories: tuple[EquationalTheory, ...] = (
        EquationalTheory.FREE,
        EquationalTheory.SYMMETRIC_ENCRYPTION,
    ),
    adversary_kind: AdversaryKind = AdversaryKind.DOLEV_YAO,
) -> ProtocolIR:
    use_symmetric = EquationalTheory.SYMMETRIC_ENCRYPTION in equational_theories
    theory = (
        EquationalTheory.SYMMETRIC_ENCRYPTION
        if use_symmetric
        else EquationalTheory.FREE
    )
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
            theory,
            **_mapped(),
        ),
        ProtocolFunction(
            "function:decrypt",
            "decrypt",
            ("sort:message", "sort:key"),
            "sort:nonce",
            FunctionKind.DESTRUCTOR,
            theory,
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
        AdversaryAccess.CONTROL
        if adversary_kind is AdversaryKind.DOLEV_YAO
        else AdversaryAccess.OBSERVE,
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
            "claim:authentication",
            ProtocolClaimKind.AUTHENTICATION,
            "Every accept authenticates an initiator run.",
            antecedent_event_ids=("event:accept",),
            consequent_event_ids=("event:begin",),
            correspondence=CorrespondenceKind.INJECTIVE,
            assumption_ids=("assumption:session-key",),
            **_mapped(),
        ),
    )
    if adversary_kind is AdversaryKind.DOLEV_YAO:
        capabilities = tuple(AdversaryCapability)
    elif adversary_kind is AdversaryKind.PASSIVE:
        capabilities = (
            AdversaryCapability.COMPOSE,
            AdversaryCapability.DECOMPOSE,
            AdversaryCapability.INTERCEPT,
        )
    else:
        capabilities = ()
    adversary = ProtocolAdversary(
        "adversary:network",
        adversary_kind,
        capabilities,
        knowledge=(
            AdversaryKnowledge(
                "knowledge:public-observation",
                ProtocolTerm(sort="sort:message", literal="public-tag"),
                **_mapped(),
            ),
        )
        if adversary_kind is not AdversaryKind.NONE
        else (),
        **_mapped(),
    )
    rewrite_facts = ()
    if use_symmetric:
        rewrite_facts = (
            RewriteFact(
                "fact:decrypt-encrypt",
                plaintext,
                nonce_term,
                EquationalTheory.SYMMETRIC_ENCRYPTION,
                **_mapped(),
            ),
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
        rewrite_facts=rewrite_facts,
        events=(begin, accept),
        claims=claims,
        equational_theories=equational_theories,
        metadata={"protocol": "challenge-response", "version": 1},
    )


def _state_fact(*, persistent: bool = False) -> MultisetFact:
    return MultisetFact(
        fact_id="fact:state-initiator",
        name="St_Initiator",
        multiplicity=(
            FactMultiplicity.PERSISTENT if persistent else FactMultiplicity.LINEAR
        ),
        kind=FactKind.STATE,
        arguments=(ProtocolTerm.symbol("name:challenge", "sort:nonce"),),
        **_mapped(),
    )


def _action_fact() -> MultisetFact:
    return MultisetFact(
        fact_id="fact:action-begin",
        name="BeginChallenge",
        multiplicity=FactMultiplicity.LINEAR,
        kind=FactKind.ACTION,
        arguments=(ProtocolTerm.symbol("name:challenge", "sort:nonce"),),
        **_mapped(),
    )


def _rule() -> MultisetRule:
    return MultisetRule(
        rule_id="rule:create-initiator",
        name="Create_Initiator",
        premises=(
            MultisetFact(
                fact_id="fact:fr",
                name="Fr",
                kind=FactKind.FRESH,
                arguments=(ProtocolTerm.symbol("name:challenge", "sort:nonce"),),
            ),
        ),
        actions=(_action_fact(),),
        conclusions=(_state_fact(),),
        **_mapped(),
    )


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert PROTOCOL_REWRITING_ADAPTER_INTERFACE == "ProtocolRewritingAdapter@1"
    assert TAMARIN_CONTROLLED_SOURCE_INTERFACE == "TamarinControlledSource@1"
    mappings = TamarinProtocolMappings(tool_version=TOOL_VERSION)
    assert mappings.interface_rewriting == PROTOCOL_REWRITING_ADAPTER_INTERFACE
    assert mappings.interface_source == TAMARIN_CONTROLLED_SOURCE_INTERFACE
    assert mappings.family_id == "cryptographic_protocol"
    assert mappings.profile_id == TAMARIN_PROFILE_ID
    assert isinstance(mappings.rewriting, ProtocolRewritingAdapter)
    assert isinstance(mappings.tamarin, TamarinControlledSource)


# ---------------------------------------------------------------------------
# Unsupported theory / rule features identified
# ---------------------------------------------------------------------------


def test_adapter_identifies_unsupported_theory_features() -> None:
    adapter = ProtocolRewritingAdapter()
    rejected = adapter.identify_unsupported_theory_features(
        ("pairing", "diff", "xor", "hashing", "equations_ac")
    )
    assert "diff" in rejected
    assert "xor" in rejected
    assert "equations_ac" in rejected
    assert "pairing" not in rejected
    assert "hashing" not in rejected
    assert set(rejected) <= UNSUPPORTED_THEORY_FEATURES


def test_adapter_identifies_unsupported_rule_features() -> None:
    adapter = ProtocolRewritingAdapter()
    rejected = adapter.identify_unsupported_rule_features(
        ("lock", "lookup", "premises", "diff_rule")
    )
    assert "lock" in rejected
    assert "lookup" in rejected
    assert "diff_rule" in rejected
    assert "premises" not in rejected
    assert set(rejected) <= UNSUPPORTED_RULE_FEATURES


def test_document_rejects_unsupported_theory_feature() -> None:
    with pytest.raises(TamarinMappingError) as excinfo:
        ProtocolRewritingDocument(
            protocol=_protocol(),
            theory_features=("diff",),
        )
    assert excinfo.value.code == CODE_UNSUPPORTED_THEORY
    assert "diff" in str(excinfo.value)


def test_rule_rejects_unsupported_feature_in_metadata() -> None:
    with pytest.raises(TamarinMappingError) as excinfo:
        MultisetRule(
            rule_id="rule:bad",
            name="Bad",
            premises=(_state_fact(),),
            conclusions=(_state_fact(persistent=True),),
            metadata={"lock": True},
        )
    assert excinfo.value.code == CODE_UNSUPPORTED_RULE


def test_rule_from_dict_rejects_unsupported_construct() -> None:
    with pytest.raises(TamarinMappingError) as excinfo:
        MultisetRule.from_dict(
            {
                "rule_id": "rule:lookup",
                "name": "Lookup",
                "construct": "lookup",
                "premises": [_state_fact().to_dict()],
                "conclusions": [_state_fact(persistent=True).to_dict()],
            }
        )
    assert excinfo.value.code == CODE_UNSUPPORTED_RULE


@pytest.mark.parametrize("feature", sorted(UNSUPPORTED_THEORY_FEATURES)[:8])
def test_require_supported_theory_features_fail_closed(feature: str) -> None:
    adapter = ProtocolRewritingAdapter()
    with pytest.raises(TamarinMappingError) as excinfo:
        adapter.require_supported_theory_features((feature,))
    assert excinfo.value.code == CODE_UNSUPPORTED_THEORY


# ---------------------------------------------------------------------------
# Event / fact provenance preserved
# ---------------------------------------------------------------------------


def test_event_fact_mapping_preserves_provenance() -> None:
    protocol = _protocol()
    adapter = ProtocolRewritingAdapter()
    facts = adapter.map_protocol_events_to_facts(protocol)

    assert len(facts) == len(protocol.events)
    for fact, event in zip(facts, protocol.events, strict=True):
        assert fact.kind is FactKind.ACTION
        assert fact.source_ref_ids == event.source_ref_ids
        assert fact.span_ids == event.span_ids
        assert fact.source_ref_ids == (SOURCE_ID,)
        assert fact.span_ids == (SPAN_ID,)
        assert fact.metadata.to_dict()["event_id"] == event.event_id


def test_action_fact_requires_provenance() -> None:
    with pytest.raises(TamarinMappingError) as excinfo:
        MultisetFact(
            fact_id="fact:orphan-action",
            name="Orphan",
            kind=FactKind.ACTION,
            arguments=(),
        )
    assert excinfo.value.code == CODE_PROVENANCE


def test_document_and_artifact_retain_event_fact_provenance() -> None:
    protocol = _protocol()
    document = ProtocolRewritingAdapter().build_document(
        protocol,
        rules=(_rule(),),
        restrictions=(
            Restriction(
                restriction_id="restriction:equality",
                name="Eq",
                formula="All x #i #j. Eq(x) @ i & Eq(x) @ j ==> #i = #j",
                **_mapped(),
            ),
        ),
        lemmas=(
            TraceLemma(
                lemma_id="lemma:extra",
                name="extra_reach",
                formula="Ex #i. BeginChallenge(x) @ i",
                claim_id="",
                **_mapped(),
            ),
        ),
    )
    receipts = document.event_fact_provenance()
    assert any(item.get("event_id") == "event:begin" for item in receipts)
    assert any(item.get("fact_id") == "fact:action-begin" for item in receipts)
    for item in receipts:
        if item.get("kind") in {"action", "protocol_event"}:
            assert item.get("source_ref_ids") == [SOURCE_ID]
            assert item.get("span_ids") == [SPAN_ID]

    artifact = lower_to_tamarin(document, tool_version=TOOL_VERSION)
    assert artifact.event_fact_provenance
    assert any(
        item.get("source_ref_ids") == [SOURCE_ID] for item in artifact.event_fact_provenance
    )
    # Equations from ProtocolIR rewrite facts retain provenance in source comments.
    assert "fact:decrypt-encrypt" in artifact.source
    assert SOURCE_ID in artifact.source or "sources=" in artifact.source


def test_persistent_and_linear_facts_map() -> None:
    linear = _state_fact(persistent=False)
    persistent = _state_fact(persistent=True)
    assert linear.multiplicity is FactMultiplicity.LINEAR
    assert persistent.multiplicity is FactMultiplicity.PERSISTENT
    assert linear.spthy_name() == "St_Initiator"
    assert persistent.spthy_name() == "!St_Initiator"
    assert linear.to_spthy({}).startswith("St_Initiator")
    assert persistent.to_spthy({}).startswith("!St_Initiator")


# ---------------------------------------------------------------------------
# Parse / lower
# ---------------------------------------------------------------------------


def test_parse_and_elaborate_round_trip() -> None:
    protocol = _protocol()
    document = parse_protocol_rewriting(
        {
            "protocol": protocol.to_dict(),
            "rules": [_rule().to_dict()],
            "facts": [_state_fact(persistent=True).to_dict()],
        }
    )
    assert document.interface == PROTOCOL_REWRITING_ADAPTER_INTERFACE
    assert document.elaborate().document_id == protocol.document_id
    assert document.equational_theories == protocol.equational_theories
    restored = ProtocolRewritingDocument.from_json(document.to_json())
    assert restored.document_id == document.document_id


def test_lower_to_tamarin_includes_rules_restrictions_lemmas_and_binding() -> None:
    document = ProtocolRewritingAdapter().build_document(
        _protocol(),
        rules=(_rule(),),
        restrictions=(
            Restriction(
                restriction_id="restriction:once",
                name="Once",
                formula="All x #i #j. Once(x) @ i & Once(x) @ j ==> #i = #j",
                **_mapped(),
            ),
        ),
        lemmas=(
            TraceLemma(
                lemma_id="lemma:manual",
                name="manual_secrecy",
                formula="not (Ex #i. K(challenge) @ i)",
                **_mapped(),
            ),
        ),
        include_event_facts=True,
    )
    artifact = lower_to_tamarin(document, tool_version=TOOL_VERSION)

    assert artifact.interface == TAMARIN_CONTROLLED_SOURCE_INTERFACE
    assert artifact.tool_id == "tamarin-prover"
    assert artifact.tool_version == TOOL_VERSION
    assert artifact.profile_id == TAMARIN_PROFILE_ID
    assert "symmetric_encryption" in artifact.equational_theories
    assert artifact.adversary_kind == "dolev_yao"
    assert artifact.ceiling.to_dict()["result_authority"] == ResultAuthority.PROTOCOL.value
    assert artifact.ceiling.to_dict()["proof_authority"] is False
    assert artifact.ceiling.to_dict()["tool_version"] == TOOL_VERSION
    assert artifact.ceiling.to_dict()["profile_id"] == TAMARIN_PROFILE_ID
    assert "rule Create_Initiator" in artifact.source
    assert "restriction Once" in artifact.source
    assert "lemma manual_secrecy" in artifact.source
    assert "claim:secrecy" in artifact.claim_lemmas.to_dict()
    assert artifact.protocol_document_id == document.protocol.document_id
    assert artifact.rewriting_document_id == document.document_id


def test_lower_supports_only_controlled_equational_theories() -> None:
    adapter = TamarinControlledSource(tool_version=TOOL_VERSION)
    assert adapter.supports_theory(EquationalTheory.HASHING)
    assert adapter.supports_theory(EquationalTheory.SYMMETRIC_ENCRYPTION)
    with pytest.raises(ValueError):
        adapter.supports_theory("exclusive_or")


# ---------------------------------------------------------------------------
# Tamarin status: tool/version/profile-bound symbolic; no proof authority
# ---------------------------------------------------------------------------


def test_tamarin_status_is_tool_version_profile_bound_symbolic_result() -> None:
    document = ProtocolRewritingAdapter().build_document(_protocol())
    artifact = lower_to_tamarin(document, tool_version=TOOL_VERSION)
    lemmas = artifact.claim_lemmas.to_dict()
    secrecy = lemmas["claim:secrecy"]
    auth = lemmas["claim:authentication"]
    stdout = (
        f"lemma {secrecy}: verified\n"
        f"lemma {auth}: verified\n"
    )
    result = interpret_tamarin_results(stdout=stdout, artifact=artifact)

    assert isinstance(result, TamarinSymbolicResult)
    assert result.authority is ResultAuthority.PROTOCOL
    assert result.authority is not ResultAuthority.THEOREM
    assert result.tool_id == "tamarin-prover"
    assert result.tool_version == TOOL_VERSION
    assert result.profile_id == TAMARIN_PROFILE_ID
    assert result.tool_version_profile_bound is True
    assert result.symbolic_model is True
    assert result.computational_soundness is False
    assert result.accepted is True
    assert result.status is ResultStatus.SECURE
    assert result.translation_ceiling is EvidenceAuthority.BOUNDED
    assert result.translation_ceiling is not EvidenceAuthority.AUTHORITATIVE
    assert result.independently_replayable is False
    assert result.can_become_proof_authority is False
    payload = result.to_dict()
    assert payload["authority"] == "protocol"
    assert payload["tool_version_profile_bound"] is True
    assert payload["can_become_proof_authority"] is False
    assert payload["independently_replayable"] is False


def test_tamarin_attack_retains_protocol_authority_and_provenance() -> None:
    document = ProtocolRewritingAdapter().build_document(_protocol())
    artifact = lower_to_tamarin(document, tool_version=TOOL_VERSION)
    lemmas = artifact.claim_lemmas.to_dict()
    secrecy = lemmas["claim:secrecy"]
    auth = lemmas["claim:authentication"]
    stdout = (
        f"lemma {secrecy}: falsified\n"
        f"lemma {auth}: falsified\n"
        "rule Create_Initiator(~n)\n"
        "action BeginChallenge(~n)\n"
    )
    result = interpret_tamarin_results(stdout=stdout, artifact=artifact)
    assert result.authority is ResultAuthority.PROTOCOL
    assert result.status is ResultStatus.ATTACK_FOUND
    assert result.accepted is False
    assert result.tool_version_profile_bound is True
    assert result.can_become_proof_authority is False
    falsified = [item for item in result.claim_outcomes if item.verdict.value == "falsified"]
    assert falsified
    assert all(item.attack_trace is not None for item in falsified)
    assert result.event_fact_provenance


def test_tamarin_symbolic_result_rejects_theorem_authority() -> None:
    document = ProtocolRewritingAdapter().build_document(_protocol())
    artifact = lower_to_tamarin(document, tool_version=TOOL_VERSION)
    with pytest.raises(TamarinControlledSourceError) as excinfo:
        TamarinSymbolicResult(
            status=ResultStatus.SECURE,
            authority=ResultAuthority.THEOREM,
            claim_outcomes=(),
            ceiling=artifact.ceiling,
            source_digest=artifact.source_digest,
            equational_theories=artifact.equational_theories,
            adversary_kind=artifact.adversary_kind,
            accepted=True,
            translation_ceiling=EvidenceAuthority.BOUNDED,
            tool_id=artifact.tool_id,
            tool_version=artifact.tool_version,
            profile_id=artifact.profile_id,
        )
    assert excinfo.value.code == CODE_RESULT_AUTHORITY
    assert "protocol authority" in str(excinfo.value)


def test_tamarin_cannot_become_proof_authority_without_replayable_route() -> None:
    document = ProtocolRewritingAdapter().build_document(_protocol())
    artifact = lower_to_tamarin(document, tool_version=TOOL_VERSION)
    lemmas = artifact.claim_lemmas.to_dict()
    secrecy = lemmas["claim:secrecy"]
    auth = lemmas["claim:authentication"]
    stdout = f"lemma {secrecy}: verified\nlemma {auth}: verified\n"
    result = interpret_tamarin_results(stdout=stdout, artifact=artifact)

    assert result.can_become_proof_authority is False
    with pytest.raises(TamarinControlledSourceError) as excinfo:
        result.as_proof_authority()
    assert excinfo.value.code == CODE_RESULT_AUTHORITY
    assert "independently replayable" in str(excinfo.value).lower()


def test_independently_replayable_still_cannot_relabel_authority() -> None:
    document = ProtocolRewritingAdapter().build_document(_protocol())
    artifact = lower_to_tamarin(document, tool_version=TOOL_VERSION)
    lemmas = artifact.claim_lemmas.to_dict()
    secrecy = lemmas["claim:secrecy"]
    auth = lemmas["claim:authentication"]
    stdout = f"lemma {secrecy}: verified\nlemma {auth}: verified\n"
    result = interpret_tamarin_results(
        stdout=stdout,
        artifact=artifact,
        independently_replayable=True,
        replay_route="kernel://lean/replay/v1#digest",
    )
    assert result.independently_replayable is True
    assert result.can_become_proof_authority is True
    assert result.authority is ResultAuthority.PROTOCOL
    # Replay may feed another lane, but this result is never re-labeled theorem.
    with pytest.raises(TamarinControlledSourceError) as excinfo:
        result.as_proof_authority()
    assert excinfo.value.code == CODE_RESULT_AUTHORITY
    assert result.authority is not ResultAuthority.THEOREM


def test_independently_replayable_requires_explicit_route() -> None:
    document = ProtocolRewritingAdapter().build_document(_protocol())
    artifact = lower_to_tamarin(document, tool_version=TOOL_VERSION)
    with pytest.raises(TamarinControlledSourceError) as excinfo:
        TamarinSymbolicResult(
            status=ResultStatus.SECURE,
            authority=ResultAuthority.PROTOCOL,
            claim_outcomes=(),
            ceiling=artifact.ceiling,
            source_digest=artifact.source_digest,
            equational_theories=artifact.equational_theories,
            adversary_kind=artifact.adversary_kind,
            accepted=True,
            translation_ceiling=EvidenceAuthority.BOUNDED,
            tool_id=artifact.tool_id,
            tool_version=artifact.tool_version,
            profile_id=artifact.profile_id,
            independently_replayable=True,
            replay_route="",
        )
    assert "replay_route" in str(excinfo.value)


def test_facade_lower_and_interpret() -> None:
    mappings = TamarinProtocolMappings(tool_version=TOOL_VERSION)
    document = mappings.parse(_protocol())
    artifact = mappings.lower_to_tamarin(document)
    lemma = next(iter(artifact.claim_lemmas.to_dict().values()))
    result = mappings.interpret_tamarin(
        stdout=f"lemma {lemma}: analysis incomplete\n",
        artifact=artifact,
    )
    assert result.authority is ResultAuthority.PROTOCOL
    assert result.status is ResultStatus.UNKNOWN
    assert result.accepted is False
    assert result.tool_version_profile_bound is True
    assert result.can_become_proof_authority is False


def test_parse_protocol_ir_directly() -> None:
    protocol = _protocol()
    document = parse_protocol_rewriting(protocol)
    assert document.protocol == protocol
    assert document.equational_theories == protocol.equational_theories
    # Auto-mapped event facts preserve provenance.
    assert document.facts
    assert all(fact.source_ref_ids == (SOURCE_ID,) for fact in document.facts)
