"""Current-source strict loading and authored diagnostic compatibility fixtures.

The explicit transition fixture authors old/new implementation maps. Its
monkeypatch is unit-test input, not qualification of either source revision.
The separate current-source test leaves implementation discovery unpatched.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_action_checkpoint_384 as api
from ipfs_datasets_py.logic.intent_ir.formalize import action_contracts as codec

SOURCE = "the agent must compute result; requires left > 0; ensures result = old(left) + old(right) and returned."


def digest(value):
    return hashlib.sha256(api.structured._raw(value)).hexdigest()


def checkpoint(*, historical=False, implementation=None):
    """Authored unit-vector classifier fixture, not trained or released weights."""
    target = codec.source_to_target(SOURCE)
    target["document"]["title"] = "a"
    template = deepcopy(target)
    template["document"]["title"] = None
    projection = {"projection_down.weight": [[0.] * 384], "projection_down.bias": [0.],
        "projection_up.weight": [[0.] for _ in range(384)], "projection_up.bias": [0.] * 384}
    state = dict(weights=[[1., -1.], *([[0., 0.]] * 383)], bias=[0., 0.])
    implementation = deepcopy(api.structured._implementation() if implementation is None else implementation)
    if historical:
        implementation["shared_runtime"]["numerical"]["files"]["tree_pin.py"] = api.OLD_TREE_SHA256
    manifests = []
    for label in ("training", "validation"):
        manifests.append([dict(id=label, **{key: hashlib.sha256((label + key).encode()).hexdigest()
            for key in ("source_sha256", "normalized_source_sha256", "embedding_sha256", "target_sha256")})])
    return dict(schema=api.structured.SCHEMA, domain_id="intent_ir", dimension=384,
        implementation=implementation,
        config=dict(ridges=[.01], embedding_provenance={"model_id": "authored-unit-vector"}),
        parent_sha256="a" * 64, parent_binding={"dimension": 384}, projection_width=1,
        projection_state=projection, projection_sha256=digest(projection),
        input_transform=dict(mean=[0.] * 384, scale=1., origin="training_projected_embeddings_only"),
        target_schema=dict(schema="fixed-typed-json-consensus/v1", shape=api.structured._shape(target),
            template=template, slots=[dict(path=["document", "title"], classes=["a", "z"])],
            origin="training_only", whole_target_memory=False),
        head_state=state, head_sha256=digest(state), training_manifest=manifests[0], validation_manifest=manifests[1],
        training=dict(selected_ridge=.01, test_used_for_selection=False, gradient_training_used=False),
        lineage=dict(parent_encoder_frozen=True, projection_tensors_inherited_exactly=list(api.structured.PROJECTION_KEYS),
            parent_modified=False, random_parameters_used=False), **api.structured.FALSE)


def write(directory, value):
    raw = api.structured._raw(value)
    checksum = hashlib.sha256(raw).hexdigest()
    path = directory / (checksum + ".json")
    path.write_bytes(raw)
    return path, checksum


def rows():
    return [dict(id="input", source_text=SOURCE, embedding=[1.] + [0.] * 383)]


@pytest.fixture
def authored_diagnostic_implementation(monkeypatch):
    """Author a new-pin expectation without changing any production policy.

    This lets the same transition and rejection cases run in a checkout with
    either reviewed diagnostic revision. All other discovered pins stay exact;
    the actual-current strict test below never requests this fixture.
    """
    actual = api.structured._implementation()
    assert api._tree_pin(actual) in {api.OLD_TREE_SHA256, api.NEW_TREE_SHA256}
    authored = deepcopy(actual)
    authored["shared_runtime"]["numerical"]["files"]["tree_pin.py"] = api.NEW_TREE_SHA256
    monkeypatch.setattr(api.structured, "_implementation", lambda: deepcopy(authored))
    return authored


def test_actual_current_checkpoint_is_strict_and_preserves_numerical_output(tmp_path):
    """Real current implementation pins; only numerical weights are authored."""
    implementation = api.structured._implementation()
    value = checkpoint(implementation=implementation)
    path, checksum = write(tmp_path, value)
    original = path.read_bytes()
    strict = api.structured.load_checkpoint(path, expected_sha256=checksum, expected_domain="intent_ir")
    runtime, receipt = api.load_intent_action_checkpoint_384(path, expected_sha256=checksum)
    assert receipt["mode"] == "strict" and receipt["applied"] is False
    assert receipt["changed_pins"] == []
    assert receipt["original_implementation"] == receipt["runtime_implementation"] == implementation
    assert runtime.checkpoint == value
    assert all(receipt[key] == expected for key, expected in api.FALSE.items())
    assert runtime.infer(rows()) == strict.infer(rows())
    assert api.verify_intent_action_checkpoint_compatibility(receipt, path=path, expected_sha256=checksum) == receipt
    assert api.structured._implementation() == implementation
    assert path.read_bytes() == original


@pytest.mark.parametrize("historical", [False, True])
def test_explicit_runtime_view_preserves_artifact_components_and_numerical_output(
        tmp_path, historical, authored_diagnostic_implementation):
    value = checkpoint(historical=historical, implementation=authored_diagnostic_implementation)
    path, checksum = write(tmp_path, value)
    original = path.read_bytes()
    if historical:
        with pytest.raises(ValueError, match="implementation pins differ"):
            api.structured.load_checkpoint(path, expected_sha256=checksum, expected_domain="intent_ir")
    runtime, receipt = api.load_intent_action_checkpoint_384(path, expected_sha256=checksum)
    assert receipt["applied"] is historical
    assert receipt["mode"] == ("known_tree_pin_stderr_diagnostic" if historical else "strict")
    assert receipt["profile"] == api.PROFILE and receipt["domain_id"] == "intent_ir"
    assert receipt["artifact_sha256"] == checksum
    changes = [dict(path=list(api.TREE_PIN_PATH), before=api.OLD_TREE_SHA256, after=api.NEW_TREE_SHA256)]
    assert receipt["changed_pins"] == (changes if historical else [])
    for key in value:
        if key != "implementation": assert runtime.checkpoint[key] == value[key]
    assert all(receipt[key] == expected for key, expected in api.FALSE.items())
    assert api.verify_intent_action_checkpoint_compatibility(receipt, path=path, expected_sha256=checksum) == receipt
    # Current-pinned authored fixture is an independent numerical comparator,
    # not a rewritten release artifact or a broadened strict loading policy.
    current = checkpoint(implementation=authored_diagnostic_implementation)
    strict_path, strict_sha = write(tmp_path, current)
    strict = api.structured.load_checkpoint(strict_path, expected_sha256=strict_sha, expected_domain="intent_ir")
    assert runtime.infer(rows()) == strict.infer(rows())
    assert path.read_bytes() == original


@pytest.mark.parametrize("change", ["unknown_old", "unknown_current", "reverse", "missing_tree", "ui",
    "intent_decoder", "intent_schema", "numerical", "runtime", "extra_pin"])
def test_every_other_pin_transition_is_rejected(tmp_path, monkeypatch, change, authored_diagnostic_implementation):
    value = checkpoint(historical=True, implementation=authored_diagnostic_implementation)
    old = value["implementation"]
    current = api.structured._implementation()
    if change == "unknown_old": old["shared_runtime"]["numerical"]["files"]["tree_pin.py"] = "b" * 64
    elif change == "unknown_current": current["shared_runtime"]["numerical"]["files"]["tree_pin.py"] = "b" * 64
    elif change == "reverse":
        old["shared_runtime"]["numerical"]["files"]["tree_pin.py"] = api.NEW_TREE_SHA256
        current["shared_runtime"]["numerical"]["files"]["tree_pin.py"] = api.OLD_TREE_SHA256
    elif change == "missing_tree": old["shared_runtime"]["numerical"]["files"].pop("tree_pin.py")
    elif change == "ui":
        old["shared_runtime"]["native"]["dependencies"]["ipfs_datasets_py.logic.ui_ux_ir.decoder"] = "d7be6bff3a1f1464d4783567b90942258ef718bc1c2b7e02938698ed4e619e57"
    elif change in {"intent_decoder", "intent_schema"}:
        module = "ipfs_datasets_py.logic.intent_ir." + ("decoder" if change == "intent_decoder" else "schema")
        old["shared_runtime"]["native"]["dependencies"][module] = "b" * 64
    elif change == "numerical": old["shared_runtime"]["numerical"]["files"]["modal_latent_formula.py"] = "b" * 64
    elif change == "runtime": old["runtime_sha256"] = "b" * 64
    else: old["shared_runtime"]["numerical"]["files"]["unexpected.py"] = "b" * 64
    monkeypatch.setattr(api.structured, "_implementation", lambda: deepcopy(current))
    path, checksum = write(tmp_path, value)
    with pytest.raises(ValueError, match="pin|implementation"):
        api.load_intent_action_checkpoint_384(path, expected_sha256=checksum)


@pytest.mark.parametrize("change", ["domain", "schema", "weight", "projection", "shape", "split", "authority", "extra"])
def test_ordinary_structured_validation_still_applies(tmp_path, change, authored_diagnostic_implementation):
    value = checkpoint(historical=True, implementation=authored_diagnostic_implementation)
    if change == "domain": value["domain_id"] = "security_ir"
    elif change == "schema": value["schema"] = "other/v1"
    elif change == "weight": value["head_state"]["weights"][0][0] = 99.
    elif change == "projection": value["projection_state"]["projection_down.weight"][0][0] = 99.
    elif change == "shape": value["target_schema"]["shape"] = {"kind": "null"}
    elif change == "split": value["validation_manifest"] = deepcopy(value["training_manifest"])
    elif change == "authority": value["proof_authority"] = True
    else: value["unexpected"] = True
    path, checksum = write(tmp_path, value)
    with pytest.raises(ValueError): api.load_intent_action_checkpoint_384(path, expected_sha256=checksum)


@pytest.mark.parametrize("change", ["hash", "symlink", "missing", "oversized", "during_load", "swapped_symlink", "swapped_fifo", "same_bytes_replaced"])
def test_exact_regular_artifact_and_endpoint_fences(tmp_path, monkeypatch, change, authored_diagnostic_implementation):
    path, checksum = write(tmp_path, checkpoint(historical=True, implementation=authored_diagnostic_implementation))
    if change == "hash": checksum = "f" * 64
    elif change == "symlink":
        link = tmp_path / "link.json"; link.symlink_to(path); path = link
    elif change == "missing": path.unlink()
    elif change == "oversized": monkeypatch.setattr(api.structured, "MAX_BYTES", 1)
    else:
        runtime = api.structured.Runtime
        def changed(value):
            result = runtime(value)
            if change == "during_load": path.write_bytes(b"changed")
            elif change == "swapped_symlink":
                target = tmp_path / "target.json"; path.rename(target); path.symlink_to(target)
            elif change == "swapped_fifo":
                path.unlink(); os.mkfifo(path)
            else:
                replacement = tmp_path / "replacement.json"; replacement.write_bytes(path.read_bytes()); replacement.replace(path)
            return result
        monkeypatch.setattr(api.structured, "Runtime", changed)
    with pytest.raises((ValueError, OSError)): api.load_intent_action_checkpoint_384(path, expected_sha256=checksum)


@pytest.mark.parametrize("change", ["profile", "domain_id", "changed_pins", "unchanged_content_sha256", "artifact_modified", "extra"])
def test_saved_receipt_requires_full_artifact_replay(tmp_path, change, authored_diagnostic_implementation):
    path, checksum = write(tmp_path, checkpoint(historical=True, implementation=authored_diagnostic_implementation))
    _, receipt = api.load_intent_action_checkpoint_384(path, expected_sha256=checksum)
    receipt[change] = [] if change == "changed_pins" else True if change == "artifact_modified" else "changed"
    with pytest.raises(ValueError, match="replay"):
        api.verify_intent_action_checkpoint_compatibility(receipt, path=path, expected_sha256=checksum)
