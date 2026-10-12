"""Pure factor, copy-geometry, membership and explicit reference-access tests."""
import ast
from collections import Counter
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import matched_temporal_curriculum as subject


def population(actor=0, scope=0, split="train"):
    return subject.build_authored_population(split=split, actor_curriculum=actor, scope_curriculum=scope)


@pytest.fixture(scope="module")
def cached_export():
    # Optional integration fixture is existing authored data, never model state.
    # Pure generator tests below remain portable without the historical cache.
    name = os.environ.get("MATCHED_CURRICULUM_PRIOR_EXPORT")
    if not name:
        pytest.skip("set MATCHED_CURRICULUM_PRIOR_EXPORT to the immutable prior authored export")
    path = Path(name)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == subject.PRIOR_EXPORT_FILE_SHA256
    return json.loads(raw)


@pytest.fixture(scope="module")
def curriculum(cached_export):
    return subject.build_curriculum(cached_export)


@pytest.mark.parametrize("actor,scope", tuple(itertools.product((0, 1), repeat=2)))
def test_72_rows_keep_class_modality_presence_quotas_and_stable_order(actor, scope):
    rows = population(actor, scope)
    assert len(rows) == 72
    tally = Counter((r["class_name"], r["modality"], r["norm_temporal_present"]) for r in rows)
    assert tally == Counter({key: 2 for key in itertools.product(subject.CLASSES, subject.MODALITIES, (False, True))})
    assert [r["slot_index"] for r in rows] == list(range(96, 168))
    assert [r["id"] for r in rows] == [r["id"] for r in population()]
    subject.validate_authored_population(rows, split="train")


def test_actor_and_scope_factors_replace_only_their_twelve_slots():
    cells = {(a, s): population(a, s) for a, s in itertools.product((0, 1), repeat=2)}
    for (a, s), rows in cells.items():
        changed = {r["slot_index"] for left, r in zip(cells[(0, 0)], rows, strict=True) if left != r}
        expected = set(range(132, 144)) if a else set()
        if s:
            expected |= set(range(156, 168))
        assert changed == expected
    # Factor effects commute; enabling one cannot modify the other's declarations.
    for position in range(72):
        slot = position + 96
        if slot in range(132, 144):
            assert cells[(1, 0)][position] == cells[(1, 1)][position]
            assert cells[(0, 0)][position] == cells[(0, 1)][position]
        if slot in range(156, 168):
            assert cells[(0, 1)][position] == cells[(1, 1)][position]
            assert cells[(0, 0)][position] == cells[(1, 0)][position]


def test_slot_character_utf8_and_token_counts_match_all_four_cells():
    # Token equality is checked by an independent structural lexeme expression.
    import re
    token = re.compile(r"\w+|[^\w\s]", re.UNICODE)
    baseline = population()
    for a, s in itertools.product((0, 1), repeat=2):
        for left, right in zip(baseline, population(a, s), strict=True):
            text0, text1 = (r["model_example"]["source_text"] for r in (left, right))
            assert len(text0) == len(text1)
            assert len(text0.encode()) == len(text1.encode())
            assert len(token.findall(text0)) == len(token.findall(text1))
    assert max(len(r["model_example"]["source_text"]) for r in baseline) < 4096


def test_actor_treatment_keeps_long_quoted_suffix_inside_actor_not_temporal():
    controls, treatments = population(), population(1, 0)
    for control, treated in zip(controls[36:48], treatments[36:48], strict=True):
        actor0 = control["model_example"]["canonical_ir"]["rules"][0]["actor"]
        actor1 = treated["model_example"]["canonical_ir"]["rules"][0]["actor"]
        assert actor0.endswith("days”")
        assert actor1.endswith("for Licensed Records and Public Archive Custody”")
        assert "Office named “within " in actor1
        assert len(actor0) == len(actor1)
        inner = next(o for o in treated["duration_occurrences"] if o["role"] == "actor")
        assert inner["normative"] is False
        assert inner["span"]["char_end"] < treated["facet_spans"]["actor"]["char_end"]
        if not treated["norm_temporal_present"]:
            assert treated["model_example"]["canonical_ir"]["rules"][0]["temporal"] == []


def test_scope_treatment_owns_quoted_condition_and_exception_without_false_deadline():
    rows = population(0, 1)[60:72]
    for row in rows:
        rule = row["model_example"]["canonical_ir"]["rules"][0]
        assert "received “within " in rule["conditions"][0]
        assert "notice states “within " in rule["exceptions"][0]
        distractors = [o for o in row["duration_occurrences"] if not o["normative"]]
        assert {o["role"] for o in distractors} == {"conditions", "exceptions"}
        assert len(distractors) == 2
        if not row["norm_temporal_present"]:
            assert rule["temporal"] == []
        elif row["slot_index"] < 162:
            assert row["facet_spans"]["temporal"]["char_start"] > row["facet_spans"]["exceptions"]["char_end"]
        else:
            assert row["facet_spans"]["exceptions"]["char_start"] < row["facet_spans"]["conditions"]["char_start"]


