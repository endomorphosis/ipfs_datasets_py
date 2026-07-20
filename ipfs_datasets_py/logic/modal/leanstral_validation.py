"""Isolated projected-change validation for Leanstral LegalIR repairs.

Leanstral may propose compiler/decompiler patches, but acceptance is a local
gate: the diff is applied in a disposable git worktree and checked against the
owned change contract, focused commands, deterministic LegalIR invariants,
mutation cases, and frozen holdout Pareto metrics.  Every rejection reason is a
stable code with structured details so the TODO/rescue lane can turn failures
into narrow follow-up work.
"""

from __future__ import annotations

import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from ipfs_datasets_py.logic.hammers.process_lifecycle import (
    ProcessKind,
    ProcessLimits,
    get_process_supervisor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    build_us_code_sample,
    stable_mock_embedding,
)

from .codec import DeterministicModalLogicCodec, ModalLogicCodecConfig, modal_ir_to_flogic_triples
from .decompiler import decode_modal_ir_document
from .introspection_metrics import (
    IntrospectionMetricRecord,
    LeanstralCanaryManifest,
    load_leanstral_canary_manifest,
)
from .leanstral import (
    LegalIRLeanTask,
    PythonPatchProposal,
    PythonPatchValidation,
    validate_python_patch_proposal,
)
from .leanstral_theorems import generate_legal_semantics_theorem_registry


LEANSTRAL_PROJECTED_VALIDATION_SCHEMA_VERSION = "legal-ir-leanstral-projected-validation-v1"
LEANSTRAL_MUTATION_FIXTURE_SCHEMA_VERSION = "legal-ir-leanstral-mutations-v1"
DEFAULT_LEANSTRAL_MUTATION_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/logic/modal/leanstral_mutations.json"
)
DEFAULT_LEANSTRAL_HOLDOUT_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/logic/modal/leanstral_canary_manifest.json"
)

Command = Sequence[str] | str
HoldoutMetricEvaluator = Callable[
    [Path, LeanstralCanaryManifest],
    Sequence[IntrospectionMetricRecord | Mapping[str, Any]],
]


@dataclass(frozen=True)
class LeanstralValidationReason:
    """One stable machine-readable rejection or warning reason."""

    code: str
    check: str
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "code": self.code,
            "details": _jsonable(self.details),
            "message": self.message,
        }


@dataclass(frozen=True)
class LeanstralValidationCheck:
    """Result for one projected-change validation phase."""

    name: str
    accepted: bool
    reasons: Sequence[LeanstralValidationReason] = field(default_factory=tuple)
    details: Mapping[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "details": _jsonable(self.details),
            "elapsed_seconds": round(float(self.elapsed_seconds), 6),
            "name": self.name,
            "reasons": [reason.to_dict() for reason in self.reasons],
        }


@dataclass(frozen=True)
class LeanstralMetricComparison:
    """Pareto comparison for one frozen holdout metric."""

    case_id: str
    metric: str
    baseline: float
    candidate: float
    deadband: float
    direction: str
    accepted: bool
    reason_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "baseline": round(float(self.baseline), 12),
            "candidate": round(float(self.candidate), 12),
            "case_id": self.case_id,
            "deadband": round(float(self.deadband), 12),
            "direction": self.direction,
            "metric": self.metric,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class LeanstralProjectedValidationConfig:
    """Configuration for isolated projected-change validation."""

    repo_root: Optional[str] = None
    worktree_parent: Optional[str] = None
    mutation_fixture_path: Optional[str] = None
    holdout_manifest_path: Optional[str] = None
    validation_commands: Sequence[Command] = field(default_factory=tuple)
    command_timeout_seconds: float = 120.0
    codec_config: ModalLogicCodecConfig = field(default_factory=ModalLogicCodecConfig)
    cross_entropy_deadband: float = 0.0
    cosine_deadband: float = 0.0
    anti_copy_deadband: float = 0.0
    max_source_span_copy_ratio: float = 0.25
    require_focus_commands: bool = True
    run_syntax_check: bool = True
    run_deterministic_round_trip: bool = True
    run_theorem_check: bool = True
    run_graph_check: bool = True
    run_provenance_check: bool = True
    run_anti_copy_check: bool = True
    run_mutation_check: bool = True
    run_holdout_check: bool = True
    keep_worktree: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["codec_config"] = asdict(self.codec_config)
        payload["validation_commands"] = [
            command if isinstance(command, str) else list(command)
            for command in self.validation_commands
        ]
        return payload


@dataclass(frozen=True)
class LeanstralProjectedChangeValidation:
    """Full projected-change gate report."""

    accepted: bool
    schema_version: str = LEANSTRAL_PROJECTED_VALIDATION_SCHEMA_VERSION
    reasons: Sequence[str] = field(default_factory=tuple)
    reason_details: Sequence[LeanstralValidationReason] = field(default_factory=tuple)
    checks: Sequence[LeanstralValidationCheck] = field(default_factory=tuple)
    changed_paths: Sequence[str] = field(default_factory=tuple)
    patch_validation: Optional[PythonPatchValidation] = None
    worktree_path: str = ""
    disposable_worktree_removed: bool = False
    report_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = self._payload(include_report_id=False)
        payload["report_id"] = self.report_id or self.expected_report_id()
        return payload

    def _payload(self, *, include_report_id: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "accepted": self.accepted,
            "changed_paths": list(self.changed_paths),
            "checks": [check.to_dict() for check in self.checks],
            "disposable_worktree_removed": self.disposable_worktree_removed,
            "patch_validation": self.patch_validation.to_dict()
            if self.patch_validation
            else None,
            "reason_details": [reason.to_dict() for reason in self.reason_details],
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
            "worktree_path": self.worktree_path,
        }
        if include_report_id:
            payload["report_id"] = self.report_id
        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def expected_report_id(self) -> str:
        payload = self._payload(include_report_id=False)
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return f"leanstral-validation-{digest}"


