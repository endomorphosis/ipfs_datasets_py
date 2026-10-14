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
