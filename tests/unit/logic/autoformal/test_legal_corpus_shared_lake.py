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


# The complete public reviewed fixture remains owned by the admission tests.
# These tests compose its APIs; no fixture or preservation implementation is
# copied into the shared owner.
def reviewed_preservation_fixture_helper_v2():
    import importlib.util
    path = Path(__file__).with_name("test_legal_norm_content_adjudication_v1.py")
    spec = importlib.util.spec_from_file_location("_shared_reviewed_admission_fixture_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reviewed_preservation_reauthorize_fixture_v2(helper, admission_owner, case):
    """Fresh fictional signatures for deliberate source/IR fixture changes."""
    helper.reviewed_refresh_manifest_v2(case)
    case["preparation"] = admission_owner.prepare_reviewed_norm_admission_v2(case["declaration"],
        **helper.reviewed_prepare_arguments_v2(case))
    subject = case["preparation"]["subject"]
    body_raw = admission_owner.norm._wire(case["declaration"])
    case["evidence"][case["declaration"]["component_id"]] = body_raw
    for claim in case["reviews"]:
        claim["subject"] = deepcopy(subject)
        claim["interpretation"]["reviewed_graph_sha256"] = subject["graph_sha256"]
        claim["interpretation"]["reviewed_ast_sha256"] = subject["ast_sha256"]
        for obligation in claim["context_closure"]["obligations"]:
            for ref in obligation["evidence_refs"]:
                if ref["artifact_id"] == case["declaration"]["component_id"]:
                    ref["sha256"] = sha(body_raw)
    helper.reviewed_resign_v2(case)


def reviewed_preservation_refresh_expression_v2(request):
    """Reconstruct an intentionally edited fixture with its canonical digest."""
    from ipfs_datasets_py.logic.syntax_core import ast
    edited = dict(request["expression"], content_digest="")
    request["expression"] = ast.TypedExpression.from_dict(edited).to_dict()


def reviewed_preservation_graph_fixture_v2(helper, admission_owner, case):
    from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graph_owner
    args, kwargs = helper.reviewed_assessment_arguments_v2(admission_owner, case)
    admission = admission_owner.assess_reviewed_norm_admission_v2(*args, **kwargs)
    assert admission["semantic_use_eligible"] is True
    admission_sha = admission_owner.norm_content_adjudication_sha256(admission)
    graph = graph_owner.build_reviewed_norm_graph_v2(admission, *args,
        expected_admission_sha256=admission_sha, **kwargs)
    return dict(helper=helper, owner=admission_owner, case=case, args=args, kwargs=kwargs,
        admission=admission, graph=graph, admission_sha=admission_sha,
        graph_sha=graph_owner.norm_definition_graph_sha256(graph))


def reviewed_preservation_prepare_fixture_v2(control, *, graph=None, admission=None, args=None, kwargs=None):
    return shared.prepare_reviewed_norm_preservation_corpus_v2(
        control["graph"] if graph is None else graph, control["admission"] if admission is None else admission,
        *(control["args"] if args is None else args), expected_graph_sha256=control["graph_sha"],
        expected_admission_sha256=control["admission_sha"], toolchain=TOOLCHAIN,
        **(control["kwargs"] if kwargs is None else kwargs))


def reviewed_preservation_validate_fixture_v2(control, offered=None, *, args=None, kwargs=None, toolchain=TOOLCHAIN):
    offered = control["preparation"] if offered is None else offered
    return shared.validate_reviewed_norm_preservation_corpus_v2(offered, control["graph"], control["admission"],
        *(control["args"] if args is None else args),
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(offered),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=toolchain, **(control["kwargs"] if kwargs is None else kwargs))


@pytest.fixture
def reviewed_preservation_control_v2():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission_owner
    helper = reviewed_preservation_fixture_helper_v2()
    case = helper.reviewed_norm_fixture_v2(admission_owner)
    control = reviewed_preservation_graph_fixture_v2(helper, admission_owner, case)
    control["preparation"] = reviewed_preservation_prepare_fixture_v2(control)
    return control


def reviewed_preservation_reseal_fixture_v2(preparation, manifest, files):
    manifest["file_sha256"] = {name: sha(body.encode("utf-8")) for name, body in sorted(files.items())}
    sealed = contracts.seal_record({key: value for key, value in manifest.items()
                                    if key not in ("record_cid", "cid_scope")})
    return replace(preparation, manifest_json=canonical_dag_json_bytes(sealed).decode(),
        files=tuple(sorted(files.items())))


def test_reviewed_preservation_v2_retains_all_unchanged_child_files_and_five_obligations(reviewed_preservation_control_v2):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    control = reviewed_preservation_control_v2
    prepared = control["preparation"]
    before = control["owner"].norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1]
    assert reviewed_preservation_validate_fixture_v2(control) == prepared
    manifest, files = prepared.to_dict(), dict(prepared.files)
    assert [row["unit_id"] for row in manifest["units"]] == [
        row["unit_id"] for row in control["case"]["declaration"]["units"]]
    assert len(manifest["preservation_obligations"]) == 15
    assert len(set(manifest["preservation_obligations"])) == 15
    assert len(manifest["expected_modules"]) == 6
    assert manifest["preparation_only"] and manifest["proof_status"] == "not_executed"
    assert manifest["lean_compilation_status"] == "not_executed"
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert manifest["semantic_use_eligible"] is False and not any(manifest["authority"].values())
    assert all(manifest[key] is False for key in preservation.FALSE_FLAGS)
    assert manifest["support_profile"]["cross_unit_definition_application_proved"] is False
    assert manifest["support_profile"]["one_exact_signature_header_including_signature_id"] is True
    assert {row["signature_id"] for row in manifest["units"]} == {manifest["signature_header"]["signature_id"]}
    assert manifest["support_profile"]["duplicate_instance_declarations_across_physical_units"] == "entire_preparation_refused"
    assert len({row["source_version_cid"] for row in manifest["units"]}) == 3
    for row in manifest["units"]:
        original = control["case"]["relational_inputs"][row["unit_id"]]
        child = preservation.prepare_relational_ast_preservation(original["report"], original["request_raw"],
            expected_report_sha256=original["expected_report_sha256"],
            expected_request_sha256=row["relational_request_sha256"], toolchain=TOOLCHAIN)
        assert row["child_preparation_sha256"] == preservation.preparation_sha256(child)
        assert files[row["child_manifest_path"]] == child.manifest_json
        assert len(row["original_child_files"]) == 7
        for companion in row["original_child_files"]:
            assert files[companion["companion_path"]] == dict(child.files)[companion["original_path"]]
        module_path = row["instance_module"].replace(".", "/") + ".lean"
        assert files[module_path] == dict(child.files)[module_path]
        assert row["preservation_obligations"] == child.to_dict()["theorems"]
    assert files[shared.REVIEWED_PRESERVATION_ROOT + ".lean"] == "".join(
        "import " + row["instance_module"] + "\n" for row in manifest["units"])
    import tomllib
    library, = tomllib.loads(files["lakefile.toml"])["lean_lib"]
    assert library["name"] == "legal"
    assert library["roots"] == manifest["expected_modules"]
    assert len(library["roots"]) == len(set(library["roots"])) == 6
    assert before == control["owner"].norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1]


@pytest.mark.parametrize("damage", ["missing_unit", "duplicate_unit", "reordered_units", "fifth_obligation",
    "alias_obligation", "occurrence", "source_version", "ast", "request", "scope", "roles",
    "inputs_companion", "child_lakefile", "child_root", "child_manifest", "active_instance", "aggregate_root",
    "aggregate_lakefile", "authority", "training_mask"])
def test_reviewed_preservation_v2_resealed_projection_or_project_requires_full_regeneration(
        reviewed_preservation_control_v2, damage):
    control = reviewed_preservation_control_v2
    prepared = control["preparation"]
    manifest, files = prepared.to_dict(), dict(prepared.files)
    unit = manifest["units"][1]
    if damage == "missing_unit": manifest["units"].pop()
    elif damage == "duplicate_unit": manifest["units"][2] = deepcopy(unit)
    elif damage == "reordered_units": manifest["units"].reverse()
    elif damage == "fifth_obligation": unit["preservation_obligations"].pop()
    elif damage == "alias_obligation":
        unit["preservation_obligations"][-1] = unit["instance_module"] + ".alias_iff_assuming_desired_equivalence"
    elif damage in ("occurrence", "source_version", "ast", "request", "scope"):
        field = {"occurrence": "source_occurrence_cid", "source_version": "source_version_cid",
            "ast": "complete_ir_sha256", "request": "relational_request_sha256", "scope": "scope_record_cid"}[damage]
        unit[field] = manifest["units"][0][field] if damage != "scope" else "fixture:unreviewed-scope"
    elif damage == "roles":
        manifest["predicate_compatibility_ledger"]["CoveredOfficer"]["ordered_argument_roles"] = ["different_role"]
    elif damage in ("inputs_companion", "child_lakefile", "child_root"):
        original_name = {"inputs_companion": "preservation-inputs.json", "child_lakefile": "lakefile.toml",
            "child_root": "LegalRelationalAstPreservation.lean"}[damage]
        companion = next(row for row in unit["original_child_files"] if row["original_path"] == original_name)
        files[companion["companion_path"]] += "\nchanged retained child bytes\n"
        companion["sha256"] = sha(files[companion["companion_path"]].encode())
    elif damage == "child_manifest": files[unit["child_manifest_path"]] += "\n"
    elif damage == "active_instance": files[unit["instance_module"].replace(".", "/") + ".lean"] += "\n-- changed\n"
    elif damage == "aggregate_root": files[shared.REVIEWED_PRESERVATION_ROOT + ".lean"] = "-- missing all units\n"
    elif damage == "aggregate_lakefile": files["lakefile.toml"] = files["lakefile.toml"].replace("legal", "other", 1)
    elif damage == "authority": manifest["authority"]["corpus_admission"] = True
    elif damage == "training_mask": manifest["training_mask"] = 1
    forged = reviewed_preservation_reseal_fixture_v2(prepared, manifest, files)
    with pytest.raises((ValueError, TypeError)):
        reviewed_preservation_validate_fixture_v2(control, forged)


@pytest.mark.parametrize("damage", ["source", "IR_request", "IR_report", "review", "revoked", "expired",
    "dependency", "graph", "admission", "toolchain"])
def test_reviewed_preservation_v2_replays_current_sources_reviews_dependencies_and_graph(
        reviewed_preservation_control_v2, damage):
    control = reviewed_preservation_control_v2
    args, kwargs = deepcopy(control["args"]), deepcopy(control["kwargs"])
    unit_id = control["case"]["declaration"]["units"][1]["unit_id"]
    if damage == "source": kwargs["preparation_inputs"]["source_inputs"][unit_id]["raw_bytes"] += b" changed"
    elif damage == "IR_request": kwargs["preparation_inputs"]["relational_inputs"][unit_id]["request_raw"] += b" "
    elif damage == "IR_report": kwargs["preparation_inputs"]["relational_inputs"][unit_id]["report"]["argument_roles"][0]["roles"] = ["other"]
    elif damage == "review": args[3][0]["interpretation"]["rationale"] += " unsigned"
    elif damage == "revoked":
        case = deepcopy({key: value for key, value in control["case"].items() if key != "signers"})
        case["signers"] = control["case"]["signers"]
        case["registry"]["keys"][0]["revoked_at_utc"] = kwargs["at_time_utc"]
        control["helper"].reviewed_resign_v2(case)
        args, kwargs = control["helper"].reviewed_assessment_arguments_v2(control["owner"], case)
    elif damage == "expired": kwargs["at_time_utc"] = "2026-11-02T00:00:00Z"
    elif damage == "dependency": kwargs["observed_artifact_sha256s"][unit_id + ":source"] = "f" * 64
    elif damage == "graph":
        graph = deepcopy(control["graph"])
        graph["unit_records"].reverse()
        with pytest.raises((ValueError, TypeError)):
            reviewed_preservation_prepare_fixture_v2(control, graph=graph)
        return
    elif damage == "admission":
        admission = deepcopy(control["admission"])
        admission["units"][1]["canonical_ir"]["assumptions"] = ["Assume desired equivalence."]
        with pytest.raises((ValueError, TypeError)):
            reviewed_preservation_prepare_fixture_v2(control, admission=admission)
        return
    with pytest.raises((ValueError, TypeError)):
        reviewed_preservation_validate_fixture_v2(control, args=args, kwargs=kwargs,
            toolchain="leanprover/lean4:v4.35.0" if damage == "toolchain" else TOOLCHAIN)


def test_reviewed_preservation_v2_refuses_same_ir_at_distinct_physical_uses():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission_owner
    helper = reviewed_preservation_fixture_helper_v2()
    case = helper.reviewed_norm_fixture_v2(admission_owner)
    original, repeated = case["declaration"]["units"][1:]
    assert original["occurrence"]["record_cid"] != repeated["occurrence"]["record_cid"]
    case["relational_inputs"][repeated["unit_id"]] = deepcopy(case["relational_inputs"][original["unit_id"]])
    repeated["relational_request_sha256"] = original["relational_request_sha256"]
    report = case["relational_inputs"][repeated["unit_id"]]["report"]
    text = case["source_inputs"][repeated["unit_id"]]["extracted_text"]
    repeated["coverage"] = [{"typed_path": row["typed_path"], "start_char": 0, "end_char": len(text),
        "start_utf8": 0, "end_utf8": len(text.encode())} for row in report["structural_mapping"]]
    case["declaration"]["definition_uses"][1]["target_typed_paths"] = deepcopy(
        case["declaration"]["definition_uses"][0]["target_typed_paths"])
    reviewed_preservation_reauthorize_fixture_v2(helper, admission_owner, case)
    control = reviewed_preservation_graph_fixture_v2(helper, admission_owner, case)
    with pytest.raises(ValueError, match="distinct physical units cannot share an instance"):
        reviewed_preservation_prepare_fixture_v2(control)


def test_reviewed_preservation_v2_requires_explicit_proof_obligation_permission():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission_owner
    helper = reviewed_preservation_fixture_helper_v2()
    case = helper.reviewed_norm_fixture_v2(admission_owner)
    case["declaration"]["permitted_uses"] = ["formalization"]
    reviewed_preservation_reauthorize_fixture_v2(helper, admission_owner, case)
    control = reviewed_preservation_graph_fixture_v2(helper, admission_owner, case)
    with pytest.raises(ValueError, match="explicit reviewed formalization and proof-obligation permissions"):
        reviewed_preservation_prepare_fixture_v2(control)


@pytest.mark.parametrize("damage", ["roles", "signature_id"])
def test_reviewed_preservation_v2_refuses_incompatible_shared_contract_after_valid_independent_replay(damage):
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission_owner
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    helper = reviewed_preservation_fixture_helper_v2()
    case = helper.reviewed_norm_fixture_v2(admission_owner)
    unit = case["declaration"]["units"][2]
    request = json.loads(case["relational_inputs"][unit["unit_id"]]["request_raw"])

    def rename(node):
        if type(node) is dict:
            if node.get("kind") == "predicate" and node.get("symbol") == "InspectsRegister":
                node["symbol"] = "FilesReport"
            for value in node.values(): rename(value)
        elif type(node) is list:
            for value in node: rename(value)

    if damage == "roles":
        rename(request["expression"]["root"])
        for symbol in request["expression"]["signature"]["symbols"]:
            if symbol["name"] == "InspectsRegister": symbol["name"] = "FilesReport"
        for roles in request["argument_roles"]:
            if roles["symbol"] == "InspectsRegister":
                roles.update(symbol="FilesReport", roles=["different_ordered_role"])
    else:
        # A separately named vocabulary is deliberately outside this minimal
        # common-header profile, despite otherwise compatible Object symbols.
        request["expression"]["signature"]["signature_id"] = "fixture:separate-signature"
    reviewed_preservation_refresh_expression_v2(request)
    request_raw = canonical_dag_json_bytes(request)
    report = relational.prepare_relational_norm_v1(request_raw, expected_request_sha256=sha(request_raw))
    case["relational_inputs"][unit["unit_id"]] = {"request_raw": request_raw, "report": report,
        "expected_report_sha256": relational.relational_norm_report_sha256(report)}
    unit["relational_request_sha256"] = sha(request_raw)
    reviewed_preservation_reauthorize_fixture_v2(helper, admission_owner, case)
    control = reviewed_preservation_graph_fixture_v2(helper, admission_owner, case)
    message = "shared predicate signature or ordered argument roles differ" if damage == "roles" else "shared Object signature headers differ"
    with pytest.raises(ValueError, match=message):
        reviewed_preservation_prepare_fixture_v2(control)


