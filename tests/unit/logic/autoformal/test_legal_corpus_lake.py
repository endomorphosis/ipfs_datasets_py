"""Independent graph/source pins and native-source integrity; no Lean execution."""

import hashlib
import importlib.util
import json
import os
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_corpus_lake as corpus
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_lake as native
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "legal_corpus_authored_fixture",
    Path(__file__).with_name("test_corpus_definition_norm_adapter.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)
adapt_case = _FIXTURE_MODULE.adapt_case

TOOLCHAIN = "leanprover/lean4:v4.34.1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def candidate(modality="O", family="deontic_fol", **options):
    record, report_raw, report, request, arguments = adapt_case(modality, family, **options)
    candidate_raw = canonical_dag_json_bytes(record)
    inputs = {
        "candidate_raw": candidate_raw,
        "report_raw": report_raw,
        "request_raw": arguments["request_raw"],
        "raw_html": arguments["raw_html"],
    }
    pins = {
        "candidate_sha256": sha(candidate_raw),
        "candidate_cid": record["record_cid"],
        "graph_cid": record["graph"]["record_cid"],
        "request_sha256": arguments["expected_request_sha256"],
        "report_sha256": arguments["expected_report_sha256"],
        "raw_sha256": arguments["expected_raw_sha256"],
        "extracted_sha256": arguments["expected_extracted_sha256"],
    }
    return inputs, pins, record, report, request


def population(*specifications):
    cases = (
        [candidate(*specification) for specification in specifications]
        if specifications
        else [candidate()]
    )
    return [case[0] for case in cases], [case[1] for case in cases], cases


def prepare(inputs, pins):
    return corpus.prepare_definition_norm_corpus(
        inputs, expected_population=pins, toolchain=TOOLCHAIN
    )


def validate(preparation, inputs, pins, *, toolchain=TOOLCHAIN):
    return corpus.validate_definition_norm_corpus(
        preparation, candidate_inputs=inputs, expected_population=pins, toolchain=toolchain
    )


def reseal(value):
    return contracts.seal_record(
        {key: item for key, item in value.items() if key not in {"record_cid", "cid_scope"}}
    )


def forged_preparation(preparation, *, files=None, mutate_manifest=None):
    manifest = preparation.to_dict()
    final_files = dict(preparation.files) if files is None else files
    manifest["file_sha256"] = {name: sha(body.encode()) for name, body in final_files.items()}
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    return replace(
        preparation,
        files=tuple(sorted(final_files.items())),
        manifest_json=canonical_dag_json_bytes(reseal(manifest)).decode(),
    )


def test_all_six_native_modules_preserve_graph_source_assertion_and_declaration_bindings():
    specs = [(modality, family) for modality in "OPF" for family in ("deontic_fol", "tdfol")]
    inputs, pins, cases = population(*specs)
    preparation = prepare(inputs, pins)
    manifest, files = preparation.to_dict(), dict(preparation.files)
    assert manifest["population"] == pins
    assert manifest["population_cid"] == cid_for_dag_json(pins)
    assert manifest["preparation_only"] is True
    assert (
        manifest["shared_definition_deduplication"]
        is manifest["external_definition_resolution"]
        is False
    )
    assert (
        len(manifest["bindings"]) == len(manifest["native_preparation_manifest"]["bindings"]) == 6
    )
    assert manifest["file_sha256"] == {name: sha(body.encode()) for name, body in files.items()}
    root_imports = files["LegalDefinitionNorm.lean"].splitlines()
    assert len(root_imports) == 6 and len(set(root_imports)) == 6
    for ordinal, (binding, case) in enumerate(zip(manifest["bindings"], cases, strict=True)):
        record, report = case[2], case[3]
        assert binding["ordinal"] == ordinal
        assert binding["candidate_cid"] == record["record_cid"]
        assert binding["graph_cid"] == record["graph"]["record_cid"]
        for key in (
            "source_version",
            "definition_record",
            "norm_record",
            "ast_record",
            "scope_record",
            "term_record",
            "symbol_record",
        ):
            assert binding[key + "_cid"] == record[key]["record_cid"]
        assert binding["source_occurrence_cids"] == [
            row["record_cid"] for row in record["source_occurrences"]
        ]
        assert binding["source_bindings"] == record["source_bindings"]
        assert binding["source_occurrences"] == [
            {
                key: occurrence[key]
                for key in (
                    "record_cid",
                    "source_version_cid",
                    "start_char",
                    "end_char",
                    "start_utf8",
                    "end_utf8",
                )
            }
            for occurrence in record["source_occurrences"]
        ]
        assertion_nodes = {
            node["node_type"]: node["record_cid"]
            for node in record["graph"]["nodes"]
            if node["node_type"] in {"definition_assertion", "norm_assertion"}
        }
        assert binding["graph_assertion_node_cids"] == assertion_nodes
        assert binding["semantic_nodes"] == [
            {
                "node_type": node["node_type"],
                "node_cid": node["record_cid"],
                "content_cid": node["content_cid"],
            }
            for node in record["graph"]["nodes"]
            if node["node_type"]
            in {"definition_assertion", "norm_assertion", "scope", "term_sense", "expression"}
        ]
        assert binding["definition_edges"] == [
            {
                "relation": edge["relation"],
                "edge_cid": edge["record_cid"],
                "src_cid": edge["src_cid"],
                "dst_cid": edge["dst_cid"],
            }
            for edge in record["graph"]["edges"]
            if edge["relation"] in {"DEFINES", "USES_DEFINITION"}
        ]
        assert binding["declaration"] == "formula_0"
        assert binding["module"] == f"LegalDefinitionNorm.Definition{ordinal:04d}"
        assert binding["qualified_declaration"] == binding["module"] + ".formula_0"
        body = files[binding["module_path"]]
        assert body == (
            f"import LegalDefinitionNorm.Prelude\nnamespace {binding['module']}\n"
            f"{report['lean_body']}\nend {binding['module']}\n"
        )
        assert binding["module_sha256"] == sha(body.encode())
        assert (
            binding["native_binding"]
            == manifest["native_preparation_manifest"]["bindings"][ordinal]
        )
        assert binding["native_binding"]["native_ast_sha256"] == native.bridge.digest(
            record["ast_record"]["native_ast"]
        )
        assert root_imports[ordinal] == "import " + binding["module"]
    assert manifest["expected_modules"] == [
        "LegalDefinitionNorm.Prelude",
        *[binding["module"] for binding in manifest["bindings"]],
        "LegalDefinitionNorm",
    ]
    assert validate(preparation, inputs, pins) == preparation


def test_equal_definition_literals_are_retained_in_each_joint_module_without_semantic_deduplication():
    inputs, pins, cases = population(("O", "deontic_fol"), ("P", "deontic_fol"))
    preparation = prepare(inputs, pins)
    manifest = preparation.to_dict()
    assert (
        cases[0][2]["term_record"]["source_literal"] == cases[1][2]["term_record"]["source_literal"]
    )
    assert len(manifest["bindings"]) == 2
    assert manifest["bindings"][0]["module"] != manifest["bindings"][1]["module"]
    assert manifest["shared_definition_deduplication"] is False
    assert all(
        cases[index][3]["lean_body"] in dict(preparation.files)[binding["module_path"]]
        for index, binding in enumerate(manifest["bindings"])
    )


def test_preparation_and_native_manifest_keep_every_authority_dimension_false():
    inputs, pins, _ = population()
    manifest = prepare(inputs, pins).to_dict()
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
    assert manifest["native_preparation_manifest"]["proof_authority"] is False
    assert manifest["native_preparation_manifest"]["admitted"] is False


def test_preparation_calls_no_native_build_process_or_toolchain_probe(monkeypatch):
    inputs, pins, _ = population()

    def forbidden(*args, **kwargs):
        raise AssertionError("preparation must not execute Lean or a backend")

    monkeypatch.setattr(native, "build", forbidden)
    monkeypatch.setattr(native.shared, "_installed_toolchain", forbidden)
    monkeypatch.setattr(native.process.BoundedToolRunner, "run", forbidden)
    preparation = prepare(inputs, pins)
    assert validate(preparation, inputs, pins) == preparation


@pytest.mark.parametrize(
    "field",
    [
        "candidate_sha256",
        "request_sha256",
        "report_sha256",
        "raw_sha256",
        "extracted_sha256",
        "candidate_cid",
        "graph_cid",
    ],
)
def test_every_independent_population_pin_is_required(field):
    inputs, pins, _ = population()
    pins[0][field] = cid_for_dag_json({"different": field}) if field.endswith("_cid") else "0" * 64
    with pytest.raises(contracts.CorpusContractError):
        prepare(inputs, pins)


@pytest.mark.parametrize(
    "damage", ["inputs_drop", "pins_drop", "inputs_reorder", "input_duplicate", "pin_duplicate"]
)
def test_supplied_population_order_multiplicity_and_denominator_cannot_drift(damage):
    inputs, pins, _ = population(("O", "deontic_fol"), ("P", "deontic_fol"))
    if damage == "inputs_drop":
        inputs.pop()
    elif damage == "pins_drop":
        pins.pop()
    elif damage == "inputs_reorder":
        inputs.reverse()
    elif damage == "input_duplicate":
        inputs[1] = inputs[0]
    else:
        pins[1] = pins[0]
    with pytest.raises(contracts.CorpusContractError):
        prepare(inputs, pins)


def test_reordering_both_inputs_and_new_pins_changes_module_mapping_and_invalidates_old_preparation():
    inputs, pins, _ = population(("O", "deontic_fol"), ("P", "deontic_fol"))
    first = prepare(inputs, pins)
    changed_inputs, changed_pins = list(reversed(inputs)), list(reversed(pins))
    other = prepare(changed_inputs, changed_pins)
    assert first.to_dict()["population_cid"] != other.to_dict()["population_cid"]
    assert (
        first.to_dict()["bindings"][0]["candidate_cid"]
        == other.to_dict()["bindings"][1]["candidate_cid"]
    )
    assert (
        dict(first.files)["LegalDefinitionNorm/Definition0000.lean"]
        != dict(other.files)["LegalDefinitionNorm/Definition0000.lean"]
    )
    with pytest.raises(contracts.CorpusContractError):
        validate(first, changed_inputs, changed_pins)


def test_distinct_graphs_with_same_native_identity_are_rejected_instead_of_renamed():
    first, first_pin, _, _, _ = candidate(edition=2024)
    second, second_pin, _, _, _ = candidate(edition=2025)
    assert first_pin["candidate_cid"] != second_pin["candidate_cid"]
    with pytest.raises(contracts.CorpusContractError, match="duplicate"):
        prepare([first, second], [first_pin, second_pin])


@pytest.mark.parametrize("damage", ["ast", "graph_drop", "other_graph", "source_binding"])
def test_resealed_candidate_and_repaired_population_pins_cannot_substitute_graph_or_ast(damage):
    inputs, pins, cases = population()
    record = deepcopy(cases[0][2])
    if damage == "ast":
        record["ast_record"]["native_ast"]["right"]["quantifier"]["value"] = "∃"
        record["ast_record"] = reseal(record["ast_record"])
    elif damage == "graph_drop":
        record["graph"]["edges"] = [
            edge for edge in record["graph"]["edges"] if edge["relation"] != "USES_DEFINITION"
        ]
        record["graph"] = reseal(record["graph"])
    elif damage == "other_graph":
        record["graph"] = candidate("P")[2]["graph"]
    else:
        record["source_bindings"][0]["paragraph_indices"] = [999]
    record = reseal(record)
    inputs[0]["candidate_raw"] = canonical_dag_json_bytes(record)
    pins[0].update(
        candidate_sha256=sha(inputs[0]["candidate_raw"]),
        candidate_cid=record["record_cid"],
        graph_cid=record["graph"]["record_cid"],
    )
    with pytest.raises(contracts.CorpusContractError):
        prepare(inputs, pins)


@pytest.mark.parametrize("field", ["report_raw", "request_raw", "raw_html"])
def test_original_companion_bytes_cannot_be_replaced_even_after_outer_hash_repair(field):
    inputs, pins, _ = population()
    inputs[0][field] += b" "
    pin = {
        "report_raw": "report_sha256",
        "request_raw": "request_sha256",
        "raw_html": "raw_sha256",
    }[field]
    pins[0][pin] = sha(inputs[0][field])
    with pytest.raises(contracts.CorpusContractError):
        prepare(inputs, pins)


@pytest.mark.parametrize(
    "damage",
    [
        "true",
        "axiom",
        "sorry",
        "missing_module",
        "drop_root_import",
        "extra_file",
        "changed_prelude",
    ],
)
def test_hash_repaired_preparation_files_cannot_replace_or_omit_native_declarations(damage):
    inputs, pins, _ = population(("O", "deontic_fol"), ("P", "deontic_fol"))
    original = prepare(inputs, pins)
    files = dict(original.files)
    path = "LegalDefinitionNorm/Definition0001.lean"
    if damage == "true":
        files[path] = "def formula_0 : Prop := True\n"
    elif damage == "axiom":
        files[path] = "axiom invented : False\n"
    elif damage == "sorry":
        files[path] = "theorem invented : False := by sorry\n"
    elif damage == "missing_module":
        del files[path]
    elif damage == "drop_root_import":
        files["LegalDefinitionNorm.lean"] = "import LegalDefinitionNorm.Definition0000\n"
    elif damage == "extra_file":
        files["../escaped.lean"] = "def formula_0 : Prop := True\n"
    else:
        files["LegalDefinitionNorm/Prelude.lean"] += "axiom invented : False\n"
    changed = forged_preparation(original, files=files)
    with pytest.raises(contracts.CorpusContractError):
        validate(changed, inputs, pins)


@pytest.mark.parametrize(
    "damage",
    [
        "binding_graph",
        "binding_ast",
        "binding_origin",
        "binding_module",
        "binding_source_roles",
        "drop_binding",
        "population",
        "native_manifest",
        "authority",
        "unknown_field",
    ],
)
def test_resealed_manifest_cannot_change_graph_module_provenance_or_authority(damage):
    inputs, pins, _ = population()
    original = prepare(inputs, pins)

    def mutate(manifest):
        binding = manifest["bindings"][0]
        if damage == "binding_graph":
            binding["graph_cid"] = cid_for_dag_json({"other": "graph"})
        elif damage == "binding_ast":
            binding["ast_record_cid"] = cid_for_dag_json({"other": "ast"})
        elif damage == "binding_origin":
            binding["source_occurrence_cids"] = []
        elif damage == "binding_module":
            binding["declaration"] = "invented"
        elif damage == "binding_source_roles":
            binding["source_bindings"].pop()
        elif damage == "drop_binding":
            manifest["bindings"] = []
        elif damage == "population":
            manifest["population"] = []
        elif damage == "native_manifest":
            manifest["native_preparation_manifest"]["bindings"][0]["native_ast_sha256"] = "0" * 64
        elif damage == "authority":
            manifest["lean_compilation_verified"] = True
        else:
            manifest["ignored"] = True

    changed = forged_preparation(original, mutate_manifest=mutate)
    with pytest.raises(contracts.CorpusContractError):
        validate(changed, inputs, pins)


@pytest.mark.parametrize(
    "toolchain", ["main", "leanprover/lean4:latest", "leanprover/lean4:v4.34.1\n", None, True]
)
def test_toolchain_requires_exact_version_pin(toolchain):
    inputs, pins, _ = population()
    with pytest.raises(contracts.CorpusContractError):
        corpus.prepare_definition_norm_corpus(inputs, expected_population=pins, toolchain=toolchain)


@pytest.mark.parametrize(
    "damage",
    ["input_extra", "input_missing", "pin_extra", "pin_missing", "mutable_bytes", "nonlist"],
)
def test_closed_input_shapes_and_exact_immutable_bytes_are_required(damage):
    inputs, pins, _ = population()
    if damage == "input_extra":
        inputs[0]["ignored"] = b"value"
    elif damage == "input_missing":
        inputs[0].pop("report_raw")
    elif damage == "pin_extra":
        pins[0]["ignored"] = "value"
    elif damage == "pin_missing":
        pins[0].pop("graph_cid")
    elif damage == "mutable_bytes":
        inputs[0]["candidate_raw"] = bytearray(inputs[0]["candidate_raw"])
    else:
        inputs = tuple(inputs)
    with pytest.raises(contracts.CorpusContractError):
        prepare(inputs, pins)


def test_empty_population_and_finite_whole_input_limits_refuse_without_filtering(monkeypatch):
    with pytest.raises(contracts.CorpusContractError):
        prepare([], [])
    inputs, pins, _ = population(("O", "deontic_fol"), ("P", "deontic_fol"))
    monkeypatch.setattr(corpus, "MAX_CANDIDATES", 1)
    with pytest.raises(contracts.CorpusContractError):
        prepare(inputs, pins)
    monkeypatch.setattr(corpus, "MAX_CANDIDATES", 64)
    monkeypatch.setattr(corpus, "MAX_INPUT_BYTES", sum(map(len, inputs[0].values())))
    with pytest.raises(contracts.CorpusContractError, match="complete input byte bound"):
        prepare(inputs, pins)


def test_preparation_is_frozen_detached_and_requires_typed_validation_input():
    inputs, pins, _ = population()
    before = deepcopy((inputs, pins))
    preparation = prepare(inputs, pins)
    assert (inputs, pins) == before
    with pytest.raises(FrozenInstanceError):
        preparation.manifest_json = "changed"
    manifest = preparation.to_dict()
    manifest["population"][0]["candidate_sha256"] = "0" * 64
    assert preparation.to_dict()["population"] == pins
    with pytest.raises(contracts.CorpusContractError):
        validate(preparation.to_dict(), inputs, pins)


@pytest.fixture(scope="module")
def frozen_project():
    inputs, pins, cases = population(("O", "deontic_fol"), ("P", "deontic_fol"))
    return prepare(inputs, pins), inputs, pins, cases


def write_project(preparation, path, inputs, pins):
    return corpus.write_definition_norm_corpus(
        preparation, path, candidate_inputs=inputs, expected_population=pins, toolchain=TOOLCHAIN
    )


def load_project(path, preparation, inputs, pins, *, expected_manifest_sha256=None):
    digest = (
        sha(preparation.manifest_json.encode())
        if expected_manifest_sha256 is None
        else expected_manifest_sha256
    )
    return corpus.load_definition_norm_corpus(
        path,
        expected_manifest_sha256=digest,
        candidate_inputs=inputs,
        expected_population=pins,
        toolchain=TOOLCHAIN,
    )


def test_writer_and_loader_read_back_exact_sources_and_sealed_external_manifest(
    tmp_path, frozen_project
):
    preparation, inputs, pins, _ = frozen_project
    path = tmp_path / "package"
    manifest = write_project(preparation, path, inputs, pins)
    assert manifest == preparation.to_dict()
    assert (path / corpus.MANIFEST_FILE).read_bytes() == preparation.manifest_json.encode()
    for name, body in preparation.files:
        assert (path / name).read_bytes() == body.encode()
    assert load_project(path, preparation, inputs, pins) == preparation


@pytest.mark.parametrize(
    "damage",
    [
        "missing_nonfirst",
        "extra_entry",
        "changed_source",
        "changed_prelude",
        "linked_file",
        "linked_directory",
    ],
)
def test_loader_refuses_incomplete_changed_or_linked_projects(tmp_path, frozen_project, damage):
    preparation, inputs, pins, _ = frozen_project
    path = tmp_path / "package"
    write_project(preparation, path, inputs, pins)
    module = path / "LegalDefinitionNorm/Definition0001.lean"
    if damage == "missing_nonfirst":
        module.unlink()
    elif damage == "extra_entry":
        (path / "unlisted.txt").write_bytes(b"unlisted data")
    elif damage == "changed_source":
        module.write_text("def formula_0 : Prop := True\n")
    elif damage == "changed_prelude":
        (path / "LegalDefinitionNorm/Prelude.lean").write_text("axiom invented : False\n")
    elif damage == "linked_file":
        target = tmp_path / "same-source.lean"
        target.write_bytes(module.read_bytes())
        module.unlink()
        module.symlink_to(target)
    else:
        directory = path / "LegalDefinitionNorm"
        moved = tmp_path / "same-modules"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    with pytest.raises((contracts.CorpusContractError, OSError)):
        load_project(path, preparation, inputs, pins)


def test_expected_fifo_is_refused_before_reading_without_blocking(
    tmp_path, frozen_project, monkeypatch
):
    preparation, inputs, pins, _ = frozen_project
    path = tmp_path / "package"
    write_project(preparation, path, inputs, pins)
    module = path / "LegalDefinitionNorm/Definition0001.lean"
    module.unlink()
    os.mkfifo(module)
    original_open = os.open
    seen = []

    def guarded_open(name, flags, *args, **kwargs):
        if str(name) == module.name:
            # Protect the regression test itself from hanging if NONBLOCK is
            # accidentally removed before fstat rejects the FIFO.
            assert flags & os.O_NONBLOCK
            seen.append(True)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)
    with pytest.raises(contracts.CorpusContractError, match="ordinary"):
        load_project(path, preparation, inputs, pins)
    assert seen


