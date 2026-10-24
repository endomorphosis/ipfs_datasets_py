"""V2 Lean preparation preserves exact assumptions without running Lean."""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

TOOLCHAIN = "leanprover/lean4:v4.34.1"


def fixture_module(filename, name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_COMBINED = fixture_module(
    "test_corpus_definition_use_review_v2.py",
    "combined_review_for_v2_native_preparation",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode()


def assessment_data(family="fol"):
    from ipfs_datasets_py.logic.autoformal import (
        corpus_definition_use_review_v2 as review,
    )

    materialized = _COMBINED.materialize(review, _COMBINED.component(family))
    signed = _COMBINED._REVIEW.signed.__wrapped__(review, materialized)
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    _COMBINED._REVIEW.refresh(signed)
    return refresh_assessment(signed)


def refresh_assessment(signed):
    from ipfs_datasets_py.logic.autoformal import (
        corpus_definition_use_review_v2 as review,
    )

    report = _COMBINED.assess(review, signed)
    args, kwargs = _COMBINED.assessment_arguments(signed)
    review_inputs = (
        dict(
            zip(
                ("subject", "registry", "policy", "reviews", "dependency_manifest"),
                args,
                strict=True,
            )
        )
        | kwargs
    )
    raw = wire(report) + b"\n"
    return {
        "signed": signed,
        "assessment": report,
        "assessment_raw": raw,
        "expected_assessment_file_sha256": sha(raw),
        "review_inputs": review_inputs,
        "toolchain": TOOLCHAIN,
    }


def arguments(data):
    return {
        key: data[key]
        for key in (
            "assessment_raw",
            "expected_assessment_file_sha256",
            "review_inputs",
            "toolchain",
        )
    }


def prepare(owner, data):
    return owner.prepare_definition_use_corpus_v2(**arguments(data))


def validate(owner, prepared, data):
    return owner.validate_definition_use_corpus_v2(prepared, **arguments(data))


def modified_manifest(prepared, manifest):
    sealed = contracts.seal_record(
        {k: v for k, v in manifest.items() if k not in {"record_cid", "cid_scope"}}
    )
    return replace(
        prepared, manifest_json=canonical_dag_json_bytes(sealed).decode("utf-8")
    )


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2

    return legal_corpus_definition_use_lake_v2


@pytest.fixture(scope="module")
def base():
    return assessment_data()


@pytest.fixture
def case(base):
    return deepcopy(base)


@pytest.fixture(scope="module")
def frozen(owner, base):
    return prepare(owner, base)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_exact_reviewed_joint_fragments_source_custody_and_closed_generated_project(
    owner, family
):
    data = assessment_data(family)
    original = deepcopy(data["signed"]["component"]["record"])
    prepared = prepare(owner, data)
    manifest, files = prepared.to_dict(), dict(prepared.files)
    assert data["signed"]["component"]["record"] == original
    assert type(prepared) is owner.DefinitionUseCorpusPreparation
    assert manifest["toolchain"] == TOOLCHAIN
    assert files["lean-toolchain"] == TOOLCHAIN + "\n"
    assert len(files) == len(prepared.files) == 9
    assert manifest["file_sha256"] == {
        name: sha(text.encode("utf-8")) for name, text in files.items()
    }
    expected = {
        "donor": data["signed"]["component"]["case"]["donor"]["candidate"][
            "definition_record"
        ]["native_ast"],
        "consumer": data["signed"]["component"]["case"]["consumer"]["candidate"][
            "definition_record"
        ]["native_ast"],
        "alias": original["alias_native"]["native_ast"],
        "joint": original["joint_native"]["native_ast"],
    }
    fragments = {row["role"]: row for row in manifest["native_fragments"]}
    assert list(fragments) == ["donor", "consumer", "alias", "joint"]
    for role, ast in expected.items():
        row = fragments[role]
        assert row["native"]["native_ast"] == ast
        assert row["native"]["exact_native_ast_roundtrip"] is True
        assert (
            row["native"]["lean_body"]
            in files[row["module"].replace(".", "/") + ".lean"]
        )
        assert row["native"]["backend_executed"] is False
    donor, consumer, alias, joint = [
        fragments[role]["module"] for role in ("donor", "consumer", "alias", "joint")
    ]
    assert manifest["expected_modules"] == [
        "LegalCorpusV2.Prelude",
        donor,
        consumer,
        alias,
        joint,
        "LegalCorpusV2",
    ]
    imports = {
        "LegalCorpusV2.Prelude": [],
        donor: ["LegalCorpusV2.Prelude"],
        consumer: ["LegalCorpusV2.Prelude"],
        alias: [donor, consumer],
        joint: [donor, consumer, alias],
        "LegalCorpusV2": [joint],
    }
    assert manifest["module_imports"] == imports
    seen = set()
    for module in manifest["expected_modules"]:
        source = files[module.replace(".", "/") + ".lean"]
        assert re.findall(r"^import ([A-Za-z0-9_.]+)$", source, re.M) == imports[module]
        assert set(imports[module]) <= seen
        seen.add(module)
    assert manifest["review_dependency_manifest"] == data["signed"]["manifest"]
    binding = json.dumps(
        manifest["review_source_binding"], sort_keys=True, separators=(",", ":")
    )
    for row in original["context_population"]:
        assert row["source_occurrence"]["record_cid"] in binding
        assert row["context"]["packet_id"] in binding
    assert original["binding_record"]["record_cid"] in binding
    assert data["signed"]["subject"]["scope_id"] in binding
    for role in ("donor", "consumer"):
        candidate = data["signed"]["component"]["case"][role]["candidate"]
        assert candidate["source_version"]["record_cid"] in binding
        assert candidate["definition_record"]["record_cid"] in binding
        assert (
            json.dumps(
                candidate["source_bindings"], sort_keys=True, separators=(",", ":")
            )
            in binding
        )
    assert (
        manifest["review_evidence_status"]
        == data["assessment"]["evidence_assessment_status"]
    )
    assert manifest["review_blockers"] == data["assessment"]["blockers"]
    assert manifest["review_prerequisites_satisfied_under_selected_trust"] is True
    assert manifest["execution_handoff"]["build_eligible"] is False
    assert manifest["preparation_only"] is True
    assert all(manifest[key] is False for key in owner.FALSE_FLAGS)
    assert validate(owner, prepared, data) == prepared


def test_theorems_expose_only_conditional_alias_transfer_and_joint_assembly(
    owner, base, frozen
):
    manifest, files = frozen.to_dict(), dict(frozen.files)
    fragments = {row["role"]: row for row in manifest["native_fragments"]}
    donor, alias, joint = [
        files[fragments[role]["module"].replace(".", "/") + ".lean"]
        for role in ("donor", "alias", "joint")
    ]
    assert "def bodyAt" in donor
    assert "def consumerPredicateAt" in alias
    assert "theorem consumer_predicate_iff_donor_body" in alias
    assert all(re.search(r"\(h" + role + r"\s*:", alias) for role in ("Donor", "Alias"))
    assert "(hAlias entity).trans (hDonor entity)" in alias
    assert "theorem joint_of_components" in joint
    assert all(
        re.search(r"\(h" + role + r"\s*:", joint)
        for role in ("Donor", "Consumer", "Alias")
    )
    assert "theorem joint_matches_original" in joint and "rfl" in joint
    assert "And.intro" in joint
    assert sum(source.count("#print axioms") for source in files.values()) == 3
    assert not re.search(r"\b(?:sorry|admit|axiom|unsafe)\b", "\n".join(files.values()))
    assert "consumer_head" not in alias
    record = base["signed"]["component"]["record"]
    donor_ast, consumer_ast, alias_ast = [
        fragments[role]["native"]["native_ast"]
        for role in ("donor", "consumer", "alias")
    ]
    body_symbol = donor_ast["formula"]["right"]["name"]
    consumer_symbol = alias_ast["formula"]["left"]["name"]
    assert f'i.atom "{body_symbol}" [entity] t' in donor
    assert f'i.atom "{consumer_symbol}" [entity] t' in alias
    omitted = {"Donor": False, "Alias": False}
    assembly_omitted = {"Donor": False, "Consumer": False, "Alias": False}
    names = [
        donor_ast["formula"]["left"]["name"],
        body_symbol,
        consumer_ast["formula"]["left"]["name"],
        consumer_symbol,
    ]
    for bits in itertools.product((False, True), repeat=4):
        values = {name: (bit, bit) for name, bit in zip(names, bits, strict=True)}
        hypotheses = {
            "Donor": _COMBINED._USE.evaluate(donor_ast, values),
            "Consumer": _COMBINED._USE.evaluate(consumer_ast, values),
            "Alias": _COMBINED._USE.evaluate(alias_ast, values),
        }
        transfer = values[consumer_symbol][0] == values[body_symbol][0]
        if hypotheses["Donor"] and hypotheses["Alias"]:
            assert transfer
        joint_truth = _COMBINED._USE.evaluate(
            record["joint_native"]["native_ast"], values
        )
        assert joint_truth == all(hypotheses.values())
        for missing in omitted:
            omitted[missing] |= not transfer and all(
                value
                for role, value in hypotheses.items()
                if role in omitted and role != missing
            )
        for missing in assembly_omitted:
            assembly_omitted[missing] |= not joint_truth and all(
                value for role, value in hypotheses.items() if role != missing
            )
    assert all(omitted.values()) and all(assembly_omitted.values())


@pytest.mark.parametrize("status", ["pending", "rejected", "stale_dependency"])
def test_valid_blocked_reviews_still_prepare_candidate_text_with_no_build_eligibility(
    owner, case, status
):
    signed = case["signed"]
    if status == "pending":
        signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
        signed["registry"]["keys"] = []
        signed["reviews"] = []
        _COMBINED._REVIEW.refresh(signed)
    elif status == "rejected":
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned change"
    else:
        identity = next(
            row["artifact_id"]
            for row in signed["manifest"]["artifacts"]
            if row["artifact_id"].startswith("definition-lookup:")
        )
        signed["observed_artifact_sha256s"][identity] = "0" * 64
    data = refresh_assessment(signed)
    manifest = prepare(owner, data).to_dict()
    assert (
        manifest["review_evidence_status"]
        == data["assessment"]["evidence_assessment_status"]
    )
    assert manifest["review_blockers"] == data["assessment"]["blockers"]
    assert manifest["review_prerequisites_satisfied_under_selected_trust"] is False
    assert manifest["execution_handoff"]["build_eligible"] is False
    assert all(manifest[key] is False for key in owner.FALSE_FLAGS)


def test_assessment_original_transport_pin_is_distinct_from_internal_report_digest(
    owner, case
):
    assert (
        case["expected_assessment_file_sha256"]
        != case["assessment"]["assessment_sha256"]
    )
    case["expected_assessment_file_sha256"] = case["assessment"]["assessment_sha256"]
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "damage", ["authority", "blockers", "review_population", "joint_digest"]
)
def test_repaired_assessment_digest_and_transport_hash_cannot_replace_original_replay(
    owner, case, damage
):
    report = case["assessment"]
    if damage == "authority":
        report["accepted_view_eligible"] = True
    elif damage == "blockers":
        report["blockers"] = []
    elif damage == "review_population":
        report["reviews"].pop()
    else:
        report["joint_ast_sha256"] = "0" * 64
    report["assessment_sha256"] = signatures.digest(
        {key: value for key, value in report.items() if key != "assessment_sha256"}
    )
    case["assessment_raw"] = wire(report)
    case["expected_assessment_file_sha256"] = sha(case["assessment_raw"])
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "damage", ["source", "lookup", "review_clock", "context_evidence"]
)
def test_complete_original_source_review_and_dependency_inputs_are_replayed(
    owner, case, damage
):
    inputs = case["review_inputs"]
    if damage == "source":
        evidence = inputs["use_inputs"]["consumer_evidence_inputs"]
        evidence["candidate_inputs"]["raw_html"] += b" changed source"
    elif damage == "lookup":
        inputs["use_inputs"]["expected_lookup_sha256"] = "0" * 64
    elif damage == "review_clock":
        inputs["at_time_utc"] = "2035-01-01T00:00:00Z"
    else:
        inputs["evidence_artifacts"]["fixture:v2-context"] += b" changed evidence"
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize("damage", ["subject", "policy", "key_scope"])
def test_rehashed_changed_review_contract_or_credentials_cannot_reuse_prior_assessment(
    owner, case, damage
):
    inputs = case["review_inputs"]
    if damage == "subject":
        inputs["subject"]["schema"] = "legal-corpus-v2-definition-review-subject/v1"
        inputs["expected_subject_sha256"] = signatures.digest(inputs["subject"])
    elif damage == "policy":
        inputs["policy"]["policy_id"] += ":changed"
        inputs["expected_policy_sha256"] = signatures.digest(inputs["policy"])
    else:
        inputs["registry"]["keys"][0]["scope_ids"] = []
        inputs["expected_registry_sha256"] = signatures.digest(inputs["registry"])
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "damage", ["source_binding", "fragment", "contexts", "dependency", "authority"]
)
def test_resealed_manifest_cannot_weaken_source_native_review_or_authority_custody(
    owner, base, frozen, damage
):
    manifest = frozen.to_dict()
    if damage == "source_binding":
        manifest["review_source_binding"] = {}
    elif damage == "fragment":
        manifest["native_fragments"][0]["native"]["native_ast"] = deepcopy(
            manifest["native_fragments"][1]["native"]["native_ast"]
        )
    elif damage == "contexts":
        manifest["review_source_binding"]["contexts"].pop()
    elif damage == "dependency":
        manifest["review_dependency_manifest"]["artifacts"].pop()
    else:
        manifest["lean_compilation_verified"] = True
    with pytest.raises(ValueError):
        validate(owner, modified_manifest(frozen, manifest), base)


