"""Privacy-preserving aggregate analytics helpers."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, Iterable, List, Optional

from .manifest import canonical_bytes
from .models import AggregateResult, AnalyticsContribution
from .privacy import noisy_count


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
    epsilon: Optional[float] = None,
    sensitivity: float = 1.0,
    privacy_budget_key: Optional[str] = None,
    privacy_budget_spent: Optional[float] = None,
    release_exact_count: bool = True,
) -> AggregateResult:
    matching = [item for item in contributions if item.template_id == template_id]
    unique_nullifiers = {item.nullifier for item in matching}
    cohort_size = len(unique_nullifiers)
    released = cohort_size >= min_cohort_size
    privacy_notes: List[str] = [
        "unique-nullifier-counting",
        f"min-cohort-size:{min_cohort_size}",
    ]
    released_count = cohort_size if released else None
    released_cohort_size = cohort_size
    released_noisy_count = None
    released_noise = None
    cohort_size_released = True
    exact_count_released = release_exact_count

    if epsilon is not None:
        if epsilon <= 0:
            raise ValueError("epsilon must be greater than zero")
        if sensitivity <= 0:
            raise ValueError("sensitivity must be greater than zero")
        privacy_notes.extend(
            [
                "differential-privacy:laplace",
                f"epsilon:{epsilon}",
                f"sensitivity:{sensitivity}",
            ]
        )
        if privacy_budget_key is not None:
            privacy_notes.append(f"privacy-budget-key:{privacy_budget_key}")
        if released:
            seed_nullifiers = ",".join(sorted(unique_nullifiers))
            seed_material = f"{template_id}:count:{seed_nullifiers}:{epsilon}:{sensitivity}"
            released_noisy_count, released_noise = noisy_count(
                count=cohort_size,
                epsilon=epsilon,
                sensitivity=sensitivity,
                seed_material=seed_material,
            )
        if not release_exact_count:
            released_count = None
            released_cohort_size = 0
            cohort_size_released = False
            privacy_notes.extend(["exact-count-suppressed", "cohort-size-suppressed"])

    if not released:
        privacy_notes.append("suppressed-small-cohort")
        if epsilon is not None and not release_exact_count:
            released_cohort_size = 0
    return AggregateResult(
        result_id=f"result-{uuid.uuid4().hex}",
        template_id=template_id,
        metric="count",
        released=released,
        suppressed=not released,
        count=released_count,
        cohort_size=released_cohort_size,
        min_cohort_size=min_cohort_size,
        privacy_notes=privacy_notes,
        noisy_count=released_noisy_count,
        epsilon=epsilon,
        noise=released_noise,
        noise_sensitivity=sensitivity if epsilon is not None else None,
        privacy_budget_key=privacy_budget_key,
        privacy_budget_spent=privacy_budget_spent,
        exact_count_released=exact_count_released,
        cohort_size_released=cohort_size_released,
    )
