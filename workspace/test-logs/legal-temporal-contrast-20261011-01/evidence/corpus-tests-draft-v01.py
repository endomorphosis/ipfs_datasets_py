"""Fictional source custody, label compatibility and exposure boundary checks."""
import ast
import copy
import hashlib
import itertools
import json
from pathlib import Path
import re

import pytest

from ipfs_datasets_py.logic.legal_ir import temporal_role_contrast_corpus as subject


def example(row):
    return row["refusal_candidate"] if "refusal_candidate" in row else row["model_example"]


def all_rows(corpus):
    return [row for population in corpus["populations"].values() for row in population]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def test_predeclared_denominators_and_no_legal_authority():
    corpus = subject.build_corpus()
    assert corpus["counts"] == {"train": 72, "tuning": 36, "challenge": 36, "ambiguous_diagnostics": 6}
    assert {key: len(rows) for key, rows in corpus["populations"].items()} == corpus["counts"]
    assert all(value is False for value in corpus["authority"].values())
    assert corpus["provenance"] == "fictional_authored_engineering_not_statutory_gold"
    assert corpus["split_contract"]["shared_templates"] is True
    assert corpus["split_contract"]["structural_novelty_claimed"] is False
    assert corpus["split_contract"]["statutory_section_holdout_created"] is False
    assert corpus["split_contract"]["challenge_reference_visibility"] == "visible_to_builder_author_generated_engineering_only"


def test_fixed_builder_returns_independent_mutable_objects():
    first = subject.build_corpus()
    second = subject.build_corpus()
    assert first == second
    first["populations"]["train"][0]["model_example"]["latent"][0] = 1.0
    assert second["populations"]["train"][0]["model_example"]["latent"][0] == 0.0
    subject.validate_corpus(second)


@pytest.mark.parametrize("split", subject.SPLITS)
def test_every_confusion_class_has_balanced_modal_presence_pairs(split):
    rows = subject.build_corpus()["populations"][split]
    repetitions = 2 if split == "train" else 1
    for class_name, modality, present in itertools.product(subject.CLASSES, subject.MODALITIES, (False, True)):
        selected = [row for row in rows if row["class_name"] == class_name and row["modality"] == modality
                    and row["norm_temporal_present"] == present]
        assert len(selected) == repetitions
        assert all(row["pair_variant"] == ("temporal_present" if present else "temporal_absent") for row in selected)


def test_related_modal_counterfactuals_and_pair_members_stay_in_one_group():
    corpus = subject.build_corpus()
    rows = {row["id"]: row for row in all_rows(corpus)}
    assert len(corpus["groups"]) == 24
    assert len(corpus["pairs"]) == 72
    for group in corpus["groups"]:
        members = [rows[identifier] for identifier in group["row_ids"]]
        assert len(members) == 6 and len(group["pair_ids"]) == 3
        assert {row["group_id"] for row in members} == {group["group_id"]}
        assert {row["split"] for row in members} == {group["split"]}
        assert {(row["modality"], row["norm_temporal_present"]) for row in members} == set(
            itertools.product(subject.MODALITIES, (False, True)))


def test_pair_reference_only_changes_normative_temporal_presence():
    corpus = subject.build_corpus()
    rows = {row["id"]: row for row in all_rows(corpus)}
    for pair in corpus["pairs"]:
        absent, present = rows[pair["absent_id"]], rows[pair["present_id"]]
        assert absent["pair_id"] == present["pair_id"] == pair["pair_id"]
        assert absent["group_id"] == present["group_id"] == pair["group_id"]
        assert absent["split"] == present["split"] == pair["split"]
        left = copy.deepcopy(example(absent)["canonical_ir"]["rules"][0])
        right = copy.deepcopy(example(present)["canonical_ir"]["rules"][0])
        assert left.pop("temporal") == []
        assert len(right.pop("temporal")) == 1
        assert left == right


