"""Privacy-preserving aggregate analytics helpers."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, Iterable, List

from .manifest import canonical_bytes
from .models import AggregateResult, AnalyticsContribution


def contribution_nullifier(wallet_id: str, template_id: str, consent_id: str) -> str:
    """Return a stable per-wallet/per-template nullifier.

    This MVP uses a deterministic hash so duplicate contributions can be
    rejected in tests. Production should derive nullifiers from a wallet secret
    and study domain separator.
    """

    _ = consent_id
    return hashlib.sha256(f"{wallet_id}:{template_id}".encode("utf-8")).hexdigest()


def make_contribution(
    *,
    template_id: str,
    consent_id: str,
    nullifier: str,
    fields: Dict[str, Any],
    proof_id: str,
) -> AnalyticsContribution:
    contribution_id = hashlib.sha256(
        canonical_bytes(
            {
                "template_id": template_id,
                "consent_id": consent_id,
                "nullifier": nullifier,
                "fields": fields,
                "proof_id": proof_id,
            }
        )
    ).hexdigest()
    return AnalyticsContribution(
        contribution_id=f"contrib-{contribution_id[:32]}",
        template_id=template_id,
        consent_id=consent_id,
        nullifier=nullifier,
        fields=dict(fields),
        proof_id=proof_id,
    )


def aggregate_count(
    *,
    template_id: str,
    contributions: Iterable[AnalyticsContribution],
    min_cohort_size: int,
) -> AggregateResult:
    matching = [item for item in contributions if item.template_id == template_id]
    unique_nullifiers = {item.nullifier for item in matching}
    cohort_size = len(unique_nullifiers)
    released = cohort_size >= min_cohort_size
    privacy_notes: List[str] = [
        "unique-nullifier-counting",
        f"min-cohort-size:{min_cohort_size}",
    ]
    if not released:
        privacy_notes.append("suppressed-small-cohort")
    return AggregateResult(
        result_id=f"result-{uuid.uuid4().hex}",
        template_id=template_id,
        metric="count",
        released=released,
        suppressed=not released,
        count=cohort_size if released else None,
        cohort_size=cohort_size,
        min_cohort_size=min_cohort_size,
        privacy_notes=privacy_notes,
    )