@pytest.mark.parametrize(
    "damage",
    ["drop_import", "drop_alias_premise", "wrong_symbol", "omit_file", "extra_file"],
)
def test_repaired_generated_file_hashes_cannot_change_imports_premises_or_exact_native_symbols(
    owner, base, frozen, damage
):
    manifest, files = frozen.to_dict(), dict(frozen.files)
    roles = {row["role"]: row for row in manifest["native_fragments"]}
    path = roles["alias"]["module"].replace(".", "/") + ".lean"
    if damage == "drop_import":
        files[path] = (
            "\n".join(
                line
                for line in files[path].splitlines()
                if not line.startswith("import ")
            )
            + "\n"
        )
    elif damage == "drop_alias_premise":
        files[path] = files[path].replace("(hAlias :", "(omittedAlias :")
    elif damage == "wrong_symbol":
        symbol = base["signed"]["component"]["record"]["binding_record"][
            "consumer_symbol"
        ]
        files[path] = files[path].replace(symbol, "foreign_predicate")
    elif damage == "omit_file":
        files.pop(path)
    else:
        files["LegalCorpusV2/Foreign.lean"] = "def fabricated : Prop := True\n"
    manifest["file_sha256"] = {name: sha(body.encode()) for name, body in files.items()}
    forged = replace(
        modified_manifest(frozen, manifest), files=tuple(sorted(files.items()))
    )
    with pytest.raises(ValueError):
        validate(owner, forged, base)


