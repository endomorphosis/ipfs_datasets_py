"""Pinned inventory and a private architecture port of learned 8D formula heads.

The conserved linguistic 8D model has no neural formula head. This adapter only
accepts the separately trained ``modal-latent-formula-checkpoint/v1`` sidecar.
It copies its full residual projection, conditioning layer, GRU, and vocabulary;
it does not attach the head to another lineage or bypass an old loader guard.
The lazy Torch port is a new preparation candidate, not original-runtime replay
or a qualified source-only teacher. Nothing trains, fetches, or publishes here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "gte-legacy8-decoder-donor/v1"
SNAPSHOT_SCHEMA = "gte-legacy8-decoder-port/v1"
CHECKPOINT_SCHEMA = "modal-latent-formula-checkpoint/v1"
ARCHITECTURE = "residual-projection-latent-formula-gru/v1"
MAX_BYTES = 48 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
_AUTHORITY = ("qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
              "semantic_correctness_verified", "promotion_performed", "publication_performed", "lake_executed")
_SOURCE_PATHS = {
    "canonical_contracts.py": "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "legal_formula_codec.py": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_codec.py",
    "legal_ir_grammar_decoder.py": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py",
    "modal_latent_formula.py": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py",
    "tree_pin.py": "ipfs_datasets_py/logic/autoformal/tree_pin.py",
}
_PORT_FLAGS = {"source_only": False, "parser_features_in_input": True, "architecture_port_candidate": True,
               "qualified": False, "semantic_correctness_verified": False, "proof_authority": False,
               "admitted": False, "original_runtime_replay_verified": False, "source_runtime_compatible": False,
               "distillation_completed": False, "optimizer_moments_copied": False}
_POLICY = {
    "source_tokenization": "unicode_casefold_word_or_punctuation/v1",
    "source_unknown": "reject", "target_unknown": "reject", "vocabulary_origin": "training_examples_only",
    "identifier_hashing": False, "target_schema": "CanonicalRoundTripIR@1", "rule_count": 1,
    "field_order": list(_FIELDS), "qualifiers": "sorted_unique_input_required", "max_qualifiers_per_facet": 4,
    "max_source_tokens": 64, "max_target_tokens": 64, "max_vocabulary": 4096,
    "source_pad_id": 0, "source_unk_id": 1, "target_pad_id": 0, "target_bos_id": 1, "target_eos_id": 2,
    "truncation": "reject", "generation_fallback": "none",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _sha(value, label="SHA256"):
    _require(type(value) is str and _HASH.fullmatch(value), label + " requires a lowercase full SHA256")
    return value


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(path, expected_sha256, max_bytes=MAX_BYTES):
    _sha(expected_sha256)
    path = Path(path).absolute()
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode), "regular nonsymlink donor file required")
    _require(before.st_size <= max_bytes, "donor file exceeds byte bound")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(stat.S_ISREG(opened.st_mode) and _identity(opened) == _identity(before), "donor changed before reading")
        raw = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= max_bytes and len(raw) == before.st_size, "donor file changed or exceeds byte bound")
    _require(_identity(before) == _identity(after) == _identity(path.lstat()), "donor file changed while reading")
    actual = hashlib.sha256(raw).hexdigest()
    _require(actual == expected_sha256, "donor file SHA256 mismatch")
    return raw, {"path": str(path.resolve()), "bytes": len(raw), "sha256": actual}


def _parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite JSON number")

    def number(value):
        parsed = float(value)
        _require(math.isfinite(parsed), "nonfinite JSON number")
        return parsed

    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=number)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid donor JSON") from error
    _require(type(result) is dict, "donor checkpoint must be an object")
    return result


def _integer(value, low, high, label):
    _require(type(value) is int and low <= value <= high, label + " is outside its integer bound")
    return value


def _config(config):
    fields = {"architecture", "device", "dtype", "temperature", "max_target_tokens", "source_input", "torch_version",
              "learning_rate", "batch_size", "seed", "hidden_size", "token_embedding_dim", "projection_width",
              "formula_weight", "reconstruction_weight"}
    _require(type(config) is dict and set(config) == fields, "closed donor config required")
    expected = {"architecture": ARCHITECTURE, "device": "cpu", "dtype": "float32", "temperature": 0,
                "max_target_tokens": 64, "source_input": "provenance_only_not_neural_input"}
    _require(_json({key: config[key] for key in expected}) == _json(expected), "donor architecture profile differs")
    _require(type(config["torch_version"]) is str and 0 < len(config["torch_version"]) <= 128, "bounded Torch provenance required")
    for key, low, high in (("batch_size", 1, 16), ("seed", 0, 2**31 - 1), ("hidden_size", 8, 128),
                           ("token_embedding_dim", 8, 64), ("projection_width", 1, 64)):
        _integer(config[key], low, high, key)
    for key, high in (("learning_rate", .1), ("formula_weight", 100.), ("reconstruction_weight", 100.)):
        value = config[key]
        _require(type(value) in (int, float) and 0 < value <= high and math.isfinite(value),
                 key + " must be finite and positive within its bound")


def _codec(codec):
    _require(type(codec) is dict and set(codec) == {"schema", "source_vocabulary", "target_vocabulary", "policy"},
             "closed donor codec required")
    _require(codec["schema"] == "legal-source-formula-codec/v1" and _json(codec["policy"]) == _json(_POLICY),
             "exact donor codec policy required")
    _require(codec["source_vocabulary"] == ["<pad>", "<unk>", "latent"], "donor cannot contain source token vocabulary")
    vocabulary = codec["target_vocabulary"]
    _require(type(vocabulary) is list and 17 <= len(vocabulary) <= 4096 and all(
        type(token) is str and len(token) <= 4096 for token in vocabulary), "bounded donor target vocabulary required")
    _require(len(set(vocabulary)) == len(vocabulary), "duplicate donor target token")
    structural = ["<pad>", "<bos>", "<eos>"]
    for field in _FIELDS:
        structural.append(json.dumps(["field", field], separators=(",", ":"), ensure_ascii=False))
        if field in _FIELDS[4:]:
            structural.append(json.dumps(["end", field], separators=(",", ":"), ensure_ascii=False))
    _require(vocabulary[:len(structural)] == structural, "target special IDs or structural grammar differ")
    atoms = vocabulary[len(structural):]
    _require(atoms == sorted(set(atoms)), "target atom order differs")
    present = set()
    for token in atoms:
        try:
            atom = json.loads(token)
        except ValueError as error:
            raise ValueError("target atom must be canonical JSON") from error
        _require(type(atom) is list and len(atom) == 3 and atom[0] == "atom" and atom[1] in _FIELDS
                 and type(atom[2]) is str and len(atom[2]) <= 4096
                 and json.dumps(atom, separators=(",", ":"), ensure_ascii=False) == token,
                 "target atom must be an exact typed field/string tuple")
        _require(atom[1] != "modality" or atom[2] in {"O", "P", "F"}, "unknown modality token")
        present.add(atom[1])
    _require(set(_FIELDS[:4]) <= present, "every scalar facet requires a training atom")
    return len(vocabulary)


def _shapes(config, vocabulary_size):
    hidden, embedding, width = config["hidden_size"], config["token_embedding_dim"], config["projection_width"]
    return {"condition.bias": [hidden], "condition.weight": [hidden, 8],
            "decoder.bias_hh_l0": [3 * hidden], "decoder.bias_ih_l0": [3 * hidden],
            "decoder.weight_hh_l0": [3 * hidden, hidden], "decoder.weight_ih_l0": [3 * hidden, embedding],
            "output.bias": [vocabulary_size], "output.weight": [vocabulary_size, hidden],
            "projection_down.bias": [width], "projection_down.weight": [width, 8],
            "projection_up.bias": [8], "projection_up.weight": [8, width],
            "target_embedding.weight": [vocabulary_size, embedding]}


def _tensor(value, shape, label, *, nonnegative=False):
    if shape:
        _require(type(value) is list and len(value) == shape[0], label + " tensor shape differs")
        count = nonzero = 0
        for item in value:
            item_count, item_nonzero = _tensor(item, shape[1:], label, nonnegative=nonnegative)
            count += item_count
            nonzero += item_nonzero
        return count, nonzero
    _require(type(value) in (int, float), label + " tensor must contain numeric values without bool")
    try:
        valid = math.isfinite(value) and abs(value) <= 1e8 and (not nonnegative or value >= 0)
    except OverflowError:
        valid = False
    _require(valid, label + " tensor must be bounded finite" + (" and nonnegative" if nonnegative else ""))
    return 1, int(value != 0)


def _validate(checkpoint):
    fields = {"schema", "binding", "projection_id", "config", "codec", "implementation",
              "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count",
              "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *_AUTHORITY}
    _require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint["schema"] == CHECKPOINT_SCHEMA,
             "closed learned 8D formula checkpoint required")
    _require(all(checkpoint[key] is False for key in _AUTHORITY), "donor checkpoint cannot grant authority")
    binding = checkpoint["binding"]
    _require(type(binding) is dict and set(binding) == {"domain", "lineage_id", "dimension", "runtime_profile", "core_sha256"},
             "closed donor binding required")
    _require(binding["domain"] == "legal_ir" and binding["lineage_id"] == "legacy_hub_v1"
             and type(binding["dimension"]) is int and binding["dimension"] == 8
             and binding["runtime_profile"] == "modal-latent-joint-formula/v1", "exact learned 8D lineage binding required")
    _sha(binding["core_sha256"], "core SHA256")
    _require(checkpoint["projection_id"] == "typed_deontic_rule_v1", "unsupported formula projection")
    _config(checkpoint["config"])
    vocabulary_size = _codec(checkpoint["codec"])
    implementation = checkpoint["implementation"]
    _require(type(implementation) is dict and set(implementation) == {"scope", "files"}
             and implementation["scope"] == "listed_latent_decoder_and_grammar_sources_only"
             and type(implementation["files"]) is dict and set(implementation["files"]) == set(_SOURCE_PATHS),
             "exact donor implementation closure required")
    for pin in implementation["files"].values():
        _sha(pin, "implementation SHA256")
    for key in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _sha(checkpoint[key], key)
    parent = checkpoint["parent_checkpoint_sha256"]
    _require(parent is None or type(parent) is str and _HASH.fullmatch(parent), "invalid parent checkpoint SHA256")
    count = _integer(checkpoint["training_count"], 1, 4096, "training count")
    _integer(checkpoint["tuning_count"], 0, 4096, "tuning count")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}, "closed training progress required")
    for key, value in progress.items():
        _integer(value, 0, 10**9, key)
    batch, cursor, steps = checkpoint["config"]["batch_size"], progress["row_cursor"], progress["optimizer_steps"]
    _require(cursor < count and cursor % batch == 0 and steps == progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch,
             "optimizer steps and row cursor differ")
    _require(steps > 0, "untrained initial head is not a learned decoder donor")
    shapes = _shapes(checkpoint["config"], vocabulary_size)
    weights = checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(shapes), "full donor model state keys differ")
    inventory = []
    for name, shape in sorted(shapes.items()):
        values, nonzero = _tensor(weights[name], shape, name)
        inventory.append({"name": name, "shape": shape, "value_count": values, "nonzero_value_count": nonzero,
                          "sha256": _digest(weights[name])})
    moments = checkpoint["optimizer_state"]
    _require(type(moments) is dict and set(moments) == {"schema", "parameters"}
             and moments["schema"] == "adam-default-betas-eps/v1" and type(moments["parameters"]) is dict
             and set(moments["parameters"]) == set(shapes), "complete donor Adam state required")
    for name, shape in shapes.items():
        item = moments["parameters"][name]
        _require(type(item) is dict and set(item) == {"step", "exp_avg", "exp_avg_sq"}
                 and type(item["step"]) is int and item["step"] == steps, "donor Adam step differs")
        _tensor(item["exp_avg"], shape, name + ".exp_avg")
        _tensor(item["exp_avg_sq"], shape, name + ".exp_avg_sq", nonnegative=True)
    return inventory


def _verify_implementation(implementation, root):
    if root is None:
        return []
    root = Path(root).resolve()
    _require(root.is_dir(), "implementation_root must be an existing repository source root")
    receipts = []
    for name, relative in sorted(_SOURCE_PATHS.items()):
        path = root / relative
        _, receipt = _read(path, implementation["files"][name], max_bytes=4 * 1024 * 1024)
        receipts.append({"name": name, **receipt})
    return receipts


def read_legacy8_decoder_donor(path, *, expected_sha256, implementation_root=None):
    """Read the complete pinned sidecar and return fresh checkpoint and inventory.

    ``implementation_root`` is a repository root containing its five recorded
    files. Exact closure verification attests their bytes, not original runtime
    compatibility, actual historical training, or source-law correctness.
    """
    raw, file_receipt = _read(path, expected_sha256)
    checkpoint = _parse(raw)
    inventory = _validate(checkpoint)
    source_files = _verify_implementation(checkpoint["implementation"], implementation_root)
    model_state_sha256 = _digest(checkpoint["model_state"])
    identity = {"checkpoint_sha256": file_receipt["sha256"], "binding": checkpoint["binding"],
                "config": checkpoint["config"], "codec_sha256": _digest(checkpoint["codec"]),
                "model_state_sha256": model_state_sha256, "implementation": checkpoint["implementation"]}
    receipt = {"schema": SCHEMA, "status": "inspected", "checkpoint_path": file_receipt["path"],
               "checkpoint_sha256": file_receipt["sha256"], "checkpoint_bytes": file_receipt["bytes"],
               "donor_identity_sha256": _digest(identity), "dimension": 8,
               "binding": copy.deepcopy(checkpoint["binding"]), "config": copy.deepcopy(checkpoint["config"]),
               "codec_sha256": identity["codec_sha256"], "target_vocabulary_sha256": _digest(checkpoint["codec"]["target_vocabulary"]),
               "target_vocabulary_count": len(checkpoint["codec"]["target_vocabulary"]),
               "model_state_sha256": model_state_sha256, "tensor_inventory": inventory,
               "implementation": copy.deepcopy(checkpoint["implementation"]), "implementation_files": source_files,
               "implementation_files_verified": implementation_root is not None,
               "progress": copy.deepcopy(checkpoint["progress"]), "optimizer_moments_validated": True,
               "optimizer_moments_copied": False, "source_only": False, "parser_features_in_input": True,
               "source_text_is_neural_input": False, "supported_projections": ["typed_deontic_rule_v1"],
               "learned_head_provenance": "checkpoint_declared_optimizer_steps_not_independent_training_attestation",
               "original_runtime_replay_verified": False, "source_runtime_compatible": False,
               "legacy_target_aware_reconstruction_is_fidelity_evidence": False,
               "architecture_port_candidate": True, "distillation_completed": False,
               "weights_copied": False, "proof_authority": False, "qualified": False,
               "semantic_correctness_verified": False, "admitted": False,
               "preparation_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return {"checkpoint": checkpoint, "receipt": receipt}


def inspect_legacy8_decoder_donor(path, *, expected_sha256, implementation_root=None):
    """Return dependency-free full tensor and codec inventory; no model is loaded."""
    return read_legacy8_decoder_donor(path, expected_sha256=expected_sha256,
                                    implementation_root=implementation_root)["receipt"]


def normalize_legacy8_decoder_donor(checkpoint, *, source_checkpoint_sha256):
    """Serialize exact copied head tensors without its Adam moments or cursor.

    Call only after external file-pin admission. This normalization alone does
    not attest that caller-supplied checkpoint content belongs to the file pin.
    A containing student checkpoint must independently pin this full snapshot.
    """
    _sha(source_checkpoint_sha256, "source checkpoint SHA256")
    _require(len(_json(checkpoint)) <= MAX_BYTES, "donor checkpoint exceeds byte bound")
    _validate(checkpoint)
    identity = {"checkpoint_sha256": source_checkpoint_sha256, "binding": checkpoint["binding"],
                "config": checkpoint["config"], "codec_sha256": _digest(checkpoint["codec"]),
                "model_state_sha256": _digest(checkpoint["model_state"]), "implementation": checkpoint["implementation"]}
    return {"schema": SNAPSHOT_SCHEMA, "source_checkpoint_sha256": source_checkpoint_sha256,
            "source_model_state_sha256": identity["model_state_sha256"], "source_codec_sha256": identity["codec_sha256"],
            "donor_identity_sha256": _digest(identity), "binding": copy.deepcopy(checkpoint["binding"]),
            "config": copy.deepcopy(checkpoint["config"]), "codec": copy.deepcopy(checkpoint["codec"]),
            "model_state": copy.deepcopy(checkpoint["model_state"]),
            "source_implementation": copy.deepcopy(checkpoint["implementation"]), **_PORT_FLAGS}


def _validated_snapshot(snapshot, expected_source_checkpoint_sha256, expected_source_model_state_sha256):
    _sha(expected_source_checkpoint_sha256, "expected source checkpoint SHA256")
    if expected_source_model_state_sha256 is not None:
        _sha(expected_source_model_state_sha256, "expected source model state SHA256")
    fields = {"schema", "source_checkpoint_sha256", "source_model_state_sha256", "source_codec_sha256",
              "donor_identity_sha256", "binding", "config", "codec", "model_state", "source_implementation", *_PORT_FLAGS}
    _require(type(snapshot) is dict and set(snapshot) == fields and snapshot["schema"] == SNAPSHOT_SCHEMA,
             "closed legacy8 decoder port snapshot required")
    _require(len(_json(snapshot)) <= MAX_BYTES, "legacy8 port snapshot exceeds byte bound")
    _require(_json({key: snapshot[key] for key in _PORT_FLAGS}) == _json(_PORT_FLAGS), "legacy8 port flags differ")
    snapshot = copy.deepcopy(snapshot)
    _require(snapshot["source_checkpoint_sha256"] == expected_source_checkpoint_sha256, "legacy8 source checkpoint pin differs")
    for key in ("source_model_state_sha256", "source_codec_sha256", "donor_identity_sha256"):
        _sha(snapshot[key], key)
    binding = snapshot["binding"]
    _require(type(binding) is dict and set(binding) == {"domain", "lineage_id", "dimension", "runtime_profile", "core_sha256"},
             "closed donor binding required")
    _require(binding["domain"] == "legal_ir" and binding["lineage_id"] == "legacy_hub_v1"
             and type(binding["dimension"]) is int and binding["dimension"] == 8
             and binding["runtime_profile"] == "modal-latent-joint-formula/v1", "exact learned 8D lineage binding required")
    _sha(binding["core_sha256"], "core SHA256")
    _config(snapshot["config"])
    vocabulary_size = _codec(snapshot["codec"])
    implementation = snapshot["source_implementation"]
    _require(type(implementation) is dict and set(implementation) == {"scope", "files"}
             and implementation["scope"] == "listed_latent_decoder_and_grammar_sources_only"
             and type(implementation["files"]) is dict and set(implementation["files"]) == set(_SOURCE_PATHS),
             "exact donor implementation closure required")
    for pin in implementation["files"].values():
        _sha(pin, "implementation SHA256")
    shapes = _shapes(snapshot["config"], vocabulary_size)
    _require(type(snapshot["model_state"]) is dict and set(snapshot["model_state"]) == set(shapes), "full donor model state keys differ")
    for name, shape in shapes.items():
        _tensor(snapshot["model_state"][name], shape, name)
    actual_state = _digest(snapshot["model_state"])
    _require(actual_state == snapshot["source_model_state_sha256"], "legacy8 copied model state SHA256 differs")
    _require(expected_source_model_state_sha256 is None or actual_state == expected_source_model_state_sha256,
             "legacy8 external model state SHA256 differs")
    _require(_digest(snapshot["codec"]) == snapshot["source_codec_sha256"], "legacy8 copied codec SHA256 differs")
    identity = {"checkpoint_sha256": snapshot["source_checkpoint_sha256"], "binding": binding,
                "config": snapshot["config"], "codec_sha256": snapshot["source_codec_sha256"],
                "model_state_sha256": actual_state, "implementation": implementation}
    _require(_digest(identity) == snapshot["donor_identity_sha256"], "legacy8 copied donor identity differs")
    return snapshot


def _build_private_model(config, codec, weights):
    import torch

    _require(torch.get_num_threads() == 1, "caller must reserve CPU and set torch.set_num_threads(1)")
    hidden, embedding, width = config["hidden_size"], config["token_embedding_dim"], config["projection_width"]
    options = {"device": "cpu", "dtype": torch.float32}

    class PrivateLegacy8Decoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.projection_down = torch.nn.Linear(8, width, **options)
            self.projection_up = torch.nn.Linear(width, 8, **options)
            self.condition = torch.nn.Linear(8, hidden, **options)
            self.target_embedding = torch.nn.Embedding(len(codec["target_vocabulary"]), embedding, padding_idx=0, **options)
            self.decoder = torch.nn.GRU(embedding, hidden, batch_first=True, **options)
            self.output = torch.nn.Linear(hidden, len(codec["target_vocabulary"]), **options)

        def project(self, latent):
            return latent + self.projection_up(torch.tanh(self.projection_down(latent)))

        def start(self, projected):
            return torch.tanh(self.condition(projected)).unsqueeze(0)

        def next_logits(self, tokens, hidden_state):
            outputs, hidden_state = self.decoder(self.target_embedding(tokens), hidden_state)
            return self.output(outputs), hidden_state

        def forward(self, latent, tokens):
            projected = self.project(latent)
            return projected, self.next_logits(tokens, self.start(projected))[0]

    with torch.random.fork_rng(devices=[]):
        model = PrivateLegacy8Decoder()
    state = {name: torch.tensor(value, dtype=torch.float32, device="cpu") for name, value in weights.items()}
    _require(_digest({name: value.tolist() for name, value in state.items()}) == _digest(weights),
             "legacy8 donor state is not exact float32 serialization")
    model.load_state_dict(state, strict=True)
    _require(all(torch.equal(value, state[name]) for name, value in model.state_dict().items()), "copied donor tensors differ")
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model


def inspect_legacy8_decoder_snapshot(snapshot, *, expected_source_checkpoint_sha256,
                                     expected_source_model_state_sha256=None):
    """Inspect a pinned container's self-contained port without importing Torch."""
    snapshot = _validated_snapshot(snapshot, expected_source_checkpoint_sha256, expected_source_model_state_sha256)
    shapes = _shapes(snapshot["config"], len(snapshot["codec"]["target_vocabulary"]))
    return {"schema": "gte-legacy8-decoder-port-inventory/v1", "status": "snapshot_inspected",
            "snapshot_sha256": _digest(snapshot), "source_checkpoint_sha256": snapshot["source_checkpoint_sha256"],
            "source_model_state_sha256": snapshot["source_model_state_sha256"],
            "source_codec_sha256": snapshot["source_codec_sha256"], "donor_identity_sha256": snapshot["donor_identity_sha256"],
            "dimension": 8, "hidden_size": snapshot["config"]["hidden_size"],
            "token_embedding_dim": snapshot["config"]["token_embedding_dim"],
            "target_vocabulary_count": len(snapshot["codec"]["target_vocabulary"]),
            "tensor_count": len(shapes), "parameter_count": sum(math.prod(shape) for shape in shapes.values()),
            "tensor_shapes": shapes, "original_donor_file_revalidated": False, **_PORT_FLAGS}


