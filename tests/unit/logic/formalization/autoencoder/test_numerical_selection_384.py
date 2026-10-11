"""Authored learned CALL tests; synthetic vectors do not establish GTE accuracy."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import numerical_selection_384 as api


def source(operator="argmax", position=0, arity=2, *, alias="np", suffix=""):
    names = [f"value_{i}{suffix}" for i in range(arity)]
    return (f"import numpy as {alias}\ndef choose{suffix}({', '.join(names)}):\n"
            f"    return {alias}.{operator}({names[position]})\n")


def unit(text=None, path="authored.py"):
    return api.prepare_selection_unit(source_bytes=(text or source()).encode(), path=path)


def authored_rows():
    rows = []
    for role, arity in (("train", 2), ("validation", 3), ("holdout", 4)):
        pairs = (("argmax", 0), ("argmin", 0), ("argmax", 1))
        if role == "holdout":
            pairs += (("argmin", 1), ("argmax", 2))
        for operator, position in pairs:
            rows.append(dict(source_text=source(operator, position, arity, suffix="_"+role),
                path=f"{role}/{operator}_{position}.py", unit_id=None, role=role,
                group_id=f"{role}/{operator}/{position}", provenance="independently_authored"))
    return rows


@pytest.fixture(scope="module")
def corpus():
    return api.prepare_selection_corpus(authored_rows())


def embeddings(corpus, roles):
    result = {}
    for index, row in enumerate(corpus["rows"]):
        if row["role"] not in roles:
            continue
        data = row["unit"]
        operator = data["target"]["document"]["operator"]
        position = data["canonical_roles"]["parameter_position"]
        result[data["unit_id"]] = [1. if operator == "numpy.argmax" else -1.,
            2.*position-1., .001*(index+1)] + [0.]*381
    return result


@pytest.fixture(scope="module")
def parent_file(tmp_path_factory):
    torch = pytest.importorskip("torch")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as legal
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        binding = dict(domain="legal_ir", lineage_id="current_legal_v2", dimension=384,
            runtime_profile="authored-numerical-selection-test/v1", core_sha256="a"*64)
        legal_ir = dict(rules=[dict(modality="O", actor="agency", action="save", object="report",
                                  conditions=[], exceptions=[], temporal=[])])
        rows = [dict(id="legal-parent-authored", source_text="The agency must save the report.",
            latent=[.5]+[0.]*383, embedding=[.3]+[0.]*383, canonical_ir=legal_ir)]
        parent = legal.build_checkpoint(binding, rows, [], hidden_size=16, token_embedding_dim=8,
                                        projection_width=4, batch_size=1)
        parent = legal.train(parent, rows, [], epochs=1, max_seconds=30)["checkpoint"]
        raw = api._wire(parent)
        path = tmp_path_factory.mktemp("numerical-legal-parent") / "parent.json"
        path.write_bytes(raw)
        return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def trained(corpus, parent_file):
    from pathlib import Path
    before = Path(parent_file["path"]).read_bytes()
    result = api.train_selection_384(corpus, embeddings(corpus, {"train", "validation"}),
                                     parent_projection=parent_file)
    assert Path(parent_file["path"]).read_bytes() == before
    return result["checkpoint"]


def test_exact_native_roles_and_public_logic_artifact_refs():
    text = "# café\n" + source("argmin", 1)
    result = unit(text)
    assert result["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    start = text.encode().index(b"def choose")
    assert result["start_byte"] == start
    assert result["end_byte"] == len(text.encode().rstrip(b"\n"))
    assert result["target"]["document"]["operator"] == "numpy.argmin"
    assert result["target"]["document"]["operand_ids"][-1] == "expr:parameter:1"
    assert result["canonical_roles"]["parameter_position"] == 1
    assert result["pending_obligation_ids"]
    assert result["span_ids"] and result["source_ref_ids"]
    assert {row["family"] for row in result["artifacts"]} == {"program", "first_order", "higher_order"}
    assert set(result["family_artifact_ids"]) <= {row["artifact_id"] for row in result["artifacts"]}
    assert result["source_obligations_discharged"] == 0 and not result["model_inference_executed"]


def test_alias_and_identifier_renames_collapse_clone_identity_not_file_identity():
    a = unit(source("argmax", 1, alias="np"))
    b = unit(source("argmax", 1, alias="numerics", suffix="_renamed"))
    assert a["target"] == b["target"] and a["clone_sha256"] == b["clone_sha256"]
    assert a["unit_id"] != b["unit_id"] and a["source_sha256"] != b["source_sha256"]
    direct = unit("from numpy import argmax as select\ndef choose(a, b):\n    return select(b)\n")
    assert direct["target"] == a["target"] and direct["clone_sha256"] == a["clone_sha256"]


@pytest.mark.parametrize("text", [
    "def f(x):\n    return np.argmax(x)\n",
    "import other as np\ndef f(x):\n    return np.argmax(x)\n",
    "import numpy as np\nnp = other\ndef f(x):\n    return np.argmax(x)\n",
    "import numpy as np\ndef f(np):\n    return np.argmax(np)\n",
    "import numpy as np\ndef f(x):\n    return np.argmax(np.abs(x))\n",
    "import numpy as np\ndef f(x):\n    return np.argmax(a=x)\n",
    "import numpy as np\ndef f(x):\n    return np.argmax(*x)\n",
    "import numpy as np\ndef f(x):\n    return np.argsort(x)\n",
    "import numpy as np\ndef f(x):\n    y = np.argmax(x)\n    return y\n",
    "import numpy as np\ndef f(x):\n    for a in x:\n        pass\n    return np.argmax(x)\n",
    "import numpy as np\ndef f(x):\n    assert x\n    return np.argmax(x)\n",
    "import numpy as np\ndef f(x=1):\n    return np.argmax(x)\n",
    "import numpy as np\ndef f(x: int):\n    return np.argmax(x)\n",
    "import numpy as np\n@other\ndef f(x):\n    return np.argmax(x)\n",
    "import numpy as np\ndef f(a,b,c,d,e):\n    return np.argmax(a)\n",
])
def test_unsupported_source_shapes_cannot_acquire_profile_coverage(text):
    with pytest.raises(api.NumericalSelectionError):
        unit(text)


def test_wrong_unit_identity_and_multiple_functions_rejected():
    with pytest.raises(api.NumericalSelectionError, match="identity"):
        api.prepare_selection_unit(source_bytes=source().encode(), path="authored.py", unit_id="0"*64)
    with pytest.raises(api.NumericalSelectionError, match="one exactly mapped"):
        unit(source()+"def second(a):\n    return a\n")


@pytest.mark.parametrize("damage", ["rename", "group", "source", "unreviewed", "tamper"])
def test_split_leakage_or_metadata_labels_cannot_be_resealed(corpus, damage):
    rows = authored_rows()
    if damage == "rename": rows[3]["source_text"] = source("argmax", 0, 2, alias="renamed")
    elif damage == "group": rows[3]["group_id"] = rows[0]["group_id"]
    elif damage == "source": rows[3]["source_text"] = rows[0]["source_text"]
    elif damage == "unreviewed": rows[0]["provenance"] = "benchmark"
    else:
        forged = deepcopy(corpus)
        forged["rows"][0]["unit"]["target"] = api._target("numpy.argmin", 0)
        forged["corpus_sha256"] = api._digest({k:v for k,v in forged.items() if k != "corpus_sha256"})
        with pytest.raises(api.NumericalSelectionError, match="exact replay"):
            api._corpus(forged)
        return
    with pytest.raises(api.NumericalSelectionError):
        api.prepare_selection_corpus(rows)


def test_holdout_vectors_are_rejected_before_shared_fit(corpus, parent_file, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("holdout-contaminated rows reached shared training")
    monkeypatch.setattr(api.shared, "train", forbidden)
    with pytest.raises(api.NumericalSelectionError, match="split population"):
        api.train_selection_384(corpus, embeddings(corpus, {"train","validation","holdout"}),
                                 parent_projection=parent_file)


def test_learned_reconstruction_and_unseen_target_count_without_parent_mutation(trained, corpus):
    heldout = embeddings(corpus, {"holdout"})
    result = api.evaluate_selection_384(trained, corpus, heldout)
    assert result["metrics"]["count"] == 5
    assert result["metrics"]["outside_training_coverage"] == 1  # unseen operand position2
    assert result["metrics"]["within_training_coverage"] == 4
    assert result["metrics"]["exact_targets"] == result["source_aligned_fragments"] == 4
    assert trained["checkpoint"]["lineage"]["parent_encoder_frozen"]
    assert not trained["checkpoint"]["lineage"]["random_parameters_used"]
    assert result["source_obligations_discharged"] == 0 and not result["holdout_used_for_selection"]
    assert all(not row["prediction"]["target_access"] and not row["candidate_replaced"] for row in result["inference"]["rows"])


@pytest.mark.parametrize("ablation", ["zero_head", "zero_projection", "shuffle_embeddings"])
def test_real_weight_ablations_are_retained_and_never_fixed_by_source(trained, corpus, ablation):
    result = api.evaluate_selection_384(trained, corpus, embeddings(corpus, {"holdout"}), weight_ablation=ablation)
    assert result["inference"]["weight_ablation"] == ablation
    if ablation in ("zero_head", "shuffle_embeddings"):
        assert result["source_aligned_fragments"] < 4
        assert any(row["status"] == "fail_open_source_mismatch" and row["matched_projection_refs"] is None
                   for row in result["inference"]["rows"])
    if ablation == "zero_projection":
        for row in result["inference"]["rows"]:
            assert row["prediction"]["projected_embedding"] == embeddings(corpus, {"holdout"})[row["unit_id"]]
    assert all(row["candidate_replaced"] is False for row in result["inference"]["rows"])


def test_target_free_runtime_and_candidate_bytes_preserved(trained, corpus, monkeypatch):
    runtime = api.NumericalSelectionRuntime384(trained)
    selected = next(r["unit"] for r in corpus["rows"] if r["role"] == "holdout")
    data = dict(source_text=selected["model_input_text"], path=selected["path"], unit_id=selected["unit_id"],
                embedding=embeddings(corpus, {"holdout"})[selected["unit_id"]])
    received = []
    original = runtime.runtime.infer
    def capture(rows, **kwargs):
        assert all(set(r) == {"id","source_text","embedding"} for r in rows)
        result = original(rows, **kwargs)
        received.append(deepcopy(result))
        return result
    monkeypatch.setattr(runtime.runtime, "infer", capture)
    result = runtime.infer([data])
    assert result["rows"][0]["prediction"] == received[0]["rows"][0]
    with pytest.raises(api.NumericalSelectionError, match="target-free"):
        runtime.infer([{**data, "target": selected["target"]}])


@pytest.mark.parametrize("damage", ["profile", "scalar_checkpoint", "parent", "head", "pins", "proof", "corpus"])
def test_checkpoint_separation_pins_lineage_and_authority(trained, damage):
    value = deepcopy(trained)
    if damage == "profile": value["profile"] = "source_program_scalar"
    elif damage == "scalar_checkpoint": value = value["checkpoint"]
    elif damage == "parent": value["parent_sha256"] = "0"*64
    elif damage == "head": value["checkpoint"]["head_state"]["bias"][0] += 1
    elif damage == "pins": value["producer"] = {}
    elif damage == "proof": value["proof_authority"] = True
    else: value["corpus_manifest"][0]["target_sha256"] = "0"*64
    with pytest.raises(ValueError):
        api.NumericalSelectionRuntime384(value)


def test_exact_checkpoint_reload_and_wrong_digest(trained, tmp_path):
    path = tmp_path / "numerical-selection.json"
    raw = api._wire(trained)
    path.write_bytes(raw)
    loaded = api.load_selection_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert loaded.checkpoint == trained
    with pytest.raises(api.NumericalSelectionError, match="bytes differ"):
        api.load_selection_checkpoint(path, expected_sha256="0"*64)
    alias = tmp_path / "linked.json"
    alias.symlink_to(path)
    with pytest.raises(api.NumericalSelectionError, match="regular"):
        api.load_selection_checkpoint(alias, expected_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("damage", ["duplicate", "nonfinite"])
def test_external_checkpoint_json_is_closed_even_with_matching_file_hash(trained, tmp_path, damage):
    raw = api._wire(trained)
    if damage == "duplicate":
        raw = b'{"profile":"numpy-unary-selection-384@1",' + raw[1:]
    else:
        raw = b'{"extra":NaN,' + raw[1:]
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="duplicate JSON|nonfinite JSON"):
        api.load_selection_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_parent_size_refused_before_loading_bytes(corpus, tmp_path, monkeypatch):
    from pathlib import Path
    parent = tmp_path / "oversized-parent.json"
    with parent.open("wb") as handle:
        handle.truncate(api.MAX_BYTES+1)
    original = Path.read_bytes
    def guarded(path):
        if path == parent:
            pytest.fail("oversized parent bytes were loaded")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    with pytest.raises(api.NumericalSelectionError, match="bounded regular"):
        api.train_selection_384(corpus, embeddings(corpus, {"train","validation"}),
            parent_projection=dict(path=str(parent),sha256="0"*64))


@pytest.mark.parametrize("field", ["unit_id", "source_sha256", "clone_sha256", "target_sha256", "group_id"])
def test_heldout_manifest_metadata_must_match_replayed_corpus(trained, corpus, field):
    changed = deepcopy(trained)
    row = next(r for r in changed["corpus_manifest"] if r["role"] == "holdout")
    row[field] = "independent-forged-group" if field == "group_id" else "0"*64
    # Train/validation still match their native manifests; evaluation must
    # additionally join the full held-out metadata to the exact source corpus.
    api.NumericalSelectionRuntime384(changed)
    with pytest.raises(api.NumericalSelectionError, match="manifest differs"):
        api.evaluate_selection_384(changed, corpus, embeddings(corpus, {"holdout"}))
