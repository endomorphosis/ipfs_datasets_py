"""Integration contract for Tamarin and ProVerif protocol backends.

Covers LFV-G047 / LFV-024 acceptance:

* compilers disclose the Dolev-Yao/symbolic-model ceiling, equational theory,
  and claim support;
* tool versions and Maude/opam dependencies bind receipts;
* attack traces normalize and replay;
* disagreement and inconclusive results quarantine;
* missing tools are explicit and never report SECURE.
"""

from __future__ import annotations

import pytest
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.protocol.proverif import (
    PROVERIF_BACKEND_VERSION,
    ProVerifBackend,
    ProVerifCompiler,
    QuarantineReason as ProVerifQuarantineReason,
    classify_claim_outcomes as classify_proverif,
    parse_attack_trace as parse_proverif_attack,
    parse_proverif_claim_outcomes,
)
from ipfs_datasets_py.logic.backends.protocol.tamarin import (
    TAMARIN_BACKEND_VERSION,
    QuarantineReason as TamarinQuarantineReason,
    TamarinBackend,
    TamarinCompiler,
    classify_claim_outcomes as classify_tamarin,
    parse_attack_trace as parse_tamarin_attack,
    parse_tamarin_claim_outcomes,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
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

SOURCE_ID = "source:handshake"
SPAN_ID = "span:protocol"

TAMARIN_SECURE = """\
lemma secrecy_claim: verified (all-traces)
lemma auth_claim: verified (all-traces)
"""

TAMARIN_ATTACK = """\
lemma secrecy_claim: falsified - found trace
rule Create_Initiator(~id)
rule Event_BeginChallenge(~n)
rule Event_AcceptChallenge(~n)
"""

TAMARIN_DISAGREE = """\
lemma secrecy_claim: verified (all-traces)
lemma auth_claim: falsified - found trace
rule Event_AcceptChallenge(x)
"""

TAMARIN_INCOMPLETE = """\
lemma secrecy_claim: analysis incomplete
lemma auth_claim: verified (all-traces)
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

PROVERIF_DISAGREE = """\
RESULT not attacker(challenge[]) is true.
RESULT event(AcceptChallenge(x)) ==> event(BeginChallenge(x)) is false.
-> event AcceptChallenge(x)
"""

PROVERIF_CANNOT = """\
RESULT not attacker(challenge[]) cannot be proved.
"""

HANDSHAKE_SPTHY = """\
theory Handshake
begin

builtins: symmetric-encryption, hashing

lemma secrecy_claim:
  "All n #i. Secret(n) @ i ==> not (Ex #j. K(n) @ j)"

lemma auth_claim:
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


def _request(
    *,
    backend_id: str,
    payload: dict,
    family: str = "cryptographic_protocol",
) -> BackendRequest:
    return BackendRequest(
        request_id="request:protocol:test",
        claim_id="claim:protocol:test",
        declaration_id="declaration:protocol:test",
        claim_digest="1" * 64,
        obligation_id="obligation:protocol:test",
        obligation_digest="2" * 64,
        assumption_ids=("assumption:reviewed",),
        logic_family=family,
        query_kind=QueryKind.THEOREM_PROOF,
        bounds=ExecutionBounds(timeout_ms=250, max_steps=20),
        payload=FrozenMap(payload),
        requested_backend_id=backend_id,
    )


def _process_runner(
    stdout: str,
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    unavailable: bool = False,
    expected_suffix: str = "",
) -> tuple[BoundedToolRunner, list[object]]:
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        if expected_suffix and hasattr(invocation, "input_files"):
            written = list(invocation.input_files.values())
            assert written, "expected compiled source in workspace inputs"
            content = written[0]
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            assert expected_suffix in content
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout,
            elapsed_seconds=0.013,
            timed_out=timed_out,
            process_tree_terminated=timed_out,
            error="executable not found" if unavailable else "",
        )

    return BoundedToolRunner(executor=execute), invocations


