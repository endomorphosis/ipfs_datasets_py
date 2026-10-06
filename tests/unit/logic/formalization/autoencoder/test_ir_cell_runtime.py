"""Guarded metadata dispatch and retained-row replay, without numerical models.

Miniature private packages are integrity fixtures. The single loader spy proves
dispatch order and row isolation; it does not qualify an encoder or decoder.
"""

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
from ipfs_datasets_py.logic.formalization.autoencoder import ir_cell_runtime as runtime
from tests.unit.logic.formalization.autoencoder import test_ir_cell_routing as shared


SUPPORTED = ("legal_ir", "security_ir", "intent_ir")
SPLITS = ("train", "validation", "test", "canary")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def vector_sha(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode())


def cached_row(family, split, index):
    text = f"Private {family} {split} source {index}."
    embedding = [((index + offset) % 17 - 8) / 32.0 for offset in range(384)]
    return {"id": f"{family}:{split}:{index}", "source_text": text,
            "source_sha256": sha(text.encode()), "embedding": embedding,
            "embedding_sha256": vector_sha(embedding),
            "embedding_token_ids_sha256": sha(f"declared-token-ids-{index}".encode()),
            "group_id": f"{family}:group:{index}", "split": split,
            "target": {"gold_only_marker": f"never-pass-{split}-{index}"},
            "wording_style": index}


def make_replay(tmp_path, family="legal_ir"):
    data = shared.make_inventory(tmp_path)
    document = data["documents"][(family, 384)]
    source = tmp_path / "synthetic-checkpoint.json"
    source.write_bytes(json.dumps({"fixture": "not a model", "family": family}).encode())
    package_dir = tmp_path / "private-package" / family
    manifest = hub.build_package(family, source, package_dir,
                                 provenance={"scope": "synthetic integrity fixture"},
                                 validation={"model_executed": False})
    checkpoint = shared.pin(package_dir / "checkpoint.json")
    document["existing_checkpoint_evidence"] = [{
        "role": "synthetic declared local package", "receipt": checkpoint,
        "dimension_role": "input_embedding", "input_width": 384,
        "source_access": "unknown", "teacher_qualified": False,
    }]
    rows = {}
    for split, record in zip(SPLITS, document["existing_cached_vector_rows"]):
        rows[split] = [cached_row(family, split, index) for index in (0, 1, 2)]
        record["receipt"] = shared.write_json(Path(record["receipt"]["path"]), {"rows": rows[split]})
    shared.rewrite_cell(data, family, 384)
    data.update(family=family, package_dir=package_dir, manifest=manifest,
                manifest_pin=shared.pin(package_dir / "manifest.json"),
                rows=rows, request=shared.request(family, checkpoint=checkpoint["sha256"]))
    return data


@pytest.fixture
def replay(tmp_path):
    return make_replay(tmp_path)


class InertRuntime:
    def __init__(self, family):
        self.family = family
        self.calls = []
        self.mutate_inputs = False
        self.after_infer = None

    def describe(self):
        return {"domain_id": self.family, "scope": "inert loader spy", "model_executed": False}

    def infer(self, rows, **options):
        self.calls.append({"rows": deepcopy(rows), "options": deepcopy(options)})
        if self.mutate_inputs:
            rows[0]["embedding"][0] = 999.0
            rows[0]["target"] = {"injected": "not from the original cache"}
        if self.after_infer is not None:
            self.after_infer()
        return {"scope": "inert loader spy", "received_ids": [row["id"] for row in rows]}


@pytest.fixture
def loader(monkeypatch):
    calls = []
    loaded = []
    controls = {"calls": calls, "loaded": loaded, "after_load": None, "mutate_factory": False}

    def instantiate(manifest, paths):
        calls.append({"manifest": deepcopy(manifest), "paths": dict(paths)})
        instance = InertRuntime(manifest["domain_id"])
        loaded.append(instance)
        if controls["mutate_factory"]:
            manifest["domain_id"] = "foreign_ir"
            manifest["files"].clear()
            paths.clear()
        if controls["after_load"] is not None:
            controls["after_load"]()
        return instance

    # This is the only production monkeypatch: all metadata parsing, hashing,
    # row selection, path association and package initializers remain real.
    monkeypatch.setattr(hub, "_instantiate", instantiate)
    return controls