@pytest.mark.parametrize(
    "toolchain",
    ["leanprover/lean4:stable", "leanprover/lean4:v4.34.1\n", "leanprover/lean4:v4.34"],
)
def test_toolchain_must_be_an_exact_version_pin_without_probing(owner, case, toolchain):
    case["toolchain"] = toolchain
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize("damage", ["assessment", "review_metadata", "aggregate"])
def test_full_native_preparation_bounds_precede_optional_review_and_native_imports(
    owner, case, damage
):
    if damage == "assessment":
        case["assessment_raw"] = b" " * (contracts.MAX_RECORD_BYTES + 1)
        case["expected_assessment_file_sha256"] = sha(case["assessment_raw"])
    elif damage == "review_metadata":
        case["review_inputs"]["reviews"][0]["interpretation"]["rationale"] = "x" * (
            contracts.MAX_RECORD_BYTES + 1
        )
    else:
        for role in ("donor_evidence_inputs", "consumer_evidence_inputs"):
            evidence = case["review_inputs"]["use_inputs"][role]
            raw = b" " * (25 * 1024 * 1024)
            evidence["candidate_inputs"]["sampling_report_raw"] = raw
            evidence["expected_candidate_pin"]["sampling_report_sha256"] = sha(raw)
    original_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        blocked = {
            "legal_graph_review",
            "legal_family_routes",
            "corpus_definition_use_review_v2",
        }
        if name.rsplit(".", 1)[-1] in blocked or blocked.intersection(fromlist or ()):
            raise AssertionError(
                "operation import occurred before complete input bounds"
            )
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", guarded):
        with pytest.raises(ValueError):
            prepare(owner, case)


def test_preparation_and_regeneration_never_execute_a_process_or_probe_a_toolchain(
    owner, base
):
    def forbidden(*args, **kwargs):
        raise AssertionError("native preparation cannot execute a process or toolchain")

    from ipfs_datasets_py.logic.autoformal import legal_pilot_lake
    from ipfs_datasets_py.logic.backends import process

    with (
        patch("subprocess.Popen", forbidden),
        patch.object(process.BoundedToolRunner, "run", forbidden),
        patch.object(legal_pilot_lake, "_installed_toolchain", forbidden),
    ):
        prepared = prepare(owner, base)
        assert validate(owner, prepared, base) == prepared


def test_public_native_preparation_import_is_inert(tmp_path):
    code = """
import subprocess,sys
def forbidden(*args,**kwargs): raise AssertionError('process executed during public import')
subprocess.Popen=forbidden
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as module
for name in ('legal_graph_review','legal_family_routes','legal_corpus_incremental','legal_source_definition_norm_lake'):
    assert 'ipfs_datasets_py.logic.autoformal.'+name not in sys.modules,name
assert not any(name in sys.modules for name in ('torch','transformers','tensorflow'))
assert callable(module.prepare_definition_use_corpus_v2)
"""
    env = dict(
        os.environ, PYTHONDONTWRITEBYTECODE="1", IPFS_DATASETS_PY_MINIMAL_IMPORTS="1"
    )
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[4])
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def write_project(owner, prepared, data, directory):
    return owner.write_definition_use_corpus_v2(prepared, directory, **arguments(data))


def load_project(owner, data, directory, manifest_sha256):
    return owner.load_definition_use_corpus_v2(
        directory, expected_manifest_sha256=manifest_sha256, **arguments(data)
    )


def test_project_writer_loader_bind_every_generated_byte_to_external_manifest_pin(
    owner, base, frozen, tmp_path
):
    directory = tmp_path / "project"
    assert write_project(owner, frozen, base, directory) == frozen.to_dict()
    raw = (directory / "corpus-manifest.json").read_bytes()
    assert raw == frozen.manifest_json.encode()
    assert load_project(owner, base, directory, sha(raw)) == frozen
    assert {
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file()
    } == {"corpus-manifest.json", *dict(frozen.files)}


@pytest.mark.parametrize("damage", ["changed", "missing", "extra", "symlink"])
def test_loader_refuses_changed_incomplete_extra_or_linked_native_projects(
    owner, base, frozen, tmp_path, damage
):
    directory = tmp_path / "project"
    write_project(owner, frozen, base, directory)
    manifest_sha = sha((directory / "corpus-manifest.json").read_bytes())
    source = directory / "LegalCorpusV2.lean"
    if damage == "changed":
        source.write_text(source.read_text() + "\n-- changed generated source\n")
    elif damage == "missing":
        source.unlink()
    elif damage == "extra":
        (directory / "foreign.lean").write_text("def injected : Prop := True\n")
    else:
        outside = tmp_path / "outside.lean"
        outside.write_text(source.read_text())
        source.unlink()
        source.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        load_project(owner, base, directory, manifest_sha)


def test_project_loader_requires_independent_manifest_pin_and_writer_never_overwrites(
    owner, base, frozen, tmp_path
):
    directory = tmp_path / "project"
    write_project(owner, frozen, base, directory)
    with pytest.raises(ValueError):
        load_project(owner, base, directory, "0" * 64)
    before = {
        str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()
    }
    with pytest.raises((ValueError, OSError)):
        write_project(owner, frozen, base, directory)
    assert before == {
        str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()
    }


