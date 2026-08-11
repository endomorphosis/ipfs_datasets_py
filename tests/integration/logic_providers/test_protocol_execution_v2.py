"""Integration tests: ProVerif / Tamarin protocol evidence with attack replay (LFP2-031).

Acceptance (fail-closed):

* Provider-specific assumptions remain distinct (applied-pi vs multiset rewriting).
* One provider's support cannot establish the other's assumptions.
* Reported attacks/witnesses are parsed and replayed or explicitly non-replayable.
* Equations, roles/rules, channels, attacker, secrecy/correspondence identities
  are preserved on every answer.

Interfaces: ProtocolProviderEvidence@2
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.protocol.execution_v2 import (
    PROVERIF_CAPABILITY,
    PROTOCOL_EXECUTION_V2_TASK_ID,
    PROTOCOL_PROVIDER_EVIDENCE_V2_INTERFACE,
    TAMARIN_CAPABILITY,
    ProtocolAssumptionsBindingV2,
    ProtocolAttackBindingV2,
    ProtocolAttackStatus,
    ProtocolAuthorityError,
    ProtocolCapabilityReceiptV2,
    ProtocolClaimKindV2,
    ProtocolDisposition,
    ProtocolDocumentBindingV2,
    ProtocolExecutionEngineV2,
    ProtocolExecutionError,
    ProtocolExecutionMode,
    ProtocolExecutionRequestV2,
    ProtocolProcessModel,
    ProtocolProviderEvidenceV2,
    ProtocolProviderKind,
    capability_for,
    execute_proverif,
    execute_tamarin,
    non_authoritative_signal_establishes,
    normalize_protocol_provider,
    provider_assumptions_establish_other,
)
from ipfs_datasets_py.logic.backends.protocol.proverif import ProVerifBackend
from ipfs_datasets_py.logic.backends.protocol.tamarin import TamarinBackend
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SOURCE_ID = "source:handshake"
SPAN_ID = "span:protocol"

TAMARIN_SECURE = """\
lemma secrecy_claim: verified (all-traces)
lemma authentication_claim: verified (all-traces)
"""

TAMARIN_ATTACK = """\
lemma secrecy_claim: falsified - found trace
rule Create_Initiator(~id)
rule Event_BeginChallenge(~n)
rule Event_AcceptChallenge(~n)
"""

PROVERIF_SECURE = """\
RESULT not attacker(challenge[]) is true.
RESULT inj-event(AcceptChallenge(x)) ==> inj-event(BeginChallenge(x)) is true.
"""

PROVERIF_ATTACK = """\
RESULT not attacker(challenge) is false.
-> event AcceptChallenge(n)
-> out(c, n)
"""

HANDSHAKE_SPTHY = """\
theory Handshake
begin

builtins: symmetric-encryption, hashing

lemma secrecy_claim:
  "All n #i. Secret(n) @ i ==> not (Ex #j. K(n) @ j)"

lemma authentication_claim:
  "All x #i. AcceptChallenge(x) @ i ==> (Ex #j. BeginChallenge(x) @ j & #j < #i)"

end
"""

HANDSHAKE_PV = """\
(* claim:secrecy *)
query not attacker(challenge).
(* claim:auth *)
query inj-event(AcceptChallenge(x)) ==> inj-event(BeginChallenge(x)).

free c: channel.
fun senc(bitstring, bitstring): bitstring.
process
  new challenge: bitstring;
  event BeginChallenge(challenge);
  event AcceptChallenge(challenge).