def test_reviewed_preservation_v2_keeps_different_definition_bodies_in_distinct_instances():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission_owner
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational, corpus_source as sources
    helper = reviewed_preservation_fixture_helper_v2()
    case = helper.reviewed_norm_fixture_v2(admission_owner)
    old = case["declaration"]["units"][0]
    new = deepcopy(old)
    identity = "fixture:act-v1/unit-4"
    text = "For this fictional Act, a covered officer means an officer appointed by the Commission."
    raw = text.encode("utf-8")
    version = sources.build_source_version(source_id=identity, release_id="fixture:act-v1",
        edition="fictional-edition-1", provision_id=identity, raw_bytes=raw,
        expected_raw_sha256=sha(raw), extracted_text=text, expected_extracted_sha256=sha(raw),
        extraction_profile="identity/v1", normalization_profile="identity/v1", media_type="text/plain")
    occurrence = sources.build_source_occurrence(version, expected_raw_sha256=sha(raw), extracted_text=text,
        expected_extracted_sha256=sha(raw), start_char=0, end_char=len(text), start_utf8=0, end_utf8=len(raw))
    # The whole original request is retained with one explicit fictional body
    # change. Nothing unifies the two different meanings of CoveredOfficer.
    request = json.loads(case["relational_inputs"][old["unit_id"]]["request_raw"].decode().replace(
        "AppointedByBoard", "AppointedByCommission"))
    reviewed_preservation_refresh_expression_v2(request)
    request = canonical_dag_json_bytes(request)
    report = relational.prepare_relational_norm_v1(request, expected_request_sha256=sha(request))
    new.update(unit_id=identity, source_version=version, occurrence=occurrence,
        source_artifact_id=identity + ":source", ir_artifact_id=identity + ":ir",
        relational_request_sha256=sha(request), coverage=[{"typed_path": row["typed_path"],
            "start_char": 0, "end_char": len(text), "start_utf8": 0, "end_utf8": len(raw)}
            for row in report["structural_mapping"]])
    case["declaration"]["units"].append(new)
    case["source_inputs"][identity] = {"raw_bytes": raw, "extracted_text": text}
    case["relational_inputs"][identity] = {"request_raw": request, "report": report,
        "expected_report_sha256": relational.relational_norm_report_sha256(report)}
    case["declaration"]["definition_uses"][1]["definition_unit_id"] = identity
    reviewed_preservation_reauthorize_fixture_v2(helper, admission_owner, case)
    control = reviewed_preservation_graph_fixture_v2(helper, admission_owner, case)
    prepared = reviewed_preservation_prepare_fixture_v2(control)
    manifest = prepared.to_dict()
    definitions = [row for row in manifest["units"] if row["kind"] == "definition"]
    assert len(definitions) == 2 and len({row["instance_module"] for row in definitions}) == 2
    assert len({row["complete_ir_sha256"] for row in definitions}) == 2
    assert len(manifest["preservation_obligations"]) == 20
    assert manifest["support_profile"]["cross_unit_definition_application_proved"] is False


@pytest.mark.parametrize("damage", ["duplicate", "parent_path", "absolute", "nested", "reordered"])
def test_reviewed_preservation_v2_requires_safe_unique_bounded_project_paths(reviewed_preservation_control_v2, damage):
    offered = reviewed_preservation_control_v2["preparation"]
    pairs = list(offered.files)
    if damage == "duplicate": pairs.append(pairs[0])
    elif damage == "reordered": pairs.reverse()
    else:
        name = {"parent_path": "../outside", "absolute": "/outside", "nested": "a/b/c"}[damage]
        pairs[0] = (name, pairs[0][1])
        pairs.sort()
    with pytest.raises(ValueError):
        shared.reviewed_preservation_corpus_sha256(replace(offered, files=tuple(pairs)))


@pytest.mark.parametrize("damage", ["common_semantics", "common_prelude", "fifth_obligation", "counted", "agent", "sort",
    "authority", "report_pin", "mask"])
