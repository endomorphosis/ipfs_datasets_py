"""Lazy CPU inference for retained contextual LegalIR development decoders.

The metadata owner authenticates every asset and source before calling here.
Restoration recreates the historical raw GRU geometry, loads its original donor
state, applies the unchanged native constructors with saved receipts, then loads
every selected tensor. No training runner, encoder, optimizer or fitting helper
is used. Generated tokens remain unqualified candidates.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math
import struct
import time

SCHEMA = "contextual-legal-ir-numeric-inference/v1"
_FALSE = dict(qualified=False, admitted=False, proof_authority=False,
              source_semantics_verified=False, teacher_qualified=False,
              production_runtime_compatible=False, encoder_executed=False,
              optimizer_executed=False, training_executed=False,
              target_access=False, reference_documents_passed_to_generation=False)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


_DRIFT_MAX_ROWS = 4096
_DRIFT_MAX_COMBINED_SCALARS = 1048576


def _drift_float32_snapshot(value, dimension):
    _require(type(value) is list and len(value) == dimension,
             "drift vectors require exact list width")
    values = tuple(value)
    _require(len(values) == dimension and all(
        type(item) is float and math.isfinite(item) for item in values),
        "drift vectors require finite exact float scalars")
    try:
        packed = struct.pack(">" + str(dimension) + "f", *values)
    except (OverflowError, struct.error) as error:
        raise ValueError("drift vector exceeds binary32 range") from error
    restored = struct.unpack(">" + str(dimension) + "f", packed)
    _require(all(before == after for before, after in zip(values, restored)),
             "drift input must already be exactly representable as binary32")
    bits = struct.unpack(">" + str(dimension) + "I", packed)
    return values, packed, bits


def _drift_ulp_rank(bits):
    magnitude = bits & 0x7fffffff
    return -magnitude if bits & 0x80000000 else magnitude


def compare_source_vector_drift_v1(rows, *, dimension=384):
    """Measure paired raw binary32 vectors without applying model preprocessing.

    Caller-owned source/artifact authentication precedes this pure calculation.
    Each row has exactly id/original/successor. Inputs are copied, never repaired,
    normalized in place, fitted, projected or fed to a model. Every scalar must
    already equal its binary32 roundtrip; signed-zero bits remain distinct.

    Relative L2 uses the original norm. Undefined relative/cosine quantities
    return None and an explicit reason. ULP distance uses a monotone finite-f32
    numerical rank with signed zeros coalesced. Bit differences retain their
    signed-zero distinction. Float64 fsum/hypot perform the diagnostic arithmetic.
    Cosine similarity uses the compensated raw dot product; cosine distance uses
    half the squared distance between diagnostic unit vectors to retain tiny
    near-parallel differences. These independently rounded results need not be
    bitwise complements. Explicit range clipping corrects diagnostic roundoff,
    never the input vectors, and establishes no empirical parity tolerance.

    This API does not authenticate provenance, restore a decoder, qualify a head,
    inspect targets, run training, or prove convergence or legal meaning.
    """
    _require(type(dimension) is int and 1 <= dimension <= 4096,
             "drift dimension must be an exact integer in 1..4096")
    _require(type(rows) is list and 1 <= len(rows) <= _DRIFT_MAX_ROWS,
             "drift requires one to 4096 paired rows")
    _require(2 * len(rows) * dimension <= _DRIFT_MAX_COMBINED_SCALARS,
             "drift combined original/successor scalar bound exceeded")
    seen, measured = set(), []
    bit_differences = numerical_differences = exact_rows = 0
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "original", "successor"},
                 "closed id/original/successor drift row required")
        identity = row["id"]
        _require(type(identity) is str and 0 < len(identity) <= 512
                 and identity.strip() and "\x00" not in identity,
                 "bounded nonblank drift identity required")
        try:
            identity_bytes = identity.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("drift identity must be valid UTF8") from error
        _require(len(identity_bytes) <= 512 and identity not in seen,
                 "drift identities must be unique and at most 512 UTF8 bytes")
        original, original_raw, original_bits = _drift_float32_snapshot(row["original"], dimension)
        successor, successor_raw, successor_bits = _drift_float32_snapshot(row["successor"], dimension)
        deltas = tuple(after - before for before, after in zip(original, successor))
        original_norm, successor_norm = math.hypot(*original), math.hypot(*successor)
        l2 = math.hypot(*deltas)
        relative = l2 / original_norm if original_norm else None
        dot = math.fsum(before * after for before, after in zip(original, successor))
        cosine = cosine_distance = None
        clipped = distance_clipped = False
        if original_norm and successor_norm:
            raw_cosine = dot / (original_norm * successor_norm)
            cosine = max(-1.0, min(1.0, raw_cosine))
            clipped = cosine != raw_cosine
            raw_distance = 0.5 * math.fsum(
                (before / original_norm - after / successor_norm) ** 2
                for before, after in zip(original, successor))
            cosine_distance = max(0.0, min(2.0, raw_distance))
            distance_clipped = cosine_distance != raw_distance
            undefined_cosine = None
        else:
            undefined_cosine = ("both_zero_norms" if not original_norm and not successor_norm
                                else "original_zero_norm" if not original_norm else "successor_zero_norm")
        ulps = tuple(abs(_drift_ulp_rank(before) - _drift_ulp_rank(after))
                     for before, after in zip(original_bits, successor_bits))
        differing_bits = sum(before != after for before, after in zip(original_bits, successor_bits))
        differing_values = sum(before != after for before, after in zip(original, successor))
        equal = original_raw == successor_raw
        measured.append(dict(id=identity,
            original_f32_be_sha256=hashlib.sha256(original_raw).hexdigest(),
            successor_f32_be_sha256=hashlib.sha256(successor_raw).hexdigest(),
            bitwise_equal=equal, bitwise_differing_coordinates=differing_bits,
            numerically_differing_coordinates=differing_values,
            max_absolute_error=max(abs(value) for value in deltas),
            l1_distance=math.fsum(abs(value) for value in deltas), l2_distance=l2,
            original_l2_norm=original_norm, successor_l2_norm=successor_norm,
            relative_l2_distance=relative,
            relative_l2_undefined_reason=None if original_norm else "original_zero_norm",
            dot_product=dot, cosine_similarity=cosine, cosine_distance=cosine_distance,
            cosine_undefined_reason=undefined_cosine, cosine_roundoff_clipped=clipped,
            cosine_distance_roundoff_clipped=distance_clipped,
            max_ulp_distance=max(ulps), mean_ulp_distance=math.fsum(ulps) / dimension))
        seen.add(identity)
        bit_differences += differing_bits
        numerical_differences += differing_values
        exact_rows += equal
    return dict(schema="legal-ir-raw-source-vector-drift/v1", dimension=dimension, rows=measured,
        counts=dict(row_count=len(measured), scalar_pairs=len(measured) * dimension,
                    exact_bitwise_rows=exact_rows, bitwise_differing_coordinates=bit_differences,
                    numerically_differing_coordinates=numerical_differences),
        input_dtype="binary32_exact", arithmetic_dtype="python_binary64_fsum_hypot",
        ulp_policy="signed-magnitude numerical rank with signed zeros coalesced",
        cosine_distance_policy="half squared distance of diagnostic unit vectors; independently rounded from similarity",
        acceptance_tolerance=None, preprocessing_applied=False, model_restored=False,
        conditioning_or_head_compatibility_qualified=False, convergence_proven=False,
        **_FALSE)


def _owners():
    # These are the eleven original numerical owners authenticated by the facade.
    from . import decoder_distillation_experiment as core
    from . import decoder_distillation_experiment_v2 as persistent
    from . import dimension_native_decoder_experiment as native
    from . import projected_source_decoder_experiment as projected
    from . import clause_source_decoder_experiment as clauses
    from . import action_factorized_clause_decoder_experiment as action
    from . import ordered_clause_recurrent_decoder_experiment as ordered
    from . import clause_source_context as contexts
    return core, persistent, native, projected, clauses, action, ordered, contexts


def _typed_tensor(torch, value, template, name):
    """Preflight exact nested shape and scalar type before any model mutation."""
    integer = template.dtype == torch.int64

    def check(part, shape):
        if shape:
            _require(type(part) is list and len(part) == shape[0],
                     "restored tensor shape differs: " + name)
            for item in part:
                check(item, shape[1:])
        else:
            valid = type(part) is int if integer else type(part) in (int, float)
            _require(valid and math.isfinite(part), "invalid restored scalar: " + name)
            if integer:
                _require(-(2**63) <= part < 2**63, "int64 scalar overflow: " + name)

    check(value, tuple(template.shape))
    result = torch.tensor(value, dtype=template.dtype, device="cpu")
    _require(not result.is_floating_point() or bool(torch.isfinite(result).all()),
             "restored float32 overflow: " + name)
    return result


def _restore_tensors(torch, serialized, model):
    templates = model.state_dict()
    _require(type(serialized) is dict and set(serialized) == set(templates),
             "complete restored tensor inventory differs")
    return {name: _typed_tensor(torch, serialized[name], template, name)
            for name, template in templates.items()}


def _raw_donor(torch, donor):
    """Recreate the original 13-tensor raw protocol, without its training owner.

    This geometry is the retained modal_latent_formula JointDecoder constructor.
    Its complete donor state replaces all temporary values before native binding.
    The caller's CPU RNG is preserved by restoration's enclosing fork_rng.
    """
    _require(type(donor) is dict and set(donor) == {"codec", "config", "model_state"},
             "closed donor construction packet required")
    config, codec = donor["config"], donor["codec"]
    _require(type(config) is dict and type(codec) is dict,
             "saved raw donor geometry and codec required")
    for key, low, high in (("hidden_size", 8, 128), ("token_embedding_dim", 8, 64),
                           ("projection_width", 1, 64), ("seed", 0, 2**31 - 1)):
        _require(type(config.get(key)) is int and low <= config[key] <= high,
                 "invalid saved donor " + key)
    vocabulary = codec.get("target_vocabulary")
    _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096,
             "bounded saved donor vocabulary required")

    class RawDonor(torch.nn.Module):
        def __init__(self):
            super().__init__()
            width, hidden = config["projection_width"], config["hidden_size"]
            self.projection_down = torch.nn.Linear(384, width, dtype=torch.float32, device="cpu")
            self.projection_up = torch.nn.Linear(width, 384, dtype=torch.float32, device="cpu")
            self.condition = torch.nn.Linear(384, hidden, dtype=torch.float32, device="cpu")
            self.target_embedding = torch.nn.Embedding(len(vocabulary),
                config["token_embedding_dim"], padding_idx=0, dtype=torch.float32, device="cpu")
            self.decoder = torch.nn.GRU(config["token_embedding_dim"], hidden,
                                        batch_first=True, dtype=torch.float32, device="cpu")
            self.output = torch.nn.Linear(hidden, len(vocabulary), dtype=torch.float32, device="cpu")

        def project(self, values):
            return values + self.projection_up(torch.tanh(self.projection_down(values)))

        def start(self, projected):
            return torch.tanh(self.condition(projected)).unsqueeze(0)

        def next_logits(self, tokens, hidden):
            values, updated = self.decoder(self.target_embedding(tokens), hidden)
            return self.output(values), updated

        def forward(self, values, prefix):
            projected = self.project(values)
            return projected, self.next_logits(prefix, self.start(projected))[0]

    # Preserve the constructor's original draw sequence as well as final bytes.
    torch.random.default_generator.manual_seed(config["seed"])
    model = RawDonor()
    model.load_state_dict(_restore_tensors(torch, donor["model_state"], model),
                          strict=True, assign=False)
    return model


@dataclass(frozen=True)
class _RestoredContextualModel:
    model: object
    dimension: int
    codec: dict
    input_transform: dict
    tensor_sha256: str


def restore_contextual_legal_model(prepared):
    """Restore a detached, authenticated saved model; import torch lazily.

    ``prepared`` contains exactly checkpoint, preprocessing and donor_checkpoint.
    Callers configure one CPU thread explicitly, as required by the original
    numerical owners. File authentication belongs to the metadata facade.
    """
    _require(type(prepared) is dict and set(prepared) == {
        "checkpoint", "preprocessing", "donor_checkpoint"},
        "closed authenticated restoration packet required")
    checkpoint, preprocessing, donor = deepcopy((prepared["checkpoint"],
        prepared["preprocessing"], prepared["donor_checkpoint"]))
    _require(type(checkpoint) is dict and type(preprocessing) is dict,
             "saved checkpoint and preprocessing required")
    dimension = checkpoint.get("dimension")
    _require(type(dimension) is int and dimension in (384, 768),
             "contextual retained 384D or 768D model required")
    _require(checkpoint.get("schema") == "private-native-dimension-source-state/v1"
             and checkpoint.get("selected") is True and checkpoint.get("role") == "selected",
             "selected contextual state required")
    _require(all(checkpoint.get(key) is False for key in (
        "qualified", "admitted", "proof_authority", "source_semantics_verified")),
        "saved state cannot grant authority")
    _require(checkpoint.get("input_transform") == preprocessing.get("input_transform"),
             "saved input transform differs")
    core, persistent, native, projected, clauses, action, ordered, _ = _owners()
    _require(core.digest(checkpoint.get("model_state")) == checkpoint.get("weights_sha256"),
             "saved selected weight digest differs")
    _require(donor["codec"] == checkpoint.get("codec"), "donor and selected codec differ")
    torch = core._torch()
    rng_before = torch.get_rng_state().clone()
    with torch.random.fork_rng(devices=[]), torch.no_grad(), torch.device("cpu"):
        raw = _raw_donor(torch, donor)
        initializer = checkpoint.get("initializer_receipt")
        _require(type(initializer) is dict
                 and core.tensor_digest(raw) == initializer.get("donor_tensor_sha256"),
                 "loaded original donor tensor digest differs")
        body, receipt = native.bind_dimension_native_body(raw, dimension=dimension,
                            source_seed=initializer.get("source_seed"))
        _require(receipt == initializer and receipt == preprocessing.get("initializer"),
                 "saved native initialization receipt differs")
        model = persistent.bind_persistent_model(body, dimension=dimension,
                                                 conditioning="every_step")
        model = projected.bind_projected_source_model(model, codec=checkpoint["codec"],
            normalization_receipt=preprocessing["paragraph_normalization"],
            count_prior_receipt=preprocessing["count_prior"],
            guide_boundary=True, scalar_guidance=True)
        model = clauses.bind_clause_source_model(model, head_seed=1729,
            clause_normalization_receipt=preprocessing["clause_normalization"])
        model = action.bind_action_factorized_clause_model(model, codec=checkpoint["codec"])
        model = ordered.bind_ordered_clause_recurrent_model(model, codec=checkpoint["codec"])
        _require(model.describe() == checkpoint.get("architecture"),
                 "original selected architecture differs")
        state = _restore_tensors(torch, checkpoint["model_state"], model)
        # Parent nn.Module.load_state_dict does not call nested custom loaders.
        # Authenticate the raw native body explicitly before the outer restore.
        prefix = "body.body.body."
        raw_state = {name[len(prefix):]: value for name, value in state.items()
                     if name.startswith(prefix)}
        model.body.body.body.validate_restored_state(raw_state)
        native.checked_specification(model.body.body.body, initializer)
        model.load_state_dict(state, strict=True, assign=False)
        model.body.body.body.check_frozen_projection()
        _require(core.tensor_digest(model) == checkpoint.get("tensor_sha256"),
                 "loaded selected native tensor digest differs")
        ordered.checked_specification(model, checkpoint["codec"])
        model.eval()
    _require(torch.equal(rng_before, torch.get_rng_state()),
             "restoration changed ambient CPU RNG")
    return _RestoredContextualModel(model, dimension, deepcopy(checkpoint["codec"]),
        deepcopy(checkpoint["input_transform"]), checkpoint["tensor_sha256"])


def infer_contextual_legal_model(restored, source_inputs, *, output_cap=512,
                                 deadline_seconds=120., batch_size=8):
    """Greedy raw generation from paragraph vectors and ordered clause vectors.

    No gold prefix, rule count, parser, label, target or reference is accepted.
    Padding follows the original input transform; independent saved paragraph
    and clause feature normalization remains inside the restored model.
    A deadline reports unfinished rows explicitly and never repairs output.
    """
    _require(type(restored) is _RestoredContextualModel, "restored contextual handle required")
    _require(type(source_inputs) is dict and set(source_inputs) == {"rows", "contexts"},
             "closed source-only inference packet required")
    _require(type(output_cap) is int and 4 <= output_cap <= 512, "output cap must be 4..512")
    _require(type(batch_size) is int and 1 <= batch_size <= 32, "bounded batch size required")
    _require(type(deadline_seconds) in (int, float) and math.isfinite(deadline_seconds)
             and 0 < deadline_seconds <= 120., "deadline must be positive and at most120seconds")
    rows, contexts = deepcopy((source_inputs["rows"], source_inputs["contexts"]))
    _require(type(rows) is list and 1 <= len(rows) <= 128,
             "bounded nonempty source rows required")
    core, _, _, _, _, _, _, contexts_owner = _owners()
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "input"},
                 "closed source-only row required")
        core._vector(row["input"], restored.dimension)
        _require(abs(sum(float(v)**2 for v in row["input"])-1.) <= 1e-4,
                 "original normalized paragraph vector required")
    context_receipt = contexts_owner.validate_contexts(rows, contexts)
    _require(context_receipt["dimension"] == restored.dimension,
             "paragraph and clause dimensions differ")
    return _infer_contextual_generation(restored,source_inputs,rows,contexts,context_receipt,
        core,contexts_owner,output_cap=output_cap,deadline_seconds=deadline_seconds,batch_size=batch_size)


def _infer_contextual_generation(restored, source_inputs, rows, contexts, context_receipt,
                                  core, contexts_owner, *, output_cap, deadline_seconds,
                                  batch_size, occurrence_guard=None):
    """Shared unchanged numerical generation; optional new-consumer custody guards."""
    torch = core._torch()
    model = restored.model
    core._model(model, torch)
    _require(all(not item.training for item in model.modules()), "frozen evaluation mode required")
    _require(all(parameter.grad is None for parameter in model.parameters()),
             "inference model must have no accumulated gradients")
    before = core.tensor_digest(model)
    _require(before == restored.tensor_sha256, "restored model changed before inference")
    rng_before = torch.get_rng_state().clone()
    inputs_sha = core.digest(source_inputs)
    deadline = time.monotonic() + float(deadline_seconds)
    predictions = []
    with torch.inference_mode(), torch.device("cpu"):
        for offset in range(0, len(rows), batch_size):
            part = rows[offset:offset+batch_size]
            if time.monotonic() >= deadline:
                generated = None
            else:
                transform = restored.input_transform
                data = (torch.tensor([row["input"] for row in part], dtype=torch.float32)
                    - torch.tensor(transform["mean"], dtype=torch.float32)) / transform["scale"]
                if occurrence_guard is not None:
                    occurrence_guard("before_batch_context",part=part,data=data)
                packet = None
                try:
                    packet = contexts_owner.batch_source_context(torch, part, contexts, transform)
                finally:
                    if occurrence_guard is not None:
                        occurrence_guard("after_batch_context",part=part,data=data,packet=packet)
                if occurrence_guard is not None:
                    occurrence_guard("before_greedy",part=part,data=data,packet=packet)
                generated, greedy_returned = None, False
                try:
                    generated = core._greedy(torch, model, data, output_cap,
                        len(restored.codec["target_vocabulary"]), deadline, source_context=packet)
                    greedy_returned = True
                finally:
                    if occurrence_guard is not None:
                        occurrence_guard("after_greedy",part=part,data=data,packet=packet,
                            generated=generated,greedy_returned=greedy_returned)
            if generated is None:
                predictions.extend(dict(id=row["id"], token_ids=[], eos_reached=False,
                                         generation_status="deadline") for row in part)
            else:
                _, tokens, statuses = generated
                _require(len(tokens) == len(statuses) == len(part),
                         "generated row cardinality differs")
                predictions.extend(dict(id=row["id"], token_ids=sequence,
                    eos_reached=status == "eos", generation_status=status)
                    for row, sequence, status in zip(part, tokens, statuses))
    after = core.tensor_digest(model)
    rng_preserved = torch.equal(rng_before, torch.get_rng_state())
    _require(after == before and rng_preserved, "inference changed model state or CPU RNG")
    _require(core.digest(source_inputs) == inputs_sha, "inference input packet changed")
    return dict(schema=SCHEMA, dimension=restored.dimension,
        codec_sha256=core.digest(restored.codec), output_cap=output_cap,
        predictions=predictions, row_count=len(rows),
        model_tensor_sha256=after, model_tensor_sha256_before=before,
        model_tensor_sha256_after=after, weights_unchanged=True,
        ambient_rng_preserved=bool(rng_preserved), source_inputs_unchanged=True,
        source_inputs_sha256=inputs_sha, source_contexts_sha256=context_receipt["contexts_sha256"],
        completed=all(row["generation_status"] != "deadline" for row in predictions),
        **_FALSE)


def _sensitivity_source_precheck(value, dimension):
    _require(type(value) is dict and set(value) == {"rows", "contexts"},
             "closed source-only sensitivity packet required")
    rows, contexts = value["rows"], value["contexts"]
    _require(type(rows) is list and 1 <= len(rows) <= 128 and type(contexts) is dict,
             "one to 128 source rows and exact contexts required")
    ids = []
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "input"},
                 "sensitivity source row must exclude targets")
        identifier, text = row["id"], row["source_text"]
        _require(type(identifier) is str and identifier.strip() and "\0" not in identifier
                 and len(identifier.encode("utf-8")) <= 512, "bounded exact source identity required")
        _require(type(text) is str and text.strip() and len(text.encode("utf-8")) <= 131072,
                 "bounded literal source text required")
        _drift_float32_snapshot(row["input"], dimension)
        _require(abs(math.fsum(v*v for v in row["input"]) - 1.) <= 1e-4,
                 "original normalized paragraph vector required")
        descriptor = contexts.get(identifier)
        _require(type(descriptor) is dict and set(descriptor) == {"source_sha256", "segments"}
                 and type(descriptor["source_sha256"]) is str and type(descriptor["segments"]) is list
                 and 1 <= len(descriptor["segments"]) <= 8,
                 "closed literal clause context required")
        for segment in descriptor["segments"]:
            _require(type(segment) is dict and set(segment) == {"source_text", "source_sha256", "embedding_sha256",
                "vector", "char_start", "char_end", "byte_start", "byte_end"}, "closed source clause required")
            _require(all(type(segment[k]) is str for k in ("source_text", "source_sha256", "embedding_sha256"))
                and all(type(segment[k]) is int for k in ("char_start", "char_end", "byte_start", "byte_end")),
                "plain source clause metadata required")
            _drift_float32_snapshot(segment["vector"], dimension)
        ids.append(identifier)
    _require(len(set(ids)) == len(ids) and set(contexts) == set(ids), "exact unique source/context membership required")
    return None


def _sensitivity_tensor_sha256(tensor):
    values = tensor.detach().reshape(-1).tolist()
    return hashlib.sha256(struct.pack(">" + str(len(values)) + "f", *values)).hexdigest()


def _sensitivity_centered_logit_delta(original, successor):
    """Stable diagnostic preference delta, separately from float32 re-centering."""
    _require(type(original) is list and type(successor) is list and len(original) == len(successor)
        and 4 <= len(original) <= 1024, "bounded paired logit snapshots required")
    _drift_float32_snapshot(original,len(original));_drift_float32_snapshot(successor,len(successor))
    delta = [float(new)-float(old) for old,new in zip(original,successor)]
    mean = math.fsum(delta)/len(delta)
    centered = [value-mean for value in delta]
    norm = math.hypot(*centered)
    return dict(mean_delta=mean,centered_max_absolute=max(abs(value) for value in centered),
        centered_l2=norm,centered_rms=norm/math.sqrt(len(delta)),
        arithmetic_dtype="binary64 delta then fsum mean; no float32 re-centering",
        acceptance_tolerance=None)


def _sensitivity_occurrence_contexts(rows, contexts, dimension, core, contexts_owner):
    """Validate physical clauses individually, without a training-cache join.

    Repeated text can have distinct authenticated vector records by occurrence.
    The legacy global cached-text validator and all training contracts remain
    unchanged. Normalized paragraph uniqueness is still required here.
    """
    normalized = [" ".join(row["source_text"].casefold().split()) for row in rows]
    _require(len(set(normalized)) == len(rows), "duplicate normalized paragraph source")
    returned_dimensions, source_inventory, occurrences = [], [], []
    for row_index,row in enumerate(rows):
        descriptor = contexts[row["id"]]
        before = core.digest(dict(row=row,descriptor=descriptor))
        returned = contexts_owner.validate_context(row,descriptor)
        _require(type(returned) is int and returned == dimension,
                 "actual per-row context validator dimension differs")
        _require(core.digest(dict(row=row,descriptor=descriptor)) == before,
                 "per-row context validation mutated captured input")
        returned_dimensions.append(returned)
        source_inventory.append(dict(id=row["id"],row_index=row_index,source_sha256=descriptor["source_sha256"]))
        for slot,segment in enumerate(descriptor["segments"]):
            occurrences.append(dict(id=row["id"],row_index=row_index,slot=slot,
                **{key:segment[key] for key in ("source_sha256","embedding_sha256",
                    "char_start","char_end","byte_start","byte_end")}))
    receipt = dict(schema="contextual-source-occurrence-validation/v1",dimension=dimension,
        contexts_sha256=core.digest(contexts),source_inventory=source_inventory,
        clause_occurrence_inventory=occurrences,per_row_validator_returns=returned_dimensions,
        source_segmentation="literal_blank_line_exact_physical_occurrences",
        global_text_to_single_cached_vector_asserted=False,reference_labels_accessed=False,admitted=False,qualified=False)
    return receipt,returned_dimensions


def compare_contextual_source_sensitivity_v1(restored, original_inputs, successor_inputs, *, batch_size=8):
    """Compare saved preprocessing and one fixed-BOS point of a frozen head.

    File/source authentication and the old/successor physical-role join belong to
    the caller. This diagnostic accepts only matching source-only packets, no
    target, caller prefix or generation policy. Existing model methods execute
    the recorded float32 transforms; existing raw drift owns all vector metrics.
    Clause padding is audited separately and never counted as a physical role.
    BOS advances the grammar to real clause0: its logits include the paragraph
    and first-clause paths, not later clauses, full sequence generation, a
    semantic target or source/head compatibility.
    """
    _require(type(restored) is _RestoredContextualModel, "restored contextual handle required")
    _require(type(batch_size) is int and 1 <= batch_size <= 16,
             "sensitivity batch must be 1..16 so all eight slots fit the native 128-row projection")
    _require(type(restored.dimension) is int and restored.dimension in (384, 768), "retained source width required")
    _sensitivity_source_precheck(original_inputs,restored.dimension)
    _sensitivity_source_precheck(successor_inputs,restored.dimension)
    core, _, _, _, _, _, _, contexts_owner = _owners()
    input_hashes = (core.digest(original_inputs),core.digest(successor_inputs))
    packets = (deepcopy(original_inputs),deepcopy(successor_inputs))
    original_receipt, original_row_returns = _sensitivity_occurrence_contexts(
        original_inputs["rows"],original_inputs["contexts"],restored.dimension,core,contexts_owner)
    original_receipt_hash = core.digest(original_receipt)
    original_return_snapshot = tuple(original_row_returns)
    _require((core.digest(original_inputs),core.digest(successor_inputs)) == input_hashes,
             "source validation mutated captured input")
    successor_receipt, successor_row_returns = _sensitivity_occurrence_contexts(
        successor_inputs["rows"],successor_inputs["contexts"],restored.dimension,core,contexts_owner)
    successor_receipt_hash = core.digest(successor_receipt)
    successor_return_snapshot = tuple(successor_row_returns)
    _require(original_receipt["dimension"] == successor_receipt["dimension"] == restored.dimension,
             "sensitivity context dimension differs")
    _require((core.digest(original_inputs),core.digest(successor_inputs)) == input_hashes
        and core.digest(original_receipt) == original_receipt_hash,"source validation mutated captured input or return")
    old_rows, new_rows = original_inputs["rows"], successor_inputs["rows"]
    _require(len(old_rows) == len(new_rows), "paired sensitivity cardinality differs")
    for old, new in zip(old_rows, new_rows):
        _require(old["id"] == new["id"] and old["source_text"] == new["source_text"],
                 "paired source identity/text/order differs")
        a, b = original_inputs["contexts"][old["id"]], successor_inputs["contexts"][new["id"]]
        _require(a["source_sha256"] == b["source_sha256"] and len(a["segments"]) == len(b["segments"]),
                 "paired literal context differs")
        for left, right in zip(a["segments"], b["segments"]):
            _require({k:v for k,v in left.items() if k not in ("vector", "embedding_sha256")} ==
                     {k:v for k,v in right.items() if k not in ("vector", "embedding_sha256")},
                     "paired literal clause metadata differs")
    metadata_hash = core.digest(dict(codec=restored.codec, input_transform=restored.input_transform))
    transform = restored.input_transform
    _require(type(transform) is dict and set(transform) == {"mode", "origin", "mean", "scale"}
        and transform["mode"] == "center_rms" and transform["origin"] == "training_only",
        "saved TRAIN input transform required")
    _require(type(transform["mean"]) is list and len(transform["mean"]) == restored.dimension
        and all(type(x) in (int, float) and math.isfinite(x) for x in transform["mean"])
        and type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"])
        and transform["scale"] > 0, "finite saved transform required")
    vocabulary = restored.codec.get("target_vocabulary")
    _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 1024 and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"],
             "saved bounded BOS vocabulary required")
    torch = core._torch(); model = restored.model
    caller_default_dtype = torch.get_default_dtype()
    _require(torch.get_float32_matmul_precision() == "highest" and not torch.is_autocast_enabled("cpu"),
             "highest float32 matmul precision and CPU autocast disabled required")
    _require(torch.get_num_threads() == 1, "caller must configure one CPU thread")
    core._model(model, torch)
    tensor_before = core.tensor_digest(model)
    _require(tensor_before == restored.tensor_sha256, "restored model changed before sensitivity")
    rng_before = torch.get_rng_state().clone()
    def guard():
        _require(all(not module.training for module in model.modules()) and
            all(parameter.grad is None for parameter in model.parameters()), "frozen eval/no-gradient model required")
        _require(core.tensor_digest(model) == tensor_before, "sensitivity changed model tensors")
        _require(torch.equal(torch.get_rng_state(), rng_before), "sensitivity changed ambient CPU RNG")
        _require((core.digest(original_inputs), core.digest(successor_inputs)) == input_hashes
            and tuple(core.digest(value) for value in packets) == input_hashes, "sensitivity source packet mutated")
        _require(core.digest(dict(codec=restored.codec,input_transform=restored.input_transform)) == metadata_hash,
                 "sensitivity restored metadata changed")
        _require(torch.get_num_threads() == 1, "sensitivity changed CPU thread setting")
        _require(torch.get_default_dtype() == caller_default_dtype
            and torch.get_float32_matmul_precision() == "highest" and not torch.is_autocast_enabled("cpu"),
            "sensitivity changed caller dtype, precision or CPU autocast policy")
        _require((core.digest(original_receipt),core.digest(successor_receipt)) ==
                 (original_receipt_hash,successor_receipt_hash), "actual context validator return mutated")
        _require((tuple(original_row_returns),tuple(successor_row_returns)) ==
                 (original_return_snapshot,successor_return_snapshot), "actual per-row context validator returns mutated")
    guard()
    stages = {}; identities = {"paragraph": [], "clause": []}; padding = [[], []]; bos = [[], []]
    def key(identifier, slot=None):
        return "sensitivity:" + hashlib.sha256(identifier.encode("utf-8")).hexdigest() + (":paragraph" if slot is None else ":clause:"+str(slot))
    for row in old_rows:
        identities["paragraph"].append(dict(id=key(row["id"]), source_row_id=row["id"], role="paragraph", slot=None))
        for slot in range(len(original_inputs["contexts"][row["id"]]["segments"])):
            identities["clause"].append(dict(id=key(row["id"],slot), source_row_id=row["id"], role="clause", slot=slot))
    def capture(stage, arm, tensor, ids):
        _require(tensor.device.type == "cpu" and tensor.dtype == torch.float32 and tensor.ndim == 2
            and tensor.shape[0] == len(ids) and bool(torch.isfinite(tensor).all()), "finite CPU float32 stage required: "+stage)
        group = stages.setdefault(stage, [[], []])
        group[arm].extend((identifier, values) for identifier,values in zip(ids,tensor.detach().tolist()))
    def point_logits(tensor, rows):
        result = []
        for row, values in zip(rows,tensor.detach().tolist()):
            ranked = sorted(range(len(values)),key=lambda i:(-values[i],i))
            top, second = ranked[:2]
            result.append(dict(id=row["id"],top1_token_id=top,top2_token_id=second,
                top1_value=values[top],top2_value=values[second],top1_top2_margin=float(values[top])-float(values[second]),
                tie_at_top=values[top] == values[second]))
        return result
    batches = 0
    try:
        with torch.inference_mode(), torch.device("cpu"):
            for offset in range(0,len(old_rows),batch_size):
                batches += 1
                for arm, packet in enumerate(packets):
                    rows = packet["rows"][offset:offset+batch_size]; contexts = packet["contexts"]
                    pids = [key(row["id"]) for row in rows]
                    cids = [key(row["id"],slot) for row in rows for slot in range(len(contexts[row["id"]]["segments"]))]
                    values = (torch.tensor([row["input"] for row in rows],dtype=torch.float32)
                        - torch.tensor(transform["mean"],dtype=torch.float32)) / transform["scale"]
                    context = contexts_owner.batch_source_context(torch,rows,contexts,transform)
                    vectors, mask = context["vectors"], context["mask"]
                    _require(mask.dtype == torch.bool and mask.device.type == "cpu" and tuple(mask.shape) == (len(rows),8)
                        and not bool(vectors[~mask].any()), "source-derived eight-slot zero padding required")
                    capture("saved_input_transform.paragraph",arm,values,pids)
                    capture("saved_input_transform.real_clause",arm,vectors[mask],cids)
                    projected = model.project(values)
                    features = model.body._features(projected)
                    clause_features, actual_mask = model.clause_features(projected,source_context=context)
                    _require(torch.equal(actual_mask,mask), "model changed source mask")
                    capture("model_projection.paragraph",arm,projected,pids)
                    capture("paragraph_feature_normalization",arm,features,pids)
                    _require(tuple(clause_features.shape) == (len(rows),8,restored.dimension) and clause_features.dtype == torch.float32
                        and clause_features.device.type == "cpu" and bool(torch.isfinite(clause_features).all()), "finite complete clause features required")
                    capture("clause_feature_normalization.real_clause",arm,clause_features[mask],cids)
                    state = model.start(projected,source_context=context)
                    _require(type(state) is tuple and len(state) == 7, "complete seven-field ordered state required")
                    hidden, source, position, counts, grammar, scalar, recurrent = state
                    _require(position.dtype == grammar.dtype == torch.long and position.device.type == grammar.device.type == "cpu"
                        and tuple(position.shape) == (len(rows),) and tuple(grammar.shape) == (len(rows),6)
                        and not bool(position.any()) and not bool(grammar.any()), "initial Long position/grammar state differs")
                    _require(torch.equal(source,projected) and hidden.ndim == 3 and hidden.shape[0] == 1
                        and hidden.shape[1] == len(rows) and tuple(counts.shape) == (len(rows),32)
                        and tuple(scalar.shape) == (len(rows),8,4,len(vocabulary))
                        and tuple(recurrent.shape) == (len(rows),8,128), "ordered state geometry differs")
                    _require(not bool(scalar[~mask].any()) and not bool(recurrent[~mask].any()), "masked head states must be zero")
                    capture("initial_state.hidden",arm,hidden.squeeze(0),pids)
                    capture("initial_state.count_logits",arm,counts,pids)
                    capture("initial_state.scalar_logits.real_clause",arm,scalar[mask].reshape(len(cids),-1),cids)
                    capture("initial_state.recurrent_clause_features.real_clause",arm,recurrent[mask],cids)
                    position_before, grammar_before, mask_before = position.clone(), grammar.clone(), mask.clone()
                    floating_before = [value.detach().clone() for value in (hidden,source,counts,scalar,recurrent)]
                    prefix = torch.full((len(rows),1),1,dtype=torch.long)
                    logits, updated = model.next_logits(prefix,state)
                    _require(type(updated) is tuple and len(updated) == 7 and tuple(logits.shape) == (len(rows),1,len(vocabulary)),
                             "one fixed-BOS output point required")
                    _require(torch.equal(position,position_before) and torch.equal(grammar,grammar_before) and torch.equal(mask,mask_before),
                             "fixed-BOS call mutated initial structural state")
                    _require(updated[2].dtype == updated[4].dtype == torch.long
                        and updated[2].device.type == updated[4].device.type == "cpu"
                        and tuple(updated[2].shape) == (len(rows),) and tuple(updated[4].shape) == (len(rows),6)
                        and bool((updated[2] == 1).all()), "updated fixed-BOS Long structural state differs")
                    _require(all(torch.equal(value,before) for value,before in zip((hidden,source,counts,scalar,recurrent),floating_before)),
                             "fixed-BOS call mutated initial floating state")
                    _require(all(value.dtype == torch.float32 and value.device.type == "cpu" and bool(torch.isfinite(value).all())
                        for value in (updated[0],updated[1],updated[3],updated[5],updated[6])), "finite updated ordered floating state required")
                    raw = logits[:,0,:]; centered = raw-raw.mean(dim=-1,keepdim=True,dtype=torch.float32)
                    capture("BOS.raw_logits",arm,raw,pids);capture("BOS.mean_centered_logits",arm,centered,pids)
                    bos[arm].extend(point_logits(raw,rows))
                    for index,row in enumerate(rows):
                        inactive = [slot for slot,value in enumerate(mask[index].tolist()) if not value]
                        padding[arm].append(dict(id=row["id"],mask=mask[index].tolist(),position=position[index].item(),
                            grammar=grammar[index].tolist(),updated_position=updated[2][index].item(),
                            updated_grammar=updated[4][index].tolist(),inactive_slots=inactive,padded_input_vectors_zero=True,
                            normalized_padding=[dict(slot=slot,f32_be_sha256=_sensitivity_tensor_sha256(clause_features[index,slot]),
                                any_nonzero=bool(clause_features[index,slot].any())) for slot in inactive],
                            scalar_and_recurrent_padding_zero=True))
                    guard()
        _require(padding[0] == padding[1], "paired structural state or normalized padding differs")
        comparisons = {}; kernel_calls = 0
        for stage,(left,right) in stages.items():
            _require([v[0] for v in left] == [v[0] for v in right] and left, "paired stage identity differs")
            dimension = len(left[0][1]); cap = min(_DRIFT_MAX_ROWS,_DRIFT_MAX_COMBINED_SCALARS//(2*dimension))
            _require(1 <= dimension <= 4096 and cap > 0, "bounded stage dimension required")
            reports = []
            for offset in range(0,len(left),cap):
                pairs = [dict(id=a[0],original=a[1],successor=b[1]) for a,b in zip(left[offset:offset+cap],right[offset:offset+cap])]
                reports.append(compare_source_vector_drift_v1(pairs,dimension=dimension));kernel_calls += 1
            comparisons[stage] = dict(dimension=dimension,observations=len(left),drift_reports=reports,kernel_calls=len(reports))
        guard()
        return dict(schema="contextual-source-sensitivity/v1",dimension=restored.dimension,vocabulary_size=len(vocabulary),
            row_count=len(old_rows),real_clause_roles=len(identities["clause"]),physical_role_uses=len(old_rows)+len(identities["clause"]),
            total_clause_cells=8*len(old_rows),padded_clause_cells=8*len(old_rows)-len(identities["clause"]),
            identity_map=identities,stage_comparisons=comparisons,padding_audit=padding[0],
            initial_Long_position_grammar_and_bool_masks_exactly_equal=True,padding_counted_as_metric_observations=False,
            BOS_points=dict(original=bos[0],successor=bos[1],argmax_agree_rows=sum(a["top1_token_id"]==b["top1_token_id"] for a,b in zip(*bos)),
                stable_centered_deltas=[dict(id=a["id"],**_sensitivity_centered_logit_delta(left[1],right[1]))
                    for a,left,right in zip(bos[0],stages["BOS.raw_logits"][0],stages["BOS.raw_logits"][1])],
                float32_centering_algorithm="each arm subtracts its float32 row mean before existing drift comparison",
                tie_policy="lowest token ID among equal values",margin_arithmetic="binary64 subtraction of exact float32 logits",
                clause_route="initial BOS advances grammar to phase1 and routes real clause0; later clauses and full sequences remain untested"),
            run_counts=dict(paired_batches=batches,arm_batches=2*batches,explicit_model_project_calls=2*batches,
                explicit_paragraph_feature_calls=2*batches,explicit_clause_feature_calls=2*batches,
                explicit_model_start_calls=2*batches,fixed_BOS_next_logits_calls=2*batches,drift_kernel_calls=kernel_calls,
                scope="Direct probe invocations only; existing methods may make additional nested protocol/validation calls."),
            model_tensor_sha256_before=tensor_before,model_tensor_sha256_after=core.tensor_digest(model),weights_unchanged=True,
            input_transform_and_codec_sha256=metadata_hash,source_inputs_sha256=dict(original=input_hashes[0],successor=input_hashes[1]),
            context_receipts=dict(original=original_receipt,successor=successor_receipt),ambient_rng_preserved=True,
            source_inputs_unchanged=True,model_math_dtype="torch.float32",model_device="cpu",cpu_threads=1,
            float32_matmul_precision="highest",CPU_autocast_enabled=False,caller_default_dtype=str(caller_default_dtype),
            caller_numeric_policy_unchanged=True,
            model_inference_executed=True,fixed_BOS_forward_executed=True,model_restored_by_probe=False,
            free_prefix_accepted=False,generation_executed=False,acceptance_tolerance=None,
            conditioning_or_head_compatibility_qualified=False,source_to_model_equivalence_proven=False,
            convergence_proven=False,**_FALSE)
    finally:
        guard()


def infer_contextual_legal_model_occurrences_v1(restored, source_inputs, *, output_cap=512,
                                               deadline_seconds=120., batch_size=8):
    """Generate raw candidates from distinct physical paragraph/clause uses.

    Repeated text does not merge source identities or require identical vectors.
    File/receipt authentication belongs to the caller. This versioned consumer
    does not change the legacy inference or training context contracts, accept
    targets/prefixes, repair output or assess IR validity or task satisfaction.
    """
    _require(type(restored) is _RestoredContextualModel, "restored contextual handle required")
    _require(type(restored.dimension) is int and restored.dimension in (384, 768), "retained source width required")
    _require(type(output_cap) is int and 4 <= output_cap <= 512, "output cap must be 4..512")
    _require(type(batch_size) is int and 1 <= batch_size <= 16,
             "occurrence inference batch must be 1..16 for the eight-slot native projection")
    _require(type(deadline_seconds) in (int, float) and math.isfinite(deadline_seconds)
             and 0 < deadline_seconds <= 120., "deadline must be positive and at most120seconds")
    _sensitivity_source_precheck(source_inputs, restored.dimension)
    core, _, _, _, _, _, _, contexts_owner = _owners()
    torch = core._torch(); model = restored.model
    dimension, codec = restored.dimension, restored.codec
    _require(torch.get_num_threads() == 1, "caller must configure one CPU thread")
    _require(torch.get_float32_matmul_precision() == "highest" and not torch.is_autocast_enabled("cpu"),
             "highest float32 matmul precision and CPU autocast disabled required")
    core._model(model, torch)
    _require(all(not item.training for item in model.modules()) and all(p.grad is None for p in model.parameters()),
             "frozen evaluation model without gradients required")
    _require(all(value.device.type == "cpu" and (not value.is_floating_point() or value.dtype == torch.float32)
                 for value in model.state_dict().values()), "CPU float32 restored state required")
    transform = restored.input_transform; vocabulary = codec.get("target_vocabulary")
    mean = transform.get("mean")
    _require(type(transform) is dict and set(transform) == {"mode", "mean", "scale", "origin"}
        and transform["origin"] == "training_only" and transform["mode"] in ("none", "center_rms")
        and type(transform["mean"]) is list and len(transform["mean"]) == restored.dimension
        and all(type(value) in (int, float) and math.isfinite(value) for value in transform["mean"])
        and type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"])
        and .01 <= transform["scale"] <= 1e8, "finite saved TRAIN transform required")
    _require(transform["mode"] != "none" or (transform["mean"] == [0.]*restored.dimension and transform["scale"] == 1.),
             "saved identity transform differs")
    _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096
        and all(type(value) is str for value in vocabulary)
        and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"], "saved bounded generation vocabulary required")
    inputs_sha = core.digest(source_inputs)
    rows, contexts = deepcopy((source_inputs["rows"], source_inputs["contexts"]))
    working_sha = core.digest(dict(rows=rows, contexts=contexts))
    metadata_sha = core.digest(dict(codec=restored.codec, input_transform=restored.input_transform))
    tensor_sha = core.tensor_digest(model)
    _require(tensor_sha == restored.tensor_sha256, "restored model changed before occurrence inference")
    rng = torch.get_rng_state().clone(); caller_dtype = torch.get_default_dtype()
    bindings = tuple((owner, name, getattr(owner, name), getattr(owner, name).__code__) for owner, name in (
        (contexts_owner, "validate_context"), (contexts_owner, "batch_source_context"), (core, "_greedy")))
    parameter_bindings = tuple((name,value,value.requires_grad) for name,value in model.named_parameters())
    def method_binding(value):
        function = getattr(value,"__func__",value)
        return (getattr(value,"__self__",None),function,getattr(function,"__code__",None))
    model_methods = tuple((name,method_binding(getattr(model,name))) for name in ("project","start","next_logits"))
    tensors, packets, generated_returns, receipt_returns, reports = [], [], [], [], []
    calls = dict(greedy_started=0,greedy_returned=0)

    def tensor_snapshot(value, *, boolean=False):
        _require(type(value) is torch.Tensor and value.device.type == "cpu"
            and value.dtype == (torch.bool if boolean else torch.float32), "plain CPU generation tensor required")
        _require(boolean or bool(torch.isfinite(value).all()), "finite generation tensor required")
        return value.detach().clone()

    def retain_tensor(value, *, boolean=False):
        for actual, _, _ in tensors:
            if actual is value:return
        tensors.append((value, tensor_snapshot(value, boolean=boolean), boolean))

    def guard(stage, *, part=None, data=None, packet=None, generated=None, greedy_returned=False):
        _require(restored.model is model and restored.codec is codec and restored.input_transform is transform
            and type(restored.dimension) is int and restored.dimension == dimension
            and type(restored.tensor_sha256) is str and restored.tensor_sha256 == tensor_sha
            and codec.get("target_vocabulary") is vocabulary and transform.get("mean") is mean,
            "occurrence inference restored handle or metadata binding changed")
        current_parameters = tuple(model.named_parameters())
        _require(len(current_parameters) == len(parameter_bindings)
            and all(name == before_name and value is before_value and value.requires_grad is requires_grad
                    for (name,value),(before_name,before_value,requires_grad) in zip(current_parameters,parameter_bindings)),
            "occurrence inference parameter binding or requires_grad changed")
        _require(all(all(current is before for current,before in zip(method_binding(getattr(model,name)),expected))
                     for name,expected in model_methods),
                 "occurrence inference model method binding changed")
        _require(core.digest(source_inputs) == inputs_sha
            and core.digest(dict(rows=rows, contexts=contexts)) == working_sha,
            "occurrence inference source or working packet changed")
        _require(core.digest(dict(codec=restored.codec, input_transform=restored.input_transform)) == metadata_sha,
                 "occurrence inference saved metadata changed")
        _require(core.tensor_digest(model) == tensor_sha == restored.tensor_sha256
            and all(not item.training for item in model.modules()) and all(p.grad is None for p in model.parameters()),
            "occurrence inference model changed")
        _require(torch.equal(rng, torch.get_rng_state()), "occurrence inference changed CPU RNG")
        _require(torch.get_default_dtype() == caller_dtype and torch.get_num_threads() == 1
            and torch.get_float32_matmul_precision() == "highest" and not torch.is_autocast_enabled("cpu"),
            "occurrence inference CPU precision policy changed")
        _require(all(getattr(owner,name) is function and function.__code__ is code
                     for owner,name,function,code in bindings), "occurrence inference owner binding changed")
        for value, snapshot, boolean in tensors:
            _require(value.device.type == "cpu" and value.dtype == snapshot.dtype
                and tuple(value.shape) == tuple(snapshot.shape) and torch.equal(value,snapshot)
                and (boolean or _sensitivity_tensor_sha256(value) == _sensitivity_tensor_sha256(snapshot)),
                "generation working tensor changed")
        for actual, vectors, mask in packets:
            _require(type(actual) is dict and set(actual) == {"vectors", "mask"}
                and actual["vectors"] is vectors and actual["mask"] is mask, "generation context packet changed")
        for value, expected in generated_returns:
            _require(core.digest(dict(tokens=value[1],statuses=value[2])) == expected,
                     "generation returned rows changed")
        for value, expected in receipt_returns + reports:
            _require(core.digest(value) == expected, "occurrence receipt or report changed")
        if data is not None:
            _require(part is not None and tuple(data.shape) == (len(part),restored.dimension), "generation data shape differs")
            retain_tensor(data)
        if packet is not None:
            _require(type(packet) is dict and set(packet) == {"vectors","mask"}, "closed generation context packet required")
            vectors, mask = packet["vectors"], packet["mask"]
            _require(type(vectors) is torch.Tensor and tuple(vectors.shape) == (len(part),8,restored.dimension)
                and type(mask) is torch.Tensor and tuple(mask.shape) == (len(part),8), "generation context shape differs")
            expected_mask = [[slot < len(contexts[row["id"]]["segments"]) for slot in range(8)] for row in part]
            _require(mask.dtype == torch.bool and mask.tolist() == expected_mask
                and not bool(vectors[~mask].any()), "generation clause mask or zero padding differs")
            retain_tensor(vectors);retain_tensor(mask,boolean=True)
            if not any(actual is packet for actual,_,_ in packets):packets.append((packet,vectors,mask))
        if generated is not None:
            _require(type(generated) is tuple and len(generated) == 3 and type(generated[1]) is list
                and type(generated[2]) is list and len(generated[1]) == len(generated[2]) == len(part),
                "closed generated row cardinality required")
            _require(type(generated[0]) is torch.Tensor and tuple(generated[0].shape) == (len(part),restored.dimension),
                     "returned projection shape differs")
            retain_tensor(generated[0])
            for tokens, status in zip(generated[1],generated[2]):
                _require(type(tokens) is list and all(type(token) is int and 3 <= token < len(vocabulary) for token in tokens)
                    and type(status) is str and status in ("eos","output_limit","invalid_special_token","deadline"),
                    "raw generated token or status differs")
                _require((status == "output_limit" and len(tokens) == output_cap-1)
                    or (status in ("eos","invalid_special_token") and len(tokens) <= output_cap-2)
                    or (status == "deadline" and not tokens), "raw generated cap or terminal status differs")
            if not any(value is generated for value,_ in generated_returns):
                generated_returns.append((generated,core.digest(dict(tokens=generated[1],statuses=generated[2]))))
        if stage == "before_greedy":calls["greedy_started"] += 1
        if stage == "after_greedy" and greedy_returned:calls["greedy_returned"] += 1

    guard("before_context_validation")
    try:
        paragraph_occurrences, clause_occurrences, per_row_returns = [], [], []
        for row_index,row in enumerate(rows):
            guard("before_row_context")
            receipt, returned = _sensitivity_occurrence_contexts([row],{row["id"]:contexts[row["id"]]},
                restored.dimension,core,contexts_owner)
            receipt_returns.extend(((receipt,core.digest(receipt)),(returned,core.digest(returned))))
            guard("after_row_context")
            paragraph_occurrences.append(dict(id=row["id"],row_index=row_index,
                source_sha256=contexts[row["id"]]["source_sha256"],embedding_sha256=core.digest(row["input"])))
            clause_occurrences.extend(dict(entry,row_index=row_index) for entry in receipt["clause_occurrence_inventory"])
            per_row_returns.extend(returned)
        context_receipt = dict(schema="contextual-source-inference-occurrences/v1",dimension=restored.dimension,
            contexts_sha256=core.digest(contexts),paragraph_occurrence_inventory=paragraph_occurrences,
            clause_occurrence_inventory=clause_occurrences,per_row_validator_returns=per_row_returns,
            source_segmentation="literal_blank_line_exact_physical_occurrences",
            paragraph_text_uniqueness_asserted=False,global_text_to_single_cached_vector_asserted=False,
            reference_labels_accessed=False,admitted=False,qualified=False)
        receipt_returns.append((context_receipt,core.digest(context_receipt)))
        guard("after_context_validation")
        legacy = _infer_contextual_generation(restored,source_inputs,rows,contexts,context_receipt,
            core,contexts_owner,output_cap=output_cap,deadline_seconds=deadline_seconds,
            batch_size=batch_size,occurrence_guard=guard)
        report = {key:value for key,value in legacy.items() if key not in ("schema","completed")}
        report.update(schema="contextual-legal-ir-occurrence-inference/v1",context_receipt=context_receipt,
            context_receipt_sha256=core.digest(context_receipt),execution_completed=legacy["completed"],
            eos_completed=all(row["generation_status"] == "eos" for row in report["predictions"]),
            decoded_IR_valid=None,task_satisfied=None,
            unassessed_reason="raw candidate generation does not assess decoded IR validity or task satisfaction",
            model_inference_executed=calls["greedy_started"] > 0,greedy_generation_executed=calls["greedy_started"] > 0,
            greedy_calls_started=calls["greedy_started"],greedy_calls_returned=calls["greedy_returned"],CPU_dtype="torch.float32",
            cpu_threads=1,float32_matmul_precision="highest",CPU_autocast_enabled=False,
            paragraph_occurrences=len(paragraph_occurrences),clause_occurrences=len(clause_occurrences),
            caller_default_dtype_preserved=True,saved_metadata_unchanged=True,
            legacy_inference_and_training_contracts_changed=False)
        reports.append((report,core.digest(report)))
        guard("return")
        return report
    finally:
        guard("finally")


__all__ = ["SCHEMA", "restore_contextual_legal_model", "infer_contextual_legal_model", "compare_source_vector_drift_v1", "compare_contextual_source_sensitivity_v1", "infer_contextual_legal_model_occurrences_v1"]
