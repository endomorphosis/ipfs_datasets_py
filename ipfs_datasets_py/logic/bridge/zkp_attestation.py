"""ZKP proof-attestation implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Optional, Sequence

from .fol_tdfol import FolTdfolBridgeAdapter
from .types import (
    BridgeEvaluationReport,
    GraphProjectionResult,
    LegalIRDocument,
    LogicIRView,
    ProofGateResult,
    RoundTripMetrics,
)


_ZKP_ATTESTATION_RECORD_CACHE_MAX_ITEMS = 4096
_ZKP_ATTESTATION_RECORD_CACHE: dict[str, list[dict[str, Any]]] = {}
_ZKP_ATTESTATION_RECORD_CACHE_LOCK = Lock()
_ZKP_ATTESTATION_RECORD_DISK_CACHE_VERSION = "zkp-attestation-record-cache-v1"
_ZKP_ATTESTATION_RECORD_DISK_CACHE_KIND = "zkp_attestation_records"
_ZKP_ATTESTATION_RECORD_DISK_CACHE_DIR_ENV = "IPFS_DATASETS_LEGAL_IR_METRIC_CACHE_DIR"
_ZKP_ATTESTATION_RECORD_DISK_CACHE_ENABLED_ENV = "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"
_ZKP_ATTESTATION_RECORD_CODE_FINGERPRINT_LOCK = Lock()
_ZKP_ATTESTATION_RECORD_CODE_FINGERPRINT_VALUE = ""
_FALSE_ENV_VALUES = {"0", "false", "no", "off", "none", "disabled"}
_COMPILER_GUIDANCE_CONTAINER_KEYS = {
    "compiler_guidance_contract",
    "compiler_guidance",
    "compiler_guidance_bundle",
    "compiler_guidance_attribution",
    "guidance_contract",
    "guidance",
    "semantic_bundle",
    "semantic_bundle_key",
    "bundle",
}


@dataclass
class ZkpAttestationBridgeAdapter:
    """Bridge formal legal formulas into ZKP attestation records.

    The current ``logic.zkp`` package defaults to a simulated backend.  This
    adapter keeps that status visible in metadata while still giving the
    optimizer a concrete ZKP view, proof gate, graph projection, and loss names.
    """

    tdfol_adapter: Optional[FolTdfolBridgeAdapter] = None
    prover_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: {
            "backend": "simulated",
            "enable_caching": True,
        }
    )
    verifier_kwargs: Mapping[str, Any] = field(default_factory=lambda: {"backend": "simulated"})

    name: str = "zkp_attestation"
    target_component: str = "zkp.circuits"

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
    ) -> tuple[LegalIRDocument, Mapping[str, Any]]:
        adapter = self.tdfol_adapter or FolTdfolBridgeAdapter()
        _, context = adapter.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
            compiler_guidance=compiler_guidance,
        )
        formula_records = list(context.get("formula_records") or [])
        if not formula_records:
            normalized_text = " ".join(str(text or "").split())
            if normalized_text:
                fallback_source_id = f"{document_id or _document_id('zkp', text)}:fallback:0"
                formula_records = [
                    {
                        "formula": normalized_text,
                        "predicates": (),
                        "source_id": fallback_source_id,
                    }
                ]
        formula_records = _formula_records_with_compiler_guidance(
            formula_records,
            compiler_guidance,
        )
        compiler_guidance_ref = _compiler_guidance_ref(
            _compiler_guidance_contract_from_mapping(compiler_guidance)
        )
        resolved_document_id = document_id or _document_id("zkp", text)
        attestations = _zkp_attestation_records(
            formula_records,
            prover_kwargs=self.prover_kwargs,
            verifier_kwargs=self.verifier_kwargs,
        )
        triples = tuple(
            _zkp_frame_logic_triples(
                resolved_document_id,
                attestations=attestations,
            )
        )
        graph_data = _graph_data_from_triples(
            triples,
            graph_id=f"{resolved_document_id}:zkp-flogic",
            metadata={
                "source": "zkp_attestation_bridge_ir",
                "zkp_attestation_count": len(attestations),
            },
        )
        views = {
            "zkp_attestations": LogicIRView(
                name="zkp_attestations",
                format="zkp-attestation-records",
                source_component="zkp.circuits",
                payload={
                    "records": [
                        _public_attestation_record(record)
                        for record in attestations
                    ]
                },
                metadata={
                    "attestation_count": len(attestations),
                    "verified_count": sum(1 for record in attestations if record["verified"]),
                },
            ),
            "zkp_public_inputs": LogicIRView(
                name="zkp_public_inputs",
                format="zkp-public-input-records",
                source_component="zkp.backends",
                payload={
                    "records": [
                        {
                            "public_inputs": _proof_public_inputs(record),
                            "source_id": record["source_id"],
                        }
                        for record in attestations
                    ]
                },
                metadata={"record_count": len(attestations)},
            ),
            "frame_logic": LogicIRView(
                name="frame_logic",
                format="flogic-triples-v1",
                source_component="zkp.circuits",
                payload={"triples": [dict(triple) for triple in triples]},
                metadata={"triple_count": len(triples)},
            ),
        }
        if graph_data is not None:
            views["neo4j_graph_data"] = LogicIRView(
                name="neo4j_graph_data",
                format="neo4j-compatible-graph-data",
                source_component="knowledge_graphs.neo4j_compat",
                payload=graph_data.to_dict(),
                metadata={
                    "node_count": graph_data.node_count,
                    "relationship_count": graph_data.relationship_count,
                },
            )

        return (
            LegalIRDocument(
                document_id=resolved_document_id,
                source_text=text,
                normalized_text=" ".join(str(text or "").split()),
                source=source,
                citation=citation,
                views=views,
                frame_logic_triples=triples,
                metadata={
                    "formula_count": len(formula_records),
                    "compiler_guidance_applied": bool(compiler_guidance_ref),
                    "compiler_guidance_ref": compiler_guidance_ref,
                    "proof_system": "simulated_zkp",
                    "zkp_attestation_count": len(attestations),
                },
            ),
            {
                "attestations": attestations,
                "compiler_guidance_ref": compiler_guidance_ref,
                "formula_records": formula_records,
                "graph_data": graph_data,
            },
        )

    def evaluate(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
        **_: Any,
    ) -> BridgeEvaluationReport:
        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
            compiler_guidance=compiler_guidance,
        )
        attestations = list(context["attestations"])
        public_attestation_records = list(
            ir_document.views["zkp_attestations"].payload.get("records") or []
        )
        from ipfs_datasets_py.logic.zkp import zkp_attestation_legal_ir_view_loss

        legal_ir_view_loss = zkp_attestation_legal_ir_view_loss(
            public_attestation_records
        )
        proof_gate = _proof_gate_from_attestations(attestations)
        graph_result = GraphProjectionResult.from_graph_data(context["graph_data"])
        attempted = max(1, len(attestations))
        verified_count = sum(1 for record in attestations if record["verified"])
        missing_loss = 0.0 if attestations else 1.0
        verification_failure_ratio = (
            max(0.0, (attempted - verified_count) / attempted)
            if attestations
            else 1.0
        )
        round_trip = RoundTripMetrics(
            cosine_similarity=max(0.0, 1.0 - missing_loss),
            cosine_loss=missing_loss,
            cross_entropy_loss=legal_ir_view_loss,
            symbolic_validity_penalty=verification_failure_ratio,
            extra_losses={
                "legal_ir_view_cross_entropy_loss": legal_ir_view_loss,
                "zkp_attestation_missing_loss": missing_loss,
                "zkp_verification_failure_ratio": verification_failure_ratio,
            },
        )
        status = "ok" if attestations and proof_gate.compiles else "partial"
        if graph_result.graph_failure_penalty:
            status = "partial"
        return BridgeEvaluationReport(
            adapter_name=self.name,
            target_component=self.target_component,
            ir_document=ir_document,
            round_trip=round_trip,
            proof_gate=proof_gate,
            graph_projection=graph_result,
            decoded_text=" ".join(str(record.get("theorem") or "") for record in attestations),
            status=status,
            metadata={
                "adapter": "zkp_attestation_bridge_v1",
                "compiler_guidance_applied": bool(
                    context.get("compiler_guidance_ref")
                ),
                "compiler_guidance_ref": str(
                    context.get("compiler_guidance_ref") or ""
                ),
                "proof_system": "simulated_zkp",
                "simulated_only": True,
            },
        )


def _zkp_attestation_records(
    formula_records: Sequence[Mapping[str, Any]],
    *,
    prover_kwargs: Mapping[str, Any],
    verifier_kwargs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not formula_records:
        return []
    cache_key = _zkp_attestation_records_cache_key(
        formula_records,
        prover_kwargs=prover_kwargs,
        verifier_kwargs=verifier_kwargs,
    )
    with _ZKP_ATTESTATION_RECORD_CACHE_LOCK:
        cached = _ZKP_ATTESTATION_RECORD_CACHE.get(cache_key)
    if cached is not None:
        return _clone_attestation_records(cached)
    disk_cached = _read_zkp_attestation_records_disk_cache(cache_key)
    if disk_cached is not None:
        _remember_zkp_attestation_records(cache_key, disk_cached)
        return _clone_attestation_records(disk_cached)

    from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        prover = ZKPProver(**dict(prover_kwargs))
        verifier = ZKPVerifier(**dict(verifier_kwargs))

    records: list[dict[str, Any]] = []
    for index, formula_record in enumerate(formula_records):
        theorem = str(formula_record.get("formula") or "").strip()
        if not theorem:
            continue
        source_id = str(formula_record.get("source_id") or f"zkp:formula:{index}")
        axioms = _private_axioms_for_formula(formula_record, theorem=theorem)
        guidance_contract = _compiler_guidance_contract(formula_record)
        guidance_ref = _compiler_guidance_ref(guidance_contract)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                proof = prover.generate_proof(
                    theorem,
                    axioms,
                    metadata={
                        "circuit_ref": "legal_ir_zkp_attestation@v1",
                        "circuit_version": 1,
                        "ruleset_id": "LegalIR_TDFOL_v1",
                        "compiler_guidance_contract": guidance_contract,
                        "compiler_guidance_ref": guidance_ref,
                    },
                )
                if guidance_ref:
                    proof.public_inputs["compiler_guidance_ref"] = guidance_ref
                    proof.public_inputs["compiler_guidance_version"] = 1
                    from ipfs_datasets_py.logic.zkp import refresh_proof_attestation

                    refresh_proof_attestation(proof)
                verified = bool(verifier.verify_proof(proof))
            proof_dict = proof.to_dict()
            proof_hash = hashlib.sha256(proof.proof_data).hexdigest()
            public_inputs = dict(proof.public_inputs)
            error = ""
        except Exception as exc:
            proof_dict = {}
            proof_hash = ""
            public_inputs = {}
            verified = False
            error = f"{type(exc).__name__}: {str(exc)[:120]}"
        records.append(
            {
                "axiom_count": len(axioms),
                "error": error,
                "proof": proof_dict,
                "proof_hash": proof_hash,
                "public_inputs": public_inputs,
                "source_id": source_id,
                "theorem": theorem,
                "verified": verified,
                "compiler_guidance_ref": guidance_ref,
            }
        )
    _remember_zkp_attestation_records(cache_key, records)
    _write_zkp_attestation_records_disk_cache(cache_key, records)
    return records


def _zkp_attestation_records_cache_key(
    formula_records: Sequence[Mapping[str, Any]],
    *,
    prover_kwargs: Mapping[str, Any],
    verifier_kwargs: Mapping[str, Any],
) -> str:
    payload = {
        "formula_records": [
            _zkp_attestation_formula_cache_payload(record, index=index)
            for index, record in enumerate(formula_records)
        ],
        "prover_kwargs": dict(sorted((str(k), v) for k, v in prover_kwargs.items())),
        "verifier_kwargs": dict(sorted((str(k), v) for k, v in verifier_kwargs.items())),
        "version": 1,
    }
    return hashlib.sha256(
        json.dumps(payload, default=str, ensure_ascii=True, sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _zkp_attestation_formula_cache_payload(
    record: Mapping[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    theorem = str(record.get("formula") or "").strip()
    source_id = str(record.get("source_id") or f"zkp:formula:{index}")
    guidance_contract = _compiler_guidance_contract(record)
    return {
        "axioms": _private_axioms_for_formula(record, theorem=theorem),
        "compiler_guidance_contract": guidance_contract,
        "compiler_guidance_ref": _compiler_guidance_ref(guidance_contract),
        "source_id": source_id,
        "theorem": theorem,
    }


def _clone_attestation_records(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return json.loads(
        json.dumps(
            list(records),
            default=str,
            ensure_ascii=True,
            sort_keys=True,
        )
    )


def _remember_zkp_attestation_records(
    cache_key: str,
    records: Sequence[Mapping[str, Any]],
) -> None:
    with _ZKP_ATTESTATION_RECORD_CACHE_LOCK:
        if (
            len(_ZKP_ATTESTATION_RECORD_CACHE)
            >= _ZKP_ATTESTATION_RECORD_CACHE_MAX_ITEMS
        ):
            _ZKP_ATTESTATION_RECORD_CACHE.pop(
                next(iter(_ZKP_ATTESTATION_RECORD_CACHE)),
                None,
            )
        _ZKP_ATTESTATION_RECORD_CACHE[cache_key] = _clone_attestation_records(records)


def _zkp_attestation_records_disk_cache_enabled() -> bool:
    raw = str(
        os.environ.get(_ZKP_ATTESTATION_RECORD_DISK_CACHE_ENABLED_ENV) or ""
    ).strip().lower()
    return raw not in _FALSE_ENV_VALUES


def _default_zkp_attestation_records_disk_cache_dir() -> Path:
    try:
        repo_root = Path(__file__).resolve().parents[3]
    except (IndexError, OSError, RuntimeError):
        repo_root = Path.cwd()
    return repo_root / "workspace" / "test-logs" / "legal-ir-metric-cache"


def _zkp_attestation_records_disk_cache_dir() -> Optional[Path]:
    if not _zkp_attestation_records_disk_cache_enabled():
        return None
    raw = str(os.environ.get(_ZKP_ATTESTATION_RECORD_DISK_CACHE_DIR_ENV) or "").strip()
    if raw.lower() in _FALSE_ENV_VALUES:
        return None
    return Path(raw).expanduser() if raw else _default_zkp_attestation_records_disk_cache_dir()


def _zkp_attestation_records_code_fingerprint() -> str:
    global _ZKP_ATTESTATION_RECORD_CODE_FINGERPRINT_VALUE
    with _ZKP_ATTESTATION_RECORD_CODE_FINGERPRINT_LOCK:
        if _ZKP_ATTESTATION_RECORD_CODE_FINGERPRINT_VALUE:
            return _ZKP_ATTESTATION_RECORD_CODE_FINGERPRINT_VALUE
        try:
            package_root = Path(__file__).resolve().parents[2]
        except (IndexError, OSError, RuntimeError):
            package_root = Path.cwd()
        candidates = [
            Path(__file__),
            package_root / "logic" / "zkp",
            package_root / "logic" / "bridge" / "fol_tdfol.py",
        ]
        tokens: list[str] = []
        for candidate in candidates:
            paths = (
                sorted(candidate.rglob("*.py"))
                if candidate.is_dir()
                else [candidate]
            )
            for path in paths:
                try:
                    stat = path.stat()
                except (OSError, RuntimeError):
                    continue
                try:
                    relative = path.relative_to(package_root)
                except ValueError:
                    relative = path
                tokens.append(f"{relative}:{stat.st_mtime_ns}:{stat.st_size}")
        _ZKP_ATTESTATION_RECORD_CODE_FINGERPRINT_VALUE = (
            hashlib.sha256("\n".join(tokens).encode("utf-8")).hexdigest()
            if tokens
            else "unknown"
        )
        return _ZKP_ATTESTATION_RECORD_CODE_FINGERPRINT_VALUE


def _zkp_attestation_records_disk_cache_key(cache_key: str) -> str:
    payload = {
        "code_fingerprint": _zkp_attestation_records_code_fingerprint(),
        "kind": _ZKP_ATTESTATION_RECORD_DISK_CACHE_KIND,
        "records_cache_key": str(cache_key),
        "version": _ZKP_ATTESTATION_RECORD_DISK_CACHE_VERSION,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _zkp_attestation_records_disk_cache_path(cache_key: str) -> Optional[Path]:
    root = _zkp_attestation_records_disk_cache_dir()
    if root is None:
        return None
    disk_key = _zkp_attestation_records_disk_cache_key(cache_key)
    return (
        root
        / _ZKP_ATTESTATION_RECORD_DISK_CACHE_KIND
        / disk_key[:2]
        / f"{disk_key}.json"
    )


def _read_zkp_attestation_records_disk_cache(
    cache_key: str,
) -> Optional[list[dict[str, Any]]]:
    path = _zkp_attestation_records_disk_cache_path(cache_key)
    if path is None or not path.is_file():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(wrapper, Mapping):
        return None
    if wrapper.get("version") != _ZKP_ATTESTATION_RECORD_DISK_CACHE_VERSION:
        return None
    if wrapper.get("kind") != _ZKP_ATTESTATION_RECORD_DISK_CACHE_KIND:
        return None
    if wrapper.get("records_cache_key") != cache_key:
        return None
    if wrapper.get("code_fingerprint") != _zkp_attestation_records_code_fingerprint():
        return None
    records = wrapper.get("records")
    if not isinstance(records, list):
        return None
    return _clone_attestation_records(
        [record for record in records if isinstance(record, Mapping)]
    )


def _write_zkp_attestation_records_disk_cache(
    cache_key: str,
    records: Sequence[Mapping[str, Any]],
) -> None:
    path = _zkp_attestation_records_disk_cache_path(cache_key)
    if path is None:
        return
    wrapper = {
        "code_fingerprint": _zkp_attestation_records_code_fingerprint(),
        "created_at": int(time.time()),
        "kind": _ZKP_ATTESTATION_RECORD_DISK_CACHE_KIND,
        "records": _clone_attestation_records(records),
        "records_cache_key": cache_key,
        "version": _ZKP_ATTESTATION_RECORD_DISK_CACHE_VERSION,
    }
    tmp_path: Optional[str] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=str(path.parent),
            encoding="utf-8",
        ) as handle:
            tmp_path = handle.name
            json.dump(wrapper, handle, ensure_ascii=True, sort_keys=True)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


def _private_axioms_for_formula(record: Mapping[str, Any], *, theorem: str) -> list[str]:
    axioms = [theorem]
    for predicate in record.get("predicates") or []:
        predicate_text = str(predicate or "").strip()
        if predicate_text:
            axioms.append(f"uses_predicate({predicate_text})")
    source_id = str(record.get("source_id") or "").strip()
    if source_id:
        axioms.append(f"source_id({source_id})")
    return sorted(set(axioms))


def _proof_gate_from_attestations(
    records: Sequence[Mapping[str, Any]],
) -> ProofGateResult:
    attempted = len(records)
    valid = sum(1 for record in records if record.get("verified"))
    failed = attempted - valid
    return ProofGateResult(
        attempted_count=attempted,
        valid_count=valid,
        failed_count=failed,
        verified_by=("zkp:simulated",) if valid else (),
        details=tuple(
            {
                "error": record.get("error") or "",
                "proof_hash": record.get("proof_hash") or "",
                "source_id": record.get("source_id") or "",
                "verified": bool(record.get("verified")),
            }
            for record in records
        ),
    )


def _zkp_frame_logic_triples(
    document_id: str,
    *,
    attestations: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    triples = [
        {"subject": document_id, "predicate": "type", "object": "legal_zkp_document"}
    ]
    for record in attestations:
        source_id = str(record.get("source_id") or "")
        if not source_id:
            continue
        public_inputs = dict(record.get("public_inputs") or {})
        proof_node = f"{source_id}:zkp_proof"
        triples.extend(
            [
                {"subject": document_id, "predicate": "contains_zkp_attestation", "object": proof_node},
                {"subject": proof_node, "predicate": "type", "object": "zkp_attestation"},
                {"subject": proof_node, "predicate": "attests_formula", "object": source_id},
                {"subject": proof_node, "predicate": "proof_hash", "object": str(record.get("proof_hash") or "")},
                {"subject": proof_node, "predicate": "verified", "object": str(bool(record.get("verified"))).lower()},
            ]
        )
        for key in ("theorem_hash", "axioms_commitment", "ruleset_id"):
            value = public_inputs.get(key)
            if value:
                triples.append(
                    {"subject": proof_node, "predicate": key, "object": str(value)}
                )
    return [triple for triple in triples if triple["object"]]


def _graph_data_from_triples(
    triples: Sequence[Mapping[str, str]],
    *,
    graph_id: str,
    metadata: Mapping[str, Any],
) -> Any:
    if not triples:
        return None
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    return flogic_triples_to_graph_data(triples, graph_id=graph_id, metadata=metadata)


def _public_attestation_record(record: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.zkp.circuits import (
        proof_attestation_view_from_proof_dict,
    )

    proof = dict(record.get("proof") or {})
    public_inputs = _proof_public_inputs(record)
    proof_metadata = proof.get("metadata")
    if not isinstance(proof_metadata, Mapping):
        proof_metadata = {}
    attestation_view = proof_attestation_view_from_proof_dict(proof)
    proof_hash = _proof_hash(record)
    compiler_guidance_ref = str(
        record.get("compiler_guidance_ref")
        or public_inputs.get("compiler_guidance_ref")
        or attestation_view.get("compiler_guidance_ref")
        or ""
    )
    return {
        "attestation_ref": str(
            public_inputs.get("attestation_ref")
            or attestation_view.get("attestation_ref")
            or ""
        ),
        "attestation_view": dict(attestation_view),
        "attestation_view_version": int(
            public_inputs.get("attestation_view_version")
            or attestation_view.get("attestation_view_version")
            or 0
        ),
        "axiom_count": int(record.get("axiom_count") or 0),
        "axioms_commitment": str(
            public_inputs.get("axioms_commitment")
            or attestation_view.get("axioms_commitment")
            or ""
        ),
        "circuit_ref": str(
            public_inputs.get("circuit_ref")
            or attestation_view.get("circuit_ref")
            or ""
        ),
        "error": record.get("error") or "",
        "proof_hash": proof_hash,
        "proof_system": str(
            attestation_view.get("proof_system")
            or proof_metadata.get("proof_system")
            or ""
        ),
        "proof_size_bytes": int(proof.get("size_bytes") or 0),
        "compiler_guidance_ref": compiler_guidance_ref,
        "public_inputs": public_inputs,
        "ruleset_id": str(
            public_inputs.get("ruleset_id")
            or attestation_view.get("ruleset_id")
            or ""
        ),
        "source_id": record.get("source_id") or "",
        "theorem": record.get("theorem") or "",
        "theorem_hash": str(
            public_inputs.get("theorem_hash")
            or attestation_view.get("theorem_hash")
            or ""
        ),
        "verified": bool(record.get("verified")),
    }


def _proof_public_inputs(record: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.zkp.circuits import proof_public_inputs_from_proof_dict

    proof = record.get("proof")
    proof_public_inputs = proof_public_inputs_from_proof_dict(proof)
    if proof_public_inputs:
        return proof_public_inputs
    return dict(record.get("public_inputs") or {})


def _proof_hash(record: Mapping[str, Any]) -> str:
    explicit = str(record.get("proof_hash") or "").strip()
    if explicit:
        return explicit

    from ipfs_datasets_py.logic.zkp.circuits import proof_digest_from_proof_dict

    return proof_digest_from_proof_dict(record.get("proof"))


def _document_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _formula_records_with_compiler_guidance(
    formula_records: Sequence[Mapping[str, Any]],
    compiler_guidance: Optional[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    guidance_contract = _compiler_guidance_contract_from_mapping(compiler_guidance)
    if not guidance_contract:
        return [dict(record) for record in formula_records]

    records: list[dict[str, Any]] = []
    for record in formula_records:
        record_dict = dict(record)
        existing_contract = _compiler_guidance_contract(record_dict)
        merged_contract = {**guidance_contract, **existing_contract}
        record_dict["compiler_guidance_contract"] = merged_contract
        records.append(record_dict)
    return records


def _compiler_guidance_contract_from_mapping(
    value: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        from ipfs_datasets_py.logic.zkp.circuits import (
            compiler_guidance_contract_from_metadata,
        )

        contract = compiler_guidance_contract_from_metadata(value)
    except Exception:
        contract = {}
    if isinstance(contract, Mapping):
        return _to_json_compatible(contract)
    return {}


def _merge_compiler_guidance_contract(
    selected: dict[str, Any],
    value: Any,
) -> None:
    mapping = value if isinstance(value, Mapping) else {}
    selected.update(_compiler_guidance_contract_from_mapping(mapping))
    for key in sorted(mapping.keys(), key=str):
        name = str(key)
        if name in _COMPILER_GUIDANCE_CONTAINER_KEYS:
            continue
        if name.startswith("compiler_guidance_"):
            selected[name] = _to_json_compatible(mapping.get(key))


def _compiler_guidance_contract(formula_record: Mapping[str, Any]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    _merge_compiler_guidance_contract(selected, formula_record.get("source_norm"))
    _merge_compiler_guidance_contract(selected, formula_record)
    return selected


def _compiler_guidance_ref(contract: Mapping[str, Any]) -> str:
    if not contract:
        return ""
    payload = json.dumps(dict(contract), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _to_json_compatible(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_json_compatible(item) for item in value]
    return str(value)


__all__ = ["ZkpAttestationBridgeAdapter"]
