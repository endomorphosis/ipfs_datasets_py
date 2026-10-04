"""Inherited-vocabulary greedy decoding with a target-independent schema mask.

The mask enforces one canonical O/P/F rule, exact field order, nonempty scalar
strings and up to four sorted unique qualifiers per facet. It uses the complete
inherited vocabulary, not observed field-value pairs or scoring references.
Syntax constraints cannot supply missing lexical values or establish meaning.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import gte_decoder_source_generation as raw
from . import gte_decoder_transfer_batch as codec_module

SCHEMA = "gte-decoder-schema-constrained-generation/v1"
POLICY = "single-canonical-rule-inherited-vocabulary-budget-aware/v1"
FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = FIELDS[4:]
require, digest = raw._require, raw.digest
RECEIPT_FIELDS = set("schema policy variant head input_dimension input_vector_sha256 numerical_input_sha256 codec_sha256 max_new_tokens inherited_max_target_tokens effective_max_new_tokens generated_ids generated_ids_sha256 terminated truncated steps decoded_target decoded_target_sha256 model_state_sha256_before model_state_sha256_after raw_argmax_overrides producer_pins model_unchanged numerical_context_restored target_access reference_prefix_used training_executed source_semantics_verified proof_authority vocabulary_extended semantic_field_value_mask".split())
STEP_FIELDS = set("step prefix_sha256 raw_logits_sha256 raw_argmax_token_id allowed_token_ids next_token_id schema_overrode_raw_argmax".split())


def producer_pins():
    return {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (raw, codec_module)} | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


class Grammar:
    """Small deterministic prefix machine; no target or source-text input."""
    def __init__(self, codec, head):
        require(head in ("primary384", "legacy8") and type(codec) is dict, "original codec and head required")
        vocabulary = codec.get("target_vocabulary")
        require(type(vocabulary) is list and 3 <= len(vocabulary) <= 4096 and
                all(type(t) is str for t in vocabulary) and len(set(vocabulary)) == len(vocabulary) and
                vocabulary[:3] == ["<pad>", "<bos>", "<eos>"], "bounded distinct inherited vocabulary required")
        self.vocabulary, self.head, self.plan = vocabulary, head, []
        positions = {token: i for i, token in enumerate(vocabulary)}
        def literal(token):
            require(token in positions, "inherited vocabulary lacks required grammar literal")
            self.plan.append(("literal", positions[token]))
        def strings(field):
            values = {}
            for index, token in enumerate(vocabulary[3:], 3):
                try:
                    value = json.loads(token)
                except (ValueError, TypeError):
                    continue
                if type(value) in (str, list):
                    canonical = json.dumps(value, separators=(',', ':'), ensure_ascii=head == "primary384")
                    require(token == canonical, "noncanonical inherited lexical token")
                if head == "legacy8":
                    if type(value) is not list or len(value) != 3 or value[:2] != ["atom", field]:
                        continue
                    value = value[2]
                if type(value) is str and 0 < len(value) <= (4096 if field in QUALIFIERS else 16384):
                    try:
                        value.encode('utf-8')
                    except UnicodeError:
                        raise ValueError("inherited string is not valid UTF8") from None
                    if field in QUALIFIERS or value.strip():
                        if field != "modality" or value in {"O", "P", "F"}:
                            values[index] = value
            return values
        if head == "primary384":
            for token in ('{', '"rules"', ':', '[', '{'):
                literal(token)
            for ordinal, field in enumerate(sorted(FIELDS)):
                if ordinal: literal(',')
                literal(json.dumps(field)); literal(':')
                values = strings(field)
                if field in QUALIFIERS:
                    require(all(t in positions for t in ('[', ']', ',')), "JSON array syntax missing")
                    self.plan.append(("array", values, positions['['], positions[']'], positions[',']))
                else:
                    require(bool(values), "no expressible scalar field: " + field)
                    self.plan.append(("scalar", values))
            for token in ('}', ']', '}', '<eos>'):
                literal(token)
        else:
            for field in FIELDS:
                literal(json.dumps(["field", field], separators=(',', ':')))
                values = strings(field)
                if field in QUALIFIERS:
                    end = json.dumps(["end", field], separators=(',', ':'))
                    require(end in positions, "legacy qualifier end marker missing")
                    self.plan.append(("legacy_array", values, positions[end]))
                else:
                    require(bool(values), "no expressible scalar field: " + field)
                    self.plan.append(("scalar", values))
            literal('<eos>')
        self.initial = (0, "item", ())

    def transitions(self, state):
        index, phase, values = state
        if index == len(self.plan): return {}
        item = self.plan[index]
        advance = (index + 1, "item", ())
        kind = item[0]
        if kind == "literal": return {item[1]: advance}
        if kind == "scalar": return {token: advance for token in item[1]}
        if kind == "array" and phase == "item": return {item[2]: (index, "value_or_end", ())}
        eligible = {token: value for token, value in item[1].items()
                    if len(values) < 4 and (not values or value > values[-1])}
        if kind == "array":
            if phase == "after_value":
                result = {item[3]: advance}
                if eligible: result[item[4]] = (index, "need_value", values)
                return result
            result = {token: (index, "after_value", (*values, value)) for token, value in eligible.items()}
            if phase == "value_or_end": result[item[3]] = advance
            return result
        return {item[2]: advance, **{token: (index, "legacy_values", (*values, value)) for token, value in eligible.items()}}

    def minimum_remaining(self, state):
        index, phase, _ = state
        if index == len(self.plan): return 0
        current = self.plan[index][0]
        now = (2 if phase in ("item", "need_value") else 1) if current == "array" else 1
        return now + sum(2 if item[0] == "array" else 1 for item in self.plan[index + 1:])

    def allowed(self, state, remaining):
        return {token: next_state for token, next_state in self.transitions(state).items()
                if 1 + self.minimum_remaining(next_state) <= remaining}

    def state_after(self, prefix):
        require(type(prefix) is list and prefix and prefix[0] == 1 and
                all(type(t) is int for t in prefix), "BOS-rooted integer prefix required")
        state = self.initial
        for token in prefix[1:]:
            choices = self.transitions(state)
            require(token in choices, "prefix violates canonical schema grammar")
            state = choices[token]
        return state


def generate_source_only(model, *, variant, head, input_vector, max_new_tokens,
                         inherited_max_target_tokens, codec):
    """Mask only impossible schema continuations; retain raw argmax evidence."""
    dimension, cap = raw._controls(variant, head, max_new_tokens, inherited_max_target_tokens)
    grammar = Grammar(codec, head)
    require(grammar.minimum_remaining(grammar.initial) <= cap, "fixed budget cannot complete one canonical rule")
    require(type(input_vector) is list and len(input_vector) == dimension and
            all(raw._finite_number(v) for v in input_vector), "finite source vector with declared dimension required")
    import torch
    require(isinstance(model, torch.nn.Module) and len(list(model.named_parameters())) ==
            (30 if variant == "student768" else 13), "complete inherited model required")
    part = model.primary if variant == "student768" and head == "primary384" else (model.legacy8 if variant == "student768" else model)
    require(part.target_embedding.num_embeddings == len(grammar.vocabulary), "model/codec vocabulary size differs")
    if variant == "student768" and head == "primary384":
        require(model.primary.max_target_tokens == inherited_max_target_tokens, "inherited target budget differs")
    pins, input_hash = producer_pins(), digest(input_vector)
    vector = torch.tensor([input_vector], dtype=torch.float32, device="cpu")
    require(bool(torch.isfinite(vector).all()), "source vector overflows float32")
    numeric_hash = digest(vector.tolist()[0])
    before, rng, threads = raw._snapshot(torch, model), torch.get_rng_state().clone(), torch.get_num_threads()
    modes = [m.training for m in model.modules()]
    ids, steps, state = [1], [], grammar.initial
    with raw._numerical_context(torch, model):
        for index in range(1, cap + 1):
            choices = grammar.allowed(state, cap - index + 1)
            require(bool(choices), "no budget-compatible canonical continuation")
            prefix = torch.tensor([ids], dtype=torch.int64, device="cpu")
            logits = raw._logits(torch, model, variant, head, vector, prefix)
            require(tuple(logits.shape) == (1, len(ids), len(grammar.vocabulary)), "prefix/logit vocabulary shape differs")
            values = logits[0, -1]
            allowed = sorted(choices)
            token = allowed[int(values[allowed].argmax())]
            steps.append({"step": index, "prefix_sha256": digest(ids), "raw_logits_sha256": digest(values.tolist()),
                "raw_argmax_token_id": int(values.argmax()), "allowed_token_ids": allowed,
                "next_token_id": token, "schema_overrode_raw_argmax": int(values.argmax()) != token})
            ids.append(token)
            state = choices[token]
            if token == 2: break
    after = raw._snapshot(torch, model)
    raw._unchanged(torch, before, after)
    require(torch.equal(rng, torch.get_rng_state()) and threads == torch.get_num_threads() and
            modes == [m.training for m in model.modules()], "numerical context not restored")
    require(digest(input_vector) == input_hash and digest(vector.tolist()[0]) == numeric_hash and pins == producer_pins(),
            "input or generation producer changed")
    require(ids[-1] == 2 and state[0] == len(grammar.plan), "schema generation did not terminate")
    decoded = codec_module._decode(ids, grammar.vocabulary, head)
    result = {"schema": SCHEMA, "policy": POLICY, "variant": variant, "head": head,
        "input_dimension": dimension, "input_vector_sha256": input_hash, "numerical_input_sha256": numeric_hash,
        "codec_sha256": digest(codec), "max_new_tokens": max_new_tokens,
        "inherited_max_target_tokens": inherited_max_target_tokens, "effective_max_new_tokens": cap,
        "generated_ids": ids, "generated_ids_sha256": digest(ids), "terminated": True, "truncated": False,
        "steps": steps, "decoded_target": decoded, "decoded_target_sha256": digest(decoded),
        "model_state_sha256_before": before["state_sha256"], "model_state_sha256_after": after["state_sha256"],
        "raw_argmax_overrides": sum(s["schema_overrode_raw_argmax"] for s in steps),
        "producer_pins": pins, "model_unchanged": True, "numerical_context_restored": True,
        "target_access": False, "reference_prefix_used": False, "training_executed": False,
        "source_semantics_verified": False, "proof_authority": False,
        "vocabulary_extended": False, "semantic_field_value_mask": False}
    inspect_source_only_generation(result, codec)
    return result


def inspect_source_only_generation(receipt, codec):
    """Recheck schema-mask decisions and output; this does not replay logits."""
    require(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS, "closed grammar receipt required")
    require(receipt["schema"] == SCHEMA and receipt["policy"] == POLICY and receipt["codec_sha256"] == digest(codec),
            "grammar receipt or exact codec differs")
    grammar = Grammar(codec, receipt["head"])
    dimension, cap = raw._controls(receipt["variant"], receipt["head"], receipt["max_new_tokens"], receipt["inherited_max_target_tokens"])
    require(type(receipt["input_dimension"]) is int and type(receipt["effective_max_new_tokens"]) is int and
            receipt["input_dimension"] == dimension and receipt["effective_max_new_tokens"] == cap, "receipt dimensions or budget differ")
    ids, state = receipt["generated_ids"], grammar.initial
    require(type(ids) is list and 2 <= len(ids) <= cap + 1 and ids[0] == 1 and ids[-1] == 2 and
            all(type(t) is int for t in ids) and type(receipt["steps"]) is list and
            len(receipt["steps"]) == len(ids) - 1, "generated token coverage differs")
    for index, step in enumerate(receipt["steps"], 1):
        require(type(step) is dict and set(step) == STEP_FIELDS and type(step["step"]) is int and
                type(step["next_token_id"]) is int and type(step["allowed_token_ids"]) is list and
                all(type(t) is int for t in step["allowed_token_ids"]), "closed strictly typed grammar step required")
        choices = grammar.allowed(state, cap - index + 1)
        token = ids[index]
        require(step["step"] == index and step["prefix_sha256"] == digest(ids[:index]) and
                step["allowed_token_ids"] == sorted(choices) and step["next_token_id"] == token and token in choices,
                "schema-mask step or generated prefix differs")
        require(type(step["raw_argmax_token_id"]) is int and 0 <= step["raw_argmax_token_id"] < len(grammar.vocabulary) and
                step["schema_overrode_raw_argmax"] is (step["raw_argmax_token_id"] != token) and raw._sha(step["raw_logits_sha256"]),
                "raw argmax evidence differs")
        require(step["raw_argmax_token_id"] not in choices or token == step["raw_argmax_token_id"],
                "grammar cannot override an already permitted raw argmax")
        state = choices[token]
    require(state[0] == len(grammar.plan) and receipt["generated_ids_sha256"] == digest(ids), "incomplete canonical generation")
    decoded = codec_module._decode(ids, grammar.vocabulary, receipt["head"])
    require(receipt["decoded_target"] == decoded and receipt["decoded_target_sha256"] == digest(decoded), "decoded target differs")
    require(receipt["terminated"] is True and receipt["truncated"] is False and
            type(receipt["raw_argmax_overrides"]) is int and
            receipt["raw_argmax_overrides"] == sum(s["schema_overrode_raw_argmax"] for s in receipt["steps"]), "stop or override accounting differs")
    require(receipt["producer_pins"] == producer_pins(), "producer changed")
    for key in ("input_vector_sha256", "numerical_input_sha256", "model_state_sha256_before", "model_state_sha256_after"):
        require(raw._sha(receipt[key]), "full SHA256 required")
    require(receipt["model_state_sha256_before"] == receipt["model_state_sha256_after"] and receipt["model_unchanged"] is True and
            receipt["numerical_context_restored"] is True, "generation mutated model/context")
    require(all(receipt[k] is False for k in ("target_access", "reference_prefix_used", "training_executed", "source_semantics_verified",
            "proof_authority", "vocabulary_extended", "semantic_field_value_mask")), "unsupported grammar generation authority claim")
    return {"syntax_valid": True, "numerical_execution_replayed": False, "source_semantics_verified": False}