@pytest.mark.parametrize("split", subject.AUTHORED_SPLITS)
def test_all_modal_counterfactuals_and_presence_partners_share_one_provision(split):
    rows = population(split=split)
    groups, pairs = {}, {}
    for row in rows:
        groups.setdefault(row["provision_group_id"], []).append(row)
        pairs.setdefault(row["pair_id"], []).append(row)
    assert len(groups) == 12 and len(pairs) == 36
    for members in groups.values():
        assert len(members) == 6
        assert {(r["modality"], r["norm_temporal_present"]) for r in members} == set(itertools.product(subject.MODALITIES, (False, True)))
    for absent, present in pairs.values():
        left, right = [copy.deepcopy(r["model_example"]["canonical_ir"]["rules"][0]) for r in (absent, present)]
        assert left.pop("temporal") == [] and len(right.pop("temporal")) == 1
        assert left == right
        assert absent["group_id"] == present["group_id"]
    subject.validate_authored_population(rows, split=split)


def test_new_dev_eval_source_pair_lexical_provision_groups_are_disjoint():
    populations = {split: population(split=split) for split in subject.AUTHORED_SPLITS}
    for left, right in itertools.combinations(subject.AUTHORED_SPLITS, 2):
        for key in ("id", "group_id", "pair_id", "provision_group_id", "lexical_group_id"):
            assert not {r[key] for r in populations[left]} & {r[key] for r in populations[right]}
        assert not {r["model_example"]["source_text"] for r in populations[left]} & {r["model_example"]["source_text"] for r in populations[right]}
    assert all(not row["fit_eligible"] for split in subject.AUTHORED_SPLITS[1:] for row in populations[split])


def test_declared_geometry_replays_character_utf8_and_copied_targets():
    unicode_difference = False
    for row in population(1, 1):
        source = row["model_example"]["source_text"]
        rule = row["model_example"]["canonical_ir"]["rules"][0]
        spans = [s for s in row["facet_spans"].values() if s]
        spans += [row["modality_cue_span"]] + [o["span"] for o in row["duration_occurrences"]]
        for span in spans:
            assert source[span["char_start"]:span["char_end"]] == span["text"]
            assert source.encode()[span["utf8_byte_start"]:span["utf8_byte_end"]].decode() == span["text"]
            assert hashlib.sha256(span["text"].encode()).hexdigest() == span["text_sha256"]
            unicode_difference |= span["char_start"] != span["utf8_byte_start"]
        for field, span in row["facet_spans"].items():
            expected = [span["text"]] if field in subject.QUALIFIERS and span else [] if field in subject.QUALIFIERS else span["text"]
            assert rule[field] == expected
    assert unicode_difference


def test_normative_quantity_does_not_have_unique_last_digit_or_smallest_rank():
    rows = population(1, 1)
    norm, distractor, ranks = set(), set(), set()
    for row in rows:
        occurrences = row["duration_occurrences"]
        norm.update(o["quantity"] % 10 for o in occurrences if o["normative"])
        distractor.update(o["quantity"] % 10 for o in occurrences if not o["normative"])
        if row["norm_temporal_present"] and len(occurrences) > 1:
            value = next(o["quantity"] for o in occurrences if o["normative"])
            ranks.add(sum(o["quantity"] < value for o in occurrences))
    assert norm == distractor == {1, 2, 3}
    assert 0 in ranks and any(rank > 0 for rank in ranks)


@pytest.mark.parametrize("corruption", ["slot", "byte", "span", "source", "cue", "latent", "pair", "provision", "duration_owner", "reference", "extra_key"])
def test_row_custody_rejects_geometry_membership_and_reference_corruption(corruption):
    rows = population(1, 1)
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
    else: row["unreviewed"] = True
    with pytest.raises(ValueError):
        subject.validate_authored_population(rows, split="train")


@pytest.mark.parametrize("actor,scope", [(True, 0), (0, False), (2, 0), (0, -1), ("1", 0)])
def test_factor_levels_do_not_coerce_booleans_or_strings(actor, scope):
    with pytest.raises(ValueError): population(actor, scope)


def test_fixed_evaluation_population_does_not_ignore_requested_factor_changes():
    with pytest.raises(ValueError, match="mixture is fixed"):
        population(1, 0, "authored_eval")


def test_complete_four_cells_keep_cached96_and_all_old_diagnostic_rows(curriculum, cached_export):
    assert list(curriculum["training_populations"]) == list(subject.CELL_IDS)
    rehearsal = cached_export["populations"]["contrast_train"][:96]
    for cell, rows in curriculum["training_populations"].items():
        assert len(rows) == 168 and rows[:96] == rehearsal
        assert Counter(r["canonical_ir"]["rules"][0]["modality"] for r in rows) == {"O": 56, "P": 56, "F": 56}
        assert Counter(bool(r["canonical_ir"]["rules"][0]["temporal"]) for r in rows) == {False: 84, True: 84}
        assert all(set(m) == set(subject.META_FIELDS) for m in curriculum["training_metadata"][cell])
    for name in ("old_tune", "fresh_tune", "fresh_challenge", "law"):
        assert curriculum["diagnostic_populations"][name] == cached_export["populations"][name]
    assert all(value is False for value in curriculum["authority"].values())
    assert curriculum["cache_provenance"]["raw_file_read_or_verified_by_module"] is False


