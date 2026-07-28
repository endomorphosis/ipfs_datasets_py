"""PLAT2-060 one-shot blind-holdout evaluation and promotion decision.

Interfaces:
* ``SemanticRoundtripHoldoutAuthorization@1`` — consumed (issued by PLAT2-055)
* ``HoldoutAccessAudit@1`` — single-use path-free append-only access receipts
* ``EvalRepairMatrixReport@1`` — terminal blind remeasure report
* ``CanonicalCompilerDecision@1`` — promotion decision under frozen rules

Doctrine (PLAT2-G060 / PLAT2-060):

* Custodian grants **one** path-free, append-only access receipt only after
  validating authorization and frozen freeze/seal identities.
* Evaluation runtime may receive blind **source** text; the scorer may receive
  **gold**. Implementation agents, prompts, packets, teachers, caches, and
  tuning worktrees receive **neither** gold nor blind diagnostics.
* Frozen baseline and candidate run on **identical** blind cases under
  isolated namespaces with preregistered per-case-first paired analysis.
* Publish terminal coverage, per-case/facet forward/cycle/e2e loss,
  coverage/polarity/source-copy gates, paired delta + CI, structural receipts
  as separate non-semantic evidence, resource/context summaries, all
  missingness, and access-ledger CID.
* ``improvement_confirmed`` requires CI high < 0 plus all gates;
  ``generalization_confirmed_no_improvement`` requires the predeclared
  noninferiority rule plus no regressions and makes **no** improvement claim;
  all other complete outcomes decline promotion.
* No code, prompt, threshold, method selection, or rerun changes after access.
* Post-hoc residuals may seed a **new** board only with a newly authored blind
  population.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.holdout_baseline import (
    AGGREGATION_DETAIL,
    AGGREGATION_ORDER,
    BOOTSTRAP_METHOD,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    DECISION_GENERALIZATION_NO_IMPROVEMENT,
    DECISION_IMPROVEMENT_CONFIRMED,
    DECISION_INCOMPLETE,
    DECISION_OUTCOMES,
    DECISION_PROMOTION_DECLINED,
    EVAL_REPAIR_MATRIX_REPORT_INTERFACE,
    EVAL_STATUS_NOT_MEASURED,
    EVAL_STATUS_RUNTIME_FAILED,
    EVAL_STATUS_SEMANTIC_SCORED,
    EVAL_STATUS_UNSUPPORTED,
    FACET_NAMES,
    FAILURE_LOSS,
    LOSS_METRICS,
    NONINFERIORITY_MARGIN,
    NONINFERIORITY_RULE,
    POST_PLAT_BASELINE_E2E_MEAN,
    POST_PLAT_BASELINE_REPORT_CID,
    PRIMARY_PROMOTION_METRIC,
    PRODUCTION_ARM_ID,
    PRODUCTION_CONSTRUCTOR_IDENTITY,
    PRODUCTION_REALIZER_IDENTITY,
    RESAMPLING_UNIT,
    SELECTION_GATE_IDS,
    capture_environment_toolchain,
    noninferiority_and_promotion_rules,
    score_deterministic_case,
)
from benchmarks.semantic_roundtrip.holdout_candidate_freeze import (
    DEFAULT_AUTHORIZATION_RELATIVE_PATH,
    DEFAULT_FREEZE_RELATIVE_PATH,
    assert_authorization_still_valid,
    load_candidate_freeze,
    load_holdout_authorization,
    parse_candidate_freeze,
    parse_holdout_authorization,
)
from benchmarks.semantic_roundtrip.holdout_protocol import (
    ACCESS_LEDGER_SCHEMA,
    ACCESS_RECEIPT_SCHEMA,
    AUTHORIZATION_GOAL_ID,
    AppendOnlyAccessLedger,
    BlindHoldoutSeal,
    HoldoutAccessAuthorization,
    HoldoutAccessReceipt,
    HoldoutProtocolError,
    HOLDOUT_ACCESS_AUDIT_INTERFACE,
    POPULATION_KIND_BLIND_HOLDOUT,
    POPULATION_KIND_PILOT,
    assert_promotion_sample_size_gate,
    load_frozen_blind_holdout_seal,
    materialize_preregistered_blind_records,
    release_blind_manifest,
    request_blind_access,
)
from benchmarks.semantic_roundtrip.matrix import (
    MatrixCase,
    load_matrix_cases,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    PILOT_CASE_IDS,
    PILOT_CASES_RELATIVE_PATH,
)
from benchmarks.semantic_roundtrip.statistics import (
    _bootstrap_delta,
    _derived_seed,
    _mean,
    _rounded,
)


# ---------------------------------------------------------------------------
# Interfaces / schemas / task identity
# ---------------------------------------------------------------------------

EVAL_TASK_ID: Final = "PLAT2-060"
EVAL_GOAL_ID: Final = "PLAT2-G060"
EVAL_EVIDENCE_ID: Final = "PLAT2EV060MEAS"
EVAL_REVISION: Final = 1
BOARD_NAMESPACE: Final = "semantic-roundtrip-plateau-holdout-v2"
BUNDLE_ID: Final = "semantic-roundtrip/plateau-holdout/remeasure"

HOLDOUT_REMEASURE_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-holdout-remeasure.v1"
)
HOLDOUT_PROMOTION_DECISION_INTERFACE: Final = "CanonicalCompilerDecision@1"
HOLDOUT_PROMOTION_DECISION_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-holdout-promotion-decision.v1"
)
ACCESS_LEDGER_EXPORT_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau2-holdout-access-ledger.v1"
)
ACCESS_LEDGER_EXPORT_INTERFACE: Final = "HoldoutAccessAudit@1"

REPORT_CID_SCOPE: Final = "payload_without_report_cid"
DECISION_CID_SCOPE: Final = "payload_without_decision_cid"
LEDGER_CID_SCOPE: Final = "payload_without_ledger_cid"
CID_CODEC: Final = "dag-json"

DEFAULT_ACCESS_LEDGER_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "plateau2_holdout_access_ledger.json"
)
DEFAULT_REMEASURE_RELATIVE_PATH: Final = Path(
    "docs/performance_snapshots/"
    "2026-07-28_semantic_roundtrip_holdout_remeasure.json"
)
DEFAULT_PROMOTION_DECISION_RELATIVE_PATH: Final = Path(
    "docs/performance_snapshots/"
    "2026-07-28_semantic_roundtrip_holdout_promotion_decision.json"
)
DEFAULT_RESULTS_DOCS_RELATIVE_PATH: Final = Path(
    "docs/benchmarks/semantic_roundtrip_holdout_results.md"
)

BASELINE_ROLE: Final = "baseline"
CANDIDATE_ROLE: Final = "candidate"
BASELINE_NAMESPACE_PREFIX: Final = "plat2-060/baseline"
CANDIDATE_NAMESPACE_PREFIX: Final = "plat2-060/candidate"
EXECUTOR_ID: Final = "plat2-060-custodian-evaluator"

# Fields that must never leave the scorer/runtime boundary into public reports,
# prompts, packets, teachers, caches, or agent-facing artifacts.
_PRIVATE_CONTENT_KEYS: Final = frozenset(
    {
        "source_text",
        "source_texts",
        "gold_ir",
        "gold_irs",
        "gold_binding",
        "blind_gold",
        "blind_source",
        "blind_diagnostics",
        "diagnostics",
        "score_bindings",
        "semantic_hints",
        "allowed_atoms",
        "allowed_atom_vocabulary",
        "l1",
        "l2",
        "reconstruction_text",
        "realized_text",
        "private_records",
        "private_manifest",
        "private_bundle",
    }
)

IMMUTABLE_REPLACEMENT_REPORT_PATH: Final = Path(
    "docs/performance_snapshots/"
    "2026-07-27_semantic_roundtrip_composition_replacement.json"
)
IMMUTABLE_REPLACEMENT_REPORT_CID: Final = (
    "baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga"
)
PILOT_PROMOTION_DECISION_PATH: Final = Path(
    "docs/performance_snapshots/"
    "2026-07-27_semantic_roundtrip_plateau_break_promotion_decision.json"
)

DEFAULT_EVAL_ASSUMPTIONS: Final = (
    "production remains typed_deontic → IR → deterministic realizer",
    "single-use custodian access only after PLAT2-055 authorization",
    "blind gold and diagnostics never enter agents/prompts/packets/teachers/"
    "caches/tuning worktrees",
    "baseline and candidate scored on identical blind cases under isolated "
    "namespaces with per-case-first paired bootstrap",
    "improvement_confirmed requires e2e CI high < 0 plus full gates",
    "generalization_confirmed_no_improvement requires noninferiority and no "
    "regressions and makes no improvement claim",
    "all other complete outcomes decline promotion",
    "no post-access code/prompt/threshold/method/rerun changes",
    "post-hoc residuals may seed only a new board with a fresh blind population",
    "Hammer/cvc5/Lean structural receipts are non-semantic evidence only",
)


class HoldoutEvaluationError(ContractError):
    """Raised when the one-shot blind evaluation protocol fails closed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require(condition: object, message: str) -> None:
    if not condition:
        raise HoldoutEvaluationError(message)


def _nonblank(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HoldoutEvaluationError(f"{path} must be a nonblank string")
    return value.strip()


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HoldoutEvaluationError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise HoldoutEvaluationError(f"{path} must be an array")
    return value


def _finite_unit(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise HoldoutEvaluationError(f"{path} must be a finite unit interval number")
    return float(value)


def _cid(value: object, path: str) -> str:
    text = _nonblank(value, path)
    try:
        validate_cid(text)
    except Exception as exc:  # pragma: no cover - validate_cid raises ContractError
        raise HoldoutEvaluationError(f"{path} is not a valid CID") from exc
    return text


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    return value


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        _plain_json(dict(payload)),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    if not encoded.endswith("\n"):
        encoded += "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
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
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "+00:00")
    )