def test_loader_requires_external_manifest_pin_even_for_well_formed_project(
    tmp_path, frozen_project
):
    preparation, inputs, pins, _ = frozen_project
    path = tmp_path / "package"
    write_project(preparation, path, inputs, pins)
    with pytest.raises(contracts.CorpusContractError):
        load_project(path, preparation, inputs, pins, expected_manifest_sha256="0" * 64)


def test_resealed_and_newly_pinned_disk_manifest_cannot_promote_compilation_or_proof(
    tmp_path, frozen_project
):
    preparation, inputs, pins, _ = frozen_project
    path = tmp_path / "package"
    write_project(preparation, path, inputs, pins)
    manifest = json.loads((path / corpus.MANIFEST_FILE).read_text())
    manifest.update(lean_compilation_verified=True, proof_authority=True)
    changed = canonical_dag_json_bytes(reseal(manifest))
    (path / corpus.MANIFEST_FILE).write_bytes(changed)
    with pytest.raises(contracts.CorpusContractError):
        load_project(path, preparation, inputs, pins, expected_manifest_sha256=sha(changed))


def test_existing_output_is_never_overwritten(tmp_path, frozen_project):
    preparation, inputs, pins, _ = frozen_project
    path = tmp_path / "existing"
    path.mkdir()
    marker = path / "sentinel"
    marker.write_bytes(b"preserve existing local data")
    with pytest.raises(FileExistsError):
        write_project(preparation, path, inputs, pins)
    assert marker.read_bytes() == b"preserve existing local data"
    assert list(path.iterdir()) == [marker]


