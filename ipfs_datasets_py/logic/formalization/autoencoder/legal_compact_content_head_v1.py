"""Weights-only CPU head for the existing fixed compact-content token profile.

Numerical operations lazily reuse the existing residual GRU. There is no
optimizer, training route, generation loop, source encoder or eligibility grant.
Signature/role context constrains selection only; it never enters the GRU.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct

SCHEMA = "legal-compact-content-head-checkpoint/v1"
SCORE_SCHEMA = "legal-compact-content-head-score/v1"
PROFILE = "object-relational-compact-head-384/v1"
TASK = "conditioning-to-compact-relational-content/v1"
ARCHITECTURE = "residual-projection-latent-formula-gru/v1"
DIMENSION, VOCABULARY_SIZE, MAX_SEQUENCE_TOKENS = 384, 537, 512
MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
MAX_PARENT_BYTES = 48 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_REPORT_BYTES = 20 * 1024 * 1024
MAX_CONTEXT_BYTES, MAX_CODEC_BYTES = 524288, 32768
MAX_JSON_ITEMS, MAX_JSON_DEPTH = 4_000_000, 96
MAX_SOURCE_BYTES = 131072
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_DIRECT_SPECS = (
    ("numerical", "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula",
     "optimizers/logic_theorem_optimizer/modal_latent_formula.py",
     "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"),
    ("transfer", "ipfs_datasets_py.optimizers.logic_theorem_optimizer.domain_384_autoencoder",
     "optimizers/logic_theorem_optimizer/domain_384_autoencoder.py",
     "66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6"),
    ("tokens", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1",
     "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    ("selection", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_selection_v1",
     "logic/formalization/autoencoder/legal_compact_content_selection_v1.py",
     "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"),
)
_SHAPE_FIELDS = ("hidden_size", "token_embedding_dim", "projection_width")
_LEXICAL = ("output.bias", "output.weight", "target_embedding.weight")
_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "accepted", "admitted",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "permitted_inference_context_verified", "conditioning_producer_verified",
    "statutory_checkpoint_qualified", "source_fidelity_verified", "proof_authority",
    "Lean_admitted", "global_prefix_completability_proven",
), False)
_LIMITATIONS = (
    "This weights-only 384D CPU float32 head has zero compact-profile training steps and no optimizer or resume state.",
    "Seeded or old-parent-transferred weights are not a newly trained 537-token decoder or evidence of source fidelity.",
    "Conditioning is a caller-supplied vector; no source encoder, embedding producer or permitted inference context is authenticated.",
    "Signature/ordered-role context is used only by the existing public prefix/selection owners, never as an input to the GRU.",
    "One score call is not a generation loop, source-grounded prediction, legal review, eligible supervision or graph/Lean admission.",
    "Stored initialization lineage is a committed engineering record; restoring it does not replay an unavailable original parent or authenticate a producer principal.",
    "Named source/input endpoint checks are not a lock, arbitrary loaded-bytecode proof, third-party integrity or an operating-system sandbox.",
)


class CompactContentHeadError(ValueError):
    """Bounded contract, input commitment, geometry or named-source refusal."""


def _need(okay, message):
    if not okay:
        raise CompactContentHeadError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _copy(value, maximum, *, allow_bytes=False, ascii_only=False):
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()

    def charge(count):
        nonlocal remaining
        remaining -= count
        _need(remaining >= 0, "complete byte bound exceeded before serialization")

    def text(item):
        _need(len(item) <= maximum, "bounded ordinary string required")
        charge(2)
        for char in item:
            code = ord(char)
            _need(code != 0 and not 0xD800 <= code <= 0xDFFF, "ordinary scalar UTF8 required")
            if char in ('"', "\\") or char in "\b\f\n\r\t":
                charge(2)
            elif code < 32:
                charge(6)
            elif ascii_only and code >= 128:
                charge(6 if code <= 65535 else 12)
            else:
                charge(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)

    def visit(item, depth):
        nonlocal items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH, "complete item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active and len(item) <= items, "cycle or complete item bound exceeded")
            active.add(id(item))
            try:
                charge(2)
                if type(item) is dict:
                    result = {}
                    for index, (key, child) in enumerate(item.items()):
                        _need(type(key) is str, "plain string keys required")
                        charge(1 + bool(index))
                        visit(key, depth + 1)
                        result[key] = visit(child, depth + 1)
                else:
                    result = []
                    for index, child in enumerate(item):
                        if index:
                            charge(1)
                        result.append(visit(child, depth + 1))
                return result
            finally:
                active.remove(id(item))
        if type(item) is bytes and allow_bytes:
            charge(len(item))
        elif type(item) is str:
            text(item)
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded plain integer required")
            charge(len(str(item)))
        elif type(item) is float:
            _need(math.isfinite(item), "finite plain number required")
            charge(len(repr(item)))
        else:
            raise CompactContentHeadError("ordinary containers/primitives required")
        return item

    try:
        return visit(value, 0)
    except (RuntimeError, RecursionError) as error:
        raise CompactContentHeadError("stable bounded ordinary input required") from error


def _wire(value, maximum, *, ensure_ascii=False):
    captured = _copy(value, maximum, ascii_only=ensure_ascii)
    try:
        raw = json.dumps(captured, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=ensure_ascii, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
        raise CompactContentHeadError("bounded canonical ordinary JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _detach(value, maximum):
    return json.loads(_wire(value, maximum))


def _digest(value, maximum=MAX_CHECKPOINT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _fingerprint(value):
    result = hashlib.sha256()

    def visit(item):
        if type(item) is dict:
            result.update(b"d" + str(len(item)).encode() + b":")
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif type(item) is list:
            result.update(b"l" + str(len(item)).encode() + b":")
            for child in item:
                visit(child)
        else:
            raw = item if type(item) is bytes else _wire(item, MAX_INPUT_BYTES)
            result.update((b"b" if type(item) is bytes else b"j") + str(len(raw)).encode() + b":")
            result.update(raw)
    visit(value)
    return result.hexdigest()


def _source(path, expected):
    _need(path.is_absolute() and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents),
          "direct source parents required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_SOURCE_BYTES,
          "bounded regular source required")
    witness = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        _need(witness(os.fstat(stream.fileno())) == witness(before), "source changed before read")
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _need(witness(before) == witness(after) == witness(path.lstat())
          and len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == expected,
          "source changed or raw pin differs")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}


def _sources():
    self_pin = _source(_SELF_PATH, _SELF_SHA)
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _DIRECT_SPECS[0][2]).is_file():
                _need(candidate.resolve() == candidate, "canonical package tree required")
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "canonical numerical/token owners unavailable")
    pins = [self_pin, *[_source(root / relative, sha) for _, _, relative, sha in _DIRECT_SPECS]]
    return root, pins


def _finish(failure, check):
    try:
        check()
    except BaseException:
        if failure is None:
            raise
        BaseException.add_note(failure, "A closing head input/source custody check also failed.")


def _owners(*, numeric=False, transfer=False):
    root, pins = _sources()
    modules, failure = {}, None
    try:
        wanted = {"tokens", "selection"} | ({"numerical"} if numeric else set()) | ({"transfer"} if transfer else set())
        for key, name, relative, _ in _DIRECT_SPECS:
            if key in wanted:
                module = importlib.import_module(name)
                _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                      "canonical direct-owner import origin differs")
                modules[key] = module
        return {"modules": modules, "root": root, "pins": pins}
    except BaseException as error:
        failure = error
        raise
    finally:
        _finish(failure, lambda: _need(_sources() == (root, pins), "source changed during lazy loading"))


def _closing(loaded):
    _need(_sources() == (loaded["root"], loaded["pins"]), "operation source custody changed")
    for key, _, relative, _ in _DIRECT_SPECS:
        if key in loaded["modules"]:
            _need(Path(loaded["modules"][key].__file__).absolute() == loaded["root"] / relative,
                  "direct owner origin changed")


def _implementation():
    return {"head_sha256": _SELF_SHA, "direct_owners": {relative: sha for _, _, relative, sha in _DIRECT_SPECS}}


def _config(offered, parent=None):
    defaults = dict(hidden_size=32, token_embedding_dim=16, projection_width=16, seed=1729)
    if parent is not None:
        defaults.update({key: parent[key] for key in _SHAPE_FIELDS})
        defaults["seed"] = parent["seed"]
    _need(offered is None or type(offered) is dict and set(offered) <= set(defaults), "unknown head configuration")
    defaults.update(offered or {})
    for name, low, high in (("hidden_size", 8, 128), ("token_embedding_dim", 8, 64),
                            ("projection_width", 1, 64), ("seed", 0, (1 << 31) - 1)):
        _need(type(defaults[name]) is int and low <= defaults[name] <= high, "invalid " + name)
    if parent is not None:
        _need(all(defaults[name] == parent[name] for name in _SHAPE_FIELDS), "parent H/E/P geometry must remain unchanged")
    return defaults


def _shapes(config):
    h, e, p = (config[key] for key in _SHAPE_FIELDS)
    return {
        "projection_down.weight": (p, DIMENSION), "projection_down.bias": (p,),
        "projection_up.weight": (DIMENSION, p), "projection_up.bias": (DIMENSION,),
        "condition.weight": (h, DIMENSION), "condition.bias": (h,),
        "target_embedding.weight": (VOCABULARY_SIZE, e),
        "decoder.weight_ih_l0": (3*h, e), "decoder.weight_hh_l0": (3*h, h),
        "decoder.bias_ih_l0": (3*h,), "decoder.bias_hh_l0": (3*h,),
        "output.weight": (VOCABULARY_SIZE, h), "output.bias": (VOCABULARY_SIZE,),
    }


def _f32(value):
    _need(type(value) in (int, float) and math.isfinite(value), "finite plain numeric scalar required")
    try:
        rounded = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as error:
        raise CompactContentHeadError("numeric scalar overflows float32") from error
    _need(math.isfinite(rounded), "numeric scalar overflows float32")
    return rounded


def _state(state, config):
    shapes = _shapes(config)
    _need(type(state) is dict and set(state) == set(shapes), "exact thirteen-state inventory required")
    def visit(value, shape):
        if shape:
            _need(type(value) is list and len(value) == shape[0], "complete state tensor shape differs")
            for child in value:
                visit(child, shape[1:])
        else:
            _need(type(value) is float and _f32(value).hex() == value.hex(),
                  "state scalar must be an exact exported finite float32 float")
    for name, shape in shapes.items():
        visit(state[name], shape)


def _codec(loaded, offered=None):
    tokens = loaded["modules"]["tokens"]
    fixed = tokens.build_compact_content_token_codec_v1()
    sha = tokens.compact_content_token_codec_sha256(fixed)
    _need(fixed["vocabulary_size"] == VOCABULARY_SIZE and fixed["max_sequence_tokens"] == MAX_SEQUENCE_TOKENS,
          "fixed public compact profile differs")
    if offered is not None:
        _need(_wire(offered, MAX_CODEC_BYTES) == _wire(fixed, MAX_CODEC_BYTES), "ordered fixed codec differs")
    return fixed, sha


def _token_rows(vocabulary, parent_vocabulary):
    positions = {token: index for index, token in enumerate(parent_vocabulary)}
    return [{"token_id": index, "token": token, "parent_token_id": positions.get(token),
             "policy": "copied_exact_token" if token in positions else "parent_lexical_row_mean"}
            for index, token in enumerate(vocabulary)]


def _initialization(mode, weights_sha, *, parent=None, parent_sha=None, loaded_parent_sha=None, lineage=None, vocabulary=None):
    warm = parent is not None
    return {
        "mode": mode, "parent_checkpoint_sha256": parent_sha,
        "parent_model_state_sha256": _digest(parent["model_state"], MAX_PARENT_BYTES) if warm else None,
        "parent_loaded_model_state_sha256": loaded_parent_sha,
        "parent_optimizer_steps": parent["progress"]["optimizer_steps"] if warm else None,
        "parent_binding": parent["binding"] if warm else None,
        "parent_shape": {key: parent["config"][key] for key in _SHAPE_FIELDS} if warm else None,
        "parent_vocabulary": parent["codec"]["target_vocabulary"] if warm else None,
        "exact_inherited_tensors": lineage["exact_inherited_tensors"] if warm else [],
        "lexical_mapped_tensors": lineage["lexical_mapped_tensors"] if warm else [],
        "token_rows": _token_rows(vocabulary, parent["codec"]["target_vocabulary"]) if warm else [],
        "new_token_initialization": "trained_parent_lexical_row_mean" if warm else "existing_seeded_constructor",
        "initial_weights_sha256": weights_sha, "parent_modified": False,
        "random_parameters_used": not warm, "fresh_optimizer_required": True,
        "parent_optimizer_state_inherited": False, "parent_public_validation_performed": warm,
    }


def _initialization_check(value, checkpoint):
    keys = {"mode", "parent_checkpoint_sha256", "parent_model_state_sha256", "parent_loaded_model_state_sha256",
            "parent_optimizer_steps", "parent_binding", "parent_shape", "parent_vocabulary",
            "exact_inherited_tensors", "lexical_mapped_tensors", "token_rows", "new_token_initialization",
            "initial_weights_sha256", "parent_modified", "random_parameters_used", "fresh_optimizer_required",
            "parent_optimizer_state_inherited", "parent_public_validation_performed"}
    _need(type(value) is dict and set(value) == keys, "closed initialization record required")
    _need(value["initial_weights_sha256"] == checkpoint["weights_sha256"] and value["parent_modified"] is False
          and value["fresh_optimizer_required"] is True and value["parent_optimizer_state_inherited"] is False,
          "weights-only initialization/resume policy differs")
    if value["mode"] == "seeded_new":
        nulls = ("parent_checkpoint_sha256", "parent_model_state_sha256", "parent_loaded_model_state_sha256",
                 "parent_optimizer_steps", "parent_binding", "parent_shape", "parent_vocabulary")
        _need(all(value[key] is None for key in nulls)
              and all(value[key] == [] for key in ("exact_inherited_tensors", "lexical_mapped_tensors", "token_rows"))
              and value["new_token_initialization"] == "existing_seeded_constructor"
              and value["random_parameters_used"] is True and value["parent_public_validation_performed"] is False,
              "seeded initialization record differs")
    else:
        _need(value["mode"] == "trained_native_384_parent_transfer", "unknown head initialization")
        for key in ("parent_checkpoint_sha256", "parent_model_state_sha256", "parent_loaded_model_state_sha256"):
            _hash(value[key], key)
        _need(type(value["parent_optimizer_steps"]) is int and 1 <= value["parent_optimizer_steps"] <= 10**9,
              "trained parent step declaration required")
        binding = value["parent_binding"]
        _need(type(binding) is dict and set(binding) == {"domain", "lineage_id", "dimension", "runtime_profile", "core_sha256"}
              and binding["domain"] == "legal_ir" and binding["lineage_id"] == "current_legal_v2"
              and type(binding["dimension"]) is int and binding["dimension"] == DIMENSION
              and type(binding["runtime_profile"]) is str and 0 < len(binding["runtime_profile"]) <= 256,
              "native384 parent binding declaration differs")
        _hash(binding["core_sha256"], "parent core declaration")
        _need(type(value["parent_shape"]) is dict and set(value["parent_shape"]) == set(_SHAPE_FIELDS)
              and all(type(value["parent_shape"][key]) is int for key in _SHAPE_FIELDS)
              and value["parent_shape"] == {key: checkpoint["config"][key] for key in _SHAPE_FIELDS},
              "parent shape declaration differs")
        old = value["parent_vocabulary"]
        _need(type(old) is list and 4 <= len(old) <= 4096 and old[:3] == ["<pad>", "<bos>", "<eos>"]
              and all(type(token) is str for token in old) and len(old) == len(set(old)), "parent vocabulary declaration differs")
        _need(value["exact_inherited_tensors"] == sorted(set(_shapes(checkpoint["config"])) - set(_LEXICAL))
              and value["lexical_mapped_tensors"] == list(_LEXICAL)
              and _wire(value["token_rows"], MAX_CHECKPOINT_BYTES)
                  == _wire(_token_rows(checkpoint["codec"]["vocabulary"], old), MAX_CHECKPOINT_BYTES)
              and value["new_token_initialization"] == "trained_parent_lexical_row_mean"
              and value["random_parameters_used"] is False and value["parent_public_validation_performed"] is True,
              "complete transfer mapping declaration differs")


def _checkpoint(offered, expected):
    _hash(expected, "complete head checkpoint")
    value = _copy(offered, MAX_CHECKPOINT_BYTES)
    _need(_digest(value) == expected, "independent complete checkpoint pin differs")
    fields = {"schema", "profile", "task", "architecture", "device", "dtype", "torch_version", "input_dimension", "input_role",
              "codec", "codec_sha256", "max_total_ids", "config", "implementation", "model_state", "weights_sha256",
              "initialization", "optimizer_state_included", "compact_training_steps", "authority",
              "training_mask", "evaluation_gold_mask", "limitations"}
    _need(type(value) is dict and set(value) == fields, "closed compact-head checkpoint required")
    _need(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["task"] == TASK
          and value["architecture"] == ARCHITECTURE and value["device"] == "cpu" and value["dtype"] == "float32"
          and type(value["torch_version"]) is str and 0 < len(value["torch_version"]) <= 128
          and type(value["input_dimension"]) is int and value["input_dimension"] == DIMENSION
          and value["input_role"] == "caller_supplied_conditioning_vector"
          and type(value["max_total_ids"]) is int and value["max_total_ids"] == MAX_SEQUENCE_TOKENS,
          "head profile, task or geometry differs")
    _need(type(value["config"]) is dict and set(value["config"]) == set(_config(None))
          and value["config"] == _config(value["config"]), "closed head config differs")
    _need(value["implementation"] == _implementation(), "head implementation pins differ")
    _hash(value["codec_sha256"], "ordered codec")
    _need(_digest(value["codec"], MAX_CODEC_BYTES) == value["codec_sha256"], "codec hash differs")
    _state(value["model_state"], value["config"])
    _need(value["weights_sha256"] == _digest(value["model_state"]), "complete state digest differs")
    _need(value["optimizer_state_included"] is False and type(value["compact_training_steps"]) is int
          and value["compact_training_steps"] == 0 and value["authority"] == _AUTHORITY
          and all(flag is False for flag in value["authority"].values())
          and type(value["training_mask"]) is int and value["training_mask"] == 0
          and type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0
          and value["limitations"] == list(_LIMITATIONS), "weights-only authority/training boundary differs")
    _initialization_check(value["initialization"], value)
    return value


def _operation(original, work, *, numeric=False, transfer=False, as_bytes=False):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    token = _fingerprint(snapshot)
    loaded, failure = None, None
    def fence():
        _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
              and _fingerprint(snapshot) == token, "original or captured operation inputs changed")
        if loaded is None:
            _sources()
        else:
            _closing(loaded)
    try:
        loaded = _owners(numeric=numeric, transfer=transfer)
        result = work(snapshot, loaded)
        if as_bytes:
            _need(type(result) is bytes and len(result) <= MAX_CHECKPOINT_BYTES,
                  "bounded immutable checkpoint serialization required")
            detached = result
        else:
            detached = _detach(result, MAX_REPORT_BYTES)
        fence()
        return detached
    except BaseException as error:
        failure = error
        raise
    finally:
        _finish(failure, fence)


def _torch(loaded):
    torch = loaded["modules"]["numerical"]._torch()
    _need(torch.get_num_threads() == 1, "caller must arrange one Torch CPU thread")
    _need(str(torch.get_default_device()) == "cpu" and torch.get_default_dtype() == torch.float32,
          "unchanged CPU float32 numerical defaults required")
    _need(not torch.is_autocast_enabled("cpu") and not torch.is_autocast_enabled("cuda"),
          "compact numerical head forbids autocast")
    return torch


def _new_model(loaded, config, vocabulary):
    return loaded["modules"]["numerical"]._model(
        {"dimension": DIMENSION}, {"target_vocabulary": vocabulary}, config)


def _model(checkpoint, loaded):
    numerical = loaded["modules"]["numerical"]
    torch = _torch(loaded)
    _need(checkpoint["torch_version"] == str(torch.__version__), "installed Torch version differs from checkpoint")
    numerical._implementation()
    rng = torch.get_rng_state().clone()
    try:
        model = _new_model(loaded, checkpoint["config"], checkpoint["codec"]["vocabulary"])
        templates = model.state_dict()
        _need(set(templates) == set(_shapes(checkpoint["config"])), "existing model state inventory differs")
        # Build/check all replacement tensors before any state installation.
        state = {name: numerical._tensor(checkpoint["model_state"][name], template, name)
                 for name, template in templates.items()}
        model.load_state_dict(state, strict=True)
        _need(all(value.device.type == "cpu" and value.dtype == torch.float32
                  and bool(torch.isfinite(value).all()) for value in model.state_dict().values()),
              "restored CPU float32 state differs")
        return model.eval()
    finally:
        _need(torch.equal(rng, torch.get_rng_state()), "existing constructor changed ambient CPU RNG")


def create_compact_content_head_v1(*, config=None, parent_checkpoint=None, expected_parent_sha256=None):
    """Create seeded weights or transfer a publicly validated trained native384 parent."""
    original = dict(config=config, parent_checkpoint=parent_checkpoint, expected_parent_sha256=expected_parent_sha256)
    def work(data, loaded):
        fixed, codec_sha = _codec(loaded)
        parent = data["parent_checkpoint"]
        numerical = loaded["modules"]["numerical"]
        torch = _torch(loaded)
        numerical._implementation()
        lineage, parent_sha, loaded_parent_sha = None, None, None
        rng = torch.get_rng_state().clone()
        try:
            if parent is None:
                _need(data["expected_parent_sha256"] is None, "no parent pin without parent required")
                settings = _config(data["config"])
                model = _new_model(loaded, settings, fixed["vocabulary"])
                mode = "seeded_new"
            else:
                _hash(data["expected_parent_sha256"], "complete native parent canonical value")
                parent_raw = _wire(parent, MAX_PARENT_BYTES, ensure_ascii=True)
                parent_sha = numerical.checkpoint_digest(parent)
                _need(parent_sha == hashlib.sha256(parent_raw).hexdigest(),
                      "public native parent canonical identity disagrees")
                _need(parent_sha == data["expected_parent_sha256"], "independent native parent canonical pin differs")
                numerical.validate_checkpoint(parent)
                _need(type(parent["binding"]["dimension"]) is int and parent["binding"]["dimension"] == DIMENSION
                      and type(parent["progress"]["optimizer_steps"]) is int and parent["progress"]["optimizer_steps"] > 0,
                      "publicly validated trained native384 parent required")
                settings = _config(data["config"], parent["config"])
                loaded_parent = {name: torch.tensor(value, dtype=torch.float32).tolist()
                                 for name, value in parent["model_state"].items()}
                loaded_parent_sha = _digest(loaded_parent)
                model, lineage = loaded["modules"]["transfer"]._transfer(parent,
                    {"target_vocabulary": fixed["vocabulary"]}, settings)
                _need(lineage["parent_modified"] is False and lineage["random_parameters_used"] is False,
                      "existing transfer policy differs")
                mode = "trained_native_384_parent_transfer"
            _need(all(tensor.device.type == "cpu" and tensor.dtype == torch.float32
                      and bool(torch.isfinite(tensor).all()) for tensor in model.state_dict().values()),
                  "created state must be finite CPU float32")
            weights = {name: tensor.detach().tolist() for name, tensor in model.state_dict().items()}
            _state(weights, settings)
            weights_sha = _digest(weights)
            result = {"schema": SCHEMA, "profile": PROFILE, "task": TASK, "architecture": ARCHITECTURE,
                "device": "cpu", "dtype": "float32", "torch_version": str(torch.__version__), "input_dimension": DIMENSION,
                "input_role": "caller_supplied_conditioning_vector", "codec": fixed, "codec_sha256": codec_sha,
                "max_total_ids": MAX_SEQUENCE_TOKENS, "config": settings, "implementation": _implementation(),
                "model_state": weights, "weights_sha256": weights_sha,
                "initialization": _initialization(mode, weights_sha, parent=parent, parent_sha=parent_sha,
                    loaded_parent_sha=loaded_parent_sha, lineage=lineage, vocabulary=fixed["vocabulary"]),
                "optimizer_state_included": False, "compact_training_steps": 0,
                "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
                "limitations": list(_LIMITATIONS)}
            _checkpoint(result, _digest(result))
            return result
        finally:
            _need(torch.equal(rng, torch.get_rng_state()), "numerical initialization changed ambient CPU RNG")
    return _operation(original, work, numeric=True, transfer=parent_checkpoint is not None)


def compact_content_head_sha256(checkpoint):
    """Bounded canonical JSON identity only; no schema/model/owner import."""
    before = _source(_SELF_PATH, _SELF_SHA)
    result = _digest(checkpoint)
    _need(_source(_SELF_PATH, _SELF_SHA) == before, "hash-helper source changed")
    return result


def _validated(data, loaded):
    value = _checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"])
    _, sha = _codec(loaded, value["codec"])
    _need(value["codec_sha256"] == sha, "fixed public codec commitment differs")
    _model(value, loaded)
    return value


def validate_compact_content_head_v1(checkpoint, *, expected_checkpoint_sha256):
    """Preflight full weights, fixed codec and source contract, then strictly restore."""
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256), _validated, numeric=True)


def compact_content_head_bytes_v1(checkpoint, *, expected_checkpoint_sha256):
    """Serialize a completely validated checkpoint without an added newline."""
    def work(data, loaded):
        value = _validated(data, loaded)
        raw = _wire(value, MAX_CHECKPOINT_BYTES)
        _need(hashlib.sha256(raw).hexdigest() == data["expected_checkpoint_sha256"],
              "serialized canonical checkpoint differs")
        return raw
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256),
                      work, numeric=True, as_bytes=True)


def load_compact_content_head_v1(checkpoint_raw, *, expected_raw_sha256):
    """Validate independent exact transport bytes, then restore their canonical value."""
    _hash(expected_raw_sha256, "raw checkpoint transport")
    _need(type(checkpoint_raw) is bytes and 0 < len(checkpoint_raw) <= MAX_CHECKPOINT_BYTES,
          "bounded exact checkpoint bytes required")
    _need(hashlib.sha256(checkpoint_raw).hexdigest() == expected_raw_sha256, "raw checkpoint transport pin differs")
    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def nonfinite(_):
        raise CompactContentHeadError("nonfinite checkpoint JSON refused")
    try:
        value = json.loads(checkpoint_raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise CompactContentHeadError("bounded duplicate-free checkpoint JSON required") from error
    return _operation(dict(checkpoint=value, expected_checkpoint_sha256=_digest(value),
                           checkpoint_raw=checkpoint_raw, expected_raw_sha256=expected_raw_sha256),
                      _validated, numeric=True)


def _conditioning(value):
    _need(type(value) is list and len(value) == DIMENSION, "exact 384-entry plain conditioning vector required")
    return [_f32(item) for item in value]


def _forward(checkpoint, conditioning, prefix_ids):
    """One real restored-model forward; no target, context or generation loop."""
    loaded = _owners(numeric=True)
    failure = None
    try:
        torch = _torch(loaded)
        model = _model(checkpoint, loaded)
        numeric = _conditioning(conditioning)
        with torch.inference_mode():
            vector = torch.tensor([numeric], dtype=torch.float32, device="cpu")
            prefix = torch.tensor([prefix_ids], dtype=torch.long, device="cpu")
            projected, logits = model(vector, prefix)
            shape = [1, len(prefix_ids), VOCABULARY_SIZE]
            _need(list(logits.shape) == shape and list(projected.shape) == [1, DIMENSION]
                  and bool(torch.isfinite(logits).all()) and bool(torch.isfinite(projected).all()),
                  "nonfinite or foreign numerical output geometry")
            values = logits[0, -1].detach().tolist()
        return {"logits": values, "numeric_conditioning": numeric, "output_shape": shape}
    except BaseException as error:
        failure = error
        raise
    finally:
        _finish(failure, lambda: _closing(loaded))


def score_compact_content_head_v1(checkpoint, conditioning, prefix_ids, context_raw, *,
                                expected_checkpoint_sha256, expected_context_sha256):
    """Check a supplied prefix/context, then expose one real last-position score vector."""
    def work(data, loaded):
        value = _checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"])
        fixed, sha = _codec(loaded, value["codec"])
        _need(value["codec_sha256"] == sha, "fixed public codec commitment differs")
        numeric = _conditioning(data["conditioning"])
        prefix = data["prefix_ids"]
        _need(type(prefix) is list and 1 <= len(prefix) <= MAX_SEQUENCE_TOKENS
              and all(type(item) is int and -(1 << 63) < item < (1 << 63) for item in prefix),
              "nonempty bounded plain integer prefix required")
        _hash(data["expected_context_sha256"], "context raw bytes")
        _need(type(data["context_raw"]) is bytes and 0 < len(data["context_raw"]) <= MAX_CONTEXT_BYTES
              and hashlib.sha256(data["context_raw"]).hexdigest() == data["expected_context_sha256"],
              "bounded independently pinned context bytes required")
        options = dict(expected_context_sha256=data["expected_context_sha256"], codec=fixed, expected_codec_sha256=sha)
        prefix_report = loaded["modules"]["tokens"].compact_content_allowed_token_ids_v1(prefix, data["context_raw"], **options)
        allowed = prefix_report["allowed_token_ids"]
        logits = logits_sha = selection = shape = None
        next_prefix = list(prefix)
        if allowed:
            observed = _forward(value, data["conditioning"], prefix)
            _need(observed["numeric_conditioning"] == numeric, "numerical conditioning conversion differs")
            logits, shape = observed["logits"], observed["output_shape"]
            _need(type(logits) is list and len(logits) == VOCABULARY_SIZE
                  and all(type(item) is float and math.isfinite(item) for item in logits),
                  "full finite float32 score-vector observation required")
            logits_sha = _digest(logits)
            selection = loaded["modules"]["selection"].select_compact_content_token_v1(
                logits, prefix, data["context_raw"], **options)
            _need(selection["prefix_report"] == prefix_report and selection["logits"] == logits
                  and selection["logits_sha256"] == logits_sha and selection["selection_performed"] is True,
                  "public selector disagrees with complete numerical observation")
            next_prefix = selection["next_prefix_ids"]
        result = {"schema": SCORE_SCHEMA, "profile": PROFILE,
            "status": "scored" if allowed else "no_forward",
            "reason": None if allowed else (prefix_report["reason"] or prefix_report["status"]),
            "checkpoint_sha256": data["expected_checkpoint_sha256"], "weights_sha256": value["weights_sha256"],
            "initialization_mode": value["initialization"]["mode"],
            "torch_version": value["torch_version"], "runtime_torch_version_verified": bool(allowed),
            "conditioning": data["conditioning"], "conditioning_sha256": _digest(data["conditioning"]),
            "numeric_conditioning": numeric, "prefix_ids": prefix, "next_prefix_ids": next_prefix,
            "context_raw_sha256": data["expected_context_sha256"], "codec_sha256": sha,
            "prefix_report": prefix_report, "numerical_forward_executed": bool(allowed),
            "model_restore_performed": bool(allowed), "logits": logits, "logits_sha256": logits_sha,
            "selection": selection, "output_shape": shape, "compact_training_steps": 0,
            "optimizer_executed": False, "authority": dict(_AUTHORITY),
            "training_mask": 0, "evaluation_gold_mask": 0, "owner_pins": loaded["pins"],
            "limitations": list(_LIMITATIONS)}
        return result
    return _operation(dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_context_sha256=expected_context_sha256), work)


__all__ = ["CompactContentHeadError", "create_compact_content_head_v1", "compact_content_head_sha256",
           "validate_compact_content_head_v1", "compact_content_head_bytes_v1",
           "load_compact_content_head_v1", "score_compact_content_head_v1"]
