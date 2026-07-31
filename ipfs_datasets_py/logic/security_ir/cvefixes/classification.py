"""Release-safe classification materialization for every CVEfixes row.

This module intentionally stops before policy inference.  It converts a
validated source row and its exact deterministic projection into:

* an ``audit`` candidate containing only accepted CVE/CWE classifications; and
* a formal view that explicitly records the forbidden action, scope,
  preconditions, and effects as unresolved.

A projected language can be retained as a descriptive, vocabulary-validated
annotation.  It is never inserted into the candidate's policy-match
attributes.  Semantic facts are likewise never promoted into vocabulary
action, effect, precondition, mitigation, or scope terms.

Both records are non-authoritative, content addressed, and bound to the exact
source-row and projection CIDs.  Invalid optional classifications or language
annotations are omitted with a status marker so one malformed optional value
does not make an otherwise validated source row disappear from a public
release.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from .projector import (
    ProjectionResult,
    canonical_source_row_cid,
)
from .schemas import (
    FormalView,
    PolicyCandidate,
    canonical_config_cid,
)
from .source_snapshot import CVEfixesSourceRow
from .vocabulary import (
    CVEFIXES_VOCABULARY_SCHEMA_VERSION,
    CVEfixesPolicyAttributes,
    CVEfixesTerm,
    CVEfixesTermKind,
    CVEfixesVocabularyError,
    cve_classification,
    cwe_classification,
    resolve_cvefixes_term,
)


CLASSIFICATION_MATERIALIZER_VERSION: Final = (
    "cvefixes-classification-materializer/v1"
)
CLASSIFICATION_CONFIG_SCHEMA_VERSION: Final = (
    "cvefixes-classification-materializer-config/v1"
)
UNRESOLVED_FORMALISM: Final = (
    "cvefixes-unresolved-forbidden-constraints-json/v1"
)
CLASSIFICATION_CONFIG_CID: Final = canonical_config_cid(
    {
        "candidate_effect": "audit",
        "classification_terms": ["cve", "cwe"],
        "forbidden_constraint_resolution": "unresolved",
        "language_usage": "descriptive_annotation_only",
        "materializer_version": CLASSIFICATION_MATERIALIZER_VERSION,
        "promote_semantic_facts": False,
        "vocabulary_schema_version": CVEFIXES_VOCABULARY_SCHEMA_VERSION,
    },
    schema_version=CLASSIFICATION_CONFIG_SCHEMA_VERSION,
)


class ClassificationMaterializationError(ValueError):
    """Raised when a projection is not bound to the supplied source row."""


@dataclass(frozen=True, slots=True)
class ClassificationMaterialization:
    """The two non-authoritative records emitted for one source row."""

    candidate: PolicyCandidate
    formal_view: FormalView


def _optional_classification(
    value: str | None,
    *,
    kind: CVEfixesTermKind,
) -> tuple[CVEfixesTerm | None, str]:
    if value is None:
        return None, "absent"
    try:
        if kind is CVEfixesTermKind.CVE:
            return cve_classification(value), "included"
        if kind is CVEfixesTermKind.CWE:
            return cwe_classification(value), "included"
    except CVEfixesVocabularyError:
        return None, "omitted_invalid"
    raise AssertionError(f"unsupported classification kind: {kind!r}")


def _optional_language_annotation(
    projection: ProjectionResult,
) -> tuple[CVEfixesTerm | None, str]:
    try:
        resolved = resolve_cvefixes_term(
            CVEfixesTermKind.LANGUAGE,
            projection.language,
        )
    except CVEfixesVocabularyError:
        return None, "omitted_invalid"
    return resolved.term, "included"


def _unresolved_expression(
    *,
    candidate: PolicyCandidate,
    projection: ProjectionResult,
) -> str:
    expression: dict[str, Any] = {
        "candidate_cid": candidate.cid,
        "classification_only": True,
        "exact_forbidden_constraints": {
            "action": None,
            "effects": [],
            "preconditions": [],
            "scope": None,
        },
        "grants_execution_authority": False,
        "projection_cid": projection.cid,
        "proof_authoritative": False,
        "resolution": "unresolved",
        "statement": (
            "Exact forbidden action and scope constraints remain unresolved."
        ),
    }
    return canonical_json_bytes(expression).decode("utf-8")


def materialize_classification(
    row: CVEfixesSourceRow,
    projection: ProjectionResult,
) -> ClassificationMaterialization:
    """Materialize release-safe classification records for one exact row.

    No source text or semantic predicate is interpreted here.  A caller must
    supply the projection produced for this row under the pinned-row identity;
    cross-row combinations fail closed.
    """

    if not isinstance(row, CVEfixesSourceRow):
        raise TypeError("row must be CVEfixesSourceRow")
    if not isinstance(projection, ProjectionResult):
        raise TypeError("projection must be ProjectionResult")

    source_cid = canonical_source_row_cid(row)
    if projection.source_cid != source_cid:
        raise ClassificationMaterializationError(
            "projection source_cid is not bound to the supplied source row"
        )

    cve, cve_status = _optional_classification(
        row.cve_id,
        kind=CVEfixesTermKind.CVE,
    )
    cwe, cwe_status = _optional_classification(
        row.cwe_id,
        kind=CVEfixesTermKind.CWE,
    )
    language, language_status = _optional_language_annotation(projection)

    attributes = CVEfixesPolicyAttributes(
        cve_ids=(cve,) if cve is not None else (),
        cwe_ids=(cwe,) if cwe is not None else (),
    )
    # This is an invariant, not a recoverable branch: changing the fields
    # above must never silently turn this materializer into policy inference.
    if not attributes.classification_only or attributes.policy_match_terms:
        raise AssertionError(
            "classification materializer created policy match constraints"
        )

    candidate = PolicyCandidate(
        source_cids=(source_cid,),
        parent_cids=(projection.cid,),
        config_cid=CLASSIFICATION_CONFIG_CID,
        effect="audit",
        scope=attributes.to_security_ir_attributes(),
        payload={
            "candidate_role": "classification_only",
            "classification_status": {
                "cve": cve_status,
                "cwe": cwe_status,
            },
            "exact_policy_constraints_present": False,
            "forbidden_constraint_resolution": "unresolved",
            "grants_execution_authority": False,
            "language_annotation": (
                language.to_dict() if language is not None else None
            ),
            "language_annotation_is_policy_constraint": False,
            "language_annotation_status": language_status,
            "materializer_version": CLASSIFICATION_MATERIALIZER_VERSION,
            "projection_cid": projection.cid,
            "projection_config_cid": projection.config_cid,
            "semantic_fact_count": len(projection.semantic_facts),
            "semantic_facts_promoted": False,
            "source_row_index": row.row_index,
        },
    )

    formal_view = FormalView(
        source_cids=(source_cid,),
        parent_cids=(projection.cid, candidate.cid),
        config_cid=CLASSIFICATION_CONFIG_CID,
        formalism=UNRESOLVED_FORMALISM,
        expression=_unresolved_expression(
            candidate=candidate,
            projection=projection,
        ),
        payload={
            "candidate_cid": candidate.cid,
            "classification_only": True,
            "exact_forbidden_action_resolved": False,
            "exact_forbidden_scope_resolved": False,
            "grants_execution_authority": False,
            "materializer_version": CLASSIFICATION_MATERIALIZER_VERSION,
            "projection_cid": projection.cid,
            "proof_authoritative": False,
            "resolution": "unresolved",
        },
    )
    return ClassificationMaterialization(
        candidate=candidate,
        formal_view=formal_view,
    )


# A concise domain spelling for callers assembling a complete release.
materialize_cvefixes_classification = materialize_classification


__all__ = [
    "CLASSIFICATION_CONFIG_CID",
    "CLASSIFICATION_CONFIG_SCHEMA_VERSION",
    "CLASSIFICATION_MATERIALIZER_VERSION",
    "ClassificationMaterialization",
    "ClassificationMaterializationError",
    "UNRESOLVED_FORMALISM",
    "materialize_classification",
    "materialize_cvefixes_classification",
]