def test_reviewed_preservation_v2_checks_child_composition_contract(reviewed_preservation_control_v2, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    control = reviewed_preservation_control_v2
    original = preservation.prepare_relational_ast_preservation
    calls = []

    def changed(*args, **kwargs):
        child = original(*args, **kwargs)
        # The first unit remains unmodified, so differing common bytes cannot
        # be silently deduplicated. The validator also regenerates each child.
        report_sha = kwargs["expected_report_sha256"]
        if report_sha not in calls: calls.append(report_sha)
        if calls.index(report_sha) != 1: return child
        manifest, files = child.to_dict(), dict(child.files)
        if damage in ("common_semantics", "common_prelude"):
            name = "LegalRelationalAstPreservation/" + ("Semantics" if damage == "common_semantics" else "Prelude") + ".lean"
            files[name] += "\n-- changed common bytes\n"
        elif damage == "fifth_obligation": manifest["theorems"].pop()
        elif damage == "counted": manifest["support_profile"]["counting_supported"] = True
        elif damage == "agent": manifest["support_profile"]["modal_agent"] = "InventedAgent"
        elif damage == "sort": manifest["support_profile"]["typed_sort"] = "Person"
        elif damage == "authority": manifest["authority"]["proof"] = True
        elif damage == "report_pin": manifest["relational_report_sha256"] = "f" * 64
        elif damage == "mask": manifest["training_mask"] = False
        manifest["file_sha256"] = {name: sha(body.encode()) for name, body in sorted(files.items())}
        manifest = contracts.seal_record({key: value for key, value in manifest.items()
                                          if key not in ("record_cid", "cid_scope")})
        return replace(child, manifest_json=canonical_dag_json_bytes(manifest).decode(), files=tuple(sorted(files.items())))

    monkeypatch.setattr(preservation, "prepare_relational_ast_preservation", changed)
    with pytest.raises(ValueError):
        reviewed_preservation_prepare_fixture_v2(control)


@pytest.mark.parametrize("damage", ["caller_inputs", "producer_pins"])
def test_reviewed_preservation_v2_fences_operation_inputs_and_producers(reviewed_preservation_control_v2, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    control = reviewed_preservation_control_v2
    if damage == "caller_inputs":
        original = preservation.prepare_relational_ast_preservation

        def changing(*args, **kwargs):
            result = original(*args, **kwargs)
            unit_id = control["case"]["declaration"]["units"][0]["unit_id"]
            control["kwargs"]["preparation_inputs"]["source_inputs"][unit_id]["raw_bytes"] += b" changed caller bytes"
            return result

        monkeypatch.setattr(preservation, "prepare_relational_ast_preservation", changing)
    else:
        original = shared._reviewed_preservation_pins
        calls = []

        def changing(owners):
            result = original(owners)
            calls.append(True)
            if len(calls) > 1:
                result[str(Path(shared.__file__).resolve())] = "f" * 64
            return result

        monkeypatch.setattr(shared, "_reviewed_preservation_pins", changing)
    with pytest.raises(ValueError, match="inputs, preparation or producers changed"):
        reviewed_preservation_prepare_fixture_v2(control)


# Reuse complete fictional V3 admission and graph fixtures before reproducing
# the aggregate seam. No legal review, child proof or original build is invented.
def test_reviewed_preservation_v3_requires_explicit_aggregate_after_genuine_mixed_replay(
        tmp_path_factory):
    from tests.unit.logic.autoformal import test_corpus_norm_definition_adapter as graph_fixture
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    baseline = graph_fixture.reviewed_graph_baseline_v3.__wrapped__(tmp_path_factory)
    baseline["helper"].assert_signatures_valid(baseline["case"])
    admission = baseline["admission"]
    assert admission["semantic_use_eligible"] is True and admission["fixture_only"] is True
    assert admission["blockers"] == []
    assert {"formalization", "proof_obligation"} <= set(admission["permitted_uses"])
    graph = graph_fixture.build_reviewed_graph_fixture_v3(baseline)
    assert graph_fixture.validate_reviewed_graph_fixture_v3(baseline, graph) == graph
    assert graph["schema"] == "legal-corpus-reviewed-norm-candidate-graph/v3"
    assert graph["counts"]["units"] == 3 and graph["counts"]["definitions"] == 1
    assert graph["counts"]["norms"] == graph["counts"]["definition_uses"] == 2
    assert graph["semantic_use_eligible"] is False and not any(graph["authority"].values())
    assert all(type(graph[key]) is int and graph[key] == 0
               for key in ("training_mask", "evaluation_gold_mask"))
    declaration = baseline["case"]["declaration"]
    assert [unit["relational_profile"] for unit in declaration["units"]] == [
        relational.PROFILE, relational.PROFILE, relational.MIXED_PROFILE]
    original = baseline["admission_owner"].norm._snapshot({
        "args": list(baseline["args"]), "inputs": baseline["inputs"]})[1]
    children = []
    headers = []
    for unit, admitted, graph_unit, ast_record in zip(declaration["units"], admission["units"],
            graph["unit_records"], graph["ast_records"], strict=True):
        inputs = baseline["case"]["relational_inputs"][unit["unit_id"]]
        report, request_raw = inputs["report"], inputs["request_raw"]
        ir = json.loads(ast_record["ast_json"])
        assert canonical_dag_json_bytes(ir) == canonical_dag_json_bytes(admitted["canonical_ir"])
        assert ir["typed_expression"] == report["typed_expression"]
        assert ir["argument_roles"] == report["argument_roles"] == admitted["argument_roles"]
        assert ir["source_binding"]["source_version_cid"] == unit["source_version"]["record_cid"]
        assert ir["source_binding"]["occurrence_cid"] == unit["occurrence"]["record_cid"]
        assert graph_unit["relational_request_sha256"] == unit["relational_request_sha256"]
        headers.append({key: value for key, value in ir["typed_expression"]["signature"].items()
                        if key != "symbols"})
        child_args = dict(expected_report_sha256=inputs["expected_report_sha256"],
                          expected_request_sha256=unit["relational_request_sha256"], toolchain=TOOLCHAIN)
        if unit["relational_profile"] == relational.MIXED_PROFILE:
            child = preservation.prepare_mixed_relational_ast_preservation(report, request_raw, **child_args)
            child_pin = preservation.preparation_sha256(child)
            assert preservation.validate_mixed_relational_ast_preservation(child, report, request_raw,
                expected_preparation_sha256=child_pin, **child_args) == child
            manifest = child.to_dict()
            assert manifest["profile"] == preservation.MIXED_PROFILE
            assert manifest["mixed_report_sha256"] == inputs["expected_report_sha256"]
            assert manifest["native_ast"] is None and manifest["native_TDFOL_route_used"] is False
            assert manifest["native_parser_roundtrip"] is False
        else:
            child = preservation.prepare_relational_ast_preservation(report, request_raw, **child_args)
            child_pin = preservation.preparation_sha256(child)
            assert preservation.validate_relational_ast_preservation(child, report, request_raw,
                expected_preparation_sha256=child_pin, **child_args) == child
            manifest = child.to_dict()
            assert manifest["profile"] == preservation.RELATIONAL_PROFILE
            assert manifest["relational_report_sha256"] == inputs["expected_report_sha256"]
        assert manifest["original_request_sha256"] == unit["relational_request_sha256"]
        assert manifest["preparation_only"] is True and not any(manifest["authority"].values())
        assert all(type(manifest[key]) is int and manifest[key] == 0
                   for key in ("training_mask", "evaluation_gold_mask"))
        assert len(child.files) == 7 and len(manifest["expected_modules"]) == 4
        assert len(manifest["theorems"]) == len(set(manifest["theorems"])) == 5
        assert manifest["file_sha256"] == {name: sha(body.encode("utf-8")) for name, body in child.files}
        children.append(child)
    assert len(children) == 3 and headers[0] == headers[1] and headers[2] != headers[0]
    assert sum(len(child.to_dict()["theorems"]) for child in children) == 15
    assert original == baseline["admission_owner"].norm._snapshot({
        "args": list(baseline["args"]), "inputs": baseline["inputs"]})[1]

    # The existing exact Object-only aggregate retains its original V2 domain.
    with pytest.raises(ValueError):
        shared.prepare_reviewed_norm_preservation_corpus_v2(graph, admission, *baseline["args"],
            expected_graph_sha256=graph_fixture.owner.norm_definition_graph_sha256(graph),
            expected_admission_sha256=baseline["admission_sha256"], toolchain=TOOLCHAIN,
            **baseline["inputs"])
    assert original == baseline["admission_owner"].norm._snapshot({
        "args": list(baseline["args"]), "inputs": baseline["inputs"]})[1]
    assert callable(getattr(shared, "prepare_reviewed_norm_preservation_corpus_v3", None)), (
        "explicit reviewed mixed-sort aggregate preservation missing after accepted V3 admission, graph and child replay")



def reviewed_preservation_graph_fixture_v3(tmp_path_factory):
    from tests.unit.logic.autoformal import test_corpus_norm_definition_adapter as graph_fixture
    baseline = graph_fixture.reviewed_graph_baseline_v3.__wrapped__(tmp_path_factory)
    baseline["helper"].assert_signatures_valid(baseline["case"])
    graph = graph_fixture.build_reviewed_graph_fixture_v3(baseline)
    assert graph_fixture.validate_reviewed_graph_fixture_v3(baseline, graph) == graph
    return dict(helper=graph_fixture, mixed_helper=baseline["helper"], owner=baseline["admission_owner"],
        case=baseline["case"], args=baseline["args"], kwargs=baseline["inputs"],
        admission=baseline["admission"], graph=graph, admission_sha=baseline["admission_sha256"],
        graph_sha=graph_fixture.owner.norm_definition_graph_sha256(graph))


def reviewed_preservation_prepare_fixture_v3(control, *, graph=None, admission=None, args=None, kwargs=None):
    return shared.prepare_reviewed_norm_preservation_corpus_v3(
        control["graph"] if graph is None else graph, control["admission"] if admission is None else admission,
        *(control["args"] if args is None else args), expected_graph_sha256=control["graph_sha"],
        expected_admission_sha256=control["admission_sha"], toolchain=TOOLCHAIN,
        **(control["kwargs"] if kwargs is None else kwargs))


def reviewed_preservation_validate_fixture_v3(control, offered=None, *, args=None, kwargs=None, toolchain=TOOLCHAIN):
    offered = control["preparation"] if offered is None else offered
    return shared.validate_reviewed_norm_preservation_corpus_v3(offered, control["graph"], control["admission"],
        *(control["args"] if args is None else args),
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(offered),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=toolchain, **(control["kwargs"] if kwargs is None else kwargs))


@pytest.fixture(scope="module")
def reviewed_preservation_control_v3(tmp_path_factory):
    control = reviewed_preservation_graph_fixture_v3(tmp_path_factory)
    control["preparation"] = reviewed_preservation_prepare_fixture_v3(control)
    return control


def test_reviewed_preservation_v3_retains_all_mixed_and_object_children_without_coercion(reviewed_preservation_control_v3):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    control = reviewed_preservation_control_v3
    prepared = control["preparation"]
    assert reviewed_preservation_validate_fixture_v3(control) == prepared
    manifest, files = prepared.to_dict(), dict(prepared.files)
    assert manifest["schema"] == shared.REVIEWED_MIXED_PRESERVATION_SCHEMA
    assert manifest["profile"] == shared.REVIEWED_MIXED_PRESERVATION_PROFILE
    assert len(files) == 35 and len(manifest["expected_modules"]) == 8
    assert len(manifest["preservation_obligations"]) == len(set(manifest["preservation_obligations"])) == 15
    assert len(manifest["common_module_profiles"]) == 2
    assert len({x["signature_namespace_sha256"] for x in manifest["units"]}) == 2
    assert manifest["definition_use_record_cids"] == [x["record_cid"] for x in control["graph"]["definition_use_records"]]
    assert manifest["preparation_only"] is True and manifest["semantic_use_eligible"] is False
    assert manifest["proof_status"] == manifest["lean_compilation_status"] == "not_executed"
    assert not any(manifest["authority"].values())
    assert all(type(manifest[k]) is int and manifest[k] == 0 for k in ("training_mask", "evaluation_gold_mask"))
    assert all(manifest[k] is False for k in preservation.FALSE_FLAGS)
    support = manifest["support_profile"]
    assert support["all_declared_units_required"] is support["ordered_units_preserved"] is True
    assert support["cross_namespace_signature_or_carrier_coercion"] is False
    assert support["cross_unit_definition_application_proved"] is False
    assert support["predicate_compatibility_is_syntactic_only"] is True
    assert (support["max_units"], support["max_files"], support["max_modules"], support["max_obligations"],
            support["max_project_utf8_bytes"]) == (8, 78, 11, 40, 8 * 1024 * 1024)
    source_units = control["case"]["declaration"]["units"]
    assert [row["unit_id"] for row in manifest["units"]] == [row["unit_id"] for row in source_units]
    headers = manifest["signature_headers_by_unit"]
    assert headers[0]["signature_header"] == headers[1]["signature_header"]
    assert headers[2]["signature_header"] != headers[0]["signature_header"]
    assert len(manifest["predicate_compatibility_ledger"]) == 2
    for row, header, unit in zip(manifest["units"], headers, source_units, strict=True):
        inputs = control["case"]["relational_inputs"][unit["unit_id"]]
        report = inputs["report"]
        expected_header = {k: v for k, v in report["typed_expression"]["signature"].items() if k != "symbols"}
        assert row["signature_header"] == header["signature_header"] == expected_header
        assert header["unit_id"] == row["unit_id"]
        assert row["relational_profile"] == header["relational_profile"] == unit["relational_profile"]
        assert row["signature_namespace_sha256"] == header["signature_namespace_sha256"] == sha(
            canonical_dag_json_bytes({"relational_profile": report["profile"], "signature_header": expected_header}))
        assert row["source_version_cid"] == unit["source_version"]["record_cid"]
        assert row["source_occurrence_cid"] == unit["occurrence"]["record_cid"]
        args = dict(expected_report_sha256=inputs["expected_report_sha256"],
            expected_request_sha256=unit["relational_request_sha256"], toolchain=TOOLCHAIN)
        if unit["relational_profile"] == relational.MIXED_PROFILE:
            child = preservation.prepare_mixed_relational_ast_preservation(report, inputs["request_raw"], **args)
            assert row["child_family"] == "tdfol" and row["child_preservation_profile"] == preservation.MIXED_PROFILE
            assert child.to_dict()["native_ast"] is None and child.to_dict()["native_parser_roundtrip"] is False
        else:
            child = preservation.prepare_relational_ast_preservation(report, inputs["request_raw"], **args)
            assert row["child_family"] == "deontic_fol" and row["child_preservation_profile"] == preservation.RELATIONAL_PROFILE
        assert row["child_preparation_sha256"] == preservation.preparation_sha256(child)
        assert files[row["child_manifest_path"]] == child.manifest_json
        assert len(row["original_child_files"]) == 7
        for companion in row["original_child_files"]:
            assert files[companion["companion_path"]] == dict(child.files)[companion["original_path"]]
        path = row["instance_module"].replace(".", "/") + ".lean"
        assert files[path] == dict(child.files)[path]
        assert row["preservation_obligations"] == child.to_dict()["theorems"]
    root = shared.REVIEWED_MIXED_PRESERVATION_ROOT
    assert files[root + ".lean"] == "".join("import " + x["instance_module"] + "\n" for x in manifest["units"])
    import tomllib
    library, = tomllib.loads(files["lakefile.toml"])["lean_lib"]
    assert library["roots"] == manifest["expected_modules"]
    assert manifest["file_sha256"] == {name: sha(body.encode()) for name, body in files.items()}


@pytest.mark.parametrize("damage", ["missing_unit", "duplicate_unit", "reordered_units", "header", "namespace",
    "source_version", "profile", "child_family", "child_profile", "definition_use", "fifth_obligation",
    "alias_obligation", "predicate_roles", "companion", "child_manifest", "active_mixed", "active_object",
    "common_semantics", "aggregate_root", "lakefile", "authority", "mask"])
def test_reviewed_preservation_v3_resealed_population_namespace_and_child_mutants_refuse(reviewed_preservation_control_v3, damage):
    control = reviewed_preservation_control_v3
    prepared = control["preparation"]
    manifest, files = prepared.to_dict(), dict(prepared.files)
    row = manifest["units"][2]
    if damage == "missing_unit": manifest["units"].pop()
    elif damage == "duplicate_unit": manifest["units"][2] = deepcopy(manifest["units"][1])
    elif damage == "reordered_units": manifest["units"].reverse()
    elif damage == "header": manifest["signature_headers_by_unit"][2]["signature_header"] = deepcopy(manifest["signature_headers_by_unit"][0]["signature_header"])
    elif damage == "namespace": row["signature_namespace_sha256"] = manifest["units"][0]["signature_namespace_sha256"]
    elif damage == "source_version": row["source_version_cid"] = manifest["units"][0]["source_version_cid"]
    elif damage == "profile": row["relational_profile"] = manifest["units"][0]["relational_profile"]
    elif damage == "child_family": row["child_family"] = "deontic_fol"
    elif damage == "child_profile": row["child_preservation_profile"] = manifest["units"][0]["child_preservation_profile"]
    elif damage == "definition_use": manifest["definition_use_record_cids"].pop()
    elif damage == "fifth_obligation": row["preservation_obligations"].pop()
    elif damage == "alias_obligation": row["preservation_obligations"][-1] = row["instance_module"] + ".alias_assuming_desired_equivalence"
    elif damage == "predicate_roles":
        ledger = next(x for x in manifest["predicate_compatibility_ledger"].values() if x["relational_profile"] == row["relational_profile"])
        ledger["predicates"]["CoveredOfficer"]["ordered_argument_roles"] = ["invented_role"]
    elif damage == "companion":
        x = next(x for x in row["original_child_files"] if x["original_path"] == "preservation-inputs.json")
        files[x["companion_path"]] += "\nchanged complete retained inputs\n"
        x["sha256"] = sha(files[x["companion_path"]].encode())
    elif damage == "child_manifest": files[row["child_manifest_path"]] += "\n"
    elif damage in ("active_mixed", "active_object"):
        chosen = row if damage == "active_mixed" else manifest["units"][0]
        files[chosen["instance_module"].replace(".", "/") + ".lean"] += "\n-- changed complete witness\n"
    elif damage == "common_semantics": files["LegalMixedRelationalAstPreservation/Semantics.lean"] += "\n-- changed common semantics\n"
    elif damage == "aggregate_root": files[shared.REVIEWED_MIXED_PRESERVATION_ROOT + ".lean"] = "-- omitted all units\n"
    elif damage == "lakefile": files["lakefile.toml"] = files["lakefile.toml"].replace("legal", "other", 1)
    elif damage == "authority": manifest["authority"]["corpus_admission"] = True
    elif damage == "mask": manifest["training_mask"] = False
    forged = reviewed_preservation_reseal_fixture_v2(prepared, manifest, files)
    with pytest.raises((ValueError, TypeError)):
        reviewed_preservation_validate_fixture_v3(control, forged)


@pytest.mark.parametrize("damage", ["source", "request", "report", "review", "time", "dependency"])
def test_reviewed_preservation_v3_replays_current_complete_sources_reviews_and_dependencies(reviewed_preservation_control_v3, damage):
    control = reviewed_preservation_control_v3
    args, kwargs = deepcopy(control["args"]), deepcopy(control["kwargs"])
    unit_id = control["case"]["declaration"]["units"][2]["unit_id"]
    if damage == "source": kwargs["preparation_inputs"]["source_inputs"][unit_id]["raw_bytes"] += b" changed"
    elif damage == "request": kwargs["preparation_inputs"]["relational_inputs"][unit_id]["request_raw"] += b" "
    elif damage == "report": kwargs["preparation_inputs"]["relational_inputs"][unit_id]["report"]["argument_roles"][0]["roles"] = ["invented_role"]
    elif damage == "review": args[3][0]["interpretation"]["rationale"] += " unsigned change"
    elif damage == "time": kwargs["at_time_utc"] = "2026-11-02T00:00:00Z"
    elif damage == "dependency": kwargs["observed_artifact_sha256s"][unit_id + ":source"] = "f" * 64
    with pytest.raises((ValueError, TypeError)):
        reviewed_preservation_validate_fixture_v3(control, args=args, kwargs=kwargs)


@pytest.mark.parametrize("direction", ["v2_prepare_v3", "v3_prepare_v2", "v2_validate_v3", "v3_validate_v2"])
def test_reviewed_preservation_v3_and_v2_domains_remain_separate(reviewed_preservation_control_v3, reviewed_preservation_control_v2, direction):
    v3, v2 = reviewed_preservation_control_v3, reviewed_preservation_control_v2
    with pytest.raises((ValueError, TypeError)):
        if direction == "v2_prepare_v3": reviewed_preservation_prepare_fixture_v2(v3)
        elif direction == "v3_prepare_v2": reviewed_preservation_prepare_fixture_v3(v2)
        elif direction == "v2_validate_v3": reviewed_preservation_validate_fixture_v2(v3)
        else: reviewed_preservation_validate_fixture_v3(v3, v2["preparation"])


@pytest.mark.parametrize("field,value", [
    ("REVIEWED_MIXED_PRESERVATION_SCHEMA", "legal-corpus-reviewed-preservation-preparation/v2"),
    ("REVIEWED_MIXED_PRESERVATION_PROFILE", "reviewed-multi-unit-object-relational-preservation/v2"),
    ("REVIEWED_MIXED_PRESERVATION_ROOT", "LegalReviewedNormPreservation"),
    ("MAX_REVIEWED_PRESERVATION_UNITS", 9), ("MAX_REVIEWED_PRESERVATION_FILES", 79),
    ("MAX_REVIEWED_PRESERVATION_MODULES", 12), ("MAX_REVIEWED_PRESERVATION_OBLIGATIONS", 41),
    ("MAX_REVIEWED_PRESERVATION_UNITS", True), ("MAX_PROJECT_BYTES", 8 * 1024 * 1024 + 1)])
def test_reviewed_preservation_v3_policy_aliases_and_raised_bounds_refuse_before_owners(reviewed_preservation_control_v3, monkeypatch, field, value):
    target = shared.joint_owner if field == "MAX_PROJECT_BYTES" else shared
    monkeypatch.setattr(target, field, value)
    monkeypatch.setattr(shared, "_reviewed_mixed_preservation_owners", lambda: pytest.fail("lazy owners reached after fixed policy refusal"))
    with pytest.raises(ValueError, match="fixed reviewed mixed preservation domain and original bounds"):
        reviewed_preservation_prepare_fixture_v3(reviewed_preservation_control_v3)


@pytest.mark.parametrize("field", ["RELATIONAL_PROFILE", "RELATIONAL_PROJECT_ROOT", "MIXED_PROFILE", "MIXED_PROJECT_ROOT", "AUTHORITY", "FALSE_FLAGS"])
def test_reviewed_preservation_v3_child_domain_constant_swaps_refuse(reviewed_preservation_control_v3, monkeypatch, field):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    if field in ("AUTHORITY", "FALSE_FLAGS"):
        replacement = dict(getattr(preservation, field))
        replacement[next(iter(replacement))] = True
    else:
        replacement = "invented-domain"
    monkeypatch.setattr(preservation, field, replacement)
    with pytest.raises(ValueError):
        reviewed_preservation_prepare_fixture_v3(reviewed_preservation_control_v3)


@pytest.mark.parametrize("field", ["root", "AUTHORITY", "FALSE_FLAGS"])
def test_reviewed_preservation_v3_late_policy_change_cannot_return_a_success(reviewed_preservation_control_v3, monkeypatch, field):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    mutated = []
    if field == "root":
        original = shared._reviewed_mixed_preservation_project
        def changing(*args, **kwargs):
            result = original(*args, **kwargs)
            monkeypatch.setattr(shared, "REVIEWED_MIXED_PRESERVATION_ROOT", "ChangedAfterProject")
            mutated.append(field)
            return result
        monkeypatch.setattr(shared, "_reviewed_mixed_preservation_project", changing)
        reason = "fixed reviewed mixed preservation domain and original bounds"
    else:
        original = preservation.validate_mixed_relational_ast_preservation
        def changing(*args, **kwargs):
            result = original(*args, **kwargs)
            replacement = dict(getattr(preservation, field))
            replacement[next(iter(replacement))] = True
            monkeypatch.setattr(preservation, field, replacement)
            mutated.append(field)
            return result
        monkeypatch.setattr(preservation, "validate_mixed_relational_ast_preservation", changing)
        reason = "complete unchanged child preservation domain and false authorities required"
    with pytest.raises(ValueError, match=reason):
        reviewed_preservation_prepare_fixture_v3(reviewed_preservation_control_v3)
    assert mutated == [field]


def reviewed_preservation_capacity_control_v3(control, total_units):
    """Extend the existing explicitly fictional source/review fixture, not a legal review."""
    from ipfs_datasets_py.logic.autoformal import corpus_source, legal_relational_norm_v1 as relational
    case = deepcopy({k: v for k, v in control["case"].items() if k != "signers"})
    case["signers"] = control["case"]["signers"]
    template = case["declaration"]["units"][1]
    original_raw = case["relational_inputs"][template["unit_id"]]["request_raw"]
    original_text = case["source_inputs"][template["unit_id"]]["extracted_text"]
    for ordinal in range(4, total_units + 1):
        identity = case["declaration"]["component_id"] + "/capacity-use-" + str(ordinal)
        text = original_text + " Fictional independent use " + str(ordinal) + "."
        raw = text.encode("utf-8")
        version = corpus_source.build_source_version(source_id=identity, release_id="fixture:mixed-act-v1",
            edition="fictional-edition-1", provision_id=identity, raw_bytes=raw, expected_raw_sha256=sha(raw),
            extracted_text=text, expected_extracted_sha256=sha(raw), extraction_profile="identity/v1",
            normalization_profile="identity/v1", media_type="text/plain")
        occurrence = corpus_source.build_source_occurrence(version, expected_raw_sha256=sha(raw),
            extracted_text=text, expected_extracted_sha256=sha(raw), start_char=0, end_char=len(text), start_utf8=0, end_utf8=len(raw))
        request = json.loads(original_raw)
        request["expression"]["expression_id"] += ":capacity-" + str(ordinal)
        reviewed_preservation_refresh_expression_v2(request)
        request_raw = canonical_dag_json_bytes(request)
        report = relational.prepare_relational_norm_v1(request_raw, expected_request_sha256=sha(request_raw))
        unit = deepcopy(template)
        unit.update(unit_id=identity, source_version=version, occurrence=occurrence,
            source_artifact_id=identity + ":source", ir_artifact_id=identity + ":ir",
            relational_request_sha256=sha(request_raw), coverage=[{"typed_path": x["typed_path"],
                "start_char": 0, "end_char": len(text), "start_utf8": 0, "end_utf8": len(raw)} for x in report["structural_mapping"]])
        case["declaration"]["units"].append(unit)
        case["source_inputs"][identity] = {"raw_bytes": raw, "extracted_text": text}
        case["relational_inputs"][identity] = dict(request_raw=request_raw, report=report,
            expected_report_sha256=relational.relational_norm_report_sha256(report))
        use = deepcopy(case["declaration"]["definition_uses"][0])
        use.update(use_unit_id=identity, use_occurrence_cid=occurrence["record_cid"])
        case["declaration"]["definition_uses"].append(use)
    helper, owner = control["mixed_helper"], control["owner"]
    case["preparation"] = helper.prepare(owner, case)
    helper.refresh_signed_reviews(case, owner)
    helper.assert_signatures_valid(case)
    args, kwargs = helper.fixture.reviewed_assessment_arguments_v2(owner, case)
    admission = owner.assess_reviewed_norm_admission_v3(*args, **kwargs)
    assert admission["semantic_use_eligible"] is True and admission["fixture_only"] is True
    assert admission["blockers"] == []
    admission_sha = owner.norm_content_adjudication_sha256(admission)
    graph_owner = control["helper"].owner
    graph = graph_owner.build_reviewed_norm_graph_v3(admission, *args, expected_admission_sha256=admission_sha, **kwargs)
    graph_sha = graph_owner.norm_definition_graph_sha256(graph)
    assert graph_owner.validate_reviewed_norm_graph_v3(graph, admission, *args,
        expected_graph_sha256=graph_sha, expected_admission_sha256=admission_sha, **kwargs) == graph
    assert graph["counts"]["units"] == total_units
    return dict(control, case=case, args=args, kwargs=kwargs, admission=admission, graph=graph,
                admission_sha=admission_sha, graph_sha=graph_sha)


@pytest.mark.parametrize("total_units", [7, 8])
def test_reviewed_preservation_v3_whole_genuine_large_population_refuses_original_capacity(reviewed_preservation_control_v3, total_units):
    control = reviewed_preservation_capacity_control_v3(reviewed_preservation_control_v3, total_units)
    before = control["owner"].norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1]
    with pytest.raises(ValueError, match="capacity"):
        reviewed_preservation_prepare_fixture_v3(control)
    assert len(control["case"]["declaration"]["units"]) == total_units
    assert before == control["owner"].norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1]


