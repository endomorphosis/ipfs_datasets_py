"""Render generated inverse tokens at grammar boundaries, without a source.

The paired tokenizer discards whitespace. Tightening punctuation across the
whole output can therefore fuse an action with a leading ``.cfg`` object. This
additive codec tightens punctuation only inside grammar fields. It retains
every generated token and refuses competing complete grammar interpretations.
The caller must still compare the result to the actually learned forward AST
and independently check the complete original instruction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import rich_grammar as grammar
from . import instruction_scope
from ....optimizers.logic_theorem_optimizer import autoencoder_paired_text as paired

SCHEMA = "intent-rich-generated-inverse-codec/v1"
METHOD = "generated_token_grammar_field_rendering"
MAX_TOKENS = 160
MAX_PARTITIONS = 1024
MAX_CANDIDATES = 64
_LEXICAL = re.compile(r"(?:[A-Za-z0-9_]+|[./:`-])\Z")


def implementation_pins():
    return {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (grammar, instruction_scope, paired)} | {
                __name__: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _key(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class _BoundExceeded(ValueError):
    pass


def recover_generated_inverse(generated_text):
    """Return a unique bounded inverse AST from generated text alone.

    This is a deterministic post-decoding codec, not a model, source parser
    fallback, theorem checker, or lossless recovery of pre-tokenization spaces.
    ``candidate`` means exactly one grammar interpretation under the declared
    in-field punctuation convention. Different source meaning is never repaired
    here. ``ambiguous`` and ``unsupported`` have no accepted text or AST.
    """
    report = {"schema": SCHEMA, "method": METHOD, "status": "unsupported",
        "text": None, "ast": None, "token_equivalent": False,
        "generated_text_sha256": None, "generated_tokens_sha256": None,
        "candidate_count": 0, "partitions_checked": 0, "frontier": [],
        "producer_pins": implementation_pins(), "source_supplied": False,
        "expected_ast_supplied": False, "neural_forward_count": 0,
        "proof_authority": False, "execution_authority": False,
        "source_semantics_verified": False,
        "limitations": ["tokenizer_whitespace_is_lossy",
            "canonical_punctuation_inside_slots_only",
            "learned_forward_AST_and_complete_source_agreement_required",
            "bounded_existing_rich_grammar_only"]}
    if (type(generated_text) is not str or not 0 < len(generated_text) <= 4096
            or any(not 32 <= ord(char) <= 126 for char in generated_text)):
        report["frontier"].append("bounded_printable_ASCII_generated_text_required")
        return report
    report["generated_text_sha256"] = hashlib.sha256(generated_text.encode()).hexdigest()
    try:
        tokens = tuple(paired.tokenize(generated_text))
    except ValueError:
        report["frontier"].append("invalid_generated_token_sequence")
        return report
    if len(tokens) > MAX_TOKENS:
        report["frontier"].append("generated_token_bound_exceeded")
        return report
    report["generated_tokens_sha256"] = hashlib.sha256(_key(tokens).encode()).hexdigest()
    # One final period is the sentence terminator, as in the frozen source
    # grammar. Preserve its presence; never manufacture missing output tokens.
    terminal = bool(tokens and tokens[-1] == ".")
    body_tokens = tokens[:-1] if terminal else tokens
    candidates = {}

    def tick():
        report["partitions_checked"] += 1
        if report["partitions_checked"] > MAX_PARTITIONS:
            raise _BoundExceeded("generated_grammar_partition_bound_exceeded")

    def render(field):
        if not field or any(not _LEXICAL.fullmatch(token) for token in field):
            raise ValueError("lexical field required")
        return grammar._unspace(" ".join(field))

    def atoms(part):
        result = {}
        for index in range(1, len(part)):
            for modality, modal_text in grammar.MODALS.items():
                modal = tuple(modal_text.split())
                if part[index:index + len(modal)] != modal:
                    continue
                start = index + len(modal)
                for end in range(start + 1, len(part)):
                    tick()
                    try:
                        actor, action, object_ = render(part[:index]), render(part[start:end]), render(part[end:])
                        ast = grammar.validate_ast({"kind": "atom", "actor": actor, "action": action,
                            "object": object_, "modality": modality})
                        # The inverse must name its actor and modality; the
                        # actual frozen grammar enforces scope and referents.
                        text = grammar.ast_to_text(ast)[:-1]
                        if grammar.parse_instruction(text, normalized_inverse=True) != ast:
                            continue
                        if tuple(paired.tokenize(text)) != part:
                            continue
                        result[_key(ast)] = ast
                        if len(result) > MAX_CANDIDATES:
                            raise _BoundExceeded("generated_candidate_bound_exceeded")
                    except (ValueError, TypeError) as error:
                        if isinstance(error, _BoundExceeded):
                            raise
        return tuple(result.values())

    def retain(ast):
        tick()
        try:
            grammar.validate_ast(ast)
            text = grammar.ast_to_text(ast)
            if not terminal:
                text = text[:-1]
            if (grammar.parse_instruction(text, normalized_inverse=True) != ast
                    or tuple(paired.tokenize(text)) != tokens):
                return
            candidates[_key(ast)] = (text, ast)
            if len(candidates) > MAX_CANDIDATES:
                raise _BoundExceeded("generated_candidate_bound_exceeded")
        except (ValueError, TypeError) as error:
            if isinstance(error, _BoundExceeded):
                raise

    try:
        for ast in atoms(body_tokens):
            retain(ast)
        for index, token in enumerate(body_tokens):
            if token not in {"and", "or", "then"}:
                continue
            for left in atoms(body_tokens[:index]):
                for right in atoms(body_tokens[index + 1:]):
                    retain({"kind": token, "left": left, "right": right})
        if body_tokens and body_tokens[0] == "if":
            for is_index, token in enumerate(body_tokens):
                if token != "is" or is_index < 2:
                    continue
                for comma in range(is_index + 2, len(body_tokens)):
                    if body_tokens[comma] != ",":
                        continue
                    tick()
                    property_tokens = body_tokens[is_index + 1:comma]
                    negative = bool(property_tokens and property_tokens[0] == "not")
                    try:
                        guard = {"subject": render(body_tokens[1:is_index]),
                            "property": render(property_tokens[1:] if negative else property_tokens),
                            "negated": negative}
                        for atom in atoms(body_tokens[comma + 1:]):
                            retain({"kind": "if", "guard": guard, "body": atom})
                    except (ValueError, TypeError) as error:
                        if isinstance(error, _BoundExceeded):
                            raise
    except _BoundExceeded as error:
        report["candidate_count"] = len(candidates)
        report["frontier"].append(str(error))
        return report
    report["candidate_count"] = len(candidates)
    if len(candidates) == 1:
        report["text"], report["ast"] = next(iter(candidates.values()))
        report["status"] = "candidate"
        report["token_equivalent"] = True
    elif candidates:
        report["status"] = "ambiguous"
        report["frontier"].append("multiple_generated_grammar_interpretations")
    else:
        report["frontier"].append("no_complete_token_preserving_rich_interpretation")
    return report


__all__ = ["SCHEMA", "METHOD", "implementation_pins", "recover_generated_inverse"]