def test_redirected_output_subdirectory_cannot_receive_writes(
    tmp_path, frozen_project, monkeypatch
):
    preparation, inputs, pins, _ = frozen_project
    path, foreign = tmp_path / "package", tmp_path / "foreign"
    foreign.mkdir()
    marker = foreign / "sentinel"
    marker.write_bytes(b"foreign directory must remain unchanged")
    original_mkdir = os.mkdir

    def redirected_mkdir(name, *args, **kwargs):
        result = original_mkdir(name, *args, **kwargs)
        if str(name) == "LegalDefinitionNorm" and kwargs.get("dir_fd") is not None:
            os.rmdir(name, dir_fd=kwargs["dir_fd"])
            os.symlink(foreign, name, dir_fd=kwargs["dir_fd"], target_is_directory=True)
        return result

    monkeypatch.setattr(os, "mkdir", redirected_mkdir)
    with pytest.raises(OSError):
        write_project(preparation, path, inputs, pins)
    assert marker.read_bytes() == b"foreign directory must remain unchanged"
    assert list(foreign.iterdir()) == [marker]
    assert not (path / corpus.MANIFEST_FILE).exists()


def test_failed_source_write_never_commits_manifest(tmp_path, frozen_project, monkeypatch):
    preparation, inputs, pins, _ = frozen_project
    path = tmp_path / "package"
    original = corpus._write_new_file

    def incomplete(parent_fd, basename, raw):
        if basename == "Definition0001.lean":
            raise OSError("authored interrupted local write")
        return original(parent_fd, basename, raw)

    monkeypatch.setattr(corpus, "_write_new_file", incomplete)
    with pytest.raises(OSError):
        write_project(preparation, path, inputs, pins)
    assert not (path / corpus.MANIFEST_FILE).exists()


