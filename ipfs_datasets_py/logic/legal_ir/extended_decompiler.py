"""Deterministic source-withheld realization of the opt-in surface IR.

This controlled legal language preserves every literal slot and statement kind.
It interprets no opaque clause, quantifier, calendar, definition applicability or
statutory meaning. The measured canonical v1 realizer remains a separate owner.
"""
from __future__ import annotations

import json

from .extended_contracts import DefinitionV2, ExtendedLegalIR, NormV2, PolicyV2

EXTENDED_REALIZER_PROFILE = "source-withheld-quoted-legal-clauses/v2"
MAX_RENDERED_UTF8_BYTES = 1024 * 1024


def decompile_extended(ir: ExtendedLegalIR) -> str:
    """Render the complete typed value, or refuse without truncating clauses.

    Only the supplied semantic slots enter the output. No source, receipt,
    identity, cache, model or original-wording channel is accepted. Collection
    order and duplicates remain visible; clause lists do not invent logical
    conjunction/disjunction or decide the applicability of a definition.
    """
    if type(ir) is not ExtendedLegalIR:
        raise ValueError("typed extended IR required")
    ExtendedLegalIR.__post_init__(ir)
    parts, size = [], 0

    def write(value):
        nonlocal size
        try:
            size += len(value.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("extended realization requires valid UTF-8 literals") from error
        if size > MAX_RENDERED_UTF8_BYTES:
            raise ValueError("complete extended realization exceeds UTF-8 byte bound; truncation refused")
        parts.append(value)

    def atom(value):
        write(json.dumps(value, ensure_ascii=False))

    def atoms(values):
        for index, value in enumerate(values):
            if index:
                write("; ")
            atom(value)

    for index, statement in enumerate(ir.statements):
        if index:
            write("\n")
        if type(statement) is NormV2:
            write("Norm: ")
            atom(statement.actor)
            write(" " + {"O": "must", "P": "may", "F": "must not"}[statement.modality] + " ")
            atom(statement.action)
            write(" ")
            atom(statement.object)
        elif type(statement) is DefinitionV2:
            write("Definition: ")
            atom(statement.term)
            write(" " + statement.relation + " ")
            atom(statement.meaning)
        elif type(statement) is PolicyV2:
            write("Policy: ")
            atom(statement.authority)
            write(" " + {"supports": "supports", "declares_policy": "declares as policy"}[statement.stance] + " ")
            atoms(statement.objectives)
        else:
            raise ValueError("unsupported extended statement type")
        write(".")
        for field, label in (("scope", "Scope"), ("conditions", "Conditions"),
                             ("exceptions", "Exceptions"), ("temporal", "Temporal")):
            values = getattr(statement, field)
            if values:
                write(" " + label + ": ")
                atoms(values)
                write(".")
    return "".join(parts)