class LeanstralProjectedChangeValidator:
    """Validate a Leanstral patch in an isolated, disposable worktree."""

    def __init__(
        self,
        config: Optional[LeanstralProjectedValidationConfig] = None,
        *,
        holdout_metric_evaluator: Optional[HoldoutMetricEvaluator] = None,
    ) -> None:
        self.config = config or LeanstralProjectedValidationConfig()
        self.holdout_metric_evaluator = holdout_metric_evaluator

    def validate(
        self,
        task: LegalIRLeanTask,
        patch: Optional[PythonPatchProposal | Any],
        *,
        samples: Sequence[LegalSample] = (),
        baseline_holdout_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]] = (),
        candidate_holdout_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]] = (),
        validation_commands: Optional[Sequence[Command]] = None,
    ) -> LeanstralProjectedChangeValidation:
        """Run the full projected-change gate and return an auditable report."""

        config = self.config
        repo_root = _repo_root(config.repo_root)
        patch = _extract_python_patch(patch)
        if patch is None:
            return _final_report(
                (
                    _single_reason_check(
                        "allowed_path",
                        "projected_patch_missing",
                        "Projected change validation requires a candidate Python diff.",
                    ),
                ),
                changed_paths=(),
                patch_validation=None,
                worktree_path="",
                disposable_worktree_removed=False,
            )
        patch_validation = validate_python_patch_proposal(
            task,
            patch,
            repo_root=str(repo_root),
        )
        checks: List[LeanstralValidationCheck] = [
            _check_from_python_patch_validation(patch_validation)
        ]
        if not patch_validation.accepted or patch is None:
            return _final_report(
                checks,
                changed_paths=patch_validation.changed_paths,
                patch_validation=patch_validation,
                worktree_path="",
                disposable_worktree_removed=False,
            )

        worktree_path = ""
        removed = False
        worktree_ref: Optional[_Worktree] = None
        try:
            with _isolated_worktree(repo_root, config) as worktree:
                worktree_ref = worktree
                worktree_path = str(worktree.path)
                checks.append(_apply_patch_check(worktree.path, patch.unified_diff))
                if checks[-1].accepted:
                    checks.extend(
                        self._worktree_checks(
                            task,
                            worktree.path,
                            changed_paths=patch_validation.changed_paths,
                            samples=samples,
                            validation_commands=validation_commands,
                            baseline_holdout_records=baseline_holdout_records,
                            candidate_holdout_records=candidate_holdout_records,
                        )
                    )
            removed = bool(worktree_ref.removed) if worktree_ref is not None else False
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            checks.append(
                _single_reason_check(
                    "isolated_worktree",
                    "worktree_validation_error",
                    f"{exc.__class__.__name__}: {exc}",
                    accepted=False,
                )
            )
        return _final_report(
            checks,
            changed_paths=patch_validation.changed_paths,
            patch_validation=patch_validation,
            worktree_path=worktree_path,
            disposable_worktree_removed=removed,
        )

    def _worktree_checks(
        self,
        task: LegalIRLeanTask,
        worktree: Path,
        *,
        changed_paths: Sequence[str],
        samples: Sequence[LegalSample],
        validation_commands: Optional[Sequence[Command]],
        baseline_holdout_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]],
        candidate_holdout_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]],
    ) -> Sequence[LeanstralValidationCheck]:
        checks: List[LeanstralValidationCheck] = []
        config = self.config
        if config.run_syntax_check:
            checks.append(_syntax_check(worktree, changed_paths))
        commands = tuple(validation_commands) if validation_commands is not None else tuple(config.validation_commands)
        checks.append(_focused_tests_check(worktree, commands, config))

        deterministic_samples = tuple(samples) or (_sample_from_task(task),)
        if config.run_deterministic_round_trip:
            checks.append(_deterministic_round_trip_check(deterministic_samples, config))
        if config.run_theorem_check:
            checks.append(_theorem_check(deterministic_samples))
        if config.run_graph_check:
            checks.append(_graph_check(deterministic_samples))
        if config.run_provenance_check:
            checks.append(_provenance_check(deterministic_samples))
        if config.run_anti_copy_check:
            checks.append(_anti_copy_check(deterministic_samples, config))
        if config.run_mutation_check:
            checks.append(_mutation_check(task, config))
        if config.run_holdout_check:
            checks.append(
                _holdout_check(
                    worktree,
                    config,
                    evaluator=self.holdout_metric_evaluator,
                    baseline_records=baseline_holdout_records,
                    candidate_records=candidate_holdout_records,
                )
            )
        return tuple(checks)


def validate_leanstral_projected_change(
    task: LegalIRLeanTask,
    patch: Optional[PythonPatchProposal | Any],
    *,
    config: Optional[LeanstralProjectedValidationConfig] = None,
    samples: Sequence[LegalSample] = (),
    baseline_holdout_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]] = (),
    candidate_holdout_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]] = (),
    validation_commands: Optional[Sequence[Command]] = None,
    holdout_metric_evaluator: Optional[HoldoutMetricEvaluator] = None,
) -> LeanstralProjectedChangeValidation:
    """Convenience wrapper for the projected-change validator."""

    return LeanstralProjectedChangeValidator(
        config,
        holdout_metric_evaluator=holdout_metric_evaluator,
    ).validate(
        task,
        patch,
        samples=samples,
        baseline_holdout_records=baseline_holdout_records,
        candidate_holdout_records=candidate_holdout_records,
        validation_commands=validation_commands,
    )


