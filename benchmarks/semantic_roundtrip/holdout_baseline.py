"""PLAT2-025 freeze: repair-development baseline and experiment contract.

Interfaces:
* ``Plateau2ExperimentContract@1`` — preregistered decision protocol identity
* ``EvalRepairMatrixReport@1`` — deterministic baseline scores on pilots and
  repair-development only

Before any edit wave, this module binds:

* post-PLAT baseline git commit / tree and recursive (benchmark-bounded) gitlinks
* deterministic production arm and constructor/realizer config
* environment / toolchain inventory
* population and residual-catalog CIDs
* metric and facet definitions
* per-case-first aggregation
* paired case-cluster bootstrap method, confidence level, and sample count
* noninferiority margin
* selection / promotion rules
* packet token budget
* capability policy
* failure taxonomy

It runs the deterministic baseline on **pilots and repair-development only**,
records per-case and per-facet forward/cycle/e2e loss, coverage, polarity,
source-copy gates, and failure clusters under the
``semantic_scored`` / ``not_measured`` / ``runtime_failed`` / ``unsupported``
status taxonomy, and asserts the blind seal remains unopened with zero access
receipts.

Protocol changes after this freeze mint a new experiment identity and retire
downstream receipts.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.contracts import (
    ComponentStatus,
    ConstructorRequest,
    ContractError,
    RealizerRequest,
)
from benchmarks.semantic_roundtrip.evaluation_status import (
    DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
)
from benchmarks.semantic_roundtrip.holdout_protocol import (
    BLIND_SEAL_RELATIVE_PATH,
    POPULATION_KIND_PILOT as HOLDOUT_POP_PILOT,
    POPULATION_KIND_REPAIR_DEVELOPMENT as HOLDOUT_POP_REPAIR,
    load_frozen_blind_holdout_seal,
    load_pilot_manifest,
    load_repair_development_manifest,
)
from benchmarks.semantic_roundtrip.matrix import (
    MatrixCase,
    load_matrix_cases,
    polarity_diagnostics,
    source_copy_diagnostics,
)
from benchmarks.semantic_roundtrip.metrics import (
    RULE_WEIGHTS,
    compare_semantic_ir,
    make_round_trip_result,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    BASELINE_ARM_ID,
    BASELINE_CONSTRUCTOR_IDENTITY,
    CATALOG_STATUS_NOT_MEASURED,
    CATALOG_STATUS_RUNTIME_FAILED,
    CATALOG_STATUS_SEMANTIC_SCORED,
    CATALOG_STATUS_UNSUPPORTED,
    DEFAULT_CATALOG_RELATIVE_PATH,
    DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH,
    HOLDOUT_BASELINE_E2E_MEAN,
    HOLDOUT_BASELINE_REPORT_CID,
    NON_SEMANTIC_CATALOG_STATUSES,
    PILOT_CASE_IDS,
    PILOT_CASES_RELATIVE_PATH,
    POPULATION_KIND_PILOT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    REPAIR_DEV_CASES_RELATIVE_PATH,
    load_plateau_residual_catalog,
    load_repair_dev_residual_catalog,
)
from benchmarks.semantic_roundtrip.statistics import (
    DEFAULT_BOOTSTRAP_SAMPLES,
    DEFAULT_CONFIDENCE_LEVEL,
)
from benchmarks.semantic_roundtrip.stage_metrics import (
    PROMOTION_FULL_GATE_IDS,
    PROMOTION_REQUIRES_FULL_GATES,
)


# ---------------------------------------------------------------------------
# Interfaces / schemas
# ---------------------------------------------------------------------------

PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE: Final = "Plateau2ExperimentContract@1"
PLATEAU2_EXPERIMENT_CONTRACT_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau2-experiment-contract.v1"
)
EVAL_REPAIR_MATRIX_REPORT_INTERFACE: Final = "EvalRepairMatrixReport@1"
EVAL_REPAIR_MATRIX_REPORT_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau2-repair-dev-baseline.v1"
)

CONTRACT_CID_SCOPE: Final = "payload_without_contract_cid"
REPORT_CID_SCOPE: Final = "payload_without_report_cid"
CID_CODEC: Final = "dag-json"

DEFAULT_BASELINE_REPORT_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "repair_dev_baseline.json"
)
DEFAULT_CONTRACT_DOCS_RELATIVE_PATH: Final = Path(
    "docs/benchmarks/semantic_roundtrip_plateau2_baseline.md"
)

# ---------------------------------------------------------------------------
# Frozen protocol constants (PLAT2-025)
# ---------------------------------------------------------------------------

EXPERIMENT_FAMILY: Final = "semantic-roundtrip-plateau-holdout-v2"
EXPERIMENT_TASK_ID: Final = "PLAT2-025"
EXPERIMENT_GOAL_ID: Final = "PLAT2-G025"
EXPERIMENT_EVIDENCE_ID: Final = "PLAT2EV025BASE"
EXPERIMENT_REVISION: Final = 1

# Production arm (post-PLAT det path).
PRODUCTION_ARM_ID: Final = BASELINE_ARM_ID
assert PRODUCTION_ARM_ID == DEFAULT_DETERMINISTIC_BASELINE_ARM_ID
PRODUCTION_CONSTRUCTOR_ID: Final = "typed_deontic"
PRODUCTION_CONSTRUCTOR_IDENTITY: Final = BASELINE_CONSTRUCTOR_IDENTITY
PRODUCTION_REALIZER_ID: Final = "deterministic"
PRODUCTION_REALIZER_IDENTITY: Final = "CanonicalDeterministicRealizer@1"
PRODUCTION_GUIDANCE: Final = "no_guidance"
PRODUCTION_REPAIR: Final = "no_repair"
PRODUCTION_ROUTE: Final = "not_applicable"
POST_PLAT_BASELINE_E2E_MEAN: Final = HOLDOUT_BASELINE_E2E_MEAN  # 0.0
POST_PLAT_BASELINE_REPORT_CID: Final = HOLDOUT_BASELINE_REPORT_CID

# Metrics / facets
PRIMARY_PROMOTION_METRIC: Final = "end_to_end_loss"
LOSS_METRICS: Final = ("forward", "cycle", "end_to_end")
FACET_NAMES: Final = ("modality", "conditions", "exceptions", "temporal")
AGGREGATION_ORDER: Final = (
    "per_case_first_macro_mean"
)
AGGREGATION_DETAIL: Final = (
    "repeats_within_case_then_unweighted_macro_average_across_cases"
)
LOSS_DIRECTION: Final = "lower_is_better"
FAILURE_LOSS: Final = 1.0

# Paired bootstrap / uncertainty
BOOTSTRAP_METHOD: Final = "seeded_percentile_case_cluster_bootstrap"
BOOTSTRAP_UNIT: Final = "case_cluster"
BOOTSTRAP_SAMPLES: Final = DEFAULT_BOOTSTRAP_SAMPLES  # 10_000
CONFIDENCE_LEVEL: Final = DEFAULT_CONFIDENCE_LEVEL  # 0.95
BOOTSTRAP_SEED: Final = 17_291  # matches canonical parity policy freeze
RESAMPLING_UNIT: Final = "case_after_within_case_repeat_aggregation"

# Noninferiority / selection (candidate − baseline on end-to-end loss)
NONINFERIORITY_MARGIN: Final = 0.03
COMPARISON_SIGN: Final = "candidate_minus_baseline"
IMPROVEMENT_RULE: Final = "paired_ci_high_lt_0"
NONINFERIORITY_RULE: Final = (
    "upper_confidence_bound_lte_noninferiority_margin"
)
SELECTION_GATE_IDS: Final = PROMOTION_FULL_GATE_IDS  # coverage/copy/polarity

# Packet token budget (frozen for PLAT2-030 packets)
PACKET_TOKEN_BUDGET: Final = 8_192
PACKET_TOKEN_BUDGET_SOFT_WARN: Final = 6_144
PACKET_TOKEN_COUNTING_METHOD: Final = "whitespace_split_proxy_v1"
PACKET_OMITTED_HANDLE_COVERAGE_REQUIRED: Final = True

# Populations in scope for this baseline freeze
BASELINE_POPULATIONS: Final = (
    POPULATION_KIND_PILOT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
)
BLIND_POPULATION_OUT_OF_SCOPE: Final = "blind_holdout"
BLIND_SEAL_MUST_REMAIN_UNOPENED: Final = True

# Evaluation status taxonomy
EVAL_STATUS_SEMANTIC_SCORED: Final = CATALOG_STATUS_SEMANTIC_SCORED
EVAL_STATUS_NOT_MEASURED: Final = CATALOG_STATUS_NOT_MEASURED
EVAL_STATUS_RUNTIME_FAILED: Final = CATALOG_STATUS_RUNTIME_FAILED
EVAL_STATUS_UNSUPPORTED: Final = CATALOG_STATUS_UNSUPPORTED
EVALUATION_STATUSES: Final = frozenset(
    {
        EVAL_STATUS_SEMANTIC_SCORED,
        EVAL_STATUS_NOT_MEASURED,
        EVAL_STATUS_RUNTIME_FAILED,
        EVAL_STATUS_UNSUPPORTED,
    }
)

# Decision outcomes (PLAT2 plan)
DECISION_IMPROVEMENT_CONFIRMED: Final = "improvement_confirmed"
DECISION_GENERALIZATION_NO_IMPROVEMENT: Final = (
    "generalization_confirmed_no_improvement"
)
DECISION_PROMOTION_DECLINED: Final = "promotion_declined"
DECISION_INCOMPLETE: Final = "incomplete"
DECISION_OUTCOMES: Final = frozenset(
    {
        DECISION_IMPROVEMENT_CONFIRMED,
        DECISION_GENERALIZATION_NO_IMPROVEMENT,
        DECISION_PROMOTION_DECLINED,
        DECISION_INCOMPLETE,
    }
)

# Capability policy (roles; semantic authority remains false for advisors)
CAPABILITY_POLICY: Final = MappingProxyType(
    {
        "production_composition": {
            "arm_id": PRODUCTION_ARM_ID,
            "constructor": PRODUCTION_CONSTRUCTOR_IDENTITY,
            "realizer": PRODUCTION_REALIZER_IDENTITY,
            "semantic_authority": True,
            "role": "production_edit_target",
        },
        "autoencoder": {
            "role": "causal_guidance_only_when_qualified",
            "semantic_authority": False,
            "may_substitute_for_e2e": False,
        },
        "spacy": {
            "role": "diagnostics",
            "semantic_authority": False,
            "may_substitute_for_e2e": False,
        },
        "symai": {
            "role": "orchestration",
            "semantic_authority": False,
            "may_substitute_for_e2e": False,
        },
        "leanstral": {
            "role": "proposal_teacher",
            "semantic_authority": False,
            "may_substitute_for_e2e": False,
        },
        "hammer": {
            "role": "structural_gate",
            "semantic_authority": False,
            "may_substitute_for_e2e": False,
        },
        "cvc5": {
            "role": "structural_gate",
            "semantic_authority": False,
            "may_substitute_for_e2e": False,
        },
        "lean": {
            "role": "structural_gate",
            "semantic_authority": False,
            "may_substitute_for_e2e": False,
        },
    }
)

# Failure taxonomy clusters used by baseline reports
FAILURE_CLUSTER_KINDS: Final = (
    "gate_full_coverage",
    "gate_source_copy_exclusion",
    "gate_polarity_preservation",
    "loss_forward_nonzero",
    "loss_cycle_nonzero",
    "loss_end_to_end_nonzero",
    "facet_modality",
    "facet_conditions",
    "facet_exceptions",
    "facet_temporal",
    "evaluation_not_measured",
    "evaluation_runtime_failed",
    "evaluation_unsupported",
    "residual_field_mismatch",
    "residual_missing_rule",
    "residual_extra_rule",
)

# Protocol assumptions bound into every contract
DEFAULT_EXPERIMENT_ASSUMPTIONS: Final = (
    "production remains typed_deontic → IR → deterministic realizer",
    "post-PLAT pilot mean e2e is 0.0 and must not regress under re-score",
    "repair-development is visible and underpowered for promotion alone",
    "blind holdout stays sealed until PLAT2-055 authorization",
    "unsupported/not_measured/runtime_failed never enter semantic score aggregates",
    "paired case-cluster bootstrap is the only uncertainty method for promotion",
    "noninferiority margin is 0.03 on candidate_minus_baseline end-to-end loss",
    "protocol change mints a new experiment identity and retires downstream receipts",
    "Hammer/cvc5/Lean have semantic_authority false",
    "CE/cosine and stage-local metrics never authorize promotion alone",
)


class HoldoutBaselineError(ContractError):
    """Raised when the experiment contract or baseline report fails validation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require(condition: object, message: str) -> None:
    if not condition:
        raise HoldoutBaselineError(message)


