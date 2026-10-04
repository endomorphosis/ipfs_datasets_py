"""Cross-family replay contracts and an actual bounded Lean Lake build."""
from dataclasses import replace
import hashlib
from pathlib import Path
import re
import shutil
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import (
    canonical_bytes, make_projection, validate_projection, source_ir_sha256,
)
from ipfs_datasets_py.logic.intent_ir.formalize.lean_projection import project_lean_family, validate_lean_projection
from ipfs_datasets_py.logic.intent_ir.formalize.extended_projections import (
    DEFAULT_FAMILIES, ADDITIONAL_REQUIREMENTS, project_intent_families, validate_intent_family_report,
)
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
from ipfs_datasets_py.logic.intent_ir.schema import IntentModality, StatementKind


def document(modality="required"):
    return frame_to_intent_ir({"actor": "agent", "action": "read", "object": "cache", "modality": modality},
                             instruction="The agent should inspect the declared cache.")


def resign(report, field):
    report = {key: value for key, value in report.items() if key != field}
    report[field] = hashlib.sha256(canonical_bytes(report)).hexdigest()
    return report


class MustNotExecute:
    def is_available(self, *args, **kwargs):
        pytest.fail("untrusted or unsupported Lean report reached executable discovery")

    def run(self, *args, **kwargs):
        pytest.fail("untrusted or unsupported Lean report reached a process")


def test_registered_default_family_coverage_and_tla_profile():
    doc = document()
    report = project_intent_families(doc)
    assert set(row["family_id"] for row in report["projections"]) == set(DEFAULT_FAMILIES)
    assert any(row["family_id"] == "transition_system" and row["profile_id"] == "tla_plus"
               for row in report["projections"])
    assert len({row["projection_id"] for row in report["projections"]}) == len(report["projections"])
    assert report["source_ir_sha256"] == source_ir_sha256(doc)
    assert report["external_backend_calls"] == 0
    assert report["training_executed"] is report["proof_authority"] is False
    assert "backend_proofs_not_run" in report["native_targets"]["qualification_gaps"]
    assert validate_intent_family_report(report, doc) == report


def test_explicit_family_selection_keeps_missing_models_visible():
    doc = document()
    requested = ["dcec", "separation_logic", "hyperproperty", "epistemic"]
    report = project_intent_families(doc, requested_families=requested)
    rows = {row["family_id"]: row for row in report["projections"]}
    assert set(rows) == set(requested)
    for family in requested[1:]:
        assert rows[family]["status"] == "unsupported"
        assert rows[family]["validation"][0]["status"] == "not_run"
        assert rows[family]["unsupported"][0]["reason"] == ADDITIONAL_REQUIREMENTS[family]
    assert report["all_requested_families_projected"] is False


@pytest.mark.parametrize("families", [[], ["dcec", "dcec"], ["lake"], ["safety"]])
def test_family_selection_rejects_ambiguous_or_wrong_namespaces(families):
    with pytest.raises(ValueError):
        project_intent_families(document(), requested_families=families)


@pytest.mark.parametrize("context", [{"pretend_proved": {}}, {"modal": []}, {"state": "approved"}])
def test_context_namespaces_are_closed(context):
    with pytest.raises(ValueError):
        project_intent_families(document(), context=context)


def test_source_and_authority_tampering_rejected_even_with_new_hashes():
    doc = document()
    report = project_lean_family(doc)
    with pytest.raises(ValueError, match="source, authority"):
        validate_projection(resign({**report, "proof_authority": True}, "projection_sha256"), doc)
    with pytest.raises(ValueError, match="source, authority"):
        validate_projection(report, document("prohibited"))
    with pytest.raises(ValueError, match="fields"):
        validate_projection({**report, "claimed_verified": True}, doc)


def test_contract_rejects_unknown_nodes_profiles_and_hidden_losses():
    doc = document()
    with pytest.raises(ValueError, match="unknown or duplicate"):
        make_projection(doc, family_id="dcec", representation={"format": "test"}, source_node_ids=["absent"])
    with pytest.raises((ValueError, KeyError)):
        make_projection(doc, family_id="dcec", profile_id="not-a-registered-profile", representation={"format": "test"})
    with pytest.raises(ValueError, match="cannot hide"):
        make_projection(doc, family_id="dcec", representation={"format": "test"}, status="projected",
                        unsupported=[{"node_id": "goal", "reason": "unsupported modality"}])


def test_lean_reports_define_interpretations_without_asserting_them():
    doc = document("prohibited")
    report = project_lean_family(doc)
    source = report["representation"]["source"]
    assert "structure Interpretation where" in source
    assert "prohibited : Prop → Prop" in source
    assert "i.prohibited (i.atom" in source
    assert not re.search(r"(?m)^\s*(?:axiom|theorem|unsafe|#eval|run_cmd)\b", source)
    assert not re.search(r"\b(?:sorry|admit)\b", source)
    assert report["validation"][0]["status"] == "not_run"
    assert report["status"] == "partial"  # The action's operational semantics are still separate.
    assert any(row["node_id"] == "action" for row in report["unsupported"])