def arguments(data, *, split="test", ids=None):
    return {"package_manifest_pin": deepcopy(data["manifest_pin"]), "cache_split": split,
            "row_ids": [row["id"] for row in data["rows"][split]] if ids is None else ids}


def prepare(data, **changes):
    options = arguments(data)
    options.update(changes)
    return runtime.prepare_ir_cell_runtime(data["directory_pin"], list(data["pins"].values()),
                                           data["request"], **options)


def open_replay(data, **changes):
    options = arguments(data)
    options.update(changes)
    return hub.open_ir_cell_autoencoder(data["directory_pin"], list(data["pins"].values()),
                                        data["request"], **options)


def reject_before_load(data, loader, **changes):
    with pytest.raises(ValueError):
        open_replay(data, **changes)
    assert loader["calls"] == []
    assert loader["loaded"] == []


def rewrite_manifest(data):
    data["manifest_pin"] = shared.write_json(data["package_dir"] / "manifest.json", data["manifest"])


def rewrite_cache(data, split="test"):
    document = data["documents"][(data["family"], 384)]
    record = next(record for record in document["existing_cached_vector_rows"] if record["split"] == split)
    record["receipt"] = shared.write_json(Path(record["receipt"]["path"]), {"rows": data["rows"][split]})
    shared.rewrite_cell(data, data["family"], 384)


@pytest.mark.parametrize("family", SUPPORTED)
def test_supported_local_package_is_selected_without_default_or_encoder(tmp_path, loader, family):
    data = make_replay(tmp_path, family)
    selected = open_replay(data)
    assert len(loader["calls"]) == 1
    call = loader["calls"][0]
    assert call["manifest"] == data["manifest"]
    assert call["paths"]["checkpoint.json"] == Path(data["documents"][(family, 384)]["existing_checkpoint_evidence"][0]["receipt"]["path"])
    assert loader["loaded"][0].calls == []
    assert callable(selected.describe) and callable(selected.infer_cached)
    assert not hasattr(selected, "infer_texts")


@pytest.mark.parametrize("family,width", [cell for cell in shared.CELLS if cell not in [(family, 384) for family in SUPPORTED]])
def test_other_cells_reject_before_loader(replay, loader, family, width):
    evidence = replay["documents"][(family, width)]["existing_checkpoint_evidence"]
    role = evidence[0]["dimension_role"] if evidence else "input_embedding"
    checkpoint = evidence[0]["receipt"]["sha256"] if evidence else None
    replay["request"] = shared.request(family, width, role=role, checkpoint=checkpoint)
    reject_before_load(replay, loader)


@pytest.mark.parametrize("field,value", [
    ("ir_family_id", "foreign_ir"), ("dimension", 786), ("dimension", True),
    ("dimension", 384.0), ("dimension_role", "latent"), ("dimension_role", "projection"),
    ("task_id", "native_ir_to_logic"), ("task_id", "retained_source_byte_restoration"),
    ("task_id", "native_ir_to_source"), ("task_id", "structural_reconstruction"),
    ("checkpoint_sha256", None), ("checkpoint_sha256", "f" * 64),
])
def test_request_is_rejected_before_any_loader(replay, loader, field, value):
    replay["request"][field] = value
    reject_before_load(replay, loader)


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_request_closed_contract_precedes_runtime_loading(replay, loader, mutation):
    if mutation == "extra":
        replay["request"]["fallback_dimension"] = 8
    else:
        replay["request"].pop("task_id")
    reject_before_load(replay, loader)


@pytest.mark.parametrize("split", SPLITS)
def test_split_and_requested_order_are_exact_and_targets_never_reach_runtime(replay, loader, split):
    rows = replay["rows"][split]
    ids = [rows[2]["id"], rows[0]["id"]]
    selected = open_replay(replay, cache_split=split, row_ids=ids)
    selected.infer_cached()
    received = loader["loaded"][0].calls[0]["rows"]
    assert [row["id"] for row in received] == ids
    for row, source in zip(received, [rows[2], rows[0]]):
        assert row["embedding"] == source["embedding"]
        assert row["source_text"] == source["source_text"]
        assert "target" not in row
        assert "gold_only_marker" not in json.dumps(row)