# These two source-complete fictional controls reproduce the aggregate identity
# seam. They do not authenticate statutory meaning or execute a native compiler.
def test_reviewed_preservation_v2_keeps_identical_ir_at_disjoint_reviewed_source_uses():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission_owner
    from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graph_owner
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation

    helper = reviewed_preservation_fixture_helper_v2()
    case = helper.reviewed_norm_fixture_v2(admission_owner)
    first, second = helper.reviewed_repeated_permission_source_v2(case, "nonoverlapping_paragraphs")
    reviewed_preservation_reauthorize_fixture_v2(helper, admission_owner, case)
    control = reviewed_preservation_graph_fixture_v2(helper, admission_owner, case)
    assert graph_owner.validate_reviewed_norm_graph_v2(control["graph"], control["admission"],
        *control["args"], expected_graph_sha256=control["graph_sha"],
        expected_admission_sha256=control["admission_sha"], **control["kwargs"]) == control["graph"]
    assert len(control["admission"]["units"]) == len(control["graph"]["unit_records"]) == 3
    assert control["admission"]["fixture_only"] is True
    assert control["admission"]["semantic_use_eligible"] is True and control["admission"]["blockers"] == []
    assert {key: control["graph"]["counts"][key] for key in ("units", "definitions", "norms", "definition_uses")} == dict(units=3, definitions=1, norms=2, definition_uses=2)
    assert first["source_version"] == second["source_version"]
    assert first["occurrence"]["record_cid"] != second["occurrence"]["record_cid"]
    assert first["occurrence"]["span_text"] == second["occurrence"]["span_text"]
    assert first["occurrence"]["end_char"] < second["occurrence"]["start_char"]
    assert first["occurrence"]["end_utf8"] < second["occurrence"]["start_utf8"]
    first_source, second_source = (case["source_inputs"][unit["unit_id"]] for unit in (first, second))
    assert first_source == second_source
    assert first["source_version"]["raw_artifact"]["sha256"] == sha(first_source["raw_bytes"])
    assert first["source_version"]["extracted_view"]["sha256"] == sha(first_source["extracted_text"].encode())
    first_input, second_input = (case["relational_inputs"][unit["unit_id"]] for unit in (first, second))
    assert first_input == second_input
    assert first["relational_request_sha256"] == second["relational_request_sha256"]
    children = []
    for unit in (first, second):
        inputs = case["relational_inputs"][unit["unit_id"]]
        child_args = dict(expected_report_sha256=inputs["expected_report_sha256"],
            expected_request_sha256=unit["relational_request_sha256"], toolchain=TOOLCHAIN)
        child = preservation.prepare_relational_ast_preservation(inputs["report"], inputs["request_raw"], **child_args)
        assert preservation.validate_relational_ast_preservation(child, inputs["report"], inputs["request_raw"],
            expected_preparation_sha256=preservation.preparation_sha256(child), **child_args) == child
        assert len(child.files) == 7 and len(child.to_dict()["theorems"]) == 5
        children.append(child)
    assert children[0] == children[1]  # Healthy legacy children share a content identity.
    opening = admission_owner.norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1]

    prepared = reviewed_source_use_prepare_fixture(control, 2)

    manifest, files = prepared.to_dict(), dict(prepared.files)
    reviewed_source_use_assert_bindings(prepared)
    assert [unit["unit_id"] for unit in manifest["units"]] == [unit["unit_id"] for unit in case["declaration"]["units"]]
    assert len(manifest["units"]) == len({unit["instance_module"] for unit in manifest["units"]}) == 3
    assert len(manifest["preservation_obligations"]) == len(set(manifest["preservation_obligations"])) == 15
    for unit in manifest["units"]:
        child_manifest = contracts.load_record_bytes(files[unit["child_manifest_path"]].encode(),
            expected_sha256=unit["child_manifest_sha256"])
        assert len(unit["original_child_files"]) == 7
        assert len(unit["preservation_obligations"]) == 5
        assert child_manifest["theorems"] == unit["preservation_obligations"]
        for companion in unit["original_child_files"]:
            assert sha(files[companion["companion_path"]].encode()) == companion["sha256"]
    assert manifest["preparation_only"] is True and not any(manifest["authority"].values())
    assert manifest["semantic_use_eligible"] is False
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert admission_owner.norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1] == opening


def test_reviewed_preservation_v3_keeps_identical_mixed_ir_at_disjoint_reviewed_source_uses():
    from tests.unit.logic.autoformal import test_legal_reviewed_norm_admission_v3 as mixed_fixture
    from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3 as admission_owner
    from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graph_owner
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    # mixed_base does not read its v2_saved argument. No saved-V2 transport or
    # filesystem compatibility experiment is claimed by this direct fixture use.
    case = mixed_fixture.mixed_base.__wrapped__(admission_owner, None)
    first, second = mixed_fixture.fixture.reviewed_repeated_permission_source_v2(case, "nonoverlapping_paragraphs")
    case["preparation"] = mixed_fixture.prepare(admission_owner, case)
    mixed_fixture.refresh_signed_reviews(case, admission_owner)
    mixed_fixture.assert_signatures_valid(case)
    args, kwargs = mixed_fixture.fixture.reviewed_assessment_arguments_v2(admission_owner, case)
    admission = admission_owner.assess_reviewed_norm_admission_v3(*args, **kwargs)
    admission_sha = admission_owner.norm_content_adjudication_sha256(admission)
    assert admission_owner.validate_reviewed_norm_admission_v3(admission, *args,
        expected_report_sha256=admission_sha, **kwargs) == admission
    graph = graph_owner.build_reviewed_norm_graph_v3(admission, *args,
        expected_admission_sha256=admission_sha, **kwargs)
    graph_sha = graph_owner.norm_definition_graph_sha256(graph)
    assert graph_owner.validate_reviewed_norm_graph_v3(graph, admission, *args,
        expected_graph_sha256=graph_sha, expected_admission_sha256=admission_sha, **kwargs) == graph
    assert len(admission["units"]) == len(graph["unit_records"]) == 3
    assert admission["fixture_only"] is True and admission["semantic_use_eligible"] is True
    assert admission["blockers"] == []
    assert {key: graph["counts"][key] for key in ("units", "definitions", "norms", "definition_uses")} == dict(units=3, definitions=1, norms=2, definition_uses=2)
    assert [unit["relational_profile"] for unit in case["declaration"]["units"]] == [
        relational.PROFILE, relational.MIXED_PROFILE, relational.MIXED_PROFILE]
    assert first["source_version"] == second["source_version"]
    assert first["occurrence"]["record_cid"] != second["occurrence"]["record_cid"]
    assert first["occurrence"]["span_text"] == second["occurrence"]["span_text"]
    assert first["occurrence"]["end_char"] < second["occurrence"]["start_char"]
    assert first["occurrence"]["end_utf8"] < second["occurrence"]["start_utf8"]
    first_source, second_source = (case["source_inputs"][unit["unit_id"]] for unit in (first, second))
    assert first_source == second_source
    assert first["source_version"]["raw_artifact"]["sha256"] == sha(first_source["raw_bytes"])
    assert first["source_version"]["extracted_view"]["sha256"] == sha(first_source["extracted_text"].encode())
    first_input, second_input = (case["relational_inputs"][unit["unit_id"]] for unit in (first, second))
    assert first_input == second_input
    assert first["relational_request_sha256"] == second["relational_request_sha256"]
    children = []
    for unit in (first, second):
        inputs = case["relational_inputs"][unit["unit_id"]]
        child_args = dict(expected_report_sha256=inputs["expected_report_sha256"],
            expected_request_sha256=unit["relational_request_sha256"], toolchain=TOOLCHAIN)
        child = preservation.prepare_mixed_relational_ast_preservation(inputs["report"], inputs["request_raw"], **child_args)
        assert preservation.validate_mixed_relational_ast_preservation(child, inputs["report"], inputs["request_raw"],
            expected_preparation_sha256=preservation.preparation_sha256(child), **child_args) == child
        assert len(child.files) == 7 and len(child.to_dict()["theorems"]) == 5
        children.append(child)
    assert children[0] == children[1]  # Healthy mixed children share a content identity.
    opening = admission_owner.norm._snapshot({"args": list(args), "kwargs": kwargs})[1]

    prepared = shared.prepare_reviewed_norm_preservation_corpus_v3(graph, admission, *args,
        expected_graph_sha256=graph_sha, expected_admission_sha256=admission_sha,
        toolchain=TOOLCHAIN, instance_identity_profile="reviewed-source-use/v1", **kwargs)

    manifest, files = prepared.to_dict(), dict(prepared.files)
    reviewed_source_use_assert_bindings(prepared)
    assert [unit["unit_id"] for unit in manifest["units"]] == [unit["unit_id"] for unit in case["declaration"]["units"]]
    assert len(manifest["units"]) == len({unit["instance_module"] for unit in manifest["units"]}) == 3
    assert len(manifest["preservation_obligations"]) == len(set(manifest["preservation_obligations"])) == 15
    for unit in manifest["units"]:
        child_manifest = contracts.load_record_bytes(files[unit["child_manifest_path"]].encode(),
            expected_sha256=unit["child_manifest_sha256"])
        assert len(unit["original_child_files"]) == 7
        assert len(unit["preservation_obligations"]) == 5
        assert child_manifest["theorems"] == unit["preservation_obligations"]
        for companion in unit["original_child_files"]:
            assert sha(files[companion["companion_path"]].encode()) == companion["sha256"]
    assert manifest["preparation_only"] is True and not any(manifest["authority"].values())
    assert manifest["semantic_use_eligible"] is False
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert admission_owner.norm._snapshot({"args": list(args), "kwargs": kwargs})[1] == opening


# Reviewed-source-use is an explicit custody domain, not a statutory or model
# qualification. These fixtures exercise full current fictional review replay.
def reviewed_source_use_prepare_fixture(control, version):
    prepare = getattr(shared, "prepare_reviewed_norm_preservation_corpus_v" + str(version))
    return prepare(control["graph"], control["admission"], *control["args"],
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, instance_identity_profile="reviewed-source-use/v1", **control["kwargs"])


def reviewed_source_use_validate_fixture(control, version, prepared, *, args=None, kwargs=None,
        instance_identity_profile="reviewed-source-use/v1"):
    validate = getattr(shared, "validate_reviewed_norm_preservation_corpus_v" + str(version))
    return validate(prepared, control["graph"], control["admission"],
        *(control["args"] if args is None else args),
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(prepared),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, instance_identity_profile=instance_identity_profile,
        **(control["kwargs"] if kwargs is None else kwargs))


def reviewed_source_use_assert_bindings(prepared):
    manifest, files = prepared.to_dict(), dict(prepared.files)
    assert manifest["instance_identity_profile"] == "reviewed-source-use/v1"
    assert manifest["profile"].endswith("+reviewed-source-use/v1")
    inputs = json.loads(files["reviewed-input-bindings.json"])
    assert inputs["instance_identity_profile"] == manifest["instance_identity_profile"]
    assert inputs["units"] == manifest["units"]
    for row in manifest["units"]:
        expected = {"schema": "legal-native-reviewed-source-use-binding/v1", **{key: row[key]
            for key in ("unit_id", "source_version_cid", "source_occurrence_cid", "complete_ir_sha256",
                "graph_unit_record_cid", "graph_ast_record_cid", "scope_record_cid", "interpretation_record_cid")}}
        assert row["source_use_binding"] == expected
        assert row["source_use_binding_sha256"] == sha(canonical_dag_json_bytes(expected))
        child = contracts.load_record_bytes(files[row["child_manifest_path"]].encode(),
            expected_sha256=row["child_manifest_sha256"])
        assert child["profile"].endswith("+reviewed-source-use/v1")
        assert child["source_use_binding"] == expected
        assert child["source_use_binding_sha256"] == row["source_use_binding_sha256"]
        assert child["instance_identity_profile"] == manifest["instance_identity_profile"]
        assert child["theorems"] == row["preservation_obligations"]
        assert len(row["original_child_files"]) == 7 and len(child["theorems"]) == 5
        for companion in row["original_child_files"]:
            body = files[companion["companion_path"]]
            assert sha(body.encode()) == child["file_sha256"][companion["original_path"]] == companion["sha256"]
            if companion["original_path"] == "preservation-inputs.json":
                child_inputs = json.loads(body)
                assert child_inputs["source_use_binding"] == expected
                assert child_inputs["source_use_binding_sha256"] == row["source_use_binding_sha256"]
                assert child_inputs["instance_identity_profile"] == manifest["instance_identity_profile"]
    assert len(manifest["expected_modules"]) <= 11 and len(files) <= 78
    assert len(manifest["preservation_obligations"]) == 5 * len(manifest["units"]) <= 40
    assert not any(manifest["authority"].values())
    assert manifest["semantic_use_eligible"] is False
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("version", [2, 3])
def test_reviewed_source_use_complete_project_and_explicit_domain_separation(request, version):
    control = request.getfixturevalue("reviewed_preservation_control_v" + str(version))
    prepared = reviewed_source_use_prepare_fixture(control, version)
    reviewed_source_use_assert_bindings(prepared)
    assert reviewed_source_use_validate_fixture(control, version, prepared) == prepared
    assert reviewed_source_use_prepare_fixture(control, version) == prepared
    with pytest.raises(ValueError):
        reviewed_source_use_validate_fixture(control, version, prepared, instance_identity_profile=None)
    with pytest.raises(ValueError):
        reviewed_source_use_validate_fixture(control, version, control["preparation"])
    assert "instance_identity_profile" not in control["preparation"].to_dict()


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("field", ["schema", "unit_id", "source_version_cid", "source_occurrence_cid",
    "complete_ir_sha256", "graph_unit_record_cid", "graph_ast_record_cid", "scope_record_cid", "interpretation_record_cid"])