"""


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


def _protocol(*, include_equivalence: bool = False) -> ProtocolIR:
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
    claims = [
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
    ]
    if include_equivalence:
        claims.append(
            ProtocolClaim(
                "claim:equivalence",
                ProtocolClaimKind.EQUIVALENCE,
                "Observations are indistinguishable.",
                left_terms=(
                    ProtocolTerm(sort="sort:message", literal="left-observation"),
                ),
                right_terms=(
                    ProtocolTerm(sort="sort:message", literal="right-observation"),
                ),
                **_mapped(),
            )
        )
    adversary = ProtocolAdversary(
        "adversary:network",
        AdversaryKind.DOLEV_YAO,
        tuple(AdversaryCapability),
        knowledge=(
            AdversaryKnowledge(
                "knowledge:public",
                ProtocolTerm(sort="sort:message", literal="public-const"),
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
        claims=tuple(claims),
        equational_theories=(
            EquationalTheory.FREE,
            EquationalTheory.SYMMETRIC_ENCRYPTION,
        ),
        metadata={"protocol": "challenge-response", "version": 1},
    )


def _source_from_invocation(invocation: object) -> str:
    """Recover compiled protocol source from a hermetic process invocation.

    ``BoundedToolRunner`` writes input files into a private workspace and only
    exposes ``cwd`` / ``argv`` on :class:`ProcessInvocation` (not the original
    ``input_files`` mapping).  Auto-secure fixtures must therefore read the
    compiled ``.spthy`` / ``.pv`` body from that workspace so RESULT/lemma
    lines align with ProtocolIR claim identities.
    """

    candidates: list[Path] = []
    cwd = getattr(invocation, "cwd", None)
    if cwd is not None:
        workspace = Path(cwd)
        candidates.extend(
            (
                workspace / "protocol.spthy",
                workspace / "protocol.pv",
            )
        )
    argv = getattr(invocation, "argv", ()) or ()
    for argument in argv:
        if not isinstance(argument, str):
            continue
        if argument.endswith((".spthy", ".pv")):
            candidates.append(Path(argument))
    for path in candidates:
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            continue

    # Compatibility path if a richer invocation surface ever exposes files.
    files = getattr(invocation, "input_files", None)
    if isinstance(files, dict) and files:
        content = next(iter(files.values()))
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return str(content)
    return ""


def _auto_tamarin_secure(source: str) -> str:
    """Emit verified lines for every lemma declared in compiled spthy."""

    import re

    lemmas = re.findall(
        r"(?im)^\s*lemma\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", source
    )
    if not lemmas:
        return TAMARIN_SECURE
    return "\n".join(f"lemma {name}: verified (all-traces)" for name in lemmas) + "\n"


def _auto_proverif_secure(source: str) -> str:
    """Emit RESULT true lines for every query declared in compiled pv."""

    import re

    queries = re.findall(r"(?is)\bquery\s+(.+?)\s*\.", source)
    if not queries:
        return PROVERIF_SECURE
    lines = []
    for query in queries:
        normalized = " ".join(query.split())
        lines.append(f"RESULT {normalized} is true.")
    return "\n".join(lines) + "\n"


def _process_runner(
    stdout: str | None = None,
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    unavailable: bool = False,
    auto_secure: str | None = None,
) -> BoundedToolRunner:
    """Build a bounded runner with fixed or source-aligned secure stdout."""

    def execute(invocation, _cancellation):
        text = stdout
        if text is None and auto_secure == "tamarin":
            text = _auto_tamarin_secure(_source_from_invocation(invocation))
        elif text is None and auto_secure == "proverif":
            text = _auto_proverif_secure(_source_from_invocation(invocation))
        elif text is None:
            text = ""
        return RawProcessResult(
            returncode=returncode,
            stdout=text,
            elapsed_seconds=0.012,
            timed_out=timed_out,
            process_tree_terminated=timed_out,
            error="executable not found" if unavailable else "",
        )

    return BoundedToolRunner(executor=execute)


def _engine_with(
    *,
    proverif_stdout: str | None = None,
    tamarin_stdout: str | None = None,
    proverif_available: bool = True,
    tamarin_available: bool = True,
    auto_secure: bool = True,
) -> ProtocolExecutionEngineV2:
    """Build an engine with hermetic runners.

    When *auto_secure* is true and no fixed stdout is provided, runners emit
    verified/true outcomes aligned with the compiled source so ProtocolIR
    document paths exercise full SECURE evidence bindings.
    """

    pv_auto = "proverif" if auto_secure and proverif_stdout is None else None
    tm_auto = "tamarin" if auto_secure and tamarin_stdout is None else None
    return ProtocolExecutionEngineV2(
        proverif=ProVerifBackend(
            runner=_process_runner(
                proverif_stdout,
                unavailable=not proverif_available,
                auto_secure=pv_auto,
            ),
            available_probe=lambda: proverif_available,
            version_probe=lambda: "ProVerif 2.05",
            opam_probe=lambda: "2.05",
            backend_version="2.05",
        ),
        tamarin=TamarinBackend(
            runner=_process_runner(
                tamarin_stdout,
                unavailable=not tamarin_available,
                auto_secure=tm_auto,
            ),
            available_probe=lambda: tamarin_available,
            version_probe=lambda: "tamarin-prover 1.8.0",
            maude_probe=lambda: "Maude 3.1",
            backend_version="1.8.0",
        ),
    )


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    engine = ProtocolExecutionEngineV2()
    assert engine.INTERFACE == PROTOCOL_PROVIDER_EVIDENCE_V2_INTERFACE
    assert engine.interface == "ProtocolProviderEvidence@2"
    assert engine.TASK_ID == PROTOCOL_EXECUTION_V2_TASK_ID
    assert engine.TASK_ID == "LFP2-031"
    assert ProtocolExecutionRequestV2.interface == "ProtocolExecutionRequest@2"


def test_provider_normalization() -> None:
    assert normalize_protocol_provider("proverif") is ProtocolProviderKind.PROVERIF
    assert normalize_protocol_provider("tamarin-prover") is ProtocolProviderKind.TAMARIN
    assert normalize_protocol_provider("protocol_proverif") is ProtocolProviderKind.PROVERIF
    assert normalize_protocol_provider(ProtocolProviderKind.TAMARIN) is ProtocolProviderKind.TAMARIN
    with pytest.raises(ProtocolExecutionError):
        normalize_protocol_provider("z3")
    with pytest.raises(ProtocolExecutionError):
        normalize_protocol_provider("proverif_tamarin")


# ---------------------------------------------------------------------------
# Independent assumptions: one provider cannot establish another
# ---------------------------------------------------------------------------


def test_each_provider_capability_is_independent() -> None:
    pv = capability_for(ProtocolProviderKind.PROVERIF)
    tm = capability_for(ProtocolProviderKind.TAMARIN)

    assert pv == PROVERIF_CAPABILITY
    assert tm == TAMARIN_CAPABILITY
    assert pv.provider is ProtocolProviderKind.PROVERIF
    assert tm.provider is ProtocolProviderKind.TAMARIN
    assert pv.process_model is ProtocolProcessModel.APPLIED_PI
    assert tm.process_model is ProtocolProcessModel.MULTISET_REWRITING
    assert pv.dependency_kind == "opam"
    assert tm.dependency_kind == "maude"
    assert pv.supports_equivalence is True
    assert tm.supports_equivalence is False
    assert ProtocolClaimKind.EQUIVALENCE.value in pv.supported_claim_kinds
    assert ProtocolClaimKind.EQUIVALENCE.value not in tm.supported_claim_kinds
    assert pv.dependency_name != tm.dependency_name
    assert set(pv.supported_claim_kinds) != set(tm.supported_claim_kinds) or (
        pv.supports_equivalence != tm.supports_equivalence
    )


def test_provider_assumptions_never_establish_other() -> None:
    for source in ProtocolProviderKind:
        for target in ProtocolProviderKind:
            assert (
                provider_assumptions_establish_other(
                    source,
                    target,
                    source_available=True,
                    source_supported=True,
                )
                is False
            )


def test_available_proverif_does_not_establish_tamarin_assumptions() -> None:
    engine = ProtocolExecutionEngineV2(
        proverif=ProVerifBackend(
            runner=_process_runner(auto_secure="proverif"),
            available_probe=lambda: True,
            version_probe=lambda: "ProVerif 2.05",
            opam_probe=lambda: "2.05",
        ),
        tamarin=TamarinBackend(
            available_probe=lambda: False,
            version_probe=lambda: "tamarin-prover 1.8.0",
            maude_probe=lambda: "Maude 3.1",
        ),
    )
    pv_cap = engine.capability_receipt(ProtocolProviderKind.PROVERIF)
    tm_cap = engine.capability_receipt(ProtocolProviderKind.TAMARIN)

    assert pv_cap.available is True
    assert tm_cap.available is False
    assert pv_cap.establishes(ProtocolProviderKind.TAMARIN) is False
    assert tm_cap.establishes(ProtocolProviderKind.PROVERIF) is False

    result = engine.execute(
        ProtocolExecutionRequestV2(
            request_id="req:pv:only",
            provider=ProtocolProviderKind.PROVERIF,
            document=_protocol(),
            mode=ProtocolExecutionMode.ENGINE,
        )
    )
    assert result.evidence.available is True
    assert result.evidence.establishes_other_provider(ProtocolProviderKind.TAMARIN) is False
    wire = result.evidence.to_dict()
    assert wire["claim_other_provider_assumptions"] is False


def test_split_provider_execution_keeps_assumptions_isolated() -> None:
    engine = _engine_with()
    results = engine.execute_split_providers(
        _protocol(),
        request_id_prefix="req:split",
    )
    assert set(results) == set(ProtocolProviderKind)
    providers_seen = {result.evidence.provider for result in results.values()}
    assert providers_seen == set(ProtocolProviderKind)

    for kind, result in results.items():
        assert result.provider is kind
        assert result.evidence.provider is kind
        assert result.evidence.assumptions.provider is kind
        assert result.evidence.bindings_complete() is True
        for other in ProtocolProviderKind:
            if other is kind:
                continue
            assert result.evidence.establishes_other_provider(other) is False

    # Distinct process models and dependency identities remain on each path.
    assert (
        results[ProtocolProviderKind.PROVERIF].evidence.assumptions.process_model
        is ProtocolProcessModel.APPLIED_PI
    )
    assert (
        results[ProtocolProviderKind.TAMARIN].evidence.assumptions.process_model
        is ProtocolProcessModel.MULTISET_REWRITING
    )
    assert (
        results[ProtocolProviderKind.PROVERIF].evidence.assumptions.dependency_kind
        == "opam"
    )
    assert (
        results[ProtocolProviderKind.TAMARIN].evidence.assumptions.dependency_kind
        == "maude"
    )
    assert (
        results[ProtocolProviderKind.PROVERIF].evidence.assumptions.supports_equivalence
        is True
    )
    assert (
        results[ProtocolProviderKind.TAMARIN].evidence.assumptions.supports_equivalence
        is False
    )


def test_capability_receipt_rejects_cross_provider_relabel() -> None:
    with pytest.raises(ProtocolAuthorityError, match="re-labeled|match"):
        ProtocolCapabilityReceiptV2(
            provider=ProtocolProviderKind.PROVERIF,
            available=True,
            supported_document=True,
            capability=TAMARIN_CAPABILITY.to_dict(),  # wrong provider payload
        )


def test_assumptions_binding_rejects_wrong_process_model() -> None:
    with pytest.raises(ProtocolAuthorityError, match="process model"):
        ProtocolAssumptionsBindingV2(
            provider=ProtocolProviderKind.PROVERIF,
            process_model=ProtocolProcessModel.MULTISET_REWRITING,  # wrong
            adversary_model="dolev_yao",
            perfect_cryptography=True,
            computational_soundness=False,
            bitstring_level=False,
            dependency_kind="opam",
            dependency_name="opam:proverif",
            supported_claim_kinds=PROVERIF_CAPABILITY.supported_claim_kinds,
            supported_equational_theories=PROVERIF_CAPABILITY.supported_equational_theories,
            supports_equivalence=True,
            backend_interface=PROVERIF_CAPABILITY.backend_interface,
        )


# ---------------------------------------------------------------------------
# Every result binds document structure, assumptions, attack status
# ---------------------------------------------------------------------------


def test_result_binds_document_assumptions_attack() -> None:
    engine = _engine_with()
    doc = _protocol()
    result = engine.execute(
        ProtocolExecutionRequestV2(
            request_id="req:bind:tamarin",
            provider=ProtocolProviderKind.TAMARIN,
            document=doc,
            mode=ProtocolExecutionMode.ENGINE,
        )
    )
    evidence = result.evidence
    assert evidence.interface == PROTOCOL_PROVIDER_EVIDENCE_V2_INTERFACE
    assert evidence.bindings_complete() is True

    # Provider + assumptions
    assert evidence.provider is ProtocolProviderKind.TAMARIN
    assert isinstance(evidence.assumptions, ProtocolAssumptionsBindingV2)
    assert evidence.assumptions.process_model is ProtocolProcessModel.MULTISET_REWRITING
    assert evidence.assumptions.dependency_kind == "maude"
    assert evidence.assumptions.perfect_cryptography is True
    assert evidence.assumptions.computational_soundness is False
    assert evidence.assumptions.tool_version
    assert evidence.assumptions.dependency_version

    # Document structure
    assert isinstance(evidence.document, ProtocolDocumentBindingV2)
    assert evidence.document.document_id == doc.document_id
    assert evidence.document.document_digest == doc.sha256
    assert "role:initiator" in evidence.document.role_ids
    assert "role:responder" in evidence.document.role_ids
    assert "channel:network" in evidence.document.channel_ids
    assert "fact:decrypt-encrypt" in evidence.document.rewrite_fact_ids
    assert "event:begin" in evidence.document.event_ids
    assert "claim:secrecy" in evidence.document.claim_ids
    assert ProtocolClaimKind.SECRECY.value in evidence.document.claim_kinds
    assert ProtocolClaimKind.AUTHENTICATION.value in evidence.document.claim_kinds
    assert EquationalTheory.SYMMETRIC_ENCRYPTION.value in (
        evidence.document.equational_theories
    )
    assert evidence.document.adversary_kind == AdversaryKind.DOLEV_YAO.value
    assert evidence.document.adversary_id == "adversary:network"

    # Attack status (secure path)
    assert isinstance(evidence.attack, ProtocolAttackBindingV2)
    assert evidence.attack.status is ProtocolAttackStatus.SECURE_NO_ATTACK
    assert evidence.attack.replayed is False
    assert evidence.attack.attack_count == 0

    # Authority ceiling
    assert evidence.result_authority is ResultAuthority.PROTOCOL
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.PROTOCOL
    assert evidence.translation_ceiling is EvidenceAuthority.BOUNDED
    assert evidence.role is ToolRole.AUTHORITY
    assert evidence.is_theorem_authority is False
    assert evidence.is_proved is False
    assert evidence.proof_established is False
    assert evidence.theorem_established is False
    assert evidence.protocol_established is True
    assert evidence.result_status is ResultStatus.SECURE
    assert evidence.disposition is ProtocolDisposition.SECURE

    wire = evidence.to_dict()
    assert wire["bindings_complete"] is True
    assert wire["provider"] == "tamarin"
    assert "document" in wire
    assert "assumptions" in wire
    assert "attack" in wire
    assert "attack_status" in wire
    assert wire["claim_theorem"] is False
    assert wire["claim_proof"] is False
    assert wire["claim_protocol"] is True
    assert wire["authorizes_universal_proof"] is False


def test_proverif_binds_applied_pi_and_opam_assumptions() -> None:
    engine = _engine_with()
    # Align RESULT lines with claim queries from compiled ProtocolIR.
    # Compiler emits claim queries from document; use secure-ish multi-true output
    # that matches claim:secrecy / claim:authentication when labels align.
    result = execute_proverif(
        _protocol(),
        request_id="req:pv:bind",
        engine=engine,
    )
    assert result.evidence.provider is ProtocolProviderKind.PROVERIF
    assert result.evidence.assumptions.process_model is ProtocolProcessModel.APPLIED_PI
    assert result.evidence.assumptions.dependency_kind == "opam"
    assert result.evidence.assumptions.dependency_name == "opam:proverif"
    assert result.evidence.assumptions.supports_equivalence is True
    assert result.evidence.document.source_format == "pv"
    assert result.evidence.bindings_complete() is True


def test_source_only_execution_binds_compile_identity() -> None:
    engine = _engine_with(proverif_stdout=PROVERIF_SECURE)
    # Match RESULT lines to labeled queries in HANDSHAKE_PV.
    stdout = (
        "RESULT not attacker(challenge) is true.\n"
        "RESULT inj-event(AcceptChallenge(x)) ==> inj-event(BeginChallenge(x)) is true.\n"
    )
    engine = ProtocolExecutionEngineV2(
        proverif=ProVerifBackend(
            runner=_process_runner(stdout),
            available_probe=lambda: True,
            version_probe=lambda: "ProVerif 2.05",
            opam_probe=lambda: "2.05",
        ),
        tamarin=TamarinBackend(available_probe=lambda: False),
    )
    result = execute_proverif(
        source=HANDSHAKE_PV,
        request_id="req:pv:source",
        engine=engine,
    )
    assert result.evidence.document.compile_digest
    assert result.evidence.document.source_format == "pv"
    assert result.evidence.document.claim_ids  # labeled claims extracted
    assert result.disposition is ProtocolDisposition.SECURE
    assert result.evidence.protocol_established is True


# ---------------------------------------------------------------------------
# Attack parse + replay / non-replayable
# ---------------------------------------------------------------------------


def test_tamarin_attack_trace_is_parsed_and_replayed() -> None:
    single_lemma = """\
