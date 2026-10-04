"""Explicit source-only clause controls for bounded decoder diagnostics.

Targets are opaque payloads: this module neither reads them nor accepts reference
formulas or counts. Clause-only and order controls intentionally pair a paragraph
vector with different clause text; their execution receipts identify both sources.
These controls do not establish source fidelity, semantic validity, or admission.
"""
from copy import deepcopy
import hashlib
import json

from . import clause_source_context as context_owner


SCHEMA = "clause-source-control-execution/v1"
KINDS = ("conditioned", "source_shuffle", "cross_length_shuffle",
    "context_only_shuffle", "context_reverse", "context_rotate")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _assignments(rows, kind):
    """Use literal source segmentation, independently of target payloads."""
    ids = [row["id"] for row in rows]
    groups = {}
    for row in rows:
        groups.setdefault(len(row["source_text"].split("\n\n")), []).append(row["id"])
    for members in groups.values():
        members.sort()
    identity = dict(zip(ids, ids))
    if kind in ("source_shuffle", "context_only_shuffle"):
        _require(all(len(members) >= 2 for members in groups.values()),
            "within-source-length shuffle requires at least two rows in every stratum")
        context = {key: donor for members in groups.values()
            for key, donor in zip(members, members[1:] + members[:1])}
    elif kind == "cross_length_shuffle":
        _require(len(ids) == 48 and set(groups) == {1, 2, 4, 8}
            and all(len(members) == 12 for members in groups.values()),
            "cross-length shuffle requires twelve source rows at each length 1/2/4/8")
        order = [identity for length in (1, 2, 4, 8) for identity in groups[length]]
        context = {identity: order[(index + 12) % 48] for index, identity in enumerate(order)}
    else:
        context = identity.copy()
    paragraph = context.copy() if kind in ("source_shuffle", "cross_length_shuffle") else identity.copy()
    return identity, paragraph, context


def prepare_control(rows, contexts, kind):
    """Return independent row/context copies and auditable source assignments.

    ``rows`` retain the usual four-field decoder envelope. On a negative control,
    its ``source_text`` describes the effective clause context, which may differ
    from the text that produced its paragraph vector. The receipt preserves the
    original and paragraph source bindings; no implicit provenance exception is
    introduced into the strict context validator.
    """
    _require(type(kind) is str and kind in KINDS, "unsupported clause source control")
    _require(type(rows) is list and 0 < len(rows) <= 4096,
        "bounded nonempty control source rows required")
    _require(all(type(row) is dict and set(row) == {"id", "source_text", "input", "target_ids"}
        and type(row["id"]) is str and bool(row["id"])
        and type(row["source_text"]) is str for row in rows), "closed source rows required")
    ids = [row["id"] for row in rows]
    _require(len(set(ids)) == len(ids), "unique control source identities required")
    # Validate the original sources before choosing or applying any substitution.
    context_owner.validate_contexts(rows, contexts)
    original_assignment, paragraph_assignment, context_assignment = _assignments(rows, kind)
    by_id = {row["id"]: row for row in rows}
    actual_rows, actual_contexts, permutations, bindings = [], {}, {}, {}
    for row in rows:
        identity = row["id"]
        paragraph = by_id[paragraph_assignment[identity]]
        donor = by_id[context_assignment[identity]]
        descriptor = contexts[donor["id"]]
        width = len(descriptor["segments"])
        permutation = list(range(width))
        if kind == "context_reverse":
            permutation.reverse()
        elif kind == "context_rotate":
            permutation = permutation[1:] + permutation[:1]
        source, rebound = context_owner.rebind_context(descriptor, row_id=identity, order=permutation)
        if kind in ("source_shuffle", "cross_length_shuffle"):
            _require(row["input"] != paragraph["input"], "ineffective equal-vector source shuffle")
        if kind in ("source_shuffle", "cross_length_shuffle", "context_only_shuffle"):
            _require(row["source_text"] != source["source_text"], "ineffective equal-text context shuffle")
        # target_ids is copied as opaque data, without inspecting or deriving any
        # assignment, permutation, length, or generation input from its contents.
        actual = deepcopy(row)
        actual["input"] = deepcopy(paragraph["input"])
        actual["source_text"] = source["source_text"]
        actual_rows.append(actual)
        actual_contexts[identity] = rebound
        permutations[identity] = permutation
        bindings[identity] = dict(
            original_source_text=row["source_text"],
            original_source_sha256=_text_digest(row["source_text"]),
            paragraph_source_text=paragraph["source_text"],
            paragraph_source_sha256=_text_digest(paragraph["source_text"]),
            context_donor_source_sha256=_text_digest(donor["source_text"]),
            actual_context_source_text=source["source_text"],
            actual_context_source_sha256=_text_digest(source["source_text"]),
            original_input_sha256=_digest(row["input"]),
            actual_input_sha256=_digest(actual["input"]),
            original_context_sha256=_digest(contexts[identity]),
            donor_context_sha256=_digest(descriptor),
            actual_context_sha256=_digest(rebound),
            original_source_clause_count=len(row["source_text"].split("\n\n")),
            actual_context_clause_count=width,
            effective_context_change=source["source_text"] != row["source_text"],
            effective_paragraph_change=actual["input"] != row["input"],
        )
    context_owner.validate_contexts(actual_rows, actual_contexts)
    execution = dict(schema=SCHEMA, kind=kind,
        control=dict(kind=kind, source_assignment=context_assignment.copy()),
        source_assignment=context_assignment.copy(),
        original_source_assignment=original_assignment,
        paragraph_source_assignment=paragraph_assignment,
        context_source_assignment=context_assignment,
        context_permutation=permutations, source_bindings=bindings,
        provenance_breaking=kind != "conditioned", source_only=True,
        references_accepted=False, target_payloads_read=False,
        source_count_policy="literal_source_text_split_double_newline",
        original_contexts_sha256=_digest(contexts),
        actual_contexts_sha256=_digest(actual_contexts),
        conditioned_source_semantics_verified=False, admitted=False,
        qualified=False, lake_executed=False,
    )
    return actual_rows, actual_contexts, execution