@pytest.mark.parametrize("selection", ["empty", "duplicate", "missing", "other_split", "too_many", "nonstring"])
def test_row_selection_rejects_before_loader(replay, loader, selection):
    ids = [row["id"] for row in replay["rows"]["test"]]
    invalid = {"empty": [], "duplicate": [ids[0], ids[0]], "missing": ["absent"],
               "other_split": [replay["rows"]["train"][0]["id"]],
               "too_many": [f"row-{index}" for index in range(65)], "nonstring": [True]}[selection]
    reject_before_load(replay, loader, row_ids=invalid)


@pytest.mark.parametrize("split", ["all", "training", "", None, True])
def test_only_an_explicit_declared_cache_split_can_be_selected(replay, loader, split):
    reject_before_load(replay, loader, cache_split=split)


@pytest.mark.parametrize("field,value", [
    ("domain_id", "security_ir"), ("dimension", 768), ("runtime", "domain_384_v1"),
    ("release_stage", "qualified"), ("proof_authority", True),
])
def test_package_identity_and_authority_controls_precede_load(replay, loader, field, value):
    replay["manifest"][field] = value
    rewrite_manifest(replay)
    reject_before_load(replay, loader)


def test_package_must_bind_the_exact_selected_checkpoint_path_even_for_identical_bytes(replay, loader):
    original = replay["package_dir"] / "checkpoint.json"
    copy = replay["package_dir"] / "same-bytes-other-path.json"
    copy.write_bytes(original.read_bytes())
    replay["manifest"]["checkpoint_file"] = copy.name
    replay["manifest"]["files"] = {copy.name: dict(replay["manifest"]["files"][original.name])}
    rewrite_manifest(replay)
    reject_before_load(replay, loader)


def test_package_copy_cannot_replace_the_selected_original_path(replay, loader, tmp_path):
    copy = tmp_path / "copied-package"
    copy.mkdir()
    for name in ("manifest.json", "checkpoint.json"):
        (copy / name).write_bytes((replay["package_dir"] / name).read_bytes())
    reject_before_load(replay, loader, package_manifest_pin=shared.pin(copy / "manifest.json"))


