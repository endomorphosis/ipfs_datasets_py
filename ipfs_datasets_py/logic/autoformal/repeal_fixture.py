"""F-logic and knowledge-graph fixture for a repeal.

The Twenty-First Amendment says the eighteenth article of amendment is
repealed. That is not a deontic shall. The fixture records the repealing
instrument and the repealed target by content id. It does not admit the span.
"""

from __future__ import annotations

from typing import Any

from ipfs_datasets_py.logic.autoformal.constitution_inventory import (
    _REPEAL,
    _amendment_number,
)


def project_repeal_sentence(text: str, *, instrument_id: str) -> dict[str, Any]:
    """Keep the performative sentence. The O/P/F compiler does not accept it.

    The F-logic frame is stored when the caller names the repealing instrument.
    Neither the sentence nor the frame is an admit.
    """

    parsed = repeal_from_sentence(text, instrument_id=instrument_id)
    surface = " ".join(str(parsed.get("surface") or "").split())
    target = str(parsed.get("target_id") or "")
    if not surface or not target:
        return {
            "decompiled": "",
            "instrument_id": str(instrument_id or ""),
            "target_id": "",
            "admitted": False,
        }
    if surface[0].islower():
        surface = surface[0].upper() + surface[1:]
    if not surface.endswith("."):
        surface += "."
    stored = ""
    if instrument_id and instrument_id not in {"agreement", "surface", "check"}:
        try:
            stored_row = RepealFixture().put(instrument_id=instrument_id, text=text)
            stored = str(stored_row.get("result") or "")
        except (ImportError, OSError, TypeError, ValueError):
            stored = "abstain"
    return {
        "decompiled": surface,
        "instrument_id": str(instrument_id or ""),
        "target_id": target,
        "stored": stored,
        "admitted": False,
    }


def repeal_from_sentence(text: str, *, instrument_id: str) -> dict[str, Any]:
    """Read a repeal the inventory regex already recognizes. Do not guess a target."""

    match = _REPEAL.search(str(text or ""))
    if not match:
        return {
            "instrument_id": str(instrument_id or ""),
            "target_id": "",
            "surface": "",
            "admitted": False,
        }
    number = _amendment_number(match.group("which"))
    target = f"amend-{number}" if number else ""
    return {
        "instrument_id": str(instrument_id or ""),
        "target_id": target,
        "surface": " ".join(match.group(0).split()),
        "admitted": False,
    }


class RepealFixture:
    """Index one repeal edge. Frame and edge bytes stay in the blob store."""

    def __init__(self, repository: Any = None) -> None:
        if repository is None:
            from ipfs_datasets_py.logic.proof_corpus.duckdb_repository import (
                ProofCorpusDuckDBRepository,
            )

            repository = ProofCorpusDuckDBRepository()
        self.repository = repository
        self._by_instrument: dict[str, dict[str, str]] = {}

    def put(self, *, instrument_id: str, text: str) -> dict[str, Any]:
        parsed = repeal_from_sentence(text, instrument_id=instrument_id)
        target = str(parsed["target_id"] or "")
        if not instrument_id or not target:
            return {"result": "abstain", "reason": "no_repeal", "admitted": False}
        frame = {
            "instrument_id": instrument_id,
            "isa": "repeal",
            "repeals": target,
        }
        edge = {"subject": instrument_id, "predicate": "repeals", "object": target}
        frame_record = self.repository.put_attestation(
            frame,
            subject_cid=f"repeal-frame:{instrument_id}",
            family="flogic",
            profile="repeal_frame",
        )
        edge_record = self.repository.put_attestation(
            edge,
            subject_cid=f"repeal-edge:{instrument_id}",
            family="graph",
            profile="repeal_edge",
        )
        row = {
            "instrument_id": instrument_id,
            "target_id": target,
            "flogic_frame_cid": frame_record.content_cid,
            "graph_edge_cid": edge_record.content_cid,
        }
        self.repository.put_attestation(
            row,
            subject_cid=f"repeal-map:{instrument_id}",
            family="repeal",
            profile="repeal_map",
        )
        self._by_instrument[instrument_id] = row
        return {"result": "yes", "admitted": False, **row}

    def slot(self, text: str, *, instrument_id: str) -> dict[str, Any]:
        parsed = repeal_from_sentence(text, instrument_id=instrument_id)
        target = str(parsed["target_id"] or "")
        if not target:
            return {"result": "abstain", "reason": "no_repeal", "admitted": False}
        row = self._by_instrument.get(instrument_id)
        if row is None or not self._cids_resolve(row):
            return {
                "result": "abstain",
                "reason": "unmapped",
                "target_id": target,
                "admitted": False,
            }
        if row["target_id"] != target:
            return {
                "result": "no",
                "reason": "target_mismatch",
                "target_id": target,
                "admitted": False,
            }
        return {
            "result": "yes",
            "reason": "",
            "instrument_id": instrument_id,
            "target_id": target,
            "frame_cid": row["flogic_frame_cid"],
            "edge_cid": row["graph_edge_cid"],
            "admitted": False,
        }

    def triples(self, instrument_id: str) -> list[dict[str, str]]:
        """Subject/predicate/object triples for the stored repeal. Empty if unmapped."""

        row = self._by_instrument.get(instrument_id)
        if row is None:
            return []
        return [
            {"subject": instrument_id, "predicate": "type", "object": "repeal"},
            {"subject": instrument_id, "predicate": "repeals", "object": row["target_id"]},
        ]

    def flogic(self, instrument_id: str) -> Any:
        """F-logic frame. ``type`` becomes ``isa``. ``repeals`` is a method."""

        from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_ontology

        return flogic_triples_to_ontology(
            self.triples(instrument_id),
            name=f"{instrument_id}_repeal",
        )

    def knowledge_graph(self, instrument_id: str) -> Any:
        """One-hop graph. No dense statute projection is added."""

        from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

        return flogic_triples_to_graph_data(
            self.triples(instrument_id),
            augment_sparse_legal_projection=False,
            graph_id=f"{instrument_id}:repeal",
        )

    def _cids_resolve(self, row: dict[str, str]) -> bool:
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
