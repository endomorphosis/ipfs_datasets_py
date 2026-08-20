"""Storage-neutral semantic-state public API (DSS-009).

This module is the sole owner of the closed producer surface:

* :func:`build_semantic_state` — cold or verified-incremental assembly
* :func:`verify_semantic_state_bundle` — full reverify of a finite bundle
* :func:`open_semantic_state` — injected-block-reader verified view
* re-exports of capsule / freshness / source / invalidation / selection / oracle

``SemanticStateView.get_block`` is read-only and storage-neutral.  No put, CAS,
WAL, provider, network, kit, scheduler, context-pack, receipt, or MCP++ envelope
hasher is used here.  Assembly has no persistence side effect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    Protocol,
    Sequence,
    runtime_checkable,
)

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    ArtifactRecord,
    DependencyEdge,
    RepositoryState,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.bindings import (
    build_environment_binding_set,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.capsules import (
    SemanticIndexForCapsules,
    compile_semantic_capsule,
    compile_semantic_capsules,
    verify_capsule_compile_result,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.freshness import (
    assess_capsule_freshness,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.invalidation import (
    extend_semantic_invalidation,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.merkle import (
    build_symbol_merkle_dag,
    verify_symbol_merkle_dag,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    AnalysisLimitation,
    EnvironmentBinding,
    EnvironmentBindingSet,
    SemanticCapsule,
    SemanticStateBundle,
    SemanticStateModelError,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
    SymbolMerkleNode,
    verify_block_bytes,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.oracle import (
    compare_test_selection_oracle,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.source import (
    read_required_source,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.test_selection import (
    select_tests_and_proofs,
)

# ---------------------------------------------------------------------------
# Interface constants
# ---------------------------------------------------------------------------

SEMANTIC_STATE_PRODUCER_INTERFACE: Final[str] = "SemanticStateProducer@1"
SEMANTIC_STATE_VIEW_INTERFACE: Final[str] = "SemanticStateView@1"
SEMANTIC_STATE_BLOCK_READER_INTERFACE: Final[str] = "SemanticStateBlockReader@1"
SEMANTIC_STATE_API_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-state-api@1"
)

_SNAPSHOT_EVIDENCE_IDS: Final[frozenset[str]] = frozenset(
    {
        "artifact:snapshot-evidence",
        "snapshot-evidence",
    }
)
_SNAPSHOT_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "snapshot-evidence",
        "snapshot",
    }
)


# ---------------------------------------------------------------------------
# Typed failures
# ---------------------------------------------------------------------------


class SemanticStateApiError(SemanticStateModelError):
    """Base typed failure for the storage-neutral semantic-state API."""


class MissingBlockError(SemanticStateApiError):
    """Raised when a required block CID is absent from the reader or bundle."""


class CorruptBlockError(SemanticStateApiError):
    """Raised when block bytes fail CID rehash, schema, or canonical checks."""


class UnknownSymbolError(SemanticStateApiError):
    """Raised when a stable symbol id is not present in a verified index."""


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class SemanticStateBlockReader(Protocol):
    """Read-only block source.  Implementations must not mutate storage."""

    def get_block(self, cid: str) -> bytes: ...


@runtime_checkable
class SemanticStateView(Protocol):
    """Verified read-only view over a semantic-state root and its blocks."""

    @property
    def root(self) -> SemanticStateRoot: ...

    def get_block(self, cid: str) -> bytes: ...

    def symbol_node(self, stable_symbol_id: str) -> SymbolMerkleNode: ...

    def capsule(self, stable_symbol_id: str) -> SemanticCapsule: ...


# ---------------------------------------------------------------------------
# Block helpers
# ---------------------------------------------------------------------------


def _normalize_cid(value: object, name: str = "cid") -> str:
    if type(value) is not str or not value:
        raise SemanticStateApiError(f"{name} must be a nonempty CID string")
    try:
        return validate_cid(value)
    except Exception as exc:
        raise SemanticStateApiError(f"{name} must be a valid CID") from exc


def _fetch_raw_block(
    get_block: Callable[[str], bytes],
    cid: str,
) -> bytes:
    """Fetch one block without reverify (caller verifies)."""
    key = _normalize_cid(cid)
    try:
        data = get_block(key)
    except MissingBlockError:
        raise
    except SemanticStateApiError:
        raise
    except KeyError as exc:
        raise MissingBlockError(f"missing block {key}") from exc
    except Exception as exc:
        # Map generic lookup failures to typed missing; corrupt is separate.
        message = str(exc).lower()
        if "missing" in message or "not found" in message or "unknown" in message:
            raise MissingBlockError(f"missing block {key}") from exc
        raise MissingBlockError(f"missing block {key}") from exc
    if type(data) is not bytes:
        raise CorruptBlockError(f"block {key} did not return bytes")
    return data


def _read_verified_block(
    get_block: Callable[[str], bytes],
    cid: str,
) -> bytes:
    """Fetch and reverify one block against its claimed CID."""
    key = _normalize_cid(cid)
    data = _fetch_raw_block(get_block, key)
    try:
        verify_block_bytes(key, data)
    except SemanticStateModelError as exc:
        raise CorruptBlockError(f"corrupt block {key}: {exc}") from exc
    except Exception as exc:
        raise CorruptBlockError(f"corrupt block {key}") from exc
    return data


_CLAIM_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "root_cid",
        "index_cid",
        "capsule_cid",
        "node_cid",
        "fact_cid",
        "link_cid",
        "limitation_cid",
        "binding_set_cid",
        "projection_cid",
        "plan_cid",
        "selection_cid",
        "comparison_cid",
        "delta_cid",
        "assessment_cid",
        "evidence_cid",
    }
)


def _load_structured_identity(
    get_block: Callable[[str], bytes],
    cid: str,
) -> dict[str, Any]:
    """Load a dag-json identity payload, requiring exact CID reverify."""
    data = _read_verified_block(get_block, cid)
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise CorruptBlockError(f"block {cid} is not UTF-8 JSON") from exc
    if type(payload) is not dict:
        raise CorruptBlockError(f"block {cid} must be a JSON object")

    # Preferred form: pure identity_payload (canonical, claim-free).
    try:
        if canonical_dag_json_bytes(payload) == data and cid_for_structured(payload) == cid:
            return payload
    except Exception:
        pass

    # Accept claim-bearing to_dict form when the claim-free projection matches.
    identity = {key: value for key, value in payload.items() if key not in _CLAIM_FIELDS}
    try:
        recomputed = cid_for_structured(identity)
    except Exception as exc:
        raise CorruptBlockError(f"block {cid} failed structured reverify") from exc
    if recomputed != cid:
        raise CorruptBlockError(
            f"block CID {cid} does not reverify (got {recomputed})"
        )
    return identity


def _load_sorted_pair_index(
    get_block: Callable[[str], bytes],
    index_cid: str,
) -> SortedPairIndex:
    identity = _load_structured_identity(get_block, index_cid)
    try:
        return SortedPairIndex.from_dict({**identity, "index_cid": index_cid})
    except SemanticStateModelError as exc:
        raise CorruptBlockError(
            f"sorted pair index {index_cid} failed schema reverify"
        ) from exc


def _lookup_index(
    index: SortedPairIndex,
    logical_key: str,
) -> str | None:
    for key, value in index.pairs:
        if key == logical_key:
            return value
    return None


def _record_structured_block(
    blocks: dict[str, bytes],
    identity_payload: Mapping[str, Any],
    claimed_cid: str,
) -> None:
    data = canonical_dag_json_bytes(identity_payload)
    recomputed = cid_for_structured(identity_payload)
    if recomputed != claimed_cid:
        raise SemanticStateApiError(
            f"claimed CID {claimed_cid} does not match recomputed {recomputed}"
        )
    existing = blocks.get(claimed_cid)
    if existing is not None and existing != data:
        raise SemanticStateApiError(
            f"conflicting block bytes for CID {claimed_cid}"
        )
    blocks[claimed_cid] = data


def _merge_blocks(*maps: Mapping[str, bytes]) -> dict[str, bytes]:
    merged: dict[str, bytes] = {}
    for mapping in maps:
        for key, data in mapping.items():
            cid = _normalize_cid(key, "block_cid")
            if type(data) is not bytes:
                raise SemanticStateApiError(f"block {cid} data must be bytes")
            if cid in merged and merged[cid] != data:
                raise SemanticStateApiError(f"conflicting block bytes for CID {cid}")
            merged[cid] = data
    return merged


def _prefer_previous_bytes(
    blocks: Mapping[str, bytes],
    previous: Mapping[str, bytes] | None,
) -> dict[str, bytes]:
    """Keep cold-path bytes; prefer previous only when byte-identical."""
    if not previous:
        return dict(blocks)
    result: dict[str, bytes] = {}
    for cid, data in blocks.items():
        prior = previous.get(cid)
        result[cid] = prior if prior == data else data
    return result


# ---------------------------------------------------------------------------
# Producer / index resolution
# ---------------------------------------------------------------------------


def _as_repository_state(
    semantic_index: object,
    name: str = "semantic_index",
) -> RepositoryState:
    if isinstance(semantic_index, RepositoryState):
        return semantic_index
    try:
        return RepositoryState(
            repository_id=semantic_index.repository_id,  # type: ignore[attr-defined]
            symbols=tuple(semantic_index.symbols),  # type: ignore[attr-defined]
            artifacts=tuple(getattr(semantic_index, "artifacts", ()) or ()),
            edges=tuple(semantic_index.edges),  # type: ignore[attr-defined]
            extractor_name=str(
                getattr(semantic_index, "extractor_name", "semantic-index")
            ),
            extractor_version=str(
                getattr(semantic_index, "extractor_version", "1")
            ),
            schema=str(
                getattr(
                    semantic_index,
                    "schema",
                    getattr(
                        semantic_index,
                        "semantic_index_schema",
                        "ipfs-datasets.software-contracts.semantic-index@2",
                    ),
                )
            ),
        )
    except SemanticStateApiError:
        raise
    except Exception as exc:
        raise SemanticStateApiError(
            f"{name} must be a RepositoryState or SemanticIndexForCapsules"
        ) from exc


def _optional_text_attr(index: object, *names: str) -> str | None:
    for name in names:
        value = getattr(index, name, None)
        if value is None:
            continue
        if type(value) is not str:
            raise SemanticStateApiError(f"{name} must be a string or None")
        if value:
            return value
    return None


def _optional_cid_attr(index: object, *names: str) -> str | None:
    text = _optional_text_attr(index, *names)
    if text is None:
        return None
    return _normalize_cid(text, names[0] if names else "cid")


def _snapshot_evidence(
    state: RepositoryState,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (snapshot_cid, git_commit, git_tree, source_manifest_cid)."""
    for artifact in state.artifacts:
        if not isinstance(artifact, ArtifactRecord):
            continue
        if (
            artifact.artifact_id not in _SNAPSHOT_EVIDENCE_IDS
            and str(artifact.kind) not in _SNAPSHOT_EVIDENCE_KINDS
        ):
            continue
        meta = dict(artifact.metadata or {})
        snap = meta.get("snapshot")
        snapshot_cid: str | None = None
        git_commit: str | None = None
        git_tree: str | None = None
        if isinstance(snap, Mapping):
            raw_cid = snap.get("snapshot_cid")
            if type(raw_cid) is str and raw_cid:
                snapshot_cid = raw_cid
            commit = snap.get("git_commit")
            tree = snap.get("git_tree")
            if type(commit) is str and commit:
                git_commit = commit
            if type(tree) is str and tree:
                git_tree = tree
        if snapshot_cid is None and artifact.source_cid:
            snapshot_cid = artifact.source_cid
        manifest = meta.get("source_manifest_cid") or meta.get("manifest_cid")
        source_manifest_cid = (
            manifest if type(manifest) is str and manifest else None
        )
        return snapshot_cid, git_commit, git_tree, source_manifest_cid
    return None, None, None, None