def _strip_private_content(value: object) -> object:
    """Recursively drop private blind bodies from public-facing payloads."""

    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        for key, item in value.items():
            if str(key) in _PRIVATE_CONTENT_KEYS:
                continue
            out[str(key)] = _strip_private_content(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_strip_private_content(item) for item in value]
    return value


def isolated_namespace(
    role: str,
    *,
    seal_cid: str,
    freeze_cid: str,
) -> str:
    """Return a deterministic isolated cache/execution namespace for one role."""

    role_key = _nonblank(role, "role")
    if role_key == BASELINE_ROLE:
        prefix = BASELINE_NAMESPACE_PREFIX
    elif role_key == CANDIDATE_ROLE:
        prefix = CANDIDATE_NAMESPACE_PREFIX
    else:
        raise HoldoutEvaluationError(f"unsupported evaluation role {role_key!r}")
    return f"{prefix}/{_cid(seal_cid, 'seal_cid')}/{_cid(freeze_cid, 'freeze_cid')}"


# ---------------------------------------------------------------------------
# Blind case materialization (custodian / evaluator boundary only)
# ---------------------------------------------------------------------------


def vocabulary_from_gold_ir(gold_ir: Mapping[str, object]) -> AllowedAtomVocabulary:
    """Derive the closed atom vocabulary from gold IR (scorer-side only)."""

    rules = gold_ir.get("rules")
    if not isinstance(rules, list) or not rules:
        raise HoldoutEvaluationError("gold_ir.rules must be a nonempty array")
    actors: set[str] = set()
    actions: set[str] = set()
    objects: set[str] = set()
    qualifiers: set[str] = set()
    for index, raw in enumerate(rules):
        rule = _mapping(raw, f"gold_ir.rules[{index}]")
        actors.add(_nonblank(rule.get("actor"), f"rules[{index}].actor"))
        actions.add(_nonblank(rule.get("action"), f"rules[{index}].action"))
        objects.add(_nonblank(rule.get("object"), f"rules[{index}].object"))
        for field in ("conditions", "exceptions", "temporal"):
            values = rule.get(field) or []
            if not isinstance(values, list):
                raise HoldoutEvaluationError(
                    f"rules[{index}].{field} must be an array"
                )
            for item in values:
                qualifiers.add(_nonblank(item, f"rules[{index}].{field}[]"))
    return AllowedAtomVocabulary(
        actors=tuple(sorted(actors)),
        actions=tuple(sorted(actions)),
        objects=tuple(sorted(objects)),
        qualifiers=tuple(sorted(qualifiers)),
    )


def private_record_to_matrix_case(record: object) -> MatrixCase:
    """Convert a custodian private blind record into a scorable MatrixCase."""

    case_id = _nonblank(getattr(record, "case_id", None), "case_id")
    source_text = _nonblank(getattr(record, "source_text", None), "source_text")
    gold_raw = getattr(record, "gold_ir", None)
    gold_map = dict(_mapping(gold_raw, "gold_ir"))
    vocabulary = vocabulary_from_gold_ir(gold_map)
    gold = CanonicalRuleIR.from_dict(gold_map, vocabulary)
    return MatrixCase(
        case_id=case_id,
        source_text=source_text,
        allowed_atom_vocabulary=vocabulary,
        gold_ir=gold,
    )


def split_runtime_and_scorer_views(
    cases: Sequence[MatrixCase],
) -> dict[str, object]:
    """Split cases into runtime (source-only) and scorer (gold) envelopes.

    Neither envelope is written to agent worktrees; both stay in evaluator
    memory. Public reports must call :func:`_strip_private_content`.
    """

    runtime_envelopes: list[dict[str, object]] = []
    scorer_bindings: list[dict[str, object]] = []
    for case in cases:
        if not isinstance(case, MatrixCase):
            raise HoldoutEvaluationError("cases must be MatrixCase records")
        runtime_envelopes.append(
            {
                "case_id": case.case_id,
                "case_cid": case.case_cid,
                "source_text": case.source_text,
                "source_visibility": "blind",
                "blind_source": True,
                "gold_visibility": "withheld",
                "population_kind": POPULATION_KIND_BLIND_HOLDOUT,
            }
        )
        scorer_bindings.append(
            {
                "case_id": case.case_id,
                "case_cid": case.case_cid,
                "gold_ir": case.gold_ir.to_dict(),
                "allowed_atom_vocabulary": case.allowed_atom_vocabulary.to_dict(),
                "gold_visibility": "blind",
                "blind_gold": True,
                "population_kind": POPULATION_KIND_BLIND_HOLDOUT,
            }
        )
    return {
        "runtime_source_envelopes": runtime_envelopes,
        "scorer_gold_bindings": scorer_bindings,
        "case_count": len(cases),
        "boundary_policy": {
            "agents_receive_gold": False,
            "agents_receive_blind_diagnostics": False,
            "prompts_packets_teachers_caches_tuning_worktrees_receive_gold": False,
            "runtime_may_receive_source": True,
            "scorer_may_receive_gold": True,
        },
    }


def materialize_blind_matrix_cases(
    *,
    records: Sequence[object] | None = None,
) -> tuple[MatrixCase, ...]:
    """Materialize preregistered blind cases for custodian evaluation only."""

    private = (
        tuple(records)
        if records is not None
        else materialize_preregistered_blind_records()
    )
    cases = tuple(private_record_to_matrix_case(item) for item in private)
    _require(cases, "blind population must be nonempty")
    ids = [case.case_id for case in cases]
    _require(len(ids) == len(set(ids)), "blind case ids must be unique")
    return cases


# ---------------------------------------------------------------------------
# Access grant (path-free append-only ledger)
# ---------------------------------------------------------------------------


def protocol_authorization_from_payload(
    authorization: Mapping[str, object],
) -> HoldoutAccessAuthorization:
    """Project a PLAT2-055 authorization artifact to the protocol type."""

    parsed = parse_holdout_authorization(authorization)
    protocol = _mapping(parsed.get("protocol_authorization"), "protocol_authorization")
    return HoldoutAccessAuthorization(
        goal_id=AUTHORIZATION_GOAL_ID,
        authorization_cid=_cid(protocol.get("authorization_cid"), "authorization_cid"),
        seal_cid=_cid(protocol.get("seal_cid"), "seal_cid"),
        candidate_freeze_cid=_cid(
            protocol.get("candidate_freeze_cid"), "candidate_freeze_cid"
        ),
        complete=True,
        holdout_authorized=True,
        outcomes_inspected=False,
        tuning_permitted=False,
    )


def validate_identities_for_access(
    *,
    authorization: Mapping[str, object],
    freeze: Mapping[str, object],
    seal: BlindHoldoutSeal,
) -> dict[str, object]:
    """Fail closed unless authorization, freeze, and seal identities align."""

    auth = parse_holdout_authorization(authorization)
    freeze_payload = parse_candidate_freeze(freeze, require_blind_unopened=False)
    _require(
        freeze_payload.get("candidate_selected") is True,
        "holdout evaluation requires a frozen selected candidate",
    )
    assert_authorization_still_valid(auth, freeze=freeze_payload)
    freeze_cid = _cid(freeze_payload.get("freeze_cid"), "freeze_cid")
    _require(
        auth.get("candidate_freeze_cid") == freeze_cid,
        "authorization candidate_freeze_cid does not match freeze",
    )
    _require(
        auth.get("seal_cid") == seal.seal_cid,
        "authorization seal_cid does not match loaded seal",
    )
    _require(
        freeze_payload.get("bindings", {}).get("blind_holdout_seal_cid")  # type: ignore[union-attr]
        == seal.seal_cid
        if isinstance(freeze_payload.get("bindings"), Mapping)
        else False,
        "freeze blind seal binding does not match loaded seal",
    )
    assert_promotion_sample_size_gate(seal)
    return {
        "authorization_artifact_cid": auth.get("authorization_artifact_cid"),
        "authorization_cid": auth.get("authorization_cid"),
        "candidate_freeze_cid": freeze_cid,
        "seal_cid": seal.seal_cid,
        "sealed_private_bundle_cid": seal.sealed_private_bundle_cid,
        "access_ledger_authority_cid": seal.access_ledger_authority_cid,
        "powered": bool(seal.sample_size_justification.powered),
        "promotion_eligible": bool(
            seal.sample_size_justification.promotion_eligible
        ),
        "exploratory": bool(seal.sample_size_justification.exploratory),
    }


