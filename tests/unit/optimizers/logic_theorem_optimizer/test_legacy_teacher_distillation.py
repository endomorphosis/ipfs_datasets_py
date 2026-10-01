"""Teacher weak labels never turn 8D features into current 384D embeddings."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_teacher_distillation as seam
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_cached import CachedLinguisticAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import LegalModalParser


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


@pytest.fixture(scope="module")
def fixtures():
    legacy = CachedLinguisticAutoencoder(compute_device="cpu")
    teacher = LegacyLinguisticTeacher(legacy)
    parser = LegalModalParser()
    texts = ["The officer shall retain the file for at least 20 days.",
             "The agency shall not disclose records.",
             "The agency may not disclose records.",
             "Company A shall submit backup report within 10 days unless emergency."]
    pairs = []
    for index, text in enumerate(texts):
        old_sample = legacy.build_sample(title="fixture", section=str(index), text=text)
        teacher_row = teacher.distillation_row(old_sample, corpus="authored_fixture")
        student = current_v2.LegalSample(sample_id=old_sample.sample_id, source="us_code",
            title=old_sample.title, section=old_sample.section, citation=old_sample.citation,
            text=text, normalized_text=parser.normalize_text(text),
            embedding_model="test:synthetic-384d-not-semantic",
            embedding_vector=[(index + 1) * 0.001] * 384,
            modal_ir=parser.parse(text, document_id=old_sample.sample_id, source="us_code"))
        pairs.append((student, teacher_row))
    return pairs


def prepare(pairs, **options):
    samples, rows = map(list, zip(*pairs))
    first = rows[0]
    kwargs = dict(expected_teacher_identity_sha256=first["evidence"]["model_binding"]["linguistic_identity_sha256"],
                  expected_producer_sha256=first["source_binding"]["producer_sha256"],
                  teacher_artifact_sha256=digest(rows), split="train")
    kwargs.update(options)
    return seam.prepare_teacher_distillation(samples, rows, **kwargs)


def test_real_teacher_screening_passes_only_weak_targets_with_separate_384_inputs(fixtures):
    pairs = deepcopy(fixtures[:3])
    prepared = prepare(pairs)
    assert prepared.receipt["accepted_count"] == 2
    assert prepared.receipt["rejected_count"] == 1
    assert prepared.receipt["rejected"][0]["reason"] == "feature_only: no screened formula target"
    assert prepared.receipt["accepted"][0]["temporal_records"] == [
        {"temporal_kind": "minimum_duration", "value": "20 days", "quantity": 20}]
    samples, targets = prepared.training_inputs()
    assert len(samples[0].embedding_vector) == 384
    assert samples[0].embedding_vector == pairs[0][0].embedding_vector
    assert samples[0].embedding_vector != pairs[0][1]["feature_target"]
    assert set(targets[0]) == {"id", "source_text", "canonical_ir"}
    assert targets[0]["canonical_ir"] == pairs[0][1]["formula_target"]
    assert prepared.receipt["accepted"][0]["teacher_row_sha256"] == digest(pairs[0][1])
    assert prepared.receipt["accepted"][0]["student_sample_sha256"] == digest(pairs[0][0].to_dict())
    assert prepared.receipt["feature_target_used"] is False
    assert prepared.receipt["temporal_sidecar_encoded_by_formula_head"] is False
    assert prepared.receipt["source_only_fidelity_evaluation"] is False
    assert "not authenticated" in prepared.receipt["integrity_scope"]
    for field in seam.FALSE:
        assert prepared.receipt[field] is False


def test_closed_targets_are_consumable_by_current_joint_head(fixtures):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula
    prepared = prepare(deepcopy(fixtures[:2]))
    model = current_v2.Autoencoder(compute_device="cpu")
    samples, targets = prepared.training_inputs()
    rows = modal_joint_formula._rows(model, samples, targets)
    assert len(rows) == 2
    assert len(rows[0]["latent"]) == len(rows[0]["embedding"]) == 384
    assert rows[0]["canonical_ir"] == targets[0]["canonical_ir"]
    assert model.state.feature_embedding_weights == {}


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r.update(sample_id="other"), "no student sample"),
    (lambda r: r.update(source_text=r["source_text"] + " changed"), "exact student sample ID and text"),
    (lambda r: r["source_binding"].update(sha256="a" * 64), "source SHA-256 differs"),
    (lambda r: r["source_binding"].update(producer_sha256="a" * 64), "producer SHA-256 differs"),
    (lambda r: r["source_binding"].update(corpus="constitution"), "Constitution"),
    (lambda r: r["source_binding"].update(corpus="unknown"), "source corpus"),
    (lambda r: r["source_binding"].pop("sample_sha256"), "provenance"),
    (lambda r: r["evidence"]["model_binding"].update(linguistic_identity_sha256="a" * 64), "identity SHA-256 differs"),
    (lambda r: r["evidence"]["model_binding"]["linguistic_identity"].update(backend="changed"), "identity SHA-256 differs"),
    (lambda r: r["distillation_mask"].update(historical_formula=True), "masks"),
    (lambda r: r["distillation_mask"].update(compiler_supervised_formula=1), "masks"),
    (lambda r: r["evidence"].update(status="feature_only"), "screening disposition"),
    (lambda r: r["evidence"].update(reasons=["unsupported_scope"]), "screening disposition"),
    (lambda r: r["evidence"]["compiler"].update(cycle_equal=False), "exact-cycle"),
    (lambda r: r["evidence"]["compiler"].update(vocabulary_source="fallback"), "exact-cycle"),
    (lambda r: r["evidence"]["compiler"]["receipt"].update(unsupported_semantics=["scope"]), "receipt contradicts"),
    (lambda r: r["evidence"]["compiler"].pop("temporal_records"), "temporal sidecar"),
    (lambda r: r["evidence"]["compiler"]["temporal_records"][0].update(quantity=21), "quantity contradicts"),
    (lambda r: r["evidence"]["compiler"]["temporal_records"][0].update(value="21 days"), "sidecar differs"),
    (lambda r: r.update(formula_target={"rules": []}), "differs from compiler"),
    (lambda r: r.update(formula_target_origin="independent_neural_formula"), "unsupported origin"),
    (lambda r: r.update(admitted=True), "unsupported authority"),
    (lambda r: r["evidence"].update(roundtrip_ok=True), "unsupported authority"),
    (lambda r: r["evidence"].update(semantic_embedding_verified=True), "unsupported qualification"),
    (lambda r: r.update(feature_target=[0.] * 384), "expected 8 values"),
])
def test_mutated_or_unqualified_teacher_rows_are_rejected_with_original_digests(fixtures, mutation, reason):
    pairs = deepcopy(fixtures[:1])
    expected_identity = pairs[0][1]["evidence"]["model_binding"]["linguistic_identity_sha256"]
    expected_producer = pairs[0][1]["source_binding"]["producer_sha256"]
    mutation(pairs[0][1])
    prepared = prepare(pairs, expected_teacher_identity_sha256=expected_identity,
                       expected_producer_sha256=expected_producer)
    assert prepared.student_samples == ()
    assert prepared.formula_targets == ()
    rejection = prepared.receipt["rejected"][0]
    assert reason in rejection["reason"]
    assert rejection["teacher_row_sha256"] == digest(pairs[0][1])


def test_forged_formula_mask_on_real_feature_only_evidence_is_rejected(fixtures):
    pairs = deepcopy(fixtures[2:3])
    row = pairs[0][1]
    row["distillation_mask"]["compiler_supervised_formula"] = True
    row["formula_target"] = row["evidence"]["corrected_ir"]
    assert prepare(pairs).receipt["accepted_count"] == 0


def test_coherent_empty_rule_with_temporal_sidecar_is_rejected_before_indexing(fixtures):
    pairs = deepcopy(fixtures[:1])
    row = pairs[0][1]
    target = {"rules": []}
    row["formula_target"] = target
    row["evidence"]["corrected_ir"] = target
    row["evidence"]["compiler"]["rules"] = target["rules"]
    row["evidence"]["compiler"]["receipt"]["canonical_ir"] = target
    assert row["evidence"]["compiler"]["temporal_records"]
    result = prepare(pairs)
    assert result.receipt["accepted_count"] == 0
    assert result.receipt["rejected_count"] == 1
    assert "requires exactly one rule" in result.receipt["rejected"][0]["reason"]
    assert result.receipt["rejected"][0]["teacher_row_sha256"] == digest(row)


def set_target_temporal(row, atoms):
    target = deepcopy(row["formula_target"])
    target["rules"][0]["temporal"] = atoms
    row["formula_target"] = target
    row["evidence"]["corrected_ir"] = target
    row["evidence"]["compiler"]["rules"] = target["rules"]
    row["evidence"]["compiler"]["receipt"]["canonical_ir"] = target


@pytest.mark.parametrize("index,atom", [(0, "20 days"), (3, "within 10 days"), (3, "10 days")])
def test_head_and_prior_canonical_temporal_atoms_preserve_exact_targets(fixtures, index, atom):
    pairs = [deepcopy(fixtures[index])]
    row = pairs[0][1]
    set_target_temporal(row, [atom])
    before = deepcopy(row)
    prepared = prepare(pairs)
    assert prepared.receipt["accepted_count"] == 1
    assert prepared.formula_targets[0]["canonical_ir"] == before["formula_target"]
    assert prepared.receipt["accepted"][0]["temporal_records"] == before["evidence"]["compiler"]["temporal_records"]
    if index == 3:
        assert prepared.formula_targets[0]["canonical_ir"]["rules"][0]["exceptions"] == ["emergency"]
    else:
        assert prepared.receipt["accepted"][0]["temporal_records"][0]["quantity"] == 20
    assert row == before


@pytest.mark.parametrize("index,atom,kind,quantity", [
    (3, "after 10 days", "within_duration", 10),
    (3, "before 10 days", "within_duration", 10),
    (3, "at least 10 days", "within_duration", 10),
    (3, "within 10 days", "minimum_duration", 10),
    (3, "10 days", "minimum_duration", 10),
    (3, "within 11 days", "within_duration", 10),
    (3, "within 10 days", "within_duration", 11),
    (0, "20 days", "within_duration", 20),
    (0, "within 20 days", "minimum_duration", 20),
])
def test_temporal_compatibility_never_erases_kind_or_quantity(fixtures, index, atom, kind, quantity):
    pairs = [deepcopy(fixtures[index])]
    row = pairs[0][1]
    set_target_temporal(row, [atom])
    row["evidence"]["compiler"]["temporal_records"][0].update(temporal_kind=kind, quantity=quantity)
    prepared = prepare(pairs)
    assert prepared.receipt["accepted_count"] == 0
    assert prepared.receipt["rejected_count"] == 1
    assert "temporal" in prepared.receipt["rejected"][0]["reason"]


@pytest.mark.parametrize("index", [0, 3])
def test_temporal_gate_without_typed_sidecar_cannot_supply_a_formula_target(fixtures, index):
    pairs = [deepcopy(fixtures[index])]
    row = pairs[0][1]
    assert row["formula_target"]["rules"][0]["temporal"]
    row["evidence"]["compiler"]["temporal_records"] = []
    prepared = prepare(pairs)
    assert prepared.receipt["accepted_count"] == 0
    assert prepared.receipt["rejected_count"] == 1
    assert prepared.receipt["rejected"][0]["reason"] == "temporal sidecar count differs from target atoms"


def test_missing_and_extra_rows_are_explicit_and_reordering_uses_exact_ids(fixtures):
    pairs = deepcopy(fixtures[:2])
    samples, rows = map(list, zip(*pairs))
    options = dict(expected_teacher_identity_sha256=rows[0]["evidence"]["model_binding"]["linguistic_identity_sha256"],
                   expected_producer_sha256=rows[0]["source_binding"]["producer_sha256"],
                   teacher_artifact_sha256=digest(rows), split="train")
    result = seam.prepare_teacher_distillation(samples, list(reversed(rows)), **options)
    assert [row["id"] for row in result.formula_targets] == [sample.sample_id for sample in reversed(samples)]
    result = seam.prepare_teacher_distillation(samples, rows[:1], **options)
    assert result.receipt["rejected"][0]["reason"] == "student sample has no teacher row"
    result = seam.prepare_teacher_distillation(samples[:1], rows, **options)
    assert result.receipt["rejected"][0]["reason"] == "teacher row has no student sample"


def test_receipts_targets_and_returned_samples_are_copy_safe(fixtures):
    pairs = deepcopy(fixtures[:1])
    result = prepare(pairs)
    expected_receipt, expected_target = result.receipt, result.formula_targets
    result.receipt["accepted"][0]["temporal_records"].clear()
    result.formula_targets[0]["canonical_ir"]["rules"].clear()
    copied_samples, copied_targets = result.training_inputs()
    copied_samples[0].embedding_vector[0] = 999
    copied_targets[0]["canonical_ir"]["rules"].clear()
    assert result.receipt == expected_receipt
    assert result.formula_targets == expected_target
    assert result.student_samples[0].embedding_vector[0] != 999
    pairs[0][1]["source_binding"]["corpus"] = "constitution"
    assert result.receipt == expected_receipt


@pytest.mark.parametrize("mutation", [
    lambda s: s.embedding_vector.__setitem__(0, 999),
    lambda s: s.modal_ir.formulas.clear(),
    lambda s: s.parser_trace.update(injected="change"),
])
def test_mutating_original_student_inputs_after_prep_cannot_silently_change_training(fixtures, mutation):
    pairs = deepcopy(fixtures[:1])
    result = prepare(pairs)
    mutation(pairs[0][0])
    with pytest.raises(ValueError, match="changed after preparation"):
        result.training_inputs()


@pytest.mark.parametrize("split", ["tuning", "holdout"])
def test_later_splits_require_explicit_source_exclusion_and_reject_overlap(fixtures, split):
    pairs = deepcopy(fixtures[:1])
    with pytest.raises(ValueError, match="require excluded sources"):
        prepare(pairs, split=split)
    with pytest.raises(ValueError, match="overlaps an excluded split"):
        prepare(pairs, split=split, excluded_source_texts=["  " + pairs[0][0].text.upper() + "  "])
    with pytest.raises(ValueError, match="overlaps an excluded split"):
        prepare(pairs, split=split, excluded_source_texts=["different prior text"],
                excluded_sample_ids=[pairs[0][0].sample_id])
    result = prepare(pairs, split=split, excluded_source_texts=["different prior text"])
    assert result.receipt["accepted_count"] == 1


def test_duplicate_and_bounded_inputs_fail_before_preparation(fixtures):
    pairs = deepcopy(fixtures[:1])
    with pytest.raises(ValueError, match="unique nonempty"):
        prepare(pairs * 2)
    with pytest.raises(ValueError, match="exceeds 256"):
        prepare(pairs * 257)
    with pytest.raises(ValueError, match="expected 384"):
        prepare([(replace(pairs[0][0], embedding_vector=[0.] * 8), pairs[0][1])])
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        prepare(pairs, expected_producer_sha256="")


def test_sample_source_metadata_binding_checked_even_when_teacher_ids_match(fixtures):
    pairs = deepcopy(fixtures[:1])
    sample, row = pairs[0]
    mismatched_ir = replace(sample.modal_ir, document_id="different")
    with pytest.raises(ValueError, match="parser features have inconsistent source binding"):
        prepare([(replace(sample, modal_ir=mismatched_ir), row)])


def test_preparation_checks_total_bytes_even_with_no_teacher_rows(fixtures, monkeypatch):
    student, row = deepcopy(fixtures[0])
    monkeypatch.setattr(seam, "MAX_BATCH_BYTES", 1)
    with pytest.raises(ValueError, match="preparation exceeds byte bound"):
        seam.prepare_teacher_distillation([student], [],
            expected_teacher_identity_sha256=row["evidence"]["model_binding"]["linguistic_identity_sha256"],
            expected_producer_sha256=row["source_binding"]["producer_sha256"],
            teacher_artifact_sha256=digest([]), split="train")


def test_missing_teacher_receipts_preserve_student_input_order(fixtures):
    pairs = deepcopy(fixtures[:2])
    students = [replace(pairs[0][0], sample_id="z", modal_ir=replace(pairs[0][0].modal_ir, document_id="z")),
                replace(pairs[1][0], sample_id="a", modal_ir=replace(pairs[1][0].modal_ir, document_id="a"))]
    row = pairs[0][1]
    result = seam.prepare_teacher_distillation(students, [],
        expected_teacher_identity_sha256=row["evidence"]["model_binding"]["linguistic_identity_sha256"],
        expected_producer_sha256=row["source_binding"]["producer_sha256"],
        teacher_artifact_sha256=digest([]), split="train")
    assert [r["sample_id"] for r in result.receipt["rejected"]] == ["z", "a"]


def test_duplicate_teacher_id_cannot_silently_choose_an_observation(fixtures):
    sample, row = deepcopy(fixtures[0])
    with pytest.raises(ValueError, match="duplicate teacher sample ID"):
        seam.prepare_teacher_distillation([sample], [row, deepcopy(row)],
            expected_teacher_identity_sha256=row["evidence"]["model_binding"]["linguistic_identity_sha256"],
            expected_producer_sha256=row["source_binding"]["producer_sha256"],
            teacher_artifact_sha256=digest([row, row]), split="train")