def _resolve_producer(
    semantic_index: object,
    state: RepositoryState,
) -> SemanticStateProducer:
    """Copy producer identity from the sealed ISI view (never ambient FS)."""
    explicit = getattr(semantic_index, "producer", None)
    if isinstance(explicit, SemanticStateProducer):
        if explicit.repository_state_cid != state.state_cid:
            raise SemanticStateApiError(
                "producer.repository_state_cid must equal semantic_index state_cid"
            )
        return explicit

    snap_cid, git_commit, git_tree, manifest_cid = _snapshot_evidence(state)

    repository_state_cid = (
        _optional_cid_attr(semantic_index, "repository_state_cid", "state_cid")
        or state.state_cid
    )
    if repository_state_cid != state.state_cid:
        raise SemanticStateApiError(
            "repository_state_cid must equal the sealed ISI state_cid"
        )

    repository_snapshot_cid = (
        _optional_cid_attr(
            semantic_index, "repository_snapshot_cid", "snapshot_cid"
        )
        or ( _normalize_cid(snap_cid, "repository_snapshot_cid") if snap_cid else None)
    )
    source_manifest_cid = (
        _optional_cid_attr(semantic_index, "source_manifest_cid", "manifest_cid")
        or (
            _normalize_cid(manifest_cid, "source_manifest_cid")
            if manifest_cid
            else None
        )
    )

    # When the sealed ISI view carries no separate snapshot/manifest authority
    # (common for pure in-memory RepositoryState tests), bind those CIDs to the
    # state content identity so the root remains a pure function of sealed input.
    if repository_snapshot_cid is None:
        repository_snapshot_cid = state.state_cid
    if source_manifest_cid is None:
        source_manifest_cid = state.state_cid

    git_commit_oid = _optional_text_attr(
        semantic_index, "git_commit_oid_or_null", "git_commit"
    )
    if git_commit_oid is None:
        git_commit_oid = git_commit
    git_tree_oid = _optional_text_attr(
        semantic_index, "git_tree_oid_or_null", "git_tree"
    )
    if git_tree_oid is None:
        git_tree_oid = git_tree

    schema = (
        _optional_text_attr(
            semantic_index, "semantic_index_schema", "schema"
        )
        or state.schema
    )
    extractor_name = (
        _optional_text_attr(semantic_index, "extractor_name")
        or state.extractor_name
    )
    extractor_version = (
        _optional_text_attr(semantic_index, "extractor_version")
        or state.extractor_version
    )

    try:
        return SemanticStateProducer(
            repository_state_cid=repository_state_cid,
            repository_snapshot_cid=repository_snapshot_cid,
            git_commit_oid_or_null=git_commit_oid,
            git_tree_oid_or_null=git_tree_oid,
            source_manifest_cid=source_manifest_cid,
            semantic_index_schema=schema,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
        )
    except SemanticStateModelError as exc:
        raise SemanticStateApiError(
            f"producer identity failed validation: {exc}"
        ) from exc