# Complete original norms and bound-variable conditionals share one closed
# project without selecting a governing definition or rewriting the norm.
_BOUND_NORM_FIXTURE_BASELINE = None


def bound_norm_definition_data(mode="body_with_membership", *, link_index=0):
    """Reuse the existing fictional source/evidence fixture only when called.

    Two typed actor uses share one physical source anchor. They do not become
    two independent statutory occurrences, and all substantive reviews stay open.
    """
    global _BOUND_NORM_FIXTURE_BASELINE
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as lake

    if _BOUND_NORM_FIXTURE_BASELINE is None:
        helper = fixture_module("test_legal_bound_variable_definition_v1.py",
                                "bound_norm_definition_original_fixture")
        _BOUND_NORM_FIXTURE_BASELINE = (helper, helper.baseline.__wrapped__())
    helper, baseline = _BOUND_NORM_FIXTURE_BASELINE
    request = helper.declaration(baseline, link_index=link_index, mode=mode)
    report = baseline["report"] if mode == "instance_only" and link_index == 0 else \
        helper.prepare(baseline, request)
    request_raw = helper.wire(request)
    data = deepcopy({
        "bound_report": report,
        "expected_bound_report_sha256": bound.bound_variable_definition_sha256(report),
        "bound_definition_inputs": {
            "companion": baseline["companion"], "request_raw": request_raw,
            "expected_companion_sha256": baseline["companion_sha256"],
            "expected_request_sha256": sha(request_raw),
            "companion_inputs": baseline["inputs"],
        },
        "toolchain": TOOLCHAIN,
    })
    return data, lake.prepare_bound_norm_definition_corpus_v1(**data)


@pytest.fixture(scope="module")
def bound_norm_instance():
    return bound_norm_definition_data("instance_only")


@pytest.fixture(scope="module")
def bound_norm_body():
    return bound_norm_definition_data("body_with_membership")


def _bound_norm_validate(owner, data, prepared):
    return owner.validate_bound_norm_definition_corpus_v1(prepared,
        expected_preparation_sha256=owner.bound_norm_definition_preparation_sha256(prepared),
        **data)


def _bound_norm_write(owner, data, prepared, directory):
    return owner.write_bound_norm_definition_corpus_v1(prepared, directory,
        expected_preparation_sha256=owner.bound_norm_definition_preparation_sha256(prepared),
        **data)


def _bound_norm_load(owner, data, prepared, directory, manifest_pin):
    return owner.load_bound_norm_definition_corpus_v1(directory,
        expected_manifest_sha256=manifest_pin,
        expected_preparation_sha256=owner.bound_norm_definition_preparation_sha256(prepared),
        **data)


def _bound_norm_no_authority(owner, manifest):
    assert all(manifest[key] is False for key in owner.BOUND_NORM_FALSE_FLAGS)
    assert all(value is False for value in manifest["authority"].values())
    assert manifest["norm_interpretation_ready"] is False
    assert manifest["selected_interpretation"] is None
    assert manifest["governing_definition_use"] is None
    assert type(manifest["training_mask"]) is int and manifest["training_mask"] == 0
    assert type(manifest["evaluation_gold_mask"]) is int and manifest["evaluation_gold_mask"] == 0
    assert manifest["execution_handoff"]["build_eligible"] is False
    assert manifest["execution_handoff"]["processes_executed"] == 0
    assert manifest["execution_handoff"]["observed_theorem_axiom_dependencies"] is None
    assert manifest["execution_handoff"]["installed_binary_pins"] is None


@pytest.mark.parametrize("mode,theorem_count", [("instance_only", 2), ("body_with_membership", 3)],
                         ids=["instance", "membership"])
def test_bound_norm_project_preserves_complete_norm_and_conditional_source(
    owner, bound_norm_instance, bound_norm_body, mode, theorem_count
):
    data, prepared = bound_norm_instance if mode == "instance_only" else bound_norm_body
    manifest, files = prepared.to_dict(), dict(prepared.files)
    bound = data["bound_report"]
    original_norm = data["bound_definition_inputs"]["companion_inputs"]["norm_preparation"][
        "correspondence"]["relational_fragment"]
    fragments = {row["role"]: row for row in manifest["native_fragments"]}
    assert set(fragments) == {"norm", "definition"}
    assert fragments["norm"]["native"] == original_norm["native_fragment"]
    assert fragments["definition"]["native"] == bound["definition_native_fragment"]
    assert original_norm["source_binding"] is None and original_norm["source_bound"] is False
    assert manifest["original_norm"] == bound["original_norm"]
    assert manifest["occurrence_binding"] == bound["occurrence_binding"]
    assert manifest["selected_link"] == bound["selected_link"]
    assert manifest["definition_alternatives"] == bound["definition_alternatives"]
    assert manifest["nomination_inventory"] == bound["nomination_inventory"]
    assert len(manifest["definition_alternatives"]) == 2
    assert len(manifest["nomination_inventory"]) == 4
    assert len({row["request_link"]["target"]["typed_path"]
                for row in manifest["nomination_inventory"]}) == 2
    assert {tuple(row["request_link"]["source_paths"])
            for row in manifest["nomination_inventory"]} == {("/occurrences/0/anchor",)}
    assert manifest["schema"] == owner.BOUND_NORM_SCHEMA
    assert manifest["profile"] == owner.BOUND_NORM_PROFILE
    assert len(files) == 9 and len(manifest["expected_modules"]) == 6
    assert all(sha(body.encode()) == manifest["file_sha256"][name]
               for name, body in files.items())
    modules, imports = manifest["expected_modules"], manifest["module_imports"]
    for index, name in enumerate(modules):
        text = files[name.replace(".", "/") + ".lean"]
        assert re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", text) == imports[name]
        assert all(dependency in modules[:index] for dependency in imports[name])
    norm_source = files[fragments["norm"]["module"].replace(".", "/") + ".lean"]
    assert original_norm["lean_body"] in norm_source
    source_binding = manifest["conditional_source_binding"]
    occurrence_module = source_binding["theorem_names"][0]["project"].rsplit(".", 1)[0]
    occurrence = files[occurrence_module.replace(".", "/") + ".lean"]
    original_tail = "theorem definition_instance " + bound["lean_source"].split(
        "\ntheorem definition_instance ", 1)[1].removesuffix("end LegalBoundVariableDefinition\n")
    assert original_tail in occurrence
    assert source_binding["conditional_theorem_body_sha256"] == sha(original_tail.encode())
    assert len(manifest["conditional_theorems"]) == theorem_count
    all_lean = "\n".join(body for name, body in files.items() if name.endswith(".lean"))
    assert len(re.findall(r"(?m)^theorem ", all_lean)) == theorem_count
    assert all_lean.count("#print axioms ") == theorem_count
    assert "exact Iff.rfl" in all_lean and "original_norm_preserved" in all_lean
    assert "hNorm" not in all_lean
    assert not re.search(r"\b(?:sorry|admit|axiom|unsafe)\b", all_lean)
    assert ("hMembership" in occurrence) is (mode == "body_with_membership")
    assert ("theorem body_instance " in occurrence) is (mode == "body_with_membership")
    assert "exact hDefinition entity" in occurrence
    if mode == "body_with_membership":
        assert "exact (hDefinition entity).mp hMembership" in occurrence
    _bound_norm_no_authority(owner, manifest)
    assert _bound_norm_validate(owner, data, prepared) == prepared


