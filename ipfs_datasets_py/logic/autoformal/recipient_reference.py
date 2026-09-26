"""Recipient references and sort satisfaction.

A recipient points at a sort and, when the graph has a node, an instance.
Satisfaction reads that graph. It does not call the keyword entity classifier
and it does not write a CanonicalRule. DuckDB is not opened. Content ids are
indexed in the process-local proof-corpus index. Frame and edge bytes stay
in the blob store.
"""

from __future__ import annotations

import re
from typing import Any


_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)


def sort_id_from_surface(surface: str) -> str:
    """Lemma of a type phrase. ``a person`` is ``person``. ``an agency`` is ``agency``."""

    text = re.sub(r"[^A-Za-z0-9]+", " ", str(surface or "")).strip().lower()
    text = _ARTICLE.sub("", text).strip()
    parts = text.split()
    return parts[-1] if parts else ""


def recipient_surface_from_sentence(text: str) -> str:
    """Surface the deontic parser already stored. Does not invent a recipient."""

    from ipfs_datasets_py.logic.deontic import DeonticConverter

    converted = DeonticConverter(
        jurisdiction="us",
        document_type="statute",
        use_ml=False,
        use_cache=False,
        enable_monitoring=False,
    ).convert(text)
    from ipfs_datasets_py.logic.common.converters import ConversionResult, ConversionStatus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_ontology_observation import (
        observe_conversion_result,
    )

    observe_conversion_result("recipient_conversion", converted,
                              result_type=ConversionResult, status_type=ConversionStatus)
    elements = list(getattr(getattr(converted, "output", None), "parser_elements", ()) or [])
    for element in elements:
        if not isinstance(element, dict):
            continue
        surface = " ".join(str(element.get("action_recipient") or "").split())
        if surface:
            return surface
    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_action_recipient

    return " ".join(str(extract_action_recipient(text) or "").split())


def recipient_reference(surface: str, *, instance_id: str = "", frame_cid: str = "") -> dict[str, Any]:
    """A reference beside the norm. Not a CanonicalRule."""

    return {
        "surface": " ".join(str(surface or "").split()),
        "sort_id": sort_id_from_surface(surface),
        "instance_id": str(instance_id or ""),
        "frame_cid": str(frame_cid or ""),
        "admitted": False,
    }


class FixtureGraph:
    """One-hop type edges. Missing nodes are distinct from a node with other types."""

    def __init__(self, edges: list[tuple[str, str]] | None = None) -> None:
        self._types: dict[str, list[str]] = {}
        for instance, type_id in edges or []:
            key = str(instance).strip().lower()
            self._types.setdefault(key, [])
            if type_id not in self._types[key]:
                self._types[key].append(str(type_id))

    def resolve(self, surface: str) -> str:
        key = sort_id_from_surface(surface) if " " in str(surface or "") else str(surface or "").strip().lower()
        if " " in str(surface or "").strip():
            key = str(surface).strip().lower()
            key = _ARTICLE.sub("", key).strip()
        return key if key in self._types else ""

    def types_of(self, instance_id: str) -> list[str] | None:
        key = str(instance_id or "").strip().lower()
        if key not in self._types:
            return None
        return list(self._types[key])


class RecipientSortIndex:
    """Index of sort mappings by content id. The row does not contain edge bytes."""

    def __init__(self, repository: Any = None) -> None:
        if repository is None:
            from ipfs_datasets_py.logic.proof_corpus.duckdb_repository import (
                ProofCorpusDuckDBRepository,
            )

            repository = ProofCorpusDuckDBRepository()
        self.repository = repository
        self._by_sort: dict[str, dict[str, str]] = {}

    def put(
        self,
        *,
        sort_id: str,
        graph_type_id: str,
        frame: dict[str, Any],
        edge: dict[str, Any],
    ) -> dict[str, str]:
        frame_record = self.repository.put_attestation(
            frame,
            subject_cid=f"sort:{sort_id}",
            family="flogic",
            profile="frame",
        )
        edge_record = self.repository.put_attestation(
            edge,
            subject_cid=f"edge:{sort_id}",
            family="graph",
            profile="type",
        )
        row = {
            "sort_id": sort_id,
            "graph_type_id": graph_type_id,
            "flogic_frame_cid": frame_record.content_cid,
            "graph_edge_cid": edge_record.content_cid,
        }
        self.repository.put_attestation(
            row,
            subject_cid=f"map:{sort_id}",
            family="recipient",
            profile="sort_map",
        )
        self._by_sort[sort_id] = row
        return dict(row)

    def get(self, sort_id: str) -> dict[str, str] | None:
        row = self._by_sort.get(sort_id)
        return dict(row) if row else None

    def cids_resolve(self, row: dict[str, str]) -> bool:
        for key in ("flogic_frame_cid", "graph_edge_cid"):
            cid = str(row.get(key) or "")
            if not cid:
                return False
            try:
                body = self.repository.blob_store.get_bytes(cid)
            except Exception:
                return False
            if not body:
                return False
        return True


def satisfies(
    instance_id: str,
    sort_id: str,
    *,
    graph: FixtureGraph,
    index: RecipientSortIndex,
) -> dict[str, Any]:
    """Whether the graph says this instance has the sort. Keyword class is not consulted."""

    if not str(instance_id or "").strip() or not str(sort_id or "").strip():
        return {"result": "abstain", "reason": "unmapped", "admitted": False}
    row = index.get(sort_id)
    if row is None or not index.cids_resolve(row):
        return {"result": "abstain", "reason": "unmapped", "admitted": False}
    types = graph.types_of(instance_id)
    if types is None:
        return {"result": "abstain", "reason": "unmapped", "admitted": False}
    if row["graph_type_id"] in types:
        return {"result": "yes", "admitted": False}
    return {"result": "no", "admitted": False}