def _resolve_limitations(semantic_index: object) -> tuple[AnalysisLimitation, ...]:
    raw = getattr(semantic_index, "limitations", None)
    if raw is None:
        raw = getattr(semantic_index, "analysis_limitations", None)
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise SemanticStateApiError(
            "limitations must be a sequence of AnalysisLimitation values"
        )
    items: list[AnalysisLimitation] = []
    for item in raw:
        if not isinstance(item, AnalysisLimitation):
            raise SemanticStateApiError(
                "limitations must be AnalysisLimitation values"
            )
        items.append(item)
    # Deterministic order by limitation CID.
    return tuple(sorted(items, key=lambda item: item.limitation_cid))


def _as_environment_bindings(
    environment_bindings: Sequence[object],
) -> Sequence[EnvironmentBinding]:
    if not isinstance(environment_bindings, Sequence) or isinstance(
        environment_bindings, (str, bytes)
    ):
        raise SemanticStateApiError(
            "environment_bindings must be a sequence of EnvironmentBinding values"
        )
    result: list[EnvironmentBinding] = []
    for item in environment_bindings:
        if not isinstance(item, EnvironmentBinding):
            raise SemanticStateApiError(
                "environment_bindings must be EnvironmentBinding values"
            )
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Verified view
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerifiedSemanticStateView:
    """In-memory or injected-reader view that reverifies every block read."""

    _root: SemanticStateRoot
    _get_block: Callable[[str], bytes]

    @property
    def root(self) -> SemanticStateRoot:
        return self._root

    def get_block(self, cid: str) -> bytes:
        return _read_verified_block(self._get_block, cid)

    def symbol_node(self, stable_symbol_id: str) -> SymbolMerkleNode:
        if type(stable_symbol_id) is not str or not stable_symbol_id:
            raise SemanticStateApiError("stable_symbol_id must be a nonempty string")
        index = _load_sorted_pair_index(
            self._get_block, self._root.symbol_node_index_cid
        )
        node_cid = _lookup_index(index, stable_symbol_id)
        if node_cid is None:
            raise UnknownSymbolError(
                f"unknown stable_symbol_id {stable_symbol_id!r} in symbol node index"
            )
        identity = _load_structured_identity(self._get_block, node_cid)
        try:
            node = SymbolMerkleNode.from_dict({**identity, "node_cid": node_cid})
        except SemanticStateModelError as exc:
            raise CorruptBlockError(
                f"symbol node {node_cid} failed schema reverify"
            ) from exc
        if node.stable_symbol_id != stable_symbol_id:
            raise CorruptBlockError(
                f"symbol node {node_cid} stable_symbol_id mismatch"
            )
        return node

    def capsule(self, stable_symbol_id: str) -> SemanticCapsule:
        if type(stable_symbol_id) is not str or not stable_symbol_id:
            raise SemanticStateApiError("stable_symbol_id must be a nonempty string")
        index = _load_sorted_pair_index(
            self._get_block, self._root.capsule_index_cid
        )
        capsule_cid = _lookup_index(index, stable_symbol_id)
        if capsule_cid is None:
            raise UnknownSymbolError(
                f"unknown stable_symbol_id {stable_symbol_id!r} in capsule index"
            )
        identity = _load_structured_identity(self._get_block, capsule_cid)
        try:
            capsule = SemanticCapsule.from_dict(
                {**identity, "capsule_cid": capsule_cid}
            )
        except SemanticStateModelError as exc:
            raise CorruptBlockError(
                f"capsule {capsule_cid} failed schema reverify"
            ) from exc
        if capsule.stable_symbol_id != stable_symbol_id:
            raise CorruptBlockError(
                f"capsule {capsule_cid} stable_symbol_id mismatch"
            )
        return capsule

    @classmethod
    def from_bundle(cls, bundle: SemanticStateBundle) -> "VerifiedSemanticStateView":
        if not isinstance(bundle, SemanticStateBundle):
            raise SemanticStateApiError("bundle must be a SemanticStateBundle")
        bundle.verify()
        return cls(_root=bundle.root, _get_block=bundle.get_block)