def grant_single_use_access(
    *,
    authorization: Mapping[str, object],
    freeze: Mapping[str, object],
    seal: BlindHoldoutSeal | None = None,
    ledger_path: str | Path | None = None,
    executor_id: str = EXECUTOR_ID,
    purpose: str = "evaluation",
) -> dict[str, object]:
    """Validate identities and append the single-use grant + release receipts.

    The on-disk append-only ledger must use an absolute path (custodian store).
    Returns a path-free export payload suitable for the repository artifact.
    """

    loaded_seal = seal if seal is not None else load_frozen_blind_holdout_seal()
    identities = validate_identities_for_access(
        authorization=authorization,
        freeze=freeze,
        seal=loaded_seal,
    )
    protocol_auth = protocol_authorization_from_payload(authorization)

    if ledger_path is None:
        # Custodian ephemeral ledger; never required to live in the worktree.
        tmp_dir = Path(tempfile.mkdtemp(prefix="plat2-060-access-ledger-"))
        absolute_ledger = (tmp_dir / "access.jsonl").resolve()
    else:
        absolute_ledger = Path(ledger_path).resolve()
        if not absolute_ledger.is_absolute():
            raise HoldoutEvaluationError("access ledger path must be absolute")

    ledger = AppendOnlyAccessLedger(absolute_ledger, seal=loaded_seal)
    existing = ledger.read_receipts()
    if any(item.event in {"access_granted", "manifest_released"} for item in existing):
        # Single-use: surface a rejected attempt rather than double-granting.
        rejected = request_blind_access(
            ledger,
            authorization=protocol_auth,
            executor_id=executor_id,
            purpose="rejected",
        )
        raise HoldoutEvaluationError(
            f"blind holdout already accessed (event={rejected.event})"
        )

    grant = request_blind_access(
        ledger,
        authorization=protocol_auth,
        executor_id=executor_id,
        purpose=purpose,
    )
    if grant.event != "access_granted":
        raise HoldoutEvaluationError(
            f"access grant failed closed with event={grant.event!r}"
        )
    released = release_blind_manifest(
        ledger,
        authorization=protocol_auth,
        executor_id=executor_id,
        purpose=purpose,
    )
    if released.event != "manifest_released":
        raise HoldoutEvaluationError(
            f"manifest release failed closed with event={released.event!r}"
        )

    receipts = [item.to_dict() for item in ledger.read_receipts()]
    export = build_access_ledger_export(
        receipts=receipts,
        identities=identities,
        executor_id=executor_id,
        purpose=purpose,
    )
    return {
        "export": export,
        "grant_receipt": grant.to_dict(),
        "identities": identities,
        "ledger_path": str(absolute_ledger),
        "release_receipt": released.to_dict(),
        "successful_access": True,
    }


def build_access_ledger_export(
    *,
    receipts: Sequence[Mapping[str, object]],
    identities: Mapping[str, object],
    executor_id: str,
    purpose: str,
) -> dict[str, object]:
    """Build the path-free repository access-ledger artifact."""

    receipt_rows = [dict(_mapping(item, "receipt")) for item in receipts]
    for row in receipt_rows:
        # Drop any accidental absolute paths; receipts are already path-free.
        row.pop("path", None)
        row.pop("ledger_path", None)
        _require(
            row.get("interface") == HOLDOUT_ACCESS_AUDIT_INTERFACE,
            "receipt interface mismatch",
        )
        _require(
            row.get("schema") == ACCESS_RECEIPT_SCHEMA,
            "receipt schema mismatch",
        )
        _require(row.get("tuning_permitted") is False, "tuning_permitted must be false")

    events = [str(row.get("event")) for row in receipt_rows]
    _require("access_granted" in events, "export requires access_granted")
    _require("manifest_released" in events, "export requires manifest_released")
    _require(
        events.count("access_granted") == 1,
        "export must contain exactly one access_granted",
    )
    _require(
        events.count("manifest_released") == 1,
        "export must contain exactly one manifest_released",
    )

    payload: dict[str, object] = {
        "access_ledger_authority_cid": identities.get("access_ledger_authority_cid"),
        "assumptions": [
            "append-only single-use access",
            "path-free public receipt export",
            "tuning after access forbidden",
            "no second grant on the same seal",
        ],
        "authorization_cid": identities.get("authorization_cid"),
        "candidate_freeze_cid": identities.get("candidate_freeze_cid"),
        "events": events,
        "executor_id": executor_id,
        "goal_id": EVAL_GOAL_ID,
        "interface": ACCESS_LEDGER_EXPORT_INTERFACE,
        "ledger_schema": ACCESS_LEDGER_SCHEMA,
        "path_free": True,
        "purpose": purpose,
        "receipt_count": len(receipt_rows),
        "receipts": receipt_rows,
        "schema_version": ACCESS_LEDGER_EXPORT_SCHEMA,
        "seal_cid": identities.get("seal_cid"),
        "sealed_private_bundle_cid": identities.get("sealed_private_bundle_cid"),
        "single_use": True,
        "successful_access": True,
        "task_id": EVAL_TASK_ID,
        "title": "PLAT2-060 blind holdout access ledger",
        "tuning_permitted": False,
    }
    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"ledger_cid", "ledger_cid_codec", "ledger_cid_scope"}
    }
    payload["ledger_cid"] = cid_for_dag_json(_plain_json(identity))
    payload["ledger_cid_codec"] = CID_CODEC
    payload["ledger_cid_scope"] = LEDGER_CID_SCOPE
    return payload


# ---------------------------------------------------------------------------
# Scoring under isolated namespaces
# ---------------------------------------------------------------------------


