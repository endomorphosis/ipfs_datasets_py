"""Exact shared-definition custody and conditional Lean source; no execution."""

import base64
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_norm_adapter as adapter
from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_lake as native
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json

TOOLCHAIN = "leanprover/lean4:v4.34.1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()


def source(*, edition=2024, duplicate_definition=False):
    second = (
        '<p class="statutory-body-1em">(2) The term "covered filer" means registered or licensed.</p>'
        if duplicate_definition
        else ""
    )
    raw = (
        '<meta charset="utf-8"><h3 class="section-head">§1. Authored shared café fixture</h3>'
        '<p class="statutory-body">(a) Définitions — In this section:</p>'
        '<p class="statutory-body-1em">(1) The term "covered filer" means registered or licensed.</p>'
        + second
        + '<p class="statutory-body">(b) Each covered filer shall register.</p>'
        '<p class="statutory-body">(c) Each covered filer may file.</p>'
        '<p class="statutory-body">(d) Each covered filer shall not disclose.</p>'
    ).encode()
    url = (
        f"https://www.govinfo.gov/content/pkg/USCODE-{edition}-title40/html/"
        f"USCODE-{edition}-title40-sec1.htm"
    )
    document = context.extract_document(raw, url=url, edition=edition, legal_id="usc:us:40:1")
    return raw, document


def candidate(
    modality="O",
    family="deontic_fol",
    *,
    edition=2024,
    duplicate_definition=False,
    definition_index=1,
    norm_id=None,
):
    raw, document = source(edition=edition, duplicate_definition=duplicate_definition)
    text = document["document_text"]
    definition_start = document["paragraphs"][definition_index]["char_start"]

    def span(literal, start=0):
        left = text.index(literal, start)
        return {"char_start": left, "char_end": left + len(literal), "text": literal}

    declaration = {
        "declaration_id": "authored-shared-definition",
        "profile": bridge.definitions.PROFILE,
        "interpretation_status": "unreviewed_caller_declaration",
        "paragraph_index": definition_index,
        "scope_span": span("In this section:"),
        "definition_cue": span("means", definition_start),
        "head": span("covered filer", definition_start),
        "body": {
            "op": "any",
            "operands": [
                {"op": "atom", "span": span(literal, definition_start)}
                for literal in ("registered", "licensed")
            ],
        },
    }
    definition_request = {
        "document": document,
        "raw_html_base64": base64.b64encode(raw).decode(),
        "declaration": declaration,
        "family": "fol",
    }
    definition = bridge.definitions.prepare_definition(definition_request)
    norm_index = {"O": 2, "P": 3, "F": 4}[modality] + int(duplicate_definition)
    start = document["paragraphs"][norm_index]["char_start"]
    cue, action = bridge.CUES[modality], {"O": "register", "P": "file", "F": "disclose"}[modality]
    norm = {
        "norm_id": norm_id or "authored-shared-" + modality,
        "profile": bridge.PROFILE,
        "interpretation_status": "unreviewed_caller_declaration",
        **{
            key: document[key]
            for key in ("document_id", "document_text_sha256", "legal_id", "edition")
        },
        "paragraph_index": norm_index,
        "source_span": span(f"Each covered filer {cue} {action}.", start),
        "quantifier_span": span("Each", start),
        "category_span": span("covered filer", start),
        "modality_span": span(cue, start),
        "action_span": span(action, span(cue, start)["char_end"]),
        "modality": modality,
        "variable": "x",
        "definition_head_symbol": definition["native_ast"]["formula"]["left"]["name"],
        "activation_scope": bridge.ACTIVATION,
        "modal_context": None,
    }
    request = {
        "definition_request": definition_request,
        "norm_declaration": norm,
        "family": family,
        "source_provenance": {
            "kind": "authored_official_shape_fixture",
            "authenticity_verified": False,
            "independently_reviewed": False,
            "training_admitted": False,
        },
    }
    report = bridge.prepare_definition_norm(request)
    request_raw, report_raw = wire(request), wire(report)
    extracted_sha = sha(text.encode())
    record = adapter.adapt_definition_norm_bytes(
        report_raw,
        expected_report_sha256=sha(report_raw),
        request_raw=request_raw,
        expected_request_sha256=sha(request_raw),
        raw_html=raw,
        expected_raw_sha256=sha(raw),
        expected_extracted_sha256=extracted_sha,
    )
    candidate_raw = canonical_dag_json_bytes(record)
    inputs = {
        "candidate_raw": candidate_raw,
        "report_raw": report_raw,
        "request_raw": request_raw,
        "raw_html": raw,
    }
    pins = {
        "candidate_sha256": sha(candidate_raw),
        "candidate_cid": record["record_cid"],
        "graph_cid": record["graph"]["record_cid"],
        "request_sha256": sha(request_raw),
        "report_sha256": sha(report_raw),
        "raw_sha256": sha(raw),
        "extracted_sha256": extracted_sha,
    }
    return inputs, pins, record, report


def prepare(cases):
    return shared.prepare_shared_definition_corpus(
        [case[0] for case in cases],
        expected_population=[case[1] for case in cases],
        toolchain=TOOLCHAIN,
    )


def validate(preparation, cases):
    return shared.validate_shared_definition_corpus(
        preparation,
        candidate_inputs=[case[0] for case in cases],
        expected_population=[case[1] for case in cases],
        toolchain=TOOLCHAIN,
    )


def reseal(record):
    return contracts.seal_record(
        {key: item for key, item in record.items() if key not in {"record_cid", "cid_scope"}}
    )


@pytest.fixture(scope="module")
def small_shared():
    cases = [candidate("O"), candidate("P")]
    return cases, prepare(cases)


def test_common_source_three_modalities_two_families_share_one_exact_definition_and_six_norms():
    cases = [candidate(modality, family) for modality in "OPF" for family in bridge.FAMILIES]
    assert len({case[2]["source_version"]["record_cid"] for case in cases}) == 1
    assert len({case[2]["definition_record"]["record_cid"] for case in cases}) == 6
    preparation = prepare(cases)
    manifest, files = preparation.to_dict(), dict(preparation.files)
    assert len(manifest["definition_modules"]) == 1
    assert len(manifest["norm_bindings"]) == 6
    definition = manifest["definition_modules"][0]
    assert definition["sharing_key_cid"] == definition["sharing_key"]["record_cid"]
    assert definition["qualified_declaration"] == definition["module"] + ".formula_0"
    assert definition["body_declaration"] == definition["module"] + ".bodyAt"
    assert len(definition["contributors"]) == 6
    assert definition["module_sha256"] == sha(files[definition["module_path"]].encode())
    assert cases[0][3]["bound_definition_native"]["lean_body"] in files[definition["module_path"]]
    for ordinal, (norm, case) in enumerate(zip(manifest["norm_bindings"], cases, strict=True)):
        record = case[2]
        assert norm["ordinal"] == ordinal and norm["candidate_cid"] == record["record_cid"]
        assert norm["definition_key_cid"] == definition["sharing_key_cid"]
        assert norm["definition_module"] == definition["module"]
        assert norm["qualified_declaration"] == norm["module"] + ".formula_0"
        assert norm["composition_theorem"] == norm["module"] + ".consequence_of_definition"
        assert norm["native_norm_fragment"]["native_ast"] == record["norm_record"]["native_ast"]
        assert norm["native_norm_fragment"]["lean_body"] in files[norm["module_path"]]
        assert norm["module_sha256"] == sha(files[norm["module_path"]].encode())
        original = norm["original_joint_binding"]
        assert original["candidate_cid"] == record["record_cid"]
        assert original["graph_cid"] == record["graph"]["record_cid"]
        assert original["source_bindings"] == record["source_bindings"]
        assert original["source_occurrence_cids"] == [
            row["record_cid"] for row in record["source_occurrences"]
        ]
        contributor = definition["contributors"][ordinal]
        assert contributor == {
            "ordinal": ordinal,
            "candidate_cid": record["record_cid"],
            "definition_record_cid": record["definition_record"]["record_cid"],
            "interpretation_cid": record["report_record"]["record_cid"],
            "term_record_cid": record["term_record"]["record_cid"],
            "symbol_record_cid": record["symbol_record"]["record_cid"],
        }
    assert manifest["file_sha256"] == {name: sha(body.encode()) for name, body in files.items()}
    assert len(set(manifest["expected_modules"])) == len(manifest["expected_modules"])
    assert validate(preparation, cases) == preparation