@pytest.mark.parametrize("artifact", ["checkpoint", "manifest", "cache"])
def test_changed_artifact_bytes_are_rejected_before_loader(replay, loader, artifact):
    if artifact == "checkpoint":
        path = replay["package_dir"] / "checkpoint.json"
    elif artifact == "manifest":
        path = Path(replay["manifest_pin"]["path"])
    else:
        path = Path(next(record for record in replay["documents"][("legal_ir", 384)]["existing_cached_vector_rows"]
                         if record["split"] == "test")["receipt"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    reject_before_load(replay, loader)


@pytest.mark.parametrize("field,value", [
    ("source_sha256", "0" * 64), ("embedding_sha256", "0" * 64),
    ("embedding_token_ids_sha256", "unverified"), ("source_text", ""),
    ("group_id", ""), ("split", "train"), ("wording_style", True),
    ("id", ""), ("target", None),
])
def test_malformed_or_inconsistent_cached_row_fails_before_load(replay, loader, field, value):
    replay["rows"]["test"][0][field] = value
    rewrite_cache(replay)
    reject_before_load(replay, loader)


@pytest.mark.parametrize("mutation", ["short", "long", "bool", "string", "nan", "inf"])
def test_cached_vectors_are_exact_finite_numeric_384d_rows(replay, loader, mutation):
    row = replay["rows"]["test"][0]
    if mutation == "short":
        row["embedding"].pop()
    elif mutation == "long":
        row["embedding"].append(0.0)
    else:
        row["embedding"][0] = {"bool": True, "string": "0.0", "nan": float("nan"), "inf": float("inf")}[mutation]
    if mutation not in ("nan", "inf"):
        row["embedding_sha256"] = vector_sha(row["embedding"])
        rewrite_cache(replay)
    else:
        # JSON NaN/Infinity are rejected even if the containing file is pinned.
        document = replay["documents"][("legal_ir", 384)]
        record = next(record for record in document["existing_cached_vector_rows"] if record["split"] == "test")
        Path(record["receipt"]["path"]).write_bytes(json.dumps({"rows": replay["rows"]["test"]}).encode())
        record["receipt"] = shared.pin(record["receipt"]["path"])
        shared.rewrite_cell(replay)
    reject_before_load(replay, loader)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate_id", "unselected_bad_row"])
def test_all_stored_rows_have_a_closed_consistent_schema_before_selection(replay, loader, mutation):
    rows = replay["rows"]["test"]
    if mutation == "missing":
        rows[0].pop("embedding_token_ids_sha256")
    elif mutation == "extra":
        rows[0]["teacher_hint"] = "gold"
    elif mutation == "duplicate_id":
        rows[1]["id"] = rows[0]["id"]
    else:
        rows[2]["source_sha256"] = "0" * 64
    rewrite_cache(replay)
    reject_before_load(replay, loader, row_ids=[rows[0]["id"]])


@pytest.mark.parametrize("mutation", ["list", "missing", "extra"])
def test_cached_file_has_exact_original_rows_envelope(replay, loader, mutation):
    document = replay["documents"][("legal_ir", 384)]
    record = next(record for record in document["existing_cached_vector_rows"] if record["split"] == "test")
    value = {"list": replay["rows"]["test"], "missing": {},
             "extra": {"rows": replay["rows"]["test"], "generated": True}}[mutation]
    record["receipt"] = shared.write_json(Path(record["receipt"]["path"]), value)
    shared.rewrite_cell(replay)
    reject_before_load(replay, loader)


@pytest.mark.parametrize("artifact", ["checkpoint", "manifest", "cache"])
def test_artifact_drift_after_open_is_refused_before_cached_inference(replay, loader, artifact):
    selected = open_replay(replay)
    if artifact == "checkpoint":
        path = replay["package_dir"] / "checkpoint.json"
    elif artifact == "manifest":
        path = Path(replay["manifest_pin"]["path"])
    else:
        path = Path(next(record for record in replay["documents"][("legal_ir", 384)]["existing_cached_vector_rows"]
                         if record["split"] == "test")["receipt"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        selected.infer_cached()
    assert len(loader["calls"]) == 1
    assert loader["loaded"][0].calls == []


def test_caller_mutation_after_open_cannot_relabel_the_dispatch_or_rows(replay, loader):
    selected = open_replay(replay)
    original_ids = [row["id"] for row in replay["rows"]["test"]]
    replay["request"]["ir_family_id"] = "security_ir"
    replay["manifest_pin"]["sha256"] = "0" * 64
    replay["pins"].clear()
    replay["directory_pin"]["sha256"] = "0" * 64
    selected.infer_cached()
    received = loader["loaded"][0].calls[0]["rows"]
    assert [row["id"] for row in received] == original_ids


def test_each_cached_replay_receives_fresh_rows_without_gold_targets(replay, loader):
    selected = open_replay(replay)
    loader["loaded"][0].mutate_inputs = True
    with pytest.raises(ValueError, match="mutated cached call inputs"):
        selected.infer_cached()
    first = deepcopy(loader["loaded"][0].calls[0]["rows"])
    loader["loaded"][0].mutate_inputs = False
    selected.infer_cached()
    assert loader["loaded"][0].calls[1]["rows"] == first
    assert all("target" not in row for row in first)


def test_real_package_initializers_and_lightweight_leaf_origins_are_present():
    package_root = Path(hub.__file__).resolve().parents[3]
    for name, relative in [
        ("ipfs_datasets_py", "__init__.py"),
        ("ipfs_datasets_py.logic", "logic/__init__.py"),
        ("ipfs_datasets_py.logic.formalization", "logic/formalization/__init__.py"),
        ("ipfs_datasets_py.logic.formalization.autoencoder", "logic/formalization/autoencoder/__init__.py"),
        ("ipfs_datasets_py.router_deps", "router_deps.py"),
    ]:
        module = importlib.import_module(name)
        assert module.__spec__.loader is not None
        assert Path(module.__file__).resolve() == package_root / relative
    assert runtime.__file__ and hub.__file__
    assert not any(name == root or name.startswith(root + ".")
                   for name in sys.modules for root in (
                       "torch", "numpy", "sentence_transformers", "transformers",
                       "huggingface_hub", "duckdb", "ipfs_accelerate_py"))


def test_preparation_is_target_free_and_authenticity_never_becomes_quality(replay, loader):
    before = deepcopy(replay)
    plan = prepare(replay)
    assert plan["schema"] == "ir-cell-cached-runtime-plan/v1"
    assert plan["route"]["request"] == replay["request"]
    assert plan["package_manifest_receipt"] == replay["manifest_pin"]
    assert plan["package_manifest"] == replay["manifest"]
    assert plan["cache_split"] == "test"
    assert plan["row_ids"] == [row["id"] for row in replay["rows"]["test"]]
    for supplied, original, receipt in zip(plan["inputs"], replay["rows"]["test"], plan["row_receipts"]):
        assert set(supplied) == {"id", "source_text", "embedding"}
        assert supplied == {key: original[key] for key in supplied}
        for field in ("id", "split", "group_id", "wording_style", "source_sha256",
                      "embedding_sha256", "embedding_token_ids_sha256"):
            assert receipt[field] == original[field]
        assert receipt["token_provenance_qualified"] is False
    assert plan["budget_status"]["qualified_source_token_limit"] is None
    assert plan["budget_status"]["source_token_budget_qualified"] is False
    assert plan["route"]["provenance"]["embedding_producer_execution_authenticated"] is False
    assert plan["route"]["declared_compatibility"]["checkpoint_task_binding"] == "unknown"
    assert not any(plan["authority"].values())
    assert loader["calls"] == []
    assert replay == before


def test_returned_preparation_is_isolated_from_caller_and_later_preparation(replay, loader):
    baseline = prepare(replay)
    changed = prepare(replay)
    changed["route"]["request"]["ir_family_id"] = "foreign_ir"
    changed["package_manifest"]["files"].clear()
    changed["inputs"][0]["embedding"][0] = 999.0
    changed["row_receipts"][0]["id"] = "foreign"
    assert prepare(replay) == baseline
    assert loader["calls"] == []


def test_description_and_inference_report_keep_runtime_output_under_false_authority(replay, loader):
    selected = open_replay(replay)
    before = selected.describe()
    assert before["model_load_performed"] is True
    assert before["cached_inference_executed"] is False
    assert not any(before["authority"].values())
    assert "gold_only_marker" not in json.dumps(before)
    result = selected.infer_cached()
    assert result["schema"] == "ir-cell-cached-inference/v1"
    assert result["model_inference_executed"] is True
    assert result["raw_candidate_report"]["scope"] == "inert loader spy"
    assert not any(result["authority"].values())
    assert selected.describe()["cached_inference_executed"] is True
    assert "gold_only_marker" not in json.dumps(result)


def test_mutating_description_or_prior_report_cannot_change_later_row_selection(replay, loader):
    selected = open_replay(replay)
    description = selected.describe()
    description["authority"]["quality_qualified"] = True
    result = selected.infer_cached()
    result["row_receipts"][0]["id"] = "relabelled"
    result["raw_candidate_report"]["received_ids"].clear()
    again = selected.infer_cached()
    assert again["row_receipts"][0]["id"] == replay["rows"]["test"][0]["id"]
    assert again["raw_candidate_report"]["received_ids"] == [row["id"] for row in replay["rows"]["test"]]
    assert not any(selected.describe()["authority"].values())


def test_factory_cannot_relabel_mutable_manifest_or_path_arguments(replay, loader):
    loader["mutate_factory"] = True
    selected = open_replay(replay)
    selected.infer_cached()
    assert loader["calls"][0]["manifest"] == replay["manifest"]
    assert len(loader["loaded"][0].calls) == 1
    assert not any(selected.describe()["authority"].values())


@pytest.mark.parametrize("artifact", ["checkpoint", "manifest", "cache"])
def test_load_time_artifact_drift_prevents_wrapper_publication(replay, loader, artifact):
    if artifact == "checkpoint":
        path = replay["package_dir"] / "checkpoint.json"
    elif artifact == "manifest":
        path = Path(replay["manifest_pin"]["path"])
    else:
        record = next(record for record in replay["documents"][("legal_ir", 384)]["existing_cached_vector_rows"]
                      if record["split"] == "test")
        path = Path(record["receipt"]["path"])
    loader["after_load"] = lambda: path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        open_replay(replay)
    assert len(loader["calls"]) == 1
    assert loader["loaded"][0].calls == []


@pytest.mark.parametrize("artifact", ["checkpoint", "manifest", "cache"])
def test_inference_time_artifact_drift_refuses_the_runtime_result(replay, loader, artifact):
    selected = open_replay(replay)
    if artifact == "checkpoint":
        path = replay["package_dir"] / "checkpoint.json"
    elif artifact == "manifest":
        path = Path(replay["manifest_pin"]["path"])
    else:
        record = next(record for record in replay["documents"][("legal_ir", 384)]["existing_cached_vector_rows"]
                      if record["split"] == "test")
        path = Path(record["receipt"]["path"])
    loader["loaded"][0].after_infer = lambda: path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        selected.infer_cached()
    assert len(loader["loaded"][0].calls) == 1


@pytest.mark.parametrize("count", [64, 65])
def test_bounded_row_selection_accepts_64_and_refuses_65_existing_rows(replay, loader, count):
    replay["rows"]["test"] = [cached_row("legal_ir", "test", index) for index in range(count)]
    rewrite_cache(replay)
    if count == 65:
        reject_before_load(replay, loader)
    else:
        selected = open_replay(replay)
        selected.infer_cached()
        assert len(loader["loaded"][0].calls[0]["rows"]) == 64


@pytest.mark.parametrize("length", [16384, 16385])
def test_source_character_bound_is_checked_without_retained_text_generation(replay, loader, length):
    row = replay["rows"]["test"][0]
    row["source_text"] = "x" * length
    row["source_sha256"] = sha(row["source_text"].encode())
    rewrite_cache(replay)
    if length == 16385:
        reject_before_load(replay, loader)
    else:
        open_replay(replay)
        assert len(loader["calls"]) == 1


def test_reference_byte_cap_is_enforced_before_loader(replay, loader):
    reject_before_load(replay, loader, max_reference_bytes=8)


def test_a_different_foreign_cells_checkpoint_cannot_be_used_as_a_donor_runtime(replay, loader):
    replay["request"]["checkpoint_sha256"] = shared.checkpoint_sha(replay, "security_ir", 384)
    reject_before_load(replay, loader)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign_payload"])
def test_selected_cache_and_checkpoint_records_are_bound_to_the_requested_cell(replay, loader, mutation):
    document = replay["documents"][("legal_ir", 384)]
    if mutation == "missing":
        document["existing_cached_vector_rows"] = [record for record in document["existing_cached_vector_rows"]
                                                    if record["split"] != "test"]
    elif mutation == "duplicate":
        record = next(record for record in document["existing_cached_vector_rows"] if record["split"] == "test")
        document["existing_cached_vector_rows"].append(deepcopy(record))
    else:
        document["existing_checkpoint_evidence"][0]["payload_ir_family"] = "security_ir"
    shared.rewrite_cell(replay)
    reject_before_load(replay, loader)


@pytest.mark.parametrize("mutation", ["absent", "changed"])
def test_every_declared_package_file_authenticates_before_loader(replay, loader, mutation):
    path = replay["package_dir"] / "codec.json"
    path.write_bytes(b'{"synthetic": "codec reference"}')
    pinned = shared.pin(path)
    replay["manifest"]["files"][path.name] = {key: pinned[key] for key in ("bytes", "sha256")}
    rewrite_manifest(replay)
    if mutation == "absent":
        path.unlink()
    else:
        path.write_bytes(b'{"synthetic": "different codec reference"}')
    reject_before_load(replay, loader)


def test_caller_row_ids_are_copied_before_the_loader_receives_control(replay, loader):
    ids = [replay["rows"]["test"][1]["id"]]
    loader["after_load"] = ids.clear
    selected = open_replay(replay, row_ids=ids)
    selected.infer_cached()
    assert loader["loaded"][0].calls[0]["rows"][0]["id"] == replay["rows"]["test"][1]["id"]


def test_cached_replay_accepts_no_new_source_or_inference_options(replay, loader):
    selected = open_replay(replay)
    with pytest.raises(TypeError):
        selected.infer_cached(source_text="new source input")
    with pytest.raises(TypeError):
        selected.infer_cached([replay["rows"]["test"][0]])
    assert loader["loaded"][0].calls == []


def test_declared_token_and_group_metadata_are_not_claimed_as_executed_producer_provenance(replay, loader):
    row = replay["rows"]["test"][0]
    row["embedding_token_ids_sha256"] = "f" * 64
    row["group_id"] = "a different serialized group declaration"
    row["target"] = {"gold_only_marker": "changed target stays unavailable to the model"}
    rewrite_cache(replay)
    selected = open_replay(replay)
    report = selected.infer_cached()
    assert report["row_receipts"][0]["embedding_token_ids_sha256"] == "f" * 64
    assert report["row_receipts"][0]["group_id"] == row["group_id"]
    assert report["row_receipts"][0]["token_provenance_qualified"] is False
    assert report["authority"]["embedding_producer_execution_authenticated"] is False
    assert "gold_only_marker" not in json.dumps(loader["loaded"][0].calls[0]["rows"])


@pytest.mark.parametrize("family", SUPPORTED)
def test_legal_fixture_assistance_and_unknown_source_budget_are_explicit(tmp_path, loader, family):
    data = make_replay(tmp_path, family)
    selected = open_replay(data)
    description = selected.describe()
    assert description["load_may_execute_model_fixture"] is (family == "legal_ir")
    assert description["capability"]["legal_parser_assistance_expected"] is (family == "legal_ir")
    assert description["capability"]["new_source_inputs_supported"] is False
    assert description["capability"]["new_embeddings_generated"] is False
    assert description["budget_status"]["qualified_source_token_limit"] is None
    assert description["budget_status"]["source_token_budget_qualified"] is False
    assert description["authority"]["source_free_reconstruction_qualified"] is False
    assert description["authority"]["teacher_qualified"] is False


@pytest.mark.parametrize("artifact", ["manifest", "cache"])
def test_duplicate_json_keys_are_rejected_even_when_artifact_bytes_are_authenticated(replay, loader, artifact):
    if artifact == "manifest":
        path = Path(replay["manifest_pin"]["path"])
        path.write_bytes(b'{"domain_id":"security_ir",' + path.read_bytes()[1:])
        replay["manifest_pin"] = shared.pin(path)
    else:
        record = next(record for record in replay["documents"][("legal_ir", 384)]["existing_cached_vector_rows"]
                      if record["split"] == "test")
        path = Path(record["receipt"]["path"])
        path.write_bytes(b'{"rows":[],' + path.read_bytes()[1:])
        record["receipt"] = shared.pin(path)
        shared.rewrite_cell(replay)
    reject_before_load(replay, loader)


def test_overflowed_json_float_cannot_become_an_authenticated_cached_vector(replay, loader):
    record = next(record for record in replay["documents"][("legal_ir", 384)]["existing_cached_vector_rows"]
                  if record["split"] == "test")
    path = Path(record["receipt"]["path"])
    raw = path.read_bytes()
    begin = raw.index(b'"embedding": [') + len(b'"embedding": [')
    end = raw.index(b",", begin)
    path.write_bytes(raw[:begin] + b"1e999" + raw[end:])
    record["receipt"] = shared.pin(path)
    shared.rewrite_cell(replay)
    reject_before_load(replay, loader)
