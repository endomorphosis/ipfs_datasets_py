"""Tests for the typed-deontic canonical constructor adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from benchmarks.bench_semantic_logic_roundtrip import _project_legal_norms
from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    ComponentStatus,
    ConstructorRequest,
    FailureReason,
    RoundTripConstructor,
)
from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
    TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE,
    TypedDeonticCanonicalConstructor,
    project_legal_norms,
)


@dataclass
class _Norm:
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.data)


def _vocabulary(
    *,
    actors: tuple[str, ...] = ("agency", "company_a"),
    actions: tuple[str, ...] = ("file", "submit", "withdraw"),
    objects: tuple[str, ...] = ("backup_report", "notice"),
    qualifiers: tuple[str, ...] = (
        "emergency",
        "natural_disaster",
        "within_10_days",
    ),
) -> AllowedAtomVocabulary:
    return AllowedAtomVocabulary(actors, actions, objects, qualifiers)


def _request(
    source_text: str = "Company A shall submit a backup report.",
    vocabulary: AllowedAtomVocabulary | None = None,
) -> ConstructorRequest:
    return ConstructorRequest(source_text, vocabulary or _vocabulary(), {})


def test_projection_emits_every_field_with_explicit_missingness_and_order() -> None:
    norms = [
        _Norm(
            {
                "modality": "permission",
                "norm_type": "permission",
                "actor": "the agency",
                "action": "withdraw the filing",
                "action_verb": "withdraws",
                "action_object": "",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": "must not cross the boundary",
                "native_metadata": {"also": "must not cross"},
            }
        ),
        _Norm(
            {
                "modality": "obligation",
                "norm_type": "obligation",
                "actor": "Company A",
                "action": "submit backup report",
                "action_verb": "submit",
                "action_object": "backup report",
                "conditions": [
                    {"text": "natural disaster"},
                    {"text": "natural disaster"},
                ],
                "exceptions": [{"text": "emergency"}],
                "temporal_constraints": [{"text": "within 10 days"}],
            }
        ),
    ]

    projected = project_legal_norms(norms, _vocabulary())

    assert projected.to_dict() == {
        "rules": [
            {
                "modality": "O",
                "actor": "company_a",
                "action": "submit",
                "object": "backup_report",
                "conditions": ["natural_disaster"],
                "exceptions": ["emergency"],
                "temporal": ["within_10_days"],
            },
            {
                "modality": "P",
                "actor": "agency",
                "action": "withdraw",
                "object": "",
                "conditions": [],
                "exceptions": [],
                "temporal": [],
            },
        ]
    }
    assert set(projected.to_dict()) == {"rules"}
    assert all(
        set(rule)
        == {
            "modality",
            "actor",
            "action",
            "object",
            "conditions",
            "exceptions",
            "temporal",
        }
        for rule in projected.to_dict()["rules"]
    )
    assert "source_text" not in repr(projected)
    assert "native_metadata" not in repr(projected)


def test_projection_matches_existing_typed_pilot_l1_exactly() -> None:
    vocabulary = _vocabulary()
    norms = [
        _Norm(
            {
                "modality": "obligation",
                "norm_type": "obligation",
                "actor": "Company A",
                "action": "submit backup report",
                "action_verb": "submit",
                "action_object": "backup report",
                "conditions": [],
                "exceptions": [{"type": "exception", "text": "emergency"}],
                "temporal_constraints": [
                    {"type": "deadline", "text": "within 10 days"}
                ],
            }
        ),
        _Norm(
            {
                "modality": "forbidden",
                "norm_type": "prohibition",
                "actor": "unknown party",
                "action": "invent",
                "action_verb": "invent",
                "action_object": "unknown object",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
            }
        ),
    ]
    pilot_case = {
        "allowed_atoms": vocabulary.to_dict(),
    }

    assert project_legal_norms(norms, vocabulary).to_dict() == (
        _project_legal_norms(norms, pilot_case)
    )


@pytest.mark.parametrize(
    ("modality", "norm_type", "expected"),
    [
        ("O", "obligation", "O"),
        ("P", "permission", "P"),
        ("F", "prohibition", "F"),
        ("must not", "obligation", "F"),
        ("", "permission", "P"),
    ],
)
def test_projection_supports_all_canonical_modalities(
    modality: str,
    norm_type: str,
    expected: str,
) -> None:
    projected = project_legal_norms(
        [
            _Norm(
                {
                    "modality": modality,
                    "norm_type": norm_type,
                    "actor": "agency",
                    "action": "file",
                    "action_verb": "file",
                    "action_object": "notice",
                }
            )
        ],
        _vocabulary(),
    )

    assert projected.rules[0].modality == expected


def test_constructor_matches_frozen_pilot_l1_for_every_case() -> None:
    """Plateau edit waves may improve L1; never regress vs the audited freeze.

    Exact IR equality remains required for the zero-residual control case.
    Non-zero pilots must not increase forward semantic loss relative to the
    2026-07-26 audited typed_deontic L1 snapshot.
    """

    from benchmarks.semantic_roundtrip.contracts import CanonicalRuleIR
    from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir

    repository_root = Path(__file__).resolve().parents[4]
    fixture_path = (
        repository_root
        / "tests"
        / "fixtures"
        / "semantic_roundtrip"
        / "pilot_cases.json"
    )
    report_path = (
        repository_root
        / "workspace"
        / "benchmarks"
        / "semantic-logic-roundtrip"
        / "2026-07-26-audited-v2"
        / "semantic-roundtrip-report.json"
    )
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    pilot_l1_by_case = {
        case["case_id"]: case["arms"]["typed_deontic"]["l1"]
        for case in report["cases"]
    }
    constructor = TypedDeonticCanonicalConstructor()

    for case in cases:
        vocabulary = AllowedAtomVocabulary.from_dict(case["allowed_atoms"])
        result = constructor.construct(
            ConstructorRequest(case["source_text"], vocabulary, {})
        )

        assert result.status is ComponentStatus.SUCCESS, case["id"]
        assert result.canonical_ir is not None
        assert result.failure_reason is None
        assert not hasattr(result, "native_payload")

        frozen_l1 = CanonicalRuleIR.from_dict(
            pilot_l1_by_case[case["id"]], vocabulary
        )
        gold = CanonicalRuleIR.from_dict(case["gold_ir"], vocabulary)
        new_loss = float(
            compare_semantic_ir(gold, result.canonical_ir)["semantic_loss"]
        )
        frozen_loss = float(
            compare_semantic_ir(gold, frozen_l1)["semantic_loss"]
        )
        assert new_loss <= frozen_loss + 1e-9, (
            f"{case['id']}: forward loss regressed "
            f"{new_loss} > frozen {frozen_loss}"
        )
        if case["id"] == "exception_with_window":
            assert result.canonical_ir.to_dict() == pilot_l1_by_case[case["id"]]


def test_constructor_reports_empty_l1_without_native_payload() -> None:
    constructor = TypedDeonticCanonicalConstructor()

    result = constructor.construct(
        _request("This paragraph contains no normative rule.")
    )

    assert result.status is ComponentStatus.FAILED
    assert result.failure_reason is FailureReason.EMPTY_L1
    assert result.canonical_ir is None
    assert not hasattr(result, "native_payload")


def test_identity_and_constructor_protocol_are_stable() -> None:
    constructor = TypedDeonticCanonicalConstructor()

    assert constructor.identity == "TypedDeonticCanonicalConstructor@1"
    assert (
        constructor.identity
        == TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE
    )
    assert isinstance(constructor, RoundTripConstructor)