def compare_leanstral_holdout_pareto(
    baseline_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]],
    candidate_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]],
    *,
    cross_entropy_deadband: float = 0.0,
    cosine_deadband: float = 0.0,
    anti_copy_deadband: float = 0.0,
) -> Sequence[LeanstralMetricComparison]:
    """Compare candidate holdout metrics against frozen baselines."""

    baseline_by_case = {
        record.case_id: record
        for record in (_coerce_metric_record(item) for item in baseline_records)
    }
    candidate_by_case = {
        record.case_id: record
        for record in (_coerce_metric_record(item) for item in candidate_records)
    }
    comparisons: List[LeanstralMetricComparison] = []
    for case_id, baseline in sorted(baseline_by_case.items()):
        candidate = candidate_by_case.get(case_id)
        if candidate is None:
            comparisons.append(
                LeanstralMetricComparison(
                    case_id=case_id,
                    metric="record",
                    baseline=1.0,
                    candidate=0.0,
                    deadband=0.0,
                    direction="present",
                    accepted=False,
                    reason_code="holdout_candidate_case_missing",
                )
            )
            continue
        comparisons.extend(
            _record_metric_comparisons(
                baseline,
                candidate,
                cross_entropy_deadband=float(cross_entropy_deadband),
                cosine_deadband=float(cosine_deadband),
                anti_copy_deadband=float(anti_copy_deadband),
            )
        )
    for case_id in sorted(set(candidate_by_case) - set(baseline_by_case)):
        comparisons.append(
            LeanstralMetricComparison(
                case_id=case_id,
                metric="record",
                baseline=0.0,
                candidate=1.0,
                deadband=0.0,
                direction="no_extra_cases",
                accepted=False,
                reason_code="holdout_unexpected_candidate_case",
            )
        )
    return tuple(comparisons)


@dataclass
class _Worktree:
    path: Path
    repo_root: Path
    kind: str
    keep: bool = False
    removed: bool = False

    def __enter__(self) -> "_Worktree":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.keep:
            self.removed = False
            return
        if self.kind == "git-worktree":
            process = subprocess.run(
                ["git", "-C", str(self.repo_root), "worktree", "remove", "--force", str(self.path)],
                capture_output=True,
                check=False,
                text=True,
                timeout=30.0,
            )
            self.removed = process.returncode == 0 and not self.path.exists()
            if not self.removed and self.path.exists():
                shutil.rmtree(self.path, ignore_errors=True)
                self.removed = not self.path.exists()
            subprocess.run(
                ["git", "-C", str(self.repo_root), "worktree", "prune"],
                capture_output=True,
                check=False,
                text=True,
                timeout=30.0,
            )
            return
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        self.removed = not self.path.exists()


def _isolated_worktree(
    repo_root: Path,
    config: LeanstralProjectedValidationConfig,
) -> _Worktree:
    parent = Path(config.worktree_parent).expanduser() if config.worktree_parent else None
    if parent:
        parent.mkdir(parents=True, exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="leanstral-projected-", dir=str(parent)))
        path.rmdir()
    else:
        path = Path(tempfile.mkdtemp(prefix="leanstral-projected-"))
        path.rmdir()

    process = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "--detach", "--quiet", str(path), "HEAD"],
        capture_output=True,
        check=False,
        text=True,
        timeout=60.0,
    )
    if process.returncode == 0:
        return _Worktree(path=path, repo_root=repo_root, kind="git-worktree", keep=config.keep_worktree)

    shutil.copytree(
        repo_root,
        path,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
    )
    subprocess.run(["git", "init", "-q", str(path)], capture_output=True, check=False, text=True, timeout=30.0)
    return _Worktree(path=path, repo_root=repo_root, kind="copytree", keep=config.keep_worktree)


