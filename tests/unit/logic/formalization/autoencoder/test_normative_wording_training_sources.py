"""Pure complete-bank controls; no encoder, fit, semantic review or proof run."""
from collections import Counter
from copy import deepcopy
import json
import random

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import normative_wording_training_sources as subject
from ipfs_datasets_py.logic.formalization.autoencoder import training_paraphrase_source_inputs as sources


def inputs():
    base = subject.base
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=list(base.VOCABULARY))
    rows = []
    for offset in range(3):
        for index, actor in enumerate(base.ACTORS):
            action = base.ACTIONS[(index + offset) % len(base.ACTIONS)]
            for obj in base.OBJECTS:
                for modality in base.MODALITIES:
                    target = {"rules": [dict(actor=actor, action=action, object=obj,
                                           modality=modality, conditions=[], exceptions=[], temporal=[])]}
                    for style in range(2):
                        modal = ({"O": "must", "P": "may", "F": "must not"} if style == 0 else
                                 {"O": "is required to", "P": "is allowed to", "F": "is forbidden to"})[modality]
                        rows.append(dict(id="synthetic-train:" + str(len(rows)),
                                         source_text=f"The {actor} {modal} {action} the {obj}.",
                                         target_ids=base._encode(target, codec)))
    inventories = {name: [dict(id=f"synthetic-exclusion:{name}:{index}",
                              source_text=f"Excluded source {name} number {index}.") for index in range(count)]
                   for name, count in subject.REQUIRED_PRIOR_COUNTS.items()}
    inventories["original_train_bank"] = [{k: row[k] for k in ("id", "source_text")} for row in rows]
    return dict(training_bank=rows, prior_sources_by_dataset=inventories, codec=codec,
                sealed_recipe_sha256="a" * 64,
                validate_rule=lambda target: dict(valid=True, canonical_ir=target))


def test_complete_targets_immutable_roles_and_separate_producer_inputs():
    args = inputs()
    before = deepcopy(args)
    result = subject.build(**args)
    assert args == before
    assert set(result) == {"source_rows", "references", "clause_references", "receipt"}
    assert len(result["source_rows"]) == len(result["references"]) == 48
    assert len(result["clause_references"]) == 180
    original = {}
    for row in args["training_bank"]:
        target = json.loads("".join(args["codec"]["target_vocabulary"][i] for i in row["target_ids"][1:-1]))
        original.setdefault(subject.digest(target["rules"][0]), []).append(row)
    clauses = {row["id"]: row for row in result["clause_references"]}
    uses, modes, actors, actions, objects = (Counter() for _ in range(5))
    for source, ref in zip(result["source_rows"], result["references"]):
        assert set(source) == {"id", "source_text"}
        assert source["id"] == ref["id"] and source["source_text"] == ref["source_text"]
        assert ref["source_sha256"] == subject.text_sha(source["source_text"])
        assert ref["split"] == "train_augmentation"
        assert len(source["source_text"].split("\n\n")) == ref["clause_count"]
        assert len(ref["clause_ids"]) == len(ref["target"]["rules"]) == len(ref["derivations"]) == ref["clause_count"]
        assert subject.base._encode(ref["target"], args["codec"]) == ref["target_ids"]
        assert ref["target_ids_sha256"] == subject.digest(ref["target_ids"])
        assert ref["target_sha256"] == subject.digest(ref["target"])
        groups = [tuple(rule[k] for k in ("actor", "action", "object")) for rule in ref["target"]["rules"]]
        assert len(groups) == len(set(groups))
        for slot, (text, rule, clause_id, derivation) in enumerate(zip(
                source["source_text"].split("\n\n"), ref["target"]["rules"], ref["clause_ids"], ref["derivations"])):
            clause = clauses[clause_id]
            key = subject.digest(rule)
            assert key in original and len(original[key]) == 2
            assert text == subject.sentence(ref["template"], rule)
            assert clause["parent_paragraph_id"] == source["id"] and clause["slot"] == slot
            assert clause["source_text"] == text and clause["source_sha256"] == subject.text_sha(text)
            assert clause["target"] == {"rules": [rule]}
            assert clause["target_ids"] == subject.base._encode(clause["target"], args["codec"])
            assert clause["original_rule_sha256"] == key == derivation["rule_sha256"]
            assert clause["derivations"] == [derivation]
            expected = [dict(id=row["id"], source_sha256=subject.text_sha(row["source_text"]),
                             target_sha256=subject.digest({"rules": [rule]}),
                             target_ids_sha256=subject.digest(row["target_ids"])) for row in original[key]]
            assert derivation["original_train_sources"] == expected
            assert clause["modality_stratum"] == rule["modality"]
            assert all(rule[k] == [] for k in ("conditions", "exceptions", "temporal"))
            assert all(clause[k] is False and ref[k] is False for k in subject.FALSE)
            uses[key] += 1
            modes[rule["modality"]] += 1
            actors[rule["actor"]] += 1
            actions[rule["action"]] += 1
            objects[rule["object"]] += 1
    assert len(uses) == 90 and set(uses.values()) == {2}
    assert modes == dict.fromkeys(subject.base.MODALITIES, 60)
    assert actors == dict.fromkeys(subject.base.ACTORS, 36)
    assert actions == dict.fromkeys(subject.base.ACTIONS, 36)
    assert objects == dict.fromkeys(subject.base.OBJECTS, 90)
    plan = sources.source_plan(result["source_rows"],
                               expected_source_rows_sha256=result["receipt"]["source_rows_sha256"],
                               sealed_recipe_sha256=args["sealed_recipe_sha256"])
    assert sources._plan(plan) == plan
    assert plan["shape_plan"]["unique_sources"] == 216
    assert plan["shape_plan"]["clause_occurrences"] == 180
    assert plan["shape_plan"]["encoder_context_tokens"] == 512
    assert plan["target_access"] is False and plan["targets_attached"] is False
    assert all(set(row) == {"id", "source_text"} for row in plan["shape_plan"]["source_inputs"])


