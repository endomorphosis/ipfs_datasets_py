"""Authored native legal stage records without supervisor or provider imports."""

from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport, LegalIRDocument, LogicIRView, RoundTripMetrics,
)


def multiview_document():
    """Build native payloads; no backend execution or proof is asserted."""
    source = "Agency must not disclose the record after confidential notice."
    source_id = "prov:bridge-1"
    payloads = {
        "deontic_norms": {
            "deontic_ir": {"norms": [{
                "action": "disclose", "action_object": "record", "actor": "agency",
                "conditions": ["after confidential notice"],
                "exceptions": ["unless a court authorizes it"],
                "norm_type": "prohibition", "source_id": source_id,
            }]},
            "deontic_formula_records": {"records": [{
                "formula_id": "formula-bridge-1", "source_id": source_id,
            }]},
            "deontic_decoder_reconstructions": {"records": [{
                "reconstruction_id": "decoder-1", "semantic_family": "deontic",
                "source_id": source_id,
            }]},
            "frame_logic": {"triples": [{
                "object": "record", "predicate": "prohibits", "subject": source_id,
            }]},
            "neo4j_graph_data": {
                "metadata": {"graph_id": "graph-bridge-1"},
                "nodes": [{"id": "agency", "type": "Actor"},
                          {"id": "record", "type": "LegalObject"}],
                "relationships": [{"source": "agency", "target": "record",
                                   "type": "PROHIBITS"}],
            },
        },
        "fol_tdfol": {
            "tdfol_formula": {"records": [{
                "formula": "forall x. notice(x)", "quantifiers": ["forall"],
                "source_id": source_id,
            }]},
        },
        "cec_dcec": {
            "cec_events": {"events": [{
                "event_id": "event:notice", "event_role": "notice", "source_id": source_id,
            }]},
            "event_calculus": {"records": [{
                "event_formula_fingerprint": "fluent:notice", "selected_frame": "notice_state",
                "source_id": source_id,
            }]},
        },
        "external_prover_router": {
            "prover_formulas": {"records": [{"source_id": source_id}]},
        },
    }
    reports = {}
    for name, stage in payloads.items():
        views = {key: LogicIRView(name=key, payload=value, source_component=name)
                 for key, value in stage.items()}
        document = LegalIRDocument("native:" + name, source, source, views=views)
        reports[name] = BridgeEvaluationReport(name, name, document, RoundTripMetrics(), status="partial")
    return MultiViewLegalIRReport(tuple(reports), LegalIRDocument("merged", source, source), reports=reports)
