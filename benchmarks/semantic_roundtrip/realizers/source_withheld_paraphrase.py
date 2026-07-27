"""Source-withheld deterministic paraphrasing for replacement experiments.

This adapter is deliberately separate from the frozen deterministic realizer.
It accepts the public :class:`RealizerRequest` boundary only and uses a single
frozen grammar profile.  In particular, it has no source-text argument,
constructor reference, file lookup, cache, or mutable state from which the
originating case could be recovered.

The replacement profile changes the obligation surface from ``shall`` to the
typed-constructor-supported ``must``.  Permission and prohibition retain
explicit, distinct ``may`` and ``must not`` constructions.  The change avoids
copying source sentences that use ``shall`` while preserving the canonical
modality and all scored qualifier facets.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    ComponentStatus,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
    RoundTripRealizer,
)


SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE: Final = (
    "SourceWithheldCanonicalParaphraser@1"
)
SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_INTERFACE: Final = (
    "SourceWithheldParaphraseAttribution@1"
)
SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-source-withheld-paraphrase-attribution.v1"
)

# Every value is scalar so the exported immutable mapping and its public wire
# representation are identical.  A request must carry this exact profile;
# arbitrary decoder options, case labels, and other potential side channels
# are rejected rather than ignored.
FROZEN_REPLACEMENT_CONFIG: Final[Mapping[str, str]] = MappingProxyType(
    {
        "profile": "typed_deontic_must_paraphrase_v1",
        "atom_surface": "underscore_to_space_v1",
        "obligation_surface": "must",
        "permission_surface": "may",
        "prohibition_surface": "must not",
        "temporal_position": "before_conditions",
        "condition_connector": "if",
        "exception_connector": "unless",
        "rule_order": "canonical_rule_ir_v1",
    }
)
FROZEN_REPLACEMENT_CONFIG_CID: Final = cid_for_dag_json(
    dict(FROZEN_REPLACEMENT_CONFIG)
)

_MODAL_PHRASES: Final = MappingProxyType(
    {
        "O": FROZEN_REPLACEMENT_CONFIG["obligation_surface"],
        "P": FROZEN_REPLACEMENT_CONFIG["permission_surface"],
        "F": FROZEN_REPLACEMENT_CONFIG["prohibition_surface"],
    }
)
_PUBLIC_INPUT_FIELDS: Final = (
    "canonical_ir",
    "allowed_atom_vocabulary",
    "config",
)
_EXCLUDED_INPUT_CHANNELS: Final = (
    "t0",
    "gold_ir",
    "native_records",
    "source_bearing_caches",
    "hidden_case_fields",
)
SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID: Final = cid_for_dag_json(
    {
        "interface": SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE,
        "replacement_config_cid": FROZEN_REPLACEMENT_CONFIG_CID,
        "accepted_input_fields": list(_PUBLIC_INPUT_FIELDS),
        "excluded_input_channels": list(_EXCLUDED_INPUT_CHANNELS),
        "stateless": True,
        "deterministic": True,
    }
)


def frozen_replacement_config() -> dict[str, str]:
    """Return a detached public copy of the one accepted configuration."""

    return dict(FROZEN_REPLACEMENT_CONFIG)


def _readable_atom(atom: str) -> str:
    """Render one already-validated closed-vocabulary atom deterministically."""

    return " ".join(atom.replace("_", " ").split())


def _join_atoms(atoms: tuple[str, ...], conjunction: str) -> str:
    return f" {conjunction} ".join(_readable_atom(atom) for atom in atoms)


def paraphrase_rule(rule: CanonicalRule) -> str:
    """Render all canonical facets with the frozen polarity-safe grammar."""

    if not isinstance(rule, CanonicalRule):
        raise ContractError("rule must be CanonicalRule")

    parts = [
        _readable_atom(rule.actor),
        _MODAL_PHRASES[rule.modality],
        _readable_atom(rule.action),
    ]
    if rule.object:
        parts.append(_readable_atom(rule.object))

    sentence = " ".join(parts)
    if rule.temporal:
        sentence += " " + _join_atoms(rule.temporal, "and")
    if rule.conditions:
        sentence += (
            f" {FROZEN_REPLACEMENT_CONFIG['condition_connector']} "
            + _join_atoms(rule.conditions, "and")
        )
    if rule.exceptions:
        sentence += (
            f" {FROZEN_REPLACEMENT_CONFIG['exception_connector']} "
            + _join_atoms(rule.exceptions, "or")
        )

    # RealizerRequest vocabulary validation guarantees nonempty actor/action
    # atoms for the benchmark inputs.  CanonicalRule itself permits empty
    # strings, so fail closed if this lower-level helper is called directly
    # with a rule that cannot form a bounded sentence.
    if not sentence:
        raise ContractError("rule cannot produce a nonblank sentence")
    return sentence[0].upper() + sentence[1:] + "."


def _configuration_matches(config: Mapping[str, object]) -> bool:
    return dict(config) == dict(FROZEN_REPLACEMENT_CONFIG)


def _attribution_receipt(
    request: RealizerRequest,
    reconstruction: str,
) -> dict[str, object]:
    """Bind every available input and the output without any source channel."""

    request_payload = request.to_payload()
    body: dict[str, object] = {
        "interface": SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_INTERFACE,
        "schema_version": SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_SCHEMA,
        "realizer_identity": SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE,
        "rendering_spec_cid": (
            SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID
        ),
        "deterministic": True,
        "source_withheld": True,
        "observed_input_fields": list(_PUBLIC_INPUT_FIELDS),
        "excluded_input_channels": list(_EXCLUDED_INPUT_CHANNELS),
        "input_attribution": {
            "canonical_l1_cid": cid_for_dag_json(
                request.canonical_ir.to_dict()
            ),
            "public_closed_vocabulary_cid": cid_for_dag_json(
                request.allowed_atom_vocabulary.to_dict()
            ),
            "frozen_replacement_config_cid": (
                FROZEN_REPLACEMENT_CONFIG_CID
            ),
            "public_request_cid": cid_for_dag_json(request_payload),
        },
        "output_attribution": {
            "t1_cid": cid_for_bytes(reconstruction.encode("utf-8")),
            "character_count": len(reconstruction),
        },
    }
    return {**body, "receipt_cid": cid_for_dag_json(body)}


class SourceWithheldCanonicalParaphraser:
    """Stateless replacement-experiment implementation of RoundTripRealizer."""

    __slots__ = ()

    @property
    def identity(self) -> str:
        return SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE

    def realize(self, request: RealizerRequest) -> RealizerResult:
        """Render only canonical L1 under the exact frozen public profile."""

        if not isinstance(request, RealizerRequest):
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=FailureReason.INVALID_OUTPUT,
                failure_detail="request must be RealizerRequest",
            )
        if not _configuration_matches(request.config):
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=FailureReason.INVALID_OUTPUT,
                failure_detail=(
                    "config must equal the frozen replacement configuration "
                    f"{FROZEN_REPLACEMENT_CONFIG_CID}"
                ),
            )
        if request.canonical_ir.is_empty:
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=FailureReason.EMPTY_L1,
                failure_detail="canonical IR contains no rules",
            )

        try:
            text = " ".join(
                paraphrase_rule(rule)
                for rule in request.canonical_ir.rules
            )
            return RealizerResult(
                status=ComponentStatus.SUCCESS,
                text=text,
            )
        except ContractError as exc:
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=FailureReason.INVALID_OUTPUT,
                failure_detail=str(exc),
            )

    def realize_with_attribution(
        self,
        request: RealizerRequest,
    ) -> tuple[RealizerResult, dict[str, object] | None]:
        """Return the ordinary result plus a deterministic CID-bound receipt."""

        result = self.realize(request)
        if result.status is not ComponentStatus.SUCCESS:
            return result, None
        assert result.text is not None
        return result, _attribution_receipt(request, result.text)

    # The taskboard calls this evidence a repair receipt.  Keep an explicit
    # alias so replacement-run orchestration need not depend on prose naming.
    realize_with_receipt = realize_with_attribution


assert isinstance(SourceWithheldCanonicalParaphraser(), RoundTripRealizer)


SourceWithheldParaphraser = SourceWithheldCanonicalParaphraser
DeterministicSourceWithheldParaphraser = SourceWithheldCanonicalParaphraser


__all__ = [
    "DeterministicSourceWithheldParaphraser",
    "FROZEN_REPLACEMENT_CONFIG",
    "FROZEN_REPLACEMENT_CONFIG_CID",
    "SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE",
    "SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_INTERFACE",
    "SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_SCHEMA",
    "SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID",
    "SourceWithheldCanonicalParaphraser",
    "SourceWithheldParaphraser",
    "frozen_replacement_config",
    "paraphrase_rule",
]
