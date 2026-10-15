"""Opt-in score sidecars from an already opened retained span decoder.

This module never opens or invokes a model. An explicit, temporary forward
hook copies the existing inference output, returns None, and is removed on
exit. The unchanged runtime remains responsible for model/input custody.
Captured logits and reconstructed copying decisions confer no legal authority.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import struct

SCHEMA = "retained-span-score-capture/v1"
SCORE_SCHEMA = "joint-source-span-scores/v1"
SPAN_FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
OPTIONAL_FIELDS = ("object", "conditions", "exceptions", "temporal")
MODALITIES = ("O", "P", "F")
_REPORT_FIELDS = {"schema", "decoder_contract_id", "checkpoint_metadata", "control", "rows",
    "input_count", "eligible_count", "submitted_positions", "custody_scope", "outcome_counts",
    "raw_owner_report", "decoder_calls", "optimizer_steps_executed", "numerical_custody_checked",
    "weights_unchanged", "ambient_CPU_RNG_preserved", "authority"}
_FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
    semantic_correctness_verified=False, semantic_accuracy_measured=False,
    training_executed=False, encoder_executed=False, targets_accessed=False,
    native_execution_attested=False, independent_model_custody_attested=False,
    default_promotion=False, family_bridge_admitted=False, Lake_executed=False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _same(left, right):
    return _wire(left) == _wire(right)


def _f32(value):
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as error:
        raise ValueError("finite float32 arithmetic required") from error
    _require(math.isfinite(result), "finite float32 arithmetic required")
    return result


def _number(value):
    _require(type(value) is float and math.isfinite(value) and _f32(value) == value,
        "exact finite float32 score required")
    return value


def _tensor(value, shape):
    try:
        _require(tuple(value.shape) == shape and str(value.dtype) == "torch.float32"
            and value.device.type == "cpu" and value.requires_grad is False,
            "detached CPU float32 output geometry required")
        return value.detach().cpu().tolist()
    except (AttributeError, TypeError) as error:
        raise ValueError("retained tensor output required") from error


def _pair_winners(starts, ends):
    # Row-major stable tie order is the retained upper-triangular torch order.
    best = []
    for left, start in enumerate(starts):
        for right in range(left, len(ends)):
            item = (_f32(start + ends[right]), left, right)
            best.append(item)
            best.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
            del best[2:]
    first = best[0]
    margin = _f32(first[0] - best[1][0]) if len(best) > 1 else None
    return first, margin


def _verify_greedy(source_text, scores, raw):
    """Check only the original greedy observations, including its early stop."""
    diagnostics = raw.get("span_diagnostics")
    _require(type(diagnostics) is dict and set(diagnostics) == {"tokens", "facets", "modality_logits"},
        "original finite-score diagnostics required")
    _require(_same(diagnostics["tokens"], scores["tokens"])
        and _same(diagnostics["modality_logits"], scores["modality_logits"]),
        "original token/modality observations differ from captured heads")
    modality = scores["modality_logits"]
    ranked = sorted(range(3), key=lambda index: (-modality[index], index))
    minimum = _f32(modality[ranked[0]] - modality[ranked[1]])
    facets, occupied, stop = {}, set(), None
    rule = {"modality": MODALITIES[ranked[0]]}
    if minimum <= 1e-7:
        stop = "ambiguous_decoder_scores"
    for field in SPAN_FIELDS:
        if stop is not None:
            break
        present, presence_margin = True, None
        if field in OPTIONAL_FIELDS:
            pair = scores["presence_logits"][field]
            presence_margin = abs(_f32(pair[1] - pair[0]))
            if presence_margin <= 1e-7:
                stop = "ambiguous_decoder_scores"
                break
            minimum = min(minimum, presence_margin)
            present = pair[1] > pair[0]
        diagnostic = dict(present=present, presence_logit_margin=presence_margin,
            token_start=None, token_end_inclusive=None, char_start=None,
            char_end=None, text=None, span_logit_margin=None)
        atom = ""
        if present:
            winner, margin = _pair_winners(scores["start_logits"][field], scores["end_logits"][field])
            if margin is not None and margin <= 1e-7:
                stop = "ambiguous_decoder_scores"
                break
            if margin is not None:
                minimum = min(minimum, margin)
            _, left, right = winner
            begin, end = scores["tokens"][left]["start"], scores["tokens"][right]["end"]
            atom = source_text[begin:end]
            diagnostic.update(token_start=left, token_end_inclusive=right,
                char_start=begin, char_end=end, text=atom, span_logit_margin=margin)
            positions = set(range(left, right + 1))
            if occupied & positions:
                facets[field] = diagnostic
                stop = "copied_spans_overlap"
                break
            occupied.update(positions)
        facets[field] = diagnostic
        rule[field] = ([atom] if present else []) if field in ("conditions", "exceptions", "temporal") else atom
    _require(_same(diagnostics["facets"], facets), "original partial greedy facet observations differ")
    if stop is not None:
        _require(raw.get("status") == "abstained" and raw.get("reason") == stop,
            "original greedy stopping decision differs")
    elif raw.get("status") == "decoded":
        _require(raw.get("reason") is None and _same(raw.get("canonical_ir"), {"rules": [rule]})
            and _same(raw.get("minimum_decision_logit_margin"), minimum),
            "original complete greedy selection differs")
    else:
        # Syntax validation belongs to the unchanged owner, not this sidecar.
        _require(raw.get("status") == "abstained" and raw.get("reason") == "generated_ir_rejected",
            "unexpected original post-selection refusal")


class _Attachment:
    def __init__(self, owner, model):
        self.owner, self.model = owner, model

    def __enter__(self):
        self.owner._attach(self.model)
        return self.owner

    def __exit__(self, exc_type, exc, traceback):
        self.owner.close()
        return False


class RetainedSpanScoreCapture:
    """One-use capture; caller explicitly invokes unchanged runtime inference."""
    def __init__(self, source_rows, *, submitted_positions):
        _require(type(source_rows) is list and 1 <= len(source_rows) <= 64,
            "one to 64 source occurrences required")
        _require(all(type(row) is dict and set(row) == {"id", "source_text"}
            and type(row["id"]) is str and row["id"] and type(row["source_text"]) is str
            and row["source_text"].strip() for row in source_rows), "closed source-only rows required")
        _require(len({row["id"] for row in source_rows}) == len(source_rows), "unique occurrence IDs required")
        _require(type(submitted_positions) is list and all(type(value) is int and 0 <= value < len(source_rows)
            for value in submitted_positions) and submitted_positions == sorted(set(submitted_positions)),
            "ordered unique submitted positions required")
        self._sources = deepcopy(source_rows)
        self._positions = list(submitted_positions)
        self._tokens = []
        if submitted_positions:
            # This retained tokenizer/grammar module has no numerical import.
            from ....optimizers.logic_theorem_optimizer.legal_span_formula import tokenize_source
            for position in submitted_positions:
                self._tokens.append([{key: token[key] for key in ("text", "start", "end")}
                    for token in tokenize_source(source_rows[position]["source_text"])])
        self._state, self._model, self._handle = "ready", None, None
        self._captured, self._failed = [], False

    def attach(self, model):
        """Return a context manager; entering registers a hook without inference."""
        return _Attachment(self, model)

    def _attach(self, model):
        _require(self._state == "ready", "capture attachment is one-use")
        if not self._positions:
            _require(model is None, "unsubmitted rows require the runtime no-model case")
            self._state = "active"
            return
        _require(model is not None and callable(getattr(model, "register_forward_hook", None)),
            "already opened retained model required")
        _require(not getattr(model, "_forward_hooks", {}) and not getattr(model, "_forward_pre_hooks", {}),
            "unmodified top-level forward hook registry required")
        self._model = model
        self._handle = model.register_forward_hook(self._hook)
        self._state = "active"

    def _hook(self, module, inputs, output):
        try:
            _require(self._state == "active" and module is self._model
                and len(self._captured) < len(self._positions), "unexpected retained forward capture")
            tokens = self._tokens[len(self._captured)]
            size = len(tokens)
            _require(type(inputs) is tuple and len(inputs) == 4
                and tuple(inputs[0].shape)[:2] == (1, size)
                and tuple(inputs[1].shape) == (1, size)
                and tuple(inputs[2].shape) == (1,)
                and inputs[2].detach().cpu().tolist() == [size], "one exact source row per forward required")
            _require(type(output) is dict and set(output) == {"modality", "presence", "start", "end"},
                "closed retained tensor heads required")
            modality = _tensor(output["modality"], (1, 3))[0]
            presence = _tensor(output["presence"], (1, 4, 2))[0]
            starts, ends = (_tensor(output[name], (1, 6, size))[0] for name in ("start", "end"))
            _require(type(modality) is list and len(modality) == 3
                and type(presence) is list and len(presence) == 4
                and all(type(row) is list and len(row) == 2 for row in presence)
                and all(type(table) is list and len(table) == 6
                    and all(type(row) is list and len(row) == size for row in table) for table in (starts, ends)),
                "captured output list geometry differs")
            for row in [modality, *presence, *starts, *ends]:
                for value in row:
                    _number(value)
            self._captured.append(dict(schema=SCORE_SCHEMA, tokens=deepcopy(tokens), modality_logits=modality,
                presence_logits=dict(zip(OPTIONAL_FIELDS, presence, strict=True)),
                start_logits=dict(zip(SPAN_FIELDS, starts, strict=True)),
                end_logits=dict(zip(SPAN_FIELDS, ends, strict=True))))
        except Exception:
            self._failed = True
            raise
        # None explicitly leaves the original model output unchanged.
        return None

    def close(self):
        """Remove the temporary hook, including when inference raises."""
        if self._state == "active":
            try:
                if self._handle is not None:
                    self._handle.remove()
                    _require(not getattr(self._model, "_forward_hooks", {}), "temporary capture hook remained")
            except Exception:
                self._failed = True
                raise
            finally:
                self._state = "closed"

    def finalize(self, report):
        """Bind separate scores to the completed, unchanged runtime report."""
        _require(self._state == "closed" and not self._failed, "closed successful capture required")
        _require(type(report) is dict and set(report) == _REPORT_FIELDS
            and report["schema"] == "arbitrary-native-retained-span-inference/v1"
            and report["decoder_contract_id"] == "arbitrary-raw-gte384-retained-span/v1"
            and type(report["control"]) is str and report["control"] in ("none", "zero", "disabled", "rotate")
            and type(report["rows"]) is list and len(report["rows"]) == len(self._sources)
            and type(report["input_count"]) is int and report["input_count"] == len(self._sources)
            and type(report["eligible_count"]) is int and report["eligible_count"] == len(self._positions)
            and _same(report["submitted_positions"], self._positions)
            and len(self._captured) == len(self._positions), "completed runtime report/capture counts differ")
        _require(type(report["authority"]) is dict and report["authority"]
            and all(value is False for value in report["authority"].values())
            and report["optimizer_steps_executed"] == 0
            and type(report["optimizer_steps_executed"]) is int
            and type(report["decoder_calls"]) is int
            and report["decoder_calls"] == int(bool(self._positions))
            and type(report["checkpoint_metadata"]) is dict,
            "unaccepted frozen runtime report required")
        has_model = bool(self._positions)
        _require(report["numerical_custody_checked"] is has_model
            and report["weights_unchanged"] is (True if has_model else None)
            and report["ambient_CPU_RNG_preserved"] is (True if has_model else None),
            "original runtime numerical custody did not complete")
        raw = report["raw_owner_report"]
        if has_model:
            _require(type(raw) is dict and type(raw.get("rows")) is list
                and len(raw["rows"]) == len(self._positions)
                and raw.get("latent_ablation") == ("disabled" if report["control"] == "disabled" else "none")
                and raw.get("checkpoint_sha256") == report["checkpoint_metadata"].get("checkpoint_sha256"),
                "original owner report/control/checkpoint differs")
        else:
            _require(raw is None, "no submitted source must have no owner report")
        by_position = dict(zip(self._positions, enumerate(self._captured), strict=True))
        rows = []
        for position, (source, row) in enumerate(zip(self._sources, report["rows"], strict=True)):
            sha = hashlib.sha256(source["source_text"].encode("utf-8")).hexdigest()
            _require(type(row) is dict and row.get("id") == source["id"]
                and type(row.get("position")) is int and row["position"] == position
                and row.get("source_sha256") == sha, "physical source occurrence/report join differs")
            donor = (position + 1) % len(self._sources) if report["control"] == "rotate" else position
            _require(type(row.get("latent_donor_position")) is int
                and row["latent_donor_position"] == donor
                and row.get("latent_donor_id") == self._sources[donor]["id"]
                and type(row.get("latent_input_enabled")) is bool
                and (report["control"] != "disabled" or row["latent_input_enabled"] is False),
                "original latent donor/control occurrence join differs")
            scores = None
            candidate = row.get("decoder_row")
            if position in by_position:
                ordinal, scores = by_position[position]
                _require(type(candidate) is dict and _same(candidate, raw["rows"][ordinal])
                    and candidate.get("source_sha256") == sha
                    and candidate.get("latent_sha256") == row.get("effective_latent_sha256")
                    and candidate.get("latent_input_enabled") is row.get("latent_input_enabled"),
                    "captured source/latent/raw owner join differs")
                _verify_greedy(source["source_text"], scores, candidate)
            else:
                _require(candidate is None, "unsubmitted occurrence must retain no decoder row")
            rows.append(dict(id=source["id"], position=position, source_sha256=sha,
                original_outcome=row.get("outcome"), raw_status=None if candidate is None else candidate.get("status"),
                raw_reason=None if candidate is None else candidate.get("reason"),
                raw_row_sha256=None if candidate is None else _digest(candidate),
                effective_latent_sha256=row.get("effective_latent_sha256"),
                latent_donor_id=row.get("latent_donor_id"), latent_donor_position=row.get("latent_donor_position"),
                latent_input_enabled=row.get("latent_input_enabled"), scores=deepcopy(scores)))
        result = dict(schema=SCHEMA, score_schema=SCORE_SCHEMA,
            origin="same_retained_inference_forward_hook", raw_report_sha256=_digest(report),
            checkpoint_metadata=deepcopy(report["checkpoint_metadata"]), control=report["control"],
            rows=rows, input_count=len(rows), submitted_positions=list(self._positions),
            captured_forward_count=len(self._captured), raw_greedy_verification_count=len(self._captured),
            additional_model_forwards=0, original_outputs_modified=False,
            custody_scope="unchanged runtime checks; hook copy and raw-greedy consistency only",
            authority=dict(_FALSE))
        self._state = "finalized"
        return result


__all__ = ["SCHEMA", "SCORE_SCHEMA", "RetainedSpanScoreCapture"]