def score_cases_for_role(
    cases: Sequence[MatrixCase],
    *,
    role: str,
    namespace: str,
    arm_id: str = PRODUCTION_ARM_ID,
    constructor: object | None = None,
    realizer: object | None = None,
    scorer: Callable[..., Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Score identical cases for one evaluation role under an isolated namespace."""

    role_key = _nonblank(role, "role")
    ns = _nonblank(namespace, "namespace")
    score_fn = scorer or score_deterministic_case
    records: list[dict[str, object]] = []
    for case in cases:
        if scorer is None:
            raw = score_fn(case, constructor=constructor, realizer=realizer)
        else:
            raw = score_fn(case)
        record = dict(_mapping(raw, "score record"))
        record["arm_id"] = arm_id
        record["evaluation_role"] = role_key
        record["cache_namespace"] = ns
        record["population_kind"] = POPULATION_KIND_BLIND_HOLDOUT
        # Never retain reconstruction text or IR bodies on the role record.
        for private_key in _PRIVATE_CONTENT_KEYS:
            record.pop(private_key, None)
        records.append(record)

    scored = [
        item
        for item in records
        if item.get("evaluation_status") == EVAL_STATUS_SEMANTIC_SCORED
        or item.get("semantic_score_eligible") is True
    ]
    means = {
        metric: (
            round(_mean([float(_mapping(item.get("losses"), "losses")[metric]) for item in scored]), 12)  # type: ignore[index,arg-type]
            if scored
            else FAILURE_LOSS
        )
        for metric in LOSS_METRICS
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
    status_counts = Counter(str(item.get("evaluation_status")) for item in records)
    return {
        "aggregates": {
            "aggregation_detail": AGGREGATION_DETAIL,
            "aggregation_order": AGGREGATION_ORDER,
            "case_count": len(records),
            "gate_pass_counts": gate_pass_counts,
            "means": means,
            "semantic_scored_count": len(scored),
            "status_counts": {
                status: int(status_counts.get(status, 0))
                for status in sorted(
                    {
                        EVAL_STATUS_SEMANTIC_SCORED,
                        EVAL_STATUS_NOT_MEASURED,
                        EVAL_STATUS_RUNTIME_FAILED,
                        EVAL_STATUS_UNSUPPORTED,
                    }
                )
            },
        },
        "arm_id": arm_id,
        "cache_namespace": ns,
        "cases": records,
        "evaluation_role": role_key,
        "population_kind": POPULATION_KIND_BLIND_HOLDOUT,
    }


def score_pilot_non_regression(
    *,
    repo_root: str | Path | None = None,
    constructor: object | None = None,
    realizer: object | None = None,
    scorer: Callable[..., Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Re-score sealed pilots under the frozen production path."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    path = root / PILOT_CASES_RELATIVE_PATH
    cases = load_matrix_cases(path)
    by_id = {case.case_id: case for case in cases}
    ordered: list[MatrixCase] = []
    for case_id in PILOT_CASE_IDS:
        _require(case_id in by_id, f"missing pilot case {case_id!r}")
        ordered.append(by_id[case_id])

    score_fn = scorer or score_deterministic_case
    records: list[dict[str, object]] = []
    for case in ordered:
        if scorer is None:
            raw = score_fn(case, constructor=constructor, realizer=realizer)
        else:
            raw = score_fn(case)
        record = dict(_mapping(raw, "pilot score"))
        for private_key in _PRIVATE_CONTENT_KEYS:
            record.pop(private_key, None)
        records.append(record)

    e2e_values = [
        float(_mapping(item.get("losses"), "losses")["end_to_end"])  # type: ignore[index]
        for item in records
        if item.get("evaluation_status") == EVAL_STATUS_SEMANTIC_SCORED
    ]
    mean_e2e = round(_mean(e2e_values), 12) if e2e_values else FAILURE_LOSS
    non_regressed = abs(mean_e2e - POST_PLAT_BASELINE_E2E_MEAN) < 1e-9
    per_case = {
        str(item["case_id"]): {
            "end_to_end": float(_mapping(item.get("losses"), "losses")["end_to_end"]),  # type: ignore[index]
            "forward": float(_mapping(item.get("losses"), "losses")["forward"]),  # type: ignore[index]
            "cycle": float(_mapping(item.get("losses"), "losses")["cycle"]),  # type: ignore[index]
            "non_regressed": abs(
                float(_mapping(item.get("losses"), "losses")["end_to_end"])  # type: ignore[index]
                - 0.0
            )
            < 1e-9
            or float(_mapping(item.get("losses"), "losses")["end_to_end"])  # type: ignore[index]
            <= 0.0 + 1e-12,
            "gates": dict(_mapping(item.get("gates"), "gates")),
            "evaluation_status": item.get("evaluation_status"),
        }
        for item in records
    }
    return {
        "cases": records,
        "mean_end_to_end": mean_e2e,
        "non_regressed": non_regressed,
        "per_case": per_case,
        "required_mean": POST_PLAT_BASELINE_E2E_MEAN,
        "population_kind": POPULATION_KIND_PILOT,
    }


# ---------------------------------------------------------------------------
# Paired analysis + decision
# ---------------------------------------------------------------------------


def _per_case_metric_map(
    block: Mapping[str, object],
    metric: str,
) -> dict[str, float | None]:
    cases = _array(block.get("cases"), "cases")
    out: dict[str, float | None] = {}
    for item in cases:
        case = _mapping(item, "case")
        case_id = _nonblank(case.get("case_id"), "case_id")
        status = case.get("evaluation_status")
        if status != EVAL_STATUS_SEMANTIC_SCORED and case.get(
            "semantic_score_eligible"
        ) is not True:
            out[case_id] = None
            continue
        losses = _mapping(case.get("losses"), "losses")
        out[case_id] = _finite_unit(losses.get(metric), f"{case_id}.{metric}")
    return out


def paired_case_cluster_analysis(
    baseline_block: Mapping[str, object],
    candidate_block: Mapping[str, object],
    *,
    baseline_arm_id: str,
    candidate_arm_id: str,
    seed: int = BOOTSTRAP_SEED,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    confidence_level: float = CONFIDENCE_LEVEL,
) -> dict[str, object]:
    """Preregistered per-case-first paired bootstrap (candidate − baseline)."""

    metrics_out: dict[str, object] = {}
    for metric in LOSS_METRICS:
        base_map = _per_case_metric_map(baseline_block, metric)
        cand_map = _per_case_metric_map(candidate_block, metric)
        case_ids = sorted(set(base_map) | set(cand_map))
        measured: list[tuple[str, float, float]] = []
        missing: list[str] = []
        for case_id in case_ids:
            b = base_map.get(case_id)
            c = cand_map.get(case_id)
            if b is None or c is None:
                missing.append(case_id)
            else:
                measured.append((case_id, float(b), float(c)))
        if measured:
            deltas = [c - b for _, b, c in measured]
            low, high = _bootstrap_delta(
                deltas,
                seed=_derived_seed(
                    seed,
                    baseline_arm_id,
                    candidate_arm_id,
                    "losses",
                    metric,
                ),
                bootstrap_samples=bootstrap_samples,
                confidence_level=confidence_level,
            )
            baseline_mean = _mean([b for _, b, _ in measured])
            candidate_mean = _mean([c for _, _, c in measured])
            mean_delta = _mean(deltas)
        else:
            low = high = baseline_mean = candidate_mean = mean_delta = None
        metrics_out[metric] = {
            "baseline_mean": _rounded(baseline_mean),
            "candidate_mean": _rounded(candidate_mean),
            "case_deltas": {
                case_id: _rounded(c - b) for case_id, b, c in measured
            },
            "confidence_interval": {
                "bootstrap_samples": bootstrap_samples,
                "confidence_level": confidence_level,
                "high": _rounded(high),
                "low": _rounded(low),
                "method": BOOTSTRAP_METHOD,
                "resampling_unit": RESAMPLING_UNIT,
            },
            "mean_delta": _rounded(mean_delta),
            "missing_case_ids": missing,
            "missing_case_count": len(missing),
            "paired_case_count": len(measured),
            "scheduled_case_count": len(case_ids),
        }

    e2e = _mapping(metrics_out.get("end_to_end"), "end_to_end")
    ci = _mapping(e2e.get("confidence_interval"), "confidence_interval")
    high = ci.get("high")
    beats = (
        isinstance(high, (int, float))
        and not isinstance(high, bool)
        and float(high) < 0.0
    )
    noninferior = (
        isinstance(high, (int, float))
        and not isinstance(high, bool)
        and float(high) <= NONINFERIORITY_MARGIN
    )
    return {
        "baseline_arm_id": baseline_arm_id,
        "bootstrap_method": BOOTSTRAP_METHOD,
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": seed,
        "candidate_arm_id": candidate_arm_id,
        "comparison": "candidate_minus_baseline",
        "confidence_level": confidence_level,
        "e2e_beats_baseline_ci_high_lt_0": beats,
        "e2e_noninferior_ucb_lte_margin": noninferior,
        "metrics": metrics_out,
        "noninferiority_margin": NONINFERIORITY_MARGIN,
        "noninferiority_rule": NONINFERIORITY_RULE,
        "primary_metric": PRIMARY_PROMOTION_METRIC,
    }


def evaluate_selection_gates_on_block(
    block: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate coverage / source-copy / polarity gates on a scored block."""

    cases = _array(block.get("cases"), "cases")
    per_case: dict[str, object] = {}
    all_pass = True
    missing: list[str] = []
    for item in cases:
        case = _mapping(item, "case")
        case_id = _nonblank(case.get("case_id"), "case_id")
        status = case.get("evaluation_status")
        if status != EVAL_STATUS_SEMANTIC_SCORED:
            missing.append(case_id)
            all_pass = False
            per_case[case_id] = {
                "evaluation_status": status,
                "gates": case.get("gates"),
                "selection_eligible": False,
            }
            continue
        gates = dict(_mapping(case.get("gates"), "gates"))
        eligible = all(bool(gates.get(name)) for name in SELECTION_GATE_IDS)
        if not eligible:
            all_pass = False
        per_case[case_id] = {
            "evaluation_status": status,
            "gates": {
                name: bool(gates.get(name))
                for name in (
                    "full_coverage",
                    "source_copy_exclusion",
                    "polarity_preservation",
                    "selection_eligible",
                )
            },
            "selection_eligible": eligible,
        }
    return {
        "all_cases_gate_pass": all_pass and not missing,
        "full_gates_pass": all_pass and not missing,
        "gates_required": list(SELECTION_GATE_IDS),
        "missing_or_failed_case_ids": missing
        + [
            case_id
            for case_id, row in per_case.items()
            if isinstance(row, Mapping) and not row.get("selection_eligible")
        ],
        "per_case": per_case,
    }


def decide_holdout_outcome(
    *,
    paired: Mapping[str, object],
    gates: Mapping[str, object],
    pilot_non_regression: Mapping[str, object],
    powered: bool,
    promotion_eligible: bool,
    evidence_complete: bool,
    exploratory: bool,
) -> dict[str, object]:
    """Apply frozen PLAT2-025 decision rules to one-shot blind results."""

    if not evidence_complete:
        outcome = DECISION_INCOMPLETE
        reason_codes = ["evidence_incomplete"]
        promotion = False
        improvement_claim = False
    elif exploratory or not powered or not promotion_eligible:
        outcome = DECISION_INCOMPLETE
        reason_codes = ["underpowered_or_exploratory_population"]
        promotion = False
        improvement_claim = False
    else:
        beats = paired.get("e2e_beats_baseline_ci_high_lt_0") is True
        noninferior = paired.get("e2e_noninferior_ucb_lte_margin") is True
        full_gates = gates.get("full_gates_pass") is True
        pilots_ok = pilot_non_regression.get("non_regressed") is True
        reason_codes = []
        if beats:
            reason_codes.append("e2e_ci_high_lt_0")
        else:
            reason_codes.append("e2e_ci_high_not_lt_0")
        if noninferior:
            reason_codes.append("noninferiority_holds")
        else:
            reason_codes.append("noninferiority_failed")
        if full_gates:
            reason_codes.append("full_gates_pass")
        else:
            reason_codes.append("full_gates_failed")
        if pilots_ok:
            reason_codes.append("pilots_non_regressed")
        else:
            reason_codes.append("pilot_regression")

        if beats and full_gates and pilots_ok:
            outcome = DECISION_IMPROVEMENT_CONFIRMED
            promotion = True
            improvement_claim = True
        elif noninferior and full_gates and pilots_ok and not beats:
            outcome = DECISION_GENERALIZATION_NO_IMPROVEMENT
            # Noninferior generalization confirms the candidate remains
            # acceptable without an improvement claim.
            promotion = True
            improvement_claim = False
        else:
            outcome = DECISION_PROMOTION_DECLINED
            promotion = False
            improvement_claim = False

    _require(outcome in DECISION_OUTCOMES, f"unknown decision outcome {outcome!r}")
    return {
        "decision_outcome": outcome,
        "evidence_complete": evidence_complete,
        "improvement_claim": improvement_claim,
        "production_promotion_authorized": promotion
        if outcome
        in {DECISION_IMPROVEMENT_CONFIRMED, DECISION_GENERALIZATION_NO_IMPROVEMENT}
        else False,
        "promotion": promotion
        if outcome == DECISION_IMPROVEMENT_CONFIRMED
        else False,
        "reason_codes": reason_codes,
        "rules": noninferiority_and_promotion_rules(),
        "selected_arm_id": PRODUCTION_ARM_ID,
        "status": outcome,
    }


def collect_missingness(
    *,
    baseline_block: Mapping[str, object],
    candidate_block: Mapping[str, object],
    paired: Mapping[str, object],
    pilot_block: Mapping[str, object],
) -> dict[str, object]:
    """Record every missing/not-measured/runtime-failed coordinate."""

    def _status_missing(block: Mapping[str, object], label: str) -> dict[str, object]:
        cases = _array(block.get("cases"), "cases")
        by_status: dict[str, list[str]] = {
            EVAL_STATUS_NOT_MEASURED: [],
            EVAL_STATUS_RUNTIME_FAILED: [],
            EVAL_STATUS_UNSUPPORTED: [],
        }
        for item in cases:
            case = _mapping(item, "case")
            status = str(case.get("evaluation_status"))
            if status in by_status:
                by_status[status].append(str(case.get("case_id")))
        return {
            "label": label,
            "missing_statuses": {key: values for key, values in by_status.items() if values},
            "semantic_scored_count": sum(
                1
                for item in cases
                if _mapping(item, "case").get("evaluation_status")
                == EVAL_STATUS_SEMANTIC_SCORED
            ),
            "scheduled_count": len(cases),
        }

    e2e = _mapping(paired.get("metrics", {}).get("end_to_end"), "paired.end_to_end")  # type: ignore[union-attr]
    return {
        "baseline": _status_missing(baseline_block, "baseline_blind"),
        "candidate": _status_missing(candidate_block, "candidate_blind"),
        "paired_e2e_missing_case_ids": list(e2e.get("missing_case_ids") or []),
        "pilot": _status_missing(pilot_block, "pilot_non_regression"),
    }


def collect_named_residuals(
    candidate_block: Mapping[str, object],
) -> list[dict[str, object]]:
    """Name residual cases from nonzero candidate losses (post-hoc only)."""

    residuals: list[dict[str, object]] = []
    for item in _array(candidate_block.get("cases"), "cases"):
        case = _mapping(item, "case")
        case_id = _nonblank(case.get("case_id"), "case_id")
        if case.get("evaluation_status") != EVAL_STATUS_SEMANTIC_SCORED:
            continue
        losses = _mapping(case.get("losses"), "losses")
        e2e = float(losses.get("end_to_end") or 0.0)
        forward = float(losses.get("forward") or 0.0)
        if e2e <= 0.0 and forward <= 0.0:
            continue
        facets = case.get("facets") or {}
        e2e_facets = (
            facets.get("end_to_end") if isinstance(facets, Mapping) else None
        )
        facet_hits: list[str] = []
        if isinstance(e2e_facets, Mapping):
            for facet in FACET_NAMES:
                value = e2e_facets.get(facet)
                if isinstance(value, (int, float)) and float(value) < 1.0:
                    facet_hits.append(facet)
        residuals.append(
            {
                "case_end_to_end_loss": e2e,
                "case_forward_loss": forward,
                "case_id": case_id,
                "failed_facets": facet_hits,
                "population": POPULATION_KIND_BLIND_HOLDOUT,
                "recommended_next_wave": (
                    "new board only with newly authored blind population; "
                    "do not retune against this holdout"
                ),
                "residual_kind": (
                    "facet_mismatch" if facet_hits else "nonzero_end_to_end_loss"
                ),
            }
        )
    residuals.sort(key=lambda row: (-float(row["case_end_to_end_loss"]), str(row["case_id"])))
    return residuals


def structural_receipts_summary() -> dict[str, object]:
    """Structural gates as separate non-semantic evidence (no e2e authority)."""

    return {
        "note": (
            "Hammer/cvc5/Lean structural receipts are non-semantic evidence only "
            "and never authorize promotion by themselves."
        ),
        "roles": {
            "Hammer": {
                "role": "structural_gate",
                "semantic_authority": False,
                "may_substitute_for_e2e": False,
            },
            "cvc5": {
                "role": "structural_gate",
                "semantic_authority": False,
                "may_substitute_for_e2e": False,
            },
            "Lean": {
                "role": "structural_gate",
                "semantic_authority": False,
                "may_substitute_for_e2e": False,
            },
        },
        "semantic_authority": False,
        "separate_from_semantic_e2e": True,
    }


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------


def build_remeasure_report(
    *,
    baseline_block: Mapping[str, object],
    candidate_block: Mapping[str, object],
    paired: Mapping[str, object],
    gates: Mapping[str, object],
    pilot_non_regression: Mapping[str, object],
    decision: Mapping[str, object],
    access_ledger: Mapping[str, object],
    identities: Mapping[str, object],
    missingness: Mapping[str, object],
    next_residuals: Sequence[Mapping[str, object]],
    resource_summary: Mapping[str, object],
    structural: Mapping[str, object],
    captured_at_utc: str | None = None,
) -> dict[str, object]:
    """Build the public ``EvalRepairMatrixReport@1`` blind remeasure report."""

    ledger_cid = _cid(access_ledger.get("ledger_cid"), "access_ledger.ledger_cid")
    baseline_public = _strip_private_content(baseline_block)
    candidate_public = _strip_private_content(candidate_block)
    pilot_public = _strip_private_content(pilot_non_regression)

    payload: dict[str, object] = {
        "acceptance": {
            "access_ledger_cid_published": True,
            "baseline_and_candidate_on_identical_blind_cases": True,
            "e2e_ci_high_lt_0": bool(paired.get("e2e_beats_baseline_ci_high_lt_0")),
            "full_gates_pass": bool(gates.get("full_gates_pass")),
            "gold_and_blind_diagnostics_withheld_from_agents": True,
            "immutable_2026_07_27_replacement_promotion_report_not_rewritten": True,
            "isolated_namespaces": True,
            "named_next_residuals_when_not_improved": True,
            "paired_bootstrap_per_case_first": True,
            "path_free_single_use_access_receipt": True,
            "pilots_rechecked_non_regressed": bool(
                pilot_non_regression.get("non_regressed")
            ),
            "promotion_authorized": bool(
                decision.get("production_promotion_authorized")
            ),
            "promotion_true_only_if_improvement_confirmed": True,
        },
        "access_ledger_cid": ledger_cid,
        "artifacts": {
            "access_ledger": {
                "path": str(DEFAULT_ACCESS_LEDGER_RELATIVE_PATH).replace("\\", "/"),
                "ledger_cid": ledger_cid,
            },
            "authorization": {
                "authorization_cid": identities.get("authorization_cid"),
                "path": str(DEFAULT_AUTHORIZATION_RELATIVE_PATH).replace("\\", "/"),
            },
            "candidate_freeze": {
                "freeze_cid": identities.get("candidate_freeze_cid"),
                "path": str(DEFAULT_FREEZE_RELATIVE_PATH).replace("\\", "/"),
            },
            "immutable_replacement_report": {
                "path": str(IMMUTABLE_REPLACEMENT_REPORT_PATH).replace("\\", "/"),
                "preserved": True,
                "report_cid": IMMUTABLE_REPLACEMENT_REPORT_CID,
            },
            "pilot_promotion_decision": {
                "note": "Historical PLAT-090 pilot promotion; not rewritten",
                "path": str(PILOT_PROMOTION_DECISION_PATH).replace("\\", "/"),
            },
        },
        "assumptions": list(DEFAULT_EVAL_ASSUMPTIONS),
        "baseline_arm_id": paired.get("baseline_arm_id"),
        "baseline_delta_tables": {
            "bootstrap_method": BOOTSTRAP_METHOD,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "confidence_level": CONFIDENCE_LEVEL,
            "description": (
                "Paired case-cluster bootstrap deltas (candidate minus baseline). "
                "Negative mean_delta means lower loss (better). Beats baseline "
                "only when CI high < 0."
            ),
            "holdout_baseline_vs_candidate": paired,
            "seed": BOOTSTRAP_SEED,
        },
        "blind_holdout": {
            "access_ledger_authority_cid": identities.get(
                "access_ledger_authority_cid"
            ),
            "case_count": _mapping(candidate_block.get("aggregates"), "aggregates").get(
                "case_count"
            ),
            "exploratory": identities.get("exploratory"),
            "population_kind": POPULATION_KIND_BLIND_HOLDOUT,
            "powered": identities.get("powered"),
            "promotion_eligible": identities.get("promotion_eligible"),
            "seal_cid": identities.get("seal_cid"),
            "sealed_private_bundle_cid": identities.get("sealed_private_bundle_cid"),
        },
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE_ID,
        "candidate_arm_id": paired.get("candidate_arm_id"),
        "captured_at_utc": captured_at_utc or _utc_now_iso(),
        "decision_summary": {
            "decision_outcome": decision.get("decision_outcome"),
            "improvement_claim": decision.get("improvement_claim"),
            "production_promotion_authorized": decision.get(
                "production_promotion_authorized"
            ),
            "promotion": decision.get("promotion"),
            "reason_codes": decision.get("reason_codes"),
            "status": decision.get("status"),
        },
        "evidence_id": EVAL_EVIDENCE_ID,
        "full_gates": gates,
        "goal_id": EVAL_GOAL_ID,
        "holdout_remeasure": {
            "baseline": baseline_public,
            "candidate": candidate_public,
            "namespaces": {
                "baseline": baseline_block.get("cache_namespace"),
                "candidate": candidate_block.get("cache_namespace"),
            },
        },
        "interface": EVAL_REPAIR_MATRIX_REPORT_INTERFACE,
        "missingness": missingness,
        "next_residuals": list(next_residuals),
        "next_residuals_note": (
            "Post-hoc residuals may seed a new board only with a newly authored "
            "blind population; do not retune or re-run this holdout."
            if next_residuals
            else "No nonzero blind residuals on the candidate arm."
        ),
        "pilot_non_regression": pilot_public,
        "production_arm_id": PRODUCTION_ARM_ID,
        "resource_context_summary": resource_summary,
        "schema_version": HOLDOUT_REMEASURE_SCHEMA,
        "structural_receipts": structural,
        "task_id": EVAL_TASK_ID,
        "title": "PLAT2-060 one-shot blind holdout remeasure",
        "tool_accounting": {
            "constructor_identity": PRODUCTION_CONSTRUCTOR_IDENTITY,
            "model_calls": 0,
            "paid_provider_calls": 0,
            "realizer_identity": PRODUCTION_REALIZER_IDENTITY,
            "semantic_authority_advisors": False,
        },
    }
    identity = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "report_cid",
            "report_cid_codec",
            "report_cid_scope",
            "promotion_decision_cid",
        }
    }
    payload["report_cid"] = cid_for_dag_json(_plain_json(identity))
    payload["report_cid_codec"] = CID_CODEC
    payload["report_cid_scope"] = REPORT_CID_SCOPE
    return payload