def test_reviewed_source_use_resealed_binding_cannot_replace_current_source(request, version, field):
    control = request.getfixturevalue("reviewed_preservation_control_v" + str(version))
    prepared = reviewed_source_use_prepare_fixture(control, version)
    manifest = prepared.to_dict()
    row = manifest["units"][1]
    row["source_use_binding"][field] += ":changed"
    row["source_use_binding_sha256"] = sha(canonical_dag_json_bytes(row["source_use_binding"]))
    forged = reviewed_preservation_reseal_fixture_v2(prepared, manifest, dict(prepared.files))
    with pytest.raises(ValueError, match="complete current regeneration"):
        reviewed_source_use_validate_fixture(control, version, forged)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("damage", ["source", "request", "review", "time", "dependency"])
def test_reviewed_source_use_replays_current_source_reviews_and_dependencies(request, version, damage):
    control = request.getfixturevalue("reviewed_preservation_control_v" + str(version))
    prepared = reviewed_source_use_prepare_fixture(control, version)
    args, kwargs = deepcopy(control["args"]), deepcopy(control["kwargs"])
    unit_id = control["case"]["declaration"]["units"][2]["unit_id"]
    if damage == "source": kwargs["preparation_inputs"]["source_inputs"][unit_id]["raw_bytes"] += b" changed"
    elif damage == "request": kwargs["preparation_inputs"]["relational_inputs"][unit_id]["request_raw"] += b" "
    elif damage == "review": args[3][0]["interpretation"]["rationale"] += " unsigned change"
    elif damage == "time": kwargs["at_time_utc"] = "2026-11-02T00:00:00Z"
    elif damage == "dependency": kwargs["observed_artifact_sha256s"][unit_id + ":source"] = "f" * 64
    with pytest.raises((ValueError, TypeError)):
        reviewed_source_use_validate_fixture(control, version, prepared, args=args, kwargs=kwargs)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("selector", [False, 0, "", "reviewed-source-use/v2", {}, []])
def test_reviewed_source_use_selector_refuses_before_lazy_owners(monkeypatch, version, selector):
    target = "_reviewed_preservation_owners" if version == 2 else "_reviewed_mixed_preservation_owners"
    monkeypatch.setattr(shared, target, lambda: pytest.fail("lazy owners reached before selector refusal"))
    prepare = getattr(shared, "prepare_reviewed_norm_preservation_corpus_v" + str(version))
    with pytest.raises(ValueError, match="explicit reviewed source-use identity profile"):
        prepare({}, {}, expected_graph_sha256="0" * 64, expected_admission_sha256="0" * 64,
            toolchain=TOOLCHAIN, instance_identity_profile=selector)


@pytest.mark.parametrize("version", [2, 3])
def test_reviewed_source_use_derived_binding_is_fenced_after_child_callbacks(request, monkeypatch, version):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    control = request.getfixturevalue("reviewed_preservation_control_v" + str(version))
    original = preservation.validate_relational_ast_preservation
    changed = []
    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        kwargs["source_use_binding"]["unit_id"] += ":changed-by-child"
        changed.append(True)
        return result
    monkeypatch.setattr(preservation, "validate_relational_ast_preservation", changing)
    with pytest.raises(ValueError, match="derived reviewed source-use binding changed"):
        reviewed_source_use_prepare_fixture(control, version)
    assert changed == [True]


@pytest.mark.parametrize("total_units", [7, 8])
def test_reviewed_source_use_preserves_original_two_namespace_capacity(reviewed_preservation_control_v3, total_units):
    control = reviewed_preservation_capacity_control_v3(reviewed_preservation_control_v3, total_units)
    with pytest.raises(ValueError, match="capacity"):
        reviewed_source_use_prepare_fixture(control, 3)
    assert len(control["case"]["declaration"]["units"]) == total_units



def test_reviewed_definition_realization_requires_constructive_api_after_complete_v3(reviewed_preservation_control_v3):
    """Fictional source-only feature probe; no legal review or native proof."""
    control = reviewed_preservation_control_v3
    preserved = control["preparation"]
    assert reviewed_preservation_validate_fixture_v3(control, preserved) == preserved
    manifest = preserved.to_dict()
    assert control["admission"]["fixture_only"] is True
    assert control["admission"]["semantic_use_eligible"] is True
    assert manifest["profile"] == shared.REVIEWED_MIXED_PRESERVATION_PROFILE
    assert len(manifest["units"]) == 3
    assert sum(unit["kind"] == "definition" for unit in control["case"]["declaration"]["units"]) == 1
    norms = [unit for unit in control["case"]["declaration"]["units"] if unit["kind"] == "norm"]
    assert len(norms) == len({unit["unit_id"] for unit in norms}) == 2
    assert len({unit["occurrence"]["record_cid"] for unit in norms}) == 2
    assert len(manifest["preservation_obligations"]) == len(set(manifest["preservation_obligations"])) == 15
    assert manifest["support_profile"]["cross_unit_definition_application_proved"] is False
    assert callable(getattr(shared, "prepare_reviewed_definition_realization_corpus_v1", None)), (
        "Missing constructive definition realization after complete fictional V3 admission, "
        "graph and preservation; existing conditional definition hypotheses are insufficient")



# Definition-realization source controls. Every legal source, reviewer and
# interpretation below is fictional. No test compiles or proves Lean here.
def reviewed_definition_realization_prepare(control, *, preservation=None, graph=None,
        admission=None, args=None, kwargs=None, **overrides):
    original = control["preparation"] if preservation is None else preservation
    options = dict(expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN)
    options.update(overrides)
    return shared.prepare_reviewed_definition_realization_corpus_v1(original,
        control["graph"] if graph is None else graph,
        control["admission"] if admission is None else admission,
        *(control["args"] if args is None else args),
        **dict(control["kwargs"] if kwargs is None else kwargs), **options)


def reviewed_definition_realization_validate(control, offered, *, args=None, kwargs=None):
    return shared.validate_reviewed_definition_realization_corpus_v1(offered,
        control["preparation"], control["graph"], control["admission"],
        *(control["args"] if args is None else args),
        expected_realization_sha256=shared.reviewed_preservation_corpus_sha256(offered),
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, **dict(control["kwargs"] if kwargs is None else kwargs))


@pytest.fixture(scope="module")
def reviewed_definition_realization_control(reviewed_preservation_control_v3):
    control = dict(reviewed_preservation_control_v3)
    control["realization"] = reviewed_definition_realization_prepare(control)
    return control


def test_reviewed_definition_realization_prepares_exact_three_heads_and_two_genuine_uses(reviewed_definition_realization_control):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    control = reviewed_definition_realization_control
    offered, original = control["realization"], control["preparation"]
    assert reviewed_definition_realization_validate(control, offered) == offered
    assert reviewed_preservation_validate_fixture_v3(control, original) == original
    manifest, files, upstream = offered.to_dict(), dict(offered.files), original.to_dict()
    assert manifest["schema"] == shared.REVIEWED_DEFINITION_REALIZATION_SCHEMA
    assert manifest["profile"] == shared.REVIEWED_DEFINITION_REALIZATION_PROFILE
    assert len(files) == 39 and len(manifest["expected_modules"]) == 10
    assert len(manifest["realization_obligations"]) == 11
    assert len(manifest["preservation_obligations"]) == 26
    assert manifest["preservation_obligations"][:15] == upstream["preservation_obligations"]
    assert len(set(manifest["preservation_obligations"])) == 26
    assert manifest["units"] == upstream["units"]
    assert manifest["upstream_manifest"] == upstream
    assert manifest["reviewed_preservation_sha256"] == shared.reviewed_preservation_corpus_sha256(original)
    selection = manifest["selection"]
    assert selection["head_symbol"] == "CoveredOfficer"
    assert selection["head_roles"] == ["officer"]
    assert selection["body_typed_node"]["symbol"] == "AppointedByBoard"
    assert selection["body_typed_sha256"] == sha(canonical_dag_json_bytes(selection["body_typed_node"]))
    occurrences = selection["occurrences"]
    assert len(occurrences) == 3
    assert [row["argument"]["symbol"] for row in occurrences] == ["officer", "officer", "supervisor"]
    assert [row["typed_path"] for row in occurrences] == [
        "/root" + "/arguments/0" * 2,
        "/root" + "/arguments/0" * 6,
        "/root" + "/arguments/0" * 5 + "/arguments/1"]
    assert len({row["unit_id"] for row in occurrences}) == 2
    assert len({row["source_occurrence_cid"] for row in occurrences}) == 2
    assert all(row["ordered_roles"] == ["officer"] for row in occurrences)
    for name, body in original.files:
        assert files[name] == body if name != "lakefile.toml" else files["definition-realization-original-lakefile.txt"] == body
    assert shared.REVIEWED_MIXED_PRESERVATION_ROOT in manifest["expected_modules"]
    assert manifest["support_profile"]["cross_unit_definition_application_proved"] is False
    assert manifest["support_profile"]["opaque_modal_rewrite"] is False
    assert manifest["support_profile"]["implicit_namespace_coercion"] is False
    assert (manifest["support_profile"]["max_files"], manifest["support_profile"]["max_modules"],
        manifest["support_profile"]["max_obligations"]) == (78, 11, 40)
    assert manifest["preparation_only"] is True
    assert manifest["proof_status"] == manifest["lean_compilation_status"] == "not_executed"
    assert manifest["semantic_use_eligible"] is False
    assert not any(manifest["authority"].values())
    assert all(manifest[key] is False for key in preservation.FALSE_FLAGS)
    assert type(manifest["training_mask"]) is int and manifest["training_mask"] == 0
    assert type(manifest["evaluation_gold_mask"]) is int and manifest["evaluation_gold_mask"] == 0
    assert manifest["file_sha256"] == {name: sha(body.encode()) for name, body in offered.files}


def test_reviewed_definition_realization_source_anchors_original_body_and_each_occurrence(reviewed_definition_realization_control):
    manifest = reviewed_definition_realization_control["realization"].to_dict()
    files = dict(reviewed_definition_realization_control["realization"].files)
    added = [x for x in manifest["expected_modules"] if x not in manifest["upstream_manifest"]["expected_modules"]]
    instance = next(x for x in added if ".Instance" in x)
    source = files[instance.replace(".", "/") + ".lean"]
    donor = manifest["selection"]["definition_instance_module"]
    assert "theorem definition_body_source_exact : " + donor + ".typedSourceAst = " in source
    assert "def definitionBodyAst : LegalRelationalAstPreservation.RoleFormula" in source
    assert "LegalRelationalAstPreservation.roleDenote base atoms definitionBodyAst" in source
    for row in manifest["selection"]["occurrences"]:
        n = str(row["ordinal"])
        assert "theorem occurrence_" + n + "_source_exact" in source
        assert "theorem occurrence_" + n + "_matches_body" in source
        whole = ".typedMixedAst" if row["relational_profile"] == "authored-many-sorted-relational-deontic/v1" else ".typedSourceAst"
        assert row["instance_module"] + whole in source
    # The same right/left Object injection is destructured constructively.
    assert "Sum.casesOn (motive := fun _ => Prop) value (fun _ => False) (fun objectOrEvent =>" in source
    assert "Sum.casesOn (motive := fun _ => Prop) objectOrEvent" in source
    assert "(fun entity => if label = \"officer\" then bodyAt base atoms entity t else False)" in source
    assert "List.rec (motive := fun _ => LegalRelationalAstPreservation.RoleFormula" in source
    assert "List.rec (motive := fun _ => LegalMixedRelationalAstPreservation.MixedFormula" in source
    assert re.search(r"\b(?:propext|funext|Classical|unsafe|partial|hDefinition|hMembership|hAlias)\b|\bEq\.(?:mp|mpr|rec|ndrec)\b|\bcast\b", source) is None
    assert "(t : Nat)" in source
    assert "(hDefinition" not in source and "(hMembership" not in source and "(hAlias" not in source
    assert re.search(r"(?m)^\s*(axiom|sorry|admit)\b", source) is None
    assert all(source.count("theorem unit_" + str(n) + "_preservation_under_realization") == 1 for n in range(3))


def test_reviewed_definition_realization_source_only_and_default_v3_remains_distinct(reviewed_definition_realization_control, monkeypatch):
    control = reviewed_definition_realization_control
    def forbidden(*args, **kwargs):
        pytest.fail("source-only definition realization attempted subprocess execution")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert reviewed_definition_realization_prepare(control) == control["realization"]
    assert reviewed_preservation_prepare_fixture_v3(control) == control["preparation"]
    assert control["preparation"].to_dict()["profile"] == shared.REVIEWED_MIXED_PRESERVATION_PROFILE
    assert control["preparation"].to_dict()["support_profile"]["cross_unit_definition_application_proved"] is False


@pytest.mark.parametrize("key", ["expected_preservation_sha256", "expected_graph_sha256", "expected_admission_sha256"])
def test_reviewed_definition_realization_requires_all_original_exact_input_pins(reviewed_definition_realization_control, key):
    with pytest.raises((ValueError, TypeError)):
        reviewed_definition_realization_prepare(reviewed_definition_realization_control, **{key: "f" * 64})


@pytest.mark.parametrize("damage", ["source", "source-version", "request", "review", "scope", "missing-path", "sorted-roles"])
def test_reviewed_definition_realization_replays_complete_current_sources_and_meaning_inputs(reviewed_definition_realization_control, damage):
    control = reviewed_definition_realization_control
    args, kwargs = deepcopy(control["args"]), deepcopy(control["kwargs"])
    inputs = kwargs["preparation_inputs"]
    unit = inputs["declaration"]["units"][2]
    key = unit["unit_id"]
    if damage == "source": inputs["source_inputs"][key]["raw_bytes"] += b" changed"
    elif damage == "source-version": unit["source_version"]["edition"] = "fictional-other-edition"
    elif damage == "request": inputs["relational_inputs"][key]["request_raw"] += b" "
    elif damage == "review": args[3][0]["interpretation"]["rationale"] += " unsigned change"
    elif damage == "scope": inputs["declaration"]["interpretation_id"] += "-another-scope"
    elif damage == "missing-path": inputs["declaration"]["definition_uses"][1]["target_typed_paths"].pop()
    elif damage == "sorted-roles":
        report = inputs["relational_inputs"][key]["report"]
        row = next(x for x in report["argument_roles"] if x["symbol"] == "InspectsRegisterAt")
        assert row["roles"] != sorted(row["roles"])
        row["roles"] = sorted(row["roles"])
    with pytest.raises((ValueError, TypeError)):
        reviewed_definition_realization_validate(control, control["realization"], args=args, kwargs=kwargs)


@pytest.mark.parametrize("damage", ["body", "missing-occurrence", "occurrence-argument", "role", "sort", "namespace",
    "source-equality", "paired-emitted-variable", "original-child", "active-lake", "saved-lake", "authority"])
