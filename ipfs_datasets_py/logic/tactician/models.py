"""Versioned, domain-neutral Logic Tactician models (``logic.tactician@1``).

This module defines the finite, content-addressed records that the generic
datasets Logic Tactician emits. Records are domain-neutral: callers supply
opaque source-class strings and identity roots. No legal, program-repair, or
other domain vocabulary is hard-coded here.

Trust boundary
--------------
Every plan and receipt carries ``semantic_authority=False``. The Tactician
may order sources, record exclusions, nominate subgoals, and declare stop/
abstain conditions. It never proves a clause, authorizes a write, executes
a network fetch, or promotes a nomination source to authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Schema / interface versioning
# ---------------------------------------------------------------------------

#: Wire interface id consumed by capability probes and supervisor adapters.
TACTICIAN_INTERFACE = "ipfs_datasets_py.logic.tactician@1"

#: Current schema version for every record defined in this module.
SCHEMA_VERSION = "1.0.0"

#: Schema versions accepted by :meth:`*.validate`.
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

#: Hard bounds preventing unbounded or body-bearing fields.
MAX_ID_LENGTH = 256
MAX_OPAQUE_ROOT_LENGTH = 512
MAX_STRING_FIELD_LENGTH = 2048
MAX_QUERY_HINT_LENGTH = 512
MAX_LIST_LENGTH = 256
MAX_MAP_ENTRIES = 64
MAX_NESTING_DEPTH = 8
MAX_METADATA_JSON_BYTES = 8192

#: Authority-promotion keys that must never be true on advisory records.
_AUTHORITY_PROMOTION_KEYS = frozenset(
    {
        "semantic_authority",
        "expectation_authority",
        "proof_authority",
        "write_authority",
        "authoritative",
    }
)


class TacticianError(ValueError):
    """Base error for Logic Tactician model validation failures."""


class TacticianValidationError(TacticianError):
    """Raised when a record violates the versioned contract."""


class RouteDisposition(str, Enum):
    """Whether a source route was selected into the ordered plan or excluded."""

    SELECTED = "selected"
    EXCLUDED = "excluded"


class StopDisposition(str, Enum):
    """Why planning or search should stop under the recorded plan."""

    CONTINUE = "continue"
    BUDGET_EXHAUSTED = "budget_exhausted"
    GAPS_CLOSED = "gaps_closed"
    NO_ADMISSIBLE_SOURCES = "no_admissible_sources"
    CYCLE_DETECTED = "cycle_detected"
    ABSTAIN = "abstain"
    POLICY_DENIED = "policy_denied"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_schema_version(schema_version: str, *, owner: str) -> None:
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise TacticianValidationError(
            f"{owner}.schema_version={schema_version!r} is not one of the "
            f"supported versions {sorted(SUPPORTED_SCHEMA_VERSIONS)!r}"
        )


def _require_nonempty_str(
    value: Any,
    *,
    field_name: str,
    owner: str,
    max_length: int = MAX_ID_LENGTH,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TacticianValidationError(
            f"{owner}.{field_name} must be a non-empty string"
        )
    text = value.strip()
    if len(text) > max_length:
        raise TacticianValidationError(
            f"{owner}.{field_name} exceeds max length {max_length}"
        )
    return text


def _require_bool(value: Any, *, field_name: str, owner: str) -> bool:
    if not isinstance(value, bool):
        raise TacticianValidationError(
            f"{owner}.{field_name} must be a boolean, got {type(value).__name__}"
        )
    return value


def _require_positive_int(value: Any, *, field_name: str, owner: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TacticianValidationError(
            f"{owner}.{field_name} must be a positive int, got {value!r}"
        )
    return value


def _require_non_negative_int(value: Any, *, field_name: str, owner: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TacticianValidationError(
            f"{owner}.{field_name} must be a non-negative int, got {value!r}"
        )
    return value


def _require_finite_number(value: Any, *, field_name: str, owner: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TacticianValidationError(
            f"{owner}.{field_name} must be a finite number"
        )
    number = float(value)
    if not math.isfinite(number):
        raise TacticianValidationError(
            f"{owner}.{field_name} must be finite, got {value!r}"
        )
    return number


def _require_string_list(
    values: Any,
    *,
    field_name: str,
    owner: str,
    max_items: int = MAX_LIST_LENGTH,
    max_item_length: int = MAX_STRING_FIELD_LENGTH,
    allow_empty: bool = True,
) -> List[str]:
    if not isinstance(values, list):
        raise TacticianValidationError(f"{owner}.{field_name} must be a list")
    if len(values) > max_items:
        raise TacticianValidationError(
            f"{owner}.{field_name} exceeds max list length {max_items}"
        )
    if not allow_empty and not values:
        raise TacticianValidationError(
            f"{owner}.{field_name} must be a non-empty list"
        )
    out: List[str] = []
    seen: set[str] = set()
    for index, item in enumerate(values):
        if not isinstance(item, str) or not item.strip():
            raise TacticianValidationError(
                f"{owner}.{field_name}[{index}] must be a non-empty string"
            )
        text = item.strip()
        if len(text) > max_item_length:
            raise TacticianValidationError(
                f"{owner}.{field_name}[{index}] exceeds max length {max_item_length}"
            )
        if text in seen:
            raise TacticianValidationError(
                f"{owner}.{field_name} contains duplicate identity {text!r}"
            )
        seen.add(text)
        out.append(text)
    return out


def _require_opaque_roots(
    roots: Any,
    *,
    field_name: str,
    owner: str,
) -> Dict[str, str]:
    if not isinstance(roots, dict):
        raise TacticianValidationError(f"{owner}.{field_name} must be a dict")
    if len(roots) > MAX_MAP_ENTRIES:
        raise TacticianValidationError(
            f"{owner}.{field_name} exceeds max map entries {MAX_MAP_ENTRIES}"
        )
    out: Dict[str, str] = {}
    for key, value in roots.items():
        if not isinstance(key, str) or not key.strip():
            raise TacticianValidationError(
                f"{owner}.{field_name} keys must be non-empty strings"
            )
        if not isinstance(value, str) or not value.strip():
            raise TacticianValidationError(
                f"{owner}.{field_name}[{key!r}] must be a non-empty opaque string"
            )
        key_text = key.strip()
        value_text = value.strip()
        if len(key_text) > MAX_ID_LENGTH or len(value_text) > MAX_OPAQUE_ROOT_LENGTH:
            raise TacticianValidationError(
                f"{owner}.{field_name} entry exceeds opaque root length bounds"
            )
        out[key_text] = value_text
    return dict(sorted(out.items()))


def _reject_authority_promotion(
    mapping: Mapping[str, Any],
    *,
    owner: str,
) -> None:
    for key in _AUTHORITY_PROMOTION_KEYS:
        if key in mapping and mapping[key] is True:
            raise TacticianValidationError(
                f"{owner} rejects authority promotion via {key}=True"
            )


def _bounded_json_depth(value: Any, *, depth: int = 0, owner: str) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise TacticianValidationError(
            f"{owner} exceeds max nesting depth {MAX_NESTING_DEPTH}"
        )
    if isinstance(value, dict):
        if len(value) > MAX_MAP_ENTRIES:
            raise TacticianValidationError(
                f"{owner} exceeds max map entries {MAX_MAP_ENTRIES}"
            )
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > MAX_ID_LENGTH:
                raise TacticianValidationError(
                    f"{owner} map keys must be short strings"
                )
            _bounded_json_depth(child, depth=depth + 1, owner=owner)
    elif isinstance(value, list):
        if len(value) > MAX_LIST_LENGTH:
            raise TacticianValidationError(
                f"{owner} exceeds max list length {MAX_LIST_LENGTH}"
            )
        for child in value:
            _bounded_json_depth(child, depth=depth + 1, owner=owner)
    elif isinstance(value, str):
        if len(value) > MAX_STRING_FIELD_LENGTH:
            raise TacticianValidationError(
                f"{owner} string leaf exceeds max length {MAX_STRING_FIELD_LENGTH}"
            )
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise TacticianValidationError(f"{owner} numbers must be finite")
    else:
        raise TacticianValidationError(
            f"{owner} contains non-JSON-serializable type {type(value).__name__}"
        )


def _require_bounded_metadata(
    metadata: Any,
    *,
    field_name: str,
    owner: str,
) -> Dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise TacticianValidationError(f"{owner}.{field_name} must be a dict")
    _reject_authority_promotion(metadata, owner=f"{owner}.{field_name}")
    _bounded_json_depth(metadata, owner=f"{owner}.{field_name}")
    encoded = json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    if len(encoded) > MAX_METADATA_JSON_BYTES:
        raise TacticianValidationError(
            f"{owner}.{field_name} exceeds max metadata bytes "
            f"{MAX_METADATA_JSON_BYTES}"
        )
    return dict(metadata)


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize ``payload`` to deterministic UTF-8 JSON bytes."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


def compute_content_digest(payload: Any) -> str:
    """Return a deterministic content digest for a JSON-serializable payload.

    Prefer a CIDv1 string when ``multiformats`` is importable; otherwise fall
    back to a stable ``sha256:<hex>`` digest. Callers must compare digests only
    for equality.
    """

    data = canonical_json_bytes(payload)
    sha256_hex = hashlib.sha256(data).hexdigest()
    try:
        from multiformats import CID, multihash  # type: ignore[import-not-found]

        mh = multihash.wrap(bytes.fromhex(sha256_hex), "sha2-256")
        return str(CID("base32", 1, "raw", mh))
    except Exception:
        return f"sha256:{sha256_hex}"


def detect_cycle(nodes: Mapping[str, Sequence[str]]) -> Optional[Tuple[str, ...]]:
    """Return one directed cycle as a tuple of node ids, or ``None``.

    ``nodes`` maps node id -> dependency ids. Edges point from a node to the
    nodes it depends on.
    """

    visiting: set[str] = set()
    visited: set[str] = set()
    stack: List[str] = []

    def dfs(node: str) -> Optional[Tuple[str, ...]]:
        if node in visiting:
            if node in stack:
                start = stack.index(node)
                return tuple(stack[start:] + [node])
            return (node, node)
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for dep in nodes.get(node, ()):
            if dep not in nodes and dep not in visited:
                # Unknown dependency identities are treated as external leaves.
                continue
            cycle = dfs(dep)
            if cycle is not None:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node_id in sorted(nodes):
        cycle = dfs(node_id)
        if cycle is not None:
            return cycle
    return None


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TacticianGoal:
    """A finite, body-free goal the Tactician may plan against.

    Attributes:
        goal_id: Stable opaque identity for this goal.
        statement_ref: Opaque reference to the goal statement (never a body).
        goal_family: Caller-defined family label (domain-supplied string).
        goal_root: Exact opaque root binding this goal's identity.
        corpus_root: Exact opaque corpus identity the plan must bind.
        config_root: Exact opaque planner/config identity the plan must bind.
        authority_roots: Additional exact opaque roots (tree, policy, ...).
        proof_gaps: Finite list of opaque gap identifiers the plan should cover.
        assumptions: Finite opaque assumption identities.
        metadata: Bounded non-authoritative annotations.
        schema_version: Record schema version.
    """

    goal_id: str
    statement_ref: str
    goal_family: str
    goal_root: str
    corpus_root: str
    config_root: str
    authority_roots: Dict[str, str] = field(default_factory=dict)
    proof_gaps: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        owner = "TacticianGoal"
        _require_schema_version(self.schema_version, owner=owner)
        object.__setattr__(
            self,
            "goal_id",
            _require_nonempty_str(self.goal_id, field_name="goal_id", owner=owner),
        )
        object.__setattr__(
            self,
            "statement_ref",
            _require_nonempty_str(
                self.statement_ref,
                field_name="statement_ref",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "goal_family",
            _require_nonempty_str(
                self.goal_family, field_name="goal_family", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "goal_root",
            _require_nonempty_str(
                self.goal_root,
                field_name="goal_root",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "corpus_root",
            _require_nonempty_str(
                self.corpus_root,
                field_name="corpus_root",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "config_root",
            _require_nonempty_str(
                self.config_root,
                field_name="config_root",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "authority_roots",
            _require_opaque_roots(
                dict(self.authority_roots), field_name="authority_roots", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "proof_gaps",
            _require_string_list(
                list(self.proof_gaps), field_name="proof_gaps", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            _require_string_list(
                list(self.assumptions), field_name="assumptions", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            _require_bounded_metadata(
                dict(self.metadata), field_name="metadata", owner=owner
            ),
        )
        _reject_authority_promotion(self.metadata, owner=owner)

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "assumptions": list(self.assumptions),
            "authority_roots": dict(self.authority_roots),
            "config_root": self.config_root,
            "corpus_root": self.corpus_root,
            "goal_family": self.goal_family,
            "goal_id": self.goal_id,
            "goal_root": self.goal_root,
            "metadata": dict(self.metadata),
            "proof_gaps": list(self.proof_gaps),
            "schema_version": self.schema_version,
            "statement_ref": self.statement_ref,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TacticianGoal":
        goal = cls(
            goal_id=str(data.get("goal_id", "")),
            statement_ref=str(data.get("statement_ref", "")),
            goal_family=str(data.get("goal_family", "")),
            goal_root=str(data.get("goal_root", "")),
            corpus_root=str(data.get("corpus_root", "")),
            config_root=str(data.get("config_root", "")),
            authority_roots=dict(data.get("authority_roots") or {}),
            proof_gaps=list(data.get("proof_gaps") or []),
            assumptions=list(data.get("assumptions") or []),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )
        goal.validate()
        return goal


@dataclass(frozen=True)
class TacticianSource:
    """A caller-provided evidence source candidate.

    Source classes are opaque strings supplied by the domain adapter. The
    generic models never hard-code legal or program-specific class names.
    """

    source_id: str
    source_class: str
    precedence: int
    rationale: str
    query_hints: List[str] = field(default_factory=list)
    source_root: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        owner = "TacticianSource"
        _require_schema_version(self.schema_version, owner=owner)
        object.__setattr__(
            self,
            "source_id",
            _require_nonempty_str(self.source_id, field_name="source_id", owner=owner),
        )
        object.__setattr__(
            self,
            "source_class",
            _require_nonempty_str(
                self.source_class, field_name="source_class", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "precedence",
            _require_non_negative_int(
                self.precedence, field_name="precedence", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "rationale",
            _require_nonempty_str(
                self.rationale,
                field_name="rationale",
                owner=owner,
                max_length=MAX_STRING_FIELD_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "query_hints",
            _require_string_list(
                list(self.query_hints),
                field_name="query_hints",
                owner=owner,
                max_item_length=MAX_QUERY_HINT_LENGTH,
            ),
        )
        if self.source_root:
            object.__setattr__(
                self,
                "source_root",
                _require_nonempty_str(
                    self.source_root,
                    field_name="source_root",
                    owner=owner,
                    max_length=MAX_OPAQUE_ROOT_LENGTH,
                ),
            )
        object.__setattr__(
            self,
            "metadata",
            _require_bounded_metadata(
                dict(self.metadata), field_name="metadata", owner=owner
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "metadata": dict(self.metadata),
            "precedence": self.precedence,
            "query_hints": list(self.query_hints),
            "rationale": self.rationale,
            "schema_version": self.schema_version,
            "source_class": self.source_class,
            "source_id": self.source_id,
            "source_root": self.source_root,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TacticianSource":
        source = cls(
            source_id=str(data.get("source_id", "")),
            source_class=str(data.get("source_class", "")),
            precedence=int(data.get("precedence", 0)),
            rationale=str(data.get("rationale", "")),
            query_hints=list(data.get("query_hints") or []),
            source_root=str(data.get("source_root") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )
        source.validate()
        return source


@dataclass(frozen=True)
class TacticianRoute:
    """One ordered source route with selection disposition and rationale."""

    route_id: str
    source_id: str
    source_class: str
    stage_index: int
    disposition: RouteDisposition
    rationale: str
    addresses_gaps: List[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        owner = "TacticianRoute"
        _require_schema_version(self.schema_version, owner=owner)
        object.__setattr__(
            self,
            "route_id",
            _require_nonempty_str(self.route_id, field_name="route_id", owner=owner),
        )
        object.__setattr__(
            self,
            "source_id",
            _require_nonempty_str(self.source_id, field_name="source_id", owner=owner),
        )
        object.__setattr__(
            self,
            "source_class",
            _require_nonempty_str(
                self.source_class, field_name="source_class", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "stage_index",
            _require_non_negative_int(
                self.stage_index, field_name="stage_index", owner=owner
            ),
        )
        if not isinstance(self.disposition, RouteDisposition):
            try:
                object.__setattr__(
                    self, "disposition", RouteDisposition(str(self.disposition))
                )
            except ValueError as exc:
                raise TacticianValidationError(
                    f"{owner}.disposition must be a RouteDisposition"
                ) from exc
        object.__setattr__(
            self,
            "rationale",
            _require_nonempty_str(
                self.rationale,
                field_name="rationale",
                owner=owner,
                max_length=MAX_STRING_FIELD_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "addresses_gaps",
            _require_string_list(
                list(self.addresses_gaps), field_name="addresses_gaps", owner=owner
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "addresses_gaps": list(self.addresses_gaps),
            "disposition": self.disposition.value,
            "rationale": self.rationale,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "source_class": self.source_class,
            "source_id": self.source_id,
            "stage_index": self.stage_index,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TacticianRoute":
        route = cls(
            route_id=str(data.get("route_id", "")),
            source_id=str(data.get("source_id", "")),
            source_class=str(data.get("source_class", "")),
            stage_index=int(data.get("stage_index", 0)),
            disposition=RouteDisposition(str(data.get("disposition", "selected"))),
            rationale=str(data.get("rationale", "")),
            addresses_gaps=list(data.get("addresses_gaps") or []),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )
        route.validate()
        return route


@dataclass(frozen=True)
class TacticianSubgoal:
    """One node in a finite acyclic goal decomposition DAG."""

    subgoal_id: str
    parent_goal_id: str
    statement_ref: str
    depends_on: List[str] = field(default_factory=list)
    addresses_gaps: List[str] = field(default_factory=list)
    rationale: str = ""
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        owner = "TacticianSubgoal"
        _require_schema_version(self.schema_version, owner=owner)
        object.__setattr__(
            self,
            "subgoal_id",
            _require_nonempty_str(
                self.subgoal_id, field_name="subgoal_id", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "parent_goal_id",
            _require_nonempty_str(
                self.parent_goal_id, field_name="parent_goal_id", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "statement_ref",
            _require_nonempty_str(
                self.statement_ref,
                field_name="statement_ref",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "depends_on",
            _require_string_list(
                list(self.depends_on), field_name="depends_on", owner=owner
            ),
        )
        if self.subgoal_id in self.depends_on:
            raise TacticianValidationError(
                f"{owner} rejects self-dependency on {self.subgoal_id!r}"
            )
        object.__setattr__(
            self,
            "addresses_gaps",
            _require_string_list(
                list(self.addresses_gaps), field_name="addresses_gaps", owner=owner
            ),
        )
        if self.rationale:
            object.__setattr__(
                self,
                "rationale",
                _require_nonempty_str(
                    self.rationale,
                    field_name="rationale",
                    owner=owner,
                    max_length=MAX_STRING_FIELD_LENGTH,
                ),
            )

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "addresses_gaps": list(self.addresses_gaps),
            "depends_on": list(self.depends_on),
            "parent_goal_id": self.parent_goal_id,
            "rationale": self.rationale,
            "schema_version": self.schema_version,
            "statement_ref": self.statement_ref,
            "subgoal_id": self.subgoal_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TacticianSubgoal":
        subgoal = cls(
            subgoal_id=str(data.get("subgoal_id", "")),
            parent_goal_id=str(data.get("parent_goal_id", "")),
            statement_ref=str(data.get("statement_ref", "")),
            depends_on=list(data.get("depends_on") or []),
            addresses_gaps=list(data.get("addresses_gaps") or []),
            rationale=str(data.get("rationale") or ""),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )
        subgoal.validate()
        return subgoal


@dataclass(frozen=True)
class TacticianPolicy:
    """Operator-controlled bounds and source-class ordering for planning.

    The planner performs no proof, write, or network work. Capability flags
    that would imply those effects are fixed closed by validation.
    """

    policy_id: str
    source_class_order: List[str] = field(default_factory=list)
    max_sources: int = 32
    max_routes: int = 32
    max_subgoals: int = 16
    max_query_hints_per_source: int = 16
    max_refinement_rounds: int = 4
    allow_learned_ranking: bool = False
    allow_llm_nomination: bool = False
    learned_model_digest: str = ""
    llm_model_digest: str = ""
    denied_source_classes: List[str] = field(default_factory=list)
    stop_conditions: List[str] = field(
        default_factory=lambda: [
            "all_selected_routes_exhausted",
            "max_routes_reached",
            "max_subgoals_reached",
            "no_remaining_proof_gaps",
        ]
    )
    abstain_conditions: List[str] = field(
        default_factory=lambda: [
            "no_admissible_sources",
            "subgoal_cycle",
            "budget_exhausted_with_open_gaps",
            "authority_promotion_attempt",
        ]
    )
    network_allowed: bool = False
    write_allowed: bool = False
    proof_execution_allowed: bool = False
    semantic_authority: bool = False
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        owner = "TacticianPolicy"
        _require_schema_version(self.schema_version, owner=owner)
        object.__setattr__(
            self,
            "policy_id",
            _require_nonempty_str(self.policy_id, field_name="policy_id", owner=owner),
        )
        object.__setattr__(
            self,
            "source_class_order",
            _require_string_list(
                list(self.source_class_order),
                field_name="source_class_order",
                owner=owner,
            ),
        )
        object.__setattr__(
            self,
            "max_sources",
            _require_positive_int(self.max_sources, field_name="max_sources", owner=owner),
        )
        object.__setattr__(
            self,
            "max_routes",
            _require_positive_int(self.max_routes, field_name="max_routes", owner=owner),
        )
        object.__setattr__(
            self,
            "max_subgoals",
            _require_positive_int(
                self.max_subgoals, field_name="max_subgoals", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "max_query_hints_per_source",
            _require_positive_int(
                self.max_query_hints_per_source,
                field_name="max_query_hints_per_source",
                owner=owner,
            ),
        )
        object.__setattr__(
            self,
            "max_refinement_rounds",
            _require_positive_int(
                self.max_refinement_rounds,
                field_name="max_refinement_rounds",
                owner=owner,
            ),
        )
        object.__setattr__(
            self,
            "allow_learned_ranking",
            _require_bool(
                self.allow_learned_ranking,
                field_name="allow_learned_ranking",
                owner=owner,
            ),
        )
        object.__setattr__(
            self,
            "allow_llm_nomination",
            _require_bool(
                self.allow_llm_nomination,
                field_name="allow_llm_nomination",
                owner=owner,
            ),
        )
        if self.allow_learned_ranking:
            object.__setattr__(
                self,
                "learned_model_digest",
                _require_nonempty_str(
                    self.learned_model_digest,
                    field_name="learned_model_digest",
                    owner=owner,
                    max_length=MAX_OPAQUE_ROOT_LENGTH,
                ),
            )
        elif self.learned_model_digest:
            object.__setattr__(
                self,
                "learned_model_digest",
                _require_nonempty_str(
                    self.learned_model_digest,
                    field_name="learned_model_digest",
                    owner=owner,
                    max_length=MAX_OPAQUE_ROOT_LENGTH,
                ),
            )
        if self.allow_llm_nomination:
            object.__setattr__(
                self,
                "llm_model_digest",
                _require_nonempty_str(
                    self.llm_model_digest,
                    field_name="llm_model_digest",
                    owner=owner,
                    max_length=MAX_OPAQUE_ROOT_LENGTH,
                ),
            )
        elif self.llm_model_digest:
            object.__setattr__(
                self,
                "llm_model_digest",
                _require_nonempty_str(
                    self.llm_model_digest,
                    field_name="llm_model_digest",
                    owner=owner,
                    max_length=MAX_OPAQUE_ROOT_LENGTH,
                ),
            )
        object.__setattr__(
            self,
            "denied_source_classes",
            _require_string_list(
                list(self.denied_source_classes),
                field_name="denied_source_classes",
                owner=owner,
            ),
        )
        object.__setattr__(
            self,
            "stop_conditions",
            _require_string_list(
                list(self.stop_conditions),
                field_name="stop_conditions",
                owner=owner,
                allow_empty=False,
            ),
        )
        object.__setattr__(
            self,
            "abstain_conditions",
            _require_string_list(
                list(self.abstain_conditions),
                field_name="abstain_conditions",
                owner=owner,
                allow_empty=False,
            ),
        )
        for flag_name in (
            "network_allowed",
            "write_allowed",
            "proof_execution_allowed",
            "semantic_authority",
        ):
            flag_value = getattr(self, flag_name)
            _require_bool(flag_value, field_name=flag_name, owner=owner)
            if flag_value is True:
                raise TacticianValidationError(
                    f"{owner}.{flag_name} must remain False "
                    f"(Tactician never proves, writes, networks, or holds authority)"
                )

    def source_class_rank(self, source_class: str) -> int:
        """Return policy rank for ``source_class`` (lower is earlier).

        Unknown classes sort after every ordered class, then by name for
        stability.
        """

        try:
            return self.source_class_order.index(source_class)
        except ValueError:
            return len(self.source_class_order)

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "abstain_conditions": list(self.abstain_conditions),
            "allow_learned_ranking": self.allow_learned_ranking,
            "allow_llm_nomination": self.allow_llm_nomination,
            "denied_source_classes": list(self.denied_source_classes),
            "learned_model_digest": self.learned_model_digest,
            "llm_model_digest": self.llm_model_digest,
            "max_query_hints_per_source": self.max_query_hints_per_source,
            "max_refinement_rounds": self.max_refinement_rounds,
            "max_routes": self.max_routes,
            "max_sources": self.max_sources,
            "max_subgoals": self.max_subgoals,
            "network_allowed": self.network_allowed,
            "policy_id": self.policy_id,
            "proof_execution_allowed": self.proof_execution_allowed,
            "schema_version": self.schema_version,
            "semantic_authority": self.semantic_authority,
            "source_class_order": list(self.source_class_order),
            "stop_conditions": list(self.stop_conditions),
            "write_allowed": self.write_allowed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TacticianPolicy":
        policy = cls(
            policy_id=str(data.get("policy_id", "")),
            source_class_order=list(data.get("source_class_order") or []),
            max_sources=int(data.get("max_sources", 32)),
            max_routes=int(data.get("max_routes", 32)),
            max_subgoals=int(data.get("max_subgoals", 16)),
            max_query_hints_per_source=int(
                data.get("max_query_hints_per_source", 16)
            ),
            max_refinement_rounds=int(data.get("max_refinement_rounds", 4)),
            allow_learned_ranking=bool(data.get("allow_learned_ranking", False)),
            allow_llm_nomination=bool(data.get("allow_llm_nomination", False)),
            learned_model_digest=str(data.get("learned_model_digest") or ""),
            llm_model_digest=str(data.get("llm_model_digest") or ""),
            denied_source_classes=list(data.get("denied_source_classes") or []),
            stop_conditions=list(
                data.get("stop_conditions")
                or [
                    "all_selected_routes_exhausted",
                    "max_routes_reached",
                    "max_subgoals_reached",
                    "no_remaining_proof_gaps",
                ]
            ),
            abstain_conditions=list(
                data.get("abstain_conditions")
                or [
                    "no_admissible_sources",
                    "subgoal_cycle",
                    "budget_exhausted_with_open_gaps",
                    "authority_promotion_attempt",
                ]
            ),
            network_allowed=bool(data.get("network_allowed", False)),
            write_allowed=bool(data.get("write_allowed", False)),
            proof_execution_allowed=bool(data.get("proof_execution_allowed", False)),
            semantic_authority=bool(data.get("semantic_authority", False)),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )
        policy.validate()
        return policy


@dataclass(frozen=True)
class TacticianPlan:
    """Finite, acyclic, content-addressed search/decomposition plan.

    ``plan_id`` is always a content digest over the plan body. The planner
    never sets ``semantic_authority`` to true.
    """

    plan_id: str
    goal_id: str
    goal_root: str
    corpus_root: str
    config_root: str
    authority_roots: Dict[str, str]
    policy_id: str
    planner_id: str
    selected_routes: List[TacticianRoute]
    excluded_routes: List[TacticianRoute]
    proof_gaps: List[str]
    subgoals: List[TacticianSubgoal]
    stop_conditions: List[str]
    abstain_conditions: List[str]
    stop_disposition: StopDisposition = StopDisposition.CONTINUE
    learned_guidance_applied: bool = False
    learned_model_digest: str = ""
    llm_guidance_applied: bool = False
    llm_model_digest: str = ""
    semantic_authority: bool = False
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        owner = "TacticianPlan"
        _require_schema_version(self.schema_version, owner=owner)
        object.__setattr__(
            self,
            "plan_id",
            _require_nonempty_str(
                self.plan_id,
                field_name="plan_id",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "goal_id",
            _require_nonempty_str(self.goal_id, field_name="goal_id", owner=owner),
        )
        object.__setattr__(
            self,
            "goal_root",
            _require_nonempty_str(
                self.goal_root,
                field_name="goal_root",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "corpus_root",
            _require_nonempty_str(
                self.corpus_root,
                field_name="corpus_root",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "config_root",
            _require_nonempty_str(
                self.config_root,
                field_name="config_root",
                owner=owner,
                max_length=MAX_OPAQUE_ROOT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "authority_roots",
            _require_opaque_roots(
                dict(self.authority_roots), field_name="authority_roots", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "policy_id",
            _require_nonempty_str(self.policy_id, field_name="policy_id", owner=owner),
        )
        object.__setattr__(
            self,
            "planner_id",
            _require_nonempty_str(
                self.planner_id, field_name="planner_id", owner=owner
            ),
        )
        if not isinstance(self.selected_routes, list) or not isinstance(
            self.excluded_routes, list
        ):
            raise TacticianValidationError(
                f"{owner} route fields must be lists of TacticianRoute"
            )
        if len(self.selected_routes) + len(self.excluded_routes) > MAX_LIST_LENGTH * 2:
            raise TacticianValidationError(f"{owner} route lists exceed bounds")
        for route in self.selected_routes:
            if not isinstance(route, TacticianRoute):
                raise TacticianValidationError(
                    f"{owner}.selected_routes must contain TacticianRoute"
                )
            route.validate()
            if route.disposition is not RouteDisposition.SELECTED:
                raise TacticianValidationError(
                    f"{owner}.selected_routes must have disposition=selected"
                )
        for route in self.excluded_routes:
            if not isinstance(route, TacticianRoute):
                raise TacticianValidationError(
                    f"{owner}.excluded_routes must contain TacticianRoute"
                )
            route.validate()
            if route.disposition is not RouteDisposition.EXCLUDED:
                raise TacticianValidationError(
                    f"{owner}.excluded_routes must have disposition=excluded"
                )
        route_ids = [r.route_id for r in self.selected_routes] + [
            r.route_id for r in self.excluded_routes
        ]
        if len(route_ids) != len(set(route_ids)):
            raise TacticianValidationError(f"{owner} rejects duplicate route identities")
        source_ids = [r.source_id for r in self.selected_routes] + [
            r.source_id for r in self.excluded_routes
        ]
        if len(source_ids) != len(set(source_ids)):
            raise TacticianValidationError(
                f"{owner} rejects duplicate source identities across routes"
            )
        object.__setattr__(
            self,
            "proof_gaps",
            _require_string_list(
                list(self.proof_gaps), field_name="proof_gaps", owner=owner
            ),
        )
        if not isinstance(self.subgoals, list) or len(self.subgoals) > MAX_LIST_LENGTH:
            raise TacticianValidationError(f"{owner}.subgoals exceeds bounds")
        subgoal_ids: List[str] = []
        dep_graph: Dict[str, List[str]] = {}
        for subgoal in self.subgoals:
            if not isinstance(subgoal, TacticianSubgoal):
                raise TacticianValidationError(
                    f"{owner}.subgoals must contain TacticianSubgoal"
                )
            subgoal.validate()
            if subgoal.parent_goal_id != self.goal_id:
                raise TacticianValidationError(
                    f"{owner} subgoal parent_goal_id must match plan goal_id"
                )
            subgoal_ids.append(subgoal.subgoal_id)
            dep_graph[subgoal.subgoal_id] = list(subgoal.depends_on)
        if len(subgoal_ids) != len(set(subgoal_ids)):
            raise TacticianValidationError(
                f"{owner} rejects duplicate subgoal identities"
            )
        cycle = detect_cycle(dep_graph)
        if cycle is not None:
            raise TacticianValidationError(
                f"{owner} rejects cyclic subgoal decomposition: {' -> '.join(cycle)}"
            )
        object.__setattr__(
            self,
            "stop_conditions",
            _require_string_list(
                list(self.stop_conditions), field_name="stop_conditions", owner=owner
            ),
        )
        object.__setattr__(
            self,
            "abstain_conditions",
            _require_string_list(
                list(self.abstain_conditions),
                field_name="abstain_conditions",
                owner=owner,
            ),
        )
        if not isinstance(self.stop_disposition, StopDisposition):
            try:
                object.__setattr__(
                    self,
                    "stop_disposition",
                    StopDisposition(str(self.stop_disposition)),
                )
            except ValueError as exc:
                raise TacticianValidationError(
                    f"{owner}.stop_disposition must be a StopDisposition"
                ) from exc
        for flag_name in (
            "learned_guidance_applied",
            "llm_guidance_applied",
            "semantic_authority",
        ):
            _require_bool(
                getattr(self, flag_name), field_name=flag_name, owner=owner
            )
        if self.semantic_authority is True:
            raise TacticianValidationError(
                f"{owner}.semantic_authority must remain False"
            )
        if self.learned_guidance_applied and not self.learned_model_digest:
            raise TacticianValidationError(
                f"{owner} requires learned_model_digest when guidance is applied"
            )
        if self.llm_guidance_applied and not self.llm_model_digest:
            raise TacticianValidationError(
                f"{owner} requires llm_model_digest when guidance is applied"
            )
        body = self._body_dict()
        expected = compute_content_digest(body)
        if self.plan_id != expected:
            raise TacticianValidationError(
                f"{owner}.plan_id must equal content digest of the plan body"
            )

    def _body_dict(self) -> Dict[str, Any]:
        return {
            "abstain_conditions": list(self.abstain_conditions),
            "authority_roots": dict(self.authority_roots),
            "config_root": self.config_root,
            "corpus_root": self.corpus_root,
            "excluded_routes": [route.to_dict() for route in self.excluded_routes],
            "goal_id": self.goal_id,
            "goal_root": self.goal_root,
            "learned_guidance_applied": self.learned_guidance_applied,
            "learned_model_digest": self.learned_model_digest,
            "llm_guidance_applied": self.llm_guidance_applied,
            "llm_model_digest": self.llm_model_digest,
            "planner_id": self.planner_id,
            "policy_id": self.policy_id,
            "proof_gaps": list(self.proof_gaps),
            "schema_version": self.schema_version,
            "selected_routes": [route.to_dict() for route in self.selected_routes],
            "semantic_authority": False,
            "stop_conditions": list(self.stop_conditions),
            "stop_disposition": (
                self.stop_disposition.value
                if isinstance(self.stop_disposition, StopDisposition)
                else str(self.stop_disposition)
            ),
            "subgoals": [subgoal.to_dict() for subgoal in self.subgoals],
        }

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        payload = self._body_dict()
        payload["plan_id"] = self.plan_id
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TacticianPlan":
        plan = cls(
            plan_id=str(data.get("plan_id", "")),
            goal_id=str(data.get("goal_id", "")),
            goal_root=str(data.get("goal_root", "")),
            corpus_root=str(data.get("corpus_root", "")),
            config_root=str(data.get("config_root", "")),
            authority_roots=dict(data.get("authority_roots") or {}),
            policy_id=str(data.get("policy_id", "")),
            planner_id=str(data.get("planner_id", "")),
            selected_routes=[
                TacticianRoute.from_dict(item)
                for item in list(data.get("selected_routes") or [])
            ],
            excluded_routes=[
                TacticianRoute.from_dict(item)
                for item in list(data.get("excluded_routes") or [])
            ],
            proof_gaps=list(data.get("proof_gaps") or []),
            subgoals=[
                TacticianSubgoal.from_dict(item)
                for item in list(data.get("subgoals") or [])
            ],
            stop_conditions=list(data.get("stop_conditions") or []),
            abstain_conditions=list(data.get("abstain_conditions") or []),
            stop_disposition=StopDisposition(
                str(data.get("stop_disposition", StopDisposition.CONTINUE.value))
            ),
            learned_guidance_applied=bool(
                data.get("learned_guidance_applied", False)
            ),
            learned_model_digest=str(data.get("learned_model_digest") or ""),
            llm_guidance_applied=bool(data.get("llm_guidance_applied", False)),
            llm_model_digest=str(data.get("llm_model_digest") or ""),
            semantic_authority=bool(data.get("semantic_authority", False)),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )
        plan.validate()
        return plan

    @classmethod
    def build(
        cls,
        *,
        goal_id: str,
        goal_root: str,
        corpus_root: str,
        config_root: str,
        authority_roots: Mapping[str, str],
        policy_id: str,
        planner_id: str,
        selected_routes: Sequence[TacticianRoute],
        excluded_routes: Sequence[TacticianRoute],
        proof_gaps: Sequence[str],
        subgoals: Sequence[TacticianSubgoal],
        stop_conditions: Sequence[str],
        abstain_conditions: Sequence[str],
        stop_disposition: StopDisposition = StopDisposition.CONTINUE,
        learned_guidance_applied: bool = False,
        learned_model_digest: str = "",
        llm_guidance_applied: bool = False,
        llm_model_digest: str = "",
        schema_version: str = SCHEMA_VERSION,
    ) -> "TacticianPlan":
        """Construct a plan with a content-derived ``plan_id``."""

        provisional = cls(
            plan_id="pending",
            goal_id=goal_id,
            goal_root=goal_root,
            corpus_root=corpus_root,
            config_root=config_root,
            authority_roots=dict(authority_roots),
            policy_id=policy_id,
            planner_id=planner_id,
            selected_routes=list(selected_routes),
            excluded_routes=list(excluded_routes),
            proof_gaps=list(proof_gaps),
            subgoals=list(subgoals),
            stop_conditions=list(stop_conditions),
            abstain_conditions=list(abstain_conditions),
            stop_disposition=stop_disposition,
            learned_guidance_applied=learned_guidance_applied,
            learned_model_digest=learned_model_digest,
            llm_guidance_applied=llm_guidance_applied,
            llm_model_digest=llm_model_digest,
            semantic_authority=False,
            schema_version=schema_version,
        )
        # Validate nested fields before hashing body (plan_id check deferred).
        for route in provisional.selected_routes + provisional.excluded_routes:
            route.validate()
        for subgoal in provisional.subgoals:
            subgoal.validate()
        plan_id = compute_content_digest(provisional._body_dict())
        plan = cls(
            plan_id=plan_id,
            goal_id=provisional.goal_id,
            goal_root=provisional.goal_root,
            corpus_root=provisional.corpus_root,
            config_root=provisional.config_root,
            authority_roots=provisional.authority_roots,
            policy_id=provisional.policy_id,
            planner_id=provisional.planner_id,
            selected_routes=provisional.selected_routes,
            excluded_routes=provisional.excluded_routes,
            proof_gaps=provisional.proof_gaps,
            subgoals=provisional.subgoals,
            stop_conditions=provisional.stop_conditions,
            abstain_conditions=provisional.abstain_conditions,
            stop_disposition=provisional.stop_disposition,
            learned_guidance_applied=provisional.learned_guidance_applied,
            learned_model_digest=provisional.learned_model_digest,
            llm_guidance_applied=provisional.llm_guidance_applied,
            llm_model_digest=provisional.llm_model_digest,
            semantic_authority=False,
            schema_version=provisional.schema_version,
        )
        plan.validate()
        return plan


__all__ = [
    "TACTICIAN_INTERFACE",
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "MAX_ID_LENGTH",
    "MAX_OPAQUE_ROOT_LENGTH",
    "MAX_STRING_FIELD_LENGTH",
    "MAX_QUERY_HINT_LENGTH",
    "MAX_LIST_LENGTH",
    "MAX_MAP_ENTRIES",
    "MAX_NESTING_DEPTH",
    "MAX_METADATA_JSON_BYTES",
    "TacticianError",
    "TacticianValidationError",
    "RouteDisposition",
    "StopDisposition",
    "TacticianGoal",
    "TacticianSource",
    "TacticianRoute",
    "TacticianSubgoal",
    "TacticianPolicy",
    "TacticianPlan",
    "canonical_json_bytes",
    "compute_content_digest",
    "detect_cycle",
]