def build_promotion_decision(
    *,
    remeasure: Mapping[str, object],
    decision: Mapping[str, object],
    access_ledger: Mapping[str, object],
    identities: Mapping[str, object],
    next_residuals: Sequence[Mapping[str, object]],
    paired: Mapping[str, object],
    gates: Mapping[str, object],
    pilot_non_regression: Mapping[str, object],
    captured_at_utc: str | None = None,
) -> dict[str, object]:
    """Build the public promotion decision artifact."""

    report_cid = _cid(remeasure.get("report_cid"), "remeasure.report_cid")
    ledger_cid = _cid(access_ledger.get("ledger_cid"), "access_ledger.ledger_cid")
    e2e = _mapping(
        _mapping(paired.get("metrics"), "metrics").get("end_to_end"),
        "end_to_end",
    )
    ci = _mapping(e2e.get("confidence_interval"), "confidence_interval")

    payload: dict[str, object] = {
        "acceptance": {
            "e2e_ci_high_lt_0": bool(paired.get("e2e_beats_baseline_ci_high_lt_0")),
            "full_gates_pass": bool(gates.get("full_gates_pass")),
            "immutable_2026_07_27_replacement_promotion_report_not_rewritten": True,
            "named_next_residuals_when_not_promoted": bool(next_residuals)
            or decision.get("decision_outcome")
            != DECISION_IMPROVEMENT_CONFIRMED,
            "no_post_access_retune": True,
            "paired_bootstrap_vs_frozen_baseline": True,
            "path_free_single_use_access": True,
            "pilots_rechecked_non_regressed": bool(
                pilot_non_regression.get("non_regressed")
            ),
            "promotion_authorized": bool(
                decision.get("production_promotion_authorized")
            ),
            "promotion_true_only_if_improvement_confirmed": True,
        },
        "artifacts": {
            "access_ledger": {
                "ledger_cid": ledger_cid,
                "path": str(DEFAULT_ACCESS_LEDGER_RELATIVE_PATH).replace("\\", "/"),
            },
            "holdout_remeasure": {
                "path": str(DEFAULT_REMEASURE_RELATIVE_PATH).replace("\\", "/"),
                "report_cid": report_cid,
            },
            "holdout_results": {
                "path": str(DEFAULT_RESULTS_DOCS_RELATIVE_PATH).replace("\\", "/"),
            },
            "immutable_replacement_report": {
                "path": str(IMMUTABLE_REPLACEMENT_REPORT_PATH).replace("\\", "/"),
                "preserved": True,
                "report_cid": IMMUTABLE_REPLACEMENT_REPORT_CID,
            },
            "pilot_promotion_decision": {
                "note": "Historical PLAT-090 pilot promotion; not rewritten by PLAT2-060",
                "path": str(PILOT_PROMOTION_DECISION_PATH).replace("\\", "/"),
            },
        },
        "captured_at_utc": captured_at_utc or _utc_now_iso(),
        "decision": {
            "decision_outcome": decision.get("decision_outcome"),
            "evidence_complete": decision.get("evidence_complete"),
            "improvement_claim": decision.get("improvement_claim"),
            "production_promotion_authorized": decision.get(
                "production_promotion_authorized"
            ),
            "promotion": decision.get("promotion"),
            "reason_codes": decision.get("reason_codes"),
            "selected_arm_id": decision.get("selected_arm_id"),
            "status": decision.get("status"),
        },
        "evidence_id": EVAL_EVIDENCE_ID,
        "goal_id": EVAL_GOAL_ID,
        "interface": HOLDOUT_PROMOTION_DECISION_INTERFACE,
        "lineage": {
            "access_ledger_cid": ledger_cid,
            "authorization_cid": identities.get("authorization_cid"),
            "board_namespace": BOARD_NAMESPACE,
            "bundle": BUNDLE_ID,
            "candidate_freeze_cid": identities.get("candidate_freeze_cid"),
            "depends_on_tasks": ["PLAT2-055"],
            "holdout_remeasure_report_cid": report_cid,
            "pilot_promotion_task": "PLAT-090",
            "seal_cid": identities.get("seal_cid"),
        },
        "next_residuals": list(next_residuals),
        "next_residuals_note": (
            "Post-hoc residuals may seed a new board only with a newly authored "
            "blind population."
            if next_residuals
            else "Empty or no residual hold for a follow-on board."
        ),
        "post_access_policy": {
            "code_prompt_threshold_method_rerun_changes": False,
            "mutable_after_access": False,
            "retune_against_this_blind_holdout": False,
            "seed_new_board_requires_fresh_blind_population": True,
        },
        "promotion_gates": {
            "beats_baseline_ci": bool(paired.get("e2e_beats_baseline_ci_high_lt_0")),
            "confidence_interval": ci,
            "full_gates_pass": bool(gates.get("full_gates_pass")),
            "mean_delta_end_to_end": e2e.get("mean_delta"),
            "noninferiority_holds": bool(
                paired.get("e2e_noninferior_ucb_lte_margin")
            ),
            "noninferiority_margin": NONINFERIORITY_MARGIN,
            "pilot_mean_e2e": pilot_non_regression.get("mean_end_to_end"),
            "pilot_non_regressed": bool(pilot_non_regression.get("non_regressed")),
        },
        "schema_version": HOLDOUT_PROMOTION_DECISION_SCHEMA,
        "task_id": EVAL_TASK_ID,
        "title": "PLAT2-060 blind holdout promotion decision",
    }
    identity = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "decision_cid",
            "decision_cid_codec",
            "decision_cid_scope",
        }
    }
    payload["decision_cid"] = cid_for_dag_json(_plain_json(identity))
    payload["decision_cid_codec"] = CID_CODEC
    payload["decision_cid_scope"] = DECISION_CID_SCOPE
    return payload