def test_source_reference_and_group_disjointness_are_actual_not_only_flags():
    corpus = subject.build_corpus()
    sources, references, groups = {}, {}, {}
    for split in subject.SPLITS:
        population = corpus["populations"][split]
        sources[split] = {example(row)["source_text"] for row in population}
        references[split] = {canonical(example(row)["canonical_ir"]) for row in population}
        groups[split] = {row["group_id"] for row in population}
        assert len(sources[split]) == len(references[split]) == len(population)
    for left, right in itertools.combinations(subject.SPLITS, 2):
        assert not sources[left] & sources[right]
        assert not references[left] & references[right]
        assert not groups[left] & groups[right]


def test_all_full_and_nested_spans_replay_character_and_utf8_bytes():
    corpus = subject.build_corpus()
    saw_unicode_offset_difference = False
    for row in all_rows(corpus):
        source = example(row)["source_text"]
        encoded = source.encode("utf-8")
        assert row["source_sha256"] == hashlib.sha256(encoded).hexdigest()
        assert row["source_characters"] == len(source)
        assert row["source_utf8_bytes"] == len(encoded)
        spans = [span for span in row["facet_spans"].values() if span is not None]
        spans += [row["modality_cue_span"]]
        spans += [occurrence["span"] for occurrence in row["duration_occurrences"]]
        for span in spans:
            assert set(span) == {"char_start", "char_end", "utf8_byte_start", "utf8_byte_end", "text", "text_sha256"}
            assert 0 <= span["char_start"] < span["char_end"] <= len(source)
            assert source[span["char_start"]:span["char_end"]] == span["text"]
            assert encoded[span["utf8_byte_start"]:span["utf8_byte_end"]].decode("utf-8") == span["text"]
            assert span["utf8_byte_start"] == len(source[:span["char_start"]].encode("utf-8"))
            assert span["utf8_byte_end"] == len(source[:span["char_end"]].encode("utf-8"))
            assert span["text_sha256"] == hashlib.sha256(span["text"].encode("utf-8")).hexdigest()
            saw_unicode_offset_difference |= span["char_start"] != span["utf8_byte_start"]
    assert saw_unicode_offset_difference


def test_full_facet_geometry_is_nonoverlapping_and_copied_to_reference():
    for row in all_rows(subject.build_corpus()):
        rule = example(row)["canonical_ir"]["rules"][0]
        assert set(rule) == {"modality", *subject.FIELDS}
        active = []
        for field, span in row["facet_spans"].items():
            atom = [span["text"]] if field in subject.QUALIFIERS and span else [] if field in subject.QUALIFIERS else span["text"] if span else ""
            assert rule[field] == atom
            if span:
                active.append((span["char_start"], span["char_end"]))
        for left, right in itertools.combinations(active, 2):
            assert left[1] <= right[0] or right[1] <= left[0]


def test_duration_occurrences_keep_their_declared_role_and_original_full_span():
    for row in all_rows(subject.build_corpus()):
        occurrences = row["duration_occurrences"]
        assert [item["occurrence_index"] for item in occurrences] == list(range(len(occurrences)))
        normative = [item for item in occurrences if item["normative"]]
        assert len(normative) == int(row["norm_temporal_present"])
        for item in occurrences:
            assert set(item) == {"role", "qualifier_index", "normative", "span", "occurrence_index"}
            assert item["normative"] is (item["role"] == "temporal")
            assert item["qualifier_index"] == (0 if item["role"] in subject.QUALIFIERS else None)
            outer = row["facet_spans"][item["role"]]
            assert outer["char_start"] <= item["span"]["char_start"] < item["span"]["char_end"] <= outer["char_end"]


@pytest.mark.parametrize("class_name", subject.CLASSES[1:])
def test_distractor_time_is_present_while_normative_temporal_is_absent(class_name):
    for split in subject.SPLITS:
        rows = [row for row in subject.build_corpus()["populations"][split]
                if row["class_name"] == class_name and not row["norm_temporal_present"]]
        assert rows
        for row in rows:
            assert row["duration_occurrences"]
            assert all(item["normative"] is False for item in row["duration_occurrences"])
            assert example(row)["canonical_ir"]["rules"][0]["temporal"] == []


