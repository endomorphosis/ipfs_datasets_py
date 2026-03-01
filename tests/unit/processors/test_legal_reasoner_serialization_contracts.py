from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.legal_data.reasoner.serialization import (
    SUPPORTED_CNL_VERSION,
    SUPPORTED_IR_VERSION,
    load_legal_ir_from_json,
    load_legacy_logic_hybrid_fixture,
)


def _minimal_ir_payload(*, ir_version: str, cnl_version: str) -> dict:
    return {
        "ir_version": ir_version,
        "cnl_version": cnl_version,
        "version": ir_version,
        "jurisdiction": "Federal",
        "clock": "discrete",
        "entities": {
            "ent:agent": {
                "id": {"namespace": "ent", "value": "agent"},
                "type_name": "LegalActor",
                "attrs": {"label": "Agency"},
            }
        },
        "frames": {
            "frm:act": {
                "id": {"namespace": "frm", "value": "act"},
                "kind": "action",
                "verb": "file",
                "roles": {"agent": "ent:agent"},
                "jurisdiction": "Federal",
                "attrs": {"action_text": "file report"},
            }
        },
        "temporal": {},
        "norms": {
            "nrm:one": {
                "id": {"namespace": "nrm", "value": "one"},
                "op": "O",
                "target_frame_ref": "frm:act",
                "activation": {"op": "atom", "atom": {"pred": "true", "args": []}},
                "exceptions": [],
                "priority": 0,
                "jurisdiction": "Federal",
                "attrs": {},
            }
        },
        "rules": {},
        "queries": {},
    }


def test_load_legal_ir_from_json_accepts_contract_v1(tmp_path):
    payload = _minimal_ir_payload(ir_version=SUPPORTED_IR_VERSION, cnl_version=SUPPORTED_CNL_VERSION)
    path = tmp_path / "ir_v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    ir = load_legal_ir_from_json(path)

    assert ir.version == SUPPORTED_IR_VERSION
    assert "nrm:one" in ir.norms


def test_load_legal_ir_from_json_rejects_non_v1_contract(tmp_path):
    payload = _minimal_ir_payload(ir_version="2.0", cnl_version=SUPPORTED_CNL_VERSION)
    path = tmp_path / "ir_bad_version.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported ir_version"):
        load_legal_ir_from_json(path)


def test_load_legacy_logic_hybrid_fixture_upgrades_embedded_payload(tmp_path):
    legacy_ir = _minimal_ir_payload(ir_version="0.1", cnl_version="0.1")
    legacy_ir["version"] = "0.1"
    legacy_fixture = {
        "@context": {"hybridIRJson": "https://example.org/logic/hybridIRJson"},
        "name": "Legacy fixture",
        "records": [
            {
                "id": "seg-1",
                "hybridIRJson": json.dumps(legacy_ir),
            }
        ],
    }

    path = tmp_path / "logic.hybrid.jsonld"
    path.write_text(json.dumps(legacy_fixture), encoding="utf-8")

    ir = load_legacy_logic_hybrid_fixture(path)

    assert ir.version == SUPPORTED_IR_VERSION
    assert "nrm:one" in ir.norms