@pytest.mark.parametrize("operation", ["writer", "loader"])
def test_project_io_refuses_a_symlinked_ancestor(tmp_path, frozen_project, operation):
    preparation, inputs, pins, _ = frozen_project
    ordinary_parent = tmp_path / "ordinary"
    ordinary_parent.mkdir()
    marker = ordinary_parent / "sentinel"
    marker.write_bytes(b"ancestor alias must not receive writes")
    if operation == "loader":
        write_project(preparation, ordinary_parent / "project", inputs, pins)
    alias = tmp_path / "linked-parent"
    alias.symlink_to(ordinary_parent, target_is_directory=True)
    with pytest.raises((contracts.CorpusContractError, OSError)):
        if operation == "writer":
            write_project(preparation, alias / "project", inputs, pins)
        else:
            load_project(alias / "project", preparation, inputs, pins)
    assert marker.read_bytes() == b"ancestor alias must not receive writes"
    if operation == "writer":
        assert not (ordinary_parent / "project").exists()


@pytest.mark.parametrize("operation", ["writer", "loader"])
def test_project_io_refuses_explicit_parent_traversal(tmp_path, frozen_project, operation):
    preparation, inputs, pins, _ = frozen_project
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    if operation == "loader":
        write_project(preparation, tmp_path / "project", inputs, pins)
    requested = intermediate / ".." / "project"
    with pytest.raises((contracts.CorpusContractError, OSError)):
        if operation == "writer":
            write_project(preparation, requested, inputs, pins)
        else:
            load_project(requested, preparation, inputs, pins)
    if operation == "writer":
        assert not (tmp_path / "project").exists()
