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
import math
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
                packet = contexts_owner.batch_source_context(torch, part, contexts, transform)
                generated = core._greedy(torch, model, data, output_cap,
                    len(restored.codec["target_vocabulary"]), deadline, source_context=packet)
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


__all__ = ["SCHEMA", "restore_contextual_legal_model", "infer_contextual_legal_model"]
