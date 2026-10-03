"""Durable candidate metadata for exact codebase-property verification requests.

This reuses the canonical proof identity and software-contract CAS cache. Every
entry remains an UNKNOWN, leased historical candidate; callers must rerun their
native checks and current-head/source observation before using any outcome.
Neither a cache hit nor a result's status field establishes checked authority.
There is no DuckDB proof-index persistence or execution bypass in this module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.common.canonical_cache_key import CanonicalProofCacheKey
from ipfs_datasets_py.logic.ir_core.axes import LogicEvidenceAuthority, LogicEvidenceKind

from .cache import (
    AnalysisCacheKey, CacheIntegrityError, FormalVerificationCache, OUTCOME_UNKNOWN,
)
from .content import canonical_dag_json_bytes, cid_for_structured, validate_cid

BINDING_SCHEMA = "codebase-property-cache-binding@1"
RESULT_SCHEMA = "codebase-property-cache-candidate@1"
MAX_BINDING_BYTES = 64 * 1024
MAX_RESULT_BYTES = 1024 * 1024
CANDIDATE_LEASE_SECONDS = 3600
_BINDING_FIELDS = frozenset({
    "schema", "source_cid", "snapshot_cid", "profile", "contract_cid", "compiled_cid",
    "bounds", "environment", "provider", "checker", "canonical_key", "canonical_key_id",
})
_ENVELOPE_FIELDS = frozenset({
    "schema", "authority", "requires_fresh_native_checks", "binding", "result",
})
_POLICY = {"schema": "codebase-property-cache-policy@1",
           "authority": "historical_candidate", "requires_fresh_native_checks": True,
           "requires_current_source_observation": True}
_NETWORK = {"schema": "codebase-property-check-network@1", "mode": "offline"}


class CodebasePropertyCacheError(CacheIntegrityError):
    """A historical candidate has malformed or mismatched identity bindings."""


def _copy(value: Any, maximum: int, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CodebasePropertyCacheError(f"{name} must be a plain JSON object")
    try:
        encoded = canonical_dag_json_bytes(value)
        if len(encoded) > maximum:
            raise CodebasePropertyCacheError(f"{name} exceeds its byte bound")
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise CodebasePropertyCacheError(f"{name} must be bounded canonical JSON") from exc


def _identity(value: Any, name: str, codec: str) -> str:
    try:
        return validate_cid(value, codecs={codec})
    except (TypeError, ValueError) as exc:
        raise CodebasePropertyCacheError(f"invalid {name}") from exc


def _key(inputs: dict[str, Any]) -> CanonicalProofCacheKey:
    """Derive each proof dimension; declarations cannot substitute a digest."""
    try:
        return CanonicalProofCacheKey.build(
            source={"source_cid": inputs["source_cid"]},
            expression={"contract_cid": inputs["contract_cid"]},
            formalization={"profile": inputs["profile"], "contract_cid": inputs["contract_cid"]},
            slice={"source_cid": inputs["source_cid"], "snapshot_cid": inputs["snapshot_cid"]},
            obligation={"compiled_cid": inputs["compiled_cid"]},
            assumptions={"profile": inputs["profile"], "contract_cid": inputs["contract_cid"]},
            bounds=inputs["bounds"],
            translation={"profile": inputs["profile"], "compiled_cid": inputs["compiled_cid"]},
            provider=inputs["provider"], environment=inputs["environment"],
            policy=_POLICY, schema={"binding": BINDING_SCHEMA, "result": RESULT_SCHEMA},
            checker=inputs["checker"], network_policy=_NETWORK,
            evidence_kind=LogicEvidenceKind.SMT_CANDIDATE,
            authority_ceiling=LogicEvidenceAuthority.NONE,
            source_cid=inputs["source_cid"],
        )
    except (TypeError, ValueError) as exc:
        raise CodebasePropertyCacheError("canonical proof key could not be derived") from exc


def build_codebase_property_binding(
    *, source_cid: str, snapshot_cid: str, profile: dict[str, Any],
    contract_cid: str, compiled_cid: str, bounds: dict[str, Any],
    environment: dict[str, Any], provider: str, checker: str,
) -> dict[str, Any]:
    """Bind owner-derived source, compilation, contract and runtime metadata.

    Profile must identify its semantics, assumptions and implementation. The
    owner supplies observed native tool/environment identities and actual bounds;
    this helper checks and hashes their structure, not their physical truth.
    A complete snapshot identity is deliberately included for this initial exact
    reuse profile. Cross-snapshot proof reuse remains a separate future profile.
    """
    inputs = {
        "schema": BINDING_SCHEMA,
        "source_cid": _identity(source_cid, "source_cid", "raw"),
        "snapshot_cid": _identity(snapshot_cid, "snapshot_cid", "dag-json"),
        "contract_cid": _identity(contract_cid, "contract_cid", "dag-json"),
        "compiled_cid": _identity(compiled_cid, "compiled_cid", "dag-json"),
        "profile": _copy(profile, MAX_BINDING_BYTES, "profile"),
        "bounds": _copy(bounds, MAX_BINDING_BYTES, "bounds"),
        "environment": _copy(environment, MAX_BINDING_BYTES, "environment"),
        "provider": provider, "checker": checker,
    }
    if not all(inputs[name] for name in ("profile", "bounds", "environment")):
        raise CodebasePropertyCacheError("profile, bounds and environment must be explicit nonempty objects")
    if any(type(inputs[name]) is not str or len(inputs[name].encode("utf-8")) > 512
           for name in ("provider", "checker")):
        raise CodebasePropertyCacheError("provider and checker must be bounded stable identifiers")
    key = _key(inputs)
    inputs["canonical_key"] = key.to_dict()
    inputs["canonical_key_id"] = key.key_id
    return _copy(inputs, MAX_BINDING_BYTES, "binding")


def _validate_binding(binding: dict[str, Any]) -> dict[str, Any]:
    value = _copy(binding, MAX_BINDING_BYTES, "binding")
    if set(value) != _BINDING_FIELDS or value["schema"] != BINDING_SCHEMA:
        raise CodebasePropertyCacheError("invalid property cache binding fields or schema")
    expected = build_codebase_property_binding(**{
        name: value[name] for name in _BINDING_FIELDS
        - {"schema", "canonical_key", "canonical_key_id"}
    })
    # Compare canonical bytes: bool/int equality must not hide malformed fields,
    # and from_dict alone does not check declared key_id/interface overrides.
    if canonical_dag_json_bytes(value) != canonical_dag_json_bytes(expected):
        raise CodebasePropertyCacheError("declared canonical key does not recompute from the exact binding")
    return expected


def property_analysis_cache_key(binding: dict[str, Any]) -> AnalysisCacheKey:
    """Project the full proof binding onto the existing CAS cache dimensions."""
    value = _validate_binding(binding)
    return AnalysisCacheKey(
        source_cid=value["source_cid"], dependency_cids=(),
        analyzer_cid=cid_for_structured({"schema": RESULT_SCHEMA, "checker": value["checker"]}),
        configuration_cid=cid_for_structured(value),
        semantics_cid=cid_for_structured(value["profile"]),
        policy_cid=cid_for_structured(_POLICY),
        solver_cid=cid_for_structured({"provider": value["provider"], "environment": value["environment"]}),
        toolchain_cid=cid_for_structured(value["environment"]),
        result_schema=RESULT_SCHEMA,
    )


class CodebasePropertyCache:
    """Exact durable historical metadata; every consumer still checks natively.

    Repeated writes replace the small key index, retaining immutable old objects.
    Entries expire after one hour; TTL is reuse hygiene, never evidence authority.
    The caller supplies finite source/property workloads and owns cache retention.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._cache = FormalVerificationCache(
            self.root, max_object_bytes=MAX_RESULT_BYTES + MAX_BINDING_BYTES + 4096,
            max_lease_seconds=CANDIDATE_LEASE_SECONDS,
        )

    def lookup(self, binding: dict[str, Any]) -> dict[str, Any] | None:
        value = _validate_binding(binding)
        lookup = self._cache.lookup(property_analysis_cache_key(value))
        if not lookup.hit:
            return None
        if (lookup.receipt is None or lookup.receipt.outcome != OUTCOME_UNKNOWN
                or lookup.receipt.lease_expires_at is None or lookup.satisfies_completion):
            raise CodebasePropertyCacheError("cached candidate cannot carry a completion outcome")
        payload = lookup.result
        if (type(payload) is not dict or set(payload) != _ENVELOPE_FIELDS
                or payload["schema"] != RESULT_SCHEMA
                or payload["authority"] != "historical_candidate"
                or payload["requires_fresh_native_checks"] is not True):
            raise CodebasePropertyCacheError("invalid historical candidate envelope")
        recorded = _validate_binding(payload["binding"])
        if canonical_dag_json_bytes(recorded) != canonical_dag_json_bytes(value):
            raise CodebasePropertyCacheError("historical candidate belongs to another exact binding")
        return _copy(payload["result"], MAX_RESULT_BYTES, "historical result")

    def put(self, binding: dict[str, Any], result: dict[str, Any]) -> None:
        value = _validate_binding(binding)
        historical = _copy(result, MAX_RESULT_BYTES, "historical result")
        payload = {"schema": RESULT_SCHEMA, "authority": "historical_candidate",
                   "requires_fresh_native_checks": True, "binding": value,
                   "result": historical}
        self._cache.put(property_analysis_cache_key(value), payload,
                        outcome=OUTCOME_UNKNOWN, lease_seconds=CANDIDATE_LEASE_SECONDS)


__all__ = ["CodebasePropertyCache", "CodebasePropertyCacheError",
           "build_codebase_property_binding", "property_analysis_cache_key"]
