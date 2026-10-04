"""Small, separate native4096 formula-head experiment.

The public training entry requires a live result from the full native owner.
Saved JSON, padded vectors and tokenizer receipts cannot authorize training.
Only the inherited token embedding, GRU and readout are reused; the two source
paths are new. This pilot does not implement the three-width factorized head,
qualify a decoder, or change any production loader or historical teacher.
"""
from copy import deepcopy
import math
import time

from . import decoder_distillation_experiment as core
from . import decoder_distillation_experiment_v2 as inherited

SCHEMA = "native-owner4096-formula-sidecar/v1"
DIMENSION = 4096
OUTPUT_LIMIT = 512
FALSE = dict(core.FALSE, checkpoint_promoted=False, lake_executed=False,
             formalized=False, roundtrip_ok=False, convergence_proven=False,
             historical_linguistic_teacher_changed=False,
             learned_embedding_reconstruction=False)
_require = core._require


def _new_body(donor, *, vocabulary_size):
    """Numerical constructor only; synthetic use cannot grant native provenance."""
    torch = core._torch()
    spec = inherited._body_spec(donor, 384, torch)
    _require(spec["vocabulary_size"] == vocabulary_size,
             "donor and target vocabulary widths differ")
    original_digest = core.tensor_digest(donor)

    class NativePilot(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.dimension = DIMENSION
            with torch.random.fork_rng(devices=[]):
                self.condition = torch.nn.Linear(DIMENSION, spec["hidden_width"], dtype=torch.float32, device="cpu")
                self.source_to_embedding = torch.nn.Linear(
                    DIMENSION, spec["token_embedding_width"], bias=False, dtype=torch.float32, device="cpu")
            for module in ("target_embedding", "decoder", "output"):
                setattr(self, module, deepcopy(getattr(donor, module)))
            with torch.no_grad():
                self.condition.weight.zero_()
                self.condition.bias.zero_()
                self.source_to_embedding.weight.zero_()
            for parameter in self.parameters():
                parameter.grad = None

        def _input(self, value):
            _require(isinstance(value, torch.Tensor) and value.dtype == torch.float32
                     and value.device.type == "cpu" and value.ndim == 2
                     and 1 <= len(value) <= 16 and value.shape[1] == DIMENSION
                     and bool(torch.isfinite(value).all()), "finite native4096 CPU input required")

        def project(self, value):
            self._input(value)
            return value  # Explicit identity; no learned reconstruction claim.

        def start(self, value):
            self._input(value)
            return torch.tanh(self.condition(value)).unsqueeze(0), value

        def next_logits(self, tokens, state):
            _require(type(state) is tuple and len(state) == 2, "explicit source state required")
            hidden, source = state
            self._input(source)
            _require(isinstance(tokens, torch.Tensor) and tokens.dtype == torch.long
                     and tokens.device.type == "cpu" and tokens.ndim == 2
                     and len(tokens) == len(source) and 1 <= tokens.shape[1] < OUTPUT_LIMIT
                     and bool((tokens >= 0).all()) and bool((tokens < vocabulary_size).all()),
                     "bounded original-vocabulary prefix required")
            _require(isinstance(hidden, torch.Tensor) and hidden.dtype == torch.float32
                     and hidden.device.type == "cpu"
                     and tuple(hidden.shape) == (1, len(source), spec["hidden_width"])
                     and bool(torch.isfinite(hidden).all()), "finite recurrent state required")
            inputs = self.target_embedding(tokens) + self.source_to_embedding(source).unsqueeze(1)
            output, updated = self.decoder(inputs, hidden)
            logits = self.output(output)
            _require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(updated).all()),
                     "nonfinite native4096 decoder output")
            return logits, (updated, source)

        def forward(self, source, prefix):
            return self.next_logits(prefix, self.start(source))[0]

    model = NativePilot()
    _require(core.tensor_digest(donor) == original_digest, "constructor changed donor")
    return model


