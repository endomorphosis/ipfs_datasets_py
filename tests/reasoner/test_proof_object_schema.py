from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import parse_cnl_sentence
from ipfs_datasets_py.processors.legal_data.reasoner import HybridLawReasoner
from ipfs_datasets_py.processors.legal_data.reasoner.models import SourceProvenance
from ipfs_datasets_py.processors.legal_data.reasoner.serialization import proof_from_dict, proof_to_dict


def _build_reasoner() -> tuple[HybridLawReasoner, str, str]:
    ir = parse_cnl_sentence("Company A shall file report within 30 days.", jurisdiction="us/federal")
    norm = next(iter(ir.norms.values()))
    frame = ir.frames[norm.target_frame_ref]
    actor_ref = frame.roles["agent"]

    provenance = {
        norm.id.ref(): SourceProvenance(
            source_path="data/federal_laws/us_constitution.jsonld",
            source_id="proof_schema_fixture#1",
            source_span="chars:120-150",
        )
    }
    return HybridLawReasoner(ir, provenance_by_norm=provenance), actor_ref, norm.target_frame_ref


def test_proof_object_has_normalized_schema_and_replay_hash() -> None:
    reasoner, actor_ref, frame_ref = _build_reasoner()
    out = reasoner.check_compliance(
        {
            "actor_ref": actor_ref,
            "frame_ref": frame_ref,
            "events": [],
            "facts": {"true": True},
        },
        {"at_time": "2026-03-20T10:00:00Z", "start": "2026-03-01T00:00:00Z", "end": "2026-03-20T10:00:00Z"},
    )

    proof = reasoner.get_proof(out["proof_id"])
    assert proof.schema_version == "1.0"
    assert len(proof.proof_hash) == 64
    assert proof.proof_id == f"pf_{proof.proof_hash[:12]}"
    assert proof.created_at
    assert len(proof.certificates) >= 2
    assert all(c.certificate_id.startswith("cert_") for c in proof.certificates)
    assert all(len(c.normalized_hash) == 64 for c in proof.certificates)
    assert all(c.format for c in proof.certificates)

    replay = reasoner.validate_proof_replay(proof.proof_id)
    assert replay["replay_match"] is True


def test_proof_steps_always_include_ir_refs_and_provenance() -> None:
    reasoner, actor_ref, frame_ref = _build_reasoner()
    out = reasoner.check_compliance(
        {
            "actor_ref": actor_ref,
            "frame_ref": frame_ref,
            "events": [],
            "facts": {"true": True, "conflict_mode": True},
        },
        {"at_time": "2026-03-20T10:00:00Z", "start": "2026-03-01T00:00:00Z", "end": "2026-03-20T10:00:00Z"},
    )

    proof = reasoner.get_proof(out["proof_id"])
    assert proof.steps
    assert all(step.ir_refs for step in proof.steps)
    assert all(step.provenance for step in proof.steps)
    assert proof.certificate_trace_map
    cert_ids = {c.certificate_id for c in proof.certificates}
    assert cert_ids == set(proof.certificate_trace_map.keys())
    assert all(proof.certificate_trace_map[cid] for cid in cert_ids)


def test_proof_id_and_hash_are_reproducible_for_identical_inputs() -> None:
    reasoner_a, actor_ref_a, frame_ref_a = _build_reasoner()
    reasoner_b, actor_ref_b, frame_ref_b = _build_reasoner()

    query_a = {
        "actor_ref": actor_ref_a,
        "frame_ref": frame_ref_a,
        "events": [],
        "facts": {"true": True},
    }
    query_b = {
        "actor_ref": actor_ref_b,
        "frame_ref": frame_ref_b,
        "events": [],
        "facts": {"true": True},
    }
    time_context = {
        "at_time": "2026-03-20T10:00:00Z",
        "start": "2026-03-01T00:00:00Z",
        "end": "2026-03-20T10:00:00Z",
    }

    out_a = reasoner_a.check_compliance(query_a, time_context)
    out_b = reasoner_b.check_compliance(query_b, time_context)
    proof_a = reasoner_a.get_proof(out_a["proof_id"])
    proof_b = reasoner_b.get_proof(out_b["proof_id"])

    assert proof_a.proof_id == proof_b.proof_id
    assert proof_a.proof_hash == proof_b.proof_hash


def test_proof_roundtrip_preserves_schema_fields() -> None:
    reasoner, actor_ref, frame_ref = _build_reasoner()
    out = reasoner.check_compliance(
        {
            "actor_ref": actor_ref,
            "frame_ref": frame_ref,
            "events": [],
            "facts": {"true": True},
        },
        {"at_time": "2026-03-20T10:00:00Z", "start": "2026-03-01T00:00:00Z", "end": "2026-03-20T10:00:00Z"},
    )

    proof = reasoner.get_proof(out["proof_id"])
    payload = proof_to_dict(proof)
    decoded = proof_from_dict(payload)

    assert decoded.schema_version == proof.schema_version
    assert decoded.proof_hash == proof.proof_hash
    assert decoded.created_at == proof.created_at
    assert len(decoded.certificates) == len(proof.certificates)
    assert set(decoded.certificate_trace_map.keys()) == set(proof.certificate_trace_map.keys())
