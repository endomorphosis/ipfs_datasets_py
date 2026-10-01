"""Fresh source design checks; sealed formulas and predictions are never read."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import formula_holdout_curriculum as module

ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "tests/fixtures/logic/action_disjoint_holdout_curriculum.json"
FILE_SHA = "727899d48ba4c8ffc64f858b7c0a6998415b2e46db3dfaba8a7b96f1b4f8f78d"
MANIFEST_SHA = "2aca49ff8d1899b11d2af5b30e35b3446b7acb4676b1fb6b0884be938073f1bb"


def exclusions():
    return [row["text"] for filename in ("actor_composition_panel.json", "actor_composition_must_training.json",
                                         "legacy_teacher_distillation.json")
            for row in json.loads((ROOT / "tests/fixtures/logic" / filename).read_text())["rows"]]


def prepare(panel=None, **options):
    kwargs = {"excluded_source_texts": exclusions(), "expected_manifest_sha256": MANIFEST_SHA}
    kwargs.update(options)
    return module.prepare_curriculum(module.build_authored_panel() if panel is None else panel, **kwargs)


def test_fixture_and_canonical_manifest_pins_match_deterministic_sources():
    prepared = module.load_curriculum(FIXTURE, expected_file_sha256=FILE_SHA,
        expected_manifest_sha256=MANIFEST_SHA, excluded_source_texts=exclusions())
    assert prepared.manifest == module.build_authored_panel()
    assert prepared.manifest_sha256 == MANIFEST_SHA
    assert prepared.receipt["manifest_sha256"] == MANIFEST_SHA
    assert all(prepared.manifest[key] is False and prepared.receipt[key] is False for key in module.FALSE)
    assert prepared.receipt["compiler_label_consistency_checked"] is False
    assert prepared.receipt["target_vocabulary_coverage_checked"] is False


def test_actor_action_and_template_pairs_are_disjoint_and_submit_templates_co_locate():
    prepared = prepare()
    actions = {name: action for name, action, _ in module.TEMPLATES}
    seen_actions, seen_templates, seen_sources = set(), set(), set()
    for split, count, actors in (("training", 32, 8), ("tuning", 8, 7), ("sealed_evaluation", 8, 7)):
        rows = prepared.rows(split)
        assert len(rows) == count
        assert len({row["actor"] for row in rows}) == actors
        assert {row["norm_template_id"] for row in rows} == set(actions)
        action_pairs = {(row["actor"], actions[row["norm_template_id"]]) for row in rows}
        template_pairs = {(row["actor"], row["norm_template_id"]) for row in rows}
        sources = {row["text"].casefold() for row in rows}
        assert not seen_actions & action_pairs and not seen_templates & template_pairs and not seen_sources & sources
        seen_actions |= action_pairs
        seen_templates |= template_pairs
        seen_sources |= sources
    for actor in module.ACTORS:
        submit = [row for row in prepared.manifest["rows"] if row["actor"] == actor
                  and actions[row["norm_template_id"]] == "submit"]
        assert len(submit) == 2 and len({row["split"] for row in submit}) == 1
    assert prepared.receipt["splits"]["training"]["template_counts"] == {
        "report": 6, "deadline": 6, "prohibition": 5, "minimum": 5, "publication": 5, "review": 5}


def test_training_variants_never_expand_nontraining_sources():
    prepared = prepare()
    train = {row["id"]: row for row in prepared.rows("training")}
    variants = prepared.training_variants()
    assert len(variants) == 32
    assert {row["parent_id"] for row in variants} == set(train)
    for row in variants:
        parent = train[row["parent_id"]]
        assert row["split"] == "training"
        assert row["text"] == parent["text"].replace(" shall ", " must ")
        assert row["parent_source_sha256"] == hashlib.sha256(parent["text"].encode()).hexdigest()
        assert row["id"] == parent["id"] + "-must-v1"
    assert len(prepared.training_rows()) == 32
    assert len(prepared.training_rows(include_must=True)) == 64
    assert len(prepared.development_rows()) == 40
    assert len(prepared.development_rows(include_must=True)) == 72
    assert all(row["split"] != "sealed_evaluation" for row in prepared.development_rows(include_must=True))
    with pytest.raises(module.HoldoutCurriculumError, match="only training"):
        module._variants(prepared.rows("sealed_evaluation"))
    with pytest.raises(TypeError):
        prepared.rows("sealed_evaluation", include_must=True)


def test_rows_manifest_receipt_and_variants_are_copy_safe():
    prepared = prepare()
    prepared.manifest["rows"].clear()
    prepared.rows("training")[0]["text"] = "changed"
    prepared.training_variants()[0]["parent_id"] = "changed"
    prepared.receipt["splits"]["training"]["row_count"] = 1
    assert prepared.manifest_sha256 == MANIFEST_SHA
    assert len(prepared.rows("training")) == 32
    assert prepared.training_variants()[0]["parent_id"] == prepared.rows("training")[0]["id"]
    assert prepared.receipt["splits"]["training"]["row_count"] == 32


@pytest.mark.parametrize("partition", ["training", "tuning", "sealed_evaluation", "variant"])
def test_previously_exposed_base_or_variant_source_rejects_normalized_overlap(partition):
    prepared = prepare()
    row = prepared.training_variants()[0] if partition == "variant" else prepared.rows(partition)[0]
    normalized_alias = "  " + "\n ".join(row["text"].upper().split()) + " "
    with pytest.raises(module.HoldoutCurriculumError, match="earlier exposed"):
        prepare(excluded_source_texts=exclusions() + [normalized_alias])


@pytest.mark.parametrize("exposed", [[], None, [""], [1], ["x"] * 1025])
def test_earlier_exposure_list_is_required_and_bounded(exposed):
    with pytest.raises(module.HoldoutCurriculumError, match="exposed source"):
        prepare(excluded_source_texts=exposed)


@pytest.mark.parametrize("mutation", ["unknown_field", "row_field", "split", "source", "order", "authority", "authority_type"])
def test_consistently_rehashed_mutations_cannot_reinterpret_the_authored_version(mutation):
    panel = module.build_authored_panel()
    if mutation == "unknown_field":
        panel["formula_gold"] = []
    elif mutation == "row_field":
        panel["rows"][0]["target"] = {}
    elif mutation == "split":
        panel["rows"][0]["split"] = "training"
    elif mutation == "source":
        panel["rows"][0]["text"] += " Another duty."
    elif mutation == "order":
        panel["rows"].reverse()
    elif mutation == "authority":
        panel["qualified"] = True
    else:
        panel["admitted"] = 0
    with pytest.raises(module.HoldoutCurriculumError, match="differ from v1"):
        prepare(panel, expected_manifest_sha256=module.manifest_digest(panel))


@pytest.mark.parametrize("pin", [None, "invalid", "0" * 64, MANIFEST_SHA.upper()])
def test_explicit_parent_manifest_pin_rejects_missing_or_wrong_value(pin):
    with pytest.raises(module.HoldoutCurriculumError, match="SHA-256"):
        prepare(expected_manifest_sha256=pin)


@pytest.mark.parametrize("bad", [None, 1, "yes"])
def test_augmentation_switch_requires_boolean(bad):
    with pytest.raises(module.HoldoutCurriculumError, match="boolean"):
        prepare().development_rows(include_must=bad)


def test_file_hash_duplicate_keys_and_size_bound_are_checked(tmp_path):
    options = dict(expected_manifest_sha256=MANIFEST_SHA, excluded_source_texts=exclusions())
    with pytest.raises(module.HoldoutCurriculumError, match="file SHA-256"):
        module.load_curriculum(FIXTURE, expected_file_sha256="0" * 64, **options)
    duplicate = FIXTURE.read_bytes().replace(b'{', b'{"schema":"duplicate",', 1)
    path = tmp_path / "panel.json"
    path.write_bytes(duplicate)
    with pytest.raises(module.HoldoutCurriculumError, match="invalid source fixture JSON"):
        module.load_curriculum(path, expected_file_sha256=hashlib.sha256(duplicate).hexdigest(), **options)
    path.write_bytes(b" " * (module.MAX_BYTES + 1))
    with pytest.raises(module.HoldoutCurriculumError, match="bounded source fixture"):
        module.load_curriculum(path, expected_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **options)


def test_helper_imports_only_standard_library_and_defines_no_formula_gold():
    tree = ast.parse(Path(module.__file__).read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = {alias.name for node in imports if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in imports if isinstance(node, ast.ImportFrom)}
    assert names <= {"__future__", "collections", "dataclasses", "hashlib", "json", "pathlib", "re"}
    for row in prepare().manifest["rows"]:
        assert set(row) == {"id", "text", "actor", "norm_template_id", "split", "corpus"}
