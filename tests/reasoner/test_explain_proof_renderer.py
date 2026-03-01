from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import parse_cnl_sentence
from ipfs_datasets_py.processors.legal_data.reasoner import HybridLawReasoner
from ipfs_datasets_py.processors.legal_data.reasoner.models import SourceProvenance


def _load_cases() -> list[dict]:
    path = Path(__file__).with_name("fixtures") / "explain_proof_nl_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _build_reasoner(sentence: str, jurisdiction: str) -> tuple[HybridLawReasoner, str, str]:
    ir = parse_cnl_sentence(sentence, jurisdiction=jurisdiction)
    norm = next(iter(ir.norms.values()))
    frame = ir.frames[norm.target_frame_ref]
    actor_ref = frame.roles["agent"]

    provenance = {
        norm.id.ref(): SourceProvenance(
            source_path="data/federal_laws/us_constitution.jsonld",
            source_id="proof_renderer_fixture#1",
            source_span="chars:200-230",
        )
    }
    return HybridLawReasoner(ir, provenance_by_norm=provenance), actor_ref, frame.id.ref()


def test_explain_proof_nl_renderer_contract_and_fixture_content() -> None:
    case = _load_cases()[0]
    reasoner, actor_ref, frame_ref = _build_reasoner(case["sentence"], case.get("jurisdiction", "us/federal"))

    result = reasoner.check_compliance(
        {
            "actor_ref": actor_ref,
            "frame_ref": frame_ref,
            "events": case["query"]["events"],
            "facts": case["query"]["facts"],
        },
        case["time_context"],
    )
    explained = reasoner.explain_proof(result["proof_id"], format="nl")

    assert explained["format"] == "nl"
    assert explained["renderer_version"] == "1.0"
    assert explained["query_summary"].startswith("query_kind=check_compliance;")
    assert isinstance(explained["reconstructed_nl"], list)
    assert explained["reconstructed_nl"]

    full_text = "\n".join(explained["reconstructed_nl"])
    for expected in case["expected_contains"]:
        assert expected in full_text, expected


def test_explain_proof_nl_renderer_is_deterministic() -> None:
    case = _load_cases()[0]

    r1, actor1, frame1 = _build_reasoner(case["sentence"], case.get("jurisdiction", "us/federal"))
    r2, actor2, frame2 = _build_reasoner(case["sentence"], case.get("jurisdiction", "us/federal"))

    out1 = r1.check_compliance(
        {
            "actor_ref": actor1,
            "frame_ref": frame1,
            "events": case["query"]["events"],
            "facts": case["query"]["facts"],
        },
        case["time_context"],
    )
    out2 = r2.check_compliance(
        {
            "actor_ref": actor2,
            "frame_ref": frame2,
            "events": case["query"]["events"],
            "facts": case["query"]["facts"],
        },
        case["time_context"],
    )

    ex1 = r1.explain_proof(out1["proof_id"], format="nl")
    ex2 = r2.explain_proof(out2["proof_id"], format="nl")

    assert ex1["proof_id"] == ex2["proof_id"]
    assert ex1["explanation"] == ex2["explanation"]
    assert ex1["reconstructed_nl"] == ex2["reconstructed_nl"]
