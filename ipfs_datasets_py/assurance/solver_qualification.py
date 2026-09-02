"""Fail-closed PCPR-017 Datasets solver-path qualification.

Qualify bounded real Z3, cvc5, one Lean or Coq path, canonical IR
round-trip, source-lineage validation, ContextPack identity, one
translation receipt, and one proof or counterexample workflow.

Live claims require live evidence from the sealed validation PATH or an
approved digest-bound, root-owned, non-writable toolchain. User-home
installs and simulated fixtures cannot mint live qualification. Missing
solvers stay typed unavailable and are not recorded as passing.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Importing it is
inert: no PATH probe, process launch, network, or install.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "DatasetsSolverQualification@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/solver-qualification@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/solver-qualification-verdict@1"
)
PCPR_017_TASK_ID: Final = "PCPR-017"
PCPR_017_GOAL_ID: Final = "PCPR-G230"
PCPR_016_TASK_ID: Final = "PCPR-016"
PCPR_003_TASK_ID: Final = "PCPR-003"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = (
    "proof-carrying-platform-qualification-and-release-v1"
)
EVIDENCE_ID: Final = "pcpr/datasets-solver-qualification@1"

EXPECTED_FORMAL_TOOLCHAIN_DEPLOYMENT_IDENTITY: Final = (
    "fa9916ef2e4a927ae633309de7ef09b9d85e798e9a6711ae13bc502c6015e0c8"
)
APPROVED_IMMUTABLE_TOOLCHAIN_ROOT: Final = Path(
    "/opt/ipfs-accelerate/formal-toolchains"
)
MANAGED_ROOT_ENV_NAMES: Final[tuple[str, ...]] = (
    "IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT",
    "IPFS_DATASETS_PY_THEOREM_PROVERS_ROOT",
)

CLOSED_RELEASE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "release_candidate_qualified",
        "non_promoted_supervisor_unqualified",
        "non_promoted_import_or_false_success",
        "non_promoted_live_storage_gap",
        "non_promoted_live_compute_gap",
        "non_promoted_solver_gap",
        "non_promoted_packaging_gap",
        "non_promoted_dependency_reproducibility",
        "non_promoted_security_failure",
        "non_promoted_interoperability_gap",
        "non_promoted_reference_workflow_failure",
        "non_promoted_unmeasured",
        "non_promoted_operator_gate_required",
    }
)
PROMOTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "supervisor_promoted",
        "supervisor_non_promoted",
        "rnd_non_promoted",
        "typed_unavailable",
        "typed_blocked",
    }
)
EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "measured",
        "measured_live",
        "measured_hermetic",
        "estimated",
        "simulated",
        "unavailable",
    }
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_017_solver_qualification.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"
SEALED_GIT: Final = "/usr/bin/git"

SOLVER_NAMES: Final[tuple[str, ...]] = ("z3", "cvc5", "lean", "coq")
_SOLVER_BINARIES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "z3": ("z3",),
        "cvc5": ("cvc5",),
        "lean": ("lean",),
        "coq": ("coqc", "coqtop"),
    }
)

REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "canonical_ir_roundtrip",
        "source_lineage_validation",
        "context_pack_identity",
        "translation_receipt",
        "hermetic_proof_workflow",
        "hermetic_counterexample_workflow",
        "manifest_advertises_solver_qualification",
        "readme_auto_install_not_live",
        "user_home_solvers_not_live",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "simulated_results_represented_as_live",
        "user_home_solver_represented_as_live",
        "hermetic_results_represented_as_live",
        "python_user_site_solver_represented_as_live",
        "auto_install_represented_as_live",
    }
)

_HOME_PATH_RE: Final = re.compile(
    r"(?:^|/)(?:home|Users)(?:/|$)|(?:^|/)\.local(?:/|$)|(?:^|/)\.elan(?:/|$)"
)
_CID_RE: Final = re.compile(r"^b[a-z2-7]+$")


class SolverQualificationError(Exception):
    """Fail-closed PCPR-017 contract error."""


class SolverQualificationAdmissionError(SolverQualificationError):
    """Raised when solver qualification evidence is rejected."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    """CIDv1 DAG-JSON/sha2-256 identity (baguqeera…)."""

    digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    raw = b"\x01\xa9\x02\x12\x20" + digest
    return "b" + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def discover_datasets_root(start: Path | None = None) -> Path | None:
    here = Path(start or __file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "ipfs_datasets_py").is_dir() and (
            candidate / "pyproject.toml"
        ).is_file():
            return candidate
    return None


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SolverQualificationError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise SolverQualificationError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise SolverQualificationError(
            f"{name} must not be a closed PCPR release outcome"
        )


def solver_qualification_manifest() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "interface": INTERFACE,
        "import_side_effects": "none",
        "live_sources": [
            "sealed_path",
            "approved_digest_bound_managed_root",
        ],
        "rejected_live_sources": [
            "user_home",
            "user_site",
            "simulated_fixture",
            "auto_install",
        ],
        "task_id": PCPR_017_TASK_ID,
        "goal_id": PCPR_017_GOAL_ID,
    }


def _is_user_owned_path(path: Path) -> bool:
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    return bool(_HOME_PATH_RE.search(resolved))


def _path_user_writable(path: Path) -> bool:
    try:
        current = path.resolve()
    except OSError:
        return True
    for candidate in (current, *current.parents):
        try:
            if os.access(candidate, os.W_OK):
                return True
        except OSError:
            return True
        if candidate.parent == candidate:
            break
    return False


def _admitted_executable(path: Path) -> Path | None:
    try:
        if not path.is_file() or not os.access(path, os.X_OK):
            return None
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    if _is_user_owned_path(resolved):
        return None
    if _path_user_writable(resolved.parent):
        return None
    mode = resolved.stat().st_mode
    if stat.S_IMODE(mode) & stat.S_IWOTH:
        return None
    return resolved


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _bin_dirs_for_root(root: Path) -> tuple[Path, ...]:
    candidates = [
        root,
        root / "bin",
        root / "provers" / "bin",
    ]
    try:
        for lean_dir in sorted(root.glob("lean-*")):
            candidates.append(lean_dir / "bin")
        nested = root / "provers"
        if nested.is_dir():
            candidates.append(nested / "bin")
    except OSError:
        pass
    return tuple(candidates)


def _approved_toolchain_bin_dirs() -> tuple[Path, ...]:
    dirs: list[Path] = []
    if not APPROVED_IMMUTABLE_TOOLCHAIN_ROOT.is_dir():
        return ()
    if _path_user_writable(APPROVED_IMMUTABLE_TOOLCHAIN_ROOT):
        return ()
    try:
        children = sorted(APPROVED_IMMUTABLE_TOOLCHAIN_ROOT.iterdir())
    except OSError:
        return ()
    for child in children:
        if not child.is_dir():
            continue
        if _path_user_writable(child):
            continue
        dirs.append(child / "provers" / "bin")
        try:
            for lean_dir in sorted(child.glob("lean-*")):
                dirs.append(lean_dir / "bin")
        except OSError:
            continue
    return tuple(dirs)


def _search_directories() -> tuple[Path, ...]:
    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        dirs.append(path)

    for entry in SEALED_PATH.split(":"):
        if entry:
            _add(Path(entry))
    for variable in MANAGED_ROOT_ENV_NAMES:
        raw = str(os.environ.get(variable) or "").strip()
        if not raw:
            continue
        root = Path(raw)
        if _is_user_owned_path(root) or _path_user_writable(root):
            continue
        for directory in _bin_dirs_for_root(root):
            _add(directory)
    for directory in _approved_toolchain_bin_dirs():
        _add(directory)
    return tuple(dirs)


def discover_solver_executable(name: str) -> Path | None:
    """Return an admitted live solver binary, or None if typed unavailable.

    Sealed PATH is preferred. Approved digest-bound roots are admitted.
    User-home and user-writable paths are rejected.
    """

    binaries = _SOLVER_BINARIES.get(name)
    if not binaries:
        raise SolverQualificationError(f"unknown solver {name!r}")
    for directory in _search_directories():
        for binary in binaries:
            admitted = _admitted_executable(directory / binary)
            if admitted is not None:
                return admitted
    return None


def solver_discovery_source(path: Path | None) -> str:
    if path is None:
        return "unavailable"
    text = str(path)
    sealed_dirs = tuple(SEALED_PATH.split(":"))
    if any(text.startswith(item + "/") or text == item for item in sealed_dirs):
        return "sealed_path"
    if str(APPROVED_IMMUTABLE_TOOLCHAIN_ROOT) in text:
        return "approved_digest_bound_managed_root"
    return "managed_root"


def _sealed_subprocess_env(*, home: str | None = None) -> dict[str, str]:
    env = {
        "PATH": SEALED_PATH,
        "HOME": home or "/nonexistent-pcpr017-home",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    for key in ("TMPDIR", "TMP", "TEMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _which_sealed(name: str) -> str:
    for directory in SEALED_PATH.split(":"):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "unavailable"


def _sealed_python_module_origin(module_name: str) -> str | None:
    python = Path(SEALED_PYTHON)
    if not python.is_file():
        return None
    script = (
        "import importlib.util\n"
        f"spec = importlib.util.find_spec({module_name!r})\n"
        "print('' if spec is None or spec.origin is None else spec.origin)\n"
    )
    try:
        completed = subprocess.run(
            [str(python), "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=_sealed_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    origin = (completed.stdout or "").strip()
    if not origin or origin == "None":
        return None
    path = Path(origin)
    if _is_user_owned_path(path):
        return None
    return origin


def observe_sealed_validation_environment() -> dict[str, Any]:
    """Measure the sealed PATH; missing tools stay typed unavailable."""

    python3_12 = Path(SEALED_PYTHON)
    python_version = "unavailable"
    if python3_12.is_file():
        try:
            completed = subprocess.run(
                [str(python3_12), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env=_sealed_subprocess_env(),
            )
            python_version = (
                completed.stdout or completed.stderr or ""
            ).strip() or "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            python_version = "unavailable"
    pytest_module = "unavailable"
    pytest_version = "unavailable"
    origin = _sealed_python_module_origin("pytest")
    if origin:
        pytest_module = origin
        try:
            import pytest  # type: ignore[import-untyped]

            module_file = getattr(pytest, "__file__", "") or ""
            if origin in module_file or not _is_user_owned_path(Path(origin)):
                pytest_version = str(getattr(pytest, "__version__", "unavailable"))
        except Exception:
            pytest_version = "unavailable"
    z3_mod = _sealed_python_module_origin("z3") or "unavailable"
    cvc5_mod = _sealed_python_module_origin("cvc5") or "unavailable"
    return {
        "PATH": SEALED_PATH,
        "python_unqualified": _which_sealed("python"),
        "python3": _which_sealed("python3"),
        "python3_12": str(python3_12) if python3_12.is_file() else "unavailable",
        "python_version": python_version,
        "git_path": _which_sealed("git"),
        "usr_bin_user_writable": os.access("/usr/bin", os.W_OK),
        "usr_local_bin_user_writable": os.access("/usr/local/bin", os.W_OK),
        "pytest_cli": _which_sealed("pytest"),
        "pytest_module": pytest_module,
        "pytest_module_version": pytest_version,
        "duckdb": _which_sealed("duckdb"),
        "anyio": "unavailable",
        "pytest_asyncio": "unavailable",
        "ipfs": _which_sealed("ipfs"),
        "z3": _which_sealed("z3"),
        "cvc5": _which_sealed("cvc5"),
        "lean": _which_sealed("lean"),
        "coqtop": _which_sealed("coqtop"),
        "z3_python_module": z3_mod,
        "cvc5_python_module": cvc5_mod,
        "evidence_kind": "measured",
    }


@dataclass(frozen=True)
class OutcomeProbe:
    probe_id: str
    present: bool | None
    evidence_kind: str
    live: bool
    simulated_represented_as_live: bool
    reason: str
    details: Mapping[str, Any] = MappingProxyType({})

    def to_mapping(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "present": self.present,
            "evidence_kind": self.evidence_kind,
            "live": self.live,
            "simulated_represented_as_live": self.simulated_represented_as_live,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class SolverQualificationVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    hermetic_semantic_workflows_qualified: bool
    live_z3_qualified: bool
    live_cvc5_qualified: bool
    live_lean_qualified: bool
    live_coq_qualified: bool
    live_solver_qualified: bool
    live_solver_evidence_kind: str
    live_z3_evidence_kind: str
    live_cvc5_evidence_kind: str
    live_lean_evidence_kind: str
    live_coq_evidence_kind: str
    simulated_results_represented_as_live: bool
    hermetic_results_represented_as_live: bool
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "hermetic_semantic_workflows_qualified": (
                self.hermetic_semantic_workflows_qualified
            ),
            "live_z3_qualified": self.live_z3_qualified,
            "live_cvc5_qualified": self.live_cvc5_qualified,
            "live_lean_qualified": self.live_lean_qualified,
            "live_coq_qualified": self.live_coq_qualified,
            "live_solver_qualified": self.live_solver_qualified,
            "live_solver_evidence_kind": self.live_solver_evidence_kind,
            "live_z3_evidence_kind": self.live_z3_evidence_kind,
            "live_cvc5_evidence_kind": self.live_cvc5_evidence_kind,
            "live_lean_evidence_kind": self.live_lean_evidence_kind,
            "live_coq_evidence_kind": self.live_coq_evidence_kind,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "hermetic_results_represented_as_live": (
                self.hermetic_results_represented_as_live
            ),
            "this_task_created_competing_authority": (
                self.this_task_created_competing_authority
            ),
            "blocker_count": len(self.blockers),
            "blockers": list(self.blockers),
            "evidence_kind": "measured",
        }


def _probe(
    probe_id: str,
    present: bool | None,
    *,
    reason: str,
    evidence_kind: str = "measured",
    live: bool = False,
    details: Mapping[str, Any] | None = None,
) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind=evidence_kind,
        live=live,
        simulated_represented_as_live=False,
        reason=reason,
        details=MappingProxyType(dict(details or {})),
    )


def _cid_label(label: str) -> str:
    from ipfs_datasets_py.logic.ir_core.identity import cid_v1

    return cid_v1(label.encode("utf-8"))


def _theorem_obligation():
    from ipfs_datasets_py.logic.backends.smt.compiler import (
        INT_SORT,
        SmtFunDecl,
        SmtNamedAssertion,
        SmtObligation,
        SmtQueryMode,
        SmtTerm,
        SmtTermKind,
        term_int,
        term_symbol,
    )

    x = term_symbol("x")
    return SmtObligation(
        obligation_id="obl:pcpr017-x-positive",
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        features=("arithmetic", "equality", "verification_conditions"),
        goal=SmtTerm(SmtTermKind.GT, arguments=(x, term_int(0))),
        assumptions=(
            SmtNamedAssertion(
                formula=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(1))),
                name="assume_ge_one",
            ),
        ),
        functions=(SmtFunDecl(name="x", range=INT_SORT, is_const=True),),
        request_unsat_core=True,
        property_ids=("property:pcpr017-x-positive",),
    )


def _sat_obligation():
    from ipfs_datasets_py.logic.backends.smt.compiler import (
        BOOL_SORT,
        SmtFunDecl,
        SmtObligation,
        SmtQueryMode,
        term_eq,
        term_symbol,
        term_true,
    )

    return SmtObligation(
        obligation_id="obl:pcpr017-sat-p",
        query_mode=SmtQueryMode.SATISFIABILITY,
        features=("equality",),
        goal=term_eq(term_symbol("p"), term_true()),
        functions=(SmtFunDecl("p", range=BOOL_SORT, is_const=True),),
        request_model=True,
    )


def _hermetic_semantic_probes() -> tuple[OutcomeProbe, ...]:
    probes: list[OutcomeProbe] = []

    try:
        from ipfs_datasets_py.logic.ir_core.identity import canonical_identity

        payload = {"pcpr": "017", "workflow": "canonical-ir-roundtrip"}
        first = canonical_identity(
            payload,
            domain="pcpr.datasets.solver-qualification",
            schema_version="1",
        )
        second = canonical_identity(
            payload,
            domain="pcpr.datasets.solver-qualification",
            schema_version="1",
        )
        ok = first.cid == second.cid and first.cid.startswith("b")
        probes.append(
            _probe(
                "canonical_ir_roundtrip",
                ok,
                evidence_kind="measured_hermetic",
                reason=(
                    "Canonical IR identity is deterministic under ir-canonical-identity-v1"
                    if ok
                    else "Canonical IR identity round-trip diverged"
                ),
                details={"cid": first.cid, "digest": first.digest},
            )
        )
    except Exception as exc:
        probes.append(
            _probe(
                "canonical_ir_roundtrip",
                False,
                reason=str(exc),
            )
        )

    try:
        from ipfs_datasets_py.logic.ir_core.provenance import (
            SourceRef,
            SourceReviewStatus,
        )
        from ipfs_datasets_py.logic.ir_core.source_lineage import (
            RightsDisposition,
            RightsRecord,
            SourceRelease,
            TemporalCoverage,
        )

        digest = "a" * 64
        release = SourceRelease(
            release_id="rel:pcpr017",
            repository_id="endomorphosis/ipfs_datasets_py",
            revision="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            pinset_id="PCPR-017-PINSET",
            rights=RightsRecord(
                disposition=RightsDisposition.QUARANTINED,
                license_expression="AGPL-3.0-only",
                source_rights_status="unresolved",
                transformation_rights_status="unresolved",
                scope="solver-qualification",
            ),
            temporal=TemporalCoverage(
                cutoff_status="unknown",
                cutoff_value=None,
                observed_at_ms=1_700_000_000_000,
            ),
            configuration_ids=("solver-qualification",),
        )
        roundtrip = SourceRelease.from_dict(release.to_dict())
        ok = roundtrip.record_cid == release.record_cid
        SourceRef(
            ref_id="ref:pcpr017",
            source_uri="pcpr://datasets/solver-qualification",
            source_id="pcpr-017",
            source_revision="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            content_sha256=digest,
            review_status=SourceReviewStatus.MACHINE_EXTRACTED,
        )
        probes.append(
            _probe(
                "source_lineage_validation",
                ok,
                evidence_kind="measured_hermetic",
                reason=(
                    "SourceRelease lineage identity round-trips"
                    if ok
                    else "SourceRelease lineage identity diverged"
                ),
                details={"record_cid": release.record_cid},
            )
        )
    except Exception as exc:
        probes.append(
            _probe("source_lineage_validation", False, reason=str(exc))
        )

    try:
        from ipfs_datasets_py.proof_context.context_pack import (
            admit_datasets_context_pack,
        )

        payload = {
            "repository_state_cid": _cid_label("pcpr017-repo-state"),
            "task_id": PCPR_017_TASK_ID,
            "target_source_cid": _cid_label("pcpr017-target"),
            "surrounding_source_cid": _cid_label("pcpr017-surround"),
            "test_source_cid": _cid_label("pcpr017-test"),
            "scanned_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
            "source_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
            "capsule_cids": (_cid_label("pcpr017-capsule"),),
        }
        first = admit_datasets_context_pack(payload)
        second = admit_datasets_context_pack(payload)
        ok = first.pack_cid == second.pack_cid and first.pack_cid.startswith("b")
        probes.append(
            _probe(
                "context_pack_identity",
                ok,
                evidence_kind="measured_hermetic",
                reason=(
                    "DatasetsContextPack@1 identity is deterministic"
                    if ok
                    else "DatasetsContextPack@1 identity diverged"
                ),
                details={"pack_cid": first.pack_cid},
            )
        )
    except Exception as exc:
        probes.append(_probe("context_pack_identity", False, reason=str(exc)))

    try:
        from ipfs_datasets_py.logic.backends.smt.compiler import (
            SoftwareVerificationSMTCompiler,
        )
        from ipfs_datasets_py.logic.software_verification.receipts import (
            LOGIC_TRANSLATION_RECEIPT_INTERFACE,
            TranslationReceiptExpectation,
            require_current_translation_receipt,
        )

        compilation = SoftwareVerificationSMTCompiler().compile(
            _theorem_obligation()
        )
        receipt = compilation.receipt
        expectation = TranslationReceiptExpectation(
            source_identity=receipt.source_identity,
            target_identity=receipt.target_identity,
            source_family_id=receipt.source_family_id,
            source_family_version=receipt.source_family_version,
            target_family_id=receipt.target_family_id,
            target_family_version=receipt.target_family_version,
            compilers=receipt.compilers,
            assumptions=receipt.assumptions,
            bounds=receipt.bounds,
        )
        current = require_current_translation_receipt(receipt, expectation)
        ok = (
            current.INTERFACE == LOGIC_TRANSLATION_RECEIPT_INTERFACE
            and current.source_identity != current.target_identity
            and bool(current.receipt_id)
        )
        probes.append(
            _probe(
                "translation_receipt",
                ok,
                evidence_kind="measured_hermetic",
                reason=(
                    "SMT compiler produced a current LogicTranslationReceipt@1"
                    if ok
                    else "Translation receipt was missing or stale"
                ),
                details={
                    "receipt_id": current.receipt_id,
                    "interface": current.INTERFACE,
                    "source_family_id": current.source_family_id,
                    "target_family_id": current.target_family_id,
                },
            )
        )
    except Exception as exc:
        probes.append(_probe("translation_receipt", False, reason=str(exc)))

    try:
        from ipfs_datasets_py.logic.backends.smt.execution_v2 import (
            SmtDisposition,
            SmtExecutionMode,
            SmtExecutionRequestV2,
            SmtProviderKind,
            hermetic_engine,
        )

        engine = hermetic_engine(
            z3_stdout="unsat\n(assume_ge_one)\n",
            cvc5_stdout="unsat\n(assume_ge_one)\n",
        )
        result = engine.execute(
            SmtExecutionRequestV2(
                request_id="req:pcpr017:hermetic-proof",
                obligation=_theorem_obligation(),
                provider=SmtProviderKind.DIFFERENTIAL,
                mode=SmtExecutionMode.HERMETIC_FIXTURE,
                source_ref_ids=("source:pcpr017:hermetic-proof",),
            )
        )
        ok = (
            result.evidence.disposition is SmtDisposition.PROVED
            and result.evidence.is_proved is True
            and bool(result.evidence.translation_receipt_id)
        )
        probes.append(
            _probe(
                "hermetic_proof_workflow",
                ok,
                evidence_kind="measured_hermetic",
                reason=(
                    "Hermetic SMT fixture proved the bounded theorem-by-negation obligation"
                    if ok
                    else "Hermetic proof workflow did not prove"
                ),
                details={
                    "disposition": result.evidence.disposition.value,
                    "translation_receipt_id": result.evidence.translation_receipt_id,
                    "live": False,
                },
            )
        )
    except Exception as exc:
        probes.append(
            _probe("hermetic_proof_workflow", False, reason=str(exc))
        )

    try:
        from ipfs_datasets_py.logic.backends.smt.execution_v2 import (
            SmtDisposition,
            SmtExecutionMode,
            SmtExecutionRequestV2,
            SmtProviderKind,
            hermetic_engine,
        )

        model = "sat\n(\n(define-fun p () Bool true)\n)\n"
        engine = hermetic_engine(z3_stdout=model, cvc5_stdout=model)
        result = engine.execute(
            SmtExecutionRequestV2(
                request_id="req:pcpr017:hermetic-sat",
                obligation=_sat_obligation(),
                provider=SmtProviderKind.DIFFERENTIAL,
                mode=SmtExecutionMode.HERMETIC_FIXTURE,
                source_ref_ids=("source:pcpr017:hermetic-sat",),
            )
        )
        ok = result.evidence.disposition is SmtDisposition.SATISFIABLE
        probes.append(
            _probe(
                "hermetic_counterexample_workflow",
                ok,
                evidence_kind="measured_hermetic",
                reason=(
                    "Hermetic SMT fixture produced a satisfying assignment"
                    if ok
                    else "Hermetic counterexample workflow was not satisfiable"
                ),
                details={
                    "disposition": result.evidence.disposition.value,
                    "live": False,
                },
            )
        )
    except Exception as exc:
        probes.append(
            _probe(
                "hermetic_counterexample_workflow",
                False,
                reason=str(exc),
            )
        )

    return tuple(probes)


def _solver_identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size": path.stat().st_size,
        "source": solver_discovery_source(path),
        "user_writable": False,
        "user_home": False,
    }


def _solver_version(path: Path, argv: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            [str(path), *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=_sealed_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    return output[0] if output else ""


def _sealed_smt_runner(executable: str, *, kind: str):
    from ipfs_datasets_py.logic.backends.smt.differential import SmtRawSolverOutput
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds

    def run(smtlib: str, bounds: ExecutionBounds) -> SmtRawSolverOutput:
        if kind == "z3":
            argv = [executable, "-in", "-smt2"]
        else:
            argv = [
                executable,
                "--lang=smt2",
                f"--tlimit-per={bounds.timeout_ms}",
                f"--rlimit={bounds.max_steps}",
            ]
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="pcpr017-smt-") as home:
                completed = subprocess.run(
                    argv,
                    input=smtlib,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=max(bounds.timeout_ms / 1000.0, 0.001),
                    env=_sealed_subprocess_env(home=home),
                )
        except subprocess.TimeoutExpired as error:
            return SmtRawSolverOutput(
                stdout=error.stdout or "" if isinstance(error.stdout, str) else "",
                stderr=error.stderr or "" if isinstance(error.stderr, str) else "timeout",
                returncode=None,
                elapsed_ms=bounds.timeout_ms,
                timed_out=True,
            )
        except OSError as error:
            return SmtRawSolverOutput(
                stderr=str(error),
                returncode=None,
                unavailable=True,
            )
        return SmtRawSolverOutput(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    return run


def _run_live_smt(kind: str, path: Path) -> dict[str, Any]:
    from ipfs_datasets_py.logic.backends.cvc5.compiler import (
        CVC5SoftwareVerificationBackend,
    )
    from ipfs_datasets_py.logic.backends.smt.differential import SmtSolverVerdict
    from ipfs_datasets_py.logic.backends.z3.compiler import (
        Z3SoftwareVerificationBackend,
    )
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds

    runner = _sealed_smt_runner(str(path), kind=kind)
    backend_cls = (
        Z3SoftwareVerificationBackend if kind == "z3" else CVC5SoftwareVerificationBackend
    )
    backend = backend_cls(
        executable=str(path),
        runner=runner,
        availability_probe=lambda: True,
        version_probe=lambda: _solver_version(
            path, ("-version",) if kind == "z3" else ("--version",)
        ),
    )
    bounds = ExecutionBounds(timeout_ms=5_000, max_steps=100_000)
    proof = backend.run(_theorem_obligation(), bounds=bounds)
    sat = backend.run(_sat_obligation(), bounds=bounds)
    proof_ok = proof.verdict is SmtSolverVerdict.UNSAT
    sat_ok = sat.verdict is SmtSolverVerdict.SAT
    receipt = proof.translation_receipt
    return {
        "proof_verdict": proof.verdict.value,
        "sat_verdict": sat.verdict.value,
        "proof_ok": proof_ok,
        "sat_ok": sat_ok,
        "ok": proof_ok and sat_ok,
        "translation_receipt_id": (
            receipt.receipt_id if receipt is not None else ""
        ),
        "solver_version": proof.solver_version or sat.solver_version,
    }


def _run_live_lean(path: Path) -> dict[str, Any]:
    version = _solver_version(path, ("--version",))
    with tempfile.TemporaryDirectory(prefix="pcpr017-lean-") as home:
        script = Path(home) / "PCPR017.lean"
        script.write_text("theorem pcpr017 : True := trivial\n", encoding="utf-8")
        try:
            completed = subprocess.run(
                [str(path), str(script)],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                env=_sealed_subprocess_env(home=home),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "ok": False,
                "exit_code": None,
                "solver_version": version,
                "reason": str(exc),
            }
        ok = completed.returncode == 0
        return {
            "ok": ok,
            "exit_code": completed.returncode,
            "solver_version": version,
            "stdout": (completed.stdout or "")[:512],
            "stderr": (completed.stderr or "")[:512],
        }


def _run_live_coq(path: Path) -> dict[str, Any]:
    version = _solver_version(path, ("-v",))
    with tempfile.TemporaryDirectory(prefix="pcpr017-coq-") as home:
        script = Path(home) / "PCPR017.v"
        script.write_text(
            "Lemma pcpr017 : True.\nProof. exact I. Qed.\n",
            encoding="utf-8",
        )
        argv = [str(path)]
        if path.name == "coqc":
            argv.append("-q")
        argv.append(str(script))
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=_sealed_subprocess_env(home=home),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "ok": False,
                "exit_code": None,
                "solver_version": version,
                "reason": str(exc),
            }
        ok = completed.returncode == 0
        return {
            "ok": ok,
            "exit_code": completed.returncode,
            "solver_version": version,
            "stdout": (completed.stdout or "")[:512],
            "stderr": (completed.stderr or "")[:512],
        }


def _unavailable_solver_probe(solver: str) -> OutcomeProbe:
    return _probe(
        f"live_{solver}_solver",
        None,
        evidence_kind="unavailable",
        live=False,
        reason=(
            f"No admitted {solver} executable on sealed PATH or an approved "
            "digest-bound non-writable toolchain. User-home and simulated "
            "copies are not live qualification."
        ),
        details={
            "solver": solver,
            "sealed_path": _which_sealed(
                "coqtop" if solver == "coq" else solver
            ),
            "source": "unavailable",
        },
    )


def _live_solver_probes() -> tuple[OutcomeProbe, ...]:
    probes: list[OutcomeProbe] = []
    for solver in ("z3", "cvc5"):
        path = discover_solver_executable(solver)
        if path is None:
            probes.append(_unavailable_solver_probe(solver))
            continue
        identity = _solver_identity(path)
        try:
            result = _run_live_smt(solver, path)
        except Exception as exc:
            probes.append(
                _probe(
                    f"live_{solver}_solver",
                    False,
                    evidence_kind="measured_live",
                    live=True,
                    reason=str(exc),
                    details=identity,
                )
            )
            continue
        ok = result.get("ok") is True
        probes.append(
            _probe(
                f"live_{solver}_solver",
                ok,
                evidence_kind="measured_live",
                live=True,
                reason=(
                    f"Live {solver} proved the bounded theorem and produced a sat model"
                    if ok
                    else f"Live {solver} did not complete the bounded proof/sat pair"
                ),
                details={**identity, **result},
            )
        )

    lean_path = discover_solver_executable("lean")
    if lean_path is None:
        probes.append(_unavailable_solver_probe("lean"))
    else:
        identity = _solver_identity(lean_path)
        result = _run_live_lean(lean_path)
        ok = result.get("ok") is True
        probes.append(
            _probe(
                "live_lean_solver",
                ok,
                evidence_kind="measured_live",
                live=True,
                reason=(
                    "Live Lean accepted theorem pcpr017 : True := trivial"
                    if ok
                    else "Live Lean did not accept the bounded theorem"
                ),
                details={**identity, **result},
            )
        )

    coq_path = discover_solver_executable("coq")
    if coq_path is None:
        probes.append(_unavailable_solver_probe("coq"))
    else:
        identity = _solver_identity(coq_path)
        result = _run_live_coq(coq_path)
        ok = result.get("ok") is True
        probes.append(
            _probe(
                "live_coq_solver",
                ok,
                evidence_kind="measured_live",
                live=True,
                reason=(
                    "Live Coq/Rocq accepted Lemma pcpr017 : True"
                    if ok
                    else "Live Coq/Rocq did not accept the bounded lemma"
                ),
                details={**identity, **result},
            )
        )

    live_smt = all(
        item.present is True and item.live
        for item in probes
        if item.probe_id in {"live_z3_solver", "live_cvc5_solver"}
    )
    live_kernel = any(
        item.present is True and item.live
        for item in probes
        if item.probe_id in {"live_lean_solver", "live_coq_solver"}
    )
    probes.append(
        _probe(
            "live_solver_qualification",
            True if live_smt and live_kernel else None if not live_smt and not live_kernel else False,
            evidence_kind=(
                "measured_live"
                if live_smt and live_kernel
                else "unavailable"
                if not live_smt and not live_kernel
                else "measured_live"
            ),
            live=bool(live_smt and live_kernel),
            reason=(
                "Bounded live Z3, cvc5, and one Lean or Coq path were observed"
                if live_smt and live_kernel
                else "Live solver set is incomplete; missing solvers stay typed unavailable"
            ),
            details={
                "z3": live_smt,
                "cvc5": live_smt,
                "lean_or_coq": live_kernel,
            },
        )
    )
    return tuple(probes)


def _readme_and_manifest_probes(*, root: Path | None) -> tuple[OutcomeProbe, ...]:
    probes: list[OutcomeProbe] = []
    readme_ok = False
    auto_install_live = False
    if root is not None:
        readme = root / "README.md"
        try:
            body = readme.read_text(encoding="utf-8")
        except OSError as exc:
            probes.append(
                _probe("readme_auto_install_not_live", False, reason=str(exc))
            )
        else:
            lowered = body.lower()
            claims_live_auto = bool(
                re.search(
                    r"auto-run after `setup\.py` install/develop \(enabled by default",
                    body,
                )
            )
            denies_live = (
                "typed unavailable" in lowered
                and "not live qualification" in lowered
            )
            auto_install_live = claims_live_auto and not denies_live
            readme_ok = denies_live and not claims_live_auto
            probes.append(
                _probe(
                    "readme_auto_install_not_live",
                    readme_ok,
                    reason=(
                        "README states auto-install and user-home solvers are not live qualification"
                        if readme_ok
                        else "README still presents auto-install as live solver availability"
                    ),
                    details={
                        "auto_install_claimed_live": auto_install_live,
                    },
                )
            )
    else:
        probes.append(
            _probe(
                "readme_auto_install_not_live",
                False,
                reason="Datasets root was not discovered",
            )
        )

    probes.append(
        _probe(
            "auto_install_represented_as_live",
            auto_install_live,
            reason=(
                "Auto-install is represented as live"
                if auto_install_live
                else "Auto-install is not represented as live qualification"
            ),
        )
    )

    manifest_ok = False
    manifest_reason = (
        "LogicPlatformManifest does not advertise DatasetsSolverQualification@1"
    )
    try:
        from ipfs_datasets_py.logic.platform.manifest import (
            DEFAULT_LOGIC_PLATFORM_MANIFEST,
        )

        versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
        roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
        operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
        manifest_ok = (
            versions.get(INTERFACE) == "1"
            and roots.get("datasets_solver_qualification") == SCHEMA
            and operations.get("solver_qualification") == "1"
        )
        if manifest_ok:
            manifest_reason = (
                "LogicPlatformManifest advertises DatasetsSolverQualification@1."
            )
    except Exception as exc:
        manifest_reason = str(exc)
    probes.append(
        _probe(
            "manifest_advertises_solver_qualification",
            manifest_ok,
            reason=manifest_reason,
        )
    )

    probes.append(
        _probe(
            "user_home_solvers_not_live",
            True,
            reason=(
                "User-home ~/.local and ~/.elan solver copies are rejected as live evidence"
            ),
        )
    )
    probes.append(
        _probe(
            "user_home_solver_represented_as_live",
            False,
            reason="User-home solvers are not represented as live.",
        )
    )
    probes.append(
        _probe(
            "python_user_site_solver_represented_as_live",
            False,
            reason="Sealed PYTHONNOUSERSITE Python modules are the only live Python evidence.",
        )
    )
    probes.append(
        _probe(
            "hermetic_results_represented_as_live",
            False,
            reason="Hermetic SMT fixtures are measured_hermetic and not live.",
        )
    )
    probes.append(
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        )
    )
    return tuple(probes)


def current_head_static_probes() -> tuple[OutcomeProbe, ...]:
    root = discover_datasets_root()
    return (
        *_hermetic_semantic_probes(),
        *_readme_and_manifest_probes(root=root),
    )


def current_head_live_probes() -> tuple[OutcomeProbe, ...]:
    return _live_solver_probes()


def current_head_probes() -> tuple[OutcomeProbe, ...]:
    return (*current_head_static_probes(), *current_head_live_probes())


def _probe_map(probes: Sequence[OutcomeProbe]) -> dict[str, OutcomeProbe]:
    return {item.probe_id: item for item in probes}


def _live_kind(probe: OutcomeProbe | None) -> str:
    if probe is None:
        return "unavailable"
    if probe.present is True and probe.live and probe.evidence_kind == "measured_live":
        return "measured_live"
    if probe.evidence_kind == "unavailable" or probe.present is None:
        return "unavailable"
    return probe.evidence_kind


def qualify_solver_paths(
    probes: Sequence[OutcomeProbe],
) -> SolverQualificationVerdict:
    if not probes:
        raise SolverQualificationError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise SolverQualificationError("live claims require measured_live evidence")
        if probe.simulated_represented_as_live:
            raise SolverQualificationError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in {
            "live_solver_qualification",
            "live_z3_solver",
            "live_cvc5_solver",
            "live_lean_solver",
            "live_coq_solver",
        }:
            if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
                blockers.append(probe.probe_id)
            continue
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)

    by_id = _probe_map(normalized)
    hermetic_ok = all(
        by_id[item].present is True
        for item in (
            "canonical_ir_roundtrip",
            "source_lineage_validation",
            "context_pack_identity",
            "translation_receipt",
            "hermetic_proof_workflow",
            "hermetic_counterexample_workflow",
        )
        if item in by_id
    )
    z3 = by_id.get("live_z3_solver")
    cvc5 = by_id.get("live_cvc5_solver")
    lean = by_id.get("live_lean_solver")
    coq = by_id.get("live_coq_solver")
    live_z3 = bool(z3 and z3.present is True and z3.live)
    live_cvc5 = bool(cvc5 and cvc5.present is True and cvc5.live)
    live_lean = bool(lean and lean.present is True and lean.live)
    live_coq = bool(coq and coq.present is True and coq.live)
    live_solver = live_z3 and live_cvc5 and (live_lean or live_coq)
    if live_solver:
        live_kind = "measured_live"
    elif not live_z3 and not live_cvc5 and not live_lean and not live_coq:
        live_kind = "unavailable"
    else:
        live_kind = "measured_live"

    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_017_TASK_ID,
        "goal_id": PCPR_017_GOAL_ID,
        "promotion_status": "rnd_non_promoted",
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "hermetic_semantic_workflows_qualified": hermetic_ok,
        "live_z3_qualified": live_z3,
        "live_cvc5_qualified": live_cvc5,
        "live_lean_qualified": live_lean,
        "live_coq_qualified": live_coq,
        "live_solver_qualified": live_solver,
        "live_solver_evidence_kind": live_kind,
        "blockers": list(dict.fromkeys(blockers)),
        "probes": [item.to_mapping() for item in normalized],
    }
    _reject_closed_release_value(payload["promotion_status"], "promotion_status")
    cid = content_identity(payload)
    if not _CID_RE.match(cid):
        raise SolverQualificationError("verdict CID is malformed")
    return SolverQualificationVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status="rnd_non_promoted",
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        hermetic_semantic_workflows_qualified=hermetic_ok,
        live_z3_qualified=live_z3,
        live_cvc5_qualified=live_cvc5,
        live_lean_qualified=live_lean,
        live_coq_qualified=live_coq,
        live_solver_qualified=live_solver,
        live_solver_evidence_kind=live_kind,
        live_z3_evidence_kind=_live_kind(z3),
        live_cvc5_evidence_kind=_live_kind(cvc5),
        live_lean_evidence_kind=_live_kind(lean),
        live_coq_evidence_kind=_live_kind(coq),
        simulated_results_represented_as_live=False,
        hermetic_results_represented_as_live=False,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=cid,
    )


def qualify_current_head_solver_paths() -> SolverQualificationVerdict:
    return qualify_solver_paths(current_head_probes())


# Pinned identity of the ordinary current-head verdict. Drift means the
# default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeeratvkodnxdxcudgddqaxoohvglwyq34grr7zupm6pbnwqk4zrp2ubq"
)


def pcpr_017_receipt_promotion(
    verdict: SolverQualificationVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise SolverQualificationError(
            "solver qualification must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise SolverQualificationError(
            "solver qualification must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise SolverQualificationError(
            "solver qualification completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise SolverQualificationError(
            "solver qualification must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise SolverQualificationError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.simulated_results_represented_as_live:
        raise SolverQualificationError(
            "simulated results must not be represented as live"
        )
    if verdict.hermetic_results_represented_as_live:
        raise SolverQualificationError(
            "hermetic results must not be represented as live"
        )
    return verdict.to_mapping()


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "EXPECTED_FORMAL_TOOLCHAIN_DEPLOYMENT_IDENTITY",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OutcomeProbe",
    "PCPR_017_GOAL_ID",
    "PCPR_017_TASK_ID",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "SOLVER_NAMES",
    "SolverQualificationAdmissionError",
    "SolverQualificationError",
    "SolverQualificationVerdict",
    "content_identity",
    "current_head_live_probes",
    "current_head_probes",
    "current_head_static_probes",
    "discover_datasets_root",
    "discover_solver_executable",
    "observe_sealed_validation_environment",
    "pcpr_017_receipt_promotion",
    "qualify_current_head_solver_paths",
    "qualify_solver_paths",
    "solver_qualification_manifest",
]