def test_reviewed_definition_realization_resealed_source_and_binding_mutants_refuse(reviewed_definition_realization_control, damage):
    control = reviewed_definition_realization_control
    offered = control["realization"]
    manifest, files = offered.to_dict(), dict(offered.files)
    selection = manifest["selection"]
    instance = next(x for x in manifest["expected_modules"] if ".Instance" in x and x not in manifest["upstream_manifest"]["expected_modules"])
    module_path = instance.replace(".", "/") + ".lean"
    if damage == "body": selection["body_typed_node"]["symbol"] = "CoveredOfficer"
    elif damage == "missing-occurrence": selection["occurrences"].pop()
    elif damage == "occurrence-argument": selection["occurrences"][1]["argument"]["symbol"] = "supervisor"
    elif damage == "role": selection["head_roles"] = ["supervisor"]
    elif damage == "sort": selection["occurrences"][2]["argument"]["sort"]["name"] = "EventFrame"
    elif damage == "namespace": manifest["units"][2]["signature_namespace_sha256"] = manifest["units"][0]["signature_namespace_sha256"]
    elif damage == "source-equality": files[module_path] = files[module_path].replace("theorem occurrence_0_source_exact", "theorem unrelated_head_source_exact", 1)
    elif damage == "paired-emitted-variable":
        # Change both a standalone emitted atom and its RHS witness. Full source
        # regeneration must reject even an internally consistent replacement.
        whole = files[module_path]
        start = whole.index("def occurrenceAst1 ")
        end = whole.index("def occurrenceAst2 ")
        selected = whole[start:end]
        assert '\"officer\", .object' in selected
        assert 'bodyAt base atoms bound0 t' in selected
        paired = selected.replace('\"officer\", .object', '\"supervisor\", .object', 1).replace(
            'bodyAt base atoms bound0 t', 'bodyAt base atoms bound1 t', 1)
        assert paired != selected
        files[module_path] = whole[:start] + paired + whole[end:]
    elif damage == "original-child":
        original = manifest["upstream_manifest"]["units"][1]["instance_module"].replace(".", "/") + ".lean"
        files[original] += "\n-- changed original normative witness\n"
    elif damage == "active-lake": files["lakefile.toml"] = "name = \"wrong\"\n"
    elif damage == "saved-lake": files["definition-realization-original-lakefile.txt"] += "\n"
    elif damage == "authority": manifest["authority"]["proof"] = True
    forged = reviewed_preservation_reseal_fixture_v2(offered, manifest, files)
    with pytest.raises((ValueError, TypeError)):
        reviewed_definition_realization_validate(control, forged)


def reviewed_definition_realization_fresh_case(control, change):
    """Fresh signatures on deliberately fictional AST changes, never real law."""
    mh, owner = control["mixed_helper"], control["owner"]
    case = mh.cloned(control["case"])
    unit = case["declaration"]["units"][2 if change == "opaque-head" else 0]
    if change == "opaque-head":
        request = json.loads(case["relational_inputs"][unit["unit_id"]]["request_raw"])
        parent = request["expression"]["root"]
        for _ in range(3): parent = parent["arguments"][0]
        original_body = deepcopy(parent["arguments"][0])
        wrapper = deepcopy(original_body["arguments"][1])
        wrapper["node_id"] = "fixture:new:opaque-head-wrapper"
        wrapper["extension"]["node_id"] = "fixture:new:opaque-head-wrapper:ext"
        wrapper["extension"]["children"] = [original_body]
        parent["arguments"][0] = wrapper
        reviewed_preservation_refresh_expression_v2(request)
    else:
        rf = mh.relational_fixture
        builder = rf.Builder()
        head = builder.atom("CoveredOfficer", "officer")
        body_symbol = ("InspectsRegisterAt" if change == "body-arity-collision" else
            "event" if change == "body-binder-collision" else "AppointedByBoard")
        if change == "recursive-body":
            body = builder.binary("and", builder.atom("AppointedByBoard", "officer"), builder.atom("CoveredOfficer", "officer"))
        elif change == "quantified-body":
            body = builder.quantify(builder.atom("AppointedByBoard", "inner"), [("inner", "forall")])
        elif change == "negated-body":
            body = rf.ast.mk_not(builder.nid(), builder.atom("AppointedByBoard", "officer"))
        elif change == "repeated-body":
            body = builder.binary("and", builder.atom(body_symbol, "officer"), builder.atom(body_symbol, "officer"))
        elif change in ("body-arity-collision", "body-binder-collision"):
            body = builder.atom(body_symbol, "officer")
        else: raise AssertionError("unknown fictional body mutation")
        request = rf.request_for(builder, builder.binary("iff", head, body),
            [("CoveredOfficer", ("officer",)), (body_symbol, ("officer",))], [("officer", "forall")])
    raw = canonical_dag_json_bytes(request)
    mixed = unit["relational_profile"] == mh.relational.MIXED_PROFILE
    report = (mh.relational.prepare_mixed_relational_norm_v1 if mixed else mh.relational.prepare_relational_norm_v1)(
        raw, expected_request_sha256=sha(raw))
    report_pin = (mh.relational.mixed_relational_norm_report_sha256 if mixed else mh.relational.relational_norm_report_sha256)(report)
    unit["relational_request_sha256"] = sha(raw)
    occurrence = unit["occurrence"]
    unit["coverage"] = [{"typed_path": row["typed_path"], **{k: occurrence[k] for k in
        ("start_char", "end_char", "start_utf8", "end_utf8")}} for row in report["structural_mapping"]]
    case["relational_inputs"][unit["unit_id"]] = {"request_raw": raw, "report": report, "expected_report_sha256": report_pin}
    if mixed:
        targets = []
        for mapping in report["structural_mapping"]:
            node = report["typed_expression"]
            for token in mapping["typed_path"].split("/")[1:]:
                node = node[int(token)] if type(node) is list else node[token]
            if type(node) is dict and node.get("kind") == "predicate" and node.get("symbol") == "CoveredOfficer":
                targets.append(mapping["typed_path"])
        case["declaration"]["definition_uses"][1]["target_typed_paths"] = targets
    case["preparation"] = mh.prepare(owner, case)
    mh.refresh_signed_reviews(case, owner)
    mh.assert_signatures_valid(case)
    args, kwargs = mh.fixture.reviewed_assessment_arguments_v2(owner, case)
    admission = owner.assess_reviewed_norm_admission_v3(*args, **kwargs)
    assert admission["semantic_use_eligible"] and admission["fixture_only"] and admission["blockers"] == []
    from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graph_owner
    admission_sha = owner.norm_content_adjudication_sha256(admission)
    graph = graph_owner.build_reviewed_norm_graph_v3(admission, *args, expected_admission_sha256=admission_sha, **kwargs)
    changed = dict(control, case=case, args=args, kwargs=kwargs, admission=admission, graph=graph,
        admission_sha=admission_sha, graph_sha=graph_owner.norm_definition_graph_sha256(graph))
    changed["preparation"] = reviewed_preservation_prepare_fixture_v3(changed)
    return changed


@pytest.mark.parametrize("change", ["recursive-body", "quantified-body", "opaque-head"])
def test_reviewed_definition_realization_refuses_fresh_reviewed_unsupported_bodies_or_modal_occurrences(reviewed_definition_realization_control, change):
    changed = reviewed_definition_realization_fresh_case(reviewed_definition_realization_control, change)
    # Unsupported realization must be tested after genuine full V3 admission,
    # graph and child preservation, never with a forged accepted report.
    assert changed["admission"]["semantic_use_eligible"] and changed["admission"]["fixture_only"]
    with pytest.raises(ValueError, match="nonrecursive|definition bodies|opaque modalities"):
        reviewed_definition_realization_prepare(changed)


def test_reviewed_definition_realization_fresh_boolean_body_has_new_exact_source_identity(reviewed_definition_realization_control):
    baseline = reviewed_definition_realization_control
    changed = reviewed_definition_realization_fresh_case(baseline, "negated-body")
    current = reviewed_definition_realization_prepare(changed)
    assert current.to_dict()["selection"]["body_typed_node"]["kind"] == "not"
    assert current.to_dict()["selection"]["body_typed_sha256"] != baseline["realization"].to_dict()["selection"]["body_typed_sha256"]
    assert current != baseline["realization"]
    assert reviewed_definition_realization_validate(changed, current) == current
    with pytest.raises(ValueError):
        reviewed_definition_realization_validate(changed, baseline["realization"])


@pytest.mark.parametrize("damage", ["input", "callback", "policy"])
def test_reviewed_definition_realization_late_callback_boundaries_refuse(reviewed_definition_realization_control, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preservation
    control = reviewed_definition_realization_control
    kwargs = deepcopy(control["kwargs"])
    unit = control["case"]["declaration"]["units"][1]["unit_id"]
    original = shared._reviewed_definition_realization_lean
    def mutate_after_render(*args, **options):
        result = original(*args, **options)
        if damage == "input": kwargs["preparation_inputs"]["source_inputs"][unit]["raw_bytes"] += b" late change"
        elif damage == "callback": monkeypatch.setattr(preservation, "_relational_source_syntax", lambda *a, **k: "altered")
        else: monkeypatch.setattr(preservation, "AUTHORITY", {**preservation.AUTHORITY, "proof": True})
        return result
    monkeypatch.setattr(shared, "_reviewed_definition_realization_lean", mutate_after_render)
    with pytest.raises(ValueError, match="changed during operation|cannot confer authority"):
        reviewed_definition_realization_prepare(control, kwargs=kwargs)


@pytest.mark.parametrize("profile", ["unreviewed-hypothesis", "reviewed-multi-unit-mixed-relational-preservation/v3"])
def test_reviewed_definition_realization_explicit_profile_does_not_fall_back(reviewed_definition_realization_control, monkeypatch, profile):
    control = reviewed_definition_realization_control
    monkeypatch.setattr(shared, "REVIEWED_DEFINITION_REALIZATION_PROFILE", profile)
    with pytest.raises(ValueError, match="fixed explicit"):
        reviewed_definition_realization_prepare(control)
    assert reviewed_preservation_validate_fixture_v3(control, control["preparation"]) == control["preparation"]



def test_reviewed_definition_realization_late_actual_result_serialization_cannot_launder_source_mutation(
        reviewed_definition_realization_control, monkeypatch):
    control = reviewed_definition_realization_control
    kwargs = deepcopy(control["kwargs"])
    unit = control["case"]["declaration"]["units"][1]["unit_id"]
    source = kwargs["preparation_inputs"]["source_inputs"][unit]
    before = source["raw_bytes"]
    actual_project = shared._reviewed_definition_realization_project
    actual_offered = shared._reviewed_preservation_offered
    actual_policy = shared._reviewed_definition_realization_policy
    operation_code = shared._reviewed_definition_realization_operation.__code__
    observed = {"result": None, "seen_result_read": False,
                "after_checked_boundary": False, "mutated": False}

    def capture_actual_project(*args, **options):
        result = actual_project(*args, **options)
        observed["result"] = result
        return result

    def observe_actual_policy():
        actual_policy()
        observed["after_checked_boundary"] = True

    def serialize_actual_result(value):
        # Return the real current envelope; do not forge an accepted artifact.
        envelope = actual_offered(value)
        if value is observed["result"]:
            eligible = (observed["seen_result_read"] and observed["after_checked_boundary"]
                        and sys._getframe(1).f_code is operation_code)
            observed["seen_result_read"] = True
            observed["after_checked_boundary"] = False
            if eligible and not observed["mutated"]:
                source["raw_bytes"] += b" changed after genuine result serialization"
                observed["mutated"] = True
        return envelope

    monkeypatch.setattr(shared, "_reviewed_definition_realization_project", capture_actual_project)
    monkeypatch.setattr(shared, "_reviewed_definition_realization_policy", observe_actual_policy)
    monkeypatch.setattr(shared, "_reviewed_preservation_offered", serialize_actual_result)
    try:
        result = reviewed_definition_realization_prepare(control, kwargs=kwargs)
    except ValueError as error:
        assert observed["result"] is not None
        assert observed["mutated"] is True
        assert "changed during operation" in str(error)
    else:
        # A closed-buffer implementation may eliminate the unsafe callback.
        # If it remains, its mutation must never pass the final input fence.
        assert observed["result"] is not None
        assert observed["mutated"] is False, "late actual-result callback mutation escaped the final source fence"
        assert source["raw_bytes"] == before
        assert result == control["realization"]



def test_reviewed_definition_realization_reused_policy_callback_cannot_hide_bound_change(
        reviewed_definition_realization_control, monkeypatch):
    control = reviewed_definition_realization_control
    original = shared._reviewed_definition_realization_lean
    observed = {"rendered": False}
    assert shared.MAX_REVIEWED_PRESERVATION_FILES == 78
    def render_then_replace_reused_policy(*args, **options):
        result = original(*args, **options)
        observed["rendered"] = True
        # Only this fixture changes: a replaced reused guard must not hide a
        # limit mutation. No persistent policy, resource or budget is changed.
        monkeypatch.setattr(shared, "_reviewed_mixed_preservation_policy", lambda: None)
        monkeypatch.setattr(shared, "MAX_REVIEWED_PRESERVATION_FILES", 79)
        return result
    monkeypatch.setattr(shared, "_reviewed_definition_realization_lean", render_then_replace_reused_policy)
    with pytest.raises(ValueError, match="changed during operation"):
        reviewed_definition_realization_prepare(control)
    assert observed["rendered"] is True


@pytest.mark.parametrize("prefix,namespace,type_name", [
    ("object", "LegalRelationalAstPreservation", "RoleFormula"),
    ("mixed", "LegalMixedRelationalAstPreservation", "MixedFormula"),
])
def test_reviewed_definition_realization_selector_branches_follow_original_inductive_order(
        reviewed_definition_realization_control, prefix, namespace, type_name):
    """Check the adapter against original child types, without claiming Lean proof.

    The independent unchanged child inductive defines constructor/field order.
    This guards recursor argument drift, including unselected logical children;
    the separate actual Native check must still inspect every theorem's axioms.
    """
    prepared = reviewed_definition_realization_control["realization"]
    manifest, files = prepared.to_dict(), dict(prepared.files)
    original = files[namespace.replace(".", "/") + "/Semantics.lean"]
    header = original.split("inductive " + type_name + " where\n", 1)[1].split("\ndef ", 1)[0]
    constructors = []
    for line in header.splitlines():
        if not line.startswith("  | "):
            continue
        fields = []
        for names, field_type in re.findall(r"\(([^:()]+) : ([^()]+)\)", line):
            fields.extend((name, field_type) for name in names.split())
        constructors.append((line.split()[1], fields))
    assert len(constructors) == (9 if prefix == "object" else 10)
    model = manifest["expected_modules"][-2]
    emitted = files[model.replace(".", "/") + ".lean"]
    selector = emitted.split("def " + prefix + "FormulaChild ", 1)[1].split("\nnoncomputable def " + prefix + "FormulaAt ", 1)[0]
    branches = [line.strip() for line in selector.splitlines() if line.startswith("    (fun ")]
    assert len(branches) == len(constructors)
    for (constructor, fields), branch in zip(constructors, branches, strict=True):
        formals, _, result = branch.removeprefix("(fun ").partition(" => ")
        children = [name for name, field_type in fields if field_type == type_name]
        expected = [name if field_type == type_name else "_" for name, field_type in fields]
        assert formals.split() == expected, constructor
        if not children:
            assert result == "none)", constructor
        else:
            # The independent source constructor's left-to-right logical child
            # sequence is the index0/index1 sequence. All later indices refuse.
            assert re.findall(r"\(some ([A-Za-z]+)\)", result) == children, constructor
            assert result.count("Nat.casesOn") == len(children), constructor
            assert result.endswith("(fun _ => none)" + ")" * len(children)), constructor


# Source-use identity is explicit custody metadata on complete fictional inputs.
# This reproduction executes no compiler and grants no legal or proof authority.
def test_reviewed_definition_realization_accepts_explicit_source_use_identity_after_healthy_v3(
        reviewed_definition_realization_control):
    control = reviewed_definition_realization_control
    # The default realization route is independently healthy before the new
    # source-use domain is requested. No missing-symbol probe supplies the RED.
    assert reviewed_definition_realization_validate(control, control["realization"]) == control["realization"]
    assert len(control["realization"].to_dict()["preservation_obligations"]) == 26
    preservation = reviewed_source_use_prepare_fixture(control, 3)
    assert reviewed_source_use_validate_fixture(control, 3, preservation) == preservation
    reviewed_source_use_assert_bindings(preservation)
    upstream = preservation.to_dict()
    assert upstream["profile"] == shared.REVIEWED_MIXED_SOURCE_USE_PRESERVATION_PROFILE
    assert upstream["instance_identity_profile"] == "reviewed-source-use/v1"
    assert len(upstream["units"]) == len({row["instance_module"] for row in upstream["units"]}) == 3
    assert len(set(upstream["preservation_obligations"])) == 15
    assert control["admission"]["fixture_only"] is True
    assert control["admission"]["semantic_use_eligible"] is True
    assert control["admission"]["blockers"] == []
    current_inputs = control["owner"].norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1]
    preservation_pin = shared.reviewed_preservation_corpus_sha256(preservation)
    # A saved upstream manifest cannot silently opt the default caller in.
    with pytest.raises(ValueError):
        reviewed_definition_realization_prepare(control, preservation=preservation,
            expected_preservation_sha256=preservation_pin)

    realized = reviewed_definition_realization_prepare(control, preservation=preservation,
        expected_preservation_sha256=preservation_pin,
        instance_identity_profile="reviewed-source-use/v1")

    manifest, files = realized.to_dict(), dict(realized.files)
    assert manifest["schema"] == shared.REVIEWED_DEFINITION_REALIZATION_SCHEMA
    assert manifest["profile"] == shared.REVIEWED_DEFINITION_REALIZATION_PROFILE + "+reviewed-source-use/v1"
    assert manifest["instance_identity_profile"] == "reviewed-source-use/v1"
    assert manifest["upstream_manifest"] == upstream and manifest["units"] == upstream["units"]
    assert manifest["reviewed_preservation_sha256"] == preservation_pin
    assert manifest["preservation_obligations"][:15] == upstream["preservation_obligations"]
    assert len(manifest["realization_obligations"]) == 11
    assert len(manifest["preservation_obligations"]) == len(set(manifest["preservation_obligations"])) == 26
    for name, body in preservation.files:
        retained = "definition-realization-original-lakefile.txt" if name == "lakefile.toml" else name
        assert files[retained] == body
    assert len(files) == 39 and len(manifest["expected_modules"]) == 10
    assert manifest["preparation_only"] is True
    assert manifest["proof_status"] == manifest["lean_compilation_status"] == "not_executed"
    assert manifest["support_profile"]["cross_unit_definition_application_proved"] is False
    assert not any(manifest["authority"].values())
    assert manifest["semantic_use_eligible"] is False
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert shared.validate_reviewed_definition_realization_corpus_v1(realized, preservation,
        control["graph"], control["admission"], *control["args"],
        expected_realization_sha256=shared.reviewed_preservation_corpus_sha256(realized),
        expected_preservation_sha256=preservation_pin,
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, instance_identity_profile="reviewed-source-use/v1", **control["kwargs"]) == realized
    assert control["owner"].norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1] == current_inputs


