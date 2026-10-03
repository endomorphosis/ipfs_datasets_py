"""Explicit original-corpus replay over private integrity fixtures.

Real package/route/schema/hash checks precede one fixed-loader spy. These tiny
checkpoints omit numerical tensors, and native evidence is deliberately inert;
the tests grant no numerical, native grammar or source-fidelity qualification.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
from ipfs_datasets_py.logic.formalization.autoencoder import ir_original_corpus_runtime as original
from tests.unit.logic.formalization.autoencoder import test_ir_cell_routing as shared
from tests.unit.logic.formalization.autoencoder import test_ir_cell_runtime as replay_shared


FAMILIES = ("intent_ir", "security_ir")
SPLITS = ("train", "validation", "test")
DOMAIN_SHA = "66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6"
JSON_TOKEN = re.compile(
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
    r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r'|true|false|null|[{}\[\],:]'
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def target(family, index):
    if family == "intent_ir":
        return {"kind": "intent_rich_ast", "document": {"kind": "atom",
            "actor": "operator", "action": ("save", "view")[index % 2],
            "object": "report", "modality": "required"}}
    return {"kind": "program_expression", "document": {
        "attributes": {}, "evaluation_order": ["expr:value", "expr:constant"],
        "expression_id": "expr:result", "kind": "binary",
        "operand_ids": ["expr:value", "expr:constant"],
        "operator": ("+", "*")[index % 2], "source_ref_ids": ["source"],
        "span_ids": [], "symbol_ids": [], "type_ref": "integer"}}


def row_manifest(row):
    return {"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
            "embedding_sha256": digest(row["embedding"]), "target_sha256": digest(row["target"])}


def make_original(tmp_path, family="intent_ir"):
    data = shared.make_inventory(tmp_path)
    rows = []
    for number, split in enumerate(SPLITS):
        for index in (0, 1):
            text = f"Private original {family} {split} source {index}."
            vector = [(number * 19 + index * 7 + offset) / 2048.0 for offset in range(384)]
            rows.append({"id": f"{family}:{split}:{index}", "source_text": text,
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "embedding": vector, "embedding_sha256": digest(vector),
                "group_id": f"authored:{family}:{split}:{index}", "split": split,
                "target": target(family, index),
                "native_evidence": {"fixture_only": "gold and evidence must stay out of infer"}})
    corpus = {"schema": "authored-native-384-development-corpus/v1", "domain": family,
        "embedding_dimension": 384, "embedding_model": hub.EMBEDDING["model_id"],
        "embedding_revision": hub.EMBEDDING["revision"], "proof_authority": False,
        "source_semantics_verified": False, "real_world_corpus_used": False,
        "semantic_target_overlap_across_partitions": True, "source_license": "Apache-2.0",
        "split_scope": "distinct source/group IDs; heldout wording with known semantic targets",
        "splits": {split: 2 for split in SPLITS}, "rows": rows}
    train = [row for row in rows if row["split"] == "train"]
    vocabulary = ["<pad>", "<bos>", "<eos>", *sorted({piece for row in train
        for piece in JSON_TOKEN.findall(canonical(row["target"]).decode())})]
    checkpoint = {"schema": "domain-384-typed-autoencoder/v1", "dimension": 384,
        "domain_id": family, "architecture": "residual-projection-latent-formula-gru/v1",
        **dict.fromkeys(("qualified", "admitted", "proof_authority", "source_semantics_verified",
                        "publication_performed"), False),
        "implementation": {"runtime": DOMAIN_SHA, "dependencies": {},
            "scope": "listed_numerical_and_native_validator_modules_only"},
        "codec": {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary},
        "config": {"max_target_tokens": 512},
        "training_manifest": [row_manifest(row) for row in train],
        "validation_manifest": [row_manifest(row) for row in rows if row["split"] == "validation"]}
    source = tmp_path / "synthetic-checkpoint.json"
    corpus_source = tmp_path / "synthetic-corpus.json"
    shared.write_json(source, checkpoint)
    corpus_source_pin = shared.write_json(corpus_source, corpus)
    directory = tmp_path / "private-original-package" / family
    manifest = hub.build_package(family, source, directory,
        provenance={"corpus_sha256": corpus_source_pin["sha256"],
                    "scope": "private schema/integrity fixture, no model tensors"},
        validation={"model_executed": False}, extra_files={"authored-corpus.json": corpus_source})
    checkpoint_pin = shared.pin(directory / "checkpoint.json")
    document = data["documents"][(family, 384)]
    document["existing_checkpoint_evidence"] = [{"role": "synthetic original-corpus package",
        "receipt": checkpoint_pin, "dimension_role": "input_embedding", "input_width": 384,
        "source_access": "recorded old embedding rows; quality unknown", "teacher_qualified": False}]
    # Existing native-v3 cache declarations intentionally contain non-JSON
    # placeholder bytes. The original-corpus lane must never parse these caches.
    shared.rewrite_cell(data, family, 384)
    data.update(family=family, corpus=corpus, checkpoint=checkpoint,
        package_dir=directory, manifest=manifest, manifest_pin=shared.pin(directory / "manifest.json"),
        corpus_pin=shared.pin(directory / "authored-corpus.json"),
        request=shared.request(family, checkpoint=checkpoint_pin["sha256"]))
    return data


@pytest.fixture
def data(tmp_path):
    return make_original(tmp_path)


loader = replay_shared.loader


@pytest.fixture(autouse=True)
def forbid_default_and_native_cache_lane(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Original corpus replay used a default, Hub fetch or native-v3 lane")
    monkeypatch.setattr(hub, "default_descriptor", forbidden)
    monkeypatch.setattr(hub, "open_autoencoder", forbidden)
    monkeypatch.setattr(hub, "open_local_autoencoder", forbidden)
    monkeypatch.setattr(hub, "open_ir_cell_autoencoder", forbidden)


def options(data, split="test", ids=None):
    return {"package_manifest_pin": deepcopy(data["manifest_pin"]),
        "corpus_pin": deepcopy(data["corpus_pin"]), "corpus_split": split,
        "row_ids": [row["id"] for row in data["corpus"]["rows"] if row["split"] == split] if ids is None else ids}


def prepare(data, **changes):
    args = options(data)
    args.update(changes)
    return original.prepare_ir_original_corpus_runtime(data["directory_pin"],
        list(data["pins"].values()), data["request"], **args)


def open_original(data, **changes):
    args = options(data)
    args.update(changes)
    return hub.open_ir_original_corpus_autoencoder(data["directory_pin"],
        list(data["pins"].values()), data["request"], **args)


def repin(data, *, manifests=False, row_digests=False):
    if row_digests:
        for row in data["corpus"]["rows"]:
            row["source_sha256"] = hashlib.sha256(row["source_text"].encode()).hexdigest()
            row["embedding_sha256"] = digest(row["embedding"])
    if manifests:
        for split, name in (("train", "training_manifest"), ("validation", "validation_manifest")):
            data["checkpoint"][name] = [row_manifest(row) for row in data["corpus"]["rows"] if row["split"] == split]
    data["corpus_pin"] = shared.write_json(data["package_dir"] / "authored-corpus.json", data["corpus"])
    checkpoint_pin = shared.write_json(data["package_dir"] / "checkpoint.json", data["checkpoint"])
    for name, pin in (("authored-corpus.json", data["corpus_pin"]), ("checkpoint.json", checkpoint_pin)):
        data["manifest"]["files"][name] = {key: pin[key] for key in ("bytes", "sha256")}
    data["manifest"]["provenance"]["corpus_sha256"] = data["corpus_pin"]["sha256"]
    data["manifest_pin"] = shared.write_json(data["package_dir"] / "manifest.json", data["manifest"])
    document = data["documents"][(data["family"], 384)]
    document["existing_checkpoint_evidence"][0]["receipt"] = checkpoint_pin
    shared.rewrite_cell(data, data["family"], 384)
    data["request"]["checkpoint_sha256"] = checkpoint_pin["sha256"]


def reject_before_loader(data, loader, **changes):
    with pytest.raises(original.OriginalCorpusRuntimeError):
        open_original(data, **changes)
    assert loader["calls"] == [] and loader["loaded"] == []


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("split", SPLITS)
def test_explicit_original_package_replays_ordered_target_free_rows(tmp_path, loader, family, split):
    data = make_original(tmp_path, family)
    rows = [row for row in data["corpus"]["rows"] if row["split"] == split]
    ids = [rows[1]["id"], rows[0]["id"]]
    plan = prepare(data, corpus_split=split, row_ids=ids)
    assert loader["calls"] == []
    assert plan["corpus_receipt"] == data["corpus_pin"]
    assert plan["corpus_split"] == split and plan["row_ids"] == ids
    assert plan["original_corpus_membership"] == {
        "total_rows": 6, "split_counts": {name: 2 for name in SPLITS},
        "canonical_encoding_covered_rows": 6, "training_manifest_exact": True,
        "validation_manifest_exact": True, "semantic_target_overlap_declared": True}
    assert plan["inputs"] == [{key: row[key] for key in ("id", "source_text", "embedding")}
                              for row in (rows[1], rows[0])]
    assert not any(plan["authority"].values())
    for receipt, row in zip(plan["row_receipts"], (rows[1], rows[0])):
        assert receipt["target_sha256"] == digest(row["target"])
        assert "target" not in receipt and "native_evidence" not in receipt
        assert receipt["checkpoint_fitting_membership"] is (split == "train")
        assert receipt["checkpoint_validation_membership"] is (split == "validation")
        assert receipt["native_grammar_verified"] is False
    selected = open_original(data, corpus_split=split, row_ids=ids)
    assert len(loader["calls"]) == 1 and loader["loaded"][0].calls == []
    assert loader["calls"][0]["paths"]["checkpoint.json"] == data["package_dir"] / "checkpoint.json"
    report = selected.infer_cached()
    assert loader["loaded"][0].calls[0]["rows"] == plan["inputs"]
    assert loader["loaded"][0].calls[0]["options"] == {}
    assert report["raw_candidate_report"]["received_ids"] == ids
    assert report["model_inference_executed"] is True and not any(report["authority"].values())
    assert not hasattr(selected, "infer_texts") and not hasattr(selected, "infer")


@pytest.mark.parametrize("field,value", [("ir_family_id", "legal_ir"), ("ir_family_id", "codebase_ir"),
    ("dimension", 8), ("dimension", 768), ("dimension", 786), ("dimension", True),
    ("dimension", 384.0), ("dimension_role", "latent"), ("dimension_role", "projection"),
    ("task_id", "native_ir_to_source"), ("task_id", "native_ir_to_logic"),
    ("checkpoint_sha256", None), ("checkpoint_sha256", "f" * 64)])
def test_foreign_cell_role_task_and_width_never_select_by_shape(data, loader, field, value):
    data["request"][field] = value
    reject_before_loader(data, loader)


@pytest.mark.parametrize("change", ["extra", "missing"])
def test_request_is_closed_before_loader(data, loader, change):
    if change == "extra":
        data["request"]["original_corpus_fallback"] = True
    else:
        del data["request"]["task_id"]
    reject_before_loader(data, loader)


@pytest.mark.parametrize("split", ["canary", "training", "", None, True])
def test_no_original_split_alias_or_canary_fallback(data, loader, split):
    reject_before_loader(data, loader, corpus_split=split, row_ids=[data["corpus"]["rows"][0]["id"]])


@pytest.mark.parametrize("ids", [[], ["outside"], ["intent_ir:test:0", "intent_ir:test:0"],
    ["intent_ir:train:0"], [False], [""], "intent_ir:test:0", None])
def test_selected_ids_are_exact_unique_and_in_selected_split(data, loader, ids):
    reject_before_loader(data, loader, row_ids=ids)


@pytest.mark.parametrize("count", [65, 100])
def test_selected_batch_bound_precedes_model_loading(data, loader, count):
    reject_before_loader(data, loader, row_ids=[f"outside:{index}" for index in range(count)])


@pytest.mark.parametrize("value", [True, 0, -1, 512.0, 512 * 1024 * 1024 + 1])
def test_reference_byte_cap_is_a_bounded_exact_integer(data, loader, value):
    reject_before_loader(data, loader, max_reference_bytes=value)


@pytest.mark.parametrize("field,value", [("schema", "rows-only/v1"), ("domain", "security_ir"),
    ("embedding_dimension", 768), ("embedding_dimension", True),
    ("embedding_model", "Alibaba-NLP/gte-multilingual-base"), ("embedding_revision", "f" * 40),
    ("proof_authority", True), ("source_semantics_verified", True), ("real_world_corpus_used", True)])
def test_corpus_header_identity_and_nonpromotion_are_authenticated(data, loader, field, value):
    data["corpus"][field] = value
    repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("change", ["extra", "missing"])
def test_corpus_header_has_closed_fields(data, loader, change):
    if change == "extra":
        data["corpus"]["converted_native_v3"] = True
    else:
        del data["corpus"]["source_license"]
    repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("field,value", [("schema", "modal-latent-formula-checkpoint/v1"),
    ("domain_id", "security_ir"), ("dimension", 768), ("dimension", True),
    ("architecture", "other-decoder/v1"), ("qualified", True), ("admitted", None),
    ("proof_authority", True), ("source_semantics_verified", True),
    ("publication_performed", True)])
def test_checkpoint_profile_cannot_be_selected_by_matching_width_alone(data, loader, field, value):
    data["checkpoint"][field] = value
    repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("change", ["unknown_source", "wrong_scope", "missing_declarations", "wrong_codec"])
def test_unrecognized_source_or_codec_profile_is_refused_before_loading(data, loader, change):
    checkpoint = data["checkpoint"]
    if change == "unknown_source": checkpoint["implementation"]["runtime"] = "f" * 64
    elif change == "wrong_scope": checkpoint["implementation"]["scope"] = "all_sources_verified"
    elif change == "missing_declarations": checkpoint["implementation"].pop("dependencies")
    else: checkpoint["codec"]["schema"] = "free-text/v1"
    repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("value", [True, 0, 1, 512.0])
def test_original_targets_respect_exact_codec_token_configuration(data, loader, value):
    data["checkpoint"]["config"]["max_target_tokens"] = value
    repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("change", ["wrong_count", "missing_split", "extra_split", "boolean_count", "zero_count"])
def test_split_counts_describe_the_entire_original_corpus(data, loader, change):
    counts = data["corpus"]["splits"]
    if change == "wrong_count": counts["train"] = 3
    elif change == "missing_split": counts.pop("validation")
    elif change == "extra_split": counts["canary"] = 0
    elif change == "boolean_count": counts["train"] = True
    else: counts["test"] = 0
    repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("change", ["extra", "missing", "duplicate_id", "wrong_split", "empty_id", "empty_group",
    "source_digest", "embedding_digest", "wrong_width", "boolean_vector", "target_not_object", "evidence_not_object"])
def test_all_corpus_rows_are_checked_even_when_not_selected(data, loader, change):
    row = data["corpus"]["rows"][0]  # Training row is outside the default test selection.
    if change == "extra": row["new_embedding"] = True
    elif change == "missing": row.pop("native_evidence")
    elif change == "duplicate_id": row["id"] = data["corpus"]["rows"][1]["id"]
    elif change == "wrong_split": row["split"] = "canary"
    elif change == "empty_id": row["id"] = ""
    elif change == "empty_group": row["group_id"] = ""
    elif change == "source_digest": row["source_sha256"] = "f" * 64
    elif change == "embedding_digest": row["embedding_sha256"] = "f" * 64
    elif change == "wrong_width": row["embedding"].pop()
    elif change == "boolean_vector": row["embedding"][0] = True
    elif change == "target_not_object": row["target"] = []
    else: row["native_evidence"] = []
    repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("manifest", ["training_manifest", "validation_manifest"])
@pytest.mark.parametrize("change", ["source_sha256", "embedding_sha256", "target_sha256", "id", "order", "missing", "extra"])
def test_checkpoint_manifests_match_exact_original_rows_and_order(data, loader, manifest, change):
    rows = data["checkpoint"][manifest]
    if change in {"source_sha256", "embedding_sha256", "target_sha256"}: rows[0][change] = "f" * 64
    elif change == "id": rows[0]["id"] = "foreign:record"
    elif change == "order": rows.reverse()
    elif change == "missing": rows.pop()
    else: rows[0]["split"] = "train"
    repin(data)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("field", ["source_text", "embedding", "target"])
def test_repinning_corpus_does_not_rewrite_checkpoint_training_history(data, loader, field):
    row = data["corpus"]["rows"][0]
    if field == "source_text": row[field] += " Changed."
    elif field == "embedding": row[field][0] += 0.25
    else: row[field]["document"]["action"] = "view"
    repin(data, row_digests=True)
    reject_before_loader(data, loader)


@pytest.mark.parametrize("split", SPLITS)
def test_oov_targets_in_any_original_split_are_refused_without_fitting(data, loader, split):
    row = next(row for row in data["corpus"]["rows"] if row["split"] == split)
    row["target"]["document"]["action"] = "unseen-operation"
    repin(data, manifests=True)
    reject_before_loader(data, loader)


def test_missing_original_corpus_package_file_never_uses_native_cache(data, loader):
    data["manifest"]["files"].pop("authored-corpus.json")
    data["manifest_pin"] = shared.write_json(data["package_dir"] / "manifest.json", data["manifest"])
    reject_before_loader(data, loader)


def test_absent_checkpoint_original_manifest_never_infers_history_from_cache_labels(data, loader):
    data["checkpoint"].pop("training_manifest")
    repin(data)
    reject_before_loader(data, loader)


def test_identical_corpus_at_different_declared_path_is_not_a_substitute(data, loader, tmp_path):
    copy = tmp_path / "same-corpus.json"
    copy.write_bytes(Path(data["corpus_pin"]["path"]).read_bytes())
    reject_before_loader(data, loader, corpus_pin=shared.pin(copy))


@pytest.mark.parametrize("name", ["authored-corpus.json", "checkpoint.json", "manifest.json"])
def test_changed_package_bytes_refuse_before_loader(data, loader, name):
    path = data["package_dir"] / name
    path.write_bytes(path.read_bytes() + b" ")
    reject_before_loader(data, loader)


def test_duplicate_raw_corpus_json_keys_are_rejected(data, loader):
    path = data["package_dir"] / "authored-corpus.json"
    encoded = json.dumps(data["corpus"], sort_keys=True)
    path.write_text('{"domain":"intent_ir",' + encoded[1:], encoding="utf-8")
    data["corpus_pin"] = shared.pin(path)
    data["manifest"]["files"]["authored-corpus.json"] = {key: data["corpus_pin"][key] for key in ("bytes", "sha256")}
    data["manifest_pin"] = shared.write_json(data["package_dir"] / "manifest.json", data["manifest"])
    reject_before_loader(data, loader)


@pytest.mark.parametrize("phase", ["load", "before_infer", "after_infer"])
@pytest.mark.parametrize("name", ["authored-corpus.json", "checkpoint.json", "manifest.json"])
def test_each_package_endpoint_is_fenced_at_load_and_inference_boundaries(data, loader, phase, name):
    path = data["package_dir"] / name
    def change():
        path.write_bytes(path.read_bytes() + b" ")
    if phase == "load":
        loader["after_load"] = change
        with pytest.raises(original.OriginalCorpusRuntimeError):
            open_original(data)
        assert len(loader["calls"]) == 1 and loader["loaded"][0].calls == []
        return
    selected = open_original(data)
    if phase == "before_infer": change()
    else: loader["loaded"][0].after_infer = change
    with pytest.raises(original.OriginalCorpusRuntimeError):
        selected.infer_cached()
    assert len(loader["loaded"][0].calls) == (0 if phase == "before_infer" else 1)


def test_loader_factory_mutation_does_not_replace_owned_plan(data, loader):
    loader["mutate_factory"] = True
    selected = open_original(data)
    assert selected.infer_cached()["raw_candidate_report"]["received_ids"] == options(data)["row_ids"]
    assert prepare(data)["package_manifest"] == data["manifest"]


def test_decoder_input_mutation_is_refused_and_original_corpus_is_unchanged(data, loader):
    saved = Path(data["corpus_pin"]["path"]).read_bytes()
    selected = open_original(data)
    loader["loaded"][0].mutate_inputs = True
    with pytest.raises(original.OriginalCorpusRuntimeError):
        selected.infer_cached()
    assert Path(data["corpus_pin"]["path"]).read_bytes() == saved


def test_plan_and_description_copies_do_not_control_runtime_selection(data, loader):
    plan = prepare(data)
    plan["inputs"][0]["embedding"][0] = 999.0
    plan["authority"]["proof_authority"] = True
    selected = open_original(data)
    desc = selected.describe()
    desc["authority"]["proof_authority"] = True
    assert not any(selected.describe()["authority"].values())
    selected.infer_cached()
    assert loader["loaded"][0].calls[0]["rows"] == prepare(data)["inputs"]


def test_caller_options_are_captured_before_loader_and_output_is_detached(data, loader):
    args = options(data)
    request = deepcopy(data["request"])
    def mutate_callers():
        args["row_ids"].reverse()
        args["corpus_pin"]["sha256"] = "f" * 64
        request["ir_family_id"] = "security_ir"
    loader["after_load"] = mutate_callers
    selected = hub.open_ir_original_corpus_autoencoder(data["directory_pin"],
        list(data["pins"].values()), request, **args)
    expected = options(data)["row_ids"]
    first = selected.infer_cached()
    first["raw_candidate_report"]["received_ids"].clear()
    first["authority"]["proof_authority"] = True
    second = selected.infer_cached()
    assert second["raw_candidate_report"]["received_ids"] == expected
    assert not any(second["authority"].values())


def test_infer_cached_accepts_no_replacement_vectors_targets_or_options(data, loader):
    selected = open_original(data)
    with pytest.raises(TypeError):
        selected.infer_cached(rows=[{"embedding": [0.0] * 384, "target": {}}])
    assert loader["loaded"][0].calls == []
