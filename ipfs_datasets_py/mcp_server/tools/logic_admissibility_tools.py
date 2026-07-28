"""MCP tools for Intent normalize / formalize / proof-corpus query / admissibility.

Interface: ``MCPIntentAdmissibility@1`` (LIG-018 / LIG-G070).

Exposed tools
-------------
* ``normalize_intent`` — skill / prompt / MCP tool → IntentIR (non-executing)
* ``formalize_intent`` — IntentIR → formalization artifact (no provers)
* ``query_proof_corpus`` — CID / source / family / obligation lookups
* ``check_intent_admissibility`` — IntentAdmissibilityGate@1 join

Fail-closed invariants
----------------------
* Handlers never execute skill_md, prompt text, MCP tool bodies, shell, or
  eval.  Source bodies are only passed as opaque strings into read-only
  normalizers and formalizers.
* Malformed input, unknown source kinds, policy denials, integrity failures,
  and missing corpus evidence return structured reject/error/abstain payloads
  — never a silent allow.
* Optional heavy provers are not imported at module load time.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

MCP_INTENT_ADMISSIBILITY_INTERFACE: Final = "MCPIntentAdmissibility@1"
MCP_INTENT_ADMISSIBILITY_SCHEMA_VERSION: Final = "mcp-intent-admissibility/v1"

TOOL_NAMES: Final[tuple[str, ...]] = (
    "normalize_intent",
    "formalize_intent",
    "query_proof_corpus",
    "check_intent_admissibility",
)

SOURCE_KINDS: Final[frozenset[str]] = frozenset({"skill", "prompt", "mcp_tool"})

# Documented JSON-ish schemas for MCP discovery / operator docs.
TOOL_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "normalize_intent": {
        "name": "normalize_intent",
        "interface": MCP_INTENT_ADMISSIBILITY_INTERFACE,
        "description": (
            "Normalize a skill, free-form prompt, or MCP tool definition into "
            "IntentIR without executing source bodies."
        ),
        "parameters": {
            "type": "object",
            "required": ["source_kind", "source"],
            "properties": {
                "source_kind": {
                    "type": "string",
                    "enum": sorted(SOURCE_KINDS),
                    "description": "Which source adapter to use.",
                },
                "source": {
                    "type": "object",
                    "description": (
                        "Source payload. For skill: skill_md + identity fields. "
                        "For prompt: text (+ optional title/source_id). "
                        "For mcp_tool: name (+ optional description/input_schema)."
                    ),
                },
            },
        },
        "returns": {
            "success": "bool",
            "status": "ok | reject | error",
            "document": "IntentIR document map when success",
            "policy": "source policy decision map when available",
            "executed": "always false",
        },
    },
    "formalize_intent": {
        "name": "formalize_intent",
        "interface": MCP_INTENT_ADMISSIBILITY_INTERFACE,
        "description": (
            "Compile a validated IntentIR document into a formalization "
            "artifact without invoking proof backends or executing sources."
        ),
        "parameters": {
            "type": "object",
            "required": ["document"],
            "properties": {
                "document": {
                    "type": "object",
                    "description": "IntentIRDocument map (Intent IR v1).",
                },
                "put_in_store": {
                    "type": "boolean",
                    "default": False,
                    "description": "When true, put the Intent envelope into the store.",
                },
                "store_root": {
                    "type": "string",
                    "description": "Optional filesystem root for ProofCorpusStore.",
                },
                "profile": {
                    "type": "string",
                    "default": "legal-strict",
                    "description": "Envelope profile id when putting into the store.",
                },
                "envelopes": {
                    "type": "array",
                    "description": "Optional seed envelopes for an ephemeral store.",
                },
            },
        },
        "returns": {
            "success": "bool",
            "status": "ok | reject | error",
            "artifact": "FormalizationArtifact map when success",
            "content_cid": "proof-corpus content CID when put_in_store",
            "executed": "always false",
        },
    },
    "query_proof_corpus": {
        "name": "query_proof_corpus",
        "interface": MCP_INTENT_ADMISSIBILITY_INTERFACE,
        "description": (
            "Query the proof corpus by CID, family, profile, source, and/or "
            "obligation digest.  Integrity is re-verified on load."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "store_root": {"type": "string"},
                "envelopes": {"type": "array"},
                "content_cid": {"type": "string"},
                "family": {"type": "string", "enum": ["intent", "legal", "security"]},
                "profile": {"type": "string"},
                "source_digest": {"type": "string"},
                "source_id": {"type": "string"},
                "obligation_digest": {"type": "string"},
            },
        },
        "returns": {
            "success": "bool",
            "status": "ok | reject | error",
            "envelopes": "list of envelope maps",
            "count": "int",
            "executed": "always false",
        },
    },
    "check_intent_admissibility": {
        "name": "check_intent_admissibility",
        "interface": MCP_INTENT_ADMISSIBILITY_INTERFACE,
        "description": (
            "Evaluate Intent formal obligations against attested Legal and "
            "Security constraints under a declared admissibility profile."
        ),
        "parameters": {
            "type": "object",
            "required": ["intent"],
            "properties": {
                "intent": {
                    "description": (
                        "Intent content CID (string), envelope map, or "
                        "FormalizationArtifact map."
                    ),
                },
                "profile": {
                    "type": "string",
                    "default": "legal-strict",
                    "description": "Admissibility profile id.",
                },
                "store_root": {"type": "string"},
                "envelopes": {"type": "array"},
            },
        },
        "returns": {
            "success": "bool",
            "status": "allow | reject | abstain | error",
            "decision": "AdmissibilityDecision@1 map when available",
            "executed": "always false",
        },
    },
}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _base_response(tool: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "executed": False,
        "interface": MCP_INTENT_ADMISSIBILITY_INTERFACE,
        "schema_version": MCP_INTENT_ADMISSIBILITY_SCHEMA_VERSION,
        "tool": tool,
    }
    payload.update(extra)
    return payload


def _ok(tool: str, **extra: Any) -> dict[str, Any]:
    return _base_response(tool, success=True, status="ok", **extra)


def _fail(
    tool: str,
    *,
    status: str = "reject",
    error: str,
    error_type: str = "fail_closed",
    **extra: Any,
) -> dict[str, Any]:
    """Structured fail-closed response (never status=allow)."""

    if status == "allow":
        status = "reject"
        error = f"{error}; coerced away from allow (fail closed)"
    return _base_response(
        tool,
        success=False,
        status=status,
        error=error,
        error_type=error_type,
        **extra,
    )


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _optional_str(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string when provided")
    return value


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


def _open_store(
    store_root: str | Path | None = None,
    envelopes: Sequence[Mapping[str, Any]] | None = None,
) -> Any:
    """Open a ProofCorpusStore, optionally seeding envelopes.

    Raises
    ------
    ValueError
        When neither a usable store_root nor envelopes is available and the
        caller needs a non-empty corpus surface, or when envelopes are
        malformed.
    """

    from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
    from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore

    root: Path | None = None
    if store_root is not None:
        if not isinstance(store_root, (str, Path)) or (
            isinstance(store_root, str) and not store_root.strip()
        ):
            raise ValueError("store_root must be a non-empty path string")
        root = Path(store_root)
        if not root.exists():
            raise ValueError(f"store_root does not exist: {root}")

    store = ProofCorpusStore(root=root)
    if envelopes is not None:
        if not isinstance(envelopes, Sequence) or isinstance(
            envelopes, (str, bytes, bytearray)
        ):
            raise TypeError("envelopes must be a sequence of mappings")
        for index, item in enumerate(envelopes):
            if not isinstance(item, Mapping):
                raise TypeError(f"envelopes[{index}] must be a mapping")
            envelope = ArtifactEnvelope.from_dict(item)
            store.put(envelope)
    return store


def _envelope_summary(envelope: Any) -> dict[str, Any]:
    """Return a compact, JSON-safe envelope summary for MCP responses."""

    try:
        payload = envelope.to_dict()
    except Exception:  # pragma: no cover - defensive
        return {
            "content_cid": getattr(envelope, "content_cid", ""),
            "family": getattr(getattr(envelope, "family", None), "value", ""),
            "profile": getattr(envelope, "profile", ""),
        }
    # Keep responses bounded: drop large nested formalization payloads by
    # default; callers can re-fetch by CID when needed.
    summary = {
        "artifact_cid": payload.get("artifact_cid", ""),
        "content_cid": payload.get("content_cid", ""),
        "family": payload.get("family", ""),
        "profile": payload.get("profile", ""),
        "producer_id": payload.get("producer_id", ""),
        "source_digest": payload.get("source_digest", ""),
        "source_id": payload.get("source_id", ""),
    }
    return summary


# ---------------------------------------------------------------------------
# normalize_intent
# ---------------------------------------------------------------------------


def _skill_record_from_source(source: Mapping[str, Any]) -> Any:
    from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
        SkillCenterSkillRecord,
    )

    skill_md = source.get("skill_md", source.get("body", source.get("text", "")))
    if not isinstance(skill_md, str) or not skill_md.strip():
        raise ValueError("skill source requires non-empty skill_md (or body/text)")

    def _s(key: str, default: str = "") -> str:
        value = source.get(key, default)
        if value is None:
            return default
        if not isinstance(value, str):
            raise TypeError(f"skill source field {key!r} must be a string")
        return value

    overall_score = source.get("overall_score")
    if overall_score is not None and not isinstance(overall_score, (int, float)):
        raise TypeError("overall_score must be a number or null")

    return SkillCenterSkillRecord(
        skill_id=_s("skill_id", "mcp-skill"),
        domain=_s("domain", "general"),
        profile=_s("profile", "security-lite"),
        source_type=_s("source_type", "mcp"),
        source_url=_s("source_url", ""),
        title=_s("title", _s("skill_id", "mcp-skill")),
        overall_score=None if overall_score is None else float(overall_score),
        skill_kind=_s("skill_kind", "mcp"),
        language=_s("language", "en"),
        source_id=_s("source_id", _s("skill_id", "mcp-skill")),
        primary_source_id=_s("primary_source_id", _s("source_id", "mcp-skill")),
        metadata_yaml=_s("metadata_yaml", 'license_spdx: "MIT"\nlicense_risk: "allow"\n'),
        skill_md=skill_md,
        library_md=_s("library_md", ""),
        dataset_id=_s("dataset_id", "mcp/local"),
        dataset_revision=_s("dataset_revision", "unpinned"),
        repository_file=_s("repository_file", "mcp/local.sqlite"),
        bundle_sha256=_s("bundle_sha256", "0" * 64),
    )


def _normalize_skill(source: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.intent_ir.normalize.skill import (
        SkillCenterIntentNormalizer,
        SkillNormalizationError,
        SkillNormalizationPolicyError,
    )

    record = _skill_record_from_source(source)
    normalizer = SkillCenterIntentNormalizer()
    try:
        result = normalizer.normalize_with_diagnostics(record)
    except SkillNormalizationPolicyError as exc:
        decision = getattr(exc, "decision", None)
        return _fail(
            "normalize_intent",
            status="reject",
            error=str(exc),
            error_type="policy_denied",
            source_kind="skill",
            policy=None if decision is None else decision.to_dict(),
        )
    except SkillNormalizationError as exc:
        return _fail(
            "normalize_intent",
            status="reject",
            error=str(exc),
            error_type="normalization_error",
            source_kind="skill",
        )

    return _ok(
        "normalize_intent",
        source_kind="skill",
        document=result.document.to_dict(),
        policy=result.policy_decision.to_dict(),
        diagnostics=[item.to_dict() for item in result.diagnostics],
        normalizer_version=result.normalizer_version,
    )


def _normalize_prompt(source: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.intent_ir.source_adapters.prompt import (
        PromptIntentAdapter,
        PromptPolicyError,
        PromptRecordError,
        PromptSourceError,
    )

    text = source.get("text", source.get("body", source.get("prompt", "")))
    if not isinstance(text, str) or not text.strip():
        raise ValueError("prompt source requires non-empty text")

    adapter = PromptIntentAdapter()
    try:
        record = adapter.make_record(
            text,
            title=_optional_str(source.get("title"), "title"),
            source_uri=_optional_str(source.get("source_uri"), "source_uri"),
            source_id=_optional_str(source.get("source_id"), "source_id"),
            source_revision=_optional_str(
                source.get("source_revision"), "source_revision"
            )
            or "unpinned",
            language=_optional_str(source.get("language"), "language") or "en",
            tags=tuple(source.get("tags") or ()),
            metadata=source.get("metadata"),
        )
        document, decision = adapter.adapt_with_policy(record)
    except PromptPolicyError as exc:
        return _fail(
            "normalize_intent",
            status="reject",
            error=str(exc),
            error_type="policy_denied",
            source_kind="prompt",
            policy=exc.decision.to_dict(),
        )
    except (PromptRecordError, PromptSourceError, TypeError, ValueError) as exc:
        return _fail(
            "normalize_intent",
            status="reject",
            error=str(exc),
            error_type="normalization_error",
            source_kind="prompt",
        )

    return _ok(
        "normalize_intent",
        source_kind="prompt",
        document=document.to_dict(),
        policy=decision.to_dict(),
        adapter=adapter.interface,
    )


def _normalize_mcp_tool(source: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.intent_ir.source_adapters.mcp_tool import (
        MCPToolIntentAdapter,
        MCPToolPolicyError,
        MCPToolRecordError,
        MCPToolSourceError,
    )

    name = source.get("name", source.get("tool_name", ""))
    if not isinstance(name, str) or not name.strip():
        raise ValueError("mcp_tool source requires non-empty name")

    adapter = MCPToolIntentAdapter()
    try:
        record = adapter.make_record(
            name,
            description=_optional_str(source.get("description"), "description"),
            input_schema=source.get("input_schema"),
            output_schema=source.get("output_schema"),
            server_name=_optional_str(source.get("server_name"), "server_name"),
            source_uri=_optional_str(source.get("source_uri"), "source_uri"),
            source_id=_optional_str(source.get("source_id"), "source_id"),
            source_revision=_optional_str(
                source.get("source_revision"), "source_revision"
            )
            or "unpinned",
            annotations=source.get("annotations"),
            tags=tuple(source.get("tags") or ()),
        )
        document, decision = adapter.adapt_with_policy(record)
    except MCPToolPolicyError as exc:
        return _fail(
            "normalize_intent",
            status="reject",
            error=str(exc),
            error_type="policy_denied",
            source_kind="mcp_tool",
            policy=exc.decision.to_dict(),
        )
    except (MCPToolRecordError, MCPToolSourceError, TypeError, ValueError) as exc:
        return _fail(
            "normalize_intent",
            status="reject",
            error=str(exc),
            error_type="normalization_error",
            source_kind="mcp_tool",
        )

    return _ok(
        "normalize_intent",
        source_kind="mcp_tool",
        document=document.to_dict(),
        policy=decision.to_dict(),
        adapter=adapter.interface,
    )


async def normalize_intent(
    source_kind: str | None = None,
    source: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Normalize skill / prompt / MCP tool source into IntentIR (non-executing).

    Parameters
    ----------
    source_kind:
        One of ``skill``, ``prompt``, ``mcp_tool``.
    source:
        Source payload mapping (never executed).

    Returns
    -------
    dict
        ``success``, ``status``, optional ``document`` / ``policy``, and
        ``executed=False`` always.
    """

    # Accept alternate kwargs used by some MCP dispatchers.
    if source is None and "payload" in kwargs:
        source = kwargs.get("payload")  # type: ignore[assignment]
    if source_kind is None and "kind" in kwargs:
        source_kind = kwargs.get("kind")  # type: ignore[assignment]

    if not isinstance(source_kind, str) or not source_kind.strip():
        return _fail(
            "normalize_intent",
            error="source_kind is required (skill|prompt|mcp_tool)",
            error_type="validation",
        )
    kind = source_kind.strip().lower().replace("-", "_")
    if kind == "mcp":
        kind = "mcp_tool"
    if kind not in SOURCE_KINDS:
        return _fail(
            "normalize_intent",
            error=f"unknown source_kind {source_kind!r}; fail closed",
            error_type="validation",
            source_kind=source_kind,
        )
    if source is None:
        return _fail(
            "normalize_intent",
            error="source payload is required; fail closed",
            error_type="validation",
            source_kind=kind,
        )
    try:
        source_map = _require_mapping(source, "source")
    except TypeError as exc:
        return _fail(
            "normalize_intent",
            error=str(exc),
            error_type="validation",
            source_kind=kind,
        )

    try:
        if kind == "skill":
            return _normalize_skill(source_map)
        if kind == "prompt":
            return _normalize_prompt(source_map)
        return _normalize_mcp_tool(source_map)
    except Exception as exc:  # fail closed — never allow on unexpected errors
        logger.exception("normalize_intent failed closed")
        return _fail(
            "normalize_intent",
            status="error",
            error=f"normalize_intent failed closed: {exc}",
            error_type=type(exc).__name__,
            source_kind=kind,
        )


