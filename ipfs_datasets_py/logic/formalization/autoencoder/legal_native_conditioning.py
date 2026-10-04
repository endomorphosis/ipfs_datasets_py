"""Source-bound conditioning from retained native encoders and decoder stages.

384D inputs must match saved native GTE production receipts exactly. This module
never generates replacement embeddings. Raw embeddings, parser/core projections
and trained residual projections have distinct receipts; dimensions alone never
identify an input space. Historical 8D outputs are explicitly linguistic feature
hashes, not pretrained semantic embeddings or learned reconstruction outputs.

Receipts establish artifact and source consistency, not cryptographic runtime
attestation or legal semantic correctness. No target fields enter these APIs.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path

SCHEMA = "legal-native-conditioning/v1"
RECEIPT_SCHEMA = "legal-native-conditioning-stage/v1"
STAGES = ("raw384", "core384", "trained384")
HISTORICAL_STAGE = "historical_linguistic_features8"
MAX_ROWS = 4096
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_FALSE = {"target_access": False, "sample_memory_used": False,
          "target_aware_reconstruction_used": False, "source_semantics_verified": False,
          "runtime_computation_proven": False, "qualified": False, "admitted": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _closed(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), "exact " + label + " fields required")


def _vector(value, dimension):
    _require(type(value) is list and len(value) == dimension and all(
        type(v) is float and math.isfinite(v) for v in value),
        "finite float vector with exact dimension required")


def _sources(rows, *, embeddings=False):
    _require(type(rows) in (list, tuple) and 0 < len(rows) <= MAX_ROWS,
             "one to 4096 source rows required")
    seen, total = set(), 0
    for row in rows:
        _closed(row, {"id", "source_text", "embedding"} if embeddings else
                {"id", "source_text"}, "source row")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in seen,
                 "bounded unique source identity required")
        text = row["source_text"]
        _require(type(text) is str and text.strip() and len(text) <= 16384,
                 "bounded nonempty source text required")
        total += len(text.encode("utf-8"))
        _require(total <= 16 * 1024**2, "source batch exceeds byte bound")
        if embeddings:
            _vector(row["embedding"], 384)
        seen.add(row["id"])
    return json.loads(_wire(list(rows)))


def producer_pins():
    _require(_sha(Path(__file__).read_bytes()) == _SELF_SHA, "conditioning producer changed after import")
    names = (
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_joint_formula",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula",
        "ipfs_datasets_py.logic.formalization.autoencoder.legal_384_package",
    )
    paths = [Path(__file__).resolve()] + [Path(importlib.import_module(n).__file__).resolve() for n in names]
    return {str(p): _sha(p.read_bytes()) for p in paths}


def _native_index(references, resolver):
    from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
    from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
    _require(type(references) in (list, tuple) and 0 < len(references) <= 128,
             "one to 128 pinned native embedding receipt references required")
    expected_assets = [{"name": name, "bytes": size, "sha256": sha}
                       for name, (size, sha) in sorted(runtime._PINNED_ASSETS.items())]
    index, seen, total = {}, set(), 0
    for reference in references:
        _closed(reference, {"path", "sha256", "bytes"}, "native receipt reference")
        _require(reference["sha256"] not in seen, "duplicate native receipt reference")
        receipt = codec.load_embedding_production_receipt(reference["path"],
            expected_sha256=reference["sha256"], expected_size_bytes=reference["bytes"])
        total += len(receipt.to_bytes())
        _require(total <= 256 * 1024**2, "aggregate native receipt bytes exceed bound")
        payload = receipt.to_dict()
        _require(receipt.native_execution_profile, "injected fixtures are not native encoder outputs")
        _require(payload["model_assets"] == expected_assets, "native encoder assets differ from pinned GTE-small")
        _require(payload["producer"]["code_sha256"] == _sha(Path(runtime.__file__).read_bytes()),
                 "native encoder producer implementation differs")
        # Whole source artifacts can be verified directly from retained exact
        # input text. Partial source spans require the caller's artifact resolver.
        whole = {}
        for item in receipt.inputs:
            raw = item.text.encode("utf-8")
            if (item.source.byte_start == 0 and item.source.byte_end == len(raw)
                    and item.source.artifact.bytes == len(raw)
                    and item.source.artifact.sha256 == _sha(raw)):
                whole[item.source.artifact.sha256] = raw

        if callable(resolver):
            receipt.validate_sources(resolver)
        else:
            _require(all(result["status"] == "missing_input" or
                (item.source.artifact.sha256 in whole and
                 whole[item.source.artifact.sha256][item.source.byte_start:item.source.byte_end]
                 == item.text.encode("utf-8"))
                for item, result in zip(receipt.inputs, payload["results"])),
                "partial source receipts require an artifact resolver")
        for item, result in zip(receipt.inputs, payload["results"]):
            if result["status"] != "embedded":
                continue
            vector = list(codec._decode_vector(result["vector"]))
            source_sha = _sha(item.text.encode("utf-8"))
            evidence = {"receipt": {"path": str(Path(reference["path"]).resolve()),
                        "sha256": receipt.sha256, "bytes": len(receipt.to_bytes())},
                "input_id": item.input_id, "source": item.to_dict()["source"],
                "model": payload["model"], "execution": payload["execution"],
                "model_assets_sha256": digest(payload["model_assets"]),
                "producer": payload["producer"], "tokens_sha256": digest(result["tokens"]),
                "token_count": len(result["tokens"]["input_ids"]),
                "native_vector_bits_sha256": _sha(bytes.fromhex(result["vector"]["bits"])),
                "source_bytes_verified": True, "native_execution_record_present": True,
                "runtime_cryptographically_attested": False}
            index.setdefault((source_sha, item.text), []).append((vector, evidence))
        seen.add(reference["sha256"])
    return index


def embedding_rows(sources, *, embedding_receipts, source_resolver=None):
    """Reuse native vectors by exact source bytes, without running an encoder.

    Sources have exactly id/source_text; receipt references have exactly
    path/sha256/bytes. When identical texts occur in multiple receipts, the first
    supplied receipt wins deterministically; vectorize binds that exact vector.
    """
    sources = _sources(sources)
    index = _native_index(embedding_receipts, source_resolver)
    result = []
    for source in sources:
        matches = index.get((_sha(source["source_text"].encode("utf-8")), source["source_text"]), [])
        _require(bool(matches), "source has no successful native GTE receipt")
        result.append({**source, "embedding": matches[0][0]})
    return result


def _stage(stage, vector, *, identity, source_sha, upstream, evidence):
    dimension = 8 if stage == HISTORICAL_STAGE else 384
    _vector(vector, dimension)
    receipt = {"schema": RECEIPT_SCHEMA, "id": identity, "source_sha256": source_sha,
        "stage": stage, "dimension": dimension, "vector_sha256": digest(vector),
        "upstream_vector_sha256": upstream, "evidence": evidence, **_FALSE}
    receipt["receipt_sha256"] = digest(receipt)
    return {"vector": vector, "receipt": receipt}


def vectorize(rows, *, package_path, package_sha256, embedding_receipts, source_resolver=None):
    """Return authentic raw384/core384/trained384 stages for exact input rows.

    No encoder inference occurs here. The saved package is loaded through its
    strict runtime, including its retained fixture replay. Core projection is
    evaluated before target-aware safety corrections with sample memory removed;
    its result is fed to the saved learned residual projection without padding,
    dimension substitution, renormalization or a newly initialized projection.
    """
    from . import legal_384_package as package
    from ....optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ....optimizers.logic_theorem_optimizer.modal_latent_formula import LatentFormulaDecoder
    from ....optimizers.logic_theorem_optimizer.domain_384_autoencoder import _cpu
    checked, pins = _sources(rows, embeddings=True), producer_pins()
    index = _native_index(embedding_receipts, source_resolver)
    matches = []
    for row in checked:
        candidates = index.get((_sha(row["source_text"].encode("utf-8")), row["source_text"]), [])
        exact = [evidence for vector, evidence in candidates if _wire(vector) == _wire(row["embedding"])]
        _require(bool(exact), "input vector differs from exact source-bound native encoder output")
        matches.append(exact[0])
    with _cpu():
        runtime = package.load_package(package_path, expected_sha256=package_sha256)
        payload = runtime._payload
        _require(payload["dimension"] == 384 and payload["formula_checkpoint"] is not None,
                 "384D package with a saved formula projection required")
        _require(payload["formula_checkpoint"]["progress"]["optimizer_steps"] > 0,
                 "trained residual projection required")
        head = LatentFormulaDecoder(payload["formula_checkpoint"], expected_binding=payload["core_binding"])
        before = digest(runtime.model.state.to_dict())
        package_ref = {"path": str(Path(package_path).resolve()), "sha256": package_sha256,
            "core_binding": payload["core_binding"], "core_state_sha256": before,
            "formula_checkpoint_sha256": digest(payload["formula_checkpoint"]),
            "projection_optimizer_steps": payload["formula_checkpoint"]["progress"]["optimizer_steps"]}
        result = []
        for start in range(0, len(checked), 128):
            chunk = checked[start:start + 128]
            samples = package._rows(chunk, payload["embedding_contract"])
            raw = [joint.raw_projection(runtime.model, sample) for sample in samples]
            trained = head.project(raw)
            for j, (row, sample, core, learned) in enumerate(zip(chunk, samples, raw, trained)):
                source_sha = _sha(row["source_text"].encode("utf-8"))
                native = matches[start + j]
                parser = {"source_sha256": source_sha, "sample_sha256": digest(sample.to_dict()),
                    "modal_ir_sha256": digest(sample.modal_ir.to_dict()), "parser_trace": sample.parser_trace,
                    "construction": "legal_384_package._rows/current_v2.build_sample",
                    "features_origin": "source_parser_not_canonical_targets"}
                stages = {}
                stages["raw384"] = _stage("raw384", row["embedding"], identity=row["id"], source_sha=source_sha,
                    upstream=None, evidence={"kind": "native_gte_source_embedding", "native": native})
                stages["core384"] = _stage("core384", core, identity=row["id"], source_sha=source_sha,
                    upstream=digest(row["embedding"]), evidence={"kind": "source_parser_sparse_core_projection",
                    "native": native, "parser": parser, "package": package_ref})
                stages["trained384"] = _stage("trained384", learned, identity=row["id"], source_sha=source_sha,
                    upstream=digest(core), evidence={"kind": "saved_learned_residual_projection",
                    "native": native, "parser": parser, "package": package_ref})
                result.append({"id": row["id"], "source_sha256": source_sha, "stages": stages})
        _require(digest(runtime.model.state.to_dict()) == before, "core state changed during conditioning")
        _require(_sha(Path(package_path).read_bytes()) == package_sha256, "package changed during conditioning")
    _require(producer_pins() == pins, "conditioning dependencies changed during production")
    output = {"schema": SCHEMA, "stages": list(STAGES), "package": package_ref,
        "producer_pins": pins, "producer_pin_scope": "listed sources plus strict saved package bindings",
        "rows": result, "encoder_inference_executed": False, "cached_native_embeddings_consumed": True,
        "core_state_unchanged": True, "training_executed": False, **_FALSE}
    output["bundle_sha256"] = digest(output)
    return output


def historical_features(rows, *, backend="historical_blank_en"):
    """Return the actual frozen linguistic 8D feature profile, separately named.

    This intentionally does not load the old 398MB sparse reconstruction state:
    that state is not used by the historical source feature hash producer. No
    encode/decode reconstruction, formula generation or sample memory is used.
    """
    from ....optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import linguistic
    checked, pins = _sources(rows), producer_pins()
    profile = linguistic.LinguisticAutoencoder(backend=backend, compute_device="cpu")
    identity = json.loads(_wire(profile._linguistic_identity))
    profile_pin = _sha(Path(linguistic.__file__).read_bytes())
    result = []
    for row in checked:
        source_sha = _sha(row["source_text"].encode("utf-8"))
        sample = profile.build_sample(title="source-feature-probe", section=source_sha[:16], text=row["source_text"])
        _require(sample.parser_trace["embedding_origin"] == "deterministic_linguistic_feature_hash",
                 "historical source profile origin differs")
        evidence = {"kind": "deterministic_linguistic_feature_hash", "profile_id": linguistic.PROFILE_ID,
            "linguistic_identity": identity, "linguistic_identity_sha256": profile._linguistic_identity_sha256,
            "source_revision": identity["source_revision"], "profile_source_sha256": profile_pin,
            "learned_reconstruction_checkpoint_used": False, "pretrained_semantic_encoder_used": False,
            "numeric_rounding": "historical profile rounds normalized feature sums to six decimals"}
        stage = _stage(HISTORICAL_STAGE, list(sample.embedding_vector), identity=row["id"],
                       source_sha=source_sha, upstream=None, evidence=evidence)
        result.append({"id": row["id"], "source_sha256": source_sha, "stages": {HISTORICAL_STAGE: stage}})
    _require(producer_pins() == pins and _sha(Path(linguistic.__file__).read_bytes()) == profile_pin,
             "historical feature producer changed during production")
    output = {"schema": SCHEMA, "stages": [HISTORICAL_STAGE], "package": None,
        "producer_pins": {**pins, str(Path(linguistic.__file__).resolve()): profile_pin},
        "producer_pin_scope": "listed sources plus verified frozen linguistic and numerical snapshots",
        "rows": result, "encoder_inference_executed": False, "cached_native_embeddings_consumed": False,
        "core_state_unchanged": True, "training_executed": False, **_FALSE}
    output["bundle_sha256"] = digest(output)
    return output


def stage_rows(bundle, *, stage, sources):
    """Validate exact source and stage bindings before consuming cached vectors.

    Hash checks detect corruption and stage confusion; they are not an attested
    proof of computation. Persist the complete producer bundle with model inputs.
    """
    checked = _sources(sources)
    _require(stage in (*STAGES, HISTORICAL_STAGE), "unknown conditioning stage")
    _closed(bundle, {"schema", "stages", "package", "producer_pins", "producer_pin_scope", "rows",
        "encoder_inference_executed", "cached_native_embeddings_consumed", "core_state_unchanged",
        "training_executed", "bundle_sha256", *_FALSE}, "conditioning bundle")
    _require(bundle["schema"] == SCHEMA and stage in bundle["stages"], "conditioning stage/schema differs")
    _require(bundle["stages"] in (list(STAGES), [HISTORICAL_STAGE]), "complete authentic stage set required")
    _require(all(bundle[key] is False for key in _FALSE) and bundle["training_executed"] is False,
             "unsupported target, memory, training or qualification claim")
    _require(bundle["encoder_inference_executed"] is False and bundle["core_state_unchanged"] is True and
             bundle["cached_native_embeddings_consumed"] is (stage != HISTORICAL_STAGE),
             "conditioning execution origin differs")
    wanted_pins = producer_pins()
    if stage == HISTORICAL_STAGE:
        from ....optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import linguistic
        wanted_pins[str(Path(linguistic.__file__).resolve())] = _sha(Path(linguistic.__file__).read_bytes())
        _require(bundle["package"] is None, "historical feature profile must not claim a learned core")
    else:
        _closed(bundle["package"], {"path", "sha256", "core_binding", "core_state_sha256",
            "formula_checkpoint_sha256", "projection_optimizer_steps"}, "saved package binding")
        _require(bundle["package"]["core_binding"]["dimension"] == 384 and
                 type(bundle["package"]["projection_optimizer_steps"]) is int and
                 bundle["package"]["projection_optimizer_steps"] > 0, "trained384 package binding required")
    _require(bundle["producer_pins"] == wanted_pins, "conditioning producer pins differ")
    _require(bundle["bundle_sha256"] == digest({k: v for k, v in bundle.items() if k != "bundle_sha256"}),
             "conditioning bundle hash differs")
    _require(type(bundle["rows"]) is list and len(bundle["rows"]) == len(checked), "complete source coverage required")
    result = []
    for source, row in zip(checked, bundle["rows"]):
        _closed(row, {"id", "source_sha256", "stages"}, "conditioning row")
        source_sha = _sha(source["source_text"].encode("utf-8"))
        _require(row["id"] == source["id"] and row["source_sha256"] == source_sha,
                 "conditioning source identity differs")
        _closed(row["stages"], bundle["stages"], "conditioning stage set")
        for name, entry in row["stages"].items():
            _closed(entry, {"vector", "receipt"}, "conditioning vector")
            receipt = entry["receipt"]
            _closed(receipt, {"schema", "id", "source_sha256", "stage", "dimension", "vector_sha256",
                "upstream_vector_sha256", "evidence", "receipt_sha256", *_FALSE}, "stage receipt")
            dimension = 8 if name == HISTORICAL_STAGE else 384
            _vector(entry["vector"], dimension)
            _require(receipt["schema"] == RECEIPT_SCHEMA and receipt["id"] == source["id"] and
                receipt["source_sha256"] == source_sha and receipt["stage"] == name and
                type(receipt["dimension"]) is int and receipt["dimension"] == dimension,
                "conditioning receipt stage, dimension or source differs")
            _require(all(receipt[key] is False for key in _FALSE), "unsupported stage qualification claim")
            _require(receipt["vector_sha256"] == digest(entry["vector"]) and
                receipt["receipt_sha256"] == digest({k: v for k, v in receipt.items() if k != "receipt_sha256"}),
                "conditioning vector or receipt hash differs")
            upstream = {"core384": "raw384", "trained384": "core384"}.get(name)
            wanted = digest(row["stages"][upstream]["vector"]) if upstream else None
            _require(receipt["upstream_vector_sha256"] == wanted, "conditioning stage chain differs")
            evidence = receipt["evidence"]
            if name == HISTORICAL_STAGE:
                _closed(evidence, {"kind", "profile_id", "linguistic_identity", "linguistic_identity_sha256",
                    "source_revision", "profile_source_sha256", "learned_reconstruction_checkpoint_used",
                    "pretrained_semantic_encoder_used", "numeric_rounding"}, "historical feature evidence")
                _require(evidence["kind"] == "deterministic_linguistic_feature_hash" and
                    evidence["profile_id"] == "legacy-linguistic-features-8d/v1" and
                    evidence["learned_reconstruction_checkpoint_used"] is False and
                    evidence["pretrained_semantic_encoder_used"] is False and
                    digest(evidence["linguistic_identity"]) == evidence["linguistic_identity_sha256"],
                    "historical feature profile identity differs")
            else:
                keys = {"kind", "native"} | ({"parser", "package"} if name != "raw384" else set())
                _closed(evidence, keys, "native stage evidence")
                kinds = {"raw384": "native_gte_source_embedding", "core384": "source_parser_sparse_core_projection",
                         "trained384": "saved_learned_residual_projection"}
                _require(evidence["kind"] == kinds[name], "conditioning evidence stage differs")
                _closed(evidence["native"], {"receipt", "input_id", "source", "model", "execution",
                    "model_assets_sha256", "producer", "tokens_sha256", "token_count", "native_vector_bits_sha256",
                    "source_bytes_verified", "native_execution_record_present", "runtime_cryptographically_attested"},
                    "native encoder evidence")
                native = evidence["native"]
                _require(native["source_bytes_verified"] is True and native["native_execution_record_present"] is True
                    and native["runtime_cryptographically_attested"] is False and native["execution"]["kind"] == "native"
                    and native["model"] == {"model_id": "thenlper/gte-small",
                        "revision": "17e1f347d17fe144873b1201da91788898c639cd", "dimension": 384},
                    "native encoder evidence profile differs")
                if name != "raw384":
                    _closed(evidence["parser"], {"source_sha256", "sample_sha256", "modal_ir_sha256",
                        "parser_trace", "construction", "features_origin"}, "source parser evidence")
                    _require(evidence["package"] == bundle["package"] and
                        evidence["parser"]["source_sha256"] == source_sha and
                        evidence["parser"]["features_origin"] == "source_parser_not_canonical_targets" and
                        native == row["stages"]["raw384"]["receipt"]["evidence"]["native"],
                        "parser, package or upstream native source binding differs")
        result.append({"id": source["id"], "source_sha256": source_sha,
                       "stage": stage, "vector": list(row["stages"][stage]["vector"]),
                       "receipt_sha256": row["stages"][stage]["receipt"]["receipt_sha256"]})
    return result


__all__ = ["embedding_rows", "vectorize", "historical_features", "stage_rows", "producer_pins",
           "SCHEMA", "STAGES", "HISTORICAL_STAGE", "digest"]