@pytest.mark.parametrize("template", subject.TEMPLATES)
def test_exact_normative_renderings_and_empty_qualifier_contract(template):
    base = dict(actor="registrar", action="approve", object="notice", conditions=[], exceptions=[], temporal=[])
    expected = {
        "explicit_actor_status_v1": (
            "Under this regulation, the registrar is obliged to approve the notice.",
            "Under this regulation, the registrar is authorized to approve the notice.",
            "Under this regulation, the registrar is prohibited from approving the notice."),
        "regulation_norm_operator_v1": (
            "This regulation places a duty on the registrar to approve the notice.",
            "This regulation grants the registrar permission to approve the notice.",
            "This regulation bans the registrar from approving the notice."),
    }
    for modality, wanted in zip(subject.base.MODALITIES, expected[template]):
        rule = dict(base, modality=modality)
        before = deepcopy(rule)
        assert subject.sentence(template, rule) == wanted
        assert rule == before


def test_fixed_packing_order_complete_strata_and_process_rng_preserved():
    args = inputs()
    state = random.getstate()
    first = subject.build(**args)
    assert random.getstate() == state
    assert subject.build(**args) == first
    assert Counter(ref["clause_count"] for ref in first["references"]) == {1: 12, 2: 12, 4: 12, 8: 12}
    for template in subject.TEMPLATES:
        refs = [ref for ref in first["references"] if ref["template"] == template]
        assert [ref["clause_count"] for ref in refs] == [1] * 6 + [2] * 6 + [4] * 6 + [8] * 6
        assert [ref["index_within_template_length"] for ref in refs] == list(range(6)) * 4
        flattened = [rule for ref in refs for rule in ref["target"]["rules"]]
        assert len(flattened) == 90 and len({subject.digest(rule) for rule in flattened}) == 90
        assert Counter(rule["modality"] for rule in flattened) == {"O": 30, "P": 30, "F": 30}
        groups = [tuple(rule[k] for k in ("actor", "action", "object")) for rule in flattened]
        assert groups[:30] == groups[30:60] == groups[60:90]
        for position in range(30):
            assert {flattened[position + round_ * 30]["modality"] for round_ in range(3)} == {"O", "P", "F"}
    receipt = first["receipt"]
    assert receipt["original_train_bank_sha256"] == subject.digest(args["training_bank"])
    assert receipt["source_rows_sha256"] == subject.digest(first["source_rows"])
    assert receipt["references_sha256"] == subject.digest(first["references"])
    assert receipt["clause_references_sha256"] == subject.digest(first["clause_references"])
    assert receipt["receipt_sha256"] == subject.digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    assert all(receipt[k] is False for k in subject.FALSE)


@pytest.mark.parametrize("dataset", subject.REQUIRED_PRIOR_DATASETS[1:] + ("future_development",))
@pytest.mark.parametrize("mode", ("literal_clause", "normalized_clause", "literal_paragraph", "normalized_paragraph"))
def test_every_named_prior_scope_rejects_clause_and_paragraph_overlap(dataset, mode):
    args = inputs()
    built = subject.build(**args)
    ref = next(ref for ref in built["references"] if ref["clause_count"] == 4)
    text = ref["source_text"] if "paragraph" in mode else ref["source_text"].split("\n\n")[2]
    if mode.startswith("normalized"):
        text = text.upper().replace(" ", "  ").replace("\n\n", "\n \n")
    if dataset in args["prior_sources_by_dataset"]:
        args["prior_sources_by_dataset"][dataset][0] = dict(id="colliding-prior", source_text=text)
    else:
        args["prior_sources_by_dataset"][dataset] = [dict(id="colliding-prior", source_text=text)]
    with pytest.raises(ValueError, match="overlaps prior"):
        subject.build(**args)


