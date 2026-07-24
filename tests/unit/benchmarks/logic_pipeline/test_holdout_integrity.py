"""Executable evidence for frozen split and holdout leakage boundaries."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib

import pytest

import benchmarks.logic_pipeline as logic_pipeline
from benchmarks.logic_pipeline import cases
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    CacheScope,
    DEFAULT_PROTOCOL_SHA256,
    RUN_CONTRACT_SCHEMA,
    RunContract,
    Split,
)


_DIGEST = "a" * 64


@pytest.fixture(scope="module")
def corpus() -> cases.ReviewedCorpus:
    return cases.load_reviewed_corpus()


def _replace_source(
    case: cases.BenchmarkCase,
    source_text: str,
    *,
    prompt_exposure: str = "none",
) -> cases.BenchmarkCase:
    provenance = dict(case.provenance)
    provenance["prompt_exposure"] = prompt_exposure
    return replace(
        case,
        source_text=source_text,
        source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        provenance=provenance,
    )


def _run_contract(
    corpus: cases.ReviewedCorpus,
    *,
    split: Split = Split.HOLDOUT,
    access_id: str | None = "holdout-access-001",
) -> RunContract:
    run_id = "integrity-run-001"
    variant_id = "A0"
    cache_mode = CacheMode.COLD
    return RunContract(
        schema=RUN_CONTRACT_SCHEMA,
        protocol_sha256=DEFAULT_PROTOCOL_SHA256,
        run_id=run_id,
        requested_variant_id=variant_id,
        effective_variant_id=variant_id,
        split=split,
        cache_mode=cache_mode,
        cache_namespace=CacheScope(
            run_id,
            DEFAULT_PROTOCOL_SHA256,
            variant_id,
            split,
            cache_mode,
        ).namespace,
        case_manifest_sha256=corpus.manifest_sha256,
        configuration_sha256=_DIGEST,
        prompts_frozen=True,
        policy_frozen=True,
        model_identities_frozen=True,
        thresholds_frozen=True,
        tuning_permitted=False,
        holdout_access_log_id=access_id,
    )


def _audit(
    corpus: cases.ReviewedCorpus,
    **overrides: object,
) -> cases.HoldoutAccessAudit:
    values: dict[str, object] = {
        "prompts_sha256": _DIGEST,
        "policy_sha256": "b" * 64,
        "model_identities_sha256": "c" * 64,
        "thresholds_sha256": "d" * 64,
        "prompt_examples": {
            "development-example": corpus.cases[10].source_text,
        },
    }
    values.update(overrides)
    return cases.HoldoutAccessAudit.from_run_contract(
        corpus,
        _run_contract(corpus),
        **values,  # type: ignore[arg-type]
    )


def test_objective_evidence_and_public_api_are_stable() -> None:
    assert (
        cases.HSSLEV0232D57()
        == "frozen split integrity and audited leakage-free holdout access"
    )
    assert logic_pipeline.HSSLEV0232D57 is cases.HSSLEV0232D57
    assert cases.SPLIT_MANIFEST_SCHEMA.endswith(".split-manifest.v1")
    assert cases.SPLIT_INTEGRITY_SCHEMA.endswith(".split-integrity.v1")
    assert cases.HOLDOUT_ACCESS_SCHEMA.endswith(".holdout-access.v1")
    assert set(logic_pipeline.__all__) >= {
        "SplitManifest",
        "SplitIntegrityManifest",
        "HoldoutAccessAudit",
        "build_split_integrity_manifest",
        "validate_split_integrity",
    }


def test_default_split_membership_and_digests_are_frozen(
    corpus: cases.ReviewedCorpus,
) -> None:
    integrity = cases.build_split_integrity_manifest(corpus)

    assert integrity is not corpus.split_integrity
    assert integrity == corpus.split_integrity
    assert integrity.integrity_sha256 == (
        "dd68177636a3db87752de54399ed8f066d5fdefe568649d9551bb29a0fb529d0"
    )
    assert integrity.integrity_sha256 == cases.FROZEN_SPLIT_INTEGRITY_SHA256
    assert {
        item.split: item.split_sha256 for item in integrity.splits
    } == dict(cases.FROZEN_SPLIT_SHA256)
    assert tuple(len(item.case_ids) for item in integrity.splits) == (10, 10, 10)
    assert integrity.holdout.case_ids == tuple(
        f"holdout-h{index:02d}" for index in range(1, 11)
    )
    assert cases.frozen_holdout_manifest(corpus) == integrity.holdout


def test_split_manifests_are_deeply_immutable_and_round_trip(
    corpus: cases.ReviewedCorpus,
) -> None:
    integrity = corpus.split_integrity
    restored = cases.SplitIntegrityManifest.from_dict(integrity.to_dict())

    assert restored == integrity
    assert restored.to_dict() == integrity.to_dict()
    with pytest.raises(FrozenInstanceError):
        restored.integrity_sha256 = _DIGEST  # type: ignore[misc]
    with pytest.raises(TypeError):
        restored.by_split[Split.HOLDOUT] = restored.holdout  # type: ignore[index]


@pytest.mark.parametrize(
    "text",
    (
        "  CAFÉ—Rules!! ",
        "ＣＡＦÉ rules",
        "Cafe\u0301\tRULES",
    ),
)
def test_normalization_is_unicode_case_punctuation_and_space_stable(
    text: str,
) -> None:
    assert cases.normalize_source_text(text) == "café rules"


def test_exact_cross_split_duplicate_is_rejected(
    corpus: cases.ReviewedCorpus,
) -> None:
    pilot = corpus.cases[0]
    holdout = replace(
        corpus.cases[20],
        source_text=pilot.source_text,
        source_sha256=pilot.source_sha256,
    )
    candidate = corpus.cases[:20] + (holdout,) + corpus.cases[21:]

    with pytest.raises(cases.CorpusContractError, match="exact source duplicate"):
        cases.validate_split_integrity(candidate)


def test_normalized_cross_split_duplicate_is_rejected(
    corpus: cases.ReviewedCorpus,
) -> None:
    pilot = corpus.cases[0]
    copied = pilot.source_text.swapcase().replace(".", " !!! ").strip()
    holdout = _replace_source(corpus.cases[20], copied)
    candidate = corpus.cases[:20] + (holdout,) + corpus.cases[21:]

    with pytest.raises(
        cases.CorpusContractError, match="normalized source duplicate"
    ):
        cases.validate_split_integrity(candidate)


def test_near_copy_at_frozen_threshold_is_rejected(
    corpus: cases.ReviewedCorpus,
) -> None:
    pilot = corpus.cases[1]
    holdout = _replace_source(corpus.cases[20], pilot.source_text + " Today.")
    assert (
        cases.source_similarity(pilot.source_text, holdout.source_text)
        >= cases.NEAR_DUPLICATE_JACCARD_THRESHOLD
    )
    candidate = corpus.cases[:20] + (holdout,) + corpus.cases[21:]

    with pytest.raises(cases.CorpusContractError, match="near-duplicate source"):
        cases.validate_split_integrity(candidate)


def test_distinct_cross_split_sources_pass_frozen_similarity_policy(
    corpus: cases.ReviewedCorpus,
) -> None:
    cases.validate_split_integrity(corpus.cases)
    cases.validate_split_integrity(corpus)
    assert (
        cases.source_similarity(
            corpus.cases[0].source_text,
            corpus.cases[20].source_text,
        )
        < cases.NEAR_DUPLICATE_JACCARD_THRESHOLD
    )


def test_reused_cross_split_provenance_is_rejected(
    corpus: cases.ReviewedCorpus,
) -> None:
    provenance = dict(corpus.cases[20].provenance)
    provenance["source_ref"] = corpus.cases[0].provenance["source_ref"]
    holdout = replace(corpus.cases[20], provenance=provenance)

    with pytest.raises(cases.CorpusContractError, match="provenance reused"):
        cases.validate_split_integrity(
            corpus.cases[:20] + (holdout,) + corpus.cases[21:]
        )


def test_holdout_prompt_exposure_is_rejected(
    corpus: cases.ReviewedCorpus,
) -> None:
    exposed = _replace_source(
        corpus.cases[20],
        corpus.cases[20].source_text,
        prompt_exposure="few_shot_example",
    )

    with pytest.raises(cases.CorpusContractError, match="holdout prompt leakage"):
        cases.validate_split_integrity(
            corpus.cases[:20] + (exposed,) + corpus.cases[21:]
        )


def test_prompt_example_copy_and_near_copy_are_rejected(
    corpus: cases.ReviewedCorpus,
) -> None:
    holdout = corpus.cases[20]
    with pytest.raises(cases.CorpusContractError, match="holdout source exposed"):
        cases.validate_holdout_prompt_isolation(
            corpus,
            {"copied-example": holdout.source_text.swapcase()},
        )
    with pytest.raises(cases.CorpusContractError, match="holdout near-copy"):
        cases.validate_holdout_prompt_isolation(
            corpus,
            {"near-copy": holdout.source_text + " Today."},
        )


def test_split_manifest_tampering_and_unknown_fields_fail_closed(
    corpus: cases.ReviewedCorpus,
) -> None:
    value = corpus.split_integrity.holdout.to_dict()
    value["case_ids"] = list(reversed(value["case_ids"]))  # type: ignore[arg-type]
    with pytest.raises(cases.CorpusContractError, match="split_sha256"):
        cases.SplitManifest.from_dict(value)
    payload = dict(value)
    payload.pop("split_sha256")
    value["split_sha256"] = hashlib.sha256(
        cases.canonical_json(payload).encode("utf-8")
    ).hexdigest()
    with pytest.raises(cases.CorpusContractError, match="not frozen revision"):
        cases.SplitManifest.from_dict(value)

    value = corpus.split_integrity.to_dict()
    value["unexpected"] = True
    with pytest.raises(cases.CorpusContractError, match="unknown"):
        cases.SplitIntegrityManifest.from_dict(value)


def test_holdout_access_is_auditable_and_deterministic(
    corpus: cases.ReviewedCorpus,
) -> None:
    first = _audit(corpus)
    second = _audit(corpus)

    assert first == second
    assert first.corpus_manifest_sha256 == corpus.manifest_sha256
    assert first.holdout_split_sha256 == cases.FROZEN_SPLIT_SHA256[Split.HOLDOUT]
    assert first.accessed_case_ids == corpus.split_integrity.holdout.case_ids
    assert "/split/holdout/" in first.cache_namespace
    assert first.tuning_permitted is False
    assert first.audit_sha256 == second.audit_sha256
    first.validate_against(corpus)
    assert cases.HoldoutAccessAudit.from_dict(first.to_dict()) == first

    with pytest.raises(FrozenInstanceError):
        first.audit_id = "changed"  # type: ignore[misc]


def test_holdout_access_log_requires_unique_contiguous_audits(
    corpus: cases.ReviewedCorpus,
) -> None:
    first = _audit(corpus)
    second_contract = replace(
        _run_contract(corpus),
        holdout_access_log_id="holdout-access-002",
    )
    second = cases.HoldoutAccessAudit.from_run_contract(
        corpus,
        second_contract,
        prompts_sha256=_DIGEST,
        policy_sha256="b" * 64,
        model_identities_sha256="c" * 64,
        thresholds_sha256="d" * 64,
        prompt_examples={},
        sequence=1,
        purpose="replay",
    )

    cases.validate_holdout_access_log(corpus, (first, second))
    with pytest.raises(cases.CorpusContractError, match="contiguous"):
        cases.validate_holdout_access_log(corpus, (second, first))
    with pytest.raises(cases.CorpusContractError, match="duplicate audit ids"):
        duplicate = cases.HoldoutAccessAudit.from_run_contract(
            corpus,
            _run_contract(corpus),
            prompts_sha256=_DIGEST,
            policy_sha256="b" * 64,
            model_identities_sha256="c" * 64,
            thresholds_sha256="d" * 64,
            prompt_examples={},
            sequence=1,
        )
        cases.validate_holdout_access_log(corpus, (first, duplicate))


def test_holdout_access_rejects_non_holdout_or_foreign_case_ids(
    corpus: cases.ReviewedCorpus,
) -> None:
    with pytest.raises(cases.CorpusContractError, match="holdout run contract"):
        cases.HoldoutAccessAudit.from_run_contract(
            corpus,
            _run_contract(corpus, split=Split.DEVELOPMENT, access_id=None),
            prompts_sha256=_DIGEST,
            policy_sha256=_DIGEST,
            model_identities_sha256=_DIGEST,
            thresholds_sha256=_DIGEST,
            prompt_examples={},
        )
    with pytest.raises(cases.CorpusContractError, match="non-holdout case"):
        _audit(corpus, accessed_case_ids=(corpus.cases[0].case_id,))


def test_holdout_access_rejects_reordered_or_tampered_receipts(
    corpus: cases.ReviewedCorpus,
) -> None:
    with pytest.raises(cases.CorpusContractError, match="frozen manifest order"):
        _audit(
            corpus,
            accessed_case_ids=tuple(
                reversed(corpus.split_integrity.holdout.case_ids)
            ),
        )

    value = _audit(corpus).to_dict()
    value["thresholds_sha256"] = "e" * 64
    with pytest.raises(cases.CorpusContractError, match="audit_sha256"):
        cases.HoldoutAccessAudit.from_dict(value)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("prompts_frozen", False, "selection inputs"),
        ("policy_frozen", False, "selection inputs"),
        ("model_identities_frozen", False, "selection inputs"),
        ("thresholds_frozen", False, "selection inputs"),
        ("tuning_permitted", True, "tuning is forbidden"),
    ),
)
def test_serialized_holdout_access_cannot_relax_freeze_or_tuning(
    corpus: cases.ReviewedCorpus,
    field: str,
    value: bool,
    message: str,
) -> None:
    data = _audit(corpus).to_dict()
    data[field] = value
    payload = dict(data)
    payload.pop("audit_sha256")
    data["audit_sha256"] = hashlib.sha256(
        cases.canonical_json(payload).encode("utf-8")
    ).hexdigest()

    with pytest.raises(cases.CorpusContractError, match=message):
        cases.HoldoutAccessAudit.from_dict(data)