def view_semantic_state_bundle(
    bundle: SemanticStateBundle,
) -> VerifiedSemanticStateView:
    """Return a verified in-memory view over a finite bundle (no storage I/O)."""
    return VerifiedSemanticStateView.from_bundle(bundle)


# ---------------------------------------------------------------------------
# Public assembly / verify / open
# ---------------------------------------------------------------------------


def build_semantic_state(
    semantic_index: RepositoryState | SemanticIndexForCapsules | object,
    *,
    environment_bindings: Sequence[EnvironmentBinding] = (),
    previous_bundle: SemanticStateBundle | None = None,
) -> SemanticStateBundle:
    """Assemble a verified finite semantic-state bundle from a sealed ISI view.

    Parameters
    ----------
    semantic_index:
        Sealed final-ISI ``RepositoryState`` or duck-typed index exposing
        repository identity, symbols, artifacts, and edges.  Optional sealed
        producer fields (snapshot/manifest/git OIDs) are copied when present.
    environment_bindings:
        Explicit environment bindings.  ISI artifacts that match closed
        binding kinds are also admitted through the bindings module.
    previous_bundle:
        Optional previously verified bundle.  Capsule/index blocks are reused
        only after current inputs reverify to the same content-addressed CID
        and stored bytes are byte-identical.  Reuse has no persistence side
        effect and does not alter the cold-path root for identical inputs.

    Returns
    -------
    SemanticStateBundle
        Verified root plus finite CID→bytes map.  Cold and verified-incremental
        assembly over identical inputs yield byte-identical reachable blocks
        and the same root CID.
    """
    if previous_bundle is not None:
        if not isinstance(previous_bundle, SemanticStateBundle):
            raise SemanticStateApiError(
                "previous_bundle must be a SemanticStateBundle or None"
            )
        # Reverify previous in memory; never write or publish.
        previous_bundle.verify()

    state = _as_repository_state(semantic_index)
    producer = _resolve_producer(semantic_index, state)
    bindings = _as_environment_bindings(environment_bindings)
    binding_set = build_environment_binding_set(
        bindings, repository_state=state
    )

    capsule_result = compile_semantic_capsules(
        state,
        binding_set=binding_set,
        previous_bundle=previous_bundle,
    )
    verify_capsule_compile_result(capsule_result)

    dag = build_symbol_merkle_dag(
        repository_state=state,
        capsule_index=capsule_result.index,
    )
    verify_symbol_merkle_dag(dag)

    limitations = _resolve_limitations(semantic_index)
    limitation_pairs = [
        (item.limitation_cid, item.limitation_cid) for item in limitations
    ]
    limitation_index = SortedPairIndex(pairs=limitation_pairs)

    blocks = _merge_blocks(dag.blocks, capsule_result.blocks)
    _record_structured_block(
        blocks, binding_set.identity_payload(), binding_set.binding_set_cid
    )
    for item in limitations:
        _record_structured_block(
            blocks, item.identity_payload(), item.limitation_cid
        )
    _record_structured_block(
        blocks, limitation_index.identity_payload(), limitation_index.index_cid
    )

    root = SemanticStateRoot(
        repository_id=state.repository_id,
        producer=producer,
        symbol_fact_index_cid=dag.symbol_fact_index_cid,
        artifact_fact_index_cid=dag.artifact_fact_index_cid,
        semantic_link_index_cid=dag.semantic_link_index_cid,
        symbol_node_index_cid=dag.symbol_node_index_cid,
        capsule_index_cid=capsule_result.index.index_cid,
        environment_binding_set_cid=binding_set.binding_set_cid,
        analysis_limitation_index_cid=limitation_index.index_cid,
    )

    previous_blocks: Mapping[str, bytes] | None = None
    if previous_bundle is not None:
        previous_blocks = previous_bundle.blocks
    blocks = _prefer_previous_bytes(blocks, previous_blocks)

    return SemanticStateBundle(root=root, blocks=MappingProxyType(blocks))