def _training_rows(native_rows, labels, codec):
    _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"}
             and type(codec["target_vocabulary"]) is list, "explicit original codec required")
    vocabulary = codec["target_vocabulary"]
    _require(len(vocabulary) == 32 and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"]
             and all(type(x) is str and 0 < len(x) <= 512 for x in vocabulary)
             and len(set(vocabulary)) == 32, "original complete32V codec required")
    _require(type(native_rows) is list and 1 <= len(native_rows) <= 16,
             "bounded native pilot rows required")
    by_id = {}
    for row in native_rows:
        _require(type(row) is dict and type(row.get("id")) is str
                 and row["id"] not in by_id, "unique native source identities required")
        by_id[row["id"]] = row
    _require(type(labels) is list and 2 <= len(labels) <= 16,
             "at least two distinct training labels required")
    rows = []
    for label in labels:
        _require(type(label) is dict and set(label) == {"id", "source_text", "target_ids"}
                 and type(label["id"]) is str and label["id"] in by_id,
                 "closed exact native source-bound target required")
        native = by_id[label["id"]]
        _require(label["source_text"] == native.get("source_text"), "native source text differs")
        vector = native.get("embedding")
        core._vector(vector, DIMENSION)
        norm = math.sqrt(sum(x*x for x in vector))
        _require(abs(norm-1.) <= 1e-5, "native LAST embedding must be L2 normalized")
        rows.append(dict(label, input=list(vector)))
    core._rows(rows, DIMENSION, vocabulary, OUTPUT_LIMIT)
    return rows


def _fit(model, rows, *, steps, learning_rate, deadline):
    """Bounded CPU numerical control; callers establish provenance separately."""
    torch = core._torch()
    _require(type(steps) is int and 1 <= steps <= 200, "bounded integer optimizer steps required")
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate)
             and 0 < learning_rate <= .01, "bounded learning rate required")
    _require(type(deadline) in (int, float) and math.isfinite(deadline)
             and time.monotonic() < deadline <= time.monotonic()+301,
             "live bounded monotonic deadline required")
    vectors = torch.tensor([row["input"] for row in rows], dtype=torch.float32)
    # Statistics use only this pilot's selected TRAIN sources. No holdout exists.
    mean64 = vectors.double().mean(0)
    scale = float(((vectors.double()-mean64).square().sum()/len(rows)).sqrt())
    _require(math.isfinite(scale) and scale > 1e-8, "distinct training vectors required")
    mean = mean64.float()
    normalized = (vectors-mean)/scale
    length = max(len(row["target_ids"]) for row in rows)
    labels = torch.tensor([row["target_ids"]+[0]*(length-len(row["target_ids"]))
                           for row in rows], dtype=torch.long)
    token_count = int((labels[:, 1:] != 0).sum())
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=learning_rate, weight_decay=.01, foreach=False)
    initial = core.tensor_digest(model)

    def loss(source):
        logits = model(source, labels[:, :-1])
        return torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].flatten(), ignore_index=0)

    def evaluate():
        _require(time.monotonic() < deadline, "pilot deadline before evaluation")
        model.eval()
        with torch.inference_mode():
            ce = float(loss(normalized))
            zero_ce = float(loss(torch.zeros_like(normalized)))
            shuffled_ce = float(loss(normalized.roll(1, 0)))
            generated = core._greedy(torch, model, normalized, OUTPUT_LIMIT, 32, deadline)
        _require(generated is not None, "pilot deadline during generation")
        predictions, statuses = generated[1:]
        return dict(cross_entropy=ce, zero_source_cross_entropy=zero_ce,
                    rotated_source_cross_entropy=shuffled_ce,
                    exact=sum(status == "eos" and tokens == row["target_ids"][1:-1]
                              for tokens, status, row in zip(predictions, statuses, rows)),
                    predictions=[dict(id=row["id"], token_ids=tokens, status=status)
                                 for row, tokens, status in zip(rows, predictions, statuses)])

    before = evaluate()
    updates = []
    started = time.monotonic()
    for step in range(steps):
        _require(time.monotonic() < deadline, "pilot deadline before optimizer update")
        model.train()
        optimizer.zero_grad(set_to_none=True)
        objective = loss(normalized)
        _require(bool(torch.isfinite(objective)), "nonfinite pilot loss")
        objective.backward()
        gradient_norm = float(torch.nn.utils.clip_grad_norm_(parameters, 1., error_if_nonfinite=True))
        source_gradients = {name: float(parameter.grad.norm()) if parameter.grad is not None else 0.
                            for name, parameter in model.named_parameters()
                            if name in ("condition.weight", "source_to_embedding.weight")}
        _require(time.monotonic() < deadline, "pilot deadline before optimizer step")
        optimizer.step()
        _require(all(bool(torch.isfinite(p).all()) for p in parameters), "nonfinite pilot weights")
        updates.append(dict(step=step+1, loss_before_update=float(objective.detach()),
                            gradient_norm_before_clip=gradient_norm, source_gradient_norms=source_gradients))
    fit_seconds = time.monotonic()-started
    after = evaluate()
    return dict(initial=before, final=after, updates=updates, optimizer_steps=steps,
                row_presentations=steps*len(rows), target_token_presentations=steps*token_count,
                fit_seconds=fit_seconds, seconds_per_row_presentation=fit_seconds/(steps*len(rows)),
                normalization=dict(mean=mean.tolist(), scale=scale,
                    statistics_dtype="float64", model_dtype="float32", training_ids=[r["id"] for r in rows]),
                initial_tensor_sha256=initial, final_tensor_sha256=core.tensor_digest(model))


