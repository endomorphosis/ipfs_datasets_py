"""Immutable-manifest-pinned native Groth16 provider for TestPassStatementV5.

This is the only proof provider that may yield ``VERIFIED`` at the test-reuse
authority boundary.  Construction and import never build, download, install,
run trusted setup, or touch the network.  Missing or mismatched executable,
circuit, proving key, verifying key, or toolchain yields ``DEFERRED`` / RUN.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Mapping

from .statements.test_pass import (
    TEST_PASS_STATEMENT_V5_VERSION,
    TEST_PASS_V5_CIRCUIT_PROFILE,
    TEST_PASS_V5_PUBLIC_INPUT_COUNT,
    TEST_PASS_V5_RULESET_ID,
    TestPassPrivateWitnessV5,
    TestPassStatementError,
    TestPassStatementV5,
)

NATIVE_GROTH16_V5_INTERFACE: Final = "NativeGroth16V5Provider@1"
NATIVE_GROTH16_V5_PROOF_INTERFACE: Final = "NativeGroth16V5Proof@1"
NATIVE_GROTH16_V5_MANIFEST_SCHEMA: Final = "ipfs-datasets/groth16-release-manifest@1"

_ENABLE_ENV: Final = "IPFS_DATASETS_ENABLE_GROTH16"
_BINARY_ENV: Final = "IPFS_DATASETS_GROTH16_BINARY"
_ARTIFACTS_ENV: Final = "GROTH16_BACKEND_ARTIFACTS_ROOT"
_DEFAULT_TIMEOUT: Final = 120.0


class NativeGroth16V5Status(StrEnum):
    READY = "ready"
    DEFERRED = "deferred"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class NativeGroth16V5Capability:
    """Typed capability; never truthy as a boolean authority claim."""

    status: NativeGroth16V5Status
    reason: str
    binary_path: str = ""
    verifying_key_path: str = ""
    proving_key_path: str = ""
    circuit_path: str = ""
    artifacts_root: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - defensive
        raise TypeError("inspect .available; capability is not truthy authority")

    @property
    def available(self) -> bool:
        return self.status is NativeGroth16V5Status.READY

    @property
    def test_action(self) -> str:
        return "prove_or_verify" if self.available else "run"


@dataclass(frozen=True, slots=True)
class NativeGroth16V5Proof:
    """Typed wire proof envelope; raw bytes and callables are never accepted."""

    envelope: bytes
    circuit_profile: str = TEST_PASS_V5_CIRCUIT_PROFILE
    interface: str = NATIVE_GROTH16_V5_PROOF_INTERFACE

    def __post_init__(self) -> None:
        if self.interface != NATIVE_GROTH16_V5_PROOF_INTERFACE:
            raise ValueError("unsupported native proof interface")
        if self.circuit_profile != TEST_PASS_V5_CIRCUIT_PROFILE:
            raise ValueError("wrong native V5 circuit profile")
        if not isinstance(self.envelope, bytes) or not self.envelope:
            raise ValueError("native proof envelope must be non-empty bytes")
        if len(self.envelope) > 4 * 1024 * 1024:
            raise ValueError("native proof envelope exceeds bound")
        try:
            value = json.loads(self.envelope)
        except (TypeError, ValueError) as exc:
            raise ValueError("native proof envelope must be JSON") from exc
        if not isinstance(value, Mapping):
            raise ValueError("native proof envelope must be a JSON object")
        version = value.get("version") or value.get("circuit_version")
        if version not in (TEST_PASS_STATEMENT_V5_VERSION, 5, "5"):
            raise ValueError("native proof envelope has wrong circuit version")
        public_inputs = value.get("public_inputs")
        if (
            not isinstance(public_inputs, list)
            or len(public_inputs) != TEST_PASS_V5_PUBLIC_INPUT_COUNT
        ):
            raise ValueError("native proof must carry exactly 7 public inputs")

    @property
    def public_inputs(self) -> list[str]:
        value = json.loads(self.envelope)
        return list(value["public_inputs"])

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NativeGroth16V5Proof":
        if not isinstance(value, Mapping):
            raise ValueError("proof mapping required")
        return cls(envelope=json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_backend_root() -> Path:
    return Path(__file__).resolve().parents[2] / "processors" / "groth16_backend"


def _default_manifest_path(root: Path) -> Path:
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        arch = "linux-aarch64"
    elif machine in {"x86_64", "amd64"}:
        arch = "linux-x86_64"
    else:
        arch = f"linux-{machine}"
    return root / "bin" / arch / "release-manifest.json"


class NativeGroth16V5Provider:
    """Local, manifest-pinned native prover/verifier for TestPassStatementV5."""

    __test__ = False
    interface: Final = NATIVE_GROTH16_V5_INTERFACE

    def __init__(
        self,
        *,
        manifest_path: str | Path | None = None,
        root: str | Path | None = None,
        artifacts_root: str | Path | None = None,
        binary_path: str | Path | None = None,
        require_enable_env: bool = True,
    ) -> None:
        self.root = Path(root) if root is not None else _default_backend_root()
        self.manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else _default_manifest_path(self.root)
        )
        env_artifacts = os.environ.get(_ARTIFACTS_ENV, "").strip()
        self.artifacts_root = (
            Path(artifacts_root)
            if artifacts_root is not None
            else Path(env_artifacts)
            if env_artifacts
            else self.root / "artifacts"
        )
        env_binary = os.environ.get(_BINARY_ENV, "").strip()
        self._binary_override = (
            Path(binary_path)
            if binary_path is not None
            else Path(env_binary)
            if env_binary
            else None
        )
        self.require_enable_env = require_enable_env

    def _load_manifest(self) -> Mapping[str, Any]:
        raw = self.manifest_path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, Mapping):
            raise ValueError("release manifest must be an object")
        if value.get("schema") != NATIVE_GROTH16_V5_MANIFEST_SCHEMA:
            raise ValueError("unsupported native release manifest schema")
        profile = None
        profiles = value.get("profiles")
        if isinstance(profiles, Mapping):
            profile = profiles.get(TEST_PASS_V5_CIRCUIT_PROFILE)
        source = value.get("source")
        if not isinstance(source, Mapping):
            raise ValueError("release manifest lacks source pins")
        if source.get("v5_profile_id") != TEST_PASS_V5_CIRCUIT_PROFILE:
            raise ValueError("release manifest does not pin exact-byte V5 profile")
        if source.get("v5_public_input_count") != TEST_PASS_V5_PUBLIC_INPUT_COUNT:
            raise ValueError("release manifest has wrong V5 public input count")
        if not isinstance(profile, Mapping) and profile is not None:
            raise ValueError("release manifest profile is malformed")
        return value

    def _resolve_binary(self, manifest: Mapping[str, Any]) -> Path:
        if self._binary_override is not None:
            return self._binary_override
        binary = manifest.get("binary")
        if isinstance(binary, Mapping) and isinstance(binary.get("path"), str):
            # Manifest paths are relative to the architecture bin directory.
            return self.manifest_path.parent / binary["path"]
        return self.manifest_path.parent / "groth16"

    def capability(self) -> NativeGroth16V5Capability:
        """Read only local pins.  Never builds, installs, downloads, or setups."""

        if self.require_enable_env and not _truthy_env(_ENABLE_ENV):
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED,
                f"{_ENABLE_ENV} is not enabled",
            )
        try:
            manifest = self._load_manifest()
            expected_arch = str(manifest.get("architecture", "")).lower()
            actual = platform.machine().lower()
            arch_norm = {
                "arm64": "linux-aarch64",
                "aarch64": "linux-aarch64",
                "x86_64": "linux-x86_64",
                "amd64": "linux-x86_64",
            }
            actual_arch = arch_norm.get(actual, f"linux-{actual}")
            if expected_arch and actual_arch != expected_arch and actual not in expected_arch:
                return NativeGroth16V5Capability(
                    NativeGroth16V5Status.DEFERRED,
                    "native release architecture does not match host",
                )

            binary = self._resolve_binary(manifest)
            if not binary.is_file() or binary.stat().st_size <= 0:
                return NativeGroth16V5Capability(
                    NativeGroth16V5Status.DEFERRED,
                    "pinned groth16 executable is missing",
                )
            binary_meta = manifest.get("binary")
            if isinstance(binary_meta, Mapping) and isinstance(binary_meta.get("sha256"), str):
                if binary.resolve() == (self.manifest_path.parent / str(binary_meta.get("path", "groth16"))).resolve():
                    if _sha256_file(binary) != binary_meta["sha256"]:
                        return NativeGroth16V5Capability(
                            NativeGroth16V5Status.DEFERRED,
                            "pinned executable digest mismatch",
                        )

            source = manifest["source"]
            for key, relative in (
                ("circuit_rs_sha256", "src/circuit.rs"),
                ("cargo_toml_sha256", "Cargo.toml"),
                ("cargo_lock_sha256", "Cargo.lock"),
                ("build_rs_sha256", "build.rs"),
            ):
                digest = source.get(key)
                path = self.root / relative
                if not isinstance(digest, str) or not path.is_file():
                    return NativeGroth16V5Capability(
                        NativeGroth16V5Status.DEFERRED,
                        f"pinned source {relative} is missing",
                    )
                if _sha256_file(path) != digest:
                    return NativeGroth16V5Capability(
                        NativeGroth16V5Status.DEFERRED,
                        f"pinned source {relative} digest mismatch",
                    )

            vk = self.artifacts_root / "v5" / "verifying_key.bin"
            pk = self.artifacts_root / "v5" / "proving_key.bin"
            if not vk.is_file() or vk.stat().st_size <= 0:
                return NativeGroth16V5Capability(
                    NativeGroth16V5Status.DEFERRED,
                    "verifying key is missing (no automatic setup)",
                    binary_path=str(binary),
                    artifacts_root=str(self.artifacts_root),
                )
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.READY,
                "native V5 release is locally pinned",
                binary_path=str(binary),
                verifying_key_path=str(vk),
                proving_key_path=str(pk) if pk.is_file() else "",
                circuit_path=str(self.root / "src" / "circuit.rs"),
                artifacts_root=str(self.artifacts_root),
            )
        except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED,
                f"native V5 release is unavailable: {exc}",
            )

    def _run(
        self,
        args: list[str],
        *,
        stdin: bytes | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> subprocess.CompletedProcess[bytes]:
        env = os.environ.copy()
        env[_ARTIFACTS_ENV] = str(self.artifacts_root)
        env.setdefault("GROTH16_BACKEND_DETERMINISTIC", "1")
        return subprocess.run(
            args,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            env=env,
        )

    def prove(
        self,
        statement: TestPassStatementV5,
        witness: TestPassPrivateWitnessV5,
        *,
        seed: int = 1,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> NativeGroth16V5Proof | NativeGroth16V5Capability:
        """Prove only after statement/witness binding; never auto-setup."""

        if not isinstance(statement, TestPassStatementV5) or not isinstance(
            witness, TestPassPrivateWitnessV5
        ):
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED,
                "V5 prove requires typed statement and witness",
            )
        try:
            statement.assert_witness_satisfies(witness)
        except (TestPassStatementError, TypeError, ValueError) as exc:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED, str(exc) or "witness rejected"
            )
        ready = self.capability()
        if not ready.available:
            return ready
        if not ready.proving_key_path or not Path(ready.proving_key_path).is_file():
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED,
                "proving key is missing (no automatic setup)",
                binary_path=ready.binary_path,
                verifying_key_path=ready.verifying_key_path,
                artifacts_root=ready.artifacts_root,
            )
        payload = witness.native_witness()
        try:
            result = self._run(
                [
                    ready.binary_path,
                    "prove",
                    "--input",
                    "/dev/stdin",
                    "--output",
                    "/dev/stdout",
                    "--seed",
                    str(int(seed)),
                    "--quiet",
                ],
                stdin=json.dumps(payload).encode("utf-8"),
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED,
                f"native prover could not run: {exc}",
                binary_path=ready.binary_path,
            )
        if result.returncode != 0 or not result.stdout:
            detail = (result.stderr or result.stdout or b"").decode("utf-8", "replace")[:200]
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED,
                f"native prove failed: {detail or result.returncode}",
                binary_path=ready.binary_path,
            )
        try:
            proof = NativeGroth16V5Proof(envelope=bytes(result.stdout))
        except ValueError as exc:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED, str(exc), binary_path=ready.binary_path
            )
        if tuple(proof.public_inputs) != statement.public_inputs.native_public_inputs:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED,
                "proof public inputs differ from TestPassStatementV5",
                binary_path=ready.binary_path,
            )
        return proof

    def verify(
        self,
        statement: TestPassStatementV5,
        proof: NativeGroth16V5Proof,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> NativeGroth16V5Capability:
        """Verify only a typed V5 proof after manifest + public-input checks."""

        if not isinstance(statement, TestPassStatementV5):
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED, "V5 requires TestPassStatementV5"
            )
        if not isinstance(proof, NativeGroth16V5Proof):
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED,
                "V5 requires NativeGroth16V5Proof (booleans/callables rejected)",
            )
        if tuple(proof.public_inputs) != statement.public_inputs.native_public_inputs:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED,
                "proof public inputs differ from TestPassStatementV5",
            )
        ready = self.capability()
        if not ready.available:
            return ready
        try:
            result = self._run(
                [ready.binary_path, "verify", "--proof", "/dev/stdin", "--json", "--quiet"],
                stdin=proof.envelope,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED,
                f"native verifier could not run: {exc}",
                binary_path=ready.binary_path,
            )
        if result.returncode != 0:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.REJECTED,
                "native Groth16 V5 verification failed",
                binary_path=ready.binary_path,
                verifying_key_path=ready.verifying_key_path,
            )
        try:
            decoded = json.loads(result.stdout or b"{}")
        except (TypeError, ValueError):
            decoded = {}
        if isinstance(decoded, Mapping):
            if decoded.get("valid") is False:
                return NativeGroth16V5Capability(
                    NativeGroth16V5Status.REJECTED,
                    "native verifier returned invalid",
                    binary_path=ready.binary_path,
                )
        return NativeGroth16V5Capability(
            NativeGroth16V5Status.READY,
            "native V5 proof verified",
            binary_path=ready.binary_path,
            verifying_key_path=ready.verifying_key_path,
            artifacts_root=ready.artifacts_root,
        )

    def setup_ephemeral_for_tests(
        self,
        *,
        seed: int = 17,
        timeout: float = 3600.0,
    ) -> NativeGroth16V5Capability:
        """Explicit test-only setup into artifacts_root.  Never called implicitly."""

        if self.require_enable_env and not _truthy_env(_ENABLE_ENV):
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED, f"{_ENABLE_ENV} is not enabled"
            )
        try:
            manifest = self._load_manifest()
            binary = self._resolve_binary(manifest)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED, f"manifest unavailable: {exc}"
            )
        if not binary.is_file():
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED, "executable missing for test setup"
            )
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        try:
            result = self._run(
                [
                    str(binary),
                    "setup",
                    "--version",
                    "5",
                    "--seed",
                    str(int(seed)),
                    "--quiet",
                ],
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED, f"test setup failed: {exc}"
            )
        if result.returncode != 0:
            detail = (result.stderr or b"").decode("utf-8", "replace")[:200]
            return NativeGroth16V5Capability(
                NativeGroth16V5Status.DEFERRED, f"test setup failed: {detail}"
            )
        return self.capability()


def is_native_groth16_v5_provider(value: Any) -> bool:
    """Reject True, lambdas, callables, and self-claiming provider objects."""

    return isinstance(value, NativeGroth16V5Provider)


__all__ = [
    "NATIVE_GROTH16_V5_INTERFACE",
    "NATIVE_GROTH16_V5_MANIFEST_SCHEMA",
    "NATIVE_GROTH16_V5_PROOF_INTERFACE",
    "NativeGroth16V5Capability",
    "NativeGroth16V5Proof",
    "NativeGroth16V5Provider",
    "NativeGroth16V5Status",
    "is_native_groth16_v5_provider",
]
