"""Fail-closed replay projections for Hammer benchmark evidence.

Fresh-worktree replay must compare the meaning of a Hammer run without
requiring per-run identifiers, timestamps, temporary directories, or resource
observations to be byte-identical.  This module validates those volatile
records *before* removing them and retains every semantic, solver,
certificate, environment, and reconstruction field.

The module is deliberately separate from :mod:`benchmarks.logic_pipeline.report`
so replay validation can be tested and reviewed as a small trust-boundary
component.  Imports of the optional native Hammer package are lazy: direct
live-runtime receipts do not import solver or ITP integrations.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import hashlib
from pathlib import PurePath
import re
import shlex
from typing import Any, Final, Mapping, Sequence

from .contracts import (
    FailureCode,
    ProtocolContractError,
    StageName,
    StageRecord,
    StageStatus,
    canonical_json,
)


HAMMER_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.hammer-evidence.v1"
)
HAMMER_TRANSLATED_ENTAILMENT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "hammer-translated-entailment.v1"
)
HAMMER_TRANSLATION_TERMINAL_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "hammer-translation-terminal.v1"
)
HAMMER_PREMISE_SELECTION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "hammer-premise-selection.v1"
)
SEMANTIC_CONTEXT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-stage-context.v1"
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

_TRANSLATED_KEYS = frozenset(
    {
        "schema",
        "case_input_sha256",
        "translation_status",
        "translation_sha256",
        "translation_shape",
        "source_sha256",
        "obligation_sha256",
        "solver_status",
        "solver_command_sha256",
        "solver_input_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "returncode",
        "timed_out",
        "process_group_reaped",
        "termination_reason",
        "proof_success",
        "proof_text",
        "candidate_created",
        "native_reconstruction",
        "efficacy_observed",
        "semantic_context",
    }
)
_TERMINAL_KEYS = frozenset(
    {
        "schema",
        "case_input_sha256",
        "translation_status",
        "solver_status",
        "candidate_created",
        "efficacy_observed",
        "reason",
        "semantic_context",
    }
)
_FULL_EVIDENCE_KEYS = frozenset(
    {
        "schema",
        "evidence_id",
        "request",
        "portfolio",
        "normalized_evidence",
        "proof_candidate",
        "reconstruction",
        "environment_lock",
        "reconstruction_kernel_accepted",
        "status",
    }
)
_SEMANTIC_BINDING_KEYS = frozenset(
    {
        "schema",
        "context_sha256",
        "source_text_sha256",
        "artifact_sha256s",
    }
)
_SEMANTIC_CONTEXT_KEYS = frozenset(
    {
        "schema",
        "context_sha256",
        "source_text_sha256",
        "artifacts",
    }
)
_SEMANTIC_ARTIFACT_KEYS = frozenset(
    {
        "stage",
        "invoked",
        "status",
        "artifact_sha256",
        "output_sha256",
        "policy_reason",
    }
)
_SEMANTIC_ARTIFACT_SUCCESS_KEYS = _SEMANTIC_ARTIFACT_KEYS | {"evidence"}

_A10_PREMISE_KEYS = frozenset(
    {
        "schema",
        "policy",
        "ranking_contract",
        "translation_sha256",
        "source_sha256",
        "obligation_sha256",
        "candidate_set_sha256",
        "candidate_count",
        "corpus_revision",
        "top_k",
        "selection_method",
        "model_id",
        "model_digest",
        "feature_version",
        "used_learned_selector",
        "fallback_reason",
        "selected",
        "receipt_sha256",
    }
)
_A11_PREMISE_KEYS = frozenset(
    {
        "schema",
        "policy",
        "ranking_contract",
        "translation_sha256",
        "source_sha256",
        "obligation_sha256",
        "candidate_set_sha256",
        "candidate_count",
        "top_k",
        "symai_invoked",
        "symai_artifact_sha256",
        "symai_output_sha256",
        "symai_identity_sha256",
        "semantic_signal_sha256",
        "semantic_term_count",
        "selected",
        "receipt_sha256",
    }
)
_A10_SELECTED_KEYS = frozenset(
    {
        "premise_id",
        "rank",
        "score",
        "source_index",
        "statement_sha256",
    }
)
_A11_SELECTED_KEYS = frozenset(
    {
        "premise_id",
        "rank",
        "overlap_count",
        "overlap_basis_points",
        "source_index",
        "statement_sha256",
    }
)

_OPERATIONAL_IDENTITY_FIELDS = frozenset(
    {
        "consumed_artifact_sha256",
        "semantic_context_sha256",
        "premise_selection_sha256",
    }
)
_OPERATIONAL_ATTEMPT_RESOURCE_FIELDS = frozenset(
    {
        "cpu_seconds",
        "max_rss_mb",
        "global_lease_wait_seconds",
    }
)
_OPERATIONAL_PORTFOLIO_TELEMETRY_FIELDS = frozenset(
    {
        "wait_time_seconds_before",
        "scheduler",
    }
)


class HammerReplayError(ProtocolContractError):
    """Raised when Hammer evidence is malformed or replay semantics drift."""


def _error(message: str) -> HammerReplayError:
    return HammerReplayError(message)


def _json(value: object, *, field: str) -> object:
    """Return detached canonical JSON while accepting frozen record views."""

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise _error(f"{field} object keys must be strings")
        result = {
            key: _json(item, field=f"{field}.{key}")
            for key, item in value.items()
        }
        canonical_json(result)
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        result = [
            _json(item, field=f"{field}[]")
            for item in value
        ]
        canonical_json(result)
        return result
    if value is None or isinstance(value, (str, bool, int, float)):
        canonical_json(value)
        return value
    raise _error(f"{field} is not canonical JSON data")


def _mapping(value: object, *, field: str) -> dict[str, object]:
    detached = _json(value, field=field)
    if not isinstance(detached, dict):
        raise _error(f"{field} must be an object")
    return detached


def _sequence(value: object, *, field: str) -> list[object]:
    detached = _json(value, field=field)
    if not isinstance(detached, list):
        raise _error(f"{field} must be an array")
    return detached


def _exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str] | set[str],
    *,
    field: str,
) -> None:
    actual = set(value)
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        unknown = sorted(actual - set(expected))
        raise _error(
            f"{field} used an unexpected schema "
            f"(missing={missing!r}, unknown={unknown!r})"
        )


def _digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise _error(f"{field} must be a lowercase SHA-256 digest")
    return value


def _content_address(value: object, *, field: str) -> str:
    """Validate the canonical CIDv1/raw/sha2-256 or fallback digest form."""

    if not isinstance(value, str):
        raise _error(f"{field} must be a content digest")
    if value.startswith("sha256:"):
        _digest(value.removeprefix("sha256:"), field=field)
        return value
    try:
        from multiformats import CID

        decoded = CID.decode(value)
    except (ImportError, KeyError, TypeError, ValueError) as exc:
        raise _error(f"{field} must be a canonical content digest") from exc
    if (
        str(decoded) != value
        or decoded.version != 1
        or decoded.base.name != "base32"
        or decoded.codec.name != "raw"
        or decoded.hashfun.name != "sha2-256"
    ):
        raise _error(f"{field} must be a canonical raw sha2-256 CIDv1")
    return value


def _nonempty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{field} must be a non-empty string")
    return value


def _boolean(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise _error(f"{field} must be a boolean")
    return value


def _integer(value: object, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _error(f"{field} must be an integer >= {minimum}")
    return value


def _self_digest(
    value: Mapping[str, object],
    *,
    digest_field: str,
    field: str,
) -> str:
    supplied = _digest(value.get(digest_field), field=f"{field}.{digest_field}")
    body = {
        key: _json(item, field=f"{field}.{key}")
        for key, item in value.items()
        if key != digest_field
    }
    expected = hashlib.sha256(
        canonical_json(body).encode("utf-8")
    ).hexdigest()
    if supplied != expected:
        raise _error(f"{field}.{digest_field} does not match its payload")
    return supplied


def project_hammer_semantic_context_for_replay(
    value: object,
) -> dict[str, object]:
    """Validate and normalize a live semantic binding or its full context.

    A direct Hammer receipt contains only the compact four-field binding.  A
    caller may also supply the complete content-addressed semantic context.
    Full contexts retain every evidence field; only stage artifact addresses
    and the derived context address are normalized.
    """

    context = _mapping(value, field="Hammer semantic context")
    if set(context) == set(_SEMANTIC_BINDING_KEYS):
        if context.get("schema") != SEMANTIC_CONTEXT_SCHEMA:
            raise _error("Hammer semantic binding used an unsupported schema")
        _digest(
            context.get("context_sha256"),
            field="Hammer semantic context.context_sha256",
        )
        source = context.get("source_text_sha256")
        if source is not None:
            _digest(source, field="Hammer semantic context.source_text_sha256")
        artifact_digests = _sequence(
            context.get("artifact_sha256s"),
            field="Hammer semantic context.artifact_sha256s",
        )
        for index, digest in enumerate(artifact_digests):
            _digest(
                digest,
                field=f"Hammer semantic context.artifact_sha256s[{index}]",
            )
        if len(set(artifact_digests)) != len(artifact_digests):
            raise _error("Hammer semantic artifact bindings must be unique")
        return {
            "schema": SEMANTIC_CONTEXT_SCHEMA,
            "source_text_sha256": source,
            "artifact_bindings": [
                f"@semantic-artifact-{index:03d}"
                for index in range(len(artifact_digests))
            ],
        }

    _exact_keys(
        context,
        _SEMANTIC_CONTEXT_KEYS,
        field="Hammer semantic context",
    )
    if context.get("schema") != SEMANTIC_CONTEXT_SCHEMA:
        raise _error("Hammer semantic context used an unsupported schema")
    _self_digest(
        context,
        digest_field="context_sha256",
        field="Hammer semantic context",
    )
    source = context.get("source_text_sha256")
    if source is not None:
        _digest(source, field="Hammer semantic context.source_text_sha256")
    artifacts = _sequence(
        context.get("artifacts"),
        field="Hammer semantic context.artifacts",
    )
    projected_artifacts: list[dict[str, object]] = []
    artifact_addresses: list[str] = []
    for index, raw_artifact in enumerate(artifacts):
        artifact = _mapping(
            raw_artifact,
            field=f"Hammer semantic context.artifacts[{index}]",
        )
        invoked = _boolean(
            artifact.get("invoked"),
            field=f"Hammer semantic context.artifacts[{index}].invoked",
        )
        status = _nonempty(
            artifact.get("status"),
            field=f"Hammer semantic context.artifacts[{index}].status",
        )
        expected_keys = (
            _SEMANTIC_ARTIFACT_SUCCESS_KEYS
            if invoked and status == "success"
            else _SEMANTIC_ARTIFACT_KEYS
        )
        _exact_keys(
            artifact,
            expected_keys,
            field=f"Hammer semantic context.artifacts[{index}]",
        )
        stage = artifact.get("stage")
        if stage not in {"spacy", "symai"}:
            raise _error("Hammer semantic context contains an unsupported stage")
        address = _digest(
            artifact.get("artifact_sha256"),
            field=f"Hammer semantic context.artifacts[{index}].artifact_sha256",
        )
        artifact_addresses.append(address)
        output = artifact.get("output_sha256")
        if output is not None:
            _digest(
                output,
                field=f"Hammer semantic context.artifacts[{index}].output_sha256",
            )
        if status == "success" and output is None:
            raise _error("successful semantic artifacts require output_sha256")
        if invoked and status == "success":
            projected_artifacts.append(
                {
                    "stage": stage,
                    "invoked": invoked,
                    "status": status,
                    "policy_reason": artifact.get("policy_reason"),
                    "evidence": _json(
                        artifact["evidence"],
                        field=(
                            f"Hammer semantic context.artifacts[{index}]."
                            "evidence"
                        ),
                    ),
                }
            )
        else:
            projected_artifacts.append(
                {
                    "stage": stage,
                    "invoked": invoked,
                    "status": status,
                    "policy_reason": artifact.get("policy_reason"),
                }
            )
    if len(set(artifact_addresses)) != len(artifact_addresses):
        raise _error("Hammer semantic artifact addresses must be unique")
    return {
        "schema": SEMANTIC_CONTEXT_SCHEMA,
        "source_text_sha256": source,
        "artifacts": projected_artifacts,
    }


def project_hammer_premise_selection_for_replay(
    value: object,
) -> dict[str, object]:
    """Validate a ranked-premise receipt and remove only upstream addresses."""

    receipt = _mapping(value, field="Hammer premise selection")
    policy = receipt.get("policy")
    if policy == "learned_selector":
        expected = _A10_PREMISE_KEYS
        selected_keys = _A10_SELECTED_KEYS
    elif policy == "symai_llm":
        expected = _A11_PREMISE_KEYS
        selected_keys = _A11_SELECTED_KEYS
    else:
        raise _error("Hammer premise selection used an unsupported policy")
    _exact_keys(receipt, expected, field="Hammer premise selection")
    if receipt.get("schema") != HAMMER_PREMISE_SELECTION_SCHEMA:
        raise _error("Hammer premise selection used an unsupported schema")
    _self_digest(
        receipt,
        digest_field="receipt_sha256",
        field="Hammer premise selection",
    )
    for name in (
        "translation_sha256",
        "source_sha256",
        "obligation_sha256",
        "candidate_set_sha256",
    ):
        _digest(receipt.get(name), field=f"Hammer premise selection.{name}")
    candidate_count = _integer(
        receipt.get("candidate_count"),
        field="Hammer premise selection.candidate_count",
    )
    top_k = _integer(
        receipt.get("top_k"),
        field="Hammer premise selection.top_k",
        minimum=1,
    )
    if top_k > candidate_count:
        raise _error("Hammer premise selection.top_k exceeds candidate_count")
    if top_k != candidate_count:
        raise _error("Hammer live premise selection must rank every candidate")
    selected = _sequence(
        receipt.get("selected"),
        field="Hammer premise selection.selected",
    )
    if len(selected) != top_k:
        raise _error("Hammer premise selection selected count does not equal top_k")
    source_indices: list[int] = []
    for index, raw_item in enumerate(selected):
        item = _mapping(
            raw_item,
            field=f"Hammer premise selection.selected[{index}]",
        )
        _exact_keys(
            item,
            selected_keys,
            field=f"Hammer premise selection.selected[{index}]",
        )
        _nonempty(
            item.get("premise_id"),
            field=f"Hammer premise selection.selected[{index}].premise_id",
        )
        if _integer(
            item.get("rank"),
            field=f"Hammer premise selection.selected[{index}].rank",
        ) != index:
            raise _error("Hammer premise selection ranks are not contiguous")
        source_index = _integer(
            item.get("source_index"),
            field=f"Hammer premise selection.selected[{index}].source_index",
        )
        if source_index >= candidate_count:
            raise _error("Hammer premise selection source_index is out of range")
        source_indices.append(source_index)
        _digest(
            item.get("statement_sha256"),
            field=(
                f"Hammer premise selection.selected[{index}]."
                "statement_sha256"
            ),
        )
        if policy == "learned_selector":
            score = item.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise _error("Hammer graph-selector score must be numeric")
            canonical_json(score)
        else:
            _integer(
                item.get("overlap_count"),
                field=(
                    f"Hammer premise selection.selected[{index}]."
                    "overlap_count"
                ),
            )
            basis_points = _integer(
                item.get("overlap_basis_points"),
                field=(
                    f"Hammer premise selection.selected[{index}]."
                    "overlap_basis_points"
                ),
            )
            if basis_points > 10_000:
                raise _error("Hammer overlap_basis_points exceeds 10000")
    if len(set(source_indices)) != len(source_indices):
        raise _error("Hammer premise selection repeats a source premise")
    if sorted(source_indices) != list(range(candidate_count)):
        raise _error("Hammer premise selection is not a complete permutation")

    if policy == "learned_selector":
        if receipt.get("ranking_contract") != "hssl-fixed-graph-selector-v1":
            raise _error("Hammer graph selector ranking contract drifted")
        if receipt.get("used_learned_selector") is not True:
            raise _error("Hammer graph selector receipt did not invoke its model")
        if receipt.get("fallback_reason") != "none":
            raise _error("Hammer graph selector receipt used a fallback")
        for name in (
            "corpus_revision",
            "selection_method",
            "model_id",
            "model_digest",
            "feature_version",
            "fallback_reason",
        ):
            _nonempty(
                receipt.get(name),
                field=f"Hammer premise selection.{name}",
            )
    else:
        ranking_contract = receipt.get("ranking_contract")
        if ranking_contract not in {
            "hssl-symai-semantic-overlap-v1",
            "ambiguity-gate-closed-source-order-v1",
        }:
            raise _error("Hammer SyMAI ranking contract drifted")
        invoked = _boolean(
            receipt.get("symai_invoked"),
            field="Hammer premise selection.symai_invoked",
        )
        expected_contract = (
            "hssl-symai-semantic-overlap-v1"
            if invoked
            else "ambiguity-gate-closed-source-order-v1"
        )
        if ranking_contract != expected_contract:
            raise _error("Hammer SyMAI invocation/ranking contract disagrees")
        for name in (
            "symai_artifact_sha256",
            "symai_identity_sha256",
            "semantic_signal_sha256",
        ):
            _digest(receipt.get(name), field=f"Hammer premise selection.{name}")
        output_digest = receipt.get("symai_output_sha256")
        if invoked:
            _digest(
                output_digest,
                field="Hammer premise selection.symai_output_sha256",
            )
        elif output_digest is not None:
            raise _error(
                "non-invoked SyMAI premise selection carried an output digest"
            )
        _integer(
            receipt.get("semantic_term_count"),
            field="Hammer premise selection.semantic_term_count",
        )

    projected = dict(receipt)
    projected.pop("receipt_sha256")
    if policy == "symai_llm":
        projected.pop("symai_artifact_sha256")
        projected.pop("symai_output_sha256")
    return projected


def validate_hammer_premise_selection_upstream_bindings(
    value: object,
    *,
    symai_artifact_sha256: str,
    symai_output_sha256: str | None,
    symai_effective_identity: object,
    symai_invoked: bool,
) -> None:
    """Bind an A11 ranking receipt to the actual consumed SyMAI artifact.

    The receipt alone can prove its own integrity, but it cannot prove that
    its three upstream addresses identify the SyMAI stage in the owning case
    graph.  Report validation supplies those graph-derived values here before
    the stable projection removes the per-run artifact and output addresses.
    """

    receipt = _mapping(value, field="Hammer premise selection")
    # Perform the complete schema/self-digest validation before examining
    # cross-stage joins.
    project_hammer_premise_selection_for_replay(receipt)
    if receipt.get("policy") != "symai_llm":
        raise _error("SyMAI upstream binding requires an A11 ranking receipt")
    actual_artifact = _digest(
        symai_artifact_sha256,
        field="SyMAI stage artifact_sha256",
    )
    if receipt.get("symai_artifact_sha256") != actual_artifact:
        raise _error("Hammer A11 ranking references another SyMAI artifact")
    if symai_output_sha256 is None:
        actual_output = None
    else:
        actual_output = _digest(
            symai_output_sha256,
            field="SyMAI stage output_sha256",
        )
    if receipt.get("symai_output_sha256") != actual_output:
        raise _error("Hammer A11 ranking references another SyMAI output")
    actual_invoked = _boolean(symai_invoked, field="SyMAI stage invoked")
    if receipt.get("symai_invoked") is not actual_invoked:
        raise _error("Hammer A11 ranking invocation state is cross-bound")
    identity = _mapping(
        symai_effective_identity,
        field="SyMAI stage effective_identity",
    )
    stable_identity = {
        key: identity[key]
        for key in (
            "provider",
            "model",
            "effective_provider",
            "effective_model",
        )
        if key in identity
    }
    identity_sha256 = hashlib.sha256(
        canonical_json(stable_identity).encode("utf-8")
    ).hexdigest()
    if receipt.get("symai_identity_sha256") != identity_sha256:
        raise _error("Hammer A11 ranking references another SyMAI backend identity")


def _project_direct_hammer(value: Mapping[str, object]) -> dict[str, object]:
    raw = dict(value)
    schema = raw.get("schema")
    if schema == HAMMER_TRANSLATION_TERMINAL_SCHEMA:
        _exact_keys(raw, _TERMINAL_KEYS, field="Hammer terminal evidence")
        _digest(raw.get("case_input_sha256"), field="Hammer.case_input_sha256")
        if raw.get("translation_status") != "unsupported":
            raise _error("Hammer terminal translation_status must be unsupported")
        if raw.get("solver_status") != "not_invoked":
            raise _error("Hammer terminal solver_status must be not_invoked")
        if raw.get("candidate_created") is not False:
            raise _error("Hammer terminal receipt cannot create a candidate")
        if raw.get("efficacy_observed") is not False:
            raise _error("Hammer terminal receipt cannot claim efficacy")
        _nonempty(raw.get("reason"), field="Hammer terminal.reason")
        raw["semantic_context"] = project_hammer_semantic_context_for_replay(
            raw["semantic_context"]
        )
        return raw

    if schema != HAMMER_TRANSLATED_ENTAILMENT_SCHEMA:
        raise _error(f"unsupported Hammer replay schema: {schema!r}")
    expected = set(_TRANSLATED_KEYS)
    if "premise_selection" in raw:
        expected.add("premise_selection")
    _exact_keys(raw, expected, field="Hammer translated evidence")
    if raw.get("translation_status") != "success":
        raise _error("Hammer translated evidence must report success")
    for name in (
        "case_input_sha256",
        "translation_sha256",
        "source_sha256",
        "obligation_sha256",
        "solver_command_sha256",
        "solver_input_sha256",
        "stdout_sha256",
        "stderr_sha256",
    ):
        _digest(raw.get(name), field=f"Hammer translated evidence.{name}")
    _nonempty(
        raw.get("translation_shape"),
        field="Hammer translated evidence.translation_shape",
    )
    _nonempty(
        raw.get("solver_status"),
        field="Hammer translated evidence.solver_status",
    )
    if raw.get("solver_status") not in {
        "sat",
        "unsat",
        "unknown",
        "inconclusive",
    }:
        raise _error("Hammer translated evidence used an unknown solver_status")
    timed_out = _boolean(
        raw.get("timed_out"),
        field="Hammer translated evidence.timed_out",
    )
    reaped = _boolean(
        raw.get("process_group_reaped"),
        field="Hammer translated evidence.process_group_reaped",
    )
    returncode = raw.get("returncode")
    if isinstance(returncode, bool) or not isinstance(returncode, int):
        raise _error(
            "Hammer translated evidence.returncode must be an integer"
        )
    termination_reason = _nonempty(
        raw.get("termination_reason"),
        field="Hammer translated evidence.termination_reason",
    )
    allowed_terminations = {
        "completed",
        "completed_with_descendant_cleanup",
        "nonzero_exit",
        "orphaned_process_group",
        "signal_exit",
        "wall_clock_deadline",
    }
    if termination_reason not in allowed_terminations:
        raise _error(
            "Hammer translated evidence used an unknown termination reason"
        )
    expected_termination = (
        "orphaned_process_group"
        if not reaped
        else (
            "wall_clock_deadline"
            if timed_out
            else (
                "signal_exit"
                if returncode < 0
                else (
                    "nonzero_exit"
                    if returncode > 0
                    else termination_reason
                )
            )
        )
    )
    if termination_reason != expected_termination or (
        returncode == 0
        and not timed_out
        and reaped
        and termination_reason
        not in {"completed", "completed_with_descendant_cleanup"}
    ):
        raise _error(
            "Hammer translated evidence termination reason is inconsistent"
        )
    proof_success = _boolean(
        raw.get("proof_success"),
        field="Hammer translated evidence.proof_success",
    )
    candidate_created = _boolean(
        raw.get("candidate_created"),
        field="Hammer translated evidence.candidate_created",
    )
    if raw.get("efficacy_observed") is not False:
        raise _error("Hammer translated evidence cannot claim efficacy")
    if proof_success is not candidate_created:
        raise _error("Hammer proof_success and candidate_created disagree")
    proof_text = raw.get("proof_text")
    reconstruction = raw.get("native_reconstruction")
    if candidate_created:
        if (
            raw.get("solver_status") != "unsat"
            or returncode != 0
            or timed_out
            or not reaped
            or not isinstance(proof_text, str)
            or not proof_text.strip()
        ):
            raise _error("Hammer candidate is inconsistent with solver evidence")
        native = _mapping(
            reconstruction,
            field="Hammer translated evidence.native_reconstruction",
        )
        _exact_keys(
            native,
            {
                "strategy",
                "certificate_sha256",
                "authoritative",
                "requires_independent_kernel",
            },
            field="Hammer translated evidence.native_reconstruction",
        )
        if native.get("strategy") != raw.get("translation_shape"):
            raise _error("Hammer reconstruction strategy drifted from translation")
        if native.get("certificate_sha256") != hashlib.sha256(
            proof_text.encode("utf-8")
        ).hexdigest():
            raise _error("Hammer native reconstruction certificate is mismatched")
        if native.get("authoritative") is not False:
            raise _error("Hammer candidate cannot be authoritative")
        if native.get("requires_independent_kernel") is not True:
            raise _error("Hammer candidate must require an independent kernel")
    elif proof_text is not None or reconstruction is not None:
        raise _error("Hammer non-candidate carried proof/reconstruction data")

    raw["semantic_context"] = project_hammer_semantic_context_for_replay(
        raw["semantic_context"]
    )
    if "premise_selection" in raw:
        premise = _mapping(
            raw["premise_selection"],
            field="Hammer translated evidence.premise_selection",
        )
        for field_name in (
            "translation_sha256",
            "source_sha256",
            "obligation_sha256",
        ):
            if premise.get(field_name) != raw.get(field_name):
                raise _error(
                    "Hammer premise selection does not bind translated evidence"
                )
        raw["premise_selection"] = (
            project_hammer_premise_selection_for_replay(premise)
        )
    return raw


def _dataclass_keys(record_type: type[object]) -> frozenset[str]:
    if not is_dataclass(record_type):
        raise _error(f"{record_type!r} is not a dataclass record type")
    return frozenset(field.name for field in fields(record_type))


def _coerce_exact_record(
    value: object,
    record_type: type[Any],
    *,
    field: str,
) -> tuple[Any, dict[str, object]]:
    raw = _mapping(value, field=field)
    _exact_keys(raw, _dataclass_keys(record_type), field=field)
    try:
        record = record_type.from_dict(dict(raw))
        validator = getattr(record, "validate", None)
        if callable(validator):
            validator()
        serialized = record.to_dict()
    except (KeyError, TypeError, ValueError) as exc:
        raise _error(
            f"{field} is not a valid {record_type.__name__}: {exc}"
        ) from exc
    canonical = _mapping(serialized, field=f"{field}.to_dict()")
    if canonical != raw:
        raise _error(f"{field} is not in canonical serialized form")
    return record, raw


def _normalize_solver_command(
    command: object,
    *,
    attempt_id: str,
    target: str,
    field: str,
) -> list[str]:
    argv = _sequence(command, field=field)
    if len(argv) < 2 or not all(
        isinstance(item, str) and item for item in argv
    ):
        raise _error(f"{field} must contain non-empty argv strings")
    suffix = {"smtlib": ".smt2", "tptp": ".p"}.get(target)
    if suffix is None:
        raise _error(f"{field} used an unsupported translation target")
    expected_name = (
        hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()[:32] + suffix
    )
    input_path = argv[-1]
    assert isinstance(input_path, str)
    path = PurePath(input_path)
    if not path.is_absolute() or path.name != expected_name:
        raise _error(f"{field} does not bind the owning solver attempt")
    parent_name = path.parent.name
    if not parent_name.startswith("itp_hammer_portfolio_"):
        raise _error(f"{field} input is not in a Hammer portfolio directory")
    normalized = list(argv)
    normalized[-1] = "<HAMMER_INPUT>"
    return normalized  # type: ignore[return-value]


def _normalize_reconstruction_command(
    command: object,
    *,
    target_itp: str,
    field: str,
) -> list[str]:
    raw = _nonempty(command, field=field)
    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        raise _error(f"{field} is not valid shell-style argv text") from exc
    if not argv:
        raise _error(f"{field} must not be empty")

    def normalize_path(
        index: int,
        *,
        prefixes: tuple[str, ...],
        basename: str,
    ) -> None:
        path = PurePath(argv[index])
        if (
            not path.is_absolute()
            or not path.parent.name.startswith(prefixes)
            or path.name != basename
        ):
            raise _error(f"{field} contains an unexpected reconstruction path")
        argv[index] = "<HAMMER_RECONSTRUCTION_SOURCE>"

    if target_itp == "lean":
        if len(argv) < 2:
            raise _error(f"{field} omitted the Lean reconstruction source")
        normalize_path(
            -1,
            prefixes=("hammer-lean-recon-", "lean-proof-gate-"),
            basename="Reconstruction.lean",
        )
    elif target_itp == "coq":
        if len(argv) < 2:
            raise _error(f"{field} omitted the Coq reconstruction source")
        normalize_path(
            -1,
            prefixes=("hammer-coq-recon-",),
            basename="Reconstruction.v",
        )
    elif target_itp == "isabelle":
        try:
            directory_index = argv.index("-d") + 1
        except (ValueError, IndexError) as exc:
            raise _error(f"{field} omitted Isabelle's -d directory") from exc
        directory = PurePath(argv[directory_index])
        if (
            not directory.is_absolute()
            or not directory.name.startswith("hammer-isabelle-recon-")
        ):
            raise _error(f"{field} contains an unexpected Isabelle directory")
        argv[directory_index] = "<HAMMER_RECONSTRUCTION_DIRECTORY>"
    else:
        raise _error(f"{field} used an unsupported target ITP")
    return argv


def _normalize_kernel_command_template(
    template: object,
    *,
    target_itp: str,
    pinned_executable: str,
    reconstruction_command: Sequence[object],
    field: str,
) -> list[str]:
    """Render a pinned kernel template and bind it to the executed argv."""

    raw = _nonempty(template, field=field)
    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        raise _error(f"{field} is not valid shell-style argv text") from exc
    if not argv:
        raise _error(f"{field} must not be empty")
    executable_name = {
        "lean": "lean",
        "coq": "coqtop",
        "isabelle": "isabelle",
    }.get(target_itp)
    if executable_name is None:
        raise _error(f"{field} used an unsupported target ITP")
    executable_placeholder = "{" + executable_name + "}"
    executable_aliases = {
        executable_placeholder,
        executable_name,
        PurePath(pinned_executable).name,
        pinned_executable,
    }
    if argv[0] not in executable_aliases:
        raise _error(f"{field} executable is not environment-locked")
    argv[0] = pinned_executable

    source_placeholders = {"{source_file}", "{proof_file}"}
    directory_placeholder = "{dir}"
    theory_placeholder = "{theory_name}"
    wildcard_indices: set[int] = set()
    source_count = 0
    directory_count = 0
    for index, token in enumerate(argv[1:], start=1):
        if token in source_placeholders:
            argv[index] = "<HAMMER_RECONSTRUCTION_SOURCE>"
            source_count += 1
        elif token == directory_placeholder:
            argv[index] = "<HAMMER_RECONSTRUCTION_DIRECTORY>"
            directory_count += 1
        elif token == theory_placeholder:
            wildcard_indices.add(index)
        elif "{" in token or "}" in token:
            raise _error(f"{field} contains an unsupported placeholder")
    if target_itp in {"lean", "coq"} and (
        source_count != 1 or directory_count != 0 or wildcard_indices
    ):
        raise _error(f"{field} must bind exactly one reconstruction source")
    if target_itp == "isabelle" and (
        source_count != 0 or directory_count != 1
    ):
        raise _error(
            f"{field} must bind exactly one reconstruction directory"
        )

    executed = list(reconstruction_command)
    if len(argv) != len(executed):
        raise _error(f"{field} disagrees with the reconstruction command")
    for index, (template_token, executed_token) in enumerate(
        zip(argv, executed, strict=True)
    ):
        if not isinstance(executed_token, str) or not executed_token:
            raise _error(
                "Hammer reconstruction command contains an invalid argv token"
            )
        if index in wildcard_indices:
            if executed_token.startswith("<HAMMER_"):
                raise _error(
                    f"{field} theory placeholder did not bind a concrete value"
                )
            argv[index] = executed_token
        elif template_token != executed_token:
            raise _error(f"{field} disagrees with the reconstruction command")
    return argv


def project_hammer_reconstruction_for_replay(
    value: object,
    *,
    request_id: str,
    candidate_id: str,
    environment_lock_id: str,
) -> dict[str, object]:
    """Return the stable, source-bound projection of one native reconstruction."""

    from ipfs_datasets_py.logic.hammers.models import ReconstructionRecord

    record, raw = _coerce_exact_record(
        value,
        ReconstructionRecord,
        field="Hammer reconstruction",
    )
    if record.request_id != request_id:
        raise _error("Hammer reconstruction belongs to another request")
    if record.candidate_id != candidate_id:
        raise _error("Hammer reconstruction belongs to another candidate")
    if record.environment_lock_id != environment_lock_id:
        raise _error("Hammer reconstruction environment lock is mismatched")
    if record.kernel_output_digest is not None:
        _content_address(
            raw["kernel_output_digest"],
            field="Hammer reconstruction.kernel_output_digest",
        )
    projected = dict(raw)
    projected["reconstruction_id"] = "@reconstruction"
    projected["request_id"] = "@request"
    projected["candidate_id"] = "@candidate"
    projected["environment_lock_id"] = "@environment"
    projected["kernel_command"] = _normalize_reconstruction_command(
        raw["kernel_command"],
        target_itp=str(raw["target_itp"]),
        field="Hammer reconstruction.kernel_command",
    )
    projected.pop("started_at")
    projected.pop("finished_at")
    return projected


def _project_full_hammer(value: Mapping[str, object]) -> dict[str, object]:
    raw = dict(value)
    _exact_keys(raw, _FULL_EVIDENCE_KEYS, field="Hammer evidence")
    if raw.get("schema") != HAMMER_EVIDENCE_SCHEMA:
        raise _error("Hammer evidence used an unsupported schema")
    _self_digest(raw, digest_field="evidence_id", field="Hammer evidence")

    # Native imports stay below schema dispatch so direct live receipts remain
    # usable in installations without the optional Hammer package.
    from ipfs_datasets_py.logic.hammers.corpus import compute_content_digest
    from ipfs_datasets_py.logic.hammers.models import (
        EnvironmentLockRecord,
        HammerRequest,
        ProofCandidateRecord,
        ReconstructionRecord,
        SolverAttemptRecord,
    )
    from ipfs_datasets_py.logic.hammers.portfolio import (
        PortfolioRunResult,
        SolverAttemptEvidence,
    )
    from ipfs_datasets_py.logic.hammers.provenance import NormalizedEvidence

    request, request_raw = _coerce_exact_record(
        raw["request"],
        HammerRequest,
        field="Hammer request",
    )
    policy_raw = _mapping(
        request_raw["policy"],
        field="Hammer request.policy",
    )
    _exact_keys(
        policy_raw,
        _dataclass_keys(type(request.policy)),
        field="Hammer request.policy",
    )
    if request.policy.to_dict() != policy_raw:
        raise _error("Hammer request.policy is not canonically serialized")

    portfolio, portfolio_raw = _coerce_exact_record(
        raw["portfolio"],
        PortfolioRunResult,
        field="Hammer portfolio",
    )
    if portfolio.request_id != request.request_id:
        raise _error("Hammer portfolio belongs to another request")

    attempt_records: dict[str, Any] = {}
    attempt_raw_by_id: dict[str, dict[str, object]] = {}
    attempt_tokens: dict[str, str] = {}
    translation_tokens: dict[str, str] = {}
    projected_attempts: list[dict[str, object]] = []
    attempts_raw = _sequence(
        portfolio_raw["attempts"],
        field="Hammer portfolio.attempts",
    )
    for index, attempt_value in enumerate(attempts_raw):
        attempt, attempt_raw = _coerce_exact_record(
            attempt_value,
            SolverAttemptRecord,
            field=f"Hammer portfolio.attempts[{index}]",
        )
        attempt_id = attempt.attempt_id
        if attempt_id in attempt_records:
            raise _error("Hammer portfolio repeats a solver attempt_id")
        if attempt.request_id != request.request_id:
            raise _error("Hammer solver attempt belongs to another request")
        if attempt.solver_name not in request.policy.allowed_solvers:
            raise _error("Hammer solver attempt used a non-allowlisted solver")
        if attempt.timeout_seconds > request.policy.timeout_seconds:
            raise _error("Hammer solver attempt exceeded the request timeout")
        if attempt.network_used and not request.policy.network_allowed:
            raise _error("Hammer solver attempt used denied network access")
        attempt_records[attempt_id] = attempt
        attempt_raw_by_id[attempt_id] = attempt_raw
        attempt_tokens[attempt_id] = f"@attempt-{index:03d}"
        if attempt.translation_id not in translation_tokens:
            translation_tokens[attempt.translation_id] = (
                f"@translation-{len(translation_tokens):03d}"
            )
        projected = dict(attempt_raw)
        projected["attempt_id"] = attempt_tokens[attempt_id]
        projected["request_id"] = "@request"
        projected["translation_id"] = translation_tokens[attempt.translation_id]
        projected.pop("started_at")
        projected.pop("finished_at")
        projected.pop("wall_time_seconds")
        resource_usage = _mapping(
            attempt_raw["resource_usage"],
            field=f"Hammer portfolio.attempts[{index}].resource_usage",
        )
        for name in _OPERATIONAL_ATTEMPT_RESOURCE_FIELDS:
            resource_usage.pop(name, None)
        projected["resource_usage"] = resource_usage
        projected_attempts.append(projected)

    evidence_raw = _mapping(
        portfolio_raw["evidence"],
        field="Hammer portfolio.evidence",
    )
    if set(evidence_raw) != set(attempt_records):
        raise _error("Hammer portfolio evidence must cover every solver attempt")
    projected_evidence: dict[str, object] = {}
    for attempt_id, attempt in attempt_records.items():
        evidence, one_raw = _coerce_exact_record(
            evidence_raw[attempt_id],
            SolverAttemptEvidence,
            field=f"Hammer portfolio.evidence[{attempt_id!r}]",
        )
        if evidence.attempt_id != attempt_id:
            raise _error("Hammer solver evidence key/attempt_id disagree")
        _content_address(
            one_raw["input_digest"],
            field=f"Hammer portfolio.evidence[{attempt_id!r}].input_digest",
        )
        if not isinstance(one_raw["raw_stdout"], str):
            raise _error("Hammer solver evidence raw_stdout must be a string")
        if not isinstance(one_raw["raw_stderr"], str):
            raise _error("Hammer solver evidence raw_stderr must be a string")
        if one_raw["solver_trace"] is not None and not isinstance(
            one_raw["solver_trace"], str
        ):
            raise _error(
                "Hammer solver evidence solver_trace must be null or a string"
            )
        expected_raw_digest = compute_content_digest(
            {
                "stdout": evidence.raw_stdout,
                "stderr": evidence.raw_stderr,
            }
        )
        if attempt.raw_output_digest != expected_raw_digest:
            raise _error("Hammer solver output digest does not match raw evidence")
        one_projected = dict(one_raw)
        one_projected["attempt_id"] = attempt_tokens[attempt_id]
        one_projected["command"] = _normalize_solver_command(
            one_raw["command"],
            attempt_id=attempt_id,
            target=attempt.target.value,
            field=f"Hammer portfolio.evidence[{attempt_id!r}].command",
        )
        projected_evidence[attempt_tokens[attempt_id]] = one_projected

    cancelled = _sequence(
        portfolio_raw["cancelled_attempt_ids"],
        field="Hammer portfolio.cancelled_attempt_ids",
    )
    if (
        len(set(cancelled)) != len(cancelled)
        or any(item not in attempt_tokens for item in cancelled)
    ):
        raise _error("Hammer portfolio cancellation ids are invalid")
    denied_raw = _sequence(
        portfolio_raw["denied"],
        field="Hammer portfolio.denied",
    )
    projected_denied: list[dict[str, object]] = []
    for index, raw_denial in enumerate(denied_raw):
        denial = _mapping(
            raw_denial,
            field=f"Hammer portfolio.denied[{index}]",
        )
        _exact_keys(
            denial,
            {"solver_name", "translation_id", "reason"},
            field=f"Hammer portfolio.denied[{index}]",
        )
        for name in ("solver_name", "translation_id", "reason"):
            _nonempty(
                denial.get(name),
                field=f"Hammer portfolio.denied[{index}].{name}",
            )
        translation_id = str(denial["translation_id"])
        if translation_id not in translation_tokens:
            translation_tokens[translation_id] = (
                f"@translation-{len(translation_tokens):03d}"
            )
        projected_denial = dict(denial)
        projected_denial["translation_id"] = translation_tokens[translation_id]
        projected_denied.append(projected_denial)

    telemetry = _mapping(
        portfolio_raw["resource_telemetry"],
        field="Hammer portfolio.resource_telemetry",
    )
    for name in _OPERATIONAL_PORTFOLIO_TELEMETRY_FIELDS:
        telemetry.pop(name, None)
    projected_portfolio = dict(portfolio_raw)
    projected_portfolio["request_id"] = "@request"
    projected_portfolio["attempts"] = projected_attempts
    projected_portfolio["evidence"] = projected_evidence
    projected_portfolio["denied"] = projected_denied
    projected_portfolio["cancelled_attempt_ids"] = [
        attempt_tokens[str(item)] for item in cancelled
    ]
    projected_portfolio["resource_telemetry"] = telemetry

    candidate = None
    candidate_raw: dict[str, object] | None = None
    if raw["proof_candidate"] is not None:
        candidate, candidate_raw = _coerce_exact_record(
            raw["proof_candidate"],
            ProofCandidateRecord,
            field="Hammer proof candidate",
        )
        if candidate.request_id != request.request_id:
            raise _error("Hammer proof candidate belongs to another request")
        if candidate.solver_attempt_id not in attempt_records:
            raise _error("Hammer proof candidate references an unknown attempt")

    normalized_raw = _mapping(
        raw["normalized_evidence"],
        field="Hammer normalized_evidence",
    )
    if set(normalized_raw) - set(attempt_records):
        raise _error("Hammer normalized evidence references an unknown attempt")
    projected_normalized: dict[str, object] = {}
    for attempt_id, raw_normalized in normalized_raw.items():
        normalized, normalized_record_raw = _coerce_exact_record(
            raw_normalized,
            NormalizedEvidence,
            field=f"Hammer normalized_evidence[{attempt_id!r}]",
        )
        digest_body = dict(normalized_record_raw)
        supplied_content = digest_body.pop("content_digest")
        supplied_evidence = digest_body.pop("evidence_id")
        expected_content = compute_content_digest(digest_body)
        if (
            supplied_content != expected_content
            or supplied_evidence != expected_content
        ):
            raise _error("Hammer normalized evidence content address is invalid")
        attempt = attempt_records.get(attempt_id)
        if (
            attempt is None
            or normalized.request_id != request.request_id
            or normalized.attempt_id != attempt_id
        ):
            raise _error("Hammer normalized evidence key/join is invalid")
        if normalized.verdict is not attempt.verdict:
            raise _error("Hammer normalized evidence verdict drifted from attempt")
        if normalized.candidate_id is not None and (
            candidate is None
            or normalized.candidate_id != candidate.candidate_id
        ):
            raise _error("Hammer normalized evidence candidate join is invalid")
        if normalized.translation_ids != [attempt.translation_id]:
            raise _error(
                "Hammer normalized evidence must bind exactly its translation"
            )
        evidence = portfolio.evidence[attempt_id]
        expected_trace = (
            compute_content_digest(
                {
                    "stdout": evidence.raw_stdout,
                    "stderr": evidence.raw_stderr,
                }
            )
            if evidence.raw_stdout or evidence.raw_stderr
            else None
        )
        if normalized.raw_trace_digest != expected_trace:
            raise _error("Hammer normalized trace digest is source-mismatched")
        projected = dict(normalized_record_raw)
        projected["request_id"] = "@request"
        projected["attempt_id"] = attempt_tokens[attempt_id]
        projected["candidate_id"] = (
            None if normalized.candidate_id is None else "@candidate"
        )
        projected["translation_ids"] = [
            translation_tokens[translation_id]
            for translation_id in normalized.translation_ids
        ]
        projected.pop("evidence_id")
        projected.pop("content_digest")
        projected_normalized[attempt_tokens[attempt_id]] = projected

    reconstruction = None
    reconstruction_raw = raw["reconstruction"]
    environment = None
    environment_raw = raw["environment_lock"]
    if reconstruction_raw is not None:
        if candidate is None or candidate_raw is None or environment_raw is None:
            raise _error(
                "Hammer reconstruction requires candidate and environment lock"
            )
        environment_record, environment_dict = _coerce_exact_record(
            environment_raw,
            EnvironmentLockRecord,
            field="Hammer environment lock",
        )
        if environment_record.itp is not request.itp:
            raise _error("Hammer environment lock targets another ITP")
        expected_policy_digest = compute_content_digest(
            request.policy.to_dict()
        )
        if environment_record.policy_digest != expected_policy_digest:
            raise _error(
                "Hammer environment lock policy_digest is request-mismatched"
            )
        if environment_record.container_digest is not None:
            _content_address(
                environment_dict["container_digest"],
                field="Hammer environment lock.container_digest",
            )
        lock_payload = {
            key: environment_dict[key]
            for key in (
                "itp",
                "itp_version",
                "kernel_command_template",
                "solver_versions",
                "executable_paths",
                "os_info",
                "container_digest",
                "policy_digest",
            )
        }
        expected_lock_id = compute_content_digest(lock_payload)
        if environment_record.lock_id != expected_lock_id:
            raise _error("Hammer environment lock_id is not content-addressed")
        reconstruction_record, _ = _coerce_exact_record(
            reconstruction_raw,
            ReconstructionRecord,
            field="Hammer reconstruction",
        )
        if reconstruction_record.target_itp is not request.itp:
            raise _error("Hammer reconstruction targets another ITP")
        reconstruction = project_hammer_reconstruction_for_replay(
            reconstruction_raw,
            request_id=request.request_id,
            candidate_id=candidate.candidate_id,
            environment_lock_id=environment_record.lock_id,
        )
        primary_executable = {
            "lean": "lean",
            "coq": "coqtop",
            "isabelle": "isabelle",
        }[request.itp.value]
        pinned_kernel = environment_record.executable_paths.get(
            primary_executable
        )
        if (
            not isinstance(pinned_kernel, str)
            or not pinned_kernel.strip()
            or not PurePath(pinned_kernel).is_absolute()
            or reconstruction["kernel_command"][0] != pinned_kernel
        ):
            raise _error(
                "Hammer reconstruction command is not environment-locked"
            )
        _normalize_kernel_command_template(
            environment_record.kernel_command_template,
            target_itp=request.itp.value,
            pinned_executable=pinned_kernel,
            reconstruction_command=reconstruction["kernel_command"],
            field="Hammer environment lock.kernel_command_template",
        )
        for attempt_id, attempt in attempt_records.items():
            command = projected_evidence[attempt_tokens[attempt_id]][
                "command"
            ]
            pinned_solver = environment_record.executable_paths.get(
                attempt.solver_name
            )
            if (
                not isinstance(pinned_solver, str)
                or not pinned_solver.strip()
                or not PurePath(pinned_solver).is_absolute()
                or command[0] != pinned_solver
            ):
                raise _error(
                    "Hammer solver command is not environment-locked"
                )
            pinned_version = environment_record.solver_versions.get(
                attempt.solver_name
            )
            if (
                not isinstance(pinned_version, str)
                or not pinned_version.strip()
                or attempt.solver_version != pinned_version
            ):
                raise _error(
                    "Hammer solver version is not environment-locked"
                )
        environment = dict(environment_dict)
        environment["lock_id"] = "@environment"
        environment.pop("pinned_at")
    elif environment_raw is not None:
        raise _error("orphan Hammer environment lock has no reconstruction")

    accepted = bool(
        reconstruction_raw is not None
        and reconstruction is not None
        and reconstruction["kernel_accepted"] is True
    )
    if raw["reconstruction_kernel_accepted"] is not accepted:
        raise _error("Hammer reconstruction acceptance summary is inconsistent")
    expected_status = (
        "verified"
        if accepted
        else ("candidate" if candidate is not None else "unknown")
    )
    if raw["status"] != expected_status:
        raise _error("Hammer status is inconsistent with its native records")

    request_projected = dict(request_raw)
    request_projected["request_id"] = "@request"
    request_projected.pop("created_at")
    candidate_projected: dict[str, object] | None = None
    if candidate is not None and candidate_raw is not None:
        candidate_projected = dict(candidate_raw)
        candidate_projected["candidate_id"] = "@candidate"
        candidate_projected["request_id"] = "@request"
        candidate_projected["solver_attempt_id"] = attempt_tokens[
            candidate.solver_attempt_id
        ]

    return {
        "schema": HAMMER_EVIDENCE_SCHEMA,
        "request": request_projected,
        "portfolio": projected_portfolio,
        "normalized_evidence": projected_normalized,
        "proof_candidate": candidate_projected,
        "reconstruction": reconstruction,
        "environment_lock": environment,
        "reconstruction_kernel_accepted": accepted,
        "status": expected_status,
    }


def project_hammer_data_for_replay(value: object) -> dict[str, object]:
    """Project one supported Hammer data payload after strict validation."""

    raw = _mapping(value, field="Hammer replay evidence")
    schema = raw.get("schema")
    if schema == HAMMER_EVIDENCE_SCHEMA:
        return _project_full_hammer(raw)
    if schema in {
        HAMMER_TRANSLATED_ENTAILMENT_SCHEMA,
        HAMMER_TRANSLATION_TERMINAL_SCHEMA,
    }:
        return _project_direct_hammer(raw)
    raise _error(f"unsupported Hammer replay schema: {schema!r}")


def _full_hammer_failure_code(
    data: Mapping[str, object],
) -> FailureCode | None:
    """Derive a failed full-record boundary from its native records."""

    reconstruction = data.get("reconstruction")
    if isinstance(reconstruction, Mapping):
        return (
            FailureCode.RECONSTRUCTION_FAILURE
            if reconstruction.get("kernel_accepted") is False
            else None
        )
    # A candidate without a reconstruction is a normal, non-authoritative
    # successful Hammer result.  It contains no evidence that reconstruction
    # was attempted and therefore cannot substantiate an outer failure.
    if data.get("proof_candidate") is not None:
        return None
    portfolio = data.get("portfolio")
    if not isinstance(portfolio, Mapping):
        return None  # the strict data projection reports the schema error
    attempts = portfolio.get("attempts")
    if not isinstance(attempts, Sequence) or isinstance(
        attempts, (str, bytes, bytearray)
    ):
        return None

    saw_signal_or_spawn_failure = False
    saw_solver_failure = False
    attempt_ids: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            return None
        attempt_id = attempt.get("attempt_id")
        if isinstance(attempt_id, str):
            attempt_ids.add(attempt_id)
        exit_code = attempt.get("exit_code")
        verdict = attempt.get("verdict")
        if verdict == "timeout":
            # A bounded timeout normally terminates the process by signal;
            # the typed verdict, like the direct receipt's timed_out flag,
            # takes priority over that cleanup return code.
            saw_solver_failure = True
        elif (
            (
                isinstance(exit_code, int)
                and not isinstance(exit_code, bool)
                and exit_code < 0
            )
            or (verdict == "error" and exit_code is None)
        ):
            saw_signal_or_spawn_failure = True
        elif (
            verdict == "error"
            or (
                isinstance(exit_code, int)
                and not isinstance(exit_code, bool)
                and exit_code > 0
            )
        ):
            saw_solver_failure = True
    if saw_signal_or_spawn_failure:
        return FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
    if saw_solver_failure:
        return FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE

    cancelled = portfolio.get("cancelled_attempt_ids")
    if (
        attempt_ids
        and isinstance(cancelled, Sequence)
        and not isinstance(cancelled, (str, bytes, bytearray))
        and set(cancelled) == attempt_ids
    ):
        return FailureCode.RESOURCE_LEASE_CANCELLATION
    return None


def _validate_hammer_stage_outcome(
    stage: StageRecord,
    data: Mapping[str, object],
) -> None:
    """Bind a supported Hammer receipt to its enclosing terminal status."""

    schema = data.get("schema")
    if stage.status is StageStatus.SUCCESS:
        if schema == HAMMER_TRANSLATED_ENTAILMENT_SCHEMA and (
            data.get("timed_out") is not False
            or data.get("process_group_reaped") is not True
            or data.get("returncode") != 0
            or data.get("termination_reason")
            not in {"completed", "completed_with_descendant_cleanup"}
        ):
            raise _error(
                "successful Hammer stage contains a failed process outcome"
            )
        return
    if stage.status is not StageStatus.FAILED:
        raise _error(
            "supported Hammer evidence must have success or failed status"
        )
    if schema == HAMMER_TRANSLATION_TERMINAL_SCHEMA:
        raise _error(
            "unsupported-translation Hammer receipt must remain a successful "
            "typed terminal outcome"
        )
    if schema == HAMMER_TRANSLATED_ENTAILMENT_SCHEMA:
        timed_out = data.get("timed_out") is True
        reaped = data.get("process_group_reaped") is True
        returncode = data.get("returncode")
        expected_failure = (
            FailureCode.ORPHANED_CHILD
            if not reaped
            else (
                FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE
                if timed_out
                else (
                    FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
                    if isinstance(returncode, int)
                    and not isinstance(returncode, bool)
                    and returncode < 0
                    else (
                        FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE
                        if isinstance(returncode, int)
                        and not isinstance(returncode, bool)
                        and returncode > 0
                        else None
                    )
                )
            )
        )
        if (
            expected_failure is None
            or stage.failure_code is not expected_failure
        ):
            raise _error(
                "failed Hammer stage disagrees with its process outcome"
            )
        return
    if schema == HAMMER_EVIDENCE_SCHEMA:
        expected_failure = _full_hammer_failure_code(data)
        if expected_failure is None or stage.failure_code is not expected_failure:
            raise _error(
                "failed full Hammer stage disagrees with its native records"
            )


def project_hammer_stage_for_replay(stage: StageRecord) -> dict[str, object]:
    """Project a terminal Hammer :class:`StageRecord` and identity.

    The compact context/ranking addresses in ``effective_identity`` are first
    joined to their data receipts and only then removed.  All other identity
    fields remain exact.
    """

    if not isinstance(stage, StageRecord):
        raise _error("Hammer replay stage must be a StageRecord")
    if stage.stage is not StageName.HAMMER:
        raise _error("Hammer replay projection received a non-Hammer stage")
    data_raw = _mapping(stage.data, field="Hammer stage.data")
    projected_data = project_hammer_data_for_replay(data_raw)
    _validate_hammer_stage_outcome(stage, data_raw)
    identity = _mapping(
        stage.provenance.effective_identity,
        field="Hammer stage.effective_identity",
    )
    requested_identity = _mapping(
        stage.provenance.requested_identity,
        field="Hammer stage.requested_identity",
    )
    if data_raw.get("schema") == HAMMER_EVIDENCE_SCHEMA:
        request = _mapping(
            data_raw.get("request"),
            field="Hammer stage.data.request",
        )
        request_id = _nonempty(
            request.get("request_id"),
            field="Hammer stage.data.request.request_id",
        )
        for identity_name, identity_value in (
            ("effective_identity", identity),
            ("requested_identity", requested_identity),
        ):
            for name in ("request_id", "hammer_request_id"):
                if name not in identity_value:
                    continue
                if identity_value[name] != request_id:
                    raise _error(
                        f"Hammer stage {identity_name}.{name} is cross-bound"
                    )
                identity_value[name] = "@request"
    semantic = data_raw.get("semantic_context")
    if semantic is not None:
        binding = _mapping(semantic, field="Hammer stage semantic binding")
        context_digest = binding.get("context_sha256")
        if identity.get("semantic_context_sha256") != context_digest:
            raise _error("Hammer semantic context does not bind stage identity")
    elif "semantic_context_sha256" in identity:
        raise _error("Hammer identity has an orphan semantic-context binding")
    premise = data_raw.get("premise_selection")
    if premise is not None:
        premise_mapping = _mapping(
            premise,
            field="Hammer stage premise selection",
        )
        if (
            identity.get("premise_selection_sha256")
            != premise_mapping.get("receipt_sha256")
        ):
            raise _error("Hammer premise selection does not bind stage identity")
        if (
            identity.get("premise_ranking_contract")
            != premise_mapping.get("ranking_contract")
        ):
            raise _error(
                "Hammer premise ranking contract does not bind stage identity"
            )
    elif "premise_selection_sha256" in identity:
        raise _error("Hammer identity has an orphan premise-selection binding")
    for name in _OPERATIONAL_IDENTITY_FIELDS:
        identity.pop(name, None)
    return {
        "data": projected_data,
        "effective_identity": identity,
        "requested_identity": requested_identity,
    }


def stable_hammer_replay_projection(value: object) -> dict[str, object]:
    """Public dispatch helper for either a Hammer stage or raw data mapping."""

    if isinstance(value, StageRecord):
        return project_hammer_stage_for_replay(value)
    return project_hammer_data_for_replay(value)


def validate_hammer_replay_equivalence(
    original: object,
    replayed: object,
) -> None:
    """Reject any stable Hammer semantic, solver, or trust-boundary drift."""

    original_projection = stable_hammer_replay_projection(original)
    replayed_projection = stable_hammer_replay_projection(replayed)
    if original_projection != replayed_projection:
        raise _error(
            "Hammer replay drifted in semantic, solver, certificate, "
            "environment, or reconstruction evidence"
        )


__all__ = [
    "HAMMER_EVIDENCE_SCHEMA",
    "HAMMER_PREMISE_SELECTION_SCHEMA",
    "HAMMER_TRANSLATED_ENTAILMENT_SCHEMA",
    "HAMMER_TRANSLATION_TERMINAL_SCHEMA",
    "HammerReplayError",
    "project_hammer_data_for_replay",
    "project_hammer_premise_selection_for_replay",
    "project_hammer_reconstruction_for_replay",
    "project_hammer_semantic_context_for_replay",
    "project_hammer_stage_for_replay",
    "stable_hammer_replay_projection",
    "validate_hammer_premise_selection_upstream_bindings",
    "validate_hammer_replay_equivalence",
]