def test_trainable_normative_duration_differs_from_every_distractor():
    for split in subject.SPLITS:
        for row in subject.build_corpus()["populations"][split]:
            normative = [item["span"]["text"] for item in row["duration_occurrences"] if item["normative"]]
            others = [item["span"]["text"] for item in row["duration_occurrences"] if not item["normative"]]
            if normative:
                assert normative[0] not in others
                assert example(row)["source_text"].count(normative[0]) == 1


def test_disabled_latent_384_placeholder_is_never_described_as_encoder_output():
    corpus = subject.build_corpus()
    assert corpus["latent_contract"] == {"dimension": 384, "latent_enabled": False,
        "representation": "zero_placeholder_not_encoder_output", "encoder_identity": None,
        "latent_decoder_evaluated": False}
    for row in all_rows(corpus):
        assert set(example(row)) == {"id", "source_text", "canonical_ir", "latent"}
        assert example(row)["latent"] == [0.0] * 384
        assert row["fit_eligible"] is (row["split"] == "train")


@pytest.mark.parametrize("split", subject.SPLITS)
def test_existing_legacy_label_owner_accepts_every_supported_reference(split):
    # This invokes the pure existing tokenizer/label contract, never a model.
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    for row in subject.build_corpus()["populations"][split]:
        value = example(row)
        tokens = span.tokenize_source(value["source_text"])
        labels = span._labels(value["source_text"], value["canonical_ir"], tokens)
        assert labels["modality"] == span.MODALITIES.index(row["modality"])
        assert labels["presence"][-1] is row["norm_temporal_present"]
        assert row["legacy_labels_supported_expected"] is True


def test_repeated_identical_refusal_candidates_remain_unsupported_by_legacy_labels():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    for row in subject.build_corpus()["populations"]["ambiguous_diagnostics"]:
        assert "model_example" not in row and "refusal_candidate" in row
        assert row["fit_eligible"] is False
        assert row["legacy_labels_supported_expected"] is False
        assert row["legacy_label_status"] == "unsupported_ambiguous_temporal_atom"
        value = row["refusal_candidate"]
        temporal = value["canonical_ir"]["rules"][0]["temporal"][0]
        assert value["source_text"].count(temporal) == 2
        occurrences = [item for item in row["duration_occurrences"] if item["span"]["text"] == temporal]
        assert len(occurrences) == 2 and sum(item["normative"] for item in occurrences) == 1
        with pytest.raises(ValueError, match="temporal source span is ambiguous"):
            span._labels(value["source_text"], value["canonical_ir"], span.tokenize_source(value["source_text"]))


def test_model_export_does_not_leak_geometry_and_is_independent_of_corpus():
    corpus = subject.build_corpus()
    before = copy.deepcopy(corpus)
    rows = subject.export_model_examples(corpus, split="train")
    assert len(rows) == 72 and all(set(row) == {"id", "source_text", "canonical_ir", "latent"} for row in rows)
    rows[0]["canonical_ir"]["rules"][0]["actor"] = "altered"
    assert corpus == before


@pytest.mark.parametrize("split", ["challenge", "ambiguous_diagnostics", "law", None, True, 1])
def test_fit_export_cannot_include_challenge_or_refusal_panel(split):
    with pytest.raises(ValueError, match="train or tuning only"):
        subject.export_model_examples(subject.build_corpus(), split=split)


@pytest.mark.parametrize("split", subject.EXPECTED_COUNTS)
def test_source_only_evaluation_export_has_no_reference_or_occurrence_leak(split):
    corpus = subject.build_corpus()
    rows = subject.export_source_panel(corpus, split=split)
    assert len(rows) == corpus["counts"][split]
    assert all(set(row) == {"id", "source_text", "latent"} for row in rows)
    assert all("canonical_ir" not in row for row in rows)


