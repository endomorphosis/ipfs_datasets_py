"""Declared grouped interpretations retain modal scope and source provenance."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.autoformal import legal_coordination as compiler
from ipfs_datasets_py.logic.deontic.coordination import build_coordination_groups


def compiled(source, scope="modal_over_actions"):
    group, = build_coordination_groups(source, "source:fixture")
    declaration = compiler.interpretation_skeleton(group)
    declaration.update(modal_scope=scope, connective="inclusive_or",
                       binding_profile="universal_actor_predicate")
    return compiler.compile_coordination_group(group, declaration)


@pytest.mark.parametrize("modal", ["shall", "may", "shall not"])
def test_same_actor_groups_compile_both_declared_scopes(modal):
    source = f"The Secretary {modal} publish notice or {modal} retain records."
    wide = compiled(source)
    narrow = compiled(source, "disjunction_of_norms")
    assert wide["structure_compiled"] is narrow["structure_compiled"] is True
    assert wide["formula"] != narrow["formula"]
    assert wide["native_ast"] != narrow["native_ast"]
    for record in (wide, narrow):
        assert record["family_validation"]["passed"] is True
        assert record["native_validation"]["validator"] == "strict_native_reparse_and_exact_AST"
        assert record["source_semantics_verified"] is record["admitted"] is record["proof_ready"] is False
        assert record["requires_validation"] is True
        assert record["blockers"] == ["source_interpretation_unreviewed"]
        assert compiler.reconstruct_compiled_group(record) == source.rstrip(".")


def test_predicate_symbols_preserve_punctuation_collisions_and_mapping_order():
    record = compiled("The Clerk shall file a-b or shall file a b.")
    rows = record["mapping"]["action_symbols"]
    assert [row["text"] for row in rows] == ["file a-b", "file a b"]
    assert len({row["symbol"] for row in rows}) == 2
    assert [row["member_indices"] for row in rows] == [[0], [1]]


def test_source_identity_is_not_hidden_by_an_equal_formula():
    source = "The Clerk shall publish notice or shall retain records."
    records = []
    for identity in ("source:left", "source:right"):
        group, = build_coordination_groups(source, identity)
        declaration = compiler.interpretation_skeleton(group)
        declaration.update(modal_scope="modal_over_actions", connective="inclusive_or",
                           binding_profile="universal_actor_predicate")
        records.append(compiler.compile_coordination_group(group, declaration))
    assert records[0]["formula"] == records[1]["formula"]
    assert records[0]["group_id"] != records[1]["group_id"]
    assert records[0]["compilation_sha256"] != records[1]["compilation_sha256"]
    tampered = deepcopy(records[0])
    tampered["group"] = records[1]["group"]
    with pytest.raises(ValueError):
        compiler.reconstruct_compiled_group(tampered)


@pytest.mark.parametrize("choice", ["modal_scope", "connective", "binding_profile"])
def test_missing_choices_produce_no_partial_logical_target(choice):
    group, = build_coordination_groups("The Clerk shall publish notice or shall retain records.")
    declaration = compiler.interpretation_skeleton(group)
    declaration.update(modal_scope="modal_over_actions", connective="inclusive_or",
                       binding_profile="universal_actor_predicate")
    declaration[choice] = None
    record = compiler.compile_coordination_group(group, declaration)
    assert record["formula"] == ""
    assert record["native_ast"] is record["native_payload"] is None
    assert record["structure_compiled"] is False
    assert "group_interpretation_incomplete" in record["blockers"]
    assert record["proof_ready"] is False


@pytest.mark.parametrize("mutation", ["formula", "ast", "mapping", "lean", "ready", "extra"])
def test_resealed_compilation_cannot_replace_source_or_declared_structure(mutation):
    record = compiled("The Clerk shall publish notice or shall retain records.")
    if mutation == "formula":
        record["formula"] = "O(Publish(x))"
    elif mutation == "ast":
        record["native_ast"] = {"node_type": "Predicate", "name": "Forged", "arguments": []}
    elif mutation == "mapping":
        record["mapping"]["action_symbols"][0]["text"] = "withhold notice"
    elif mutation == "lean":
        record["lean_body"] = "def formula_0 := True"
    elif mutation == "ready":
        record["proof_ready"] = record["source_semantics_verified"] = True
    else:
        record["semantic_approval"] = True
    record.pop("compilation_sha256")
    record["compilation_sha256"] = compiler.digest(record)
    with pytest.raises(ValueError):
        compiler.reconstruct_compiled_group(record)