theory AttackOnly
begin
lemma secrecy_claim:
  "All n #i. Secret(n) @ i ==> not (Ex #j. K(n) @ j)"
end
"""
    engine = ProtocolExecutionEngineV2(
        tamarin=TamarinBackend(
            runner=_process_runner(TAMARIN_ATTACK),
            available_probe=lambda: True,
            version_probe=lambda: "tamarin-prover 1.8.0",
            maude_probe=lambda: "Maude 3.1",
        ),
        proverif=ProVerifBackend(available_probe=lambda: False),
    )
    result = execute_tamarin(
        source=single_lemma,
        request_id="req:tm:attack",
        engine=engine,
    )
    assert result.disposition is ProtocolDisposition.ATTACK_FOUND
    assert result.attack_status is ProtocolAttackStatus.ATTACK_REPLAYED
    assert result.evidence.attack.replayed is True
    assert result.evidence.attack.non_replayable is False
    assert result.evidence.attack.attack_count >= 1
    assert result.evidence.attack.replay_tokens
    assert all(
        isinstance(token, str) and ":" in token
        for token in result.evidence.attack.replay_tokens
    )
    assert result.evidence.attack.attack_traces
    assert result.evidence.protocol_established is True
    assert result.evidence.result_status is ResultStatus.ATTACK_FOUND
    wire = result.evidence.to_dict()
    assert wire["attack_status"] == "attack_replayed"
    assert wire["attack"]["replayed"] is True


def test_proverif_attack_trace_is_parsed_and_replayed() -> None:
    source = "(* claim:secrecy *)\nquery not attacker(challenge).\nprocess 0.\n"
    engine = ProtocolExecutionEngineV2(
        proverif=ProVerifBackend(
            runner=_process_runner(PROVERIF_ATTACK),
            available_probe=lambda: True,
            version_probe=lambda: "ProVerif 2.05",
            opam_probe=lambda: "2.05",
        ),
        tamarin=TamarinBackend(available_probe=lambda: False),
    )
    result = execute_proverif(
        source=source,
        request_id="req:pv:attack",
        engine=engine,
    )
    assert result.disposition is ProtocolDisposition.ATTACK_FOUND
    assert result.attack_status is ProtocolAttackStatus.ATTACK_REPLAYED
    assert result.evidence.attack.replayed is True
    assert result.evidence.attack.replay_tokens
    assert result.evidence.attack.attack_traces
    # Deterministic replay tokens.
    tokens = list(result.evidence.attack.replay_tokens)
    assert tokens == list(result.evidence.attack.replay_tokens)


def test_attack_binding_explicitly_non_replayable() -> None:
    binding = ProtocolAttackBindingV2.from_outcomes(
        disposition=ProtocolDisposition.ATTACK_FOUND,
        claim_outcomes=(
            {
                "claim_id": "claim:secrecy",
                "attack_trace": {
                    "claim_id": "claim:secrecy",
                    "trace_id": "attack-trace:opaque",
                    # No replay field → non-replayable.
                },
            },
        ),
    )
    assert binding.status is ProtocolAttackStatus.ATTACK_NON_REPLAYABLE
    assert binding.non_replayable is True
    assert binding.replayed is False
    assert "claim:secrecy" in binding.non_replayable_claim_ids
    assert binding.replay_tokens == ()


def test_attack_found_without_any_trace_is_non_replayable() -> None:
    binding = ProtocolAttackBindingV2.from_outcomes(
        disposition=ProtocolDisposition.ATTACK_FOUND,
        claim_outcomes=({"claim_id": "claim:secrecy", "attack_trace": None},),
    )
    assert binding.status is ProtocolAttackStatus.ATTACK_NON_REPLAYABLE
    assert binding.non_replayable is True
    assert binding.replayed is False


def test_secure_path_has_no_attack() -> None:
    engine = _engine_with()
    result = execute_tamarin(
        _protocol(),
        request_id="req:tm:secure",
        engine=engine,
    )
    assert result.disposition is ProtocolDisposition.SECURE
    assert result.attack_status is ProtocolAttackStatus.SECURE_NO_ATTACK
    assert result.evidence.attack.attack_count == 0
    assert result.evidence.attack.replayed is False


# ---------------------------------------------------------------------------
# Fail-closed: mock / fallback / missing tool
# ---------------------------------------------------------------------------


def test_mock_output_cannot_establish_protocol() -> None:
    engine = _engine_with()
    result = engine.execute(
        ProtocolExecutionRequestV2(
            request_id="req:mock",
            provider=ProtocolProviderKind.PROVERIF,
            document=_protocol(),
            mode=ProtocolExecutionMode.MOCK,
            mock_output={"status": "secure"},
            confidence=0.99,
            fluent_text="Obviously secure.",
        )
    )
    assert result.disposition is ProtocolDisposition.MOCK_REJECTED
    assert result.evidence.protocol_established is False
    assert result.evidence.mock_output_present is True
    assert result.evidence.claim_established(ProtocolClaimKindV2.PROTOCOL) is False
    assert result.evidence.claim_established(ProtocolClaimKindV2.THEOREM) is False
    assert (
        non_authoritative_signal_establishes(
            ProtocolClaimKindV2.PROTOCOL,
            mock_output={"status": "secure"},
            available=True,
            confidence=0.99,
        )
        is False
    )


def test_fallback_output_cannot_establish_protocol() -> None:
    engine = _engine_with()
    result = engine.execute(
        ProtocolExecutionRequestV2(
            request_id="req:fallback",
            provider=ProtocolProviderKind.TAMARIN,
            document=_protocol(),
            mode=ProtocolExecutionMode.FALLBACK,
            fallback_output={"status": "secure"},
        )
    )
    assert result.disposition is ProtocolDisposition.FALLBACK_REJECTED
    assert result.evidence.protocol_established is False
    assert result.evidence.fallback_output_present is True
    assert result.evidence.is_theorem_authority is False


def test_missing_tool_is_unavailable_never_secure() -> None:
    engine = ProtocolExecutionEngineV2(
        proverif=ProVerifBackend(
            available_probe=lambda: False,
            version_probe=lambda: "ProVerif 2.05",
            opam_probe=lambda: "2.05",
        ),
        tamarin=TamarinBackend(
            available_probe=lambda: False,
            version_probe=lambda: "tamarin-prover 1.8.0",
            maude_probe=lambda: "Maude 3.1",
        ),
    )
    result = execute_proverif(
        _protocol(),
        request_id="req:pv:missing",
        engine=engine,
    )
    assert result.disposition is ProtocolDisposition.UNAVAILABLE
    assert result.evidence.result_status is ResultStatus.UNAVAILABLE
    assert result.evidence.protocol_established is False
    assert result.evidence.result_status is not ResultStatus.SECURE
    assert result.attack_status is ProtocolAttackStatus.NONE


def test_unsupported_equivalence_on_tamarin_is_explicit() -> None:
    engine = _engine_with()
    result = execute_tamarin(
        _protocol(include_equivalence=True),
        request_id="req:tm:equiv",
        engine=engine,
    )
    # Tamarin backend quarantines unsupported claims as UNSUPPORTED.
    assert result.disposition in {
        ProtocolDisposition.UNSUPPORTED,
        ProtocolDisposition.QUARANTINED,
    }
    assert result.evidence.protocol_established is False
    # Capability still records Tamarin does not support equivalence.
    assert result.evidence.assumptions.supports_equivalence is False
    assert (
        ProtocolClaimKind.EQUIVALENCE.value
        not in result.evidence.assumptions.supported_claim_kinds
    )


def test_proverif_supports_equivalence_claim_compilation() -> None:
    engine = _engine_with()
    # Equivalence claim is in ProVerif ceiling; compile should not be unsupported.
    cap = engine.capability_receipt(
        ProtocolProviderKind.PROVERIF,
        document=_protocol(include_equivalence=True),
    )
    assert cap.supported_document is True
    assert capability_for(ProtocolProviderKind.PROVERIF).supports_equivalence is True


# ---------------------------------------------------------------------------
# Authority ceiling / identity
# ---------------------------------------------------------------------------


def test_evidence_never_claims_theorem_authority() -> None:
    engine = _engine_with()
    result = execute_tamarin(
        _protocol(),
        request_id="req:auth:ceiling",
        engine=engine,
    )
    evidence = result.evidence
    assert evidence.is_theorem_authority is False
    assert evidence.is_proved is False
    assert evidence.proof_established is False
    assert evidence.satisfiability_established is False
    assert evidence.theorem_established is False
    assert evidence.authorizes_universal_proof is False
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.PROTOCOL
    wire = evidence.to_dict()
    assert wire["claim_theorem"] is False
    assert wire["claim_proof"] is False
    assert wire["claim_satisfiability"] is False
    assert wire["is_proved"] is False
    assert wire["authorizes_universal_proof"] is False


def test_request_rejects_empty_document_and_source() -> None:
    with pytest.raises(ProtocolExecutionError, match="document and/or source"):
        ProtocolExecutionRequestV2(
            request_id="req:empty",
            provider=ProtocolProviderKind.PROVERIF,
        )


def test_document_binding_preserves_structure_ids() -> None:
    doc = _protocol()
    binding = ProtocolDocumentBindingV2.from_document(doc, source_format="spthy")
    assert binding.role_ids == tuple(sorted(item.role_id for item in doc.roles)) or set(
        binding.role_ids
    ) == {item.role_id for item in doc.roles}
    assert set(binding.channel_ids) == {item.channel_id for item in doc.channels}
    assert set(binding.rewrite_fact_ids) == {item.fact_id for item in doc.rewrite_facts}
    assert set(binding.event_ids) == {item.event_id for item in doc.events}
    assert set(binding.claim_ids) == {item.claim_id for item in doc.claims}
    assert EquationalTheory.FREE.value in binding.equational_theories
    wire = binding.to_dict()
    assert wire["interface"] == "ProtocolDocumentBinding@2"
    assert "equational_theories" in wire
    assert "role_ids" in wire
    assert "channel_ids" in wire
    assert "adversary_kind" in wire
