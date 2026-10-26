"""CPU head engineering controls with fabricated conditioning and exposed targets.

A/B fixtures are two authored interpretations of one retained occurrence. Prefix
forward checks are not statutory accuracy, permitted context or eligible training.
The optional tiny parent actually trains once under the OLD flat grammar; this
new weights-only compact head performs zero optimizer updates. No donor download
or historical test-module import is used.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import math
import re
import struct
import sys

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_selection_v1 as selector
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

CONTENT_RAW = {'A': b'{"schema":"legal-relational-compact-content/v1","tree":["forall",0,["forall",1,["forall",2,["implies",["extension","P",["or",["predicate",0,[["variable",0],["variable",1]]],["predicate",1,[["variable",0],["variable",1]]]]],["predicate",2,[["variable",2],["variable",0]]]]]]]}', 'B': b'{"schema":"legal-relational-compact-content/v1","tree":["forall",0,["forall",1,["forall",2,["extension","P",["implies",["or",["predicate",0,[["variable",0],["variable",1]]],["predicate",1,[["variable",0],["variable",1]]]],["predicate",2,[["variable",2],["variable",0]]]]]]]]}'}
CONTEXT_RAW = b'{"argument_roles":[{"roles":["recipient","duties"],"symbol":"Assign"},{"roles":["recipient","duties"],"symbol":"Transfer"},{"roles":["approver","recipient"],"symbol":"Approve"}],"schema":"legal-relational-compact-context/v1","signature":{"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":[],"interface":"LogicSignature@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-signature/v1","sorts":[{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"symbols":[{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Assign","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Transfer","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Approve","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"}]}}'
CONTENT_SHA = {'A': '719ce8351155bf64f096997dada4e493b401c1ae1b816cda47cbb07e4ab81427', 'B': '61d5c35821044d0a1d73a750378002a025e01143dc1cf935e86520f644f33485'}
CONTEXT_SHA = '64c9e1574f5c344936cea743adbfda6004d6f5f81b153df10ad25d9f6a9c87af'

LEXICAL = re.compile(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]')
SMALL_CONFIG = {"hidden_size": 8, "token_embedding_dim": 8,
                "projection_width": 4, "seed": 1729}
LEXICAL_TENSORS = {"target_embedding.weight", "output.weight", "output.bias"}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw): return hashlib.sha256(raw).hexdigest()


def digest(value): return sha(wire(value))


def context(): return json.loads(CONTEXT_RAW)


def conditioning(): return [.25, -.125] + [0.] * 382


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def codec(): return tokens.build_compact_content_token_codec_v1()


def codec_sha(codec): return tokens.compact_content_token_codec_sha256(codec)


def ids_for(label, codec):
    return ids_value(json.loads(CONTENT_RAW[label]), codec)


def ids_value(value, codec, *, eos=True):
    raw = wire(value).decode("utf-8")
    lexical = LEXICAL.findall(raw)
    assert "".join(lexical) == raw
    positions = {value: index for index, value in enumerate(codec["vocabulary"])}
    return [1, *(positions[value] for value in lexical), *([2] if eos else [])]


@pytest.fixture(scope="module")
def checkpoint(): return subject.create_compact_content_head_v1(config=SMALL_CONFIG)


@pytest.fixture(scope="module")
def parent(tmp_path_factory):
    """One actual update on an authored OLD one-rule fixture, not compact fitting."""
    binding = {"domain": "legal_ir", "lineage_id": "current_legal_v2", "dimension": 384,
               "runtime_profile": "unit-test-compact-head-donor/v1", "core_sha256": "a" * 64}
    target = {"rules": [{"modality": "O", "actor": "agency", "action": "save",
        "object": "report", "conditions": [], "exceptions": [], "temporal": []}]}
    rows = [{"id": "authored-old-parent", "source_text": "The agency must save the report.",
        "latent": [.5] + [0.] * 383, "embedding": [.3] + [0.] * 383,
        "canonical_ir": target}]
    before = torch.get_rng_state().clone()
    initial = numerical.build_checkpoint(binding, rows, [], hidden_size=8,
        token_embedding_dim=8, projection_width=4, batch_size=1)
    result = numerical.train(initial, rows, [], epochs=1, max_seconds=30,
                              max_optimizer_steps=1)
    trained = result["checkpoint"]
    assert trained["progress"]["optimizer_steps"] == 1
    assert trained["model_state"] != initial["model_state"]
    assert torch.equal(torch.get_rng_state(), before)
    directory = tmp_path_factory.mktemp("head-old-parent")
    retained = {"old-parent-training-report.json": result["report"],
                "old-parent-trained-checkpoint.json": trained}
    descriptors = []
    for name, value in retained.items():
        raw = wire(value)
        path = directory / name
        path.write_bytes(raw)
        descriptors.append({"path": str(path), "bytes": len(raw), "sha256": sha(raw)})
    (directory / "old-parent-fixture-evidence.json").write_bytes(wire({
        "schema": "authored-old-modal-parent-fixture/v1", "files": descriptors,
        "initial_model_state_sha256": digest(initial["model_state"]),
        "trained_model_state_sha256": digest(trained["model_state"]),
        "initial_checkpoint_sha256": digest(initial), "trained_checkpoint_sha256": digest(trained),
        "old_grammar_optimizer_steps": 1, "compact_head_optimizer_steps": 0,
        "source_origin": "authored_engineering_fixture", "training_mask": 0,
        "evaluation_gold_mask": 0, "statutory_accuracy_claimed": False}))
    return trained


def checked(value):
    return subject.validate_compact_content_head_v1(value, expected_checkpoint_sha256=digest(value))


def score(value, offered=None, vector=None, raw=CONTEXT_RAW, **overrides):
    options = {"expected_checkpoint_sha256": digest(value),
               "expected_context_sha256": sha(raw)}
    options.update(overrides)
    return subject.score_compact_content_head_v1(value,
        conditioning() if vector is None else vector,
        [1] if offered is None else offered, raw, **options)


def forbidden(*args, **kwargs):
    pytest.fail("invalid input or terminal prefix reached numerical execution")


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["compact_training_steps"] == 0


def independent_logits(checkpoint, vector, offered):
    """Independent existing-GRU invocation; public head/selector remain genuine."""
    model = numerical._model({"dimension": 384},
        {"target_vocabulary": checkpoint["codec"]["vocabulary"]}, checkpoint["config"])
    model.load_state_dict({name: torch.tensor(value, dtype=torch.float32, device="cpu")
                          for name, value in checkpoint["model_state"].items()}, strict=True)
    model.eval()
    with torch.no_grad():
        _, logits = model(torch.tensor([vector], dtype=torch.float32, device="cpu"),
                          torch.tensor([offered], dtype=torch.int64, device="cpu"))
    assert tuple(logits.shape) == (1, len(offered), 537)
    assert bool(torch.isfinite(logits).all())
    return logits[0, -1].tolist()


def test_head_public_api_has_no_training_target_optimizer_resume_or_gold_input():
    assert set(inspect.signature(subject.score_compact_content_head_v1).parameters) == {
        "checkpoint", "conditioning", "prefix_ids", "context_raw",
        "expected_checkpoint_sha256", "expected_context_sha256"}
    assert set(inspect.signature(subject.create_compact_content_head_v1).parameters) == {
        "config", "parent_checkpoint", "expected_parent_sha256"}
    assert not any(name in subject.__all__ for name in ("train", "fit", "resume", "generate"))


@pytest.mark.parametrize("change", [
    "extra", "bool_seed", "negative_seed", "float_hidden", "zero_embedding", "huge_width"])
def test_head_invalid_constructor_config_is_refused(change):
    config = dict(SMALL_CONFIG)
    if change == "extra": config["optimizer_steps"] = 1
    elif change == "bool_seed": config["seed"] = True
    elif change == "negative_seed": config["seed"] = -1
    elif change == "float_hidden": config["hidden_size"] = 8.0
    elif change == "zero_embedding": config["token_embedding_dim"] = 0
    elif change == "huge_width": config["projection_width"] = 10**9
    with pytest.raises(ValueError): subject.create_compact_content_head_v1(config=config)


@pytest.mark.parametrize("raw", [b"not json", b"[]", b"{}", b'{"schema":1,"schema":2}',
                                  b'{"weight":NaN}', b'{"weight":Infinity}'])
def test_head_raw_checkpoint_parser_refuses_malformed_duplicate_and_nonfinite_json(raw):
    with pytest.raises(ValueError):
        subject.load_compact_content_head_v1(raw, expected_raw_sha256=sha(raw))


def test_head_raw_hash_is_independent_from_canonical_checkpoint_identity(checkpoint):
    canonical = subject.compact_content_head_bytes_v1(checkpoint,
        expected_checkpoint_sha256=digest(checkpoint))
    assert canonical == wire(checkpoint)
    pretty = json.dumps(checkpoint, indent=2, ensure_ascii=False, allow_nan=False).encode()
    assert sha(pretty) != sha(canonical)
    assert subject.load_compact_content_head_v1(pretty, expected_raw_sha256=sha(pretty)) == checkpoint
    with pytest.raises(ValueError):
        subject.load_compact_content_head_v1(pretty, expected_raw_sha256=sha(canonical))
    for operation in (subject.validate_compact_content_head_v1, subject.compact_content_head_bytes_v1):
        with pytest.raises(ValueError): operation(checkpoint, expected_checkpoint_sha256="0" * 64)


@pytest.mark.parametrize("vector", [[], [0.] * 383, [0.] * 385,
    [True] + [0.] * 383, [float("nan")] + [0.] * 383,
    [float("inf")] + [0.] * 383, [1e100] + [0.] * 383,
    (0.,) * 384])
def test_head_conditioning_refuses_wrong_shape_type_nonfinite_and_float32_overflow(checkpoint, vector):
    with pytest.raises(ValueError): score(checkpoint, vector=vector)


@pytest.mark.parametrize("offered", [[], (), [True], [1.], [1] * 513, [2**63]])
def test_head_prefix_api_refuses_empty_nonplain_and_overbound_inputs(checkpoint, offered):
    with pytest.raises(ValueError): score(checkpoint, offered=offered)


def test_head_checkpoint_and_context_pins_refuse_changed_inputs(checkpoint):
    with pytest.raises(ValueError): score(checkpoint, expected_checkpoint_sha256="0" * 64)
    with pytest.raises(ValueError): score(checkpoint, expected_context_sha256="0" * 64)
    damaged = json.loads(CONTEXT_RAW)
    damaged["argument_roles"][0]["roles"].reverse()
    with pytest.raises(ValueError): score(checkpoint, raw=wire(damaged), expected_context_sha256=CONTEXT_SHA)


def test_head_raw_identity_hash_helper_does_not_consume_optimizer_or_retag_legacy_parent(parent):
    assert subject.compact_content_head_sha256(parent) == digest(parent)
    with pytest.raises(ValueError): checked(parent)
    with pytest.raises(ValueError):
        subject.load_compact_content_head_v1(wire(parent), expected_raw_sha256=digest(parent))


def test_head_seeded_construction_and_validation_preserve_runtime_and_detach(checkpoint):
    before_rng = torch.get_rng_state().clone()
    before_threads = torch.get_num_threads()
    before_dtype = torch.get_default_dtype()
    duplicate = subject.create_compact_content_head_v1(config=SMALL_CONFIG)
    assert duplicate == checkpoint
    different = subject.create_compact_content_head_v1(config={**SMALL_CONFIG, "seed": 1730})
    assert different["model_state"] != checkpoint["model_state"]
    restored = checked(checkpoint)
    assert restored == checkpoint and restored is not checkpoint
    assert subject.compact_content_head_sha256(checkpoint) == digest(checkpoint)
    restored["model_state"]["output.bias"][0] += .5
    assert restored != checkpoint
    assert torch.equal(torch.get_rng_state(), before_rng)
    assert torch.get_num_threads() == before_threads and torch.get_default_dtype() == before_dtype


def test_head_independent_json_restore_keeps_every_tensor_exact(checkpoint):
    raw = subject.compact_content_head_bytes_v1(checkpoint,
        expected_checkpoint_sha256=digest(checkpoint))
    restored = subject.load_compact_content_head_v1(raw, expected_raw_sha256=sha(raw))
    assert restored == checkpoint and restored is not checkpoint
    assert set(restored["model_state"]) == {
        "projection_down.weight", "projection_down.bias", "projection_up.weight", "projection_up.bias",
        "condition.weight", "condition.bias", "target_embedding.weight",
        "decoder.weight_ih_l0", "decoder.weight_hh_l0", "decoder.bias_ih_l0", "decoder.bias_hh_l0",
        "output.weight", "output.bias"}
    assert len(restored["model_state"]["target_embedding.weight"]) == 537
    assert len(restored["model_state"]["output.weight"]) == 537
    assert len(restored["model_state"]["output.bias"]) == 537
    assert digest(restored["model_state"]) == digest(checkpoint["model_state"])
    after = score(restored)
    assert after == score(checkpoint)


@pytest.mark.parametrize("damage", ["missing", "extra", "ragged", "bool", "integer_scalar", "nan", "infinity", "overflow", "nonexact_float32"])
def test_head_resealed_model_state_damage_cannot_pass_checkpoint_validation(checkpoint, damage):
    changed = deepcopy(checkpoint)
    state = changed["model_state"]
    if damage == "missing": del state["condition.bias"]
    elif damage == "extra": state["unexpected.weight"] = [0.]
    elif damage == "ragged": state["output.weight"][0].pop()
    elif damage == "bool": state["output.bias"][0] = True
    elif damage == "integer_scalar": state["output.bias"][0] = 0
    elif damage == "nan": state["output.bias"][0] = float("nan")
    elif damage == "infinity": state["output.bias"][0] = float("inf")
    elif damage == "overflow": state["output.bias"][0] = 1e100
    elif damage == "nonexact_float32": state["output.bias"][0] = .1
    # Nonfinite plain data has no valid canonical commitment; refusal must occur
    # during bounded identity admission rather than fabricating a new hash.
    if damage in {"nan", "infinity"}:
        with pytest.raises(ValueError): subject.compact_content_head_sha256(changed)
    else:
        changed["weights_sha256"] = digest(state)
        changed["initialization"]["initial_weights_sha256"] = changed["weights_sha256"]
        with pytest.raises(ValueError): checked(changed)


def test_head_checkpoint_binds_complete_ordered_codec_and_zero_update_profile(checkpoint, codec):
    assert checkpoint["schema"] == "legal-compact-content-head-checkpoint/v1"
    assert checkpoint["codec"] == codec
    assert checkpoint["codec_sha256"] == codec_sha(codec)
    assert checkpoint["codec"]["vocabulary"][:3] == ["<pad>", "<bos>", "<eos>"]
    assert checkpoint["max_total_ids"] == 512 and checkpoint["input_dimension"] == 384
    assert checkpoint["device"] == "cpu" and checkpoint["dtype"] == "float32"
    assert checkpoint["torch_version"] == str(torch.__version__)
    assert checkpoint["optimizer_state_included"] is False
    assert "optimizer_state" not in checkpoint and "progress" not in checkpoint
    assert checkpoint["weights_sha256"] == digest(checkpoint["model_state"])
    assert checkpoint["initialization"]["mode"] == "seeded_new"
    no_authority(checkpoint)


@pytest.mark.parametrize("label,position", [("A",1), ("A",49), ("A",99),
                                           ("B",1), ("B",49), ("B",99)])
def test_head_actual_exposed_prefixes_use_real_logits_and_exact_public_selector(label, position, checkpoint, codec):
    assert sha(CONTENT_RAW[label]) == CONTENT_SHA[label] and sha(CONTEXT_RAW) == CONTEXT_SHA
    target = ids_for(label, codec)
    assert len(target) == 101
    offered = target[:position]
    before = deepcopy((checkpoint, offered))
    rng, threads = torch.get_rng_state().clone(), torch.get_num_threads()
    report = score(checkpoint, offered=offered)
    expected_logits = independent_logits(checkpoint, conditioning(), offered)
    expected_selection = selector.select_compact_content_token_v1(expected_logits, offered, CONTEXT_RAW,
        expected_context_sha256=CONTEXT_SHA, codec=codec, expected_codec_sha256=codec_sha(codec))
    assert report["schema"] == "legal-compact-content-head-score/v1" and report["status"] == "scored"
    assert report["numerical_forward_executed"] is True and report["model_restore_performed"] is True
    assert report["torch_version"] == str(torch.__version__)
    assert report["runtime_torch_version_verified"] is True
    assert report["optimizer_executed"] is False
    assert report["output_shape"] == [1, position, 537]
    assert report["logits"] == expected_logits and len(report["logits"]) == 537
    assert all(type(value) is float and math.isfinite(value) for value in report["logits"])
    assert report["logits_sha256"] == digest(expected_logits)
    assert report["selection"] == expected_selection
    assert report["prefix_report"] == expected_selection["prefix_report"]
    assert report["prefix_ids"] == offered
    assert report["next_prefix_ids"] == expected_selection["next_prefix_ids"]
    assert report["conditioning"] == conditioning() and report["conditioning_sha256"] == digest(conditioning())
    assert report["checkpoint_sha256"] == digest(checkpoint)
    assert report["weights_sha256"] == digest(checkpoint["model_state"])
    assert (checkpoint, offered) == before
    assert torch.equal(torch.get_rng_state(), rng) and torch.get_num_threads() == threads
    no_authority(report)


def test_head_changed_fabricated_condition_changes_actual_scores_without_target_or_context_lookup(checkpoint):
    first = score(checkpoint)
    alternate = [.75, .375] + [0.] * 382
    second = score(checkpoint, vector=alternate)
    assert first["logits"] != second["logits"]
    assert second["numeric_conditioning"] == alternate
    assert first["prefix_report"] == second["prefix_report"]
    assert second["conditioning_sha256"] == digest(alternate)
    no_authority(first); no_authority(second)


def test_head_role_row_reordering_is_new_context_not_a_semantic_rejection(checkpoint):
    changed = context()
    changed["argument_roles"].reverse()
    report = score(checkpoint, raw=wire(changed))
    assert report["status"] == "scored"
    assert report["context_raw_sha256"] == digest(changed)
    # Neural input is the explicit fabricated vector/prefix; decoder context
    # governs public admissibility without asserting a source-to-context producer.
    assert report["logits"] == score(checkpoint)["logits"]
    no_authority(report)


def unary_context():
    value = context()
    symbol = deepcopy(value["signature"]["symbols"][0])
    symbol["name"] = "Eligible"; symbol["domain"] = symbol["domain"][:1]
    value["signature"]["symbols"] = [symbol]
    value["argument_roles"] = [{"symbol": "Eligible", "roles": ["subject"]}]
    return value


def balanced(rows):
    while len(rows) > 1:
        grouped = [["and", rows[index], rows[index+1]] for index in range(0,len(rows)-1,2)]
        if len(rows) % 2: grouped.append(rows[-1])
        rows = grouped
    return rows[0]


@pytest.mark.parametrize("case", ["complete", "unknown_id", "interior_PAD", "local_dead_end", "budget"])
def test_head_no_allowed_prefix_never_runs_forward_and_never_repairs_ids(case, checkpoint, codec, monkeypatch):
    raw = CONTEXT_RAW
    if case == "complete": offered = ids_for("A",codec)
    elif case == "unknown_id": offered = [1,-1]
    elif case == "interior_PAD": offered = [1,0]
    elif case == "local_dead_end":
        value = {"schema":tokens.CONTENT_SCHEMA,
            "tree":["forall",0,["predicate",0,[["variable",0],["variable",0]]]]}
        offered = ids_value(value,codec,eos=False)[:-1]
    else:
        raw = wire(unary_context())
        body = balanced([["predicate",0,[["variable",0]]] for _ in range(27)])
        value = {"schema":tokens.CONTENT_SCHEMA,
            "tree":["forall",0,["exists",1,["not",["not",["not",body]]]]]}
        full = ids_value(value,codec,eos=False)
        assert len(full) == 514
        offered = full[:512]
    expected = tokens.compact_content_allowed_token_ids_v1(offered,raw,
        expected_context_sha256=sha(raw),codec=codec,expected_codec_sha256=codec_sha(codec))
    assert expected["allowed_token_ids"] == []
    # Labelled NEWhead forward seam only. Public grammar remains genuine.
    monkeypatch.setattr(subject,"_forward",forbidden)
    report = score(checkpoint,offered=offered,raw=raw)
    assert report["status"] == "no_forward" and report["prefix_report"] == expected
    assert report["prefix_ids"] == report["next_prefix_ids"] == offered
    assert report["numerical_forward_executed"] is False and report["model_restore_performed"] is False
    assert report["torch_version"] == checkpoint["torch_version"]
    assert report["runtime_torch_version_verified"] is False
    assert report["logits"] is report["logits_sha256"] is report["selection"] is None
    assert report["output_shape"] is None and report["optimizer_executed"] is False
    no_authority(report)


@pytest.mark.parametrize("damage", ["schema", "profile", "task", "max_total_ids", "input_dimension",
    "device", "dtype", "torch_version", "codec_order", "codec_old_size", "optimizer_extra", "optimizer_flag",
    "compact_steps", "authority", "training_mask", "gold_mask"])
def test_head_resealed_profile_codec_optimizer_and_authority_changes_are_refused(checkpoint, damage):
    changed = deepcopy(checkpoint)
    if damage in {"schema", "profile", "task"}: changed[damage] = "foreign-profile/v1"
    elif damage == "max_total_ids": changed[damage] = 1024
    elif damage == "input_dimension": changed[damage] = 768
    elif damage == "device": changed[damage] = "cuda"
    elif damage == "dtype": changed[damage] = "float64"
    elif damage == "torch_version": changed[damage] = "0.0.0+authored-wrong-runtime"
    elif damage == "codec_order":
        vocabulary = changed["codec"]["vocabulary"]
        vocabulary[3], vocabulary[4] = vocabulary[4], vocabulary[3]
        changed["codec_sha256"] = digest(changed["codec"])
    elif damage == "codec_old_size":
        changed["codec"]["vocabulary"] = changed["codec"]["vocabulary"][:5]
        changed["codec"]["vocabulary_size"] = 5
        changed["codec_sha256"] = digest(changed["codec"])
    elif damage == "optimizer_extra": changed["optimizer_state"] = {"state": {}, "resume": True}
    elif damage == "optimizer_flag": changed["optimizer_state_included"] = True
    elif damage == "compact_steps": changed["compact_training_steps"] = 1
    elif damage == "authority": changed["authority"][next(iter(changed["authority"]))] = True
    elif damage == "training_mask": changed["training_mask"] = 1
    elif damage == "gold_mask": changed["evaluation_gold_mask"] = 1
    with pytest.raises(ValueError): checked(changed)


def test_head_optional_trained_parent_transfer_has_exact_inherited_and_token_row_oracles(parent, codec):
    before = deepcopy(parent)
    rng, threads = torch.get_rng_state().clone(), torch.get_num_threads()
    transferred = subject.create_compact_content_head_v1(parent_checkpoint=parent,
        expected_parent_sha256=digest(parent))
    assert transferred["initialization"]["mode"] == "trained_native_384_parent_transfer"
    assert parent == before and parent["progress"]["optimizer_steps"] == 1
    assert transferred["compact_training_steps"] == 0 and transferred["optimizer_state_included"] is False
    assert "optimizer_state" not in transferred
    old_vocab = parent["codec"]["target_vocabulary"]
    positions = {token:index for index,token in enumerate(old_vocab)}
    inherited = set(parent["model_state"]) - LEXICAL_TENSORS
    assert len(inherited) == 10
    initialization = transferred["initialization"]
    assert initialization["parent_checkpoint_sha256"] == digest(parent)
    assert initialization["parent_optimizer_steps"] == 1
    assert initialization["parent_modified"] is False
    assert initialization["fresh_optimizer_required"] is True
    assert initialization["parent_optimizer_state_inherited"] is False
    assert initialization["parent_public_validation_performed"] is True
    assert initialization["random_parameters_used"] is False
    assert initialization["parent_model_state_sha256"] == digest(parent["model_state"])
    assert set(initialization["exact_inherited_tensors"]) == inherited
    assert set(initialization["lexical_mapped_tensors"]) == LEXICAL_TENSORS
    assert len(initialization["token_rows"]) == 537
    saw_new = saw_copied = False
    for name in inherited:
        assert transferred["model_state"][name] == parent["model_state"][name]
    for name in LEXICAL_TENSORS:
        donor = torch.tensor(parent["model_state"][name], dtype=torch.float32, device="cpu")
        mean = donor.mean(0)
        for index, token in enumerate(codec["vocabulary"]):
            old = positions.get(token)
            wanted = donor[old] if old is not None else mean
            assert transferred["model_state"][name][index] == wanted.tolist()
            row = initialization["token_rows"][index]
            assert row["token_id"] == index and row["token"] == token
            assert row["parent_token_id"] == old
            assert row["policy"] == ("copied_exact_token" if old is not None else "parent_lexical_row_mean")
            saw_new |= old is None; saw_copied |= old is not None
    assert saw_new and saw_copied
    assert torch.equal(torch.get_rng_state(),rng) and torch.get_num_threads() == threads
    assert score(transferred)["numerical_forward_executed"] is True
    no_authority(transferred)


@pytest.mark.parametrize("damage", ["missing_pin", "wrong_pin", "untrained", "wrong_dimension", "architecture"])
def test_head_parent_transfer_refuses_uncommitted_untrained_or_incompatible_donors(parent, damage):
    changed = deepcopy(parent)
    expected = digest(changed)
    options = {}
    if damage == "missing_pin": expected = None
    elif damage == "wrong_pin": expected = "0" * 64
    elif damage == "untrained":
        changed["progress"] = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
        changed["optimizer_state"] = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
        expected = digest(changed)
    elif damage == "wrong_dimension":
        changed["binding"]["dimension"] = 8
        changed["binding"]["lineage_id"] = "legacy_hub_v1"
        expected = digest(changed)
    elif damage == "architecture": options["config"] = {**SMALL_CONFIG,"hidden_size":16}
    with pytest.raises(ValueError):
        subject.create_compact_content_head_v1(parent_checkpoint=changed,
            expected_parent_sha256=expected, **options)


def test_head_unicode_parent_uses_existing_public_parent_canonical_identity(parent):
    changed = deepcopy(parent)
    changed["binding"]["runtime_profile"] += "/é"
    before = deepcopy(changed)
    # The existing donor owner hashes ASCII-escaped JSON. The new head's own
    # UTF8 identity helper is deliberately a different transport convention.
    public_parent_sha = numerical.checkpoint_digest(changed)
    assert public_parent_sha != digest(changed)
    transferred = subject.create_compact_content_head_v1(parent_checkpoint=changed,
        expected_parent_sha256=public_parent_sha)
    assert transferred["initialization"]["parent_checkpoint_sha256"] == public_parent_sha
    assert transferred["initialization"]["parent_binding"] == changed["binding"]
    assert changed == before and transferred["compact_training_steps"] == 0
    no_authority(transferred)
    with pytest.raises(ValueError):
        subject.create_compact_content_head_v1(parent_checkpoint=changed,
            expected_parent_sha256=digest(changed))


@pytest.mark.parametrize("failure_type", [RuntimeError, KeyboardInterrupt])
def test_head_operational_owner_load_errors_propagate_unchanged(checkpoint, monkeypatch, failure_type):
    failure = failure_type("authored numerical dependency unavailable")
    def unavailable(*args, **kwargs): raise failure
    # Labelled NEWhead loader seam only; upstream grammar/selector stay genuine.
    monkeypatch.setattr(subject,"_owners",unavailable)
    with pytest.raises(failure_type) as raised: score(checkpoint)
    assert raised.value is failure


def test_head_closing_source_fence_refuses_mutation_during_final_serialization(checkpoint,monkeypatch):
    original = subject._detach
    def source_changed(*args,**kwargs):
        detached = original(*args,**kwargs)
        monkeypatch.setattr(subject,"_SELF_SHA","0" * 64)
        return detached
    # Labelled NEWhead serialization/source seam; no modified source file.
    monkeypatch.setattr(subject,"_detach",source_changed)
    with pytest.raises(ValueError): score(checkpoint)


def test_head_mutable_caller_vector_is_not_silently_substituted_during_serialization(checkpoint,monkeypatch):
    vector = conditioning()
    original = subject._detach
    def mutate_input(*args,**kwargs):
        detached = original(*args,**kwargs)
        vector[0] = .75
        return detached
    monkeypatch.setattr(subject,"_detach",mutate_input)
    with pytest.raises(ValueError): score(checkpoint,vector=vector)


@pytest.mark.parametrize("ambient", ["float64_default", "cpu_autocast", "meta_default"])
def test_head_actual_cpu_runtime_guards_refuse_before_model_construction(ambient,checkpoint,monkeypatch):
    # Actual reversible child-local CPU settings, with a labelled NEWhead
    # allocation seam. No upstream constructor is replaced and CUDA is unused.
    monkeypatch.setattr(subject,"_new_model",forbidden)
    if ambient == "float64_default":
        original = torch.get_default_dtype()
        try:
            torch.set_default_dtype(torch.float64)
            with pytest.raises(ValueError): subject.create_compact_content_head_v1(config=SMALL_CONFIG)
        finally:
            torch.set_default_dtype(original)
        assert torch.get_default_dtype() == original
    elif ambient == "meta_default":
        original = torch.get_default_device()
        try:
            torch.set_default_device("meta")
            with pytest.raises(ValueError): subject.create_compact_content_head_v1(config=SMALL_CONFIG)
        finally:
            torch.set_default_device(original)
        assert torch.get_default_device() == original
    else:
        assert not torch.is_autocast_enabled("cpu")
        with torch.autocast("cpu",dtype=torch.bfloat16):
            with pytest.raises(ValueError): score(checkpoint)
        assert not torch.is_autocast_enabled("cpu")


def test_head_conditioning_retains_original_commitment_and_declares_float32_rounding(checkpoint):
    vector = [.1] + [0] * 383
    report = score(checkpoint,vector=vector)
    rounded = [struct.unpack("!f",struct.pack("!f",value))[0] for value in vector]
    assert report["conditioning"] == vector
    assert type(report["conditioning"][1]) is int
    assert report["conditioning_sha256"] == digest(vector)
    assert report["numeric_conditioning"] == rounded and rounded[0] != vector[0]
    assert all(type(value) is float for value in report["numeric_conditioning"])
    assert report["logits"] == independent_logits(checkpoint,vector,[1])
    no_authority(report)


def test_head_pure_bounded_json_cumulative_alias_cycle_and_escape_admission():
    """Labelled NEWhead ordinary-data seam, independent of model validation."""
    ordinary = {"escape": '\\"\n\t', "unicode": "é漢🙂", "float": -0.0}
    exact = wire(ordinary)
    assert subject._wire(ordinary,len(exact)) == exact
    with pytest.raises(ValueError): subject._wire(ordinary,len(exact)-1)
    with pytest.raises(ValueError,match="before serialization"):
        subject._wire(["x" * 128] * 16,1024)
    cyclic = []; cyclic.append(cyclic)
    with pytest.raises(ValueError): subject._wire(cyclic,4096)
    nested = None
    for _ in range(98): nested = [nested]
    with pytest.raises(ValueError): subject._wire(nested,4096)
