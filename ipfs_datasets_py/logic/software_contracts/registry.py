"""Reviewed software-contract registry (DSCON-G200).

:class:`ContractRegistry` is the sole mutable-assembly surface for reviewed
callable contracts.  Insertion is fail-closed: duplicate IDs, lower-authority
overrides of higher-authority facts, and direct predicate contradictions become
:class:`ContractFinding` records rather than silent merges.

The registry itself is immutable once built.  Serialization is a
:class:`~ipfs_datasets_py.logic.software_contracts.contracts.ContractDocument`
whose CID is stable under the software-contract content profile.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Iterable, Iterator, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.contracts import (
    AUTHORITY_RANK_ORDER,
    GOAL_ID,
    SOFTWARE_CONTRACT_SCHEMA,
    TASK_ID,
    BoundedPredicate,
    CallableContract,
    ContractDocument,
    ContractFinding,
    ContractIRError,
    EffectContract,
    ResourceContract,
)


REGISTRY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.contract-registry@1"
)


class ContractRegistryError(ContractIRError):
    """Raised when registry construction or lookup fails closed."""


def _predicate_conflict_key(predicate: BoundedPredicate) -> tuple[str, str, str]:
    """Identity of a predicate for contradiction checks (role, operator, subject)."""

    return (predicate.role, predicate.operator, predicate.subject)


def _effect_conflict_key(effect: EffectContract) -> tuple[str, str, str]:
    return (effect.kind, effect.operation, effect.subject)


def _resource_conflict_key(resource: ResourceContract) -> str:
    return resource.kind


def _arguments_equal(left: Sequence[Any], right: Sequence[Any]) -> bool:
    return list(left) == list(right)


def detect_callable_conflicts(
    existing: CallableContract,
    incoming: CallableContract,
) -> list[ContractFinding]:
    """Return findings when *incoming* contradicts *existing* without override rights.

    Rules:

    * same ``contract_id`` / ``qualified_name`` with incompatible high-level shape
      is always a contradiction;
    * a lower-rank authority may not weaken or rewrite a higher-rank fact;
    * equal-rank contradictory predicates / effects / resources are findings;
    * higher-rank incoming may replace lower-rank facts without a finding
      (recorded as an authority selection, not a contradiction).
    """

    findings: list[ContractFinding] = []
    base = f"conflict:{existing.contract_id}:{incoming.contract_id}"

    if existing.shape != incoming.shape:
        findings.append(
            ContractFinding(
                finding_id=f"{base}:shape",
                kind="contradiction",
                severity="error",
                message=(
                    f"callable shape mismatch: existing={existing.shape!r} "
                    f"incoming={incoming.shape!r}"
                ),
                subject=existing.qualified_name,
                left_contract_id=existing.contract_id,
                right_contract_id=incoming.contract_id,
                details=(existing.shape, incoming.shape),
            )
        )

    existing_rank = existing.provenance.authority.rank_order
    incoming_rank = incoming.provenance.authority.rank_order

    if incoming_rank > existing_rank:
        # Lower authority (higher numeric order) attempting to override.
        findings.append(
            ContractFinding(
                finding_id=f"{base}:authority_override",
                kind="authority_override",
                severity="error",
                message=(
                    "lower-authority contract cannot override higher-authority "
                    f"contract (existing={existing.provenance.authority.rank}, "
                    f"incoming={incoming.provenance.authority.rank})"
                ),
                subject=existing.qualified_name,
                left_contract_id=existing.contract_id,
                right_contract_id=incoming.contract_id,
                details=(
                    existing.provenance.authority.rank,
                    incoming.provenance.authority.rank,
                ),
            )
        )
        return findings

    # Predicate contradictions at equal or comparable rank.
    existing_preds = {
        _predicate_conflict_key(item): item
        for item in (
            *existing.preconditions,
            *existing.postconditions,
            *existing.invariants,
        )
    }
    for predicate in (
        *incoming.preconditions,
        *incoming.postconditions,
        *incoming.invariants,
    ):
        key = _predicate_conflict_key(predicate)
        prior = existing_preds.get(key)
        if prior is None:
            continue
        prior_rank = prior.provenance.authority.rank_order
        new_rank = predicate.provenance.authority.rank_order
        if _arguments_equal(prior.arguments, predicate.arguments):
            continue
        if new_rank > prior_rank:
            findings.append(
                ContractFinding(
                    finding_id=f"{base}:pred-override:{prior.predicate_id}",
                    kind="authority_override",
                    severity="error",
                    message=(
                        "lower-authority predicate cannot override higher-authority "
                        f"predicate on {key[0]}/{key[1]}/{key[2]}"
                    ),
                    subject=existing.qualified_name,
                    left_contract_id=existing.contract_id,
                    right_contract_id=incoming.contract_id,
                    details=(prior.predicate_id, predicate.predicate_id),
                )
            )
        elif new_rank == prior_rank:
            findings.append(
                ContractFinding(
                    finding_id=f"{base}:pred-contradiction:{prior.predicate_id}",
                    kind="contradiction",
                    severity="error",
                    message=(
                        "contradictory predicates at equal authority rank for "
                        f"{key[0]}/{key[1]}/{key[2]}"
                    ),
                    subject=existing.qualified_name,
                    left_contract_id=existing.contract_id,
                    right_contract_id=incoming.contract_id,
                    details=(
                        prior.predicate_id,
                        predicate.predicate_id,
                        json.dumps(list(prior.arguments), sort_keys=True),
                        json.dumps(list(predicate.arguments), sort_keys=True),
                    ),
                )
            )

    existing_effects = {
        _effect_conflict_key(item): item for item in existing.effects
    }
    for effect in incoming.effects:
        key = _effect_conflict_key(effect)
        prior = existing_effects.get(key)
        if prior is None:
            continue
        if prior.permitted == effect.permitted and prior.required == effect.required:
            continue
        prior_rank = prior.provenance.authority.rank_order
        new_rank = effect.provenance.authority.rank_order
        if new_rank > prior_rank:
            findings.append(
                ContractFinding(
                    finding_id=f"{base}:effect-override:{prior.effect_id}",
                    kind="authority_override",
                    severity="error",
                    message=(
                        "lower-authority effect cannot override higher-authority "
                        f"effect {key[0]}/{key[1]}"
                    ),
                    subject=existing.qualified_name,
                    left_contract_id=existing.contract_id,
                    right_contract_id=incoming.contract_id,
                    details=(prior.effect_id, effect.effect_id),
                )
            )
        elif new_rank == prior_rank:
            findings.append(
                ContractFinding(
                    finding_id=f"{base}:effect-contradiction:{prior.effect_id}",
                    kind="contradiction",
                    severity="error",
                    message=(
                        f"contradictory effect permissions for {key[0]}/{key[1]}"
                    ),
                    subject=existing.qualified_name,
                    left_contract_id=existing.contract_id,
                    right_contract_id=incoming.contract_id,
                    details=(prior.effect_id, effect.effect_id),
                )
            )

    existing_resources = {
        _resource_conflict_key(item): item for item in existing.resources
    }
    for resource in incoming.resources:
        key = _resource_conflict_key(resource)
        prior = existing_resources.get(key)
        if prior is None:
            continue
        if prior.minimum == resource.minimum and prior.maximum == resource.maximum:
            continue
        # Disjoint bounds are a contradiction at equal rank.
        disjoint = (
            resource.maximum < prior.minimum or resource.minimum > prior.maximum
        )
        prior_rank = prior.provenance.authority.rank_order
        new_rank = resource.provenance.authority.rank_order
        if not disjoint and new_rank < prior_rank:
            # Higher authority may tighten bounds.
            continue
        if new_rank > prior_rank:
            findings.append(
                ContractFinding(
                    finding_id=f"{base}:resource-override:{prior.resource_id}",
                    kind="authority_override",
                    severity="error",
                    message=(
                        "lower-authority resource bound cannot override "
                        f"higher-authority bound for {key}"
                    ),
                    subject=existing.qualified_name,
                    left_contract_id=existing.contract_id,
                    right_contract_id=incoming.contract_id,
                    details=(prior.resource_id, resource.resource_id),
                )
            )
        elif new_rank == prior_rank and (
            disjoint
            or prior.minimum != resource.minimum
            or prior.maximum != resource.maximum
        ):
            findings.append(
                ContractFinding(
                    finding_id=f"{base}:resource-contradiction:{prior.resource_id}",
                    kind="contradiction",
                    severity="error",
                    message=f"contradictory resource bounds for {key}",
                    subject=existing.qualified_name,
                    left_contract_id=existing.contract_id,
                    right_contract_id=incoming.contract_id,
                    details=(
                        prior.resource_id,
                        resource.resource_id,
                        str(prior.minimum),
                        str(prior.maximum),
                        str(resource.minimum),
                        str(resource.maximum),
                    ),
                )
            )

    return findings


@dataclass(frozen=True, slots=True)
class ContractRegistry:
    """Immutable, content-addressed registry of reviewed callable contracts.

    Construction via :meth:`from_callables` runs conflict detection.  Findings
    are retained on the registry; callers decide whether findings block merge.
    Lookup is exact by ``contract_id`` or ``qualified_name``.
    """

    registry_id: str
    revision: str
    contracts: Mapping[str, CallableContract]
    findings: tuple[ContractFinding, ...] = ()
    owner_goal: str = GOAL_ID
    schema: str = REGISTRY_SCHEMA

    def __post_init__(self) -> None:
        if type(self.registry_id) is not str or not self.registry_id:
            raise ContractRegistryError("registry_id must be a non-empty string")
        if type(self.revision) is not str or not self.revision:
            raise ContractRegistryError("revision must be a non-empty string")
        if self.owner_goal != GOAL_ID:
            raise ContractRegistryError(f"owner_goal must be {GOAL_ID}")
        if self.schema != REGISTRY_SCHEMA:
            raise ContractRegistryError(f"schema must be {REGISTRY_SCHEMA}")
        if not isinstance(self.contracts, Mapping):
            raise ContractRegistryError("contracts must be a mapping")
        # Freeze as MappingProxyType for defensive immutability.
        frozen = MappingProxyType(dict(self.contracts))
        for key, value in frozen.items():
            if type(key) is not str or not key:
                raise ContractRegistryError("contract keys must be non-empty strings")
            if not isinstance(value, CallableContract):
                raise ContractRegistryError(
                    "registry values must be CallableContract instances"
                )
            if value.contract_id != key:
                raise ContractRegistryError(
                    f"contract map key {key!r} does not match "
                    f"contract_id {value.contract_id!r}"
                )
        object.__setattr__(self, "contracts", frozen)
        if not isinstance(self.findings, tuple):
            object.__setattr__(self, "findings", tuple(self.findings))
        for finding in self.findings:
            if not isinstance(finding, ContractFinding):
                raise ContractRegistryError(
                    "findings must contain only ContractFinding records"
                )

    # -- construction -------------------------------------------------------

    @classmethod
    def from_callables(
        cls,
        registry_id: str,
        callables: Iterable[CallableContract],
        *,
        revision: str = "1.0.0",
        reject_on_findings: bool = False,
    ) -> "ContractRegistry":
        """Build a registry, detecting contradictions as findings.

        Contracts are admitted in authority-rank order (highest first), then
        ``contract_id`` order for stability.  When two contracts share a
        ``qualified_name``, conflict detection runs; higher-authority contracts
        win the slot, and conflicts become findings.
        """

        items = list(callables)
        if not all(isinstance(item, CallableContract) for item in items):
            raise ContractRegistryError(
                "from_callables requires CallableContract instances"
            )

        # Sort for deterministic assembly: higher authority first.
        items.sort(
            key=lambda item: (
                item.provenance.authority.rank_order,
                item.contract_id,
            )
        )

        by_id: dict[str, CallableContract] = {}
        by_name: dict[str, CallableContract] = {}
        findings: list[ContractFinding] = []
        seen_ids: set[str] = set()

        for contract in items:
            if contract.contract_id in seen_ids:
                findings.append(
                    ContractFinding(
                        finding_id=f"dup:{contract.contract_id}",
                        kind="contradiction",
                        severity="error",
                        message=(
                            f"duplicate contract_id {contract.contract_id!r}"
                        ),
                        subject=contract.qualified_name,
                        left_contract_id=contract.contract_id,
                        right_contract_id=contract.contract_id,
                    )
                )
                continue
            seen_ids.add(contract.contract_id)

            prior = by_name.get(contract.qualified_name)
            if prior is not None:
                conflicts = detect_callable_conflicts(prior, contract)
                findings.extend(conflicts)
                # Keep higher-authority (already present, admitted first).
                # Only replace when incoming has strictly higher authority
                # (lower rank_order) and no authority_override finding.
                override_blocked = any(
                    item.kind == "authority_override" for item in conflicts
                )
                if (
                    not override_blocked
                    and contract.provenance.authority.rank_order
                    < prior.provenance.authority.rank_order
                ):
                    del by_id[prior.contract_id]
                    by_id[contract.contract_id] = contract
                    by_name[contract.qualified_name] = contract
                continue

            by_id[contract.contract_id] = contract
            by_name[contract.qualified_name] = contract

        findings_tuple = tuple(
            sorted(findings, key=lambda item: item.finding_id)
        )
        if reject_on_findings and findings_tuple:
            raise ContractRegistryError(
                f"registry rejected: {len(findings_tuple)} conflict finding(s)"
            )

        # Deterministic map order by contract_id.
        ordered = {
            key: by_id[key] for key in sorted(by_id)
        }
        return cls(
            registry_id=registry_id,
            revision=revision,
            contracts=ordered,
            findings=findings_tuple,
        )

    # -- lookup -------------------------------------------------------------

    def get(self, contract_id: str) -> CallableContract:
        try:
            return self.contracts[contract_id]
        except KeyError as exc:
            raise ContractRegistryError(
                f"unknown contract_id: {contract_id}"
            ) from exc

    def get_by_qualified_name(self, qualified_name: str) -> CallableContract:
        for contract in self.contracts.values():
            if contract.qualified_name == qualified_name:
                return contract
        raise ContractRegistryError(
            f"unknown qualified_name: {qualified_name}"
        )

    def __contains__(self, contract_id: object) -> bool:
        return isinstance(contract_id, str) and contract_id in self.contracts

    def __len__(self) -> int:
        return len(self.contracts)

    def __iter__(self) -> Iterator[CallableContract]:
        return iter(self.contracts.values())

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)

    @property
    def error_findings(self) -> tuple[ContractFinding, ...]:
        return tuple(
            item
            for item in self.findings
            if item.severity in {"error", "fatal"}
        )

    # -- serialization ------------------------------------------------------

    def to_document(self) -> ContractDocument:
        """Project the registry into a content-addressed ContractDocument."""

        return ContractDocument(
            document_id=self.registry_id,
            callables=tuple(
                self.contracts[key] for key in sorted(self.contracts)
            ),
            findings=self.findings,
            registry_revision=self.revision,
            owner_goal=self.owner_goal,
            schema=SOFTWARE_CONTRACT_SCHEMA,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "registry_id": self.registry_id,
            "revision": self.revision,
            "owner_goal": self.owner_goal,
            "task_id": TASK_ID,
            "contract_schema": SOFTWARE_CONTRACT_SCHEMA,
            "contracts": [
                self.contracts[key].to_dict() for key in sorted(self.contracts)
            ],
            "findings": [item.to_dict() for item in self.findings],
            "authority_rank_order": list(AUTHORITY_RANK_ORDER),
        }

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes.decode("utf-8")

    def verify_cid(self, claimed_cid: str) -> str:
        return decode_and_recompute_structured(claimed_cid, self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractRegistry":
        if type(value) is not dict:
            raise ContractRegistryError("registry payload must be an exact mapping")
        expected = {
            "schema",
            "registry_id",
            "revision",
            "owner_goal",
            "task_id",
            "contract_schema",
            "contracts",
            "findings",
            "authority_rank_order",
        }
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        if missing or extra:
            raise ContractRegistryError(
                f"registry fields are closed (missing={missing}, extra={extra})"
            )
        if value["schema"] != REGISTRY_SCHEMA:
            raise ContractRegistryError(
                f"unsupported registry schema: {value['schema']!r}"
            )
        if value["owner_goal"] != GOAL_ID:
            raise ContractRegistryError("owner_goal mismatch")
        if value["task_id"] != TASK_ID:
            raise ContractRegistryError("task_id mismatch")
        if value["contract_schema"] != SOFTWARE_CONTRACT_SCHEMA:
            raise ContractRegistryError("contract_schema mismatch")
        if list(value["authority_rank_order"]) != list(AUTHORITY_RANK_ORDER):
            raise ContractRegistryError("authority_rank_order mismatch")

        contracts = [
            CallableContract.from_dict(item) for item in value["contracts"]
        ]
        findings = [
            ContractFinding.from_dict(item) for item in value["findings"]
        ]
        ordered = {item.contract_id: item for item in contracts}
        if len(ordered) != len(contracts):
            raise ContractRegistryError("duplicate contract_id in registry payload")
        return cls(
            registry_id=value["registry_id"],
            revision=value["revision"],
            contracts=ordered,
            findings=tuple(sorted(findings, key=lambda item: item.finding_id)),
            owner_goal=value["owner_goal"],
            schema=value["schema"],
        )

    @classmethod
    def from_json(cls, text: str) -> "ContractRegistry":
        if type(text) is not str:
            raise ContractRegistryError("JSON input must be a string")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContractRegistryError("invalid JSON") from exc
        return cls.from_dict(payload)

    @classmethod
    def from_document(cls, document: ContractDocument) -> "ContractRegistry":
        """Rebuild a registry view from a ContractDocument."""

        if not isinstance(document, ContractDocument):
            raise ContractRegistryError("from_document requires a ContractDocument")
        ordered = {item.contract_id: item for item in document.callables}
        return cls(
            registry_id=document.document_id,
            revision=document.registry_revision,
            contracts=ordered,
            findings=document.findings,
        )


def empty_registry(
    registry_id: str = "registry:empty",
    *,
    revision: str = "1.0.0",
) -> ContractRegistry:
    """Return an empty reviewed registry shell."""

    return ContractRegistry(
        registry_id=registry_id,
        revision=revision,
        contracts={},
        findings=(),
    )


__all__ = [
    "ContractRegistry",
    "ContractRegistryError",
    "REGISTRY_SCHEMA",
    "detect_callable_conflicts",
    "empty_registry",
]
