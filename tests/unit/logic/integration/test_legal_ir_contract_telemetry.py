"""Contract telemetry stays deterministic, structural, and source-free."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION,
    attach_legal_ir_contract_telemetry,
    collect_legal_ir_contract_telemetry,
    legal_ir_contract_payloads_from_multiview_report,
    summarize_legal_ir_contract_telemetry,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    update_daemon_hammer_guidance_summary,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    uscode_modal_daemon_runner as daemon_runner,
)


DEONTIC_CONTRACT = "legal-ir-view/deontic/v1"


def _views() -> dict[str, dict[str, object]]:
    provenance = ["prov:sha256:111"]
    return {
        "deontic": {
            "formula_id": "formula-1",
            "operator": "F",
            "norm_type": "prohibition",
            "polarity": "negative",
            "actor": "agency",
            "action": "disclose",
            "object": "record",
            "conditions": [],
            "exceptions": ["exception-1"],
            "provenance_ids": provenance,
        },
        "frame_logic": {
            "formula_id": "formula-1",
            "frame_id": "frame-1",
            "subject": "agency",
            "predicate": "must_not_disclose",
            "object": "record",
            "role": "prohibition",
            "provenance_ids": provenance,
        },
        "tdfol": {
            "formula_id": "formula-1",
            "expression": {"operator": "before", "arguments": ["notice", "disclose"]},
            "quantifiers": [],
            "temporal_anchors": ["event:notice"],
            "provenance_ids": provenance,
        },
        "cec": {
            "formula_id": "formula-1",
            "events": [{"id": "event:notice", "type": "notice"}],
            "fluents": [{"id": "fluent:eligible", "type": "eligibility"}],
            "lifecycle_transitions": [
                {
                    "event_id": "event:notice",
                    "fluent_id": "fluent:eligible",
                    "effect": "initiates",
                }
            ],
            "provenance_ids": provenance,
        },
        "knowledge_graphs": {
            "graph_id": "graph-1",
            "nodes": [
                {"id": "agency", "type": "Actor"},
                {"id": "record", "type": "LegalObject"},
            ],
            "relationships": [
                {"source": "agency", "target": "record", "type": "MUST_NOT_DISCLOSE"}
            ],
            "provenance_ids": provenance,
        },
        "external_provers": {
            "obligation_id": "obligation-1",
            "input_formula_id": "formula-1",
            "backend_route": ["z3"],
            "backend_status": {"z3": "proved"},
            "reconstruction_status": "verified",
            "provenance_ids": provenance,
        },
        "decompiler": {
            "formula_id": "formula-1",
            "source_contract_id": DEONTIC_CONTRACT,
            "reconstructed_structure": {"norm_type": "prohibition"},
            "operator": "F",
            "predicate": {"name": "disclose", "arity": 2},
            "arguments": ["agency", "record"],
            "conditions": [],
            "exceptions": ["exception-1"],
            "provenance_ids": provenance,
        },
    }


def _executed_multiview_report() -> dict[str, object]:
    source_id = "prov:bridge-1"
    return {
        "reports": {
            "deontic_norms": {
                "ir_document": {
                    "document_id": "bridge-document",
                    "views": {
                        "deontic_ir": {
                            "payload": {
                                "norms": [
                                    {
                                        "action": "disclose",
                                        "action_object": "record",
                                        "actor": "agency",
                                        "conditions": ["after confidential notice"],
                                        "exceptions": ["unless a court authorizes it"],
                                        "norm_type": "prohibition",
                                        "source_id": source_id,
                                    }
                                ]
                            }
                        },
                        "deontic_formula_records": {
                            "payload": {
                                "records": [
                                    {"formula_id": "formula-bridge-1", "source_id": source_id}
                                ]
                            }
                        },
                        "deontic_decoder_reconstructions": {
                            "payload": {
                                "records": [
                                    {
                                        "reconstruction_id": "decoder-1",
                                        "semantic_family": "deontic",
                                        "source_id": source_id,
                                    }
                                ]
                            }
                        },
                        "frame_logic": {
                            "payload": {
                                "triples": [
                                    {
                                        "object": "record",
                                        "predicate": "prohibits",
                                        "subject": source_id,
                                    }
                                ]
                            }
                        },
                        "neo4j_graph_data": {
                            "payload": {
                                "metadata": {"graph_id": "graph-bridge-1"},
                                "nodes": [
                                    {"id": "agency", "type": "Actor"},
                                    {"id": "record", "type": "LegalObject"},
                                ],
                                "relationships": [
                                    {
                                        "source": "agency",
                                        "target": "record",
                                        "type": "PROHIBITS",
                                    }
                                ],
                            }
                        },
                    },
                }
            },
            "fol_tdfol": {
                "ir_document": {
                    "views": {
                        "tdfol_formula": {
                            "payload": {
                                "records": [
                                    {
                                        "formula": "forall x. notice(x)",
                                        "quantifiers": ["forall"],
                                        "source_id": source_id,
                                    }
                                ]
                            }
                        }
                    }
                }
            },
            "cec_dcec": {
                "ir_document": {
                    "views": {
                        "cec_events": {
                            "payload": {
                                "events": [
                                    {
                                        "event_id": "event:notice",
                                        "event_role": "notice",
                                        "source_id": source_id,
                                    }
                                ]
                            }
                        },
                        "event_calculus": {
                            "payload": {
                                "records": [
                                    {
                                        "event_formula_fingerprint": "fluent:notice",
                                        "selected_frame": "notice_state",
                                        "source_id": source_id,
                                    }
                                ]
                            }
                        },
                    }
                }
            },
            "external_prover_router": {
                "ir_document": {
                    "views": {
                        "prover_formulas": {
                            "payload": {"records": [{"source_id": source_id}]}
                        }
                    }
                },
                "proof_gate": {
                    "details": [
                        {
                            "available_provers": ["z3_python"],
                            "completed_provers": ["z3_python"],
                            "proved": False,
                        }
                    ],
                    "verified_by": [],
                },
            },
        }
    }


def test_multiview_projection_uses_only_executed_stages_and_hashes_source_spans() -> None:
    report = _executed_multiview_report()
    payloads = legal_ir_contract_payloads_from_multiview_report(report)
    serialized = json.dumps(payloads, sort_keys=True)

    assert set(payloads) == {
        "cec",
        "decompiler",
        "deontic",
        "external_provers",
        "frame_logic",
        "knowledge_graphs",
        "tdfol",
    }
    assert "after confidential notice" not in serialized
    assert "unless a court authorizes it" not in serialized
    assert payloads["deontic"][0]["conditions"][0].startswith("condition:")
    assert payloads["deontic"][0]["exceptions"][0].startswith("exception:")

    partial = {"reports": {"deontic_norms": report["reports"]["deontic_norms"]}}
    partial_payloads = legal_ir_contract_payloads_from_multiview_report(partial)
    assert "external_provers" not in partial_payloads
    assert "cec" not in partial_payloads
    assert "tdfol" not in partial_payloads


def test_complete_contract_telemetry_is_deterministic_and_fully_covered() -> None:
    first = collect_legal_ir_contract_telemetry("sample-1", _views())
    second = collect_legal_ir_contract_telemetry("sample-1", _views())

    assert first.to_dict() == second.to_dict()
    assert first.schema_version == LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION
    assert first.legal_ir_contract_coverage == 1.0
    assert not first.legal_ir_contract_view_family_gaps
    assert not first.missing_required_fields
    assert not first.cross_view_mismatches
    assert not first.decompiler_preservation_failures
    assert first.source_references == ("prov:sha256:111",)


def test_missing_fields_cross_view_and_decompiler_failures_are_hash_only() -> None:
    views = _views()
    views["deontic"] = dict(views["deontic"])
    views["deontic"].pop("actor")
    views["frame_logic"] = dict(views["frame_logic"], provenance_ids=["prov:other"])
    views["decompiler"] = dict(views["decompiler"], operator="P")
    views["decompiler"]["source_text"] = "The agency shall not disclose the record."

    telemetry = collect_legal_ir_contract_telemetry("sample-2", views)
    serialized = json.dumps(telemetry.to_dict(), sort_keys=True)

    assert telemetry.legal_ir_contract_coverage < 1.0
    assert telemetry.missing_required_fields["deontic"] == ("actor",)
    assert any(item.field_path == "provenance_ids" for item in telemetry.cross_view_mismatches)
    assert any(
        item.field_path == "operator" and item.reason == "preserved_value_mismatch"
        for item in telemetry.decompiler_preservation_failures
    )
    assert telemetry.failure_counts["missing_required_fields"] == 1
    assert telemetry.failure_counts["cross_view_mismatches"] > 0
    assert telemetry.failure_counts["decompiler_preservation_failures"] > 0
    assert telemetry.validation_issue_counts["source_text_forbidden"] == 1
    assert "The agency shall not disclose" not in serialized


def test_daemon_summary_and_hammer_artifact_include_stable_contract_fields() -> None:
    telemetry = collect_legal_ir_contract_telemetry("sample-3", _views())
    aggregate = summarize_legal_ir_contract_telemetry([telemetry])
    artifacts = attach_legal_ir_contract_telemetry(
        [{"guidance_id": "guidance-1", "metadata": {"sample_id": "sample-3"}}],
        telemetry,
    )

    embedded = artifacts[0]["legal_ir_contract_telemetry"]
    assert embedded == artifacts[0]["metadata"]["legal_ir_contract_telemetry"]
    assert embedded["legal_ir_contract_coverage"] == 1.0
    assert embedded["source_references"] == ["prov:sha256:111"]

    summary: dict[str, object] = {}
    update_daemon_hammer_guidance_summary(
        summary,
        {
            **aggregate,
            "legal_ir_contract_telemetry": [telemetry.to_dict()],
            "hammer_metrics": {},
        },
    )
    assert summary["legal_ir_contract_coverage"] == 1.0
    assert summary["legal_ir_contract_failure_counts"] == aggregate[
        "legal_ir_contract_failure_counts"
    ]
    assert summary["legal_ir_contract_view_family_gaps"] == {}
    assert summary["latest_legal_ir_contract_telemetry"][0]["sample_id"] == "sample-3"


def test_modal_ir_projection_uses_provenance_ids_and_reports_unobserved_lanes() -> None:
    sample = {
        "sample_id": "modal-sample",
        "text": "This raw source must never be emitted.",
        "modal_ir": {
            "document_id": "modal-sample",
            "normalized_text": "This raw source must never be emitted.",
            "formulas": [
                {
                    "formula_id": "formula-1",
                    "operator": {"family": "deontic", "symbol": "F", "system": "KD"},
                    "predicate": {
                        "name": "disclose",
                        "arguments": ["agency", "record"],
                        "role": "prohibition",
                    },
                    "conditions": [],
                    "exceptions": [],
                    "provenance": {"source_id": "prov:modal-sample"},
                }
            ],
            "frame_logic": {
                "graph_id": "graph-1",
                "triples": [
                    {"subject": "agency", "predicate": "acts_on", "object": "record"}
                ],
            },
        },
    }

    telemetry = collect_legal_ir_contract_telemetry(sample)
    serialized = json.dumps(telemetry.to_dict(), sort_keys=True)

    assert telemetry.contract_coverage["deontic"]["valid"] is True
    assert telemetry.contract_coverage["frame_logic"]["valid"] is True
    assert telemetry.contract_coverage["knowledge_graphs"]["valid"] is True
    assert {"cec", "external_provers", "decompiler"} <= set(
        telemetry.legal_ir_contract_view_family_gaps
    )
    assert telemetry.source_references == ("prov:modal-sample",)
    assert "This raw source" not in serialized


def test_daemon_cycle_persists_and_embeds_per_sample_contract_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sample = {"sample_id": "daemon-sample", "legal_ir_views": _views()}
    args = Namespace(
        daemon_hammer_guidance_cache_enabled=False,
        daemon_hammer_guidance_enabled=True,
        daemon_hammer_guidance_max_samples_per_cycle=1,
        daemon_hammer_guidance_output_dir=str(tmp_path),
        daemon_hammer_guidance_train_autoencoder=False,
        leanstral_direct_guidance_path="",
        run_id="contract-telemetry",
    )
    monkeypatch.setattr(
        daemon_runner,
        "generate_legal_ir_proof_obligations",
        lambda _sample, **_kwargs: [object()],
    )
    monkeypatch.setattr(
        daemon_runner,
        "run_legal_ir_hammer",
        lambda *args, **kwargs: {
            "artifacts": [
                {
                    "guidance_id": "guidance-1",
                    "metadata": {"sample_id": "daemon-sample"},
                    "proved": False,
                    "trusted": False,
                }
            ],
            "obligation_count": 1,
        },
    )
    monkeypatch.setattr(
        daemon_runner,
        "_daemon_hammer_contract_sample",
        lambda _args, source: (
            dict(source),
            {
                "adapter_count": 5,
                "bridge_failures": {},
                "contract_view_counts": {
                    name: 1 for name in _views()
                },
                "document_hash": "contract-projection-unit",
            },
        ),
    )
    monkeypatch.setattr(
        daemon_runner,
        "_daemon_hammer_runtime_canary",
        lambda _config: {
            "checker_routes": ["lean"],
            "proved_count": 1,
            "reconstruction_count": 1,
            "schema_version": "legal-ir-hammer-runtime-canary-v1",
            "status": "passed",
            "trusted_count": 1,
            "winner_backends": ["z3_python"],
        },
    )

    report = daemon_runner.run_daemon_hammer_guidance_cycle(
        args=args,
        root=tmp_path,
        cycle=1,
        samples=[sample],
    )

    assert report["legal_ir_contract_coverage"] == 1.0
    assert report["legal_ir_contract_failure_counts"]["missing_required_fields"] == 0
    assert report["legal_ir_contract_view_family_gaps"] == {}
    embedded = report["hammer_guidance_artifacts"][0][
        "legal_ir_contract_telemetry"
    ]
    assert embedded["sample_id"] == "daemon-sample"
    assert embedded["source_references"] == ["prov:sha256:111"]
    persisted = json.loads(Path(report["output_path"]).read_text(encoding="utf-8"))
    assert persisted["legal_ir_contract_coverage"] == 1.0
    assert persisted["hammer_guidance_artifacts"][0][
        "legal_ir_contract_telemetry"
    ] == embedded