def verify_semantic_state_bundle(
    bundle: SemanticStateBundle,
) -> SemanticStateRoot:
    """Reverify every bundle block and every root-referenced index/schema.

    Returns the verified :class:`SemanticStateRoot` on success.  Missing or
    corrupt root-reachable blocks fail typed.
    """
    if not isinstance(bundle, SemanticStateBundle):
        raise SemanticStateApiError("bundle must be a SemanticStateBundle")

    root = bundle.verify()

    # Every root-referenced durable index must be present and schema-valid.
    for index_cid in (
        root.symbol_fact_index_cid,
        root.artifact_fact_index_cid,
        root.semantic_link_index_cid,
        root.symbol_node_index_cid,
        root.capsule_index_cid,
        root.analysis_limitation_index_cid,
    ):
        _load_sorted_pair_index(bundle.get_block, index_cid)

    try:
        binding_identity = _load_structured_identity(
            bundle.get_block, root.environment_binding_set_cid
        )
        EnvironmentBindingSet.from_dict(
            {
                **binding_identity,
                "binding_set_cid": root.environment_binding_set_cid,
            }
        )
    except SemanticStateApiError:
        raise
    except SemanticStateModelError as exc:
        raise CorruptBlockError(
            f"environment binding set {root.environment_binding_set_cid} "
            f"failed schema reverify"
        ) from exc

    return root