def load_private_legacy8_decoder_snapshot(snapshot, *, expected_source_checkpoint_sha256,
                                         expected_source_model_state_sha256=None):
    """Reload a self-contained private head; caller pins its enclosing artifact.

    Pass the original admission receipt's model-state digest as an external
    expectation when available. Digests inside an unpinned snapshot establish
    consistency only, not membership in the source donor checkpoint.
    """
    snapshot = _validated_snapshot(snapshot, expected_source_checkpoint_sha256, expected_source_model_state_sha256)
    model = _build_private_model(snapshot["config"], snapshot["codec"], snapshot["model_state"])
    import torch
    receipt = {"schema": "gte-legacy8-decoder-port-receipt/v1", "status": "private_architecture_port_loaded",
               "snapshot_sha256": _digest(snapshot), "source_checkpoint_sha256": snapshot["source_checkpoint_sha256"],
               "source_model_state_sha256": snapshot["source_model_state_sha256"],
               "donor_identity_sha256": snapshot["donor_identity_sha256"], "weights_copied": True,
               "tensor_copy_verified": True, "device": "cpu", "dtype": "float32", "frozen": True,
               "original_donor_file_revalidated": False, "torch_runtime_version": str(torch.__version__),
               "preparation_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), **_PORT_FLAGS}
    return {"model": model, "codec": copy.deepcopy(snapshot["codec"]), "receipt": receipt, "snapshot": snapshot}


def load_private_legacy8_decoder(path, *, expected_sha256, implementation_root=None):
    """Lazily copy all learned tensors into a private frozen CPU float32 port.

    Its boundary is raw 8D modal latent input. A future 768D student needs an
    explicit new connector; vector padding or copying an 8-column condition
    matrix into a 768-column one cannot preserve this decoder's computation.
    """
    loaded = read_legacy8_decoder_donor(path, expected_sha256=expected_sha256, implementation_root=implementation_root)
    checkpoint, receipt = loaded["checkpoint"], loaded["receipt"]
    snapshot = normalize_legacy8_decoder_donor(checkpoint, source_checkpoint_sha256=expected_sha256)
    port = load_private_legacy8_decoder_snapshot(snapshot, expected_source_checkpoint_sha256=expected_sha256,
        expected_source_model_state_sha256=receipt["model_state_sha256"])
    # Retain the exact source identity even if another process changes the file
    # while constructing the port. No old shared checkpoint is mutated.
    final = inspect_legacy8_decoder_donor(path, expected_sha256=expected_sha256, implementation_root=implementation_root)
    _require(final == receipt, "donor or preparation implementation changed during private load")
    receipt = {**receipt, "status": "private_architecture_port_loaded", "weights_copied": True,
               "tensor_copy_verified": True, "device": "cpu", "dtype": "float32", "frozen": True,
               "torch_runtime_version": port["receipt"]["torch_runtime_version"], "snapshot_sha256": _digest(snapshot)}
    return {"model": port["model"], "codec": port["codec"], "receipt": receipt, "snapshot": snapshot}
