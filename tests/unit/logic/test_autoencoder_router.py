"""Infer first. Train and the router run only when that inference fails."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.autoformal.autoencoder_router import (
    agrees_with_compiler,
    inference_from_bridge_receipt,
    run_inference_then_router,
)


@pytest.mark.parametrize("source,rendered,missing", [
    ("Use Square 580 up to I–395.", "Use Square up to I.", ["580", "i-395"]),
    ("Use Square 580 up to I–395.", "Use Square 1580 up to I-3950.", ["580", "i-395"]),
    ("Use I–395.", "Use I-395.", []),
    ("Pay 12.5 dollars.", "Pay 12 dollars.", ["12.5"]),
    ("Pay 5 dollars and retain 5 records.", "Pay 5 dollars and retain records.", ["5"]),
    ("§ 2186. Square 580 landscape maintenance\nUse Square 580 up to I–395.",
     "Use Square 580 up to I-395.", []),
    ("§ 2186. Square 580 landscape maintenance\nUse Square 580 up to I–395.",
     "Use Square up to I.", ["580", "i-395"]),
    ("Follow § 2186 within 10 days.", "Follow the rule within 10 days.", ["2186"]),
    ("§ 5 The agency shall pay 10 dollars.\nThe agency shall retain records.",
     "The agency must retain records.", ["10", "5"]),
])
def test_source_numeric_surfaces_are_independent_of_candidate_parser(source, rendered, missing):
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import source_surface_diagnostics
    assert source_surface_diagnostics(source, rendered)["missing_numeric_surfaces"] == missing


@pytest.mark.parametrize("actor", [
    "For fiscal year 2016, the Architect of the Capitol",
    "the Architect of the Capitol, in consultation with the District of Columbia",
    "Square 580 landscape maintenance the Architect of the Capitol",
    "Subject to paragraph (2), the Secretary",
])
def test_actor_cannot_absorb_heading_or_known_scope_prefix(actor):
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import source_surface_diagnostics
    source = "§ 2186. Square 580 landscape maintenance\nThe Architect may maintain Square 580."
    assert source_surface_diagnostics(source, source, actors=[actor])["actor_scope_issues"] == [actor]
    assert not source_surface_diagnostics(source, source, actors=["the Architect of the Capitol"])["actor_scope_issues"]


def test_census_rejects_missing_number_even_when_parser_dependent_checks_agree(monkeypatch):
    from ipfs_datasets_py.logic import autoformal
    from ipfs_datasets_py.logic.autoformal import autoencoder_router as router, ontology_capture
    # Model an evaluator blind spot without using a proposed compiler as oracle.
    monkeypatch.setattr(autoformal, "compile_span", lambda *a, **k: {
        "compiler_status": "compiled", "fields": [], "decompiled": "The officer may use Square."})
    monkeypatch.setattr(ontology_capture, "dropped_clauses", lambda *a: [])
    monkeypatch.setattr(ontology_capture, "missing_qualifier_surfaces", lambda *a: [])
    monkeypatch.setattr(router, "_capture_for_first_clause", lambda *a: {})
    result = router.agreement_census([{"id": "scope", "text": "The officer may use Square 580."}], {})
    assert not result["agrees"]
    assert result["rows"][0]["source_integrity"]["missing_numeric_surfaces"] == ["580"]
    assert result["rows"][0]["reason"] == "dropped_clause"


def test_census_checks_actual_actor_slot_not_just_rendered_surface(monkeypatch):
    from ipfs_datasets_py.logic import autoformal
    from ipfs_datasets_py.logic.autoformal import autoencoder_router as router, ontology_capture
    text = "For fiscal year 2016, the Architect may maintain records."
    def compile_one(session, *args, **kwargs):
        session.rows.append(autoformal.RuleRow("scope", "clause", 0, len(text), "frame",
            rule={"actor": "For fiscal year 2016, the Architect"}, status="compiled", decompiled=text))
        return {"compiler_status": "compiled", "fields": [], "decompiled": text}
    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    monkeypatch.setattr(ontology_capture, "dropped_clauses", lambda *a: [])
    monkeypatch.setattr(ontology_capture, "missing_qualifier_surfaces", lambda *a: [])
    monkeypatch.setattr(router, "_capture_for_first_clause", lambda *a: {})
    result = router.agreement_census([{"id": "scope", "text": text}], {})
    assert not result["agrees"]
    assert result["rows"][0]["reason"] == "compiler_abstain:actor_scope_contamination"
    assert result["rows"][0]["source_integrity"]["actor_scope_issues"]


def _extension_fixture():
    import hashlib
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import canonical_bytes, repair_packets
    from ipfs_datasets_py.logic.autoformal.extended_repair import extension_packet
    from ipfs_datasets_py.logic.legal_ir.extended_contracts import ExtendedLegalIR, PolicyV2
    parent = repair_packets({"rows": [{"id": "source-policy", "text": "Council supports—\n(1) retaining reports.",
                                      "reason": "compiler_abstain", "agrees": False}]},
                            release_id="pinned-release", code_identity="old-compiler", model_identity="model")[0]
    before = canonical_bytes(parent["packet"])
    item = extension_packet(parent["packet"], parent["sha256"], code_identity="extended-compiler",
                            family="policy", expected_ir=ExtendedLegalIR((PolicyV2("Council", "supports", ("retaining reports",)),)).to_dict())
    assert canonical_bytes(parent["packet"]) == before
    assert hashlib.sha256(canonical_bytes(item["packet"])).hexdigest() == item["sha256"]
    return parent, item


def test_extended_contract_is_strict_and_not_a_v1_modality_extension():
    from dataclasses import FrozenInstanceError
    from ipfs_datasets_py.logic.legal_ir.extended_contracts import DefinitionV2, PolicyV2, ExtendedLegalIR
    definition = DefinitionV2("record", "means", "an account", scope=("this section",))
    policy = PolicyV2("Congress", "supports", ("retaining 17 reports", "publishing 29 notices"))
    ir = ExtendedLegalIR((definition, policy))
    assert ExtendedLegalIR.from_dict(ir.to_dict()) == ir
    with pytest.raises(FrozenInstanceError):
        definition.term = "changed"
    with pytest.raises(ValueError):
        DefinitionV2("record", "O", "an account")
    with pytest.raises(ValueError):
        PolicyV2("Congress", "O", ("retain records",))
    with pytest.raises(ValueError):
        ExtendedLegalIR.from_dict({**ir.to_dict(), "source_text": "hidden channel"})
    bad = ir.to_dict()
    bad["statements"][0]["modality"] = "O"
    with pytest.raises(ValueError):
        ExtendedLegalIR.from_dict(bad)


@pytest.mark.parametrize("bad", ["", " padded ", "multi\nline", "embedded\x00null", "x" * 16385])
def test_extended_atoms_are_bounded_and_cannot_carry_multiline_source(bad):
    from ipfs_datasets_py.logic.legal_ir.extended_contracts import DefinitionV2
    with pytest.raises(ValueError):
        DefinitionV2(bad, "means", "an account")


def test_extended_task_has_new_identity_scope_and_immutable_parent():
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import repair_outputs
    parent, item = _extension_fixture()
    assert item["sha256"] != parent["sha256"]
    assert item["packet"]["row"]["text_sha256"] == parent["packet"]["row"]["text_sha256"]
    assert item["packet"]["extension"]["parent_packet_sha256"] == parent["sha256"]
    outputs = repair_outputs(item["packet"], item["sha256"])
    assert outputs[:2] == ["ipfs_datasets_py/logic/legal_ir/extended_compiler.py", "ipfs_datasets_py/logic/legal_ir/extended_decompiler.py"]
    assert all("canonical_" not in path for path in outputs)
    assert item["packet"]["admitted"] is False


def test_extension_metadata_cannot_reinterpret_a_legacy_task():
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import repair_outputs, RepairQueueError
    parent, item = _extension_fixture()
    parent["packet"]["extension"] = item["packet"]["extension"]
    with pytest.raises(RepairQueueError, match="reinterpret"):
        repair_outputs(parent["packet"], parent["sha256"])


@pytest.mark.parametrize("field,value", [("parent_packet_sha256", "0" * 64), ("parent_source_sha256", "0" * 64),
                                       ("family", "definition"), ("schema", "unknown")])
def test_extension_contract_rejects_lineage_and_kind_drift(field, value):
    from ipfs_datasets_py.logic.autoformal.extended_repair import validate_extension
    _, item = _extension_fixture()
    item["packet"]["extension"][field] = value
    with pytest.raises(ValueError):
        validate_extension(item["packet"])


def test_extension_gate_rejects_passthrough_and_abstention_as_success():
    from ipfs_datasets_py.logic.autoformal.extended_repair import replay_extension
    _, item = _extension_fixture()
    for compiler in (lambda text: text, lambda text: None, lambda text: {"source_text": text}):
        result = replay_extension(item["packet"], compiler=compiler, renderer=lambda _: "unused")
        assert not result["passed"] and result["formalized"] is False
        assert result["parent_task_completed"] is False


def test_extension_gate_positive_fixture_and_mutation_checks():
    """Injected oracle tests the gate; it is not evidence of a real compiler."""
    import hashlib
    from ipfs_datasets_py.logic.autoformal.extended_repair import replay_extension, contract_cases
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import canonical_bytes
    from ipfs_datasets_py.logic.legal_ir.extended_contracts import ExtendedLegalIR
    _, item = _extension_fixture()
    packet = item["packet"]
    cases = [{"text": packet["row"]["text"], "expected_ir": packet["extension"]["expected_ir"]},
             *contract_cases("policy", seed=hashlib.sha256(canonical_bytes(packet)).hexdigest())]
    by_text = {case["text"]: ExtendedLegalIR.from_dict(case["expected_ir"]) if case["expected_ir"] else None for case in cases}
    by_ir = {json.dumps(value.to_dict(), sort_keys=True): text for text, value in by_text.items() if value}
    compiler = by_text.get
    good = replay_extension(packet, compiler=compiler, renderer=lambda ir: by_ir[json.dumps(ir.to_dict(), sort_keys=True)])
    assert good["passed"] and good["admitted"] is False
    bad = replay_extension(packet, compiler=compiler, renderer=lambda ir: "Council supports retaining reports.")
    assert not bad["passed"]


def test_extension_v3_does_not_rewrite_v2_acceptance_cases():
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal.extended_repair import (
        CONTRACT, LEGACY_CONTRACT, contract_cases, replay_extension, validate_extension,
    )
    _, item = _extension_fixture()
    current = item["packet"]
    old = deepcopy(current)
    old["extension"]["schema"] = LEGACY_CONTRACT
    assert validate_extension(old)["schema"] == LEGACY_CONTRACT
    assert current["extension"]["schema"] == CONTRACT
    old_cases = contract_cases("policy", seed="regression", contract=LEGACY_CONTRACT)
    new_cases = contract_cases("policy", seed="regression", contract=CONTRACT)
    assert len(old_cases) == 3
    assert old_cases == new_cases[:3]
    assert len(new_cases) == 10
    assert replay_extension(old, compiler=lambda _: None)["checked_count"] == 4
    assert replay_extension(current, compiler=lambda _: None)["checked_count"] == 11
    with pytest.raises(ValueError, match="acceptance contract"):
        contract_cases("policy", contract="unreviewed")


@pytest.mark.parametrize("mutated_case", [
    "unrepresented_list_disjunction_must_abstain",
    "operative_heading_must_not_disappear",
    "unpunctuated_atom_is_not_a_connector",
    "repeated_conditions_must_all_survive",
    "outline_labels_must_not_be_renumbered",
    "duplicate_outline_labels_must_abstain",
    "policy_list_followed_by_permission_must_abstain",
])
def test_extension_v3_gate_rejects_each_observed_policy_loss(mutated_case):
    """Test the evaluator with injected mutants, not a compiler success claim."""
    import hashlib
    from ipfs_datasets_py.logic.autoformal.extended_repair import contract_cases, replay_extension
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import canonical_bytes
    from ipfs_datasets_py.logic.legal_ir.extended_contracts import ExtendedLegalIR
    _, item = _extension_fixture()
    packet = item["packet"]
    cases = [{"name": "source", "text": packet["row"]["text"], "expected_ir": packet["extension"]["expected_ir"]},
             *contract_cases("policy", seed=hashlib.sha256(canonical_bytes(packet)).hexdigest())]
    by_text = {case["text"]: ExtendedLegalIR.from_dict(case["expected_ir"]) if case["expected_ir"] else None for case in cases}
    by_ir = {json.dumps(ir.to_dict(), sort_keys=True): text for text, ir in by_text.items() if ir}
    target = next(case for case in cases if case["name"] == mutated_case)
    incorrect = ExtendedLegalIR.from_dict(packet["extension"]["expected_ir"])
    def mutant(text):
        return incorrect if text == target["text"] else by_text.get(text)
    result = replay_extension(packet, compiler=mutant,
                              renderer=lambda ir: by_ir[json.dumps(ir.to_dict(), sort_keys=True)])
    assert not result["passed"]
    assert [row["case"] for row in result["failures"]] == [mutated_case]
    assert not result["admitted"] and not result["formalized"]


def test_the_router_prompt_asks_for_an_inference_match_and_lake_admission() -> None:
    seen = {}

    def infer(samples):
        return {"ok": True, "captures": [{"sample_id": "backup", "triples": [], "admitted": False}]}

    def train(samples):
        raise AssertionError("training must not run")

    def generate(prompt, **kwargs):
        seen["prompt"] = prompt
        return json.dumps({
            "compiler": "def compile(text, capture=None):\n    return {'match': True}\n",
            "decompiler": "def decompile(rule):\n    return '10 days'\n",
        })

    result = run_inference_then_router(
        ["backup"],
        infer=infer,
        train=train,
        generate=generate,
        agree=lambda samples, inference: {"agrees": False, "reason": "compiler_abstain"},
    )
    assert "Emit an edit" in seen["prompt"]
    assert "compiler_abstain" in seen["prompt"]
    assert "lake build Legal" in seen["prompt"]
    assert "A match is not an admit" in seen["prompt"]
    assert result["router_called"] is True
    assert result["agrees"] is False
    assert result["admitted"] is False


def test_router_generate_leaves_model_and_provider_unset(monkeypatch) -> None:
    from ipfs_datasets_py.logic.autoformal import autoencoder_router as router_mod

    seen = {}

    class _Module:
        def generate_text(self, prompt, **kwargs):
            seen["prompt"] = prompt
            seen["kwargs"] = kwargs
            return "ok"

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.leanstral_audit.resolve_leanstral_llm_router",
        lambda: (_Module(), {}),
    )
    assert router_mod.llm_router_generate("write both", temperature=0, provider="llm_router") == "ok"
    assert seen["kwargs"]["temperature"] == 0
    assert seen["kwargs"]["task_kind"] == "legal"
    assert "model_name" not in seen["kwargs"]
    assert "provider" not in seen["kwargs"]


def test_a_gap_todo_carries_the_failure_features_and_acceptance_test() -> None:
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import (
        integrate_when_agreed,
        ir_edit_todo,
    )

    todo = ir_edit_todo({
        "id": "amend-1.span-1",
        "text": "Congress shall make no law abridging the freedom of speech, or of the press.",
        "reason": "dropped_clause",
        "dropped": ["speech", "press"],
        "decompiled": "Congress must make no law respecting an establishment of religion.",
        "capture": {
            "recipient": {"surface": ""},
            "procedure": {"procedure_id": ""},
            "triples": [{"subject": "amend-1", "predicate": "object", "object": "speech"}],
        },
    })
    metadata = todo.metadata
    assert metadata["failure_mode"] == "dropped_clause"
    assert metadata["autoencoder_features"]["triples"][0]["object"] == "speech"
    assert "speech" in metadata["acceptance"]["must_contain"]
    assert "press" in metadata["acceptance"]["must_contain"]
    assert metadata["acceptance"]["match_is_not_admit"] is True
    refused = integrate_when_agreed(todo, "Congress must make no law.")
    assert refused["integrated"] is False
    assert refused["admitted"] is False
    assert todo.status == "failed_validation"
    fixed = ir_edit_todo({
        "id": "amend-1.span-1",
        "text": metadata["source_text"],
        "reason": "dropped_clause",
        "dropped": ["speech", "press"],
        "decompiled": metadata["decompiled"],
        "capture": {
            "triples": [{"subject": "amend-1", "predicate": "object", "object": "speech"}],
            "recipient": {"surface": ""},
            "procedure": {},
        },
    })
    accepted = integrate_when_agreed(
        fixed,
        "Congress must make no law abridging the freedom of speech, or of the press.",
    )
    assert accepted["integrated"] is True
    assert accepted["admitted"] is False
    assert fixed.status == "completed"


def test_a_complete_target_count_is_inference_and_not_an_admit() -> None:
    receipt = {"bridge": {"legal_ir_target_count": 3}}
    assert inference_from_bridge_receipt(receipt, 3)["ok"] is True
    assert inference_from_bridge_receipt(receipt, 4)["ok"] is False
    assert inference_from_bridge_receipt(receipt, 3)["admitted"] is False


def test_working_inference_projects_features_without_training() -> None:
    order = []

    def infer(samples):
        order.append("infer")
        return {"ok": True, "captures": [{"sample_id": "span", "admitted": False}]}

    def train(samples):
        order.append("train")
        return {"accepted_epochs": 1}

    def generate(prompt, **kwargs):
        order.append(("router", kwargs.get("temperature")))
        assert "span" in prompt
        return json.dumps({
            "compiler": "def compile(text):\n    return {}\n",
            "decompiler": "def decompile(rule):\n    return 'ok'\n",
        })

    def agree(samples, inference):
        order.append("agree")
        return {"agrees": True, "reason": ""}

    result = run_inference_then_router(
        ["span"],
        infer=infer,
        train=train,
        generate=generate,
        agree=agree,
    )
    assert order == ["infer", "agree"]
    assert result["trained"] is False
    assert result["router_called"] is False
    assert result["agrees"] is True
    assert result["admitted"] is False


def test_failed_inference_trains_before_the_router_and_then_checks_agreement(tmp_path) -> None:
    order = []
    inferred = {"n": 0}

    def infer(samples):
        inferred["n"] += 1
        order.append(f"infer{inferred['n']}")
        return {"ok": inferred["n"] > 1, "captures": [{"sample_id": "backup", "triples": []}]}

    def train(samples):
        order.append("train")
        return {"accepted_epochs": 1, "captures": [{"sample_id": "backup", "admitted": False}]}

    def generate(prompt, **kwargs):
        order.append(("router", kwargs.get("temperature")))
        assert "backup" in prompt
        return json.dumps({
            "compiler": "def compile(text):\n    return {'status': 'compiled'}\n",
            "decompiler": "def decompile(rule):\n    return '10 days'\n",
        })

    def agree(samples, inference):
        order.append("agree")
        assert inference["ok"] is True
        return {"agrees": False, "reason": "compiler_abstain"}

    result = run_inference_then_router(
        ["backup"],
        infer=infer,
        train=train,
        generate=generate,
        agree=agree,
        output_dir=tmp_path,
    )
    assert order == ["infer1", "train", "infer2", "agree", ("router", 0)]
    assert result["trained"] is True
    assert result["router_called"] is True
    assert result["wrote_compiler"] is True
    assert result["inference_ok"] is True
    assert result["agrees"] is False
    assert result["admitted"] is False
    assert result["formalized"] is False


def test_training_repeats_until_the_cap_when_inference_never_passes() -> None:
    order = []

    def infer(samples):
        order.append("infer")
        return {"ok": False}

    def train(samples):
        order.append("train")
        return {"accepted_epochs": 1}

    def generate(prompt, **kwargs):
        order.append("router")
        return "{}"

    result = run_inference_then_router(
        ["span"],
        infer=infer,
        train=train,
        generate=generate,
        max_steps=3,
    )
    assert order == ["infer", "train", "infer", "train", "infer", "train", "infer"]
    assert result["router_called"] is False
    assert result["training_steps"] == 3
    assert result["reason"] == "inference_still_failing"
    assert result["admitted"] is False


def test_a_router_draft_that_calls_out_is_not_written_and_agreement_is_not_run(tmp_path) -> None:
    order = []
    seen = {"n": 0}

    def infer(samples):
        seen["n"] += 1
        order.append("infer")
        return {"ok": seen["n"] > 1, "captures": [{"sample_id": "span"}]}

    def train(samples):
        order.append("train")
        return {"accepted_epochs": 1, "captures": []}

    def generate(prompt, **kwargs):
        order.append("router")
        return json.dumps({
            "compiler": "def compile(text):\n    eval(text)\n",
            "decompiler": "def decompile(rule):\n    return ''\n",
        })

    def agree(samples, inference):
        order.append("agree")
        return {"agrees": False, "reason": "compiler_abstain"}

    result = run_inference_then_router(
        ["span"],
        infer=infer,
        train=train,
        generate=generate,
        agree=agree,
        output_dir=tmp_path,
    )
    assert order == ["infer", "train", "infer", "agree", "router"]
    assert result["wrote_compiler"] is False
    assert result["reason"] == "forbidden_call"
    assert result["agrees"] is False
    assert not (tmp_path / "proposed_compiler.py").exists()


def test_a_working_capture_must_still_appear_in_the_deterministic_decompilation() -> None:
    text = "Company A shall submit backup report within 10 days unless emergency."
    inference = {
        "ok": True,
        "captures": [{
            "sample_id": "backup",
            "triples": [{"subject": "backup", "predicate": "object", "object": "backup report"}],
            "recipient": {},
        }],
    }
    agreed = agrees_with_compiler([{"id": "backup", "text": text}], inference)
    assert agreed["agrees"] is True
    assert agreed["admitted"] is False
    dropped = {
        "ok": True,
        "captures": [{
            "sample_id": "backup",
            "triples": [{"subject": "backup", "predicate": "object", "object": "shall"}],
            "recipient": {},
        }],
    }
    disagreed = agrees_with_compiler([{"id": "backup", "text": text}], dropped)
    assert disagreed["agrees"] is False
    assert disagreed["reason"] == "capture_not_in_decompilation"


def test_discrepancies_go_to_the_supervisor_instead_of_the_compiler() -> None:
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import (
        run_inference_then_supervisor,
    )

    order = []

    def infer(samples):
        order.append("infer")
        return {"ok": True, "captures": []}

    def train(samples):
        order.append("train")
        raise AssertionError("training must not run")

    def submit(agreement, **kwargs):
        order.append("supervisor")
        assert kwargs.get("upload") is None or callable(kwargs.get("upload"))
        return {
            "jsonl_written": False,
            "task_count": 1,
            "wrote_compiler": False,
            "wrote_decompiler": False,
        }

    result = run_inference_then_supervisor(
        [{"id": "usc:us:5:552.span-1", "text": "Each agency shall make records available."}],
        infer=infer,
        train=train,
        agree=lambda samples, inference: {
            "agrees": False,
            "reason": "compiler_abstain",
            "rows": [
                {
                    "id": "usc:us:5:552.span-1",
                    "text": "Each agency shall make records available.",
                    "reason": "compiler_abstain",
                    "agrees": False,
                    "skipped": False,
                }
            ],
        },
        submit=submit,
    )
    assert "generate" not in order
    assert order == ["infer", "supervisor"]
    assert result["stage"] == "supervisor_todo"
    assert result["router_called"] is False
    assert result["wrote_compiler"] is False
    assert result["jsonl_written"] is False
    assert result["admitted"] is False
    assert result["formalized"] is False
    assert result["task_count"] == 1


def test_failed_inference_becomes_a_supervisor_todo_not_a_compiler_edit() -> None:
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import (
        run_inference_then_supervisor,
    )

    def infer(samples):
        return {"ok": False}

    def train(samples):
        return {"accepted_epochs": 1}

    seen = {}

    def submit(agreement, **kwargs):
        seen["reason"] = agreement["reason"]
        return {"task_count": 1, "jsonl_written": False, "wrote_compiler": False}

    result = run_inference_then_supervisor(
        ["span"],
        infer=infer,
        train=train,
        submit=submit,
        max_steps=1,
    )
    assert seen["reason"] == "inference_still_failing"
    assert result["router_called"] is False
    assert result["wrote_compiler"] is False
    assert result["stage"] == "supervisor_todo"


def test_default_supervisor_submit_forwards_source_bound_failure_to_native():
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import run_inference_then_supervisor
    seen = []
    agreement = {"agrees": False, "reason": "compiler_disagreement", "rows": [
        {"id": "s1", "text": "The clerk shall retain notices.", "reason": "compiler_abstain", "agrees": False}]}
    def native(value, **kwargs):
        seen.append(value)
        return {"authority": "accelerate-duckdb", "task_count": 1}
    result = run_inference_then_supervisor(["sample"], infer=lambda _: {"ok": True},
        train=lambda _: pytest.fail("no training needed"), agree=lambda *args: agreement, native=native)
    assert seen == [agreement]
    assert result["supervisor"]["authority"] == "accelerate-duckdb"
    assert not result["admitted"] and not result["formalized"]


def test_inference_only_failure_does_not_fabricate_native_compiler_task():
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import run_inference_then_supervisor
    result = run_inference_then_supervisor(["sample"], infer=lambda _: {"ok": False},
        train=lambda _: {"accepted_epochs": 0}, max_steps=1,
        native=lambda *a, **k: pytest.fail("inference-only failure has no sealed compiler source"))
    assert result["supervisor"]["native_enqueue_skipped"] == "inference_failure_has_no_compiler_source"
    assert result["task_count"] == 1  # Unchanged generic supervisor todo, not a compiler repair.
    assert result["wrote_compiler"] is False
