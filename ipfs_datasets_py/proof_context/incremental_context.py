"""Datasets-owned incremental ContextPack expansion (ASEH-034).

Generate a safe delta or affected-suffix pack bound to a parent pack.
Resolve only named missing CID, symbol, contract, test, counterexample, or
obligation references. Whole-repository expansion is a typed completeness
failure, never silent rediscovery. Retrieval and executor budgets remain
with Kit/Accelerate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.proof_context.context_pack import (
    AUTHORITY,
    INCREMENTAL_BUILDER_ID,
    INCREMENTAL_PACK_KINDS,
    INTERFACE,
    NAMED_MISSING_RECORD_FIELDS,
    TREE_CHANGE_TRIGGER,
    CompletenessFailure,
    ContextPackConstructionError,
    ContextPackRecord,
    CriticalOmissionError,
    UnboundParentError,
    bind_named_missing_references,
    build_incremental_semantic_pack,
    format_named_missing_reference,
    parent_pack_cid_from_envelope,
    parent_tree_oid_from_envelope,
    parse_named_missing_reference,
)
from ipfs_datasets_py.proof_context.contracts import StaleContextError

INCREMENTAL_INTERFACE: Final[str] = "DatasetsIncrementalContext@0.1"
WHOLE_REPOSITORY_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "*",
        "whole-repo",
        "whole_repo",
        "whole-repository",
        "whole_repository",
        "repository",
        "rediscover",
    }
)
CATALOG_FIELDS: Final[tuple[str, ...]] = NAMED_MISSING_RECORD_FIELDS


class IncrementalContextError(ContextPackConstructionError):
    """Fail-closed incremental expansion error."""

    reason = "invalid"


class MissingReferenceError(IncrementalContextError):
    reason = "missing_reference"


def _error(message: str) -> IncrementalContextError:
    return IncrementalContextError(message)


def _parent_envelope(
    parent: ContextPackRecord | Mapping[str, Any] | None,
) -> dict[str, Any]:
    if parent is None:
        raise UnboundParentError("unbound parent")
    if isinstance(parent, ContextPackRecord):
        return parent.to_dict()
    if not isinstance(parent, Mapping):
        raise UnboundParentError("unbound parent")
    return dict(parent)


def _string_tuple(values: Sequence[str] | Iterable[str]) -> tuple[str, ...]:
    items: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item not in seen:
            seen.add(item)
            items.append(item)
    return tuple(sorted(items))


def expansion_precision_recall(
    retrieved: Sequence[str],
    relevant: Sequence[str],
) -> tuple[int, int, int]:
    """Return ``(relevant_retrieved, retrieved_count, relevant_count)``.

    Precision is relevant_retrieved / retrieved_count; recall is
    relevant_retrieved / relevant_count. Empty-empty is exact (1/1).
    """
    retrieved_set = set(retrieved)
    relevant_set = set(relevant)
    relevant_retrieved = len(retrieved_set & relevant_set)
    retrieved_count = len(retrieved_set)
    relevant_count = len(relevant_set)
    return relevant_retrieved, retrieved_count, relevant_count


def compute_affected_suffix(
    ordered_files: Sequence[str],
    changed_files: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Preserve the unaffected prefix; return only the affected suffix."""

    if any(marker in WHOLE_REPOSITORY_MARKERS for marker in changed_files):
        raise CompletenessFailure(
            "whole-repository expansion requires a typed completeness failure"
        )
    ordered = tuple(ordered_files)
    changed = tuple(changed_files)
    changed_set = set(changed)
    start: int | None = None
    for index, path in enumerate(ordered):
        if path in changed_set:
            start = index
            break
    if start is None:
        prefix = ordered
        suffix = tuple(path for path in changed if path not in prefix)
        return prefix, suffix
    prefix = ordered[:start]
    suffix_list = list(ordered[start:])
    seen = set(suffix_list)
    for path in changed:
        if path not in seen and path not in prefix:
            suffix_list.append(path)
            seen.add(path)
    return prefix, tuple(suffix_list)


def evaluate_parent_tree_freshness(
    parent: ContextPackRecord | Mapping[str, Any],
    scanned_tree_oid: str,
) -> tuple[bool, tuple[str, ...]]:
    """Return ``(fresh, stale_fields)`` for exact parent-tree freshness."""

    envelope = _parent_envelope(parent)
    parent_tree = parent_tree_oid_from_envelope(envelope)
    if parent_tree != scanned_tree_oid:
        return False, (TREE_CHANGE_TRIGGER,)
    return True, ()


def require_parent_current_tree(
    parent: ContextPackRecord | Mapping[str, Any],
    scanned_tree_oid: str,
) -> None:
    """Reject reuse of a parent pack across a changed tree."""

    fresh, stale_fields = evaluate_parent_tree_freshness(parent, scanned_tree_oid)
    if not fresh:
        raise StaleContextError(
            "changed tree invalidates the parent ContextPack: "
            + ",".join(stale_fields)
        )


def _bind_catalog_record(item: Any, index: int) -> dict[str, Any]:
    name = f"catalog[{index}]"
    if not isinstance(item, Mapping):
        raise _error(f"{name} must be a mapping")
    extra = set(item) - set(CATALOG_FIELDS)
    if extra:
        raise _error(f"{name} unknown field {sorted(extra)}")
    missing = {"kind", "name"} - set(item)
    if missing:
        raise _error(f"{name} omitted view input {sorted(missing)}")
    kind, token_name = parse_named_missing_reference(
        {"kind": item["kind"], "name": item["name"]}
    )
    cid = item.get("cid")
    if cid is None:
        raise MissingReferenceError(f"missing reference {kind}:{token_name}")
    path = item.get("path")
    meaning = item.get("meaning")
    if path is not None and (type(path) is not str or not path):
        raise _error(f"{name}.path must be a nonempty string or omitted")
    if meaning is not None and (type(meaning) is not str or not meaning):
        raise _error(f"{name}.meaning must be a nonempty string or omitted")
    return {
        "kind": kind,
        "name": token_name,
        "cid": cid,
        "path": path,
        "meaning": meaning,
        "token": format_named_missing_reference(kind, token_name),
    }


def _bind_catalog(
    catalog: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if catalog is None:
        return {}
    records: list[dict[str, Any]]
    if isinstance(catalog, Mapping):
        records = []
        for index, (key, item) in enumerate(catalog.items()):
            if not isinstance(item, Mapping):
                raise _error(f"catalog[{key!r}] must be a mapping")
            payload = dict(item)
            if "kind" not in payload or "name" not in payload:
                kind, name = parse_named_missing_reference(key)
                payload.setdefault("kind", kind)
                payload.setdefault("name", name)
            records.append(_bind_catalog_record(payload, index))
    elif isinstance(catalog, (list, tuple)):
        records = [_bind_catalog_record(item, index) for index, item in enumerate(catalog)]
    else:
        raise _error("catalog must be a list or mapping")
    bound: dict[str, dict[str, Any]] = {}
    for record in records:
        token = record["token"]
        if token in bound:
            raise _error(f"catalog must not contain duplicate {token}")
        bound[token] = record
    return bound


def _source_cid(envelope: Mapping[str, Any], key: str, override: str | None) -> str:
    if override is not None:
        return override
    required = envelope.get("required_source_cids")
    if isinstance(required, Mapping) and required.get(key):
        return str(required[key])
    raise _error(f"missing reference {key}")


def _detect_whole_repository(
    *,
    whole_repository: bool,
    named_missing: Sequence[str],
    changed_files: Sequence[str],
    changed_symbols: Sequence[str],
    catalog_tokens: Sequence[str],
) -> None:
    if whole_repository:
        raise CompletenessFailure(
            "whole-repository expansion requires a typed completeness failure"
        )
    markers = (
        set(named_missing)
        | set(changed_files)
        | set(changed_symbols)
        | set(catalog_tokens)
    )
    for item in markers:
        tail = item.split(":", 1)[-1] if ":" in item else item
        if item in WHOLE_REPOSITORY_MARKERS or tail in WHOLE_REPOSITORY_MARKERS:
            raise CompletenessFailure(
                "whole-repository expansion requires a typed completeness failure"
            )


@dataclass(frozen=True)
class IncrementalExpansionResult:
    """Closed incremental expansion witness. Budgets are not admitted here."""

    pack: ContextPackRecord
    parent_pack_cid: str
    delta_cid: str
    pack_kind: str
    parent_invalidated: bool
    invalidation_triggers: tuple[str, ...]
    named_missing: tuple[str, ...]
    retrieved: tuple[str, ...]
    relevant: tuple[str, ...]
    affected_suffix: tuple[str, ...]
    preserved_prefix: tuple[str, ...]
    relevant_retrieved: int
    retrieved_count: int
    relevant_count: int
    builder_identity: str = INCREMENTAL_BUILDER_ID
    interface: str = INCREMENTAL_INTERFACE
    producer: str = AUTHORITY

    @property
    def precision(self) -> float:
        if self.retrieved_count == 0:
            return 1.0 if self.relevant_count == 0 else 0.0
        return self.relevant_retrieved / self.retrieved_count

    @property
    def recall(self) -> float:
        if self.relevant_count == 0:
            return 1.0
        return self.relevant_retrieved / self.relevant_count

    def to_dict(self) -> dict[str, Any]:
        envelope = self.pack.to_dict()
        return {
            "schema": INCREMENTAL_INTERFACE,
            "interface": INTERFACE,
            "builder_identity": self.builder_identity,
            "producer": self.producer,
            "parent_pack_cid": self.parent_pack_cid,
            "delta_cid": self.delta_cid,
            "pack_kind": self.pack_kind,
            "parent_invalidated": self.parent_invalidated,
            "invalidation_triggers": list(self.invalidation_triggers),
            "named_missing": list(self.named_missing),
            "retrieved": list(self.retrieved),
            "relevant": list(self.relevant),
            "affected_suffix": list(self.affected_suffix),
            "preserved_prefix": list(self.preserved_prefix),
            "relevant_retrieved": self.relevant_retrieved,
            "retrieved_count": self.retrieved_count,
            "relevant_count": self.relevant_count,
            "pack_cid": self.pack.pack_cid,
            "pack": envelope,
        }


def expand_incremental_pack(
    *,
    parent: ContextPackRecord | Mapping[str, Any] | None,
    scanned_tree_oid: str,
    named_missing: Sequence[Any] = (),
    catalog: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None = (),
    changed_files: Sequence[str] = (),
    changed_symbols: Sequence[str] = (),
    ordered_files: Sequence[str] | None = None,
    critical_dependencies: Sequence[str] = (),
    whole_repository: bool = False,
    source_tree_oid: str | None = None,
    repository_state_cid: str | None = None,
    target_source_cid: str | None = None,
    surrounding_source_cid: str | None = None,
    test_source_cid: str | None = None,
    task_id: str | None = None,
    pack_kind: str | None = None,
    **kwargs: Any,
) -> IncrementalExpansionResult:
    """Expand a parent pack by named missing references or an affected suffix.

    Extra catalog members are never retrieved. Whole-repository expansion
    raises :class:`CompletenessFailure`. Critical dependencies that are not
    named and not in the affected suffix fail closed.
    """
    envelope = _parent_envelope(parent)
    parent_cid = parent_pack_cid_from_envelope(
        parent if isinstance(parent, ContextPackRecord) else envelope
    )
    parent_tree = parent_tree_oid_from_envelope(envelope)
    bound_missing = bind_named_missing_references(list(named_missing))
    bound_catalog = _bind_catalog(catalog)
    changed_file_list = list(changed_files)
    changed_symbol_list = list(changed_symbols)
    _detect_whole_repository(
        whole_repository=whole_repository,
        named_missing=bound_missing,
        changed_files=changed_file_list,
        changed_symbols=changed_symbol_list,
        catalog_tokens=list(bound_catalog),
    )

    fresh, _stale_fields = evaluate_parent_tree_freshness(envelope, scanned_tree_oid)
    parent_invalidated = not fresh
    if not bound_missing and not changed_file_list and not changed_symbol_list:
        raise CompletenessFailure(
            "whole-repository expansion requires a typed completeness failure"
        )

    parent_scope = envelope.get("scope") if isinstance(envelope.get("scope"), Mapping) else {}
    parent_files = list(parent_scope.get("affected_files") or ())
    ordered = tuple(ordered_files) if ordered_files is not None else tuple(parent_files)
    if parent_invalidated or changed_file_list:
        preserved_prefix, affected_suffix = compute_affected_suffix(
            ordered, changed_file_list
        )
        selected_kind = pack_kind or "affected_suffix"
    else:
        preserved_prefix = ordered
        affected_suffix = ()
        selected_kind = pack_kind or "delta"
    if selected_kind not in INCREMENTAL_PACK_KINDS:
        raise _error(f"pack_kind has unsupported value {selected_kind!r}")
    if selected_kind == "delta" and (parent_invalidated or affected_suffix):
        # A changed tree is only safe as an affected-suffix pack.
        selected_kind = "affected_suffix"

    resolved: list[dict[str, Any]] = []
    retrieved_tokens: list[str] = []
    for token in bound_missing:
        record = bound_catalog.get(token)
        if record is None:
            raise MissingReferenceError(f"missing reference {token}")
        resolved.append(record)
        retrieved_tokens.append(token)

    extra_catalog = sorted(set(bound_catalog) - set(bound_missing))
    # Precision: unused catalog members stay with the parent; never retrieve them.
    if extra_catalog and any(
        item.split(":", 1)[-1] in WHOLE_REPOSITORY_MARKERS for item in extra_catalog
    ):
        raise CompletenessFailure(
            "whole-repository expansion requires a typed completeness failure"
        )

    for path in affected_suffix:
        retrieved_tokens.append(path)

    for symbol in changed_symbol_list:
        if symbol not in retrieved_tokens and symbol not in bound_missing:
            retrieved_tokens.append(symbol)

    relevant_tokens = list(bound_missing)
    relevant_tokens.extend(path for path in affected_suffix if path not in relevant_tokens)
    relevant_tokens.extend(
        symbol
        for symbol in changed_symbol_list
        if symbol not in relevant_tokens
        and format_named_missing_reference("symbol", symbol) not in relevant_tokens
    )

    omitted_critical: list[str] = []
    named_lookup = set(bound_missing)
    retrieved_lookup = set(retrieved_tokens)
    for item in critical_dependencies:
        aliases = {item}
        if ":" in item:
            aliases.add(item.split(":", 1)[-1])
        else:
            aliases.add(format_named_missing_reference("symbol", item))
            aliases.add(format_named_missing_reference("cid", item))
            aliases.add(format_named_missing_reference("obligation", item))
            aliases.add(format_named_missing_reference("contract", item))
            aliases.add(format_named_missing_reference("test", item))
            aliases.add(format_named_missing_reference("counterexample", item))
        if aliases.isdisjoint(named_lookup | retrieved_lookup | set(affected_suffix)):
            omitted_critical.append(item)
    if omitted_critical:
        raise CriticalOmissionError(
            f"critical omission {sorted(set(omitted_critical))}"
        )

    dependencies: list[dict[str, Any]] = []
    contract_names: list[str] = []
    test_names: list[str] = []
    counterexamples: list[str] = []
    obligations: list[str] = []
    for record in resolved:
        kind = record["kind"]
        name = record["name"]
        if kind in {"cid", "symbol"}:
            dependencies.append(
                {
                    "symbol": name if kind == "symbol" else record["token"],
                    "cid": record["cid"],
                    "path": record["path"] or (f"{name}.py" if kind == "symbol" else name),
                    "meaning": record["meaning"] or f"named missing {kind}",
                }
            )
        elif kind == "contract":
            contract_names.append(name)
            dependencies.append(
                {
                    "symbol": name,
                    "cid": record["cid"],
                    "path": record["path"] or f"contracts/{name}",
                    "meaning": record["meaning"] or "named missing contract",
                }
            )
        elif kind == "test":
            test_names.append(name)
            dependencies.append(
                {
                    "symbol": name,
                    "cid": record["cid"],
                    "path": record["path"] or f"tests/{name}",
                    "meaning": record["meaning"] or "named missing test",
                }
            )
        elif kind == "counterexample":
            counterexamples.append(name)
            dependencies.append(
                {
                    "symbol": name,
                    "cid": record["cid"],
                    "path": record["path"] or f"counterexamples/{name}",
                    "meaning": record["meaning"] or "named missing counterexample",
                }
            )
        elif kind == "obligation":
            obligations.append(name)
            dependencies.append(
                {
                    "symbol": name,
                    "cid": record["cid"],
                    "path": record["path"] or f"obligations/{name}",
                    "meaning": record["meaning"] or "named missing obligation",
                }
            )

    derived_contracts = {
        "applicable_api_contracts": contract_names,
        "assumptions_and_guarantees": [],
        "invariants": [],
        "security_constraints": [],
        "side_effect_classes": [],
        "allowed_mutation_scope": [],
    }
    derived_validation = {
        "known_tests": test_names,
        "selected_tests": test_names,
        "type_static_schema_checks": [],
        "proof_obligations": obligations,
        "required_full_suite_conditions": [],
        "current_authoritative_receipts": [],
    }
    derived_history = {
        "relevant_prior_failures": [],
        "relevant_counterexamples": counterexamples,
        "prior_accepted_patches": [],
        "stale_or_invalidated_receipts": [parent_cid] if parent_invalidated else [],
        "retry_and_rescue_history": [],
    }

    retrieved = _string_tuple(retrieved_tokens)
    relevant = _string_tuple(relevant_tokens)
    relevant_retrieved, retrieved_count, relevant_count = expansion_precision_recall(
        retrieved, relevant
    )
    if retrieved_count and relevant_retrieved != retrieved_count:
        raise CompletenessFailure(
            "expansion precision is not exact; unnamed members were retrieved"
        )
    if relevant_count and relevant_retrieved != relevant_count:
        raise CriticalOmissionError("expansion recall is not exact")

    repo_state = repository_state_cid or envelope.get("repository_state_cid")
    if not repo_state:
        raise _error("missing reference repository_state_cid")
    bound_task = task_id or envelope.get("task_id")
    if not bound_task:
        raise _error("missing reference task_id")

    passthrough = {
        key: value
        for key, value in {
            "task_class": envelope.get("task_class"),
            "risk_class": envelope.get("risk_class"),
            "route_tier": envelope.get("route_tier"),
            "identity_kind": envelope.get("identity_kind"),
            "evidence_kind": envelope.get("evidence_kind"),
            "execution_mode": envelope.get("execution_mode"),
            "repository_identity": envelope.get("identity", {}).get("repository_identity")
            if isinstance(envelope.get("identity"), Mapping)
            else envelope.get("repository_identity"),
            "commit": envelope.get("identity", {}).get("commit")
            if isinstance(envelope.get("identity"), Mapping)
            else envelope.get("commit"),
            "objective_identity": envelope.get("identity", {}).get("objective_identity")
            if isinstance(envelope.get("identity"), Mapping)
            else envelope.get("objective_identity"),
            "objective_revision": envelope.get("identity", {}).get("objective_revision")
            if isinstance(envelope.get("identity"), Mapping)
            else envelope.get("objective_revision"),
            "policy_identity": envelope.get("identity", {}).get("policy_identity")
            if isinstance(envelope.get("identity"), Mapping)
            else envelope.get("policy_identity"),
            "creation_time": envelope.get("identity", {}).get("creation_time")
            if isinstance(envelope.get("identity"), Mapping)
            else envelope.get("creation_time"),
        }.items()
        if value is not None and key not in kwargs
    }
    passthrough.update(kwargs)

    pack = build_incremental_semantic_pack(
        repository_state_cid=str(repo_state),
        task_id=str(bound_task),
        target_source_cid=_source_cid(envelope, "target_source", target_source_cid),
        surrounding_source_cid=_source_cid(
            envelope, "surrounding_source", surrounding_source_cid
        ),
        test_source_cid=_source_cid(envelope, "test_source", test_source_cid),
        scanned_tree_oid=scanned_tree_oid,
        source_tree_oid=source_tree_oid or scanned_tree_oid,
        parent_context_pack_cid=parent_cid,
        named_missing=bound_missing,
        changed_files=changed_file_list,
        changed_symbols=changed_symbol_list,
        pack_kind=selected_kind,
        parent_tree_oid=parent_tree,
        dependencies=dependencies,
        obligations=obligations,
        contracts=derived_contracts,
        validation=derived_validation,
        history=derived_history,
        reverse_dependencies=list(envelope.get("scope", {}).get("reverse_dependencies") or ())
        if isinstance(envelope.get("scope"), Mapping)
        else (),
        explicitly_excluded_paths=(
            list(preserved_prefix) if selected_kind == "affected_suffix" else []
        ),
        **passthrough,
    )

    payload = pack.canonical_payload()
    bound_parent = payload["parent"]["parent_context_pack_cid"]
    if bound_parent != parent_cid:
        raise UnboundParentError("parent binding does not match parent pack CID")
    if payload["identity"]["parent_context_pack_cid"] != parent_cid:
        raise UnboundParentError("identity parent binding does not match parent pack CID")
    if payload["delta"]["incremental"] is not True:
        raise _error("incremental packs require parent and delta identity")
    if payload["delta"]["named_missing"] != bound_missing:
        raise _error("delta.named_missing does not match named_missing")
    if parent_invalidated and TREE_CHANGE_TRIGGER not in payload["invalidation"][
        "invalidation_triggers"
    ]:
        raise StaleContextError("changed tree must invalidate the parent pack")

    triggers = tuple(payload["invalidation"]["invalidation_triggers"])
    return IncrementalExpansionResult(
        pack=pack,
        parent_pack_cid=parent_cid,
        delta_cid=str(payload["delta"]["delta_cid"]),
        pack_kind=selected_kind,
        parent_invalidated=parent_invalidated,
        invalidation_triggers=triggers,
        named_missing=tuple(bound_missing),
        retrieved=retrieved,
        relevant=relevant,
        affected_suffix=affected_suffix,
        preserved_prefix=preserved_prefix,
        relevant_retrieved=relevant_retrieved,
        retrieved_count=retrieved_count,
        relevant_count=relevant_count,
    )


def expand_named_missing(
    parent: ContextPackRecord | Mapping[str, Any],
    named_missing: Sequence[Any],
    catalog: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]],
    **kwargs: Any,
) -> IncrementalExpansionResult:
    """Resolve only the named missing references against the parent tree."""

    envelope = _parent_envelope(parent)
    tree = kwargs.pop("scanned_tree_oid", None) or parent_tree_oid_from_envelope(envelope)
    return expand_incremental_pack(
        parent=parent,
        scanned_tree_oid=tree,
        named_missing=named_missing,
        catalog=catalog,
        **kwargs,
    )
