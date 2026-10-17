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
