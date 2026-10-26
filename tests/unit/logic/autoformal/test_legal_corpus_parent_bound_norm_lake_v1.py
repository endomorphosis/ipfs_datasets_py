"""Parent conditional composition preserves complete unreviewed source custody.

These controls reuse the genuine parent-bound definition fixture and existing
Lake renderer. No model, toolchain probe, Lean build or legal admission occurs.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

TOOLCHAIN = "leanprover/lean4:v4.34.1"


def fixture_module(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _captured_json_pointer(document, pointer):
    """Resolve declared output pointers independently of product helpers."""
    assert type(pointer) is str and pointer.startswith("/")
    value = document
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            assert part.isdecimal() and str(int(part)) == part
            value = value[int(part)]
        else:
            assert type(value) is dict and part in value
            value = value[part]
    return value


def modified_manifest(preparation, manifest):
    sealed = contracts.seal_record({key: value for key, value in manifest.items()
                                   if key not in {"record_cid", "cid_scope"}})
    return replace(preparation, manifest_json=canonical_dag_json_bytes(sealed).decode("utf-8"))


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_corpus_parent_bound_norm_lake_v1
    return legal_corpus_parent_bound_norm_lake_v1


# Parent bound-variable composition reuses the full genuine parent nomination
# fixture. These engineering examples do not resolve statutory meaning, choose
# governing definitions, run Lean, or qualify a training target.
@pytest.fixture(scope="module")
def parent_bound_norm_helpers():
    return fixture_module("test_legal_bound_variable_definition_v1.py",
                          "parent_bound_norm_original_conditional_fixture")


@pytest.fixture(scope="module")
def parent_bound_norm_base(parent_bound_norm_helpers, tmp_path_factory):
    helper = parent_bound_norm_helpers
    return helper.parent_bound_base.__wrapped__(
        helper.parent_bound_helpers.__wrapped__(), tmp_path_factory)


def _parent_bound_norm_data(helper, original, *, mode="body_with_membership", link_index=0):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    request = helper._parent_bound_declaration(original, mode=mode, link_index=link_index)
    replay = helper._parent_bound_arguments(original, request)
    report = bound.prepare_parent_bound_variable_definition_v1(**replay)
    return {"bound_report": report,
            "expected_bound_report_sha256": bound.bound_variable_definition_sha256(report),
            "bound_definition_inputs": replay, "toolchain": TOOLCHAIN}


@pytest.fixture(scope="module")
def parent_bound_norm_modes(owner, parent_bound_norm_helpers, parent_bound_norm_base):
    result = {}
    for mode in ("instance_only", "body_with_membership"):
        data = _parent_bound_norm_data(parent_bound_norm_helpers, parent_bound_norm_base, mode=mode)
        result[mode] = (data, owner.prepare_parent_bound_norm_definition_corpus_v1(**data))
    return result


def _parent_bound_norm_validate(owner, preparation, data, **overrides):
    return owner.validate_parent_bound_norm_definition_corpus_v1(preparation,
        expected_preparation_sha256=owner.parent_bound_norm_definition_preparation_sha256(preparation),
        **(data | overrides))


def _parent_bound_norm_unqualified(owner, manifest):
    assert manifest["authority"] and all(value is False for value in manifest["authority"].values())
    assert manifest["preparation_only"] is True
    assert manifest["lean_compilation_status"] == "not_run" and manifest["proof_status"] == "pending"
    assert manifest["execution_handoff"]["build_eligible"] is False
    assert manifest["execution_handoff"]["processes_executed"] == 0
    assert manifest["execution_handoff"]["observed_theorem_axiom_dependencies"] is None
    assert manifest["execution_handoff"]["installed_binary_pins"] is None
    assert all(manifest[field] is False for field in owner.PARENT_BOUND_NORM_FALSE_FLAGS)
    assert manifest["norm_interpretation_ready"] is False
    assert manifest["selected_interpretation"] is None
    assert manifest["governing_definition_use"] is None
    for field in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(manifest[field]) is int and manifest[field] == 0
    assert manifest["external_complete_inputs_required"] is True
    assert manifest["review_blockers"]


@pytest.mark.parametrize("mode,theorem_count", [("instance_only", 2), ("body_with_membership", 3)],
                         ids=["instance", "membership"])
def test_parent_bound_norm_project_keeps_complete_parent_norm_donor_and_explicit_hypotheses(
        owner, parent_bound_norm_modes, monkeypatch, tmp_path, mode, theorem_count):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context as markup
    data, expected = parent_bound_norm_modes[mode]
    before = deepcopy(data)
    observed = []
    genuine = bound.validate_parent_bound_variable_definition_v1
    def retained(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append(result)
        return result
    def forbidden(*args, **kwargs):
        raise AssertionError("parent bound norm preparation cannot extract HTML or execute a tool")
    monkeypatch.setattr(bound, "validate_parent_bound_variable_definition_v1", retained)
    monkeypatch.setattr(markup, "extract_document", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    # The module fixture already prepared both genuine modes. Exercise the
    # public validator once here; its opening and closing replays remain real.
    prepared = _parent_bound_norm_validate(owner, expected, data)
    assert prepared == expected and data == before
    assert len(observed) == 2 and observed[0] == observed[1] == data["bound_report"]
    manifest, files = prepared.to_dict(), dict(prepared.files)
    report = data["bound_report"]
    norm = data["bound_definition_inputs"]["companion_inputs"]["norm_preparation"][
        "correspondence"]["relational_fragment"]
    assert manifest["schema"] == owner.PARENT_BOUND_NORM_SCHEMA
    assert manifest["profile"] == owner.PARENT_BOUND_NORM_PROFILE
    assert "parent_bound_definition_report" not in manifest
    assert "original_parent_context_populations" not in manifest
    assert manifest["bound_definition_report_sha256"] == data["expected_bound_report_sha256"]
    input_name = "bound-norm-input-bindings.json"
    input_raw = files[input_name].encode("utf-8")
    document = json.loads(input_raw)
    assert input_raw == canonical_dag_json_bytes(document) + b"\n"
    assert set(document) == {"schema", "profile", "review_intake_binding", "parent_bound_definition_report"}
    assert document["schema"] == "legal-corpus-parent-bound-norm-original-inputs/v1"
    assert document["profile"] == manifest["profile"]
    assert document["review_intake_binding"] == manifest["review_intake_binding"]
    assert canonical_dag_json_bytes(document["parent_bound_definition_report"]) == canonical_dag_json_bytes(report)
    expected_ref = {"file": input_name, "file_sha256": sha(input_raw),
        "json_pointer": "/parent_bound_definition_report",
        "report_sha256": data["expected_bound_report_sha256"],
        "binding_json_pointer": "/review_intake_binding",
        "schema": "legal-corpus-parent-bound-norm-original-inputs/v1", "profile": manifest["profile"]}
    assert manifest["parent_bound_definition_report_ref"] == expected_ref
    assert sha(canonical_dag_json_bytes(_captured_json_pointer(document, expected_ref["json_pointer"]))) == \
        data["expected_bound_report_sha256"]
    assert _captured_json_pointer(document, expected_ref["binding_json_pointer"]) == manifest["review_intake_binding"]
    companion = data["bound_definition_inputs"]["companion"]
    original_norm = data["bound_definition_inputs"]["companion_inputs"]["norm_preparation"]
    norm_fields = ("source_identity", "original_parent_context", "obligations", "obligation_ids",
                   "context_obligation_ids", "producer_pins")
    definition_fields = ("producer_pins", "parent_source_binding", "contexts", "context_slot_ids",
                         "expected_context_population")
    norm_context = {"preparation_sha256": companion["norm_preparation_sha256"],
                    **{key: original_norm[key] for key in norm_fields}}
    definition_contexts = [{"ordinal": ordinal, "alternative_id": row["alternative_id"],
        "preparation_sha256": row["preparation_sha256"],
        **{key: row["preparation"][key] for key in definition_fields}}
        for ordinal, row in enumerate(companion["definitions"])]
    whole_context = {"norm": norm_context, "definitions": definition_contexts}
    norm_prefix = "/parent_bound_definition_report/companion/norm_preparation/"
    context_bindings = {"schema": "legal-corpus-parent-bound-norm-context-bindings/v1",
        "report_ref_sha256": sha(canonical_dag_json_bytes(expected_ref)),
        "projection_sha256": sha(canonical_dag_json_bytes(whole_context)),
        "norm": {"preparation_sha256": norm_context["preparation_sha256"],
            "preparation_sha256_pointer": "/parent_bound_definition_report/companion/norm_preparation_sha256",
            "fields": {key: {"json_pointer": norm_prefix + key,
                             "sha256": sha(canonical_dag_json_bytes(original_norm[key]))}
                       for key in norm_fields}}, "definitions": []}
    for row in definition_contexts:
        prefix = "/parent_bound_definition_report/companion/definitions/" + str(row["ordinal"])
        context_bindings["definitions"].append({"ordinal": row["ordinal"],
            "alternative_id": row["alternative_id"], "alternative_id_pointer": prefix + "/alternative_id",
            "preparation_sha256": row["preparation_sha256"],
            "preparation_sha256_pointer": prefix + "/preparation_sha256",
            "fields": {key: {"json_pointer": prefix + "/preparation/" + key,
                             "sha256": sha(canonical_dag_json_bytes(row[key]))}
                       for key in definition_fields}})
    assert canonical_dag_json_bytes(manifest["original_parent_context_bindings"]) == \
        canonical_dag_json_bytes(context_bindings)
    assert manifest["review_intake_binding"]["source_context_sha256"] == context_bindings["projection_sha256"]
    assert _captured_json_pointer(document, context_bindings["norm"]["preparation_sha256_pointer"]) == \
        norm_context["preparation_sha256"]
    for name, descriptor in context_bindings["norm"]["fields"].items():
        value = _captured_json_pointer(document, descriptor["json_pointer"])
        assert canonical_dag_json_bytes(value) == canonical_dag_json_bytes(original_norm[name])
        assert sha(canonical_dag_json_bytes(value)) == descriptor["sha256"]
    for original, binding in zip(definition_contexts, context_bindings["definitions"], strict=True):
        assert _captured_json_pointer(document, binding["alternative_id_pointer"]) == original["alternative_id"]
        assert _captured_json_pointer(document, binding["preparation_sha256_pointer"]) == original["preparation_sha256"]
        for name, descriptor in binding["fields"].items():
            value = _captured_json_pointer(document, descriptor["json_pointer"])
            assert canonical_dag_json_bytes(value) == canonical_dag_json_bytes(original[name])
            assert sha(canonical_dag_json_bytes(value)) == descriptor["sha256"]
    assert len(context_bindings["definitions"]) == len(companion["definitions"]) == 2
    assert canonical_dag_json_bytes(manifest["review_blockers"]) == canonical_dag_json_bytes({
        "norm_obligations": context_bindings["norm"]["fields"]["obligations"],
        "definition_context_slot_ids": [{"ordinal": row["ordinal"], "alternative_id": row["alternative_id"],
            "context_slot_ids": row["fields"]["context_slot_ids"]}
            for row in context_bindings["definitions"]]})
    assert manifest["conditional_theorem_statements"] == report["conditional_theorem_statements"]
    assert manifest["input_budget"] == {"bytes": 48 * 1024 * 1024, "expanded_values": 1_000_000,
                                        "depth": 48, "complete_overflow_refused": True}
    assert manifest["renderer_compatibility"]["source_sha256"] == owner.LEGACY_LAKE_SOURCE_SHA256
    assert manifest["renderer_compatibility"]["existing_project_renderer_reused"] is True
    assert sha(Path(owner.lake.__file__).read_bytes()) == \
        "5c98152db328b75583f6c0cd181e2724ca5f7392870ec0faf1e4d870cbb76b32"
    for field in ("original_norm", "selected_link", "occurrence_binding",
                  "definition_alternative_refs", "nomination_inventory"):
        assert manifest[field] == report[field]
    assert len(manifest["definition_alternative_refs"]) == 2
    assert len(manifest["nomination_inventory"]) == 6
    assert len({row["request_link"]["target"]["typed_path"]
                for row in manifest["nomination_inventory"]}) == 3
    assert norm["source_binding"] is None and norm["source_bound"] is False
    fragments = {row["role"]: row for row in manifest["native_fragments"]}
    assert set(fragments) == {"norm", "definition"}
    assert fragments["norm"]["native"] == norm["native_fragment"]
    assert fragments["definition"]["native"] == report["definition_native_fragment"]
    assert len(files) == 9 and len(manifest["expected_modules"]) == 6
    assert manifest["file_sha256"] == {name: sha(text.encode("utf-8")) for name, text in files.items()}
    for index, module in enumerate(manifest["expected_modules"]):
        text = files[module.replace(".", "/") + ".lean"]
        imports = re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", text)
        assert imports == manifest["module_imports"][module]
        assert all(item in manifest["expected_modules"][:index] for item in imports)
    assert norm["lean_body"] in files[fragments["norm"]["module"].replace(".", "/") + ".lean"]
    binding = manifest["conditional_source_binding"]
    occurrence_module = binding["theorem_names"][0]["project"].rsplit(".", 1)[0]
    occurrence = files[occurrence_module.replace(".", "/") + ".lean"]
    original_tail = "theorem definition_instance " + report["lean_source"].split(
        "\ntheorem definition_instance ", 1)[1].removesuffix("end LegalBoundVariableDefinition\n")
    assert original_tail in occurrence
    assert binding["conditional_theorem_body_sha256"] == sha(original_tail.encode("utf-8"))
    assert len(manifest["conditional_theorems"]) == theorem_count
    lean = "\n".join(text for name, text in files.items() if name.endswith(".lean"))
    assert len(re.findall(r"(?m)^theorem ", lean)) == lean.count("#print axioms ") == theorem_count
    assert "exact Iff.rfl" in lean and "hNorm" not in lean
    assert "exact hDefinition entity" in occurrence
    assert ("hMembership" in occurrence) is (mode == "body_with_membership")
    assert ("theorem body_instance " in occurrence) is (mode == "body_with_membership")
    if mode == "body_with_membership":
        assert "exact (hDefinition entity).mp hMembership" in occurrence
    assert not re.search(r"\b(?:sorry|admit|sorryAx|axiom|unsafe)\b", lean)
    _parent_bound_norm_unqualified(owner, manifest)
    # Retain these actual generated bytes as owned engineering examples for
    # independent inspection. This is test capture, not a new product writer.
    directory = tmp_path / "project"
    directory.mkdir(mode=0o700)
    payloads = {"corpus-manifest.json": prepared.manifest_json, **files}
    assert len(payloads) == 10
    for name, text in payloads.items():
        path = directory / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        with path.open("xb") as stream:
            assert stream.write(raw) == len(raw)
        actual = path.read_bytes()
        assert actual == raw and len(actual) == len(raw) and sha(actual) == sha(raw)
        if name != "corpus-manifest.json":
            assert sha(actual) == manifest["file_sha256"][name]
    assert {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()} == set(payloads)


@pytest.mark.parametrize("link_index", [2, 1], ids=["other-variable", "other-definition"])
def test_parent_bound_norm_retains_all_alternatives_and_repeated_variable_identity(
        owner, parent_bound_norm_helpers, parent_bound_norm_base, parent_bound_norm_modes, link_index):
    data = _parent_bound_norm_data(parent_bound_norm_helpers, parent_bound_norm_base, link_index=link_index)
    prepared = owner.prepare_parent_bound_norm_definition_corpus_v1(**data)
    baseline = parent_bound_norm_modes["body_with_membership"][1].to_dict()
    manifest = prepared.to_dict()
    assert manifest["original_norm"] == baseline["original_norm"]
    assert manifest["definition_alternative_refs"] == baseline["definition_alternative_refs"]
    assert manifest["nomination_inventory"] == baseline["nomination_inventory"]
    assert manifest["selected_link"] != baseline["selected_link"]
    assert manifest["occurrence_binding"] == data["bound_report"]["occurrence_binding"]
    assert owner.parent_bound_norm_definition_preparation_sha256(prepared) != \
        owner.parent_bound_norm_definition_preparation_sha256(parent_bound_norm_modes["body_with_membership"][1])
    if link_index == 2:
        assert manifest["occurrence_binding"]["target"] != baseline["occurrence_binding"]["target"]
    else:
        assert data["bound_report"]["request"]["alternative_id"] != \
            parent_bound_norm_modes["body_with_membership"][0]["bound_report"]["request"]["alternative_id"]
    _parent_bound_norm_unqualified(owner, manifest)


@pytest.mark.parametrize("pin", ["report", "request", "companion", "preparation"])
def test_parent_bound_norm_independent_pins_refuse_before_full_parent_replay(
        owner, parent_bound_norm_modes, monkeypatch, pin):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    data, prepared = deepcopy(parent_bound_norm_modes["body_with_membership"])
    if pin == "report": data["expected_bound_report_sha256"] = "0" * 64
    elif pin in ("request", "companion"):
        data["bound_definition_inputs"]["expected_" + pin + "_sha256"] = "0" * 64
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid independent pin reached full parent replay")
    monkeypatch.setattr(bound, "validate_parent_bound_variable_definition_v1", forbidden)
    with pytest.raises(ValueError):
        if pin == "preparation":
            owner.validate_parent_bound_norm_definition_corpus_v1(prepared,
                expected_preparation_sha256="0" * 64, **data)
        else:
            owner.prepare_parent_bound_norm_definition_corpus_v1(**data)


@pytest.mark.parametrize("damage", ["membership", "alternative", "physical-population"])
def test_parent_bound_norm_rehashed_bound_report_cannot_drop_original_parent_or_promote_membership(
        owner, parent_bound_norm_modes, damage):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    data = deepcopy(parent_bound_norm_modes["body_with_membership"][0])
    report = data["bound_report"]
    if damage == "membership": report["authority"]["membership_assumption_verified"] = True
    elif damage == "alternative": report["definition_alternative_refs"].pop()
    else: report["companion"]["definitions"].pop()
    data["expected_bound_report_sha256"] = bound.bound_variable_definition_sha256(report)
    with pytest.raises(ValueError):
        owner.prepare_parent_bound_norm_definition_corpus_v1(**data)


@pytest.mark.parametrize("damage", ["authority", "norm-body", "membership-premise", "mask-type", "input-report"])
def test_parent_bound_norm_resealed_project_cannot_replace_complete_content_or_pending_status(
        owner, parent_bound_norm_modes, monkeypatch, damage):
    data, prepared = parent_bound_norm_modes["body_with_membership"]
    manifest, files = prepared.to_dict(), dict(prepared.files)
    genuine_returns = []
    if damage == "authority": manifest["norm_truth_proved"] = True
    elif damage == "mask-type": manifest["training_mask"] = False
    elif damage == "input-report":
        # Repair the stored report and every directly affected public custody
        # hash. Independent external originals still govern regeneration.
        name = "bound-norm-input-bindings.json"
        document = json.loads(files[name])
        document["parent_bound_definition_report"]["authority"]["membership_assumption_verified"] = True
        changed_report_sha256 = sha(canonical_dag_json_bytes(document["parent_bound_definition_report"]))
        binding = document["review_intake_binding"]
        binding["bound_definition_report_sha256"] = changed_report_sha256
        binding = contracts.seal_record({key: value for key, value in binding.items()
                                        if key not in {"record_cid", "cid_scope"}})
        document["review_intake_binding"] = binding
        manifest["review_intake_binding"] = binding
        manifest["bound_definition_report_sha256"] = changed_report_sha256
        files[name] = (canonical_dag_json_bytes(document) + b"\n").decode("utf-8")
        file_sha256 = sha(files[name].encode("utf-8"))
        manifest["file_sha256"][name] = file_sha256
        reference = manifest["parent_bound_definition_report_ref"]
        reference["file_sha256"] = file_sha256
        reference["report_sha256"] = changed_report_sha256
        manifest["original_parent_context_bindings"]["report_ref_sha256"] = \
            sha(canonical_dag_json_bytes(reference))
        assert file_sha256 == manifest["file_sha256"][name] == reference["file_sha256"]
        assert reference["report_sha256"] == sha(canonical_dag_json_bytes(
            _captured_json_pointer(document, reference["json_pointer"])))
        assert _captured_json_pointer(document, reference["binding_json_pointer"]) == manifest["review_intake_binding"]
        genuine = owner.bound.validate_parent_bound_variable_definition_v1
        def retained(*args, **kwargs):
            result = genuine(*args, **kwargs)
            genuine_returns.append(result)
            return result
        monkeypatch.setattr(owner.bound, "validate_parent_bound_variable_definition_v1", retained)
    else:
        if damage == "norm-body":
            module = next(row["module"] for row in manifest["native_fragments"] if row["role"] == "norm")
            path = module.replace(".", "/") + ".lean"
            files[path] += "\n-- changed complete parent norm\n"
        else:
            theorem = manifest["conditional_source_binding"]["theorem_names"][0]["project"]
            path = theorem.rsplit(".", 1)[0].replace(".", "/") + ".lean"
            assert "(hMembership : headAt i entity t)" in files[path]
            files[path] = files[path].replace("(hMembership : headAt i entity t)", "")
        manifest["file_sha256"][path] = sha(files[path].encode("utf-8"))
    changed = modified_manifest(replace(prepared, files=tuple(sorted(files.items()))), manifest)
    with pytest.raises(ValueError):
        _parent_bound_norm_validate(owner, changed, data)
    if damage == "input-report":
        assert len(genuine_returns) == 2
        assert all(sha(canonical_dag_json_bytes(result)) == data["expected_bound_report_sha256"]
                   for result in genuine_returns)
        assert all(result["authority"]["membership_assumption_verified"] is False for result in genuine_returns)


@pytest.mark.parametrize("damage", ["bytes", "cycle", "depth", "toolchain", "missing-replay"])
def test_parent_bound_norm_complete_input_profile_refuses_before_genuine_replay(
        owner, parent_bound_norm_modes, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    data = deepcopy(parent_bound_norm_modes["body_with_membership"][0])
    if damage == "bytes": monkeypatch.setattr(owner.lake, "MAX_INPUT_BYTES", 1)
    elif damage == "toolchain": data["toolchain"] = "leanprover/lean4:stable"
    elif damage == "missing-replay": data["bound_definition_inputs"].pop("companion_inputs")
    else:
        inputs = data["bound_definition_inputs"]["companion_inputs"]
        if damage == "cycle": inputs["budget_probe"] = inputs
        else:
            nested = None
            for _ in range(60): nested = [nested]
            inputs["budget_probe"] = nested
    def forbidden(*args, **kwargs):
        raise AssertionError("out-of-profile complete graph reached genuine parent replay")
    monkeypatch.setattr(bound, "validate_parent_bound_variable_definition_v1", forbidden)
    with pytest.raises(ValueError):
        owner.prepare_parent_bound_norm_definition_corpus_v1(**data)


def test_parent_bound_norm_parent_profile_is_not_accepted_by_legacy_bound_project(
        owner, parent_bound_norm_modes):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as legacy
    data = parent_bound_norm_modes["body_with_membership"][0]
    with pytest.raises(ValueError): legacy.prepare_bound_norm_definition_corpus_v1(**data)


@pytest.mark.parametrize("location", ["caller", "detached"])
def test_parent_bound_norm_late_caller_and_actual_detached_inputs_remain_fenced(
        owner, parent_bound_norm_modes, monkeypatch, location):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    data = deepcopy(parent_bound_norm_modes["body_with_membership"][0])
    genuine = bound.validate_parent_bound_variable_definition_v1
    observed = []
    def changed(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if not observed:
            observed.append("genuine_opening_parent_bound_replay_completed")
            target = data["bound_report"] if location == "caller" else args[0]
            target["training_mask"] = False
        return result
    monkeypatch.setattr(bound, "validate_parent_bound_variable_definition_v1", changed)
    with pytest.raises(ValueError):
        owner.prepare_parent_bound_norm_definition_corpus_v1(**data)
    assert observed == ["genuine_opening_parent_bound_replay_completed"]


@pytest.mark.parametrize("return_index", [0, 1], ids=["opening", "closing"])
def test_parent_bound_norm_actual_parent_bound_returns_survive_last_serialization_guard(
        owner, parent_bound_norm_modes, monkeypatch, return_index):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    data = deepcopy(parent_bound_norm_modes["body_with_membership"][0])
    genuine = bound.validate_parent_bound_variable_definition_v1
    serialized = owner._parent_bound_norm_serialized_fence
    actual, observed = [], []
    def retained(*args, **kwargs):
        result = genuine(*args, **kwargs)
        actual.append(result)
        return result
    def changed(preparation, expected_storage):
        result = serialized(preparation, expected_storage)
        observed.append("genuine_final_storage_check_completed")
        if len(observed) == 2:
            assert len(actual) == 2
            actual[return_index]["training_mask"] = False
        return result
    monkeypatch.setattr(bound, "validate_parent_bound_variable_definition_v1", retained)
    monkeypatch.setattr(owner, "_parent_bound_norm_serialized_fence", changed)
    with pytest.raises(ValueError):
        owner.prepare_parent_bound_norm_definition_corpus_v1(**data)
    assert len(actual) == 2 and observed == ["genuine_final_storage_check_completed"] * 2


@pytest.mark.parametrize("endpoint", ["norm", "definition"])
def test_parent_bound_norm_physical_parent_remains_bound_after_last_serialization(
        owner, parent_bound_norm_helpers, tmp_path, monkeypatch, endpoint):
    helper = parent_bound_norm_helpers
    nomination = helper.parent_bound_helpers.__wrapped__()
    inputs = nomination._parent_nomination_materialize(
        nomination.parent_nomination_helpers.__wrapped__(), tmp_path / "physical-originals")
    companion = nomination._parent_nomination_prepare(inputs)
    original = {"inputs": inputs, "companion": companion,
                "companion_sha256": nomination.owner.norm_definition_evidence_sha256(companion)}
    data = _parent_bound_norm_data(helper, original)
    path = nomination._parent_nomination_parent_path(inputs, endpoint)
    raw = path.read_bytes()
    serialized = owner._parent_bound_norm_serialized_fence
    observed = []
    def changed(preparation, expected_storage):
        result = serialized(preparation, expected_storage)
        observed.append("genuine_final_storage_check_completed")
        if len(observed) == 2: path.write_bytes(raw + b"\nchanged physical parent after final storage check\n")
        return result
    monkeypatch.setattr(owner, "_parent_bound_norm_serialized_fence", changed)
    with pytest.raises(ValueError):
        owner.prepare_parent_bound_norm_definition_corpus_v1(**data)
    assert observed == ["genuine_final_storage_check_completed"] * 2 and path.read_bytes() != raw


def test_parent_bound_norm_final_actual_preparation_storage_stays_fenced(
        owner, parent_bound_norm_modes, monkeypatch):
    data = deepcopy(parent_bound_norm_modes["body_with_membership"][0])
    serialized = owner._parent_bound_norm_serialized_fence
    observed = []
    def changed(preparation, expected_storage):
        result = serialized(preparation, expected_storage)
        observed.append("genuine_final_storage_check_completed")
        if len(observed) == 2:
            object.__setattr__(preparation, "manifest_json", preparation.manifest_json + " ")
        return result
    monkeypatch.setattr(owner, "_parent_bound_norm_serialized_fence", changed)
    with pytest.raises(ValueError):
        owner.prepare_parent_bound_norm_definition_corpus_v1(**data)
    assert observed == ["genuine_final_storage_check_completed"] * 2


def test_parent_bound_norm_late_policy_bool_integer_drift_is_type_sensitive(
        owner, parent_bound_norm_modes, monkeypatch):
    data = deepcopy(parent_bound_norm_modes["body_with_membership"][0])
    serialized = owner._parent_bound_norm_serialized_fence
    observed = []
    assert owner.PARENT_BOUND_NORM_FALSE_FLAGS["source_bound"] is False
    def changed(preparation, expected_storage):
        result = serialized(preparation, expected_storage)
        observed.append("genuine_final_storage_check_completed")
        if len(observed) == 2:
            # Equality alone treats False and 0 alike; the held policy commits
            # their distinct types even though the generated output is intact.
            monkeypatch.setitem(owner.PARENT_BOUND_NORM_FALSE_FLAGS, "source_bound", 0)
        return result
    monkeypatch.setattr(owner, "_parent_bound_norm_serialized_fence", changed)
    with pytest.raises(ValueError):
        owner.prepare_parent_bound_norm_definition_corpus_v1(**data)
    assert observed == ["genuine_final_storage_check_completed"] * 2


def test_parent_bound_norm_primary_failure_preserves_secondary_original_custody_note(
        owner, parent_bound_norm_modes, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    data = deepcopy(parent_bound_norm_modes["body_with_membership"][0])
    genuine = bound.validate_parent_bound_variable_definition_v1
    primary = RuntimeError("authored primary parent-bound Lake failure")
    observed = []
    def changed(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append("genuine_parent_bound_replay_completed")
        if len(observed) == 1:
            data["bound_report"]["training_mask"] = False
            raise primary
        return result
    monkeypatch.setattr(bound, "validate_parent_bound_variable_definition_v1", changed)
    with pytest.raises(RuntimeError) as caught:
        owner.prepare_parent_bound_norm_definition_corpus_v1(**data)
    assert caught.value is primary and observed
    assert getattr(primary, "__notes__", [])
