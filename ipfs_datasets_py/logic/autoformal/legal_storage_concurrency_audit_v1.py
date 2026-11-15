"""Keep storage roles, grants, foreign assets, and caps on separate labels.

Budget-expanded lineage, temporary replay, retained evidence, and publication
overlap stay distinct. A native grant stays an observation. Foreign assets
stay preserved. The recorded ledger cap and external file cap stay unchanged.
This module calls no feed, scores no federal corpus, and records an authored
fixture only.
"""

from __future__ import annotations

SCHEMA = "legal-storage-concurrency-audit/v1"
STORAGE_CONCURRENCY_BOUNDARY = """Budget-expanded lineage, temporary replay, retained evidence and publication overlap stay separate.
A native grant stays purpose-specific to observation.
Foreign claims and assets stay preserved.
Ledger and cap values are not bypassed.
"""

EXTERNAL_FILE_CAP = 134217728
LEDGER_CAP = 16777216
_ROLES = (
    "budget-expanded-lineage",
    "temporary-replay",
    "retained-evidence",
    "publication-overlap",
)


class StorageConcurrencyAuditError(ValueError):
    """A storage role collapsed, a grant widened, or a cap moved."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise StorageConcurrencyAuditError(message)


def audit_storage_concurrency(*, refusal: str = "") -> dict[str, object]:
    """Record the four storage roles and the unchanged caps."""

    roles = _ROLES
    if refusal == "overlap":
        collapsed = tuple(
            "retained-evidence" if role == "publication-overlap" else role for role in roles
        )
        _need(len(set(collapsed)) < len(collapsed), "publication overlap did not replace retained evidence")
        raise StorageConcurrencyAuditError("publication overlap replaced retained evidence")
    if refusal == "grant":
        resource_admission = True
        _need(resource_admission is True, "native grant did not leave observation")
        raise StorageConcurrencyAuditError("native grant left its purpose")
    if refusal == "foreign":
        disposition = "deleted"
        _need(disposition != "preserved", "foreign asset stayed preserved")
        raise StorageConcurrencyAuditError("foreign asset was not preserved")
    if refusal == "cap":
        requested = EXTERNAL_FILE_CAP + 1
        _need(requested > EXTERNAL_FILE_CAP, "requested cap did not exceed the recorded cap")
        raise StorageConcurrencyAuditError("ledger or cap value was bypassed")
    _need(refusal == "", "unknown storage concurrency refusal")
    _need(len(roles) == 4 and len(set(roles)) == 4, "storage roles are not separate")
    _need(roles[2] != roles[3], "publication overlap replaced retained evidence")
    native_grant_purpose = "observation-only"
    _need(native_grant_purpose == "observation-only", "native grant left its purpose")
    resource_admission = False
    ledger_changed = False
    files_deleted = False
    _need(resource_admission is False and ledger_changed is False and files_deleted is False,
          "native grant left its purpose")
    foreign_asset_disposition = "preserved"
    _need(foreign_asset_disposition == "preserved", "foreign asset was not preserved")
    external_file_cap = EXTERNAL_FILE_CAP
    ledger_cap = LEDGER_CAP
    _need(external_file_cap == 134217728 and ledger_cap == 16777216, "ledger or cap value was bypassed")
    _need(external_file_cap < 2**63 and ledger_cap < external_file_cap, "ledger or cap value was bypassed")
    return {
        "schema": SCHEMA,
        "authored_fixture_only": True,
        "role_count": 4,
        "roles_distinct": True,
        "budget_expanded_lineage": roles[0],
        "temporary_replay": roles[1],
        "retained_evidence": roles[2],
        "publication_overlap": roles[3],
        "publication_overlap_replaced_retained": False,
        "native_grant_purpose": native_grant_purpose,
        "native_grant_purpose_specific": True,
        "resource_admission": False,
        "ledger_changed": False,
        "files_deleted": False,
        "foreign_asset_disposition": foreign_asset_disposition,
        "foreign_assets_preserved": True,
        "external_file_cap": external_file_cap,
        "ledger_cap": ledger_cap,
        "cap_bypassed": False,
        "ledger_bypassed": False,
        "decoder_executed": False,
        "model_executed": False,
        "training_executed": False,
        "worker_launched": False,
        "federal_corpus_scored": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }
