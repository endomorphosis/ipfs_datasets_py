"""Closed, canonical semantic task-plan contracts.

This module owns the meaning and content identity of a task plan.  It is
deliberately not an executor, scheduler, or admission authority: consumers may
use a :class:`TaskContract` to decide what work is described, but must enforce
its budgets, paths, and effects themselves.

The contract is fail closed.  Every identity-bearing input is part of the
canonical CID payload; unknown fields, non-canonical lists, stale witnesses,
uncovered required obligations, and out-of-scope mutations are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)


TASK_CONTRACT_SCHEMA: Final[str] = "aseh/task-contract@1"
COMPLETENESS_WITNESS_SCHEMA: Final[str] = "aseh/completeness-witness@1"
TASK_CONTRACT_INTERFACE: Final[str] = "SemanticTaskContract@1"
TASK_CONTRACT_PRODUCER: Final[str] = (
    "ipfs_datasets_py.logic.software_contracts.semantic_state.task_contract"
)
SCHEMA_PATH: Final[Path] = Path(__file__).with_name("task_contract.schema.json")

_GIT_OID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
_MAX_TEXT: Final[int] = 16_384
_MAX_ITEMS: Final[int] = 4_096
_MAX_JSON_INT: Final[int] = 9_007_199_254_740_991
_EFFECT_KINDS: Final[frozenset[str]] = frozenset(
    {"read", "write", "delete", "rename", "execute"}
)
_MUTATING_EFFECT_KINDS: Final[frozenset[str]] = frozenset(
    {"write", "delete", "rename"}
)
_OBLIGATION_KINDS: Final[frozenset[str]] = frozenset(
    {"acceptance", "test", "proof"}
)

CANONICAL_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "interface",
    "producer",
    "task_id",
    "objective_revision",
    "repository_commit",
    "repository_tree",
    "policy_identity",
    "assumptions",
    "guarantees",
    "cone",
    "interfaces",
    "permitted_paths",
    "side_effects",
    "acceptance",
    "validation",
    "questions",
    "obligations",
    "budget",
    "fallback",
    "recovery",
    "completeness_witness",
)
ENVELOPE_FIELDS: Final[tuple[str, ...]] = CANONICAL_FIELDS + ("task_contract_cid",)


class TaskContractError(ValueError):
    """Raised when a semantic task-plan contract is malformed or unsafe."""


def _error(message: str) -> TaskContractError:
    return TaskContractError(message)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise _error(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise _error(f"{name} must be trimmed NFC text")
    if len(value) > _MAX_TEXT or any(not char.isprintable() for char in value):
        raise _error(f"{name} contains invalid text")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise _error(f"{name} must be a valid CID") from exc


def _oid(value: Any, name: str) -> str:
    text = _text(value, name)
    if _GIT_OID_RE.fullmatch(text) is None:
        raise _error(f"{name} must be a lowercase git object id")
    return text


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise _error(f"{name} must be an integer")
    if value < 0 or value > _MAX_JSON_INT or (positive and value == 0):
        qualifier = "a positive" if positive else "a nonnegative"
        raise _error(f"{name} must be {qualifier} JSON-safe integer")
    return value


def _closed(value: Any, fields: Sequence[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"{name} must be a mapping")
    actual = set(value)
    expected = set(fields)
    missing = expected - actual
    extra = actual - expected
    if missing:
        raise _error(f"{name} omitted required field(s) {sorted(missing)}")
    if extra:
        raise _error(f"{name} has unknown field(s) {sorted(extra)}")
    return {field: value[field] for field in fields}


def _sorted_unique_texts(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise _error(f"{name} must be a list")
    if len(value) > _MAX_ITEMS:
        raise _error(f"{name} exceeds maximum length")
    items = [_text(item, name) for item in value]
    if len(set(items)) != len(items):
        raise _error(f"{name} must not contain duplicates")
    return sorted(items)


def _repository_path(value: Any, name: str) -> str:
    path = _text(value, name)
    if path.startswith("/") or "\\" in path:
        raise _error(f"{name} must be a repository-relative POSIX path")
    components = path.split("/")
    if any(part in {"", ".", ".."} for part in components):
        raise _error(f"{name} must be a normalized repository-relative path")
    return path


def _sorted_paths(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise _error(f"{name} must be a list")
    if len(value) > _MAX_ITEMS:
        raise _error(f"{name} exceeds maximum length")
    paths = [_repository_path(item, name) for item in value]
    if len(set(paths)) != len(paths):
        raise _error(f"{name} must not contain duplicates")
    return sorted(paths)


def _records_by_id(
    value: Any,
    name: str,
    fields: Sequence[str],
    normalizer: Any,
) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise _error(f"{name} must be a list")
    if len(value) > _MAX_ITEMS:
        raise _error(f"{name} exceeds maximum length")
    records = [normalizer(_closed(item, fields, name), f"{name}[{index}]") for index, item in enumerate(value)]
    identifiers = [record["id"] for record in records]
    if len(set(identifiers)) != len(identifiers):
        raise _error(f"{name} must not contain duplicate ids")
    return sorted(records, key=lambda record: record["id"])


def _fact(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    return {"id": _text(record["id"], f"{name}.id"), "statement": _text(record["statement"], f"{name}.statement")}


def _guarantee(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    return {
        "id": _text(record["id"], f"{name}.id"),
        "statement": _text(record["statement"], f"{name}.statement"),
        "under_assumptions": _sorted_unique_texts(
            record["under_assumptions"], f"{name}.under_assumptions"
        ),
    }


def _effect(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    kind = _text(record["kind"], f"{name}.kind")
    if kind not in _EFFECT_KINDS:
        raise _error(f"{name}.kind has unsupported value {kind!r}")
    return {
        "id": _text(record["id"], f"{name}.id"),
        "kind": kind,
        "paths": _sorted_paths(record["paths"], f"{name}.paths"),
        "description": _text(record["description"], f"{name}.description"),
    }


def _test(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    return {"id": _text(record["id"], f"{name}.id"), "command": _text(record["command"], f"{name}.command")}


def _proof(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    return {"id": _text(record["id"], f"{name}.id"), "claim": _text(record["claim"], f"{name}.claim")}


def _question(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    blocking = record["blocking"]
    if type(blocking) is not bool:
        raise _error(f"{name}.blocking must be a boolean")
    return {"id": _text(record["id"], f"{name}.id"), "question": _text(record["question"], f"{name}.question"), "blocking": blocking}


def _obligation(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    kind = _text(record["kind"], f"{name}.kind")
    if kind not in _OBLIGATION_KINDS:
        raise _error(f"{name}.kind has unsupported value {kind!r}")
    required = record["required"]
    if type(required) is not bool:
        raise _error(f"{name}.required must be a boolean")
    return {"id": _text(record["id"], f"{name}.id"), "kind": kind, "subject_id": _text(record["subject_id"], f"{name}.subject_id"), "required": required}


def _cone(value: Any) -> dict[str, Any]:
    raw = _closed(value, ("affected_symbols", "affected_paths", "dependencies", "dependents"), "cone")
    return {
        "affected_symbols": _sorted_unique_texts(raw["affected_symbols"], "cone.affected_symbols"),
        "affected_paths": _sorted_paths(raw["affected_paths"], "cone.affected_paths"),
        "dependencies": _sorted_unique_texts(raw["dependencies"], "cone.dependencies"),
        "dependents": _sorted_unique_texts(raw["dependents"], "cone.dependents"),
    }


def _budget(value: Any) -> dict[str, Any]:
    fields = ("max_tokens", "max_tool_calls", "max_wall_time_seconds")
    raw = _closed(value, fields + ("validation_reserve",), "budget")
    maximum = {field: _integer(raw[field], f"budget.{field}", positive=True) for field in fields}
    reserve_raw = _closed(raw["validation_reserve"], fields, "budget.validation_reserve")
    reserve = {field: _integer(reserve_raw[field], f"budget.validation_reserve.{field}", positive=True) for field in fields}
    for field in fields:
        if reserve[field] >= maximum[field]:
            raise _error(f"budget.validation_reserve.{field} must leave implementation capacity")
    return {**maximum, "validation_reserve": reserve}


def _fallback(value: Any) -> dict[str, Any]:
    raw = _closed(value, ("trigger", "action"), "fallback")
    return {field: _text(raw[field], f"fallback.{field}") for field in raw}


def _recovery(value: Any) -> dict[str, Any]:
    raw = _closed(value, ("trigger", "rollback", "retry"), "recovery")
    return {field: _text(raw[field], f"recovery.{field}") for field in raw}


def _witness(value: Any, *, identity: Mapping[str, str], required_obligation_ids: Sequence[str], blocking_questions: bool) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = _closed(value, ("schema", "witness_cid", "task_id", "objective_revision", "repository_commit", "repository_tree", "policy_identity", "obligation_ids"), "completeness_witness")
    witness = {
        "schema": _text(raw["schema"], "completeness_witness.schema"),
        "witness_cid": _cid(raw["witness_cid"], "completeness_witness.witness_cid"),
        "task_id": _text(raw["task_id"], "completeness_witness.task_id"),
        "objective_revision": _text(raw["objective_revision"], "completeness_witness.objective_revision"),
        "repository_commit": _oid(raw["repository_commit"], "completeness_witness.repository_commit"),
        "repository_tree": _oid(raw["repository_tree"], "completeness_witness.repository_tree"),
        "policy_identity": _text(raw["policy_identity"], "completeness_witness.policy_identity"),
        "obligation_ids": _sorted_unique_texts(raw["obligation_ids"], "completeness_witness.obligation_ids"),
    }
    if witness["schema"] != COMPLETENESS_WITNESS_SCHEMA:
        raise _error("completeness_witness has an unsupported schema")
    for field, expected in identity.items():
        if witness[field] != expected:
            raise _error(f"completeness_witness.{field} is stale for the task identity")
    if witness["obligation_ids"] != sorted(required_obligation_ids):
        raise _error("completeness_witness must cover exactly every required obligation")
    if blocking_questions:
        raise _error("a task with blocking questions cannot claim a completeness witness")
    return witness


def _canonical_payload(
    *,
    task_id: Any,
    objective_revision: Any,
    repository_commit: Any,
    repository_tree: Any,
    policy_identity: Any,
    assumptions: Any,
    guarantees: Any,
    cone: Any,
    interfaces: Any,
    permitted_paths: Any,
    side_effects: Any,
    acceptance: Any,
    tests: Any,
    proofs: Any,
    questions: Any,
    obligations: Any,
    budget: Any,
    fallback: Any,
    recovery: Any,
    completeness_witness: Any,
) -> dict[str, Any]:
    task_id_value = _text(task_id, "task_id")
    identity = {
        "task_id": task_id_value,
        "objective_revision": _text(objective_revision, "objective_revision"),
        "repository_commit": _oid(repository_commit, "repository_commit"),
        "repository_tree": _oid(repository_tree, "repository_tree"),
        "policy_identity": _text(policy_identity, "policy_identity"),
    }
    normalized_assumptions = _records_by_id(assumptions, "assumptions", ("id", "statement"), _fact)
    assumption_ids = {item["id"] for item in normalized_assumptions}
    normalized_guarantees = _records_by_id(guarantees, "guarantees", ("id", "statement", "under_assumptions"), _guarantee)
    for guarantee in normalized_guarantees:
        unknown = set(guarantee["under_assumptions"]) - assumption_ids
        if unknown:
            raise _error(f"guarantees[{guarantee['id']}] references unknown assumptions {sorted(unknown)}")
    used_assumptions = {item for guarantee in normalized_guarantees for item in guarantee["under_assumptions"]}
    if used_assumptions != assumption_ids:
        raise _error("every assumption must condition at least one guarantee")

    normalized_acceptance = _records_by_id(acceptance, "acceptance", ("id", "statement"), _fact)
    normalized_tests = _records_by_id(tests, "validation.tests", ("id", "command"), _test)
    normalized_proofs = _records_by_id(proofs, "validation.proofs", ("id", "claim"), _proof)
    normalized_obligations = _records_by_id(obligations, "obligations", ("id", "kind", "subject_id", "required"), _obligation)
    subjects = {
        "acceptance": {item["id"] for item in normalized_acceptance},
        "test": {item["id"] for item in normalized_tests},
        "proof": {item["id"] for item in normalized_proofs},
    }
    for obligation in normalized_obligations:
        if obligation["subject_id"] not in subjects[obligation["kind"]]:
            raise _error(f"obligations[{obligation['id']}] references an unknown {obligation['kind']} subject")
    for kind, subject_ids in subjects.items():
        covered = {item["subject_id"] for item in normalized_obligations if item["kind"] == kind}
        if covered != subject_ids:
            raise _error(f"every {kind} fact must have one obligation")
    if not normalized_obligations:
        raise _error("obligations must not be empty")

    normalized_paths = _sorted_paths(permitted_paths, "permitted_paths")
    permitted = set(normalized_paths)
    normalized_effects = _records_by_id(side_effects, "side_effects", ("id", "kind", "paths", "description"), _effect)
    for effect in normalized_effects:
        if effect["kind"] in _MUTATING_EFFECT_KINDS:
            if not effect["paths"]:
                raise _error(f"side_effects[{effect['id']}] mutation requires an explicit path")
            outside = set(effect["paths"]) - permitted
            if outside:
                raise _error(f"side_effects[{effect['id']}] mutates path(s) outside permitted_paths {sorted(outside)}")

    normalized_questions = _records_by_id(questions, "questions", ("id", "question", "blocking"), _question)
    required_ids = [item["id"] for item in normalized_obligations if item["required"]]
    witness = _witness(completeness_witness, identity=identity, required_obligation_ids=required_ids, blocking_questions=any(item["blocking"] for item in normalized_questions))
    payload = {
        "schema": TASK_CONTRACT_SCHEMA,
        "interface": TASK_CONTRACT_INTERFACE,
        "producer": TASK_CONTRACT_PRODUCER,
        "task_id": task_id_value,
        **identity,
        "assumptions": normalized_assumptions,
        "guarantees": normalized_guarantees,
        "cone": _cone(cone),
        "interfaces": _sorted_unique_texts(interfaces, "interfaces"),
        "permitted_paths": normalized_paths,
        "side_effects": normalized_effects,
        "acceptance": normalized_acceptance,
        "validation": {"tests": normalized_tests, "proofs": normalized_proofs},
        "questions": normalized_questions,
        "obligations": normalized_obligations,
        "budget": _budget(budget),
        "fallback": _fallback(fallback),
        "recovery": _recovery(recovery),
        "completeness_witness": witness,
    }
    try:
        validate_structured_value(payload, path="task_contract")
    except Exception as exc:
        raise _error(f"task contract is not a supported structured identity: {exc}") from exc
    return {field: payload[field] for field in CANONICAL_FIELDS}


def _payload_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _closed(value, CANONICAL_FIELDS, "task contract payload")
    if raw["schema"] != TASK_CONTRACT_SCHEMA or raw["interface"] != TASK_CONTRACT_INTERFACE:
        raise _error("task contract payload has an unsupported schema or interface")
    if raw["producer"] != TASK_CONTRACT_PRODUCER:
        raise _error("task contract payload has an untrusted producer")
    validation = _closed(raw["validation"], ("tests", "proofs"), "validation")
    return _canonical_payload(
        task_id=raw["task_id"], objective_revision=raw["objective_revision"],
        repository_commit=raw["repository_commit"], repository_tree=raw["repository_tree"],
        policy_identity=raw["policy_identity"], assumptions=raw["assumptions"],
        guarantees=raw["guarantees"], cone=raw["cone"], interfaces=raw["interfaces"],
        permitted_paths=raw["permitted_paths"], side_effects=raw["side_effects"],
        acceptance=raw["acceptance"], tests=validation["tests"], proofs=validation["proofs"],
        questions=raw["questions"], obligations=raw["obligations"], budget=raw["budget"],
        fallback=raw["fallback"], recovery=raw["recovery"],
        completeness_witness=raw["completeness_witness"],
    )


@dataclass(frozen=True)
class TaskContract:
    """Verified immutable view of a canonical task-plan contract."""

    task_contract_cid: str
    _canonical: Mapping[str, Any]

    def canonical_payload(self) -> dict[str, Any]:
        """Return a detached canonical CID payload."""
        return _thaw(self._canonical)

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.canonical_payload())

    def to_dict(self) -> dict[str, Any]:
        envelope = self.canonical_payload()
        envelope["task_contract_cid"] = self.task_contract_cid
        return envelope

    @property
    def is_complete(self) -> bool:
        """Whether this contract has a current identity-bound completeness witness."""
        return self._canonical["completeness_witness"] is not None

    def verify_identity(self) -> str:
        return decode_and_recompute_structured(self.task_contract_cid, self.canonical_payload())

    @classmethod
    def from_dict(cls, envelope: Mapping[str, Any]) -> "TaskContract":
        validated = validate_task_contract_envelope(envelope)
        return cls(
            validated["task_contract_cid"],
            _freeze({field: validated[field] for field in CANONICAL_FIELDS}),
        )


def build_task_contract(
    *, task_id: str, objective_revision: str, repository_commit: str, repository_tree: str,
    policy_identity: str, assumptions: Sequence[Mapping[str, Any]],
    guarantees: Sequence[Mapping[str, Any]], cone: Mapping[str, Any], interfaces: Sequence[str],
    permitted_paths: Sequence[str], side_effects: Sequence[Mapping[str, Any]],
    acceptance: Sequence[Mapping[str, Any]], tests: Sequence[Mapping[str, Any]],
    proofs: Sequence[Mapping[str, Any]], questions: Sequence[Mapping[str, Any]],
    obligations: Sequence[Mapping[str, Any]], budget: Mapping[str, Any], fallback: Mapping[str, Any],
    recovery: Mapping[str, Any], completeness_witness: Mapping[str, Any] | None,
) -> TaskContract:
    """Build a closed, CID-bound task plan from semantic facts.

    The caller supplies facts only.  This function establishes their canonical
    order and validates the cross-fact guarantees described in the module
    documentation; it never spends budget or authorizes an effect.
    """
    payload = _canonical_payload(
        task_id=task_id, objective_revision=objective_revision,
        repository_commit=repository_commit, repository_tree=repository_tree,
        policy_identity=policy_identity, assumptions=assumptions, guarantees=guarantees,
        cone=cone, interfaces=interfaces, permitted_paths=permitted_paths,
        side_effects=side_effects, acceptance=acceptance, tests=tests, proofs=proofs,
        questions=questions, obligations=obligations, budget=budget, fallback=fallback,
        recovery=recovery, completeness_witness=completeness_witness,
    )
    return TaskContract(cid_for_structured(payload), _freeze(payload))


def canonical_payload_from_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Extract and validate the exact canonical payload from an envelope."""
    raw = _closed(envelope, ENVELOPE_FIELDS, "task contract envelope")
    canonical = _payload_from_mapping({field: raw[field] for field in CANONICAL_FIELDS})
    if canonical != {field: raw[field] for field in CANONICAL_FIELDS}:
        raise _error("task contract envelope is not canonical")
    return canonical


def validate_task_contract_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on malformed, stale, non-canonical, or forged envelopes."""
    raw = _closed(envelope, ENVELOPE_FIELDS, "task contract envelope")
    canonical = canonical_payload_from_envelope(raw)
    claimed = _cid(raw["task_contract_cid"], "task_contract_cid")
    recomputed = cid_for_structured(canonical)
    if claimed != recomputed:
        raise _error("task_contract_cid does not match the canonical task contract")
    return {**canonical, "task_contract_cid": claimed}


def load_task_contract_schema() -> dict[str, Any]:
    """Load the package-local JSON Schema for closed task-contract envelopes."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


__all__ = [
    "CANONICAL_FIELDS", "COMPLETENESS_WITNESS_SCHEMA", "ENVELOPE_FIELDS", "SCHEMA_PATH", "TASK_CONTRACT_INTERFACE",
    "TASK_CONTRACT_PRODUCER", "TASK_CONTRACT_SCHEMA", "TaskContract", "TaskContractError",
    "build_task_contract", "canonical_payload_from_envelope", "load_task_contract_schema",
    "validate_task_contract_envelope",
]
