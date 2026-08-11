"""Native release integrity and exact-byte TestPass V5 contracts (PTR-163)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

BACKEND = (
    Path(__file__).resolve().parents[4]
    / "ipfs_datasets_py"
    / "processors"
    / "groth16_backend"
)
BIN_DIR = BACKEND / "bin" / "linux-aarch64"
STAGED_BINARY = BIN_DIR / "groth16"
MANIFEST = BIN_DIR / "release-manifest.json"
RELEASE_BINARY = BACKEND / "target" / "release" / "groth16"
CAPACITY = 128
PROFILE_ID = "test-pass-exact-byte-v5-groth16@1"
RULESET = "test_pass_exact_byte_v5"

# Proposal gate forbids rewriting the staged ELF; functional V5 coverage uses a
# cargo-built binary under target/ (gitignored). The release-manifest still
# rehashes the immutable staged package binary.
_RUNTIME_BINARY: Path | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_runtime_binary() -> Path:
    """Return a V5-capable release binary built from the reviewed source tree."""
    global _RUNTIME_BINARY
    if _RUNTIME_BINARY is not None and _RUNTIME_BINARY.is_file():
        return _RUNTIME_BINARY

    if RELEASE_BINARY.is_file():
        probe = subprocess.run(
            [str(RELEASE_BINARY), "capabilities", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if probe.returncode == 0 and PROFILE_ID in probe.stdout:
            _RUNTIME_BINARY = RELEASE_BINARY
            return RELEASE_BINARY

    build = subprocess.run(
        ["cargo", "build", "--release", "--locked", "--manifest-path", str(BACKEND / "Cargo.toml")],
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stderr or build.stdout
    assert RELEASE_BINARY.is_file(), "cargo release binary missing after build"
    probe = subprocess.run(
        [str(RELEASE_BINARY), "capabilities", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert PROFILE_ID in probe.stdout
    _RUNTIME_BINARY = RELEASE_BINARY
    return RELEASE_BINARY


def _pad_opening(msg: bytes) -> tuple[str, int]:
    assert len(msg) <= CAPACITY
    buf = bytearray(CAPACITY)
    buf[: len(msg)] = msg
    return bytes(buf).hex(), len(msg)


def _v5_witness(receipt: bytes, attestation: bytes) -> dict:
    r_hex, rlen = _pad_opening(receipt)
    a_hex, alen = _pad_opening(attestation)
    return {
        "private_axioms": [],
        "theorem": "",
        "axioms_commitment_hex": "00" * 32,
        "theorem_hash_hex": "00" * 32,
        "circuit_version": 5,
        "ruleset_id": RULESET,
        "test_pass_v5": {
            "receipt_bytes_hex": r_hex,
            "receipt_len": rlen,
            "attestation_bytes_hex": a_hex,
            "attestation_len": alen,
        },
    }


def test_release_manifest_rehashes_executable_and_build_inputs():
    assert STAGED_BINARY.is_file(), "staged groth16 binary required"
    assert MANIFEST.is_file(), "release-manifest.json required"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ipfs-datasets/groth16-release-manifest@1"
    assert manifest["architecture"] == "linux-aarch64"
    assert manifest["binary"]["sha256"] == _sha256(STAGED_BINARY)
    assert manifest["binary"]["toolchain"]
    source = manifest["source"]
    assert source["cargo_lock_sha256"] == _sha256(BACKEND / "Cargo.lock")
    assert source["circuit_rs_sha256"] == _sha256(BACKEND / "src" / "circuit.rs")
    assert source["cargo_toml_sha256"] == _sha256(BACKEND / "Cargo.toml")
    assert source["build_rs_sha256"] == _sha256(BACKEND / "build.rs")
    assert source["v5_profile_id"] == PROFILE_ID
    assert source["v5_circuit_version"] == 5
    assert source["v5_public_input_count"] == 7
    assert source["v5_capacity_bytes"] == CAPACITY


def test_release_manifest_does_not_claim_absent_production_keys():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    profile = manifest["profiles"][PROFILE_ID]
    assert profile["circuit_version"] == 5
    assert profile["public_input_count"] == 7
    assert profile["status"] in {"unavailable", "deferred"}
    assert profile.get("proving_key_present") is False
    assert profile.get("verifying_key_present") is False
    # No staged production v5 keys under the package tree.
    assert not (BIN_DIR / "proving_key.bin").exists()
    assert not (BIN_DIR / "verifying_key.bin").exists()
    assert manifest["trusted_setup"]["generated_during_build"] is False
    assert manifest["trusted_setup"]["generated_during_package_install"] is False


def test_capabilities_is_side_effect_free_and_reports_v5_profile(tmp_path: Path):
    binary = _ensure_runtime_binary()
    before = {p.name: p.stat().st_mtime_ns for p in BIN_DIR.iterdir()}
    # Point artifacts at an empty root so capabilities cannot depend on keys.
    empty_root = tmp_path / "artifacts"
    empty_root.mkdir()
    env = os.environ.copy()
    env["GROTH16_BACKEND_ARTIFACTS_ROOT"] = str(empty_root)
    result = subprocess.run(
        [str(binary), "capabilities", "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema"] == "ipfs-datasets/groth16-capabilities@1"
    v5 = report["profiles"]["5"]
    assert v5["id"] == PROFILE_ID
    assert v5["public_input_count"] == 7
    assert v5["public_inputs"] == [
        "receipt_digest_hi",
        "receipt_digest_lo",
        "attestation_digest_hi",
        "attestation_digest_lo",
        "receipt_len",
        "attestation_len",
        "circuit_version",
    ]
    assert v5["digest_encoding"] == "two_u128_limbs_be"
    assert v5["caller_supplied_digest_labels"] is False
    assert report["side_effects"]["setup_on_capabilities"] is False
    assert report["side_effects"]["setup_on_verify"] is False
    # No keys or new files created under empty root or package bin.
    assert list(empty_root.iterdir()) == []
    after = {p.name: p.stat().st_mtime_ns for p in BIN_DIR.iterdir()}
    assert after == before
    # Staged package binary is left untouched by the runtime path.
    assert STAGED_BINARY.is_file()


def test_verify_without_keys_is_unavailable_not_auto_setup(tmp_path: Path):
    binary = _ensure_runtime_binary()
    empty_root = tmp_path / "artifacts"
    empty_root.mkdir()
    env = os.environ.copy()
    env["GROTH16_BACKEND_ARTIFACTS_ROOT"] = str(empty_root)
    # Minimal invalid proof body: verify must not create keys.
    proof = {
        "schema_version": 1,
        "proof_a": "[]",
        "proof_b": "[]",
        "proof_c": "[]",
        "public_inputs": ["0x" + "00" * 32] * 7,
        "timestamp": 0,
        "version": 5,
    }
    result = subprocess.run(
        [str(binary), "verify", "--proof", "/dev/stdin", "--json"],
        input=json.dumps(proof).encode(),
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )
    # Invalid or operational failure — never success that required manufactured keys.
    assert result.returncode in {1, 2}
    assert list(empty_root.rglob("*")) == []


@pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "").strip()
    not in {"1", "true", "TRUE", "yes", "YES"},
    reason="Groth16 backend is opt-in",
)
def test_ephemeral_v5_setup_prove_verify_mutations_and_a_vs_b():
    """Real ephemeral V5 setup/prove/verify with no skip/xfail; mutation + A≠B."""
    binary = _ensure_runtime_binary()
    with tempfile.TemporaryDirectory(prefix="groth16_v5_native_") as tmp:
        root = Path(tmp)
        env = os.environ.copy()
        env["GROTH16_BACKEND_ARTIFACTS_ROOT"] = str(root)
        env["GROTH16_BACKEND_DETERMINISTIC"] = "1"

        setup = subprocess.run(
            [str(binary), "setup", "--version", "5", "--seed", "17", "--quiet"],
            capture_output=True,
            text=True,
            env=env,
            timeout=3600,
            check=False,
        )
        assert setup.returncode == 0, setup.stderr
        assert (root / "v5" / "proving_key.bin").is_file()
        assert (root / "v5" / "verifying_key.bin").is_file()

        witness_a = _v5_witness(b"receipt-statement-A", b"attestation-statement-A")
        prove_a = subprocess.run(
            [
                str(binary),
                "prove",
                "--input",
                "/dev/stdin",
                "--output",
                "/dev/stdout",
                "--seed",
                "99",
                "--quiet",
            ],
            input=json.dumps(witness_a).encode(),
            capture_output=True,
            env=env,
            timeout=600,
            check=False,
        )
        assert prove_a.returncode == 0, prove_a.stderr.decode(errors="replace")
        proof_a = json.loads(prove_a.stdout.decode())
        assert proof_a["version"] == 5
        assert len(proof_a["public_inputs"]) == 7
        # Flattened extra fields appear at top level via serde flatten.
        assert proof_a.get("test_pass_profile") == PROFILE_ID
        assert "evm_proof" in proof_a
        assert "evm_public_inputs" in proof_a
        assert proof_a["evm_public_inputs"] == proof_a["public_inputs"]

        verify_a = subprocess.run(
            [str(binary), "verify", "--proof", "/dev/stdin", "--json", "--quiet"],
            input=json.dumps(proof_a).encode(),
            capture_output=True,
            env=env,
            timeout=120,
            check=False,
        )
        assert verify_a.returncode == 0, verify_a.stderr.decode(errors="replace")
        assert json.loads(verify_a.stdout.decode()).get("valid") is True

        # Mutate every public input.
        for idx in range(7):
            bad = json.loads(json.dumps(proof_a))
            pi = bad["public_inputs"][idx]
            raw = bytes.fromhex(pi[2:] if pi.startswith(("0x", "0X")) else pi)
            mutated = bytearray(raw)
            mutated[-1] ^= 0x01
            new_hex = "0x" + mutated.hex()
            bad["public_inputs"][idx] = new_hex
            if "evm_public_inputs" in bad:
                bad["evm_public_inputs"][idx] = new_hex
            v = subprocess.run(
                [str(binary), "verify", "--proof", "/dev/stdin", "--json", "--quiet"],
                input=json.dumps(bad).encode(),
                capture_output=True,
                env=env,
                timeout=120,
                check=False,
            )
            assert v.returncode == 1, f"public input {idx} mutation must be invalid"

        # Statement B must not verify with proof A.
        witness_b = _v5_witness(b"receipt-statement-B", b"attestation-statement-B")
        prove_b = subprocess.run(
            [
                str(binary),
                "prove",
                "--input",
                "/dev/stdin",
                "--output",
                "/dev/stdout",
                "--seed",
                "100",
                "--quiet",
            ],
            input=json.dumps(witness_b).encode(),
            capture_output=True,
            env=env,
            timeout=600,
            check=False,
        )
        assert prove_b.returncode == 0, prove_b.stderr.decode(errors="replace")
        proof_b = json.loads(prove_b.stdout.decode())
        cross = json.loads(json.dumps(proof_a))
        cross["public_inputs"] = proof_b["public_inputs"]
        if "evm_public_inputs" in proof_b:
            cross["evm_public_inputs"] = proof_b["evm_public_inputs"]
        cross_v = subprocess.run(
            [str(binary), "verify", "--proof", "/dev/stdin", "--json", "--quiet"],
            input=json.dumps(cross).encode(),
            capture_output=True,
            env=env,
            timeout=120,
            check=False,
        )
        assert cross_v.returncode == 1

        # Reject non-canonical padding / wrong lengths at prove time.
        bad_pad = _v5_witness(b"abc", b"def")
        raw = bytearray(bytes.fromhex(bad_pad["test_pass_v5"]["receipt_bytes_hex"]))
        raw[bad_pad["test_pass_v5"]["receipt_len"]] = 0xFF
        bad_pad["test_pass_v5"]["receipt_bytes_hex"] = raw.hex()
        pad_res = subprocess.run(
            [
                str(binary),
                "prove",
                "--input",
                "/dev/stdin",
                "--output",
                "/dev/stdout",
                "--quiet",
            ],
            input=json.dumps(bad_pad).encode(),
            capture_output=True,
            env=env,
            timeout=120,
            check=False,
        )
        assert pad_res.returncode == 2

        # Reject missing openings (caller-supplied label path).
        no_open = {
            "private_axioms": [],
            "theorem": "",
            "axioms_commitment_hex": "00" * 32,
            "theorem_hash_hex": "00" * 32,
            "circuit_version": 5,
            "ruleset_id": RULESET,
        }
        label_res = subprocess.run(
            [
                str(binary),
                "prove",
                "--input",
                "/dev/stdin",
                "--output",
                "/dev/stdout",
                "--quiet",
            ],
            input=json.dumps(no_open).encode(),
            capture_output=True,
            env=env,
            timeout=60,
            check=False,
        )
        assert label_res.returncode == 2
