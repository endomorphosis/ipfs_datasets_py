"""Unit tests for SymbolicProtocolSyntax@1 and ProVerifControlledSource@1 (LFP-029).

Acceptance evidence:

* equational theory and attacker model enter identity
* unsupported process constructs fail explicitly
* ProVerif results retain symbolic over-approximation and query-specific authority
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.parsers.protocol import (
    CODE_UNSUPPORTED_PROCESS,
    PROVERIF_CONTROLLED_SOURCE_INTERFACE,
    ProcessKind,
    ProcessNode,
    ProVerifControlledSource,
    ProVerifControlledSourceError,
    ProVerifSymbolicResult,
    SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE,
    SymbolicProtocolDocument,
    SymbolicProtocolSyntax,
    UNSUPPORTED_PROCESS_CONSTRUCTS,
    interpret_proverif_results,
    lower_to_proverif,
    parse_symbolic_protocol,
    ProtocolSyntaxError,
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
        AdversaryAccess.CONTROL if adversary_kind is AdversaryKind.DOLEV_YAO else AdversaryAccess.OBSERVE,
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
    capabilities: tuple[AdversaryCapability, ...]
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


def _initiator_process() -> ProcessNode:
    nonce_term = ProtocolTerm.symbol("name:challenge", "sort:nonce")
    session_key = ProtocolTerm.symbol("key:session", "sort:key")
    ciphertext = ProtocolTerm.application(
        "function:encrypt", (nonce_term, session_key), "sort:message"
    )
    return ProcessNode(
        kind=ProcessKind.SEQUENCE,
        children=(
            ProcessNode(
                kind=ProcessKind.NEW,
                name="name:challenge",
                sort="sort:nonce",
                children=(
                    ProcessNode(
                        kind=ProcessKind.EVENT,
                        event_id="event:begin",
                        parameters=(nonce_term,),
                        children=(
                            ProcessNode(
                                kind=ProcessKind.OUT,
                                channel="channel:network",
                                term=ciphertext,
                                children=(ProcessNode.null(),),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE == "SymbolicProtocolSyntax@1"
    assert PROVERIF_CONTROLLED_SOURCE_INTERFACE == "ProVerifControlledSource@1"
    syntax = SymbolicProtocolSyntax()
    assert syntax.interface == SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE
    assert syntax.family_id == "cryptographic_protocol"
    assert isinstance(syntax.proverif, ProVerifControlledSource)


# ---------------------------------------------------------------------------
# Equational theory and attacker model enter identity
# ---------------------------------------------------------------------------


def test_equational_theory_enters_document_identity() -> None:
    free_only = SymbolicProtocolDocument(
        protocol=_protocol(equational_theories=(EquationalTheory.FREE,))
    )
    with_sym = SymbolicProtocolDocument(
        protocol=_protocol(
            equational_theories=(
                EquationalTheory.FREE,
                EquationalTheory.SYMMETRIC_ENCRYPTION,
            )
        )
    )

    assert free_only.document_id != with_sym.document_id
    assert free_only.semantic_dict()["equational_theories"] == ["free"]
    assert "symmetric_encryption" in with_sym.semantic_dict()["equational_theories"]
    # Identity preimage embeds ProtocolIR semantics, which also carry theories.
    assert free_only.semantic_dict()["protocol"]["equational_theories"] == ["free"]
    assert free_only.protocol.document_id != with_sym.protocol.document_id


def test_attacker_model_enters_document_identity() -> None:
    dolev = SymbolicProtocolDocument(
        protocol=_protocol(adversary_kind=AdversaryKind.DOLEV_YAO)
    )
    passive = SymbolicProtocolDocument(
        protocol=_protocol(adversary_kind=AdversaryKind.PASSIVE)
    )

    assert dolev.document_id != passive.document_id
    assert dolev.semantic_dict()["protocol_adversary_kind"] == "dolev_yao"
    assert passive.semantic_dict()["protocol_adversary_kind"] == "passive"
    assert dolev.adversary.kind is AdversaryKind.DOLEV_YAO
    assert passive.adversary.kind is AdversaryKind.PASSIVE


def test_identity_stable_under_process_order_and_excludes_observations() -> None:
    process = _initiator_process()
    first = SymbolicProtocolDocument(
        protocol=_protocol(),
        processes=(("role:initiator", process),),
    )
    second = SymbolicProtocolDocument(
        protocol=_protocol(),
        processes={"role:initiator": process},
    )
    assert first.document_id == second.document_id
    assert first.semantic_dict() == second.semantic_dict()


# ---------------------------------------------------------------------------
# Unsupported process constructs fail explicitly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("construct", sorted(UNSUPPORTED_PROCESS_CONSTRUCTS))
def test_unsupported_process_constructs_fail_explicitly(construct: str) -> None:
    with pytest.raises(ProtocolSyntaxError) as excinfo:
        ProcessNode.from_dict({"kind": construct})
    error = excinfo.value
    assert error.code == CODE_UNSUPPORTED_PROCESS
    assert construct in str(error)


def test_unknown_process_construct_fails_closed() -> None:
    with pytest.raises(ProtocolSyntaxError) as excinfo:
        ProcessNode(kind="teleport")
    assert excinfo.value.code == CODE_UNSUPPORTED_PROCESS


def test_supported_process_constructs_round_trip() -> None:
    term = ProtocolTerm.symbol("name:challenge", "sort:nonce")
    node = ProcessNode(
        kind=ProcessKind.OUT,
        channel="channel:network",
        term=term,
        children=(ProcessNode.null(),),
    )
    restored = ProcessNode.from_dict(node.to_dict())
    assert restored == node
    assert restored.kind is ProcessKind.OUT


def test_document_rejects_process_for_unknown_role() -> None:
    with pytest.raises(ProtocolSyntaxError) as excinfo:
        SymbolicProtocolDocument(
            protocol=_protocol(),
            processes=(("role:missing", ProcessNode.null()),),
        )
    assert excinfo.value.code == "protocol.unknown_role_process"


# ---------------------------------------------------------------------------
# Parse / elaborate / ProVerif lowering
# ---------------------------------------------------------------------------


def test_parse_and_elaborate_round_trip() -> None:
    protocol = _protocol()
    document = parse_symbolic_protocol(
        {
            "protocol": protocol.to_dict(),
            "processes": {
                "role:initiator": _initiator_process().to_dict(),
            },
        }
    )
    assert document.interface == SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE
    assert document.elaborate().document_id == protocol.document_id
    syntax = SymbolicProtocolSyntax()
    printed = syntax.print_json(document)
    restored = syntax.parse_json(printed)
    assert restored.document_id == document.document_id
    assert restored.protocol.document_id == protocol.document_id


def test_lower_to_proverif_includes_theory_attacker_and_process() -> None:
    document = SymbolicProtocolDocument(
        protocol=_protocol(),
        processes=(("role:initiator", _initiator_process()),),
    )
    artifact = lower_to_proverif(document)

    assert artifact.interface == PROVERIF_CONTROLLED_SOURCE_INTERFACE
    assert "symmetric_encryption" in artifact.equational_theories
    assert artifact.adversary_kind == "dolev_yao"
    assert artifact.ceiling.to_dict()["symbolic_over_approximation"] is True
    assert artifact.ceiling.to_dict()["computational_soundness"] is False
    assert artifact.ceiling.to_dict()["result_authority"] == ResultAuthority.PROTOCOL.value
    assert artifact.ceiling.to_dict()["query_specific"] is True
    assert "free c: channel." in artifact.source
    assert "query" in artifact.source
    assert "out(" in artifact.source
    assert "event" in artifact.source
    assert "claim:secrecy" in artifact.claim_queries.to_dict()
    assert artifact.protocol_document_id == document.protocol.document_id
    assert artifact.symbolic_document_id == document.document_id


def test_lower_supports_only_controlled_equational_theories() -> None:
    adapter = ProVerifControlledSource()
    assert adapter.supports_theory(EquationalTheory.HASHING)
    assert adapter.supports_theory(EquationalTheory.SYMMETRIC_ENCRYPTION)
    with pytest.raises(ValueError):
        adapter.supports_theory("exclusive_or")


# ---------------------------------------------------------------------------
# ProVerif results: symbolic over-approximation + query-specific authority
# ---------------------------------------------------------------------------


def test_proverif_results_retain_symbolic_over_approximation_and_protocol_authority() -> None:
    document = SymbolicProtocolDocument(protocol=_protocol())
    artifact = lower_to_proverif(document)
    queries = artifact.claim_queries.to_dict()
    secrecy_query = queries["claim:secrecy"]
    auth_query = queries["claim:authentication"]

    stdout = (
        f"RESULT {secrecy_query} is true.\n"
        f"RESULT {auth_query} is true.\n"
    )
    result = interpret_proverif_results(stdout=stdout, artifact=artifact)

    assert isinstance(result, ProVerifSymbolicResult)
    assert result.authority is ResultAuthority.PROTOCOL
    assert result.authority is not ResultAuthority.THEOREM
    assert result.symbolic_over_approximation is True
    assert result.computational_soundness is False
    assert result.query_specific is True
    assert result.accepted is True
    assert result.status is ResultStatus.SECURE
    assert result.translation_ceiling is EvidenceAuthority.BOUNDED
    assert result.translation_ceiling is not EvidenceAuthority.AUTHORITATIVE
    assert {item.claim_id for item in result.claim_outcomes} >= {
        "claim:secrecy",
        "claim:authentication",
    }
    assert all(item.verdict.value == "true" for item in result.claim_outcomes)
    payload = result.to_dict()
    assert payload["authority"] == "protocol"
    assert payload["symbolic_over_approximation"] is True
    assert payload["query_specific"] is True
    assert payload["computational_soundness"] is False


def test_proverif_attack_is_query_specific_and_never_theorem_authority() -> None:
    document = SymbolicProtocolDocument(protocol=_protocol())
    artifact = lower_to_proverif(document)
    secrecy_query = artifact.claim_queries.to_dict()["claim:secrecy"]
    stdout = (
        f"RESULT {secrecy_query} is false.\n"
        "-> out(c, challenge)\n"
        "-> event(BeginChallenge)\n"
    )
    # Leave authentication without a RESULT so multi-claim becomes inconclusive
    # when only one is false... actually false alone with missing others is
    # quarantined as incomplete. Force both false for ATTACK_FOUND.
    auth_query = artifact.claim_queries.to_dict()["claim:authentication"]
    stdout = (
        f"RESULT {secrecy_query} is false.\n"
        f"RESULT {auth_query} is false.\n"
        "-> out(c, challenge)\n"
    )
    result = interpret_proverif_results(stdout=stdout, artifact=artifact)
    assert result.authority is ResultAuthority.PROTOCOL
    assert result.status is ResultStatus.ATTACK_FOUND
    assert result.accepted is False
    assert result.symbolic_over_approximation is True
    false_hits = [item for item in result.claim_outcomes if item.verdict.value == "false"]
    assert false_hits
    assert all(item.attack_trace is not None for item in false_hits)


def test_proverif_symbolic_result_rejects_theorem_authority() -> None:
    document = SymbolicProtocolDocument(protocol=_protocol())
    artifact = lower_to_proverif(document)
    with pytest.raises(ProVerifControlledSourceError) as excinfo:
        ProVerifSymbolicResult(
            status=ResultStatus.SECURE,
            authority=ResultAuthority.THEOREM,
            claim_outcomes=(),
            ceiling=artifact.ceiling,
            source_digest=artifact.source_digest,
            equational_theories=artifact.equational_theories,
            adversary_kind=artifact.adversary_kind,
            accepted=True,
            translation_ceiling=EvidenceAuthority.BOUNDED,
        )
    assert "protocol authority" in str(excinfo.value)


def test_proverif_symbolic_result_rejects_dropping_over_approximation() -> None:
    document = SymbolicProtocolDocument(protocol=_protocol())
    artifact = lower_to_proverif(document)
    with pytest.raises(ProVerifControlledSourceError):
        ProVerifSymbolicResult(
            status=ResultStatus.SECURE,
            authority=ResultAuthority.PROTOCOL,
            claim_outcomes=(),
            ceiling=artifact.ceiling,
            source_digest=artifact.source_digest,
            equational_theories=artifact.equational_theories,
            adversary_kind=artifact.adversary_kind,
            accepted=True,
            translation_ceiling=EvidenceAuthority.BOUNDED,
            symbolic_over_approximation=False,
        )


def test_syntax_facade_lower_and_interpret() -> None:
    syntax = SymbolicProtocolSyntax()
    document = syntax.parse_protocol_ir(_protocol())
    artifact = syntax.lower_to_proverif(document)
    query = next(iter(artifact.claim_queries.to_dict().values()))
    result = syntax.interpret_proverif(
        stdout=f"RESULT {query} is cannot be proved.\n",
        artifact=artifact,
    )
    assert result.authority is ResultAuthority.PROTOCOL
    assert result.status is ResultStatus.UNKNOWN
    assert result.accepted is False
    assert result.symbolic_over_approximation is True


def test_parse_protocol_ir_directly() -> None:
    protocol = _protocol()
    document = parse_symbolic_protocol(protocol)
    assert document.protocol == protocol
    assert document.equational_theories == protocol.equational_theories