@pytest.mark.parametrize("link_index", [2, 1], ids=["second-typed-use", "other-definition"])
def test_bound_norm_selection_retains_all_alternatives_and_exact_typed_use(
    owner, bound_norm_body, link_index
):
    baseline_data, baseline = bound_norm_body
    data, prepared = bound_norm_definition_data(link_index=link_index)
    first, current = baseline.to_dict(), prepared.to_dict()
    assert current["original_norm"] == first["original_norm"]
    assert current["definition_alternatives"] == first["definition_alternatives"]
    assert current["nomination_inventory"] == first["nomination_inventory"]
    assert current["selected_link"] != first["selected_link"]
    assert current["occurrence_binding"] == data["bound_report"]["occurrence_binding"]
    assert current["review_intake_binding"]["bound_definition_report_sha256"] == \
        data["expected_bound_report_sha256"]
    assert owner.bound_norm_definition_preparation_sha256(prepared) != \
        owner.bound_norm_definition_preparation_sha256(baseline)
    if link_index == 2:
        assert data["bound_report"]["request"]["alternative_id"] == \
            baseline_data["bound_report"]["request"]["alternative_id"]
        assert current["occurrence_binding"]["target"] != first["occurrence_binding"]["target"]
    else:
        assert data["bound_report"]["request"]["alternative_id"] != \
            baseline_data["bound_report"]["request"]["alternative_id"]
    _bound_norm_no_authority(owner, current)


@pytest.mark.parametrize("damage", ["bound-pin", "request-pin", "companion-pin", "missing-input", "toolchain"],
                         ids=["bound-pin", "request-pin", "companion-pin", "missing-input", "toolchain"])
def test_bound_norm_independent_inputs_refuse_before_operation_owners(
    owner, bound_norm_body, monkeypatch, damage
):
    data = deepcopy(bound_norm_body[0])
    if damage == "bound-pin":
        data["expected_bound_report_sha256"] = "0" * 64
    elif damage == "request-pin":
        data["bound_definition_inputs"]["expected_request_sha256"] = "0" * 64
    elif damage == "companion-pin":
        data["bound_definition_inputs"]["expected_companion_sha256"] = "0" * 64
    elif damage == "missing-input":
        data["bound_definition_inputs"].pop("companion_inputs")
    else:
        data["toolchain"] = "leanprover/lean4:stable"
    def forbidden():
        raise AssertionError("invalid independent input reached operation owners")
    monkeypatch.setattr(owner, "_owners", forbidden)
    with pytest.raises(ValueError):
        owner.prepare_bound_norm_definition_corpus_v1(**data)


@pytest.mark.parametrize("operation", ["validate", "write"], ids=["validate", "write"])
def test_bound_norm_preparation_commitment_refuses_before_owners(
    owner, bound_norm_body, tmp_path, monkeypatch, operation
):
    data, prepared = bound_norm_body
    def forbidden():
        raise AssertionError("wrong preparation commitment reached operation owners")
    monkeypatch.setattr(owner, "_owners", forbidden)
    with pytest.raises(ValueError):
        if operation == "validate":
            owner.validate_bound_norm_definition_corpus_v1(prepared,
                expected_preparation_sha256="0" * 64, **data)
        else:
            owner.write_bound_norm_definition_corpus_v1(prepared, tmp_path / "never-written",
                expected_preparation_sha256="0" * 64, **data)
    assert not (tmp_path / "never-written").exists()


@pytest.mark.parametrize("damage", ["membership", "alternative"], ids=["membership", "alternative"])
def test_bound_norm_rehashed_bound_report_cannot_promote_or_drop_original_evidence(
    owner, bound_norm_body, damage
):
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as bound
    data = deepcopy(bound_norm_body[0])
    if damage == "membership":
        data["bound_report"]["authority"]["membership_assumption_verified"] = True
    else:
        data["bound_report"]["definition_alternatives"].pop()
    data["expected_bound_report_sha256"] = bound.bound_variable_definition_sha256(data["bound_report"])
    with pytest.raises(ValueError):
        owner.prepare_bound_norm_definition_corpus_v1(**data)


@pytest.mark.parametrize("damage", ["authority", "norm-body", "premise"],
                         ids=["authority", "norm-body", "premise"])
def test_bound_norm_resealed_project_cannot_change_authority_norm_or_membership_premise(
    owner, bound_norm_body, damage
):
    data, prepared = bound_norm_body
    manifest, files = prepared.to_dict(), dict(prepared.files)
    if damage == "authority":
        manifest["norm_truth_proved"] = True
    else:
        if damage == "norm-body":
            row = next(row for row in manifest["native_fragments"] if row["role"] == "norm")
            path = row["module"].replace(".", "/") + ".lean"
            files[path] += "\n-- changed complete norm source\n"
        else:
            name = manifest["conditional_source_binding"]["theorem_names"][0]["project"]
            path = name.rsplit(".", 1)[0].replace(".", "/") + ".lean"
            assert "(hMembership : headAt i entity t)" in files[path]
            files[path] = files[path].replace("(hMembership : headAt i entity t)", "")
        manifest["file_sha256"][path] = sha(files[path].encode())
    changed = replace(prepared, files=tuple(sorted(files.items())))
    changed = modified_manifest(changed, manifest)
    with pytest.raises(ValueError):
        _bound_norm_validate(owner, data, changed)


@pytest.mark.parametrize("damage", ["bytes", "cycle", "depth"], ids=["bytes", "cycle", "depth"])
def test_bound_norm_complete_input_bounds_precede_operation_owners(
    owner, bound_norm_body, monkeypatch, damage
):
    data = deepcopy(bound_norm_body[0])
    if damage == "bytes":
        monkeypatch.setattr(owner, "MAX_INPUT_BYTES", 1)
    else:
        inputs = data["bound_definition_inputs"]["companion_inputs"]["norm_inputs"]
        if damage == "cycle":
            inputs["budget_probe"] = inputs
        else:
            nested = None
            for _ in range(60):
                nested = [nested]
            inputs["budget_probe"] = nested
    def forbidden():
        raise AssertionError("unbounded complete graph reached operation owners")
    monkeypatch.setattr(owner, "_owners", forbidden)
    with pytest.raises(ValueError):
        owner.prepare_bound_norm_definition_corpus_v1(**data)