def _apply_patch_check(worktree: Path, diff: str) -> LeanstralValidationCheck:
    start = time.monotonic()
    try:
        process = subprocess.run(
            ["git", "-C", str(worktree), "apply", "--whitespace=error", "-"],
            input=diff,
            capture_output=True,
            check=False,
            text=True,
            timeout=30.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _single_reason_check(
            "apply_patch",
            f"projected_patch_apply_error:{exc.__class__.__name__}",
            "Git failed while applying the projected diff in the disposable worktree.",
            elapsed=time.monotonic() - start,
        )
    output = ((process.stdout or "") + (process.stderr or "")).strip()
    if process.returncode != 0:
        return _single_reason_check(
            "apply_patch",
            "projected_patch_apply_failed",
            "The projected diff did not apply cleanly in the disposable worktree.",
            details={"git_output": output},
            elapsed=time.monotonic() - start,
        )
    return LeanstralValidationCheck(
        name="apply_patch",
        accepted=True,
        details={"git_output": output},
        elapsed_seconds=time.monotonic() - start,
    )


def _syntax_check(worktree: Path, changed_paths: Sequence[str]) -> LeanstralValidationCheck:
    start = time.monotonic()
    reasons: List[LeanstralValidationReason] = []
    compiled: List[str] = []
    for path in changed_paths:
        if not path.endswith(".py"):
            continue
        target = worktree / path
        if not target.is_file():
            reasons.append(
                LeanstralValidationReason(
                    code="syntax_path_missing",
                    check="syntax",
                    message="Changed Python path is missing after applying the projected diff.",
                    details={"path": path},
                )
            )
            continue
        try:
            py_compile.compile(str(target), doraise=True)
            compiled.append(path)
        except py_compile.PyCompileError as exc:
            reasons.append(
                LeanstralValidationReason(
                    code="python_syntax_error",
                    check="syntax",
                    message="Changed Python path does not compile.",
                    details={"path": path, "error": str(exc)},
                )
            )
    return LeanstralValidationCheck(
        name="syntax",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={"compiled_paths": compiled},
        elapsed_seconds=time.monotonic() - start,
    )


def _focused_tests_check(
    worktree: Path,
    commands: Sequence[Command],
    config: LeanstralProjectedValidationConfig,
) -> LeanstralValidationCheck:
    start = time.monotonic()
    if not commands:
        accepted = not config.require_focus_commands
        reasons = ()
        if not accepted:
            reasons = (
                LeanstralValidationReason(
                    code="focused_tests_missing",
                    check="focused_tests",
                    message="Projected change validation requires explicit focused test commands.",
                ),
            )
        return LeanstralValidationCheck(
            name="focused_tests",
            accepted=accepted,
            reasons=reasons,
            details={"commands": []},
            elapsed_seconds=time.monotonic() - start,
        )
    command_results: List[Dict[str, Any]] = []
    reasons: List[LeanstralValidationReason] = []
    for command in commands:
        result = _run_command(worktree, command, timeout_seconds=config.command_timeout_seconds)
        command_results.append(result)
        if int(result["returncode"]) != 0:
            reasons.append(
                LeanstralValidationReason(
                    code="focused_test_command_failed",
                    check="focused_tests",
                    message="A focused validation command failed in the disposable worktree.",
                    details={
                        "command": result["command"],
                        "returncode": result["returncode"],
                        "output": result["output"][-4000:],
                    },
                )
            )
    return LeanstralValidationCheck(
        name="focused_tests",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={"commands": command_results},
        elapsed_seconds=time.monotonic() - start,
    )


def _deterministic_round_trip_check(
    samples: Sequence[LegalSample],
    config: LeanstralProjectedValidationConfig,
) -> LeanstralValidationCheck:
    start = time.monotonic()
    codec = DeterministicModalLogicCodec(config.codec_config)
    reasons: List[LeanstralValidationReason] = []
    results: List[Dict[str, Any]] = []
    for sample in samples:
        first = codec.encode(
            sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        )
        second = codec.encode(
            sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        )
        first_hash = first.modal_ir.canonical_hash()
        second_hash = second.modal_ir.canonical_hash()
        decoded = decode_modal_ir_document(first.modal_ir)
        recompiled = codec.encode(
            decoded.text or sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        )
        recompiled_hash = recompiled.modal_ir.canonical_hash()
        accepted = first_hash == second_hash and bool(decoded.text.strip())
        if not accepted:
            reasons.append(
                LeanstralValidationReason(
                    code="deterministic_round_trip_failed",
                    check="deterministic_round_trip",
                    message="LegalIR encode/decode contract is not deterministic for a validation sample.",
                    details={
                        "case_id": sample.sample_id,
                        "first_hash": first_hash,
                        "second_hash": second_hash,
                        "decoded_empty": not bool(decoded.text.strip()),
                    },
                )
            )
        results.append(
            {
                "case_id": sample.sample_id,
                "decoded_sha256": hashlib.sha256(decoded.text.encode("utf-8")).hexdigest(),
                "first_hash": first_hash,
                "recompiled_hash": recompiled_hash,
                "second_hash": second_hash,
            }
        )
    return LeanstralValidationCheck(
        name="deterministic_round_trip",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={"samples": results},
        elapsed_seconds=time.monotonic() - start,
    )


def _theorem_check(samples: Sequence[LegalSample]) -> LeanstralValidationCheck:
    start = time.monotonic()
    reasons: List[LeanstralValidationReason] = []
    registries: List[Dict[str, Any]] = []
    for sample in samples:
        registry = generate_legal_semantics_theorem_registry(sample)
        theorem_ids = registry.theorem_ids()
        if not theorem_ids:
            reasons.append(
                LeanstralValidationReason(
                    code="theorem_registry_empty",
                    check="theorem",
                    message="Verifier-owned theorem registry is empty for a validation sample.",
                    details={"case_id": sample.sample_id},
                )
            )
        if len(set(theorem_ids)) != len(theorem_ids):
            reasons.append(
                LeanstralValidationReason(
                    code="theorem_registry_duplicate_ids",
                    check="theorem",
                    message="Verifier-owned theorem registry emitted duplicate theorem ids.",
                    details={"case_id": sample.sample_id},
                )
            )
        registries.append(
            {
                "case_id": sample.sample_id,
                "registry_hash": registry.registry_hash,
                "theorem_count": registry.theorem_count,
            }
        )
    return LeanstralValidationCheck(
        name="theorem",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={"registries": registries},
        elapsed_seconds=time.monotonic() - start,
    )


def _graph_check(samples: Sequence[LegalSample]) -> LeanstralValidationCheck:
    start = time.monotonic()
    reasons: List[LeanstralValidationReason] = []
    graphs: List[Dict[str, Any]] = []
    for sample in samples:
        triples = modal_ir_to_flogic_triples(sample.modal_ir, selected_frame=sample.selected_frame)
        dangling = [
            triple
            for triple in triples
            if not str(triple.get("subject", "")).strip()
            or not str(triple.get("predicate", "")).strip()
            or not str(triple.get("object", "")).strip()
        ]
        if dangling:
            reasons.append(
                LeanstralValidationReason(
                    code="graph_dangling_endpoint",
                    check="graph",
                    message="F-logic graph projection contains a blank subject, predicate, or object.",
                    details={"case_id": sample.sample_id, "dangling_count": len(dangling)},
                )
            )
        graphs.append(
            {
                "case_id": sample.sample_id,
                "graph_hash": _hash_json(_canonical_triples(triples)),
                "triple_count": len(triples),
            }
        )
    return LeanstralValidationCheck(
        name="graph",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={"graphs": graphs},
        elapsed_seconds=time.monotonic() - start,
    )


def _provenance_check(samples: Sequence[LegalSample]) -> LeanstralValidationCheck:
    start = time.monotonic()
    reasons: List[LeanstralValidationReason] = []
    spans: List[Dict[str, Any]] = []
    for sample in samples:
        text = sample.normalized_text or sample.text
        for formula in sample.modal_ir.formulas:
            start_char = int(formula.provenance.start_char)
            end_char = int(formula.provenance.end_char)
            span = text[max(0, start_char) : max(0, end_char)].strip()
            if start_char < 0 or end_char <= start_char or end_char > len(text) or not span:
                reasons.append(
                    LeanstralValidationReason(
                        code="source_provenance_invalid",
                        check="provenance",
                        message="Modal formula provenance does not identify a non-empty source span.",
                        details={
                            "case_id": sample.sample_id,
                            "end_char": end_char,
                            "formula_id": formula.formula_id,
                            "start_char": start_char,
                            "text_length": len(text),
                        },
                    )
                )
            spans.append(
                {
                    "case_id": sample.sample_id,
                    "end_char": end_char,
                    "formula_id": formula.formula_id,
                    "source_span_hash": hashlib.sha256(span.encode("utf-8")).hexdigest(),
                    "start_char": start_char,
                }
            )
    return LeanstralValidationCheck(
        name="provenance",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={"source_spans": spans},
        elapsed_seconds=time.monotonic() - start,
    )


def _anti_copy_check(
    samples: Sequence[LegalSample],
    config: LeanstralProjectedValidationConfig,
) -> LeanstralValidationCheck:
    start = time.monotonic()
    codec = DeterministicModalLogicCodec(config.codec_config)
    reasons: List[LeanstralValidationReason] = []
    metrics: List[Dict[str, Any]] = []
    for sample in samples:
        result = codec.encode(
            sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        )
        ratio = float(result.losses.get("source_span_copy_ratio", 0.0))
        penalty = float(
            result.losses.get(
                "source_copy_reward_hack_penalty",
                result.losses.get("anti_copy_penalty", 0.0),
            )
        )
        if ratio > float(config.max_source_span_copy_ratio):
            reasons.append(
                LeanstralValidationReason(
                    code="anti_copy_ratio_exceeded",
                    check="anti_copy",
                    message="Decompiler output copies too much raw source span text.",
                    details={
                        "case_id": sample.sample_id,
                        "max_source_span_copy_ratio": config.max_source_span_copy_ratio,
                        "source_span_copy_ratio": ratio,
                    },
                )
            )
        metrics.append(
            {
                "anti_copy_penalty": round(penalty, 12),
                "case_id": sample.sample_id,
                "source_span_copy_ratio": round(ratio, 12),
            }
        )
    return LeanstralValidationCheck(
        name="anti_copy",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={"metrics": metrics},
        elapsed_seconds=time.monotonic() - start,
    )


def _mutation_check(
    task: LegalIRLeanTask,
    config: LeanstralProjectedValidationConfig,
) -> LeanstralValidationCheck:
    start = time.monotonic()
    path = Path(config.mutation_fixture_path).expanduser() if config.mutation_fixture_path else DEFAULT_LEANSTRAL_MUTATION_FIXTURE
    reasons: List[LeanstralValidationReason] = []
    try:
        fixture = _load_mutation_fixture(path)
    except (OSError, ValueError, TypeError) as exc:
        return _single_reason_check(
            "mutation",
            "mutation_fixture_invalid",
            "Mutation fixture could not be loaded or validated.",
            details={"error": str(exc), "path": str(path)},
            elapsed=time.monotonic() - start,
        )
    required = tuple(str(value) for value in (task.compiler_change_spec or {}).get("mutation_cases", ()))
    by_id = {str(item["mutation_id"]): item for item in fixture}
    missing = [mutation_id for mutation_id in required if mutation_id not in by_id]
    if missing:
        reasons.append(
            LeanstralValidationReason(
                code="required_mutation_case_missing",
                check="mutation",
                message="Change contract references mutation cases missing from the fixture.",
                details={"missing_mutation_cases": missing},
            )
        )
    selected = [by_id[mutation_id] for mutation_id in required if mutation_id in by_id]
    if not selected:
        selected = list(fixture)
    codec = DeterministicModalLogicCodec(config.codec_config)
    results: List[Dict[str, Any]] = []
    for mutation in selected:
        result = _run_mutation_case(codec, mutation)
        results.append(result)
        if not result["accepted"]:
            reasons.append(
                LeanstralValidationReason(
                    code=str(result["reason_code"]),
                    check="mutation",
                    message="Mutation case was not detected by deterministic LegalIR invariants.",
                    details=result,
                )
            )
    return LeanstralValidationCheck(
        name="mutation",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={"fixture_path": str(path), "mutations": results},
        elapsed_seconds=time.monotonic() - start,
    )


def _holdout_check(
    worktree: Path,
    config: LeanstralProjectedValidationConfig,
    *,
    evaluator: Optional[HoldoutMetricEvaluator],
    baseline_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]],
    candidate_records: Sequence[IntrospectionMetricRecord | Mapping[str, Any]],
) -> LeanstralValidationCheck:
    start = time.monotonic()
    path = Path(config.holdout_manifest_path).expanduser() if config.holdout_manifest_path else DEFAULT_LEANSTRAL_HOLDOUT_MANIFEST
    reasons: List[LeanstralValidationReason] = []
    try:
        manifest = load_leanstral_canary_manifest(path)
    except (OSError, ValueError, TypeError) as exc:
        return _single_reason_check(
            "frozen_holdout",
            "holdout_manifest_invalid",
            "Frozen holdout canary manifest could not be loaded or validated.",
            details={"error": str(exc), "path": str(path)},
            elapsed=time.monotonic() - start,
        )
    baseline = tuple(baseline_records) if baseline_records else tuple(manifest.cases)
    candidate: Sequence[IntrospectionMetricRecord | Mapping[str, Any]]
    if candidate_records:
        candidate = tuple(candidate_records)
    elif evaluator is not None:
        try:
            candidate = tuple(evaluator(worktree, manifest))
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            return _single_reason_check(
                "frozen_holdout",
                f"holdout_metric_evaluator_error:{exc.__class__.__name__}",
                "Holdout metric evaluator failed for the projected worktree.",
                details={"error": str(exc)},
                elapsed=time.monotonic() - start,
            )
    else:
        candidate = tuple(manifest.cases)

    comparisons = compare_leanstral_holdout_pareto(
        baseline,
        candidate,
        cross_entropy_deadband=config.cross_entropy_deadband,
        cosine_deadband=config.cosine_deadband,
        anti_copy_deadband=config.anti_copy_deadband,
    )
    failed = [comparison for comparison in comparisons if not comparison.accepted]
    for comparison in failed:
        reasons.append(
            LeanstralValidationReason(
                code=comparison.reason_code or "holdout_pareto_regression",
                check="frozen_holdout",
                message="Candidate holdout metric regressed beyond its explicit deadband.",
                details=comparison.to_dict(),
            )
        )
    return LeanstralValidationCheck(
        name="frozen_holdout",
        accepted=not reasons,
        reasons=tuple(reasons),
        details={
            "comparison_count": len(comparisons),
            "comparisons": [comparison.to_dict() for comparison in comparisons],
            "cross_entropy_deadband": config.cross_entropy_deadband,
            "cosine_deadband": config.cosine_deadband,
            "manifest_path": str(path),
        },
        elapsed_seconds=time.monotonic() - start,
    )


