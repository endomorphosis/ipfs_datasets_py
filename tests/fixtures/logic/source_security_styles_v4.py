"""Fresh authored Security groups; holdouts are generated only when requested."""
from __future__ import annotations

import hashlib

from ipfs_datasets_py.logic.formalization.autoencoder.security.source_style_augmentation_384 import (
    NUISANCE_VARIANTS, TEMPORARY_STYLES, render_source_style,
)
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression

SCHEMA = "authored-security-source-styles/v4"
NAMES = ("quota", "count", "score", "balance", "offset", "limit", "size")
OPERATORS = (("<", "<="), (">", ">="), ("==", "!="), ("+", "-"), ("*",))
FUNCTIONS = ("evaluate_bounds", "combine_inputs", "derive_value", "inspect_pair")


def split_for(i, j):
    return "test" if j == (i + 1) % 5 else "validation" if j == (i + 4) % 5 else "train"


def manifest():
    return dict(schema=SCHEMA, groups={"train": 21, "validation": 7, "test": 7},
        base_styles=[0, 1, 2, 3], augmented_styles=list(range(8)), validation_styles=list(range(8)),
        test_styles=list(range(8)), canary_styles=[8, 9, 10, 11],
        training_seed_count=84, base_training_count=336, added_training_variant_count=1008,
        combined_training_count=1344, validation_count=504, test_count=504, canary_count=112,
        augmentation_nuisance_variants=list(NUISANCE_VARIANTS),
        validation_and_test_temporary_nuisance_variants=list(NUISANCE_VARIANTS),
        canary_nuisance_variants=[0],
        split_unit="parameter_name_and_operator_family_including_polarity_function_and_style_variants",
        canary_groups_shared_with_test=True, real_world_corpus=False,
        known_vocabulary_recombination=True, prior_v3_test_used_for_fitting=False)


def rows(split, *, styles=None):
    if split not in ("train", "validation", "test", "canary"):
        raise ValueError("explicit supported split required")
    chosen = tuple(styles) if styles is not None else tuple(
        range(8, 12) if split == "canary" else range(4) if split == "train" else range(8))
    if not chosen or any(type(value) is not int or value not in range(12) for value in chosen
            ) or len(set(chosen)) != len(chosen):
        raise ValueError("explicit source styles required")
    result = []
    for i, name in enumerate(NAMES):
        for j, operators in enumerate(OPERATORS):
            if split_for(i, j) != ("test" if split == "canary" else split):
                continue
            for oi, operator in enumerate(operators):
                for fi, function in enumerate(FUNCTIONS[:4 // len(operators)]):
                    source = f"def {function}({name}: int, boundary: int) -> {'bool' if j < 3 else 'int'}:\n    return {name} {operator} boundary\n"
                    refs = ("expr:" + name, "expr:boundary")
                    target = dict(kind="program_expression", document=ProgramExpression("expr:result", "binary",
                        "boolean" if j < 3 else "integer", operand_ids=refs, evaluation_order=refs,
                        operator=operator, source_ref_ids=("source",)).to_dict())
                    for style in chosen:
                        variants = NUISANCE_VARIANTS if split in ("validation", "test") and style in TEMPORARY_STYLES else (0,)
                        for variant in variants:
                            text = render_source_style(source, style, variant)
                            result.append(dict(id=f"v4:security_ir:{i}:{j}:{oi}:{fi}:{style}:{variant}",
                                group_id=f"v4:security_ir:{i}:{j}", split=split, source_text=text,
                                target=target, wording_style=style, nuisance_variant=variant,
                                source_sha256=hashlib.sha256(text.encode()).hexdigest()))
    if len({row["id"] for row in result}) != len(result) or len({row["source_sha256"] for row in result}) != len(result):
        raise ValueError("source-style panel has duplicate identities or source bytes")
    return result