def test_same_html_other_edition_has_different_definition_group():
    cases = [candidate(edition=edition, norm_id=f"edition-{edition}") for edition in (2024, 2025)]
    assert cases[0][0]["raw_html"] == cases[1][0]["raw_html"]
    assert cases[0][3]["definition"]["scope_key"] == cases[1][3]["definition"]["scope_key"]
    assert cases[0][3]["scope_key"] != cases[1][3]["scope_key"]
    manifest = prepare(cases).to_dict()
    assert len(manifest["definition_modules"]) == 2
    assert len({row["sharing_key_cid"] for row in manifest["definition_modules"]}) == 2


def test_equal_native_ast_at_distinct_definition_occurrences_is_not_merged():
    cases = [
        candidate(
            duplicate_definition=True,
            definition_index=index,
            norm_id=f"definition-occurrence-{index}",
        )
        for index in (1, 2)
    ]
    assert cases[0][0]["raw_html"] == cases[1][0]["raw_html"]
    assert cases[0][2]["source_version"] == cases[1][2]["source_version"]
    assert (
        cases[0][2]["definition_record"]["native_ast"]
        == cases[1][2]["definition_record"]["native_ast"]
    )
    assert (
        cases[0][2]["definition_record"]["declaration"]
        != cases[1][2]["definition_record"]["declaration"]
    )
    manifest = prepare(cases).to_dict()
    assert len(manifest["definition_modules"]) == 2 and len(manifest["norm_bindings"]) == 2


def test_shared_source_has_only_conditional_consequence_with_explicit_definition_norm_and_body_hypotheses(
    small_shared,
):
    cases, preparation = small_shared
    manifest, files = preparation.to_dict(), dict(preparation.files)
    for binding, case in zip(manifest["norm_bindings"], cases, strict=True):
        body = files[binding["module_path"]]
        assert "def modalActionAt" in body and "def jointAt" in body
        assert "theorem consequence_of_definition" in body
        assert all(re.search(r"\(h" + name + r"\s*:", body) for name in ("Def", "Norm", "Body"))
        assert binding["definition_module"] + ".formula_0" in body
        assert binding["definition_module"] + ".bodyAt" in body
        assert "∧" in body
        assert f'"deontic:{case[3]["norm_declaration"]["modality"]}"' in body
        assert not re.search(r"\b(?:axiom|sorry|admit)\b|:=\s*True\b", body)
    # Independent one-entity interpretations show why all three hypotheses are
    # necessary. This is a Boolean entailment check, not execution of Lean or a
    # claim that any predicate interpretation describes the law.
    absent = {"Def": False, "Norm": False, "Body": False}
    for category, registered, licensed, modal_action in itertools.product((False, True), repeat=4):
        hypotheses = {
            "Def": category == (registered or licensed),
            "Norm": not category or modal_action,
            "Body": registered or licensed,
        }
        if all(hypotheses.values()):
            assert modal_action
        for omitted in absent:
            if not modal_action and all(
                value for key, value in hypotheses.items() if key != omitted
            ):
                absent[omitted] = True
    assert all(absent.values())


def test_preparation_retains_false_legal_review_build_and_proof_authority(small_shared):
    _, preparation = small_shared
    manifest = preparation.to_dict()
    for key in (
        "source_semantics_verified",
        "source_authenticity_verified",
        "context_closure_verified",
        "independently_reviewed",
        "admitted",
        "formalized",
        "training_qualified",
        "proof_authority",
        "backend_executed",
        "lean_compilation_verified",
    ):
        assert manifest[key] is False


@pytest.mark.parametrize(
    "damage",
    [
        "definition_drop",
        "contributor_drop",
        "norm_drop",
        "wrong_group",
        "binding_source",
        "authority",
    ],
)
def test_resealed_manifest_cannot_omit_origins_modules_or_change_sharing_or_authority(
    small_shared, damage
):
    cases, preparation = small_shared
    manifest = preparation.to_dict()
    if damage == "definition_drop":
        manifest["definition_modules"] = []
    elif damage == "contributor_drop":
        manifest["definition_modules"][0]["contributors"].pop()
    elif damage == "norm_drop":
        manifest["norm_bindings"].pop()
    elif damage == "wrong_group":
        manifest["norm_bindings"][0]["definition_key_cid"] = cid_for_dag_json(
            {"other": "definition"}
        )
    elif damage == "binding_source":
        manifest["norm_bindings"][0]["original_joint_binding"]["source_bindings"] = []
    else:
        manifest["proof_authority"] = True
    changed = replace(
        preparation, manifest_json=canonical_dag_json_bytes(reseal(manifest)).decode()
    )
    with pytest.raises(contracts.CorpusContractError):
        validate(changed, cases)


@pytest.mark.parametrize(
    "damage",
    [
        "definition_true",
        "norm_true",
        "drop_definition_import",
        "drop_hypothesis",
        "missing_norm",
        "extra_module",
    ],
)
def test_repaired_file_hashes_cannot_weaken_shared_definition_or_conditional_composition(
    small_shared, damage
):
    cases, preparation = small_shared
    manifest, files = preparation.to_dict(), dict(preparation.files)
    definition_path, norm_path = (
        manifest["definition_modules"][0]["module_path"],
        manifest["norm_bindings"][0]["module_path"],
    )
    if damage == "definition_true":
        files[definition_path] = "def formula_0 : Prop := True\n"
    elif damage == "norm_true":
        files[norm_path] = "def formula_0 : Prop := True\n"
    elif damage == "drop_definition_import":
        files[norm_path] = (
            "\n".join(
                line for line in files[norm_path].splitlines() if not line.startswith("import ")
            )
            + "\n"
        )
    elif damage == "drop_hypothesis":
        files[norm_path] = files[norm_path].replace("hBody", "missingBody")
    elif damage == "missing_norm":
        del files[manifest["norm_bindings"][1]["module_path"]]
    else:
        files["Unlisted.lean"] = "axiom invented : False\n"
    manifest["file_sha256"] = {name: sha(body.encode()) for name, body in files.items()}
    changed = replace(
        preparation,
        files=tuple(sorted(files.items())),
        manifest_json=canonical_dag_json_bytes(reseal(manifest)).decode(),
    )
    with pytest.raises(contracts.CorpusContractError):
        validate(changed, cases)