# Selected realization remains a constructed fictional interpretation. Explicit
# source-use identity separates technical domains; it supplies no legal review.
@pytest.fixture(scope="module")
def reviewed_definition_realization_source_use_control_v1(reviewed_preservation_control_v3):
    control = dict(reviewed_preservation_control_v3)
    control["preparation"] = reviewed_source_use_prepare_fixture(control, 3)
    assert reviewed_source_use_validate_fixture(control, 3, control["preparation"]) == control["preparation"]
    reviewed_source_use_assert_bindings(control["preparation"])
    control["realization"] = reviewed_definition_realization_prepare(control,
        instance_identity_profile="reviewed-source-use/v1")
    manifest = control["realization"].to_dict()
    assert manifest["selection"]["instance_identity_profile"] == "reviewed-source-use/v1"
    assert manifest["selection"]["source_use_bindings"] == [
        {"unit_id": unit["unit_id"], "source_use_binding": unit["source_use_binding"],
         "source_use_binding_sha256": unit["source_use_binding_sha256"]} for unit in manifest["units"]]
    return control


def reviewed_definition_realization_source_use_validate_v1(control, offered=None, *, args=None, kwargs=None, **changes):
    offered = control["realization"] if offered is None else offered
    options = dict(expected_realization_sha256=shared.reviewed_preservation_corpus_sha256(offered),
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, instance_identity_profile="reviewed-source-use/v1")
    options.update(changes)
    return shared.validate_reviewed_definition_realization_corpus_v1(offered, control["preparation"],
        control["graph"], control["admission"], *(control["args"] if args is None else args),
        **dict(control["kwargs"] if kwargs is None else kwargs), **options)


@pytest.mark.parametrize("selector", [False, True, 0, "", "reviewed-source-use/v2", {}, []])
def test_reviewed_definition_realization_source_use_invalid_selector_refuses_before_owners(monkeypatch, selector):
    monkeypatch.setattr(shared, "_reviewed_mixed_preservation_owners",
        lambda: pytest.fail("invalid realization selector reached lazy replay owners"))
    with pytest.raises(ValueError, match="explicit reviewed source-use identity profile"):
        shared.prepare_reviewed_definition_realization_corpus_v1(None, {}, {},
            expected_preservation_sha256="1" * 64, expected_graph_sha256="2" * 64,
            expected_admission_sha256="3" * 64, toolchain=TOOLCHAIN,
            instance_identity_profile=selector)


@pytest.mark.parametrize("damage", ["selector", "profile", "upstream-selector", "selection-selector", "selection-binding"])
def test_reviewed_definition_realization_source_use_resealed_mode_swap_refuses(
        reviewed_definition_realization_source_use_control_v1, damage):
    control = reviewed_definition_realization_source_use_control_v1
    offered = control["realization"]
    assert reviewed_definition_realization_source_use_validate_v1(control) == offered
    manifest = offered.to_dict()
    if damage == "selector": manifest["instance_identity_profile"] = "reviewed-source-use/v2"
    elif damage == "profile": manifest["profile"] = shared.REVIEWED_DEFINITION_REALIZATION_PROFILE
    elif damage == "upstream-selector": manifest["upstream_manifest"].pop("instance_identity_profile")
    elif damage == "selection-selector": manifest["selection"]["instance_identity_profile"] = "reviewed-source-use/v2"
    else:
        row = manifest["selection"]["source_use_bindings"][1]
        row["source_use_binding"] = deepcopy(manifest["units"][2]["source_use_binding"])
        row["source_use_binding_sha256"] = sha(canonical_dag_json_bytes(row["source_use_binding"]))
    forged = reviewed_preservation_reseal_fixture_v2(offered, manifest, dict(offered.files))
    # The offered pin is recomputed; refusal must bind the selected domain and
    # current original children rather than depend on an obsolete envelope pin.
    with pytest.raises(ValueError):
        reviewed_definition_realization_source_use_validate_v1(control, forged)
    with pytest.raises(ValueError):
        reviewed_definition_realization_source_use_validate_v1(control, instance_identity_profile=None)


@pytest.mark.parametrize("damage", ["source", "revoked", "binding"])
def test_reviewed_definition_realization_source_use_replays_current_source_reviews_and_closed_binding(
        reviewed_definition_realization_source_use_control_v1, damage):
    control = reviewed_definition_realization_source_use_control_v1
    assert reviewed_definition_realization_source_use_validate_v1(control) == control["realization"]
    args, kwargs = deepcopy(control["args"]), deepcopy(control["kwargs"])
    offered = control["realization"]
    if damage == "source":
        unit = control["case"]["declaration"]["units"][2]["unit_id"]
        kwargs["preparation_inputs"]["source_inputs"][unit]["raw_bytes"] += b" changed current source"
    elif damage == "revoked":
        helper = control["mixed_helper"]
        case = helper.cloned(control["case"])
        case["registry"]["keys"][0]["revoked_at_utc"] = kwargs["at_time_utc"]
        helper.refresh_signed_reviews(case, control["owner"])
        helper.assert_signatures_valid(case)
        args, kwargs = helper.fixture.reviewed_assessment_arguments_v2(control["owner"], case)
        current = control["owner"].assess_reviewed_norm_admission_v3(*args, **kwargs)
        assert current["semantic_use_eligible"] is False
        assert "key_revoked" in json.dumps(current)
    else:
        manifest = offered.to_dict()
        row = manifest["units"][1]
        row["source_use_binding"] = deepcopy(manifest["units"][2]["source_use_binding"])
        row["source_use_binding_sha256"] = sha(canonical_dag_json_bytes(row["source_use_binding"]))
        offered = reviewed_preservation_reseal_fixture_v2(offered, manifest, dict(offered.files))
    with pytest.raises((ValueError, TypeError)):
        reviewed_definition_realization_source_use_validate_v1(control, offered, args=args, kwargs=kwargs)


# A whole-norm application is a separate conditional engineering obligation.
# Existing source/review fixtures remain fictional; preparation executes no Lean.
def reviewed_definition_application_RED_at_v1(tree, path):
    selected = tree
    for token in path.split("/")[1:]:
        selected = selected[int(token)] if type(selected) is list else selected[token]
    return selected


def reviewed_definition_application_RED_without_node_ids_v1(value):
    if type(value) is dict:
        return {key: reviewed_definition_application_RED_without_node_ids_v1(item)
            for key, item in value.items() if key != "node_id"}
    if type(value) is list:
        return [reviewed_definition_application_RED_without_node_ids_v1(item) for item in value]
    return value


@pytest.mark.parametrize("instance_identity_profile", [None, "reviewed-source-use/v1"], ids=["default", "source-use"])
def test_reviewed_definition_application_whole_norm_requires_both_exact_source_norm_expansions(
        request, instance_identity_profile):
    fixture_name = ("reviewed_definition_realization_control" if instance_identity_profile is None else
        "reviewed_definition_realization_source_use_control_v1")
    control = request.getfixturevalue(fixture_name)
    preservation, legacy = control["preparation"], control["realization"]
    upstream, previous = preservation.to_dict(), legacy.to_dict()
    mode = {} if instance_identity_profile is None else {"instance_identity_profile": instance_identity_profile}
    # Current complete admission, V3 source/graph and old realization must all
    # be healthy before the feature probe. Missing methods/imports cannot count.
    assert control["owner"].assess_reviewed_norm_admission_v3(*control["args"], **control["kwargs"]) == control["admission"]
    assert control["admission"]["fixture_only"] is control["admission"]["semantic_use_eligible"] is True
    assert control["admission"]["blockers"] == []
    if instance_identity_profile is None:
        assert reviewed_preservation_validate_fixture_v3(control, preservation) == preservation
        assert reviewed_definition_realization_validate(control, legacy) == legacy
        assert "instance_identity_profile" not in previous
    else:
        assert reviewed_source_use_validate_fixture(control, 3, preservation) == preservation
        reviewed_source_use_assert_bindings(preservation)
        assert reviewed_definition_realization_source_use_validate_v1(control, legacy) == legacy
        assert previous["instance_identity_profile"] == instance_identity_profile
    assert len(upstream["units"]) == 3 and len({u["instance_module"] for u in upstream["units"]}) == 3
    assert len(upstream["preservation_obligations"]) == 15
    assert len(previous["preservation_obligations"]) == 26
    assert len(previous["realization_obligations"]) == 11
    assert "definition_application_profile" not in previous
    assert previous["support_profile"]["cross_unit_definition_application_proved"] is False
    assert previous["selection"]["body_typed_node"]["symbol"] == "AppointedByBoard"
    snapshot = control["owner"].norm._snapshot({"graph": control["graph"], "admission": control["admission"],
        "args": list(control["args"]), "kwargs": control["kwargs"]})[1]

    # This explicit opt-in is intentionally unsupported by the published
    # baseline. It must become a complete source-bound expansion, not a new
    # desired-Iff premise or another constructed-model/head-only receipt.
    application_profile = "whole-norm-definition-expansion/v1"
    offered = reviewed_definition_realization_prepare(control,
        definition_application_profile=application_profile, **mode)

    from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression
    manifest, files = offered.to_dict(), dict(offered.files)
    assert manifest["definition_application_profile"] == application_profile
    assert manifest["selection"] == previous["selection"]
    assert manifest["units"] == upstream["units"] and manifest["upstream_manifest"] == upstream
    assert manifest["reviewed_preservation_sha256"] == shared.reviewed_preservation_corpus_sha256(preservation)
    assert len(files) == 39 and len(manifest["expected_modules"]) == 10
    assert len(manifest["preservation_obligations"]) == len(set(manifest["preservation_obligations"])) == 30
    assert manifest["preservation_obligations"][:15] == upstream["preservation_obligations"]
    assert len(manifest["realization_obligations"]) == 15
    additions = manifest["definition_application_obligations"]
    assert len(additions) == len(set(additions)) == 4
    assert manifest["preservation_obligations"][-4:] == manifest["realization_obligations"][-4:] == additions
    for name, body in preservation.files:
        retained = "definition-realization-original-lakefile.txt" if name == "lakefile.toml" else name
        assert files[retained] == body

    admitted = {row["unit_id"]: row for row in control["admission"]["units"]}
    definition = next(row for row in upstream["units"] if row["kind"] == "definition")
    norms = [row for row in upstream["units"] if row["kind"] == "norm"]
    assert len(norms) == 2
    original_definition = admitted[definition["unit_id"]]["canonical_ir"]["typed_expression"]
    assert previous["selection"]["definition_source_occurrence_cid"] == definition["source_occurrence_cid"]
    applications = manifest["definition_applications"]
    assert [row["unit_id"] for row in applications] == [row["unit_id"] for row in norms]
    assert len(applications) == 2
    for unit, application in zip(norms, applications, strict=True):
        assert application["typed_expression_transport"] == "canonical-dag-json-text/v1"
        for kind in ("definition", "original", "expanded"):
            text = application[kind + "_typed_expression"]
            assert type(text) is str
            assert canonical_dag_json_bytes(json.loads(text)) == text.encode("utf-8")
            assert shared._reviewed_definition_application_expression(application, kind) == json.loads(text)
            assert application[kind + "_typed_expression_sha256"] == sha(text.encode("utf-8"))
        ir = admitted[unit["unit_id"]]["canonical_ir"]
        uses = [use for use in control["graph"]["definition_use_records"]
            if use["use_unit_id"] == unit["unit_id"] and use["definition_unit_id"] == definition["unit_id"]]
        assert len(uses) == 1
        use = uses[0]
        paths = [row["typed_path"] for row in previous["selection"]["occurrences"] if row["unit_id"] == unit["unit_id"]]
        assert application["definition_unit_id"] == definition["unit_id"]
        assert application["definition_use_record_cid"] == use["record_cid"]
        assert application["scope_record_cid"] == definition["scope_record_cid"] == unit["scope_record_cid"]
        assert application["interpretation_record_cid"] == unit["interpretation_record_cid"]
        assert json.loads(application["definition_typed_expression"]) == original_definition
        assert application["definition_typed_expression_sha256"] == sha(canonical_dag_json_bytes(original_definition))
        assert json.loads(application["original_typed_expression"]) == ir["typed_expression"]
        assert application["original_typed_expression_sha256"] == sha(canonical_dag_json_bytes(ir["typed_expression"]))
        assert application["original_argument_roles"] == ir["argument_roles"]
        assert application["target_typed_paths"] == paths and len(application["replacement_records"]) == len(paths)
        expanded = json.loads(application["expanded_typed_expression"])
        assert application["expanded_typed_expression_sha256"] == sha(canonical_dag_json_bytes(expanded))
        assert expanded["content_digest"] != ir["typed_expression"]["content_digest"]
        assert TypedExpression.from_dict(expanded).to_dict() == expanded
        # The existing fixed fixture's SOURCE body is the single AppointedByBoard
        # atom. This explicit expectation is not a generic substitution engine.
        expected = deepcopy(ir["typed_expression"])
        for path in paths:
            atom = reviewed_definition_application_RED_at_v1(expected, path)
            assert atom["kind"] == "predicate" and atom["symbol"] == "CoveredOfficer"
            atom["symbol"] = "AppointedByBoard"
        assert reviewed_definition_application_RED_without_node_ids_v1(expanded["root"]) == \
            reviewed_definition_application_RED_without_node_ids_v1(expected["root"])
        assert expanded["root"] != ir["typed_expression"]["root"]
        assert application["expanded_argument_roles"]
        assert {key: value for key, value in expanded.items() if key not in {"root", "signature", "content_digest"}} == \
            {key: value for key, value in ir["typed_expression"].items() if key not in {"root", "signature", "content_digest"}}

    whole = [entry for entry in manifest["theorem_bindings"] if entry["binding"]["kind"] == "whole_norm_definition_expansion"]
    exact = [entry for entry in manifest["theorem_bindings"] if entry["binding"]["kind"] == "whole_norm_expansion_source_exact"]
    assert len(whole) == len(exact) == 2
    assert {entry["binding"]["unit_id"] for entry in whole} == {row["unit_id"] for row in norms}
    assert {entry["binding"]["unit_id"] for entry in exact} == {row["unit_id"] for row in norms}
    assert {entry["theorem"] for entry in whole + exact} == set(additions)
    for entry in whole:
        binding = entry["binding"]
        assert binding["premise_kind"] == "independently_denoted_source_definition"
        assert binding["desired_equivalence_hypothesis"] is False
        unit = next(row for row in norms if row["unit_id"] == binding["unit_id"])
        if unit["relational_profile"] == "authored-many-sorted-relational-deontic/v1":
            assert binding["atom_binding"] == "canonical_Object_restriction_of_original_mixed_atoms"
    assert manifest["preparation_only"] is True
    assert manifest["proof_status"] == manifest["lean_compilation_status"] == "not_executed"
    assert manifest["support_profile"]["cross_unit_definition_application_proved"] is False
    assert not any(manifest["authority"].values()) and manifest["semantic_use_eligible"] is False
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert shared.validate_reviewed_definition_realization_corpus_v1(offered, preservation,
        control["graph"], control["admission"], *control["args"],
        expected_realization_sha256=shared.reviewed_preservation_corpus_sha256(offered),
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(preservation),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, definition_application_profile=application_profile, **mode, **control["kwargs"]) == offered
    assert control["owner"].norm._snapshot({"graph": control["graph"], "admission": control["admission"],
        "args": list(control["args"]), "kwargs": control["kwargs"]})[1] == snapshot
    assert len(control["realization"].to_dict()["preservation_obligations"]) == 26


