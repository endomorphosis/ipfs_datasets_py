"""Audit repair-target identities without supplying a teacher.

A changed authored target changes the split, experiment, and teacher
identities. Semantic distillation scope stays off unless the caller
sets independently_qualified, and this audit never records that set.
Engineering retention stays a separate label. No training runs and no
federal corpus is scored.
"""

from __future__ import annotations

from ipfs_datasets_py.logic.autoformal.supervisor_queue import (
    RepairQueueError,
    repair_target_identities,
)

SCHEMA = "legal-teacher-identity-audit/v1"
TEACHER_IDENTITY_BOUNDARY = """Changed targets invalidate split, experiment and teacher identities.
Only an independently qualified teacher supplies semantic distillation scope.
Engineering retention stays a separate label.
No independently qualified teacher was supplied.
"""


class TeacherIdentityAuditError(ValueError):
    """A changed target kept an identity, or a teacher was invented."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise TeacherIdentityAuditError(message)


def _target(target_id: str, target_text: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "target_id": target_id,
        "target_text": target_text,
        "split_label": "declared-split",
        "experiment_label": "declared-experiment",
        "teacher_label": "declared-unqualified-teacher",
        "engineering_retention": "engineering-retention",
        "independently_qualified": False,
    }
    value.update(overrides)
    return value


def _identities_of(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row["split_identity"]),
        str(row["experiment_identity"]),
        str(row["teacher_identity"]),
    )


def audit_teacher_boundaries(*, refusal: str = "") -> dict[str, object]:
    """Record invalidated target identities and an unsupplied teacher.

    A preserved identity, an adopted qualified teacher, or engineering
    retention used as distillation scope is refused.
    """

    if refusal == "preserved-identity":
        raise TeacherIdentityAuditError("changed targets kept an identity")
    if refusal == "qualified-teacher":
        try:
            qualified = repair_target_identities(
                _target(
                    "authored-target-a",
                    "retain the authored record",
                    independently_qualified=True,
                )
            )
        except RepairQueueError as exc:
            raise TeacherIdentityAuditError("qualified teacher gate failed") from exc
        _need(
            qualified["semantic_distillation_scope_supplied"] is True,
            "qualified teacher gate failed",
        )
        _need(qualified["independently_qualified"] is True, "qualified teacher gate failed")
        raise TeacherIdentityAuditError("independently qualified teacher was invented")
    if refusal == "retention-scope":
        try:
            repair_target_identities(
                _target(
                    "authored-target-a",
                    "retain the authored record",
                    engineering_retention="semantic-distillation-scope",
                )
            )
        except RepairQueueError as exc:
            if "engineering retention supplied distillation scope" not in str(exc):
                raise TeacherIdentityAuditError(
                    "engineering retention supplied distillation scope"
                ) from exc
        else:
            raise TeacherIdentityAuditError(
                "engineering retention supplied distillation scope"
            )
        raise TeacherIdentityAuditError("engineering retention supplied distillation scope")
    if refusal:
        raise TeacherIdentityAuditError("unknown teacher identity refusal")
    first = repair_target_identities(
        _target("authored-target-a", "retain the authored record")
    )
    second = repair_target_identities(
        _target("authored-target-b", "retain the other authored record")
    )
    again = repair_target_identities(
        _target("authored-target-a", "retain the authored record")
    )
    retained = repair_target_identities(
        _target(
            "authored-target-a",
            "retain the authored record",
            engineering_retention="other-engineering-retention",
        )
    )
    first_ids = _identities_of(first)
    second_ids = _identities_of(second)
    _need(first_ids == _identities_of(again), "unchanged target changed an identity")
    _need(len(set(first_ids)) == 3, "target identities collided")
    _need(first_ids != second_ids, "changed targets kept an identity")
    _need(first["split_identity"] != second["split_identity"], "changed targets kept an identity")
    _need(
        first["experiment_identity"] != second["experiment_identity"],
        "changed targets kept an identity",
    )
    _need(
        first["teacher_identity"] != second["teacher_identity"],
        "changed targets kept an identity",
    )
    _need(first["semantic_distillation_scope_supplied"] is False, "distillation scope was supplied")
    _need(second["semantic_distillation_scope_supplied"] is False, "distillation scope was supplied")
    _need(first["independently_qualified"] is False, "independently qualified teacher was invented")
    _need(first["engineering_retention"] == "engineering-retention", "engineering retention moved")
    _need(first_ids == _identities_of(retained), "engineering retention changed an identity")
    _need(
        retained["semantic_distillation_scope_supplied"] is False,
        "engineering retention supplied distillation scope",
    )
    _need(
        retained["engineering_retention"] == "other-engineering-retention",
        "engineering retention is not a separate label",
    )
    _need(first["target_sha256"] != second["target_sha256"], "changed targets kept an identity")
    return {
        "schema": SCHEMA,
        "authored_fixture_only": True,
        "target_count": 2,
        "target_sha256": first["target_sha256"],
        "changed_target_sha256": second["target_sha256"],
        "split_identity": first["split_identity"],
        "changed_split_identity": second["split_identity"],
        "experiment_identity": first["experiment_identity"],
        "changed_experiment_identity": second["experiment_identity"],
        "teacher_identity": first["teacher_identity"],
        "changed_teacher_identity": second["teacher_identity"],
        "split_identity_changed": True,
        "experiment_identity_changed": True,
        "teacher_identity_changed": True,
        "unchanged_target_identities_stable": True,
        "semantic_distillation_scope_supplied": False,
        "independently_qualified_teacher_supplied": False,
        "engineering_retention": "engineering-retention",
        "engineering_retention_separately_labeled": True,
        "retention_identity_unchanged": True,
        "decoder_executed": False,
        "model_executed": False,
        "training_executed": False,
        "worker_launched": False,
        "federal_corpus_scored": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "teacher_promoted": False,
        "admitted": False,
        "formalized": False,
    }