def test_order_and_independent_population_cannot_be_changed_without_new_preparation(small_shared):
    cases, preparation = small_shared
    with pytest.raises(contracts.CorpusContractError):
        shared.prepare_shared_definition_corpus(
            [case[0] for case in reversed(cases)],
            expected_population=[case[1] for case in cases],
            toolchain=TOOLCHAIN,
        )
    with pytest.raises(contracts.CorpusContractError):
        validate(preparation, list(reversed(cases)))
    with pytest.raises(contracts.CorpusContractError):
        validate(preparation, cases[:1])


def test_source_graph_and_request_pins_are_still_enforced_before_sharing(small_shared):
    cases, _ = small_shared
    inputs, pins = [deepcopy(case[0]) for case in cases], [deepcopy(case[1]) for case in cases]
    pins[0]["graph_cid"] = cid_for_dag_json({"other": "graph"})
    with pytest.raises(contracts.CorpusContractError):
        shared.prepare_shared_definition_corpus(
            inputs, expected_population=pins, toolchain=TOOLCHAIN
        )


def test_shared_preparation_calls_no_build_runner_or_installed_toolchain_probe(
    monkeypatch, small_shared
):
    cases, _ = small_shared

    def forbidden(*args, **kwargs):
        raise AssertionError("shared preparation cannot run Lean or a backend")

    monkeypatch.setattr(native, "build", forbidden)
    monkeypatch.setattr(native.shared, "_installed_toolchain", forbidden)
    monkeypatch.setattr(native.process.BoundedToolRunner, "run", forbidden)
    preparation = prepare(cases)
    assert validate(preparation, cases) == preparation


def test_public_shared_import_leaves_session_native_owners_and_numerical_models_unloaded(tmp_path):
    code = """
import json, subprocess, sys
def forbidden(*args, **kwargs):
    raise AssertionError('public shared import executed a process')
subprocess.Popen = forbidden
from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake
import ipfs_datasets_py.logic.autoformal as package
assert 'SESSION' not in vars(package)
assert not any(name in sys.modules for name in ('torch','transformers','tensorflow'))
assert 'ipfs_datasets_py.logic.autoformal.legal_source_definition_norm_bridge' not in sys.modules
assert 'ipfs_datasets_py.logic.autoformal.legal_source_definition_norm_lake' not in sys.modules
print(json.dumps({'public_import_inert': True}))
"""
    env = dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", PYTHONDONTWRITEBYTECODE="1")
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
    assert json.loads(result.stdout) == {"public_import_inert": True}
    assert not list(tmp_path.iterdir())


def test_shared_project_writer_loader_preserve_exact_manifest_and_all_modules(
    tmp_path, small_shared
):
    cases, preparation = small_shared
    directory = tmp_path / "project"
    kwargs = {
        "candidate_inputs": [case[0] for case in cases],
        "expected_population": [case[1] for case in cases],
        "toolchain": TOOLCHAIN,
    }
    written = shared.write_shared_definition_corpus(preparation, directory, **kwargs)
    assert written == preparation.to_dict()
    manifest_sha = sha(preparation.manifest_json.encode())
    assert (
        shared.load_shared_definition_corpus(
            directory, expected_manifest_sha256=manifest_sha, **kwargs
        )
        == preparation
    )
    assert {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    } == {
        **{name: body.encode() for name, body in preparation.files},
        "corpus-manifest.json": preparation.manifest_json.encode(),
    }
    with pytest.raises(contracts.CorpusContractError):
        shared.load_shared_definition_corpus(directory, expected_manifest_sha256="0" * 64, **kwargs)
    with pytest.raises((contracts.CorpusContractError, FileExistsError)):
        shared.write_shared_definition_corpus(preparation, directory, **kwargs)
    (directory / preparation.to_dict()["norm_bindings"][1]["module_path"]).unlink()
    with pytest.raises(contracts.CorpusContractError):
        shared.load_shared_definition_corpus(
            directory, expected_manifest_sha256=manifest_sha, **kwargs
        )


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "missing_nonfirst_definition",
        "missing_nonfirst_norm",
        "missing_axiom",
        "binary_changed",
        "workspace_not_cleaned",
        "error_on_success",
        "postrun_revalidation_refused",
        "missing_binary",
    ],
)
def test_fake_native_build_requires_every_definition_norm_axiom_and_unchanged_binary(
    monkeypatch, tmp_path, small_shared, failure
):
    # Only this fake runner executes. The .olean bytes explicitly identify their
    # authored provenance and cannot be mistaken for actual compiler output.
    cases, preparation = small_shared
    if failure == "missing_nonfirst_definition":
        cases = [candidate(edition=year, norm_id=f"build-edition-{year}") for year in (2024, 2025)]
        preparation = prepare(cases)
    manifest = preparation.to_dict()
    executable = tmp_path / "fake-lake"
    executable.write_bytes(b"\x7fELF-authored-unit-test-stub-no-real-compiler")
    binary_sha = sha(executable.read_bytes())
    monkeypatch.setattr(
        native.shared,
        "_installed_toolchain",
        lambda *args: (executable, {str(executable): binary_sha}, {"fixture": "fake toolchain"}),
    )
    captured = {}
    original_validate = shared.validate_shared_definition_corpus
    validation_calls = []
    if failure == "postrun_revalidation_refused":

        def refuse_postrun(*args, **kwargs):
            validation_calls.append("validate")
            if len(validation_calls) > 1:
                raise contracts.CorpusContractError("authored post-run integrity refusal")
            return original_validate(*args, **kwargs)

        monkeypatch.setattr(shared, "validate_shared_definition_corpus", refuse_postrun)

    def fake_run(self, request, **kwargs):
        assert request.argv == (str(executable), "--offline", "--no-cache", "build", "legal")
        assert request.input_files == dict(preparation.files)
        assert request.environment == {"ELAN_TOOLCHAIN": TOOLCHAIN, "LEAN_NUM_THREADS": "1"}
        assert request.output_paths == tuple(
            ".lake/build/lib/lean/" + module.replace(".", "/") + ".olean"
            for module in manifest["expected_modules"]
        )
        assert request.limits.timeout_seconds <= 60
        outputs = {name: b"authored-fake-olean:" + name.encode() for name in request.output_paths}
        if failure == "missing_nonfirst_definition":
            omitted = manifest["definition_modules"][1]["module"]
            outputs.pop(".lake/build/lib/lean/" + omitted.replace(".", "/") + ".olean")
        elif failure == "missing_nonfirst_norm":
            omitted = manifest["norm_bindings"][1]["module"]
            outputs.pop(".lake/build/lib/lean/" + omitted.replace(".", "/") + ".olean")
        elif failure == "binary_changed":
            executable.write_bytes(b"\x7fELF-changed-after-toolchain-pin")
        elif failure == "missing_binary":
            executable.unlink()
        theorem_bindings = manifest["norm_bindings"]
        if failure == "missing_axiom":
            theorem_bindings = theorem_bindings[:-1]
        stdout = "\n".join(
            "'" + row["composition_theorem"] + "' does not depend on any axioms"
            for row in theorem_bindings
        )
        captured.update(outputs)
        return native.process.ToolRunResult(
            interface_version="authored-fake-build/v1",
            runtime=native.process.ToolRuntime.NATIVE,
            command=request.argv,
            returncode=0,
            stdout=stdout,
            stderr="",
            elapsed_seconds=0.01,
            pid=123,
            output_files=outputs,
            workspace_cleaned=failure != "workspace_not_cleaned",
            # The actual runner uses this flag for forced termination. Normal
            # successful process exit must not require forced termination.
            process_tree_terminated=False,
            error="authored runner diagnostic despite exit zero"
            if failure == "error_on_success"
            else "",
        )

    monkeypatch.setattr(native.process.BoundedToolRunner, "run", fake_run)
    output = tmp_path / "build"
    receipt = shared.build_shared_definition_corpus(
        preparation,
        candidate_inputs=[case[0] for case in cases],
        expected_population=[case[1] for case in cases],
        toolchain=TOOLCHAIN,
        lake_executable=str(executable),
        output_directory=output,
    )
    assert receipt["build_passed"] is (failure is None)
    assert receipt["composition_obligations_checked"] is (failure is None)
    assert receipt["lean_compilation_verified"] is (failure is None)
    assert receipt["backend_executed"] is True
    assert receipt["binaries_unchanged"] is (failure not in {"binary_changed", "missing_binary"})
    assert receipt["workspace_cleaned"] is (failure != "workspace_not_cleaned")
    assert receipt["process_tree_terminated"] is False
    assert receipt["execution_error"] == (
        "authored runner diagnostic despite exit zero" if failure == "error_on_success" else ""
    )
    assert receipt["post_run_validation_passed"] is (failure != "postrun_revalidation_refused")
    if failure == "postrun_revalidation_refused":
        assert len(validation_calls) == 2
        assert receipt["post_run_validation_error"] == {
            "type": "CorpusContractError",
            "message": "authored post-run integrity refusal",
        }
    else:
        assert not receipt["post_run_validation_error"]
    if failure == "missing_binary":
        assert receipt["binary_recheck_error"]
    else:
        assert not receipt["binary_recheck_error"]
    assert receipt["manifest_coverage_passed"] is (
        failure not in {"missing_nonfirst_definition", "missing_nonfirst_norm"}
    )
    assert len(receipt["theorem_axiom_dependencies"]) == len(manifest["norm_bindings"]) - (
        failure == "missing_axiom"
    )
    assert receipt["preparation_cid"] == manifest["record_cid"]
    assert receipt["expected_modules"] == manifest["expected_modules"]
    assert receipt["binary_sha256"] == {str(executable): binary_sha}
    assert receipt["artifact_sha256"] == {name: sha(raw) for name, raw in captured.items()}
    assert receipt["artifact_files"] == {
        name: "compiled/" + name.removeprefix(".lake/build/lib/lean/") for name in captured
    }
    for name, raw in captured.items():
        assert (output / receipt["artifact_files"][name]).read_bytes() == raw
    assert (output / "build-receipt.json").read_bytes() == canonical_dag_json_bytes(receipt)
    assert (
        shared.load_shared_definition_corpus(
            output / "project",
            expected_manifest_sha256=sha(preparation.manifest_json.encode()),
            candidate_inputs=[case[0] for case in cases],
            expected_population=[case[1] for case in cases],
            toolchain=TOOLCHAIN,
        )
        == preparation
    )
    for flag in shared.FALSE_FLAGS:
        if flag not in {"backend_executed", "lean_compilation_verified"}:
            assert receipt[flag] is False