def _record_metric_comparisons(
    baseline: IntrospectionMetricRecord,
    candidate: IntrospectionMetricRecord,
    *,
    cross_entropy_deadband: float,
    cosine_deadband: float,
    anti_copy_deadband: float,
) -> Sequence[LeanstralMetricComparison]:
    comparisons: List[LeanstralMetricComparison] = []
    lower_better = (
        ("compiler_ir.cross_entropy_loss", baseline.compiler_ir.cross_entropy_loss, candidate.compiler_ir.cross_entropy_loss, cross_entropy_deadband, "holdout_cross_entropy_regression"),
        ("compiler_ir.cross_entropy_excess_loss", baseline.compiler_ir.cross_entropy_excess_loss, candidate.compiler_ir.cross_entropy_excess_loss, cross_entropy_deadband, "holdout_cross_entropy_regression"),
        ("compiler_ir.cosine_loss", baseline.compiler_ir.cosine_loss, candidate.compiler_ir.cosine_loss, cosine_deadband, "holdout_cosine_regression"),
        ("source_to_decoded.embedding_cosine_loss", baseline.source_to_decoded.embedding_cosine_loss, candidate.source_to_decoded.embedding_cosine_loss, cosine_deadband, "holdout_cosine_regression"),
        ("source_to_decoded.token_loss", baseline.source_to_decoded.token_loss, candidate.source_to_decoded.token_loss, cross_entropy_deadband, "holdout_token_regression"),
        ("anti_copy.source_copy_loss", baseline.anti_copy.source_copy_loss, candidate.anti_copy.source_copy_loss, anti_copy_deadband, "holdout_anti_copy_regression"),
        ("anti_copy.source_span_copy_ratio", baseline.anti_copy.source_span_copy_ratio, candidate.anti_copy.source_span_copy_ratio, anti_copy_deadband, "holdout_anti_copy_regression"),
        ("anti_copy.anti_copy_penalty", baseline.anti_copy.anti_copy_penalty, candidate.anti_copy.anti_copy_penalty, anti_copy_deadband, "holdout_anti_copy_regression"),
        ("validity.failure_ratio", baseline.validity.failure_ratio, candidate.validity.failure_ratio, cross_entropy_deadband, "holdout_validity_regression"),
    )
    for metric, base, cand, deadband, reason_code in lower_better:
        accepted = float(cand) <= float(base) + float(deadband)
        comparisons.append(
            LeanstralMetricComparison(
                case_id=baseline.case_id,
                metric=metric,
                baseline=float(base),
                candidate=float(cand),
                deadband=float(deadband),
                direction="lower_or_equal",
                accepted=accepted,
                reason_code="" if accepted else reason_code,
            )
        )
    higher_better = (
        ("compiler_ir.cosine_similarity", baseline.compiler_ir.cosine_similarity, candidate.compiler_ir.cosine_similarity, cosine_deadband, "holdout_cosine_regression"),
        ("source_to_decoded.embedding_cosine_similarity", baseline.source_to_decoded.embedding_cosine_similarity, candidate.source_to_decoded.embedding_cosine_similarity, cosine_deadband, "holdout_cosine_regression"),
        ("source_to_decoded.token_similarity", baseline.source_to_decoded.token_similarity, candidate.source_to_decoded.token_similarity, cosine_deadband, "holdout_token_regression"),
    )
    for metric, base, cand, deadband, reason_code in higher_better:
        accepted = float(cand) + float(deadband) >= float(base)
        comparisons.append(
            LeanstralMetricComparison(
                case_id=baseline.case_id,
                metric=metric,
                baseline=float(base),
                candidate=float(cand),
                deadband=float(deadband),
                direction="higher_or_equal",
                accepted=accepted,
                reason_code="" if accepted else reason_code,
            )
        )
    bools = (
        ("validity.structural_valid", baseline.validity.structural_valid, candidate.validity.structural_valid),
        ("validity.modal_ir_valid", baseline.validity.modal_ir_valid, candidate.validity.modal_ir_valid),
        ("validity.prover_compiles", baseline.validity.prover_compiles, candidate.validity.prover_compiles),
        ("validity.proofs_valid", baseline.validity.proofs_valid, candidate.validity.proofs_valid),
    )
    for metric, base, cand in bools:
        accepted = (not bool(base)) or bool(cand)
        comparisons.append(
            LeanstralMetricComparison(
                case_id=baseline.case_id,
                metric=metric,
                baseline=1.0 if bool(base) else 0.0,
                candidate=1.0 if bool(cand) else 0.0,
                deadband=0.0,
                direction="preserve_true",
                accepted=accepted,
                reason_code="" if accepted else "holdout_validity_regression",
            )
        )
    for family, base_metric in baseline.learned_ir_view_by_family.items():
        cand_metric = candidate.learned_ir_view_by_family.get(family)
        if cand_metric is None:
            comparisons.append(
                LeanstralMetricComparison(
                    case_id=baseline.case_id,
                    metric=f"learned_ir_view_by_family.{family}",
                    baseline=1.0,
                    candidate=0.0,
                    deadband=0.0,
                    direction="present",
                    accepted=False,
                    reason_code="holdout_family_metric_missing",
                )
            )
            continue
        comparisons.extend(
            (
                _lower_metric(
                    baseline.case_id,
                    f"learned_ir_view_by_family.{family}.cross_entropy_loss",
                    base_metric.cross_entropy_loss,
                    cand_metric.cross_entropy_loss,
                    cross_entropy_deadband,
                    "holdout_cross_entropy_regression",
                ),
                _lower_metric(
                    baseline.case_id,
                    f"learned_ir_view_by_family.{family}.cross_entropy_excess_loss",
                    base_metric.cross_entropy_excess_loss,
                    cand_metric.cross_entropy_excess_loss,
                    cross_entropy_deadband,
                    "holdout_cross_entropy_regression",
                ),
                _lower_metric(
                    baseline.case_id,
                    f"learned_ir_view_by_family.{family}.cosine_loss",
                    base_metric.cosine_loss,
                    cand_metric.cosine_loss,
                    cosine_deadband,
                    "holdout_cosine_regression",
                ),
                _higher_metric(
                    baseline.case_id,
                    f"learned_ir_view_by_family.{family}.cosine_similarity",
                    base_metric.cosine_similarity,
                    cand_metric.cosine_similarity,
                    cosine_deadband,
                    "holdout_cosine_regression",
                ),
            )
        )
    return tuple(comparisons)