def train_native_pilot(result, *, donor, codec, training_labels,
                       steps=20, learning_rate=.001, max_seconds=120):
    """Train a diagnostic head only after a real owned native forward succeeds.

    ``training_labels`` must select original training sources by exact identity
    and text. Extra native rows can be repeat/reset controls, never extra labels.
    This pilot has no held-out selection and never promotes its last iterate.
    """
    from .source_embeddings_4096_full_owner import require_live_result
    started = time.monotonic()
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds)
             and 0 < max_seconds <= 300, "bounded total pilot deadline required")
    native = require_live_result(result)
    rows = _training_rows(native["rows"], training_labels, codec)
    donor_digest = core.tensor_digest(donor)
    model = _new_body(donor, vocabulary_size=32)
    fit = _fit(model, rows, steps=steps, learning_rate=learning_rate, deadline=started+max_seconds)
    # A copied/forked result or changed live owner module still fails here.
    _require(require_live_result(result) == native, "native operation binding changed during fit")
    _require(core.tensor_digest(donor) == donor_digest, "pilot changed donor")
    receipt = dict(schema=SCHEMA, dimension=DIMENSION,
                   architecture="native4096-persistent-source-inherited-token-gru-pilot/v1",
                   codec=deepcopy(codec), donor_tensor_sha256=donor_digest,
                   native_provenance=deepcopy(native["provenance"]),
                   training_rows_sha256=core.digest(rows), training_source_count=len(rows),
                   encoder_context_tokens=512, decoder_output_tokens=OUTPUT_LIMIT, temperature=0,
                   fit=fit, elapsed_seconds=time.monotonic()-started,
                   model_state={name: tensor.detach().tolist() for name, tensor in model.state_dict().items()},
                   optimizer_resumable=False, optimizer="fresh_AdamW_default_betas_eps_weight_decay.01",
                   learning_rate=learning_rate, max_grad_norm=1.,
                   bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
                   workers=1, encoder_finetuned=False, historical_teacher_trained=False,
                   factorized_three_width_head_compatible=False, validation_count=0,
                   selection_policy="none_no_holdout_no_promotion",
                   loss_scope="training_token_cross_entropy_only",
                   projection_policy="identity_no_learned_embedding_reconstruction", **FALSE)
    receipt["receipt_sha256"] = core.digest(receipt)
    return receipt
