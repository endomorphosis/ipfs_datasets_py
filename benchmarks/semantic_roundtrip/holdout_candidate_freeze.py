"""PLAT2-055 freeze: candidate selection, attribution evidence, holdout authorization.

Interfaces:
* ``Plateau2CandidateFreeze@1`` — immutable zero-or-one candidate freeze with
  per-wave and cumulative attribution on pilot + repair-development only
* ``SemanticRoundtripHoldoutAuthorization@1`` — sole issuer of blind-access
  authorization (binds seal + freeze; forbids post-access retuning)

Acceptance (PLAT2-G055 / PLAT2-055):

* Replay each isolated edit wave and the cumulative candidate on identical
  repair-development and pilot cases **without** blind data.
* Report per-wave marginal and cumulative deltas, interactions, first-pass /
  eventual repair success, accepted-patch regressions, structural-gate
  coverage, context tokens, provider calls, and cost.
* Select **zero or one** candidate under frozen PLAT2-025 rules.
* Bind baseline and candidate commits / recursive gitlinks, compiler/realizer
  code, configs, metrics, aggregation/bootstrap/noninferiority rules,
  intervention registry, packets, prompts, provider/model/toolchain
  identities, environment, tests, population/seal CIDs, and all thresholds.
* Emit authorization **only** when the blind seal has zero prior access, pilot
  and required gates pass, evidence is complete, and a candidate is frozen.
* Any subsequent code/config/prompt/threshold/population change invalidates the
  authorization and requires a **new experiment identity** plus a **fresh**
  blind holdout rather than retuning against this one.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.contracts import ContractError
from benchmarks.semantic_roundtrip.holdout_baseline import (
    AGGREGATION_ORDER,
    BOOTSTRAP_METHOD,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    DEFAULT_BASELINE_REPORT_RELATIVE_PATH,
    EXPERIMENT_FAMILY,
    FAILURE_LOSS,
    NONINFERIORITY_MARGIN,
    PACKET_TOKEN_BUDGET,
    PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE,
    POST_PLAT_BASELINE_E2E_MEAN,
    POST_PLAT_BASELINE_REPORT_CID,
    PRIMARY_PROMOTION_METRIC,
    PRODUCTION_ARM_ID,
    PRODUCTION_CONSTRUCTOR_IDENTITY,
    PRODUCTION_REALIZER_IDENTITY,
    SELECTION_GATE_IDS,
    assert_blind_seal_unopened,
    bootstrap_definition,
    capture_environment_toolchain,
    capture_git_tree_binding,
    load_repair_dev_baseline_report,
    metric_facet_definitions,
    noninferiority_and_promotion_rules,
    packet_token_budget_definition,
    score_deterministic_case,
)
from benchmarks.semantic_roundtrip.holdout_protocol import (
    AUTHORIZATION_GOAL_ID,
    BLIND_SEAL_RELATIVE_PATH,
    HoldoutAccessAuthorization,
    POPULATION_KIND_PILOT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    load_frozen_blind_holdout_seal,
    load_pilot_manifest,
    load_repair_development_manifest,
)
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
from benchmarks.semantic_roundtrip.residual_catalog import (
    DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH,
    PILOT_CASE_IDS,
    PILOT_CASES_RELATIVE_PATH,
    REPAIR_DEV_CASES_RELATIVE_PATH,
    load_repair_dev_residual_catalog,
)


# ---------------------------------------------------------------------------
# Interfaces / schemas / task identity
# ---------------------------------------------------------------------------

PLATEAU2_CANDIDATE_FREEZE_INTERFACE: Final = "Plateau2CandidateFreeze@1"
PLATEAU2_CANDIDATE_FREEZE_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau2-candidate-freeze.v1"
)
SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_INTERFACE: Final = (
    "SemanticRoundtripHoldoutAuthorization@1"
)
SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau2-holdout-authorization.v1"
)

FREEZE_CID_SCOPE: Final = "payload_without_freeze_cid"
AUTHORIZATION_ARTIFACT_CID_SCOPE: Final = "payload_without_authorization_artifact_cid"
CID_CODEC: Final = "dag-json"

FREEZE_TASK_ID: Final = "PLAT2-055"
FREEZE_GOAL_ID: Final = "PLAT2-G055"
FREEZE_EVIDENCE_ID: Final = "PLAT2EV055FREEZE"
FREEZE_REVISION: Final = 1

DEFAULT_FREEZE_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "plateau2_candidate_freeze.json"
)
DEFAULT_AUTHORIZATION_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "plateau2_holdout_authorization.json"
)
DEFAULT_FREEZE_DOCS_RELATIVE_PATH: Final = Path(
    "docs/benchmarks/semantic_roundtrip_plateau2_candidate_freeze.md"
)
DEFAULT_EDIT_WAVE_RECEIPT_DIR: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "repair_dev_edit_wave_receipts"
)
DEFAULT_EDIT_WAVE_MANIFEST_RELATIVE_PATH: Final = (
    DEFAULT_EDIT_WAVE_RECEIPT_DIR / "manifest.json"
)
DEFAULT_INTERVENTION_REGISTRY_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "repair_dev_intervention_registry.json"
)
DEFAULT_PACKET_METRICS_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "repair_dev_packet_context_metrics.json"
)

# Frozen selection thresholds (bound from PLAT2-025; not retunable post-auth).
PILOT_E2E_TOLERANCE: Final = 1e-9
LOSS_COMPARISON_TOLERANCE: Final = 1e-9

DEFAULT_FREEZE_ASSUMPTIONS: Final = (
    "production remains typed_deontic → IR → deterministic realizer",
    "attribution and candidate selection use pilot + repair-development only",
    "blind holdout sources/gold/residuals never enter freeze evidence",
    "zero or one candidate is selected under frozen PLAT2-025 rules",
    "authorization requires complete evidence, pilot non-regression, "
    "required gates, and zero prior blind access",
    "post-authorization code/config/prompt/threshold/population change "
    "invalidates authorization and requires a new experiment identity plus a "
    "fresh blind holdout",
    "Hammer/cvc5/Lean have semantic_authority false",
    "optional spaCy/AE/Leanstral/SyMAI are non-authoritative teachers only",
    "structural gate coverage is reported separately from semantic e2e loss",
    "paired case-cluster bootstrap and noninferiority margin remain as in "
    "PLAT2-025 and are not reopened here",
)

# Paths whose mutation invalidates a freeze/authorization after emission.
INVALIDATING_CHANGE_CLASSES: Final = (
    "compiler_or_realizer_code",
    "production_arm_or_config",
    "metrics_or_facets",
    "aggregation_or_bootstrap",
    "noninferiority_margin_or_thresholds",
    "selection_or_promotion_rules",
    "intervention_registry",
    "packets_or_prompts",
    "provider_model_or_toolchain_identity",
    "environment",
    "tests_that_define_acceptance",
    "population_or_seal_cid",
    "candidate_source_tree",
)


class HoldoutCandidateFreezeError(ContractError):
    """Raised when candidate freeze or authorization fails validation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require(condition: object, message: str) -> None:
    if not condition:
        raise HoldoutCandidateFreezeError(message)