# Parent sharing extends this owner without fabricating legacy norm records.
# These helpers replay the genuine literal-parent endpoint, lookup, combined
# review and Lake preparation owners. Authored signatures remain unreviewed
# engineering fixtures, and this cohort never runs a compiler or model.
def parent_shared_fixture_module():
    import importlib.util

    path = Path(__file__).with_name("test_plaintext_definition_use_lake.py")
    spec = importlib.util.spec_from_file_location("parent_shared_original_lake_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parent_shared_family_examples(path, family, *, donor_body_op=None):
    from types import SimpleNamespace

    from ipfs_datasets_py.logic.autoformal import corpus_definition_use_review_v2 as review
    from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parents

    lake = parent_shared_fixture_module()
    support = lake.support.__wrapped__()
    source_fixture, endpoints_fixture = support.source, support.data
    definition = endpoints_fixture.definition
    original_case = endpoints_fixture.supplied.definition.case

    def three_region_case(parent, *, family="fol", parent_index=0):
        request, inputs = original_case(parent, family=family, parent_index=parent_index)
        if donor_body_op is not None and parent_index == 0:
            # An explicitly different unreviewed interpretation of the same
            # physical text; regenerate every downstream record normally.
            assert donor_body_op in ("all", "any")
            assert request["declaration"]["body"]["op"] == "all"
            request["declaration"]["body"]["op"] = donor_body_op
        if parent_index == 2:
            # Keep region2's genuine source/scope/binding; copy only the same
            # explicit unreviewed declaration shape used by consumer region1.
            template, _ = original_case(parent, family=family, parent_index=1)
            for key in ("head", "body"):
                request["declaration"][key] = deepcopy(template["declaration"][key])
            request["declaration"]["declaration_id"] = "authored-consumer-filer-two"
        return request, inputs

    endpoints_fixture.supplied.definition.case = three_region_case
    helpers = definition.helper("test_plaintext_graph_custody")
    original = helpers.helper("test_corpus_parent_occurrence_adapter").case(
        path, source_text="registered", parent_texts=[definition.TEXT] * 3)
    bundle = parents.build_parent_occurrence_corpus(**original["arguments"])
    parent = {"data": original, "bundle": bundle,
              "records": {row["record_cid"]: row for row in bundle["records"]},
              "helpers": helpers}
    endpoints = [source_fixture.endpoint(endpoints_fixture, parent, family=family, index=index)
                 for index in range(3)]
    cases = []
    for index in (1, 2):
        donor, consumer = deepcopy(endpoints[0]), deepcopy(endpoints[index])
        body = [row for row in consumer["candidate"]["source_bindings"]
                if row["role"].startswith("definition_body/")]
        request = {"schema": source_fixture.owner.PARENT_REQUEST_SCHEMA,
                   "profile": source_fixture.owner.PARENT_PROFILE,
                   "interpretation_status": "unreviewed_caller_declaration",
                   "use_id": "authored-parent-shared-use-" + str(index),
                   "consumer_symbol": body[0]["symbol"],
                   "donor_symbol": donor["candidate"]["term_record"]["symbol"],
                   "body_roles": [row["role"] for row in body],
                   "donor_partition_id": "donor", "local_partition_id": "local"}
        case = {"donor": donor, "consumer": consumer, "request": request}
        case["lookup_inputs"] = source_fixture.lookup_inputs(case)
        request_raw, kwargs = source_fixture.arguments(case)
        record = source_fixture.owner.prepare_parent_definition_use_v1(request_raw, **kwargs)
        raw = canonical_dag_json_bytes(record)
        component = {"case": case, "record": record, "component_raw": raw,
                     "expected_component_pin": {
                         "component_sha256": sha(raw), "component_cid": record["record_cid"],
                         "graph_cid": record["graph"]["record_cid"],
                         "joint_ast_sha256": sha(canonical_dag_json_bytes(record["joint_native"]["native_ast"]))},
                     "use_inputs": {"request_raw": request_raw, **kwargs}}
        materialized = lake._PARENT.materialize(component)
        domain = SimpleNamespace(CLAIM_SCHEMA=review.PARENT_CLAIM_SCHEMA,
                                 ACTION=review.PARENT_ACTION, AUDIENCE=review.PARENT_AUDIENCE)
        signed = support.signing.signed.__wrapped__(domain, materialized)
        signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
        support.signing.refresh(signed)
        cases.append(lake.refresh_assessment(support, signed))
    return {"family": family, "lake": lake, "support": support, "cases": cases}


def parent_shared_arguments(cases):
    return {"component_inputs": [
                {key: case[key] for key in ("assessment_raw", "expected_assessment_file_sha256", "review_inputs")}
                for case in cases],
            "expected_population": [
                {"component_cid": case["signed"]["component"]["record"]["record_cid"],
                 "assessment_file_sha256": case["expected_assessment_file_sha256"]}
                for case in cases],
            "toolchain": TOOLCHAIN}


def parent_shared_definition(manifest, ordinal, role):
    rows = [row for row in manifest["definition_modules"]
            if any(item["ordinal"] == ordinal and item["role"] == role
                   for item in row["contributors"])]
    assert len(rows) == 1
    return rows[0]


@pytest.fixture(scope="module")
def parent_shared_examples(tmp_path_factory):
    result = {}
    for family in ("fol", "tdfol"):
        example = parent_shared_family_examples(
            tmp_path_factory.mktemp("parent-shared-" + family, numbered=False), family)
        example["arguments"] = parent_shared_arguments(example["cases"])
        example["preparation"] = shared.prepare_parent_shared_definition_use_corpus_v1(**example["arguments"])
        result[family] = example
    return result


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_shared_two_distinct_physical_consumers_share_one_complete_donor(
        parent_shared_examples, family, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as parent_owner

    example = parent_shared_examples[family]
    cases, preparation = example["cases"], example["preparation"]
    manifest, files = preparation.to_dict(), dict(preparation.files)
    endpoints = [case["signed"]["component"]["case"] for case in cases]
    assert endpoints[0]["donor"]["candidate"] == endpoints[1]["donor"]["candidate"]
    first, second = [item["consumer"]["candidate"] for item in endpoints]
    assert first["source_version"]["record_cid"] != second["source_version"]["record_cid"]
    assert first["definition_record"]["record_cid"] != second["definition_record"]["record_cid"]
    assert {row["record_cid"] for row in first["source_occurrences"]}.isdisjoint(
        {row["record_cid"] for row in second["source_occurrences"]})
    assert type(preparation) is shared.ParentSharedCorpusPreparation
    assert manifest["schema"] != shared.SCHEMA and manifest["profile"] != shared.PROFILE
    assert len(manifest["components"]) == 2 and len(manifest["definition_modules"]) == 3
    donor = parent_shared_definition(manifest, 0, "donor")
    assert donor == parent_shared_definition(manifest, 1, "donor")
    assert donor["contributors"] == [
        {"ordinal": ordinal, "role": "donor", "component_cid": row["component_cid"]}
        for ordinal, row in enumerate(manifest["components"])]
    assert parent_shared_definition(manifest, 0, "consumer")["module"] != (
        parent_shared_definition(manifest, 1, "consumer")["module"])
    joints = [row["joint_module"] for row in manifest["components"]]
    assert len(set(joints)) == 2
    assert manifest["module_imports"]["LegalCorpusParent"] == sorted(joints)
    assert len(manifest["expected_modules"]) == len(set(manifest["expected_modules"])) == 9
    assert manifest["expected_modules"][0] == "LegalCorpusParent.Prelude"
    assert manifest["expected_modules"][-1] == "LegalCorpusParent"
    seen = set()
    for module in manifest["expected_modules"]:
        body = files[module.replace(".", "/") + ".lean"]
        imports = re.findall(r"^import ([A-Za-z0-9_.]+)$", body, re.M)
        assert imports == manifest["module_imports"][module] and set(imports) <= seen
        seen.add(module)
    for ordinal, case in enumerate(cases):
        original = parent_owner.prepare_parent_definition_use_corpus_v1(
            **example["lake"].arguments(case))
        original_manifest = original.to_dict()
        row = manifest["components"][ordinal]
        assert row["original_preparation_cid"] == original_manifest["record_cid"]
        assert files[row["manifest_file"]] == original.manifest_json
        assert row["manifest_sha256"] == sha(original.manifest_json.encode())
        assert files[row["input_bindings_file"]] == dict(original.files)["parent-input-bindings.json"]
        assert row["input_bindings_sha256"] == sha(files[row["input_bindings_file"]].encode())
        assert row["review_intake_binding"] == original_manifest["review_intake_binding"]
        assert row["conditional_theorems"] == original_manifest["conditional_theorems"]
        assert set(row["original_file_mapping"]) == {name for name, _ in original.files}
        assert {name for name, mapped in row["original_file_mapping"].items() if mapped is None} == {
            "lakefile.toml", "LegalCorpusParent.lean"}
        for original_path, aggregate_path in row["original_file_mapping"].items():
            if aggregate_path is not None:
                assert files[aggregate_path] == dict(original.files)[original_path]
        for role in ("donor", "consumer"):
            definition = parent_shared_definition(manifest, ordinal, role)
            fragment = next(item for item in original_manifest["native_fragments"] if item["role"] == role)
            assert definition["native_fragment"] == fragment["native"]
            assert definition["module"] == fragment["module"]
            assert definition["module_sha256"] == sha(files[definition["module_path"]].encode())
    assert manifest["file_sha256"] == {name: sha(body.encode()) for name, body in files.items()}
    assert manifest["preparation_only"] is True
    assert all(manifest[key] is False for key in parent_owner.PARENT_FALSE_FLAGS)

    def forbidden(*args, **kwargs):
        raise AssertionError("parent sharing preparation must not run a compiler")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(native.shared, "_installed_toolchain", forbidden)
    assert shared.validate_parent_shared_definition_use_corpus_v1(
        preparation, **example["arguments"]) == preparation


@pytest.mark.parametrize("damage", ["missing", "order", "assessment_pin"])
def test_parent_shared_independent_component_population_is_complete_and_ordered(
        parent_shared_examples, damage):
    example = parent_shared_examples["fol"]
    arguments = deepcopy(example["arguments"])
    if damage == "missing":
        arguments["expected_population"].pop()
    elif damage == "order":
        arguments["expected_population"].reverse()
    else:
        arguments["expected_population"][1]["assessment_file_sha256"] = "0" * 64
    with pytest.raises(contracts.CorpusContractError):
        shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)


@pytest.mark.parametrize("damage", ["donor_contributor", "component_lineage"])
def test_parent_shared_resealed_manifest_cannot_drop_a_use_or_rebind_lineage(
        parent_shared_examples, damage):
    example = parent_shared_examples["fol"]
    preparation = example["preparation"]
    manifest = preparation.to_dict()
    if damage == "donor_contributor":
        parent_shared_definition(manifest, 0, "donor")["contributors"].pop()
    else:
        manifest["components"][1]["original_preparation_cid"] = manifest["components"][0]["original_preparation_cid"]
    changed = replace(preparation, manifest_json=canonical_dag_json_bytes(reseal(manifest)).decode())
    with pytest.raises(contracts.CorpusContractError):
        shared.validate_parent_shared_definition_use_corpus_v1(changed, **example["arguments"])


def test_parent_shared_rehashed_files_cannot_remove_second_joint_import(parent_shared_examples):
    example = parent_shared_examples["fol"]
    preparation = example["preparation"]
    manifest, files = preparation.to_dict(), dict(preparation.files)
    second = manifest["components"][1]["joint_module"]
    files["LegalCorpusParent.lean"] = files["LegalCorpusParent.lean"].replace("import " + second + "\n", "")
    manifest["module_imports"]["LegalCorpusParent"].remove(second)
    manifest["file_sha256"] = {name: sha(body.encode()) for name, body in files.items()}
    changed = replace(preparation, files=tuple(sorted(files.items())),
                      manifest_json=canonical_dag_json_bytes(reseal(manifest)).decode())
    with pytest.raises(contracts.CorpusContractError):
        shared.validate_parent_shared_definition_use_corpus_v1(changed, **example["arguments"])


def test_parent_shared_aggregate_budget_refuses_before_any_child_replay(parent_shared_examples, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as parent_owner

    arguments = deepcopy(parent_shared_examples["fol"]["arguments"])
    # Each entry remains below the child whole-input limit; together their
    # ordinary byte payloads exceed that limit. Their semantic shape is not
    # offered as valid review data: aggregate accounting must precede replay.
    payload = b"x" * (parent_owner.MAX_INPUT_BYTES // 2 + 1)
    for item in arguments["component_inputs"]:
        item["review_inputs"]["aggregate_budget_probe"] = payload
    entered = []

    def forbidden(*args, **kwargs):
        entered.append(True)
        raise AssertionError("aggregate over-budget input reached a child")

    monkeypatch.setattr(parent_owner, "prepare_parent_definition_use_corpus_v1", forbidden)
    with pytest.raises(contracts.CorpusContractError):
        shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)
    assert entered == []


def test_parent_shared_caller_mutation_during_genuine_child_replay_is_not_returned(
        parent_shared_examples, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as parent_owner

    arguments = deepcopy(parent_shared_examples["fol"]["arguments"])
    original = parent_owner.prepare_parent_definition_use_corpus_v1
    entered = []

    def mutate_after_genuine_replay(*args, **kwargs):
        prepared = original(*args, **kwargs)
        if not entered:
            arguments["component_inputs"][1]["review_inputs"]["use_inputs"][
                "consumer_evidence_inputs"]["context_inputs"][0]["dependency_requests"] = [
                    {"authored_aggregate_mutation": True}]
        entered.append(True)
        return prepared

    monkeypatch.setattr(parent_owner, "prepare_parent_definition_use_corpus_v1", mutate_after_genuine_replay)
    with pytest.raises(contracts.CorpusContractError):
        shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)
    assert entered


def test_parent_shared_fresh_blocked_review_keeps_its_outcome_and_no_authority(parent_shared_examples):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as parent_owner

    example = parent_shared_examples["fol"]
    cases = deepcopy(example["cases"])
    signed = cases[1]["signed"]
    signed["registry"]["mode"] = signed["policy"]["mode"] = "synthetic_fixture"
    example["support"].signing.refresh(signed)
    cases[1] = example["lake"].refresh_assessment(example["support"], signed)
    prepared = shared.prepare_parent_shared_definition_use_corpus_v1(**parent_shared_arguments(cases))
    manifest = prepared.to_dict()
    evidence = manifest["components"][1]["review_evidence"]
    assert evidence == {
        "status": cases[1]["assessment"]["evidence_assessment_status"],
        "blockers": cases[1]["assessment"]["blockers"],
        "prerequisites_satisfied_under_selected_trust": False}
    assert all(manifest[key] is False for key in parent_owner.PARENT_FALSE_FLAGS)
    assert len(manifest["components"]) == 2 and manifest["preparation_only"] is True


def test_parent_shared_offered_mutation_during_genuine_regeneration_is_not_returned(
        parent_shared_examples, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as parent_owner

    example = parent_shared_examples["fol"]
    offered = replace(example["preparation"])
    original = parent_owner.prepare_parent_definition_use_corpus_v1
    entered = []

    def mutate_after_genuine_regeneration(*args, **kwargs):
        child = original(*args, **kwargs)
        if not entered:
            object.__setattr__(offered, "manifest_json", offered.manifest_json + " ")
        entered.append(True)
        return child

    monkeypatch.setattr(parent_owner, "prepare_parent_definition_use_corpus_v1", mutate_after_genuine_regeneration)
    with pytest.raises(contracts.CorpusContractError):
        shared.validate_parent_shared_definition_use_corpus_v1(offered, **example["arguments"])
    assert entered


def test_parent_shared_saved_assessment_cannot_hide_a_fresh_key_revocation(parent_shared_examples):
    example = parent_shared_examples["fol"]
    cases = deepcopy(example["cases"])
    signed = cases[1]["signed"]
    signed["registry"]["keys"][0]["revoked_at_utc"] = example["support"].signing.NOW
    example["support"].signing.refresh(signed)
    cases[1]["review_inputs"] = example["lake"].review_arguments(example["support"], signed)
    # Keep the original assessment bytes: current revocation must reopen this
    # contributor, even though its graph and independently pinned donor match.
    with pytest.raises(contracts.CorpusContractError):
        shared.prepare_parent_shared_definition_use_corpus_v1(**parent_shared_arguments(cases))


def test_parent_shared_writer_loader_keep_every_child_manifest_and_binding(
        parent_shared_examples, tmp_path):
    example = parent_shared_examples["fol"]
    preparation = example["preparation"]
    directory = tmp_path / "parent-shared-project"
    assert shared.write_parent_shared_definition_use_corpus_v1(
        preparation, directory, **example["arguments"]) == preparation.to_dict()
    assert shared.load_parent_shared_definition_use_corpus_v1(
        directory, expected_manifest_sha256=sha(preparation.manifest_json.encode()),
        **example["arguments"]) == preparation
    assert {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()} == {
                **{name: body.encode() for name, body in preparation.files},
                "corpus-manifest.json": preparation.manifest_json.encode()}
    with pytest.raises((contracts.CorpusContractError, FileExistsError)):
        shared.write_parent_shared_definition_use_corpus_v1(
            preparation, directory, **example["arguments"])


@pytest.mark.parametrize("damage", ["missing_binding", "changed_manifest", "extra_file"])
def test_parent_shared_loader_refuses_incomplete_changed_or_extra_transport(
        parent_shared_examples, tmp_path, damage):
    example = parent_shared_examples["fol"]
    preparation = example["preparation"]
    directory = tmp_path / "parent-shared-project"
    shared.write_parent_shared_definition_use_corpus_v1(preparation, directory, **example["arguments"])
    row = preparation.to_dict()["components"][1]
    if damage == "missing_binding":
        (directory / row["input_bindings_file"]).unlink()
    elif damage == "changed_manifest":
        (directory / row["manifest_file"]).write_text("{}", encoding="utf-8")
    else:
        (directory / "unlisted.lean").write_text("def unrelated : Prop := True\n", encoding="utf-8")
    with pytest.raises(contracts.CorpusContractError):
        shared.load_parent_shared_definition_use_corpus_v1(
            directory, expected_manifest_sha256=sha(preparation.manifest_json.encode()),
            **example["arguments"])


def test_parent_shared_and_legacy_preparation_types_cannot_be_relabelled(parent_shared_examples, small_shared):
    example = parent_shared_examples["fol"]
    cases, legacy = small_shared
    with pytest.raises(contracts.CorpusContractError):
        shared.validate_parent_shared_definition_use_corpus_v1(legacy, **example["arguments"])
    with pytest.raises(contracts.CorpusContractError):
        validate(example["preparation"], cases)


@pytest.mark.parametrize("bad_pin", [None, []], ids=["null", "list"])
def test_parent_shared_malformed_component_pins_refuse_before_native_dispatch(
        parent_shared_examples, monkeypatch, bad_pin):
    arguments = deepcopy(parent_shared_examples["fol"]["arguments"])
    arguments["component_inputs"][0]["review_inputs"]["expected_component_pin"] = bad_pin

    def forbidden():
        raise AssertionError("malformed parent shared population reached native owners")

    monkeypatch.setattr(shared, "_parent_shared_pins", forbidden)
    with pytest.raises(contracts.CorpusContractError):
        shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)


def test_parent_shared_repeated_component_keeps_both_contributions_without_extra_modules(
        parent_shared_examples):
    example = parent_shared_examples["fol"]
    arguments = parent_shared_arguments([example["cases"][0], example["cases"][0]])
    manifest = shared.prepare_parent_shared_definition_use_corpus_v1(**arguments).to_dict()
    assert len(manifest["components"]) == 2 and len(manifest["expected_modules"]) == 6
    assert manifest["components"][0]["component_cid"] == manifest["components"][1]["component_cid"]
    assert manifest["components"][0]["manifest_file"] != manifest["components"][1]["manifest_file"]
    assert [row["ordinal"] for row in parent_shared_definition(manifest, 0, "donor")["contributors"]] == [0, 1]


@pytest.mark.parametrize("operation", ["prepare", "validate"])
def test_parent_shared_closing_replay_refuses_physical_source_changed_after_opening_children(
        tmp_path, monkeypatch, operation):
    """Later child completion cannot leave an earlier physical source stale."""
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as parent_owner
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as parent_native
    from ipfs_datasets_py.logic.backends import process

    def forbidden(*args, **kwargs):
        pytest.fail("physical-source preparation control cannot execute or probe a toolchain")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(native.shared, "_installed_toolchain", forbidden)
    monkeypatch.setattr(parent_native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    originals = tmp_path / "originals"
    originals.mkdir()
    example = parent_shared_family_examples(originals, "fol")
    arguments = parent_shared_arguments(example["cases"])
    before = deepcopy(arguments)
    # Validation's offered project is fully and genuinely prepared before the
    # mutation observer is installed. The prepare branch needs no offered data.
    offered = (shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)
               if operation == "validate" else None)
    descriptor = arguments["component_inputs"][0]["review_inputs"]["use_inputs"][
        "donor_evidence_inputs"]["parent_inputs"]["replay_inputs"][
        "parent_text_views_inputs"]["parent_descriptor"]
    physical = Path(descriptor["local_path"])
    assert physical.is_relative_to(originals) and not physical.is_symlink()
    original_bytes = physical.read_bytes()
    assert original_bytes and sha(original_bytes) == descriptor["sha256"]
    original_prepare = parent_owner.prepare_parent_definition_use_corpus_v1
    attempts, successes = [], []
    mutated = []

    def prepare_then_change_earlier_source(*args, **kwargs):
        raw = kwargs["assessment_raw"]
        attempts.append(raw)
        result = original_prepare(*args, **kwargs)
        successes.append(raw)
        if len(successes) == 2:
            # Both genuine opening children have now completed. Change only
            # the earlier child's physical file; every saved pin stays intact.
            physical.write_bytes(original_bytes + b"\nchanged isolated physical-close fixture")
            mutated.append(True)
        return result

    monkeypatch.setattr(parent_owner, "prepare_parent_definition_use_corpus_v1",
                        prepare_then_change_earlier_source)
    try:
        with pytest.raises(ValueError):
            if operation == "prepare":
                shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)
            else:
                shared.validate_parent_shared_definition_use_corpus_v1(offered, **arguments)
        first, second = [item["assessment_raw"] for item in arguments["component_inputs"]]
        assert first != second
        assert mutated == [True]
        assert successes == [first, second]
        assert attempts == [first, second, first]
        assert physical.read_bytes() != original_bytes
        assert arguments == before
    finally:
        physical.write_bytes(original_bytes)
    assert physical.read_bytes() == original_bytes


@pytest.fixture(scope="module")
def parent_shared_replay_transport_data(tmp_path_factory):
    # Exactly one genuine signed FOL component, one original shared preparation
    # and one export. Its fictional sources and generated test signers establish
    # public replay custody, without human/statutory review or a native build.
    lake = parent_shared_fixture_module()
    with pytest.MonkeyPatch.context() as patch:
        lake.parent_replay_transport_guards(patch)
        support = lake.support.__wrapped__()

        def forbidden(*args, **kwargs):
            pytest.fail("public replay transport must not probe or execute Lean")

        patch.setattr(native.shared, "_installed_toolchain", forbidden)
        directory = tmp_path_factory.mktemp("parent-shared-replay-originals", numbered=False)
        data = lake.make_data(support, directory, family="fol")
        arguments = parent_shared_arguments([data])
        preparation = shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)
        manifest = preparation.to_dict()
        assert len(manifest["expected_modules"]) == 6
        manifest_pin = sha(preparation.manifest_json.encode("utf-8"))
        payload = shared.export_parent_shared_replay_inputs_v1(
            preparation, **arguments, expected_manifest_sha256=manifest_pin)
        pins = dict(expected_payload_sha256=sha(payload), expected_payload_bytes=len(payload),
                    expected_input_commitment_sha256=manifest["input_commitment_sha256"],
                    expected_manifest_sha256=manifest_pin)
        control = dict(lake=lake, support=support, data=data, arguments=arguments,
                       preparation=preparation, payload=payload, pins=pins, directory=directory)
    return control


