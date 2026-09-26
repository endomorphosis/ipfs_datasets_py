"""Procedure slots taken from indexed law rows.

A procedure is the event chain the parser already stored. A law database
row supplies that chain only by content id. The statute text stays in the
blob store. A missing row abstains. Nothing here writes a CanonicalRule.
"""

from __future__ import annotations

from typing import Any, Sequence


def procedure_id(events: Sequence[str]) -> str:
    """Stable id for an event chain. ``notice`` then ``hearing`` is ``notice->hearing``."""

    cleaned = [" ".join(str(event).split()).lower() for event in events if str(event).strip()]
    return "->".join(cleaned)


def procedure_from_sentence(text: str) -> dict[str, Any]:
    """The procedure record the deontic parser already stored. Does not invent events."""

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

    observe_conversion_result("procedure_conversion", converted,
                              result_type=ConversionResult, status_type=ConversionStatus)
    elements = list(getattr(getattr(converted, "output", None), "parser_elements", ()) or [])
    for element in elements:
        if not isinstance(element, dict):
            continue
        record = element.get("procedure") or {}
        events = [str(event) for event in record.get("events") or [] if str(event).strip()]
        if events:
            return {
                "events": events,
                "procedure_id": procedure_id(events),
                "surface": " -> ".join(events),
                "admitted": False,
            }
    return {"events": [], "procedure_id": "", "surface": "", "admitted": False}


class ProcedureLawIndex:
    """Index law procedures by content id. The row does not contain the statute text."""

    def __init__(self, repository: Any = None) -> None:
        if repository is None:
            from ipfs_datasets_py.logic.proof_corpus.duckdb_repository import (
                ProofCorpusDuckDBRepository,
            )

            repository = ProofCorpusDuckDBRepository()
        self.repository = repository
        self._by_procedure: dict[str, dict[str, str]] = {}

    def put(
        self,
        *,
        citation: str,
        events: Sequence[str],
        frame: dict[str, Any],
        edge: dict[str, Any],
    ) -> dict[str, str]:
        chain = procedure_id(events)
        frame_record = self.repository.put_attestation(
            frame,
            subject_cid=f"procedure:{chain}",
            family="flogic",
            profile="procedure_frame",
        )
        edge_record = self.repository.put_attestation(
            edge,
            subject_cid=f"law:{citation}",
            family="graph",
            profile="procedure_edge",
        )
        row = {
            "citation": citation,
            "procedure_id": chain,
            "flogic_frame_cid": frame_record.content_cid,
            "graph_edge_cid": edge_record.content_cid,
        }
        self.repository.put_attestation(
            row,
            subject_cid=f"procedure-map:{chain}",
            family="procedure",
            profile="procedure_map",
        )
        self._by_procedure[chain] = row
        return dict(row)

    def get(self, chain: str) -> dict[str, str] | None:
        row = self._by_procedure.get(chain)
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


def slot_procedure(events: Sequence[str], index: ProcedureLawIndex) -> dict[str, Any]:
    """Attach a law procedure frame when the indexed chain matches. Otherwise abstain."""

    chain = procedure_id(events)
    if not chain:
        return {"result": "abstain", "reason": "no_procedure", "admitted": False}
    row = index.get(chain)
    if row is None or not index.cids_resolve(row):
        return {"result": "abstain", "reason": "unmapped", "procedure_id": chain, "admitted": False}
    return {
        "result": "yes",
        "reason": "",
        "procedure_id": chain,
        "citation": row["citation"],
        "frame_cid": row["flogic_frame_cid"],
        "admitted": False,
    }
