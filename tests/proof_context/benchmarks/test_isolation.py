"""PCCE-074 benchmark and provider-disclosure isolation tests."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from typing import Any

import pytest

# isort: split

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_obj
from ipfs_datasets_py.proof_context.benchmarks import isolation
from ipfs_datasets_py.proof_context.benchmarks.isolation import (
    AgentAccessGraph,
    ArtifactGrant,
    BenchmarkIsolationSession,
    EvaluationScore,
    EvaluatorAccessGraph,
    IsolationDenial,
    IsolationError,
    ProviderPayloadManifest,
    TerminalProposal,
    build_agent_access_graph,
    build_evaluator_access_graph,
    isolation_descriptor,
    isolation_descriptor_cid,
)

TASK_ID = "PCCE-074-fixture"
BASE_COMMIT = "1" * 40
BASE_TREE = "2" * 40
BASELINE_PATH = "src/pkg/core.py"
PUBLIC_TEST_PATH = "tests/test_core.py"
HIDDEN_PATH = "hidden/test_core_hidden.py"
ANSWER_PATH = "answers/expected.patch"
NEGATIVE_PATH = "review/negative.txt"
ASSURANCE_PATH = "assurance/mutant.json"

BASELINE_BYTES = b"def visible(value):\n    return value + 1\n"
PUBLIC_TEST_BYTES = b"def test_visible():\n    assert True\n"
HIDDEN_BYTES = b"hidden-check-body: expected behavior must remain confidential\n"
ANSWER_BYTES = b"historical-answer-body: never enter an agent or provider payload\n"
NEGATIVE_BYTES = b"negative-review-body: autonomous acceptance is forbidden\n"
ASSURANCE_BYTES = b'{"mutant":"hidden-assurance-outcome","survived":false}\n'

DESCRIPTOR_CID = "baguqeera5ifpsadums6lrug6jcoi34hsvj7rhq4gv2xoordagmsvtbzr3cta"
AGENT_GRAPH_CID = "baguqeera6mlkkidlacu32zlrudxx24z5t6mbcimltabihlu5vmliyfplamya"
EVALUATOR_GRAPH_CID = "baguqeeraz2ptwatgtxwe5pj46npjjse3bpakfdgqvo5f7ztuaw6a5apgu64a"
PROVIDER_PAYLOAD_CID = "baguqeeragr7sku3go5albbwt7k3hxjdwwwphevcd2ehec3lwk6rlac46h74q"
TERMINAL_PROPOSAL_CID = "baguqeeral5pmhkqh3ffgyjyezhfhnbge6sgniv3dmqbgqikd3evyoc36wgbq"
EVALUATION_SCORE_CID = "baguqeeraukhpdfgyd7ve3ndxqozdp6mx7ebdrjh65w4klf7wivo46uijqkpa"
DAG_PB_FUTURE_CID = "bafybeihlwppiupm2ia3gcmxllxvvv5cojslmcfuw7d6dj2rmdwf5qomroe"


@dataclass(frozen=True)
class Fixture:
    agent_root: Path
    evaluator_root: Path
    agent_graph: AgentAccessGraph
    evaluator_graph: EvaluatorAccessGraph


def _write(root: Path, relative_path: str, payload: bytes) -> None:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _agent_graph(
    *, objective: str = "Repair visible behavior within the declared scope."
) -> AgentAccessGraph:
    return build_agent_access_graph(
        task_id=TASK_ID,
        baseline_commit=BASE_COMMIT,
        baseline_tree=BASE_TREE,
        objective=objective,
        owned_paths=(BASELINE_PATH,),
        baseline_files=((BASELINE_PATH, BASELINE_BYTES),),
        public_tests=((PUBLIC_TEST_PATH, PUBLIC_TEST_BYTES),),
    )


def _evaluator_graph(agent_graph: AgentAccessGraph) -> EvaluatorAccessGraph:
    return build_evaluator_access_graph(
        task_id=TASK_ID,
        agent_graph=agent_graph,
        hidden_tests=((HIDDEN_PATH, HIDDEN_BYTES),),
        historical_answers=((ANSWER_PATH, ANSWER_BYTES),),
        negative_reviews=((NEGATIVE_PATH, NEGATIVE_BYTES),),
        assurance_data=((ASSURANCE_PATH, ASSURANCE_BYTES),),
    )


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    agent_root = tmp_path / "agent"
    evaluator_root = tmp_path / "evaluator"
    agent_root.mkdir()
    evaluator_root.mkdir()
    for path, payload in (
        (BASELINE_PATH, BASELINE_BYTES),
        (PUBLIC_TEST_PATH, PUBLIC_TEST_BYTES),
    ):
        _write(agent_root, path, payload)
    for path, payload in (
        (HIDDEN_PATH, HIDDEN_BYTES),
        (ANSWER_PATH, ANSWER_BYTES),
        (NEGATIVE_PATH, NEGATIVE_BYTES),
        (ASSURANCE_PATH, ASSURANCE_BYTES),
    ):
        _write(evaluator_root, path, payload)
    agent_graph = _agent_graph()
    return Fixture(
        agent_root=agent_root,
        evaluator_root=evaluator_root,
        agent_graph=agent_graph,
        evaluator_graph=_evaluator_graph(agent_graph),
    )


def _payload(session: BenchmarkIsolationSession) -> ProviderPayloadManifest:
    return session.build_provider_payload()


def _proposal(
    graph: AgentAccessGraph,
    payload: ProviderPayloadManifest,
    *,
    proposal_id: str = "proposal-0001",
    status: str = "proposed",
    patch: bytes | None = b"diff --git opaque\n",
) -> TerminalProposal:
    return TerminalProposal(
        proposal_id=proposal_id,
        task_id=graph.task_id,
        agent_access_graph_cid=graph.cid,
        provider_payload_cid=payload.cid,
        terminal_status=status,
        patch_cid=cid_for_bytes(patch) if patch is not None else None,
    )


def _score_all(material: Any) -> list[bool]:
    handles = material.handles()
    bodies = [material.read(handle.artifact_id, handle.content_cid) for handle in handles]
    return [bool(body) for body in bodies]


def _implementation_traceback_locals(error: BaseException) -> str:
    values: list[str] = []
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_globals.get("__name__") == isolation.__name__:
            values.extend(f"{name}={value!r}" for name, value in frame.f_locals.items())
        traceback = traceback.tb_next
    return "\n".join(values)


def test_cold_descriptor_is_truthful_closed_and_stable() -> None:
    descriptor = isolation_descriptor()
    assert descriptor["runtime_integration_status"] == "not_integrated"
    assert descriptor["enforcement_disposition"] == "observed_tested_limited"
    assert descriptor["qualification_credit"] is False
    assert descriptor["provider_call_authority"] is False
    assert descriptor["live_benchmark_authority"] is False
    assert descriptor["filename_only_access_authority"] is False
    assert descriptor["future_ref_access_authority"] is False
    assert descriptor["controls"] == ["PC-074"]
    assert set(descriptor["threats"]) == {"TH-001", "TH-007", "TH-010", "TH-011"}
    assert descriptor["evaluator_mount_time"] == "after-exact-terminal-proposal"
    assert "normalized-hidden-fragment-overlap" in descriptor["objective_screening"]
    assert "mixed-script-provider-redaction" in descriptor["objective_screening"]
    assert (
        "evaluator-admission-private-path-and-name-screening" in descriptor["objective_screening"]
    )
    assert "evaluator-access-graph-cid-anchor" in descriptor["session_identity_controls"]
    assert "factory-only-evaluator-graph-construction" in descriptor["session_identity_controls"]
    assert "pre-session-agent-admission-denial" in descriptor["session_identity_controls"]
    assert "opaque-material-bound-admission-attempt-cids" in descriptor["session_identity_controls"]
    assert (
        "closed-denial-reason-without-private-exception-chain"
        in descriptor["session_identity_controls"]
    )
    assert isolation_descriptor_cid() == cid_for_obj(descriptor)
    assert isolation_descriptor_cid() == DESCRIPTOR_CID
    assert not any(name.startswith(("run_provider", "run_benchmark")) for name in isolation.__all__)


def test_access_graphs_are_separate_immutable_and_exactly_identified() -> None:
    agent = _agent_graph()
    evaluator = _evaluator_graph(agent)
    assert agent.cid == cid_for_obj(agent.to_mapping())
    assert agent.cid == AGENT_GRAPH_CID
    assert evaluator.cid == EVALUATOR_GRAPH_CID
    assert evaluator.agent_access_graph_cid == agent.cid
    assert "sealed_evaluator" not in agent.to_mapping()
    assert {grant.kind for grant in agent.grants} == {"baseline", "public_test"}
    assert "hidden" not in repr(evaluator).casefold()
    assert HIDDEN_PATH not in repr(evaluator)
    assert evaluator.cid not in repr(evaluator)
    with pytest.raises(IsolationError, match="serialization") as private:
        evaluator.to_mapping()
    assert private.value.reason == "serialization_forbidden"
    with pytest.raises(FrozenInstanceError):
        agent.task_id = "mutated"  # type: ignore[misc]
    detached = agent.to_mapping()
    detached["owned_paths"].append("stolen/path.py")
    assert agent.owned_paths == (BASELINE_PATH,)


def test_evaluator_graph_cannot_be_constructed_outside_hidden_body_factory() -> None:
    agent = _agent_graph()
    evaluator = _evaluator_graph(agent)
    with pytest.raises(IsolationError) as direct:
        EvaluatorAccessGraph(
            task_id=agent.task_id,
            agent_access_graph_cid=agent.cid,
            _grants=evaluator._grants,
        )
    assert direct.value.reason == "invalid_record"

    leaked_agent = _agent_graph(objective="WINNING PATCH MARKER 834729")
    with pytest.raises(IsolationError) as body_alias:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=leaked_agent,
            hidden_tests=((HIDDEN_PATH, b"WINNING PATCH MARKER 834729"),),
        )
    assert body_alias.value.reason == "content_alias"


def test_access_graph_builders_are_permutation_stable_and_direct_order_is_canonical() -> None:
    graph_kwargs = {
        "task_id": TASK_ID,
        "baseline_commit": BASE_COMMIT,
        "baseline_tree": BASE_TREE,
        "objective": "Repair visible behavior within the declared scope.",
    }
    first = build_agent_access_graph(
        **graph_kwargs,
        owned_paths=("src/b.py", "src/a.py"),
        baseline_files=(("src/b.py", b"b"), ("src/a.py", b"a")),
        public_tests=(("tests/z.py", b"z"), ("tests/y.py", b"y")),
    )
    second = build_agent_access_graph(
        **graph_kwargs,
        owned_paths=("src/a.py", "src/b.py"),
        baseline_files=(("src/a.py", b"a"), ("src/b.py", b"b")),
        public_tests=(("tests/y.py", b"y"), ("tests/z.py", b"z")),
    )
    assert first.to_mapping() == second.to_mapping()
    assert first.cid == second.cid

    baseline = next(grant for grant in first.grants if grant.kind == "baseline")
    public = next(grant for grant in first.grants if grant.kind == "public_test")
    noncanonical = (
        ArtifactGrant(
            artifact_id="artifact-0000",
            kind=public.kind,
            relative_path=public.relative_path,
            content_cid=public.content_cid,
            byte_count=public.byte_count,
        ),
        ArtifactGrant(
            artifact_id="artifact-0001",
            kind=baseline.kind,
            relative_path=baseline.relative_path,
            content_cid=baseline.content_cid,
            byte_count=baseline.byte_count,
        ),
    )
    with pytest.raises(IsolationError) as rejected:
        AgentAccessGraph(
            task_id=first.task_id,
            baseline_commit=first.baseline_commit,
            baseline_tree=first.baseline_tree,
            objective=first.objective,
            owned_paths=first.owned_paths,
            grants=noncanonical,
        )
    assert rejected.value.reason == "invalid_record"


def test_agent_reads_require_opaque_grant_and_exact_cid_not_filename(
    fixture: Fixture,
) -> None:
    baseline = next(grant for grant in fixture.agent_graph.grants if grant.kind == "baseline")
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        assert session.read_agent_artifact(baseline.artifact_id, baseline.content_cid) == (
            BASELINE_BYTES
        )
        for guessed_name in (BASELINE_PATH, Path(BASELINE_PATH).name, "core"):
            with pytest.raises(IsolationError) as denied:
                session.read_agent_artifact(guessed_name, baseline.content_cid)
            assert denied.value.reason == "unknown_grant"
        with pytest.raises(IsolationError) as mismatched:
            session.read_agent_artifact(baseline.artifact_id, cid_for_bytes(b"other"))
        assert mismatched.value.reason == "grant_identity_mismatch"
        serialized = "".join(event.to_json() for event in session.denials())
        assert BASELINE_PATH not in serialized
        assert Path(BASELINE_PATH).name not in serialized
        assert "other" not in serialized


def test_evaluator_is_sealed_until_exact_terminal_proposal(fixture: Fixture) -> None:
    called = False

    def scorer(_material: Any) -> list[bool]:
        nonlocal called
        called = True
        return [True]

    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(fixture.agent_graph, payload)
        with pytest.raises(IsolationError) as sealed:
            session.score(proposal, scorer)
        assert sealed.value.reason == "evaluator_sealed"
        assert called is False
        assert session.phase == "proposal_open"


def test_post_proposal_scoring_is_one_way_aggregate_and_body_free(fixture: Fixture) -> None:
    retained: list[Any] = []

    def scorer(material: Any) -> list[bool]:
        retained.append(material)
        handles = material.handles()
        assert {handle.kind for handle in handles} == {
            "hidden_test",
            "historical_answer",
            "negative_review",
            "assurance_data",
        }
        assert all("/" not in handle.artifact_id for handle in handles)
        bodies = [material.read(handle.artifact_id, handle.content_cid) for handle in handles]
        assert set(bodies) == {
            HIDDEN_BYTES,
            ANSWER_BYTES,
            NEGATIVE_BYTES,
            ASSURANCE_BYTES,
        }
        return [True, True, False, True]

    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(fixture.agent_graph, payload)
        session.close_proposal(proposal)
        assert session.phase == "proposal_closed"
        score = session.score(proposal, scorer)
        assert session.phase == "evaluated"
        assert score.status == "scored_failures"
        assert score.evaluated_artifact_count == 4
        assert score.passed_check_count == 3
        assert score.failed_check_count == 1
        assert proposal.cid == TERMINAL_PROPOSAL_CID
        assert score.cid == EVALUATION_SCORE_CID
        assert EvaluationScore.from_json(score.to_json()) == score
        serialized = score.to_json()
        for forbidden in (
            HIDDEN_PATH,
            ANSWER_PATH,
            NEGATIVE_PATH,
            ASSURANCE_PATH,
            HIDDEN_BYTES.decode().strip(),
            ANSWER_BYTES.decode().strip(),
            fixture.evaluator_graph.cid,
        ):
            assert forbidden not in serialized
        with pytest.raises(IsolationError) as expired:
            retained[0].handles()
        assert expired.value.reason == "closed"
        with pytest.raises(IsolationError) as repeated:
            session.score(proposal, _score_all)
        assert repeated.value.reason == "evaluation_already_terminal"
        with pytest.raises(IsolationError):
            session.build_provider_payload()


def test_provider_manifest_is_visible_only_bounded_redacted_and_policy_specific(
    fixture: Fixture,
) -> None:
    secret_objective = (
        f"Repair {BASELINE_PATH} with OPENAI_API_KEY=supersecretvalue and keep scope exact."
    )
    agent = _agent_graph(objective=secret_objective)
    evaluator = _evaluator_graph(agent)
    with BenchmarkIsolationSession(
        agent_graph=agent,
        evaluator_graph=evaluator,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = session.build_provider_payload()
    assert payload.objective_preview == "[redacted]"
    assert payload.redaction_applied is True
    assert payload.body_bytes_included is False
    assert payload.filename_metadata_included is False
    assert payload.evaluator_identity_included is False
    assert payload.provider_call_authority is False
    assert payload.live_benchmark_authority is False
    assert len(payload.to_json().encode("utf-8")) <= isolation.MAX_PROVIDER_PAYLOAD_BYTES
    serialized = payload.to_json()
    assert {item.content_cid for item in payload.artifacts} == {
        grant.content_cid for grant in agent.grants
    }
    for forbidden in (
        BASELINE_PATH,
        PUBLIC_TEST_PATH,
        Path(BASELINE_PATH).name,
        Path(PUBLIC_TEST_PATH).name,
        "supersecretvalue",
        evaluator.cid,
        HIDDEN_PATH,
        ANSWER_PATH,
        HIDDEN_BYTES.decode().strip(),
        ANSWER_BYTES.decode().strip(),
    ):
        assert forbidden not in serialized
    assert ProviderPayloadManifest.from_json(serialized) == payload


def test_provider_denial_discards_exception_context_and_hidden_traceback_locals(
    fixture: Fixture,
) -> None:
    oversized_objective = "Repair visible behavior. " + "z" * (
        isolation.MAX_PROVIDER_OBJECTIVE_BYTES + 1
    )
    agent = _agent_graph(objective=oversized_objective)
    evaluator = _evaluator_graph(agent)
    with BenchmarkIsolationSession(
        agent_graph=agent,
        evaluator_graph=evaluator,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        with pytest.raises(IsolationError) as rejected:
            session.build_provider_payload()
        assert rejected.value.reason == "payload_overflow"
        assert rejected.value.__context__ is None
        assert rejected.value.__cause__ is None
        implementation_locals = _implementation_traceback_locals(rejected.value)
        for forbidden in (
            HIDDEN_PATH,
            ANSWER_PATH,
            NEGATIVE_PATH,
            ASSURANCE_PATH,
            evaluator.cid,
            *(grant.content_cid for grant in evaluator._grants),
        ):
            assert forbidden not in implementation_locals
        assert session.denials()[-1].reason == "payload_overflow"
        assert session.denials()[-1].stage == "provider_payload"


@pytest.mark.parametrize(
    "secret_objective",
    (
        "Use OPENAI_API_KEY supersecretvalue for the request.",
        "Use API KEY supersecretvalue for the request.",
        "Use api.key=supersecretvalue for the request.",
        "Use API-KEY=supersecretvalue for the request.",
        "Use API_KEY=supersecretvalue for the request.",
        "Use APIKEY=supersecretvalue for the request.",
        "Use API\tKEY=supersecretvalue for the request.",
        "Use API\nKEY=supersecretvalue for the request.",
        "Use API\r\nKEY=supersecretvalue for the request.",
        "Use API\N{NO-BREAK SPACE}KEY=supersecretvalue for the request.",
        "Use API\N{FULLWIDTH FULL STOP}KEY=supersecretvalue for the request.",
        "Use API\N{ZERO WIDTH SPACE}KEY=supersecretvalue for the request.",
        "Use api:key=supersecretvalue for the request.",
        "Use API\N{HYPHEN}KEY=supersecretvalue for the request.",
        "Use API\N{DIVISION SLASH}KEY=supersecretvalue for the request.",
        "Use API\N{BULLET}KEY=supersecretvalue for the request.",
        "Use API|KEY=supersecretvalue for the request.",
        "Use API\N{COMBINING GRAPHEME JOINER}KEY=supersecretvalue for the request.",
        "Use API\N{VARIATION SELECTOR-16}KEY=supersecretvalue for the request.",
        "Use \N{CYRILLIC CAPITAL LETTER A}PI KEY=supersecretvalue for the request.",
        "Use \N{GREEK CAPITAL LETTER ALPHA}PI KEY=supersecretvalue for the request.",
        "Use \N{LATIN CAPITAL LETTER A WITH ACUTE}PI KEY=supersecretvalue for the request.",
        "Use AP\N{GREEK CAPITAL LETTER IOTA} KEY=supersecretvalue for the request.",
        "Use API K\N{GREEK CAPITAL LETTER EPSILON}Y=supersecretvalue for the request.",
        "Use APӀ KEY=supersecretvalue for the request.",
        "Use PASѕԜORD=supersecretvalue for the request.",
        "Authorization is Basic dXNlcjpwYXNz for this request.",
        "The credential supersecretvalue must stay private.",
        "The client secret supersecretvalue must stay private.",
    ),
)
def test_provider_redacts_broader_bounded_secret_syntax(
    fixture: Fixture,
    secret_objective: str,
) -> None:
    agent = _agent_graph(objective=secret_objective)
    evaluator = _evaluator_graph(agent)
    with BenchmarkIsolationSession(
        agent_graph=agent,
        evaluator_graph=evaluator,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = session.build_provider_payload()
    assert payload.objective_preview == "[redacted]"
    assert payload.redaction_applied is True
    assert "supersecretvalue" not in payload.to_json()
    assert "dXNlcjpwYXNz" not in payload.to_json()


def test_non_nfc_combining_secret_spelling_is_rejected_before_projection() -> None:
    with pytest.raises(IsolationError) as rejected:
        _agent_graph(
            objective="Use A\N{COMBINING ACUTE ACCENT}PI KEY=supersecretvalue for the request."
        )
    assert rejected.value.reason == "invalid_record"


def test_provider_objective_without_sensitive_metadata_remains_visible(fixture: Fixture) -> None:
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = session.build_provider_payload()
    assert payload.objective_preview == fixture.agent_graph.objective
    assert payload.redaction_applied is False
    assert payload.cid == PROVIDER_PAYLOAD_CID


@pytest.mark.parametrize(
    "objective",
    (
        "The API client handles key rotation through a separately governed service.",
        "Preserve the visible colon and Unicode punctuation in public output.",
    ),
)
def test_secret_label_normalization_does_not_join_unrelated_words(
    fixture: Fixture,
    objective: str,
) -> None:
    agent = _agent_graph(objective=objective)
    evaluator = _evaluator_graph(agent)
    with BenchmarkIsolationSession(
        agent_graph=agent,
        evaluator_graph=evaluator,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = session.build_provider_payload()
    assert payload.objective_preview == objective
    assert payload.redaction_applied is False


def test_short_hidden_name_has_token_exact_protection_without_substring_false_denial(
    fixture: Fixture,
) -> None:
    hidden_path = "x"
    hidden_body = b"opaque evaluator material 8542\n"
    _write(fixture.evaluator_root, hidden_path, hidden_body)

    clean_agent = _agent_graph()
    clean_evaluator = build_evaluator_access_graph(
        task_id=TASK_ID,
        agent_graph=clean_agent,
        hidden_tests=((hidden_path, hidden_body),),
    )
    with BenchmarkIsolationSession(
        agent_graph=clean_agent,
        evaluator_graph=clean_evaluator,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        clean_payload = session.build_provider_payload()
    assert clean_payload.redaction_applied is False
    assert clean_payload.objective_preview == clean_agent.objective

    named_agent = _agent_graph(objective="Repair visible behavior; x is evaluator-only.")
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=named_agent,
            hidden_tests=((hidden_path, hidden_body),),
        )
    assert rejected.value.reason == "content_alias"
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None
    assert f'"{hidden_path}"' not in rejected.value.denial.to_json()


@pytest.mark.parametrize(
    ("hidden_path", "objective"),
    (
        ("x", "The evaluator marker is \N{FULLWIDTH LATIN SMALL LETTER X}."),
        ("a", "The evaluator marker is \N{GREEK CAPITAL LETTER ALPHA}."),
        ("api", "The evaluator marker is APӀ."),
        ("hidden.bin", "The evaluator marker is hidden\N{ZERO WIDTH SPACE}.bin."),
        (
            "hidden.bin",
            "The evaluator marker is "
            "\N{FULLWIDTH LATIN SMALL LETTER H}"
            "\N{FULLWIDTH LATIN SMALL LETTER I}"
            "\N{FULLWIDTH LATIN SMALL LETTER D}"
            "\N{FULLWIDTH LATIN SMALL LETTER D}"
            "\N{FULLWIDTH LATIN SMALL LETTER E}"
            "\N{FULLWIDTH LATIN SMALL LETTER N}"
            "\N{FULLWIDTH FULL STOP}"
            "\N{FULLWIDTH LATIN SMALL LETTER B}"
            "\N{FULLWIDTH LATIN SMALL LETTER I}"
            "\N{FULLWIDTH LATIN SMALL LETTER N}.",
        ),
    ),
)
def test_normalized_hidden_filename_aliases_are_denied_before_session(
    fixture: Fixture,
    hidden_path: str,
    objective: str,
) -> None:
    hidden_body = b"opaque evaluator material 9531\n"
    _write(fixture.evaluator_root, hidden_path, hidden_body)
    agent = _agent_graph(objective=objective)
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=agent,
            hidden_tests=((hidden_path, hidden_body),),
        )
    assert rejected.value.reason == "content_alias"
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None
    assert objective not in rejected.value.denial.to_json()


@pytest.mark.parametrize(
    ("ascii_alias", "unicode_alias"),
    (("v", "ν"), ("c", "ϲ"), ("l", "ι"), ("r", "г"), ("d", "ԁ"), ("q", "ԛ")),
)
def test_single_script_homoglyph_hidden_aliases_fail_closed(
    fixture: Fixture,
    ascii_alias: str,
    unicode_alias: str,
) -> None:
    hidden_body = b"opaque evaluator material 7129\n"
    _write(fixture.evaluator_root, ascii_alias, hidden_body)
    agent = _agent_graph(objective=f"The evaluator marker is {unicode_alias}.")
    with pytest.raises(IsolationError) as private_name:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=agent,
            hidden_tests=((ascii_alias, hidden_body),),
        )
    assert private_name.value.reason == "content_alias"
    assert private_name.value.__context__ is None

    leaked_agent = _agent_graph(objective=f"Return {unicode_alias}.")
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=leaked_agent,
            historical_answers=((ANSWER_PATH, ascii_alias.encode("ascii")),),
        )
    assert rejected.value.reason == "content_alias"
    assert isinstance(rejected.value.denial, IsolationDenial)
    assert rejected.value.denial.stage == "evaluator_graph_admission"
    assert unicode_alias not in rejected.value.denial.to_json()


@pytest.mark.parametrize(
    ("ascii_alias", "unicode_alias"),
    (("h", "հ"), ("l", "ǀ"), ("i", "ɪ"), ("o", "ᴏ"), ("v", "ᴠ"), ("u", "ᴜ")),
)
@pytest.mark.parametrize(
    "material_field",
    ("hidden_tests", "historical_answers", "negative_reviews", "assurance_data"),
)
def test_unmapped_unicode_hidden_path_and_body_aliases_fail_closed(
    ascii_alias: str,
    unicode_alias: str,
    material_field: str,
) -> None:
    agent = _agent_graph(objective=f"Return {unicode_alias}.")
    with pytest.raises(IsolationError) as body_alias:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=agent,
            **{material_field: ((ANSWER_PATH, ascii_alias.encode("ascii")),)},
        )
    assert body_alias.value.reason == "content_alias"
    assert body_alias.value.denial.stage == "evaluator_graph_admission"
    assert body_alias.value.__context__ is None

    with pytest.raises(IsolationError) as path_alias:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=agent,
            **{material_field: ((ascii_alias, b"opaque evaluator material"),)},
        )
    assert path_alias.value.reason == "content_alias"
    assert path_alias.value.denial.stage == "evaluator_graph_admission"
    assert path_alias.value.__context__ is None


def test_hidden_material_cannot_alias_provider_visible_task_id_before_session() -> None:
    task_id = "OMEGA31337"
    agent = build_agent_access_graph(
        task_id=task_id,
        baseline_commit=BASE_COMMIT,
        baseline_tree=BASE_TREE,
        objective="Repair visible behavior within the declared scope.",
        owned_paths=(BASELINE_PATH,),
        baseline_files=((BASELINE_PATH, BASELINE_BYTES),),
        public_tests=((PUBLIC_TEST_PATH, PUBLIC_TEST_BYTES),),
    )
    for private_material in (
        {"historical_answers": ((ANSWER_PATH, task_id.encode("ascii")),)},
        {"hidden_tests": ((f"sealed/{task_id}", b"opaque evaluator material"),)},
    ):
        with pytest.raises(IsolationError) as rejected:
            build_evaluator_access_graph(
                task_id=task_id,
                agent_graph=agent,
                **private_material,
            )
        assert rejected.value.reason == "content_alias"
        assert rejected.value.denial.stage == "evaluator_graph_admission"
        assert rejected.value.__context__ is None
        assert rejected.value.__cause__ is None


def test_proposal_binding_single_closure_and_terminal_shapes(fixture: Fixture) -> None:
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        foreign = TerminalProposal(
            proposal_id="proposal-foreign",
            task_id="PCCE-074-other",
            agent_access_graph_cid=fixture.agent_graph.cid,
            provider_payload_cid=payload.cid,
            terminal_status="proposed",
            patch_cid=cid_for_bytes(b"patch"),
        )
        with pytest.raises(IsolationError) as mismatch:
            session.close_proposal(foreign)
        assert mismatch.value.reason == "proposal_mismatch"
        proposal = _proposal(fixture.agent_graph, payload)
        session.close_proposal(proposal)
        assert TerminalProposal.from_json(proposal.to_json()) == proposal
        with pytest.raises(IsolationError) as duplicate:
            session.close_proposal(proposal)
        assert duplicate.value.reason == "proposal_already_closed"

    abstained = _proposal(
        fixture.agent_graph,
        payload,
        proposal_id="proposal-abstained",
        status="abstained",
        patch=None,
    )
    assert abstained.patch_cid is None
    with pytest.raises(IsolationError):
        TerminalProposal(
            proposal_id="proposal-invalid",
            task_id=TASK_ID,
            agent_access_graph_cid=fixture.agent_graph.cid,
            provider_payload_cid=payload.cid,
            terminal_status="abstained",
            patch_cid=cid_for_bytes(b"not-allowed"),
        )


def test_closed_serializers_reject_duplicate_unknown_float_and_authority(
    fixture: Fixture,
) -> None:
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(fixture.agent_graph, payload)
        session.close_proposal(proposal)
        score = session.score(proposal, _score_all)

    duplicate = '{"schema":"x","schema":"y"}'
    with pytest.raises(IsolationError):
        ProviderPayloadManifest.from_json(duplicate)

    unknown = payload.to_mapping()
    unknown["hidden_path"] = HIDDEN_PATH
    with pytest.raises(IsolationError):
        ProviderPayloadManifest.from_mapping(unknown)

    floating = payload.to_mapping()
    floating["scope_item_count"] = 1.5
    with pytest.raises(IsolationError):
        ProviderPayloadManifest.from_json(json.dumps(floating))

    with pytest.raises(IsolationError) as oversized:
        ProviderPayloadManifest.from_json(" " * (isolation.MAX_WIRE_RECORD_BYTES + 1))
    assert oversized.value.reason == "payload_overflow"

    invalid_unicode = payload.to_mapping()
    invalid_unicode["objective_preview"] = "\ud800"
    with pytest.raises(IsolationError):
        ProviderPayloadManifest.from_mapping(invalid_unicode)

    authority = payload.to_mapping()
    authority["provider_call_authority"] = True
    with pytest.raises(IsolationError) as forbidden:
        ProviderPayloadManifest.from_mapping(authority)
    assert forbidden.value.reason == "provider_disclosure"

    contradictory = score.to_mapping()
    contradictory["status"] = "scored_failures"
    with pytest.raises(IsolationError):
        EvaluationScore.from_mapping(contradictory)
    assert score.cid == cid_for_obj(score.to_mapping())


@pytest.mark.parametrize(
    "hostile_path",
    (
        "../hidden/answer.patch",
        "/absolute/answer.patch",
        "src/./core.py",
        "src//core.py",
        "src/.git/config",
        "src\\core.py",
        "src/core.py\x00hidden",
        "src/core.py.",
        "C:/host/answer.patch",
    ),
)
def test_graph_admission_rejects_traversal_magic_and_noncanonical_paths(
    hostile_path: str,
) -> None:
    with pytest.raises(IsolationError) as denied:
        build_agent_access_graph(
            task_id=TASK_ID,
            baseline_commit=BASE_COMMIT,
            baseline_tree=BASE_TREE,
            objective="Repair visible behavior.",
            owned_paths=(hostile_path,),
            baseline_files=((hostile_path, b"visible"),),
        )
    assert denied.value.reason in {"invalid_path", "path_traversal"}
    assert isinstance(denied.value.denial, IsolationDenial)
    assert denied.value.denial.reason == denied.value.reason
    assert denied.value.denial.stage == "agent_graph_admission"


def test_casefold_unicode_and_duplicate_content_aliases_fail_closed() -> None:
    with pytest.raises(IsolationError) as path_alias:
        build_agent_access_graph(
            task_id=TASK_ID,
            baseline_commit=BASE_COMMIT,
            baseline_tree=BASE_TREE,
            objective="Repair visible behavior.",
            owned_paths=("src/core.py",),
            baseline_files=(("src/core.py", b"visible"),),
            public_tests=(("tests/Test.py", b"one"), ("tests/test.py", b"two")),
        )
    assert path_alias.value.reason == "path_alias"
    assert isinstance(path_alias.value.denial, IsolationDenial)
    assert path_alias.value.denial.stage == "agent_graph_admission"

    agent = _agent_graph()
    with pytest.raises(IsolationError) as content_alias:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=agent,
            hidden_tests=((HIDDEN_PATH, BASELINE_BYTES),),
        )
    assert content_alias.value.reason == "content_alias"
    assert isinstance(content_alias.value.denial, IsolationDenial)
    assert content_alias.value.denial.reason == "content_alias"
    assert content_alias.value.denial.stage == "evaluator_graph_admission"

    hidden_answer = "This exact historical answer must not become an objective."
    leaked_agent = _agent_graph(objective=f"Repair behavior. {hidden_answer}")
    with pytest.raises(IsolationError) as answer_alias:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=leaked_agent,
            historical_answers=((ANSWER_PATH, hidden_answer.encode()),),
        )
    assert answer_alias.value.reason == "content_alias"
    assert isinstance(answer_alias.value.denial, IsolationDenial)
    assert answer_alias.value.denial.stage == "evaluator_graph_admission"


def test_non_bytes_agent_material_rejection_has_body_free_admission_denial() -> None:
    with pytest.raises(IsolationError) as rejected:
        build_agent_access_graph(
            task_id=TASK_ID,
            baseline_commit=BASE_COMMIT,
            baseline_tree=BASE_TREE,
            objective="Repair visible behavior.",
            owned_paths=(BASELINE_PATH,),
            baseline_files=((BASELINE_PATH, "not-bytes"),),
        )
    assert rejected.value.reason == "invalid_record"
    assert isinstance(rejected.value.denial, IsolationDenial)
    assert rejected.value.denial.stage == "agent_graph_admission"
    assert "not-bytes" not in rejected.value.denial.to_json()
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None
    assert "not-bytes" not in _implementation_traceback_locals(rejected.value)


@pytest.mark.parametrize("bad_oid", (None, 7, b"not-an-oid", object()))
def test_malformed_agent_oid_types_are_closed_body_free_denials(bad_oid: Any) -> None:
    with pytest.raises(IsolationError) as rejected:
        build_agent_access_graph(
            task_id=TASK_ID,
            baseline_commit=bad_oid,
            baseline_tree=BASE_TREE,
            objective="Repair visible behavior.",
            owned_paths=(BASELINE_PATH,),
            baseline_files=((BASELINE_PATH, BASELINE_BYTES),),
        )
    assert rejected.value.reason == "invalid_record"
    assert isinstance(rejected.value.denial, IsolationDenial)
    assert rejected.value.denial.stage == "agent_graph_admission"
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None
    implementation_locals = _implementation_traceback_locals(rejected.value)
    assert "not-an-oid" not in implementation_locals


def test_presession_denials_bind_distinct_opaque_rejected_attempts() -> None:
    agent_path_denials: list[IsolationDenial] = []
    for hostile_path in ("../TOP-SECRET-PATH-A", "../TOP-SECRET-PATH-B"):
        with pytest.raises(IsolationError) as rejected:
            build_agent_access_graph(
                task_id=TASK_ID,
                baseline_commit=BASE_COMMIT,
                baseline_tree=BASE_TREE,
                objective="Repair visible behavior.",
                owned_paths=(hostile_path,),
            )
        assert rejected.value.__context__ is None
        assert hostile_path not in rejected.value.denial.to_json()
        assert hostile_path not in _implementation_traceback_locals(rejected.value)
        agent_path_denials.append(rejected.value.denial)
    assert agent_path_denials[0].cid != agent_path_denials[1].cid

    agent_body_denials: list[IsolationDenial] = []
    for hostile_body in ("TOP-SECRET-BODY-A", "TOP-SECRET-BODY-B"):
        with pytest.raises(IsolationError) as rejected:
            build_agent_access_graph(
                task_id=TASK_ID,
                baseline_commit=BASE_COMMIT,
                baseline_tree=BASE_TREE,
                objective="Repair visible behavior.",
                owned_paths=(BASELINE_PATH,),
                baseline_files=((BASELINE_PATH, hostile_body),),
            )
        assert rejected.value.__context__ is None
        assert hostile_body not in rejected.value.denial.to_json()
        assert hostile_body not in _implementation_traceback_locals(rejected.value)
        agent_body_denials.append(rejected.value.denial)
    assert agent_body_denials[0].cid != agent_body_denials[1].cid

    agent = _agent_graph()
    evaluator_denials: list[IsolationDenial] = []
    for hostile_body in ("PRIVATE-EVALUATOR-A", "PRIVATE-EVALUATOR-B"):
        with pytest.raises(IsolationError) as rejected:
            build_evaluator_access_graph(
                task_id=TASK_ID,
                agent_graph=agent,
                hidden_tests=((HIDDEN_PATH, hostile_body),),
            )
        assert rejected.value.__context__ is None
        assert hostile_body not in rejected.value.denial.to_json()
        assert hostile_body not in _implementation_traceback_locals(rejected.value)
        evaluator_denials.append(rejected.value.denial)
    assert evaluator_denials[0].cid != evaluator_denials[1].cid


@pytest.mark.parametrize(
    ("hidden_answer", "objective"),
    (
        (b"h", "Return \N{CYRILLIC SMALL LETTER SHHA}."),
        (b"l", "Return \N{CYRILLIC SMALL LETTER PALOCHKA}."),
        (b"i", "Return \N{LATIN SMALL LETTER DOTLESS I}."),
        (b"o", "Return \N{ARMENIAN SMALL LETTER OH}."),
        (b"j", "Return \N{GREEK LETTER YOT}."),
        (b"v", "Return \N{CYRILLIC SMALL LETTER IZHITSA}."),
        (b"u", "Return \N{GREEK SMALL LETTER UPSILON}."),
    ),
)
def test_single_script_confusable_hidden_answers_are_denied_before_session(
    hidden_answer: bytes,
    objective: str,
) -> None:
    agent = _agent_graph(objective=objective)
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=agent,
            historical_answers=((ANSWER_PATH, hidden_answer),),
        )
    assert rejected.value.reason == "content_alias"
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None
    assert objective not in rejected.value.denial.to_json()


@pytest.mark.parametrize(
    ("private_path", "objective"),
    (
        ("hidden/secret_case.py", "Repair behavior for secret_case.py."),
        ("hidden/secret_case.py", "Repair hidden/secret_case.py."),
        (
            "hidden/secret_case.py",
            "Repair behavior for secret_c\N{CYRILLIC SMALL LETTER A}se.py.",
        ),
    ),
)
def test_private_evaluator_paths_and_names_are_denied_before_session(
    private_path: str,
    objective: str,
) -> None:
    agent = _agent_graph(objective=objective)
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=agent,
            hidden_tests=((private_path, b"opaque private bytes"),),
        )
    assert rejected.value.reason == "content_alias"
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None
    assert private_path not in rejected.value.denial.to_json()


def test_partial_normalized_hidden_answer_overlap_is_rejected_without_body_leakage() -> None:
    hidden_answer = (
        b"CONFIDENTIAL: the winning-fix changes_limit to OMEGA-31337 and returns safely.\n"
    )
    agent = _agent_graph(
        objective=("Implement the winning fix: CHANGE LIMIT to omega 31337 without widening scope.")
    )
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=agent,
            historical_answers=(("answers/winner.bin", hidden_answer),),
        )
    assert rejected.value.reason == "content_alias"
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None
    implementation_locals = _implementation_traceback_locals(rejected.value)
    assert hidden_answer.decode().strip() not in implementation_locals
    assert "answers/winner.bin" not in implementation_locals


def test_short_hidden_answer_uses_token_exact_not_incidental_substring_screening() -> None:
    leaked_agent = _agent_graph(objective="Return yes when the visible condition holds.")
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=leaked_agent,
            historical_answers=(("answers/label.txt", b"yes"),),
        )
    assert rejected.value.reason == "content_alias"

    clean_agent = _agent_graph(objective="Repair exact visible behavior.")
    evaluator = build_evaluator_access_graph(
        task_id=TASK_ID,
        agent_graph=clean_agent,
        hidden_tests=(("hidden/label.txt", b"x"),),
    )
    assert evaluator.agent_access_graph_cid == clean_agent.cid


@pytest.mark.parametrize(
    ("hidden_answer", "objective"),
    (
        (b"+", "Return +."),
        (b"++", "Return ++."),
        (b"...", "Return ..."),
        ("\N{POUND SIGN}".encode(), "Return \N{POUND SIGN}."),
        ("\N{WHITE HEAVY CHECK MARK}".encode(), "Return \N{WHITE HEAVY CHECK MARK}."),
        (
            "\N{WHITE HEAVY CHECK MARK}\N{VARIATION SELECTOR-16}".encode(),
            "Return \N{WHITE HEAVY CHECK MARK}.",
        ),
        ("+\N{VARIATION SELECTOR-16}".encode(), "Return +."),
    ),
)
def test_short_symbol_only_hidden_answers_are_rejected(
    hidden_answer: bytes,
    objective: str,
) -> None:
    leaked_agent = _agent_graph(objective=objective)
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=leaked_agent,
            historical_answers=((ANSWER_PATH, hidden_answer),),
        )
    assert rejected.value.reason == "content_alias"
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None
    implementation_locals = _implementation_traceback_locals(rejected.value)
    assert hidden_answer.decode() not in implementation_locals
    assert ANSWER_PATH not in implementation_locals


@pytest.mark.parametrize(
    ("hidden_answer", "objective"),
    (
        (b"a", "Return \N{GREEK CAPITAL LETTER ALPHA}."),
        (b"yes", "Return y.e.s."),
        (b"yes", "Return y\N{ZERO WIDTH SPACE}es."),
        (b"omega31337", "Use omega-31337."),
        (b"winning fix", "Apply the winning-fix."),
    ),
)
def test_hidden_tokens_cannot_be_disclosed_through_punctuation_or_ignorables(
    hidden_answer: bytes,
    objective: str,
) -> None:
    leaked_agent = _agent_graph(objective=objective)
    with pytest.raises(IsolationError) as rejected:
        build_evaluator_access_graph(
            task_id=TASK_ID,
            agent_graph=leaked_agent,
            historical_answers=((ANSWER_PATH, hidden_answer),),
        )
    assert rejected.value.reason == "content_alias"
    assert rejected.value.__context__ is None
    assert rejected.value.__cause__ is None


@pytest.mark.parametrize(
    "future_reference",
    (
        "3" * 40,
        "ABCDEF0123456789ABCDEF0123456789ABCDEF01",
        "abcdef012345",
        "DeAdBeEf1234",
        "refs/heads/future-release",
        "refs-heads-future-release",
        "HEAD~2",
        "commit deadbe",
        "tag:v2.0.0",
        "tag v2.0.0",
        "branch=release-next",
        "branch release-next",
        "ref release-next",
        "refs/pull/42/head",
        "refs/merge-requests/7/head",
        "refs/notes/review",
        "refs/stash",
        TERMINAL_PROPOSAL_CID,
        DAG_PB_FUTURE_CID,
        "main@{1}",
        "@{1}",
        "@{yesterday}",
        "@{-1}",
        "release-next~2",
        "head~2",
        "Head^",
        "main..future",
        "main...future",
        "main:path",
        ":/winning-fix",
    ),
)
def test_future_refs_and_future_fields_are_denied_not_projected(
    fixture: Fixture,
    future_reference: str,
) -> None:
    with pytest.raises(IsolationError) as future:
        _agent_graph(objective=f"Use revision {future_reference} as the answer.")
    assert future.value.reason == "future_ref"
    assert isinstance(future.value.denial, IsolationDenial)
    assert future.value.denial.reason == "future_ref"
    assert future.value.denial.stage == "agent_graph_admission"
    assert future_reference not in future.value.denial.to_json()
    assert IsolationDenial.from_json(future.value.denial.to_json()) == future.value.denial

    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = session.build_provider_payload()
    injected = payload.to_mapping()
    injected["future_ref"] = future_reference
    with pytest.raises(IsolationError):
        ProviderPayloadManifest.from_mapping(injected)
    assert future_reference not in payload.to_json()


@pytest.mark.parametrize(
    "objective",
    (
        "Use commit cafe as the answer.",
        "Use commit deadbe as the answer.",
        "Use commit deadbeef as the answer.",
        "Use feature@{1} as the answer.",
        "Use feature~2 as the answer.",
        "Use feature:path as the answer.",
        "Use feature/foo..future/bar as the answer.",
        "Use deadbeef..cafebabe as the answer.",
        "The answer is commit foo.",
        "Use topic@{2.days.ago} as the answer.",
        "Use v2.0.0 as the answer.",
        "Use release-next as the answer.",
        "Run git show topic before coding.",
        "Run git log topic before coding.",
        "Run git rev-parse topic before coding.",
        "Run git cat-file -p topic before coding.",
        "Run git ls-tree topic before coding.",
        "Run git archive topic before coding.",
        "Run git describe topic before coding.",
        "Run git log foo..bar before coding.",
        "Inspect topic before coding.",
        "Use v2.0.0 before coding.",
        "Merge topic before coding.",
        "Merge branch topic before coding.",
        "Merge topic.",
        "Checkout topic.",
        "Switch to topic.",
        "Use topic@{2026-08-24 12:34:56 +0000} as the answer.",
        "Use topic@{Mon Aug 24 12:34:56 2026 +0000} as the answer.",
        "Use refs/\N{CYRILLIC SMALL LETTER SHHA}eads/future as the answer.",
        "The answer is foo^2.",
        "The answer is foo..bar.",
    ),
)
def test_direct_future_ref_syntax_is_denied_without_a_qualifier(objective: str) -> None:
    with pytest.raises(IsolationError) as rejected:
        _agent_graph(objective=objective)
    assert rejected.value.reason == "future_ref"


@pytest.mark.parametrize(
    "objective",
    (
        "Run git -P show topic before coding.",
        "Run git --paginate show topic before coding.",
        "Run git --no-replace-objects show topic before coding.",
        "Run git --literal-pathspecs show topic before coding.",
        "Run git --config-env=alias.x=CFG show topic before coding.",
        "Run git --config-env=alias.peek=CFG peek topic-name.",
        "Run git --config-env alias.peek=CFG peek topic-name.",
        "Run git --exec-path=/tmp show topic before coding.",
        "Run git -c a.a=1 -c b.b=2 -c c.c=3 -c d.d=4 -c e.e=5 show topic.",
        "Run /usr/bin/git --paginate show topic before coding.",
        "Run env MODE=clean command git --paginate show topic before coding.",
        "Run git -c alias.peek=show peek topic before coding.",
        "Run git -c 'http.extraHeader=Foo Bar' show topic/custom-name.",
        "Run git -c alias.peek='show' peek topic/custom-name.",
        'Run git -c alias.peek="show" peek topic/custom-name.',
        "Run git --git-dir '/tmp/repo with spaces/.git' show topic/custom-name.",
        "Run git \\\n show topic/custom-name.",
        r"Run g\it show topic-name.",
        "Run g''it show topic-name.",
        "Run g$''it show topic-name.",
        'Run g$""it show topic-name.',
        "Run $'git' show topic-name.",
        "Run git status; g''it show topic-name.",
        r"Run git -c alias.peek='!g\it show' peek topic-name.",
        "Run git -c \"alias.peek=!g''it show\" peek topic-name.",
        "Run './git' show topic-name.",
        "Run '/opt/git tools/git' show topic-name.",
        "Run git --paginate diff foo..bar before coding.",
        "Checkout --detach topic before coding.",
        "Reset --hard topic before coding.",
        "Switch --detach topic before coding.",
        "Diff topic before coding.",
        "Review changes between foo..bar before coding.",
        "The comparison foo...bar determines visible behavior.",
        "Use topic@{Mon, 24 Aug 2026 12:34:56 +0000} as the answer.",
        "Use topic@{one month ago} as the answer.",
        "Use topic@{2 months ago} as the answer.",
        "Use topic@{last Monday} as the answer.",
        "Inspect հead before coding.",
        "Inspect maɪn before coding.",
        "Inspect maⲓn before coding.",
    ),
)
def test_global_git_options_context_ranges_reflogs_and_unicode_refs_are_denied(
    objective: str,
) -> None:
    with pytest.raises(IsolationError) as rejected:
        _agent_graph(objective=objective)
    assert rejected.value.reason == "future_ref"


@pytest.mark.parametrize(
    "objective",
    (
        "Run git annotate topic -- src/pkg/core.py.",
        "Run git diff-tree topic before coding.",
        "Run git read-tree topic before coding.",
        "Run git merge-tree topic other before coding.",
        "Run git fast-export topic before coding.",
        "Run git filter-branch -- --all before coding.",
        "Run git --attr-source=topic-name status --short.",
        "Run git check-attr --source=topic-name attr -- src/pkg/core.py.",
    ),
)
def test_closed_git_consumer_and_revision_option_model_denies_unknown_readers(
    objective: str,
) -> None:
    assert isolation._contains_git_revision_command(objective)
    assert isolation._contains_future_reference(objective)
    with pytest.raises(IsolationError) as rejected:
        _agent_graph(objective=objective)
    assert rejected.value.reason == "future_ref"


@pytest.mark.parametrize(
    "objective",
    (
        r"Run git${IFS}show${IFS}topic-name.",
        'f() { command git "$1" "$2"; }\nf show topic-name',
        "Run ${GIT_COMMAND} show topic-name.",
    ),
)
def test_unresolved_shell_words_and_wrappers_fail_closed(objective: str) -> None:
    assert isolation._contains_git_revision_command(objective)
    assert isolation._contains_future_reference(objective)
    with pytest.raises(IsolationError) as rejected:
        _agent_graph(objective=objective)
    assert rejected.value.reason == "future_ref"


@pytest.mark.parametrize(
    "objective",
    (
        "Run /usr/lib/git-core/git-show topic-name before coding.",
        "Run /usr/bin/g?t show topic-name before coding.",
        "Run /usr/bin/g{,x}it show topic-name before coding.",
        "Run /usr/lib/git-core/git-{status,show} topic-name before coding.",
        'Run sh -c "g""it show topic-name".',
        'Run /bin/b{a,}sh -c "git show topic-name".',
        'Run eval "g""it show topic-name".',
        'Run sh -c "eval g""it show topic-name".',
    ),
)
def test_git_helper_glob_and_shell_quote_concatenation_fail_closed(objective: str) -> None:
    assert isolation._contains_git_revision_command(objective)
    assert isolation._contains_future_reference(objective)
    with pytest.raises(IsolationError) as rejected:
        _agent_graph(objective=objective)
    assert rejected.value.reason == "future_ref"


@pytest.mark.parametrize(
    ("objective", "is_revision_command"),
    (
        ("Run git \\\n show topic-name.", True),
        ('Run "g\\\nit" show topic-name.', True),
        ("'g\\\nit' show topic", False),
        ("g\\\\\nit show topic", False),
        ("Render '$HOME' literally in visible documentation.", False),
    ),
)
def test_shell_continuations_preserve_quote_and_escape_context(
    objective: str,
    is_revision_command: bool,
) -> None:
    assert isolation._contains_git_revision_command(objective) is is_revision_command
    assert isolation._contains_future_reference(objective) is is_revision_command
    if is_revision_command:
        with pytest.raises(IsolationError) as rejected:
            _agent_graph(objective=objective)
        assert rejected.value.reason == "future_ref"
    else:
        assert _agent_graph(objective=objective).objective == objective


@pytest.mark.parametrize(
    "objective",
    (
        "Run git status --short.",
        "Run git add -- src/pkg/core.py.",
        "Run git --config-env=core.pager=PAGER status --short.",
        "Repair git's status parser without reading revisions.",
        "Preserve the unmatched ' quote in visible text.",
        r"Render g\izmo as visible text.",
        "Render g''izmo as visible text.",
        "Run /usr/lib/git-core/git-status --short.",
        "Render /usr/bin/g?z literally.",
        "Render /usr/bin/g{izmo,adget} literally.",
        'Run sh -c "printf %s visible".',
        'Run eval "printf %s visible".',
        "Run git 'status --short.",
        "Keep the half-open interval A..Z in the documentation.",
        "Use a..z in the visible range expression.",
        "Render user@{host} literally in the template.",
        "Compare release 1.2.3 with release 1.2.4.",
    ),
)
def test_nearby_non_revision_controls_remain_admissible(objective: str) -> None:
    assert _agent_graph(objective=objective).objective == objective


@pytest.mark.parametrize(
    "future_reference",
    (
        "x@{1}",
        "ab@{today}",
        "1@{1}",
        "x~2",
        "x~",
        "1~2",
        "ab^",
        "1^",
        "x:path",
        "ab:path",
        "1:path",
        "feature..future",
        "feature...future",
        "feature..",
        "..future",
        "feature...",
        "...future",
        "feature/foo..bar",
        "foo..feature/bar",
    ),
)
def test_short_and_one_sided_git_revision_syntax_is_denied(
    future_reference: str,
) -> None:
    with pytest.raises(IsolationError) as rejected:
        _agent_graph(objective=f"Use {future_reference} as the answer.")
    assert rejected.value.reason == "future_ref"


@pytest.mark.parametrize(
    "objective",
    (
        "Use x^2 as the answer.",
        "branch x",
        "tag x",
        "ref x",
        "revision x",
        "branch feature",
        "tag candidate",
        "commit feature",
        "Use commit x now.",
        "Inspect topic^2 now.",
        "Read topic:LICENSE now.",
        "Compare topic..other before coding.",
        "Use @ as the answer.",
        "branch 未来",
    ),
)
def test_contextual_short_and_qualified_simple_refs_are_denied(objective: str) -> None:
    with pytest.raises(IsolationError) as rejected:
        _agent_graph(objective=objective)
    assert rejected.value.reason == "future_ref"


def test_all_supported_standard_multibase_cids_are_future_references() -> None:
    from multiformats import CID

    cid = CID.decode(cid_for_bytes(b"multibase-future-reference"))
    bases = (
        "base2",
        "base8",
        "base10",
        "base16",
        "base16upper",
        "base32",
        "base32upper",
        "base32pad",
        "base32padupper",
        "base32hex",
        "base32hexupper",
        "base32hexpad",
        "base32hexpadupper",
        "base32z",
        "base36",
        "base36upper",
        "base58btc",
        "base58flickr",
        "base64",
        "base64pad",
        "base64url",
        "base64urlpad",
        "proquint",
    )
    for base in bases:
        encoded = cid.encode(base)
        with pytest.raises(IsolationError) as rejected:
            _agent_graph(objective=f"Use CID {encoded} as the future answer.")
        assert rejected.value.reason == "future_ref", base


def test_benign_head_and_future_language_is_not_misclassified_as_a_ref() -> None:
    objectives = (
        "Commit changes that improve branch coverage in the linked-list head "
        "for future compatibility.",
        "Repair the effaced label while preserving branch coverage and tag metadata.",
        "Use the feedback to improve the decade-old parser.",
        "Process invoice number 1234567 without changing it.",
        "Commit dead code without changing behavior.",
        "Use x^2 in the visible scoring formula.",
        "Render user@{host} literally in the template.",
        "Handle HTTP HEAD requests and preserve status codes.",
        "Document HTTP HEAD semantics for visible clients.",
        "Keep the message Wait...what happened? unchanged.",
        "Keep the CSS color #abcdef12 unchanged.",
        "Preserve UUID 123e4567-e89b-12d3-a456-426614174000.",
        "Commit added files without changing scope.",
        "Commit facade changes after review.",
        "Preserve value^2 in the visible formula.",
        "Preserve key:value syntax in the documentation.",
        "Render field:default in the template.",
        "Keep the half-open interval A..Z in the documentation.",
        "Compare the visible letters A..Z.",
        "Use x^2 as the visible exponent.",
        "Use y^3 in the visible polynomial.",
        "Use a..z in the visible range expression.",
        "Use key:value in the visible mapping.",
        "Use 1:2 as the visible ratio.",
    )
    for objective in objectives:
        assert _agent_graph(objective=objective).objective == objective


def test_future_ref_and_graph_identity_drift_are_audited_before_provider_projection(
    fixture: Fixture,
) -> None:
    original_cid = fixture.agent_graph.cid
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        object.__setattr__(
            fixture.agent_graph,
            "objective",
            "Use refs/heads/future-release as the answer.",
        )
        with pytest.raises(IsolationError) as future:
            session.build_provider_payload()
        assert future.value.reason == "future_ref"
        assert future.value.__context__ is None
        assert future.value.__cause__ is None
        assert session.denials()[-1].reason == "future_ref"
        assert session.denials()[-1].stage == "provider_payload"
        assert session.denials()[-1].agent_access_graph_cid == original_cid

    agent = _agent_graph()
    evaluator = _evaluator_graph(agent)
    with BenchmarkIsolationSession(
        agent_graph=agent,
        evaluator_graph=evaluator,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        object.__setattr__(agent, "owned_paths", ("src/other.py",))
        with pytest.raises(IsolationError) as drift:
            session.build_provider_payload()
        assert drift.value.reason == "graph_identity_drift"
        assert drift.value.__context__ is None
        assert drift.value.__cause__ is None
        assert session.denials()[-1].reason == "graph_identity_drift"


def test_symlink_file_and_symlink_root_are_denied_before_body_access(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_bytes(BASELINE_BYTES)
    agent_root = tmp_path / "agent"
    evaluator_root = tmp_path / "evaluator"
    agent_root.mkdir()
    evaluator_root.mkdir()
    _write(agent_root, PUBLIC_TEST_PATH, PUBLIC_TEST_BYTES)
    target = agent_root / BASELINE_PATH
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)
    _write(evaluator_root, HIDDEN_PATH, HIDDEN_BYTES)
    agent = _agent_graph()
    evaluator = build_evaluator_access_graph(
        task_id=TASK_ID,
        agent_graph=agent,
        hidden_tests=((HIDDEN_PATH, HIDDEN_BYTES),),
    )
    with pytest.raises(IsolationError) as symlink:
        BenchmarkIsolationSession(
            agent_graph=agent,
            evaluator_graph=evaluator,
            agent_root=agent_root,
            evaluator_root=evaluator_root,
        )
    assert symlink.value.reason == "path_symlink"

    safe_agent_root = tmp_path / "safe-agent"
    safe_agent_root.mkdir()
    _write(safe_agent_root, BASELINE_PATH, BASELINE_BYTES)
    _write(safe_agent_root, PUBLIC_TEST_PATH, PUBLIC_TEST_BYTES)
    evaluator_alias = tmp_path / "evaluator-alias"
    evaluator_alias.symlink_to(evaluator_root, target_is_directory=True)
    with pytest.raises(IsolationError) as root_symlink:
        BenchmarkIsolationSession(
            agent_graph=agent,
            evaluator_graph=evaluator,
            agent_root=safe_agent_root,
            evaluator_root=evaluator_alias,
        )
    assert root_symlink.value.reason == "path_symlink"


def test_evaluator_symlink_is_not_opened_before_proposal_and_fails_during_score(
    tmp_path: Path,
) -> None:
    agent_root = tmp_path / "agent"
    evaluator_root = tmp_path / "evaluator"
    outside = tmp_path / "outside-hidden.py"
    agent_root.mkdir()
    evaluator_root.mkdir()
    outside.write_bytes(HIDDEN_BYTES)
    _write(agent_root, BASELINE_PATH, BASELINE_BYTES)
    _write(agent_root, PUBLIC_TEST_PATH, PUBLIC_TEST_BYTES)
    hidden = evaluator_root / HIDDEN_PATH
    hidden.parent.mkdir(parents=True)
    hidden.symlink_to(outside)
    agent = _agent_graph()
    evaluator = build_evaluator_access_graph(
        task_id=TASK_ID,
        agent_graph=agent,
        hidden_tests=((HIDDEN_PATH, HIDDEN_BYTES),),
    )
    with BenchmarkIsolationSession(
        agent_graph=agent,
        evaluator_graph=evaluator,
        agent_root=agent_root,
        evaluator_root=evaluator_root,
    ) as session:
        assert session.phase == "proposal_open"
        payload = _payload(session)
        proposal = _proposal(agent, payload)
        session.close_proposal(proposal)
        with pytest.raises(IsolationError) as denied:
            session.score(proposal, _score_all)
        assert denied.value.reason == "path_symlink"
        assert session.phase == "evaluation_failed"


@pytest.mark.parametrize("projection", ("agent", "evaluator"))
def test_hardlinks_are_denied_in_both_projection_roots(tmp_path: Path, projection: str) -> None:
    agent_root = tmp_path / "agent"
    evaluator_root = tmp_path / "evaluator"
    agent_root.mkdir()
    evaluator_root.mkdir()
    _write(agent_root, BASELINE_PATH, BASELINE_BYTES)
    _write(agent_root, PUBLIC_TEST_PATH, PUBLIC_TEST_BYTES)
    _write(evaluator_root, HIDDEN_PATH, HIDDEN_BYTES)
    external = tmp_path / "external"
    if projection == "agent":
        (agent_root / BASELINE_PATH).unlink()
        external.write_bytes(BASELINE_BYTES)
        os.link(external, agent_root / BASELINE_PATH)
    else:
        (evaluator_root / HIDDEN_PATH).unlink()
        external.write_bytes(HIDDEN_BYTES)
        os.link(external, evaluator_root / HIDDEN_PATH)
    agent = _agent_graph()
    evaluator = build_evaluator_access_graph(
        task_id=TASK_ID,
        agent_graph=agent,
        hidden_tests=((HIDDEN_PATH, HIDDEN_BYTES),),
    )
    if projection == "agent":
        with pytest.raises(IsolationError) as denied:
            BenchmarkIsolationSession(
                agent_graph=agent,
                evaluator_graph=evaluator,
                agent_root=agent_root,
                evaluator_root=evaluator_root,
            )
        assert denied.value.reason == "path_hardlink"
        return
    with BenchmarkIsolationSession(
        agent_graph=agent,
        evaluator_graph=evaluator,
        agent_root=agent_root,
        evaluator_root=evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(agent, payload)
        session.close_proposal(proposal)
        with pytest.raises(IsolationError) as denied:
            session.score(proposal, _score_all)
        assert denied.value.reason == "path_hardlink"


def test_root_overlap_and_post_admission_identity_drift_fail_closed(fixture: Fixture) -> None:
    with pytest.raises(IsolationError) as overlap:
        BenchmarkIsolationSession(
            agent_graph=fixture.agent_graph,
            evaluator_graph=fixture.evaluator_graph,
            agent_root=fixture.agent_root,
            evaluator_root=fixture.agent_root,
        )
    assert overlap.value.reason == "root_overlap"

    with pytest.raises(IsolationError) as root_alias:
        BenchmarkIsolationSession(
            agent_graph=fixture.agent_graph,
            evaluator_graph=fixture.evaluator_graph,
            agent_root=fixture.agent_root,
            evaluator_root="//",
        )
    assert root_alias.value.reason == "invalid_path"

    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        baseline = next(grant for grant in fixture.agent_graph.grants if grant.kind == "baseline")
        (fixture.agent_root / BASELINE_PATH).write_bytes(b"attacker replacement")
        with pytest.raises(IsolationError) as drift:
            session.read_agent_artifact(baseline.artifact_id, baseline.content_cid)
        assert drift.value.reason == "grant_identity_mismatch"


def test_visible_identity_drift_blocks_provider_manifest_and_proposal_closure(
    fixture: Fixture,
) -> None:
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        baseline_path = fixture.agent_root / BASELINE_PATH
        baseline_path.chmod(baseline_path.stat().st_mode ^ stat.S_IXUSR)
        with pytest.raises(IsolationError) as drift:
            session.build_provider_payload()
        assert drift.value.reason == "path_identity_drift"

    baseline_path = fixture.agent_root / BASELINE_PATH
    baseline_path.chmod(baseline_path.stat().st_mode ^ stat.S_IXUSR)
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = session.build_provider_payload()
        proposal = _proposal(fixture.agent_graph, payload)
        public_path = fixture.agent_root / PUBLIC_TEST_PATH
        public_path.chmod(public_path.stat().st_mode ^ stat.S_IXUSR)
        with pytest.raises(IsolationError) as drift:
            session.close_proposal(proposal)
        assert drift.value.reason == "path_identity_drift"


def test_evaluator_identity_drift_after_closure_cannot_be_scored(fixture: Fixture) -> None:
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(fixture.agent_graph, payload)
        session.close_proposal(proposal)
        (fixture.evaluator_root / HIDDEN_PATH).write_bytes(b"replacement hidden body")
        with pytest.raises(IsolationError) as drift:
            session.score(proposal, _score_all)
        assert drift.value.reason == "grant_identity_mismatch"
        assert session.phase == "evaluation_failed"


def test_adversarial_scorer_error_and_denials_never_log_hidden_detail(
    fixture: Fixture,
) -> None:
    leaked = HIDDEN_BYTES.decode().strip()

    def malicious(material: Any) -> list[bool]:
        handle = material.handles()[0]
        body = material.read(handle.artifact_id, handle.content_cid)
        raise RuntimeError(f"{body.decode()} {HIDDEN_PATH} {fixture.evaluator_graph.cid}")

    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(fixture.agent_graph, payload)
        session.close_proposal(proposal)
        with pytest.raises(IsolationError) as failed:
            session.score(proposal, malicious)
        assert failed.value.reason == "scoring_failed"
        assert str(failed.value) == "evaluator scoring failed"
        assert failed.value.__context__ is None
        assert failed.value.__cause__ is None
        audit = "".join(denial.to_json() for denial in session.denials())
        for forbidden in (leaked, HIDDEN_PATH, Path(HIDDEN_PATH).name, fixture.evaluator_graph.cid):
            assert forbidden not in audit
        assert all(IsolationDenial.from_json(item.to_json()) == item for item in session.denials())

    def invalid_hidden_result(material: Any) -> list[bytes]:
        handle = material.handles()[0]
        return [material.read(handle.artifact_id, handle.content_cid)]

    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(
            fixture.agent_graph,
            payload,
            proposal_id="proposal-hidden-invalid-result",
        )
        session.close_proposal(proposal)
        with pytest.raises(IsolationError) as failed:
            session.score(proposal, invalid_hidden_result)
        assert failed.value.reason == "scoring_failed"
        assert failed.value.__context__ is None
        assert failed.value.__cause__ is None
        implementation_locals = _implementation_traceback_locals(failed.value)
        for forbidden in (leaked, HIDDEN_PATH, fixture.evaluator_graph.cid):
            assert forbidden not in implementation_locals


def test_incomplete_scoring_and_filename_only_evaluator_lookup_are_denied(
    fixture: Fixture,
) -> None:
    def incomplete(material: Any) -> list[bool]:
        first = material.handles()[0]
        material.read(first.artifact_id, first.content_cid)
        return [True]

    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(fixture.agent_graph, payload)
        session.close_proposal(proposal)
        with pytest.raises(IsolationError) as denied:
            session.score(proposal, incomplete)
        assert denied.value.reason == "incomplete_evaluation"

    def filename_lookup(material: Any) -> list[bool]:
        material.read(HIDDEN_PATH, cid_for_bytes(HIDDEN_BYTES))
        return [True]

    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        payload = _payload(session)
        proposal = _proposal(fixture.agent_graph, payload, proposal_id="proposal-0002")
        session.close_proposal(proposal)
        with pytest.raises(IsolationError) as denied:
            session.score(proposal, filename_lookup)
        assert denied.value.reason == "unknown_grant"
        assert HIDDEN_PATH not in session.denials()[-1].to_json()


def test_denial_audit_is_bounded_and_closes_on_overflow(fixture: Fixture) -> None:
    baseline = fixture.agent_graph.grants[0]
    with BenchmarkIsolationSession(
        agent_graph=fixture.agent_graph,
        evaluator_graph=fixture.evaluator_graph,
        agent_root=fixture.agent_root,
        evaluator_root=fixture.evaluator_root,
    ) as session:
        for _index in range(isolation.MAX_DENIAL_EVENTS):
            with pytest.raises(IsolationError):
                session.read_agent_artifact("filename-only-guess", baseline.content_cid)
        assert len(session.denials()) == isolation.MAX_DENIAL_EVENTS
        assert session.denials()[-1].reason == "audit_overflow"
        assert session.denials()[-1].stage == "audit"
        assert session.phase == "closed"
        with pytest.raises(IsolationError) as overflow:
            session.read_agent_artifact("another-guess", baseline.content_cid)
        assert overflow.value.reason == "audit_overflow"
        assert len(session.denials()) == isolation.MAX_DENIAL_EVENTS