def test_challenge_reference_export_discloses_access_without_attesting_holdout():
    result = subject.export_reference_panel(subject.build_corpus(), split="challenge")
    assert len(result["rows"]) == 36
    assert result["reference_access_explicit"] is True
    assert result["reference_free_generation_verified"] is False
    assert result["semantic_gold"] is False and result["legal_fidelity_qualified"] is False
    assert result["fit_export_permitted"] is False


@pytest.mark.parametrize("corruption", [
    "extra_key", "authority", "count_bool", "source", "offset", "byte_offset", "role",
    "cue", "latent", "missing_row", "moved_group", "pair_member", "reference",
    "fit_diagnostic", "diagnostic_truncation", "split_claim",
])
def test_closed_validation_rejects_source_geometry_exposure_and_group_corruption(corruption):
    corpus = subject.build_corpus()
    row = corpus["populations"]["train"][0]
    if corruption == "extra_key":
        corpus["custom"] = "unreviewed"
    elif corruption == "authority":
        corpus["authority"]["semantic_gold"] = True
    elif corruption == "count_bool":
        corpus["counts"]["train"] = True
    elif corruption == "source":
        row["model_example"]["source_text"] += " extra"
    elif corruption == "offset":
        row["facet_spans"]["actor"]["char_start"] = 1
    elif corruption == "byte_offset":
        row["facet_spans"]["object"]["utf8_byte_start"] += 1
    elif corruption == "role":
        corpus["populations"]["train"][1]["duration_occurrences"][0]["role"] = "conditions"
    elif corruption == "cue":
        row["modality_cue_span"]["text"] = "may"
    elif corruption == "latent":
        row["model_example"]["latent"][0] = float("nan")
    elif corruption == "missing_row":
        corpus["populations"]["tuning"].pop()
    elif corruption == "moved_group":
        corpus["groups"][0]["split"] = "challenge"
    elif corruption == "pair_member":
        corpus["pairs"][0]["present_id"] = corpus["pairs"][1]["present_id"]
    elif corruption == "reference":
        row["model_example"]["canonical_ir"]["rules"][0]["temporal"] = ["within 3 days"]
    elif corruption == "fit_diagnostic":
        corpus["populations"]["ambiguous_diagnostics"][0]["fit_eligible"] = True
    elif corruption == "diagnostic_truncation":
        corpus["populations"]["ambiguous_diagnostics"].pop()
    else:
        corpus["split_contract"]["shared_templates"] = False
    with pytest.raises(ValueError):
        subject.validate_corpus(corpus)


@pytest.mark.parametrize("value", [None, [], "corpus", 1, True])
def test_corpus_validation_requires_exact_object(value):
    with pytest.raises(ValueError, match="closed corpus object"):
        subject.validate_corpus(value)


def test_closed_validation_keeps_all_denominators_without_model_or_label_execution():
    corpus = subject.build_corpus()
    before = copy.deepcopy(corpus)
    result = subject.validate_corpus(corpus)
    assert corpus == before
    assert result["passed"] is True and result["counts"] == corpus["counts"]
    assert result["semantic_gold"] is False
    assert result["legacy_label_execution_performed"] is False
    assert result["model_execution_performed"] is False
    raw = canonical(corpus).encode("utf-8")
    assert result["corpus_sha256"] == hashlib.sha256(raw).hexdigest()


def test_module_is_standard_library_only_and_never_selects_first_occurrence():
    body = Path(subject.__file__).read_text(encoding="utf-8")
    tree = ast.parse(body)
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = [node.module if isinstance(node, ast.ImportFrom) else alias.name
             for node in imports for alias in ([None] if isinstance(node, ast.ImportFrom) else node.names)]
    assert set(names) <= {"__future__", "hashlib", "json"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {"find", "index", "search", "finditer"}
                   and isinstance(node.func.value, ast.Name) and node.func.value.id in {"source", "text"}
                   for node in ast.walk(tree))
    # Only the declared class-order lookup uses index; no text search selects custody.
    assert re.search(r"\b(torch|numpy|transformers|subprocess|requests)\b", body) is None