def test_bound_norm_replay_is_input_immutable_and_never_probes_native_tools(
    owner, bound_norm_body
):
    from ipfs_datasets_py.logic.autoformal import legal_pilot_lake
    from ipfs_datasets_py.logic.backends import process
    data, prepared = bound_norm_body
    before = deepcopy(data)
    def forbidden(*args, **kwargs):
        raise AssertionError("bound norm preparation cannot run or probe a tool")
    with patch("subprocess.Popen", forbidden), \
         patch.object(process.BoundedToolRunner, "run", forbidden), \
         patch.object(legal_pilot_lake, "_installed_toolchain", forbidden):
        assert _bound_norm_validate(owner, data, prepared) == prepared
    assert data == before


@pytest.mark.parametrize("damage", ["changed", "missing", "extra", "alias"],
                         ids=["changed", "missing", "extra", "alias"])
def test_bound_norm_loader_refuses_modified_or_aliased_complete_project(
    owner, bound_norm_body, tmp_path, damage
):
    data, prepared = bound_norm_body
    directory = tmp_path / "bound-norm-project"
    _bound_norm_write(owner, data, prepared, directory)
    manifest_pin = sha((directory / "corpus-manifest.json").read_bytes())
    root = prepared.to_dict()["expected_modules"][-1].replace(".", "/") + ".lean"
    source = directory / root
    offered = directory
    descriptor = None
    if damage == "changed":
        source.write_text(source.read_text() + "\n-- transport changed\n")
    elif damage == "missing":
        source.unlink()
    elif damage == "extra":
        (directory / "foreign.lean").write_text("def foreign : Prop := True\n")
    else:
        # An existing proc-fd directory alias exercises literal-path refusal
        # without creating an owned symlink that violates managed inventory.
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        offered = Path("/proc/self/fd") / str(descriptor)
    try:
        with pytest.raises((ValueError, OSError)):
            _bound_norm_load(owner, data, prepared, offered, manifest_pin)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def test_bound_norm_writer_loader_exact_bytes_and_independent_pins(owner, bound_norm_body, tmp_path):
    data, prepared = bound_norm_body
    directory = tmp_path / "bound-norm-project"
    assert _bound_norm_write(owner, data, prepared, directory) == prepared.to_dict()
    raw = (directory / "corpus-manifest.json").read_bytes()
    assert raw == prepared.manifest_json.encode()
    assert _bound_norm_load(owner, data, prepared, directory, sha(raw)) == prepared
    assert {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()} == \
        {"corpus-manifest.json", *dict(prepared.files)}
    with pytest.raises((ValueError, OSError)):
        _bound_norm_load(owner, data, prepared, directory, "0" * 64)
    with pytest.raises((ValueError, OSError)):
        _bound_norm_write(owner, data, prepared, directory)


def test_bound_norm_profile_does_not_change_legacy_preparation_in_same_process(
    owner, base, frozen, bound_norm_body
):
    assert prepare(owner, base) == frozen
    data, prepared = bound_norm_body
    assert _bound_norm_validate(owner, data, prepared) == prepared
    assert prepare(owner, base) == frozen


# Direct parent complete-norm preparation is separate from HTML bound-definition
# composition. These authored fixtures preserve the whole relational norm and
# original physical parent replay; no meaning, definition or build is supplied.
@pytest.fixture(scope="module")
def parent_norm_helpers():
    return fixture_module("test_legal_norm_scope_correspondence_v1.py",
                          "parent_complete_norm_original_correspondence_fixture")


def _parent_norm_materialize(helper, directory, *, selected=0, variant="necessary"):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    source = helper.scope_fixture.parent_case(directory, selected=selected)
    original_request = helper.authored_request
    with patch.object(helper, "authored_request", lambda: original_request(
            sufficient=variant == "sufficient", swapped=variant == "swapped_roles")):
        value = helper.parent_correspondence_case(directory, source_value=source)
    report = helper.parent_correspondence_prepare(value)
    positional, keyword = helper.parent_correspondence_arguments(value)
    inputs = dict(zip(("scope_report", "relational_report", "mapping_request_raw"),
                      positional, strict=True)) | keyword
    return {"correspondence": report,
            "expected_correspondence_sha256": correspondence.norm_scope_correspondence_sha256(report),
            "correspondence_inputs": inputs, "toolchain": TOOLCHAIN}


@pytest.fixture(scope="module")
def parent_norm_base(parent_norm_helpers, tmp_path_factory):
    return _parent_norm_materialize(parent_norm_helpers,
        tmp_path_factory.mktemp("parent-complete-norm-originals", numbered=False))


def _parent_norm_prepare(owner, data):
    return owner.prepare_parent_norm_corpus_v1(**data)


def _parent_norm_validate(owner, prepared, data, **overrides):
    return owner.validate_parent_norm_corpus_v1(prepared,
        expected_preparation_sha256=owner.parent_norm_preparation_sha256(prepared),
        **(data | overrides))


def _parent_norm_parent_path(data):
    replay = data["correspondence_inputs"]["scope_replay_inputs"]["replay_inputs"]
    return Path(replay["parent_text_views_inputs"]["parent_descriptor"]["local_path"])


def _parent_norm_assert_unsigned(manifest):
    assert manifest["authority"] and all(value is False for value in manifest["authority"].values())
    for name in ("training_mask", "evaluation_gold_mask"):
        assert type(manifest[name]) is int and manifest[name] == 0
    assert manifest["preparation_only"] is True
    assert manifest["lean_compilation_status"] == "not_run"
    assert manifest["proof_status"] == "pending"
    assert manifest["execution_handoff"]["build_eligible"] is False
    assert manifest["execution_handoff"]["processes_executed"] == 0
    assert manifest["execution_handoff"]["observed_theorem_axiom_dependencies"] is None
    assert manifest["execution_handoff"]["installed_binary_pins"] is None


