import json
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp import ZKPError, ZKPProof
from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend
from ipfs_datasets_py.logic.zkp.circuits import (
    attestation_view_matches_proof,
    complete_zkp_attestation_record,
    decode_simulated_proof_layout,
    zkp_attestation_legal_ir_view_loss,
)


def _fake_provekit_cli(path: Path, *, write_proof: bool = True) -> Path:
    script = f"""#!/usr/bin/env python3
import pathlib
import sys

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "prove":
    if {str(write_proof)!r} == "True":
        out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])
        out.write_bytes(b"NP" + b"x" * 198)
    print("fake prove ok")
    raise SystemExit(0)
if cmd == "verify":
    print("fake verify ok")
    raise SystemExit(0)
raise SystemExit(2)
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _artifact_metadata(tmp_path: Path) -> dict:
    pkp = tmp_path / "circuit.pkp"
    pkv = tmp_path / "circuit.pkv"
    prover_toml = tmp_path / "Prover.toml"
    proof_path = tmp_path / "proof.np"
    pkp.write_bytes(b"pkp")
    pkv.write_bytes(b"pkv")
    prover_toml.write_text('theorem_hash_field = "1"\n', encoding="utf-8")
    return {
        "security_level": 128,
        "provekit_artifacts": {
            "program_dir": str(tmp_path),
            "prover_key_path": str(pkp),
            "verifier_key_path": str(pkv),
            "input_path": str(prover_toml),
            "proof_path": str(proof_path),
        },
    }


def test_backend_returns_zkpproof_envelope_with_attestation(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))
    metadata = _artifact_metadata(tmp_path)
    started = time.time()

    proof = backend.generate_proof(
        theorem="Q",
        private_axioms=["private axiom", "private axiom -> Q"],
        metadata=metadata,
    )

    assert isinstance(proof, ZKPProof)
    assert proof.proof_data == b"NP" + b"x" * 198
    assert proof.size_bytes == len(proof.proof_data)
    assert proof.timestamp >= started
    assert proof.public_inputs["theorem"] == "Q"
    assert proof.public_inputs["circuit_ref"] == "provekit_knowledge_of_axioms@v1"
    assert proof.metadata["backend"] == "provekit"
    assert proof.metadata["proof_system"] == "ProveKit-WHIR"
    assert proof.metadata["curve_id"] == "bn254"
    assert proof.metadata["provekit"]["command"]["ok"] is True
    assert proof.metadata["provekit"]["public_input_schema"] == "provekit-public-inputs-v1"

    assert proof.public_inputs["attestation_ref"]
    assert proof.public_inputs["attestation_view_version"] == 1
    assert proof.metadata["attestation_view"]["attestation_ref"] == proof.public_inputs["attestation_ref"]
    assert attestation_view_matches_proof(
        proof_data=proof.proof_data,
        public_inputs=proof.public_inputs,
        metadata=proof.metadata,
    )


def test_backend_envelope_does_not_leak_private_axiom_text(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))

    proof = backend.generate_proof(
        theorem="Q",
        private_axioms=["secret legal axiom", "secret legal axiom -> Q"],
        metadata=_artifact_metadata(tmp_path),
    )

    payload = json.dumps(proof.to_dict(), sort_keys=True)
    assert "secret legal axiom" not in payload


def test_backend_verify_uses_envelope_artifacts(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))
    proof = backend.generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata=_artifact_metadata(tmp_path),
    )

    assert backend.verify_proof(proof) is True


def test_attestation_check_rejects_stale_proof_bytes(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))
    proof = backend.generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata=_artifact_metadata(tmp_path),
    )

    assert not attestation_view_matches_proof(
        proof_data=b"changed proof bytes",
        public_inputs=proof.public_inputs,
        metadata=proof.metadata,
    )


def test_attestation_check_accepts_embedded_view_when_public_fields_dropped():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata={"security_level": 128},
    )
    public_inputs = {
        key: value
        for key, value in proof.public_inputs.items()
        if key not in {"attestation_ref", "attestation_view_version"}
    }

    assert attestation_view_matches_proof(
        proof_data=proof.proof_data,
        public_inputs=public_inputs,
        metadata=proof.metadata,
    )

    sparse_record = {
        "proof": {
            **proof.to_dict(),
            "public_inputs": public_inputs,
        },
        "form_id": "us-code-42-18403.-96a82a94ef457b84",
    }
    completed = complete_zkp_attestation_record(sparse_record)

    assert completed["attestation_ref"] == proof.public_inputs["attestation_ref"]
    assert completed["public_inputs"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["proof"]["public_inputs"]["attestation_ref"] == completed["attestation_ref"]
    assert zkp_attestation_legal_ir_view_loss([sparse_record]) == 0.0


def test_attestation_check_rejects_half_dropped_public_attestation_fields():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata={"security_level": 128},
    )
    public_inputs = dict(proof.public_inputs)
    public_inputs.pop("attestation_view_version")

    assert not attestation_view_matches_proof(
        proof_data=proof.proof_data,
        public_inputs=public_inputs,
        metadata=proof.metadata,
    )


def test_simulated_proof_layout_decodes_serialized_hex():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata={"security_level": 128},
    )
    proof_dict = proof.to_dict()

    layout = decode_simulated_proof_layout(proof_dict["proof_data"])

    assert layout["valid"] is True
    assert layout["format"] == "SIMZKP/1"


def test_sparse_legal_ir_record_is_completed_from_nested_proof():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata={"security_level": 128},
    )
    sparse_record = {
        "proof": proof.to_dict(),
        "form_id": "us-code-33-701e-19ea9c3021f51521",
    }

    completed = complete_zkp_attestation_record(sparse_record)

    assert completed["attestation_ref"] == proof.public_inputs["attestation_ref"]
    assert completed["attestation_view"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["public_inputs"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["proof_hash"]
    assert completed["source_id"] == "us-code-33-701e-19ea9c3021f51521"
    assert zkp_attestation_legal_ir_view_loss([sparse_record]) == 0.0


def test_flattened_record_replaces_empty_duplicated_attestation_fields():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
            "ruleset_id": "LegalIR_TDFOL_v1",
        },
    )
    proof_dict = proof.to_dict()
    flattened_record = {
        "attestation_ref": "",
        "attestation_view_version": 0,
        "proof_data": proof_dict["proof_data"],
        "proof_hash": "",
        "public_inputs": {
            key: value
            for key, value in proof_dict["public_inputs"].items()
            if not key.startswith("attestation_")
        },
        "metadata": proof_dict["metadata"],
        "sample_id": "us-code-42-18726.-3ff52550e83c51a1",
    }

    completed = complete_zkp_attestation_record(flattened_record)

    assert completed["attestation_ref"] == proof.public_inputs["attestation_ref"]
    assert completed["attestation_view_version"] == 1
    assert completed["public_inputs"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["proof"]["public_inputs"]["attestation_ref"] == (
        completed["attestation_ref"]
    )
    assert completed["proof"]["metadata"]["attestation_view"]["attestation_ref"] == (
        completed["attestation_ref"]
    )
    assert completed["proof_hash"] == proof.metadata["attestation_view"]["proof_digest"]
    assert completed["axioms_commitment"] == proof.public_inputs["axioms_commitment"]
    assert completed["source_id"] == "us-code-42-18726.-3ff52550e83c51a1"
    assert zkp_attestation_legal_ir_view_loss([flattened_record]) == 0.0


def test_sparse_us_code_record_uses_citation_as_source_id():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="O(submit_annual_cost_analysis(service))",
        private_axioms=[
            "O(submit_annual_cost_analysis(service))",
            "source_citation(16 U.S.C. 1544)",
        ],
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
            "ruleset_id": "LegalIR_TDFOL_v1",
        },
    )
    sparse_record = {
        "proof": proof.to_dict(),
        "citation": "16 U.S.C. 1544",
        "section": "1544",
        "source": "us_code",
        "title": "16",
    }

    completed = complete_zkp_attestation_record(sparse_record)

    assert completed["source_id"] == "16 U.S.C. 1544"
    assert completed["attestation_ref"] == completed["public_inputs"]["attestation_ref"]
    assert completed["proof"]["metadata"]["attestation_view"]["attestation_ref"] == (
        completed["attestation_ref"]
    )
    assert zkp_attestation_legal_ir_view_loss([sparse_record]) == 0.0


def test_sparse_us_code_record_derives_source_id_from_title_and_section():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="O(file_record(director))",
        private_axioms=["O(file_record(director))", "source_section(4583)"],
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
            "ruleset_id": "LegalIR_TDFOL_v1",
        },
    )
    sparse_record = {
        "proof": proof.to_dict(),
        "section": "4583",
        "source": "us_code",
        "title": "12",
    }

    completed = complete_zkp_attestation_record(sparse_record)

    assert completed["source_id"] == "12 U.S.C. 4583"
    assert zkp_attestation_legal_ir_view_loss([sparse_record]) == 0.0


def test_sparse_us_code_record_derives_source_id_from_alias_fields():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="O(share_supply_chain_risk_information(secretary))",
        private_axioms=[
            "O(share_supply_chain_risk_information(secretary))",
            "source_section(985)",
        ],
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
            "ruleset_id": "LegalIR_TDFOL_v1",
        },
    )
    sparse_record = {
        "proof": proof.to_dict(),
        "source_type": "U.S. Code",
        "title_number": "6",
        "section_number": "985",
    }

    completed = complete_zkp_attestation_record(sparse_record)

    assert completed["source_id"] == "6 U.S.C. 985"
    assert completed["attestation_ref"] == completed["public_inputs"]["attestation_ref"]
    assert zkp_attestation_legal_ir_view_loss([sparse_record]) == 0.0


def test_proofless_us_code_sample_gets_source_attestation_view():
    raw_sample = {
        "citation": "42 U.S.C. 6979b.",
        "sample_id": "us-code-42-6979b.-e152dcb0fac962de",
        "section": "6979b.",
        "source": "us_code",
        "text": (
            "\u00a76979b. Law enforcement authority The Attorney General of the "
            "United States shall, at the request of the Administrator and on "
            "the basis of a showing of need, deputize qualified employees."
        ),
        "title": "42",
    }

    completed = complete_zkp_attestation_record(raw_sample)

    assert completed["source_id"] == "us-code-42-6979b.-e152dcb0fac962de"
    assert completed["attestation_ref"] == completed["public_inputs"]["attestation_ref"]
    assert completed["attestation_view"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["circuit_ref"] == "legal_ir_source_attestation@v1"
    assert completed["proof"]["public_inputs"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["proof"]["metadata"]["attestation_view"]["attestation_ref"] == (
        completed["attestation_ref"]
    )
    assert completed["proof_hash"]
    assert completed["ruleset_id"] == "LegalIR_Source_Attestation_v1"
    assert completed["theorem_hash"] == completed["public_inputs"]["theorem_hash"]
    assert zkp_attestation_legal_ir_view_loss([raw_sample]) == 0.0


def test_proofless_us_code_source_attestation_verifies():
    from ipfs_datasets_py.logic.zkp import ZKPProof, ZKPVerifier

    raw_sample = {
        "citation": "42 U.S.C. 5183.",
        "sample_id": "us-code-42-5183.-f1276b109cf80b41",
        "section": "5183.",
        "source": "us_code",
        "text": (
            "\u00a75183. Crisis counseling assistance and training (a) In general "
            "The President is authorized to provide professional counseling services."
        ),
        "title": "42",
    }

    completed = complete_zkp_attestation_record(raw_sample)
    proof = ZKPProof.from_dict(completed["proof"])

    assert completed["proof_hash"] == completed["attestation_view"]["proof_digest"]
    assert proof.public_inputs["attestation_ref"] == completed["attestation_ref"]
    assert ZKPVerifier(backend="simulated").verify_proof(proof) is True


@pytest.mark.parametrize(
    ("text", "expected_source_id"),
    [
        (
            "42 U.S.C. 5183.: §5183. Crisis counseling assistance and "
            "training (a) In general The President is authorized to provide "
            "professional counseling services.",
            "42 U.S.C. 5183.",
        ),
        (
            "42 U.S.C. 9859b.: §9859b. Programs The Secretary shall make "
            "allotments to eligible States under section 9859c of this title.",
            "42 U.S.C. 9859b.",
        ),
    ],
)
def test_proofless_us_code_text_prefix_gets_source_attestation_view(
    text,
    expected_source_id,
):
    raw_sample = {"text": text}

    completed = complete_zkp_attestation_record(raw_sample)

    assert completed["source_id"] == expected_source_id
    assert completed["attestation_ref"] == completed["public_inputs"]["attestation_ref"]
    assert completed["attestation_view"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["circuit_ref"] == "legal_ir_source_attestation@v1"
    assert completed["ruleset_id"] == "LegalIR_Source_Attestation_v1"
    assert zkp_attestation_legal_ir_view_loss([raw_sample]) == 0.0


@pytest.mark.parametrize(
    ("sample_text", "expected_source_id"),
    [
        (
            "42 U.S.C. 5183.: §5183. Crisis counseling assistance and training "
            "(a) In general The President is authorized to provide professional "
            "counseling services, including financial assistance to State or "
            "local agencies or private mental health organizations.",
            "42 U.S.C. 5183.",
        ),
        (
            "42 U.S.C. 9859b.: §9859b. Programs The Secretary shall make "
            "allotments to eligible States under section 9859c of this title. "
            "The Secretary shall make the allotments to enable the States to "
            "establish programs to improve the health and safety of children.",
            "42 U.S.C. 9859b.",
        ),
    ],
)
def test_proofless_metric_sample_text_gets_source_attestation_view(
    sample_text,
    expected_source_id,
):
    raw_sample = {"sample_text": sample_text}

    completed = complete_zkp_attestation_record(raw_sample)

    assert completed["source_id"] == expected_source_id
    assert completed["attestation_ref"] == completed["public_inputs"]["attestation_ref"]
    assert completed["attestation_view"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["circuit_ref"] == "legal_ir_source_attestation@v1"
    assert completed["ruleset_id"] == "LegalIR_Source_Attestation_v1"
    assert zkp_attestation_legal_ir_view_loss([raw_sample]) == 0.0


def test_backend_fails_if_cli_succeeds_without_proof_file(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli", write_proof=False)
    backend = ProveKitBackend(binary_path=str(binary))

    with pytest.raises(ZKPError, match="proof output was not created"):
        backend.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"],
            metadata=_artifact_metadata(tmp_path),
        )
