"""Pure tests for fixed mixed layouts, copy geometry and deferred references."""
import ast
from collections import Counter
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import re

import pytest

from ipfs_datasets_py.logic.legal_ir import targeted_loss_curriculum as subject


@pytest.fixture(scope="module")
def cached_export():
    name = os.environ.get("TARGETED_LOSS_PRIOR_EXPORT") or os.environ.get("MATCHED_CURRICULUM_PRIOR_EXPORT")
    if not name:
        pytest.skip("set TARGETED_LOSS_PRIOR_EXPORT to the immutable prior authored export")
    raw = Path(name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == subject.PRIOR_EXPORT_FILE_SHA256
    return json.loads(raw)


@pytest.fixture(scope="module")
def curriculum(cached_export):
    return subject.build_curriculum(cached_export)


@pytest.mark.parametrize("split", subject.AUTHORED_SPLITS)
def test_fixed72_rows_balance_six_classes_modalities_presence_and_layouts(split):
    rows = subject.build_authored_population(split=split)
    assert len(rows) == 72
    assert [r["slot_index"] for r in rows] == list(range(96, 168) if split == "train" else range(72))
    expected = Counter({k: 2 for k in itertools.product(subject.CLASSES, subject.MODALITIES, (False, True))})
    assert Counter((r["class_name"], r["modality"], r["norm_temporal_present"]) for r in rows) == expected
    for class_name, factor in (("actor_duration_name", "actor_variant"),
                               ("condition_exception_duration", "scope_variant")):
        members = [r for r in rows if r["class_name"] == class_name]
        assert [r[factor] for r in members] == [0] * 6 + [1] * 6
        for variant in (0, 1):
            selected = [r for r in members if r[factor] == variant]
            assert Counter(r["modality"] for r in selected) == {"O": 2, "P": 2, "F": 2}
            assert Counter(r["norm_temporal_present"] for r in selected) == {False: 3, True: 3}
    assert subject.validate_authored_population(rows, split=split)["passed"]


def test_mixed_training_exactly_reuses_previous_slot_ids_examples_and_lengths():
    previous = {(a, s): subject.matched.build_authored_population(actor_curriculum=a, scope_curriculum=s)
                for a, s in itertools.product((0, 1), repeat=2)}
    rows = subject.build_authored_population()
    token = re.compile(r"\w+|[^\w\s]", re.UNICODE)
    for index, row in enumerate(rows):
        variant = index % 12 // 6
        assert row["model_example"] == previous[(variant, variant)][index]["model_example"]
        control = previous[(0, 0)][index]
        assert row["id"] == control["id"] and row["slot_index"] == control["slot_index"]
        left, right = (r["model_example"]["source_text"] for r in (control, row))
        assert len(left) == len(right) and len(left.encode()) == len(right.encode())
        assert len(token.findall(left)) == len(token.findall(right))
        for key in ("facet_spans", "modality_cue_span", "duration_occurrences"):
            assert row[key] == previous[(variant, variant)][index][key]
    changed = {r["slot_index"] for left, r in zip(previous[(0, 0)], rows, strict=True)
               if left["model_example"] != r["model_example"]}
    assert changed == set(range(138, 144)) | set(range(162, 168))
    assert all(r["prior_exposure"] == "previously_exposed_training_occurrences_fixed_mixed_layout" for r in rows)


def test_new_dev_eval_are_disjoint_from_all_prior_matched_occurrences_and_new_train():
    old = [r for a, s in itertools.product((0, 1), repeat=2)
           for r in subject.matched.build_authored_population(actor_curriculum=a, scope_curriculum=s)]
    old += subject.matched.build_authored_population(split="authored_dev")
    old += subject.matched.build_authored_population(split="authored_eval")
    populations = {split: subject.build_authored_population(split=split) for split in subject.AUTHORED_SPLITS}
    for left, right in itertools.combinations(subject.AUTHORED_SPLITS, 2):
        for key in ("id", "group_id", "pair_id", "provision_group_id", "lexical_group_id"):
            assert not {r[key] for r in populations[left]} & {r[key] for r in populations[right]}
        assert not {r["model_example"]["source_text"] for r in populations[left]} & {
            r["model_example"]["source_text"] for r in populations[right]}
    for split in subject.AUTHORED_SPLITS[1:]:
        rows = populations[split]
        for key in ("id", "group_id", "pair_id", "provision_group_id", "lexical_group_id"):
            assert not {r[key] for r in rows} & {r[key] for r in old}
        assert not {r["model_example"]["source_text"] for r in rows} & {r["model_example"]["source_text"] for r in old}
        assert all(not r["fit_eligible"] and r["id"].startswith("targeted-loss-") for r in rows)


@pytest.mark.parametrize("split", subject.AUTHORED_SPLITS)
def test_declared_occurrence_geometry_replays_independent_cue_and_facet_joins(split):
    any_utf8_offset_difference = False
    for row in subject.build_authored_population(split=split):
        source = row["model_example"]["source_text"]
        rule = row["model_example"]["canonical_ir"]["rules"][0]
        spans = [s for s in row["facet_spans"].values() if s]
        spans += [row["modality_cue_span"]] + [o["span"] for o in row["duration_occurrences"]]
        for span in spans:
            assert source[span["char_start"]:span["char_end"]] == span["text"]
            assert source.encode()[span["utf8_byte_start"]:span["utf8_byte_end"]].decode() == span["text"]
            assert hashlib.sha256(span["text"].encode()).hexdigest() == span["text_sha256"]
            any_utf8_offset_difference |= span["char_start"] != span["utf8_byte_start"]
        assert row["modality_cue_span"]["text"] == {"O": "shall", "P": "may", "F": "shall not"}[rule["modality"]]
        for field, span in row["facet_spans"].items():
            expected = [span["text"]] if field in subject.QUALIFIERS and span else [] if field in subject.QUALIFIERS else span["text"]
            assert rule[field] == expected
        for occurrence in row["duration_occurrences"]:
            inner, outer = occurrence["span"], row["facet_spans"][occurrence["role"]]
            assert outer["char_start"] <= inner["char_start"] < inner["char_end"] <= outer["char_end"]
            assert occurrence["normative"] is (occurrence["role"] == "temporal")
        assert sum(o["normative"] for o in row["duration_occurrences"]) == int(row["norm_temporal_present"])
        assert len(source) <= 239
        assert len(re.findall(r"\w+|[^\w\s]", source)) == subject.source_token_count(source) <= 128
    assert any_utf8_offset_difference


@pytest.mark.parametrize("split", subject.AUTHORED_SPLITS)
def test_whole_provisions_keep_modal_counterfactuals_and_exact_presence_partners(split):
    rows = subject.build_authored_population(split=split)
    groups, pairs = {}, {}
    for row in rows:
        groups.setdefault(row["provision_group_id"], []).append(row)
        pairs.setdefault(row["pair_id"], []).append(row)
    assert len(groups) == 12 and len(pairs) == 36
    for members in groups.values():
        assert len(members) == 6
        assert {(r["modality"], r["norm_temporal_present"]) for r in members} == set(itertools.product(subject.MODALITIES, (False, True)))
        for present in (False, True):
            rules = [copy.deepcopy(r["model_example"]["canonical_ir"]["rules"][0]) for r in members if r["norm_temporal_present"] is present]
            for rule in rules:
                rule.pop("modality")
            assert rules[0] == rules[1] == rules[2]
    for absent, present in pairs.values():
        left, right = [copy.deepcopy(r["model_example"]["canonical_ir"]["rules"][0]) for r in (absent, present)]
        assert left.pop("temporal") == [] and len(right.pop("temporal")) == 1
        assert left == right


def test_distractor_quantities_do_not_encode_unique_normative_digit_or_rank():
    norm, distractor, ranks = set(), set(), set()
    for row in subject.build_authored_population(split="authored_eval"):
        occurrences = row["duration_occurrences"]
        norm.update(o["quantity"] % 10 for o in occurrences if o["normative"])
        distractor.update(o["quantity"] % 10 for o in occurrences if not o["normative"])
        if row["norm_temporal_present"] and len(occurrences) > 1:
            value = next(o["quantity"] for o in occurrences if o["normative"])
            ranks.add(sum(o["quantity"] < value for o in occurrences))
    assert norm == distractor == {1, 2, 3}
    assert 0 in ranks and any(rank > 0 for rank in ranks)


@pytest.mark.parametrize("split", [True, 1, None, "old_authored_eval", "invented"])
def test_split_is_explicit_and_fixed_not_coerced(split):
    with pytest.raises(ValueError): subject.build_authored_population(split=split)


@pytest.mark.parametrize("corruption", ["slot", "byte", "span", "source", "cue", "latent", "pair", "provision",
                                        "duration_owner", "reference", "layout", "schema", "exposure", "extra_key"])
def test_authored_rows_reject_membership_geometry_reference_and_layout_drift(corruption):
    rows = subject.build_authored_population()
    row = rows[0]
    if corruption == "slot": row["slot_index"] = True
    elif corruption == "byte": row["facet_spans"]["action"]["utf8_byte_end"] += 1
    elif corruption == "span": row["facet_spans"]["actor"]["char_start"] += 1
    elif corruption == "source": row["model_example"]["source_text"] += " extra"
    elif corruption == "cue": row["modality_cue_span"]["text"] = "may"
    elif corruption == "latent": row["model_example"]["latent"][0] = float("nan")
    elif corruption == "pair": row["pair_id"] = rows[2]["pair_id"]
    elif corruption == "provision": row["provision_group_id"] = "another-provision"
    elif corruption == "duration_owner": rows[1]["duration_occurrences"][0]["role"] = "actor"
    elif corruption == "reference": row["model_example"]["canonical_ir"]["rules"][0]["actor"] = "short actor"
    elif corruption == "layout": rows[36]["actor_variant"] = 1
    elif corruption == "schema": row["schema"] = "matched-temporal-authored-row/v1"
    elif corruption == "exposure": row["prior_exposure"] = "independent_gold"
    else: row["unreviewed"] = True
    with pytest.raises(ValueError): subject.validate_authored_population(rows, split="train")


def test_structural_token_counter_requires_text_and_counts_curly_quotes():
    assert subject.source_token_count('the Office “within 9101 days” shall not submit.') == 11
    for value in (None, 1, True, ["text"]):
        with pytest.raises(ValueError): subject.source_token_count(value)


def test_one_common168_keeps_cached96_and_expected_panel_counts(curriculum, cached_export):
    assert set(curriculum["training_populations"]) == set(curriculum["training_metadata"]) == {"mixed"}
    rows = curriculum["training_populations"]["mixed"]
    assert len(rows) == 168 and rows[:96] == cached_export["populations"]["contrast_train"][:96]
    assert curriculum["training_metadata"]["mixed"][:96] == cached_export["metadata"]["contrast_train"][:96]
    assert Counter(r["canonical_ir"]["rules"][0]["modality"] for r in rows) == {"O": 56, "P": 56, "F": 56}
    assert Counter(bool(r["canonical_ir"]["rules"][0]["temporal"]) for r in rows) == {False: 84, True: 84}
    expected = {"old_tune": 96, "fresh_tune": 36, "fresh_challenge": 36, "old_authored_eval": 72,
                "authored_dev": 72, "authored_eval": 72, "law": 8}
    assert {k: len(v) for k, v in curriculum["diagnostic_populations"].items()} == expected
    assert set(curriculum["diagnostic_metadata"]) == set(expected) - {"authored_eval", "law"}
    for name in ("old_tune", "fresh_tune", "fresh_challenge", "law"):
        assert curriculum["diagnostic_populations"][name] == cached_export["populations"][name]
    assert all(value is False for value in curriculum["authority"].values())
    assert curriculum["cache_provenance"]["raw_file_read_or_verified_by_module"] is False


def test_old_authored_eval_is_exactly_retained_as_exposed_reference_diagnostic(curriculum):
    examples = curriculum["diagnostic_populations"]["old_authored_eval"]
    expected = [r["model_example"] for r in subject.matched.build_authored_population(split="authored_eval")]
    assert examples == expected and all("canonical_ir" in r for r in examples)
    assert subject._digest(examples) == subject.OLD_AUTHORED_EVAL_SHA256
    assert "old_authored_eval" in curriculum["panel_contract"]["exposed_regression_panels"]
    assert curriculum["split_contract"]["old_authored_eval_rows_exposed"] == 72


def test_eval_export_has_exact_three_keys_no_metadata_or_references(curriculum):
    assert all(set(r) == {"id", "source_text", "latent"} for r in curriculum["diagnostic_populations"]["authored_eval"])
    assert "authored_eval" not in curriculum["diagnostic_metadata"]
    for name in curriculum["diagnostic_populations"]:
        sources = subject.export_source_panel(curriculum, split=name)
        assert all(set(r) == {"id", "source_text", "latent"} for r in sources)
        assert all(subject.source_token_count(r["source_text"]) <= 128 for r in sources)


def test_explicit_reference_packet_declares_four_cell_gate_without_attesting_blind_gold(curriculum):
    for token in (None, True, "explicit_author_visible_engineering_references"):
        with pytest.raises(ValueError):
            subject.export_reference_panel(curriculum, split="authored_eval", reference_access=token)
    opened = subject.export_reference_panel(curriculum, split="authored_eval", reference_access=subject.REFERENCE_ACCESS)
    assert len(opened["rows"]) == 72 and opened["references_visible_to_builder_author"] is True
    assert opened["semantic_gold"] is False and opened["reference_access_order_attested"] is False
    assert opened["new_reference_packet_forbidden_until_all_four_cell_outputs_frozen"] is True
    assert opened["prior_exposed_regression_diagnostic"] is False
    prior = subject.export_reference_panel(curriculum, split="old_authored_eval", reference_access=subject.REFERENCE_ACCESS)
    assert prior["prior_exposed_regression_diagnostic"] is True
    assert curriculum["split_contract"]["geometry_packet_permitted_in_numerical_inputs"] is False


def test_annotation_packet_can_hide_declared_references_but_cannot_establish_gold(curriculum):
    blank = subject.export_annotation_packet(curriculum, split="authored_eval")
    declared = subject.export_annotation_packet(curriculum, split="authored_eval", mode="author_declared_review")
    assert all(r["annotation"] is None and "author_canonical_ir" not in r for r in blank["rows"])
    assert all("author_canonical_ir" in r and "facet_spans" in r["author_declaration"] for r in declared["rows"])
    assert blank["semantic_gold"] is False and declared["independently_reviewed"] is False
    assert declared["review_response_can_establish_legal_gold_without_separate_provenance"] is False


def test_registration_contract_exposes_counts_source_only_scope_and_no_runtime_claim(curriculum):
    contract = subject.registration_contract(curriculum)
    assert contract["training_population"] == "mixed" and contract["training_rows"] == 168
    assert contract["diagnostic_panel_rows"] == {k: len(v) for k, v in curriculum["diagnostic_populations"].items()}
    assert contract["latent_dimension"] == 384 and contract["latent_enabled"] is False
    assert contract["all_panel_max_structural_tokens"] == 76
    assert contract["authored_eval_child_keys"] == ["id", "source_text", "latent"]
    assert contract["resource_API_calls_performed"] is contract["semantic_gold"] is False
    assert contract["reference_access_order_attested"] is False


@pytest.mark.parametrize("corruption", ["legacy", "legacy_metadata", "old_panel", "old_metadata", "old_eval",
    "old_eval_metadata", "train_source", "train_geometry", "manifest", "eval_reference", "eval_metadata",
    "authority", "cache_pin", "slot_type", "split_extra", "latent_type", "gate", "panel_rows",
    "extra_training_population", "packet_schema", "packet_old_eval", "source_duplicate", "new_dev_reference"])
def test_complete_curriculum_rejects_cache_panel_geometry_masking_and_authority_drift(curriculum, corruption):
    value = copy.deepcopy(curriculum)
    if corruption == "legacy": value["training_populations"]["mixed"][0]["source_text"] += " drift"
    elif corruption == "legacy_metadata": value["training_metadata"]["mixed"][0]["class_name"] = "unreviewed"
    elif corruption == "old_panel": value["diagnostic_populations"]["fresh_challenge"][0]["source_text"] += " drift"
    elif corruption == "old_metadata": value["diagnostic_metadata"]["fresh_challenge"][0]["class_name"] = "unreviewed"
    elif corruption == "old_eval": value["diagnostic_populations"]["old_authored_eval"][0]["canonical_ir"]["rules"][0]["modality"] = "P"
    elif corruption == "old_eval_metadata": value["diagnostic_metadata"]["old_authored_eval"][0]["class_name"] = "unreviewed"
    elif corruption == "train_source": value["training_populations"]["mixed"][96]["source_text"] += " drift"
    elif corruption == "train_geometry": value["geometry_review_packet"]["training"]["mixed"][0]["facet_spans"]["actor"]["utf8_byte_start"] += 1
    elif corruption == "manifest": value["manifests"]["training"]["mixed"]["rows"] = 167
    elif corruption == "eval_reference": value["diagnostic_populations"]["authored_eval"][0]["canonical_ir"] = {"rules": []}
    elif corruption == "eval_metadata": value["diagnostic_metadata"]["authored_eval"] = []
    elif corruption == "authority": value["authority"]["semantic_gold"] = True
    elif corruption == "cache_pin": value["cache_provenance"]["canonical_export_sha256"] = "0" * 64
    elif corruption == "slot_type": value["slot_contract"]["presence_order"] = [0, 1]
    elif corruption == "split_extra": value["split_contract"]["blind_gold"] = True
    elif corruption == "latent_type": value["latent_contract"]["latent_enabled"] = 0
    elif corruption == "gate": value["split_contract"]["new_reference_packet_forbidden_until_all_four_cell_outputs_frozen"] = False
    elif corruption == "panel_rows": value["panel_contract"]["rows"]["old_authored_eval"] = 0
    elif corruption == "extra_training_population": value["training_populations"]["other"] = []
    elif corruption == "packet_schema": value["geometry_review_packet"]["schema"] = "unreviewed"
    elif corruption == "packet_old_eval": value["geometry_review_packet"]["old_authored_eval"][0]["prior_exposure"] = "fresh_holdout"
    elif corruption == "source_duplicate": value["diagnostic_populations"]["authored_dev"][1] = copy.deepcopy(value["diagnostic_populations"]["authored_dev"][0])
    else: value["geometry_review_packet"]["authored_dev"][0]["model_example"]["canonical_ir"]["rules"][0]["actor"] = "different actor"
    with pytest.raises(ValueError): subject.validate_curriculum(value)


def test_export_clones_and_builds_do_not_share_mutable_records(curriculum, cached_export):
    exported = subject.export_training_examples(curriculum)
    exported[0]["latent"][0] = 1.0
    assert curriculum["training_populations"]["mixed"][0]["latent"][0] != 1.0
    before = copy.deepcopy(curriculum)
    fresh = subject.build_curriculum(cached_export)
    fresh["training_populations"]["mixed"][96]["latent"][0] = 1.0
    assert before == curriculum
    for cell in (True, "actor0-scope0", None):
        with pytest.raises(ValueError): subject.export_training_examples(curriculum, cell=cell)


def test_invalid_prior_export_fails_before_any_reference_or_source_generation(cached_export):
    for value in (None, [], {"missing": "cache"}):
        with pytest.raises(ValueError): subject.build_curriculum(value)
    value = copy.deepcopy(cached_export)
    value["populations"]["contrast_train"][0]["source_text"] += " drift"
    with pytest.raises(ValueError, match="cached prior export"):
        subject.build_curriculum(value)


def test_module_imports_only_stdlib_and_unchanged_pure_matched_builder():
    tree = ast.parse(Path(subject.__file__).read_text())
    direct = {a.name for node in tree.body if isinstance(node, ast.Import) for a in node.names}
    assert direct <= {"hashlib", "itertools", "json", "re"}
    imported = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert {(node.level, node.module) for node in imported} == {(0, "__future__"), (0, "collections"), (1, None)}
    relative = next(node for node in imported if node.level)
    assert [a.name for a in relative.names] == ["matched_temporal_curriculum"]
    assert hashlib.sha256(Path(subject.matched.__file__).read_bytes()).hexdigest() == "a64fa4f79e949593744768c8ab4896f349d93d2885ebbc36a13d0854e6185a71"
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"open", "exec", "eval", "__import__"} for node in ast.walk(tree))