@pytest.mark.parametrize("variant", ["necessary", "sufficient", "swapped_roles"])
def test_parent_complete_norm_project_preserves_full_relational_content_and_closed_imports(
        owner, parent_norm_helpers, parent_norm_base, tmp_path, monkeypatch, variant):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context as markup
    data = parent_norm_base if variant == "necessary" else _parent_norm_materialize(
        parent_norm_helpers, tmp_path / "originals", variant=variant)
    before = deepcopy(data)
    observed = []
    genuine = correspondence.validate_norm_scope_correspondence_v2
    def replayed(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append(result)
        return result
    def forbidden(*args, **kwargs):
        raise AssertionError("parent norm preparation must neither invent HTML nor execute a process")
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", replayed)
    monkeypatch.setattr(markup, "extract_document", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    prepared = _parent_norm_prepare(owner, data)
    assert len(observed) == 2
    manifest, files = prepared.to_dict(), dict(prepared.files)
    original = data["correspondence"]
    norm = original["relational_fragment"]
    assert type(prepared) is owner.DefinitionUseCorpusPreparation
    assert manifest["schema"] == owner.PARENT_NORM_SCHEMA
    assert manifest["profile"] == owner.PARENT_NORM_PROFILE
    assert manifest["correspondence"] == original
    assert manifest["correspondence_sha256"] == data["expected_correspondence_sha256"]
    assert manifest["original_norm"]["source_binding"] is None
    assert manifest["original_norm"]["source_bound"] is False
    assert manifest["original_norm"]["unchanged"] is True
    assert norm["source_binding"] is None and norm["source_bound"] is False
    assert manifest["declared_semantic_coverage"] == original["declared_semantic_coverage"] == "partial"
    assert original["source_scope"]["parent_source_binding"]["context"]["availability"] == "required_unavailable"
    assert manifest["original_parent_context"] == original["source_scope"]["source_context_record"]
    assert manifest["review_blockers"]
    assert manifest["native_fragments"] == [{"role": "norm",
        "module": manifest["native_fragments"][0]["module"], "native": norm["native_fragment"]}]
    expression = norm["typed_expression"]
    assert expression == data["correspondence_inputs"]["relational_report"]["typed_expression"]
    if variant != "necessary":
        baseline_norm = parent_norm_base["correspondence"]["relational_fragment"]
        assert expression != baseline_norm["typed_expression"]
        assert norm["typed_expression_content_digest"] != baseline_norm["typed_expression_content_digest"]
        assert norm["native_formula"] != baseline_norm["native_formula"]
        assert norm["native_ast"] != baseline_norm["native_ast"]
    assert len([row for row in norm["structural_mapping"] if row["kind"] == "binder"]) == 2
    assert norm["argument_roles"] == data["correspondence_inputs"]["relational_report"]["argument_roles"]
    assert len(files) == len(prepared.files) == 7
    modules = manifest["expected_modules"]
    assert len(modules) == 4 and modules[0] == "LegalCorpusParentNorm.Prelude"
    assert modules[-1] == "LegalCorpusParentNorm"
    assert files["lean-toolchain"] == TOOLCHAIN + "\n"
    assert "parent-norm-input-bindings.json" in files
    assert not {"v2-input-bindings.json", "parent-input-bindings.json"} & files.keys()
    for index, module in enumerate(modules):
        body = files[module.replace(".", "/") + ".lean"]
        imports = re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", body)
        assert imports == manifest["module_imports"][module]
        assert all(dependency in modules[:index] for dependency in imports)
    assert all(sha(body.encode("utf-8")) == manifest["file_sha256"][name]
               for name, body in files.items())
    norm_module = manifest["native_fragments"][0]["module"]
    assert norm["lean_body"] in files[norm_module.replace(".", "/") + ".lean"]
    lean = "\n".join(body for name, body in files.items() if name.endswith(".lean"))
    assert len(manifest["conditional_theorems"]) == 1
    assert manifest["conditional_theorems"][0].endswith(".original_norm_preserved")
    assert len(re.findall(r"(?m)^theorem ", lean)) == 1
    assert lean.count("#print axioms ") == 1 and "Iff.rfl" in lean
    assert not re.search(r"\b(?:sorry|admit|axiom|unsafe|hDefinition|hMembership)\b", lean)
    _parent_norm_assert_unsigned(manifest)
    assert _parent_norm_validate(owner, prepared, data) == prepared
    assert len(observed) == 4 and data == before


@pytest.mark.parametrize("selected", [1, 2], ids=["other-offset", "other-physical-row"])
def test_parent_complete_norm_equal_literals_keep_original_physical_identity(
        owner, parent_norm_helpers, parent_norm_base, tmp_path, selected):
    data = _parent_norm_materialize(parent_norm_helpers, tmp_path, selected=selected)
    first = _parent_norm_prepare(owner, parent_norm_base)
    other = _parent_norm_prepare(owner, data)
    assert data["correspondence"]["relational_fragment"] == parent_norm_base["correspondence"]["relational_fragment"]
    binding = data["correspondence"]["source_scope"]["parent_source_binding"]
    previous = parent_norm_base["correspondence"]["source_scope"]["parent_source_binding"]
    assert binding["selector"]["span_text"] == previous["selector"]["span_text"]
    assert binding["selector"]["record_cid"] != previous["selector"]["record_cid"]
    assert other.to_dict()["parent_source_binding_sha256"] != first.to_dict()["parent_source_binding_sha256"]
    assert owner.parent_norm_preparation_sha256(other) != owner.parent_norm_preparation_sha256(first)
    _parent_norm_assert_unsigned(other.to_dict())


@pytest.mark.parametrize("pin", ["correspondence", "request", "preparation"])
def test_parent_complete_norm_independent_commitments_refuse_before_replay(
        owner, parent_norm_base, monkeypatch, pin):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    data = deepcopy(parent_norm_base)
    prepared = _parent_norm_prepare(owner, data) if pin == "preparation" else None
    def forbidden(*args, **kwargs):
        raise AssertionError("independent commitment failed after correspondence replay")
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", forbidden)
    if pin == "correspondence":
        data["expected_correspondence_sha256"] = "0" * 64
    elif pin == "request":
        data["correspondence_inputs"]["expected_mapping_request_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        if prepared is None:
            _parent_norm_prepare(owner, data)
        else:
            owner.validate_parent_norm_corpus_v1(prepared,
                expected_preparation_sha256="0" * 64, **data)


@pytest.mark.parametrize("damage", ["report-bytes", "physical-parent"])
def test_parent_complete_norm_repaired_outer_pins_cannot_replace_original_parent_replay(
        owner, parent_norm_helpers, tmp_path, damage):
    data = _parent_norm_materialize(parent_norm_helpers, tmp_path)
    replay = data["correspondence_inputs"]["scope_replay_inputs"]
    if damage == "report-bytes":
        replay["report_bytes"]["parent_text_views"] += b" "
        replay["expected_report_pins"]["parent_text_views"]["raw_sha256"] = sha(
            replay["report_bytes"]["parent_text_views"])
    else:
        path = _parent_norm_parent_path(data)
        path.write_bytes(path.read_bytes() + b" changed after genuine parent preparation")
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, data)


@pytest.mark.parametrize("damage", ["typed-target", "source-row"])
def test_parent_complete_norm_rehashed_correspondence_cannot_drop_complete_accounting(
        owner, parent_norm_base, damage):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    data = deepcopy(parent_norm_base)
    key = "typed_rows" if damage == "typed-target" else "source_rows"
    data["correspondence"]["request"][key].pop()
    data["expected_correspondence_sha256"] = correspondence.norm_scope_correspondence_sha256(data["correspondence"])
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, data)


@pytest.mark.parametrize("damage", ["norm-body", "imports", "authority"])
def test_parent_complete_norm_rehashed_project_cannot_change_norm_imports_or_authority(
        owner, parent_norm_base, damage):
    prepared = _parent_norm_prepare(owner, parent_norm_base)
    manifest, files = prepared.to_dict(), dict(prepared.files)
    if damage == "authority":
        manifest["authority"][next(iter(manifest["authority"]))] = True
    else:
        module = manifest["native_fragments"][0]["module"] if damage == "norm-body" else manifest["expected_modules"][-1]
        path = module.replace(".", "/") + ".lean"
        if damage == "norm-body":
            old = manifest["correspondence"]["relational_fragment"]["lean_body"]
            assert old in files[path]
            files[path] = files[path].replace(old, old.replace("formula_0", "changed_norm", 1), 1)
        else:
            files[path] += "\nimport LegalCorpusParentNorm.Unsupplied\n"
        manifest["file_sha256"][path] = sha(files[path].encode())
    offered = replace(modified_manifest(prepared, manifest), files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        _parent_norm_validate(owner, offered, parent_norm_base)


def test_parent_complete_norm_refuses_genuine_html_correspondence_profile(
        owner, parent_norm_helpers, parent_norm_base):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    value = parent_norm_helpers.case()
    report = parent_norm_helpers.prepare(value)
    positional, keywords = parent_norm_helpers.arguments(value)
    data = dict(correspondence=report,
        expected_correspondence_sha256=correspondence.norm_scope_correspondence_sha256(report),
        correspondence_inputs=dict(zip(("scope_report", "relational_report", "mapping_request_raw"),
                                       positional, strict=True)) | keywords,
        toolchain=TOOLCHAIN)
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, data)


@pytest.mark.parametrize("location", ["caller", "detached"])
def test_parent_complete_norm_late_original_inputs_are_fenced_after_genuine_replay(
        owner, parent_norm_base, monkeypatch, location):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    data = deepcopy(parent_norm_base)
    genuine = correspondence.validate_norm_scope_correspondence_v2
    observed = []
    def changed(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if not observed:
            observed.append("genuine_opening_correspondence_completed")
            target = data["correspondence"] if location == "caller" else args[0]
            target["training_mask"] = False
        return result
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", changed)
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, data)
    assert observed == ["genuine_opening_correspondence_completed"]


@pytest.mark.parametrize("return_index", [0, 1], ids=["opening", "closing"])
def test_parent_complete_norm_actual_validator_returns_remain_held_after_final_serialization(
        owner, parent_norm_base, monkeypatch, return_index):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    data = deepcopy(parent_norm_base)
    genuine = correspondence.validate_norm_scope_correspondence_v2
    actual_returns, observed = [], []
    def retained(*args, **kwargs):
        result = genuine(*args, **kwargs)
        actual_returns.append(result)
        return result
    serialized = owner._parent_norm_serialized_fence
    def changed(preparation, expected_storage):
        result = serialized(preparation, expected_storage)
        if not observed:
            assert len(actual_returns) == 2
            observed.append("genuine_final_storage_check_completed")
            actual_returns[return_index]["training_mask"] = False
        return result
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", retained)
    monkeypatch.setattr(owner, "_parent_norm_serialized_fence", changed)
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, data)
    assert observed == ["genuine_final_storage_check_completed"]
    assert len(actual_returns) == 2