def reviewed_definition_application_validate_v1(control, offered, **changes):
    options = dict(expected_realization_sha256=shared.reviewed_preservation_corpus_sha256(offered),
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, definition_application_profile="whole-norm-definition-expansion/v1")
    options.update(changes)
    return shared.validate_reviewed_definition_realization_corpus_v1(offered, control["preparation"],
        control["graph"], control["admission"], *control["args"], **options, **control["kwargs"])


@pytest.fixture(scope="module")
def reviewed_definition_application_control_v1(reviewed_definition_realization_control):
    control = reviewed_definition_realization_control
    offered = reviewed_definition_realization_prepare(control,
        definition_application_profile="whole-norm-definition-expansion/v1")
    assert reviewed_definition_application_validate_v1(control, offered) == offered
    return control, offered


def reviewed_definition_application_node_ids_v1(value):
    # Inspect JSON identities only; this helper implements no expansion semantics.
    if type(value) is dict:
        return ([value["node_id"]] if "node_id" in value else []) + [node_id
            for item in value.values() for node_id in reviewed_definition_application_node_ids_v1(item)]
    if type(value) is list:
        return [node_id for item in value for node_id in reviewed_definition_application_node_ids_v1(item)]
    return []


@pytest.mark.parametrize("change", ["negated-body", "repeated-body"])
def test_whole_norm_definition_application_rebinds_every_boolean_body_without_capture(
        reviewed_definition_realization_control, change):
    changed = reviewed_definition_realization_fresh_case(reviewed_definition_realization_control, change)
    old = reviewed_definition_realization_prepare(changed)
    assert len(old.to_dict()["preservation_obligations"]) == 26
    offered = reviewed_definition_realization_prepare(changed,
        definition_application_profile="whole-norm-definition-expansion/v1")
    assert reviewed_definition_application_validate_v1(changed, offered) == offered
    manifest = offered.to_dict()
    assert len(manifest["preservation_obligations"]) == 30
    definition_ids = set(reviewed_definition_application_node_ids_v1(manifest["selection"]["body_typed_node"]))
    replacements_seen = set()
    for application in manifest["definition_applications"]:
        original_expression = json.loads(application["original_typed_expression"])
        expanded_expression = json.loads(application["expanded_typed_expression"])
        original = original_expression["root"]
        expanded = expanded_expression["root"]
        # Hide exactly the selected replacement subtrees, then compare every
        # remaining original node, ID, binder and opaque modal payload verbatim.
        before_context = deepcopy(original_expression)
        after_context = deepcopy(expanded_expression)
        for path in application["target_typed_paths"]:
            for context in (before_context, after_context):
                target = reviewed_definition_application_RED_at_v1(context, path)
                target.clear()
                target["selected_replacement_subtree"] = True
        assert before_context["root"] == after_context["root"]
        original_ids = set(reviewed_definition_application_node_ids_v1(original))
        expanded_ids = reviewed_definition_application_node_ids_v1(expanded)
        assert len(expanded_ids) == len(set(expanded_ids))
        assert expanded["node_id"] == original["node_id"]
        for path in application["target_typed_paths"]:
            prior = reviewed_definition_application_RED_at_v1(original_expression, path)
            node = reviewed_definition_application_RED_at_v1(expanded_expression, path)
            assert prior["symbol"] == "CoveredOfficer"
            assert node["kind"] == ("not" if change == "negated-body" else "and")
            assert len(node["arguments"]) == (1 if change == "negated-body" else 2)
            for atom in node["arguments"]:
                assert atom["kind"] == "predicate" and atom["symbol"] == "AppointedByBoard"
                assert [argument["symbol"] for argument in atom["arguments"]] == [prior["arguments"][0]["symbol"]]
            inserted = reviewed_definition_application_node_ids_v1(node)
            assert len(inserted) == len(set(inserted))
            assert not (set(inserted) & (original_ids | definition_ids | replacements_seen))
            replacements_seen.update(inserted)
    assert len(manifest["definition_applications"]) == 2 and replacements_seen


@pytest.mark.parametrize("change", ["body-arity-collision", "body-binder-collision"])
def test_whole_norm_definition_application_refuses_cross_unit_signature_or_binder_collisions(
        reviewed_definition_realization_control, change):
    changed = reviewed_definition_realization_fresh_case(reviewed_definition_realization_control, change)
    # Both original V3 and constructed26 support the independently scoped donor.
    # The new cross-unit application must refuse incompatible target signatures.
    assert reviewed_preservation_validate_fixture_v3(changed, changed["preparation"]) == changed["preparation"]
    assert len(reviewed_definition_realization_prepare(changed).to_dict()["preservation_obligations"]) == 26
    with pytest.raises(ValueError, match="predicate|signature|role|binder|collision|arity"):
        reviewed_definition_realization_prepare(changed,
            definition_application_profile="whole-norm-definition-expansion/v1")


@pytest.mark.parametrize("change", ["recursive-body", "quantified-body", "opaque-head"])
def test_whole_norm_definition_application_retains_fresh_reviewed_unsupported_refusals(
        reviewed_definition_realization_control, change):
    changed = reviewed_definition_realization_fresh_case(reviewed_definition_realization_control, change)
    assert changed["admission"]["fixture_only"] and changed["admission"]["semantic_use_eligible"]
    with pytest.raises(ValueError, match="nonrecursive|definition bodies|opaque modalities"):
        reviewed_definition_realization_prepare(changed,
            definition_application_profile="whole-norm-definition-expansion/v1")


@pytest.mark.parametrize("damage", ["original-source", "expanded-source", "missing-norm", "use-cid", "source-premise", "profile", "non-record"])
def test_whole_norm_definition_application_rejects_resealed_witness_and_scope_substitution(
        reviewed_definition_application_control_v1, damage):
    from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression
    control, offered = reviewed_definition_application_control_v1
    manifest, files = offered.to_dict(), dict(offered.files)
    applications = manifest["definition_applications"]
    row = applications[0]
    if damage in ("original-source", "expanded-source"):
        key = "original_typed_expression" if damage == "original-source" else "expanded_typed_expression"
        expression = json.loads(row[key])
        path = row["target_typed_paths"][0]
        node = reviewed_definition_application_RED_at_v1(expression, path)
        assert node["kind"] == "predicate"
        if damage == "original-source":
            # Change meaning using another already declared compatible symbol;
            # preserve the original signature to isolate the full source witness.
            head = next(declared for declared in expression["signature"]["symbols"]
                if declared["name"] == node["symbol"])
            alternative = next(declared for declared in expression["signature"]["symbols"]
                if declared["name"] != head["name"] and declared["domain"] == head["domain"]
                and declared["range"] == head["range"])
            node["symbol"] = alternative["name"]
        else:
            node["symbol"] = "CoveredOfficer"
        expression.pop("content_digest")
        expression = TypedExpression.from_dict(expression).to_dict()
        row[key] = canonical_dag_json_bytes(expression).decode("utf-8")
        row[key + "_sha256"] = sha(canonical_dag_json_bytes(expression))
    elif damage == "missing-norm": applications.pop()
    elif damage == "non-record": applications[0] = None
    elif damage == "use-cid":
        assert applications[1]["definition_use_record_cid"] != row["definition_use_record_cid"]
        row["definition_use_record_cid"] = applications[1]["definition_use_record_cid"]
    elif damage == "source-premise":
        binding = next(entry["binding"] for entry in manifest["theorem_bindings"]
            if entry["binding"]["kind"] == "whole_norm_definition_expansion")
        binding["premise_kind"] = "caller_assumed_whole_norm_equivalence"
        binding["desired_equivalence_hypothesis"] = True
    elif damage == "profile": manifest.pop("definition_application_profile")
    forged = reviewed_preservation_reseal_fixture_v2(offered, manifest, files)
    with pytest.raises((ValueError, TypeError)):
        reviewed_definition_application_validate_v1(control, forged)


@pytest.mark.parametrize("profile", [True, "unknown", {}, " whole-norm-definition-expansion/v1"])
def test_whole_norm_definition_application_invalid_selectors_refuse_before_callbacks(
        reviewed_definition_realization_control, monkeypatch, profile):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid application selector reached operation callbacks")
    monkeypatch.setattr(shared, "_reviewed_definition_realization_callbacks", forbidden)
    with pytest.raises((ValueError, TypeError)):
        reviewed_definition_realization_prepare(reviewed_definition_realization_control,
            definition_application_profile=profile)


@pytest.mark.parametrize("damage", ["marker", "structured-value", "noncanonical", "duplicate-key",
    "nonfinite", "digest", "too-deep", "oversized", "invalid-ast", "key-bound", "integer-bound", "nul-string"])
def test_whole_norm_definition_application_refuses_invalid_lossless_expression_transport(
        reviewed_definition_application_control_v1, damage):
    control, offered = reviewed_definition_application_control_v1
    manifest, files = offered.to_dict(), dict(offered.files)
    row = manifest["definition_applications"][0]
    key = "original_typed_expression"
    raw = row[key]
    assert row["typed_expression_transport"] == "canonical-dag-json-text/v1"
    assert type(raw) is str and json.loads(raw)["root"]
    if damage == "marker": row["typed_expression_transport"] = "unreviewed-json/v0"
    elif damage == "structured-value": row[key] = json.loads(raw)
    elif damage == "noncanonical": row[key] = " " + raw
    elif damage == "duplicate-key":
        expression_id = json.loads(raw)["expression_id"]
        row[key] = '{"expression_id":' + json.dumps(expression_id) + ',' + raw[1:]
    elif damage == "nonfinite": row[key] = raw[:-1] + ',"untrusted_number":NaN}'
    elif damage == "digest": row[key + "_sha256"] = "0" * 64
    elif damage == "too-deep": row[key] = "[" * 145 + "0" + "]" * 145
    elif damage == "oversized": row[key] = " " * (contracts.MAX_RECORD_BYTES + 1)
    elif damage in ("key-bound", "integer-bound", "nul-string"):
        decoded = json.loads(raw)
        metadata = decoded.setdefault("metadata", {})
        if damage == "key-bound": metadata["x" * 4097] = "too long"
        elif damage == "integer-bound": metadata["untrusted_integer"] = contracts.MAX_INTEGER + 1
        else: metadata["untrusted_text"] = "bad" + chr(0) + "text"
        row[key] = json.dumps(decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    elif damage == "invalid-ast":
        decoded = json.loads(raw)
        decoded["root"]["kind"] = "unsupported-test-constructor"
        row[key] = canonical_dag_json_bytes(decoded).decode("utf-8")
    if type(row[key]) is str and damage != "digest":
        # Bind each malformed payload's actual bytes, so stale hashes cannot
        # stand in for canonical/shape/depth rejection. The oversize case may
        # correctly refuse at the unchanged enclosing-record byte bound.
        row[key + "_sha256"] = sha(row[key].encode("utf-8"))
    # Check the codec itself as well as the public source replay boundary:
    # rejection must not rely only on differing from the retained source row.
    with pytest.raises((ValueError, TypeError)):
        shared._reviewed_definition_application_expression(row, "original")
    with pytest.raises((ValueError, TypeError)):
        forged = reviewed_preservation_reseal_fixture_v2(offered, manifest, files)
        reviewed_definition_application_validate_v1(control, forged)


@pytest.mark.parametrize("endpoint", ["prepare", "validate"])
def test_physical_realization_api_refuses_none_request_on_healthy_legacy_control(
        reviewed_definition_realization_control, endpoint):
    control = reviewed_definition_realization_control
    original, offered = control["preparation"], control["realization"]
    assert not control["case"]["declaration"]["cross_references"]
    assert reviewed_definition_realization_validate(control, offered) == offered
    assert offered.to_dict()["schema"] == shared.REVIEWED_DEFINITION_REALIZATION_SCHEMA
    options = dict(physical_request_raw=None, expected_physical_request_sha256=None,
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(original),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, **control["kwargs"])
    with pytest.raises(ValueError, match="original immutable physical request bytes required"):
        if endpoint == "prepare":
            shared.prepare_reviewed_physical_definition_realization_corpus_v1(
                original, control["graph"], control["admission"], *control["args"], **options)
        else:
            shared.validate_reviewed_physical_definition_realization_corpus_v1(
                offered, original, control["graph"], control["admission"], *control["args"],
                expected_realization_sha256=shared.reviewed_preservation_corpus_sha256(offered), **options)