def _nonblank(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HoldoutCandidateFreezeError(f"{path} must be a nonblank string")
    return value.strip()


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HoldoutCandidateFreezeError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise HoldoutCandidateFreezeError(f"{path} must be an array")
    return value


def _finite_number(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise HoldoutCandidateFreezeError(f"{path} must be a finite number")
    return float(value)


def _finite_unit(value: object, path: str) -> float:
    number = _finite_number(value, path)
    if not 0.0 <= number <= 1.0:
        raise HoldoutCandidateFreezeError(
            f"{path} must be a finite number from zero to one"
        )
    return number


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k): _plain_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _cid(value: object, path: str) -> str:
    text = _nonblank(value, path)
    try:
        return validate_cid(text, codecs=(CID_CODEC,))
    except (TypeError, ValueError) as exc:
        raise HoldoutCandidateFreezeError(
            f"{path} must be a canonical dag-json CID"
        ) from exc


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".json",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


# ---------------------------------------------------------------------------
# Edit-wave receipt loading
# ---------------------------------------------------------------------------


def load_edit_wave_manifest(
    path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, object]:
    """Load the PLAT2-050 repair-development edit-wave receipt manifest."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    manifest_path = (
        Path(path)
        if path is not None
        else root / DEFAULT_EDIT_WAVE_MANIFEST_RELATIVE_PATH
    )
    _require(manifest_path.is_file(), f"missing edit-wave manifest: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = dict(_mapping(data, "edit-wave manifest"))
    _require(
        manifest.get("interface") == "PlateauEditWaveReceiptSet@1",
        "edit-wave manifest interface mismatch",
    )
    _require(
        manifest.get("population_kind") == POPULATION_KIND_REPAIR_DEVELOPMENT,
        "edit-wave manifest must target repair_development",
    )
    _require(
        manifest.get("blind_data_accessed") is False,
        "edit-wave manifest must not access blind data",
    )
    _require(
        list(manifest.get("optional_runtimes_promoted") or []) == [],
        "edit-wave manifest must not promote optional runtimes",
    )
    _cid(manifest.get("manifest_cid"), "manifest_cid")
    _cid(manifest.get("residual_catalog_cid"), "residual_catalog_cid")
    _cid(manifest.get("intervention_registry_cid"), "intervention_registry_cid")
    _cid(manifest.get("tree_cid"), "tree_cid")
    case_ids = _array(manifest.get("case_ids"), "case_ids")
    _require(case_ids, "edit-wave manifest case_ids must be non-empty")
    receipt_paths = _array(manifest.get("receipt_paths"), "receipt_paths")
    _require(
        len(receipt_paths) == len(case_ids),
        "receipt_paths length must match case_ids",
    )
    return manifest


def load_edit_wave_receipts(
    *,
    repo_root: str | Path | None = None,
    manifest: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], ...]:
    """Load and lightly validate every terminal PLAT2-050 edit-wave receipt."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    man = dict(manifest) if manifest is not None else load_edit_wave_manifest(repo_root=root)
    compositions = root / "workspace/benchmarks/semantic-roundtrip-compositions"
    receipts: list[dict[str, object]] = []
    for rel in _array(man.get("receipt_paths"), "receipt_paths"):
        rel_text = _nonblank(rel, "receipt_paths[]")
        path = compositions / rel_text
        if not path.is_file():
            # Allow absolute or repo-relative paths.
            candidate = root / rel_text
            path = candidate if candidate.is_file() else path
        _require(path.is_file(), f"missing edit-wave receipt: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        receipt = dict(_mapping(payload, f"receipt {path.name}"))
        _require(
            receipt.get("interface") == "PlateauEditWaveReceipt@1",
            f"{path.name}: interface mismatch",
        )
        _require(
            receipt.get("population_kind") == POPULATION_KIND_REPAIR_DEVELOPMENT,
            f"{path.name}: population_kind must be repair_development",
        )
        _require(
            receipt.get("edit_wave_task_id") == "PLAT2-050",
            f"{path.name}: edit_wave_task_id must be PLAT2-050",
        )
        doctrine = _mapping(receipt.get("doctrine"), f"{path.name}.doctrine")
        _require(
            doctrine.get("blind_data_accessed") is False,
            f"{path.name}: blind data must not be accessed",
        )
        _require(
            list(receipt.get("optional_runtimes_promoted") or []) == [],
            f"{path.name}: optional runtimes must not be promoted",
        )
        _require(
            receipt.get("implementable") is True,
            f"{path.name}: receipt must be terminal implementable",
        )
        _cid(receipt.get("receipt_cid"), f"{path.name}.receipt_cid")
        _nonblank(receipt.get("case_id"), f"{path.name}.case_id")
        _mapping(receipt.get("prior_scores"), f"{path.name}.prior_scores")
        _mapping(receipt.get("post_scores"), f"{path.name}.post_scores")
        _mapping(receipt.get("context_tokens"), f"{path.name}.context_tokens")
        _mapping(receipt.get("provider_calls"), f"{path.name}.provider_calls")
        _mapping(receipt.get("structural_receipts"), f"{path.name}.structural_receipts")
        receipts.append(receipt)

    expected_ids = {
        _nonblank(case_id, "manifest.case_ids[]")
        for case_id in _array(man.get("case_ids"), "case_ids")
    }
    actual_ids = {
        _nonblank(item.get("case_id"), "receipt.case_id") for item in receipts
    }
    _require(
        expected_ids == actual_ids,
        f"edit-wave receipt case set mismatch: expected {sorted(expected_ids)}, "
        f"got {sorted(actual_ids)}",
    )
    # Stable order: manifest order.
    by_id = {
        _nonblank(item.get("case_id"), "receipt.case_id"): item for item in receipts
    }
    ordered = tuple(by_id[case_id] for case_id in man["case_ids"])  # type: ignore[index]
    return ordered


# ---------------------------------------------------------------------------
# Isolated-wave attribution (from receipts; no blind data)
# ---------------------------------------------------------------------------


def _case_loss_from_scores(
    scores: Mapping[str, object],
    *,
    case_id: str,
    metric: str,
) -> float | None:
    key = f"{case_id}_{metric}_loss"
    if key in scores:
        return _finite_number(scores[key], key)
    # Fallback generic keys used by some receipts.
    generic = f"repair_dev_case_{metric}_loss"
    if generic in scores:
        return _finite_number(scores[generic], generic)
    return None


def _pilot_mean_from_scores(scores: Mapping[str, object]) -> float | None:
    if "mean_pilot_forward_loss" in scores:
        return _finite_number(
            scores["mean_pilot_forward_loss"], "mean_pilot_forward_loss"
        )
    pilot = scores.get("pilot_forward_losses")
    if isinstance(pilot, Mapping) and pilot:
        values = [
            _finite_number(value, f"pilot_forward_losses.{key}")
            for key, value in pilot.items()
        ]
        return _mean(values)
    return None


def replay_isolated_edit_wave(
    receipt: Mapping[str, object],
) -> dict[str, object]:
    """Attribute one isolated edit wave from its sealed terminal receipt.

    Isolated waves are reconstructed from PLAT2-050 receipts (prior → post on
    the targeted repair-development case plus pilot non-regression notes).
    Blind cases are never loaded.
    """

    case_id = _nonblank(receipt.get("case_id"), "receipt.case_id")
    prior = _mapping(receipt.get("prior_scores"), "prior_scores")
    post = _mapping(receipt.get("post_scores"), "post_scores")
    prior_forward = _case_loss_from_scores(prior, case_id=case_id, metric="forward")
    post_forward = _case_loss_from_scores(post, case_id=case_id, metric="forward")
    prior_e2e = _case_loss_from_scores(prior, case_id=case_id, metric="end_to_end")
    post_e2e = _case_loss_from_scores(post, case_id=case_id, metric="end_to_end")
    _require(
        prior_forward is not None and post_forward is not None,
        f"{case_id}: prior/post forward loss required for isolated replay",
    )
    assert prior_forward is not None and post_forward is not None
    if prior_e2e is None:
        prior_e2e = prior_forward
    if post_e2e is None:
        post_e2e = post_forward

    forward_delta = float(post_forward) - float(prior_forward)
    e2e_delta = float(post_e2e) - float(prior_e2e)
    first_pass_cleared = bool(post_forward == 0.0)
    eventual_cleared = first_pass_cleared  # single-shot waves are terminal

    improvement = _mapping(receipt.get("improvement"), "improvement")
    cleared_flag = improvement.get(f"{case_id}_cleared")
    if cleared_flag is not None:
        eventual_cleared = bool(cleared_flag) and first_pass_cleared

    pilot_prior = _pilot_mean_from_scores(prior)
    pilot_post = _pilot_mean_from_scores(post)
    pilot_delta = None
    if pilot_prior is not None and pilot_post is not None:
        pilot_delta = float(pilot_post) - float(pilot_prior)

    context = _mapping(receipt.get("context_tokens"), "context_tokens")
    provider = _mapping(receipt.get("provider_calls"), "provider_calls")
    structural = _mapping(receipt.get("structural_receipts"), "structural_receipts")
    constraints = list(
        receipt.get("structural_constraints_preserved")
        or structural.get("constraints_preserved")
        or []
    )

    # Cost is not metered for residual-only det waves; record explicit zero.
    leanstral_calls = int(provider.get("leanstral_calls") or 0)
    symai_calls = int(provider.get("symai_calls") or 0)
    llm_calls = int(provider.get("llm_runtime_calls") or 0)
    optional_calls = int(provider.get("optional_teacher_calls") or 0)
    total_provider_calls = leanstral_calls + symai_calls + llm_calls + optional_calls
    cost = {
        "currency": "USD",
        "metered": False,
        "provider_call_cost": 0.0,
        "total_cost": 0.0,
        "note": (
            "residual-only deterministic edit wave; no paid provider inference"
        ),
    }

    accepted_patch_regression = False
    if pilot_delta is not None and pilot_delta > LOSS_COMPARISON_TOLERANCE:
        accepted_patch_regression = True
    if float(post_forward) > float(prior_forward) + LOSS_COMPARISON_TOLERANCE:
        # Targeted case worsened after accepted patch.
        accepted_patch_regression = True

    return {
        "ablation_kind": "isolated_edit_wave",
        "accepted_patch_regression": accepted_patch_regression,
        "case_id": case_id,
        "context_tokens": {
            "budget_exceeded": bool(context.get("budget_exceeded")),
            "counting_method": context.get("counting_method"),
            "packet_token_budget": context.get("packet_token_budget"),
            "packet_token_count": context.get("packet_token_count"),
        },
        "cost": cost,
        "deterministic_hypothesis": receipt.get("deterministic_hypothesis"),
        "eventual_repair_success": eventual_cleared,
        "first_pass_repair_success": first_pass_cleared,
        "intervention_ids": list(receipt.get("intervention_ids") or []),
        "marginal_deltas": {
            "end_to_end": e2e_delta,
            "forward": forward_delta,
            "mean_pilot_forward": pilot_delta,
        },
        "packet_cids": list(receipt.get("packet_cids") or []),
        "packet_ids": list(receipt.get("packet_ids") or []),
        "populations_in_scope": [
            POPULATION_KIND_PILOT,
            POPULATION_KIND_REPAIR_DEVELOPMENT,
        ],
        "post_losses": {
            "end_to_end": float(post_e2e),
            "forward": float(post_forward),
        },
        "prior_losses": {
            "end_to_end": float(prior_e2e),
            "forward": float(prior_forward),
        },
        "provider_calls": {
            "leanstral_calls": leanstral_calls,
            "llm_runtime_calls": llm_calls,
            "optional_teacher_calls": optional_calls,
            "symai_calls": symai_calls,
            "total_provider_calls": total_provider_calls,
        },
        "receipt_cid": receipt.get("receipt_cid"),
        "residual_cluster": receipt.get("residual_cluster"),
        "residual_field_paths": list(receipt.get("residual_field_paths") or []),
        "structural_gate_coverage": {
            "constraints_preserved": constraints,
            "coverage_count": len(constraints),
            "may_substitute_for_e2e": bool(
                structural.get("may_substitute_for_e2e") is True
            ),
            "semantic_authority": bool(structural.get("semantic_authority") is True),
            "status": structural.get("status"),
        },
        "wave_id": f"plat2-050:{case_id}",
    }


def replay_all_isolated_edit_waves(
    receipts: Sequence[Mapping[str, object]] | None = None,
    *,
    repo_root: str | Path | None = None,
) -> list[dict[str, object]]:
    """Replay every isolated edit wave for attribution."""

    waves = (
        list(receipts)
        if receipts is not None
        else list(load_edit_wave_receipts(repo_root=repo_root))
    )
    return [replay_isolated_edit_wave(receipt) for receipt in waves]


# ---------------------------------------------------------------------------
# Cumulative candidate scoring (live production path; no blind)
# ---------------------------------------------------------------------------


def _baseline_case_index(
    baseline_report: Mapping[str, object],
    population_kind: str,
) -> dict[str, dict[str, object]]:
    populations = _mapping(baseline_report.get("populations"), "populations")
    block = _mapping(populations.get(population_kind), f"populations.{population_kind}")
    cases = _array(block.get("cases"), f"populations.{population_kind}.cases")
    index: dict[str, dict[str, object]] = {}
    for item in cases:
        case = dict(_mapping(item, "baseline case"))
        case_id = _nonblank(case.get("case_id"), "case_id")
        index[case_id] = case
    return index


def score_population_block(
    population_kind: str,
    *,
    repo_root: str | Path | None = None,
    case_records: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Score one visible population on the current production candidate arm."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    if case_records is None:
        if population_kind == POPULATION_KIND_PILOT:
            path = root / PILOT_CASES_RELATIVE_PATH
            cases = load_matrix_cases(path)
            by_id = {case.case_id: case for case in cases}
            ordered = []
            for case_id in PILOT_CASE_IDS:
                _require(case_id in by_id, f"missing pilot case {case_id!r}")
                ordered.append(by_id[case_id])
            case_records = [score_deterministic_case(case) for case in ordered]
        elif population_kind == POPULATION_KIND_REPAIR_DEVELOPMENT:
            path = root / REPAIR_DEV_CASES_RELATIVE_PATH
            cases = load_matrix_cases(path)
            case_records = [score_deterministic_case(case) for case in cases]
        else:
            raise HoldoutCandidateFreezeError(
                f"freeze scoring rejects population_kind {population_kind!r}; "
                "blind data is forbidden"
            )
    else:
        _require(
            population_kind
            in {POPULATION_KIND_PILOT, POPULATION_KIND_REPAIR_DEVELOPMENT},
            f"freeze scoring rejects population_kind {population_kind!r}",
        )

    records = [dict(_mapping(item, "case record")) for item in case_records]
    for record in records:
        _nonblank(record.get("case_id"), "case_id")
        losses = _mapping(record.get("losses"), "losses")
        for metric in ("forward", "cycle", "end_to_end"):
            _finite_unit(losses.get(metric), f"losses.{metric}")
        gates = _mapping(record.get("gates"), "gates")
        for gate in (
            "full_coverage",
            "source_copy_exclusion",
            "polarity_preservation",
            "selection_eligible",
        ):
            _require(isinstance(gates.get(gate), bool), f"gate {gate} must be bool")

    scored = [
        record
        for record in records
        if record.get("evaluation_status") == "semantic_scored"
        or record.get("semantic_score_eligible") is True
    ]
    means = {
        metric: _mean(
            [
                float(_mapping(item.get("losses"), "losses")[metric])  # type: ignore[arg-type]
                for item in scored
            ]
        )
        if scored
        else FAILURE_LOSS
        for metric in ("forward", "cycle", "end_to_end")
    }
    gate_pass_counts = {
        gate: sum(
            1
            for item in records
            if bool(_mapping(item.get("gates"), "gates").get(gate))
        )
        for gate in (
            "full_coverage",
            "source_copy_exclusion",
            "polarity_preservation",
            "selection_eligible",
        )
    }
    return {
        "aggregates": {
            "aggregation_order": AGGREGATION_ORDER,
            "case_count": len(records),
            "gate_pass_counts": gate_pass_counts,
            "means": means,
            "semantic_scored_count": len(scored),
        },
        "cases": records,
        "population_kind": population_kind,
    }


def score_cumulative_candidate(
    *,
    repo_root: str | Path | None = None,
    population_results: Mapping[str, Mapping[str, object]] | None = None,
    run_scoring: bool = True,
) -> dict[str, object]:
    """Score the cumulative candidate on pilot + repair-development only."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    if population_results is not None:
        pilot = dict(
            _mapping(
                population_results.get(POPULATION_KIND_PILOT),
                "population_results.pilot",
            )
        )
        repair = dict(
            _mapping(
                population_results.get(POPULATION_KIND_REPAIR_DEVELOPMENT),
                "population_results.repair_development",
            )
        )
    else:
        if not run_scoring:
            raise HoldoutCandidateFreezeError(
                "population_results required when run_scoring is False"
            )
        pilot = score_population_block(POPULATION_KIND_PILOT, repo_root=root)
        repair = score_population_block(
            POPULATION_KIND_REPAIR_DEVELOPMENT, repo_root=root
        )

    return {
        POPULATION_KIND_PILOT: pilot,
        POPULATION_KIND_REPAIR_DEVELOPMENT: repair,
        "arm_id": PRODUCTION_ARM_ID,
        "blind_data_used": False,
        "populations_in_scope": [
            POPULATION_KIND_PILOT,
            POPULATION_KIND_REPAIR_DEVELOPMENT,
        ],
    }


# ---------------------------------------------------------------------------
# Attribution aggregation + selection
# ---------------------------------------------------------------------------


def _per_case_loss_map(
    block: Mapping[str, object],
    metric: str = "end_to_end",
) -> dict[str, float]:
    cases = _array(block.get("cases"), "cases")
    out: dict[str, float] = {}
    for item in cases:
        case = _mapping(item, "case")
        case_id = _nonblank(case.get("case_id"), "case_id")
        losses = _mapping(case.get("losses"), "losses")
        out[case_id] = _finite_unit(losses.get(metric), f"{case_id}.{metric}")
    return out


def compute_attribution_evidence(
    *,
    isolated_waves: Sequence[Mapping[str, object]],
    cumulative: Mapping[str, object],
    baseline_report: Mapping[str, object],
) -> dict[str, object]:
    """Aggregate per-wave marginals, cumulative deltas, and interactions."""

    pilot_block = _mapping(
        cumulative.get(POPULATION_KIND_PILOT), "cumulative.pilot"
    )
    repair_block = _mapping(
        cumulative.get(POPULATION_KIND_REPAIR_DEVELOPMENT),
        "cumulative.repair_development",
    )
    baseline_pilot = _baseline_case_index(baseline_report, POPULATION_KIND_PILOT)
    baseline_repair = _baseline_case_index(
        baseline_report, POPULATION_KIND_REPAIR_DEVELOPMENT
    )

    cum_pilot_e2e = _per_case_loss_map(pilot_block, "end_to_end")
    cum_repair_e2e = _per_case_loss_map(repair_block, "end_to_end")
    cum_repair_forward = _per_case_loss_map(repair_block, "forward")

    base_pilot_e2e = {
        case_id: _finite_unit(
            _mapping(row.get("losses"), "losses").get("end_to_end"),
            f"baseline pilot {case_id} e2e",
        )
        for case_id, row in baseline_pilot.items()
    }
    base_repair_e2e = {
        case_id: _finite_unit(
            _mapping(row.get("losses"), "losses").get("end_to_end"),
            f"baseline repair {case_id} e2e",
        )
        for case_id, row in baseline_repair.items()
    }
    base_repair_forward = {
        case_id: _finite_unit(
            _mapping(row.get("losses"), "losses").get("forward"),
            f"baseline repair {case_id} forward",
        )
        for case_id, row in baseline_repair.items()
    }

    pilot_deltas = {
        case_id: cum_pilot_e2e[case_id] - base_pilot_e2e[case_id]
        for case_id in sorted(set(cum_pilot_e2e) & set(base_pilot_e2e))
    }
    repair_e2e_deltas = {
        case_id: cum_repair_e2e[case_id] - base_repair_e2e[case_id]
        for case_id in sorted(set(cum_repair_e2e) & set(base_repair_e2e))
    }
    repair_forward_deltas = {
        case_id: cum_repair_forward[case_id] - base_repair_forward[case_id]
        for case_id in sorted(set(cum_repair_forward) & set(base_repair_forward))
    }

    # Interactions: for each wave-targeted case, cumulative_delta - isolated_marginal.
    interactions: list[dict[str, object]] = []
    sum_isolated_forward = 0.0
    for wave in isolated_waves:
        case_id = _nonblank(wave.get("case_id"), "wave.case_id")
        marginal = _mapping(wave.get("marginal_deltas"), "marginal_deltas")
        isolated_forward = _finite_number(marginal.get("forward"), "marginal.forward")
        sum_isolated_forward += isolated_forward
        cumulative_forward = repair_forward_deltas.get(case_id)
        if cumulative_forward is None:
            interactions.append(
                {
                    "case_id": case_id,
                    "interaction_forward": None,
                    "note": "case absent from cumulative repair-development scores",
                }
            )
            continue
        interactions.append(
            {
                "case_id": case_id,
                "cumulative_forward_delta": cumulative_forward,
                "interaction_forward": float(cumulative_forward) - float(isolated_forward),
                "isolated_forward_delta": isolated_forward,
                "note": (
                    "near-zero interaction expected for non-overlapping "
                    "per-case waves on a shared deterministic hotspot"
                ),
            }
        )

    first_pass = sum(
        1 for wave in isolated_waves if wave.get("first_pass_repair_success") is True
    )
    eventual = sum(
        1 for wave in isolated_waves if wave.get("eventual_repair_success") is True
    )
    regressions = [
        _nonblank(wave.get("case_id"), "wave.case_id")
        for wave in isolated_waves
        if wave.get("accepted_patch_regression") is True
    ]
    pilot_regressions = [
        case_id
        for case_id, delta in pilot_deltas.items()
        if delta > LOSS_COMPARISON_TOLERANCE
    ]

    total_tokens = 0
    total_provider_calls = 0
    total_cost = 0.0
    structural_constraint_union: set[str] = set()
    for wave in isolated_waves:
        ctx = _mapping(wave.get("context_tokens"), "context_tokens")
        count = ctx.get("packet_token_count")
        if isinstance(count, (int, float)):
            total_tokens += int(count)
        calls = _mapping(wave.get("provider_calls"), "provider_calls")
        total_provider_calls += int(calls.get("total_provider_calls") or 0)
        cost = _mapping(wave.get("cost"), "cost")
        total_cost += float(cost.get("total_cost") or 0.0)
        coverage = _mapping(
            wave.get("structural_gate_coverage"), "structural_gate_coverage"
        )
        for name in coverage.get("constraints_preserved") or []:
            structural_constraint_union.add(str(name))

    pilot_mean_e2e = float(
        _mapping(pilot_block.get("aggregates"), "aggregates")
        .get("means", {})
        .get("end_to_end", FAILURE_LOSS)  # type: ignore[union-attr]
    )
    repair_mean_e2e = float(
        _mapping(repair_block.get("aggregates"), "aggregates")
        .get("means", {})
        .get("end_to_end", FAILURE_LOSS)  # type: ignore[union-attr]
    )
    base_pilot_mean = _mean(list(base_pilot_e2e.values())) if base_pilot_e2e else 0.0
    base_repair_mean = (
        _mean(list(base_repair_e2e.values())) if base_repair_e2e else 0.0
    )

    return {
        "accepted_patch_regressions": {
            "pilot_case_ids": pilot_regressions,
            "wave_case_ids": regressions,
            "has_regression": bool(pilot_regressions or regressions),
        },
        "blind_data_used": False,
        "context_tokens": {
            "counting_method": "whitespace_split_proxy_v1",
            "packet_token_budget": PACKET_TOKEN_BUDGET,
            "sum_packet_token_count": total_tokens,
            "wave_count": len(isolated_waves),
        },
        "cost": {
            "currency": "USD",
            "metered": False,
            "total_cost": total_cost,
        },
        "cumulative_deltas": {
            "mean_pilot_end_to_end": pilot_mean_e2e - base_pilot_mean,
            "mean_repair_development_end_to_end": repair_mean_e2e - base_repair_mean,
            "per_case_pilot_end_to_end": pilot_deltas,
            "per_case_repair_development_end_to_end": repair_e2e_deltas,
            "per_case_repair_development_forward": repair_forward_deltas,
        },
        "cumulative_means": {
            "baseline_pilot_end_to_end": base_pilot_mean,
            "baseline_repair_development_end_to_end": base_repair_mean,
            "candidate_pilot_end_to_end": pilot_mean_e2e,
            "candidate_repair_development_end_to_end": repair_mean_e2e,
        },
        "interactions": interactions,
        "isolated_waves": list(isolated_waves),
        "provider_calls": {
            "sum_total_provider_calls": total_provider_calls,
            "wave_count": len(isolated_waves),
        },
        "repair_success": {
            "eventual_success_count": eventual,
            "first_pass_success_count": first_pass,
            "wave_count": len(isolated_waves),
        },
        "structural_gate_coverage": {
            "constraint_union": sorted(structural_constraint_union),
            "constraint_union_count": len(structural_constraint_union),
            "may_substitute_for_e2e": False,
            "semantic_authority": False,
        },
        "sum_isolated_forward_delta": sum_isolated_forward,
    }


def evaluate_selection_gates(
    *,
    attribution: Mapping[str, object],
    cumulative: Mapping[str, object],
    baseline_report: Mapping[str, object],
    receipts: Sequence[Mapping[str, object]],
    blind_status: Mapping[str, object],
) -> dict[str, object]:
    """Apply frozen PLAT2-025 selection rules; return zero-or-one decision."""

    pilot_block = _mapping(cumulative.get(POPULATION_KIND_PILOT), "pilot")
    repair_block = _mapping(
        cumulative.get(POPULATION_KIND_REPAIR_DEVELOPMENT), "repair_development"
    )
    pilot_mean = float(
        _mapping(pilot_block.get("aggregates"), "aggregates")
        .get("means", {})
        .get("end_to_end", 1.0)  # type: ignore[union-attr]
    )
    pilot_non_regressed = abs(pilot_mean - POST_PLAT_BASELINE_E2E_MEAN) <= PILOT_E2E_TOLERANCE

    base_pilot = _baseline_case_index(baseline_report, POPULATION_KIND_PILOT)
    cum_pilot_cases = {
        _nonblank(_mapping(item, "case").get("case_id"), "case_id"): dict(
            _mapping(item, "case")
        )
        for item in _array(pilot_block.get("cases"), "pilot.cases")
    }

    # No new pilot e2e regressions vs baseline; no new gate failures.
    pilot_e2e_regressions: list[str] = []
    new_gate_failures: list[dict[str, object]] = []
    for case_id, base_row in base_pilot.items():
        cand = cum_pilot_cases.get(case_id)
        if cand is None:
            pilot_e2e_regressions.append(case_id)
            continue
        base_e2e = _finite_unit(
            _mapping(base_row.get("losses"), "losses").get("end_to_end"),
            f"base {case_id} e2e",
        )
        cand_e2e = _finite_unit(
            _mapping(cand.get("losses"), "losses").get("end_to_end"),
            f"cand {case_id} e2e",
        )
        if cand_e2e > base_e2e + LOSS_COMPARISON_TOLERANCE:
            pilot_e2e_regressions.append(case_id)
        base_gates = _mapping(base_row.get("gates"), "base gates")
        cand_gates = _mapping(cand.get("gates"), "cand gates")
        for gate in SELECTION_GATE_IDS:
            if base_gates.get(gate) is True and cand_gates.get(gate) is not True:
                new_gate_failures.append(
                    {"case_id": case_id, "gate": gate, "kind": "new_failure"}
                )

    # Evidence completeness: every nonzero residual case has a terminal receipt.
    catalog_case_ids = {
        _nonblank(receipt.get("case_id"), "receipt.case_id") for receipt in receipts
    }
    all_terminal = all(receipt.get("implementable") is True for receipt in receipts)
    no_optional_promoted = all(
        list(receipt.get("optional_runtimes_promoted") or []) == []
        for receipt in receipts
    )
    no_blind_in_receipts = all(
        _mapping(receipt.get("doctrine"), "doctrine").get("blind_data_accessed")
        is False
        for receipt in receipts
    )
    production_unchanged = all(
        receipt.get("production_composition") == PRODUCTION_ARM_ID
        or receipt.get("baseline_arm_id") == PRODUCTION_ARM_ID
        for receipt in receipts
    )

    regressions = _mapping(
        attribution.get("accepted_patch_regressions"), "accepted_patch_regressions"
    )
    has_patch_regression = regressions.get("has_regression") is True

    repair_means = _mapping(
        _mapping(repair_block.get("aggregates"), "aggregates").get("means"),
        "repair means",
    )
    repair_mean_forward = float(repair_means.get("forward", 1.0))
    repair_success = _mapping(attribution.get("repair_success"), "repair_success")
    improved = int(repair_success.get("eventual_success_count") or 0) > 0

    blind_unopened = blind_status.get("blind_seal_unopened") is True
    access_receipt_count = blind_status.get("access_receipt_count")
    zero_access = (
        isinstance(access_receipt_count, (int, float))
        and not isinstance(access_receipt_count, bool)
        and int(access_receipt_count) == 0
    )

    evidence_complete = bool(
        receipts
        and all_terminal
        and catalog_case_ids
        and no_optional_promoted
        and no_blind_in_receipts
        and production_unchanged
        and blind_unopened
        and zero_access
        and cumulative.get("blind_data_used") is False
    )

    required_gates_pass = (
        pilot_non_regressed
        and not pilot_e2e_regressions
        and not new_gate_failures
        and not has_patch_regression
    )

    # Select one candidate only when evidence is complete, gates pass, and at
    # least one repair-development residual was cleared under frozen rules.
    select = bool(evidence_complete and required_gates_pass and improved)

    reasons: list[str] = []
    if not evidence_complete:
        reasons.append("evidence_incomplete")
    if not pilot_non_regressed:
        reasons.append("pilot_mean_e2e_regressed")
    if pilot_e2e_regressions:
        reasons.append("pilot_case_e2e_regressed")
    if new_gate_failures:
        reasons.append("new_pilot_gate_failures")
    if has_patch_regression:
        reasons.append("accepted_patch_regression")
    if not improved:
        reasons.append("no_repair_development_improvement")
    if select:
        reasons.append("selected_under_plat2_025_rules")

    decision = {
        "candidate_selected": select,
        "candidates_selected_count": 1 if select else 0,
        "evidence_complete": evidence_complete,
        "improved_repair_development": improved,
        "new_pilot_gate_failures": new_gate_failures,
        "no_optional_runtimes_promoted": no_optional_promoted,
        "pilot_case_e2e_regressions": pilot_e2e_regressions,
        "pilot_mean_e2e": pilot_mean,
        "pilot_non_regressed": pilot_non_regressed,
        "production_arm_id": PRODUCTION_ARM_ID,
        "production_path_unchanged": production_unchanged,
        "reasons": reasons,
        "receipt_case_ids": sorted(catalog_case_ids),
        "repair_development_mean_forward": repair_mean_forward,
        "required_gates_pass": required_gates_pass,
        "rules_ref": {
            "comparison": "candidate_minus_baseline",
            "noninferiority_margin": NONINFERIORITY_MARGIN,
            "pilot_non_regression_mean": POST_PLAT_BASELINE_E2E_MEAN,
            "primary_promotion_metric": PRIMARY_PROMOTION_METRIC,
            "selection_gate_ids": list(SELECTION_GATE_IDS),
            "source": "PLAT2-025",
        },
        "selection_policy": "zero_or_one_under_frozen_plat2_025_rules",
    }
    return decision


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    _require(path.is_file(), f"missing {label}: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(_mapping(data, label))


def collect_freeze_bindings(
    *,
    repo_root: str | Path | None = None,
    candidate_tree: Mapping[str, object] | None = None,
    environment: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Bind every identity the freeze must pin for later evaluation."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()

    baseline_report = load_repair_dev_baseline_report(repo_root=root)
    seal = load_frozen_blind_holdout_seal(repository_root=root)
    pilot_manifest = load_pilot_manifest(repository_root=root)
    repair_manifest = load_repair_development_manifest(repository_root=root)
    residual = load_repair_dev_residual_catalog(
        root / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH, repo_root=root
    )
    registry = _load_json_object(
        root / DEFAULT_INTERVENTION_REGISTRY_RELATIVE_PATH,
        "intervention registry",
    )
    packets = _load_json_object(
        root / DEFAULT_PACKET_METRICS_RELATIVE_PATH,
        "packet context metrics",
    )
    wave_manifest = load_edit_wave_manifest(repo_root=root)

    tree = (
        dict(candidate_tree)
        if candidate_tree is not None
        else capture_git_tree_binding(root)
    )
    # Slim identity: keep gitlinks_cid, drop bulky gitlinks rows from freeze payload.
    tree_binding = {
        "commit": tree.get("commit"),
        "gitlink_count": tree.get("gitlink_count"),
        "gitlinks_cid": tree.get("gitlinks_cid"),
        "inventory": tree.get("inventory"),
        "revision": tree.get("revision"),
        "tree": tree.get("tree"),
        "tree_binding_cid": tree.get("tree_binding_cid"),
    }
    env = (
        dict(environment)
        if environment is not None
        else capture_environment_toolchain()
    )

    decision_rules = noninferiority_and_promotion_rules()
    metrics = metric_facet_definitions()
    bootstrap = bootstrap_definition()
    packet_budget = packet_token_budget_definition()

    return {
        "baseline": {
            "arm_id": PRODUCTION_ARM_ID,
            "baseline_report_cid": baseline_report.get("report_cid"),
            "contract_cid": baseline_report.get("contract_cid"),
            "experiment_id": baseline_report.get("experiment_id"),
            "post_plat_baseline_e2e_mean": POST_PLAT_BASELINE_E2E_MEAN,
            "post_plat_baseline_report_cid": POST_PLAT_BASELINE_REPORT_CID,
        },
        "blind_holdout_seal_cid": seal.seal_cid,
        "blind_holdout_seal_path": str(BLIND_SEAL_RELATIVE_PATH).replace("\\", "/"),
        "bootstrap": bootstrap,
        "candidate_source_tree": tree_binding,
        "compiler_realizer": {
            "arm_id": PRODUCTION_ARM_ID,
            "constructor_identity": PRODUCTION_CONSTRUCTOR_IDENTITY,
            "constructor_module": (
                "benchmarks/semantic_roundtrip/constructors/typed_deontic.py"
            ),
            "realizer_identity": PRODUCTION_REALIZER_IDENTITY,
            "realizer_module": (
                "benchmarks/semantic_roundtrip/realizers/deterministic.py"
            ),
        },
        "decision_rules": decision_rules,
        "edit_wave_manifest_cid": wave_manifest.get("manifest_cid"),
        "environment_toolchain": env,
        "experiment_contract_interface": PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE,
        "experiment_family": EXPERIMENT_FAMILY,
        "intervention_registry_cid": registry.get("registry_cid"),
        "metrics": metrics,
        "noninferiority_margin": NONINFERIORITY_MARGIN,
        "packet_context_metrics_cid": packets.get("metrics_cid"),
        "packet_token_budget": packet_budget,
        "populations": {
            "pilot": {
                "case_ids": list(pilot_manifest.case_ids),
                "manifest_cid": pilot_manifest.manifest_cid,
                "population_kind": POPULATION_KIND_PILOT,
            },
            "repair_development": {
                "case_ids": list(repair_manifest.case_ids),
                "manifest_cid": repair_manifest.manifest_cid,
                "population_cid": residual.get("population_cid"),
                "population_kind": POPULATION_KIND_REPAIR_DEVELOPMENT,
                "residual_catalog_cid": residual.get("catalog_cid"),
                "tree_cid": residual.get("tree_cid"),
            },
        },
        "provider_model_toolchain_identities": {
            "deterministic_production": {
                "constructor": PRODUCTION_CONSTRUCTOR_IDENTITY,
                "realizer": PRODUCTION_REALIZER_IDENTITY,
                "role": "production_edit_target",
                "semantic_authority": True,
            },
            "optional_teachers_not_promoted": [
                "autoencoder",
                "spacy",
                "symai",
                "leanstral",
            ],
            "structural_gates_semantic_authority_false": [
                "Hammer",
                "cvc5",
                "Lean",
            ],
        },
        "selection_gate_ids": list(SELECTION_GATE_IDS),
        "tests": {
            "candidate_freeze": (
                "tests/unit/benchmarks/semantic_roundtrip/"
                "test_holdout_candidate_freeze.py"
            ),
            "edit_waves": (
                "tests/unit/benchmarks/semantic_roundtrip/"
                "test_repair_dev_edit_waves.py"
            ),
            "holdout_protocol": (
                "tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py"
            ),
            "validation_commands": [
                (
                    "PYTHONPATH=. python -m pytest "
                    "tests/unit/benchmarks/semantic_roundtrip/"
                    "test_holdout_candidate_freeze.py "
                    "tests/unit/benchmarks/semantic_roundtrip/"
                    "test_holdout_protocol.py -q"
                )
            ],
        },
        "thresholds": {
            "confidence_level": CONFIDENCE_LEVEL,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_method": BOOTSTRAP_METHOD,
            "noninferiority_margin": NONINFERIORITY_MARGIN,
            "packet_token_budget": PACKET_TOKEN_BUDGET,
            "pilot_mean_e2e_required": POST_PLAT_BASELINE_E2E_MEAN,
            "primary_promotion_metric": PRIMARY_PROMOTION_METRIC,
        },
    }


# ---------------------------------------------------------------------------
# Freeze + authorization builders
# ---------------------------------------------------------------------------


def build_candidate_freeze(
    repo_root: str | Path | None = None,
    *,
    receipts: Sequence[Mapping[str, object]] | None = None,
    population_results: Mapping[str, Mapping[str, object]] | None = None,
    run_scoring: bool = True,
    candidate_tree: Mapping[str, object] | None = None,
    environment: Mapping[str, object] | None = None,
    access_ledger_path: str | Path | None = None,
) -> dict[str, object]:
    """Build the immutable ``Plateau2CandidateFreeze@1`` artifact."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()

    blind_status = assert_blind_seal_unopened(
        root, access_ledger_path=access_ledger_path
    )
    baseline_report = load_repair_dev_baseline_report(repo_root=root)
    wave_receipts = (
        tuple(receipts)
        if receipts is not None
        else load_edit_wave_receipts(repo_root=root)
    )
    isolated = replay_all_isolated_edit_waves(wave_receipts)
    cumulative = score_cumulative_candidate(
        repo_root=root,
        population_results=population_results,
        run_scoring=run_scoring,
    )
    attribution = compute_attribution_evidence(
        isolated_waves=isolated,
        cumulative=cumulative,
        baseline_report=baseline_report,
    )
    selection = evaluate_selection_gates(
        attribution=attribution,
        cumulative=cumulative,
        baseline_report=baseline_report,
        receipts=wave_receipts,
        blind_status=blind_status,
    )
    bindings = collect_freeze_bindings(
        repo_root=root,
        candidate_tree=candidate_tree,
        environment=environment,
    )

    candidate_block: dict[str, object] | None
    if selection.get("candidate_selected") is True:
        candidate_block = {
            "arm_id": PRODUCTION_ARM_ID,
            "constructor_identity": PRODUCTION_CONSTRUCTOR_IDENTITY,
            "realizer_identity": PRODUCTION_REALIZER_IDENTITY,
            "selection_index": 0,
            "source_tree": bindings["candidate_source_tree"],
            "status": "frozen",
        }
    else:
        candidate_block = None

    payload: dict[str, object] = {
        "assumptions": list(DEFAULT_FREEZE_ASSUMPTIONS),
        "attribution": _plain_json(attribution),
        "bindings": _plain_json(bindings),
        "blind_holdout": _plain_json(blind_status),
        "board_namespace": EXPERIMENT_FAMILY,
        "candidate": candidate_block,
        "candidate_selected": bool(selection.get("candidate_selected")),
        "candidates_selected_count": (
            1 if selection.get("candidate_selected") is True else 0
        ),
        "cumulative_candidate_scores": {
            POPULATION_KIND_PILOT: _plain_json(cumulative[POPULATION_KIND_PILOT]),
            POPULATION_KIND_REPAIR_DEVELOPMENT: _plain_json(
                cumulative[POPULATION_KIND_REPAIR_DEVELOPMENT]
            ),
            "arm_id": PRODUCTION_ARM_ID,
            "blind_data_used": False,
        },
        "evidence_id": FREEZE_EVIDENCE_ID,
        "experiment_family": EXPERIMENT_FAMILY,
        "goal_id": FREEZE_GOAL_ID,
        "interface": PLATEAU2_CANDIDATE_FREEZE_INTERFACE,
        "invalidation_policy": {
            "action_on_change": (
                "mint_new_experiment_identity_and_require_fresh_blind_holdout"
            ),
            "invalidating_change_classes": list(INVALIDATING_CHANGE_CLASSES),
            "mutable_after_freeze": False,
            "retune_against_this_blind_holdout": False,
        },
        "isolated_wave_count": len(isolated),
        "protocol_change_policy": {
            "after_authorization": (
                "any code/config/prompt/threshold/population change invalidates "
                "authorization and requires a new experiment identity plus a "
                "fresh blind holdout rather than retuning against this one"
            ),
            "mutable_after_authorization": False,
        },
        "revision": FREEZE_REVISION,
        "schema_version": PLATEAU2_CANDIDATE_FREEZE_SCHEMA,
        "selection": _plain_json(selection),
        "task_id": FREEZE_TASK_ID,
        "title": "PLAT2-055 candidate freeze and attribution evidence",
    }

    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"freeze_cid", "freeze_cid_codec", "freeze_cid_scope"}
    }
    freeze_cid = cid_for_dag_json(_plain_json(identity))
    payload["freeze_cid"] = freeze_cid
    payload["freeze_cid_codec"] = CID_CODEC
    payload["freeze_cid_scope"] = FREEZE_CID_SCOPE
    return payload


def parse_candidate_freeze(
    value: object,
    *,
    require_blind_unopened: bool = True,
) -> dict[str, object]:
    """Validate a ``Plateau2CandidateFreeze@1`` payload."""

    data = dict(_mapping(value, "candidate freeze"))
    _require(
        data.get("interface") == PLATEAU2_CANDIDATE_FREEZE_INTERFACE,
        "candidate freeze interface mismatch",
    )
    _require(
        data.get("schema_version") == PLATEAU2_CANDIDATE_FREEZE_SCHEMA,
        "candidate freeze schema mismatch",
    )
    _require(data.get("task_id") == FREEZE_TASK_ID, "task_id mismatch")
    _require(data.get("goal_id") == FREEZE_GOAL_ID, "goal_id mismatch")
    _require(data.get("evidence_id") == FREEZE_EVIDENCE_ID, "evidence_id mismatch")
    _cid(data.get("freeze_cid"), "freeze_cid")

    selected = data.get("candidate_selected")
    _require(isinstance(selected, bool), "candidate_selected must be boolean")
    if "candidates_selected_count" not in data:
        raise HoldoutCandidateFreezeError("candidates_selected_count required")
    count = int(data["candidates_selected_count"])  # type: ignore[arg-type]
    _require(count in (0, 1), "candidates_selected_count must be 0 or 1")
    _require(
        (selected is True and count == 1) or (selected is False and count == 0),
        "candidate_selected/count inconsistency",
    )
    if selected:
        candidate = _mapping(data.get("candidate"), "candidate")
        _require(candidate.get("status") == "frozen", "candidate status must be frozen")
        _require(
            candidate.get("arm_id") == PRODUCTION_ARM_ID,
            "frozen candidate arm mismatch",
        )
    else:
        _require(
            data.get("candidate") is None,
            "candidate must be null when none selected",
        )

    attribution = _mapping(data.get("attribution"), "attribution")
    _require(attribution.get("blind_data_used") is False, "attribution used blind data")
    _array(attribution.get("isolated_waves"), "attribution.isolated_waves")
    _mapping(attribution.get("cumulative_deltas"), "attribution.cumulative_deltas")
    _mapping(attribution.get("repair_success"), "attribution.repair_success")
    _mapping(attribution.get("context_tokens"), "attribution.context_tokens")
    _mapping(attribution.get("provider_calls"), "attribution.provider_calls")
    _mapping(attribution.get("cost"), "attribution.cost")
    _mapping(
        attribution.get("structural_gate_coverage"),
        "attribution.structural_gate_coverage",
    )

    bindings = _mapping(data.get("bindings"), "bindings")
    for key in (
        "baseline",
        "candidate_source_tree",
        "compiler_realizer",
        "metrics",
        "bootstrap",
        "decision_rules",
        "thresholds",
        "populations",
        "tests",
    ):
        _mapping(bindings.get(key), f"bindings.{key}")
    _cid(bindings.get("blind_holdout_seal_cid"), "bindings.blind_holdout_seal_cid")
    _cid(
        bindings.get("intervention_registry_cid"),
        "bindings.intervention_registry_cid",
    )

    if require_blind_unopened:
        blind = _mapping(data.get("blind_holdout"), "blind_holdout")
        _require(blind.get("blind_seal_unopened") is True, "blind must be unopened")
        _require(
            int(blind.get("access_receipt_count", -1)) == 0,
            "access receipts must be zero at freeze",
        )

    scores = _mapping(
        data.get("cumulative_candidate_scores"), "cumulative_candidate_scores"
    )
    _require(scores.get("blind_data_used") is False, "scores used blind data")
    for kind in (POPULATION_KIND_PILOT, POPULATION_KIND_REPAIR_DEVELOPMENT):
        _mapping(scores.get(kind), f"cumulative_candidate_scores.{kind}")

    invalidation = _mapping(data.get("invalidation_policy"), "invalidation_policy")
    _require(
        invalidation.get("retune_against_this_blind_holdout") is False,
        "retune against this blind holdout must be forbidden",
    )
    _require(
        invalidation.get("mutable_after_freeze") is False,
        "freeze must be immutable",
    )

    identity = {
        key: value
        for key, value in data.items()
        if key not in {"freeze_cid", "freeze_cid_codec", "freeze_cid_scope"}
    }
    expected = cid_for_dag_json(_plain_json(identity))
    _require(
        data.get("freeze_cid") == expected,
        "freeze_cid does not match payload identity",
    )
    return data


def build_holdout_authorization(
    freeze: Mapping[str, object] | None = None,
    *,
    repo_root: str | Path | None = None,
    access_ledger_path: str | Path | None = None,
) -> dict[str, object] | None:
    """Build ``SemanticRoundtripHoldoutAuthorization@1`` or return ``None``.

    Authorization is emitted only when:

    * freeze selects exactly one candidate,
    * evidence is complete,
    * pilot and required gates pass,
    * blind seal has zero prior access,
    * freeze payload validates.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    freeze_payload = (
        parse_candidate_freeze(freeze)
        if freeze is not None
        else parse_candidate_freeze(
            load_candidate_freeze(repo_root=root),
            require_blind_unopened=True,
        )
    )

    if freeze_payload.get("candidate_selected") is not True:
        return None
    selection = _mapping(freeze_payload.get("selection"), "selection")
    if selection.get("evidence_complete") is not True:
        return None
    if selection.get("required_gates_pass") is not True:
        return None

    blind_status = assert_blind_seal_unopened(
        root, access_ledger_path=access_ledger_path
    )
    receipt_count = blind_status.get("access_receipt_count")
    if (
        blind_status.get("blind_seal_unopened") is not True
        or not isinstance(receipt_count, (int, float))
        or isinstance(receipt_count, bool)
        or int(receipt_count) != 0
    ):
        return None

    seal = load_frozen_blind_holdout_seal(repository_root=root)
    freeze_cid = _cid(freeze_payload.get("freeze_cid"), "freeze_cid")
    protocol_auth = HoldoutAccessAuthorization.build(
        seal=seal,
        candidate_freeze_cid=freeze_cid,
    )

    payload: dict[str, object] = {
        "assumptions": [
            "authorization is single-use for PLAT2-060 one-shot evaluation",
            "outcomes must not be inspected before evaluation completes",
            "tuning against this blind holdout is forbidden after authorization",
            "any code/config/prompt/threshold/population change invalidates this "
            "authorization and requires a new experiment identity plus a fresh "
            "blind holdout",
        ],
        "authorization_cid": protocol_auth.authorization_cid,
        "blind_holdout": _plain_json(blind_status),
        "candidate_freeze_cid": freeze_cid,
        "complete": True,
        "evidence_id": FREEZE_EVIDENCE_ID,
        "goal_id": AUTHORIZATION_GOAL_ID,
        "holdout_authorized": True,
        "interface": SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_INTERFACE,
        "invalidation_policy": {
            "action_on_change": (
                "mint_new_experiment_identity_and_require_fresh_blind_holdout"
            ),
            "invalidating_change_classes": list(INVALIDATING_CHANGE_CLASSES),
            "mutable_after_authorization": False,
            "retune_against_this_blind_holdout": False,
        },
        "outcomes_inspected": False,
        "protocol_authorization": protocol_auth.to_dict(),
        "schema_version": SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_SCHEMA,
        "seal_cid": seal.seal_cid,
        "task_id": FREEZE_TASK_ID,
        "title": "PLAT2-055 holdout access authorization",
        "tuning_permitted": False,
    }

    identity = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "authorization_artifact_cid",
            "authorization_artifact_cid_codec",
            "authorization_artifact_cid_scope",
        }
    }
    artifact_cid = cid_for_dag_json(_plain_json(identity))
    payload["authorization_artifact_cid"] = artifact_cid
    payload["authorization_artifact_cid_codec"] = CID_CODEC
    payload["authorization_artifact_cid_scope"] = AUTHORIZATION_ARTIFACT_CID_SCOPE
    return payload


def parse_holdout_authorization(value: object) -> dict[str, object]:
    """Validate a ``SemanticRoundtripHoldoutAuthorization@1`` artifact."""

    data = dict(_mapping(value, "holdout authorization"))
    _require(
        data.get("interface") == SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_INTERFACE,
        "authorization interface mismatch",
    )
    _require(
        data.get("schema_version")
        == SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_SCHEMA,
        "authorization schema mismatch",
    )
    _require(data.get("goal_id") == AUTHORIZATION_GOAL_ID, "goal_id must be PLAT2-055")
    _require(data.get("task_id") == FREEZE_TASK_ID, "task_id mismatch")
    _require(data.get("complete") is True, "authorization must be complete")
    _require(
        data.get("holdout_authorized") is True,
        "authorization must set holdout_authorized",
    )
    _require(
        data.get("outcomes_inspected") is False,
        "authorization must not follow outcome inspection",
    )
    _require(
        data.get("tuning_permitted") is False,
        "authorization forbids tuning",
    )
    freeze_cid = _cid(data.get("candidate_freeze_cid"), "candidate_freeze_cid")
    seal_cid = _cid(data.get("seal_cid"), "seal_cid")
    auth_cid = _cid(data.get("authorization_cid"), "authorization_cid")
    _cid(data.get("authorization_artifact_cid"), "authorization_artifact_cid")

    protocol = _mapping(data.get("protocol_authorization"), "protocol_authorization")
    rebuilt = HoldoutAccessAuthorization(
        goal_id=AUTHORIZATION_GOAL_ID,
        authorization_cid=auth_cid,
        seal_cid=seal_cid,
        candidate_freeze_cid=freeze_cid,
        complete=True,
        holdout_authorized=True,
        outcomes_inspected=False,
        tuning_permitted=False,
    )
    _require(
        protocol.get("authorization_cid") == rebuilt.authorization_cid,
        "protocol authorization_cid mismatch",
    )
    _require(
        protocol.get("candidate_freeze_cid") == freeze_cid,
        "protocol candidate_freeze_cid mismatch",
    )
    _require(protocol.get("seal_cid") == seal_cid, "protocol seal_cid mismatch")

    blind = _mapping(data.get("blind_holdout"), "blind_holdout")
    _require(blind.get("blind_seal_unopened") is True, "blind must be unopened")
    _require(
        int(blind.get("access_receipt_count", -1)) == 0,
        "access receipts must be zero at authorization",
    )

    invalidation = _mapping(data.get("invalidation_policy"), "invalidation_policy")
    _require(
        invalidation.get("retune_against_this_blind_holdout") is False,
        "retune against this blind holdout must be forbidden",
    )
    _require(
        invalidation.get("mutable_after_authorization") is False,
        "authorization must be immutable",
    )

    identity = {
        key: value
        for key, value in data.items()
        if key
        not in {
            "authorization_artifact_cid",
            "authorization_artifact_cid_codec",
            "authorization_artifact_cid_scope",
        }
    }
    expected = cid_for_dag_json(_plain_json(identity))
    _require(
        data.get("authorization_artifact_cid") == expected,
        "authorization_artifact_cid does not match payload identity",
    )
    return data


def authorization_from_freeze(
    freeze: Mapping[str, object],
    *,
    repo_root: str | Path | None = None,
) -> HoldoutAccessAuthorization:
    """Return the protocol ``HoldoutAccessAuthorization`` for a frozen candidate.

    Raises if the freeze did not select a candidate or fails validation.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    parsed = parse_candidate_freeze(freeze)
    _require(
        parsed.get("candidate_selected") is True,
        "cannot authorize without a frozen candidate",
    )
    seal = load_frozen_blind_holdout_seal(repository_root=root)
    return HoldoutAccessAuthorization.build(
        seal=seal,
        candidate_freeze_cid=_cid(parsed.get("freeze_cid"), "freeze_cid"),
    )


def assert_authorization_still_valid(
    authorization: Mapping[str, object],
    *,
    freeze: Mapping[str, object],
    code_config_prompt_threshold_population_changed: bool = False,
) -> None:
    """Fail closed when post-authorization inputs change."""

    parse_holdout_authorization(authorization)
    freeze_payload = parse_candidate_freeze(freeze, require_blind_unopened=False)
    _require(
        authorization.get("candidate_freeze_cid") == freeze_payload.get("freeze_cid"),
        "authorization candidate_freeze_cid does not match freeze",
    )
    if code_config_prompt_threshold_population_changed:
        raise HoldoutCandidateFreezeError(
            "authorization invalidated: code/config/prompt/threshold/population "
            "changed after authorization; mint a new experiment identity and a "
            "fresh blind holdout rather than retuning against this one"
        )


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def load_candidate_freeze(
    path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, object]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    freeze_path = (
        Path(path) if path is not None else root / DEFAULT_FREEZE_RELATIVE_PATH
    )
    payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    return parse_candidate_freeze(payload)


def load_holdout_authorization(
    path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, object]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    auth_path = (
        Path(path)
        if path is not None
        else root / DEFAULT_AUTHORIZATION_RELATIVE_PATH
    )
    payload = json.loads(auth_path.read_text(encoding="utf-8"))
    return parse_holdout_authorization(payload)


def write_candidate_freeze(
    path: str | Path,
    *,
    freeze: Mapping[str, object] | None = None,
    repo_root: str | Path | None = None,
    run_scoring: bool = True,
    population_results: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    payload = (
        dict(freeze)
        if freeze is not None
        else build_candidate_freeze(
            root,
            run_scoring=run_scoring,
            population_results=population_results,
        )
    )
    parse_candidate_freeze(payload)
    _atomic_write_json(Path(path), payload)
    return payload


def write_holdout_authorization(
    path: str | Path,
    *,
    authorization: Mapping[str, object] | None = None,
    freeze: Mapping[str, object] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, object] | None:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    payload = (
        dict(authorization)
        if authorization is not None
        else build_holdout_authorization(freeze, repo_root=root)
    )
    if payload is None:
        return None
    parse_holdout_authorization(payload)
    _atomic_write_json(Path(path), payload)
    return payload


def build_freeze_and_authorization_bundle(
    repo_root: str | Path | None = None,
    *,
    run_scoring: bool = True,
    population_results: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build freeze + optional authorization as one cohesive evidence bundle."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    freeze = build_candidate_freeze(
        root,
        run_scoring=run_scoring,
        population_results=population_results,
    )
    authorization = build_holdout_authorization(freeze, repo_root=root)
    return {
        "authorization": authorization,
        "authorization_emitted": authorization is not None,
        "freeze": freeze,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "PLAT2-055 freeze candidate, attribution evidence, and holdout "
            "authorization"
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="repository root (default: inferred from module path)",
    )
    parser.add_argument(
        "--freeze-output",
        type=Path,
        default=None,
        help="path for plateau2_candidate_freeze.json",
    )
    parser.add_argument(
        "--authorization-output",
        type=Path,
        default=None,
        help="path for plateau2_holdout_authorization.json",
    )
    parser.add_argument(
        "--skip-scoring",
        action="store_true",
        help="require pre-built scores via environment (not for production freeze)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.repo_root or _repo_root()

    if args.skip_scoring:
        raise SystemExit(
            "refusing --skip-scoring without injected population_results; "
            "use the Python API for test harnesses"
        )

    freeze_path = args.freeze_output or (root / DEFAULT_FREEZE_RELATIVE_PATH)
    auth_path = args.authorization_output or (
        root / DEFAULT_AUTHORIZATION_RELATIVE_PATH
    )
    freeze = write_candidate_freeze(freeze_path, repo_root=root, run_scoring=True)
    authorization = write_holdout_authorization(
        auth_path, freeze=freeze, repo_root=root
    )
    print(
        json.dumps(
            {
                "authorization_artifact_cid": (
                    authorization.get("authorization_artifact_cid")
                    if authorization
                    else None
                ),
                "authorization_emitted": authorization is not None,
                "authorization_path": str(auth_path) if authorization else None,
                "candidate_selected": freeze.get("candidate_selected"),
                "freeze_cid": freeze.get("freeze_cid"),
                "freeze_path": str(freeze_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "DEFAULT_AUTHORIZATION_RELATIVE_PATH",
    "DEFAULT_FREEZE_RELATIVE_PATH",
    "FREEZE_EVIDENCE_ID",
    "FREEZE_GOAL_ID",
    "FREEZE_TASK_ID",
    "HoldoutCandidateFreezeError",
    "INVALIDATING_CHANGE_CLASSES",
    "PLATEAU2_CANDIDATE_FREEZE_INTERFACE",
    "PLATEAU2_CANDIDATE_FREEZE_SCHEMA",
    "SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_INTERFACE",
    "SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_SCHEMA",
    "assert_authorization_still_valid",
    "authorization_from_freeze",
    "build_candidate_freeze",
    "build_freeze_and_authorization_bundle",
    "build_holdout_authorization",
    "collect_freeze_bindings",
    "compute_attribution_evidence",
    "evaluate_selection_gates",
    "load_candidate_freeze",
    "load_edit_wave_manifest",
    "load_edit_wave_receipts",
    "load_holdout_authorization",
    "main",
    "parse_candidate_freeze",
    "parse_holdout_authorization",
    "replay_all_isolated_edit_waves",
    "replay_isolated_edit_wave",
    "score_cumulative_candidate",
    "score_population_block",
    "write_candidate_freeze",
    "write_holdout_authorization",
]