def test_evaluation_sources_have_no_references_or_geometry(curriculum):
    for row in curriculum["diagnostic_populations"]["authored_eval"]:
        assert set(row) == {"id", "source_text", "latent"}
    assert len(curriculum["diagnostic_populations"]["authored_dev"]) == 72
    assert len(curriculum["diagnostic_populations"]["authored_eval"]) == 72
    for name in curriculum["diagnostic_populations"]:
        assert all(set(row) == {"id", "source_text", "latent"} for row in subject.export_source_panel(curriculum, split=name))


def test_explicit_reference_and_annotation_packets_do_not_attest_blind_gold(curriculum):
    with pytest.raises(ValueError):
        subject.export_reference_panel(curriculum, split="authored_eval", reference_access=True)
    opened = subject.export_reference_panel(curriculum, split="authored_eval", reference_access=subject.REFERENCE_ACCESS)
    assert len(opened["rows"]) == 72 and opened["references_visible_to_builder_author"] is True
    assert opened["semantic_gold"] is False and opened["reference_access_order_attested"] is False
    blank = subject.export_annotation_packet(curriculum, split="authored_eval")
    declared = subject.export_annotation_packet(curriculum, split="authored_eval", mode="author_declared_review")
    assert all(row["annotation"] is None and "author_canonical_ir" not in row for row in blank["rows"])
    assert all("author_canonical_ir" in row and "facet_spans" in row["author_declaration"] for row in declared["rows"])
    assert declared["independently_reviewed"] is False


@pytest.mark.parametrize("corruption", ["legacy", "legacy_metadata", "old_panel", "old_metadata", "outside_slot", "manifest", "eval_reference", "authority", "cache_pin", "slot_type", "split_extra", "latent_type"])
def test_full_curriculum_rejects_cache_factor_exposure_and_manifest_drift(curriculum, corruption):
    value = copy.deepcopy(curriculum)
    if corruption == "legacy": value["training_populations"]["actor0-scope0"][0]["source_text"] += " drift"
    elif corruption == "legacy_metadata": value["training_metadata"]["actor0-scope0"][0]["class_name"] = "unreviewed"
    elif corruption == "old_panel": value["diagnostic_populations"]["fresh_challenge"][0]["source_text"] += " drift"
    elif corruption == "old_metadata": value["diagnostic_metadata"]["fresh_challenge"][0]["class_name"] = "unreviewed"
    elif corruption == "outside_slot": value["training_populations"]["actor1-scope0"][96]["source_text"] += " drift"
    elif corruption == "manifest": value["manifests"]["training"]["actor0-scope0"]["rows"] = 167
    elif corruption == "eval_reference": value["diagnostic_populations"]["authored_eval"][0]["canonical_ir"] = {"rules": []}
    elif corruption == "authority": value["authority"]["semantic_gold"] = True
    elif corruption == "slot_type": value["slot_contract"]["presence_order"] = [0, 1]
    elif corruption == "split_extra": value["split_contract"]["blind_gold"] = True
    elif corruption == "latent_type": value["latent_contract"]["latent_enabled"] = 0
    else: value["cache_provenance"]["canonical_export_sha256"] = "0" * 64
    with pytest.raises(ValueError): subject.validate_curriculum(value)


def test_caller_mutations_do_not_change_another_cell_or_fixed_builder(curriculum):
    first = copy.deepcopy(curriculum)
    exported = subject.export_training_examples(first, cell="actor0-scope0")
    exported[0]["latent"][0] = 1.0
    assert first == curriculum
    first["training_populations"]["actor0-scope0"][0]["latent"][0] = 1.0
    assert first["training_populations"]["actor1-scope0"][0]["latent"][0] == curriculum["training_populations"]["actor1-scope0"][0]["latent"][0]


def test_bad_cached_values_fail_closed_without_file_or_parser_access(cached_export):
    value = copy.deepcopy(cached_export)
    value["populations"]["contrast_train"][0]["source_text"] += " drift"
    with pytest.raises(ValueError, match="cached prior export"):
        subject.build_curriculum(value)


def test_module_has_only_standard_library_imports_and_no_source_first_match():
    body = Path(subject.__file__).read_text()
    tree = ast.parse(body)
    names = [n.module if isinstance(n, ast.ImportFrom) else a.name
             for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
             for a in ([None] if isinstance(n, ast.ImportFrom) else n.names)]
    assert set(names) <= {"__future__", "collections", "hashlib", "itertools", "json"}
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr in {"find", "search", "finditer"}
                   and isinstance(n.func.value, ast.Name) and n.func.value.id in {"source", "text"}
                   for n in ast.walk(tree))
