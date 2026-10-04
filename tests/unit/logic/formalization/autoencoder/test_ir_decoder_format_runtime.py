"""Decoder format identity contracts over private, inert original-corpus fixtures.

Only checkpoint_hub._instantiate is replaced by a fixed loader spy. The source,
route, codec, corpus and digest checks remain real; no numerical model, native
validator or new embedding producer runs and no quality authority is granted.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
from ipfs_datasets_py.logic.formalization.autoencoder import ir_decoder_format_runtime as formats
from tests.unit.logic.formalization.autoencoder import test_ir_original_corpus_runtime as original_shared
from tests.unit.logic.formalization.autoencoder import test_ir_cell_routing as shared


FAMILIES = ("intent_ir", "security_ir")
SPLITS = ("train", "validation", "test")
SPECS = {
    "intent_ir": {
        "target_format_id": "intent_ir/intent_rich_ast",
        "schema_version": "intent-rich-grammar/v1",
        "task_id": "source_to_native_ir",
    },
    "security_ir": {
        "target_format_id": "security_ir/program_expression",
        "schema_version": "program-ir/v1",
        "task_id": "source_to_native_ir",
    },
}
VALIDATOR_BINDINGS = {
    "intent_ir": (
        "ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar",
        "6c40ac99d7e339651b6029764f94b12430ca515d4c5f7426770b013499efe92b",
    ),
    "security_ir": (
        "ipfs_datasets_py.logic.software_verification.program",
        "f051f42d64c5f993451972924953cc7eaa6d17df097235ddabfd5d791d406f91",
    ),
}
base_loader = original_shared.loader


def make_format_data(tmp_path, family="intent_ir"):
    data = original_shared.make_original(tmp_path, family)
    name, digest = VALIDATOR_BINDINGS[family]
    data["checkpoint"]["implementation"]["dependencies"][name] = digest
    original_shared.repin(data)
    return data


@pytest.fixture
def data(tmp_path):
    return make_format_data(tmp_path)


@pytest.fixture
def loader(base_loader):
    """Extend the returned inert spy, preserving its sole production patch."""
    base_loader["output_change"] = None
    base_loader["abstain"] = False
    base_loader["last_raw_report"] = None

    def install_report_adapter():
        instance = base_loader["loaded"][-1]
        original_infer = instance.infer

        def infer(rows, **options):
            report = original_infer(rows, **options)
            report.update(schema="domain-384-typed-autoencoder/v1",
                          domain_id=instance.family, dimension=384,
                          rows=[{
                              "id": row["id"],
                              "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                              "status": "fail_open_invalid_output" if base_loader["abstain"] else "unqualified_candidate",
                              "candidate_ir": None if base_loader["abstain"] else original_shared.target(instance.family, 0),
                          } for row in rows])
            if base_loader["output_change"] is not None:
                base_loader["output_change"](report)
            base_loader["last_raw_report"] = report
            return report

        instance.infer = infer

    base_loader["after_load"] = install_report_adapter
    base_loader["install_report_adapter"] = install_report_adapter
    return base_loader


def arguments(data, split="test", ids=None):
    return {**original_shared.options(data, split, ids),
            "format_request": deepcopy(SPECS[data["family"]])}


def prepare(data, **changes):
    options = arguments(data)
    options.update(changes)
    return formats.prepare_ir_decoder_format_runtime(data["directory_pin"],
        list(data["pins"].values()), data["request"], **options)


def open_format(data, **changes):
    options = arguments(data)
    options.update(changes)
    return hub.open_ir_decoder_format_autoencoder(data["directory_pin"],
        list(data["pins"].values()), data["request"], **options)


def reject_before_loader(data, loader, **changes):
    with pytest.raises(formats.DecoderFormatRuntimeError):
        open_format(data, **changes)
    assert loader["calls"] == [] and loader["loaded"] == []


def refresh_codec(data):
    """Keep miniature altered fixtures lexical-covered, without fitting a model."""
    pieces = {piece for row in data["corpus"]["rows"] for piece in
              original_shared.JSON_TOKEN.findall(original_shared.canonical(row["target"]).decode())}
    data["checkpoint"]["codec"]["target_vocabulary"] = ["<pad>", "<bos>", "<eos>", *sorted(pieces)]
    original_shared.repin(data, manifests=True)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def intent_constructor(kind):
    atom = original_shared.target("intent_ir", 0)["document"]
    if kind == "atom":
        return atom
    if kind == "if":
        return {"kind": kind, "guard": {"subject": "operator", "property": "ready", "negated": False},
                "body": atom}
    return {"kind": kind, "left": atom, "right": deepcopy(atom)}


def program_constructor(kind):
    document = original_shared.target("security_ir", 0)["document"]
    arity = {"unary": 1, "field": 1, "old": 1, "binary": 2, "conditional": 3}.get(kind, 0)
    document.update(kind=kind, operand_ids=[f"expr:operand:{index}" for index in range(arity)],
                    evaluation_order=[f"expr:operand:{index}" for index in range(arity)],
                    symbol_ids=["symbol:result"] if kind in ("symbol", "result") else [],
                    operator="+" if kind in ("unary", "binary", "field", "index", "quantified") else "")
    return document


def drift_path(data, artifact):
    return Path({"checkpoint": data["documents"][(data["family"], 384)]["existing_checkpoint_evidence"][0]["receipt"],
                 "corpus": data["corpus_pin"], "package": data["manifest_pin"],
                 "directory": data["directory_pin"], "cell": data["pins"][(data["family"], 384)]
                 }[artifact]["path"])


def alter_bytes(data, artifact):
    path = drift_path(data, artifact)
    path.write_bytes(path.read_bytes() + b"\n ")


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("split", SPLITS)
def test_explicit_fragment_contract_preserves_lane_and_target_free_order(tmp_path, loader, family, split):
    data = make_format_data(tmp_path, family)
    rows = [row for row in data["corpus"]["rows"] if row["split"] == split]
    ids = [rows[1]["id"], rows[0]["id"]]
    plan = prepare(data, corpus_split=split, row_ids=ids)
    assert loader["calls"] == []
    assert len(data["pins"]) == 12 and set(plan["route"]["request"]) == {
        "ir_family_id", "dimension", "dimension_role", "task_id", "checkpoint_sha256"}
    assert plan["format_request"] == SPECS[family]
    expected = [{key: row[key] for key in ("id", "source_text", "embedding")} for row in reversed(rows)]
    assert plan["inputs"] == expected
    contract = plan["format_contract"]
    binding = {key: value for key, value in contract.items() if key not in ("contract_id", "contract_sha256")}
    assert contract["contract_sha256"] == digest(binding)
    assert contract["contract_id"] == "ir-decoder-format-contract/v1:" + digest(binding)
    assert contract["canonical_codec_sha256"] == digest(data["checkpoint"]["codec"])
    assert contract["decoder_configuration_sha256"] == digest(data["checkpoint"]["config"])
    assert contract["implementation_declaration_sha256"] == digest(data["checkpoint"]["implementation"])
    assert contract["training_manifest_sha256"] == digest(data["checkpoint"]["training_manifest"])
    assert contract["validation_manifest_sha256"] == digest(data["checkpoint"]["validation_manifest"])
    assert contract["checkpoint_receipt"] == data["documents"][(family, 384)]["existing_checkpoint_evidence"][0]["receipt"]
    assert contract["corpus_receipt"] == data["corpus_pin"]
    assert contract["format_implementation_module"] == VALIDATOR_BINDINGS[family][0]
    assert contract["format_implementation_receipt"]["sha256"] == VALIDATOR_BINDINGS[family][1]
    assert contract["output_scope"] == "serialized_native_fragment"
    assert contract["all_original_targets_checked"] == 6
    assert contract["all_original_targets_structurally_match"] is True
    constructor = "atom" if family == "intent_ir" else "binary"
    assert contract["fitted_constructor_coverage"] == {constructor: 2}
    assert contract["original_constructor_coverage_by_split"] == {name: {constructor: 2} for name in SPLITS}
    assert contract["selected_output_contract_only"] is False and contract["native_grammar_verified"] is False
    assert not any(plan["authority"].values())
    assert plan["capability"]["full_native_document_supported"] is False
    assert plan["capability"]["source_text_decoder_supported"] is False
    assert plan["capability"]["logic_decoder_supported"] is False
    selected = open_format(data, corpus_split=split, row_ids=ids)
    assert len(loader["calls"]) == 1 and loader["loaded"][0].calls == []
    description = selected.describe()
    assert description["format_contract"] == contract
    assert description["model_load_started"] is True and description["model_load_performed"] is True
    assert description["model_inference_started"] is False and description["cached_inference_executed"] is False
    report = selected.infer_cached()
    assert loader["loaded"][0].calls == [{"rows": expected, "options": {}}]
    assert report["schema"] == "ir-decoder-format-inference/v1"
    assert report["format_contract"] == contract and report["format_request"] == SPECS[family]
    assert report["candidate_format_checks"]["attempted_rows"] == 2
    assert report["candidate_format_checks"]["decoded_rows"] == 2
    assert report["candidate_format_checks"]["abstained_rows"] == 0
    assert report["candidate_format_checks"]["semantic_correctness_verified"] is False
    assert report["candidate_format_checks"]["native_grammar_verified"] is False
    assert report["model_inference_executed"] is True and not any(report["authority"].values())
    assert all(set(row) == {"id", "source_text", "embedding"} for row in expected)
    assert not hasattr(selected, "infer_texts") and not hasattr(selected, "infer")


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("change", ["foreign_family", "full_document", "future_schema", "other_family_schema",
                                   "text_task", "logic_task", "unspecified_task"])
def test_family_document_schema_and_task_mismatches_precede_loader(tmp_path, loader, family, change):
    data = make_format_data(tmp_path, family)
    request = deepcopy(SPECS[family])
    foreign = "security_ir" if family == "intent_ir" else "intent_ir"
    if change == "foreign_family":
        request["target_format_id"] = SPECS[foreign]["target_format_id"]
    elif change == "full_document":
        request["target_format_id"] = family + "/full_document"
    elif change == "future_schema":
        request["schema_version"] = request["schema_version"].replace("/v1", "/v2")
    elif change == "other_family_schema":
        request["schema_version"] = SPECS[foreign]["schema_version"]
    else:
        request["task_id"] = {"text_task": "native_ir_to_source", "logic_task": "native_ir_to_logic",
                              "unspecified_task": ""}[change]
    reject_before_loader(data, loader, format_request=request)


@pytest.mark.parametrize("value", [None, [], "intent_ir/intent_rich_ast", True, 384, ()])
def test_format_request_requires_an_explicit_closed_mapping(data, loader, value):
    reject_before_loader(data, loader, format_request=value)


@pytest.mark.parametrize("field", ["target_format_id", "schema_version", "task_id"])
@pytest.mark.parametrize("value", [None, True, 1, ["source_to_native_ir"]])
def test_format_fields_are_exact_strings(data, loader, field, value):
    request = deepcopy(SPECS["intent_ir"])
    request[field] = value
    reject_before_loader(data, loader, format_request=request)


@pytest.mark.parametrize("field", ["target_format_id", "schema_version", "task_id", "extra"])
def test_format_request_has_no_default_or_extra_authority_field(data, loader, field):
    request = deepcopy(SPECS["intent_ir"])
    if field == "extra":
        request["grammar_qualified"] = True
    else:
        del request[field]
    reject_before_loader(data, loader, format_request=request)


@pytest.mark.parametrize("field,value", [("ir_family_id", "legal_ir"), ("ir_family_id", "codebase_ir"),
    ("dimension", 8), ("dimension", 768), ("dimension", 786), ("dimension", True),
    ("dimension_role", "latent"), ("task_id", "native_ir_to_source"),
    ("checkpoint_sha256", None), ("checkpoint_sha256", "f" * 64)])
def test_format_sidecar_does_not_promote_foreign_lane_role_or_task(data, loader, field, value):
    data["request"][field] = value
    reject_before_loader(data, loader)


@pytest.mark.parametrize("field", ["target_format_id", "schema_version"])
def test_format_identity_is_separate_from_the_legacy_five_field_request(data, loader, field):
    data["request"][field] = SPECS["intent_ir"][field]
    reject_before_loader(data, loader)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("change", ["foreign_kind", "full_document", "extra_wrapper", "missing_document",
                                   "nonobject_document", "extra_document"])
def test_unselected_original_targets_are_checked_before_loader(tmp_path, loader, family, change):
    data = make_format_data(tmp_path, family)
    row = next(row for row in data["corpus"]["rows"] if row["split"] == "validation")
    if change == "foreign_kind":
        row["target"]["kind"] = "program_expression" if family == "intent_ir" else "intent_rich_ast"
    elif change == "full_document":
        row["target"] = {"kind": "document", "document": {"nodes": [], "references": []}}
    elif change == "extra_wrapper":
        row["target"]["schema_version"] = SPECS[family]["schema_version"]
    elif change == "missing_document":
        del row["target"]["document"]
    elif change == "nonobject_document":
        row["target"]["document"] = []
    else:
        row["target"]["document"]["native_grammar_verified"] = True
    refresh_codec(data)
    reject_before_loader(data, loader, corpus_split="test")


@pytest.mark.parametrize("field,value", [("actor", ""), ("actor", "a b c d e"), ("actor", "bad@actor"),
    ("actor", "`unclosed"), ("action", "Save"), ("action", "save report"), ("action", ""),
    ("object", ""), ("object", "a  b"), ("object", "x" * 161),
    ("modality", "obligated"), ("modality", True), ("kind", "unknown")])
def test_intent_atom_profile_rejects_invalid_primitives_in_unselected_rows(data, loader, field, value):
    data["corpus"]["rows"][0]["target"]["document"][field] = value
    refresh_codec(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("change", ["bad_id", "boolean_kind", "unknown_kind", "blank_type", "nonobject_attributes",
    "blank_operator", "wrong_arity", "duplicate_operand", "missing_evaluation", "foreign_evaluation",
    "unsorted_sources", "duplicate_source", "missing_source", "invalid_source", "nonlist_symbols",
    "literal_operands", "symbol_without_symbol"])
def test_program_fragment_profile_rejects_invalid_local_structure(tmp_path, loader, change):
    data = make_format_data(tmp_path, "security_ir")
    document = data["corpus"]["rows"][0]["target"]["document"]
    changes = {
        "bad_id": {"expression_id": "bad ID"}, "boolean_kind": {"kind": True},
        "unknown_kind": {"kind": "statement"}, "blank_type": {"type_ref": " "},
        "nonobject_attributes": {"attributes": []}, "blank_operator": {"operator": " "},
        "wrong_arity": {"operand_ids": ["expr:value"], "evaluation_order": ["expr:value"]},
        "duplicate_operand": {"operand_ids": ["expr:value", "expr:value"]},
        "missing_evaluation": {"evaluation_order": []},
        "foreign_evaluation": {"evaluation_order": ["expr:value", "expr:foreign"]},
        "unsorted_sources": {"source_ref_ids": ["source:z", "source:a"]},
        "duplicate_source": {"source_ref_ids": ["source", "source"]},
        "missing_source": {"source_ref_ids": [], "span_ids": []},
        "invalid_source": {"source_ref_ids": [True]}, "nonlist_symbols": {"symbol_ids": {}},
        "literal_operands": {"kind": "literal"}, "symbol_without_symbol": {"kind": "symbol"},
    }
    document.update(changes[change])
    refresh_codec(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("kind", ["atom", "and", "or", "then", "if"])
def test_intent_declared_constructors_do_not_claim_fitted_coverage(data, loader, kind):
    data["corpus"]["rows"][-1]["target"]["document"] = intent_constructor(kind)
    refresh_codec(data)
    plan = prepare(data)
    assert loader["calls"] == []
    contract = plan["format_contract"]
    assert contract["fitted_constructor_coverage"] == {"atom": 2}
    expected = {"atom": 2} if kind == "atom" else {"atom": 1, kind: 1}
    assert contract["original_constructor_coverage_by_split"]["test"] == expected
    assert contract["native_grammar_verified"] is False and not any(plan["authority"].values())


@pytest.mark.parametrize("kind", ["literal", "symbol", "unary", "binary", "conditional", "call",
                                   "field", "index", "quantified", "old", "result", "undefined"])
def test_program_declared_constructors_do_not_claim_fitted_coverage(tmp_path, loader, kind):
    data = make_format_data(tmp_path, "security_ir")
    data["corpus"]["rows"][-1]["target"]["document"] = program_constructor(kind)
    refresh_codec(data)
    plan = prepare(data)
    assert loader["calls"] == []
    contract = plan["format_contract"]
    assert contract["fitted_constructor_coverage"] == {"binary": 2}
    expected = {"binary": 2} if kind == "binary" else {"binary": 1, kind: 1}
    assert contract["original_constructor_coverage_by_split"]["test"] == expected
    assert contract["native_grammar_verified"] is False


@pytest.mark.parametrize("change", ["nested_branch", "extra_guard", "boolean_property", "nonboolean_negation"])
def test_intent_composite_profile_is_closed_and_primitive(data, loader, change):
    document = intent_constructor("if" if change != "nested_branch" else "and")
    if change == "nested_branch":
        document["left"] = intent_constructor("and")
    elif change == "extra_guard":
        document["guard"]["schema"] = "qualified/v1"
    elif change == "boolean_property":
        document["guard"]["property"] = True
    else:
        document["guard"]["negated"] = 0
    data["corpus"]["rows"][-1]["target"]["document"] = document
    refresh_codec(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("change", ["missing", "foreign_module", "wrong_hash"])
def test_format_implementation_dependency_is_exact_before_loading(tmp_path, loader, family, change):
    data = make_format_data(tmp_path, family)
    module, expected = VALIDATOR_BINDINGS[family]
    dependencies = data["checkpoint"]["implementation"]["dependencies"]
    if change == "missing":
        dependencies.pop(module)
    elif change == "foreign_module":
        dependencies.pop(module)
        dependencies[VALIDATOR_BINDINGS["security_ir" if family == "intent_ir" else "intent_ir"][0]] = expected
    else:
        dependencies[module] = "f" * 64
    original_shared.repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("change", ["checkpoint_schema", "checkpoint_domain", "runtime_binding", "codec_schema",
                                   "codec_oov", "codec_special_order", "decoder_limit"])
def test_checkpoint_and_codec_cannot_be_relabelled_by_format_sidecar(data, loader, change):
    checkpoint = data["checkpoint"]
    if change == "checkpoint_schema":
        checkpoint["schema"] = "security-decoder/v2"
    elif change == "checkpoint_domain":
        checkpoint["domain_id"] = "security_ir"
    elif change == "runtime_binding":
        checkpoint["implementation"]["runtime"] = "f" * 64
    elif change == "codec_schema":
        checkpoint["codec"]["schema"] = "typed-json-lexical/v2"
    elif change == "codec_oov":
        checkpoint["codec"]["target_vocabulary"].remove('"actor"')
    elif change == "codec_special_order":
        vocabulary = checkpoint["codec"]["target_vocabulary"]
        vocabulary[0], vocabulary[1] = vocabulary[1], vocabulary[0]
    else:
        checkpoint["config"]["max_target_tokens"] = 3
    original_shared.repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("family", FAMILIES)
def test_authenticated_codec_changes_contract_identity_without_weight_repin_claim(tmp_path, loader, family):
    data = make_format_data(tmp_path, family)
    before = prepare(data)["format_contract"]
    vocabulary = data["checkpoint"]["codec"]["target_vocabulary"]
    vocabulary.append('"unused_token"')
    vocabulary[3:] = sorted(vocabulary[3:])
    original_shared.repin(data)
    after = prepare(data)["format_contract"]
    assert loader["calls"] == []
    assert after["canonical_codec_sha256"] != before["canonical_codec_sha256"]
    assert after["checkpoint_receipt"]["sha256"] != before["checkpoint_receipt"]["sha256"]
    assert after["contract_id"] != before["contract_id"]
    assert after["native_grammar_verified"] is False


def test_equal_bytes_at_another_checkpoint_path_do_not_replace_selected_asset(data, loader, tmp_path):
    checkpoint_pin = data["documents"][("intent_ir", 384)]["existing_checkpoint_evidence"][0]["receipt"]
    other = tmp_path / "same-checkpoint-bytes.json"
    other.write_bytes(Path(checkpoint_pin["path"]).read_bytes())
    data["documents"][("intent_ir", 384)]["existing_checkpoint_evidence"][0]["receipt"] = shared.pin(other)
    shared.rewrite_cell(data, "intent_ir", 384)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("artifact", ["checkpoint", "corpus", "package", "directory", "cell"])
@pytest.mark.parametrize("when", ["after_load", "before_infer", "after_infer"])
def test_file_binding_drift_refuses_at_actual_owner_boundary(data, loader, artifact, when):
    if when == "after_load":
        def after_load():
            loader["install_report_adapter"]()
            alter_bytes(data, artifact)
        loader["after_load"] = after_load
        with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
            open_format(data)
        assert caught.value.model_load_started is True and caught.value.model_load_performed is True
        assert caught.value.model_inference_started is False and caught.value.model_inference_executed is False
        assert loader["loaded"][0].calls == []
    else:
        selected = open_format(data)
        if when == "before_infer":
            alter_bytes(data, artifact)
        else:
            loader["loaded"][0].after_infer = lambda: alter_bytes(data, artifact)
        with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
            selected.infer_cached()
        assert caught.value.model_load_started is True and caught.value.model_load_performed is True
        assert caught.value.model_inference_started is (when == "after_infer")
        assert caught.value.model_inference_executed is (when == "after_infer")
        assert len(loader["loaded"][0].calls) == (1 if when == "after_infer" else 0)
        assert (caught.value.raw_candidate_report is not None) is (when == "after_infer")


def test_caller_format_and_selection_are_captured_before_loader(data, loader):
    options = arguments(data)
    pins = list(data["pins"].values())
    original_request, original_options = deepcopy(data["request"]), deepcopy(options)

    def after_load():
        loader["install_report_adapter"]()
        data["request"]["task_id"] = "native_ir_to_logic"
        options["format_request"]["target_format_id"] = "intent_ir/full_document"
        options["format_request"]["schema_version"] = "intent-rich-grammar/v99"
        options["row_ids"].reverse()
        options["corpus_split"] = "train"
        options["package_manifest_pin"]["sha256"] = "f" * 64
        pins.clear()

    loader["after_load"] = after_load
    selected = hub.open_ir_decoder_format_autoencoder(data["directory_pin"], pins, data["request"], **options)
    report = selected.infer_cached()
    assert report["runtime_selection"]["request"] == original_request
    assert report["format_request"] == original_options["format_request"]
    assert selected.describe()["row_selection"]["split"] == original_options["corpus_split"]
    assert [row["id"] for row in loader["loaded"][0].calls[0]["rows"]] == original_options["row_ids"]


def test_prepared_description_and_reports_are_detached_from_owner_and_each_other(data, loader):
    plan = prepare(data)
    original_contract = deepcopy(plan["format_contract"])
    plan["inputs"][0]["embedding"][0] = 999.0
    plan["format_contract"]["format_request"]["task_id"] = "foreign"
    assert prepare(data)["format_contract"] == original_contract
    selected = open_format(data)
    description = selected.describe()
    description["format_contract"]["format_request"]["task_id"] = "foreign"
    description["row_selection"]["row_ids"].clear()
    first = selected.infer_cached()
    first["format_contract"]["format_request"]["schema_version"] = "foreign"
    first["raw_candidate_report"]["rows"][0]["candidate_ir"]["document"]["actor"] = "foreign"
    first["candidate_format_checks"]["row_checks"].clear()
    assert loader["last_raw_report"]["rows"][0]["candidate_ir"]["document"]["actor"] == "operator"
    loader["last_raw_report"]["rows"].clear()
    assert selected.describe()["format_contract"] == original_contract
    second = selected.infer_cached()
    assert second["format_contract"] == original_contract
    assert len(second["raw_candidate_report"]["rows"]) == 2
    assert len(second["candidate_format_checks"]["row_checks"]) == 2
    assert not any(second["authority"].values())


def test_mutable_factory_arguments_do_not_rewrite_format_control_plan(data, loader):
    loader["mutate_factory"] = True
    selected = open_format(data)
    report = selected.infer_cached()
    assert report["runtime_selection"]["request"] == data["request"]
    assert report["format_request"] == SPECS["intent_ir"]
    assert len(report["raw_candidate_report"]["rows"]) == 2


def test_owner_input_mutation_refuses_return_without_changing_retained_artifacts(data, loader):
    corpus_before = Path(data["corpus_pin"]["path"]).read_bytes()
    selected = open_format(data)
    loader["loaded"][0].mutate_inputs = True
    with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
        selected.infer_cached()
    assert caught.value.model_inference_started is True and caught.value.model_inference_executed is True
    assert caught.value.raw_candidate_report is not None
    assert Path(data["corpus_pin"]["path"]).read_bytes() == corpus_before
    assert not any(selected.describe()["authority"].values())


@pytest.mark.parametrize("change", ["schema", "domain", "dimension", "boolean_dimension", "missing_rows",
    "nonlist_rows", "missing_row", "extra_row", "duplicate_id", "foreign_id", "wrong_source",
    "missing_source", "missing_status", "unknown_status", "missing_candidate", "candidate_null",
    "abstention_with_candidate"])
def test_returned_candidate_identity_and_status_are_not_relabelled(data, loader, change):
    def change_output(report):
        if change == "schema":
            report["schema"] = "claimed-format/v1"
        elif change == "domain":
            report["domain_id"] = "security_ir"
        elif change in ("dimension", "boolean_dimension"):
            report["dimension"] = 768 if change == "dimension" else True
        elif change == "missing_rows":
            del report["rows"]
        elif change == "nonlist_rows":
            report["rows"] = {}
        elif change == "missing_row":
            report["rows"].pop()
        elif change == "extra_row":
            report["rows"].append(deepcopy(report["rows"][0]))
        elif change == "duplicate_id":
            report["rows"][1] = deepcopy(report["rows"][0])
        else:
            row = report["rows"][0]
            if change == "foreign_id":
                row["id"] = "foreign:test:0"
            elif change == "wrong_source":
                row["source_sha256"] = "f" * 64
            elif change == "missing_source":
                del row["source_sha256"]
            elif change == "missing_status":
                del row["status"]
            elif change == "unknown_status":
                row["status"] = "verified"
            elif change == "missing_candidate":
                del row["candidate_ir"]
            elif change == "candidate_null":
                row["candidate_ir"] = None
            else:
                row["status"] = "fail_open_invalid_output"
    loader["output_change"] = change_output
    selected = open_format(data)
    with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
        selected.infer_cached()
    assert all((caught.value.model_load_started, caught.value.model_load_performed,
                caught.value.model_inference_started, caught.value.model_inference_executed))
    assert caught.value.raw_candidate_report == loader["last_raw_report"]
    assert caught.value.raw_candidate_report is not loader["last_raw_report"]
    assert len(loader["loaded"][0].calls) == 1


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("change", ["foreign_kind", "full_document", "wrong_constructor", "extra_field", "blank_primitive"])
def test_foreign_returned_fragment_refuses_after_inference(tmp_path, loader, family, change):
    data = make_format_data(tmp_path, family)
    def change_output(report):
        target = report["rows"][0]["candidate_ir"]
        if change == "foreign_kind":
            target["kind"] = "program_expression" if family == "intent_ir" else "intent_rich_ast"
        elif change == "full_document":
            target["document"] = {"nodes": [], "references": [], "schema": SPECS[family]["schema_version"]}
        elif change == "wrong_constructor":
            target["document"]["kind"] = "unknown"
        elif change == "extra_field":
            target["document"]["native_grammar_verified"] = True
        else:
            target["document"]["action" if family == "intent_ir" else "type_ref"] = " "
    loader["output_change"] = change_output
    selected = open_format(data)
    with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
        selected.infer_cached()
    assert caught.value.model_inference_started is True and caught.value.model_inference_executed is True
    assert caught.value.raw_candidate_report == loader["last_raw_report"]
    assert not any(selected.describe()["authority"].values())


def test_explicit_abstentions_preserve_attempted_denominator(data, loader):
    loader["abstain"] = True
    report = open_format(data).infer_cached()
    checks = report["candidate_format_checks"]
    assert (checks["attempted_rows"], checks["decoded_rows"], checks["abstained_rows"]) == (2, 0, 2)
    assert all(row["structural_format_match"] is None and row["constructor"] is None for row in checks["row_checks"])
    assert report["model_inference_executed"] is True and not any(report["authority"].values())


def test_returned_row_order_may_differ_but_source_associations_remain_exact(data, loader):
    loader["output_change"] = lambda report: report["rows"].reverse()
    selected = open_format(data)
    report = selected.infer_cached()
    assert [row["id"] for row in report["raw_candidate_report"]["rows"]] == list(reversed(arguments(data)["row_ids"]))
    assert report["candidate_format_checks"]["decoded_rows"] == 2
    assert [row["id"] for row in loader["loaded"][0].calls[0]["rows"]] == arguments(data)["row_ids"]


def test_untrusted_raw_authority_claims_are_preserved_without_root_promotion(data, loader):
    def change_output(report):
        report["proof_authority"] = True
        report["quality_qualified"] = True
        report["native_grammar_verified"] = True
    loader["output_change"] = change_output
    report = open_format(data).infer_cached()
    assert report["raw_candidate_report"]["proof_authority"] is True
    assert report["raw_candidate_report"]["quality_qualified"] is True
    assert not any(report["authority"].values())
    assert report["format_contract"]["native_grammar_verified"] is False
    assert report["candidate_format_checks"]["native_grammar_verified"] is False


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, OSError])
@pytest.mark.parametrize("boundary", ["loader", "infer"])
def test_ordinary_owner_failures_record_started_and_returned_boundaries(data, loader, error_type, boundary):
    failure = error_type("inert owner failure")
    def raise_failure():
        raise failure
    if boundary == "loader":
        loader["after_load"] = raise_failure
        with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
            open_format(data)
    else:
        selected = open_format(data)
        loader["loaded"][0].after_infer = raise_failure
        with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
            selected.infer_cached()
    assert caught.value.__cause__ is failure
    assert caught.value.model_load_started is True
    assert caught.value.model_load_performed is (boundary == "infer")
    assert caught.value.model_inference_started is (boundary == "infer")
    assert caught.value.model_inference_executed is False
    assert caught.value.raw_candidate_report is None
    assert len(loader["calls"]) == 1


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("boundary", ["loader", "infer"])
def test_owner_process_control_exceptions_propagate_unchanged(data, loader, error_type, boundary):
    failure = error_type("inert control flow")
    def raise_failure():
        raise failure
    if boundary == "loader":
        loader["after_load"] = raise_failure
        with pytest.raises(error_type) as caught:
            open_format(data)
    else:
        selected = open_format(data)
        loader["loaded"][0].after_infer = raise_failure
        with pytest.raises(error_type) as caught:
            selected.infer_cached()
    assert caught.value is failure


@pytest.mark.parametrize("value", [float("nan"), object()])
def test_noncanonical_returned_reports_refuse_after_actual_return(data, loader, value):
    loader["output_change"] = lambda report: report.update(noncanonical=value)
    selected = open_format(data)
    with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
        selected.infer_cached()
    assert caught.value.model_inference_started is True and caught.value.model_inference_executed is True
    assert caught.value.raw_candidate_report is None


def test_preinfer_drift_after_prior_success_records_this_call_as_not_started(data, loader):
    selected = open_format(data)
    selected.infer_cached()
    alter_bytes(data, "corpus")
    with pytest.raises(formats.DecoderFormatRuntimeError) as caught:
        selected.infer_cached()
    assert caught.value.model_load_started is True and caught.value.model_load_performed is True
    assert caught.value.model_inference_started is False and caught.value.model_inference_executed is False
    assert caught.value.raw_candidate_report is None
    assert len(loader["loaded"][0].calls) == 1
    assert selected.describe()["cached_inference_executed"] is True


@pytest.mark.parametrize("options", [{"rows": []}, {"format_request": SPECS["security_ir"]}, {"temperature": 0}])
def test_cached_inference_accepts_no_replacement_inputs_format_or_generation_options(data, loader, options):
    selected = open_format(data)
    with pytest.raises(TypeError):
        selected.infer_cached(**options)
    assert loader["loaded"][0].calls == []


def test_legacy_original_corpus_api_keeps_its_five_field_request(data, loader):
    selected = original_shared.open_original(data)
    report = selected.infer_cached()
    assert report["schema"] == "ir-original-corpus-inference/v1"
    assert "format_contract" not in report and "format_request" not in report
    assert set(report["runtime_selection"]["request"]) == {
        "ir_family_id", "dimension", "dimension_role", "task_id", "checkpoint_sha256"}
    assert len(loader["loaded"][0].calls) == 1 and not any(report["authority"].values())