def _nonblank(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HoldoutBaselineError(f"{path} must be a nonblank string")
    return value.strip()


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HoldoutBaselineError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise HoldoutBaselineError(f"{path} must be an array")
    return value


def _finite_unit(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise HoldoutBaselineError(
            f"{path} must be a finite number from zero to one"
        )
    return float(value)


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
        raise HoldoutBaselineError(
            f"{path} must be a canonical dag-json CID"
        ) from exc


def _git_value(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HoldoutBaselineError(
            f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Source tree / gitlinks / environment
# ---------------------------------------------------------------------------


def capture_git_tree_binding(
    repo_root: str | Path | None = None,
    *,
    revision: str = "HEAD",
) -> dict[str, object]:
    """Bind the post-PLAT baseline git commit, tree, and recursive gitlinks.

    Uses the benchmark-bounded recursive inventory (top-level gitlinks plus
    direct children of ``ipfs_accelerate_py``) so cyclic tool repositories do
    not enter the freeze boundary.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    commit = _git_value(root, "rev-parse", revision)
    tree = _git_value(root, "rev-parse", f"{revision}^{{tree}}")
    try:
        from benchmarks.logic_pipeline.source_reconciliation import (
            _capture_benchmark_bounded_gitlinks,
        )

        gitlinks = _capture_benchmark_bounded_gitlinks(root, commit)
        gitlink_rows = [item.to_dict() for item in gitlinks]
    except Exception as exc:  # pragma: no cover - environment edge
        raise HoldoutBaselineError(
            f"failed to capture recursive gitlinks: {type(exc).__name__}: {exc}"
        ) from exc

    gitlinks_cid = cid_for_dag_json(
        {
            "commit": commit,
            "gitlinks": gitlink_rows,
            "scope": "benchmark_bounded_recursive_gitlinks",
            "tree": tree,
        }
    )
    tree_binding_cid = cid_for_dag_json(
        {
            "commit": commit,
            "gitlinks_cid": gitlinks_cid,
            "scope": "plateau2_baseline_source_tree",
            "tree": tree,
        }
    )
    return {
        "commit": commit,
        "gitlink_count": len(gitlink_rows),
        "gitlinks": gitlink_rows,
        "gitlinks_cid": gitlinks_cid,
        "inventory": "benchmark_bounded_recursive",
        "revision": revision,
        "tree": tree,
        "tree_binding_cid": tree_binding_cid,
    }


def capture_environment_toolchain() -> dict[str, object]:
    """Record the environment / toolchain inventory for the freeze."""

    return {
        "constructor_identity": PRODUCTION_CONSTRUCTOR_IDENTITY,
        "platform": platform.platform(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "realizer_identity": PRODUCTION_REALIZER_IDENTITY,
        "sys_platform": sys.platform,
        "toolchain": {
            "deterministic_realizer": PRODUCTION_REALIZER_IDENTITY,
            "structural_gates": ["Hammer", "cvc5", "Lean"],
            "typed_deontic_constructor": PRODUCTION_CONSTRUCTOR_IDENTITY,
        },
    }


def load_population_and_residual_cids(
    repo_root: str | Path | None = None,
) -> dict[str, object]:
    """Bind pilot / repair-development population and residual catalog CIDs."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    pilot_manifest = load_pilot_manifest(repository_root=root)
    repair_manifest = load_repair_development_manifest(repository_root=root)
    pilot_catalog = load_plateau_residual_catalog(
        root / DEFAULT_CATALOG_RELATIVE_PATH, repo_root=root
    )
    repair_catalog = load_repair_dev_residual_catalog(
        root / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH, repo_root=root
    )
    seal = load_frozen_blind_holdout_seal(repository_root=root)

    pilot_catalog_cid = _nonblank(
        pilot_catalog.get("catalog_cid"), "pilot residual catalog_cid"
    )
    repair_catalog_cid = _nonblank(
        repair_catalog.get("catalog_cid"), "repair residual catalog_cid"
    )
    repair_population_cid = _nonblank(
        repair_catalog.get("population_cid"), "repair population_cid"
    )
    repair_tree_cid = _nonblank(
        repair_catalog.get("tree_cid"), "repair tree_cid"
    )

    return {
        "blind_holdout_seal_cid": seal.seal_cid,
        "blind_holdout_seal_path": str(BLIND_SEAL_RELATIVE_PATH).replace(
            "\\", "/"
        ),
        "pilot": {
            "case_ids": list(pilot_manifest.case_ids),
            "manifest_cid": pilot_manifest.manifest_cid,
            "population_kind": HOLDOUT_POP_PILOT,
            "residual_catalog_cid": pilot_catalog_cid,
            "residual_catalog_path": str(DEFAULT_CATALOG_RELATIVE_PATH).replace(
                "\\", "/"
            ),
        },
        "repair_development": {
            "case_ids": list(repair_manifest.case_ids),
            "manifest_cid": repair_manifest.manifest_cid,
            "population_cid": repair_population_cid,
            "population_kind": HOLDOUT_POP_REPAIR,
            "residual_catalog_cid": repair_catalog_cid,
            "residual_catalog_path": str(
                DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH
            ).replace("\\", "/"),
            "tree_cid": repair_tree_cid,
        },
    }


def assert_blind_seal_unopened(
    repo_root: str | Path | None = None,
    *,
    access_ledger_path: str | Path | None = None,
) -> dict[str, object]:
    """Assert the blind seal remains unopened with zero access receipts."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    seal = load_frozen_blind_holdout_seal(repository_root=root)
    # Public seal must not contain private content fields.
    raw = json.loads(
        (root / BLIND_SEAL_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    forbidden = {
        "case_ids",
        "cases",
        "source_text",
        "gold_ir",
        "labels",
        "per_case_digests",
        "semantic_hints",
        "score_bindings",
    }
    leaked = sorted(forbidden.intersection(raw))
    _require(not leaked, f"blind seal exposes forbidden fields: {leaked}")

    receipt_count = 0
    ledger_exists = False
    if access_ledger_path is not None:
        ledger = Path(access_ledger_path)
        ledger_exists = ledger.is_file()
        if ledger_exists:
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            receipts = payload.get("receipts") if isinstance(payload, Mapping) else None
            if isinstance(receipts, list):
                receipt_count = len(receipts)
    _require(
        receipt_count == 0,
        "blind access ledger must have zero receipts before baseline freeze",
    )

    return {
        "access_receipt_count": receipt_count,
        "blind_seal_cid": seal.seal_cid,
        "blind_seal_unopened": True,
        "ledger_exists": ledger_exists,
        "private_content_absent_from_public_seal": True,
        "status": "sealed_unopened",
    }


# ---------------------------------------------------------------------------
# Metric / decision / capability definitions
# ---------------------------------------------------------------------------


def metric_facet_definitions() -> dict[str, object]:
    """Preregistered metric and facet definitions."""

    return {
        "aggregation_detail": AGGREGATION_DETAIL,
        "aggregation_order": AGGREGATION_ORDER,
        "facet_names": list(FACET_NAMES),
        "failure_loss": FAILURE_LOSS,
        "loss_direction": LOSS_DIRECTION,
        "loss_metrics": list(LOSS_METRICS),
        "primary_promotion_metric": PRIMARY_PROMOTION_METRIC,
        "rule_weights": {key: float(value) for key, value in RULE_WEIGHTS.items()},
        "selection_gate_ids": list(SELECTION_GATE_IDS),
    }


def bootstrap_definition() -> dict[str, object]:
    return {
        "bootstrap_method": BOOTSTRAP_METHOD,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_unit": BOOTSTRAP_UNIT,
        "confidence_level": CONFIDENCE_LEVEL,
        "resampling_unit": RESAMPLING_UNIT,
    }


def noninferiority_and_promotion_rules() -> dict[str, object]:
    return {
        "comparison": COMPARISON_SIGN,
        "decision_outcomes": sorted(DECISION_OUTCOMES),
        "improvement_rule": IMPROVEMENT_RULE,
        "noninferiority_margin": NONINFERIORITY_MARGIN,
        "noninferiority_rule": NONINFERIORITY_RULE,
        "pilot_non_regression": {
            "metric": PRIMARY_PROMOTION_METRIC,
            "required_mean": POST_PLAT_BASELINE_E2E_MEAN,
            "rule": "pilot_mean_e2e_must_remain_0",
        },
        "promotion_requires_full_gates": PROMOTION_REQUIRES_FULL_GATES,
        "rules": {
            DECISION_IMPROVEMENT_CONFIRMED: (
                "paired blind candidate_minus_baseline CI high < 0 AND every "
                "frozen gate passes AND pilot non-regression holds AND sample "
                "is powered AND evidence is complete"
            ),
            DECISION_GENERALIZATION_NO_IMPROVEMENT: (
                "frozen noninferiority rule and no-regression gates pass, but "
                "no improvement is claimed"
            ),
            DECISION_PROMOTION_DECLINED: (
                "all other complete outcomes (including residual hold)"
            ),
            DECISION_INCOMPLETE: (
                "missing, leaked, stale, underpowered, or unauthorized evidence"
            ),
        },
        "selection_gate_ids": list(SELECTION_GATE_IDS),
        "underpowered_cannot_promote": True,
    }


def packet_token_budget_definition() -> dict[str, object]:
    return {
        "counting_method": PACKET_TOKEN_COUNTING_METHOD,
        "max_tokens": PACKET_TOKEN_BUDGET,
        "omitted_handle_coverage_required": (
            PACKET_OMITTED_HANDLE_COVERAGE_REQUIRED
        ),
        "soft_warn_tokens": PACKET_TOKEN_BUDGET_SOFT_WARN,
    }


def capability_policy_definition() -> dict[str, object]:
    return {key: dict(value) for key, value in CAPABILITY_POLICY.items()}


def failure_taxonomy_definition() -> dict[str, object]:
    return {
        "evaluation_statuses": sorted(EVALUATION_STATUSES),
        "failure_cluster_kinds": list(FAILURE_CLUSTER_KINDS),
        "non_semantic_excluded_from_score_aggregates": True,
        "non_semantic_statuses": sorted(NON_SEMANTIC_CATALOG_STATUSES),
        "semantic_score_statuses": [EVAL_STATUS_SEMANTIC_SCORED],
    }


# ---------------------------------------------------------------------------
# Experiment contract
# ---------------------------------------------------------------------------


def build_experiment_contract(
    repo_root: str | Path | None = None,
    *,
    source_tree: Mapping[str, object] | None = None,
    environment: Mapping[str, object] | None = None,
    population_bindings: Mapping[str, object] | None = None,
    blind_status: Mapping[str, object] | None = None,
    include_gitlinks_payload: bool = True,
) -> dict[str, object]:
    """Build the CID-bound ``Plateau2ExperimentContract@1`` freeze.

    Any subsequent protocol change must call
    :func:`mint_new_experiment_identity` rather than mutating this payload.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()

    tree = dict(source_tree) if source_tree is not None else capture_git_tree_binding(root)
    if not include_gitlinks_payload:
        # Keep CID stable for identity while allowing slim receipts.
        tree = {
            key: value
            for key, value in tree.items()
            if key != "gitlinks"
        }
    env = (
        dict(environment)
        if environment is not None
        else capture_environment_toolchain()
    )
    populations = (
        dict(population_bindings)
        if population_bindings is not None
        else load_population_and_residual_cids(root)
    )
    blind = (
        dict(blind_status)
        if blind_status is not None
        else assert_blind_seal_unopened(root)
    )

    arm_config = {
        "arm_id": PRODUCTION_ARM_ID,
        "constructor_id": PRODUCTION_CONSTRUCTOR_ID,
        "constructor_identity": PRODUCTION_CONSTRUCTOR_IDENTITY,
        "guidance": PRODUCTION_GUIDANCE,
        "realizer_id": PRODUCTION_REALIZER_ID,
        "realizer_identity": PRODUCTION_REALIZER_IDENTITY,
        "repair": PRODUCTION_REPAIR,
        "route": PRODUCTION_ROUTE,
        "post_plat_baseline_e2e_mean": POST_PLAT_BASELINE_E2E_MEAN,
        "post_plat_baseline_report_cid": POST_PLAT_BASELINE_REPORT_CID,
    }

    payload: dict[str, object] = {
        "arm_config": arm_config,
        "assumptions": list(DEFAULT_EXPERIMENT_ASSUMPTIONS),
        "baseline_populations": list(BASELINE_POPULATIONS),
        "blind_holdout": _plain_json(blind),
        "blind_population_out_of_scope": BLIND_POPULATION_OUT_OF_SCOPE,
        "bootstrap": bootstrap_definition(),
        "capability_policy": capability_policy_definition(),
        "decision_rules": noninferiority_and_promotion_rules(),
        "environment_toolchain": _plain_json(env),
        "evidence_id": EXPERIMENT_EVIDENCE_ID,
        "experiment_family": EXPERIMENT_FAMILY,
        "experiment_revision": EXPERIMENT_REVISION,
        "failure_taxonomy": failure_taxonomy_definition(),
        "goal_id": EXPERIMENT_GOAL_ID,
        "interface": PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE,
        "metrics": metric_facet_definitions(),
        "packet_token_budget": packet_token_budget_definition(),
        "populations": _plain_json(populations),
        "protocol_change_policy": {
            "action_on_change": (
                "mint_new_experiment_identity_and_retire_downstream_receipts"
            ),
            "downstream_receipts_retired": True,
            "mutable_after_freeze": False,
        },
        "schema_version": PLATEAU2_EXPERIMENT_CONTRACT_SCHEMA,
        "source_tree": _plain_json(tree),
        "task_id": EXPERIMENT_TASK_ID,
    }

    # Identity excludes the self-CID fields.
    identity = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "contract_cid",
            "contract_cid_codec",
            "contract_cid_scope",
            "experiment_id",
        }
    }
    contract_cid = cid_for_dag_json(_plain_json(identity))
    experiment_id = cid_for_dag_json(
        {
            "contract_cid": contract_cid,
            "experiment_family": EXPERIMENT_FAMILY,
            "experiment_revision": EXPERIMENT_REVISION,
            "task_id": EXPERIMENT_TASK_ID,
        }
    )
    payload["contract_cid"] = contract_cid
    payload["contract_cid_codec"] = CID_CODEC
    payload["contract_cid_scope"] = CONTRACT_CID_SCOPE
    payload["experiment_id"] = experiment_id
    return payload


def mint_new_experiment_identity(
    previous_contract: Mapping[str, object],
    *,
    reason: str,
    revision_bump: int = 1,
) -> dict[str, object]:
    """Mint a successor experiment identity and retire the previous one.

    Protocol changes after PLAT2-025 must use this helper rather than editing
    the frozen contract in place. Downstream receipts bound to the previous
    ``experiment_id`` / ``contract_cid`` are marked retired.
    """

    prev = dict(previous_contract)
    previous_id = _nonblank(prev.get("experiment_id"), "previous experiment_id")
    previous_cid = _nonblank(prev.get("contract_cid"), "previous contract_cid")
    previous_revision = prev.get("experiment_revision", EXPERIMENT_REVISION)
    if (
        isinstance(previous_revision, bool)
        or not isinstance(previous_revision, int)
        or previous_revision < 1
    ):
        raise HoldoutBaselineError(
            "previous experiment_revision must be a positive integer"
        )
    if (
        isinstance(revision_bump, bool)
        or not isinstance(revision_bump, int)
        or revision_bump < 1
    ):
        raise HoldoutBaselineError("revision_bump must be a positive integer")

    reason_text = _nonblank(reason, "reason")
    new_revision = previous_revision + revision_bump
    retirement = {
        "previous_contract_cid": previous_cid,
        "previous_experiment_id": previous_id,
        "reason": reason_text,
        "retired": True,
        "successor_revision": new_revision,
    }
    successor_id = cid_for_dag_json(
        {
            "experiment_family": EXPERIMENT_FAMILY,
            "experiment_revision": new_revision,
            "previous_experiment_id": previous_id,
            "reason": reason_text,
            "task_id": EXPERIMENT_TASK_ID,
        }
    )
    return {
        "experiment_family": EXPERIMENT_FAMILY,
        "experiment_id": successor_id,
        "experiment_revision": new_revision,
        "previous_contract_cid": previous_cid,
        "previous_experiment_id": previous_id,
        "retired_receipts_policy": (
            "all receipts bound to previous_experiment_id are invalid"
        ),
        "retirement": retirement,
        "task_id": EXPERIMENT_TASK_ID,
    }


def parse_experiment_contract(
    value: object,
    *,
    require_blind_unopened: bool = True,
) -> dict[str, object]:
    """Validate a ``Plateau2ExperimentContract@1`` payload."""

    data = dict(_mapping(value, "experiment contract"))
    _require(
        data.get("interface") == PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE,
        "experiment contract interface mismatch",
    )
    _require(
        data.get("schema_version") == PLATEAU2_EXPERIMENT_CONTRACT_SCHEMA,
        "experiment contract schema mismatch",
    )
    _require(
        data.get("task_id") == EXPERIMENT_TASK_ID,
        "experiment contract task_id mismatch",
    )
    arm = _mapping(data.get("arm_config"), "arm_config")
    _require(
        arm.get("arm_id") == PRODUCTION_ARM_ID,
        "arm_config.arm_id must be the production deterministic arm",
    )
    metrics = _mapping(data.get("metrics"), "metrics")
    _require(
        metrics.get("aggregation_order") == AGGREGATION_ORDER,
        "metrics.aggregation_order must be per-case-first macro mean",
    )
    bootstrap = _mapping(data.get("bootstrap"), "bootstrap")
    _require(
        bootstrap.get("bootstrap_method") == BOOTSTRAP_METHOD,
        "bootstrap method mismatch",
    )
    _require(
        int(bootstrap.get("bootstrap_samples", 0)) == BOOTSTRAP_SAMPLES,
        "bootstrap_samples mismatch",
    )
    _require(
        float(bootstrap.get("confidence_level", 0.0)) == CONFIDENCE_LEVEL,
        "confidence_level mismatch",
    )
    rules = _mapping(data.get("decision_rules"), "decision_rules")
    _require(
        float(rules.get("noninferiority_margin", -1.0))
        == NONINFERIORITY_MARGIN,
        "noninferiority_margin mismatch",
    )
    budget = _mapping(data.get("packet_token_budget"), "packet_token_budget")
    _require(
        int(budget.get("max_tokens", 0)) == PACKET_TOKEN_BUDGET,
        "packet_token_budget.max_tokens mismatch",
    )
    taxonomy = _mapping(data.get("failure_taxonomy"), "failure_taxonomy")
    statuses = set(_array(taxonomy.get("evaluation_statuses"), "evaluation_statuses"))
    _require(
        statuses == set(EVALUATION_STATUSES),
        "failure taxonomy evaluation_statuses mismatch",
    )
    capability = _mapping(data.get("capability_policy"), "capability_policy")
    for name, expected in CAPABILITY_POLICY.items():
        entry = _mapping(capability.get(name), f"capability_policy.{name}")
        if expected.get("semantic_authority") is False:
            _require(
                entry.get("semantic_authority") is False,
                f"capability_policy.{name}.semantic_authority must be false",
            )
    populations = _mapping(data.get("populations"), "populations")
    _require("pilot" in populations, "populations.pilot required")
    _require(
        "repair_development" in populations,
        "populations.repair_development required",
    )
    source_tree = _mapping(data.get("source_tree"), "source_tree")
    _nonblank(source_tree.get("commit"), "source_tree.commit")
    _nonblank(source_tree.get("tree"), "source_tree.tree")
    _cid(source_tree.get("gitlinks_cid"), "source_tree.gitlinks_cid")

    identity = {
        key: value
        for key, value in data.items()
        if key
        not in {
            "contract_cid",
            "contract_cid_codec",
            "contract_cid_scope",
            "experiment_id",
        }
    }
    expected_cid = cid_for_dag_json(_plain_json(identity))
    _require(
        data.get("contract_cid") == expected_cid,
        "contract_cid does not match payload identity",
    )
    _cid(data.get("experiment_id"), "experiment_id")

    if require_blind_unopened:
        blind = _mapping(data.get("blind_holdout"), "blind_holdout")
        _require(
            blind.get("blind_seal_unopened") is True,
            "blind seal must remain unopened",
        )
        _require(
            int(blind.get("access_receipt_count", -1)) == 0,
            "blind access_receipt_count must be zero",
        )

    return data


# ---------------------------------------------------------------------------
# Deterministic baseline scoring
# ---------------------------------------------------------------------------


def _default_constructor():
    from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
        TypedDeonticCanonicalConstructor,
    )

    return TypedDeonticCanonicalConstructor()


def _default_realizer():
    from benchmarks.semantic_roundtrip.realizers.deterministic import (
        CanonicalDeterministicRealizer,
    )

    return CanonicalDeterministicRealizer()


def score_deterministic_case(
    case: MatrixCase,
    *,
    constructor: object | None = None,
    realizer: object | None = None,
) -> dict[str, object]:
    """Score one case on the production deterministic arm.

    Records forward/cycle/e2e losses, facet survival, selection gates, and an
    evaluation status from the frozen taxonomy.
    """

    if not isinstance(case, MatrixCase):
        raise HoldoutBaselineError("case must be MatrixCase")

    ctor = constructor or _default_constructor()
    det = realizer or _default_realizer()
    construct = getattr(ctor, "construct", None)
    realize = getattr(det, "realize", None)
    if not callable(construct) or not callable(realize):
        raise HoldoutBaselineError(
            "constructor/realizer must provide construct()/realize()"
        )

    try:
        initial = construct(
            ConstructorRequest(
                case.source_text, case.allowed_atom_vocabulary, {}
            )
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return _failed_case_record(
            case,
            status=EVAL_STATUS_RUNTIME_FAILED,
            reason="constructor_exception",
            detail=f"{type(exc).__name__}: {exc}",
        )

    if (
        not hasattr(initial, "status")
        or initial.status is ComponentStatus.FAILED
        or getattr(initial, "canonical_ir", None) is None
    ):
        return _failed_case_record(
            case,
            status=EVAL_STATUS_RUNTIME_FAILED,
            reason="constructor_failed",
            detail=str(getattr(initial, "failure_detail", None) or "construct failed"),
        )

    l1 = initial.canonical_ir
    try:
        realized = realize(
            RealizerRequest(l1, case.allowed_atom_vocabulary, {})
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return _failed_case_record(
            case,
            status=EVAL_STATUS_RUNTIME_FAILED,
            reason="realizer_exception",
            detail=f"{type(exc).__name__}: {exc}",
        )

    text = getattr(realized, "text", None)
    if (
        not hasattr(realized, "status")
        or realized.status is ComponentStatus.FAILED
        or not isinstance(text, str)
        or not text.strip()
    ):
        return _failed_case_record(
            case,
            status=EVAL_STATUS_RUNTIME_FAILED,
            reason="realizer_failed",
            detail=str(getattr(realized, "failure_detail", None) or "realize failed"),
        )

    try:
        recompiled = construct(
            ConstructorRequest(text, case.allowed_atom_vocabulary, {})
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return _failed_case_record(
            case,
            status=EVAL_STATUS_RUNTIME_FAILED,
            reason="recompile_exception",
            detail=f"{type(exc).__name__}: {exc}",
        )

    if (
        not hasattr(recompiled, "status")
        or recompiled.status is ComponentStatus.FAILED
        or getattr(recompiled, "canonical_ir", None) is None
    ):
        return _failed_case_record(
            case,
            status=EVAL_STATUS_RUNTIME_FAILED,
            reason="recompile_failed",
            detail=str(
                getattr(recompiled, "failure_detail", None) or "recompile failed"
            ),
        )

    l2 = recompiled.canonical_ir
    result = make_round_trip_result(case.gold_ir, l1, text, l2)
    copy = source_copy_diagnostics(case.source_text, text)
    polarity = polarity_diagnostics(case.gold_ir, l2)
    forward_cmp = compare_semantic_ir(case.gold_ir, l1)
    cycle_cmp = compare_semantic_ir(l1, l2)
    e2e_cmp = compare_semantic_ir(case.gold_ir, l2)

    gates = {
        "full_coverage": bool(result.is_complete),
        "source_copy_exclusion": bool(copy.get("gate_passed")),
        "polarity_preservation": bool(polarity.get("gate_passed")),
    }
    gates["selection_eligible"] = all(
        gates[name] for name in ("full_coverage", "source_copy_exclusion", "polarity_preservation")
    )

    facets = {
        "forward": dict(forward_cmp["facet_survival"]),  # type: ignore[arg-type]
        "cycle": dict(cycle_cmp["facet_survival"]),  # type: ignore[arg-type]
        "end_to_end": dict(e2e_cmp["facet_survival"]),  # type: ignore[arg-type]
    }

    return {
        "arm_id": PRODUCTION_ARM_ID,
        "case_cid": case.case_cid,
        "case_id": case.case_id,
        "evaluation_status": EVAL_STATUS_SEMANTIC_SCORED,
        "evaluation_status_reason": "success",
        "facets": facets,
        "gates": gates,
        "losses": {
            "cycle": float(result.cycle_loss),
            "end_to_end": float(result.end_to_end_loss),
            "forward": float(result.forward_loss),
        },
        "polarity": {
            "gate_passed": bool(polarity.get("gate_passed")),
            "inversion_count": int(polarity.get("inversion_count") or 0)
            if isinstance(polarity.get("inversion_count"), (int, float))
            else None,
        },
        "semantic_score_eligible": True,
        "source_copy": {
            "copy_risk": bool(copy.get("copy_risk")),
            "gate_passed": bool(copy.get("gate_passed")),
            "shared_8gram_precision": copy.get("shared_8gram_precision"),
        },
    }


def _failed_case_record(
    case: MatrixCase,
    *,
    status: str,
    reason: str,
    detail: str,
) -> dict[str, object]:
    _require(status in EVALUATION_STATUSES, f"unknown evaluation status {status!r}")
    return {
        "arm_id": PRODUCTION_ARM_ID,
        "case_cid": case.case_cid,
        "case_id": case.case_id,
        "detail": detail,
        "evaluation_status": status,
        "evaluation_status_reason": reason,
        "facets": None,
        "gates": {
            "full_coverage": False,
            "polarity_preservation": False,
            "selection_eligible": False,
            "source_copy_exclusion": False,
        },
        "losses": {
            "cycle": FAILURE_LOSS,
            "end_to_end": FAILURE_LOSS,
            "forward": FAILURE_LOSS,
        },
        "polarity": None,
        "semantic_score_eligible": status == EVAL_STATUS_SEMANTIC_SCORED,
        "source_copy": None,
    }


def _load_population_cases(
    population_kind: str,
    repo_root: Path,
) -> tuple[MatrixCase, ...]:
    if population_kind == POPULATION_KIND_PILOT:
        path = repo_root / PILOT_CASES_RELATIVE_PATH
        cases = load_matrix_cases(path)
        # Preserve sealed pilot order.
        by_id = {case.case_id: case for case in cases}
        ordered = []
        for case_id in PILOT_CASE_IDS:
            _require(case_id in by_id, f"missing pilot case {case_id!r}")
            ordered.append(by_id[case_id])
        return tuple(ordered)
    if population_kind == POPULATION_KIND_REPAIR_DEVELOPMENT:
        path = repo_root / REPAIR_DEV_CASES_RELATIVE_PATH
        return load_matrix_cases(path)
    raise HoldoutBaselineError(
        f"baseline scoring rejects population_kind {population_kind!r}; "
        "only pilot and repair_development are in scope"
    )


def _residual_failure_clusters(
    residual_catalog: Mapping[str, object] | None,
) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = {
        "residual_field_mismatch": [],
        "residual_missing_rule": [],
        "residual_extra_rule": [],
    }
    if residual_catalog is None:
        return clusters
    residuals = residual_catalog.get("residuals")
    if not isinstance(residuals, list):
        return clusters
    for item in residuals:
        if not isinstance(item, Mapping):
            continue
        case_id = item.get("case_id")
        kind = item.get("residual_kind") or item.get("kind")
        if not isinstance(case_id, str):
            continue
        if kind == "field_mismatch":
            clusters["residual_field_mismatch"].append(case_id)
        elif kind == "missing_rule":
            clusters["residual_missing_rule"].append(case_id)
        elif kind == "extra_rule":
            clusters["residual_extra_rule"].append(case_id)
    for key, values in clusters.items():
        clusters[key] = sorted(set(values))
    return clusters


def _build_failure_clusters(
    case_records: Sequence[Mapping[str, object]],
    *,
    residual_catalog: Mapping[str, object] | None = None,
) -> dict[str, object]:
    clusters: dict[str, list[str]] = {kind: [] for kind in FAILURE_CLUSTER_KINDS}
    for record in case_records:
        case_id = str(record["case_id"])
        status = str(record.get("evaluation_status"))
        if status == EVAL_STATUS_NOT_MEASURED:
            clusters["evaluation_not_measured"].append(case_id)
        elif status == EVAL_STATUS_RUNTIME_FAILED:
            clusters["evaluation_runtime_failed"].append(case_id)
        elif status == EVAL_STATUS_UNSUPPORTED:
            clusters["evaluation_unsupported"].append(case_id)

        if not record.get("semantic_score_eligible"):
            continue
        losses = record.get("losses") or {}
        if isinstance(losses, Mapping):
            if float(losses.get("forward", 0.0) or 0.0) > 0.0:
                clusters["loss_forward_nonzero"].append(case_id)
            if float(losses.get("cycle", 0.0) or 0.0) > 0.0:
                clusters["loss_cycle_nonzero"].append(case_id)
            if float(losses.get("end_to_end", 0.0) or 0.0) > 0.0:
                clusters["loss_end_to_end_nonzero"].append(case_id)
        gates = record.get("gates") or {}
        if isinstance(gates, Mapping):
            if not gates.get("full_coverage"):
                clusters["gate_full_coverage"].append(case_id)
            if not gates.get("source_copy_exclusion"):
                clusters["gate_source_copy_exclusion"].append(case_id)
            if not gates.get("polarity_preservation"):
                clusters["gate_polarity_preservation"].append(case_id)
        facets = record.get("facets") or {}
        e2e_facets = facets.get("end_to_end") if isinstance(facets, Mapping) else None
        if isinstance(e2e_facets, Mapping):
            for facet in FACET_NAMES:
                value = e2e_facets.get(facet)
                if isinstance(value, (int, float)) and float(value) < 1.0:
                    clusters[f"facet_{facet}"].append(case_id)

    residual_clusters = _residual_failure_clusters(residual_catalog)
    for key, values in residual_clusters.items():
        clusters[key] = sorted(set(clusters.get(key, []) + values))

    return {
        kind: sorted(set(values))
        for kind, values in clusters.items()
        if values
    }


def _macro_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 9)


def _population_aggregates(
    case_records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    status_counts: Counter[str] = Counter()
    scored_losses: dict[str, list[float]] = {
        "forward": [],
        "cycle": [],
        "end_to_end": [],
    }
    gate_pass_counts = {
        "full_coverage": 0,
        "source_copy_exclusion": 0,
        "polarity_preservation": 0,
        "selection_eligible": 0,
    }
    for record in case_records:
        status = str(record.get("evaluation_status"))
        status_counts[status] += 1
        if not record.get("semantic_score_eligible"):
            continue
        losses = record.get("losses") or {}
        if isinstance(losses, Mapping):
            for key in scored_losses:
                scored_losses[key].append(float(losses[key]))  # type: ignore[index]
        gates = record.get("gates") or {}
        if isinstance(gates, Mapping):
            for gate_name in gate_pass_counts:
                if gates.get(gate_name):
                    gate_pass_counts[gate_name] += 1

    scored_n = status_counts.get(EVAL_STATUS_SEMANTIC_SCORED, 0)
    return {
        "aggregation": AGGREGATION_ORDER,
        "case_count": len(case_records),
        "gate_pass_counts": gate_pass_counts,
        "means": {
            key: _macro_mean(vals) for key, vals in scored_losses.items()
        },
        "scored_case_count": scored_n,
        "status_counts": {
            status: int(status_counts.get(status, 0))
            for status in sorted(EVALUATION_STATUSES)
        },
    }


def run_deterministic_baseline(
    repo_root: str | Path | None = None,
    *,
    populations: Sequence[str] = BASELINE_POPULATIONS,
    constructor: object | None = None,
    realizer: object | None = None,
    residual_catalogs: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, dict[str, object]]:
    """Run the deterministic baseline on pilots and repair-development only.

    Blind populations are rejected. Returns a mapping of population kind to
    case records, aggregates, and failure clusters.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    ctor = constructor or _default_constructor()
    det = realizer or _default_realizer()

    results: dict[str, dict[str, object]] = {}
    for kind in populations:
        if kind not in BASELINE_POPULATIONS:
            raise HoldoutBaselineError(
                f"baseline scoring rejects population {kind!r}; blind and "
                "other populations are out of scope for PLAT2-025"
            )
        cases = _load_population_cases(kind, root)
        records = [
            score_deterministic_case(case, constructor=ctor, realizer=det)
            for case in cases
        ]
        residual = None
        if residual_catalogs is not None:
            residual = residual_catalogs.get(kind)
        elif kind == POPULATION_KIND_REPAIR_DEVELOPMENT:
            residual = load_repair_dev_residual_catalog(
                root / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH,
                repo_root=root,
            )
        elif kind == POPULATION_KIND_PILOT:
            residual = load_plateau_residual_catalog(
                root / DEFAULT_CATALOG_RELATIVE_PATH, repo_root=root
            )
        results[kind] = {
            "aggregates": _population_aggregates(records),
            "cases": records,
            "failure_clusters": _build_failure_clusters(
                records, residual_catalog=residual
            ),
            "population_kind": kind,
        }
    return results


# ---------------------------------------------------------------------------
# Baseline report (EvalRepairMatrixReport@1)
# ---------------------------------------------------------------------------


def build_repair_dev_baseline_report(
    repo_root: str | Path | None = None,
    *,
    contract: Mapping[str, object] | None = None,
    population_results: Mapping[str, Mapping[str, object]] | None = None,
    run_scoring: bool = True,
) -> dict[str, object]:
    """Build the frozen repair-development baseline report.

    The report binds the experiment contract, scores pilots and
    repair-development only, and records that the blind seal is unopened.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    contract_payload = (
        dict(contract)
        if contract is not None
        else build_experiment_contract(root)
    )
    parse_experiment_contract(contract_payload, require_blind_unopened=True)

    if population_results is None:
        if not run_scoring:
            raise HoldoutBaselineError(
                "population_results required when run_scoring is False"
            )
        population_results = run_deterministic_baseline(root)
    else:
        for kind in population_results:
            if kind not in BASELINE_POPULATIONS:
                raise HoldoutBaselineError(
                    f"baseline report rejects population {kind!r}"
                )

    pilot_block = population_results.get(POPULATION_KIND_PILOT)
    repair_block = population_results.get(POPULATION_KIND_REPAIR_DEVELOPMENT)
    _require(pilot_block is not None, "pilot population results required")
    _require(
        repair_block is not None,
        "repair_development population results required",
    )
    assert pilot_block is not None
    assert repair_block is not None

    pilot_mean = float(
        _mapping(pilot_block.get("aggregates"), "pilot aggregates")
        .get("means", {})
        .get("end_to_end", 1.0)  # type: ignore[union-attr]
    )
    # Soft check: pilot non-regression is a promotion gate; record it.
    pilot_non_regressed = abs(pilot_mean - POST_PLAT_BASELINE_E2E_MEAN) < 1e-9

    blind = assert_blind_seal_unopened(root)

    payload: dict[str, object] = {
        "arm_id": PRODUCTION_ARM_ID,
        "blind_holdout": _plain_json(blind),
        "contract_cid": contract_payload["contract_cid"],
        "experiment_id": contract_payload["experiment_id"],
        "interface": EVAL_REPAIR_MATRIX_REPORT_INTERFACE,
        "kind": "plateau2_repair_dev_deterministic_baseline",
        "populations": _plain_json(
            {
                POPULATION_KIND_PILOT: pilot_block,
                POPULATION_KIND_REPAIR_DEVELOPMENT: repair_block,
            }
        ),
        "post_plat_baseline_e2e_mean": POST_PLAT_BASELINE_E2E_MEAN,
        "post_plat_baseline_report_cid": POST_PLAT_BASELINE_REPORT_CID,
        "promotion_gates_snapshot": {
            "pilot_mean_e2e": pilot_mean,
            "pilot_non_regressed": pilot_non_regressed,
            "promotion_requires_full_gates": PROMOTION_REQUIRES_FULL_GATES,
            "selection_gate_ids": list(SELECTION_GATE_IDS),
        },
        "schema_version": EVAL_REPAIR_MATRIX_REPORT_SCHEMA,
        "scoped_populations": list(BASELINE_POPULATIONS),
        "task_id": EXPERIMENT_TASK_ID,
        "title": "PLAT2-025 repair-development deterministic baseline",
    }

    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"report_cid", "report_cid_codec", "report_cid_scope"}
    }
    report_cid = cid_for_dag_json(_plain_json(identity))
    payload["report_cid"] = report_cid
    payload["report_cid_codec"] = CID_CODEC
    payload["report_cid_scope"] = REPORT_CID_SCOPE
    return payload


def parse_repair_dev_baseline_report(
    value: object,
    *,
    require_blind_unopened: bool = True,
) -> dict[str, object]:
    """Validate an ``EvalRepairMatrixReport@1`` repair-dev baseline report."""

    data = dict(_mapping(value, "baseline report"))
    _require(
        data.get("interface") == EVAL_REPAIR_MATRIX_REPORT_INTERFACE,
        "baseline report interface mismatch",
    )
    _require(
        data.get("schema_version") == EVAL_REPAIR_MATRIX_REPORT_SCHEMA,
        "baseline report schema mismatch",
    )
    _require(data.get("task_id") == EXPERIMENT_TASK_ID, "task_id mismatch")
    _require(
        data.get("arm_id") == PRODUCTION_ARM_ID,
        "baseline report arm_id mismatch",
    )
    _cid(data.get("contract_cid"), "contract_cid")
    _cid(data.get("experiment_id"), "experiment_id")
    populations = _mapping(data.get("populations"), "populations")
    for kind in BASELINE_POPULATIONS:
        block = _mapping(populations.get(kind), f"populations.{kind}")
        cases = _array(block.get("cases"), f"populations.{kind}.cases")
        for index, case in enumerate(cases):
            case_map = _mapping(case, f"populations.{kind}.cases[{index}]")
            status = case_map.get("evaluation_status")
            _require(
                status in EVALUATION_STATUSES,
                f"case {case_map.get('case_id')!r} has unknown evaluation_status",
            )
            losses = _mapping(
                case_map.get("losses"),
                f"populations.{kind}.cases[{index}].losses",
            )
            for loss_name in LOSS_METRICS:
                _finite_unit(
                    losses.get(loss_name),
                    f"populations.{kind}.cases[{index}].losses.{loss_name}",
                )
            gates = _mapping(
                case_map.get("gates"),
                f"populations.{kind}.cases[{index}].gates",
            )
            for gate in (
                "full_coverage",
                "source_copy_exclusion",
                "polarity_preservation",
                "selection_eligible",
            ):
                _require(
                    isinstance(gates.get(gate), bool),
                    f"gate {gate} must be boolean",
                )
        _mapping(block.get("aggregates"), f"populations.{kind}.aggregates")
        _mapping(
            block.get("failure_clusters"),
            f"populations.{kind}.failure_clusters",
        )

    forbidden_pops = set(populations) - set(BASELINE_POPULATIONS)
    _require(
        not forbidden_pops,
        f"baseline report must not include populations {sorted(forbidden_pops)}",
    )

    if require_blind_unopened:
        blind = _mapping(data.get("blind_holdout"), "blind_holdout")
        _require(blind.get("blind_seal_unopened") is True, "blind must be unopened")
        _require(
            int(blind.get("access_receipt_count", -1)) == 0,
            "access receipts must be zero",
        )

    identity = {
        key: value
        for key, value in data.items()
        if key not in {"report_cid", "report_cid_codec", "report_cid_scope"}
    }
    expected = cid_for_dag_json(_plain_json(identity))
    _require(
        data.get("report_cid") == expected,
        "report_cid does not match payload identity",
    )
    return data


def load_repair_dev_baseline_report(
    path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, object]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    report_path = (
        Path(path)
        if path is not None
        else root / DEFAULT_BASELINE_REPORT_RELATIVE_PATH
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return parse_repair_dev_baseline_report(payload)


def write_repair_dev_baseline_report(
    path: str | Path,
    *,
    report: Mapping[str, object] | None = None,
    repo_root: str | Path | None = None,
    run_scoring: bool = True,
) -> dict[str, object]:
    """Write the baseline report atomically and return the sealed payload."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    payload = (
        dict(report)
        if report is not None
        else build_repair_dev_baseline_report(root, run_scoring=run_scoring)
    )
    parse_repair_dev_baseline_report(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".repair_dev_baseline.",
        suffix=".json",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return payload


def build_frozen_baseline_bundle(
    repo_root: str | Path | None = None,
    *,
    run_scoring: bool = True,
) -> dict[str, object]:
    """Build contract + baseline report as one freeze bundle."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    contract = build_experiment_contract(root)
    report = build_repair_dev_baseline_report(
        root, contract=contract, run_scoring=run_scoring
    )
    return {
        "contract": contract,
        "report": report,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PLAT2-025 freeze repair-development baseline and experiment contract"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="repository root (default: inferred from module path)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="path for repair_dev_baseline.json",
    )
    parser.add_argument(
        "--skip-scoring",
        action="store_true",
        help="build contract only (no deterministic scoring)",
    )
    parser.add_argument(
        "--contract-only",
        action="store_true",
        help="print the experiment contract JSON to stdout",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.repo_root or _repo_root()

    if args.contract_only:
        contract = build_experiment_contract(root)
        parse_experiment_contract(contract)
        print(json.dumps(contract, indent=2, sort_keys=True))
        return 0

    if args.skip_scoring:
        contract = build_experiment_contract(root)
        print(json.dumps({"contract_cid": contract["contract_cid"]}, indent=2))
        return 0

    out = args.output or (root / DEFAULT_BASELINE_REPORT_RELATIVE_PATH)
    report = write_repair_dev_baseline_report(out, repo_root=root, run_scoring=True)
    print(
        json.dumps(
            {
                "report_cid": report["report_cid"],
                "contract_cid": report["contract_cid"],
                "experiment_id": report["experiment_id"],
                "path": str(out),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "AGGREGATION_ORDER",
    "BASELINE_POPULATIONS",
    "BOOTSTRAP_METHOD",
    "BOOTSTRAP_SAMPLES",
    "BOOTSTRAP_SEED",
    "CAPABILITY_POLICY",
    "CONFIDENCE_LEVEL",
    "DEFAULT_BASELINE_REPORT_RELATIVE_PATH",
    "EVALUATION_STATUSES",
    "EVAL_REPAIR_MATRIX_REPORT_INTERFACE",
    "EVAL_REPAIR_MATRIX_REPORT_SCHEMA",
    "EVAL_STATUS_NOT_MEASURED",
    "EVAL_STATUS_RUNTIME_FAILED",
    "EVAL_STATUS_SEMANTIC_SCORED",
    "EVAL_STATUS_UNSUPPORTED",
    "EXPERIMENT_FAMILY",
    "EXPERIMENT_TASK_ID",
    "FAILURE_CLUSTER_KINDS",
    "HoldoutBaselineError",
    "NONINFERIORITY_MARGIN",
    "PACKET_TOKEN_BUDGET",
    "PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE",
    "PLATEAU2_EXPERIMENT_CONTRACT_SCHEMA",
    "POST_PLAT_BASELINE_E2E_MEAN",
    "POST_PLAT_BASELINE_REPORT_CID",
    "PRODUCTION_ARM_ID",
    "SELECTION_GATE_IDS",
    "assert_blind_seal_unopened",
    "bootstrap_definition",
    "build_experiment_contract",
    "build_frozen_baseline_bundle",
    "build_repair_dev_baseline_report",
    "capability_policy_definition",
    "capture_environment_toolchain",
    "capture_git_tree_binding",
    "failure_taxonomy_definition",
    "load_population_and_residual_cids",
    "load_repair_dev_baseline_report",
    "main",
    "metric_facet_definitions",
    "mint_new_experiment_identity",
    "noninferiority_and_promotion_rules",
    "packet_token_budget_definition",
    "parse_experiment_contract",
    "parse_repair_dev_baseline_report",
    "run_deterministic_baseline",
    "score_deterministic_case",
    "write_repair_dev_baseline_report",
]