@pytest.fixture
def parent_shared_replay_transport(parent_shared_replay_transport_data, monkeypatch):
    control = parent_shared_replay_transport_data
    control["lake"].parent_replay_transport_guards(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("public replay transport must not probe or execute Lean")

    monkeypatch.setattr(native.shared, "_installed_toolchain", forbidden)
    return control


def load_parent_shared_replay_fixture(control, **overrides):
    pins = dict(control["pins"], **overrides)
    return shared.load_parent_shared_replay_inputs_v1(control["payload"], **pins)


def test_parent_shared_replay_preserves_original_public_bytes_and_no_private_keys(
        parent_shared_replay_transport, monkeypatch):
    control = parent_shared_replay_transport

    def forbidden(*args, **kwargs):
        pytest.fail("loading pinned historical bytes cannot replay sources/reviews or load native owners")

    monkeypatch.setattr(shared.parent_owner, "_owners", forbidden)
    monkeypatch.setattr(shared.parent_owner, "prepare_parent_definition_use_corpus_v1", forbidden)
    monkeypatch.setattr(control["lake"].review, "validate_parent_definition_use_review_assessment_v1", forbidden)
    from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages
    monkeypatch.setattr(legal_parent_parquet_pages, "read_selected_parent_rows", forbidden)
    loaded = load_parent_shared_replay_fixture(control)
    assert type(loaded) is dict
    assert set(loaded) == {"component_inputs", "expected_population", "toolchain"}
    assert loaded == control["arguments"]
    component, original = loaded["component_inputs"][0], control["arguments"]["component_inputs"][0]
    assert type(component["assessment_raw"]) is bytes
    assert component["assessment_raw"] == control["data"]["assessment_raw"]
    assert component["review_inputs"]["reviews"] == original["review_inputs"]["reviews"]
    assert component["review_inputs"]["registry"] == original["review_inputs"]["registry"]
    assert component["review_inputs"]["policy"] == original["review_inputs"]["policy"]
    assert component["review_inputs"]["at_time_utc"] == original["review_inputs"]["at_time_utc"]
    serialization = control["support"].signing.serialization
    for signer in control["data"]["signed"]["signers"]:
        private = signer.private_key.private_bytes(serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw, serialization.NoEncryption())
        assert private not in control["payload"] and private.hex().encode() not in control["payload"]
    pending = [loaded]
    while pending:
        value = pending.pop()
        assert type(value) in {dict, list, bytes, str, int, float, bool, type(None)}
        if type(value) is dict:
            assert not {"signers", "private_key", "private_keys"}.intersection(value)
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
    manifest = control["preparation"].to_dict()
    assert all(manifest[key] is False for key in shared.PARENT_FALSE_FLAGS)


def test_parent_shared_replay_loaded_arguments_regenerate_exact_original_project(parent_shared_replay_transport):
    control = parent_shared_replay_transport
    loaded = load_parent_shared_replay_fixture(control)
    prepared = shared.prepare_parent_shared_definition_use_corpus_v1(**loaded)
    checked = shared.validate_parent_shared_definition_use_corpus_v1(control["preparation"], **loaded)
    for result in (prepared, checked):
        assert result.manifest_json == control["preparation"].manifest_json
        assert result.files == control["preparation"].files
    assert loaded == control["arguments"]


def test_parent_shared_replay_loaded_mutation_cannot_change_retained_arguments(parent_shared_replay_transport):
    control = parent_shared_replay_transport
    loaded = load_parent_shared_replay_fixture(control)
    loaded["component_inputs"][0]["review_inputs"]["at_time_utc"] = "2099-01-01T00:00:00Z"
    loaded["expected_population"].clear()
    assert load_parent_shared_replay_fixture(control) == control["arguments"]


@pytest.mark.parametrize("binding", ["payload-sha", "payload-length", "input-commitment", "manifest"])
def test_parent_shared_replay_requires_each_independent_binding(parent_shared_replay_transport, binding):
    control = parent_shared_replay_transport
    key = {"payload-sha": "expected_payload_sha256", "payload-length": "expected_payload_bytes",
           "input-commitment": "expected_input_commitment_sha256", "manifest": "expected_manifest_sha256"}[binding]
    replacement = len(control["payload"]) + 1 if binding == "payload-length" else "0" * 64
    with pytest.raises(contracts.CorpusContractError):
        load_parent_shared_replay_fixture(control, **{key: replacement})


@pytest.mark.parametrize("damage", ["envelope-extra", "schema", "inputs-extra", "component-extra", "population-extra"])
def test_parent_shared_replay_resealed_closed_shape_substitutions_refuse(parent_shared_replay_transport, damage):
    control = parent_shared_replay_transport
    envelope = shared.parent_owner.decode_parent_replay_value_v1(
        control["payload"], expected_payload_sha256=control["pins"]["expected_payload_sha256"])
    if damage == "envelope-extra":
        envelope["proof_authority"] = True
    elif damage == "schema":
        envelope["schema"] = "unsupported-parent-replay/v0"
    elif damage == "inputs-extra":
        envelope["inputs"]["admitted"] = True
    elif damage == "component-extra":
        envelope["inputs"]["component_inputs"][0]["toolchain"] = TOOLCHAIN
    else:
        envelope["inputs"]["expected_population"][0]["proof_authority"] = True
    substituted = shared.parent_owner.encode_parent_replay_value_v1(envelope)
    pins = dict(control["pins"], expected_payload_sha256=sha(substituted), expected_payload_bytes=len(substituted))
    with pytest.raises(contracts.CorpusContractError):
        shared.load_parent_shared_replay_inputs_v1(substituted, **pins)


def test_parent_shared_replay_recomputes_commitment_after_valid_payload_reseal(parent_shared_replay_transport):
    control = parent_shared_replay_transport
    envelope = shared.parent_owner.decode_parent_replay_value_v1(
        control["payload"], expected_payload_sha256=control["pins"]["expected_payload_sha256"])
    envelope["inputs"]["toolchain"] = "leanprover/lean4:v4.34.2"
    substituted = shared.parent_owner.encode_parent_replay_value_v1(envelope)
    pins = dict(control["pins"], expected_payload_sha256=sha(substituted), expected_payload_bytes=len(substituted))
    with pytest.raises(contracts.CorpusContractError, match="commitment"):
        shared.load_parent_shared_replay_inputs_v1(substituted, **pins)


def test_parent_shared_replay_historical_load_does_not_authorize_changed_physical_source(parent_shared_replay_transport):
    control = parent_shared_replay_transport
    loaded = load_parent_shared_replay_fixture(control)
    descriptor = loaded["component_inputs"][0]["review_inputs"]["use_inputs"][
        "donor_evidence_inputs"]["parent_inputs"]["replay_inputs"][
        "parent_text_views_inputs"]["parent_descriptor"]
    physical = Path(descriptor["local_path"])
    assert physical.is_relative_to(control["directory"]) and not physical.is_symlink()
    original = physical.read_bytes()
    assert sha(original) == descriptor["sha256"]
    try:
        physical.write_bytes(original + b"\nchanged isolated replay-transport fixture")
        # Loading data is not a current-source validation capability.
        assert load_parent_shared_replay_fixture(control) == control["arguments"]
        with pytest.raises(ValueError):
            shared.prepare_parent_shared_definition_use_corpus_v1(**loaded)
    finally:
        physical.write_bytes(original)
    assert physical.read_bytes() == original


def test_parent_shared_replay_saved_trust_cannot_hide_resigned_current_revocation(parent_shared_replay_transport):
    control = parent_shared_replay_transport
    loaded = load_parent_shared_replay_fixture(control)
    signed = deepcopy(control["data"]["signed"])
    original_reviews = deepcopy(signed["reviews"])
    signed["registry"]["keys"][0]["revoked_at_utc"] = control["support"].signing.NOW
    control["support"].signing.refresh(signed)
    assert all(before["signature"] != after["signature"]
               for before, after in zip(original_reviews, signed["reviews"], strict=True))
    loaded["component_inputs"][0]["review_inputs"] = control["lake"].review_arguments(control["support"], signed)
    assert loaded["component_inputs"][0]["assessment_raw"] == control["data"]["assessment_raw"]
    with pytest.raises(ValueError, match="combined-use review assessment differs from exact regeneration"):
        shared.prepare_parent_shared_definition_use_corpus_v1(**loaded)
    current = control["lake"].refresh_assessment(control["support"], signed)
    assert current["assessment"]["evidence_assessment_status"] == "rejected"
    assert all(row["signature_status"] == "valid" for row in current["assessment"]["reviews"])
    assert any("key_revoked" in row["blockers"] for row in current["assessment"]["reviews"])
    # Original saved trust is retained historical data, not an ambient grant of
    # present review validity. Rechecking different current inputs is mandatory.
    assert load_parent_shared_replay_fixture(control) == control["arguments"]


def test_parent_shared_replay_export_requires_exact_manifest_pin_before_child_dispatch(
        parent_shared_replay_transport, monkeypatch):
    control = parent_shared_replay_transport

    def forbidden(*args, **kwargs):
        pytest.fail("mismatched independent project pin must refuse before child replay")

    monkeypatch.setattr(shared.parent_owner, "prepare_parent_definition_use_corpus_v1", forbidden)
    with pytest.raises(contracts.CorpusContractError, match="manifest"):
        shared.export_parent_shared_replay_inputs_v1(control["preparation"],
            **control["arguments"], expected_manifest_sha256="0" * 64)


def test_parent_shared_replay_length_requires_exact_positive_integer(parent_shared_replay_transport):
    with pytest.raises(contracts.CorpusContractError):
        load_parent_shared_replay_fixture(parent_shared_replay_transport, expected_payload_bytes=True)
