"""Source-independent prefix languages for the frozen rich Intent codec.

These constraints have no source instruction, expected AST, or semantic slot
values. They prune syntax only. Complete predictions still require independent
source agreement, a genuine learned inverse, and scoped logic projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from . import rich_grammar as grammar
from .rich_decoder import sha

POLICY_ID = "intent-rich-generated-prefix-grammar/v1"
_LEXICAL = re.compile(r"(?:[A-Za-z0-9_]+|[./:`-])\Z")


@dataclass(frozen=True)
class Field:
    name: str


@dataclass(frozen=True)
class Choice:
    tokens: frozenset


def _field_possible(field, tokens, *, complete):
    if not tokens:
        return not complete
    if field.name == 'modal':
        options = [tuple(value.split()) for value in grammar.MODALS.values()]
        return tuple(tokens) in options if complete else any(tuple(tokens) == value[:len(tokens)] for value in options)
    if len(tokens) > 160 or any(not _LEXICAL.fullmatch(token) for token in tokens):
        return False
    value = grammar._unspace(" ".join(tokens))
    if field.name in {"action", "property"}:
        expression = r"[a-z][a-z0-9_-]*" if field.name == "action" else grammar._ATOM
        if not re.fullmatch(expression, value):
            return False
        if complete and field.name == "property":
            return value.lower() not in grammar._GRAMMAR_WORDS | grammar._UNSUPPORTED | grammar._REFERENCES
        return True
    if not complete:
        # A future closing backtick can change whitespace normalization, so
        # field word/character bounds are enforced when crossing its boundary.
        return len(value) <= 164
    try:
        grammar._slot(value, words=16 if field.name == "object" else 4)
        return True
    except ValueError:
        return False


def _patterns(direction):
    actor, action, object_, subject, property_ = map(Field, ("actor", "action", "object", "subject", "property"))
    if direction == "encode":
        atoms = [("<actor>", actor, "<action>", action, "<object>", object_, "<modality>", Choice(frozenset(grammar.MODALS)))]
        patterns = list(atoms)
        patterns += [(f"<{kind}>", *left, "<next>", *right)
                     for kind in ("and", "or", "then") for left in atoms for right in atoms]
        patterns += [("<if>", subject, "<property>", property_, "<polarity>", Choice(frozenset({'positive','negative'})), "<body>", *body)
                     for body in atoms]
        return tuple(patterns)
    if direction == "decode":
        atoms = [(actor, Field('modal'), action, object_)]
        bodies = list(atoms)
        bodies += [(*left, kind, *right) for kind in ("and", "or", "then") for left in atoms for right in atoms]
        bodies += [("if", subject, "is", *negative, property_, ",", *body)
                   for negative in ((), ("not",)) for body in atoms]
        return tuple(pattern for body in bodies for pattern in (body, (*body, ".")))
    raise ValueError("paired direction required for rich prefix grammar")


class RichPrefixConstraint:
    """Finite set of bounded production patterns, with cached prefix states."""

    def __init__(self, direction):
        self.direction = direction
        self.patterns = _patterns(direction)
        self._cached_states = lru_cache(maxsize=8192)(self._states)

    def _closure(self, states):
        result = set(states)
        pending = list(result)
        while pending:
            pattern_id, index, buffer = pending.pop()
            pattern = self.patterns[pattern_id]
            if (index < len(pattern) and isinstance(pattern[index], Field)
                    and _field_possible(pattern[index], buffer, complete=True)):
                following = (pattern_id, index + 1, ())
                if following not in result:
                    result.add(following)
                    pending.append(following)
        return frozenset(result)

    def _states(self, prefix):
        if not prefix:
            return self._closure((index, 0, ()) for index in range(len(self.patterns)))
        previous = self._cached_states(prefix[:-1])
        token = prefix[-1]
        result = set()
        for pattern_id, index, buffer in previous:
            pattern = self.patterns[pattern_id]
            if index == len(pattern):
                continue
            part = pattern[index]
            if isinstance(part, Field):
                extended = (*buffer, token)
                if _field_possible(part, extended, complete=False):
                    result.add((pattern_id, index, extended))
            elif (token in part.tokens if isinstance(part, Choice) else token == part):
                result.add((pattern_id, index + 1, ()))
        return self._closure(result)

    def __call__(self, prefix, *, eos=False):
        if (type(prefix) is not tuple or len(prefix) > 160 or type(eos) is not bool
                or any(type(token) is not str for token in prefix)):
            return False
        states = self._cached_states(prefix)
        if not eos:
            return bool(states)
        if not any(index == len(self.patterns[pattern_id]) for pattern_id, index, _ in states):
            return False
        try:
            if self.direction == "encode":
                grammar.sequence_to_ast(" ".join(prefix))
            else:
                text = re.sub(r"\s+,", ",", grammar._unspace(" ".join(prefix)))
                grammar.parse_instruction(text, normalized_inverse=True)
            return True
        except (ValueError, TypeError):
            return False


def policy_identity():
    return {"policy_id": POLICY_ID, "policy_sha256": sha(Path(__file__).read_bytes())}
