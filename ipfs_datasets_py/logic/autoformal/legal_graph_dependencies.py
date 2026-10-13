"""Bounded declared dependency custody and reverse invalidation for legal graphs.

Edges point from a dependent artifact to its dependency. Invalidation traverses
the reverse direction until every reachable dependent has been visited, including
cycles. Missing targets and unbound pins are explicit and prevent reuse. This
does not infer legal dependencies, establish an exhaustive legal theory, or
prove that unchanged artifacts are semantically correct.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any

SCHEMA = "legal-graph-dependency-manifest/v1"
INVALIDATION_SCHEMA = "legal-graph-reverse-invalidation/v1"
PIN_KINDS = ("root", "source", "revision", "context", "definition", "model", "policy")
MAX_ARTIFACTS = 4096
MAX_EDGES = 16384
MAX_PINS_PER_ARTIFACT = 256
MAX_BYTES = 8 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FALSE = {key: False for key in ("legal_dependency_inventory_exhaustive", "source_semantics_verified",
                                "global_consistency_verified", "proof_authority", "admitted")}


class GraphDependencyError(ValueError):
    """Declared identities, dependency population, or finite bounds disagree."""


def _need(condition, message):
    if not condition:
        raise GraphDependencyError(message)


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise GraphDependencyError("finite UTF-8 dependency JSON required") from exc
    _need(len(raw) <= MAX_BYTES, "dependency byte bound exceeded; no partial inventory")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _identity(value):
    _need(type(value) is str and value.strip() and len(value.encode("utf-8")) <= 2048,
          "bounded nonblank artifact or pin identity required")
    return value


def _sha(value, *, missing=False):
    _need((missing and value is None) or type(value) is str and _SHA.fullmatch(value),
          "exact SHA256 or explicit missing null required")
    return value


def _pins(value):
    _need(type(value) is dict and set(value) == set(PIN_KINDS),
          "all seven dependency pin categories must be explicit")
    count, result = 0, {}
    for kind in PIN_KINDS:
        rows = value[kind]
        _need(type(rows) is list, "dependency pin category must be a list; empty means no declared pins")
        count += len(rows)
        _need(count <= MAX_PINS_PER_ARTIFACT, "artifact dependency pin bound exceeded")
        seen, result[kind] = set(), []
        for row in rows:
            _need(type(row) is dict and set(row) == {"key", "sha256"}, "closed dependency pin required")
            key = _identity(row["key"])
            _need(key not in seen, "duplicate dependency pin key")
            seen.add(key)
            result[kind].append({"key": key, "sha256": _sha(row["sha256"], missing=True)})
    return result


def _cycles(ids, edges):
    """Iterative SCC inventory; no recursion or hidden depth/hop cut-off."""
    adjacency, reverse = {key: [] for key in ids}, {key: [] for key in ids}
    for edge in edges:
        left, right = edge["dependent_id"], edge["dependency_id"]
        if right in adjacency:
            adjacency[left].append(right)
            reverse[right].append(left)
    visited, order = set(), []
    for start in ids:
        stack = [(start, False)]
        while stack:
            node, finishing = stack.pop()
            if finishing:
                order.append(node)
            elif node not in visited:
                visited.add(node)
                stack.append((node, True))
                stack.extend((child, False) for child in reversed(adjacency[node]) if child not in visited)
    visited, components = set(), []
    for start in reversed(order):
        if start in visited:
            continue
        component, stack = [], [start]
        visited.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for child in reverse[node]:
                if child not in visited:
                    visited.add(child)
                    stack.append(child)
        if len(component) > 1 or start in adjacency[start]:
            components.append(sorted(component))
    return sorted(components)


def build_dependency_manifest(artifacts, edges, *, expected_artifact_ids):
    """Bind every artifact in exact caller-supplied order, without filtering.

    Artifact fields are ``artifact_id``, ``artifact_sha256``, and
    ``dependency_pins``. Each of seven pin categories contains explicit
    ``{key, sha256}`` rows; null hashes mean missing evidence. Empty categories
    mean no dependencies were declared, not that legal completeness was proved.
    Edge fields are ``dependent_id`` and ``dependency_id``. A missing target is
    retained as an open dependency rather than silently removed.
    """
    _need(type(artifacts) is list and 0 < len(artifacts) <= MAX_ARTIFACTS, "bounded artifact population required")
    _need(type(edges) is list and len(edges) <= MAX_EDGES, "dependency edge bound exceeded")
    _need(isinstance(expected_artifact_ids, (list, tuple)) and len(expected_artifact_ids) == len(artifacts),
          "exact expected artifact population required")
    expected = [_identity(key) for key in expected_artifact_ids]
    _need(len(set(expected)) == len(expected), "duplicate expected artifact identity")
    normalized = []
    for artifact in artifacts:
        _need(type(artifact) is dict and set(artifact) == {"artifact_id", "artifact_sha256", "dependency_pins"},
              "closed artifact dependency record required")
        normalized.append({"artifact_id": _identity(artifact["artifact_id"]),
                           "artifact_sha256": _sha(artifact["artifact_sha256"]),
                           "dependency_pins": _pins(artifact["dependency_pins"])})
    _need([row["artifact_id"] for row in normalized] == expected,
          "artifact population differs in membership, order, or multiplicity")
    known, seen_edges, normalized_edges = set(expected), set(), []
    for edge in edges:
        _need(type(edge) is dict and set(edge) == {"dependent_id", "dependency_id"}, "closed directed edge required")
        pair = (_identity(edge["dependent_id"]), _identity(edge["dependency_id"]))
        _need(pair[0] in known, "edge dependent is omitted from artifact population")
        _need(pair not in seen_edges, "duplicate directed dependency edge")
        seen_edges.add(pair)
        normalized_edges.append(dict(zip(("dependent_id", "dependency_id"), pair)))
    reverse = {key: [] for key in expected}
    missing = []
    for edge in normalized_edges:
        reverse.setdefault(edge["dependency_id"], []).append(edge["dependent_id"])
        if edge["dependency_id"] not in known:
            missing.append(edge)
    report = {"schema": SCHEMA, "edge_direction": "dependent_to_dependency",
              "expected_artifact_ids": expected, "artifacts": normalized, "edges": normalized_edges,
              "reverse_index": {key: sorted(value) for key, value in sorted(reverse.items())},
              "missing_dependencies": missing, "cycles": _cycles(expected, normalized_edges),
              "population_complete": True, "coverage_scope": "exact_declared_artifacts_pins_and_edges_only", **_FALSE}
    report["manifest_sha256"] = _digest(report)
    _wire(report)
    return report


def validate_dependency_manifest(manifest, *, expected_manifest_sha256):
    """Replay a manifest only under an independently retained content pin."""
    _need(type(manifest) is dict, "dependency manifest must be an object")
    _sha(expected_manifest_sha256)
    _need(manifest.get("manifest_sha256") == expected_manifest_sha256,
          "dependency manifest differs from independently expected identity")
    expected = build_dependency_manifest(manifest.get("artifacts"), manifest.get("edges"),
                                         expected_artifact_ids=manifest.get("expected_artifact_ids"))
    _need(_wire(manifest) == _wire(expected), "dependency manifest differs from exact regeneration")
    return expected


def invalidate_dependencies(manifest, *, expected_manifest_sha256, observed_artifact_sha256s, observed_pins):
    """Mark changed/missing artifacts and every reverse-reachable dependent.

    Observations must enumerate every declared artifact, including explicit null
    for unavailable artifacts. Pin observations contain all seven categories,
    mapping declared keys to current SHA256 or null; absent keys are missing.
    Unaffected artifacts are reusable only under this declared custody contract,
    never by reason of legal meaning or semantic consistency.
    """
    manifest = validate_dependency_manifest(manifest, expected_manifest_sha256=expected_manifest_sha256)
    ids = manifest["expected_artifact_ids"]
    _need(type(observed_artifact_sha256s) is dict and set(observed_artifact_sha256s) == set(ids),
          "observations must account for every artifact; use null for unavailable")
    for value in observed_artifact_sha256s.values():
        _sha(value, missing=True)
    _need(type(observed_pins) is dict and set(observed_pins) == set(PIN_KINDS),
          "all observed dependency pin categories must be explicit")
    known_pins = {kind: {pin["key"] for row in manifest["artifacts"]
                        for pin in row["dependency_pins"][kind]} for kind in PIN_KINDS}
    for kind, observations in observed_pins.items():
        _need(type(observations) is dict and set(observations) <= known_pins[kind],
              "observed pin keys differ from declared dependencies")
        for value in observations.values():
            _sha(value, missing=True)
    reasons = {key: [] for key in ids}
    for artifact in manifest["artifacts"]:
        key = artifact["artifact_id"]
        current = observed_artifact_sha256s[key]
        if current != artifact["artifact_sha256"]:
            reasons[key].append({"code": "artifact_missing" if current is None else "artifact_changed"})
        for kind in PIN_KINDS:
            for pin in artifact["dependency_pins"][kind]:
                observed = observed_pins[kind].get(pin["key"])
                if pin["sha256"] is None or observed != pin["sha256"]:
                    reasons[key].append({"code": "dependency_pin_unbound" if pin["sha256"] is None
                                         else "dependency_pin_missing" if observed is None else "dependency_pin_changed",
                                         "kind": kind, "key": pin["key"]})
    for edge in manifest["missing_dependencies"]:
        reasons[edge["dependent_id"]].append({"code": "dependency_artifact_missing", "dependency_id": edge["dependency_id"]})
    seeds = [key for key in ids if reasons[key]]
    stale, queue = set(seeds), deque(seeds)
    witnesses = []
    while queue:
        dependency = queue.popleft()
        for dependent in manifest["reverse_index"][dependency]:
            if dependent not in stale:
                stale.add(dependent)
                queue.append(dependent)
                witnesses.append({"dependency_id": dependency, "dependent_id": dependent})
    report = {"schema": INVALIDATION_SCHEMA, "manifest_sha256": manifest["manifest_sha256"],
              "observed_artifact_sha256s": observed_artifact_sha256s, "observed_pins": observed_pins,
              "seed_artifact_ids": seeds, "seed_reasons": {key: value for key, value in reasons.items() if value},
              "stale_artifact_ids": [key for key in ids if key in stale],
              "reusable_under_declared_dependencies": [key for key in ids if key not in stale],
              "propagation_witnesses": witnesses, "cycles": manifest["cycles"],
              "missing_dependencies": manifest["missing_dependencies"],
              "population_complete": True, "coverage_scope": manifest["coverage_scope"], **_FALSE}
    # Detach observations so mutation after evaluation cannot alter the report.
    report = json.loads(_wire(report))
    report["invalidation_sha256"] = _digest(report)
    return report


def validate_invalidation(report, manifest, *, expected_manifest_sha256, observed_artifact_sha256s, observed_pins):
    expected = invalidate_dependencies(manifest, observed_artifact_sha256s=observed_artifact_sha256s,
                                       observed_pins=observed_pins, expected_manifest_sha256=expected_manifest_sha256)
    _need(_wire(report) == _wire(expected), "invalidation report differs from exact regeneration")
    return expected


__all__ = ["GraphDependencyError", "build_dependency_manifest", "validate_dependency_manifest",
           "invalidate_dependencies", "validate_invalidation"]