def _lower_metric(
    case_id: str,
    metric: str,
    baseline: float,
    candidate: float,
    deadband: float,
    reason_code: str,
) -> LeanstralMetricComparison:
    accepted = float(candidate) <= float(baseline) + float(deadband)
    return LeanstralMetricComparison(
        case_id=case_id,
        metric=metric,
        baseline=float(baseline),
        candidate=float(candidate),
        deadband=float(deadband),
        direction="lower_or_equal",
        accepted=accepted,
        reason_code="" if accepted else reason_code,
    )


def _higher_metric(
    case_id: str,
    metric: str,
    baseline: float,
    candidate: float,
    deadband: float,
    reason_code: str,
) -> LeanstralMetricComparison:
    accepted = float(candidate) + float(deadband) >= float(baseline)
    return LeanstralMetricComparison(
        case_id=case_id,
        metric=metric,
        baseline=float(baseline),
        candidate=float(candidate),
        deadband=float(deadband),
        direction="higher_or_equal",
        accepted=accepted,
        reason_code="" if accepted else reason_code,
    )


def _run_command(worktree: Path, command: Command, *, timeout_seconds: float) -> Dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    argv = ["bash", "-lc", command] if isinstance(command, str) else list(command)
    process = get_process_supervisor().run(
        argv,
        cwd=str(worktree),
        env=env,
        kind=ProcessKind.TRANSLATOR,
        limits=ProcessLimits(
            wall_time_seconds=max(1.0, float(timeout_seconds))
        ),
    )
    output = ((process.stdout or "") + (process.stderr or "")).strip()
    if process.timed_out:
        return {
            "command": command if isinstance(command, str) else list(command),
            "output": output,
            "returncode": 124,
        }
    if process.error:
        return {
            "command": command if isinstance(command, str) else list(command),
            "output": process.error,
            "returncode": 127,
        }
    return {
        "command": command if isinstance(command, str) else list(command),
        "output": output,
        "returncode": int(process.returncode or 0),
    }