def test_parent_complete_norm_physical_parent_remains_bound_after_final_storage_check(
        owner, parent_norm_helpers, tmp_path, monkeypatch):
    data = _parent_norm_materialize(parent_norm_helpers, tmp_path)
    path = _parent_norm_parent_path(data)
    original = path.read_bytes()
    serialized = owner._parent_norm_serialized_fence
    observed = []
    def changed(preparation, expected_storage):
        result = serialized(preparation, expected_storage)
        if not observed:
            observed.append("genuine_final_storage_check_completed")
            path.write_bytes(original + b" changed after complete parent replay")
        return result
    monkeypatch.setattr(owner, "_parent_norm_serialized_fence", changed)
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, data)
    assert observed == ["genuine_final_storage_check_completed"]
    assert path.read_bytes() != original


def test_parent_complete_norm_producer_remains_bound_after_final_storage_check(
        owner, parent_norm_base, tmp_path, monkeypatch):
    original = Path(owner.__file__).read_bytes()
    copied = tmp_path / "copied_complete_parent_norm_lake_owner.py"
    copied.write_bytes(original)
    monkeypatch.setattr(owner, "__file__", str(copied))
    monkeypatch.setattr(owner, "_IMPORTED_PURE_PINS", owner._pure_pins())
    monkeypatch.setattr(owner, "_PARENT_NORM_OPERATION_PINS", None)
    serialized = owner._parent_norm_serialized_fence
    observed = []
    def changed(preparation, expected_storage):
        result = serialized(preparation, expected_storage)
        if not observed:
            observed.append("genuine_final_storage_check_completed")
            copied.write_bytes(original + b"\n# producer changed after complete parent replay\n")
        return result
    monkeypatch.setattr(owner, "_parent_norm_serialized_fence", changed)
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, deepcopy(parent_norm_base))
    assert observed == ["genuine_final_storage_check_completed"]
    assert copied.read_bytes() != original


def test_parent_complete_norm_final_preparation_storage_cannot_change_after_genuine_check(
        owner, parent_norm_base, monkeypatch):
    serialized = owner._parent_norm_serialized_fence
    observed = []
    def changed(preparation, expected_storage):
        result = serialized(preparation, expected_storage)
        observed.append("genuine_final_storage_check_completed")
        if len(observed) == 2:
            object.__setattr__(preparation, "manifest_json", preparation.manifest_json + " ")
        return result
    monkeypatch.setattr(owner, "_parent_norm_serialized_fence", changed)
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, deepcopy(parent_norm_base))
    assert observed == ["genuine_final_storage_check_completed"] * 2


@pytest.mark.parametrize("damage", ["bytes", "cycle"])
def test_parent_complete_norm_complete_input_bounds_precede_original_replay(
        owner, parent_norm_base, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    data = deepcopy(parent_norm_base)
    if damage == "bytes":
        monkeypatch.setattr(owner, "MAX_INPUT_BYTES", 1)
    else:
        nested = data["correspondence_inputs"]["scope_replay_inputs"]
        nested["budget_probe"] = nested
    def forbidden(*args, **kwargs):
        raise AssertionError("unbounded complete parent population reached genuine replay")
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", forbidden)
    with pytest.raises(ValueError):
        _parent_norm_prepare(owner, data)


def test_parent_complete_norm_primary_error_keeps_secondary_custody_failure_note(
        owner, parent_norm_base, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
    data = deepcopy(parent_norm_base)
    genuine = correspondence.validate_norm_scope_correspondence_v2
    primary = RuntimeError("authored primary complete-norm replay failure")
    observed = []
    def changed(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append("genuine_correspondence_completed")
        if len(observed) == 1:
            data["correspondence"]["training_mask"] = False
            raise primary
        return result
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", changed)
    with pytest.raises(RuntimeError) as caught:
        _parent_norm_prepare(owner, data)
    assert caught.value is primary
    assert observed and getattr(primary, "__notes__", [])