def test_tamarin_compiler_discloses_ceiling_theory_and_claim_support():
    protocol = _protocol()
    compiler = TamarinCompiler()
    compiled = compiler.compile_protocol(protocol)

    ceiling = compiled.ceiling.to_dict()
    assert ceiling["adversary_model"] == "dolev_yao"
    assert ceiling["perfect_cryptography"] is True
    assert ceiling["computational_soundness"] is False
    assert EquationalTheory.SYMMETRIC_ENCRYPTION.value in ceiling["equational_theories"]
    assert ProtocolClaimKind.SECRECY.value in ceiling["supported_claim_kinds"]
    assert ProtocolClaimKind.EQUIVALENCE.value not in ceiling["supported_claim_kinds"]
    assert "claim:secrecy" in compiled.claim_lemmas.to_dict()
    assert "theory challenge_response" in compiled.source or "theory" in compiled.source
    assert "symbolic-model-ceiling" in compiled.source
    assert compiled.protocol_document_id == protocol.document_id


def test_proverif_compiler_discloses_ceiling_and_supports_equivalence():
    protocol = _protocol(include_equivalence=True)
    compiler = ProVerifCompiler()
    compiled = compiler.compile_protocol(protocol)

    ceiling = compiled.ceiling.to_dict()
    assert ceiling["adversary_model"] == "dolev_yao"
    assert ceiling["tool"] == "proverif"
    assert ProtocolClaimKind.EQUIVALENCE.value in ceiling["supported_claim_kinds"]
    assert "claim:equivalence" in compiled.claim_queries.to_dict()
    assert "(* claim:claim:secrecy *)" in compiled.source or "claim:secrecy" in compiled.source
    assert "query" in compiled.source
    assert EquationalTheory.SYMMETRIC_ENCRYPTION.value in compiled.equational_theories


def test_tamarin_missing_tool_is_explicit_unavailable_never_secure():
    runner, _ = _process_runner("", unavailable=True)
    backend = TamarinBackend(
        runner=runner,
        available_probe=lambda: False,
        version_probe=lambda: "tamarin-prover 1.8.0",
        maude_probe=lambda: "Maude 3.1",
    )
    request = _request(
        backend_id="tamarin",
        payload={"encoding": "spthy", "source": HANDSHAKE_SPTHY},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.result.authority is ResultAuthority.PROTOCOL
    assert outcome.receipt.accepted is False
    assert "not available" in outcome.result.reason
    assert outcome.result.status is not ResultStatus.SECURE


def test_proverif_missing_tool_is_explicit_unavailable():
    backend = ProVerifBackend(
        available_probe=lambda: False,
        version_probe=lambda: "ProVerif 2.05",
        opam_probe=lambda: "2.05",
    )
    request = _request(
        backend_id="proverif",
        payload={"encoding": "pv", "source": HANDSHAKE_PV},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.receipt.toolchain.dependencies[0].name.startswith("opam:")
    assert outcome.receipt.accepted is False


def test_tamarin_secure_run_binds_maude_version_and_ceiling():
    runner, invocations = _process_runner(
        TAMARIN_SECURE, expected_suffix="lemma secrecy_claim"
    )
    backend = TamarinBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "tamarin-prover 1.8.0",
        maude_probe=lambda: "Maude 3.1",
        backend_version="1.8.0",
    )
    request = _request(
        backend_id="tamarin",
        payload={"encoding": "spthy", "source": HANDSHAKE_SPTHY},
    )
    outcome = backend.run(request)

    assert outcome.result.status is ResultStatus.SECURE
    assert outcome.receipt.accepted is True
    assert outcome.interface_version == TAMARIN_BACKEND_VERSION
    toolchain = outcome.receipt.toolchain.to_dict()
    assert toolchain["tool_version"] == "tamarin-prover 1.8.0"
    assert toolchain["dependencies"][0]["name"] == "maude"
    assert toolchain["dependencies"][0]["version"] == "Maude 3.1"
    assert outcome.receipt.ceiling.to_dict()["adversary_model"] == "dolev_yao"
    assert invocations, "expected Tamarin invocation"


def test_proverif_secure_run_binds_opam_dependency():
    # Align RESULT text with labeled queries extracted from HANDSHAKE_PV.
    stdout = (
        "RESULT not attacker(challenge) is true.\n"
        "RESULT inj-event(AcceptChallenge(x)) ==> inj-event(BeginChallenge(x)) is true.\n"
    )
    runner, _ = _process_runner(stdout, expected_suffix="query")
    backend = ProVerifBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "ProVerif 2.05",
        opam_probe=lambda: "2.05",
        backend_version="2.05",
    )
    request = _request(
        backend_id="proverif",
        payload={"encoding": "pv", "source": HANDSHAKE_PV},
    )
    outcome = backend.run(request)

    assert outcome.result.status is ResultStatus.SECURE
    assert outcome.receipt.accepted is True
    assert outcome.interface_version == PROVERIF_BACKEND_VERSION
    dep = outcome.receipt.toolchain.dependencies[0]
    assert dep.name == "opam:proverif"
    assert dep.version == "2.05"
    assert outcome.receipt.ceiling.to_dict()["tool"] == "proverif"


