"""Unit tests for PlateauSupervisorMaterializer@1 packet → supervisor tasks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    CanonicalRuleIR,
)
from benchmarks.semantic_roundtrip.plateau_codex_packet import (
    DEFAULT_HOLDOUT_VALIDATION_COMMANDS,
    DEFAULT_PREDICTED_FILES,
    DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS,
    HOLDOUT_BASELINE_E2E,
    REPAIR_DEV_POPULATION_KIND,
    build_holdout_packet_from_proposal_admission,
    build_packet_from_proposal_admission,
    build_plateau_codex_packet,
    build_repair_dev_packet_from_proposal_admission,
)
from benchmarks.semantic_roundtrip.plateau_supervisor_materialize import (
    BUNDLE_SUPERVISOR_MODULE,
    CASE_TO_EDIT_WAVE_TASK,
    DEFAULT_BOARD_NAMESPACE,
    DEFAULT_MATERIALIZER_PREDICTED_FILES,
    DEFAULT_MAX_LANES,
    DEFAULT_MERGE_TARGET_BRANCH,
    DEFAULT_TASK_PREFIX,
    HOLDOUT_BOARD_NAMESPACE,
    HOLDOUT_BUNDLE,
    HOLDOUT_CASE_TO_EDIT_WAVE_TASK,
    HOLDOUT_MAX_LANES,
    HOLDOUT_TASK_PREFIX,
    MATERIALIZER_PREDICTED_FILE_PREFIXES,
    PLATEAU_SUPERVISOR_MATERIALIZER_EVIDENCE,
    PLATEAU_SUPERVISOR_MATERIALIZER_INTERFACE,
    PLATEAU_SUPERVISOR_NOTE_INTERFACE,
    PLATEAU_SUPERVISOR_TASK_INTERFACE,
    REPAIR_DEV_BOARD_NAMESPACE,
    REPAIR_DEV_BUNDLE,
    REPAIR_DEV_CASE_TO_EDIT_WAVE_TASK,
    BundleSupervisorLaunchSpec,
    MaterializedKind,
    PlateauSupervisorMaterializeError,
    coerce_packet,
    default_launch_spec,
    filter_supervisor_predicted_files,
    holdout_launch_spec,
    is_holdout_case,
    is_materializer_allowed_path,
    is_repair_dev_packet,
    load_packets_from_json_path,
    main,
    materialize_holdout_packets,
    materialize_packet,
    materialize_packets,
    materialize_repair_dev_packets,
    render_launch_markdown,
    repair_dev_launch_spec,
)
from benchmarks.semantic_roundtrip.selective_repair import StructuralTool
from benchmarks.semantic_roundtrip.structural_admission import (
    AdmissionDisposition,
    StructuralAdmissionGate,
    StructuralAdmissionPolicy,
    admit_hybrid_repair,
    make_error_binding,
    make_passing_binding,
    make_rejecting_binding,
    make_timeout_binding,
)
from benchmarks.semantic_roundtrip.plateau_codex_packet import (
    ResidualRef,
    TeacherProposal,
)


PRIOR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="",
        ),
    )
)
CANDIDATE = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
        ),
    )
)
OBJECT_PATH = "rules[0].object"


def _residual(
    residual_id: str = "resid-legal-object",
    case_id: str = "legal_doc_1",
) -> ResidualRef:
    return ResidualRef(
        residual_id=residual_id,
        case_id=case_id,
        field_paths=(OBJECT_PATH,),
        facet="object",
        estimated_forward_contribution=0.05,
        catalog_digest="a" * 64,
        detail="missing object atom on pilot residual",
    )


def _proposal(
    proposal_id: str = "prop-leanstral-1",
    residual_id: str = "resid-legal-object",
    candidate: CanonicalRuleIR | None = CANDIDATE,
) -> TeacherProposal:
    return TeacherProposal(
        proposal_id=proposal_id,
        teacher="leanstral",
        residual_ref_ids=(residual_id,),
        allowed_field_paths=(OBJECT_PATH,),
        candidate_l1=candidate,
        detail="selective object fill proposal",
        semantic_authority=False,
    )


def _accept_gate() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(
            tools=(StructuralTool.HAMMER_CVC5, StructuralTool.LEAN),
        ),
        validators=(
            make_passing_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
            make_passing_binding(
                validator_id="lean",
                tool=StructuralTool.LEAN,
            ),
        ),
    )


def _reject_gate() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_rejecting_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
                detail="candidate violates structural constraint",
            ),
        ),
    )


def _timeout_gate() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(
            tools=(StructuralTool.LEAN,),
            timeout_seconds=0.05,
            fail_closed_on_timeout=True,
        ),
        validators=(
            make_timeout_binding(
                validator_id="lean",
                tool=StructuralTool.LEAN,
                sleep_seconds=2.0,
            ),
        ),
    )


def _error_gate() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_error_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
        ),
    )


def _accepted_packet(*, case_id: str = "legal_doc_1", packet_id: str = "pkt-legal-accept-1"):
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    return build_packet_from_proposal_admission(
        packet_id=packet_id,
        baseline_l1=PRIOR,
        residual_ref=_residual(case_id=case_id),
        proposal=_proposal(),
        admission=admission,
        case_id=case_id,
        detail=f"accepted object fill for {case_id}",
    )


def _rejected_packet(
    gate_factory,
    *,
    packet_id: str = "pkt-reject-1",
    case_id: str = "legal_doc_1",
):
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=gate_factory(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    return build_packet_from_proposal_admission(
        packet_id=packet_id,
        baseline_l1=PRIOR,
        residual_ref=_residual(case_id=case_id),
        proposal=_proposal(),
        admission=admission,
        case_id=case_id,
    )


def test_interface_constants_and_defaults() -> None:
    assert (
        PLATEAU_SUPERVISOR_MATERIALIZER_INTERFACE
        == "PlateauSupervisorMaterializer@1"
    )
    assert PLATEAU_SUPERVISOR_MATERIALIZER_EVIDENCE == "PLATEV070SUP"
    assert PLATEAU_SUPERVISOR_TASK_INTERFACE.endswith("Task@1")
    assert PLATEAU_SUPERVISOR_NOTE_INTERFACE.endswith("Note@1")
    assert DEFAULT_MERGE_TARGET_BRANCH == (
        "benchmark/semantic-roundtrip-20260726"
    )
    assert DEFAULT_MAX_LANES == 4
    assert DEFAULT_TASK_PREFIX == "## PLAT-"
    assert "typed_deontic" in " ".join(MATERIALIZER_PREDICTED_FILE_PREFIXES)
    assert any(
        p.startswith("benchmarks/semantic_roundtrip/realizers/")
        for p in MATERIALIZER_PREDICTED_FILE_PREFIXES
    )
    assert any(
        p.startswith("tests/unit/benchmarks/semantic_roundtrip/")
        for p in MATERIALIZER_PREDICTED_FILE_PREFIXES
    )
    assert CASE_TO_EDIT_WAVE_TASK["legal_doc_1"] == "PLAT-081"
    assert CASE_TO_EDIT_WAVE_TASK["construction_contract"] == "PLAT-082"
    assert CASE_TO_EDIT_WAVE_TASK["corp_policy_1"] == "PLAT-083"
    assert CASE_TO_EDIT_WAVE_TASK["exec_order_1"] == "PLAT-084"


def test_predicted_file_allowlist_typed_deontic_realizer_tests() -> None:
    assert is_materializer_allowed_path(
        "benchmarks/semantic_roundtrip/constructors/typed_deontic.py"
    )
    assert is_materializer_allowed_path(
        "benchmarks/semantic_roundtrip/realizers/deterministic.py"
    )
    assert is_materializer_allowed_path(
        "tests/unit/benchmarks/semantic_roundtrip/test_typed_constructor.py"
    )
    # Packet-level allowlist may include docs / AE modules; materializer rejects.
    assert not is_materializer_allowed_path(
        "docs/benchmarks/semantic_roundtrip_plateau_codex_packet.md"
    )
    assert not is_materializer_allowed_path(
        "benchmarks/semantic_roundtrip/constructors/modal_spacy.py"
    )
    assert not is_materializer_allowed_path(
        "benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py"
    )
    assert not is_materializer_allowed_path("../secrets.txt")
    assert not is_materializer_allowed_path("/abs/path.py")

    filtered = filter_supervisor_predicted_files(
        [
            "docs/benchmarks/foo.md",
            "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
            "benchmarks/semantic_roundtrip/constructors/modal_spacy.py",
            "benchmarks/semantic_roundtrip/realizers/",
            "tests/unit/benchmarks/semantic_roundtrip/",
        ]
    )
    assert filtered == (
        "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
        "benchmarks/semantic_roundtrip/realizers/",
        "tests/unit/benchmarks/semantic_roundtrip/",
    )

    # Empty / all-rejected falls back to default det. surface.
    fallback = filter_supervisor_predicted_files(
        ["docs/benchmarks/only-docs.md"]
    )
    assert fallback == DEFAULT_MATERIALIZER_PREDICTED_FILES


def test_implementable_packet_becomes_edit_task() -> None:
    packet = _accepted_packet()
    assert packet.implementable is True

    item = materialize_packet(packet)

    assert item.kind is MaterializedKind.IMPLEMENTABLE
    assert item.implementable is True
    assert item.authorize_merge is False
    assert item.semantic_authority is False
    assert item.interface == PLATEAU_SUPERVISOR_TASK_INTERFACE
    assert item.packet_id == packet.packet_id
    assert item.packet_digest == packet.packet_digest
    assert packet.packet_id in item.title
    assert packet.packet_id in item.body
    assert packet.packet_digest[:12] in item.task_id
    assert item.case_id == "legal_doc_1"
    assert item.edit_wave_task_id == "PLAT-081"
    assert item.predicted_files
    for path in item.predicted_files:
        assert is_materializer_allowed_path(path)
    # Must not expand beyond typed_deontic / realizer / tests.
    assert all(
        "typed_deontic" in path
        or path.startswith("benchmarks/semantic_roundtrip/realizers/")
        or path.startswith("tests/unit/benchmarks/semantic_roundtrip/")
        for path in item.predicted_files
    )
    assert item.validation_commands
    assert item.residual_ref_ids == ("resid-legal-object",)
    assert item.proposal_ids == ("prop-leanstral-1",)
    assert item.admitted_field_changes
    assert all(
        change["canonical_field"] == "object"
        for change in item.admitted_field_changes
    )
    payload = item.to_dict()
    assert payload["implementable"] is True
    assert payload["semantic_authority"] is False
    assert payload["authorize_merge"] is False
    assert payload["packet_digest"] == packet.packet_digest

    markdown = item.to_markdown()
    assert item.task_id in markdown
    assert "Predicted files:" in markdown
    assert "Admitted field changes" in markdown


@pytest.mark.parametrize(
    "gate_factory,expected_disposition",
    [
        (_reject_gate, AdmissionDisposition.VALIDATOR_REJECT),
        (_timeout_gate, AdmissionDisposition.TIMEOUT),
        (_error_gate, AdmissionDisposition.ERROR),
    ],
)
def test_non_implementable_packet_becomes_obligation_only_note(
    gate_factory,
    expected_disposition: AdmissionDisposition,
) -> None:
    packet = _rejected_packet(
        gate_factory,
        packet_id=f"pkt-{expected_disposition.value}",
    )
    assert packet.implementable is False
    assert packet.proof_obligation_ids

    item = materialize_packet(packet)

    assert item.kind is MaterializedKind.OBLIGATION_ONLY
    assert item.implementable is False
    assert item.authorize_merge is False
    assert item.semantic_authority is False
    assert item.interface == PLATEAU_SUPERVISOR_NOTE_INTERFACE
    assert item.predicted_files == ()
    assert item.validation_commands == ()
    assert item.admitted_field_changes == ()
    assert item.primary_disposition == expected_disposition.value
    assert item.proof_obligation_ids == packet.proof_obligation_ids
    assert item.proof_obligations
    for obligation in item.proof_obligations:
        assert obligation["semantic_authority"] is False
        assert obligation["obligation_id"] in item.proof_obligation_ids

    markdown = item.to_markdown()
    assert "Obligation-only" in item.title or "obligation" in markdown.lower()
    assert "Proof obligations" in markdown
    assert "Do **not** authorize merge" in markdown
    for oid in item.proof_obligation_ids:
        assert oid in markdown


def test_not_applicable_is_obligation_only_without_edit_surface() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        None,
        gate=_accept_gate(),
    )
    assert admission.disposition is AdmissionDisposition.NOT_APPLICABLE
    packet = build_plateau_codex_packet(
        packet_id="pkt-not-applicable",
        baseline_l1=PRIOR,
        residual_refs=(_residual(),),
        proposals=(),
        admission_results=(admission,),
        case_id="legal_doc_1",
    )
    assert packet.implementable is False

    item = materialize_packet(packet)
    assert item.kind is MaterializedKind.OBLIGATION_ONLY
    assert item.predicted_files == ()
    assert item.authorize_merge is False


def test_materialize_strips_disallowed_predicted_files() -> None:
    packet = _accepted_packet(packet_id="pkt-filter-files")
    # Packet contract allows docs; materializer must drop them.
    wide_files = (
        "docs/benchmarks/semantic_roundtrip_plateau_codex_packet.md",
        "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
        "benchmarks/semantic_roundtrip/constructors/modal_spacy.py",
        "tests/unit/benchmarks/semantic_roundtrip/",
    )
    # Rebuild with wide predicted files via override on materialize.
    item = materialize_packet(
        packet,
        predicted_files_override=wide_files,
    )
    assert item.kind is MaterializedKind.IMPLEMENTABLE
    assert (
        "docs/benchmarks/semantic_roundtrip_plateau_codex_packet.md"
        not in item.predicted_files
    )
    assert (
        "benchmarks/semantic_roundtrip/constructors/modal_spacy.py"
        not in item.predicted_files
    )
    assert (
        "benchmarks/semantic_roundtrip/constructors/typed_deontic.py"
        in item.predicted_files
    )
    assert (
        "tests/unit/benchmarks/semantic_roundtrip/" in item.predicted_files
    )


def test_coerce_packet_and_digest_verification() -> None:
    packet = _accepted_packet(packet_id="pkt-coerce-1")
    as_dict = packet.to_dict()
    as_json = packet.to_json()

    from_obj = coerce_packet(packet)
    from_dict = coerce_packet(as_dict)
    from_json = coerce_packet(as_json)
    assert from_obj.packet_digest == packet.packet_digest
    assert from_dict.packet_digest == packet.packet_digest
    assert from_json.packet_digest == packet.packet_digest

    # Tampered digest fails closed.
    tampered = dict(as_dict)
    tampered["packet_digest"] = "0" * 64
    with pytest.raises(PlateauSupervisorMaterializeError):
        coerce_packet(tampered)

    # Materialize via dict path.
    item = materialize_packet(as_dict)
    assert item.packet_digest == packet.packet_digest


def test_materialize_packets_batch_receipt(tmp_path: Path) -> None:
    accepted = _accepted_packet(packet_id="pkt-batch-accept")
    rejected = _rejected_packet(_reject_gate, packet_id="pkt-batch-reject")

    receipt = materialize_packets(
        [accepted, rejected],
        merge_target_branch=DEFAULT_MERGE_TARGET_BRANCH,
        max_lanes=DEFAULT_MAX_LANES,
    )

    assert receipt.implementable_count == 1
    assert receipt.obligation_only_count == 1
    assert len(receipt.items) == 2
    assert receipt.packet_ids == (accepted.packet_id, rejected.packet_id)
    assert receipt.merge_target_branch == DEFAULT_MERGE_TARGET_BRANCH
    assert receipt.max_lanes == DEFAULT_MAX_LANES
    assert receipt.semantic_authority is False
    assert receipt.receipt_digest
    assert len(receipt.implementable_items()) == 1
    assert len(receipt.obligation_only_items()) == 1

    payload = receipt.to_dict()
    assert payload["interface"] == PLATEAU_SUPERVISOR_MATERIALIZER_INTERFACE
    assert payload["evidence"] == PLATEAU_SUPERVISOR_MATERIALIZER_EVIDENCE
    assert payload["receipt_digest"] == receipt.receipt_digest

    md = receipt.to_markdown()
    assert "Implementable tasks: 1" in md
    assert "Obligation-only notes: 1" in md
    assert DEFAULT_MERGE_TARGET_BRANCH in md
    assert str(DEFAULT_MAX_LANES) in md

    # Round-trip via JSON file loader.
    path = tmp_path / "packets.json"
    path.write_text(
        json.dumps(
            {"packets": [accepted.to_dict(), rejected.to_dict()]},
            indent=2,
        ),
        encoding="utf-8",
    )
    loaded = load_packets_from_json_path(path)
    assert len(loaded) == 2
    again = materialize_packets(loaded)
    assert again.implementable_count == 1
    assert again.obligation_only_count == 1


def test_load_single_packet_json_file(tmp_path: Path) -> None:
    packet = _accepted_packet(packet_id="pkt-file-single")
    path = tmp_path / "one.json"
    path.write_text(packet.to_json(), encoding="utf-8")
    loaded = load_packets_from_json_path(path)
    assert len(loaded) == 1
    assert loaded[0].packet_id == packet.packet_id


def test_launch_spec_lists_bundle_supervisor_flags_merge_branch_max_lanes() -> None:
    spec = default_launch_spec()
    assert isinstance(spec, BundleSupervisorLaunchSpec)
    flags = spec.flags()
    assert flags["module"] == BUNDLE_SUPERVISOR_MODULE
    assert flags["merge_target_branch"] == DEFAULT_MERGE_TARGET_BRANCH
    assert flags["max_lanes"] == DEFAULT_MAX_LANES
    assert flags["task_prefix"] == DEFAULT_TASK_PREFIX
    assert flags["implement"] is True
    assert flags["start"] is True
    assert "bundle_index_path" in flags
    assert "state_root" in flags
    assert "worktree_root" in flags
    assert "repo_root" in flags

    command = spec.to_command()
    assert BUNDLE_SUPERVISOR_MODULE in command
    assert "--max-lanes 4" in command
    assert f"--merge-target-branch {DEFAULT_MERGE_TARGET_BRANCH}" in command
    assert "--implement" in command
    assert "--start" in command
    assert "--bundle-index-path" in command
    assert "--task-prefix" in command
    assert "--state-root" in command
    assert "--worktree-root" in command
    assert "--repo-root" in command

    rendered = render_launch_markdown(spec)
    assert "Merge target branch" in rendered
    assert "Max lanes" in rendered
    assert DEFAULT_MERGE_TARGET_BRANCH in rendered
    assert "4" in rendered
    assert BUNDLE_SUPERVISOR_MODULE in rendered


def test_main_print_launch(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--print-launch"])
    assert rc == 0
    out = capsys.readouterr().out
    assert BUNDLE_SUPERVISOR_MODULE in out
    assert "--max-lanes" in out
    assert "--merge-target-branch" in out


def test_main_materialize_to_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    packet = _accepted_packet(packet_id="pkt-cli-1")
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(packet.to_json(), encoding="utf-8")
    out_json = tmp_path / "receipt.json"
    out_md = tmp_path / "tasks.md"

    rc = main(
        [
            str(packet_path),
            "--output",
            str(out_json),
            "--markdown",
            str(out_md),
        ]
    )
    assert rc == 0
    receipt = json.loads(out_json.read_text(encoding="utf-8"))
    assert receipt["implementable_count"] == 1
    assert receipt["obligation_only_count"] == 0
    md = out_md.read_text(encoding="utf-8")
    assert packet.packet_id in md
    # Quiet when writing files.
    assert capsys.readouterr().out == ""


def test_implementable_defaults_include_typed_deontic_and_tests() -> None:
    # DEFAULT_PREDICTED_FILES from packet contract should already be allowed.
    for path in DEFAULT_PREDICTED_FILES:
        assert is_materializer_allowed_path(path)
    packet = _accepted_packet(packet_id="pkt-default-files")
    item = materialize_packet(packet)
    assert (
        "benchmarks/semantic_roundtrip/constructors/typed_deontic.py"
        in item.predicted_files
        or any("typed_deontic" in p for p in item.predicted_files)
    )
    assert any(
        p.startswith("tests/unit/benchmarks/semantic_roundtrip")
        for p in item.predicted_files
    )


def test_edit_wave_mapping_for_all_nonzero_pilots() -> None:
    for case_id, wave in CASE_TO_EDIT_WAVE_TASK.items():
        packet = _accepted_packet(
            case_id=case_id,
            packet_id=f"pkt-{case_id.replace('_', '-')}",
        )
        item = materialize_packet(packet)
        assert item.edit_wave_task_id == wave
        assert item.case_id == case_id


def test_launch_doc_exists_and_lists_required_launch_fields() -> None:
    root = Path(__file__).resolve().parents[4]
    launch_doc = (
        root
        / "docs"
        / "benchmarks"
        / "semantic_roundtrip_plateau_supervisor_launch.md"
    )
    assert launch_doc.is_file(), f"missing launch doc: {launch_doc}"
    text = launch_doc.read_text(encoding="utf-8")
    assert "bundle_supervisor" in text
    assert "--max-lanes" in text or "max-lanes" in text or "max lanes" in text.lower()
    assert "merge" in text.lower()
    assert DEFAULT_MERGE_TARGET_BRANCH in text
    assert str(DEFAULT_MAX_LANES) in text
    assert BUNDLE_SUPERVISOR_MODULE in text or "bundle_supervisor" in text
    assert "implementable" in text.lower()
    assert "obligation" in text.lower()


# ---------------------------------------------------------------------------
# Holdout population materializer (PLAT2-030)
# ---------------------------------------------------------------------------

HOLDOUT_CONDITIONS_PATH = "rules[0].conditions"
HOLDOUT_PRIOR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
            conditions=("if_requested",),
        ),
    )
)
HOLDOUT_CANDIDATE = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
            conditions=(),
        ),
    )
)


def _holdout_residual(
    residual_id: str = "resid-holdout-conditions",
    case_id: str = "low_confidence_object",
) -> ResidualRef:
    return ResidualRef(
        residual_id=residual_id,
        case_id=case_id,
        field_paths=(HOLDOUT_CONDITIONS_PATH,),
        facet="conditions",
        estimated_forward_contribution=0.1,
        catalog_digest="c" * 64,
        detail="holdout residual for materializer tests",
    )


def _holdout_proposal(
    residual_id: str = "resid-holdout-conditions",
) -> TeacherProposal:
    return TeacherProposal(
        proposal_id="prop-holdout-mat-1",
        teacher="leanstral",
        residual_ref_ids=(residual_id,),
        allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
        candidate_l1=HOLDOUT_CANDIDATE,
        detail="holdout proposal for materializer",
        semantic_authority=False,
    )


def _holdout_accepted_packet(
    *,
    packet_id: str = "holdout-pkt-mat-accept",
    case_id: str = "low_confidence_object",
) -> object:
    residual = _holdout_residual(
        residual_id=f"resid-{case_id}",
        case_id=case_id,
    )
    return build_holdout_packet_from_proposal_admission(
        packet_id=packet_id,
        baseline_l1=HOLDOUT_PRIOR,
        residual_ref=residual,
        proposal=_holdout_proposal(residual_id=residual.residual_id),
        admission=admit_hybrid_repair(
            HOLDOUT_PRIOR,
            HOLDOUT_CANDIDATE,
            gate=_accept_gate(),
            allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
        ),
        case_id=case_id,
    )


def _holdout_rejected_packet(
    gate_factory,
    *,
    packet_id: str = "holdout-pkt-mat-reject",
    case_id: str = "low_confidence_object",
):
    residual = _holdout_residual(
        residual_id=f"resid-{case_id}-rej",
        case_id=case_id,
    )
    return build_holdout_packet_from_proposal_admission(
        packet_id=packet_id,
        baseline_l1=HOLDOUT_PRIOR,
        residual_ref=residual,
        proposal=_holdout_proposal(residual_id=residual.residual_id),
        admission=admit_hybrid_repair(
            HOLDOUT_PRIOR,
            HOLDOUT_CANDIDATE,
            gate=gate_factory(),
            allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
        ),
        case_id=case_id,
    )


def test_holdout_launch_spec_and_constants() -> None:
    assert HOLDOUT_BOARD_NAMESPACE == "semantic-roundtrip-plateau-holdout-v2"
    assert HOLDOUT_TASK_PREFIX == "## PLAT2-"
    assert HOLDOUT_BUNDLE.endswith("plateau-holdout/packets")
    assert HOLDOUT_MAX_LANES == 2
    assert is_holdout_case("low_confidence_object")
    assert is_holdout_case("contradictory_modality")
    assert is_holdout_case("missing_temporal")
    assert not is_holdout_case("legal_doc_1")

    spec = holdout_launch_spec()
    assert spec.task_prefix == HOLDOUT_TASK_PREFIX
    assert spec.board_namespace == HOLDOUT_BOARD_NAMESPACE
    assert spec.max_lanes == HOLDOUT_MAX_LANES
    flags = spec.flags()
    assert flags["task_prefix"] == "## PLAT2-"
    assert "plateau_holdout" in flags["scheduler_config_path"]
    md = render_launch_markdown(spec)
    assert HOLDOUT_TASK_PREFIX in md
    assert HOLDOUT_BOARD_NAMESPACE in md


def test_holdout_implementable_packet_emits_det_only_task() -> None:
    packet = _holdout_accepted_packet()
    assert packet.implementable is True
    assert packet.baseline_e2e == pytest.approx(HOLDOUT_BASELINE_E2E)

    item = materialize_packet(packet)
    assert item.kind is MaterializedKind.IMPLEMENTABLE
    assert item.implementable is True
    assert item.population_kind == "holdout"
    assert item.board_namespace == HOLDOUT_BOARD_NAMESPACE
    assert item.bundle == HOLDOUT_BUNDLE
    assert item.edit_wave_task_id == HOLDOUT_CASE_TO_EDIT_WAVE_TASK[
        "low_confidence_object"
    ]
    assert item.predicted_files
    for path in item.predicted_files:
        assert is_materializer_allowed_path(path)
    # Det. surface only: typed_deontic / realizer / tests.
    assert not any(path.startswith("docs/") for path in item.predicted_files)
    assert item.validation_commands
    assert any("pytest" in cmd for cmd in item.validation_commands)
    # Holdout packets carry holdout validation defaults when built via helpers.
    assert item.validation_commands == DEFAULT_HOLDOUT_VALIDATION_COMMANDS or all(
        isinstance(cmd, str) and cmd.strip() for cmd in item.validation_commands
    )
    assert item.authorize_merge is False
    assert item.semantic_authority is False
    payload = item.to_dict()
    assert payload["population_kind"] == "holdout"
    assert payload["predicted_files"]
    assert payload["validation_commands"]
    md = item.to_markdown()
    assert "Predicted files:" in md
    assert "Validation:" in md
    assert HOLDOUT_BOARD_NAMESPACE in md
    assert "Holdout case" in item.body


@pytest.mark.parametrize(
    "gate_factory,expected_disposition",
    [
        (_reject_gate, AdmissionDisposition.VALIDATOR_REJECT),
        (_timeout_gate, AdmissionDisposition.TIMEOUT),
        (_error_gate, AdmissionDisposition.ERROR),
    ],
)
def test_holdout_non_implementable_becomes_obligation_only(
    gate_factory, expected_disposition: AdmissionDisposition
) -> None:
    packet = _holdout_rejected_packet(
        gate_factory,
        packet_id=f"holdout-pkt-{expected_disposition.value}",
    )
    assert packet.implementable is False
    item = materialize_packet(packet)
    assert item.kind is MaterializedKind.OBLIGATION_ONLY
    assert item.implementable is False
    assert item.predicted_files == ()
    assert item.validation_commands == ()
    assert item.authorize_merge is False
    assert item.population_kind == "holdout"
    assert item.board_namespace == HOLDOUT_BOARD_NAMESPACE
    assert item.primary_disposition == expected_disposition.value


def test_materialize_holdout_packets_one_task_per_implementable() -> None:
    accepted_a = _holdout_accepted_packet(
        packet_id="holdout-pkt-batch-a",
        case_id="low_confidence_object",
    )
    accepted_b = _holdout_accepted_packet(
        packet_id="holdout-pkt-batch-b",
        case_id="contradictory_modality",
    )
    rejected = _holdout_rejected_packet(
        _reject_gate, packet_id="holdout-pkt-batch-rej"
    )

    receipt = materialize_holdout_packets([accepted_a, accepted_b, rejected])
    assert receipt.implementable_count == 2
    assert receipt.obligation_only_count == 1
    assert len(receipt.items) == 3
    assert len(receipt.implementable_items()) == 2

    for item in receipt.implementable_items():
        assert item.kind is MaterializedKind.IMPLEMENTABLE
        assert item.predicted_files
        for path in item.predicted_files:
            assert is_materializer_allowed_path(path)
        assert item.validation_commands
        assert item.board_namespace == HOLDOUT_BOARD_NAMESPACE
        assert item.bundle == HOLDOUT_BUNDLE
        assert item.population_kind == "holdout"

    obligation = receipt.obligation_only_items()[0]
    assert obligation.predicted_files == ()
    assert obligation.implementable is False

    # Pilot materialize path remains on pilot board namespace.
    pilot = _accepted_packet(packet_id="pkt-pilot-ns-check")
    pilot_item = materialize_packet(pilot)
    assert pilot_item.board_namespace == DEFAULT_BOARD_NAMESPACE
    assert pilot_item.population_kind is None


def test_holdout_edit_wave_mapping_for_registered_cases() -> None:
    # Limit to the original transitional holdout fixture cases (shared prior/candidate).
    for case_id in (
        "missing_temporal",
        "low_confidence_object",
        "contradictory_modality",
    ):
        wave = HOLDOUT_CASE_TO_EDIT_WAVE_TASK[case_id]
        packet = _holdout_accepted_packet(
            case_id=case_id,
            packet_id=f"holdout-pkt-{case_id.replace('_', '-')}",
        )
        item = materialize_packet(packet)
        assert item.edit_wave_task_id == wave
        assert item.case_id == case_id
        assert item.population_kind == "holdout"


# ---------------------------------------------------------------------------
# Repair-development materializer (PLAT2-030 normative path)
# ---------------------------------------------------------------------------


def _repair_dev_residual(
    residual_id: str = "resid-repair-dev-mat",
    case_id: str = "low_confidence_object",
):
    from benchmarks.semantic_roundtrip.plateau_codex_packet import ResidualRef

    return ResidualRef(
        residual_id=residual_id,
        case_id=case_id,
        field_paths=(HOLDOUT_CONDITIONS_PATH,),
        facet="conditions",
        estimated_forward_contribution=0.1,
        catalog_digest="e" * 64,
        detail="repair_development residual for materializer tests",
    )


def _repair_dev_proposal(residual_id: str = "resid-repair-dev-mat"):
    from benchmarks.semantic_roundtrip.plateau_codex_packet import TeacherProposal

    return TeacherProposal(
        proposal_id="prop-repair-dev-mat-1",
        teacher="leanstral",
        residual_ref_ids=(residual_id,),
        allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
        candidate_l1=HOLDOUT_CANDIDATE,
        detail="repair_development proposal for materializer",
        semantic_authority=False,
    )


def _repair_dev_accepted_packet(
    *,
    packet_id: str = "repair-dev-pkt-mat-accept",
    case_id: str = "low_confidence_object",
    catalog: dict | None = None,
):
    residual = _repair_dev_residual(
        residual_id=f"resid-{case_id}-rd",
        case_id=case_id,
    )
    return build_repair_dev_packet_from_proposal_admission(
        packet_id=packet_id,
        baseline_l1=HOLDOUT_PRIOR,
        residual_ref=residual,
        proposal=_repair_dev_proposal(residual_id=residual.residual_id),
        admission=admit_hybrid_repair(
            HOLDOUT_PRIOR,
            HOLDOUT_CANDIDATE,
            gate=_accept_gate(),
            allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
        ),
        case_id=case_id,
        catalog=catalog,
        require_repair_dev_evidence=catalog is not None,
    )


def test_repair_dev_launch_spec_and_materialize_det_only() -> None:
    assert REPAIR_DEV_BOARD_NAMESPACE == HOLDOUT_BOARD_NAMESPACE
    assert REPAIR_DEV_BUNDLE == HOLDOUT_BUNDLE
    assert is_holdout_case("legal_doc_2")
    assert is_holdout_case("hr_handbook")
    assert REPAIR_DEV_CASE_TO_EDIT_WAVE_TASK["legal_doc_2"] == "PLAT2-050"

    spec = repair_dev_launch_spec()
    assert spec.board_namespace == REPAIR_DEV_BOARD_NAMESPACE
    assert spec.task_prefix == HOLDOUT_TASK_PREFIX

    catalog = json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "workspace"
            / "benchmarks"
            / "semantic-roundtrip-compositions"
            / "repair_dev_residual_catalog.json"
        ).read_text(encoding="utf-8")
    )
    packet = _repair_dev_accepted_packet(catalog=catalog)
    assert packet.implementable is True
    assert packet.population_kind == REPAIR_DEV_POPULATION_KIND
    assert is_repair_dev_packet(packet)

    item = materialize_packet(packet)
    assert item.kind is MaterializedKind.IMPLEMENTABLE
    assert item.population_kind == REPAIR_DEV_POPULATION_KIND
    assert item.board_namespace == REPAIR_DEV_BOARD_NAMESPACE
    assert item.bundle == REPAIR_DEV_BUNDLE
    assert item.predicted_files
    for path in item.predicted_files:
        assert is_materializer_allowed_path(path)
    assert not any(path.startswith("docs/") for path in item.predicted_files)
    assert item.validation_commands == DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    assert any("test_holdout_baseline" in cmd for cmd in item.validation_commands)
    assert any(
        "test_plateau_codex_packet" in cmd for cmd in item.validation_commands
    )
    assert any(
        "test_structural_admission" in cmd for cmd in item.validation_commands
    )
    assert "Repair-development case" in item.body
    assert item.authorize_merge is False
    assert item.semantic_authority is False


def test_materialize_repair_dev_packets_batch() -> None:
    catalog = json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "workspace"
            / "benchmarks"
            / "semantic-roundtrip-compositions"
            / "repair_dev_residual_catalog.json"
        ).read_text(encoding="utf-8")
    )
    accepted = _repair_dev_accepted_packet(
        packet_id="repair-dev-pkt-batch-a",
        catalog=catalog,
    )
    rejected = build_repair_dev_packet_from_proposal_admission(
        packet_id="repair-dev-pkt-batch-rej",
        baseline_l1=HOLDOUT_PRIOR,
        residual_ref=_repair_dev_residual(residual_id="resid-rd-rej"),
        proposal=_repair_dev_proposal(residual_id="resid-rd-rej"),
        admission=admit_hybrid_repair(
            HOLDOUT_PRIOR,
            HOLDOUT_CANDIDATE,
            gate=_reject_gate(),
            allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
        ),
        catalog=catalog,
    )
    assert rejected.implementable is False

    receipt = materialize_repair_dev_packets([accepted, rejected])
    assert receipt.implementable_count == 1
    assert receipt.obligation_only_count == 1
    impl = receipt.implementable_items()[0]
    assert impl.population_kind == REPAIR_DEV_POPULATION_KIND
    assert impl.board_namespace == REPAIR_DEV_BOARD_NAMESPACE
    assert impl.predicted_files
    for path in impl.predicted_files:
        assert is_materializer_allowed_path(path)
    assert impl.validation_commands
    obligation = receipt.obligation_only_items()[0]
    assert obligation.predicted_files == ()
    assert obligation.implementable is False
