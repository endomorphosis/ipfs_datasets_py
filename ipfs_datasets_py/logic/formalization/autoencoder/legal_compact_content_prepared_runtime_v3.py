"""Operation-local prepared inference for the unchanged compact v2 checkpoint.

One structural inspection and at most one model restore serve each public score
or bounded generation. Every step still runs the full-prefix GRU. Source/input,
model-state, runtime and CPU-RNG custody remain active; no global model cache,
optimizer, source encoder, target input or semantic authority is introduced.
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

SCHEMA = "legal-compact-content-generation/v3"
SCORE_SCHEMA = "legal-compact-content-head-score/v3"
SCORE_PROFILE = "prepared-trained-compact-head-384/v3"
PROFILE = "bounded-prepared-trained-compact-content-generation-384/v3"
BATCH_SCHEMA = "legal-compact-content-generation-batch-prediction/v3"
BATCH_PROFILE = "verified-prepared-trace-to-declared-content-observation/v3"
MAX_SEQUENCE_TOKENS = 512
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
MAX_CONTEXT_BYTES = 524288
MAX_POPULATION_BYTES = 128 * 1024
MAX_INPUT_BYTES = 192 * 1024 * 1024
MAX_REPORT_BYTES = 96 * 1024 * 1024
MAX_JSON_ITEMS, MAX_JSON_DEPTH = 12_000_000, 96
MAX_SOURCE_BYTES = 4 * 1024 * 1024
PREFIX_ORIGINS = ("bos_seed", "authored_fixture", "target_derived_label", "caller_supplied_unverified")
CONTEXT_ORIGINS = ("authored_fixture", "target_derived_label", "caller_supplied_unverified")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
# The head is a separately authored producer. This observed generation must be
# refreshed only after its author freezes a reviewed replacement, before enroll.
_SOURCE_SPECS = (
    ("engine", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_training_v2",
     "logic/formalization/autoencoder/legal_compact_content_training_v2.py",
     "3ff34b8094a8bb19315741a03873c95f7d809654b35717fd4cee97e074fd2b59"),
    ("tokens", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1",
     "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    ("selection", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_selection_v1",
     "logic/formalization/autoencoder/legal_compact_content_selection_v1.py",
     "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"),
    ("batch", "ipfs_datasets_py.logic.autoformal.legal_relational_batch_evaluation_v1",
     "logic/autoformal/legal_relational_batch_evaluation_v1.py",
     "663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138"),
    (None, None, "optimizers/logic_theorem_optimizer/modal_latent_formula.py",
     "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"),
    (None, None, "optimizers/logic_theorem_optimizer/domain_384_autoencoder.py",
     "66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6"),
    (None, None, "logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
    ("legacy_head", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_head_v1",
     "logic/formalization/autoencoder/legal_compact_content_head_v1.py",
     "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"),
    ("baseline", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_trained_runtime_v2",
     "logic/formalization/autoencoder/legal_compact_content_trained_runtime_v2.py",
     "43037fe64c58de0bcfc2072178eabe1276b4a020863e20b9498a634763b56e5a"),
)
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "source_bound", "source_encoder_authenticated",
    "conditioning_producer_verified", "context_permission_verified", "prefix_origin_verified",
    "held_out_generation_verified", "training_qualified", "evaluation_gold_qualified",
    "legal_accuracy_established", "convergence_proved", "accepted", "admitted", "Lean_admitted"), False)
_LIMITATIONS = [
    "Conditioning, context origin and prefix origin are caller observations; no source encoder or permitted context is authenticated.",
    "Initial prefix IDs are supplied. Only selected_token_ids were emitted by these numerical decisions; generated_ids includes the supplied prefix.",
    "raw_argmax_ids_by_step records raw maxima evaluated along the constrained selected prefixes, not an independently autoregressed unconstrained trajectory.",
    "Fixture-trained or exposed-prefix continuation does not establish complete source-generated prediction quality or held-out accuracy.",
    "Pure inspection composes the exact installed trainer contract; recorded runtime and Adam metadata are declarations until a model-only forward verifies the live runtime. No optimizer is constructed or restored.",
    "Historical optimizer steps and parent hashes are retained commitments, not independently authenticated training history; this call performs no training.",
    "Terminal or blocked prefixes retain their original IDs without importing a numerical owner, allocating a model or verifying the live runtime.",
    "Whole finite traces belong in indexed artifacts addressed by content hashes. Compact lexical geometry does not establish provider-token savings or justify injecting full traces into supervisor prompts.",
    "Prepared inspection/restore counts are enclosing-operation totals, repeated in trace rows rather than additive per-token work. Every numerical step still runs the complete prefix.",
    "Input fingerprints use a bounded typed stream rather than a per-scalar JSON encoding. Their digests are internal custody observations, not canonical checkpoint identities.",
    "Named source/input fences are finite custody checks, not a hermetic interpreter, arbitrary loaded-bytecode proof or third-party binary attestation.",
]
_REPORT_FIELDS = {"schema", "profile", "status", "reason", "checkpoint_sha256", "weights_sha256", "codec_sha256",
    "conditioning", "conditioning_sha256", "initial_prefix_ids", "prefix_origin", "context_origin",
    "context_raw_sha256", "context_sha256", "settings", "settings_sha256", "trace", "selected_token_ids",
    "raw_argmax_ids_by_step", "generated_ids", "emitted_token_count", "total_token_count", "score_call_count",
    "numerical_forward_count", "final_prefix_report", "final_decoding", "exposure", "model_executed",
    "training_executed", "compact_optimizer_executed", "owner_pins", "authority", "training_mask",
    "evaluation_gold_mask", "limitations", "compact_training_steps", "initial_checkpoint_sha256", "initial_weights_sha256",
    "parent_checkpoint_sha256", "training_progress", "runtime_verified", "optimizer_constructed", "optimizer_state_restored", "preparation"}


class CompactContentGenerationError(ValueError):
    """Input, whole bound, source generation or cross-owner commitment failed."""


def _need(ok, message):
    if not ok:
        raise CompactContentGenerationError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "independent SHA256 required: " + label)


def _copy(value, maximum, *, allow_bytes=False):
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()
    def charge(count):
        nonlocal remaining
        remaining -= count
        _need(remaining >= 0, "whole JSON byte bound exceeded")
    def text(item):
        _need(len(item) <= maximum, "bounded string required")
        charge(2)
        for character in item:
            code = ord(character)
            _need(code != 0 and not 0xD800 <= code <= 0xDFFF, "ordinary scalar UTF8 required")
            if character in ('"', "\\") or character in "\b\f\n\r\t":
                charge(2)
            elif code < 32:
                charge(6)
            else:
                charge(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
    def visit(item, depth):
        nonlocal items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH, "whole JSON item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active and len(item) <= items, "cyclic or oversized ordinary container")
            active.add(id(item))
            charge(2)
            try:
                if type(item) is dict:
                    result = {}
                    for index, (key, child) in enumerate(item.items()):
                        _need(type(key) is str, "plain string keys required")
                        charge(1 + bool(index))
                        result[visit(key, depth + 1)] = visit(child, depth + 1)
                    return result
                result = []
                for index, child in enumerate(item):
                    if index: charge(1)
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
            _need(math.isfinite(item), "finite plain numbers required")
            charge(len(repr(item)))
        else:
            raise CompactContentGenerationError("ordinary JSON containers/primitives required")
        return item
    try:
        return visit(value, 0)
    except (RuntimeError, RecursionError) as error:
        raise CompactContentGenerationError("stable bounded ordinary input required") from error


def _wire(value, maximum=MAX_REPORT_BYTES):
    checked = _copy(value, maximum)
    raw = json.dumps(checked, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    _need(len(raw) <= maximum, "complete serialized bound exceeded; truncation refused")
    return raw


def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _fingerprint(value, maximum=MAX_INPUT_BYTES, *, allow_bytes=True):
    """Bounded, type-injective streaming custody digest; no retained copy.

    Tags and explicit lengths distinguish all admitted scalar/container types,
    including bool/int and signed float zero. The byte charge is the same JSON
    budget as _copy, with exact bytes charged as raw transport. This digest is
    deliberately separate from canonical public JSON/checkpoint hashes.
    """
    digest = hashlib.sha256()
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()
    def charge(count):
        nonlocal remaining
        remaining -= count
        _need(remaining >= 0, "whole fingerprint byte bound exceeded")
    def frame(tag, body):
        digest.update(tag)
        digest.update(str(len(body)).encode("ascii"))
        digest.update(b":")
        digest.update(body)
    def visit(item, depth):
        nonlocal items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH, "whole fingerprint item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active and len(item) <= items, "cyclic or oversized ordinary container")
            active.add(id(item)); charge(2)
            try:
                digest.update((b"d" if type(item) is dict else b"l") + str(len(item)).encode("ascii") + b":")
                if type(item) is dict:
                    _need(all(type(key) is str for key in item), "plain string keys required")
                    for index, key in enumerate(sorted(item)):
                        charge(1 + bool(index)); visit(key, depth + 1); visit(item[key], depth + 1)
                else:
                    for index, child in enumerate(item):
                        if index: charge(1)
                        visit(child, depth + 1)
            finally:
                active.remove(id(item))
        elif type(item) is bytes and allow_bytes:
            charge(len(item)); frame(b"b", item)
        elif type(item) is str:
            _need(len(item) <= maximum, "bounded string required")
            charge(2)
            for character in item:
                code = ord(character)
                _need(code != 0 and not 0xD800 <= code <= 0xDFFF, "ordinary scalar UTF8 required")
                if character in ('"', "\\") or character in "\b\f\n\r\t": charge(2)
                elif code < 32: charge(6)
                else: charge(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
            frame(b"s", item.encode("utf-8"))
        elif item is None:
            charge(4); digest.update(b"n")
        elif type(item) is bool:
            charge(4 if item else 5); digest.update(b"t" if item else b"f")
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded plain integer required")
            raw = str(item).encode("ascii"); charge(len(raw)); frame(b"i", raw)
        elif type(item) is float:
            _need(math.isfinite(item), "finite plain numbers required")
            charge(len(repr(item))); digest.update(b"r" + struct.pack(">d", item))
        else:
            raise CompactContentGenerationError("ordinary JSON containers/primitives required")
    try:
        visit(value, 0)
    except (RuntimeError, RecursionError, KeyError) as error:
        raise CompactContentGenerationError("stable bounded ordinary input required") from error
    return digest.hexdigest()


def _source(path, expected):
    _need(path.is_absolute() and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents), "unaliased source parents required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded single-link source required")
    witness = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        _need(witness(os.fstat(stream.fileno())) == witness(before), "source changed before read")
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _need(witness(before) == witness(after) == witness(path.lstat()) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, "source witness or raw pin changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, witness(after)


def _sources():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SOURCE_SPECS[1][2]).is_file():
                _need(candidate.resolve() == candidate, "canonical source tree required")
                root = candidate
                break
        if root is not None: break
    _need(root is not None, "canonical dependencies unavailable")
    observed = [_source(_SELF_PATH, _SELF_SHA), *[_source(root / relative, sha) for _, _, relative, sha in _SOURCE_SPECS]]
    return root, observed


def _owners():
    root, observed = _sources()
    modules = {}
    failure = None
    try:
        for key, name, relative, _ in _SOURCE_SPECS:
            if key is not None:
                module = importlib.import_module(name)
                _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative, "canonical public owner origin required")
                modules[key] = module
        return root, observed, modules
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_sources() == (root, observed), "source changed during lazy imports")
        except BaseException:
            if failure is None: raise
            BaseException.add_note(failure, "A closing lazy-import source check also failed.")


def _operation(original, work):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    token = _fingerprint(snapshot)
    loaded, failure = None, None
    def fence():
        _need(_fingerprint(original) == token
              and _fingerprint(snapshot) == token, "original or detached operation inputs changed")
        if loaded is not None:
            root, observed, modules = loaded
            _need(_sources() == (root, observed), "operation source custody changed")
            for key, _, relative, _ in _SOURCE_SPECS:
                if key is not None:
                    _need(Path(modules[key].__file__).absolute() == root / relative, "public owner origin changed")
    try:
        loaded = _owners()
        result = work(snapshot, loaded, fence)
        raw = _wire(result)
        fence()
        return json.loads(raw)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None: raise
            BaseException.add_note(failure, "A closing generation input/source custody check also failed.")


def _inputs(checkpoint, conditioning, prefix_ids, context_raw, expected_checkpoint_sha256,
            expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    value = dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids, context_raw=context_raw,
        expected_checkpoint_sha256=expected_checkpoint_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin=prefix_origin, context_origin=context_origin)
    checked = _copy(value, MAX_INPUT_BYTES, allow_bytes=True)
    for key in ("expected_checkpoint_sha256", "expected_context_sha256"): _hash(checked[key], key)
    _need(type(checked["checkpoint"]) is dict and _digest(checked["checkpoint"], MAX_CHECKPOINT_BYTES) == expected_checkpoint_sha256, "complete checkpoint commitment differs")
    _need(type(checked["conditioning"]) is list and len(checked["conditioning"]) == 384
          and all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 1e8 for x in checked["conditioning"]), "plain384 conditioning vector required")
    _need(type(checked["prefix_ids"]) is list and 1 <= len(checked["prefix_ids"]) <= MAX_SEQUENCE_TOKENS
          and all(type(x) is int for x in checked["prefix_ids"]), "nonempty bounded plain integer prefix required")
    _need(type(max_new_tokens) is int and 1 <= max_new_tokens <= MAX_SEQUENCE_TOKENS, "bounded positive new-token allowance required")
    _need(type(prefix_origin) is str and prefix_origin in PREFIX_ORIGINS and (prefix_origin != "bos_seed" or checked["prefix_ids"] == [1]), "declared prefix origin differs")
    _need(type(context_origin) is str and context_origin in CONTEXT_ORIGINS, "declared context origin differs")
    _need(type(context_raw) is bytes and 0 < len(context_raw) <= MAX_CONTEXT_BYTES
          and hashlib.sha256(context_raw).hexdigest() == expected_context_sha256, "raw context commitment differs")
    return value


def _producer_rows(report, loaded, expected_paths):
    rows = report["owner_pins"]
    available = {row[0]["path"]: row[0] for row in loaded[1]}
    _need(type(rows) is list and len(rows) == len(expected_paths), "complete public producer population required")
    _need(all(type(row) is dict and row == available.get(row.get("path")) for row in rows)
          and {row["path"] for row in rows} == expected_paths, "public producer descriptors differ")
    _need(type(report["authority"]) is dict and report["authority"] and all(x is False for x in report["authority"].values())
          and type(report["training_mask"]) is int and report["training_mask"] == 0
          and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0, "public authority or masks differ")





def _inspect(checkpoint, expected, loaded):
    """Reuse the byte-pinned v2 pure contract exactly once per public operation."""
    return loaded[2]["baseline"]._inspect(checkpoint, expected, loaded)


def inspect_compact_content_prepared_checkpoint_v3(checkpoint, *, expected_checkpoint_sha256):
    """Return structurally checked v2 state, without verifying live runtime or history.

    No numerical owner/Torch import, model allocation, Adam construction or
    restoration occurs here. Runtime fields remain recorded declarations.
    """
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256),
        lambda data, loaded, fence: _inspect(data["checkpoint"], data["expected_checkpoint_sha256"], loaded))


class _PreparedModel:
    """Private model lifetime for one operation; never returned or cached."""
    def __init__(self, checkpoint, conditioning, loaded, fence):
        self.head, self.trainer = loaded[2]["legacy_head"], loaded[2]["engine"]
        self.fence, self.model, self.closed = fence, None, False
        self.numeric_owners = self.head._owners(numeric=True)
        self.torch = self.rng = None
        try:
            self.torch = self.head._torch(self.numeric_owners)
            self.rng = self.torch.get_rng_state().clone()
            self.runtime = self.trainer._runtime(self.head, self.numeric_owners)
            _need(_wire(self.runtime, 32768) == _wire(checkpoint["runtime"], 32768),
                  "actual inference runtime differs from trained checkpoint")
            numerical = self.numeric_owners["modules"]["numerical"]
            numerical._implementation()
            self.model = numerical._model({"dimension": 384},
                {"target_vocabulary": checkpoint["codec"]["vocabulary"]}, checkpoint["config"])
            templates = self.model.state_dict()
            _need(list(templates) == checkpoint["parameter_order"], "trained model-only parameter order differs")
            state = {name: numerical._tensor(checkpoint["model_state"][name], template, name)
                     for name, template in templates.items()}
            self.model.load_state_dict(state, strict=True)
            self.model.eval()
            _need({name: tensor.detach().tolist() for name, tensor in self.model.state_dict().items()}
                  == checkpoint["model_state"], "model-only restore changed trained weights")
            self.numeric_conditioning = self.head._conditioning(conditioning)
            self.vector = self.torch.tensor([self.numeric_conditioning], dtype=self.torch.float32, device="cpu")
            self.vector_bytes = self.vector.detach().view(self.torch.uint8).clone()
            self.parameters = tuple((name, id(value)) for name, value in self.model.named_parameters())
            self.buffers = tuple((name, id(value)) for name, value in self.model.named_buffers())
            self.modules = tuple((name, id(value), type(value)) for name, value in self.model.named_modules())
            self.states = {name: (self._metadata(tensor), tensor.detach().contiguous().view(self.torch.uint8).clone())
                           for name, tensor in self.model.state_dict().items()}
            self._guard()
        except BaseException as error:
            # Constructor failures must close numerical source/RNG custody too.
            self.head._finish(error, self._close_unprepared)
            self.model = self.vector = None
            self.closed = True
            raise

    @staticmethod
    def _metadata(tensor):
        return (tuple(tensor.shape), str(tensor.dtype), str(tensor.device),
                str(tensor.layout), tuple(tensor.stride()), tensor.storage_offset())

    def _close_unprepared(self):
        self.fence()
        self.head._closing(self.numeric_owners)
        if self.torch is not None and self.rng is not None:
            _need(self.torch.equal(self.rng, self.torch.get_rng_state()), "prepared inference changed ambient CPU RNG")

    def _guard(self):
        _need(not self.closed and self.model is not None, "prepared model lifetime ended")
        self.fence()
        self.head._closing(self.numeric_owners)
        _need(_wire(self.trainer._runtime(self.head, self.numeric_owners), 32768)
              == _wire(self.runtime, 32768), "live runtime changed during prepared operation")
        _need(self.torch.equal(self.rng, self.torch.get_rng_state()), "prepared inference changed ambient CPU RNG")
        _need(tuple((name, id(value)) for name, value in self.model.named_parameters()) == self.parameters
              and tuple((name, id(value)) for name, value in self.model.named_buffers()) == self.buffers
              and tuple((name, id(value), type(value)) for name, value in self.model.named_modules()) == self.modules
              and all(module.training is False for module in self.model.modules()),
              "prepared parameter/module inventory or eval mode changed")
        states = self.model.state_dict()
        _need(list(states) == list(self.states), "prepared complete state inventory changed")
        for name, tensor in states.items():
            metadata, original = self.states[name]
            _need(self._metadata(tensor) == metadata and self.torch.equal(
                tensor.detach().contiguous().view(self.torch.uint8), original),
                "prepared model state changed: " + name)
        _need(self.vector.dtype == self.torch.float32 and self.vector.device.type == "cpu"
              and tuple(self.vector.shape) == (1, 384)
              and self.torch.equal(self.vector.detach().contiguous().view(self.torch.uint8), self.vector_bytes),
              "prepared numerical conditioning changed")

    def forward(self, prefix_ids):
        """One unchanged full-prefix model forward, without restoring again."""
        failure = None
        try:
            self._guard()
            with self.torch.inference_mode():
                prefix = self.torch.tensor([prefix_ids], dtype=self.torch.long, device="cpu")
                projected, logits = self.model(self.vector, prefix)
                shape = [1, len(prefix_ids), 537]
                _need(list(logits.shape) == shape and list(projected.shape) == [1, 384]
                      and bool(self.torch.isfinite(logits).all()) and bool(self.torch.isfinite(projected).all()),
                      "trained forward geometry or finite values differ")
                scores = logits[0, -1].detach().tolist()
            self._guard()
            return {"logits": scores, "numeric_conditioning": list(self.numeric_conditioning),
                    "output_shape": shape, "runtime": dict(self.runtime)}
        except BaseException as error:
            failure = error
            raise
        finally:
            self.head._finish(failure, self._guard)

    def close(self):
        """Check custody even after failure and end this private model lifetime."""
        try:
            self._guard()
        finally:
            self.closed = True
            self.model = self.vector = None
            self.states = self.vector_bytes = None


def _preparation(session):
    return dict(checkpoint_inspection_count=1, model_restore_count=int(session is not None),
        scope="enclosing_public_operation", full_prefix_each_step=True,
        cross_call_model_cache=False, incremental_hidden_state=False)


def _close_session(box, failure, loaded):
    if box[0] is not None:
        loaded[2]["legacy_head"]._finish(failure, box[0].close)


def _prepare_score(data, loaded, fence):
    # The pinned inspector returns a detached checked value. Put it back into
    # the captured input so the same enclosing custody fence covers it too.
    value = _inspect(data["checkpoint"], data["expected_checkpoint_sha256"], loaded)
    data["checkpoint"] = value
    fixed = loaded[2]["tokens"].build_compact_content_token_codec_v1()
    codec_sha = loaded[2]["tokens"].compact_content_token_codec_sha256(fixed)
    _need(_wire(value["codec"]) == _wire(fixed) and value["codec_sha256"] == codec_sha,
          "trained checkpoint fixed codec differs")
    _need(type(data["conditioning"]) is list and len(data["conditioning"]) == 384
          and all(type(number) in (int, float) and math.isfinite(number) and abs(number) <= 1e8
                  for number in data["conditioning"]), "bounded plain384 conditioning required")
    # Keep the validated codec under the same captured checkpoint fence.
    fixed = value["codec"]
    numeric = loaded[2]["legacy_head"]._conditioning(data["conditioning"])
    prefix = data["prefix_ids"]
    _need(type(prefix) is list and 1 <= len(prefix) <= MAX_SEQUENCE_TOKENS
          and all(type(item) is int and -(1 << 63) < item < (1 << 63) for item in prefix),
          "nonempty bounded plain integer prefix required")
    _hash(data["expected_context_sha256"], "context")
    _need(type(data["context_raw"]) is bytes and 0 < len(data["context_raw"]) <= MAX_CONTEXT_BYTES
          and hashlib.sha256(data["context_raw"]).hexdigest() == data["expected_context_sha256"],
          "independently pinned bounded context bytes required")
    fence()
    return value, fixed, codec_sha, numeric


def _score(data, loaded, fence, prepared, prefix_ids, box):
    """One grammar/score operation under an already inspected checkpoint."""
    root, observed, modules = loaded
    value, fixed, codec_sha, numeric = prepared
    prefix = _copy(prefix_ids, 8192)
    original_prefix = _fingerprint(prefix, 8192)
    def check():
        if box[0] is None: fence()
        else: box[0]._guard()
        _need(_fingerprint(prefix_ids, 8192) == original_prefix
              and _fingerprint(prefix, 8192) == original_prefix, "original or captured score prefix changed")
    failure = None
    try:
        check()
        options = dict(expected_context_sha256=data["expected_context_sha256"], codec=fixed,
                       expected_codec_sha256=codec_sha)
        prefix_report = modules["tokens"].compact_content_allowed_token_ids_v1(prefix, data["context_raw"], **options)
        check()
        logits = logits_sha = selection = shape = None
        next_prefix, allowed = list(prefix), prefix_report["allowed_token_ids"]
        restored = False
        if allowed:
            if box[0] is None:
                box[0] = _PreparedModel(value, data["conditioning"], loaded, fence)
                restored = True
            check()
            result = box[0].forward(prefix)
            check()
            _need(result["numeric_conditioning"] == numeric and result["runtime"] == value["runtime"]
                  and result["output_shape"] == [1, len(prefix), 537],
                  "numeric conditioning, runtime or output geometry differs")
            logits, shape = result["logits"], result["output_shape"]
            _need(type(logits) is list and len(logits) == 537
                  and all(type(item) is float and math.isfinite(item) for item in logits),
                  "complete finite537 score vector required")
            logits_sha = _digest(logits)
            selection = modules["selection"].select_compact_content_token_v1(logits, prefix, data["context_raw"], **options)
            check()
            _need(selection["prefix_report"] == prefix_report and selection["logits"] == logits
                  and selection["logits_sha256"] == logits_sha and selection["selection_performed"] is True,
                  "existing selector disagrees with actual model observation")
            next_prefix = selection["next_prefix_ids"]
        result = dict(schema=SCORE_SCHEMA, profile=SCORE_PROFILE, status="scored" if allowed else "no_forward",
            reason=None if allowed else (prefix_report["reason"] or prefix_report["status"]),
            checkpoint_sha256=data["expected_checkpoint_sha256"], weights_sha256=value["weights_sha256"],
            initialization_mode=value["initial_checkpoint"]["initialization"]["mode"],
            torch_version=value["runtime"]["torch_version"], runtime_torch_version_verified=bool(allowed),
            runtime_verified=bool(allowed), conditioning=data["conditioning"],
            conditioning_sha256=_digest(data["conditioning"]), numeric_conditioning=numeric,
            prefix_ids=prefix, next_prefix_ids=next_prefix, context_raw_sha256=data["expected_context_sha256"],
            codec_sha256=codec_sha, prefix_report=prefix_report, numerical_forward_executed=bool(allowed),
            model_restore_performed=restored, prepared_model_reused=bool(allowed) and not restored,
            logits=logits, logits_sha256=logits_sha, selection=selection, output_shape=shape,
            compact_training_steps=value["progress"]["optimizer_steps"], optimizer_executed=False,
            optimizer_constructed=False, optimizer_state_restored=False,
            training_checkpoint_profile=value["profile"], training_progress=value["progress"],
            initial_checkpoint_sha256=value["initial_checkpoint_sha256"], initial_weights_sha256=value["initial_weights_sha256"],
            parent_checkpoint_sha256=value["parent_checkpoint_sha256"], preparation=_preparation(box[0]),
            authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0,
            owner_pins=[row[0] for row in observed], limitations=list(_LIMITATIONS))
        check()
        return _copy(result, MAX_REPORT_BYTES)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            check()
        except BaseException:
            if failure is None: raise
            BaseException.add_note(failure, "A closing prepared score custody check also failed.")


def score_compact_content_prepared_v3(checkpoint, conditioning, prefix_ids, context_raw, *,
                                     expected_checkpoint_sha256, expected_context_sha256):
    """Standalone scoring retains full inspection and one private model restore."""
    def work(data, loaded, fence):
        box, failure = [None], None
        try:
            prepared = _prepare_score(data, loaded, fence)
            return _score(data, loaded, fence, prepared, data["prefix_ids"], box)
        except BaseException as error:
            failure = error
            raise
        finally:
            _close_session(box, failure, loaded)
    return _operation(dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_context_sha256=expected_context_sha256), work)


def generate_compact_content_prepared_v3(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Continue an explicit supplied prefix; emit no more than the finite allowance."""
    original = _inputs(checkpoint, conditioning, prefix_ids, context_raw, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
    def work(data, loaded, fence):
        root, observed, modules = loaded
        tokens = modules["tokens"]
        prepared = _prepare_score(data, loaded, fence)
        checked, codec, codec_sha, numeric = prepared
        options = dict(expected_context_sha256=data["expected_context_sha256"], codec=codec,
                       expected_codec_sha256=codec_sha)
        box = [None]
        def guard():
            if box[0] is None: fence()
            else: box[0]._guard()
        failure = None
        try:
            head_paths = {row[0]["path"] for row in observed}
            token_paths = {str(root / _SOURCE_SPECS[i][2]) for i in (1, 6)}
            current, emitted, argmax, trace = list(data["prefix_ids"]), [], [], []
            settings = dict(max_new_tokens=data["max_new_tokens"], max_total_ids=MAX_SEQUENCE_TOKENS,
                            prefix_origin=data["prefix_origin"], context_origin=data["context_origin"])
            status = reason = final_prefix = None
            while True:
                if len(emitted) >= data["max_new_tokens"]:
                    status, reason = "step_budget_exhausted", "max_new_tokens_reached"
                    break
                guard()
                score = _score(data, loaded, fence, prepared, current, box)
                guard()
                _producer_rows(score, loaded, head_paths)
                codec, codec_sha = checked["codec"], checked["codec_sha256"]
                options = dict(expected_context_sha256=data["expected_context_sha256"], codec=codec, expected_codec_sha256=codec_sha)
                _need(score["schema"] == SCORE_SCHEMA
                      and score["checkpoint_sha256"] == data["expected_checkpoint_sha256"]
                      and score["weights_sha256"] == checked["weights_sha256"] and score["codec_sha256"] == codec_sha
                      and score["conditioning"] == data["conditioning"] and score["conditioning_sha256"] == _digest(data["conditioning"])
                      and score["prefix_ids"] == current and score["context_raw_sha256"] == data["expected_context_sha256"]
                      and score["optimizer_executed"] is False and score["compact_training_steps"] == checked["progress"]["optimizer_steps"]
                      and score["training_progress"] == checked["progress"]
                      and score["initial_checkpoint_sha256"] == checked["initial_checkpoint_sha256"]
                      and score["initial_weights_sha256"] == checked["initial_weights_sha256"]
                      and score["parent_checkpoint_sha256"] == checked["parent_checkpoint_sha256"]
                      and score["optimizer_constructed"] is score["optimizer_state_restored"] is False
                      and score["preparation"] == _preparation(box[0]),
                      "head report disagrees with original generation inputs")
                trace.append(score)
                final_prefix = score["prefix_report"]
                _producer_rows(final_prefix, loaded, token_paths)
                _need(final_prefix["offered_ids"] == current and final_prefix["context_raw_sha256"] == data["expected_context_sha256"]
                      and final_prefix["codec_sha256"] == codec_sha, "public prefix input commitments differ")
                if score["status"] == "no_forward":
                    _need(score["numerical_forward_executed"] is score["model_restore_performed"] is score["prepared_model_reused"] is False
                          and score["runtime_verified"] is score["runtime_torch_version_verified"] is False
                          and score["logits"] is score["logits_sha256"] is score["selection"] is score["output_shape"] is None
                          and score["next_prefix_ids"] == current and final_prefix["allowed_token_ids"] == [], "no-forward disposition differs")
                    status = "supplied_complete" if not emitted and final_prefix["status"] == "complete" else "blocked"
                    reason = "supplied_prefix_already_complete" if status == "supplied_complete" else (final_prefix["reason"] or final_prefix["status"])
                    break
                selected = score["selection"]
                _need(score["status"] == "scored" and score["numerical_forward_executed"] is True
                      and score["model_restore_performed"] is (len(emitted) == 0)
                      and score["prepared_model_reused"] is (len(emitted) != 0)
                      and score["runtime_verified"] is score["runtime_torch_version_verified"] is True
                      and type(score["logits"]) is list and len(score["logits"]) == 537
                      and all(type(x) is float and math.isfinite(x) for x in score["logits"])
                      and score["logits_sha256"] == _digest(score["logits"])
                      and selected["logits"] == score["logits"] and selected["logits_sha256"] == score["logits_sha256"]
                      and selected["offered_prefix_ids"] == current and selected["prefix_report"] == final_prefix
                      and selected["selection_performed"] is True and type(selected["selected_token_id"]) is int
                      and selected["selected_token_id"] in final_prefix["allowed_token_ids"]
                      and selected["next_prefix_ids"] == current + [selected["selected_token_id"]]
                      and score["next_prefix_ids"] == selected["next_prefix_ids"]
                      and len(current) < MAX_SEQUENCE_TOKENS, "complete score/selected-prefix binding differs")
                emitted.append(selected["selected_token_id"])
                argmax.append(selected["raw_argmax_token_id"])
                current = list(score["next_prefix_ids"])
                guard()
                final_prefix = tokens.compact_content_allowed_token_ids_v1(current, data["context_raw"], **options)
                guard()
                _producer_rows(final_prefix, loaded, token_paths)
                _need(final_prefix["offered_ids"] == current and final_prefix["context_raw_sha256"] == data["expected_context_sha256"]
                      and final_prefix["codec_sha256"] == codec_sha, "public next-prefix commitments differ")
                if final_prefix["status"] == "complete":
                    status, reason = "complete", None
                    break
                if not final_prefix["allowed_token_ids"]:
                    status, reason = "blocked", final_prefix["reason"] or final_prefix["status"]
                    break
            guard()
            decoded = tokens.decode_compact_content_tokens_v1(current, data["context_raw"], **options)
            guard()
            _producer_rows(decoded, loaded, token_paths)
            _need(decoded["generated_ids"] == current and decoded["context_raw_sha256"] == data["expected_context_sha256"]
                  and decoded["codec_sha256"] == codec_sha and decoded["context_sha256"] == final_prefix["context_sha256"], "final token intake commitments differ")
            _need((status in ("complete", "supplied_complete")) == (decoded["status"] == "valid_candidate"), "generation terminal and token candidate disagree")
            exposure = dict(teacher_forcing=data["prefix_ids"] != [1],
                target_access=data["prefix_origin"] == "target_derived_label" or data["context_origin"] == "target_derived_label",
                source_encoder_authenticated=False, context_permission_verified=False, prefix_origin_verified=False, encoder_sha256=None)
            return dict(schema=SCHEMA, profile=PROFILE, status=status, reason=reason,
                checkpoint_sha256=data["expected_checkpoint_sha256"], weights_sha256=checked["weights_sha256"], codec_sha256=codec_sha,
                conditioning=data["conditioning"], conditioning_sha256=_digest(data["conditioning"]),
                initial_prefix_ids=data["prefix_ids"], prefix_origin=data["prefix_origin"], context_origin=data["context_origin"],
                context_raw_sha256=data["expected_context_sha256"], context_sha256=decoded["context_sha256"],
                settings=settings, settings_sha256=_digest(settings), trace=trace, selected_token_ids=emitted,
                raw_argmax_ids_by_step=argmax, generated_ids=current, emitted_token_count=len(emitted), total_token_count=len(current),
                score_call_count=len(trace), numerical_forward_count=len(emitted), final_prefix_report=final_prefix, final_decoding=decoded,
                exposure=exposure, model_executed=bool(emitted), training_executed=False, compact_optimizer_executed=False,
                compact_training_steps=checked["progress"]["optimizer_steps"], training_progress=checked["progress"],
                initial_checkpoint_sha256=checked["initial_checkpoint_sha256"], initial_weights_sha256=checked["initial_weights_sha256"],
                parent_checkpoint_sha256=checked["parent_checkpoint_sha256"], runtime_verified=bool(emitted),
                optimizer_constructed=False, optimizer_state_restored=False, preparation=_preparation(box[0]),
                owner_pins=[row[0] for row in observed], authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0,
                limitations=list(_LIMITATIONS))
        except BaseException as error:
            failure = error
            raise
        finally:
            _close_session(box, failure, loaded)
    return _operation(original, work)


def compact_content_prepared_generation_sha256(report):
    """Closed report identity only, without importing numerical operation owners."""
    before = _source(_SELF_PATH, _SELF_SHA)
    checked = _copy(report, MAX_REPORT_BYTES)
    _need(type(checked) is dict and set(checked) == _REPORT_FIELDS and checked["schema"] == SCHEMA
          and checked["profile"] == PROFILE, "complete closed generation report required")
    result = _digest(checked)
    _need(_source(_SELF_PATH, _SELF_SHA) == before, "generation hash source changed")
    return result


def validate_compact_content_prepared_generation_v3(report, checkpoint, conditioning, prefix_ids, context_raw, *,
        expected_report_sha256, expected_checkpoint_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Require an independent report commitment and deterministic original replay."""
    _hash(expected_report_sha256, "complete generation report")
    offered = _copy(report, MAX_REPORT_BYTES)
    _need(compact_content_prepared_generation_sha256(offered) == expected_report_sha256, "independent generation report pin differs")
    original = _inputs(checkpoint, conditioning, prefix_ids, context_raw, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
    original.update(report=report, expected_report_sha256=expected_report_sha256)
    def work(data, loaded, fence):
        _need(compact_content_prepared_generation_sha256(data["report"]) == data["expected_report_sha256"], "captured report commitment differs")
        regenerated = generate_compact_content_prepared_v3(data["checkpoint"], data["conditioning"], data["prefix_ids"], data["context_raw"],
            expected_checkpoint_sha256=data["expected_checkpoint_sha256"], expected_context_sha256=data["expected_context_sha256"],
            max_new_tokens=data["max_new_tokens"], prefix_origin=data["prefix_origin"], context_origin=data["context_origin"])
        fence()
        _need(_wire(data["report"]) == _wire(regenerated), "generation differs from complete original-bound replay")
        return regenerated
    return _operation(original, work)


def prepare_compact_content_prepared_batch_prediction_v3(report, checkpoint, conditioning, prefix_ids, context_raw,
        population_raw, *, expected_generation_sha256, expected_population_sha256, occurrence_id,
        expected_checkpoint_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Link one verified continuation to one row of the unchanged CONTENT population."""
    _hash(expected_population_sha256, "original whole population")
    _need(type(population_raw) is bytes and 0 < len(population_raw) <= MAX_POPULATION_BYTES
          and hashlib.sha256(population_raw).hexdigest() == expected_population_sha256, "whole population commitment differs")
    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate population JSON key")
            result[key] = value
        return result
    population = json.loads(population_raw.decode(), object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(CompactContentGenerationError("finite population JSON required")))
    population = _copy(population, MAX_POPULATION_BYTES)
    _need(type(population) is dict and set(population) == {"schema", "partition", "selection_sha256", "rows"}
          and population["schema"] == "legal-relational-batch-population/v1" and type(population["rows"]) is list
          and 1 <= len(population["rows"]) <= 64, "existing complete population transport required")
    _need(type(population["partition"]) is str and 0 < len(population["partition"]) <= 128
          and bool(population["partition"].strip()), "bounded original population partition required")
    _hash(population["selection_sha256"], "original population selection")
    seen = set()
    for bound in population["rows"]:
        _need(type(bound) is dict and set(bound) == {"id", "source_sha256", "context_sha256"}
              and type(bound["id"]) is str and 0 < len(bound["id"]) <= 256 and bool(bound["id"].strip())
              and bound["id"] not in seen, "complete unique population row identities required")
        seen.add(bound["id"])
        _hash(bound["source_sha256"], "population source")
        _hash(bound["context_sha256"], "population context")
    matching = [row for row in population["rows"] if type(row) is dict and row.get("id") == occurrence_id]
    _need(len(matching) == 1 and type(occurrence_id) is str and 0 < len(occurrence_id) <= 256, "one declared population occurrence required")
    row = matching[0]
    _need(set(row) == {"id", "source_sha256", "context_sha256"}, "closed existing population row required")
    for key in ("source_sha256", "context_sha256"): _hash(row[key], key)
    original = _inputs(checkpoint, conditioning, prefix_ids, context_raw, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
    original.update(report=report, population=population, population_raw=population_raw,
        expected_generation_sha256=expected_generation_sha256, expected_population_sha256=expected_population_sha256,
        occurrence_id=occurrence_id)
    def work(data, loaded, fence):
        value = validate_compact_content_prepared_generation_v3(data["report"], data["checkpoint"], data["conditioning"], data["prefix_ids"], data["context_raw"],
            expected_report_sha256=data["expected_generation_sha256"], expected_checkpoint_sha256=data["expected_checkpoint_sha256"],
            expected_context_sha256=data["expected_context_sha256"], max_new_tokens=data["max_new_tokens"],
            prefix_origin=data["prefix_origin"], context_origin=data["context_origin"])
        fence()
        _need(loaded[2]["batch"].CONTENT_PREDICTIONS_SCHEMA == "legal-relational-content-token-batch-predictions/v1", "existing CONTENT schema differs")
        source_row = next(row for row in data["population"]["rows"] if type(row) is dict and row.get("id") == data["occurrence_id"])
        exposure = value["exposure"]
        observation = {**source_row, "status": "generated", "teacher_forcing": exposure["teacher_forcing"], "target_access": exposure["target_access"],
            "generated_ids": value["generated_ids"], "generated_ids_sha256": _digest(value["generated_ids"]), "reason": None,
            "content_context_utf8": data["context_raw"].decode(), "content_context_sha256": value["context_raw_sha256"],
            "content_context_origin": value["context_origin"]}
        predictions = {"schema": loaded[2]["batch"].CONTENT_PREDICTIONS_SCHEMA, "codec": data["checkpoint"]["codec"],
            "codec_sha256": value["codec_sha256"], "generation": {"kind": "decoder_declared",
                "population_sha256": data["expected_population_sha256"], "latent_dimension": 384,
                "checkpoint_sha256": value["checkpoint_sha256"], "encoder_sha256": None,
                "settings_sha256": value["settings_sha256"], "teacher_forcing": exposure["teacher_forcing"],
                "target_access": exposure["target_access"]}, "rows": [observation]}
        fence()
        return dict(schema=BATCH_SCHEMA, profile=BATCH_PROFILE, generation_sha256=data["expected_generation_sha256"],
            generation_report_sha256=data["expected_generation_sha256"], population_sha256=data["expected_population_sha256"],
            occurrence_id=data["occurrence_id"], prediction_row=observation, predictions=predictions,
            authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0,
            limitations=["This adapter links a replayed generation report but the existing batch evaluator does not authenticate that trace automatically.",
                "encoder_sha256 is null because no source encoder exists in this profile; decoder_declared therefore remains unverifiable_generation with no comparison credit.",
                "Source/model-context identities and the whole selected population remain caller declarations. One row leaves every other occurrence missing under the existing evaluator.",
                "generated_ids retains the supplied prefix plus selected IDs; exposure flags do not prove permission or target absence."])
    return _operation(original, work)


__all__ = ["inspect_compact_content_prepared_checkpoint_v3", "CompactContentGenerationError", "score_compact_content_prepared_v3", "generate_compact_content_prepared_v3", "compact_content_prepared_generation_sha256",
           "validate_compact_content_prepared_generation_v3", "prepare_compact_content_prepared_batch_prediction_v3"]