# ---------------------------------------------------------------------------
# formalize_intent
# ---------------------------------------------------------------------------


async def formalize_intent(
    document: Mapping[str, Any] | None = None,
    *,
    put_in_store: bool = False,
    store_root: str | Path | None = None,
    profile: str = "legal-strict",
    envelopes: Sequence[Mapping[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Formalize an IntentIR document into a FormalizationArtifact.

    Does not execute source text, invoke provers, or dispatch tools.
    """

    if document is None and "intent_document" in kwargs:
        document = kwargs.get("intent_document")  # type: ignore[assignment]
    if document is None and "intent_ir" in kwargs:
        document = kwargs.get("intent_ir")  # type: ignore[assignment]

    if document is None:
        return _fail(
            "formalize_intent",
            error="document is required; fail closed",
            error_type="validation",
        )
    try:
        document_map = _require_mapping(document, "document")
    except TypeError as exc:
        return _fail(
            "formalize_intent",
            error=str(exc),
            error_type="validation",
        )

    try:
        from ipfs_datasets_py.logic.intent_ir.decoder import decode_intent_ir
        from ipfs_datasets_py.logic.intent_ir.formalize.compiler import (
            IntentFormalizationCompiler,
        )
        from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope

        intent_doc = decode_intent_ir(document_map)
        compiler = IntentFormalizationCompiler()
        artifact = compiler.compile(intent_doc)
        result: dict[str, Any] = _ok(
            "formalize_intent",
            artifact=artifact.to_dict(),
            sample_id=artifact.sample_id,
            declaration_id=artifact.declaration_id,
            declaration_digest=artifact.declaration_digest,
            obligation_count=len(artifact.proof_obligations),
        )

        if put_in_store:
            if store_root is None and envelopes is None:
                # Ephemeral in-memory store still produces a content CID.
                store = _open_store(None, None)
            else:
                store = _open_store(store_root, envelopes)
            if not isinstance(profile, str) or not profile.strip():
                return _fail(
                    "formalize_intent",
                    error="profile must be a non-empty string when putting",
                    error_type="validation",
                )
            envelope = store.put(
                ArtifactEnvelope.from_intent_artifact(
                    artifact, profile=profile.strip()
                )
            )
            result["content_cid"] = envelope.content_cid
            result["artifact_cid"] = envelope.artifact_cid
            result["profile"] = envelope.profile
            result["store_size"] = store.stats()["size"]
        return result
    except Exception as exc:
        logger.exception("formalize_intent failed closed")
        return _fail(
            "formalize_intent",
            status="error",
            error=f"formalize_intent failed closed: {exc}",
            error_type=type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# query_proof_corpus
# ---------------------------------------------------------------------------


async def query_proof_corpus(
    store_root: str | Path | None = None,
    envelopes: Sequence[Mapping[str, Any]] | None = None,
    *,
    content_cid: str | None = None,
    family: str | None = None,
    profile: str | None = None,
    source_digest: str | None = None,
    source_id: str | None = None,
    obligation_digest: str | None = None,
    include_artifact: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Query the proof corpus with fail-closed filter semantics."""

    # Alternate kw spellings.
    if content_cid is None and "cid" in kwargs:
        content_cid = kwargs.get("cid")  # type: ignore[assignment]

    filters = {
        "content_cid": content_cid,
        "family": family,
        "profile": profile,
        "source_digest": source_digest,
        "source_id": source_id,
        "obligation_digest": obligation_digest,
    }
    if not any(value is not None and value != "" for value in filters.values()):
        return _fail(
            "query_proof_corpus",
            error=(
                "query requires at least one filter "
                "(content_cid, family, profile, source_digest, "
                "source_id, or obligation_digest); fail closed"
            ),
            error_type="validation",
        )

    if store_root is None and envelopes is None:
        return _fail(
            "query_proof_corpus",
            error="store_root or envelopes is required; fail closed",
            error_type="validation",
        )

    try:
        from ipfs_datasets_py.logic.proof_corpus.query import (
            ProofCorpusQuery,
            ProofCorpusQueryError,
        )

        store = _open_store(store_root, envelopes)
        query = ProofCorpusQuery(store=store)
        query.rebuild_index()
        try:
            matched = query.query(
                content_cid=content_cid or None,
                family=family or None,
                profile=profile or None,
                source_digest=source_digest or None,
                source_id=source_id or None,
                obligation_digest=obligation_digest or None,
            )
        except ProofCorpusQueryError as exc:
            return _fail(
                "query_proof_corpus",
                status="reject",
                error=str(exc),
                error_type="query_error",
            )
        if include_artifact:
            envelope_payloads = [env.to_dict() for env in matched]
        else:
            envelope_payloads = [_envelope_summary(env) for env in matched]
        return _ok(
            "query_proof_corpus",
            envelopes=envelope_payloads,
            count=len(envelope_payloads),
            filters={k: v for k, v in filters.items() if v is not None and v != ""},
            stats=query.stats(),
        )
    except Exception as exc:
        logger.exception("query_proof_corpus failed closed")
        return _fail(
            "query_proof_corpus",
            status="error",
            error=f"query_proof_corpus failed closed: {exc}",
            error_type=type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# check_intent_admissibility
# ---------------------------------------------------------------------------


async def check_intent_admissibility(
    intent: str | Mapping[str, Any] | None = None,
    profile: str | None = None,
    *,
    store_root: str | Path | None = None,
    envelopes: Sequence[Mapping[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run IntentAdmissibilityGate@1; never executes source/tool bodies.

    Parameters
    ----------
    intent:
        Intent formal content CID, envelope map, or FormalizationArtifact map.
    profile:
        Admissibility profile id (default ``legal-strict``).
    store_root / envelopes:
        Proof corpus snapshot to evaluate against.
    """

    if intent is None and "intent_cid" in kwargs:
        intent = kwargs.get("intent_cid")  # type: ignore[assignment]
    if intent is None and "content_cid" in kwargs:
        intent = kwargs.get("content_cid")  # type: ignore[assignment]

    if intent is None or (isinstance(intent, str) and not intent.strip()):
        return _fail(
            "check_intent_admissibility",
            error="intent is required (content CID, envelope, or artifact); fail closed",
            error_type="validation",
        )

    if store_root is None and envelopes is None:
        return _fail(
            "check_intent_admissibility",
            error="store_root or envelopes is required; fail closed",
            error_type="validation",
        )

    try:
        from ipfs_datasets_py.logic.admissibility.gate import evaluate_admissibility
        from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus

        store = _open_store(store_root, envelopes)
        decision = evaluate_admissibility(
            store,
            intent.strip() if isinstance(intent, str) else intent,
            profile,
        )
        decision_map = decision.to_dict()
        # Map decision status onto tool status; never upgrade to allow unless
        # the gate itself returned allow.
        status = decision.status.value
        if status not in {
            AdmissibilityStatus.ALLOW.value,
            AdmissibilityStatus.REJECT.value,
            AdmissibilityStatus.ABSTAIN.value,
        }:
            return _fail(
                "check_intent_admissibility",
                status="reject",
                error=f"unknown decision status {status!r}; fail closed",
                error_type="invalid_decision",
                decision=decision_map,
            )
        return _base_response(
            "check_intent_admissibility",
            success=decision.is_allow,
            status=status,
            decision=decision_map,
            reason_codes=list(decision.reason_codes),
            profile_id=decision.profile_id,
            intent_cid=decision.intent_cid,
            constraint_cids=list(decision.constraint_cids),
        )
    except Exception as exc:
        logger.exception("check_intent_admissibility failed closed")
        return _fail(
            "check_intent_admissibility",
            status="error",
            error=f"check_intent_admissibility failed closed: {exc}",
            error_type=type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def list_tools() -> list[dict[str, Any]]:
    """Return documented tool schemas for MCP / CLI discovery."""

    return [dict(TOOL_SCHEMAS[name]) for name in TOOL_NAMES]


def get_tool_schema(name: str) -> dict[str, Any] | None:
    """Return one tool schema by name, or ``None`` if unknown."""

    if not isinstance(name, str):
        return None
    return dict(TOOL_SCHEMAS[name]) if name in TOOL_SCHEMAS else None


async def logic_admissibility_capabilities() -> dict[str, Any]:
    """Report tool surface without importing provers or executing sources."""

    return _ok(
        "logic_admissibility_capabilities",
        tools=list(TOOL_NAMES),
        source_kinds=sorted(SOURCE_KINDS),
        schemas=list_tools(),
    )


__all__ = [
    "MCP_INTENT_ADMISSIBILITY_INTERFACE",
    "MCP_INTENT_ADMISSIBILITY_SCHEMA_VERSION",
    "SOURCE_KINDS",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "check_intent_admissibility",
    "formalize_intent",
    "get_tool_schema",
    "list_tools",
    "logic_admissibility_capabilities",
    "normalize_intent",
    "query_proof_corpus",
]