def render_holdout_results_markdown(
    *,
    remeasure: Mapping[str, object],
    decision: Mapping[str, object],
    access_ledger: Mapping[str, object],
) -> str:
    """Render the human-readable holdout results document."""

    report_cid = remeasure.get("report_cid")
    decision_cid = decision.get("decision_cid")
    ledger_cid = access_ledger.get("ledger_cid")
    decision_body = _mapping(decision.get("decision"), "decision")
    outcome = decision_body.get("decision_outcome")
    paired = _mapping(
        _mapping(remeasure.get("baseline_delta_tables"), "baseline_delta_tables").get(
            "holdout_baseline_vs_candidate"
        ),
        "paired",
    )
    e2e = _mapping(_mapping(paired.get("metrics"), "metrics").get("end_to_end"), "e2e")
    ci = _mapping(e2e.get("confidence_interval"), "ci")
    gates = _mapping(remeasure.get("full_gates"), "full_gates")
    pilot = _mapping(remeasure.get("pilot_non_regression"), "pilot")
    candidate = _mapping(
        _mapping(remeasure.get("holdout_remeasure"), "holdout_remeasure").get(
            "candidate"
        ),
        "candidate",
    )
    cases = _array(candidate.get("cases"), "cases")
    means = _mapping(
        _mapping(candidate.get("aggregates"), "aggregates").get("means"), "means"
    )
    residuals = _array(remeasure.get("next_residuals"), "next_residuals")
    captured = remeasure.get("captured_at_utc")

    lines: list[str] = [
        "# Semantic round-trip blind holdout remeasure results",
        "",
        f"**Interface:** `{EVAL_REPAIR_MATRIX_REPORT_INTERFACE}`  ",
        f"**Schema:** `{HOLDOUT_REMEASURE_SCHEMA}`  ",
        f"**Task:** {EVAL_TASK_ID}  ",
        f"**Report CID:** `{report_cid}`  ",
        f"**Promotion decision CID:** `{decision_cid}`  ",
        f"**Access ledger CID:** `{ledger_cid}`  ",
        f"**Captured:** {captured}",
        "",
        "This receipt is the **one-shot** PLAT2-060 blind-holdout evaluation under",
        "a single path-free append-only access grant. Frozen baseline and candidate",
        "ran on identical blind cases under isolated namespaces with preregistered",
        "per-case-first paired bootstrap. Blind gold and diagnostics remain outside",
        "agents, prompts, packets, teachers, caches, and tuning worktrees.",
        "",
        "The immutable 2026-07-27 replacement promotion report is **not** rewritten:",
        "",
        f"- Replacement report CID: `{IMMUTABLE_REPLACEMENT_REPORT_CID}`",
        f"- Path: `{IMMUTABLE_REPLACEMENT_REPORT_PATH.as_posix()}`",
        "",
        "## Decision",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Decision outcome | **{outcome}** |",
        f"| Production promotion authorized | **{decision_body.get('production_promotion_authorized')}** |",
        f"| Improvement claim | **{decision_body.get('improvement_claim')}** |",
        f"| E2e CI high &lt; 0 | **{paired.get('e2e_beats_baseline_ci_high_lt_0')}** (high = {ci.get('high')}) |",
        f"| Noninferiority (UCB ≤ {NONINFERIORITY_MARGIN}) | **{paired.get('e2e_noninferior_ucb_lte_margin')}** |",
        f"| Full gates pass | **{gates.get('full_gates_pass')}** |",
        f"| Pilots non-regressed (mean e2e 0.0) | **{pilot.get('non_regressed')}** |",
        f"| Candidate holdout mean e2e | **{e2e.get('candidate_mean')}** |",
        f"| Baseline holdout mean e2e | **{e2e.get('baseline_mean')}** |",
        f"| Mean Δ e2e (candidate − baseline) | **{e2e.get('mean_delta')}** |",
        f"| Selected production arm | `{PRODUCTION_ARM_ID}` |",
        f"| Access ledger CID | `{ledger_cid}` |",
        f"| Next residuals | {len(residuals)} named residual case(s) |",
        "",
        "Promotion rule (fail-closed):",
        "",
        f"- `{DECISION_IMPROVEMENT_CONFIRMED}`: e2e CI high &lt; 0 **and** full gates **and** pilot non-regression (improvement claim).",
        f"- `{DECISION_GENERALIZATION_NO_IMPROVEMENT}`: noninferiority holds **and** no regressions **and** full gates; **no** improvement claim.",
        f"- `{DECISION_PROMOTION_DECLINED}` / `{DECISION_INCOMPLETE}`: decline promotion.",
        "",
        "No post-access code, prompt, threshold, method selection, or rerun is permitted.",
        "Authorization was issued by **PLAT2-055**. Post-hoc residuals may seed a **new**",
        "board only with a newly authored blind population.",
        "",
        "## Access ledger (path-free)",
        "",
        f"- Ledger CID: `{ledger_cid}`",
        f"- Events: {', '.join(str(e) for e in access_ledger.get('events') or [])}",
        f"- Single-use: **{access_ledger.get('single_use')}**",
        f"- Tuning permitted: **{access_ledger.get('tuning_permitted')}**",
        "",
        "## Blind holdout candidate remeasure",
        "",
        f"Arm under test: `{PRODUCTION_ARM_ID}`  ",
        f"Namespace: `{candidate.get('cache_namespace')}`",
        "",
        "| Case | Status | Forward | Cycle | End-to-end |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for item in cases:
        case = _mapping(item, "case")
        losses = _mapping(case.get("losses"), "losses")
        lines.append(
            f"| `{case.get('case_id')}` | {case.get('evaluation_status')} | "
            f"{float(losses.get('forward') or 0.0):.6f} | "
            f"{float(losses.get('cycle') or 0.0):.6f} | "
            f"{float(losses.get('end_to_end') or 0.0):.6f} |"
        )
    lines.extend(
        [
            "",
            "| Metric | Candidate holdout mean |",
            "| --- | ---: |",
            f"| Forward | {float(means.get('forward') or 0.0):.6f} |",
            f"| Cycle | {float(means.get('cycle') or 0.0):.6f} |",
            f"| End-to-end | {float(means.get('end_to_end') or 0.0):.6f} |",
            "",
            "## Pilot non-regression re-check",
            "",
            f"Required mean pilot e2e remains **{POST_PLAT_BASELINE_E2E_MEAN}**.",
            "",
            f"- Pilot mean e2e: **{pilot.get('mean_end_to_end')}**",
            f"- Non-regressed: **{pilot.get('non_regressed')}**",
            "",
            "## Paired bootstrap (candidate − baseline)",
            "",
            f"Method: `{BOOTSTRAP_METHOD}`, samples={BOOTSTRAP_SAMPLES}, "
            f"seed={BOOTSTRAP_SEED}, confidence={CONFIDENCE_LEVEL}.",
            "",
            f"| Metric | Mean Δ | CI low | CI high |",
            f"| --- | ---: | ---: | ---: |",
        ]
    )
    for metric in LOSS_METRICS:
        row = _mapping(_mapping(paired.get("metrics"), "metrics").get(metric), metric)
        row_ci = _mapping(row.get("confidence_interval"), "ci")
        lines.append(
            f"| {metric} | {row.get('mean_delta')} | {row_ci.get('low')} | {row_ci.get('high')} |"
        )
    lines.extend(
        [
            "",
            "## Full selection gates",
            "",
            f"- Full gates pass: **{gates.get('full_gates_pass')}**",
            f"- Required: {', '.join(SELECTION_GATE_IDS)}",
            "",
            "## Structural receipts (non-semantic)",
            "",
            "Hammer / cvc5 / Lean remain structural gates with "
            "`semantic_authority: false` and never replace e2e loss.",
            "",
            "## Next residuals",
            "",
        ]
    )
    if not residuals:
        lines.append("None.")
    else:
        lines.extend(
            [
                "| Case | E2e | Forward | Failed facets |",
                "| --- | ---: | ---: | --- |",
            ]
        )
        for row in residuals:
            residual = _mapping(row, "residual")
            facets = residual.get("failed_facets") or []
            facet_text = ", ".join(str(x) for x in facets) if facets else "—"
            lines.append(
                f"| `{residual.get('case_id')}` | "
                f"{float(residual.get('case_end_to_end_loss') or 0.0):.6f} | "
                f"{float(residual.get('case_forward_loss') or 0.0):.6f} | "
                f"{facet_text} |"
            )
        lines.append("")
        lines.append(
            "These residuals may seed a **new** board only with a newly authored "
            "blind population."
        )
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```bash",
            "PYTHONPATH=. python -m benchmarks.semantic_roundtrip.holdout_evaluation \\",
            "  --repo-root .",
            "",
            "PYTHONPATH=. python -m pytest \\",
            "  tests/unit/benchmarks/semantic_roundtrip/test_holdout_evaluation.py \\",
            "  tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py \\",
            "  tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py -q",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# One-shot evaluation orchestration
# ---------------------------------------------------------------------------


def run_one_shot_blind_evaluation(
    repo_root: str | Path | None = None,
    *,
    freeze: Mapping[str, object] | None = None,
    authorization: Mapping[str, object] | None = None,
    seal: BlindHoldoutSeal | None = None,
    blind_cases: Sequence[MatrixCase] | None = None,
    ledger_path: str | Path | None = None,
    constructor: object | None = None,
    realizer: object | None = None,
    scorer: Callable[..., Mapping[str, object]] | None = None,
    run_pilots: bool = True,
    pilot_non_regression: Mapping[str, object] | None = None,
    resource_summary: Mapping[str, object] | None = None,
    captured_at_utc: str | None = None,
    skip_access_grant: bool = False,
    access_export: Mapping[str, object] | None = None,
    identities: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Execute the complete one-shot blind holdout evaluation protocol."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()

    freeze_payload = (
        parse_candidate_freeze(freeze, require_blind_unopened=False)
        if freeze is not None
        else load_candidate_freeze(repo_root=root)
    )
    auth_payload = (
        parse_holdout_authorization(authorization)
        if authorization is not None
        else load_holdout_authorization(repo_root=root)
    )
    loaded_seal = (
        seal if seal is not None else load_frozen_blind_holdout_seal(repository_root=root)
    )

    if skip_access_grant:
        _require(access_export is not None, "access_export required when skip_access_grant")
        _require(identities is not None, "identities required when skip_access_grant")
        assert access_export is not None
        assert identities is not None
        access_bundle = {
            "export": dict(access_export),
            "identities": dict(identities),
            "successful_access": True,
        }
    else:
        access_bundle = grant_single_use_access(
            authorization=auth_payload,
            freeze=freeze_payload,
            seal=loaded_seal,
            ledger_path=ledger_path,
        )

    identity_map = dict(_mapping(access_bundle.get("identities"), "identities"))
    ledger_export = dict(_mapping(access_bundle.get("export"), "export"))

    cases = (
        tuple(blind_cases)
        if blind_cases is not None
        else materialize_blind_matrix_cases()
    )
    # Boundary split retained only in memory for doctrine checks.
    boundary = split_runtime_and_scorer_views(cases)
    _require(
        boundary["boundary_policy"]["agents_receive_gold"] is False,  # type: ignore[index]
        "boundary policy forbids agent gold",
    )

    freeze_cid = _cid(identity_map.get("candidate_freeze_cid"), "candidate_freeze_cid")
    seal_cid = _cid(identity_map.get("seal_cid"), "seal_cid")
    baseline_ns = isolated_namespace(
        BASELINE_ROLE, seal_cid=seal_cid, freeze_cid=freeze_cid
    )
    candidate_ns = isolated_namespace(
        CANDIDATE_ROLE, seal_cid=seal_cid, freeze_cid=freeze_cid
    )
    _require(baseline_ns != candidate_ns, "baseline/candidate namespaces must differ")

    baseline_block = score_cases_for_role(
        cases,
        role=BASELINE_ROLE,
        namespace=baseline_ns,
        arm_id=PRODUCTION_ARM_ID,
        constructor=constructor,
        realizer=realizer,
        scorer=scorer,
    )
    candidate_block = score_cases_for_role(
        cases,
        role=CANDIDATE_ROLE,
        namespace=candidate_ns,
        arm_id=PRODUCTION_ARM_ID,
        constructor=constructor,
        realizer=realizer,
        scorer=scorer,
    )

    paired = paired_case_cluster_analysis(
        baseline_block,
        candidate_block,
        baseline_arm_id=f"{PRODUCTION_ARM_ID}__{BASELINE_ROLE}",
        candidate_arm_id=f"{PRODUCTION_ARM_ID}__{CANDIDATE_ROLE}",
    )
    gates = evaluate_selection_gates_on_block(candidate_block)

    if pilot_non_regression is not None:
        pilot_block = dict(pilot_non_regression)
    elif run_pilots:
        pilot_block = score_pilot_non_regression(
            repo_root=root,
            constructor=constructor,
            realizer=realizer,
            scorer=scorer,
        )
    else:
        pilot_block = {
            "cases": [],
            "mean_end_to_end": None,
            "non_regressed": False,
            "per_case": {},
            "required_mean": POST_PLAT_BASELINE_E2E_MEAN,
            "population_kind": POPULATION_KIND_PILOT,
        }

    evidence_complete = (
        bool(ledger_export.get("successful_access"))
        and int(_mapping(candidate_block.get("aggregates"), "aggregates").get("case_count") or 0)
        > 0
        and paired.get("metrics") is not None
    )
    decision = decide_holdout_outcome(
        paired=paired,
        gates=gates,
        pilot_non_regression=pilot_block,
        powered=bool(identity_map.get("powered")),
        promotion_eligible=bool(identity_map.get("promotion_eligible")),
        evidence_complete=bool(evidence_complete),
        exploratory=bool(identity_map.get("exploratory")),
    )
    missingness = collect_missingness(
        baseline_block=baseline_block,
        candidate_block=candidate_block,
        paired=paired,
        pilot_block=pilot_block,
    )
    next_residuals = collect_named_residuals(candidate_block)
    structural = structural_receipts_summary()
    resources = dict(resource_summary) if resource_summary is not None else {
        "context_tokens": {
            "note": "one-shot evaluation; no packet materialization",
            "packet_token_budget": 8192,
            "used": 0,
        },
        "cost": {
            "currency": "USD",
            "metered": False,
            "total_cost": 0.0,
        },
        "environment_toolchain": capture_environment_toolchain(),
        "model_calls": 0,
        "wall_time_note": "deterministic in-process scoring",
    }
    stamp = captured_at_utc or _utc_now_iso()

    remeasure = build_remeasure_report(
        baseline_block=baseline_block,
        candidate_block=candidate_block,
        paired=paired,
        gates=gates,
        pilot_non_regression=pilot_block,
        decision=decision,
        access_ledger=ledger_export,
        identities=identity_map,
        missingness=missingness,
        next_residuals=next_residuals,
        resource_summary=resources,
        structural=structural,
        captured_at_utc=stamp,
    )
    promotion = build_promotion_decision(
        remeasure=remeasure,
        decision=decision,
        access_ledger=ledger_export,
        identities=identity_map,
        next_residuals=next_residuals,
        paired=paired,
        gates=gates,
        pilot_non_regression=pilot_block,
        captured_at_utc=stamp,
    )
    remeasure = dict(remeasure)
    remeasure["promotion_decision_cid"] = promotion["decision_cid"]
    # Re-bind report_cid after attaching decision cid would change identity;
    # keep promotion_decision_cid outside the report identity by design:
    # rebuild without re-including it in identity (already excluded).

    results_md = render_holdout_results_markdown(
        remeasure=remeasure,
        decision=promotion,
        access_ledger=ledger_export,
    )

    # Public safety: ensure private bodies never ship in published JSON.
    def _assert_no_private_bodies(label: str, payload: Mapping[str, object]) -> None:
        stripped = _strip_private_content(payload)
        dumped = json.dumps(_plain_json(stripped), sort_keys=True)

        def _walk(node: object, path: str) -> None:
            if isinstance(node, Mapping):
                for key, item in node.items():
                    key_s = str(key)
                    if key_s in _PRIVATE_CONTENT_KEYS:
                        raise HoldoutEvaluationError(
                            f"{label} retained private key at {path}.{key_s}"
                        )
                    _walk(item, f"{path}.{key_s}")
            elif isinstance(node, list):
                for index, item in enumerate(node):
                    _walk(item, f"{path}[{index}]")

        _walk(stripped, label)
        for token in (
            "runtime_source_envelopes",
            "scorer_gold_bindings",
            "private_records",
            "materialize_preregistered_blind_records",
        ):
            _require(token not in dumped, f"{label} must not embed {token}")

    _assert_no_private_bodies("remeasure", remeasure)
    _assert_no_private_bodies("promotion", promotion)
    _assert_no_private_bodies("access_ledger", ledger_export)

    return {
        "access_ledger": ledger_export,
        "boundary": {
            "case_count": boundary["case_count"],
            "boundary_policy": boundary["boundary_policy"],
            # Deliberately omit runtime/scorer bodies from the returned public bundle.
        },
        "decision": decision,
        "promotion_decision": promotion,
        "remeasure": remeasure,
        "results_markdown": results_md,
    }


def write_evaluation_artifacts(
    bundle: Mapping[str, object],
    *,
    repo_root: str | Path | None = None,
    access_ledger_path: str | Path | None = None,
    remeasure_path: str | Path | None = None,
    decision_path: str | Path | None = None,
    results_path: str | Path | None = None,
) -> dict[str, str]:
    """Atomically write the four PLAT2-060 public artifacts."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()
    paths = {
        "access_ledger": Path(
            access_ledger_path
            if access_ledger_path is not None
            else root / DEFAULT_ACCESS_LEDGER_RELATIVE_PATH
        ),
        "remeasure": Path(
            remeasure_path
            if remeasure_path is not None
            else root / DEFAULT_REMEASURE_RELATIVE_PATH
        ),
        "promotion_decision": Path(
            decision_path
            if decision_path is not None
            else root / DEFAULT_PROMOTION_DECISION_RELATIVE_PATH
        ),
        "results_markdown": Path(
            results_path
            if results_path is not None
            else root / DEFAULT_RESULTS_DOCS_RELATIVE_PATH
        ),
    }
    _atomic_write_json(
        paths["access_ledger"],
        _mapping(bundle.get("access_ledger"), "access_ledger"),
    )
    _atomic_write_json(
        paths["remeasure"],
        _mapping(bundle.get("remeasure"), "remeasure"),
    )
    _atomic_write_json(
        paths["promotion_decision"],
        _mapping(bundle.get("promotion_decision"), "promotion_decision"),
    )
    results_text = bundle.get("results_markdown")
    if not isinstance(results_text, str) or not results_text.strip():
        raise HoldoutEvaluationError("results_markdown must be a nonempty string")
    paths["results_markdown"].parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{paths['results_markdown'].name}.",
        suffix=".tmp",
        dir=str(paths["results_markdown"].parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(results_text)
            if not results_text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, paths["results_markdown"])
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    return {key: str(path) for key, path in paths.items()}


def run_and_write_default_artifacts(
    repo_root: str | Path | None = None,
    **kwargs: Any,
) -> dict[str, object]:
    """Run one-shot evaluation and write the six expected output paths' contents."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    bundle = run_one_shot_blind_evaluation(root, **kwargs)
    written = write_evaluation_artifacts(bundle, repo_root=root)
    return {"bundle": bundle, "written": written}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PLAT2-060 one-shot blind-holdout evaluation and decision"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect from package location)",
    )
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=None,
        help="Absolute path for the append-only custodian JSONL ledger",
    )
    parser.add_argument(
        "--skip-write",
        action="store_true",
        help="Run evaluation without writing repository artifacts",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.repo_root.resolve() if args.repo_root is not None else _repo_root()
    ledger = args.ledger_path.resolve() if args.ledger_path is not None else None
    if args.skip_write:
        bundle = run_one_shot_blind_evaluation(root, ledger_path=ledger)
        decision = bundle["decision"]
        print(
            json.dumps(
                {
                    "decision_outcome": decision.get("decision_outcome"),
                    "report_cid": bundle["remeasure"].get("report_cid"),  # type: ignore[union-attr]
                    "decision_cid": bundle["promotion_decision"].get("decision_cid"),  # type: ignore[union-attr]
                    "ledger_cid": bundle["access_ledger"].get("ledger_cid"),  # type: ignore[union-attr]
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = run_and_write_default_artifacts(root, ledger_path=ledger)
    print(json.dumps(result["written"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ACCESS_LEDGER_EXPORT_INTERFACE",
    "ACCESS_LEDGER_EXPORT_SCHEMA",
    "BASELINE_ROLE",
    "CANDIDATE_ROLE",
    "DEFAULT_ACCESS_LEDGER_RELATIVE_PATH",
    "DEFAULT_PROMOTION_DECISION_RELATIVE_PATH",
    "DEFAULT_REMEASURE_RELATIVE_PATH",
    "DEFAULT_RESULTS_DOCS_RELATIVE_PATH",
    "EVAL_EVIDENCE_ID",
    "EVAL_GOAL_ID",
    "EVAL_TASK_ID",
    "HOLDOUT_PROMOTION_DECISION_INTERFACE",
    "HOLDOUT_PROMOTION_DECISION_SCHEMA",
    "HOLDOUT_REMEASURE_SCHEMA",
    "HoldoutEvaluationError",
    "build_access_ledger_export",
    "build_promotion_decision",
    "build_remeasure_report",
    "collect_missingness",
    "collect_named_residuals",
    "decide_holdout_outcome",
    "evaluate_selection_gates_on_block",
    "grant_single_use_access",
    "isolated_namespace",
    "main",
    "materialize_blind_matrix_cases",
    "paired_case_cluster_analysis",
    "private_record_to_matrix_case",
    "protocol_authorization_from_payload",
    "render_holdout_results_markdown",
    "run_and_write_default_artifacts",
    "run_one_shot_blind_evaluation",
    "score_cases_for_role",
    "score_pilot_non_regression",
    "split_runtime_and_scorer_views",
    "structural_receipts_summary",
    "validate_identities_for_access",
    "vocabulary_from_gold_ir",
    "write_evaluation_artifacts",
]