def _run_mutation_case(
    codec: DeterministicModalLogicCodec,
    mutation: Mapping[str, Any],
) -> Dict[str, Any]:
    mutation_id = str(mutation["mutation_id"])
    original_text = str(mutation["original_text"])
    mutated_text = str(mutation["mutated_text"])
    original = codec.encode(
        original_text,
        document_id=f"{mutation_id}-original",
        citation=str(mutation.get("citation") or "5 U.S.C. 552"),
        source="us_code",
        source_embedding=stable_mock_embedding(original_text),
    )
    mutated = codec.encode(
        mutated_text,
        document_id=f"{mutation_id}-mutated",
        citation=str(mutation.get("citation") or "5 U.S.C. 552"),
        source="us_code",
        source_embedding=stable_mock_embedding(mutated_text),
    )
    original_hash = original.modal_ir.canonical_hash()
    mutated_hash = mutated.modal_ir.canonical_hash()
    original_families = _families(original.modal_ir.formulas)
    mutated_families = _families(mutated.modal_ir.formulas)
    expected_hash_change = bool(mutation.get("expected_hash_change", True))
    expected_family_change = bool(mutation.get("expected_family_change", False))
    hash_changed = original_hash != mutated_hash
    family_changed = original_families != mutated_families
    accepted = (hash_changed or not expected_hash_change) and (
        family_changed or not expected_family_change
    )
    reason_code = ""
    if expected_hash_change and not hash_changed:
        reason_code = "mutation_hash_not_detected"
    elif expected_family_change and not family_changed:
        reason_code = "mutation_family_not_detected"
    return {
        "accepted": accepted,
        "expected_family_change": expected_family_change,
        "expected_hash_change": expected_hash_change,
        "family_changed": family_changed,
        "hash_changed": hash_changed,
        "mutated_families": list(mutated_families),
        "mutated_hash": mutated_hash,
        "mutation_id": mutation_id,
        "original_families": list(original_families),
        "original_hash": original_hash,
        "reason_code": reason_code,
    }