def open_semantic_state(
    root_cid: str,
    get_block: Callable[[str], bytes],
) -> VerifiedSemanticStateView:
    """Open a verified view over an injected block reader.

    Every subsequent :meth:`VerifiedSemanticStateView.get_block` call reverifies
    CID and schema.  Missing and corrupt blocks fail typed.  The reader is
    never used for put, CAS, WAL, provider, or network operations.
    """
    if not callable(get_block):
        raise SemanticStateApiError("get_block must be callable")
    key = _normalize_cid(root_cid, "root_cid")
    identity = _load_structured_identity(get_block, key)
    try:
        root = SemanticStateRoot.from_dict({**identity, "root_cid": key})
    except SemanticStateModelError as exc:
        raise CorruptBlockError(
            f"root {key} failed schema reverify"
        ) from exc
    if root.root_cid != key:
        raise CorruptBlockError(
            f"root CID {key} does not match recomputed {root.root_cid}"
        )
    return VerifiedSemanticStateView(_root=root, _get_block=get_block)


# ---------------------------------------------------------------------------
# Public re-exports (exactly closed surface)
# ---------------------------------------------------------------------------


__all__ = [
    # Interfaces / constants
    "SEMANTIC_STATE_API_SCHEMA",
    "SEMANTIC_STATE_BLOCK_READER_INTERFACE",
    "SEMANTIC_STATE_PRODUCER_INTERFACE",
    "SEMANTIC_STATE_VIEW_INTERFACE",
    # Protocols / view
    "SemanticStateBlockReader",
    "SemanticStateView",
    "VerifiedSemanticStateView",
    # Errors
    "SemanticStateApiError",
    "MissingBlockError",
    "CorruptBlockError",
    "UnknownSymbolError",
    # Core assembly
    "build_semantic_state",
    "verify_semantic_state_bundle",
    "open_semantic_state",
    "view_semantic_state_bundle",
    # Capsule / freshness / source
    "compile_semantic_capsule",
    "assess_capsule_freshness",
    "read_required_source",
    # Invalidation / selection / oracle
    "extend_semantic_invalidation",
    "select_tests_and_proofs",
    "compare_test_selection_oracle",
]
