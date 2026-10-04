"""Bounded source-style training augmentation for checked binary expressions.

No targets are inferred or repaired. Each source variant must independently
qualify against the supplied, unchanged training target. Group lineage survives
augmentation; embedding and numerical fitting remain separate shared stages.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib

from . import source_program_binding_384 as source_contract
from .source_program_binding_384_v2 import qualify_source_candidate

SCHEMA = "security-source-style-augmentation-384/v1"
FIELDS = {"id", "group_id", "split", "source_text", "target"}
TRAINING_STYLES = (4, 5, 6, 7)
NUISANCE_VARIANTS = (0, 1, 2)
TEMPORARY_STYLES = (2, 3, 5, 6, 7, 9, 10, 11)
TEMPORARY_NAMES = ("outcome", "scratch_value", "intermediate_result")


def render_source_style(source_text, style, nuisance_variant=0):
    """Render one explicit authored style without changing the binary operation.

    This formatter accepts just a two-parameter, directly returned binary or
    comparison expression. It is a training utility, never a decoder fallback.
    The augmentation API independently checks each new source/target pair.
    """
    if type(style) is not int or style not in range(12):
        raise ValueError("explicit supported source style required")
    if type(nuisance_variant) is not int or nuisance_variant not in NUISANCE_VARIANTS:
        raise ValueError("explicit supported nuisance variant required")
    if type(source_text) is not str or not 0 < len(source_text.encode()) <= 16384:
        raise ValueError("bounded source required")
    # Reuse the exact source grammar and declared-type checks. This utility
    # never expands the accepted source language or interprets new operators.
    function, _, _, _, _, _, _ = source_contract._guard(source_text)
    if len(function.body) != 1:
        raise ValueError("direct binary return seed required")
    canonical = ast.unparse(function)
    header = canonical.splitlines()[0] + "\n"
    expression = ast.unparse(function.body[0].value)
    # Choose a fresh local symbol without altering either operand identifier.
    used = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
    # The nuisance name is independent of layout/comment style. Every training
    # style crosses all three choices instead of teaching one name per style.
    local = TEMPORARY_NAMES[nuisance_variant]
    while local in used:
        local += "_local"
    multiline_return = (
        f"    return (\n        {expression}\n    )\n",
        f"    # Evaluate the expression before returning its value.\n    return (\n        {expression}\n    )\n",
        f"    return (\n        {expression}  # Preserve the expression value.\n    )\n",
    )[nuisance_variant]
    bodies = (
        f"    return {expression}\n",
        f"    # Evaluate the requested expression.\n    return ({expression})\n",
        f"    {local} = {expression}\n    return {local}\n",
        f"    # Keep the computed value.\n    {local} = ({expression})\n    return {local}\n",
        multiline_return,
        f"\t{local} = ( {expression} )\n\t# Return the intermediate value unchanged.\n\treturn {local}\n",
        f"    {local} = (\n        {expression}\n    )\n    # Carry this result to the caller.\n    return {local}\n",
        f"    # The variable holds the result for subsequent return.\n    {local} = {expression}\n\n    # No further updates are needed.\n    return ({local})\n",
        f"    return (  # Preserve the expression value.\n        ({expression})\n    )\n",
        f"    {local} = {expression}; return {local}\n",
        f"\t# Compute the value once.\n\t{local} = (\n\t    {expression}\n\t)\n\treturn ({local})\n",
        f"    {local} = ({expression})\n    # Supply the calculated result to the caller.\n    # This concludes the computation.\n    return {local}\n",
    )
    result = header + bodies[style]
    ast.parse(result)
    return result


def augment_training_sources(rows, *, styles=TRAINING_STYLES, nuisance_variants=NUISANCE_VARIANTS):
    """Return only new variants; reject tuning/test inputs and altered labels."""
    if type(rows) is not list or not 1 <= len(rows) <= 256:
        raise ValueError("one to 256 training seeds required")
    if type(styles) not in (tuple, list) or not styles or any(
            type(style) is not int or style not in TRAINING_STYLES for style in styles
            ) or len(set(styles)) != len(styles):
        raise ValueError("explicit unique training styles required")
    if type(nuisance_variants) not in (tuple, list) or not nuisance_variants or any(
            type(value) is not int or value not in NUISANCE_VARIANTS for value in nuisance_variants
            ) or len(set(nuisance_variants)) != len(nuisance_variants):
        raise ValueError("explicit unique training nuisance variants required")
    if any(type(row) is not dict or set(row) != FIELDS or row["split"] != "train"
            or type(row["id"]) is not str or not 0 < len(row["id"]) <= 160
            or not row["id"].strip() or type(row["group_id"]) is not str
            or not 0 < len(row["group_id"]) <= 512 or not row["group_id"].strip() for row in rows):
        raise ValueError("closed train-only seed rows required")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate training seed identity")
    results, bindings, seen = [], [], set()
    identities = {row["id"] for row in rows}
    seed_sources = set()
    for seed in rows:
        if type(seed["source_text"]) is not str:
            raise ValueError("training seed source text required")
        sha = hashlib.sha256(seed["source_text"].encode()).hexdigest()
        if sha in seed_sources:
            raise ValueError("duplicate training seed source")
        seed_sources.add(sha)
    for seed in rows:
        if qualify_source_candidate(seed["source_text"], seed["target"])["status"] != "qualified":
            raise ValueError("training seed source/target mismatch or unsupported source")
        for style in styles:
            for variant in nuisance_variants:
                text = render_source_style(seed["source_text"], style, variant)
                if qualify_source_candidate(text, seed["target"])["status"] != "qualified":
                    raise ValueError("augmentation did not preserve checked source target")
                sha = hashlib.sha256(text.encode()).hexdigest()
                if sha in seen or sha in seed_sources:
                    raise ValueError("duplicate augmented source or original source reused")
                seen.add(sha)
                row = {**deepcopy(seed), "id": seed["id"] + ":style-" + str(style)
                    + ":nuisance-" + str(variant), "source_text": text}
                if row["id"] in identities:
                    raise ValueError("augmented identity collides with a training seed or variant")
                identities.add(row["id"])
                results.append(row)
                bindings.append(dict(id=row["id"], parent_id=seed["id"], group_id=seed["group_id"],
                    style=style, nuisance_variant=variant, source_sha256=sha,
                    parent_source_sha256=hashlib.sha256(seed["source_text"].encode()).hexdigest()))
    return dict(rows=results, report=dict(schema=SCHEMA, seed_count=len(rows), variant_count=len(results),
        styles=list(styles), nuisance_variants=list(nuisance_variants),
        temporary_names_independent_of_style=True, bindings=bindings, targets_changed=False, group_ids_changed=False,
        validation_or_test_used=False, embedding_generated=False, proof_authority=False,
        source_semantics_verified=False, scope="independent narrow AST/typed-expression source checks; not full Python equivalence"))


__all__ = ["augment_training_sources", "render_source_style"]