def test_asserted_goal_preserves_native_intention_convention():
    doc = document()
    doc = replace(doc, statements=(replace(doc.statements[0], modality=IntentModality.ASSERTED),))
    report = project_lean_family(doc)
    assert "i.intended (i.atom" in report["representation"]["source"]
    row = report["representation"]["payload"]["statements"][0]
    assert row["modality"] == "asserted" and row["effective_modality"] == "intended"


def test_tampered_and_resigned_lean_source_rejected_before_discovery():
    doc = document()
    report = project_lean_family(doc)
    representation = {**report["representation"], "source": report["representation"]["source"] + "\n#eval IO.println 1\n"}
    modified = resign({**report, "representation": representation}, "projection_sha256")
    # A hash validates an envelope, not a generator. The external gate must replay the producer.
    validate_projection(modified, doc)
    with pytest.raises(ValueError, match="exact generated"):
        validate_lean_projection(modified, doc, runner=MustNotExecute())


def test_resigned_aggregate_also_requires_deterministic_replay():
    doc = document()
    report = project_intent_families(doc, requested_families=["higher_order"])
    altered = {**report, "external_backend_calls": 1}
    with pytest.raises(ValueError, match="deterministic source replay"):
        validate_intent_family_report(resign(altered, "report_sha256"), doc)


def test_unsupported_lean_input_does_not_run_vacuous_build():
    doc = document()
    doc = replace(doc, statements=(replace(doc.statements[0], predicate=""),))
    report = project_lean_family(doc)
    assert report["status"] == "unsupported"
    result = validate_lean_projection(report, doc, runner=MustNotExecute())
    assert result["status"] == "not_run"
    assert result["backend_executed"] is result["syntax_valid"] is False


def test_missing_lake_is_unavailable_not_verified():
    class MissingRunner:
        def is_available(self, executable):
            return False

        def run(self, request):
            pytest.fail("missing backend was executed")

    doc = document()
    result = validate_lean_projection(project_lean_family(doc), doc, runner=MissingRunner())
    assert result["status"] == "unavailable"
    assert result["backend_executed"] is result["syntax_valid"] is result["proof_authority"] is False


def test_explicit_mismatched_toolchain_never_reaches_build():
    class VersionOnlyRunner:
        def __init__(self):
            self.calls = []

        def is_available(self, executable):
            return True

        def run(self, request):
            self.calls.append(request.argv)
            assert request.argv[-1] == "--version", "mismatched toolchain attempted a build or download"
            return SimpleNamespace(ok=True, returncode=0, stdout="Lake version 5.0.0 (Lean version 4.34.1)", stderr="")

    runtime = VersionOnlyRunner()
    doc = document()
    result = validate_lean_projection(project_lean_family(doc), doc, runner=runtime,
        lake_executable="/opt/standalone/bin/lake", toolchain="leanprover/lean4:v99.0.0")
    assert result["status"] == "unavailable"
    assert result["reason"] == "requested_toolchain_does_not_match_installed_lake"
    assert result["backend_executed"] is False
    assert len(runtime.calls) == 1


@pytest.mark.parametrize("timeout", [True, 0, 61, float("nan")])
def test_external_timeout_is_bounded_before_discovery(timeout):
    doc = document()
    with pytest.raises(ValueError, match="timeout"):
        validate_lean_projection(project_lean_family(doc), doc, timeout_seconds=timeout, runner=MustNotExecute())


def test_actual_lake_build_multimodality_unicode_and_escaped_strings():
    native = Path.home() / ".elan/toolchains/leanprover--lean4---v4.34.1/bin/lake"
    executable = str(native) if native.is_file() else shutil.which("lake")
    if not executable:
        pytest.skip("installed Lake executable required for actual compiler integration")
    doc = document()
    modalities = tuple(IntentModality)
    statements = tuple(replace(doc.statements[0], statement_id="decl-" + modality.value,
        kind=StatementKind.ASSUMPTION, modality=modality,
        arguments=('cache "quoted" \\ path', "δοκιμή 日本語 🙂", "line\nsecond\tcolumn")) for modality in modalities)
    doc = replace(doc, statements=(*doc.statements, *statements), actions=(), entry_action_ids=(), terminal_action_ids=())
    report = project_lean_family(doc)
    result = validate_lean_projection(report, doc, lake_executable=executable,
                                     toolchain="leanprover/lean4:v4.34.1", timeout_seconds=30)
    assert result["status"] == "passed", result
    assert result["syntax_valid"] is result["typecheck_valid"] is result["backend_executed"] is True
    assert result["proof_authority"] is result["proof_obligations_discharged"] is False
    assert result["source_semantics_verified"] is result["program_correctness_verified"] is False
    assert result["dependencies"] == []
    assert [row["stage"] for row in result["observations"]] == ["version", "build"]
    assert all(row["returncode"] == 0 for row in result["observations"])