@pytest.mark.parametrize("dataset", subject.REQUIRED_PRIOR_DATASETS)
def test_mandatory_exclusion_inventory_cannot_be_omitted(dataset):
    args = inputs()
    del args["prior_sources_by_dataset"][dataset]
    with pytest.raises(ValueError, match="all ten R4"):
        subject.build(**args)


@pytest.mark.parametrize("dataset", subject.REQUIRED_PRIOR_DATASETS)
def test_prior_scope_cannot_be_nominal_or_incomplete(dataset):
    args = inputs()
    args["prior_sources_by_dataset"][dataset].pop()
    with pytest.raises(ValueError, match="no partial exclusion corpus"):
        subject.build(**args)


@pytest.mark.parametrize("field", ("conditions", "exceptions", "temporal"))
def test_qualifier_refusal_is_explicit_in_renderer_and_complete_bank(field):
    args = inputs()
    target = json.loads("".join(subject.base.VOCABULARY[i] for i in args["training_bank"][0]["target_ids"][1:-1]))
    target["rules"][0][field] = ["notice"]
    with pytest.raises(ValueError, match="no dropped qualifier"):
        subject.sentence(subject.TEMPLATES[0], target["rules"][0])
    args["training_bank"][0]["target_ids"] = subject.base._encode(target, args["codec"])
    with pytest.raises(ValueError, match="no dropped qualifier"):
        subject.build(**args)


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "boolean_token", "unknown_token", "noncanonical",
                                        "extra_label_field", "unbalanced", "codec", "validator", "mutating_validator"))
def test_incompatible_bank_never_selects_or_repairs_a_subset(mutation):
    args = inputs()
    if mutation == "missing":
        args["training_bank"].pop()
    elif mutation == "duplicate":
        args["training_bank"][1] = deepcopy(args["training_bank"][0])
    elif mutation == "boolean_token":
        args["training_bank"][0]["target_ids"][0] = True
    elif mutation == "unknown_token":
        args["training_bank"][0]["target_ids"][3] = 32
    elif mutation == "noncanonical":
        ids = args["training_bank"][0]["target_ids"]
        # Parseable rule with its final two empty-field keys swapped.
        ids[22], ids[32] = ids[32], ids[22]
    elif mutation == "extra_label_field":
        args["training_bank"][0]["target"] = {"rules": []}
    elif mutation == "unbalanced":
        args["training_bank"][0]["target_ids"] = list(args["training_bank"][4]["target_ids"])
    elif mutation == "codec":
        args["codec"]["target_vocabulary"].pop()
    elif mutation == "validator":
        args["validate_rule"] = lambda value: dict(valid=False)
    else:
        def mutate(value):
            value["rules"][0]["modality"] = "F"
            return dict(valid=True, canonical_ir=value)
        args["validate_rule"] = mutate
    with pytest.raises(ValueError):
        subject.build(**args)


@pytest.mark.parametrize("seed", (True, 1729, 20261007, "20261006", 20261006.0))
def test_sealed_seed_cannot_be_changed(seed):
    with pytest.raises(ValueError, match="fixed nonboolean"):
        subject.build(**inputs(), seed=seed)


def test_named_original_bank_and_source_only_exclusions_are_exact():
    args = inputs()
    args["prior_sources_by_dataset"]["original_train_bank"][0]["source_text"] += " "
    with pytest.raises(ValueError, match="source inventory differs"):
        subject.build(**args)
    args = inputs()
    args["prior_sources_by_dataset"]["exposed_v3"][0]["target"] = {"rules": []}
    with pytest.raises(ValueError, match="source-only row"):
        subject.build(**args)


def test_prior_identity_conflicts_refused_even_when_text_differs():
    args = inputs()
    built = subject.build(**args)
    identity = built["clause_references"][0]["id"]
    args["prior_sources_by_dataset"]["future_development"] = [dict(id=identity, source_text="A different source.")]
    with pytest.raises(ValueError, match="clause identity overlaps"):
        subject.build(**args)


def test_generated_collision_aborts_complete_generation(monkeypatch):
    args = inputs()
    render = subject.sentence
    monkeypatch.setattr(subject, "sentence", lambda template, rule: render(subject.TEMPLATES[0], rule))
    with pytest.raises(ValueError, match="generated source"):
        subject.build(**args)