def _load_mutation_fixture(path: Path) -> Sequence[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("mutation fixture root must be an object")
    if payload.get("schema_version") != LEANSTRAL_MUTATION_FIXTURE_SCHEMA_VERSION:
        raise ValueError("unsupported mutation fixture schema_version")
    mutations = payload.get("mutations")
    if not isinstance(mutations, Sequence) or isinstance(mutations, (str, bytes)):
        raise ValueError("mutations must be an array")
    normalized: List[Mapping[str, Any]] = []
    seen: set[str] = set()
    for item in mutations:
        if not isinstance(item, Mapping):
            raise ValueError("mutation entries must be objects")
        mutation_id = str(item.get("mutation_id") or "").strip()
        if not mutation_id:
            raise ValueError("mutation_id must not be empty")
        if mutation_id in seen:
            raise ValueError(f"duplicate mutation_id: {mutation_id}")
        if not str(item.get("original_text") or "").strip():
            raise ValueError(f"mutation {mutation_id} missing original_text")
        if not str(item.get("mutated_text") or "").strip():
            raise ValueError(f"mutation {mutation_id} missing mutated_text")
        seen.add(mutation_id)
        normalized.append(dict(item))
    return tuple(normalized)


def _sample_from_task(task: LegalIRLeanTask) -> LegalSample:
    text = task.source_span or str((task.modal_formula.get("predicate") or {}).get("text") or "")
    if not text.strip():
        text = "The agency must provide notice."
    return build_us_code_sample(
        title="5",
        section="552",
        text=text,
        citation="5 U.S.C. 552",
    )


def _extract_python_patch(candidate: Optional[Any]) -> Optional[PythonPatchProposal]:
    if candidate is None:
        return None
    if isinstance(candidate, PythonPatchProposal):
        return candidate
    nested = getattr(candidate, "python_patch", None)
    if nested is None and isinstance(candidate, Mapping):
        nested = candidate.get("python_patch")
    if isinstance(nested, PythonPatchProposal):
        return nested
    if isinstance(nested, Mapping):
        return PythonPatchProposal.from_mapping(nested)
    if isinstance(candidate, Mapping) and "unified_diff" in candidate:
        return PythonPatchProposal.from_mapping(candidate)
    return candidate


def _check_from_python_patch_validation(
    validation: PythonPatchValidation,
) -> LeanstralValidationCheck:
    reasons = tuple(
        LeanstralValidationReason(
            code=reason,
            check="allowed_path",
            message="Projected Python patch failed admission before worktree validation.",
            details={"changed_paths": list(validation.changed_paths), "git_output": validation.git_output},
        )
        for reason in validation.reasons
        if reason != "not_requested" or validation.requested
    )
    return LeanstralValidationCheck(
        name="allowed_path",
        accepted=validation.accepted,
        reasons=reasons,
        details=validation.to_dict(),
    )


def _final_report(
    checks: Sequence[LeanstralValidationCheck],
    *,
    changed_paths: Sequence[str],
    patch_validation: Optional[PythonPatchValidation],
    worktree_path: str,
    disposable_worktree_removed: bool,
) -> LeanstralProjectedChangeValidation:
    reason_details: List[LeanstralValidationReason] = []
    for check in checks:
        reason_details.extend(check.reasons)
    reasons = tuple(dict.fromkeys(reason.code for reason in reason_details))
    accepted = all(check.accepted for check in checks)
    result = LeanstralProjectedChangeValidation(
        accepted=accepted,
        reasons=reasons,
        reason_details=tuple(reason_details),
        checks=tuple(checks),
        changed_paths=tuple(changed_paths),
        patch_validation=patch_validation,
        worktree_path=worktree_path,
        disposable_worktree_removed=disposable_worktree_removed,
    )
    return LeanstralProjectedChangeValidation(
        accepted=result.accepted,
        reasons=result.reasons,
        reason_details=result.reason_details,
        checks=result.checks,
        changed_paths=result.changed_paths,
        patch_validation=result.patch_validation,
        worktree_path=result.worktree_path,
        disposable_worktree_removed=result.disposable_worktree_removed,
        report_id=result.expected_report_id(),
    )


def _single_reason_check(
    name: str,
    code: str,
    message: str,
    *,
    accepted: bool = False,
    details: Optional[Mapping[str, Any]] = None,
    elapsed: float = 0.0,
) -> LeanstralValidationCheck:
    return LeanstralValidationCheck(
        name=name,
        accepted=accepted,
        reasons=(
            LeanstralValidationReason(
                code=code,
                check=name,
                message=message,
                details=details or {},
            ),
        )
        if not accepted
        else (),
        details=details or {},
        elapsed_seconds=elapsed,
    )


def _repo_root(value: Optional[str]) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _coerce_metric_record(
    record: IntrospectionMetricRecord | Mapping[str, Any],
) -> IntrospectionMetricRecord:
    if isinstance(record, IntrospectionMetricRecord):
        return record
    return IntrospectionMetricRecord.from_mapping(record)


def _families(formulas: Iterable[Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(getattr(getattr(formula, "operator", None), "family", ""))
                for formula in formulas
                if str(getattr(getattr(formula, "operator", None), "family", "")).strip()
            }
        )
    )


def _canonical_triples(triples: Iterable[Mapping[str, Any]]) -> Sequence[Mapping[str, str]]:
    return tuple(
        sorted(
            (
                {
                    "object": str(triple.get("object", "")),
                    "predicate": str(triple.get("predicate", "")),
                    "subject": str(triple.get("subject", "")),
                }
                for triple in triples
            ),
            key=lambda item: (item["subject"], item["predicate"], item["object"]),
        )
    )


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "DEFAULT_LEANSTRAL_HOLDOUT_MANIFEST",
    "DEFAULT_LEANSTRAL_MUTATION_FIXTURE",
    "LEANSTRAL_MUTATION_FIXTURE_SCHEMA_VERSION",
    "LEANSTRAL_PROJECTED_VALIDATION_SCHEMA_VERSION",
    "LeanstralMetricComparison",
    "LeanstralProjectedChangeValidation",
    "LeanstralProjectedChangeValidator",
    "LeanstralProjectedValidationConfig",
    "LeanstralValidationCheck",
    "LeanstralValidationReason",
    "compare_leanstral_holdout_pareto",
    "validate_leanstral_projected_change",
]
