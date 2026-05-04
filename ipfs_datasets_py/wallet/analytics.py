"""Privacy-preserving aggregate analytics helpers."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
                "noise-source:system-random",
            ]
        )
        if privacy_budget_key is not None:
            privacy_notes.append(f"privacy-budget-key:{privacy_budget_key}")
        if released:
            released_noisy_count, released_noise = noisy_count(
                count=cohort_size,
                epsilon=epsilon,
                sensitivity=sensitivity,
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


def aggregate_count_by_fields(
    *,
    template_id: str,
    contributions: Iterable[AnalyticsContribution],
    group_by: List[str],
    min_cohort_size: int,
    epsilon: Optional[float] = None,
    sensitivity: float = 1.0,
    privacy_budget_key: Optional[str] = None,
    privacy_budget_spent: Optional[float] = None,
    release_exact_count: bool = True,
) -> AggregateResult:
    if not group_by:
        raise ValueError("group_by must include at least one field")
    if len(set(group_by)) != len(group_by):
        raise ValueError("group_by fields must be unique")

    matching = [item for item in contributions if item.template_id == template_id]
    cohorts_by_key: Dict[Tuple[Tuple[str, str], ...], Dict[str, Any]] = {}
    for contribution in matching:
        if not set(group_by).issubset(contribution.fields):
            continue
        key = tuple((field, _cohort_key_value(contribution.fields[field])) for field in group_by)
        cohort = cohorts_by_key.setdefault(
            key,
            {
                "fields": {field: contribution.fields[field] for field in group_by},
                "nullifiers": set(),
            },
        )
        cohort["nullifiers"].add(contribution.nullifier)

    privacy_notes: List[str] = [
        "unique-nullifier-counting",
        f"min-cohort-size:{min_cohort_size}",
        f"group-by:{','.join(group_by)}",
        "sparse-cell-suppression",
    ]
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
                "noise-source:system-random",
                "cohort-noise:per-cell",
            ]
        )
        if privacy_budget_key is not None:
            privacy_notes.append(f"privacy-budget-key:{privacy_budget_key}")

    released_cohorts: List[Dict[str, Any]] = []
    suppressed_cohort_count = 0
    total_released_count = 0
    total_noisy_count = 0.0
    has_noisy_count = False
    for cohort in cohorts_by_key.values():
        cohort_size = len(cohort["nullifiers"])
        if cohort_size < min_cohort_size:
            suppressed_cohort_count += 1
            continue

        noisy_value = None
        noise = None
        if epsilon is not None:
            noisy_value, noise = noisy_count(
                count=cohort_size,
                epsilon=epsilon,
                sensitivity=sensitivity,
            )
            total_noisy_count += noisy_value
            has_noisy_count = True

        released_cohorts.append(
            {
                "fields": dict(cohort["fields"]),
                "released": True,
                "suppressed": False,
                "count": cohort_size if release_exact_count else None,
                "cohort_size": cohort_size if release_exact_count else 0,
                "noisy_count": noisy_value,
                "noise": noise,
            }
        )
        total_released_count += cohort_size

    released_cohorts.sort(key=lambda item: canonical_bytes(item["fields"]))
    released = bool(released_cohorts)
    suppressed = suppressed_cohort_count > 0 or not released
    if suppressed_cohort_count:
        privacy_notes.append(f"suppressed-cohorts:{suppressed_cohort_count}")
    if not released:
        privacy_notes.append("suppressed-small-cohort")
    if epsilon is not None and not release_exact_count:
        privacy_notes.extend(["exact-count-suppressed", "cohort-size-suppressed"])

    return AggregateResult(
        result_id=f"result-{uuid.uuid4().hex}",
        template_id=template_id,
        metric="count_by_fields",
        released=released,
        suppressed=suppressed,
        count=total_released_count if released and release_exact_count else None,
        cohort_size=total_released_count if release_exact_count else 0,
        min_cohort_size=min_cohort_size,
        privacy_notes=privacy_notes,
        noisy_count=total_noisy_count if has_noisy_count else None,
        epsilon=epsilon,
        noise=None,
        noise_sensitivity=sensitivity if epsilon is not None else None,
        privacy_budget_key=privacy_budget_key,
        privacy_budget_spent=privacy_budget_spent,
        exact_count_released=release_exact_count,
        cohort_size_released=release_exact_count,
        group_by=list(group_by),
        cohorts=released_cohorts,
        suppressed_cohort_count=suppressed_cohort_count,
    )


def _cohort_key_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    return canonical_bytes(value).decode("utf-8")