def test_tamarin_attack_trace_normalizes_and_replays():
    single_lemma = """\
theory AttackOnly
begin
lemma secrecy_claim:
  "All n #i. Secret(n) @ i ==> not (Ex #j. K(n) @ j)"
end
"""
    runner, _ = _process_runner(TAMARIN_ATTACK)
    backend = TamarinBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "tamarin-prover 1.8.0",
        maude_probe=lambda: "Maude 3.1",
    )
    request = _request(
        backend_id="tamarin",
        payload={"encoding": "spthy", "source": single_lemma},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.ATTACK_FOUND
    assert outcome.receipt.accepted is False
    attacks = outcome.result.witness.to_dict()["attack_traces"]
    assert attacks
    replay = outcome.result.witness.to_dict()["attack_trace_replay"]
    assert replay and all(isinstance(token, str) for token in replay[0])
    # Direct parse API also replays deterministically.
    trace = parse_tamarin_attack(TAMARIN_ATTACK, claim_id="claim:secrecy")
    assert trace is not None
    assert trace.replay() == tuple(step.replay_token() for step in trace.steps)
    assert trace.replay()[0].startswith("0:")


def test_proverif_attack_trace_normalizes_and_replays():
    runner, _ = _process_runner(PROVERIF_ATTACK)
    backend = ProVerifBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "ProVerif 2.05",
        opam_probe=lambda: "2.05",
    )
    # Single secrecy query so false RESULT maps cleanly.
    source = "(* claim:secrecy *)\nquery not attacker(challenge).\nprocess 0.\n"
    request = _request(
        backend_id="proverif",
        payload={"encoding": "pv", "source": source},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.ATTACK_FOUND
    attacks = outcome.result.witness.to_dict()["attack_traces"]
    assert attacks
    assert outcome.result.witness.to_dict()["attack_trace_replay"]
    trace = parse_proverif_attack(PROVERIF_ATTACK, claim_id="claim:secrecy")
    assert trace is not None
    assert list(trace.replay()) == list(trace.to_dict()["replay"])


def test_tamarin_disagreement_is_quarantined():
    runner, _ = _process_runner(TAMARIN_DISAGREE)
    backend = TamarinBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "tamarin-prover 1.8.0",
        maude_probe=lambda: "Maude 3.1",
    )
    request = _request(
        backend_id="tamarin",
        payload={"encoding": "spthy", "source": HANDSHAKE_SPTHY},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.UNKNOWN
    assert outcome.receipt.quarantine is not None
    assert outcome.receipt.quarantine.reason is TamarinQuarantineReason.DISAGREEMENT
    assert outcome.receipt.accepted is False
    assert "quarantine" in outcome.result.witness.to_dict()


def test_proverif_disagreement_is_quarantined():
    runner, _ = _process_runner(PROVERIF_DISAGREE)
    backend = ProVerifBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "ProVerif 2.05",
        opam_probe=lambda: "2.05",
    )
    request = _request(
        backend_id="proverif",
        payload={"encoding": "pv", "source": HANDSHAKE_PV},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.UNKNOWN
    assert outcome.receipt.quarantine is not None
    assert (
        outcome.receipt.quarantine.reason is ProVerifQuarantineReason.DISAGREEMENT
    )


def test_tamarin_inconclusive_is_quarantined():
    runner, _ = _process_runner(TAMARIN_INCOMPLETE)
    backend = TamarinBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "tamarin-prover 1.8.0",
        maude_probe=lambda: "Maude 3.1",
    )
    request = _request(
        backend_id="tamarin",
        payload={"encoding": "spthy", "source": HANDSHAKE_SPTHY},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.UNKNOWN
    assert outcome.receipt.quarantine is not None
    assert outcome.receipt.quarantine.reason is TamarinQuarantineReason.INCONCLUSIVE


def test_proverif_cannot_prove_is_quarantined():
    runner, _ = _process_runner(PROVERIF_CANNOT)
    backend = ProVerifBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "ProVerif 2.05",
        opam_probe=lambda: "2.05",
    )
    source = "(* claim:secrecy *)\nquery not attacker(challenge).\nprocess 0.\n"
    request = _request(
        backend_id="proverif",
        payload={"encoding": "pv", "source": source},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.UNKNOWN
    assert outcome.receipt.quarantine is not None
    assert (
        outcome.receipt.quarantine.reason is ProVerifQuarantineReason.INCONCLUSIVE
    )


def test_protocol_ir_end_to_end_tamarin_and_proverif():
    protocol = _protocol()
    t_compiled = TamarinCompiler().compile_protocol(protocol)
    t_stdout = "\n".join(
        f"lemma {lemma}: verified"
        for lemma in t_compiled.claim_lemmas.to_dict().values()
    ) + "\n"
    tamarin_runner, t_inv = _process_runner(
        t_stdout,
        expected_suffix="symbolic-model-ceiling",
    )
    tamarin = TamarinBackend(
        runner=tamarin_runner,
        available_probe=lambda: True,
        version_probe=lambda: "tamarin-prover 1.8.0",
        maude_probe=lambda: "Maude 3.1",
    )
    t_request = _request(
        backend_id="tamarin",
        payload={
            "encoding": "protocol-ir",
            "protocol_ir": protocol.to_dict(),
        },
    )
    t_outcome = tamarin.run(t_request)
    assert t_outcome.compile_result.protocol_document_id == protocol.document_id
    assert t_outcome.result.status is ResultStatus.SECURE
    assert t_inv

    # Compile once to learn exact query texts for RESULT matching.
    compiled = ProVerifCompiler().compile_protocol(protocol)
    proverif_stdout_lines = [
        f"RESULT {query} is true."
        for query in compiled.claim_queries.to_dict().values()
    ]
    p_runner, p_inv = _process_runner(
        "\n".join(proverif_stdout_lines) + "\n",
        expected_suffix="Dolev-Yao",
    )
    proverif = ProVerifBackend(
        runner=p_runner,
        available_probe=lambda: True,
        version_probe=lambda: "ProVerif 2.05",
        opam_probe=lambda: "2.05",
    )
    p_request = _request(
        backend_id="proverif",
        payload={
            "encoding": "protocol-ir",
            "protocol_ir": protocol.to_dict(),
        },
    )
    p_outcome = proverif.run(p_request)
    assert p_outcome.compile_result.protocol_document_id == protocol.document_id
    assert p_outcome.result.status is ResultStatus.SECURE
    assert p_inv


def test_parse_helpers_and_classifiers_are_deterministic():
    t_outcomes = parse_tamarin_claim_outcomes(
        TAMARIN_SECURE,
        "",
        claim_lemmas={
            "claim:secrecy": "secrecy_claim",
            "claim:auth": "auth_claim",
        },
    )
    status, quarantine, accepted = classify_tamarin(t_outcomes)
    assert status is ResultStatus.SECURE
    assert quarantine is None
    assert accepted is True

    p_outcomes = parse_proverif_claim_outcomes(
        PROVERIF_SECURE,
        "",
        claim_queries={
            "claim:secrecy": "not attacker(challenge[])",
            "claim:auth": (
                "inj-event(AcceptChallenge(x)) ==> inj-event(BeginChallenge(x))"
            ),
        },
    )
    status, quarantine, accepted = classify_proverif(p_outcomes)
    assert status is ResultStatus.SECURE
    assert quarantine is None
    assert accepted is True


def test_timeout_never_reports_secure():
    runner, _ = _process_runner("", timed_out=True)
    backend = TamarinBackend(
        runner=runner,
        available_probe=lambda: True,
        version_probe=lambda: "tamarin-prover 1.8.0",
        maude_probe=lambda: "Maude 3.1",
    )
    request = _request(
        backend_id="tamarin",
        payload={"encoding": "spthy", "source": HANDSHAKE_SPTHY},
    )
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.TIMEOUT
    assert outcome.receipt.accepted is False
    assert outcome.result.status is not ResultStatus.SECURE
