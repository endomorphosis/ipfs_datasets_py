"""Opt-in controlled-language compiler for the existing legal surface IR.

Only the complete quoted-clause profile is supported. General source prose,
partial matches and mixed residue abstain; a definition or policy is never
promoted to an obligation. Literal clauses remain uninterpreted atoms.
"""
from __future__ import annotations

import json

from .extended_contracts import DefinitionV2, ExtendedLegalIR, MAX_STATEMENTS, NormV2, PolicyV2
from .extended_decompiler import MAX_RENDERED_UTF8_BYTES


class _ClauseReader:
    def __init__(self, text):
        self.text, self.position = text, 0
        self.decoder = json.JSONDecoder()

    def starts(self, literal):
        return self.text.startswith(literal, self.position)

    def take(self, literal):
        if not self.starts(literal):
            raise ValueError("unsupported controlled-language boundary")
        self.position += len(literal)

    def atom(self):
        if not self.starts('"'):
            raise ValueError("quoted literal required")
        value, self.position = self.decoder.raw_decode(self.text, self.position)
        return value

    def atoms(self):
        values = [self.atom()]
        while self.starts("; "):
            if len(values) >= MAX_STATEMENTS:
                raise ValueError("clause collection exceeds bound")
            self.take("; ")
            values.append(self.atom())
        return tuple(values)

    def choice(self, spellings):
        for literal, value in spellings:
            if self.starts(literal):
                self.take(literal)
                return value
        raise ValueError("unknown statement operator")


def _statement(text):
    reader = _ClauseReader(text)
    if reader.starts("Norm: "):
        reader.take("Norm: ")
        actor = reader.atom()
        modality = reader.choice(((" must not ", "F"), (" must ", "O"), (" may ", "P")))
        action = reader.atom()
        reader.take(" ")
        values, kind = dict(modality=modality, actor=actor, action=action, object=reader.atom()), NormV2
    elif reader.starts("Definition: "):
        reader.take("Definition: ")
        term = reader.atom()
        relation = reader.choice(tuple((" " + word + " ", word) for word in ("means", "includes", "excludes")))
        values, kind = dict(term=term, relation=relation, meaning=reader.atom()), DefinitionV2
    elif reader.starts("Policy: "):
        reader.take("Policy: ")
        authority = reader.atom()
        stance = reader.choice(((" supports ", "supports"), (" declares as policy ", "declares_policy")))
        values, kind = dict(authority=authority, stance=stance, objectives=reader.atoms()), PolicyV2
    else:
        raise ValueError("unsupported statement kind")
    reader.take(".")
    for field, label in (("scope", "Scope"), ("conditions", "Conditions"),
                         ("exceptions", "Exceptions"), ("temporal", "Temporal")):
        prefix = " " + label + ": "
        if reader.starts(prefix):
            reader.take(prefix)
            values[field] = reader.atoms()
            reader.take(".")
    if reader.position != len(text):
        raise ValueError("unconsumed or out-of-order source clauses")
    return kind(**values)


def compile_extended(text: str) -> ExtendedLegalIR | None:
    """Compile the whole supported controlled span; otherwise abstain.

    This is a deterministic literal-slot inverse, not a general legal-language
    interpreter or a reviewed source-correspondence judgment. No clause is
    inferred from a reference target, source-bearing cache or proof outcome.
    """
    if type(text) is not str or not text.strip():
        raise ValueError("source must be nonempty text")
    if len(text) > MAX_RENDERED_UTF8_BYTES:
        return None
    try:
        if len(text.encode("utf-8")) > MAX_RENDERED_UTF8_BYTES:
            return None
        lines = text.split("\n", MAX_STATEMENTS)
        if len(lines) > MAX_STATEMENTS:
            return None
        return ExtendedLegalIR(tuple(_statement(line) for line in lines))
    except (ValueError, UnicodeError, RecursionError):
        return None
